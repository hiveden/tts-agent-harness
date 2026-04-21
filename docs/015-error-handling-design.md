# 异常处理 & Loading 状态架构设计

## 问题

前端 12 个异步操作中 5 个无错误处理（静默失败），所有操作无 loading 反馈，无防重复提交机制。api-client middleware 只拦截 401，5xx/4xx 无全局通知。

## 设计原则

1. **异常不丢失** — 每个异常必须到达用户可见的位置
2. **操作有反馈** — 每个异步操作必须有 loading → success/error 的完整生命周期
3. **分层处理** — UI 层主动处理，API 层兜底，Error Boundary 防白屏
4. **不过度设计** — 不引入新状态管理库，用 hook 解决

## 架构决策

### 两层错误拦截

```
UI 层（主力）                    API 层（兜底）
┌──────────────────┐           ┌─────────────────┐
│ useAction hook    │           │ api-client       │
│ - try/catch       │           │ onResponse:      │
│ - error → toast   │           │ - 5xx → toast    │
│ - loading state   │           │ - 401 → 提示key  │
│ - 防重复提交      │           │ （4xx 不 toast） │
└──────────────────┘           └─────────────────┘
```

- **UI 层**：所有命令式操作（create/run/delete 等）通过 `useAction` hook 统一管理
- **API 层**：middleware 只 toast 5xx（服务端异常）。4xx 是业务错误，由 UI 层处理，避免双重 toast
- **Error Boundary**：包裹根组件，防止未捕获渲染异常导致白屏

### 查询 vs 命令分离

| 类型 | 方案 | 错误展示 | Loading 展示 |
|------|------|---------|-------------|
| 查询（读数据） | SWR hooks | 内联错误 + Retry 按钮 | SWR isLoading |
| 命令（写操作） | useAction hook | toast.error | 按钮 disabled + 文字变化 |

不混用。SWR 管查询缓存和轮询，useAction 管一次性命令的执行状态。

## 技术选型

### useAction hook（自建）

统一管理命令式异步操作的 loading / error / 防重复。

```typescript
const [run, running] = useAction(async () => {
  await store.runEpisode("synthesize");
  await mutateDetail();
});
// run()    — 执行，自动 loading + error toast + 防重复
// running  — boolean，控制按钮 disabled
```

**为什么不用 tanstack-query mutation**：项目已用 SWR 做查询，命令式操作不需要缓存/重试/乐观更新，useAction ~20 行代码足够。

**为什么不用 useSWRMutation**：API 不如自建 hook 直观，不支持防重复提交。

**为什么不在 Zustand store 加 loading map**：loading 是 UI 关注点，不是业务状态，放 store 会让 store 膨胀。

### openapi-fetch middleware（增强现有）

在现有 `api-client.ts` middleware 的 `onResponse` 中增加 5xx 拦截。

**为什么只 toast 5xx 不 toast 4xx**：4xx 是业务错误（如 "episode not found"），UI 层 useAction 会 catch 并以更友好的前缀 toast（如 "创建失败: ..."）。middleware 再 toast 会双重通知。5xx 是意外错误，UI 层可能没预期到，需要兜底。

### React Error Boundary（标准方案）

防止未捕获的渲染异常导致白屏。显示 fallback UI + 重试按钮。

**为什么不用 react-error-boundary 库**：只需要基础功能，class component ~20 行，不值得加依赖。

### sonner（不变）

已在用，不换。

## 后端层（已实现，无变更）

### 统一错误响应格式

```json
{ "error": "error_code", "detail": "Human-readable message" }
```

### 全局异常捕获

| 异常类型 | HTTP Status |
|---|---|
| DomainError | 按 code 映射（400/404/409） |
| ValidationError (Pydantic) | 422 |
| Exception (兜底) | 500 |

### Task 层异常链路

每个 task 有各自的 `_emit_stage_failed()` 函数，best-effort 写 Event(stage_failed)，错误字符串在调用处内联拼接。

