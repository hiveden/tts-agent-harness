# TTS Agent Harness — 用户故事 & 功能点 & 链路审计

> 初稿: 2026-04-10
> 最近重构: 2026-04-21（对照当前代码更新状态、术语、新增功能）
> 审计范围: 前端 page.tsx → hooks → api-client → FastAPI routes → Prefect flows → DB/MinIO 全链路

## Pipeline 术语说明

当前完整阶段（见 `server/core/domain.py:30`）：

```
P1 → P1c → P2 → P2c → P2v → P5 → P6 → P6v
```

历史文档中提到的 **P3**（WhisperX 独立转录）和 **P4** 已被合并到 **P2v**（含转写 + 2D scoring）。旧版 L0/L1 自动 repair 模块在 2026-04-13 已删除（commit `5e391a6`），失败统一走 `needs_review` 人工兜底。

---

## 产品设计决策

### D-01: TTS Config 管理

- **层级**：Episode 级（不下放到 chunk）
- **工作流**：探针校准 → 锁定 → 批量合成 → 后续只微调文本
- **理由**：config 调整是一次性的前置校准，不是贯穿全程的操作

### D-02: Run 按钮职责

- Run = "选定范围内的 chunk，跑完整 pipeline"
- Run **不管** "从哪个 stage 开始" — 那是 chunk 级 StageLogDrawer 的职责
- P1 切分与 Run 分离 — P1 是独立操作，Run 的前提是 chunks 已存在

### D-03: 按钮状态设计

| Episode Status | 按钮 | 行为 |
|---|---|---|
| `empty` | 切分 | 只跑 P1 |
| `ready` | 合成全部 / 合成选中(N) | 全部或勾选的 chunk 跑 P2→P2c→P2v→P5→P6 |
| `running` | 运行中... | 禁用（带取消） |
| `failed` | 重试失败(N) | 只跑 status=failed 的 chunk |
| `done` | 完成 ✓ | 菜单里"重新生成"（需确认，清空重来） |

### D-04: 两层重试分离

| 层 | UI 位置 | 粒度 |
|---|---|---|
| Episode 级 | Header 按钮 | 批量 chunk × 完整 pipeline |
| Stage 级 | Episode stage 进度条（`EpisodeStageBar`） | 批量重跑某 stage 的失败 chunk |
| Chunk 级 | StageLogDrawer retry 按钮 | 单 chunk × 指定 stage |

### D-05: 跳过已确认 chunk

- **规则**：有 `selectedTakeId` 的 chunk → Run 时跳过 P2，直接跑下游
- **不加新字段**：selectedTakeId 本身就是"已确认"的信号
- **全部重做**："重新生成" = 清空 takes → 回 pending → 全量跑

### D-06: Episode 级 Stage 进度条

```
P1 [✓ 20/20] ─── P2 [17/20 ⚠3] ─── P2v [17/17] ─── P5 [17/17] ─── P6 [pending]
                    └── 点击 → "重跑 3 个失败的 P2"
```

数据来源：从所有 chunks 的 stageRuns 聚合。已实装为 `EpisodeStageBar.tsx`，在 `page.tsx` 中集成。

---

## Part 1: 用户故事清单

图例：✅ 已实装 / ⚠️ 部分实装或待核查 / ❌ 未实装

### US-01: 创建新 Episode

用户上传 script.json，指定 episode ID，创建新 episode。

| 功能点 | 链路 | 状态 |
|---|---|---|
| F-01-1 打开新建对话框 | page.tsx → NewEpisodeDialog | ✅ |
| F-01-2 输入 ID + 选择文件 | NewEpisodeDialog 本地 state | ✅ |
| F-01-3 提交创建 | hooks.ts `createEpisode()` → `POST /episodes` multipart | ✅ |
| F-01-4 列表更新 | `mutateList()` → SWR refetch `GET /episodes` | ✅ |

### US-02: 选择 Episode 加载详情

| 功能点 | 链路 | 状态 |
|---|---|---|
| F-02-1 点击 sidebar | EpisodeSidebar → `setSelectedId()` | ✅ |
| F-02-2 加载详情 | `useEpisode(id)` → `GET /episodes/{id}` | ✅ |
| F-02-3 连接 SSE | `connectSSE(id)` → `/episodes/{id}/stream` | ✅ |

### US-03: 查看状态和进度

| 功能点 | 链路 | 状态 |
|---|---|---|
| F-03-1 状态 badge | EpisodeHeader STATUS_BADGE | ✅ |
| F-03-2 Episode 级 stage 进度条 | `EpisodeStageBar.tsx`，从 chunks.stageRuns 聚合 | ✅ |
| F-03-3 SSE 推送更新 | `pg_notify → sse.py → EventSource → mutate()` | ✅ |
| F-03-4 running 轮询 | SWR `refreshInterval: 2000` when `status=running` | ✅ |

### US-04: 切分脚本 (P1)

