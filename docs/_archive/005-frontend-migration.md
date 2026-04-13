# 前端组件迁移清单

> 目标：恢复 page.tsx 的完整功能，所有丢失的组件接回新 types 体系
> 方法：逐个迁移 → e2e 测试 → 修 bug → 记录问题

## 组件清单

### 已接入 page.tsx ✅

| # | 组件 | 功能 | 状态 |
|---|---|---|---|
| 1 | EpisodeSidebar | episode 列表 + 选择 | ✅ |
| 2 | EpisodeHeader | 标题 + 状态 + Run 按钮 | ✅ |
| 3 | TtsConfigBar | TTS 参数配置 | ✅ |
| 4 | StageProgress | episode 运行状态条 | ✅ |
| 5 | EpisodeStageBar | episode 级 stage 聚合进度 | ✅ |
| 6 | EditBanner | 编辑暂存提示条 | ✅ |
| 7 | ChunksTable | chunks 列表容器 | ✅ |
| 8 | LogViewer | 事件日志 | ✅ |
| 9 | NewEpisodeDialog | 新建 episode 弹窗 | ✅ |

### 需要迁移 ❌

| # | 组件 | 功能 | 依赖 | 迁移复杂度 |
|---|---|---|---|---|
| M1 | **StagePipeline** | chunk 行内 stage pills (P2/P3/P5) | StageRun[], getStageRun() | 低 — 已适配新 types |
| M2 | **ChunkRow + StagePipeline 集成** | 在 ChunkRow 底部渲染 StagePipeline | M1 完成 | 中 — 需加 onStageClick prop |
| M3 | **StageLogDrawer** | 点 stage pill → 侧边看日志 + retry | StageRun, StageName | 低 — 已适配新 types |
| M4 | **StageLogDrawer 接入 page.tsx** | drawerOpen 状态 + 渲染 | M3 | 中 — 需恢复 page.tsx 状态 |
| M5 | **ScriptPreview** | P1 前 script 预览 | ScriptSegment | 低 — 纯展示 |
| M6 | **HelpDialog** | 使用说明弹窗 | 无 | 低 — 纯展示 |
| M7 | **SettingsDialog** | harness 配置弹窗 | 无外部依赖 | 低 — 但需确认与 TtsConfigBar 的职责边界 |
| M8 | **RetryBanner** | retry 模式提示条 | runMode | 低 — 但 runMode 已移除，可能不再需要 |
| M9 | **键盘快捷键** | Space/j/k/e/Esc | playingChunkId, editing | 中 — 需恢复 useEffect |
| M10 | **删除/复制/归档** | sidebar 右键菜单 | deleteEpisode/duplicateEpisode/archiveEpisode | 中 — 需恢复 handlers |

## 迁移顺序（按依赖排序）

1. **M1** StagePipeline — 已重写，确认可用
2. **M2** ChunkRow + StagePipeline 集成
3. **M3+M4** StageLogDrawer 接入 page.tsx
4. **M5** ScriptPreview 接入
5. **M10** 删除/复制/归档 handlers
6. **M6** HelpDialog
7. **M9** 键盘快捷键
8. **M7** SettingsDialog（评估是否需要）
9. **M8** RetryBanner（评估是否需要）

## 迁移结果

| # | 组件 | 状态 | 备注 |
|---|---|---|---|
| M1 | StagePipeline | ✅ 完成 | 已适配 stageRuns 数组 |
| M2 | ChunkRow + StagePipeline | ✅ 完成 | compact mode，onStageClick prop chain |
| M3 | StageLogDrawer | ✅ 完成 | 已适配 StageRun type |
| M4 | StageLogDrawer 接入 page.tsx | ✅ 完成 | drawerOpen state |
| M5 | ScriptPreview | ⚠ 已 import | 后端不返回 segments，暂不渲染 |
| M6 | HelpDialog | ✅ 完成 | ? 按钮在 header |
| M7 | SettingsDialog | ⏭ 跳过 | 与 TtsConfigBar 职责重叠，待设计决策 |
| M8 | RetryBanner | ⏭ 跳过 | runMode 已移除，不再需要 |
| M9 | 键盘快捷键 | ✅ 完成 | Space/j/k/e/Esc |
| M10 | 删除/复制/归档 | ✅ 完成 | sidebar ⋯ menu + handlers |

## 问题记录

| # | 问题 | 严重度 | 状态 | 备注 |
|---|---|---|---|---|
| P1 | ScriptPreview 无数据源 | 低 | 跳过 | 后端 GET /episodes/{id} 不返回 script segments，前端无法渲染预览。需后端解析 script.json |
| P2 | duration 异常值 48695s | 中 | 待修 | P2 合成后 take.durationS 为 48695.77，明显不对。可能是 WAV header 解析或 Fish API 返回的 metadata 问题 |
| P3 | SettingsDialog 职责不明 | 低 | 跳过 | 原 demo 版管理 .harness/config.json，新版有 TtsConfigBar 管 episode.config，两者重叠 |
