# AB 参数测试 — Fish TTS temperature / top_p 对英文发音的影响

## 目标

验证 Fish Audio TTS (S2-Pro) 的采样参数 `temperature` 和 `top_p` 是否影响中文语境中英文关键词的发音准确度，找出最优参数组合。

## 背景

Fish TTS 在中文文本中遇到英文品牌名/缩写（Mac、Ollama、RAG）时，发音不稳定——同一文本多次合成可能读法不同。我们假设降低 temperature/top_p 可以减少随机性，提高英文关键词发音的一致性和准确度。

## 测试设计

### 测试文本

取自 brief02 segment 1 的 tts_text（含 3 个英文关键词）：

> Mac 跑本地模型，之前一直很尴尬。装了 Ollama，跑个小模型还行，大一点的慢得受不了，玩两下就吃灰了。最近我在做一个 RAG 项目，需要大量跑测试，重新研究了一下，发现情况变了。

### 参数组

| 组 | temperature | top_p | 预期 |
|----|-------------|-------|------|
| A_default | 0.7 | 0.7 | Fish 默认值，发音变化最大 |
| B_mid | 0.3 | 0.5 | 中等约束 |
| C_low | 0.2 | 0.3 | 强约束，预期最稳定 |

每组合成 3 次（`run1.wav` ~ `run3.wav`），共 9 个样本。

### 关键词 & 期望发音

| 关键词 | 上下文定位 | 期望拼音（中文读法） |
|--------|-----------|---------------------|
| Mac | 句首 ~ "跑本地" | mai ke（麦克） |
| Ollama | "装了" ~ "跑个小" | ou la ma（欧拉玛） |
| RAG | "一个" ~ "项目" | rui ge（瑞格） |

## 验证方法

### 流程

```
WAV → WhisperX ASR 转写 → 定位关键词区域（上下文匹配） → 三路判定
```

### 三路判定逻辑

1. **ASR 转出英文且完全匹配** → `exact_match`，score = 1.0
2. **ASR 转出英文但不匹配** → 字符编辑距离（归一化），`char_distance`
3. **ASR 转出中文谐音** → pypinyin 转拼音 → 与期望拼音比编辑距离，`pinyin`

### 阈值

| 路径 | 阈值 | 含义 |
|------|------|------|
| char_distance | < 0.34 | 字符距离 / max(len1, len2) |
| pinyin | < 0.40 | 拼音距离 / max(len1, len2) |

> **已知问题**：当前阈值偏松，存在假通过（如 "卖个" 通过 Mac、"欧罗麦" 通过 Ollama）。需要根据实际样本进一步收紧。

## 运行

```bash
# 步骤 1：合成（需要 FISH_TTS_KEY）
set -a && source .env && set +a && bash test/ab-param-test/ab-synth.sh

# 步骤 2：验证（需要 WhisperX + pypinyin）
bash test/ab-param-test/ab-verify.sh
```

### 依赖

- Fish TTS API key（`.env` 中的 `FISH_TTS_KEY`）
- ffmpeg / ffprobe
- Python 3 + whisperx + pypinyin
- jq

### 产物

```
test/ab-param-test/output/
├── A_default/
│   ├── run1.wav ~ run3.wav
├── B_mid/
│   ├── run1.wav ~ run3.wav
├── C_low/
│   ├── run1.wav ~ run3.wav
├── results.csv              ← 合成时长 & 延迟
└── verify-results.json      ← 关键词判定详情
```

## 待解决

- [ ] 收紧阈值，减少假通过
- [ ] 验证 Fish TTS API 是否真正使用 temperature/top_p 参数（用极端值 0.01 vs 0.99 对比）
- [ ] 如果参数无效，考虑其他调优手段（prompt engineering、reference_id 等）

## 文件说明

| 文件 | 作用 |
|------|------|
| `ab-synth.sh` | 步骤 1：调用 Fish TTS API 合成音频 |
| `ab-verify.sh` | 步骤 2：wrapper，调用 ab-verify.py |
| `ab-verify.py` | 步骤 2：WhisperX 转写 + 关键词发音验证逻辑 |
| `README.md` | 本文档 |
