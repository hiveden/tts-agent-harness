# A9 API — Worklog

**Agent**: A9
**Wave**: W4
**Branch**: agent/A9-api
**Status**: completed

## 产物

| 文件 | 说明 |
|------|------|
| `server/api/__init__.py` | API 包入口 |
| `server/api/main.py` | FastAPI app — lifespan (SSE LISTEN), CORS, auth, routers |
| `server/api/deps.py` | DI: get_session, get_storage, get_prefect_client |
| `server/api/auth.py` | shared token 鉴权 (dev mode + token mode) |
| `server/api/errors.py` | DomainError → HTTP status 映射 |
| `server/api/routes/__init__.py` | routes 包入口 |
| `server/api/routes/episodes.py` | 全部 episode/chunk routes (8 endpoints) |
| `server/api/routes/health.py` | GET /healthz |
| `server/api/sse.py` | SSE — asyncpg LISTEN + Queue fan-out + StreamingResponse |
| `server/tests/api/__init__.py` | 测试包入口 |
| `server/tests/api/test_routes.py` | 22 个 route 测试 (含 auth 4 case) |
| `server/tests/api/test_sse.py` | 7 个 SSE 测试 (fan-out/filter/cleanup/fetch) |
| `server/pyproject.toml` | 新增 python-multipart + httpx 依赖 |

## 关键决策

1. **ORM → Pydantic 避免 lazy load**: SQLAlchemy async session 下 `model_validate(orm_obj)` 会触发 relationship lazy load 导致 `MissingGreenlet`。解决方案是手动构建 dict 再实例化 Pydantic 模型，而非依赖 `from_attributes=True` 自动提取。这保证了 route handler 不需要 eager load 策略。

2. **SSE 不用 sse-starlette**: 按任务要求自己用 `StreamingResponse(media_type="text/event-stream")` 实现。asyncpg `add_listener` callback 推入 per-client `asyncio.Queue`，30s keepalive comment 防止连接超时。

3. **Auth 用异常而非 HTTPException**: `verify_token` 抛自定义 `_Unauthorized` 异常而非 FastAPI 的 `HTTPException`，与 `DomainError` 模式一致，统一由 exception handler 转换为 JSON response。

4. **DomainError 从 domain.py 导入**: 按 W3-gate 要求，`errors.py` 只从 `server.core.domain` 导入 `DomainError`。A5 的 `fish_client.py` 有本地副本，未修改（不在 A9 职责范围内），未来需统一。

5. **Prefect 触发用 deployment name**: `run-episode/run-episode`、`retry-chunk-stage/retry-chunk-stage`、`finalize-take/finalize-take`，与 ADR-002 §3.5 的 deployment 清单对齐。

## 放弃的方案

- **selectinload eager loading**: 考虑在 `list_by_episode` 时用 `selectinload(Chunk.takes, Chunk.stage_runs)` 避免 N+1。放弃原因：这需要修改 `repositories.py`（禁区），且 per-episode chunk 数量通常 < 50，N+1 不是瓶颈。用 dict 构建方式绕过了 lazy load 问题。

- **SSE 用 asyncio.Task 轮询**: 考虑在 lifespan 启一个 Task `while True: conn.wait_for_notify()`。改用 asyncpg 的 `add_listener` callback 模式更简洁，不需要管理 Task 生命周期。

## 给下游的提示

1. **PYTHONPATH**: 测试运行时 rootdir 是 `server/`，但 import path 是 `server.xxx`。pytest 通过 conftest.py + rootdir 自动处理。手动运行 `python -c "from server.api.main import app"` 需要 `sys.path.insert(0, '<worktree-root>')`。

2. **ChunkStatus 扩展**: W3-gate 提到 A6 引入了 `p5_done` 但未扩展 `ChunkStatus` Literal。当前 route 序列化时如果 chunk.status 不在 Literal 范围内会报 validation error。A8 需要决定是否扩展 Literal。

3. **POST /episodes multipart 格式**: 前端需要用 `FormData` 发送 `id` + `title` + `script` (file)。不是 JSON body。

4. **SSE LISTEN 连接**: lifespan 启动时创建一个 raw asyncpg 连接做 LISTEN。如果 DB 不可用（如 SQLite 测试），SSE 功能降级为不推送（warning log）。

## 测试

```
SKIP_DOCKER_TESTS=1 pytest server/tests/ -v
→ 160 passed, 7 skipped in 1.54s
```

- API tests: 29 passed (22 routes + 7 SSE)
- W1-W3 regression: 131 passed (无 regression)
- 7 skipped: docker-dependent tests (storage + PG LISTEN)
