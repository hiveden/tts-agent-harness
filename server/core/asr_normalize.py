"""Normalization of text for ASR/script character alignment.

# 为什么要归一化

字符级对齐算法（char_alignment.py）通过匹配"原文字符 ↔ ASR 字符"来建立
时间锚点。如果两边的字符表示不一致，匹配率虚低，锚点太稀疏，插值误差变
大。常见的不一致源：

1. **繁简差异**：Whisper 中文模型（含 WhisperX 大模型）默认输出倾向繁体。
   "关注我们" vs "關注我們" —— 原文简体、ASR 繁体，每个字符都不匹配但
   语义完全一致。必须归一化。

2. **大小写**：ASR 可能大写开头（"ThoughtWorks"），原文可能用小写拼写
   （"thoughtworks"），或某些情况 ASR 全大写。统一小写规避。

3. **标点**：原文可能有 `，。、；：` 等，ASR 多数不输出。原文的控制标记
   `[break]/[pause]` 更是 ASR 完全没有。这些字符参与匹配会降低匹配率。

4. **空白**：原文的空格（"我用 OpenClaw"）和 ASR 的空格（word 边界导致
   的前导空格 " Development"）处理不一致。统一 strip。

# 为什么单独一个模块

`p5_logic.py` 已有 `strip_control_markers` 和 `_STRIP_PUNCT_RE`，但它们
是给"显示用"的（strip 后给用户看），保留了空格/大小写等视觉信息。对齐
用的归一化需要更激进（strip 全部空白 + 标点 + 简繁转换 + 小写），和显
示归一化分开避免互相影响。

也因此独立模块，对齐算法单元测试可以不依赖 p5_logic。
"""

from __future__ import annotations

import re

from zhconv import convert

# Matches any bracketed control marker: [break] [^tomato] [long break] ...
# Same pattern as p5_logic for consistency but duplicated intentionally — the
# alignment layer must not silently break if display-side marker semantics
# change in the future.
_BRACKET_RE = re.compile(r"\[[^\[\]]*\]")

# Match any whitespace, punctuation (CN + EN), zero-width chars, full-width
# space. Strip these entirely for alignment purposes — punctuation is not
# uttered and would lower the match ratio.
_STRIP_RE = re.compile(
    r"[\s，。、；：？！\u201c\u201d\u2018\u2019（）《》【】"
    r"\-—…·,.;:?!()\[\]{}\"'\/\\\u200b\u3000]"
)


def normalize_for_alignment(text: str) -> str:
    """Return a string ready for character-level comparison.

    The transformation chain:

    1. Drop ``[...]`` bracketed control markers entirely (not just whitespace
       replace — for alignment we want *shorter* strings that mirror what's
       actually spoken).
    2. Convert to simplified Chinese via ``zhconv.convert(..., "zh-cn")``.
       This is a character-level mapping, does not change string length.
    3. Lowercase. ``zh-cn`` output leaves ASCII alone; ``.lower()`` catches
       any Latin characters whose case differs.
    4. Strip all whitespace / punctuation / zero-width chars. Alignment
       cares about spoken characters only.

    Pure function, deterministic, O(n).
    """
    if not text:
        return ""
    cleaned = _BRACKET_RE.sub("", text)
    cleaned = convert(cleaned, "zh-cn")
    cleaned = cleaned.lower()
    cleaned = _STRIP_RE.sub("", cleaned)
    return cleaned


def normalize_char_stream(chars: list[str]) -> list[str]:
    """Normalize a **sequence of single characters** while preserving
    per-position correspondence with the input.

    ASR word lists arrive as multi-char tokens (``"Open"``, ``" Skills"``).
    After flattening to a char list we still need each *character* normalized
    individually so index mapping stays intact. Returns a list the same
    length as the input where each element is either:
    - the normalized single char (possibly empty string if it was punctuation
      / whitespace / a bracket char), or
    - the original char if normalization would change its length (should not
      happen with the current rules but guards future changes).

    The caller filters out empty-string elements to get the "alignment
    stream" while keeping a parallel array of original indices.
    """
    out: list[str] = []
    for c in chars:
        norm = normalize_for_alignment(c)
        # Single-char input must yield 0 or 1 chars out (all our rules are
        # per-char or pure deletions). If that invariant breaks we fail loudly
        # rather than silently misalign.
        if len(norm) > 1:
            raise ValueError(
                f"normalize_for_alignment altered char-length unexpectedly: "
                f"{c!r} -> {norm!r}"
            )
        out.append(norm)
    return out
