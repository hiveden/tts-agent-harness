# E2E 细粒度测试用例

> 基于全流程通过后的细化验证，覆盖已知 bug 和边界场景。

## 已知 Bug

| # | 描述 | 根因推测 |
|---|---|---|
| BUG-1 | **Duration 显示不对** — chunk 行 Dur 列显示异常值（如 48695.7s） | P2 的 `run_p2_synth` 写入 `take.duration_s` 时可能没正确解析 WAV header，或 Fish API 返回的不是标准 WAV |
| BUG-2 | **Subtitle 列切换 TTS 源有 bug** — 点击「字幕/TTS源」切换按钮后显示异常 | 待通过测试定位具体表现 |

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

### TC-03: Duration 列（BUG-1 验证）

```
前置: episode 已合成（P2 完成，有 take）
操作: 查看 chunks 列表
验证:
  - [ ] Dur 列显示合理秒数（如 1.2s, 3.5s），不是 48695.7s
  - [ ] duration 来自 currentTake.durationS
  - [ ] 后端 API 返回的 take.durationS 值是否合理
  - [ ] 如果后端值异常，检查 P2 写 take 时 duration_s 的来源
```

**排查链路:**
```
Fish API 返回 WAV bytes
  → P2 run_p2_synth 计算 duration_s
    → 怎么计算的？是从 WAV header 解析还是从 Fish API metadata 读？
  → INSERT takes (duration_s=???)
  → 前端 chunk.takes[0].durationS → ChunkRow Dur 列
```

### TC-04: 字幕/TTS源 切换（BUG-2 验证）

```
前置: episode 已合成（P2 完成）
操作:
  1. 默认模式是 "字幕"，观察文本列显示内容
  2. 点击 "TTS源" 切换按钮
  3. 观察文本列变化
  4. 点击 "字幕" 切换回来
验证:
  - [ ] 字幕模式: 显示 getDisplaySubtitle(chunk)
    - 如果 chunk.subtitleText 非空 → 显示 stripControlMarkers(subtitleText)
    - 如果 chunk.subtitleText 为空 → 显示 stripControlMarkers(text)
  - [ ] TTS源模式: 显示 chunk.textNormalized（含 [break] 等控制标记）
  - [ ] 切换后文本内容确实不同（如果 textNormalized 含控制标记）
  - [ ] 切换不影响其他列（ID/状态/时长/播放）
  - [ ] 编辑状态下切换是否正常
```

### TC-05: 音频播放

```
前置: episode 已合成（P2 完成，chunk 有 take）
操作:
  1. 点击 ▶ 播放按钮
  2. 等 audio 加载
  3. 点击 ⏸ 暂停
验证:
  - [ ] ▶ 按钮变为 ⏸
  - [ ] audio 元素 src 包含 /audio/
  - [ ] audio 元素能实际播放（不是 404/空）
  - [ ] duration 与 Dur 列一致
  - [ ] 暂停后再点能继续播放
  - [ ] 同时只有一个 chunk 在播放
```

### TC-06: Stage Pills 显示

```
前置: episode 已跑完 synthesize（P2→P3→P5 完成）
操作: 查看每个 chunk 行
验证:
  - [ ] 每个 chunk 行底部有 stage pills
  - [ ] P2 pill: 绿色 (ok)
  - [ ] P3 pill: 绿色 (ok)
  - [ ] P5 pill: 绿色 (ok)
  - [ ] 如果某 stage 失败 → 红色 pill + ⚠ 图标
  - [ ] EpisodeStageBar（顶部）显示聚合: P2 [2/2 ✓] P3 [2/2 ✓] P5 [2/2 ✓]
```

### TC-07: Stage Log Drawer

```
前置: chunk 有 stageRuns（P2 ok）
操作: 点击 P2 stage pill
验证:
  - [ ] 右侧 drawer 打开
  - [ ] 显示 chunk ID + stage 名 + status badge
  - [ ] 如果有 error → 显示 error 信息
  - [ ] 日志区域（可能为空 — dev mode 不写日志文件）
  - [ ] "仅重跑 P2" 和 "从 P2 起重跑" 按钮可见
  - [ ] 点 ✕ 关闭 drawer
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
  - [ ] 展开后显示 5 个参数字段
  - [ ] 修改后出现 "● 未保存" 标记
  - [ ] Save 后标记消失
  - [ ] 刷新后值保持 0.5（持久化成功）
  - [ ] Reset 按钮恢复原值
```