| 功能点 | 链路 | 状态 |
|---|---|---|
| F-04-1 切分按钮（status=empty 时） | EpisodeHeader → `onRun("chunk_only")` | ✅ |
| F-04-2 P1 执行 | `POST /episodes/{id}/run` → `p1_chunk()` | ✅ |
| F-04-3 chunks 预览 | ChunksTable 显示切分结果 | ✅ |

### US-05: 探针校准 TTS Config

用 chunk #1 当探针，调 TTS 参数后锁定 config。

| 功能点 | 链路 | 状态 |
|---|---|---|
| F-05-1 TtsConfigBar 显示 config | 读 `episode.config` | ✅ 已集成 `page.tsx` |
| F-05-2 修改 config | `PUT /episodes/{id}/config` | ✅ `episodes.py:341-380` |
| F-05-3 单 chunk P2 探针 | 选 chunk #1 → retry P2 | ✅ |
| F-05-4 P2 读 `episode.config` 构造 FishTTSParams | `p2_synth.py` | ⚠️ **待核查**：需确认 P2 确实读取 `episode.config` 而非仅 env var |
| F-05-5 听 → 不满意 → 再调 → 重跑 | 循环 F-05-2 → F-05-3 | ✅ |
| F-05-6 锁定后批量合成 | 确认 config 跑全部 P2 | ✅ |

### US-06: 批量合成 (Run)

| 功能点 | 链路 | 状态 |
|---|---|---|
| F-06-1 合成全部按钮 | EpisodeHeader (status=ready) | ✅ |
| F-06-2 跳过有 take 的 chunk | `run_episode.py` 第 25 行注释声明跳过 selectedTake | ⚠️ **待核查**：逻辑声明存在，需在 `_run_synthesize` 内验证实装 |
| F-06-3 P2→P2c→P2v→P5→P6 级联 | `run_episode_flow` | ✅ |
| F-06-4 多选 chunk 合成 | 批量选择 + 批量 Run | ✅ （见下方"批量操作"） |

### US-07: 编辑 Chunk TTS 源文本

| 功能点 | 链路 | 状态 |
|---|---|---|
| F-07-1 打开编辑 | ChunksTable `onEdit()` → ChunkEditor | ✅ |
| F-07-2 Stage 草稿 | `handleStage()` → `edits` state | ✅ |
| F-07-3 Apply All | `applyEdits()` → per-chunk `POST .../edit` + `POST .../retry?from_stage=p2&cascade=true` | ✅ |
| F-07-4 P2→下游级联 | `retry_chunk_stage_flow` | ✅ |

### US-08: 编辑 Chunk 字幕文本（P5 微调）

| 功能点 | 链路 | 状态 |
|---|---|---|
| F-08-1 编辑字幕 | ChunkEditor subtitleText field | ✅ |
| F-08-2 Retry P5 | `from_stage="p5"` | ✅ |
| F-08-3 手动调 cue 时间 | `SubtitleTimingEditor` | ✅ `PUT /chunks/{cid}/cues` |

### US-09: 播放 Chunk 音频

| 功能点 | 链路 | 状态 |
|---|---|---|
| F-09-1 Play 按钮 | ChunkRow toggle `playingChunkId` | ✅ |
| F-09-2 获取 URL | `getAudioUrl(audioUri)` → `/audio/{audioUri}` | ✅ |
| F-09-3 音频路由 | `GET /audio/{audio_key}` → MinIO download | ✅ |
| F-09-4 播放控制 | HTMLAudioElement play/pause | ✅ |

### US-10: 选择 Take

| 功能点 | 链路 | 状态 |
|---|---|---|
| F-10-1 显示 takes 列表 | TakeSelector | ✅ |
| F-10-2 Finalize take | `finalizeTake()` → `POST .../finalize-take?take_id=...` | ✅ |

### US-11: 查看 Stage 执行日志

| 功能点 | 链路 | 状态 |
|---|---|---|
| F-11-1 点击 stage pill | StagePipeline `onStageClick()` | ✅ |
| F-11-2 StageLogDrawer 获取日志 | `GET .../chunks/{cid}/log?stage=xxx` | ✅ |
| F-11-3 Retry 单 stage | `POST .../retry?from_stage=xxx` | ✅ |
| F-11-4 Retry + cascade | cascade=true 级联下游 | ✅ |

### US-12: 查看 Episode 事件日志

| 功能点 | 链路 | 状态 |
|---|---|---|
| F-12-1 LogViewer 显示 | `useEpisodeLogs` hook 5s 轮询 + `<LogViewer log={logLines} />` | ✅ |
| F-12-2 后端日志 | `GET /episodes/{id}/logs?tail=100` → `EventRepo.list_recent()` | ✅ |

### US-13/14/15: 删除 / 复制 / 归档 Episode

| 功能点 | 状态 |
|---|---|
| F-13 删除 episode | ✅ `DELETE /episodes/{id}` + cascade |
| F-14 复制 episode | ✅ `POST .../duplicate` |
| F-15 归档 episode | ✅ `POST .../archive`；`GET /episodes` 默认排除 archived |

### US-16: 重试失败的 Chunks

