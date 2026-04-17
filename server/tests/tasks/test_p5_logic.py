"""Unit tests for :mod:`server.core.p5_logic` — pure functions, no I/O."""

from __future__ import annotations

import math

import pytest

from server.core.p5_logic import (
    _format_ts,
    build_srt,
    compose_srt,
    distribute_timestamps,
    split_subtitle_lines,
    strip_control_markers,
)


# ---------------------------------------------------------------------------
# strip_control_markers
# ---------------------------------------------------------------------------


class TestStripControlMarkers:
    def test_break_marker(self) -> None:
        assert strip_control_markers("你好 [break] 世界") == "你好 世界"

    def test_long_break_marker(self) -> None:
        assert strip_control_markers("开头 [long break] 结尾") == "开头 结尾"

    def test_breath_marker(self) -> None:
        assert strip_control_markers("hello [breath] world") == "hello world"

    def test_phoneme_marker(self) -> None:
        assert strip_control_markers("我喜欢 [^tomato] 番茄") == "我喜欢 番茄"

    def test_mixed_markers(self) -> None:
        raw = "开场 [breath] 中段 [long break] 关键词 [^pronounce] 结尾。"
        assert strip_control_markers(raw) == "开场 中段 关键词 结尾。"

    def test_empty_input(self) -> None:
        assert strip_control_markers("") == ""
        assert strip_control_markers("   ") == ""

    def test_only_markers(self) -> None:
        # After stripping every bracketed token, only whitespace remains.
        assert strip_control_markers("[break][long break][^foo]") == ""

    def test_preserves_internal_spacing(self) -> None:
        # Single-space collapse, leading/trailing trim.
        assert strip_control_markers("  hello   world  ") == "hello world"


# ---------------------------------------------------------------------------
# split_subtitle_lines
# ---------------------------------------------------------------------------


class TestSplitSubtitleLines:
    def test_chinese_punctuation(self) -> None:
        text = "你好。世界？很好！"
        assert split_subtitle_lines(text) == ["你好。", "世界？", "很好！"]

    def test_english_punctuation(self) -> None:
        text = "Hello. World? Yes!"
        assert split_subtitle_lines(text) == ["Hello.", "World?", "Yes!"]

    def test_mixed_punctuation(self) -> None:
        text = "开头。This is English. 结尾！"
        assert split_subtitle_lines(text) == ["开头。", "This is English.", "结尾！"]

    def test_single_sentence_no_terminator(self) -> None:
        assert split_subtitle_lines("只有一句话没有标点") == ["只有一句话没有标点"]

    def test_empty_and_whitespace(self) -> None:
        assert split_subtitle_lines("") == []
        assert split_subtitle_lines("   \n  ") == []

    def test_explicit_newlines_split(self) -> None:
        # Authors can force cue breaks with literal newlines.
        text = "第一行\n第二行。第三行"
        assert split_subtitle_lines(text) == ["第一行", "第二行。", "第三行"]


# ---------------------------------------------------------------------------
# distribute_timestamps
# ---------------------------------------------------------------------------


class TestDistributeTimestamps:
    def test_single_line_fills_total(self) -> None:
        cues = distribute_timestamps(["只有一行话"], 3.0)
        assert len(cues) == 1
        assert cues[0] == (0.0, 3.0)

    def test_weighted_allocation(self) -> None:
        # 3 chars vs 6 chars vs 1 char → 10 chars total, duration 10s.
        # Shares: 0.3, 0.6, 0.1 → (0, 3), (3, 9), (9, 10).
        cues = distribute_timestamps(["aaa", "bbbbbb", "c"], 10.0)
        assert len(cues) == 3
        assert cues[0] == pytest.approx((0.0, 3.0))
        assert cues[1] == pytest.approx((3.0, 9.0))
        # Last cue snapped to total_duration.
        assert cues[2] == pytest.approx((9.0, 10.0))
        assert cues[2][1] == 10.0

    def test_back_to_back_no_gap(self) -> None:
        cues = distribute_timestamps(["a", "b", "c", "d"], 4.0)
        for prev, cur in zip(cues, cues[1:]):
            assert prev[1] == pytest.approx(cur[0])

    def test_empty_lines_returns_empty(self) -> None:
        assert distribute_timestamps([], 5.0) == []

    def test_zero_duration(self) -> None:
        cues = distribute_timestamps(["a", "b"], 0.0)
        assert cues == [(0.0, 0.0), (0.0, 0.0)]

    def test_negative_duration_treated_as_zero(self) -> None:
        cues = distribute_timestamps(["abc"], -1.0)
        assert cues == [(0.0, 0.0)]

    def test_determinism(self) -> None:
        args = (["hello", "world", "!"], 7.5)
        assert distribute_timestamps(*args) == distribute_timestamps(*args)

    def test_total_duration_never_exceeded(self) -> None:
        total = 5.0
        cues = distribute_timestamps(["one", "two", "three", "four"], total)
        assert cues[-1][1] == pytest.approx(total)
        assert all(end <= total + 1e-9 for _, end in cues)


