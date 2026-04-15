# TTS Agent Harness — 并发架构优化方案

## 1. 现状问题

### 1.1 部署模型

当前生产环境（Fly.io）和开发环境均为 **Uvicorn 单 worker 单进程**：

```
deploy/supervisord.conf:
  command=python -m uvicorn server.api.main:app --host 0.0.0.0 --port 8100
```

所有并发依赖 asyncio 事件循环。单个同步阻塞调用会卡死整个服务。

### 1.2 已识别的阻塞点

| 位置 | 问题 | 影响范围 |
|------|------|---------|
| `episodes.py:1434` export 中 `subprocess.run(ffmpeg)` | 同步阻塞最长 30s | 导出期间全部请求排队 |

### 1.3 已正确异步化的部分

| 组件 | 方式 | 状态 |
|------|------|------|
| MinIO I/O | `asyncio.to_thread()` 包装同步 Minio client | OK |
| HTTP (Fish TTS / Groq) | `httpx.AsyncClient` | OK |
| DB | SQLAlchemy `AsyncSession` | OK |
| Pipeline 执行 | `asyncio.create_task`（dev）/ Prefect flow（prod） | OK |
| SSE 推送 | PostgreSQL LISTEN/NOTIFY → asyncio.Queue fan-out | OK（单 worker） |

### 1.4 并发风险

| 场景 | 风险等级 | 原因 |
|------|---------|------|
| 导出阻塞 | 高 | `subprocess.run` 卡事件循环 |
| Episode 重复 run | 中 | check-then-act 竞态（两人同时点 Run） |
| 多 worker SSE | 高 | `_subscribers` 全局 dict，跨进程不共享 |
| 多 worker 任务管理 | 高 | `_running_tasks` 全局 dict，跨进程不共享 |
| DB 连接池不足 | 中 | 默认 pool_size=5, max_overflow=10 |

---

## 2. 架构目标

```
   Clients (browser)
        │
   ┌────▼─────────────────────────────┐
   │       Stateless API Layer        │
   │   Gunicorn + N UvicornWorkers    │
   │   - 零同步阻塞                    │
   │   - 无进程级全局状态               │
   │   - 所有端点 < 200ms 返回         │
   └──┬──────────┬──────────┬─────────┘
      │          │          │
  ┌───▼───┐ ┌───▼────┐ ┌───▼───┐
  │  DB   │ │Prefect │ │ MinIO │
  │(PG)   │ │Server  │ │       │
  └───────┘ └───┬────┘ └───────┘
                │
         ┌──────▼──────┐
         │  Prefect    │
         │  Worker(s)  │
         │  重活在这里   │
         └─────────────┘
```

**核心原则**：

1. **API 零阻塞** — 所有 I/O 异步，subprocess 异步，重活交 Worker
2. **API 无状态** — 无全局 dict，可多 worker 水平扩展
3. **长任务队列化** — export、pipeline 通过 Prefect 调度，API 只管触发和查询
4. **SSE 跨 worker** — 基于 PostgreSQL LISTEN/NOTIFY，每个 worker 独立监听

---

## 3. 技术选型

### 3.1 异步 subprocess — Python stdlib

**选型：`asyncio.create_subprocess_exec`**

替代 `subprocess.run`，非阻塞执行 ffmpeg。零额外依赖。

```python
proc = await asyncio.create_subprocess_exec(
    "ffmpeg", "-y", "-i", input_path, output_path,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
stdout, stderr = await proc.communicate()
```

- 文档：https://docs.python.org/3/library/asyncio-subprocess.html

### 3.2 任务队列 — Prefect 3（已有）

**选型：复用现有 Prefect 基础设施**

项目已依赖 Prefect，`make dev` 已启动 Prefect Server。不引入新的任务队列。

- export 任务注册为 Prefect flow
- API 通过 `prefect.client` 提交 flow run、查询状态
- Worker 独立进程执行，不占 API 事件循环

```python
# API 端提交
client = get_client()
flow_run = await client.create_flow_run_from_deployment(
    "export-episode/export-episode",
    parameters={"episode_id": episode_id},
)
return {"task_id": flow_run.id, "status": "submitted"}

# API 端查询
flow_run = await client.read_flow_run(flow_run_id)
state = flow_run.state_type  # PENDING / RUNNING / COMPLETED / FAILED
```

**备选方案（未选）：**

| 方案 | 不选原因 |
|------|---------|
| `arq` | 需要额外 Redis 依赖，增加基础设施复杂度 |
| `Celery` | 非 asyncio 原生，配置重 |
| `FastAPI BackgroundTasks` | 同进程执行、无持久化、无状态查询 |

- Prefect 3 文档：https://docs.prefect.io/v3
- arq（备参考）：https://github.com/python-arq/arq

### 3.3 SSE 跨 Worker — PostgreSQL LISTEN/NOTIFY

**选型：asyncpg 原生 LISTEN/NOTIFY**

项目已在使用 asyncpg LISTEN/NOTIFY（`server/api/sse.py`）。多 worker 下每个 worker 独立维护 LISTEN 连接即可，无需额外中间件。

```
Worker 1 ──LISTEN events──→ PostgreSQL ←──NOTIFY events── Prefect Worker / 任何进程
Worker 2 ──LISTEN events──→ PostgreSQL
```

改造点：
- `_subscribers` 从全局 dict 变为 per-worker 实例（随 worker 进程隔离自然实现）
- 每个 worker 启动时建立独立的 LISTEN 长连接

**备选方案（未选）：**

