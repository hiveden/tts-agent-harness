# 系统异常处理架构设计

## 问题

当前异常处理是零散的、不一致的，导致：

1. Pydantic 验证失败 → 500 裸响应，前端白屏，用户无法定位原因
2. 后端 `except` 块日志写了但 StageRun.error 没写 → 前端看不到
3. 前端 SWR error 被忽略 → 请求失败时显示空白而非错误信息
4. 前端用 `alert()` 弹窗 → 阻塞 UI，体验差
5. dev mode 异常后 episode 标 failed 但不知道哪个 stage 在哪个 chunk 失败

## 设计原则

1. **异常不丢失** — 每个异常必须到达用户可见的位置（UI 或日志）
2. **分层处理** — 每层只处理自己能处理的，其余向上传递
3. **结构化错误** — 统一的错误格式，前后端一致
4. **不阻塞 UI** — 用 toast/banner 替代 alert()

## 三层架构

```
┌──────────────────────────────────────────┐
│ 前端 UI 层                                │
│ Toast 通知 + 内联错误状态 + Retry 按钮     │
├──────────────────────────────────────────┤
│ 后端 API 层                               │
│ 统一错误响应格式 + 全局异常捕获             │
├──────────────────────────────────────────┤
│ 后端 Task 层                              │
│ Stage 级错误记录 + Event 写入              │
└──────────────────────────────────────────┘
```

## 后端 API 层

### 统一错误响应格式

所有错误响应（4xx/5xx）统一为：

```json
{
  "error": "error_code",
  "detail": "Human-readable message",
  "context": {}
}
```

### 全局异常捕获

在 `errors.py` 中注册三个 handler，按优先级：

| 异常类型 | HTTP Status | 说明 |
|---|---|---|
| `DomainError` | 按 code 映射 | 业务错误（已有） |
| `ValidationError` (Pydantic) | 422 | 数据验证失败，包含字段和值 |
| `Exception` (兜底) | 500 | 未预期的异常，记录完整 traceback |

```python
# errors.py 新增

async def validation_error_handler(_request: Request, exc: ValidationError) -> JSONResponse:
    """Pydantic validation failures — e.g. DB has 'transcribed' but Literal doesn't."""
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "detail": str(exc),
            "context": {"errors": exc.errors()},
        },
    )

async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unexpected exceptions."""
    log.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal",
            "detail": f"{type(exc).__name__}: {exc}",
        },
    )
```

效果：Pydantic 的 `'transcribed' not in Literal` 返回 422 + 具体字段信息，而不是裸 500。

### dev mode 异常链路

```
Task 内部异常
  → _mark_stage(error=err_msg)        写 StageRun.error
  → _write_event(stage_failed)        写 Event 表
  → raise                             向上传递
  → _run_dev except                   写 episode.status=failed
  → 前端 SSE 收到 episode_status_changed → UI 更新
```

每个 except 块必须：
1. 写 StageRun.error（用 double-write 保证）
2. 写 Event（stage_failed + error payload）
3. 再 raise（让外层设 episode.status=failed）

## 后端 Task 层

### Stage 错误标准化

每个 task 的异常处理统一为：

```python
try:
    result = await do_work()
except Exception as exc:
    error_msg = format_error(exc)  # 统一格式化
    await write_stage_run(chunk_id, stage, "failed", error=error_msg)
    await write_event(episode_id, chunk_id, "stage_failed", {
        "stage": stage,
        "error": error_msg,
        "attempt": attempt,
    })
    raise
```

`format_error` 统一函数：

```python
def format_error(exc: Exception, max_length: int = 500) -> str:
    """Extract meaningful error message from exception chain."""
    msg = str(exc)
    if not msg.strip():
        # Dig into cause chain (httpx ConnectError etc.)
        cause = exc
        while cause and not str(cause).strip():
            cause = cause.__cause__ or cause.__context__
        msg = f"{type(cause).__name__}" if cause else "unknown error"
    result = f"{type(exc).__name__}: {msg}"
    return result[:max_length] + "..." if len(result) > max_length else result
```

## 前端 UI 层

### Toast 替代 alert()

使用 **sonner**（shadcn/ui 推荐的 toast 库）：

```bash
pnpm add sonner
```

```typescript
// layout.tsx
import { Toaster } from "sonner";
// <Toaster position="bottom-right" />

// 使用（任意组件内）
import { toast } from "sonner";
toast.error("P2 合成失败", { description: error.message });
toast.success("配置已保存");
```

不需要自建 Toast 组件。

### SWR 错误统一处理

所有 SWR hook 返回的 error 必须被消费：

| Hook | 当前 | 改为 |
|---|---|---|
| `useEpisodes()` | error 忽略 | 侧边栏显示 "加载失败" + Retry |
| `useEpisode(id)` | error 忽略 | 主区域显示错误信息 + Retry（已修） |
| `useEpisodeLogs(id)` | error 忽略 | LogViewer 显示 "日志加载失败" |

### API 调用错误统一处理

openapi-fetch 已经返回结构化 `error` 对象，不需要自建 ApiError。

page.tsx 的 `withRefresh` wrapper 用 sonner toast：

```typescript
import { toast } from "sonner";

const withRefresh = (fn) => async (...args) => {
  try {
    await fn(...args);
    await mutateDetail();
    await mutateList();
  } catch (e) {
    toast.error("操作失败", { description: (e as Error).message });
  }
};
```

全局替换 `alert(...)` → `toast.error(...)`。

### 内联错误状态

| 位置 | 错误时显示 |
|---|---|
| Episode 详情主区域 | 红色 "Failed to load" + error + Retry（已修） |
| Episode 侧边栏 | "加载失败" + Retry |
| Stage pill drawer | 红色 Error banner（已修） |
| ChunkEditor | 保存失败 toast |
| LogViewer | "日志不可用" |

## 错误流向总图

```
Task 异常
  ↓ format_error()
StageRun.error + Event.payload.error
  ↓ API 响应
{ "error": "code", "detail": "msg" }
  ↓ hooks.ts
throw ApiError
  ↓ page.tsx withRefresh / SWR error
Toast 通知 或 内联错误状态
  ↓
用户看到：错误类型 + 具体信息 + 可操作的下一步
```

## 实施优先级

| 优先级 | 任务 | 影响 |
|---|---|---|
| **P0** | 后端全局异常捕获（Pydantic ValidationError → 422） | 解决白屏问题 |
| **P0** | 前端 SWR error 消费（所有 hook） | 解决空白页 |
| **P1** | Toast 组件替代 alert() | 改善体验 |
| **P1** | format_error 统一函数 | 错误信息一致性 |
| **P2** | ApiError 结构化错误 | 前端可按 code 分类处理 |
| **P2** | dev mode 异常链路完善 | 确保每个失败都有 StageRun.error |
