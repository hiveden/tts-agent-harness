# TTS Harness 工程实践（四）：字幕对齐的三次错做与一次做对

> 项目：tts-agent-harness — 视频脚本转语音+字幕生产工具
> 时间跨度：2026-04-17（单日，追踪一个"字幕比语音慢"的 bug）
> 技术栈：FastAPI + Prefect + PostgreSQL + MinIO + Next.js 16 + WhisperX

---

## 一、问题

视频字幕工具里最基础的需求：**字幕显示时机要和语音对齐**。

用户反馈的体感：

> "spec-driven development——GitHub Spec-Kit、OpenSpec 三个连续的长英文词后，字幕还是慢了"
>
> "字幕到 GitHub 时，语音已经到了 用规格驱动"

这不是 edge case。在我们的项目里中英混合内容是常态（开发话题、技术雷达、工具名——ThoughtWorks、OpenSpec、GitHub、WuppieFuzz、cargo-mutants），**只要中英夹杂，字幕就会系统性地慢**。

底层的 pipeline 看起来没毛病：

```
chunk.text (原文) → P2 Fish TTS → WAV → P2v WhisperX ASR → transcript.json (带 word 时间戳)
                                                                      ↓
                                                               P5 compose_srt
                                                                      ↓
                                                              cue 列表 + SRT
```

字幕时间戳的来源是 ASR 的 word 时间。ASR 每个 word 的 start/end 是精确的（来自 wav2vec2 对齐）。**时间是对的**。那为什么字幕还慢？

---

## 二、错做一：贪心消费（算法层补丁）

我们打开 `p5_logic.py`，看到的是"按字符数比例分配 word"：

```python
每行 word 数 = round(该行字符权重 / 总字符权重 × 总 word 数)
```

一眼看出问题：中英字符密度不均。`OpenClaw` 有 8 个显示字符但 ASR 只听成 2 个 word (`Open` + `Cloud`)。按字符比例分，前面的行会被强行塞进去过多 word，后续行的时间窗口整体后移。

我们的第一反应是改算法——从"比例分配"换成"贪心消费"：

```python
for each line:
    consumed = 0
    while consumed < line_target_chars:
        consumed += len(next_word)
        cursor += 1
    start = first_word.start
    end = last_word.end
```

"消费到字符目标就停"——CORE03 数据上立竿见影，字幕前移 0.8–1s。我们写了 14 个测试覆盖各种场景，跑绿。

**然后用户给了 shot05:2 这条 chunk 验证，字幕还是慢。**

---

## 三、错做二：gap-aware 早停（魔数上贴魔数）

诊断数据：

```
原文:  agent 的规划和实现。反馈控制：动手后让 agent ...
ASR:   [ag][ent][规][划][和][实][现][反][馈]...
                                      ↑ ASR 漏了"的"字
```

贪心算法的"字符守恒"假设破产了——原文 11 个字符，ASR 只给了 10 个。游标被迫往后吃了 `反` 这个 word（属于下一句），行的 end 跳到 10.86 而不是该停在 10.02。字幕慢 ~0.4s。

我们的第二反应还是改算法：加一个**句末 gap 早停**：

```python
_SENTENCE_END_RE = r"[。？！.?!]"
_SENTENCE_BOUNDARY_GAP_S = 0.3

if line_ends_with_sentence_punct:
    if words[cursor].start - words[cursor-1].end >= 0.3:
        break  # 跨过句间静默，不继续吃
```

写测试，跑绿。重启 API，用户验证——shot05:2 修好了。

但是：

- 句末标点的字符集是写死的（中英日西阿语言的标点怎么办？）
- `0.3s` 是基于"WhisperX 中文 TTS 经验值"的魔数（换 TTS 模型怎么办？）
- 规则只在"行末是句末标点"时生效（`ThoughtWorks` 行末没有任何标点，防线形同虚设）

**每加一个魔数、每加一条 special case，都是一次警告。我们没听见。**

---

## 四、用户打断

用户丢过来一条 message：

> 检查代码。你是不是在写硬编码和死规则？

我们被迫把**所有硬编码列出来**。一列发现 17 条：

- A 级（范式错）：字符守恒假设 + 3 个魔数
- B 级（语言锁死）：`_DEFAULT_MAX_LINE_CHARS = 20`（中文习惯，换英文场景就不对）
- C 级（策略魔数）：`round(x, 3)`、`0.4 倍阈值`、"last line 吃剩余 words"…
- D 级（业务硬编码）：`displayMode === "subtitle" && edit?.subtitleText === undefined` 这种双条件

用户追问："是不是做了两件事？一件事是重构代码，一件是优化算法？"

我们把 session 内的改动按这两件事分：

| 维度 | 重构（契约层） | 算法（打补丁层） |
|---|---|---|
| 改动 | 前端消费后端 cues、抽屉展示真值 | 贪心消费 + gap-aware |
| 硬编码含量 | 低（字段约定） | 极高（魔数 + 语言 + 规则）|
| 架构正确性 | 正确 | 错的 |

**一次 session，把对的（契约重构）和错的（算法补丁）绑在一起提交了。**

> 第二件事（算法）：全部回退。按这个做。

我们 `git checkout HEAD -- server/core/p5_logic.py`，把贪心 + gap-aware 全部撤掉。契约重构保留。干净的 diff。

---

## 五、跳出循环：看数据

回退完，问题还在。用户抛出关键问题：

> ASR 从语音转出的带时间戳文本和原文本比对，有 80% 以上的匹配度吗？

这是前两次都没问的问题。我们埋头改算法，没看过数据的分布。

写 10 行 Python 跑 FLASH01-v2 的 14 个 chunk：

```
chunk                   orig  asr  ratio
shot01:1                111   110  95.0%
shot02:1                146   145  96.9%
shot02:2                 85    85 100.0%
shot03:1                123   121  92.6%
shot03:2                110   110 100.0%
shot03:3                 48    48 100.0%
shot04:1                 94    94  91.5%
shot04:2                126   126  99.2%
shot04:3                 77    79  98.7%
shot05:1                 99    99  93.9%
shot05:2                156   156  98.1%
shot05:3                 43    36  83.5%
shot06:1                 44    44  97.7%
shot07:1                 32    32  75.0%
平均: 94.1%  最低: 75.0%
```

`shot07:1` 为什么 75%？用户发现 ASR 给的是繁体：

```
原文: 完整版 pdf 五十多页 强烈建议 自己翻一遍 关注 工具人研究所 我们 下期见
ASR:  完整版 pdf 50 多頁 強烈建議 自己翻一遍 關注 工具人研究所 我們 下期見
```

Whisper 中文模型**默认倾向繁体输出**——这是已知问题，和听错无关，ASR 其实听对了。加一行 `zhconv.convert(..., "zh-cn")` 归一化后：

```
平均: 95.8%  最低: 83.5%  >90% 的 chunk: 13/14
```

**95.8%**。这一个数字改变了整个思考方向。

---

## 六、错做三：人工编辑 ASR（走错过的弯路也要诚实写下来）

既然 ASR 错字是问题根源，直觉反应是：**给用户一个界面编辑 ASR**，让他把 `Falseworks` 改回 `ThoughtWorks`，然后重跑 P5。

我们讨论了半天"编辑 ASR 的 UX 策略"——纯字符串编辑？chip UI？时间戳怎么处理？用户改字符串但 word 边界不变？

用户一句话打断：

> 字幕时间戳和字幕匹配规则是什么了吗？

我们又被迫停下来画匹配规则。画完发现：

- 字幕**显示**的是原文（不会显示 Falseworks）
- 字幕**时间戳**来自 ASR
- "编辑 ASR" 这件事从一开始就没对——用户从来不需要看到 Falseworks，需要的是 Falseworks 那段时间被**正确地归属给** ThoughtWorks 这 12 个原文字符。

**编辑 ASR 是 workaround 的 workaround**——绕过错的对齐算法，不是修它。

---

## 七、做对：字符锚定 + 插值

用户提出：

> 第一，优化 ASR 提高匹配率。第二，如果文字匹配到原文，说明百分百准确，将时间戳锚定到原文字幕。如果匹配不上，暂时跳过，按两次匹配到的原文的时间差平均分配给未匹配到的字符。

这**一句话就是正解**。我们评估后：

- 方案 1 优化 ASR：zhconv 归一化是纯 win（零成本，95.8% → 更高），`initial_prompt` 不做（会让 ASR 配合原文输出，破坏它的独立性 = 破坏锚点可信度）
- 方案 2 锚定 + 插值：这是 forced alignment 的**纯数据近似版**，不用声学模型，实现几十行

算法写出来是这样：

```python
def align_chars_to_timestamps(original, asr_words, chunk_start):
    # 1. 展开 ASR word → 字符流 + 每字符时间
    asr_chars, asr_times = expand_asr_to_chars(asr_words, chunk_start)

    # 2. 归一化（zhconv 简繁 + lower + strip 标点）
    orig_stream = [c for c in original if normalize(c)]
    asr_stream  = [c for c in asr_chars if normalize(c)]

    # 3. SequenceMatcher 找最长公共子序列
    anchors = SequenceMatcher(None, orig_stream, asr_stream).get_matching_blocks()

    # 4. 匹配字符 → 锚定 ASR 时间
    # 5. 未匹配字符 → 前后锚点线性插值
    return char_times
```

**唯一规则：匹配就锚定，不匹配就插值。**

对比：

| ASR 失败模式 | 老的贪心算法 | 新的锚定算法 |
|---|---|---|
| `ThoughtWorks → Falseworks` | 字符守恒假设破产，吃后续字符 | 英文区全部未匹配，被前后中文锚点夹着插值，不泄漏时间 |
| `的` 字漏听 | 游标越界 | 该字符无锚点，从左右邻居插值，自然落在 silence gap 内 |
| `资讯 → 咨询` | 勉强对 | 完美匹配（归一化层面看等价）|
| 繁简差异 | 降低匹配率 | 归一化消除 |
| 中英混合 | 按字符/word 比例强行分 | 字符级处理，不管比例 |

**没有硬编码**。不需要 `_SENTENCE_BOUNDARY_GAP_S`，不需要"句末标点触发"，不需要字符守恒假设，不需要 per-language special case。

**优雅退化**：ASR 完全崩盘（0 匹配）时，自动降级为"按字符数均分 chunk 时长"，等价于原始的 char-weighted 分配，不比现状差。

---

## 八、配套观测：Human 也要能看真值

算法只解决 95%。剩下 5% 是 TTS 本身发音有问题（ASR 听不出来是正常的），这时候人必须介入。

我们做了**⏱ 按钮**——chunk 级别的字幕时间微调面板。不是抽屉，抽屉是 stage 诊断；字幕微调是 chunk 级产物的编辑。

面板内容：

```
[cue 编辑表]
  [0] 0.00 → 2.02  "Agent Skills 把指令模块化、"
  [1] 2.02 → 3.00  "按需加载；"
  ...

[原文 vs ASR 对照]   ← 让人眼一秒看出 ASR 听成了什么
  原文: ThoughtWorks 在四月十五日发布了...
  ASR:  ThoughtWorks 在 4 月 15 日发布了...

[ASR 分词时间戳]（点击跳转播放）
  [ThoughtWorks 0.72] [在 0.84] [4 1.12] [月 1.22] ...
```

关键 UX：**修改的 cues 先在前端 state 里**，播放直接用新 cues 预览，不需要"保存 → 关面板 → 听 → 不对 → 再改"的慢循环。满意才写回 metadata + SRT。

**算法和观测同级设计**，不是"先做算法再补 UI"。

---

## 九、启示

### 9.1 识别"贴补丁" vs "换范式"

