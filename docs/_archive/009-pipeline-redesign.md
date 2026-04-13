# Pipeline 设计 — 透明校验与自动修复

## 设计原则

1. **全流程可见** — 每个 stage 在 UI 上有对应状态，没有黑盒环节
2. **单一职责** — 每个 stage 只做一件事
3. **确定性优先** — 校验尽量用确定性信号，模型信号做辅助
4. **自动修复分级升级** — 从廉价到昂贵，自动尝试到人工兜底
5. **供应商无关** — pipeline 通过输入/输出契约解耦，stage 内部实现可替换

## Pipeline

本文档描述的是**单个 chunk 的 pipeline 流程**。chunk 之间的并行调度是 runner 层的职责，不在此讨论。

```
P1 → P1c → P2 ⇄ P2c ⇄ P2v → P5 → P6 → P6v
切分  输入校验  ╰── 合成循环 ──╯  字幕  拼接  端到端验证
```

合成循环：P2v 不过时，Repair 决策后回退到 P2 重试。通过后才进入 P5。循环有上界（max_total_attempts），用尽则标记 needs_review 并停止。

```
P2 → P2c → P2v → [pass] → P5 → P6 → P6v
 ↑           │
 │    [fail, attempt < N]
 └── Repair ─┘
       │
 [attempt = N]
       ↓
  needs_review (停)
```

## Stage 定义

### P1 · 切分

| 项目 | 说明 |
|------|------|
| 输入 | script.json |
| 输出 | chunks.json |
| 确定性 | 是 |
| 职责 | 将 script segments 按句切分为 chunks，生成 text 和 text_normalized |

### P1c · 输入校验

| 项目 | 说明 |
|------|------|
| 输入 | chunks.json |
| 输出 | pass/fail（per chunk） |
| 确定性 | 是 |
| 职责 | 校验 chunks 合法性，在 TTS 调用前拦截可预见的问题 |

校验规则：

| 检查项 | 规则 | 失败级别 |
|--------|------|----------|
| chunk 长度上限 | char_count ≤ 300 | hard |
| chunk 长度下限 | char_count ≥ 5 | hard |
| 空文本 | text_normalized.trim() 非空 | hard |
| 字符集 | 不含 emoji / 不可打印 Unicode | hard |
| 控制标记平衡 | `[break]` 等标记不占比超过 50% | warning |
| 可逆性 | chunks 拼回后 === 原 segment 文本 | hard |

### P2 · TTS 合成

| 项目 | 说明 |
|------|------|
| 输入 | chunk.text_normalized + TTS 参数 |
| 输出 | {chunk_id}.wav |
| 确定性 | 否（外部 API） |
| 职责 | 调用 TTS 引擎将文本合成为语音 |

P2 通过 provider 抽象与具体 TTS 供应商解耦。每个 provider 实现统一接口：

```typescript
interface TtsProvider {
  name: string;
  synthesize(text: string, params: TtsParams): Promise<Buffer>;  // 返回 WAV
  supportedParams: string[];  // 该 provider 支持的参数列表
}
```

Provider 配置：

```json
{
  "p2": {
    "provider": "fish-s2pro",
    "params": { "temperature": 0.7, "top_p": 0.8, "speed": 1.15 }
  }
}
```

P2 以外的所有 stage 只依赖输出契约（WAV 44100Hz mono），不感知 provider。Repair 的 Level 1 调参策略需要读取 `supportedParams` 来决定可调范围。

### P2c · 格式校验

| 项目 | 说明 |
|------|------|
| 输入 | {chunk_id}.wav |
| 输出 | pass/fail（per chunk） |
| 确定性 | 是 |
| 职责 | 校验 WAV 文件格式合法性，在 ASR 之前拦截坏文件，避免浪费 WhisperX 算力 |

校验规则：

| 检查项 | 规则 | 失败级别 |
|--------|------|----------|
| 文件存在 | wav 文件存在 | hard |
| 时长范围 | 0 < duration < 60s | hard |
| 采样率 | 44100 Hz | hard |
| 声道 | mono（1 channel） | hard |
| 语速合理性 | 2-12 字/秒（中文） | warning |

P2c 不过 → 直接 retry P2（不需要跑 ASR）。

### P2v · 内容验证

| 项目 | 说明 |
|------|------|
| 输入 | {chunk_id}.wav + chunk.text（原文） |
| 输出 | transcript.json + 校验报告（per chunk） |
| 确定性 | 否（WhisperX 模型） |
| 职责 | (1) ASR 转写获取 word-level timestamps (2) 原文比对做质量校验 |

ASR 只调一次，同时产出 P5 需要的 transcript 和质量校验结果。校验通过的 chunk，transcript.json 直接作为 P5 的输入。

#### 多维评估框架

单一文本比对无法区分 TTS 真错 vs ASR 误识别。采用多维评估，确定性信号为主、模型信号为辅：