**per-chunk 合成链路**（`_synth_one_chunk`）：
```
P2/P2c/P2v 异常
  → log.exception
  → _set_chunk_status("needs_review")     chunk 标记 needs_review
  → _write_event("needs_review", reason)  写 Event
  → return {verdict: "needs_review"}      不 raise，不终止 episode
```

异常不会向上传播，episode 继续运行其余 chunk。最终 episode 状态取决于是否所有 chunk 都通过。

**独立 task 链路**（P1/P5/P6 等）：
```
Task 异常
  → _emit_stage_failed(error=str)   best-effort 写 Event
  → raise                           向上传递，由 API 层 catch 返回 500
```

## 附录：备选方案对比

### A. 全局错误拦截

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| openapi-fetch middleware | 已有基础设施，改动最小 | 只拦截 openapi-fetch 调用 | **选用** |
| 全局 fetch wrapper | 覆盖所有请求 | 侵入性大，影响 Next.js 内部 fetch | 排除 |
| window.onerror | 覆盖最广 | 信息粗糙，无法区分 API 错误 | 排除 |

直接 fetch 调用仅 4 处（cancel/download/preview/stage-context），逐个加 catch 即可，不值得做全局 wrapper。

### B. Loading 状态管理

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| 自定义 useAction hook | 轻量，统一 loading+error+防重复，~20 行 | 自己维护 | **选用** |
| tanstack-query mutation | 功能丰富（retry、乐观更新） | 新依赖，与 SWR 重叠 | 过度 |
| useSWRMutation | 无新依赖 | API 不直观，无防重复 | 不够用 |
| Zustand loading map | 集中管理 | store 膨胀，loading 不是业务状态 | 错误抽象层 |

### C. Error Boundary

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| 手写 class component | 零依赖，~20 行 | 需维护 | **选用** |
| react-error-boundary | 功能丰富 | 新依赖，只用基础功能 | 过度 |

### D. Toast 库

sonner 已在用，无替换需求。

## 落地状态（2026-04-21）

文档设计全部落地：
- `useAction` hook（~22 行）：`web/lib/useAction.ts`
- openapi-fetch middleware 拦截 5xx
- Error Boundary class component（~20 行）：`web/components/ErrorBoundary.tsx`
- sonner toast

查询类错误当前多以 toast 呈现或静默处理，未独立实现"内联错误 + Retry 按钮"——实践中按需触发 `mutate()` 重载即可，没必要专用组件。

### 本轮补丁（tech-debt cleanup 2026-04-21）

- **`ApiKeyDialog` 的 fetch 错误处理**：原本 `fetchStatus().then(...)` 无 `.catch`，网络失败用户完全不知道；补上 catch + `parseKeysStatus` runtime shape 校验。这里是少数**没走 openapi-fetch** 的地方（`/keys` 路径不在 OpenAPI schema 里），保留手写 fetch 但加了类型 guard。后续如果 schema 覆盖了 `/keys`，应替换为 openapi-fetch client。
- **`audio.play().catch(() => {})` 静默吞错**：改为 `console.warn`，至少给诊断留个落脚点（不 toast，避免用户被满屏打扰）。
- **长轮询 unmount 安全**：`EpisodeHeader` 导出轮询用 `AbortController` 一把收：unmount 时 abort → 所有 `await fetch({signal})` 抛 `AbortError` → catch 块识别 `AbortError` 静默 return。**不再额外加 `mountedRef`**（双重保护冗余）。`setTimeout` 包了一个 `sleep(ms, signal)` helper 让它也响应 abort。

### Export "服务重启" 边缘情况

Export 状态活在进程内存（`_exports` dict），跨重启丢。API 查询返回 `{"status": "none"}` 时有两种可能：从未导过 / 导过但重启了。前端在**轮询中**收到 `none` 视为后者，抛"服务可能已重启，请重新点击导出"。