### TC-09: 编辑 Chunk 文本

```
前置: episode 已合成
操作:
  1. 点击 ✎ 打开编辑器
  2. 修改 textNormalized
  3. 点 Stage（暂存）
  4. 观察 EditBanner
  5. 点 Apply All
验证:
  - [ ] ✎ 按钮变为 ✕（关闭编辑器）
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
  5. 按 Esc → 关闭编辑器
验证:
  - [ ] Space 在非 input 状态下切换播放
  - [ ] j/k 在播放状态下切换 chunk
  - [ ] e 打开当前 chunk 的编辑器
  - [ ] Esc 优先级: 编辑器 > drawer > 播放
  - [ ] 在 input/textarea 内按键不触发快捷键
```

### TC-11: Sidebar 菜单操作

```
前置: 有多个 episode
操作:
  1. 点击 ⋯ 打开菜单
  2. 测试 Duplicate
  3. 测试 Archive
  4. 测试 Delete
验证:
  - [ ] ⋯ 菜单显示 3 个选项
  - [ ] Duplicate: 弹出 prompt → 输入新 ID → 新 episode 出现
  - [ ] Archive: 确认后 episode 从列表消失
  - [ ] Delete: 确认后 episode 从列表消失且不可恢复
  - [ ] 菜单点外面自动关闭
```

### TC-12: 合成全部 + 跳过已确认（D-05）

```
前置:
  - episode 有 3 个 chunks
  - chunk #1 已有 selected_take（之前合成过）
  - chunk #2, #3 无 take
操作: 点击 "合成全部"
验证:
  - [ ] chunk #1 的 P2 被跳过（stage pill 直接 ok，不走 Fish API）
  - [ ] chunk #2, #3 的 P2 真实调用 Fish API
  - [ ] 所有 3 个 chunk 的 P3/P5 都跑
  - [ ] 最终 episode status=done
```

### TC-13: 失败重试

```
前置:
  - episode 已合成但 P3 失败（如 WhisperX 挂了）
  - chunk #1: P2 ok, P3 failed
操作:
  1. 按钮显示 "重试失败(1)"
  2. 点击 "重试失败"
验证:
  - [ ] 只重跑失败的 chunk #1，不动其他 chunk
  - [ ] P3 重新执行
  - [ ] 成功后 stage pill P3 变绿
  - [ ] episode status → done（如果全部 chunk 通过）
```

### TC-14: SSE 实时更新

```
前置: episode 正在合成
操作: 观察页面实时变化
验证:
  - [ ] 不需要手动刷新，stage pills 自动更新
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
| running | 禁用          | running (动画) | chunks + 进度 |
| failed  | "重试失败(N)" | failed | chunks + 失败标记 |
| done    | "完成 ✓"      | done   | chunks + 全绿 |
```

## Playwright 实现策略

上述 TC 拆为 **3 个 Playwright test**：

1. **journey-happy-path.spec.ts** — TC-01 到 TC-07 的正常流程（已有，就是 full-pipeline.spec.ts）
2. **journey-edit-retry.spec.ts** — TC-08, TC-09, TC-12, TC-13（编辑 + 重试场景）
3. **journey-ui-details.spec.ts** — TC-03, TC-04, TC-10, TC-11, TC-14, TC-15（UI 细节验证）

每个 test 是一个完整旅程，一个录屏。

## Bug 排查计划

### BUG-1: Duration 异常

```
排查步骤:
1. 看 P2 task run_p2_synth 里 duration_s 怎么算的
2. 看 Fish API 返回的 WAV header
3. 看 TakeAppend 写入 DB 的值
4. 修: 如果 P2 没算 duration，改为从 WAV bytes 解析
```

### BUG-2: 字幕/TTS源 切换

```
排查步骤:
1. 在浏览器里实际点切换，看 console 有没有报错
2. 检查 displayMode state 是否正确传到 ChunkRow
3. 检查 getDisplaySubtitle vs textNormalized 的实际值差异
4. 可能是 subtitleText 为 null 时两个模式显示一样（不是 bug 而是数据问题）
```