每次加一个魔数、加一条 special case，都是在地基坏的房子上再刷墙。我们在范式内绕了两圈（贪心、gap-aware）都没想过换范式。

**判断标准**：

- 新加的东西里有**阈值**（0.3、0.4、20）→ 大概率是补丁
- 新加的东西里有**触发条件枚举**（"行末是句末标点时才..."）→ 大概率是补丁
- 新规则只解决**特定数据**看到的问题→ 换个数据就坏 → 补丁

**换范式的信号**：

- 需要新加的 **假设**（字符守恒）
- 假设在一部分场景成立、一部分不成立 → 不是"优化假设"，是"这个假设不该有"

### 9.2 数据决策优先于算法选择

我们在**没看数据**的情况下写了两个算法。看了数据（95.8% 匹配率）才发现：

- 不需要声学模型做 forced alignment（精度冗余）
- 不需要编辑 ASR（95%+ 自动匹配）
- **简单字符对齐就够了**

数据推导了方案，方案反过来验证数据——这是对的顺序。反过来（先选方案，用数据合理化）容易翻车。

### 9.3 Agent 的思维陷阱

我们反复在**错的范式里更努力**——v1 比例分配换成 v2 贪心是改算法，v2 贪心加 gap-aware 也是改算法。两次都在同一个层次（字符数当桥）上优化。

Agent 擅长执行，不擅长质疑前提。用户的角色不是"比 Agent 更懂代码"，而是**站在上面一层强制打断**：

> "检查代码，你是不是在写硬编码？"
> "救你妈的急。"
> "你考虑当前 chunk 的时间戳和字幕匹配规则了吗？"

每一句都是把 Agent 从正在优化的局部拉回全局。**没有这些打断，我们会继续改算法直到它看起来不错但本质错误。**

### 9.4 "写在纸上" 是最低成本的反思机制

我们列 17 条硬编码清单那一刻，其实已经自己看到问题了——列举本身就是诊断。

类似的还有"当前匹配规则是什么"——我们一画图就发现字幕显示文字（原文）和字幕时间戳（ASR）是两个独立来源，"编辑 ASR"这个方向从匹配规则上看就是错的。

**在动手之前把目前的模型画出来**，比动手改快十倍。

### 9.5 分享的价值在过程不在算法

算法本身不值得分享——`SequenceMatcher` + 字符匹配 + 线性插值都是标准工具，我们只是组合起来。业界有大量更重、更精准的 forced alignment 方案（WhisperX、ctc-forced-aligner、NVIDIA NFA、Aeneas…），都是声学模型驱动。

**值得分享的是决策链**：
- 怎么识别补丁
- 怎么被用户推出错的循环
- 怎么用数据反向推导方案
- 怎么在精度 / 成本之间选一个"够用"的点

这篇文档的目的是——如果下一个人遇到同类问题，**至少知道别走我们走过的三次弯路**。

---

## 十、最终交付（2026-04-17）

4 个 commit，推到 `feat/concurrency-optimization`：

```
e822f53 docs: refresh CLAUDE.md + rewrite P5 alignment design doc
b4850f6 feat(ui): chunk-level subtitle timing editor with ASR reference
ed04cef feat(align): replace greedy + gap-aware P5 with character-level anchoring
ed4f97a chore(logs): add structured info log points to all pipeline stages
```

技术侧：
- `server/core/char_alignment.py` (新) — 锚定 + 插值
- `server/core/asr_normalize.py` (新) — zhconv 简繁 + strip 归一化
- `server/core/p5_logic.py` — 删除贪心 + gap-aware，接入新算法
- `web/components/SubtitleTimingEditor.tsx` (新) — 人工兜底 UI

新增依赖：`zhconv>=1.4`（纯 Python，< 1MB）。

算法代码：~100 行；删除的硬编码：2 个常量 + 1 套规则；测试：16 个单元测试 + shot05:2 真实数据回归。

**一天。从翻车到见底。**
