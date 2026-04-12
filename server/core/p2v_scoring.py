"""P2v 多维评估引擎 -- 确定性信号为主，模型信号为辅

纯函数模块，不依赖 DB/MinIO/Prefect。所有评估函数接收已提取的数据，
返回 0-1 范围的分数（1.0 = 最优）。

五个维度：
  1. duration_ratio  — 时长/字数比合理性
  2. silence         — 静音异常检测
  3. phonetic_distance — 音素距离（pypinyin + levenshtein）
  4. char_ratio      — 字符比
  5. asr_confidence  — ASR 词级置信度均值
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict

from pypinyin import pinyin, Style


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class VerifyScores:
    duration_ratio: float      # 时长/字数比合理性 (0-1)
    silence: float             # 静音异常检测 (0-1)
    phonetic_distance: float   # 音素距离 (0-1)
    char_ratio: float          # 字符比 (0-1)
    asr_confidence: float      # ASR 词级置信度均值 (0-1)
    weighted_score: float      # 加权综合分 (0-1)


@dataclass
class Diagnosis:
    verdict: str               # "pass" | "fail"
    type: str | None           # "word_mismatch" | "word_missing" | "speed_anomaly" | None
    missing: list[str]         # 原文有但转写没有的词
    extra: list[str]           # 转写有但原文没有的词
    low_confidence_words: list[str]  # score < 0.5 的词


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WEIGHTS = {
    "duration_ratio": 0.25,
    "silence": 0.20,
    "phonetic_distance": 0.25,
    "char_ratio": 0.15,
    "asr_confidence": 0.15,
}

PASS_THRESHOLD = 0.70

# 中文合理语速范围 (字/秒)
_SPEED_MIN = 3.0
_SPEED_MAX = 8.0
_SPEED_CENTER = (_SPEED_MIN + _SPEED_MAX) / 2  # 5.5


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

_PUNCT_RE = re.compile(
    r"[\s\u3000"
    r"\u3001-\u3003\u3008-\u3011\u3014-\u301F"  # CJK punctuation
    r"\uFF01-\uFF0F\uFF1A-\uFF20\uFF3B-\uFF40\uFF5B-\uFF65"  # fullwidth
    r"!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~"  # ASCII punctuation
    r"]"
)

_CONTROL_TAG_RE = re.compile(
    r"\[(?:break|breath|long break)\]"
    r"|<phoneme[^>]*>[^<]*</phoneme>"
    r"|\{[^}]*\}",
    re.IGNORECASE,
)


def _strip_control_tags(text: str) -> str:
    """Remove TTS control tags ([break], phoneme, etc.)."""
    return _CONTROL_TAG_RE.sub("", text)


def _strip_punct(text: str) -> str:
    """Remove all punctuation and whitespace."""
    return _PUNCT_RE.sub("", text)


def _is_chinese_char(c: str) -> bool:
    """Check if a character is CJK unified ideograph."""
    return "\u4e00" <= c <= "\u9fff"


def _split_cn_en(text: str) -> tuple[str, str]:
    """Split text into Chinese characters and English words."""
    clean = _strip_punct(_strip_control_tags(text))
    cn_chars = []
    en_parts = []
    en_buf: list[str] = []
    for c in clean:
        if _is_chinese_char(c):
            cn_chars.append(c)
            if en_buf:
                en_parts.append("".join(en_buf))
                en_buf.clear()
        elif c.isascii() and c.isalpha():
            en_buf.append(c)
        else:
            if en_buf:
                en_parts.append("".join(en_buf))
                en_buf.clear()
    if en_buf:
        en_parts.append("".join(en_buf))
    return "".join(cn_chars), " ".join(en_parts).lower()


# ---------------------------------------------------------------------------
# Levenshtein
# ---------------------------------------------------------------------------


def _levenshtein(s1: str, s2: str) -> int:
    """Standard edit distance."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for c1 in s1:
        curr = [prev[0] + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (c1 != c2)))
        prev = curr
    return prev[-1]


def _normalized_distance(s1: str, s2: str) -> float:
    """Normalized edit distance (0-1), 0 = identical."""
    max_len = max(len(s1), len(s2))
    if max_len == 0:
        return 0.0
    return _levenshtein(s1, s2) / max_len


