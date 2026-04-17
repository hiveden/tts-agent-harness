"""P1 chunking — pure functions.

This module is deliberately free of I/O, database access, Prefect imports,
and any environmental coupling. It is the single place where the P1
segmentation rules are encoded so that the Prefect task layer in
``server.flows.tasks.p1_chunk`` can stay a thin adapter around it, and so
that the rules can be exhaustively unit-tested without a database.

The P1 contract (see the A4 task prompt) is:

* Input: a script dict of the shape
  ``{"title": str, "segments": [{"id": int | str, "type": str, "text": str}, ...]}``.
* Output: an ordered list of :class:`ChunkInput`, one per sentence.
* A segment's ``id`` is either a string (used verbatim, e.g. ``"shot01"``)
  or an int, in which case it is zero-padded to 2 digits and prefixed with
  ``"shot"`` (``1`` -> ``"shot01"``).
* Each segment's ``text`` is split into sentences on the canonical Chinese
  sentence-terminators (``。``, ``？``, ``！``) plus their ASCII equivalents
  (``?``, ``!``). The terminator is kept attached to the preceding sentence.
* A ``chunk.text`` is the sentence verbatim (including its terminator, and
  including any ``[break]`` / ``[breath]`` / ``[long break]`` / phoneme
  control markers — those are TTS engine directives, not sentence
  boundaries).
* ``chunk.text_normalized = text.strip()`` — P1 never rewrites content.
* Empty / whitespace-only "sentences" are dropped.
* ``chunk.id = f"{episode_id}:{shot_id}:{idx}"`` where ``idx`` is 1-based
  inside the shot.
* ``chunk.boundary_hash = sha256(f"{shot_id}|{idx}|{text}").hexdigest()[:16]``
  — any change invalidates downstream stages.

**Determinism**: for a given input dict this module will always return the
exact same chunk list, including ``boundary_hash``.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from .domain import ChunkInput

# Sentence terminators. We intentionally include both full-width Chinese and
# ASCII punctuation so that mixed CJK / Latin scripts split correctly.
# The regex uses a character class; consecutive terminators (``?!``, ``。。``)
# collapse into a single break because the re.split keeps the run as one
# captured group.
_SENT_TERMINATORS = "。？！?!"
_SENT_SPLIT_RE = re.compile(rf"([^{_SENT_TERMINATORS}]*[{_SENT_TERMINATORS}]+)")


def split_segment_into_sentences(text: str) -> list[str]:
    """Split ``text`` into sentences on CJK + ASCII terminators.

    The terminator stays attached to the preceding sentence (``"你好。"`` ->
    ``["你好。"]``). A trailing fragment without a terminator is still emitted
    as its own sentence (``"你好。世界"`` -> ``["你好。", "世界"]``).

    Whitespace-only fragments are dropped, but whitespace *inside* a
    sentence (including newlines) is preserved — the task prompt says P1
    only ``trim``s, and the trimming lives in :func:`script_to_chunks`, not
    here. Here we only segment.
    """
    if not text:
        return []

    pieces: list[str] = []
    cursor = 0
    for match in _SENT_SPLIT_RE.finditer(text):
        sentence = match.group(1)
        if sentence.strip():
            pieces.append(sentence)
        cursor = match.end()

    tail = text[cursor:]
    if tail.strip():
        pieces.append(tail)

    return pieces


def compute_boundary_hash(shot_id: str, idx: int, text: str) -> str:
    """Return the 16-char hex digest used to detect upstream changes.

    The hash covers ``shot_id``, ``idx`` and the **raw** (un-trimmed)
    sentence text. Downstream consumers compare this to decide whether a
    previously-synthesised take is still valid.
    """
    payload = f"{shot_id}|{idx}|{text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _normalise_shot_id(raw: Any) -> str:
    """Normalise a segment ``id`` field into a canonical ``shot_id``.

    * ``int`` -> ``"shot{NN}"`` zero-padded to 2 digits.
    * ``str`` digits (``"1"``) -> same as ``int``. This is a small robustness
      nicety; the task prompt did not require it but it avoids breakage on
      scripts exported by tools that JSON-encode ints as strings.
    * any other ``str`` -> used verbatim (e.g. ``"shot01"``, ``"hook-a"``).
    """
    if isinstance(raw, bool):  # guard: bool is an int subclass
        raise ValueError(f"segment id must be int or str, got bool: {raw!r}")
    if isinstance(raw, int):
        return f"shot{raw:02d}"
    if isinstance(raw, str):
        if raw.isdigit():
            return f"shot{int(raw):02d}"
        return raw
    raise ValueError(f"segment id must be int or str, got {type(raw).__name__}")


def _group_sentences(
    sentences: list[str],
    max_chars: int,
) -> list[str]:
    """Greedily merge consecutive sentences until *max_chars* would be exceeded.

    * A single sentence longer than *max_chars* is never split — it becomes
      its own group.
    * ``max_chars <= 0`` disables grouping (each sentence = one group, i.e.
      the legacy per-sentence behaviour).
    """
    if max_chars <= 0:
        return list(sentences)

    groups: list[str] = []
    buf: list[str] = []
    buf_len = 0

    for sent in sentences:
        sent_len = len(sent.strip())
        if buf and buf_len + sent_len > max_chars:
            # Flush current group.
            groups.append("".join(buf))
            buf = []
            buf_len = 0
        buf.append(sent)
        buf_len += sent_len

    if buf:
        groups.append("".join(buf))

    return groups


# Default grouping limit (characters).  Overridable per-call.
DEFAULT_MAX_CHUNK_CHARS = 200


def script_to_chunks(
    script: dict,
    episode_id: str,
    *,
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
) -> list[ChunkInput]:
    """Turn a parsed ``script.json`` into an ordered list of chunks.

    ``max_chunk_chars`` controls how sentences within a shot are grouped:

    * ``> 0`` — adjacent sentences are greedily merged until adding the
      next sentence would exceed the limit.  A single sentence longer than
      the limit is never split.
    * ``0``   — disable grouping; every sentence is its own chunk (legacy
      per-sentence behaviour).

    Any segment missing ``text`` is silently skipped (no text -> no chunk),
    so that authoring tools can leave placeholder rows during drafting.
    A segment whose ``text`` splits into zero non-empty sentences likewise
    contributes nothing. Neither is an error.
    """
    segments = script.get("segments") or []
    chunks: list[ChunkInput] = []

    for segment in segments:
        if not isinstance(segment, dict):
            raise ValueError(f"segment must be a dict, got {type(segment).__name__}")
        if "id" not in segment:
            raise ValueError(f"segment missing 'id': {segment!r}")

        shot_id = _normalise_shot_id(segment["id"])
        raw_text = segment.get("text") or ""
        if not isinstance(raw_text, str):
            raise ValueError(
                f"segment.text must be str, got {type(raw_text).__name__}"
            )

        sentences = split_segment_into_sentences(raw_text)
        # Drop whitespace-only fragments before grouping.
        sentences = [s for s in sentences if s.strip()]
        groups = _group_sentences(sentences, max_chunk_chars)

        for group_idx, group_text in enumerate(groups, start=1):
            text_normalized = group_text.strip()
            if not text_normalized:
                continue
            chunk_id = f"{episode_id}:{shot_id}:{group_idx}"
            chunks.append(
                ChunkInput(
                    id=chunk_id,
                    episode_id=episode_id,
                    shot_id=shot_id,
                    idx=group_idx,
                    text=group_text,
                    text_normalized=text_normalized,
                    subtitle_text=None,
                    char_count=len(text_normalized),
                    boundary_hash=compute_boundary_hash(
                        shot_id, group_idx, group_text
                    ),
                    metadata={"segment_type": segment.get("type")}
                    if segment.get("type")
                    else {},
                )
            )

    return chunks


__all__ = [
    "split_segment_into_sentences",
    "compute_boundary_hash",
    "script_to_chunks",
    "DEFAULT_MAX_CHUNK_CHARS",
]
