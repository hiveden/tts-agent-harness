"""Tests for character-level ASR-to-script alignment."""

from __future__ import annotations

import pytest

from server.core.char_alignment import align_chars_to_timestamps
from server.core.asr_normalize import normalize_for_alignment


# ---------------------------------------------------------------------------
# Normalization smoke tests (keep align algorithm assumptions explicit)
# ---------------------------------------------------------------------------


def test_normalize_strips_control_markers() -> None:
    assert normalize_for_alignment("你好 [break] 世界") == "你好世界"


def test_normalize_converts_traditional_to_simplified() -> None:
    # Traditional 頁 -> 简 页, 們 -> 们
    assert normalize_for_alignment("我們建議翻頁") == "我们建议翻页"


def test_normalize_lowercases_ascii() -> None:
    assert normalize_for_alignment("ThoughtWorks") == "thoughtworks"


def test_normalize_strips_punct_whitespace() -> None:
    assert normalize_for_alignment("hello, world! 你好。") == "helloworld你好"


# ---------------------------------------------------------------------------
# align_chars_to_timestamps — core algorithm
# ---------------------------------------------------------------------------


def _w(word: str, start: float, end: float) -> dict:
    return {"word": word, "start": start, "end": end}


def test_empty_original_returns_empty() -> None:
    assert align_chars_to_timestamps("", [_w("a", 0, 1)], 0.0) == []


def test_empty_asr_distributes_evenly_when_total_duration_known() -> None:
    times = align_chars_to_timestamps("abcd", [], 0.0, chunk_total_duration=4.0)
    # Even distribution across 4s.
    assert times == [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0), (3.0, 4.0)]


def test_empty_asr_all_zeros_when_no_duration() -> None:
    times = align_chars_to_timestamps("abcd", [], 0.0)
    assert times == [(0.0, 0.0)] * 4


def test_perfect_match_anchors_every_char() -> None:
    """Every script char has an ASR counterpart → all anchored, no interpolation."""
    original = "你好"
    words = [_w("你", 0.0, 0.3), _w("好", 0.3, 0.6)]
    times = align_chars_to_timestamps(original, words, 0.0)
    assert len(times) == 2
    assert times[0] == pytest.approx((0.0, 0.3))
    assert times[1] == pytest.approx((0.3, 0.6))


def test_multi_char_asr_word_splits_time_evenly_per_char() -> None:
    """ASR word 'Open' spanning 0.4-0.6s → each char gets 0.05s."""
    original = "open"
    words = [_w("Open", 0.4, 0.6)]
    times = align_chars_to_timestamps(original, words, 0.0)
    assert len(times) == 4
    # O: 0.40-0.45, p: 0.45-0.50, e: 0.50-0.55, n: 0.55-0.60
    assert times[0] == pytest.approx((0.4, 0.45))
    assert times[3] == pytest.approx((0.55, 0.60))


def test_shot05_dropped_character_does_not_leak_to_next_sentence() -> None:
    """The canonical FLASH01-v2:shot05:2 regression.

    Script:   "agent 的规划和实现。"         (10 displayable chars incl. '的')
    ASR:      [ag][ent][规][划][和][实][现][反]...
              — ASR *dropped* "的" (weak-stressed particle) and the next
              utterance ("反馈控制") starts after a pause at 10.46s.

    Old greedy algorithm: char count mismatch → consumes "反" to fill the
    shortfall → line end = 10.86 (into the next sentence) → subsequent
    subtitles all lag by ~0.4s.

    New algorithm: "的" has no ASR counterpart → interpolated between
    anchors "t" (ASR 'ent'.end≈9.00) and "规" (ASR '规'.start=9.00). Result:
    "的" lands in the 0s gap between those anchors. Crucially "反" is NOT
    consumed — the line ends at "现".end=10.02 naturally.
    """
    # Script text (strip control markers already done upstream).
    original = "agent的规划和实现"  # strip punctuation + space; what p5 passes
    words = [
        _w("ag", 8.58, 8.94),
        _w("ent", 8.94, 9.00),
        _w("规", 9.00, 9.32),
        _w("划", 9.32, 9.46),
        _w("和", 9.46, 9.70),
        _w("实", 9.70, 9.88),
        _w("现", 9.88, 10.02),
        # Next utterance starts here — must NOT be consumed:
        _w("反", 10.46, 10.86),
        _w("馈", 10.86, 10.92),
    ]
    times = align_chars_to_timestamps(original, words, 0.0)
    assert len(times) == len(original)

    # First char 'a' anchored to ASR 'ag' first char → 8.58.
    assert times[0][0] == pytest.approx(8.58, abs=0.01)
    # Last char '现' anchored to ASR '现' → ends at 10.02. This is the
    # structural fix: previously greedy would have ended past "反".
    assert times[-1][1] == pytest.approx(10.02, abs=0.01)
    # Entire alignment stays within [first_asr.start, last_matched_asr.end].
    # '反' must NOT appear in any timestamp.
    for s, e in times:
        assert s <= 10.10, f"alignment leaked past 现.end: {s=}"
        assert e <= 10.10, f"alignment leaked past 现.end: {e=}"


