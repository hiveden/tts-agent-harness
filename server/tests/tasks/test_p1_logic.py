"""Unit tests for ``server.core.p1_logic``.

Everything tested here is pure (no DB, no MinIO, no Prefect), so the suite
runs in a few milliseconds and is the source of truth for the P1 product
rules. Integration-level concerns (DB persistence, event emission, episode
state transitions) live in ``test_p1_task.py``.
"""

from __future__ import annotations

import pytest

from server.core.p1_logic import (
    compute_boundary_hash,
    script_to_chunks,
    split_segment_into_sentences,
)


# ---------------------------------------------------------------------------
# split_segment_into_sentences
# ---------------------------------------------------------------------------


def test_split_single_segment_multiple_sentences() -> None:
    text = "你好世界。今天天气不错！我们出发吧？"
    assert split_segment_into_sentences(text) == [
        "你好世界。",
        "今天天气不错！",
        "我们出发吧？",
    ]


def test_split_trailing_fragment_without_terminator() -> None:
    # A sentence missing a terminator should still be kept as the tail.
    assert split_segment_into_sentences("你好。世界") == ["你好。", "世界"]


def test_split_mixed_cjk_and_ascii_punctuation() -> None:
    text = "Hello world. 你好! Is this working? 是的。"
    # "Hello world." uses an ASCII period which is NOT in our terminator set
    # (periods are ambiguous in mixed-script text: "v1.2" shouldn't split).
    # So the first sentence only breaks at the Chinese "!" / "?".
    assert split_segment_into_sentences(text) == [
        "Hello world. 你好!",
        " Is this working?",
        " 是的。",
    ]


def test_split_preserves_control_markers() -> None:
    # [break], [breath], [long break] and phoneme markers are TTS engine
    # directives; they must not be treated as sentence boundaries and must
    # survive into chunk.text verbatim.
    text = "大家好[break]我是主播。今天[long break]我们聊聊 AI。"
    parts = split_segment_into_sentences(text)
    assert parts == ["大家好[break]我是主播。", "今天[long break]我们聊聊 AI。"]
    assert "[break]" in parts[0]
    assert "[long break]" in parts[1]


def test_split_empty_and_whitespace() -> None:
    assert split_segment_into_sentences("") == []
    assert split_segment_into_sentences("   ") == []
    assert split_segment_into_sentences("\n\n") == []


# ---------------------------------------------------------------------------
# compute_boundary_hash
# ---------------------------------------------------------------------------


def test_boundary_hash_is_deterministic() -> None:
    h1 = compute_boundary_hash("shot01", 1, "你好。")
    h2 = compute_boundary_hash("shot01", 1, "你好。")
    assert h1 == h2
    assert len(h1) == 16
    assert all(c in "0123456789abcdef" for c in h1)


def test_boundary_hash_changes_when_text_changes() -> None:
    h1 = compute_boundary_hash("shot01", 1, "你好。")
    h2 = compute_boundary_hash("shot01", 1, "你好！")
    h3 = compute_boundary_hash("shot01", 2, "你好。")
    h4 = compute_boundary_hash("shot02", 1, "你好。")
    assert len({h1, h2, h3, h4}) == 4


# ---------------------------------------------------------------------------
# script_to_chunks
# ---------------------------------------------------------------------------


def test_script_numeric_id_becomes_zero_padded_shot() -> None:
    script = {
        "title": "demo",
        "segments": [
            {"id": 1, "type": "hook", "text": "你好。"},
            {"id": 2, "type": "content", "text": "世界！"},
            {"id": 10, "type": "cta", "text": "再见。"},
        ],
    }
    chunks = script_to_chunks(script, "ep-x")
    assert [c.shot_id for c in chunks] == ["shot01", "shot02", "shot10"]
    assert [c.id for c in chunks] == [
        "ep-x:shot01:1",
        "ep-x:shot02:1",
        "ep-x:shot10:1",
    ]


