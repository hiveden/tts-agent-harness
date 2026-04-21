# TTS Agent Harness — 并发架构优化方案

> **状态（2026-04-21）**：Phase 1 ✅ 已完成 / Phase 2 🟡 完成实用部分、剩余子项经 code review **明确否决** / Phase 3 ❌ 未开工（业务取舍，单用户单 worker 够用）。

### 本轮 code review 决策（2026-04-21）

原设计里"Export 迁 Prefect flow"、"download 真流式生成器"、"`_running_tasks` 迁 DB"这些子项，在实际代码 review 时被**明确否决**：

- **Export 持久化（DB 表）**：单进程重启丢内存状态 → 前端提示"服务可能已重启，请重新点击导出"就够；跨进程要 advisory lock / heartbeat，DB 表是半吊子；否决。
- **真流式 zip 下载**：当前 `BytesIO + StreamingResponse` 本身就按 chunk 读，非"一次性加载"。zip 在内存构建是 zip 格式特性（central directory 在末尾），真流式需要 `stream-zip` 或临时文件，架构重构而非技术债。
- **`storage.download_stream` 基础设施**：曾经写了这个函数，code review 判定为无 caller 的投机性代码，删除。
- **Phase 3 多 worker**：单用户/小团队根本不需要，维持单 uvicorn worker 稳定跑。

结论：并发优化 Phase 1 的阻塞消除 + 行锁 + 连接池调整已覆盖当前所有痛点。Phase 2/3 里未完成部分是**业务取舍**，不是遗留债。

## 0. 业务痛点

### 典型工作流

用户在 Web UI 上的日常操作：上传脚本 → 运行 pipeline（P1-P6）→ 逐 chunk 试听 → 不满意的编辑重试 → 全部满意后导出 zip。一个 episode 通常 20-50 个 chunk，pipeline 运行 2-5 分钟，导出 10-30 秒。

### 痛点场景

**场景 1：导出卡死全站**（Phase 1 已消除）

用户 A 点击导出，export 端点原本同步执行 ffmpeg 拼接（每个 shot 一次 `subprocess.run`，最长 30s）。此期间：

- 用户 A 自己的页面无法刷新（API 不响应）
- SSE 心跳中断，前端丢失 pipeline 实时状态
- 如果有用户 B 在线上同时操作，所有请求排队——试听、编辑、查看进度全部卡住

实测：导出一个 6 shot 的 episode，服务不可用约 15 秒。Phase 1 切到 `asyncio.create_subprocess_exec` 后已消除。

**场景 2：批量导出失败**（Phase 1 已缓解，Phase 2 半解决）

用户需要导出 3 个 episode 的产物交给下游 Remotion 项目。点第一个导出后，立刻点第二个、第三个：

- 第一个正在 ffmpeg 拼接，事件循环阻塞
- 后续请求超时或连接被拒
- 前端只显示"导出失败"，无具体原因

当前行为：export 已 fire-and-forget 化（`asyncio.Task` + `_export_tasks` dict），连续提交不再互相阻塞；但仍未通过 Prefect 持久化，多 worker 或进程重启会丢失状态。

**场景 3：多人同时运行 pipeline**（Phase 1 已修复）

线上环境两人同时对同一 episode 点 Run：

- 两个请求都读到 `status=ready`，都通过检查
- 两个 pipeline 同时跑，重复调用 Fish TTS API（浪费配额）
- 最终状态不确定——后完成的覆盖先完成的结果

Phase 1 通过 `with_for_update(nowait=True)` 行级锁已消除该竞态。

**场景 4：单人批量操作**（部分缓解）

用户上传了 3-5 个 episode 的脚本，想批量跑 pipeline 然后逐个导出。Phase 1 后：

- 切 episode、试听、编辑均不再被 export 阻塞
- 但 P2v 阶段同时大量请求 Groq/WhisperX 仍会互相争抢（受后端服务自身限流，不是本文范围）

**场景 5：高峰期连锁反应**（Phase 3 才能彻底消除）

多人同时操作线上系统（编辑、试听、运行、导出混合），当前单 worker 下若长任务再次阻塞事件循环，仍会出现 SSE 断连风暴。Phase 3 多 worker 才能真正水平隔离。

### 痛点根因映射