def test_english_asr_mishearing_recovered_by_anchor_context() -> None:
    """ASR: 'Falseworks' when script says 'ThoughtWorks'. Zero chars match
    (t,h,o,u,g != F,a,l,s,e). The WHOLE English region is un-anchored.
    But the surrounding Chinese *does* anchor, so the English region's
    time is bracketed by those anchors and linearly interpolated across.

    Net effect: ThoughtWorks gets the time span Falseworks occupied —
    same as before — but any trailing time doesn't spill over because
    the next Chinese char anchors cleanly.
    """
    original = "ThoughtWorks在4月"  # ASR 会听成 Falseworks 在 4 月
    words = [
        # Falseworks mishearing — split weirdly as ASR usually does.
        _w("Fa", 0.00, 0.20),
        _w("lse", 0.20, 0.30),
        _w("works", 0.30, 0.60),
        # Chinese chars ASR gets right:
        _w("在", 0.60, 0.84),
        _w("4", 0.84, 1.12),
        _w("月", 1.12, 1.22),
    ]
    times = align_chars_to_timestamps(original, words, 0.0)
    assert len(times) == len(original)

    # '在' is a reliable anchor — must land at ASR '在'.start.
    zai_idx = original.index("在")
    assert times[zai_idx][0] == pytest.approx(0.60, abs=0.01)

    # '月' also anchored.
    yue_idx = original.index("月")
    assert times[yue_idx][1] == pytest.approx(1.22, abs=0.02)

    # All ThoughtWorks chars (indices 0..11) land *before* '在' anchor.
    for i in range(zai_idx):
        assert times[i][1] <= 0.61, f"char {i}={original[i]!r} leaked past 在"


def test_traditional_asr_matches_simplified_script() -> None:
    """ASR outputs 繁体 but script is 简体. Normalization must bridge them
    so every char anchors."""
    original = "关注我们"  # simplified
    words = [
        _w("關", 0.0, 0.2),
        _w("注", 0.2, 0.4),
        _w("我", 0.4, 0.6),
        _w("們", 0.6, 0.8),
    ]
    times = align_chars_to_timestamps(original, words, 0.0)
    # All 4 chars should be anchored — no interpolation needed.
    assert times[0] == pytest.approx((0.0, 0.2))
    assert times[1] == pytest.approx((0.2, 0.4))
    assert times[2] == pytest.approx((0.4, 0.6))
    assert times[3] == pytest.approx((0.6, 0.8))


def test_chunk_start_offset_applied() -> None:
    """ASR is on the absolute episode timeline. Chunk-relative times must
    subtract chunk_start."""
    original = "你好"
    words = [_w("你", 10.0, 10.3), _w("好", 10.3, 10.6)]
    times = align_chars_to_timestamps(original, words, chunk_start=10.0)
    assert times[0] == pytest.approx((0.0, 0.3))
    assert times[1] == pytest.approx((0.3, 0.6))


def test_interpolation_spans_gap_between_anchors() -> None:
    """Two anchors with a 0.6s gap between them; 3 un-anchored chars
    inside → each gets 0.2s."""
    # Script: 'a的的的b'. ASR only says 'a'(0-0.1) and 'b'(0.7-0.8).
    original = "a的的的b"
    words = [_w("a", 0.0, 0.1), _w("b", 0.7, 0.8)]
    times = align_chars_to_timestamps(original, words, 0.0)
    assert len(times) == 5
    # 'a' anchored.
    assert times[0] == pytest.approx((0.0, 0.1))
    # 3x '的' share the 0.6s gap [0.1, 0.7].
    assert times[1][0] == pytest.approx(0.1, abs=0.01)
    assert times[1][1] == pytest.approx(0.3, abs=0.01)
    assert times[2] == pytest.approx((0.3, 0.5), abs=0.01)
    assert times[3] == pytest.approx((0.5, 0.7), abs=0.01)
    # 'b' anchored.
    assert times[4] == pytest.approx((0.7, 0.8))


def test_monotonic_start_times() -> None:
    """Regardless of gaps / mis-hearings, start times must be monotonic
    non-decreasing. This is a safety invariant used by downstream cue
    building."""
    original = "开头 和 Falseworks 结尾。"
    words = [
        _w("开", 0.00, 0.15),
        _w("头", 0.15, 0.30),
        _w("和", 0.30, 0.50),
        _w("F", 0.50, 0.60),
        _w("al", 0.60, 0.70),
        _w("se", 0.70, 0.80),
        _w("works", 0.80, 1.00),
        _w("结", 1.00, 1.20),
        _w("尾", 1.20, 1.40),
    ]
    times = align_chars_to_timestamps(original, words, 0.0)
    for i in range(1, len(times)):
        assert times[i][0] >= times[i - 1][0] - 1e-6, (
            f"start times not monotonic at idx {i}: "
            f"{times[i-1]} then {times[i]}"
        )


def test_length_preserved_for_original_text() -> None:
    """Length invariant: output has exactly len(original_text) entries."""
    original = "The quick brown 狐狸 jumped 过了 lazy dog"
    words = [_w(w, float(i), float(i) + 0.5) for i, w in enumerate(original.split())]
    times = align_chars_to_timestamps(original, words, 0.0)
    assert len(times) == len(original)
