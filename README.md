# TTS Agent Harness

A multi-agent harness for automated TTS (Text-to-Speech) production with quality validation. Input a script, get back audio + time-aligned subtitles.

## Architecture

Three AI agents orchestrated by a deterministic harness:

```
Script (JSON)
  |
  v
+---------------- Harness (run.sh + chunks.json) -----------------+
|                                                                   |
|  [P1]  Deterministic chunking (JS)    -- text -> chunks          |
|  [P2]  Fish TTS Agent                 -- text -> speech (black box) |
|  [+2]  Deterministic pre-check        -- WAV exists/duration/rate |
|  [P3]  WhisperX Agent                 -- speech -> text + timestamps |
|  [+3]  Deterministic pre-check        -- JSON schema/char ratio  |
|  [P4]  Claude Agent                   -- validate + auto-fix loop |
|         |-> FAIL? -> fix text_normalized -> P2 -> P3 -> P4       |
|  [P5]  Deterministic subtitles (JS)   -- timestamps -> per-chunk subs |
|  [P6]  Deterministic concat (JS)      -- concat + offset -> final |
|  [V2]  Review preview                 -- HTML audio + subtitle highlight |
|                                                                   |
|  Cross-round memory: chunks.json status + trace.jsonl            |
+-----------------------------------------------------------------+
  |
  v
Output: per-shot WAV + subtitles.json + durations.json + preview.html
```

### Harness Engineering — Four Elements

| Element | Implementation |
|---------|---------------|
| **Scope** | `text_normalized` field (only this changes per round) |
| **Eval** | Deterministic pre-checks (free) + Claude semantic validation (paid) |
| **Constraints** | Prompt defines error taxonomy + max 3 retry rounds |
| **Memory** | `chunks.json` status + `validation/*_roundN.json` + `trace.jsonl` |

## Quick Start

### Prerequisites

- Node.js 18+
- Python 3.11 (for WhisperX)
- ffmpeg + ffprobe
- [Fish TTS](https://fish.audio) API key
- Claude API access (via proxy or direct)
- HTTPS proxy (e.g., ClashX) at `127.0.0.1:7890`

### Setup

```bash
# 1. Clone
git clone <repo-url> tts-agent-harness
cd tts-agent-harness

# 2. Python venv + WhisperX
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure
cp example/.env.example .env
# Edit .env with your API keys
```

### Run the demo

```bash
source .env
bash run.sh example/demo-script.json demo
```

The pipeline will:
1. **P1**: Split 4 segments into 4 chunks (smart sentence-based splitting)
2. **P2**: Synthesize each chunk via Fish TTS (parallel, with retry)
3. **Pre-check**: Verify WAV files are valid (duration, speech rate)
4. **P3**: Start WhisperX server, batch transcribe for timestamps
5. **Pre-check**: Verify transcription quality (schema, char ratio, monotonic timestamps)
6. **P4**: Claude validates speech vs script, auto-fixes `text_normalized` and retries P2→P3→P4 up to 3 rounds (uses P3 server for fast retranscription)
7. **V1 checkpoint**: Human reviews any `needs_human` chunks
8. **P5**: Generate time-aligned subtitles (per-chunk relative timestamps)
9. **P6**: Concatenate audio with padding/gaps, compute global subtitle offsets
10. **V2 checkpoint**: Opens HTML preview — play audio with progressive subtitle reveal

### Resume from a step

```bash
# Skip P1/P2, start from transcription
bash run.sh example/demo-script.json demo --from p3
```

### Redo a single chunk

```bash
# P4 auto-fix does this internally, but you can also do it manually:
node scripts/p2-synth.js --chunks .work/demo/chunks.json --outdir .work/demo/audio --chunk shot01_chunk02
```

## Script Format

```json
{
  "title": "Episode Title",
  "segments": [
    {
      "id": 1,
      "type": "hook",
      "text": "The text to be spoken. This becomes the subtitle."
    }
  ]
}
```

Each segment's `text` field is:
- Split into chunks by P1 (≤200 chars, ≤5 sentences per chunk)
- Normalized for TTS (symbol replacement: `-` -> `to`, `%` -> `percent`, etc.)
- The **original text** is preserved for subtitles; only `text_normalized` goes to TTS

## Output

```
public/<episode>/tts/
  shot01.wav          # Per-shot concatenated audio
  shot02.wav
  durations.json      # Per-shot duration

.work/<episode>/
  chunks.json         # State machine (the "memory")
  subtitles.json      # Time-aligned subtitles
  trace.jsonl         # Structured execution trace
  preview.html        # V2 review page
```

### subtitles.json format

```json
{
  "shot01": [
    { "id": "sub_001", "text": "Original script text", "start": 0.2, "end": 2.54 }
  ]
}
```

## Configuration

Environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `FISH_TTS_KEY` | Yes | Fish TTS API key |
| `FISH_TTS_REFERENCE_ID` | No | Voice clone reference ID |
| `FISH_TTS_MODEL` | No | Fish TTS model (default: `s1`) |
| `TTS_SPEED` | No | Playback speed multiplier (default: `1.0`) |

### Proxy

P2 routes Fish TTS API calls through an HTTPS proxy at `127.0.0.1:7890` (HTTP CONNECT tunnel). To change or disable, edit `PROXY_HOST`/`PROXY_PORT` in `scripts/p2-synth.js`.

### Claude API

P4 calls Claude via `localhost:8317` (CLIProxyAPI). To use direct Anthropic API, change `CLAUDE_PROXY_URL` in `scripts/p4-validate.js`.

## Testing

The demo script (`example/demo-script.json`) is a Chinese-English mixed stress test with brand names (Karpathy, autoResearch), numbers (630, 60000), and technical terms (NLAH, ICLR, cargo test) — the hardest cases for Chinese TTS.

```bash
# Quick: P1 only, no API needed, instant
bash test.sh --p1-only

# Medium: P1→P6, skip P4 Claude validation (needs FISH_TTS_KEY)
FISH_TTS_KEY=xxx bash test.sh --no-p4

# Full: P1→P6 with P4 auto-fix loop (needs FISH_TTS_KEY + Claude API)
FISH_TTS_KEY=xxx bash test.sh
```

### Verified test results

Shot01 (Chinese-English mixed, highest difficulty):

| Round | High Issues | Auto-Fix Action |
|-------|-------------|-----------------|
| 1 | 4: Karpathy→CarPayD, 630→六三型, 60000 stars→6万秒TARS, The→的 | Karpathy→卡帕西, 630→六百三十, 60000→六万个星标 |
| 2 | 3: 六百三十→630, 六万→6万, The卡帕西→的卡帕西 | 六百三十→六三零, The卡帕西Loop→卡帕西循环 |
| 3 | 1: 它→他的 (pronoun error, TTS engine limitation) | → `needs_human` |

From 4 high-severity issues down to 1 (a TTS engine limitation), fully automated.

P3 server mode: retranscription takes **~8s** per chunk (vs ~2min when reloading model each time).

## License

MIT