| 方案 | 不选原因 |
|------|---------|
| `broadcaster` 库 | 维护不活跃；底层也是 PG LISTEN/NOTIFY，多一层抽象无必要 |
| Redis Pub/Sub | 需要额外 Redis 依赖 |

- asyncpg LISTEN/NOTIFY：https://magicstack.github.io/asyncpg/current/api/index.html
- broadcaster（备参考）：https://github.com/encode/broadcaster

### 3.4 并发控制 — SQLAlchemy `with_for_update`

**选型：行级锁 + 原子更新**

防止 episode 重复 run / 重复 export 的竞态条件。

```python
# 原子化状态转换：只有 status=ready 的行才能被锁定并更新
stmt = (
    select(Episode)
    .where(Episode.id == episode_id, Episode.status == "ready")
    .with_for_update(nowait=True)
)
result = await session.execute(stmt)
episode = result.scalar_one_or_none()
if not episode:
    raise DomainError("invalid_state", "episode not available")
episode.status = "running"
await session.commit()
```

`nowait=True`：获取不到锁立即失败，不排队等待。

- SQLAlchemy with_for_update：https://docs.sqlalchemy.org/en/20/orm/queryguide/api.html#sqlalchemy.orm.Query.with_for_update
- SQLAlchemy AsyncSession：https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html

### 3.5 多 Worker 部署 — Gunicorn + UvicornWorker

**选型：Gunicorn 管理多个 Uvicorn worker 进程**

```bash
gunicorn server.api.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 4 \
  --bind 0.0.0.0:8100 \
  --timeout 120
```

Fly.io 单 VM 场景下最简方案。每个 worker 是独立进程 + 独立事件循环。

- Gunicorn 文档：https://docs.gunicorn.org/en/stable/
- Uvicorn 部署指南：https://www.uvicorn.org/deployment/#gunicorn

### 3.6 文件下载 — StreamingResponse

**选型：MinIO → API → 客户端流式代理**

export zip 存入 MinIO 后，下载时流式代理，不将整个文件加载到内存。

```python
async def stream_from_minio(key: str):
    # MinIO get_object 返回流式响应
    data = await storage.download_stream(key)
    for chunk in data:
        yield chunk

return StreamingResponse(
    stream_from_minio(zip_key),
    media_type="application/zip",
    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}"},
)
```

- Starlette StreamingResponse：https://www.starlette.io/responses/#streamingresponse
- FastAPI 自定义响应：https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse

### 3.7 DB 连接池 — SQLAlchemy 调参

```python
create_async_engine(
    database_url,
    pool_size=10,        # 常驻连接数（默认 5）
    max_overflow=20,     # 突发额外连接（默认 10）
    pool_pre_ping=True,  # 连接健康检查
)
```

- SQLAlchemy 连接池配置：https://docs.sqlalchemy.org/en/20/core/pooling.html

---

## 4. 实施路线

### Phase 1：单 Worker 不卡（改动小，收益大）

| 改动 | 文件 | 工作量 |
|------|------|-------|
| ffmpeg → `asyncio.create_subprocess_exec` | `episodes.py` | 10 行 |
| episode run 原子化 `with_for_update` | `episodes.py` | 20 行 |
| DB 连接池扩容 | `db.py` | 3 行 |

**效果**：单 worker 可正常服务 3-5 人并发，所有操作非阻塞。

### Phase 2：Export 异步化

| 改动 | 文件 | 工作量 |
|------|------|-------|
| export 逻辑抽成 Prefect flow | 新建 `flows/tasks/export.py` | ~100 行 |
| API 端改为 POST 触发 + GET 查询状态 + GET 下载 | `episodes.py` | ~50 行 |
| 前端改为轮询/SSE 等待 + 下载链接 | `EpisodeHeader.tsx` | ~30 行 |

**效果**：export 不再阻塞 API，支持多 episode 并发导出。

### Phase 3：去全局状态，多 Worker 就绪

| 改动 | 文件 | 工作量 |
|------|------|-------|
| `_running_tasks` → DB 字段 + Prefect 查询 | `episodes.py` | ~40 行 |
| `_subscribers` → per-worker LISTEN 连接 | `sse.py` | ~30 行 |
| supervisord 启动命令改 Gunicorn | `supervisord.conf` | 3 行 |

**效果**：API 完全无状态，可 `--workers 4` 水平扩展。

---

## 5. 参考文档索引

| 技术 | 文档链接 |
|------|---------|
| asyncio subprocess | https://docs.python.org/3/library/asyncio-subprocess.html |
| Prefect 3 | https://docs.prefect.io/v3 |
| arq（备参考） | https://github.com/python-arq/arq |
| FastAPI BackgroundTasks | https://fastapi.tiangolo.com/tutorial/background-tasks/ |
| asyncpg LISTEN/NOTIFY | https://magicstack.github.io/asyncpg/current/api/index.html |
| broadcaster（备参考） | https://github.com/encode/broadcaster |
| SQLAlchemy with_for_update | https://docs.sqlalchemy.org/en/20/orm/queryguide/api.html#sqlalchemy.orm.Query.with_for_update |
| SQLAlchemy AsyncSession | https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html |
| SQLAlchemy 连接池 | https://docs.sqlalchemy.org/en/20/core/pooling.html |
| Gunicorn | https://docs.gunicorn.org/en/stable/ |
| Uvicorn 部署 | https://www.uvicorn.org/deployment/#gunicorn |
| Starlette StreamingResponse | https://www.starlette.io/responses/#streamingresponse |
| FastAPI 自定义响应 | https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse |
