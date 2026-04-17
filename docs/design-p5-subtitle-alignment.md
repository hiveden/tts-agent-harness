# P5 字幕对齐优化：字符级贪心消费

## 问题描述

### 现状

P5 字幕对齐使用 `distribute_timestamps_with_words`，算法是**按字符数比例分配 word 给行**：

```
每行分到的 word 数 = round(该行字符权重 / 总字符权重 × 总 word 数)
```

### 为什么偏慢

用 CORE03-v3:shot01:1 实际数据说明：

| 字幕行 | 显示文本 | 去标点字符数 | 比例分配 word 数 |
|--------|---------|------------|----------------|
| 1 | 我用 OpenClaw | 10 | round(10/88 × 76) = **9** |
| 2 | 做了一个资讯推送。 | 8 | round(8/88 × 76) = 7 |

行 1 按比例拿到 9 个 word（我/用/Open/Cloud/**做/了/一个/咨/询**），时间窗口延伸到 1.72s。但实际 "OpenClaw" 在 0.84s 就说完了——**后面 5 个 word 本属于行 2，被行 1 吃掉了**。

根本原因：**"OpenClaw" 有 8 个显示字符但只占 2 个 transcript word**。比例分配按字符数给行 1 分了过多 word，导致所有后续行的时间窗口系统性后移。

### 影响范围

中英混合文本、控制标记密集的文本都会触发此问题。CORE03 全篇中英混合，每个 chunk 都受影响。

## 方案设计：字符级贪心消费

### 核心思路

不按比例分配，而是**逐行消费 transcript word 的字符**，当已消费的 word 字符数 >= 当前行的显示字符数时，该行结束，转下一行。

### 算法

```
输入：lines（字幕行列表），words（带时间戳的 word 列表），chunk_start
输出：每行的 (start, end)

word_cursor = 0
for each line (except last):
    target_chars = len(strip_punct(line))
    consumed_chars = 0
    first_word_idx = word_cursor

    while consumed_chars < target_chars and word_cursor < len(words):
        consumed_chars += len(words[word_cursor].word.strip())
        word_cursor += 1

    last_word_idx = word_cursor - 1
    start = words[first_word_idx].start - chunk_start
    end = words[last_word_idx].end - chunk_start

last line: 取所有剩余 words
```

### 用 shot01:1 验证

| 行 | 目标字符数 | 消费 word | 时间 | vs 当前 |
|----|-----------|-----------|------|---------|
| 1 "我用 OpenClaw" | 10 | 我(1)+用(1)+Open(4)+Cloud(5)=11 >= 10 → 4 words | 0.00-0.84 | 当前 0.00-1.70 |
| 2 "做了一个资讯推送。" | 8 | 做(1)+了(1)+一个(2)+咨(1)+询(1)+推(1)+送(1)=8 >= 8 → 7 words | 0.84-2.08 | 当前 1.70-3.06 |
| 3 "需求很简单——抓AI领域的热点，" | 13 | 需~点 = 13 chars → 12 words | 2.22-4.92 | 当前 3.06-5.78 |

每行都提前了约 0.8-1s，和实际语音对齐。

## 可行性分析

### 优势

- **改动极小**：只替换 `distribute_timestamps_with_words` 函数体，约 30 行代码
- **无外部依赖**：纯字符串操作，不需要 NLP 库或模糊匹配
- **向下兼容**：函数签名不变，P5 task 和 compose_srt 无需改动
- **不依赖文本相同**：不做内容匹配，只用字符数做消费计数，ASR 错字（"资讯" -> "咨询"）不影响

### 边界情况

| 情况 | 处理 |
|------|------|
| ASR 总字符 < 显示总字符 | 最后几行可能无 word → snap 到上一行 end（同当前逻辑） |
| ASR 总字符 > 显示总字符 | 最后一行取所有剩余 word（同当前逻辑） |
| 单行目标字符为 0 | 保底 target=1（同当前的 max(1, ...) 逻辑） |
| word_cursor 耗尽 | 剩余行 snap 到最后已知时间（同当前逻辑） |

### 风险

无。算法严格改进，不引入新依赖，不改数据模型。最坏情况退化为和当前比例分配接近的结果（当所有 word 都是单字符时两种算法等价）。

## 涉及文件

- `server/core/p5_logic.py` — `distribute_timestamps_with_words` 函数替换
- `server/tests/` — 对应单元测试更新
