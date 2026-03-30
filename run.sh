#!/bin/bash
# TTS Agent Harness — Multi-Agent Orchestration
#
# Usage:
#   bash run.sh <script.json> <episode_id>
#   bash run.sh example/demo-script.json demo
#
# Resume from a step:
#   bash run.sh <script.json> <episode_id> --from p3

set -euo pipefail

SCRIPT_PATH="${1:?Usage: run.sh <script.json> <episode_id> [--from pN]}"
EPISODE="${2:?Usage: run.sh <script.json> <episode_id> [--from pN]}"

FROM_STEP="p1"
if [[ "${3:-}" == "--from" ]]; then
  FROM_STEP="${4:?--from requires a step name (p1-p6)}"
fi

# Paths — all relative to this repo root
HARNESS_DIR="$(cd "$(dirname "$0")" && pwd)"
WORK_DIR="$HARNESS_DIR/.work/$EPISODE"
AUDIO_DIR="$WORK_DIR/audio"
TRANSCRIPT_DIR="$WORK_DIR/transcripts"
VALIDATION_DIR="$WORK_DIR/validation"
OUTPUT_DIR="$WORK_DIR/output"

CHUNKS="$WORK_DIR/chunks.json"
SUBTITLES="$WORK_DIR/subtitles.json"
PREVIEW="$WORK_DIR/preview.html"
TRACE="$WORK_DIR/trace.jsonl"

VENV="$HARNESS_DIR/.venv/bin/activate"

mkdir -p "$WORK_DIR" "$AUDIO_DIR" "$TRANSCRIPT_DIR" "$VALIDATION_DIR" "$OUTPUT_DIR"

# Only clear trace on fresh run (--from p1)
if [[ "$FROM_STEP" == "p1" ]]; then
  > "$TRACE"
fi

should_run() {
  local steps=("p1" "p2" "check2" "p3" "check3" "p4" "p5" "p6" "v2")
  local found=false
  for s in "${steps[@]}"; do
    [[ "$s" == "$FROM_STEP" ]] && found=true
    [[ "$found" == true && "$s" == "$1" ]] && return 0
  done
  return 1
}

echo "=================================================="
echo " TTS Agent Harness: $EPISODE"
echo " Script: $SCRIPT_PATH"
echo " Working dir: $WORK_DIR"
echo " Trace: $TRACE"
echo "=================================================="

# --- P1: Deterministic chunking ---
if should_run p1; then
  echo ""
  echo "=== P1: Text Chunking ==="
  node "$HARNESS_DIR/scripts/p1-chunk.js" \
    --script "$HARNESS_DIR/$SCRIPT_PATH" \
    --outdir "$WORK_DIR"
fi

# --- P2: Fish TTS Agent ---
if should_run p2; then
  echo ""
  echo "=== P2: TTS Synthesis (Fish TTS Agent) ==="
  node "$HARNESS_DIR/scripts/p2-synth.js" \
    --chunks "$CHUNKS" \
    --outdir "$AUDIO_DIR" \
    --trace "$TRACE"
fi

# --- Post-P2 deterministic pre-check ---
if should_run check2; then
  echo ""
  node "$HARNESS_DIR/scripts/precheck.js" \
    --stage p2 \
    --chunks "$CHUNKS" \
    --audiodir "$AUDIO_DIR"
fi

# --- P3: WhisperX Agent (start server, batch transcribe, keep alive for P4) ---
P3_PORT=5555
P3_PID=""

if should_run p3 || should_run p4; then
  echo ""
  echo "=== P3: Starting WhisperX Agent Server (port $P3_PORT) ==="
  source "$HARNESS_DIR/scripts/start-p3-server.sh" "$P3_PORT" "$VENV" "$HARNESS_DIR/scripts/p3-transcribe.py"
fi

# --- P3: Batch transcribe via server ---
if should_run p3; then
  echo ""
  echo "=== P3: Batch Transcription (via HTTP) ==="
  python "$HARNESS_DIR/scripts/p3-transcribe.py" \
    --chunks "$CHUNKS" \
    --audiodir "$AUDIO_DIR" \
    --outdir "$TRANSCRIPT_DIR" \
    --server-url "http://127.0.0.1:$P3_PORT"
fi

# --- Post-P3 deterministic pre-check ---
if should_run check3; then
  echo ""
  node "$HARNESS_DIR/scripts/precheck.js" \
    --stage p3 \
    --chunks "$CHUNKS" \
    --transcripts "$TRANSCRIPT_DIR"
fi

# --- P4: Claude Agent (validate + auto-fix loop, uses P3 server for retranscribe) ---
if should_run p4; then
  echo ""
  echo "=== P4: Validation + Auto-Fix (Claude Agent) ==="
  node "$HARNESS_DIR/scripts/p4-validate.js" \
    --chunks "$CHUNKS" \
    --transcripts "$TRANSCRIPT_DIR" \
    --audiodir "$AUDIO_DIR" \
    --outdir "$VALIDATION_DIR" \
    --p3-server "http://127.0.0.1:$P3_PORT" \
    --trace "$TRACE"
  echo ""
  echo ">>> V1 Review: Check validation results above <<<"
  echo "    All chunks passed or only low severity — press Enter to continue"
  echo "    Need manual intervention — press Ctrl+C to exit"
  read -r
fi

# --- Shutdown P3 server ---
if [[ -n "$P3_PID" ]] && kill -0 "$P3_PID" 2>/dev/null; then
  echo "  Shutting down P3 server (PID $P3_PID)..."
  kill "$P3_PID" 2>/dev/null
  wait "$P3_PID" 2>/dev/null || true
fi

# --- P5: Deterministic subtitle generation ---
if should_run p5; then
  echo ""
  echo "=== P5: Subtitle Generation ==="
  node "$HARNESS_DIR/scripts/p5-subtitles.js" \
    --chunks "$CHUNKS" \
    --transcripts "$TRANSCRIPT_DIR" \
    --outdir "$WORK_DIR"
fi

# --- P6: Deterministic audio concat + subtitle offset fix ---
if should_run p6; then
  echo ""
  echo "=== P6: Audio Concatenation ==="
  node "$HARNESS_DIR/scripts/p6-concat.js" \
    --chunks "$CHUNKS" \
    --audiodir "$AUDIO_DIR" \
    --subtitles "$SUBTITLES" \
    --outdir "$OUTPUT_DIR"
fi

# --- V2: Review preview ---
if should_run v2; then
  echo ""
  echo "=== V2: Review Preview ==="
  node "$HARNESS_DIR/scripts/v2-preview.js" \
    --audiodir "$OUTPUT_DIR" \
    --subtitles "$SUBTITLES" \
    --output "$PREVIEW"

  # Trace summary
  if [[ -s "$TRACE" ]]; then
    echo ""
    echo "=== Pipeline Trace Summary ==="
    node -e "require('$HARNESS_DIR/scripts/trace.js').summary('$TRACE')"
  fi

  echo ""
  echo ">>> V2 Review: Open preview in browser <<<"
  echo "    open $PREVIEW"
  open "$PREVIEW" 2>/dev/null || true
fi

echo ""
echo "=================================================="
echo " Done!"
echo " Output:"
echo "   Audio:     $OUTPUT_DIR/<shot>.wav"
echo "   Durations: $OUTPUT_DIR/durations.json"
echo "   Subtitles: $SUBTITLES"
echo "   Preview:   $PREVIEW"
echo "   Trace:     $TRACE"
echo "=================================================="
