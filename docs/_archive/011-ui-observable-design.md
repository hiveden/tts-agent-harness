# UI 白盒可观测设计

## 设计目标

用户在 UI 上能看到 pipeline 每一步的执行状态、输入输出、校验结果和修复历程。
不需要看日志文件或终端输出就能理解"系统做了什么、为什么、结果如何"。

## 三个层级的可观测性

```
Episode 级 ─── 全局进度，哪些 chunk 在跑，哪些卡住
  └─ Chunk 级 ─── 8 个 stage 的状态 pill，当前 attempt 和 level
      └─ Stage 级 ─── 输入参数、校验分数、诊断详情、修复动作
```

### 1. Episode 级 — EpisodeStageBar

当前只展示 P2/P3/P5 三个聚合 pill。改为 8 个 stage，区分处理 stage 和校验 gate：

```
Pipeline  [P1 ✓] · [P1c ✓] ─ [P2 17/20 ⚠3] · [P2c 17/17 ✓] · [P2v 14/17 ⚠3] ─ [P5 ✓] ─ [P6 ✓] · [P6v ✓]
                               处理 stage ● 圆形       校验 gate ■ 方形
```

设计要点：

- 处理 stage（P1/P2/P5/P6）用圆角 pill，校验 gate（P1c/P2c/P2v/P6v）用更小的方形 pill
- 校验 gate 和对应 stage 之间用 `·` 紧凑连接，stage 之间用 `─` 连线
- 聚合逻辑：`ok/total` 和 `⚠N` 保持不变
- needs_review 的 chunk 用独立颜色（琥珀色）标出：`P2v 14/17 ⚠3 🔍2`

### 2. Chunk 级 — StagePipeline + 状态摘要

每行 chunk 下方的 stage pill 从 5 个扩展到 8 个：

pipeline 是一条线，合成循环体现在 P2/P2c/P2v 区域的 attempt 角标上：

```
shot01_chunk01  ✓  8.5s  ▶  第一句正常通过的文本
                [P1]─[P1c]─[P2]─[P2c]─[P2v]─[P5]─[P6]─[P6v]     一次通过

shot01_chunk03  ✓  8.5s  ▶  Mac 跑本地模型，之前一直很尴尬...
                [P1]─[P1c]─[P2③]─[P2c]─[P2v③]─[P5]─[P6]─[P6v]   第3次 attempt 通过

shot03_chunk02  ◐  --    ▶  GitHub 上有多个 issues...
                [P1]─[P1c]─[P2②]─[P2c]─[P2v]                     正在第2次合成循环

shot06_chunk01  🔍  --   ▶  用 API 跑，烧钱...
                [P1]─[P1c]─[P2⑤]─[P2c]─[P2v⑤]                    5次用尽，needs_review
```

合成循环中，P2 和 P2v 的 attempt 角标同步增长，用户一眼看出"试了几次"。

P2v pill 的展示：

| 状态 | pill 样式 | 含义 |
|------|-----------|------|
| 一次通过 | 绿色 `P2v` | 首次校验就过了 |
| 重试后通过 | 绿色 `P2v③` | 第 3 次 attempt 通过 |
| 合成循环中 | 蓝色 pulse `P2v` | P2→P2c→P2v 正在执行 |
| needs_review | 琥珀色 `P2v⑤` | attempt 用尽，等人工 |

chunk 状态摘要：

| ChunkStatus | 图标 | 颜色 | 说明 |
|-------------|------|------|------|
| pending | ○ | neutral | 未开始 |
| synth_done | ◐ | blue | 在合成循环中（P2 done，等 P2c/P2v） |
| verified | ✓ | green | P2v 通过，可进入 P5 |
| needs_review | 🔍 | amber | 合成循环 attempt 用尽 |
| failed | ✗ | red | 不可恢复的错误 |

### 3. Stage 级 — StageLogDrawer 扩展

点击任意 stage pill 打开右侧 drawer。当前 drawer 展示日志文本 + request/response。
扩展为三个 tab：

#### Tab 1: 概览

```
┌─────────────────────────────────────────────┐
│ shot01_chunk03 · P2v · attempt 3 / Level 1  │
│                                             │
│ Status    [ok]         Duration  1,240ms    │
│ Started   14:23:05     Finished  14:23:06   │
│                                             │
│ ─── 评估结果 ────────────────────────────── │
│                                             │
│  时长/字数比    ✓ 0.95  (6.2 字/秒)          │
│  静音检测      ✓ 1.00  (无异常静音)          │
│  音素距离      ✓ 0.88  ("mai ke" ≈ "mai ke") │
│  字符比        ✗ 0.72                        │
│  ASR 置信度    0.85                          │
│  ────────────                               │
│  综合          0.87 → PASS                   │
│                                             │
│ ─── 文本对比 ────────────────────────────── │
│                                             │
│  原文:  Mac 跑本地模型，之前一直很尴尬       │
│  转写:  麦克跑本地模型，之前一直很尴尬       │
│         ^^^                                 │
│         音素匹配 ✓ (mai ke = mai ke)          │
│                                             │
│ ─── TTS 参数 ───────────────────────────── │
│                                             │
│  provider    fish-s2pro                      │
│  temperature 0.3  (Level 1: 从 0.7 降低)     │
│  top_p       0.8                             │
│  speed       1.15                            │
└─────────────────────────────────────────────┘
```

评估维度用**分数条**可视化（类似进度条），通过的绿色，未通过的红色，一眼看出哪个维度拉低了分数。

#### Tab 2: Attempt 历史

纵向时间线，展示完整的修复历程：

