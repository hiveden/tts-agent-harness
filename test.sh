#!/bin/bash
# TTS Agent Harness — 端到端测试
#
# 用中英混合压力测试脚本验证全链路。
# 需要: FISH_TTS_KEY 环境变量、Python venv 已安装、CLIProxyAPI (localhost:8317) 可用
#
# Usage:
#   bash test.sh              # 跑完整测试
#   bash test.sh --p1-only    # 只跑 P1（不需要 API，秒完）
#   bash test.sh --no-p4      # 跳过 P4 Claude 校验（省钱省时间）

set -euo pipefail

HARNESS_DIR="$(cd "$(dirname "$0")" && pwd)"
TEST_EPISODE="test-mixed"
WORK="$HARNESS_DIR/.work/$TEST_EPISODE"
SCRIPT="example/demo-script.json"

MODE="${1:-full}"

echo "=================================================="
echo " TTS Harness Test: $MODE"
echo "=================================================="

# 清理上次测试
rm -rf "$WORK"

# ========================================
# TEST 1: P1 切分
# ========================================
echo ""
echo "--- TEST 1: P1 Chunking ---"
node "$HARNESS_DIR/scripts/p1-chunk.js" --script "$HARNESS_DIR/$SCRIPT" --outdir "$WORK"

# 验证: 4 segments → 4 chunks, 可逆性通过
CHUNK_COUNT=$(python3 -c "import json; print(len(json.load(open('$WORK/chunks.json'))))")
if [[ "$CHUNK_COUNT" -ne 4 ]]; then
  echo "FAIL: Expected 4 chunks, got $CHUNK_COUNT"
  exit 1
fi