| 功能点 | 链路 | 状态 |
|---|---|---|
| F-16-1 "重试失败(N)" 按钮 | EpisodeHeader (status=failed) | ✅ |
| F-16-2 只跑 failed chunks | Run flow 过滤 `chunk.status=="failed"` | ✅ `retry_failed` 模式 |
| F-16-3 从失败的 stage 继续 | 读 stage_runs 定位失败 stage | ✅ |

### US-17: 重新生成（全部重做）

| 功能点 | 链路 | 状态 |
|---|---|---|
| F-17-1 "重新生成" 菜单项 | EpisodeHeader 菜单 (status=done) | ✅ |
| F-17-2 确认弹窗 | shadcn AlertDialog | ✅ |
| F-17-3 清空 + 重跑 | DELETE chunks/takes → P1 → 全链路 | ✅ |

### US-18: 实时事件推送 (SSE)

| 功能点 | 状态 |
|---|---|
| F-18-1 连接 EventSource | ✅ |
| F-18-2 监听 `stage_event` | ✅ |
| F-18-3 自动重连 | ✅ |

### US-19: API Token 认证

| 功能点 | 链路 | 状态 |
|---|---|---|
| F-19-1 Token 验证 | `auth.py::verify_token()` | ✅ |
| F-19-2 Dev mode（未设 token→放行） | ✅ |
| F-19-3 前端注入 Authorization | `api-client.ts` | ✅ |

### US-20: 批量操作（2026-04 新增）

| 功能点 | 链路 | 状态 |
|---|---|---|
| F-20-1 批量选择模式 | `batchMode` / `batchSelected` store | ✅ `page.tsx:222-296` |
| F-20-2 批量 Run | `batchRun()` 多 chunk 并发触发 | ✅ |
| F-20-3 批量 Export | `batchExport()` | ✅ |

### US-21: 连续播放模式（2026-04 新增）

| 功能点 | 链路 | 状态 |
|---|---|---|
| F-21-1 连续播放开关 | `ContinuousPlayBar` | ✅ |
| F-21-2 自动切下一 chunk | store `continuousPlay` | ✅ |
| F-21-3 速率调整 | store `playbackRate` | ✅ |

### US-22: 运行取消（2026-04 新增）

| 功能点 | 链路 | 状态 |
|---|---|---|
| F-22-1 取消按钮 | `execCancel` @ `page.tsx:120-129` | ✅ |
| F-22-2 Stage 级重试 | `execStageRetry` @ `page.tsx:184-195` | ✅ |

---

## Part 2: Break Point 清单（2026-04-21 更新）

原清单 BP-01 ~ BP-07 所列断点均已修复。当前剩余：

| # | 功能 | 断点 | 严重度 | 建议 |
|---|---|---|---|---|
| BP-A | TTS Config 联动 P2（F-05-4） | 需确认 `p2_synth.py` 确实从 `episode.config` 读参数；若仅用 env var，则 UI 修改 config 不生效 | 中 | 代码抽查 + 补 test |
| BP-B | 跳过已确认 chunk（F-06-2） | `run_episode.py` 注释声明跳过，需在 `_run_synthesize` 验证实际跳过逻辑 | 中 | 加 integration test |

---

## Part 3: 测试覆盖度（2026-04-21）

### 已覆盖

| US | 单元 | 集成 | e2e |
|---|---|---|---|
| US-01 创建 | — | test_routes::test_create_episode | test_episode_crud::test_create |
| US-02 加载详情 | — | test_routes::test_get_episode | test_episode_crud::test_get |
| US-06 Run pipeline | test_run_episode | test_routes::test_trigger_run | test_full_pipeline::happy_path |
| US-07 编辑文本 | — | test_routes::test_edit_chunk | test_chunk_operations::test_edit |
| US-07 重试 P2 | test_retry_chunk | test_routes::test_retry_chunk | test_chunk_operations::test_retry |
| US-10 Finalize take | — | test_routes::test_finalize_take | — |
| US-11 查看日志 | — | test_routes::test_get_chunk_log | — |
| US-13 删除 | — | test_routes::test_delete_episode | test_episode_crud::test_delete |
| US-14 复制 | — | test_routes::test_duplicate | — |
| US-15 归档 | — | test_routes::test_archive | — |
| US-18 SSE | test_sse | — | test_sse |
| US-19 认证 | — | test_routes::test_auth_* | — |

### 待补测

| US | 缺失维度 | 原因 |
|---|---|---|
| US-05 探针校准 | 集成测试 | config API 已实装但链路测试缺失 |
| US-06 跳过已确认（F-06-2） | 全部 | 逻辑未验证 |
| US-08 手动调 cue | e2e | `SubtitleTimingEditor` 新增，无 Playwright 覆盖 |
| US-09 播放音频 | e2e | 浏览器自动化 audio 较难测 |
| US-12 事件日志 | 前端 | `useEpisodeLogs` 已实装但无断言 |
| US-20 批量操作 | 全部 | 新功能，无测试 |
| US-21 连续播放 | 全部 | 新功能，无测试 |
| US-22 取消运行 | 全部 | 新功能，无测试 |
| 前端组件测试 | 全部 | vitest 已配置但无测试文件 |