def test_script_string_id_used_verbatim() -> None:
    script = {
        "segments": [
            {"id": "shot42", "type": "hook", "text": "你好。"},
            {"id": "hook-a", "type": "hook", "text": "再见。"},
        ],
    }
    chunks = script_to_chunks(script, "ep")
    assert [c.shot_id for c in chunks] == ["shot42", "hook-a"]


def test_script_splits_segment_into_multiple_chunks() -> None:
    script = {
        "segments": [
            {
                "id": 1,
                "type": "content",
                "text": "第一句。第二句！第三句？",
            }
        ]
    }
    # max_chunk_chars=0 disables grouping → legacy per-sentence behaviour
    chunks = script_to_chunks(script, "ep", max_chunk_chars=0)
    assert len(chunks) == 3
    assert [c.idx for c in chunks] == [1, 2, 3]
    assert [c.id for c in chunks] == [
        "ep:shot01:1",
        "ep:shot01:2",
        "ep:shot01:3",
    ]
    assert chunks[0].text == "第一句。"
    assert chunks[0].text_normalized == "第一句。"
    assert chunks[0].char_count == len("第一句。")


def test_script_ignores_empty_and_whitespace_segments() -> None:
    script = {
        "segments": [
            {"id": 1, "text": ""},
            {"id": 2, "text": "   \n  "},
            {"id": 3, "text": "实际内容。"},
        ]
    }
    chunks = script_to_chunks(script, "ep")
    assert len(chunks) == 1
    assert chunks[0].shot_id == "shot03"
    assert chunks[0].text_normalized == "实际内容。"


def test_script_long_paragraph_splits_into_ordered_chunks() -> None:
    paragraph = (
        "开场白一。开场白二。开场白三！开场白四？"
        "开场白五。开场白六。"
    )
    script = {"segments": [{"id": 1, "text": paragraph}]}
    chunks = script_to_chunks(script, "ep", max_chunk_chars=0)
    assert len(chunks) == 6
    assert [c.idx for c in chunks] == [1, 2, 3, 4, 5, 6]
    # Each chunk inside a shot gets a monotonically increasing idx and all
    # share the same shot_id.
    assert {c.shot_id for c in chunks} == {"shot01"}


def test_script_preserves_control_markers_in_text_but_not_as_splits() -> None:
    script = {
        "segments": [
            {"id": 1, "text": "开场[break]白。[breath]正文[long break]结束！"}
        ]
    }
    chunks = script_to_chunks(script, "ep", max_chunk_chars=0)
    assert len(chunks) == 2
    assert chunks[0].text == "开场[break]白。"
    assert chunks[1].text == "[breath]正文[long break]结束！"
    # text_normalized is just trim, so leading whitespace is stripped but
    # control markers are preserved.
    assert "[breath]" in chunks[1].text_normalized
    assert "[long break]" in chunks[1].text_normalized


def test_script_empty_segments_produces_empty_chunks() -> None:
    assert script_to_chunks({"title": "t", "segments": []}, "ep") == []
    assert script_to_chunks({}, "ep") == []


def test_script_boundary_hash_is_deterministic_and_unique() -> None:
    script = {
        "segments": [
            {"id": 1, "text": "你好。世界！"},
            {"id": 2, "text": "你好。"},
        ]
    }
    a = script_to_chunks(script, "ep-abc", max_chunk_chars=0)
    b = script_to_chunks(script, "ep-abc", max_chunk_chars=0)
    # Deterministic: two calls return byte-identical hashes.
    assert [c.boundary_hash for c in a] == [c.boundary_hash for c in b]
    # Unique per (shot, idx, text) tuple within the episode.
    hashes = [c.boundary_hash for c in a]
    assert len(hashes) == 3
    assert len(set(hashes)) == 3