| 痛点 | 直接原因 | 根因 | 当前状态 |
|------|---------|------|---------|
| 导出卡全站 | `subprocess.run` 阻塞事件循环 | async 端点中混入同步调用 | ✅ Phase 1 修复（异步 subprocess） |
| 批量导出失败 | 导出是同步请求，串行排队 | 重活没有交给任务队列 | 🟡 部分解决（asyncio.Task，未 Prefect 化） |
| 导出期间无法操作 | 事件循环被阻塞 | 同上 | ✅ Phase 1 修复 |
| Pipeline 重复运行 | check-then-act 非原子 | 缺少 DB 级并发控制 | ✅ Phase 1 修复（行锁） |
| SSE 断连风暴 | 事件循环被阻塞无法发心跳 | 同步阻塞 | ✅ 主因消除；多 worker 场景需 Phase 3 |
| 连接池耗尽 | 默认配置偏小 | 未按生产负载调参 | ✅ Phase 1 修复（pool 10/20） |

---

## 1. 现状分析（2026-04-21）

### 1.1 部署模型

当前生产（Fly.io 单 VM, 1 CPU / 2GB）和开发环境均为 **Uvicorn 单 worker 单进程**：

```
deploy/supervisord.conf:16
  command=python -m uvicorn server.api.main:app --host 0.0.0.0 --port 8100
```

所有并发依赖 asyncio 事件循环。Phase 3 目标是切 Gunicorn + 多 UvicornWorker，尚未执行。

### 1.2 已消除的阻塞点

| 位置 | 原问题 | 当前方案 |
|------|------|---------|
| export 中 ffmpeg | 同步 `subprocess.run` 最长 30s | `asyncio.create_subprocess_exec` @ `server/flows/export_logic.py` |

### 1.3 已正确异步化的部分

| 组件 | 方式 | 状态 |
|------|------|------|
| MinIO I/O | `asyncio.to_thread()` 包装同步 Minio client | ✅ |
| HTTP (Fish TTS / Groq) | `httpx.AsyncClient` | ✅ |
| DB | SQLAlchemy `AsyncSession`，pool 10/20 | ✅ |
| Pipeline 执行 | `asyncio.create_task`（dev）/ Prefect flow（prod） | ✅ |
| SSE 推送 | PostgreSQL LISTEN/NOTIFY → asyncio.Queue fan-out | ✅（单 worker；多 worker 代码已就绪） |
| Export 任务 | `asyncio.Task` + `_exports` 内存 dict | ✅ 单进程内完整；重启靠前端提示重试 |
| Export 下载 | `BytesIO + StreamingResponse`（按 chunk 读） | ✅ 现实内存占用可接受 |
| cleanup task（删 episode 后清 MinIO） | `asyncio.create_task` + `_cleanup_tasks` 强引用 | ✅ 防 GC |

### 1.4 当前接受的局限（业务取舍，不列入债）

| 场景 | 性质 | 处置 |
|------|------|------|
| 进程重启丢 in-flight export | 取舍 | 前端轮询收 `status: "none"` 时提示"服务可能已重启，请重新点击导出" |
| 多 worker 部署 | 未开工 | 单 worker 稳定跑；多并发场景出现再做 |
| 超大 zip 下载峰值内存 | 格式限制 | zip 需要 central directory 在末尾，真流式需重构；现实规模可接受 |

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

- asyncpg LISTEN/NOTIFY：https://magicstack.github.io/asyncpg/current/api/index.html

### 3.4 并发控制 — SQLAlchemy `with_for_update`

**选型：行级锁 + 原子更新**（已实装 @ `episodes.py:451`）

防止 episode 重复 run / 重复 export 的竞态条件。

```python
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

### 3.5 多 Worker 部署 — Gunicorn + UvicornWorker

**选型：Gunicorn 管理多个 Uvicorn worker 进程**（Phase 3，未实装）

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

### 3.6 文件下载 — StreamingResponse（Phase 2 未完成）

**目标方案：MinIO → API → 客户端真流式代理**

```python
async def stream_from_minio(key: str):
    async for chunk in storage.download_stream(key):
        yield chunk