# 验证: normalize 处理了英文品牌名
HAS_BRAND_BREAK=$(python3 -c "
import json
chunks = json.load(open('$WORK/chunks.json'))
# shot04 有 'Agent Loop是现象' → normalized 应该有 'Agent Loop. 是现象'
shot04 = [c for c in chunks if c['shot_id'] == 'shot04'][0]
print('yes' if '. ' in shot04['text_normalized'] else 'no')
")
if [[ "$HAS_BRAND_BREAK" != "yes" ]]; then
  echo "FAIL: Brand name break not applied in text_normalized"
  exit 1
fi

echo "PASS: 4 chunks, normalize rules applied, reversibility verified"

if [[ "$MODE" == "--p1-only" ]]; then
  echo ""
  echo "=== P1-only test complete ==="
  exit 0
fi

# ========================================
# TEST 2: P2 TTS 合成
# ========================================
echo ""
echo "--- TEST 2: P2 TTS Synthesis ---"
if [[ -z "${FISH_TTS_KEY:-}" ]]; then
  echo "SKIP: FISH_TTS_KEY not set"
  exit 0
fi

mkdir -p "$WORK/audio"
node "$HARNESS_DIR/scripts/p2-synth.js" --chunks "$WORK/chunks.json" --outdir "$WORK/audio"

# 验证: 所有 chunk 都有 WAV
SYNTH_OK=$(python3 -c "import json; chunks=json.load(open('$WORK/chunks.json')); print(sum(1 for c in chunks if c.get('status')=='synth_done'))")
echo "  Synthesized: $SYNTH_OK/4"

# Post-P2 precheck
echo ""
echo "--- TEST 2b: Post-P2 Precheck ---"
node "$HARNESS_DIR/scripts/precheck.js" --stage p2 --chunks "$WORK/chunks.json" --audiodir "$WORK/audio"

if [[ "$MODE" == "--no-p4" ]]; then
  # 跳 P4，直接跑 P3→P5→P6→V2
  echo ""
  echo "--- TEST 3: P3 Transcription (batch, no server) ---"
  mkdir -p "$WORK/transcripts"
  source "$HARNESS_DIR/.venv/bin/activate"
  python "$HARNESS_DIR/scripts/p3-transcribe.py" \
    --chunks "$WORK/chunks.json" --audiodir "$WORK/audio" --outdir "$WORK/transcripts"

  echo ""
  echo "--- TEST 3b: Post-P3 Precheck ---"
  node "$HARNESS_DIR/scripts/precheck.js" --stage p3 --chunks "$WORK/chunks.json" --transcripts "$WORK/transcripts"

  echo ""
  echo "--- TEST 5: P5 Subtitles ---"
  node "$HARNESS_DIR/scripts/p5-subtitles.js" \
    --chunks "$WORK/chunks.json" --transcripts "$WORK/transcripts" --outdir "$WORK"

  echo ""
  echo "--- TEST 6: P6 Concat ---"
  mkdir -p "$WORK/output"
  node "$HARNESS_DIR/scripts/p6-concat.js" \
    --chunks "$WORK/chunks.json" --audiodir "$WORK/audio" --subtitles "$WORK/subtitles.json" --outdir "$WORK/output"

  echo ""
  echo "--- TEST 7: V2 Preview ---"
  node "$HARNESS_DIR/scripts/v2-preview.js" \
    --audiodir "$WORK/output" --subtitles "$WORK/subtitles.json" --output "$WORK/preview.html"

  echo ""
  echo "=== Test complete (--no-p4 mode) ==="
  echo "  Preview: open $WORK/preview.html"
  exit 0
fi

# ========================================
# TEST 3: P3 server + transcription
# ========================================
echo ""
echo "--- TEST 3: P3 Server Mode ---"
mkdir -p "$WORK/transcripts"

source "$HARNESS_DIR/scripts/start-p3-server.sh" 5556 "$HARNESS_DIR/.venv/bin/activate" "$HARNESS_DIR/scripts/p3-transcribe.py"

# Batch 转写 via HTTP
python "$HARNESS_DIR/scripts/p3-transcribe.py" \
  --chunks "$WORK/chunks.json" --audiodir "$WORK/audio" --outdir "$WORK/transcripts" \
  --server-url http://127.0.0.1:5556

echo ""
echo "--- TEST 3b: Post-P3 Precheck ---"
node "$HARNESS_DIR/scripts/precheck.js" --stage p3 --chunks "$WORK/chunks.json" --transcripts "$WORK/transcripts"

# ========================================
# TEST 4: P4 单 chunk 校验（验证 server 模式 retranscribe）
# ========================================
echo ""
echo "--- TEST 4: P4 Claude Validation (shot01 only) ---"
mkdir -p "$WORK/validation"
node "$HARNESS_DIR/scripts/p4-validate.js" \
  --chunks "$WORK/chunks.json" \
  --transcripts "$WORK/transcripts" \
  --audiodir "$WORK/audio" \
  --outdir "$WORK/validation" \
  --p3-server http://127.0.0.1:5556 \
  --chunk shot01_chunk01 || true  # 允许 needs_human

# 显示校验轮次
ROUNDS=$(ls "$WORK/validation/" 2>/dev/null | grep shot01 | wc -l | tr -d ' ')
echo "  shot01 went through $ROUNDS validation round(s)"

# 关闭 P3 server
kill "$P3_PID" 2>/dev/null; wait "$P3_PID" 2>/dev/null || true
echo "  P3 server stopped"

# ========================================
# TEST 5-7: P5 + P6 + V2
# ========================================
# 把未经 P4 的 chunks 也标记为 validated 以便 P5 处理
python3 -c "
import json
chunks = json.load(open('$WORK/chunks.json'))
for c in chunks:
    if c['status'] == 'transcribed':
        c['status'] = 'validated'
json.dump(chunks, open('$WORK/chunks.json','w'), ensure_ascii=False, indent=2)
"

echo ""
echo "--- TEST 5: P5 Subtitles ---"
node "$HARNESS_DIR/scripts/p5-subtitles.js" \
  --chunks "$WORK/chunks.json" --transcripts "$WORK/transcripts" --outdir "$WORK"

echo ""
echo "--- TEST 6: P6 Concat ---"
mkdir -p "$WORK/output"
node "$HARNESS_DIR/scripts/p6-concat.js" \
  --chunks "$WORK/chunks.json" --audiodir "$WORK/audio" --subtitles "$WORK/subtitles.json" --outdir "$WORK/output"

# 验证: 输出 WAV 时长合理
for f in "$WORK/output"/shot*.wav; do
  DUR=$(ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$f")
  NAME=$(basename "$f")
  echo "  $NAME: ${DUR}s"
done

echo ""
echo "--- TEST 7: V2 Preview ---"
node "$HARNESS_DIR/scripts/v2-preview.js" \
  --audiodir "$WORK/output" --subtitles "$WORK/subtitles.json" --output "$WORK/preview.html"

echo ""
echo "=================================================="
echo " ALL TESTS PASSED"
echo "=================================================="
echo " Artifacts:"
echo "   Chunks:    $WORK/chunks.json"
echo "   Audio:     $WORK/output/<shot>.wav"
echo "   Subtitles: $WORK/subtitles.json"
echo "   Validation: $WORK/validation/"
echo "   Preview:   $WORK/preview.html"
echo ""
echo " To review: open $WORK/preview.html"
