# P5 字幕对齐：字符级锚定 + 插值

## 问题

P5 要给每行字幕打上时间戳 `(start, end)`，依赖 P2v 给出的 ASR word 列表 `[{word, start, end}]`。ASR 的时间戳是精确的（来自 WhisperX + wav2vec2 对齐），但**文字可能错**——中英混合、长英文词、繁简、弱读字的漏听都会让 ASR 输出和原文字符不一致。

实际数据（FLASH01-v2 14 个 chunk 实测）：
- 平均字符相似度 **95.8%**（简繁归一化后）
- 最低 83.5%（生僻专有名词 `cargo-mutants`、`WuppieFuzz` 等）
- ASR 典型错法：`ThoughtWorks → Falseworks`、`OpenClaw → Open Cloud`、`资讯 → 咨询`、"的"字丢失、简体输入→繁体输出

## 算法演进

### v1（历史）：按字符数比例分配

```
每行分到的 word 数 = round(该行字符权重 / 总字符权重 × 总 word 数)
```

假设：原文字符数 ≈ ASR 字符数。中英混合时破产：`OpenClaw`（8 字符）对应 ASR 只有 `Open`+`Cloud`（2 word），按字符比例强行分配过多 word 到前面行，后续时间窗口系统性后移。

### v2（已废弃）：贪心消费 + gap-aware 早停

v1 的改进——逐行消费 word 字符到达行目标字符数即停，加上"句末标点 + 0.3s gap"的早停规则挽救 ASR 漏字场景。

问题：
- 引入硬编码 `_SENTENCE_END_RE`、`_SENTENCE_BOUNDARY_GAP_S = 0.3`
- 只在"行末是句末标点"时救场，其它场景（如 `ThoughtWorks` 行不带标点）防线不开
- 字符守恒假设仍是地基，ASR 一错就塌
- **方向错误：在错的范式上打补丁**

v2 被完整回退，教训见 commit ed04cef。

### v3（当前）：字符级锚定 + 插值

单一规则：**匹配就锚定，不匹配就插值**。

```
1. 展开 ASR word 列表成字符流，每个字符继承 word 时长均分
2. 归一化原文和 ASR 字符（zhconv t2s + lower + strip 标点/空白）
3. SequenceMatcher.get_matching_blocks() 找最长公共子序列匹配
4. 匹配字符: 继承对应 ASR 字符的时间戳（= 锚点）
5. 未匹配字符: 从左右锚点线性插值
6. 边界: 开头无锚点用 0;结尾无锚点用 chunk_total_duration
```

## 为什么字符级锚定正确

**统一算法替代一堆规则**。对每种 ASR 失败模式都自然处理：

| ASR 失败模式 | 字符锚定的表现 |
|---|---|
| ASR 错字（Thought→False） | 英文区 0 匹配，周围中文锚点夹着插值；不会泄漏时间到下一句 |
| ASR 漏字（"的"） | 该字符无锚点，从左右邻居插值，时间落在自然 gap 内 |
| ASR 多字（幻觉） | 多出的 ASR 字符未被匹配，不占用原文字符时间 |
| 繁简差异 | 归一化层统一简体，匹配率恢复 |
| 中英混合 | 字符级处理，不依赖字符和 word 的数量比例 |

**无硬编码**：
- 没有"0.3s 阈值"
- 没有"句末标点触发"
- 没有字符守恒假设
- 没有 per-language special case

**优雅退化**：ASR 完全不相关（0 匹配）时，退化为"按字符数均分 chunk 时长"——等价于原始 `distribute_timestamps`，不比现状差。

## 数据流

```
script.json (作者原文)
         ↓
chunks.text (含控制标记 [break]/[pause])
         ↓ strip_control_markers
display text (纯文本)
         ↓ split_subtitle_lines  →  lines = ["行1", "行2", ...]
         ↓
"".join(lines)  ← 作为对齐的原文字符序列
         ↓
align_chars_to_timestamps(original, asr_words, chunk_start)
         ↓
每字符 (start, end) 列表
         ↓ 按 lines 切段
每行 cue (start, end, text)
         ↓
SRT + metadata.subtitle_cues
```

## 归一化规则

`server/core/asr_normalize.py::normalize_for_alignment`：

1. 去除 `[...]` 控制标记（包括 `[^phoneme]`）
2. `zhconv.convert(..., "zh-cn")` — 繁→简
3. `.lower()` — ASCII 小写
4. 去除所有标点 / 空白 / 零宽字符 / 全角空格

只用于对齐比对，**不影响显示**。显示文本走 `strip_control_markers`（保留空格、换行、大小写）。两套归一化分层，避免互相影响。

## 边界情况

| 情况 | 处理 |
|---|---|
| 原文为空 | 返回 `[]` |
| ASR 为空，知道总时长 | 按字符数均分时长 |
| ASR 为空，不知总时长 | 每字符 `(0.0, 0.0)`，上层决定兜底 |
| 开头未匹配 | 左锚点 = 0.0 |
| 结尾未匹配 | 右锚点 = max(最后 ASR word.end, chunk_total_duration) |
| 零匹配（极端差异） | 退化为按字符数均分 |

## 观测

`SequenceMatcher.ratio()` 给出整体字符匹配度。结合每字符是"锚点"还是"插值"可进一步统计覆盖率。未来如需质量指标落地到 `chunks.metadata.align_quality`，数据来源都现成。

## 相关文件

- `server/core/char_alignment.py` — 对齐算法核心
- `server/core/asr_normalize.py` — 归一化（zhconv + strip）
- `server/core/p5_logic.py::distribute_timestamps_with_words` — 对接层（30 行 shim）
- `server/tests/tasks/test_char_alignment.py` — 16 个单元测试
- `web/components/SubtitleTimingEditor.tsx` — 极端 case 的人工兜底 UI

## 兜底：人工微调

95%+ 场景自动对齐足够准。剩余极端 case（低匹配率、TTS 合成错误）通过 chunk 行的 ⏱ 按钮打开 `SubtitleTimingEditor` 面板手动微调：
- 查看原文 vs ASR 对照
- 点击 ASR word 跳音频到该位置试听
- 手动改 cue 的 start/end
- 本地预览（不保存也能通过 chunk 播放器试听）
- 保存 → 覆盖 `chunks.metadata.subtitle_cues` + 重生成 SRT

流程见 `web/components/SubtitleTimingEditor.tsx` 头部注释。
