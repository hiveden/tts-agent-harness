"""Character-level time alignment between script text and ASR words.

# 问题

P5 的上游（P2v）给出 ASR word 列表 `[{word, start, end}]` —— 每个 word
都有精确时间戳，但 word 的**文字内容可能错**（长英文词被听成别的、漏字、
多字、繁简、语义混淆）。原文（chunks.text）是作者写的"真值文字"但
**没有时间戳**。

下游（字幕）需要"每行字幕的精确时间"。原先的做法（贪心消费 + gap-aware）
都基于"字符守恒假设"——原文字符数 ≈ ASR 字符数。中文场景这基本成立
(~95% 相似度)，但 ASR 一旦听错长英文词（ThoughtWorks→Falseworks）或漏
字（"的"），该假设破坏，后续所有时间戳误差累积。

# 思路

把"字幕时间戳来自 ASR"这件事细化到**单个字符**：

1. 把 ASR word 列表展开成"带时间戳的字符序列"，每个字符继承所属 word 的
   时间（word 内字符按位置均分 word 时长）。
2. 归一化原文和 ASR 字符序列（zhconv + lower + strip punct）。
3. 用 `difflib.SequenceMatcher` 找最长公共子序列式的匹配块。
4. **匹配的原文字符**继承对应 ASR 字符的时间戳（= 锚点）。
5. **未匹配的原文字符**在相邻锚点之间做**线性插值**——ASR 再错，前后
   字符如果能匹配上，中间错字的时间戳从前后"夹出来"还是大致正确的。
6. 边界：原文最前未匹配段用 chunk_start/0 做左锚；最末未匹配段用 chunk
   总时长/最后一个 ASR word.end 做右锚。

这是 forced alignment（用声学模型把原文强制对到音频）的**纯数据近似版**：
不需要额外模型，算法确定性，零新依赖（SequenceMatcher 是 Python 标准库）。

# 对比

| 方案 | ThoughtWorks→Falseworks | 的字漏了 | 中英混合 | 简繁 | 硬编码 |
|---|---|---|---|---|---|
| 贪心消费（旧） | ❌ 吃后续字符 | ❌ 越界 | ❌ 匀速比例 | ❌ | 多 |
| gap-aware（补丁）| ❌ 无帮助 | ⚠ 部分救场 | ❌ | ❌ | 0.3s 魔数+句末字符集 |
| 字符锚定（本模块）| ✅ 周围中文当锚 | ✅ 插值 | ✅ 字符级 | ✅ 归一化 | 无 |

# 接口形态

入参：
- ``original_text``: 原文字符串（已 strip 控制标记但**未归一化**，归一
  化在算法内部做以保持字符-位置对应）
- ``asr_words``: ASR word 列表，每个 ``{"word": str, "start": float,
  "end": float}``
- ``chunk_start``: chunk 在 ASR 时间轴上的起始偏移（通常 0，如果 ASR
  是对整段 episode 跑的话非 0）

返回：长度 = ``len(original_text)`` 的 ``list[tuple[float, float]]``，
每个元素是该字符的 ``(start, end)``，已做 chunk-relative 偏移。

# 极端情况退化

- 零匹配（ASR 完全不相关）：退化为"按原文字符数 / ASR 总时长均分"，和
  旧的 ``distribute_timestamps`` 等价——不比现状差。
- 零 ASR word：每个字符返回 ``(0, 0)``，上层决定如何兜底。
- 原文为空：返回 ``[]``。
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from server.core.asr_normalize import normalize_for_alignment


def _expand_asr_to_chars(
    asr_words: list[dict[str, Any]],
    chunk_start: float,
) -> tuple[list[str], list[tuple[float, float]]]:
    """Flatten ASR words into a parallel (char, (start, end)) stream.

    Each word's character times are derived by distributing the word's time
    span linearly across its characters. This is a necessary approximation
    (wav2vec2 could give true char-level times but we don't have that output
    on this path). Empty / whitespace-only words are dropped — they'd
    pollute the alignment with zero-width anchors.
    """
    chars: list[str] = []
    times: list[tuple[float, float]] = []
    for w in asr_words:
        token = w.get("word", "")
        start = w.get("start")
        end = w.get("end")
        if start is None or end is None:
            continue
        # Strip leading/trailing whitespace but keep internal chars intact
        # so per-char position maps cleanly to per-char time.
        t = token.strip()
        if not t:
            continue
        n = len(t)
        span = max(0.0, float(end) - float(start))
        for i, ch in enumerate(t):
            c_start = max(0.0, float(start) + (span * i / n) - chunk_start)
            c_end = max(0.0, float(start) + (span * (i + 1) / n) - chunk_start)
            chars.append(ch)
            times.append((c_start, c_end))
    return chars, times


def _find_anchors(
    original_chars: list[str],
    asr_chars: list[str],
) -> list[tuple[int, int]]:
    """Find character-level matches between original and ASR.

    Returns a list of ``(orig_idx, asr_idx)`` pairs for every matching
    character in the longest-common-subsequence sense. Both input lists
    are expected to already be normalized (lowercase, simplified Chinese,
    punctuation stripped) — we do that at the higher-level wrapper.

    Uses ``SequenceMatcher.get_matching_blocks()`` which returns
    ``(i, j, size)`` triples of matching runs. The trailing dummy
    ``(len_a, len_b, 0)`` is dropped naturally because ``size > 0``
    filter.
    """
    matcher = SequenceMatcher(None, original_chars, asr_chars, autojunk=False)
    anchors: list[tuple[int, int]] = []
    for orig_i, asr_i, size in matcher.get_matching_blocks():
        for k in range(size):
            anchors.append((orig_i + k, asr_i + k))
    return anchors


def _interpolate_gaps(
    char_times: list[tuple[float, float] | None],
    left_bound_start: float,
    right_bound_end: float,
) -> list[tuple[float, float]]:
    """Fill ``None`` entries by linear interpolation between neighbouring anchors.

    For each run of consecutive ``None`` entries:
    - The left anchor is the previous non-None ``(..., end)``; if no previous
      anchor exists, use ``left_bound_start`` (the chunk's open-side bound).
    - The right anchor is the next non-None ``(start, ...)``; if none,
      use ``right_bound_end``.
    - The run's characters divide the ``[left_end, right_start]`` interval
      into equal sub-intervals; each un-anchored char gets its own
      ``(start, end)`` slice.

    This preserves monotonicity by construction and never produces negative
    durations as long as anchor ordering is consistent (it is, because
    ``_find_anchors`` returns in sequence).
    """
    n = len(char_times)
    out: list[tuple[float, float]] = [(0.0, 0.0)] * n

    # Walk the list, detecting gaps.
    i = 0
    while i < n:
        if char_times[i] is not None:
            out[i] = char_times[i]  # type: ignore[assignment]
            i += 1
            continue

        # Gap starts at i. Find the extent [i, j).
        j = i
        while j < n and char_times[j] is None:
            j += 1

        # Left anchor: previous anchored char's end, or left_bound_start.
        left = left_bound_start
        if i > 0 and char_times[i - 1] is not None:
            left = char_times[i - 1][1]  # type: ignore[index]

        # Right anchor: next anchored char's start, or right_bound_end.
        right = right_bound_end
        if j < n and char_times[j] is not None:
            right = char_times[j][0]  # type: ignore[index]

        span = max(0.0, right - left)
        run_len = j - i
        # Distribute [left, right] across the un-anchored chars.
        # Each char gets a sub-interval of width span/run_len.
        width = span / run_len if run_len > 0 else 0.0
        for k in range(run_len):
            s = left + width * k
            e = left + width * (k + 1)
            out[i + k] = (s, e)

        i = j

    return out


def align_chars_to_timestamps(
    original_text: str,
    asr_words: list[dict[str, Any]],
    chunk_start: float = 0.0,
    chunk_total_duration: float | None = None,
) -> list[tuple[float, float]]:
    """Produce one ``(start, end)`` per original character.

    Returned list is the same length as ``original_text`` (pre-normalization)
    so downstream code (``split_subtitle_lines``-style logic that still
    works on the original characters) can index directly without worrying
    about normalized-index vs original-index drift.

    Algorithm:
    1. Expand ASR words into per-char stream with times.
    2. Normalize both streams char-by-char (preserves position).
    3. Drop normalized-to-empty chars from the alignment stream but keep a
       "position map" so anchors point back to original indices.
    4. Run SequenceMatcher, derive anchors.
    5. Apply anchor times to original chars (punct / whitespace originals
       that had no normalized counterpart inherit the nearest anchor via
       interpolation).
    6. Interpolate un-anchored original chars between anchors.
    7. Close open boundaries with chunk_start (left) and
       last-asr-char.end / chunk_total_duration (right).

    Examples (shot05:2 shape):
        original  = "agent 的规划和实现。"
        asr_words = [{word:"ag", start:8.58, end:8.94}, ...,
                     {word:"现", start:9.88, end:10.02},
                     {word:"反", start:10.46, end:10.86}, ...]

        Anchors will match "a","g","e","n","t","规","划","和","实","现"
        leaving "的" un-anchored (ASR dropped it) and ".，。" stripped.
        "的" then interpolates between "t".end and "规".start — landing
        in the silence gap between ``ent.end=9.00`` and ``规.start=9.00``
        which is ~0s here (no gap), so "的" gets near-zero duration.
        Crucially the next line's anchor "反"(10.46) is NOT consumed by
        this line — fixing the original "subtitle lag" bug structurally.
    """
    n_orig = len(original_text)
    if n_orig == 0:
        return []

    # 1. Expand ASR words to char stream.
    asr_chars_raw, asr_times_raw = _expand_asr_to_chars(asr_words, chunk_start)

    # If ASR is empty, degenerate: distribute original chars evenly over
    # the chunk duration if known, else all zeros.
    if not asr_chars_raw:
        if chunk_total_duration is None or chunk_total_duration <= 0:
            return [(0.0, 0.0)] * n_orig
        width = chunk_total_duration / n_orig
        return [(width * i, width * (i + 1)) for i in range(n_orig)]

    # 2+3. Normalize both streams char-by-char while keeping position maps.
    # orig_pos_map[i] = index in original_text of the i-th "alignment stream"
    # char. If a char normalizes to empty it doesn't appear in the stream.
    orig_stream: list[str] = []
    orig_pos_map: list[int] = []
    for i, c in enumerate(original_text):
        nc = normalize_for_alignment(c)
        if nc:
            orig_stream.append(nc)
            orig_pos_map.append(i)

    asr_stream: list[str] = []
    asr_times: list[tuple[float, float]] = []
    for c, t in zip(asr_chars_raw, asr_times_raw):
        nc = normalize_for_alignment(c)
        if nc:
            asr_stream.append(nc)
            asr_times.append(t)

    # 4. Find anchors on the normalized streams.
    stream_anchors = _find_anchors(orig_stream, asr_stream)

    # 5. Project anchor times back to original char positions.
    #    orig_char_times[k] = (s, e) from asr_times[asr_stream_idx], else None.
    orig_char_times: list[tuple[float, float] | None] = [None] * n_orig
    for stream_orig_idx, stream_asr_idx in stream_anchors:
        original_idx = orig_pos_map[stream_orig_idx]
        orig_char_times[original_idx] = asr_times[stream_asr_idx]

    # 6+7. Interpolate un-anchored chars.
    right_bound = (
        asr_times_raw[-1][1]
        if asr_times_raw
        else (chunk_total_duration if chunk_total_duration is not None else 0.0)
    )
    if chunk_total_duration is not None:
        # Prefer chunk_total_duration when it's larger — ASR might truncate
        # silence at the end that we still want to cover.
        right_bound = max(right_bound, float(chunk_total_duration))

    return _interpolate_gaps(
        orig_char_times,
        left_bound_start=0.0,
        right_bound_end=right_bound,
    )


__all__ = ["align_chars_to_timestamps"]