def test_script_mixed_punctuation_chunk_fields() -> None:
    script = {
        "segments": [
            {"id": 1, "type": "hook", "text": "Hello 世界! Is this OK? 好的。"}
        ]
    }
    chunks = script_to_chunks(script, "ep", max_chunk_chars=0)
    assert len(chunks) == 3
    # char_count uses len(text_normalized) — i.e. unicode code points, not
    # bytes, which is the right thing for a Chinese-first product.
    assert chunks[0].char_count == len(chunks[0].text_normalized)
    # Metadata carries segment type so downstream (optional) consumers can
    # treat hook vs content differently without re-parsing the script.
    assert chunks[0].metadata == {"segment_type": "hook"}


# ---------------------------------------------------------------------------
# Sentence grouping (max_chunk_chars)
# ---------------------------------------------------------------------------


def test_grouping_merges_short_sentences() -> None:
    """Adjacent sentences under max_chunk_chars are merged into one chunk."""
    script = {
        "segments": [{"id": 1, "text": "第一句。第二句！第三句？"}]
    }
    # Total text is 12 chars — fits in one group with limit=200
    chunks = script_to_chunks(script, "ep", max_chunk_chars=200)
    assert len(chunks) == 1
    assert chunks[0].text == "第一句。第二句！第三句？"
    assert chunks[0].idx == 1


def test_grouping_splits_at_limit() -> None:
    """When adding next sentence exceeds limit, start a new group."""
    script = {
        "segments": [{"id": 1, "text": "第一句。第二句！第三句？"}]
    }
    # Each sentence is 4 chars. Limit=8 allows 2 per group.
    # Group 1: "第一句。"(4) + "第二句！"(4) = 8 ≤ 8 → merge
    # Group 2: "第三句？"(4) alone
    chunks = script_to_chunks(script, "ep", max_chunk_chars=8)
    assert len(chunks) == 2
    assert chunks[0].text == "第一句。第二句！"
    assert chunks[1].text == "第三句？"


def test_grouping_single_long_sentence_never_split() -> None:
    """A sentence exceeding max_chunk_chars is kept whole."""
    script = {
        "segments": [{"id": 1, "text": "这是一个超长的句子不会被切割。短句。"}]
    }
    chunks = script_to_chunks(script, "ep", max_chunk_chars=5)
    assert len(chunks) == 2
    assert chunks[0].text == "这是一个超长的句子不会被切割。"
    assert chunks[1].text == "短句。"


def test_grouping_zero_disables() -> None:
    """max_chunk_chars=0 gives legacy per-sentence behavior."""
    script = {
        "segments": [{"id": 1, "text": "一。二。三。"}]
    }
    chunks = script_to_chunks(script, "ep", max_chunk_chars=0)
    assert len(chunks) == 3


def test_grouping_default_merges_typical_script() -> None:
    """Default 200-char limit merges a typical shot into 1-2 chunks."""
    # Simulate a shot with ~100 chars total
    text = "这是第一句话。" * 5 + "结尾。"  # ~43 chars
    script = {"segments": [{"id": 1, "text": text}]}
    chunks = script_to_chunks(script, "ep")  # default max_chunk_chars=200
    assert len(chunks) == 1


def test_grouping_respects_shot_boundary() -> None:
    """Groups never cross shot boundaries."""
    script = {
        "segments": [
            {"id": 1, "text": "A句。B句。"},
            {"id": 2, "text": "C句。D句。"},
        ]
    }
    chunks = script_to_chunks(script, "ep", max_chunk_chars=9999)
    assert len(chunks) == 2
    assert chunks[0].shot_id == "shot01"
    assert chunks[1].shot_id == "shot02"


def test_script_rejects_unknown_id_type() -> None:
    with pytest.raises(ValueError):
        script_to_chunks({"segments": [{"id": 1.5, "text": "x。"}]}, "ep")


def test_script_rejects_bool_id() -> None:
    # bool is a subclass of int in Python — guard explicitly so that True
    # doesn't silently become "shot01".
    with pytest.raises(ValueError):
        script_to_chunks({"segments": [{"id": True, "text": "x。"}]}, "ep")