# ---------------------------------------------------------------------------
# build_srt + _format_ts
# ---------------------------------------------------------------------------


class TestBuildSrt:
    def test_format_ts_zero_pad(self) -> None:
        assert _format_ts(0.0) == "00:00:00,000"

    def test_format_ts_sub_second(self) -> None:
        assert _format_ts(1.5) == "00:00:01,500"

    def test_format_ts_multi_hour(self) -> None:
        # 1h 2m 3.456s
        assert _format_ts(3723.456) == "01:02:03,456"

    def test_format_ts_rounding_carries(self) -> None:
        # 0.9996 s rounds to 1000 ms → 00:00:01,000
        assert _format_ts(0.9996) == "00:00:01,000"

    def test_format_ts_negative_clamps(self) -> None:
        assert _format_ts(-0.5) == "00:00:00,000"

    def test_build_srt_basic(self) -> None:
        cues = [
            (0.0, 1.5, "字幕第一行"),
            (1.5, 3.0, "字幕第二行"),
        ]
        expected = (
            "1\n"
            "00:00:00,000 --> 00:00:01,500\n"
            "字幕第一行\n"
            "\n"
            "2\n"
            "00:00:01,500 --> 00:00:03,000\n"
            "字幕第二行\n"
            "\n"
        )
        assert build_srt(cues) == expected

    def test_build_srt_empty(self) -> None:
        assert build_srt([]) == ""


# ---------------------------------------------------------------------------
# compose_srt — end-to-end pure path
# ---------------------------------------------------------------------------


class TestComposeSrt:
    def test_happy_path(self) -> None:
        text = "你好。世界！"
        srt, n, _cues = compose_srt(text, 4.0)
        assert n == 2
        assert srt.startswith("1\n00:00:00,000 --> ")
        assert "你好。" in srt
        assert "世界！" in srt

    def test_strips_markers_before_split(self) -> None:
        text = "开头。[break] 中段 [^tomato] 结尾！"
        srt, n, _cues = compose_srt(text, 6.0)
        assert n == 2  # [break] stripped → "开头。" + "中段 番茄-less 结尾！"
        assert "[break]" not in srt
        assert "[^tomato]" not in srt

    def test_all_markers_returns_empty(self) -> None:
        srt, n, cues = compose_srt("[break][long break]", 3.0)
        assert srt == ""
        assert n == 0
        assert cues == []

    def test_determinism(self) -> None:
        args = ("第一句话。第二句话！", 5.0)
        assert compose_srt(*args) == compose_srt(*args)

    def test_cues_shape_and_line_count_agree(self) -> None:
        """Cues is the same data the SRT encodes — exposed as structured
        JSON so the frontend can drive karaoke highlight without re-parsing
        the SRT. Shape / length are the contract the frontend relies on."""
        text = "你好。世界！"
        _srt, n, cues = compose_srt(text, 4.0)
        assert len(cues) == n
        for cue in cues:
            assert set(cue.keys()) == {"start", "end", "text"}
            assert isinstance(cue["start"], float)
            assert isinstance(cue["end"], float)
            assert isinstance(cue["text"], str)