```
                  ┌─ 时长/字数比 ──────── 确定性 ─── 权重 0.25
                  ├─ 静音段检测 ──────── 确定性 ─── 权重 0.20
P2v 综合评分 ← ├─ 音素距离 ─────────── 确定性 ─── 权重 0.25
                  ├─ 字符比 ────────────── 模型依赖 ─ 权重 0.15
                  └─ ASR 词级置信度 ──── 模型自评 ─ 权重 0.15
```

| 维度 | 数据来源 | 确定性 | 说明 |
|------|----------|--------|------|
| 时长/字数比 | ffprobe + char_count | 是 | 200 字 2 秒 = 必然有问题 |
| 静音段检测 | ffmpeg silencedetect | 是 | 异常长静音 = 可能吞字 |
| 音素距离 | pypinyin / 音素词典 | 是 | 拼音层比对，区分"读对但 ASR 转写不同"和"真的读错" |
| 字符比 | WhisperX 转写文本 | 否 | 原文 vs 转写文本的字符数比值 |
| ASR 词级置信度 | WhisperX word.score | 否 | 低 score 的 mismatch 大概率是 ASR 听错，不该算 TTS 的问题 |

判定逻辑：

```
综合加权分 > 0.7 → pass
综合加权分 ≤ 0.7 → fail，进入 Repair 流程
```

#### P2v 产物

每次 attempt 写一份独立记录（不覆盖），保证人工可追溯：

```
.work/<episode>/verify/
  ├── chunk_01.attempt_1.json
  ├── chunk_01.attempt_2.json
  └── chunk_02.attempt_1.json
```

记录格式：

```json
{
  "chunk_id": "chunk_01",
  "attempt": 2,
  "level": 1,
  "verdict": "fail",
  "scores": {
    "duration_ratio": 0.95,
    "silence": 1.00,
    "phonetic_distance": 0.42,
    "char_ratio": 0.68,
    "asr_confidence": 0.31
  },
  "weighted_score": 0.61,
  "diagnosis": {
    "type": "word_mismatch",
    "missing": ["4o", "API"],
    "extra": ["佛哦", "A劈唉"],
    "low_confidence_words": ["佛哦"]
  },
  "original_text": "GPT-4o 的 API 表现令人惊艳",
  "transcribed_text": "GPT佛哦的A劈唉表现令人惊艳",
  "segments": [{ "...word-level timestamps..." }],
  "repair_action": {
    "next_level": 2,
    "strategy": "rewrite_text",
    "suggested_text": "GPT four o 的 API 表现令人惊艳"
  }
}
```

### P5 · 字幕生成

| 项目 | 说明 |
|------|------|
| 输入 | P2v 产出的 transcript.json + chunk.text（原文） |
| 输出 | subtitles.json |
| 确定性 | 是 |
| 职责 | 将 word-level timestamps 与原文对齐，按行分配时间，生成字幕 |

### P6 · 音频拼接

| 项目 | 说明 |
|------|------|
| 输入 | 所有 chunk 的 wav + subtitles |
| 输出 | final.wav + final.srt |
| 确定性 | 是 |
| 职责 | ffmpeg 拼接 + padding/gap + 字幕时间戳偏移 |

### P6v · 端到端验证

| 项目 | 说明 |
|------|------|
| 输入 | final 产物 |
| 输出 | 验证报告 |
| 确定性 | 是 |
| 职责 | 最终产物完整性校验 |

校验规则：

| 检查项 | 规则 |
|--------|------|
| 字幕覆盖率 | 字幕总时长 / 音频总时长 > 阈值 |
| 字幕 gap | 相邻字幕间隔 < 阈值 |
| 字幕 overlap | 相邻字幕无时间重叠 |
| 音频时长 | ≈ sum(chunk durations) + padding |
| 字幕行数 | = sum(chunk subtitle 行数) |

## 状态机

主流程和子流程各有独立的状态转移：

### 主流程状态（chunk 粒度）

```
pending
  → synth_done            P2 合成完成
    → verified            P2v 通过（继续 P5）
    → synth_done          P2v 不过 + attempt < N → Repair 后回到 P2
    → needs_review        P2v 不过 + attempt = N → 停止，等人工
      → pending           人工修改 text_normalized 后重置
```

chunk 在合成循环中反复经历 `synth_done → (P2v fail) → synth_done`，直到 P2v pass 或 attempt 用尽。不引入额外的中间状态。

## 自动修复

### 分级升级

```
Level 0: 原样重试（利用 TTS 随机性）
  ↓ 仍然不过
Level 1: 调参重试（降 temperature / top_p）
  ↓ 仍然不过
Level 2: 改文本重试（phoneme 标记 / 品牌名映射 / LLM 改写）
  ↓ 仍然不过
Level 3: 人工介入（needs_review）
```

### Level 0 — 原样重试

