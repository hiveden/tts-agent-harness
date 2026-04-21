# Dev Mode 容错架构设计

## 问题

dev mode (`_run_dev`) 的 pipeline 执行存在三个结构性问题：

1. **单点故障阻断全局**：一个 chunk 的 P2 失败 → raise → 整个 episode 中断，后续 chunk 不执行
2. **状态不同步**：StageRun 标记为 failed，但 chunk.status 仍为 pending，前端无法识别失败
3. **无网络重试**：dev mode 不走 Prefect（没有 retries=3），网络超时直接报错

## 设计原则

1. **chunk 间故障隔离** — 单个 chunk 失败不影响其他 chunk
2. **状态一致** — chunk.status 和 StageRun.status 同步
3. **网络容错** — 外部 API 调用有重试
4. **可恢复** — 失败后可批量重试

## 架构

### 执行模型

```
_run_dev (synthesize mode):

  Stage 1: P2 (所有 chunk，故障隔离)
  ┌─────────────────────────────────────┐
  │ for chunk in target_chunks:         │
  │   try:                              │
  │     retry_async(P2, retries=3)      │
  │     chunk.status = synth_done       │
  │   except:                           │
  │     chunk.status = failed           │
  │     continue  ← 不阻断             │
  └─────────────────────────────────────┘

  Stage 2: P2c (只处理 synth_done 的 chunk)
  Stage 3: P2v (只处理 P2c 通过的 chunk)
  Stage 4: P5 (只处理 verified 的 chunk)
  Stage 5: P6 (拼接所有 verified 的 chunk)

  Episode status:
    所有 chunk verified → done
    有 failed chunk → failed
    有 pending chunk → failed（被阻断的也算失败）
```

### 每个 stage 的执行规则

```python
# 统一模式：每个 stage 都是 for + try/except + continue
for cid in target_ids:
    chunk = get_chunk(cid)

    # 前置条件检查：只处理状态匹配的 chunk
    if chunk.status not in STAGE_PRECONDITIONS[stage]:
        skip(cid, stage)
        continue

    try:
        result = await retry_async(run_stage, retries=3, backoff=[2, 4, 8])
        await mark_stage(cid, stage, "ok")
        await set_chunk_status(cid, next_status)
    except Exception as e:
        await mark_stage(cid, stage, "failed", error=format_error(e))
        await set_chunk_status(cid, "failed")
        continue  # 不阻断
```

### Stage 前置条件

| Stage | 只处理 | 产出状态 |
|-------|--------|----------|
| P2 | pending, failed | synth_done |
| P2c | synth_done | synth_done（通过）/ failed（不通过） |
| P2v | synth_done（P2c 通过后） | verified / failed |
| P5 | verified | verified |
| P6 | 全量（只拼 verified 的 chunk） | - |

### retry_async 工具函数

```python
async def retry_async(fn, *args, retries=3, backoff=(2, 4, 8), **kwargs):
    """重试包装器，指数退避。"""
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if attempt < retries:
                await asyncio.sleep(backoff[min(attempt - 1, len(backoff) - 1)])
    raise last_exc
```

### Episode 最终状态

```python
# P6 完成后决定 episode status
async with session:
    chunks = await chunk_repo.list_by_episode(episode_id)
    all_verified = all(c.status == "verified" for c in chunks)
    has_failed = any(c.status == "failed" for c in chunks)

    if all_verified:
        episode.status = "done"
    elif has_failed:
        episode.status = "failed"  # 前端显示"重试失败(N)"按钮
```

### "重试失败" 按钮

```typescript
// 前端 failedCount 同时看 chunk.status 和 StageRun
const failedCount = episode.chunks.filter(c =>
  c.status === "failed" ||
  c.stageRuns.some(sr => sr.status === "failed")
).length;
```

### retry_failed mode

```python
# mode="retry_failed" 重跑所有失败的 chunk
target = [c for c in chunks if c.status in ("failed", "needs_review")]
# 重置 status 为 pending，然后走正常流程
for c in target:
    c.status = "pending"
```

## 变更清单

| 文件 | 变更 |
|------|------|
| `server/api/routes/episodes.py` `_run_dev` | P2/P2c/P2v 循环用 try/except + continue，失败时设 chunk.status=failed |
| `server/api/routes/episodes.py` `_run_dev` | 加 retry_async 包装 P2 调用 |
| `server/api/routes/episodes.py` `_run_dev` | 每个 stage 跳过状态不匹配的 chunk |
| `server/api/routes/episodes.py` `_run_dev` | episode 最终状态根据 chunk 聚合 |
| `server/api/routes/episodes.py` `_retry_dev` | 同样的容错模式 |
| `web/app/page.tsx` | failedCount 同时看 chunk.status 和 StageRun |

## 落地状态（2026-04-21）

故障隔离模式（P2/P2c/P2v `try/except` + `continue`）与前端 `failedCount` 聚合均已实装。设计与实装的命名差异：

- **`retry_async` / `_retry` 实装位置**：重试逻辑以 **inline 闭包**形式定义在 `server/api/routes/episodes.py:595` `_run_dev` 内部：
  ```python
  async def _retry(fn, *args, retries=3, backoff=(2, 4, 8), **kwargs):
      ...
  ```
  功能上与设计目标一致（`retries=3`、指数退避 2/4/8s），只是未抽成顶层模块。Prefect 路径走 `@task(retries=N, retry_delay_seconds=...)`，由框架负责。
- **`_retry_dev` 命名**：实际代码中未见独立函数，重试路径复用 `_run_dev`，按 `mode="retry_failed"` 参数区分。
