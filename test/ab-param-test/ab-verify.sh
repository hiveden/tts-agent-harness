#!/bin/bash
# AB 测试 — 步骤 2：Forced Alignment 发音验证
#
# 对 ab-synth.sh 产出的音频做 forced alignment，检测关键词发音置信度
# 直接本地加载模型（不走 P3 server）
#
# Usage: bash test/ab-param-test/ab-verify.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUTDIR="$SCRIPT_DIR/output"

if [ ! -d "$OUTDIR" ]; then
  echo "ERROR: $OUTDIR not found. Run ab-synth.sh first." >&2
  exit 1
fi

# 检查是否有 WAV 文件
wav_count=$(find "$OUTDIR" -name "run*.wav" | wc -l | tr -d ' ')
if [ "$wav_count" -eq 0 ]; then
  echo "ERROR: No WAV files found in $OUTDIR" >&2
  exit 1
fi

echo "找到 $wav_count 个音频文件，开始 forced alignment 验证..."
echo ""

python3 "$SCRIPT_DIR/ab-verify.py" --audiodir "$OUTDIR"
