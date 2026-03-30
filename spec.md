# TTS Harness — 多 Agent 语音生产系统规范

## 概述

本文档定义了从脚本定稿到字幕输出的完整语音生产 harness，解决以下核心问题：

- 长文本直接进 TTS 导致部分调整需整条重做
- 语音错误（如 `-` 读成「减」）无法自动检测
- 语音与字幕对齐依赖手工校准

## 架构：三 Agent + 确定性胶水

```
脚本 (script.json)
  │
  ▼
┌─────────────── Harness (run.sh + chunks.json) ────────────────┐
│                                                                │
│  [P1]  确定性切分 (JS)        ── text → chunks.json           │
│  [P2]  Fish TTS Agent         ── text → speech (黑盒)         │
│  [✓2]  确定性预检             ── WAV 存在/时长/语速合理       │
│  [P3]  WhisperX Agent         ── speech → text + timestamps   │
│  [✓3]  确定性预检             ── JSON schema/字数比/时间戳    │
│  [P4]  Claude Agent           ── 校验 + 自动修复 (最多3轮)    │
│         └→ FAIL? → 改 text_normalized → P2 → P3 → P4         │
│  [P5]  确定性字幕 (JS)        ── timestamps → per-chunk subs  │
│  [P6]  确定性拼接 (JS)        ── concat + offset → final      │
│  [V2]  验收预览               ── HTML 播放+字幕高亮           │
│                                                                │
│  跨轮记忆: chunks.json status + trace.jsonl                    │
└────────────────────────────────────────────────────────────────┘
  │
  ▼
产物: per-shot WAV + subtitles.json + durations.json + preview.html
```

### Harness 四要素映射

| 要素 | 实现 |
|------|------|
| 操作对象 | `text_normalized` 字段（每轮只改这一个） |
| 评估函数 | 确定性预检（免费）+ Claude 语义校验（付费） |
| 约束系统 | prompt 定义错误分类规则 + 最大 3 轮重试 |
| 跨轮记忆 | `chunks.json` status + `validation/*_roundN.json` + `trace.jsonl` |

---

## 数据流与契约

### chunks.json — 状态机

```
pending → synth_done → transcribed → validated → (P5/P6 消费)
            │              │              │
       synth_failed   transcribe_failed  needs_human
                                    ↑
                              (P4 auto-retry:
                               改 text_normalized
                               → pending → synth_done → transcribed → 再校验)
```

### chunk 数据结构

```json
{
  "id": "shot02_chunk01",
  "shot_id": "shot02",
  "text": "原始文本（用于字幕显示）",
  "text_normalized": "TTS 输入文本（符号已替换）",
  "sentence_count": 3,
  "char_count": 120,
  "status": "pending",
  "duration_s": 0,
  "file": null,
  "validate_round": 0
}
```

### subtitles.json — Remotion 消费格式

```json
{
  "shot01": [
    { "id": "sub_001", "text": "原始脚本中的这句话", "start": 0.2, "end": 2.54 },
    { "id": "sub_002", "text": "下一句原始文本", "start": 2.54, "end": 4.72 }
  ],
  "shot02": [ ... ]
}
```

- `start` / `end`：浮点秒，精确到 3 位小数
- 字幕文本用 `text`（原始文稿），不用 `text_normalized` 或转写文本
- 时间戳已包含首部 padding 和 chunk 间 gap 的偏移

---

## P1 — 智能切分（确定性）

### 输入
`script.json`（按 segment/shot 组织的脚本）

### 切分规则

| 优先级 | 规则 | 说明 |
|--------|------|------|
| 1 | 以 shot 为一级单元 | 每个 shot 的 chunks 独立管理 |
| 2 | shot 内按句号/问号/感叹号/分号切分 | 句子级粒度 |
| 3 | 打包：每 chunk ≤ 5 句且 ≤ 200 字 | 控制 TTS 输入长度 |
| 4 | 最小片段保护：≥ 2 句 | 避免语气孤立 |
| 5 | 特殊符号预处理 | `-` → 到，`%` → 百分之，英文品牌名加断句 |

### 关键约束
- `text` 保留原始文稿（用于字幕显示）
- `text_normalized` 是实际送入 TTS 的文本
- 可逆性：`concat(chunks[].text) === 原始脚本`

---

## P2 — Fish TTS Agent

- 每个 chunk 独立调用 Fish TTS API（通过 ClashX 代理 127.0.0.1:7890）
- 并行度上限：3
- 使用 `text_normalized` 作为 TTS 输入
- 输出 `<chunk_id>.wav`（44100Hz，经 atempo 加速）
- 重试 3 次，指数退避

### Post-P2 确定性预检
- WAV 文件存在且时长 > 0 且 < 60s
- 语速合理（2-12 chars/sec）

---

## P3 — WhisperX Agent