def _to_pinyin_str(text: str) -> str:
    """Convert Chinese text to pinyin string (no tones, space separated)."""
    result = pinyin(text, style=Style.NORMAL)
    return " ".join(p[0] for p in result)


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------


def score_duration_ratio(char_count: int, duration_s: float) -> float:
    """Evaluate speech rate reasonableness.

    Reasonable Chinese speech rate: 3-8 chars/sec, center at 5.5.
    Returns 1.0 if within range, degrades as it deviates.
    """
    if duration_s <= 0 or char_count <= 0:
        return 0.0
    chars_per_sec = char_count / duration_s
    return max(0.0, 1.0 - min(1.0, abs(chars_per_sec - _SPEED_CENTER) / _SPEED_CENTER))


def score_silence(
    duration_s: float,
    silence_segments: list[dict],
) -> float:
    """Detect abnormal silence.

    Deductions:
      - Internal silence segment > 1.0s (not head/tail) -> penalty
      - Total silence ratio > 30% -> penalty
    Returns 1.0 if no anomalies.
    """
    if duration_s <= 0:
        return 0.0
    if not silence_segments:
        return 1.0

    score = 1.0
    total_silence = 0.0
    HEAD_MARGIN = 0.1   # segments starting within 0.1s of start are "head"
    TAIL_MARGIN = 0.1   # segments ending within 0.1s of end are "tail"

    for seg in silence_segments:
        seg_start = seg.get("start", 0.0)
        seg_end = seg.get("end", 0.0)
        seg_dur = seg.get("duration", seg_end - seg_start)
        total_silence += seg_dur

        # Check if internal (not head or tail)
        is_head = seg_start < HEAD_MARGIN
        is_tail = seg_end > duration_s - TAIL_MARGIN
        if not is_head and not is_tail and seg_dur > 1.0:
            # Penalty proportional to how long the silence is
            penalty = min(0.3, (seg_dur - 1.0) * 0.15)
            score -= penalty

    # Total silence ratio check
    silence_ratio = total_silence / duration_s
    if silence_ratio > 0.3:
        score -= min(0.4, (silence_ratio - 0.3) * 2.0)

    return max(0.0, score)


def score_phonetic_distance(original: str, transcribed: str) -> float:
    """Compute phonetic similarity between original and transcribed text.

    - Chinese portions: compare via pypinyin
    - English portions: direct character edit distance
    Returns 1.0 for perfect match, 0.0 for completely different.
    """
    orig_cn, orig_en = _split_cn_en(original)
    trans_cn, trans_en = _split_cn_en(transcribed)

    distances: list[float] = []
    lengths: list[int] = []

    # Chinese: pinyin comparison
    if orig_cn or trans_cn:
        orig_py = _to_pinyin_str(orig_cn) if orig_cn else ""
        trans_py = _to_pinyin_str(trans_cn) if trans_cn else ""
        dist = _normalized_distance(orig_py, trans_py)
        weight = max(len(orig_cn), len(trans_cn))
        distances.append(dist * weight)
        lengths.append(weight)

    # English: character comparison
    if orig_en or trans_en:
        dist = _normalized_distance(orig_en, trans_en)
        weight = max(len(orig_en), len(trans_en))
        distances.append(dist * weight)
        lengths.append(weight)

    if not lengths:
        return 1.0

    total_weight = sum(lengths)
    if total_weight == 0:
        return 1.0

    weighted_dist = sum(distances) / total_weight
    return max(0.0, 1.0 - weighted_dist)


def score_char_ratio(original: str, transcribed: str) -> float:
    """Character count ratio score.

    Ratio in [0.8, 1.2] -> 1.0. Degrades as it deviates further.
    """
    orig_clean = _strip_punct(_strip_control_tags(original))
    trans_clean = _strip_punct(_strip_control_tags(transcribed))

    orig_len = len(orig_clean)
    trans_len = len(trans_clean)

    if orig_len == 0:
        return 1.0 if trans_len == 0 else 0.0

    ratio = trans_len / orig_len

    if 0.8 <= ratio <= 1.2:
        return 1.0

    # How far outside the acceptable range
    if ratio < 0.8:
        deviation = 0.8 - ratio
    else:
        deviation = ratio - 1.2

    return max(0.0, 1.0 - deviation * 2.0)


