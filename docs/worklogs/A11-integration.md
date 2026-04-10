# A11 Integration — Worklog

**Agent**: A11
**Wave**: W5
**Branch**: agent/A11-integration
**Status**: completed

## 产物

| 文件 | 说明 |
|------|------|
| `server/tests/e2e/__init__.py` | e2e 测试包 |
| `server/tests/e2e/conftest.py` | 共享 fixtures: api_client (ASGI transport), db_session (真实 PG), storage (真实 MinIO), cleanup (自动清理 e2e- 前缀数据) |
| `server/tests/e2e/test_episode_crud.py` | 7 个 case: 创建/获取详情/列表/删除/重复ID/删除不存在/带config创建 |
| `server/tests/e2e/test_full_pipeline.py` | 2 个 case: happy path (P1->P2->P3->P5->P6 全链路) + P2 失败场景 |
| `server/tests/e2e/test_chunk_operations.py` | 5 个 case: P1 真实切分/编辑 chunk/retry 生成新 take/编辑不存在 chunk/API retry |
| `server/tests/e2e/test_sse.py` | 3 个 case: 事件持久化/SSE endpoint content-type/多事件链 |
| `server/pyproject.toml` | 追加 `e2e` marker |

## 测试清单 (17 cases)

### test_episode_crud.py (7)
1. `test_create_episode` - POST 创建 episode, 验证 DB + MinIO + event
2. `test_get_episode_detail` - GET 详情, 验证 chunks 嵌套结构
3. `test_list_episodes` - GET 列表, 验证新建的 episode 在列表中
4. `test_delete_episode` - DELETE, 验证 DB 清理 + 后续 GET 返回 404
5. `test_duplicate_episode_id` - 重复 ID 创建返回 422
6. `test_delete_nonexistent` - 删除不存在的 episode 返回 404
7. `test_create_with_config` - 带 config override 创建

### test_full_pipeline.py (2)
8. `test_full_pipeline_happy_path` - P1->P2->P3->P5->P6 全链路, 验证 MinIO final WAV+SRT, episode status empty->ready->done, events 完整链
9. `test_pipeline_p2_failure` - P2 失败时 stage_failed 事件正确写入

### test_chunk_operations.py (5)
10. `test_p1_real_chunking` - 真实 P1 切分, 验证 chunks 在 DB 中的字段正确性
11. `test_edit_chunk_text` - API 编辑 chunk text_normalized, 验证 DB 更新 + char_count 重算
12. `test_retry_chunk_generates_new_take` - 同一 chunk 跑两次 P2, 验证两个 take + selected_take_id 更新
13. `test_edit_nonexistent_chunk` - 编辑不存在的 chunk 返回 404
14. `test_retry_via_api` - POST retry API 返回 flow_run_id

### test_sse.py (3)
15. `test_events_persisted_after_episode_create` - 创建 episode 后 events 表有 episode_created 记录
16. `test_sse_endpoint_content_type` - SSE endpoint 返回 text/event-stream content-type
17. `test_multiple_events_from_operations` - 多操作产生事件链 (episode_created + episode_status_changed)

## 关键决策

1. **不用 testcontainers, 直连 dev stack** — 按任务要求直接使用 A1 搭建的已运行容器 (localhost:55432 PG, localhost:59000 MinIO), 省去容器启动时间
2. **每个测试创建独立 engine** — 避免 pytest-asyncio 的 event loop 切换导致 engine 绑定到错误的 loop
3. **e2e- 前缀隔离** — 所有测试数据 ID 以 `e2e-{uuid}` 开头, autouse cleanup fixture 在每个测试前后清理
4. **Pipeline 测试直接调用 `run_p{N}_*` 纯函数** — 不走 Prefect task decorator, 避免需要 Prefect server 连接
5. **SSE 流测试用 asyncio.wait_for 超时** — ASGI transport 下 SSE 流会阻塞, 3 秒超时验证 headers 后退出

## Mock 策略

- **FakeFishClient**: `synthesize()` 返回 `make_silent_wav(1.0)` (真实的 16kHz 16bit PCM WAV)
- **FakeWhisperXClient**: httpx.MockTransport 返回 `{"transcript": [{"word": "test", ...}], "duration_s": 1.0}`
- **P1, P5, P6**: 使用真实逻辑 (P1 纯文本切分, P5 字幕算法, P6 真 ffmpeg)
- **Prefect client**: API route 测试中 mock `create_flow_run_from_deployment`, 返回假 flow_run_id

## 放弃的方案

- **testcontainers** — 任务明确要求不用
- **httpx 直接起 uvicorn** — ASGI transport 更轻量, 且 API 测试不需要真正的 HTTP 连接
- **单个 engine 全局复用** — pytest-asyncio 每个测试函数新建 event loop, 全局 engine 会绑定到第一个 loop 导致后续测试失败

## 卡点

无阻塞性卡点。

## Bug / Limitation

1. **SSE 实时推送在 ASGI transport 下不可测** — asyncpg LISTEN 需要真实的 TCP 连接, ASGI transport 内部不启动 lifespan 的 SSE listener (或 start_listener 因无法连接 PG 而静默跳过)。已用 polling fallback (直查 events 表) 作为替代测试。**这不是代码 bug, 是测试模式的固有限制**。完整 SSE 推送测试需要 pytest + 真实 uvicorn 进程。

2. **P6 的 DI 模式不统一** — P6 (p6_concat.py) 没有 `configure_p6_dependencies()` 函数, 而是在 task wrapper 里直接从环境变量创建 engine/storage。`run_p6_concat()` 纯函数接受显式 session + storage 参数, 所以 e2e 测试可以直接传入, 但与 P2/P3/P5 的模块级 DI 模式不一致。**建议 A8-Flow 或后续统一**。

3. **P1 的 DomainError 重复定义** — `server/flows/tasks/p1_chunk.py` 自定义了一个 `DomainError` 类, 与 `server/core/domain.py` 的 `DomainError` 不是同一个类。在 e2e 测试中不影响行为 (P1 内部 raise 的 DomainError 在 P1 内部被处理), 但如果需要在 flow 层统一捕获 DomainError, 会出问题。**建议 P1 改为 import `server.core.domain.DomainError`**。

## 给下游的提示

- e2e 测试依赖 dev stack 在线, 运行前确认 `docker ps | grep tts-harness` 有 3 个容器 (postgres, minio, prefect-server)
- 运行方式: `SKIP_DOCKER_TESTS=1 pytest server/tests/e2e/ -v` (SKIP_DOCKER_TESTS 跳过 testcontainers, 不影响 e2e)
- 全量回归: `SKIP_DOCKER_TESTS=1 pytest server/tests/ -v` → 189 passed, 7 skipped
- e2e 测试是 idempotent 的, 支持 pytest-randomly 随机顺序

## 测试

```
SKIP_DOCKER_TESTS=1 pytest server/tests/e2e/ -v
→ 17 passed in 4.62s

SKIP_DOCKER_TESTS=1 pytest server/tests/ -v
→ 189 passed, 7 skipped in 5.65s
```