- WhisperX large-v3，CPU 模式
- 输出 segment-level + word-level 时间戳
- 模型加载一次，批量处理所有 chunk
- 失败的 chunk 标记 `transcribe_failed` 并 exit(1)

### Post-P3 确定性预检
- JSON schema 合法
- 时间戳单调递增
- 转写字数 vs 原文字数偏差 < 30%

---

## P4 — Claude Agent（校验 + 自动修复循环）

通过 CLIProxyAPI (localhost:8317) 调用 Claude。

### 校验逻辑
将原始文稿、normalized 文本、转写结果三方比对。

### 自动修复循环（最多 3 轮）

```
Round 1: Claude 校验
  ├─ PASS → validated
  ├─ 只有 low severity → 自动放行
  └─ 有 high severity → Claude 生成 text_normalized 修改
      → 自动重跑 P2 → P3 → Round 2 校验
        └─ ... → Round 3 → 仍 FAIL → needs_human
```

### 错误分类

| 类型 | 说明 | severity |
|------|------|----------|
| misread | TTS 读错字 | high |
| missing | 原文有但语音缺失 | high |
| extra | 语音有但原文没有 | low |
| semantic_drift | 含义改变 | high |

**不算错误**：同音字替换、标点差异、语气词增减。

---

## P5 — 字幕生成（确定性）

- 复用 P3 WhisperX 的 segment 时间戳
- 字幕文本用原始文稿 `text`，按 ≤ 20 字/行 分行
- 输出 **per-chunk 相对时间戳**（从 0 开始）
- P6 负责全局偏移修正

---

## P6 — 音频拼接 + 字幕偏移修正（确定性）

### 拼接规则
- 首尾 padding：200ms 静音
- chunk 间：50ms 静音间隔
- 单 chunk shot：padding + audio + padding

### 字幕偏移计算
P6 根据实际拼接结构计算每个 chunk 的全局偏移：

```
chunk1 offset = PADDING_MS
chunk2 offset = PADDING_MS + chunk1_duration + GAP_MS
chunk3 offset = PADDING_MS + chunk1_duration + GAP_MS + chunk2_duration + GAP_MS
...
```

### 输出
- `<shot>.wav` — per-shot 拼接音频
- `durations.json` — per-shot 时长
- 回写 `subtitles.json`（偏移已修正）

---

## 可观测性

### trace.jsonl
每个 Agent 阶段写一行结构化 JSONL：

```jsonl
{"ts":"2026-03-30T10:00:01Z","chunk":"shot02_chunk01","phase":"p2","event":"start"}
{"ts":"2026-03-30T10:00:14Z","chunk":"shot02_chunk01","phase":"p2","event":"done","duration_ms":13200}
```

运行结束后自动输出摘要：per-phase 耗时、P4 平均轮次、错误统计。

---

## 人工验收节点

| 节点 | 时机 | 内容 |
|------|------|------|
| V1 | P4 之后 | 终端输出校验摘要，needs_human 的 chunk 需人工听音频 |
| V2 | P6 之后 | HTML 预览页，播放音频同时高亮字幕，确认同步 |

---

## 文件结构

```
tts-harness/
├── run.sh                    # Harness 调度
├── spec.md                   # 本文档
├── requirements.txt          # Python 依赖
├── .venv/                    # Python 3.11 + whisperx + torch
├── scripts/
│   ├── p1-chunk.js           # 确定性切分
│   ├── p2-synth.js           # Fish TTS Agent
│   ├── p3-transcribe.py      # WhisperX Agent
│   ├── p4-validate.js        # Claude Agent（校验+修复循环）
│   ├── p5-subtitles.js       # 确定性字幕
│   ├── p6-concat.js          # 确定性拼接
│   ├── precheck.js           # 确定性预检（Post-P2/P3）
│   ├── trace.js              # JSONL trace 工具
│   └── v2-preview.js         # HTML 验收预览
└── .work/<episode>/          # 中间产物（不进 public）
    ├── chunks.json
    ├── audio/<chunk>.wav
    ├── transcripts/<chunk>.json
    ├── validation/<chunk>_roundN.json
    ├── subtitles.json
    ├── trace.jsonl
    └── preview.html
```

---

## 运行方式

```bash
# 完整运行
bash tts-harness/run.sh script/brief01-script.json brief01

# 从某步继续
bash tts-harness/run.sh script/brief01-script.json brief01 --from p3

# 重做单个 chunk（P4 自动修复循环内部使用）
node tts-harness/scripts/p2-synth.js --chunks ... --outdir ... --chunk shot02_chunk01
```

---

## 异常处理

| 场景 | 处理 |
|------|------|
| Fish TTS 超时 | 重试 3 次，指数退避 |
| WhisperX 时间戳异常 | 确定性预检拦截，不进入 P4 |
| Claude 校验 3 轮仍不过 | 标记 needs_human |
| 音频采样率不一致 | P6 拼接前 `-ar 44100` 统一 |
| 连续失败 | 确定性预检 exit(1) 中断流水线 |
