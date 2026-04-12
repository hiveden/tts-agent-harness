"""Unit tests for the P2v multi-dimensional scoring engine.

12 test cases covering all 5 scoring dimensions + integrated evaluate().
All tests are pure-function, no I/O or DB needed.
"""

from __future__ import annotations

import pytest

from server.core.p2v_scoring import (
    PASS_THRESHOLD,
    Diagnosis,
    VerifyScores,
    evaluate,
    score_asr_confidence,
    score_char_ratio,
    score_duration_ratio,
    score_phonetic_distance,
    score_silence,
)


# ---------------------------------------------------------------------------
# 1-3: duration_ratio
# ---------------------------------------------------------------------------


def test_duration_ratio_normal_speed():
    """Normal speech rate (5 chars/sec) -> high score."""
    # 30 chars in 6 seconds = 5 chars/sec, close to center 5.5
    score = score_duration_ratio(char_count=30, duration_s=6.0)
    assert score >= 0.9


def test_duration_ratio_too_fast():
    """Very fast speech (20 chars/sec) -> low score."""
    # 100 chars in 5 seconds = 20 chars/sec
    score = score_duration_ratio(char_count=100, duration_s=5.0)
    assert score < 0.5


def test_duration_ratio_too_slow():
    """Very slow speech (1 char/sec) -> low score."""
    # 5 chars in 5 seconds = 1 char/sec
    score = score_duration_ratio(char_count=5, duration_s=5.0)
    assert score < 0.5


# ---------------------------------------------------------------------------
# 4-5: silence
# ---------------------------------------------------------------------------


def test_silence_none():
    """No silence segments -> 1.0."""
    score = score_silence(duration_s=10.0, silence_segments=[])
    assert score == 1.0


def test_silence_long_internal():
    """Long internal silence -> low score."""
    segments = [
        {"start": 3.0, "end": 5.5, "duration": 2.5},  # 2.5s internal silence
    ]
    score = score_silence(duration_s=10.0, silence_segments=segments)
    assert score < 0.9


# ---------------------------------------------------------------------------
# 6-8: phonetic_distance
# ---------------------------------------------------------------------------


def test_phonetic_perfect_match():
    """Identical texts -> 1.0."""
    text = "Mac跑本地模型之前一直很尴尬"
    score = score_phonetic_distance(text, text)
    assert score == 1.0


def test_phonetic_chinese_homophone():
    """Chinese homophones (similar pinyin) -> high score.

    'Mac' transcribed as Chinese characters with similar sound should
    still score reasonably well via pinyin comparison.
    """
    original = "麦克风"
    transcribed = "麦克疯"  # same pinyin: mai ke feng
    score = score_phonetic_distance(original, transcribed)
    assert score >= 0.8


def test_phonetic_completely_different():
    """Completely different texts -> low score."""
    original = "人工智能技术发展"
    transcribed = "天气预报明天下雨"
    score = score_phonetic_distance(original, transcribed)
    assert score < 0.5


# ---------------------------------------------------------------------------
# 9-10: char_ratio
# ---------------------------------------------------------------------------


def test_char_ratio_perfect():
    """Ratio 1.0 -> 1.0."""
    original = "这是一段测试文本"
    score = score_char_ratio(original, original)
    assert score == 1.0


def test_char_ratio_half():
    """Ratio ~0.5 -> low score."""
    original = "这是一段测试文本十二个字的文本"
    transcribed = "这是一段测试"
    score = score_char_ratio(original, transcribed)
    assert score < 0.6


# ---------------------------------------------------------------------------
# 11: asr_confidence
# ---------------------------------------------------------------------------


def test_asr_confidence_all_high():
    """All high confidence scores -> high result."""
    words = [
        {"word": "你", "score": 0.95},
        {"word": "好", "score": 0.98},
        {"word": "世界", "score": 0.92},
    ]
    score = score_asr_confidence(words)
    assert score >= 0.9


# ---------------------------------------------------------------------------
# 12: evaluate (integration)
# ---------------------------------------------------------------------------


def test_evaluate_pass():
    """Good synthesis -> weighted score above threshold, verdict=pass."""
    original = "这是一段用于测试的中文文本"
    transcribed = "这是一段用于测试的中文文本"
    words = [
        {"word": "这", "score": 0.95},
        {"word": "是", "score": 0.92},
        {"word": "一", "score": 0.90},
        {"word": "段", "score": 0.93},
        {"word": "用于", "score": 0.91},
        {"word": "测试", "score": 0.94},
        {"word": "的", "score": 0.89},
        {"word": "中文", "score": 0.96},
        {"word": "文本", "score": 0.95},
    ]
    # 12 chars in ~2.2s = ~5.5 chars/sec (ideal)
    scores, diag = evaluate(
        original_text=original,
        transcribed_text=transcribed,
        words=words,
        duration_s=2.2,
        char_count=12,
        silence_segments=[],
    )
    assert isinstance(scores, VerifyScores)
    assert isinstance(diag, Diagnosis)
    assert scores.weighted_score >= PASS_THRESHOLD
    assert diag.verdict == "pass"


def test_evaluate_fail():
    """Bad synthesis -> weighted score below threshold, verdict=fail."""
    original = "人工智能技术在各个领域都有广泛应用"
    transcribed = "天气"  # completely wrong, very short
    words = [
        {"word": "天气", "score": 0.3},
    ]
    # 2 chars in 10s = 0.2 chars/sec (extremely slow for the transcription,
    # but char_count refers to original)
    scores, diag = evaluate(
        original_text=original,
        transcribed_text=transcribed,
        words=words,
        duration_s=10.0,
        char_count=15,
        silence_segments=[
            {"start": 2.0, "end": 5.0, "duration": 3.0},
            {"start": 6.0, "end": 8.0, "duration": 2.0},
        ],
    )
    assert scores.weighted_score < PASS_THRESHOLD
    assert diag.verdict == "fail"
    assert len(diag.missing) > 0  # many original words missing
