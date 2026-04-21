# E2E 细粒度测试用例

> 初稿: 2026-04-12
> 最近更新: 2026-04-21（阶段名更新 P3→P2c/P2v；原始 BUG 已解决；补 TC-16~19）

基于全流程通过后的细化验证，覆盖关键交互和边界场景。

## Pipeline 阶段名

当前完整阶段：`p1 / p1c / p2 / p2c / p2v / p5 / p6 / p6v`。下文 TC 步骤中如出现历史版本的 P3，一律对应现在的 P2v。

## 测试用例

### TC-01: Episode 创建与展示

```
前置: 无
操作: 创建 episode，上传含 2 个 segment 的 script.json
验证:
  - [ ] sidebar 显示 episode title（不是 ID）
  - [ ] status badge 显示 "empty"
  - [ ] 主区域显示 "还没有 chunks"
  - [ ] TTS Config bar 可见（折叠状态）
  - [ ] 按钮显示 "切分"
```

### TC-02: P1 切分

```
前置: TC-01 创建的 episode（status=empty）
操作: 点击 "切分" 按钮
验证:
  - [ ] chunks 列表出现（2 个 segment → 预期 2 个 chunk）
  - [ ] 每个 chunk 显示: ID | 状态(○ pending) | Dur(--) | Play(禁用) | 文本
  - [ ] 按钮变为 "合成全部"
  - [ ] status badge 变为 "ready"
  - [ ] EpisodeStageBar 不显示（chunks 无 stageRuns）
```

### TC-03: Duration 列正确性

```
前置: episode 已合成（P2 完成，有 take）
操作: 查看 chunks 列表
验证:
  - [ ] Dur 列显示合理秒数（如 1.2s, 3.5s）
  - [ ] duration 来自 currentTake.durationS
  - [ ] 后端 P2 通过 `wave` 模块解析 WAV header 计算
```

历史背景：初版由于未解析 WAV header 而显示过 48695.7s 的异常值，已在 `p2_synth.py` 中修复，改为 stdlib `wave` 模块读取。

### TC-04: 字幕/TTS源 切换

```
前置: episode 已合成（P2 完成）
操作:
  1. 默认模式是 "字幕"，观察文本列
  2. 点击 "TTS源" 切换
  3. 点击 "字幕" 切回
验证:
  - [ ] 字幕模式: 显示 getDisplaySubtitle(chunk)
    - subtitleText 非空 → 显示 stripControlMarkers(subtitleText)
    - subtitleText 为空 → 显示 stripControlMarkers(text)
  - [ ] TTS 源模式: 显示 chunk.textNormalized（含 [break] 控制标记）
  - [ ] 两种模式文本确实不同（当 textNormalized 含控制标记时）
  - [ ] 切换不影响其他列
```

实装位置：`ChunkRow.tsx:15` `displayMode` state。

### TC-05: 音频播放

```
前置: episode 已合成（chunk 有 take）
操作: 点击 ▶ → 等加载 → 点击 ⏸
验证:
  - [ ] ▶ 按钮变为 ⏸
  - [ ] audio 元素 src 包含 /audio/
  - [ ] 实际可播放（非 404）
  - [ ] duration 与 Dur 列一致
  - [ ] 暂停后再点继续播放
  - [ ] 同时只有一个 chunk 在播放
```

### TC-06: Stage Pills 显示

```
前置: episode 已跑完 synthesize（P2→P2c→P2v→P5 完成）
操作: 查看每个 chunk 行
验证:
  - [ ] 每个 chunk 行底部有 stage pills
  - [ ] P2/P2c/P2v/P5 pills: 全绿
  - [ ] 若某 stage 失败 → 红色 pill + ⚠
  - [ ] EpisodeStageBar（顶部）聚合: P2 [2/2 ✓] P2v [2/2 ✓] P5 [2/2 ✓] ...
```

### TC-07: Stage Log Drawer

```
前置: chunk 有 stageRuns（P2 ok）
操作: 点击 P2 stage pill
验证:
  - [ ] 右侧 drawer 打开
  - [ ] 显示 chunk ID + stage 名 + status badge
  - [ ] 若有 error 显示 error 信息
  - [ ] "仅重跑 P2" 和 "从 P2 起重跑" 按钮可见
  - [ ] 点 ✕ 关闭
```

### TC-08: TTS Config 修改

```
前置: episode 存在
操作:
  1. 展开 TTS Config bar
  2. 修改 temperature 为 0.5
  3. 点 Save Config
  4. 刷新页面
验证:
  - [ ] 展开前显示 "▸ TTS Config"
  - [ ] 展开后显示 config 参数（temperature/top_p/chunk_length/normalize 等）
  - [ ] 修改后出现 "● 未保存" 标记
  - [ ] Save 后标记消失
  - [ ] 刷新后值保持 0.5
  - [ ] Reset 按钮恢复原值
  - [ ] 修改 config 后新 P2 run 使用新参数（需 verify P2 实际读 episode.config）
```

### TC-09: 编辑 Chunk 文本

```
前置: episode 已合成
操作:
  1. 点击 ✎ 打开编辑器
  2. 修改 textNormalized
  3. 点 Stage 暂存
  4. 点 Apply All
验证:
  - [ ] ✎ 按钮变为 ✕
  - [ ] textarea 显示当前 textNormalized
  - [ ] Stage 后 chunk 行显示 "TTS dirty" badge
  - [ ] EditBanner 显示 "1 TTS change"
  - [ ] Apply All 后 dirty badge 消失
  - [ ] 后端触发 P2 重新合成（stage pills 变化）
```