return StreamingResponse(
    stream_from_minio(zip_key),
    media_type="application/zip",
    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}"},
)
```

**当前实装**：`episodes.py` 的 download 端点用 `BytesIO + StreamingResponse`。FastAPI 对 BytesIO 按 64KB chunk 读取，属分块流式。zip 的内存峰值来自"zip 整个在 BytesIO 里构建"这步 —— 是 zip 格式要求（central directory 在末尾），真流式需 `stream-zip` 库或临时文件。code review 判定当前规模可接受，不做重构。

- Starlette StreamingResponse：https://www.starlette.io/responses/#streamingresponse

### 3.7 DB 连接池 — SQLAlchemy 调参（已实装）

```python
create_async_engine(
    database_url,
    pool_size=10,        # 常驻连接数
    max_overflow=20,     # 突发额外连接
    pool_pre_ping=True,  # 连接健康检查
)
```

位置：`server/core/db.py:56-57`。

- SQLAlchemy 连接池配置：https://docs.sqlalchemy.org/en/20/core/pooling.html

---

## 4. 实施路线

### Phase 1：消除阻塞 + 并发安全 — ✅ 已完成

**驱动场景**：单人批量操作（上传多 episode → 批量 run → 批量导出），导出阻塞全站。

| 改动 | 文件 | 状态 |
|------|------|------|
| ffmpeg → `asyncio.create_subprocess_exec` | `server/flows/export_logic.py` | ✅ |
| episode run 原子化 `with_for_update` | `server/api/routes/episodes.py:451` | ✅ |
| DB 连接池扩容（pool 10 / overflow 20） | `server/core/db.py:56-57` | ✅ |
| MinIO I/O 统一 `asyncio.to_thread()` | `server/core/storage.py` | ✅ |
| SSE per-worker 隔离代码就绪 | `server/api/sse.py` | ✅ |

**效果**：事件循环不再被阻塞，单 worker 可交替处理多个导出 + 试听 + SSE。防止 pipeline 重复触发。生产已验证。

### Phase 2：Export 异步化 — ✅ 完成（实用部分）

**驱动场景**：批量导出 3-5 个 episode，每个 10-30s，用户不愿干等。

| 改动 | 文件 | 状态 |
|------|------|------|
| export 抽成异步任务（非阻塞 API） | `episodes.py::_run_export` | ✅ `asyncio.Task` + `_exports` 内存 dict |
| API 端改为 POST 触发 + GET 查询 + GET 下载 | `episodes.py` | ✅ |
| 前端：提交任务 → 轮询 → 下载 | `EpisodeHeader.tsx` | ✅（AbortController + AbortError 守卫） |
| 前端：进程重启场景友好提示 | `EpisodeHeader.tsx` | ✅ 轮询收 `status: "none"` 抛 "服务可能已重启，请重新点击导出" |
| export 产物存 MinIO | `storage.py` | ✅ |

#### 原设计里本 Phase 未完成、经 code review 明确否决的子项

| 子项 | 否决理由 |
|------|---------|
| export 迁 Prefect flow + `export_jobs` DB 表 | 单进程用内存 dict + 前端提示即可；跨进程需 advisory lock/heartbeat，DB 表是半吊子 |
| `storage.download_stream` 基础设施 | 无 caller，投机性代码 |
| 真流式 zip 生成器 | BytesIO + StreamingResponse 已分块流；zip 格式要求 central directory 在末尾，真流式是架构重构 |

### Phase 3：无状态 API + 多 Worker — ❌ 未开工（业务取舍）

单用户/小团队单 worker 稳定跑，Phase 1 已消除痛点。多人并发出现前不开工。

| 改动 | 文件 | 状态 |
|------|------|------|
| `_running_tasks` → DB 字段 + Prefect 状态查询 | `episodes.py` | ❌ 进程级 dict（单 worker 够用） |
| `_subscribers` → per-worker 独立 LISTEN 连接 | `sse.py` | ✅ 代码已就绪 |
| supervisord 启动命令改 Gunicorn + UvicornWorker | `deploy/supervisord.conf` | ❌ 仍为单 Uvicorn worker |
| `_run_dev` 与 Prefect flow 统一（消除双写） | `episodes.py` + `flows/run_episode.py` | ❌ 语义已分叉（`failed` vs `needs_review`、P6v 有无、逐 stage vs 逐 chunk），统一前需产品决策 |

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