```
┌─────────────────────────────────────────────┐
│ Attempt 历史 (3 次)                          │
│                                             │
│  ① L0 · 14:22:58 · 1,180ms · FAIL          │
│  │  综合 0.45                                │
│  │  诊断: 英文品牌名错读                      │
│  │        "Mac" → "卖个" (音素距离 0.35)      │
│  │  修复: 原样重试                            │
│  │                                           │
│  ② L0 · 14:23:01 · 1,210ms · FAIL          │
│  │  综合 0.52                                │
│  │  诊断: 仍然错读                            │
│  │        "Mac" → "马克" (音素距离 0.55)      │
│  │  修复: 升级 Level 1, 降 temperature        │
│  │                                           │
│  ③ L1 · 14:23:05 · 1,240ms · PASS  ← 当前  │
│     综合 0.87                                │
│     temperature: 0.7 → 0.3                   │
│     "Mac" → "麦克" (音素距离 0.88) ✓          │
└─────────────────────────────────────────────┘
```

每个 attempt 节点可展开查看完整的评估分数和诊断详情。

#### Tab 3: 日志

保持现有的原始日志输出（`pre` 标签），用于调试。

### needs_review 交互

chunk 进入 needs_review 状态时，UI 提供直接操作入口：

```
┌─────────────────────────────────────────────────────────┐
│ shot03_chunk02 · needs_review                           │
│                                                         │
│ ⚠ 自动修复已用尽 5 次 attempt（L0×2, L1×2, L2×1）       │
│                                                         │
│ 最后诊断: "GitHub" 持续被读为 "DTHUB"                    │
│ 音素距离: 0.28 (阈值 0.70)                               │
│ 建议: 手动改写为 "git hub" 或添加 phoneme 标记            │
│                                                         │
│ ┌─ text_normalized ──────────────────────────────────┐  │
│ │ GitHub 上有多个 issues 记录了这些问题               │  │
│ │                                                    │  │
│ │ [编辑区域，可直接修改]                               │  │
│ └────────────────────────────────────────────────────┘  │
│                                                         │
│              [查看历史 attempt]    [重置并重试 →]          │
└─────────────────────────────────────────────────────────┘
```

要素：
- 最后一次诊断的摘要（不需要用户翻日志）
- 系统的修复建议（来自 P2v diagnosis.repair_action）
- text_normalized 内联编辑框（不需要跳转到别的页面）
- "重置并重试"按钮（将状态改回 pending，触发新一轮 P2 → P2v）

## 数据流

### 新增 API 字段

StageRun 扩展：

```typescript
interface StageRun {
  stage: StageName;
  status: StageStatus;
  attempt: number;
  level?: number;              // 新增：当前修复 level (0/1/2)
  startedAt?: string;
  finishedAt?: string;
  durationMs?: number;
  error?: string;
  logUri?: string;
  stale: boolean;
  scores?: VerifyScores;       // 新增：P2v 多维评估分数
  diagnosis?: Diagnosis;       // 新增：P2v 诊断结果
}

interface VerifyScores {
  durationRatio: number;
  silence: number;
  phoneticDistance: number;
  charRatio: number;
  asrConfidence: number;
  weightedScore: number;
}

interface Diagnosis {
  type: "word_mismatch" | "word_missing" | "speed_anomaly";
  missing?: string[];
  extra?: string[];
  lowConfidenceWords?: string[];
  repairAction?: {
    nextLevel: number;
    strategy: string;
    suggestedText?: string;
  };
}
```

Chunk 扩展：

```typescript
interface Chunk {
  // ...existing fields...
  status: "pending" | "synth_done" | "verified" | "needs_review" | "failed";
  attemptHistory?: AttemptRecord[];  // 新增：P2v 的所有 attempt 记录
}

interface AttemptRecord {
  attempt: number;
  level: number;
  verdict: "pass" | "fail";
  scores: VerifyScores;
  diagnosis?: Diagnosis;
  params: Record<string, unknown>;  // 本次使用的 TTS 参数
  textUsed: string;                 // 本次使用的 text_normalized
  transcribedText: string;
  durationMs: number;
  timestamp: string;
}
```

### SSE 事件扩展

新增事件类型，实时推送 P2v 进展：

```typescript
// P2v attempt 开始
{ kind: "verify_start", chunkId: "...", attempt: 2, level: 1 }

// P2v attempt 结束
{ kind: "verify_end", chunkId: "...", attempt: 2, verdict: "fail",
  scores: { weightedScore: 0.52, ... }, diagnosis: { ... } }

// 进入 needs_review
{ kind: "needs_review", chunkId: "...", totalAttempts: 5 }

// 人工重置后重新开始
{ kind: "review_reset", chunkId: "...", newText: "..." }
```

## 组件变更清单

| 组件 | 变更 |
|------|------|
| `types.ts` | StageName 加 p1c/p2c/p2v/p6v，ChunkStatus 加 verified/needs_review，新增 VerifyScores/Diagnosis/AttemptRecord 类型 |
| `stage-info.ts` | 新增 4 个 check gate 的描述 |
| `StagePipeline.tsx` | 8 个 pill，校验 gate 用方形样式，P2v 显示 attempt 角标 |
| `EpisodeStageBar.tsx` | CHUNK_STAGES 扩展到 8 个，紧凑/宽松两种视觉分组 |
| `StageLogDrawer.tsx` | 三 tab 重构（概览/历史/日志），概览 tab 展示评估分数条 |
| `ChunkRow.tsx` | statusIcon 支持新状态，needs_review 行高亮琥珀色 |
| 新增 `VerifyScoreBar.tsx` | 多维评估分数的可视化条形图组件 |
| 新增 `AttemptTimeline.tsx` | attempt 历史时间线组件 |
| 新增 `NeedsReviewPanel.tsx` | needs_review 的内联编辑 + 重试面板 |