def score_asr_confidence(words: list[dict]) -> float:
    """Mean ASR word-level confidence.

    Each word dict should have a ``score`` field (0-1).
    Words without a score are treated as 0.5.
    """
    if not words:
        return 0.5

    total = 0.0
    for w in words:
        s = w.get("score")
        total += s if s is not None else 0.5
    return total / len(words)


# ---------------------------------------------------------------------------
# Diagnosis helpers
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """Simple tokenization: each Chinese char is a token, English words are tokens."""
    clean = _strip_punct(_strip_control_tags(text))
    tokens: list[str] = []
    en_buf: list[str] = []
    for c in clean:
        if _is_chinese_char(c):
            if en_buf:
                tokens.append("".join(en_buf).lower())
                en_buf.clear()
            tokens.append(c)
        elif c.isascii() and c.isalpha():
            en_buf.append(c)
        else:
            if en_buf:
                tokens.append("".join(en_buf).lower())
                en_buf.clear()
    if en_buf:
        tokens.append("".join(en_buf).lower())
    return tokens


def _build_diagnosis(
    original: str,
    transcribed: str,
    words: list[dict],
    scores: VerifyScores,
) -> Diagnosis:
    """Analyze differences to produce a diagnosis."""
    orig_tokens = set(_tokenize(original))
    trans_tokens = set(_tokenize(transcribed))

    missing = sorted(orig_tokens - trans_tokens)
    extra = sorted(trans_tokens - orig_tokens)

    low_conf = []
    for w in words:
        s = w.get("score")
        word_text = w.get("word", "")
        if s is not None and s < 0.5 and word_text.strip():
            low_conf.append(word_text.strip())

    # Determine type
    diag_type: str | None = None
    if scores.duration_ratio < 0.5:
        diag_type = "speed_anomaly"
    elif missing:
        diag_type = "word_missing"
    elif extra or low_conf:
        diag_type = "word_mismatch"

    verdict = "pass" if scores.weighted_score >= PASS_THRESHOLD else "fail"

    return Diagnosis(
        verdict=verdict,
        type=diag_type,
        missing=missing,
        extra=extra,
        low_confidence_words=low_conf,
    )


# ---------------------------------------------------------------------------
# Main evaluate
# ---------------------------------------------------------------------------


def evaluate(
    original_text: str,
    transcribed_text: str,
    words: list[dict],
    duration_s: float,
    char_count: int,
    silence_segments: list[dict],
) -> tuple[VerifyScores, Diagnosis]:
    """Run all 5 scoring dimensions and produce a weighted verdict.

    Returns (VerifyScores, Diagnosis) tuple.
    """
    s_duration = score_duration_ratio(char_count, duration_s)
    s_silence = score_silence(duration_s, silence_segments)
    s_phonetic = score_phonetic_distance(original_text, transcribed_text)
    s_char = score_char_ratio(original_text, transcribed_text)
    s_asr = score_asr_confidence(words)

    weighted = (
        s_duration * WEIGHTS["duration_ratio"]
        + s_silence * WEIGHTS["silence"]
        + s_phonetic * WEIGHTS["phonetic_distance"]
        + s_char * WEIGHTS["char_ratio"]
        + s_asr * WEIGHTS["asr_confidence"]
    )

    scores = VerifyScores(
        duration_ratio=round(s_duration, 4),
        silence=round(s_silence, 4),
        phonetic_distance=round(s_phonetic, 4),
        char_ratio=round(s_char, 4),
        asr_confidence=round(s_asr, 4),
        weighted_score=round(weighted, 4),
    )

    diagnosis = _build_diagnosis(original_text, transcribed_text, words, scores)

    return scores, diagnosis


def scores_to_dict(scores: VerifyScores) -> dict:
    """Serialize VerifyScores to dict."""
    return asdict(scores)


def diagnosis_to_dict(diagnosis: Diagnosis) -> dict:
    """Serialize Diagnosis to dict."""
    return asdict(diagnosis)


__all__ = [
    "VerifyScores",
    "Diagnosis",
    "WEIGHTS",
    "PASS_THRESHOLD",
    "score_duration_ratio",
    "score_silence",
    "score_phonetic_distance",
    "score_char_ratio",
    "score_asr_confidence",
    "evaluate",
    "scores_to_dict",
    "diagnosis_to_dict",
]
