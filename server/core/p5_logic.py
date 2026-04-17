"""Pure logic for P5 subtitle assignment.

This module has **zero I/O**: no database, no object storage, no Prefect,
no HTTP. It only transforms strings and numbers, which makes it trivially
unit-testable and — more importantly — **deterministic**.

Pipeline (all driven by callers):

1. ``strip_control_markers(text)``                — remove S2-Pro control markers
2. ``split_subtitle_lines(display, max_chars)``   — smart line splitting
3. ``distribute_timestamps(lines, T)``            — char-weighted fallback
   ``distribute_timestamps_with_words(lines, words, chunk_start)``
                                                   — word-level alignment (primary)
4. ``build_srt(cues)``                            — serialize to SRT wire format

The algorithm is documented inline because the "why" matters more than the
"what" for future maintainers.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# 1. Strip S2-Pro control markers
# ---------------------------------------------------------------------------

# Known named pause / breath markers that Fish S2-Pro recognises.
# Anything inside square brackets that matches one of these is dropped.
_NAMED_MARKERS = {
    "break",
    "long break",
    "short break",
    "breath",
    "sigh",
    "laugh",
    "cough",
    "pause",
}

# Matches **any** bracketed token of the form [...] or [^...].
# We deliberately use a greedy strip: bracketed tokens are never part of
# displayable subtitle text in our authoring convention.
_BRACKET_RE = re.compile(r"\[[^\[\]]*\]")


def strip_control_markers(text: str) -> str:
    """Remove S2-Pro control markers from ``text``.

    Stripped tokens:

    - Named pauses: ``[break]``, ``[long break]``, ``[breath]``, ``[sigh]`` ...
    - Phoneme overrides: ``[^tomato]``, ``[^hello]`` ...
    - Any other ``[...]`` bracketed token — authoring convention forbids
      literal square brackets in displayable text, so this is safe.

    The function also collapses the whitespace created by removed markers:
    ``"你好 [break] 世界"`` → ``"你好 世界"`` (single internal space preserved).

    Empty / all-marker input returns an empty string.
    """
    if not text:
        return ""
    stripped = _BRACKET_RE.sub(" ", text)
    # Collapse runs of spaces/tabs but preserve explicit newlines so that
    # split_subtitle_lines() can still honour author-provided breaks.
    stripped = re.sub(r"[ \t]+", " ", stripped)
    # Trim whitespace at line boundaries.
    stripped = re.sub(r" *\n *", "\n", stripped)
    return stripped.strip()


# Keep the marker set public for test visibility.
STRIPPABLE_MARKERS = frozenset(_NAMED_MARKERS)


# ---------------------------------------------------------------------------
# 2. Split into subtitle lines (smart, ported from JS p5-subtitles.js)
# ---------------------------------------------------------------------------

# Split at sentence-ending AND clause-ending punctuation (commas, enumeration
# commas, semicolons). The terminator stays attached to the preceding text.
_SPLIT_RE = re.compile(r"(?<=[。？！，、；,])")

# For detecting "pure punctuation" lines that should merge into the previous.
_STRIP_PUNCT_RE = re.compile(
    r"[\s，。、；：？！\u201c\u201d\u2018\u2019（）《》【】\-—…·,.;:?!()\[\]{}\"\'/\\\u200b\u3000]"
)

_DEFAULT_MAX_LINE_CHARS = 20


def _is_chinese(c: str) -> bool:
    return "\u4e00" <= c <= "\u9fff"


def split_subtitle_lines(
    display_text: str,
    max_line_chars: int = _DEFAULT_MAX_LINE_CHARS,
) -> list[str]:
    """Split display-ready text into subtitle lines (one per SRT cue).

    Ported from the original JS ``splitSubtitleLines`` with identical
    semantics:

    - Split on sentence-ending **and** clause-ending punctuation (commas,
      enumeration commas, semicolons) — not just full stops.
    - Short consecutive parts are merged when they fit within
      *max_line_chars* (buffer accumulation).
    - Oversized parts are broken intelligently:
      1. Prefer space boundaries.
      2. Fall back to Chinese/Latin script boundaries.
      3. Never split an English word.
    - Pure-punctuation lines are merged into the preceding line.
    - Hard newlines still act as forced cue breaks.
    """
    if not display_text or not display_text.strip():
        return []

    raw_lines: list[str] = []
    # First split on explicit newlines so authors can force cue breaks.
    for paragraph in display_text.split("\n"):
        parts = _SPLIT_RE.split(paragraph)
        buffer = ""
        for part in parts:
            if not part:
                continue
            if len(buffer) + len(part) <= max_line_chars:
                buffer += part
            else:
                if buffer:
                    raw_lines.append(buffer)
                if len(part) > max_line_chars:
                    # Smart break: space > CJK/Latin boundary > hard cut
                    remaining = part
                    while len(remaining) > max_line_chars:
                        cut_at = max_line_chars
                        # 1. Prefer space
                        space_idx = remaining.rfind(" ", 0, max_line_chars)
                        if space_idx > int(max_line_chars * 0.4):
                            cut_at = space_idx + 1
                        else:
                            # 2. CJK/Latin boundary (scan right-to-left)
                            found = False
                            for j in range(
                                max_line_chars,
                                int(max_line_chars * 0.4),
                                -1,
                            ):
                                prev_c = remaining[j - 1] if j - 1 >= 0 else ""
                                cur_c = remaining[j] if j < len(remaining) else ""
                                if (_is_chinese(prev_c) and re.match(r"[a-zA-Z0-9]", cur_c)) or (
                                    re.match(r"[a-zA-Z0-9]", prev_c) and _is_chinese(cur_c)
                                ):
                                    cut_at = j
                                    found = True
                                    break
                            if not found:
                                cut_at = max_line_chars
                        raw_lines.append(remaining[:cut_at])
                        remaining = remaining[cut_at:]
                    if remaining:
                        raw_lines.append(remaining)
                    buffer = ""
                else:
                    buffer = part
        if buffer:
            raw_lines.append(buffer)

    # Merge pure-punctuation lines into the previous line.
    filtered: list[str] = []
    for line in raw_lines:
        stripped = _STRIP_PUNCT_RE.sub("", line)
        if len(stripped) == 0 and filtered:
            filtered[-1] += line
        else:
            filtered.append(line)

    # Trim whitespace on each line (e.g. leading space from ", text" splits).
    return [line.strip() for line in filtered if line.strip()]


# ---------------------------------------------------------------------------
# 3. Char-weighted timestamp distribution
# ---------------------------------------------------------------------------


def distribute_timestamps(
    lines: list[str], total_duration: float
) -> list[tuple[float, float]]:
    """Assign ``(start, end)`` seconds to each subtitle line.

    Algorithm (char-weighted, deterministic):

    Let ``T`` be ``total_duration`` and ``C`` be the sum of character counts
    across all lines. Each line ``i`` gets duration
    ``d_i = len(line_i) / C * T`` and is laid out back-to-back:

        start_0 = 0
        end_i   = start_i + d_i
        start_{i+1} = end_i
        end_{last}  = T      # exact, see below

    Rationale
    ---------
    - **Word-level timestamps from WhisperX are per-audio-word**, but cue
      boundaries are per *displayable* sentence which may include words
      that are not spoken (e.g. bracketed control markers were stripped
      upstream). Character weighting is a simple, stable proxy that does
      not rely on a brittle alignment between WhisperX words and display
      characters.
    - Back-to-back layout (no gap) matches the "continuous speech" nature
      of a single TTS take. Gaps would look like dropouts.
    - The last cue's ``end`` is snapped to ``T`` exactly to absorb float
      rounding — guarantees ``end_last <= total_duration`` always.

    Edge cases
    ----------
    - Empty ``lines`` list           → returns ``[]``.
    - ``total_duration <= 0``         → all cues collapse to ``(0.0, 0.0)``.
    - Lines with zero characters      → treated as 1 character each (to
      preserve ordering without division-by-zero).  In practice callers
      should pre-filter empty strings via :func:`split_subtitle_lines`.
    """
    if not lines:
        return []

    # Guard against zero-length lines sneaking in.
    char_counts = [max(len(line), 1) for line in lines]
    total_chars = sum(char_counts)

    if total_duration <= 0 or total_chars <= 0:
        return [(0.0, 0.0) for _ in lines]

    cues: list[tuple[float, float]] = []
    cursor = 0.0
    for i, c in enumerate(char_counts):
        share = c / total_chars
        duration = share * total_duration
        start = cursor
        end = cursor + duration
        cursor = end
        cues.append((start, end))

    # Snap the final end to exactly ``total_duration`` to kill float drift.
    if cues:
        last_start, _ = cues[-1]
        cues[-1] = (last_start, float(total_duration))
    return cues


# ---------------------------------------------------------------------------
# 3b. Word-level timestamp distribution (primary path)
# ---------------------------------------------------------------------------


def distribute_timestamps_with_words(
    lines: list[str],
    words: list[dict],
    chunk_start: float,
) -> list[tuple[float, float]]:
    """Assign ``(start, end)`` to each line using WhisperX word timestamps.

    Algorithm — character-level anchor + interpolation.

    Delegates to :func:`server.core.char_alignment.align_chars_to_timestamps`
    to build a per-character timestamp for the concatenated ``lines``
    string (which is a stand-in for the display text, already stripped of
    control markers by ``compose_srt``). Each line's cue then reads its
    first/last character's times off that array.

    This replaces the previous greedy-consumption + gap-aware implementation.
    The old approach baked "字符守恒假设" (original char count ≈ ASR char
    count) into the algorithm, with a stack of special-case rules
    (``_SENTENCE_END_RE``, ``_SENTENCE_BOUNDARY_GAP_S = 0.3``) patched on
    top to survive ASR mishearing long English words in Chinese contexts.
    Every rule carried a magic number and a failure mode.

    The new algorithm has one rule: match characters between script and
    ASR (after normalization), anchor matched characters to ASR word time,
    interpolate un-anchored characters between anchors. No thresholds,
    no punctuation-specific triggers, no accumulating error.

    Parameters
    ----------
    lines : list[str]
        Subtitle lines (from :func:`split_subtitle_lines`). Concatenated
        to form the character stream that's aligned against ``words``.
    words : list[dict]
        WhisperX word dicts with ``word``, ``start``, ``end`` keys.
    chunk_start : float
        Absolute start time of the chunk (subtracted from word times so
        the returned cues are chunk-relative, starting near 0).

    Returns
    -------
    list[tuple[float, float]]
        Same shape as :func:`distribute_timestamps` for drop-in use.
    """
    if not lines:
        return []

    valid_words = [w for w in words if w.get("start") is not None and w.get("end") is not None]
    if not valid_words:
        return [(0.0, 0.0) for _ in lines]

    # Concatenate lines for character alignment. split_subtitle_lines may
    # strip inter-line whitespace but the alignment normalization drops
    # whitespace anyway, so this is safe — the characters that *do* matter
    # for anchoring (letters, CJK) all survive.
    original = "".join(lines)
    from server.core.char_alignment import align_chars_to_timestamps

    char_times = align_chars_to_timestamps(
        original,
        valid_words,
        chunk_start=chunk_start,
    )

    cues: list[tuple[float, float]] = []
    offset = 0
    last_end = 0.0
    for line in lines:
        ln = len(line)
        if ln == 0:
            cues.append((last_end, last_end))
            continue
        segment = char_times[offset : offset + ln]
        if not segment:
            cues.append((last_end, last_end))
        else:
            start = segment[0][0]
            end = segment[-1][1]
            cues.append((round(start, 3), round(end, 3)))
            last_end = end
        offset += ln

    return cues


# ---------------------------------------------------------------------------
# 4. SRT serialization
# ---------------------------------------------------------------------------


def _format_ts(seconds: float) -> str:
    """Format seconds as ``HH:MM:SS,mmm`` — SRT wire format.

    Negative values are clamped to zero (SRT has no negative timestamps).
    Milliseconds round to the nearest integer; carry is propagated up so
    ``999.6 ms`` rolls into the next second cleanly.
    """
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def build_srt(cues: list[tuple[float, float, str]]) -> str:
    """Serialize ``(start, end, text)`` triples to an SRT document.

    Output is LF-terminated and ends with a trailing blank line, which is
    the shape most SRT consumers expect.  Empty ``cues`` returns ``""``.
    """
    if not cues:
        return ""
    blocks: list[str] = []
    for i, (start, end, text) in enumerate(cues, start=1):
        block = (
            f"{i}\n"
            f"{_format_ts(start)} --> {_format_ts(end)}\n"
            f"{text}\n"
        )
        blocks.append(block)
    return "\n".join(blocks) + "\n"


# ---------------------------------------------------------------------------
# Orchestration helper (still pure)
# ---------------------------------------------------------------------------


def compose_srt(
    source_text: str,
    total_duration: float,
    *,
    transcript_words: list[dict] | None = None,
    chunk_start: float = 0.0,
    max_line_chars: int = _DEFAULT_MAX_LINE_CHARS,
) -> tuple[str, int, list[dict]]:
    """One-shot transform: raw chunk text → (srt_document, line_count, cues).

    Returns the cue list alongside the SRT so callers (P5 task) can persist
    it for the frontend to consume directly. Exposing cues avoids having
    the UI re-parse the SRT or approximate character timings locally.

    Parameters
    ----------
    transcript_words : list[dict] | None
        If provided and non-empty, word-level timestamps from WhisperX are
        used to align subtitle cues (primary path). Otherwise falls back to
        char-weighted distribution.
    chunk_start : float
        Absolute start time of the chunk audio in the transcript timeline.
        Used to compute chunk-relative timestamps when *transcript_words*
        is provided.
    max_line_chars : int
        Maximum characters per subtitle line for the smart splitter.

    Returns
    -------
    tuple[str, int, list[dict]]
        ``(srt_document, line_count, cues)`` — cues are a JSON-ready list
        of ``{"start": float, "end": float, "text": str}``. Empty input
        yields ``("", 0, [])``.
    """
    display = strip_control_markers(source_text)
    lines = split_subtitle_lines(display, max_line_chars=max_line_chars)
    if not lines:
        return "", 0, []

    if transcript_words:
        timings = distribute_timestamps_with_words(lines, transcript_words, chunk_start)
    else:
        timings = distribute_timestamps(lines, total_duration)

    triples = [(start, end, text) for (start, end), text in zip(timings, lines)]
    cues = [{"start": s, "end": e, "text": t} for s, e, t in triples]
    return build_srt(triples), len(lines), cues


__all__ = [
    "STRIPPABLE_MARKERS",
    "strip_control_markers",
    "split_subtitle_lines",
    "distribute_timestamps",
    "distribute_timestamps_with_words",
    "build_srt",
    "compose_srt",
]
