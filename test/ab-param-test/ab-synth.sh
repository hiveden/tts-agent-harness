#!/bin/bash
# AB 测试 — 步骤 1：TTS 合成
#
# 用三组 temperature/top_p 参数各合成 N 次，记录时长和延迟
# 产物: output/param-ab-test/{A_default,B_mid,C_low}/runN.wav + results.csv
#
# Usage: set -a && source .env && set +a && bash test/ab-param-test/ab-synth.sh

set -euo pipefail

if [ -z "${FISH_TTS_KEY:-}" ]; then
  echo "ERROR: FISH_TTS_KEY not set. Run: source .env" >&2
  exit 1
fi
command -v ffprobe >/dev/null || { echo "ERROR: ffprobe not found"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUTDIR="$SCRIPT_DIR/output"
rm -rf "$OUTDIR"
mkdir -p "$OUTDIR"

# --- 读 config ---
MODEL=$(node -e "
  const c = JSON.parse(require('fs').readFileSync('$REPO_DIR/.harness/config.json','utf-8'));
  console.log(process.env.FISH_TTS_MODEL || c.p2.model || 's1');
")
SPEED=$(node -e "
  const c = JSON.parse(require('fs').readFileSync('$REPO_DIR/.harness/config.json','utf-8'));
  console.log(process.env.TTS_SPEED || c.p2.default_speed || '1.0');
")
REFERENCE_ID="${FISH_TTS_REFERENCE_ID:-}"

# --- 测试文本（brief02 segment 1 的 tts_text） ---
TEXT='Mac 跑本地模型，[break]之前一直很尴尬。装了 Ollama，跑个小模型还行，[breath]大一点的慢得受不了，玩两下就吃灰了。[long break]最近我在做一个 RAG 项目，需要大量跑测试，[break]重新研究了一下，发现情况变了。'

echo "============================================"
echo " AB 测试 — 步骤 1：TTS 合成"
echo "============================================"
echo "模型: $MODEL | 语速: ${SPEED}x"
echo "文本: ${TEXT:0:50}..."
echo "Reference ID: ${REFERENCE_ID:-（默认声音）}"
echo ""

# --- 参数组 ---
GROUP_NAMES=("A_default" "B_mid" "C_low")
TEMPS=(0.7 0.3 0.2)
TOP_PS=(0.7 0.5 0.3)
RUNS=3

# --- 工具函数 ---
get_duration() {
  ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$1" 2>/dev/null
}

call_tts() {
  local text="$1" temp="$2" top_p="$3" outfile="$4"
  local payload
  if [ -n "$REFERENCE_ID" ]; then
    payload=$(jq -n \
      --arg text "$text" --arg ref "$REFERENCE_ID" \
      --argjson temp "$temp" --argjson top_p "$top_p" \
      '{text: $text, reference_id: $ref, temperature: $temp, top_p: $top_p}')
  else
    payload=$(jq -n \
      --arg text "$text" \
      --argjson temp "$temp" --argjson top_p "$top_p" \
      '{text: $text, temperature: $temp, top_p: $top_p}')
  fi

  local mp3file="${outfile%.wav}.mp3"
  local start_ms end_ms
  start_ms=$(python3 -c "import time; print(int(time.time()*1000))")

  local http_code
  http_code=$(curl -s -o "$mp3file" -w "%{http_code}" \
    -X POST "https://api.fish.audio/v1/tts" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $FISH_TTS_KEY" \
    -H "model: $MODEL" \
    -d "$payload")

  end_ms=$(python3 -c "import time; print(int(time.time()*1000))")
  local elapsed=$(( end_ms - start_ms ))

  if [ "$http_code" != "200" ]; then
    echo "ERROR: HTTP $http_code" >&2
    rm -f "$mp3file"
    echo "error,$elapsed"
    return 1
  fi

  ffmpeg -y -i "$mp3file" -filter:a "atempo=$SPEED" -ar 44100 "$outfile" 2>/dev/null
  rm -f "$mp3file"

  local duration
  duration=$(get_duration "$outfile")
  echo "$duration,$elapsed"
}

# --- 运行 ---
RESULTS_CSV="$OUTDIR/results.csv"
echo "group,run,temperature,top_p,duration_s,latency_ms" > "$RESULTS_CSV"

for g in 0 1 2; do
  group="${GROUP_NAMES[$g]}"
  temp="${TEMPS[$g]}"
  top_p="${TOP_PS[$g]}"

  echo "--- 组 $group: temperature=$temp, top_p=$top_p ---"
  mkdir -p "$OUTDIR/$group"

  for run in $(seq 1 $RUNS); do
    outfile="$OUTDIR/$group/run${run}.wav"
    printf "  run %d/%d ... " "$run" "$RUNS"

    result=$(call_tts "$TEXT" "$temp" "$top_p" "$outfile")
    duration=$(echo "$result" | cut -d, -f1)
    latency=$(echo "$result" | cut -d, -f2)

    if [ "$duration" = "error" ]; then
      echo "FAILED (${latency}ms)"
      echo "$group,$run,$temp,$top_p,error,$latency" >> "$RESULTS_CSV"
    else
      printf "%.2fs (%dms)\n" "$duration" "$latency"
      echo "$group,$run,$temp,$top_p,$duration,$latency" >> "$RESULTS_CSV"
    fi
    sleep 1
  done
  echo ""
done

# --- 统计 ---
echo "============================================"
echo " 合成统计"
echo "============================================"

node -e "
const fs = require('fs');
const lines = fs.readFileSync('$RESULTS_CSV', 'utf-8').trim().split('\n').slice(1);
const data = lines.map(l => {
  const [group, run, temp, top_p, dur, lat] = l.split(',');
  return { group, run: +run, temp, top_p, duration: dur === 'error' ? null : +dur, latency: +lat };
});
const groups = [...new Set(data.map(d => d.group))];
const avg = arr => arr.reduce((a, b) => a + b, 0) / arr.length;
const std = arr => { const m = avg(arr); return Math.sqrt(arr.reduce((s, v) => s + (v - m) ** 2, 0) / arr.length); };

for (const g of groups) {
  const rows = data.filter(d => d.group === g);
  const ok = rows.filter(r => r.duration !== null);
  if (ok.length === 0) { console.log('组 ' + g + ': 全部失败'); continue; }
  const durs = ok.map(r => r.duration);
  const lats = ok.map(r => r.latency);
  console.log('');
  console.log('组 ' + g + ' (temp=' + rows[0].temp + ', top_p=' + rows[0].top_p + ')');
  console.log('  成功: ' + ok.length + '/' + rows.length);
  console.log('  时长: avg=' + avg(durs).toFixed(2) + 's  std=' + std(durs).toFixed(3) + '  range=[' + Math.min(...durs).toFixed(2) + ', ' + Math.max(...durs).toFixed(2) + ']');
  console.log('  延迟: avg=' + avg(lats).toFixed(0) + 'ms  range=[' + Math.min(...lats) + ', ' + Math.max(...lats) + ']');
}
console.log('');
console.log('产物: $OUTDIR');
console.log('下一步: bash test/ab-verify.sh');
"