### TC-10: Keyboard Shortcuts

```
前置: episode 有 chunks
操作:
  1. 按 Space → 播放/暂停
  2. 按 j → 下一个 chunk
  3. 按 k → 上一个 chunk
  4. 按 e → 打开编辑器
  5. 按 Esc → 关闭
验证:
  - [ ] Space 在非 input 状态切换播放
  - [ ] j/k 切换 chunk
  - [ ] e 打开编辑器
  - [ ] Esc 优先级: 编辑器 > drawer > 播放
  - [ ] 在 input/textarea 内不触发
```

### TC-11: Sidebar 菜单操作

```
前置: 有多个 episode
操作: ⋯ → Duplicate / Archive / Delete
验证:
  - [ ] ⋯ 菜单显示 3 个选项
  - [ ] Duplicate: 输入新 ID → 新 episode 出现
  - [ ] Archive: 确认后从列表消失
  - [ ] Delete: 确认后从列表消失且不可恢复
  - [ ] 点外面自动关闭
```

### TC-12: 合成全部 + 跳过已确认（D-05）

```
前置:
  - episode 3 chunks
  - chunk #1 已有 selected_take
  - chunk #2, #3 无 take
操作: "合成全部"
验证:
  - [ ] chunk #1 的 P2 被跳过（stage pill 直接 ok，不走 Fish API）
  - [ ] chunk #2/#3 的 P2 真实调用 Fish API
  - [ ] 所有 3 个 chunk 的 P2v/P5 都跑
  - [ ] 最终 status=done

注：F-06-2 跳过逻辑尚待代码抽查，此 TC 现阶段可能失败。
```

### TC-13: 失败重试

```
前置:
  - chunk #1: P2 ok, P2v failed
  - 按钮显示 "重试失败(1)"
操作: "重试失败"
验证:
  - [ ] 只重跑失败的 chunk #1
  - [ ] P2v 重新执行
  - [ ] 成功后 pill 变绿
  - [ ] episode status → done
```

### TC-14: SSE 实时更新

```
前置: episode 正在合成
操作: 观察实时变化
验证:
  - [ ] 不需要刷新，stage pills 自动更新
  - [ ] EpisodeStageBar 实时显示进度
  - [ ] LogViewer 底部实时追加事件日志
  - [ ] status badge 自动从 running → done/failed
```

### TC-15: Episode 状态流转完整性

```
验证所有状态下的按钮和显示:

| status  | 按钮          | badge  | chunks 区 |
|---------|---------------|--------|-----------|
| empty   | "切分"        | empty  | "还没有 chunks" |
| ready   | "合成全部"    | ready  | chunks 列表 |
| running | 运行中+取消   | running (动画) | chunks + 进度 |
| failed  | "重试失败(N)" | failed | chunks + 失败标记 |
| done    | "完成 ✓"      | done   | chunks + 全绿 |
```

### TC-16: 批量操作（2026-04 新增）

```
前置: episode 多 chunks
操作:
  1. 开启批量模式
  2. 勾选 2-3 个 chunk
  3. 点击 "合成选中(N)"
  4. 再试 "导出选中"
验证:
  - [ ] 批量模式切换后 chunk 行显示 checkbox
  - [ ] 勾选数量正确反映在按钮上
  - [ ] 批量 Run 只跑勾选的 chunk
  - [ ] 批量 Export 仅对勾选范围生成 zip
  - [ ] 退出批量模式清空 batchSelected
```

### TC-17: 取消运行（2026-04 新增）

```
前置: pipeline 正在 running
操作: 点击"取消"按钮
验证:
  - [ ] 取消按钮可见于 running 状态下
  - [ ] 点击后 SSE 事件推送状态切换
  - [ ] 正在执行的 chunk 标记为 failed 或 pending
  - [ ] episode status 回到 ready/failed
  - [ ] 再次可点击 Run
```

### TC-18: Stage 级重试（D-04）

```
前置: 某 chunk 的 P2v 失败
操作: 点击 EpisodeStageBar 上 P2v 的重跑入口
验证:
  - [ ] 只重跑失败 chunk 的 P2v stage，不动其他 stage
  - [ ] 通过后 pill 变绿
  - [ ] 不级联到 P5/P6（stage-only 模式）
```

### TC-19: 连续播放（2026-04 新增）

```
前置: episode 有 3+ chunks 已合成
操作:
  1. 打开 ContinuousPlayBar
  2. 开启连续播放
  3. 播放 chunk #1
  4. 等播完
  5. 调整速率为 1.5x
验证:
  - [ ] chunk #1 播完后自动切到 #2
  - [ ] 播放光标与当前 chunk 一致
  - [ ] 速率切换对后续播放生效
  - [ ] 手动点其他 chunk 播放仍允许
  - [ ] 关闭连续播放后停在当前 chunk
```

## Playwright 实现策略

当前 3 个 spec（`web/tests/`）：

| Spec | 覆盖 |
|------|-----|
| `full-pipeline.spec.ts` | TC-01 ~ TC-07（happy path） |
| `ui-details.spec.ts` | TC-10 / TC-11 / TC-14 / TC-15（UI 细节） |
| `record-v1.spec.ts` | 录屏 / 回归对比 |

待补：
- `edit-retry.spec.ts` → TC-08 / TC-09 / TC-12 / TC-13
- `batch-and-continuous.spec.ts` → TC-16 / TC-17 / TC-18 / TC-19

每个 test 是一个完整旅程，支持录屏。