同样的 text_normalized、同样的 TTS 参数，再调一次 TTS API。利用多数 TTS 引擎的随机性，同一输入可能产出不同发音。

### Level 1 — 调参重试

P2v 诊断后，根据症状调整 TTS 参数。确定性规则匹配，不需要 LLM：

| 症状 | 调参策略 |
|------|----------|
| 英文发音不稳定 | 降 temperature（0.7 → 0.3） |
| 语速异常 | 调 speed |
| 吞字 / 重复 | 降 top_p |

### Level 2 — 改文本重试

根据 P2v 的 diff 诊断（定位到具体问题词），修改 text_normalized：

| 手段 | 示例 |
|------|------|
| 英文展开 | `4o` → `four o` |
| 添加 phoneme | `<\|phoneme_start\|>fɔːr oʊ<\|phoneme_end\|>` |
| 品牌名映射表 | `GPT-4o` → 查表得到推荐写法 |
| LLM 辅助改写 | 分析问题词并建议替换 |

修改记录写入 chunk 的 `normalized_history`，保留完整修改链。

### Level 3 — 人工介入

- 标记 chunk 状态为 `needs_review`
- pipeline 暂停该 chunk，其他 chunk 继续
- UI 展示完整的 attempt 历史（每次的参数、诊断、修复动作）

人工操作：查看 attempt 记录 → 修改 text_normalized → 重置为 pending。

### Repair 调度

Repair 是子流程内部的调度逻辑，不影响主流程：

```
主流程:  ... → P2v → [pass] → P5 → P6 → P6v
                ↓
              [fail] → 派生子流程
P2 → P2c → P2v → [pass] → P5 → P6 → P6v
 ↑           │
 │    [fail] → Repair 决策
 │           │
 │    ┌── L0: 原样重试 ──→ P2
 │    ├── L1: 调参重试 ──→ P2（新参数）
 │    ├── L2: 改文本重试 → P2（新 text_normalized）
 └────┘
      └── attempt = N → needs_review（停止）
```

整个合成循环是同步阻塞的——P2v 不过，chunk 不会进入 P5。

### 重试配置

```json
{
  "repair": {
    "max_attempts_per_level": [2, 2, 1],
    "max_total_attempts": 5,
    "level_0_enabled": true,
    "level_1_enabled": true,
    "level_2_enabled": false
  }
}
```

## UI 可观测性

### Stage Pipeline

8 个 stage 全部可见：

```
[P1] — [P1c] — [P2] — [P2c] — [P2v] — [P5] — [P6] — [P6v]
```

check gate（P1c / P2c / P2v / P6v）使用不同的视觉样式（如方形 vs 圆形），区分"处理 stage"和"校验 gate"。

### P2v 详情

每个 chunk 的 P2v 结果展示全部评估维度：

```
chunk_01 · P2v attempt #2 · Level 1
───────────────────────────────────
  时长/字数比    ✓ 0.95  (6.2 字/秒)
  静音检测      ✓ 1.00  (无异常静音)
  音素距离      ✗ 0.42  ("4o" → "佛哦")
  字符比        ✗ 0.68
  ASR 置信度    0.31   (低，ASR 自己也不确定)
  ─────────────
  综合          0.61 → FAIL
  诊断          英文片段发音偏差，ASR 置信度低
  下一步        Level 2 · 改写 text_normalized
```

### needs_review 状态

- 完整的 attempt 历史列表
- 每次的参数、诊断结论、修复动作
- 提供"修改 text_normalized 并重试"的操作入口

## 类型定义

```typescript
export type StageName = "p1" | "p1c" | "p2" | "p2c" | "p2v" | "p5" | "p6" | "p6v";

export const STAGE_ORDER: readonly StageName[] = [
  "p1", "p1c", "p2", "p2c", "p2v", "p5", "p6", "p6v",
];

export type ChunkStatus = "pending" | "synth_done" | "verified" | "needs_review" | "failed";
```

## 实施阶段

### Phase 1: Stage 可见化
- P1c / P2c / P6v 拆为独立 stage 脚本
- 更新 StageName、STAGE_ORDER、StagePipeline、stage-info

### Phase 2: P2v 合并
- 新建 P2v，合并 ASR 转写 + 质量校验
- 产出 transcript.json + 校验报告
- 状态机新增 verified 状态

### Phase 3: 多维评估
- 音素距离比对（pypinyin）
- 静音段检测（ffmpeg silencedetect）
- WhisperX word.score 保留
- 加权评估框架

### Phase 4: 自动修复
- Runner 层 Repair 调度逻辑
- Level 0 / Level 1
- 状态机新增 retry_synth / needs_review
- UI attempt 历史

### Phase 5: 智能修复
- Level 2: 品牌名映射表 + LLM 辅助改写
- normalized_history 记录修改链
- UI needs_review 修改入口
