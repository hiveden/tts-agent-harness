#!/bin/bash
# 启动 P3 WhisperX server，等模型加载完成后返回 PID
#
# Usage:
#   source scripts/start-p3-server.sh <port> <venv_activate_path> <script_path>
#   echo $P3_PID  # server PID
#
# Caller is responsible for: kill $P3_PID

P3_PORT="${1:?Usage: start-p3-server.sh <port> <venv_activate> <script_path>}"
VENV_ACTIVATE="${2:?}"
P3_SCRIPT="${3:?}"

if [[ ! -f "$VENV_ACTIVATE" ]]; then
  echo "ERROR: Python venv not found at $VENV_ACTIVATE"
  exit 1
fi

source "$VENV_ACTIVATE"

echo "  Starting P3 WhisperX server on port $P3_PORT..."
python "$P3_SCRIPT" --server --port "$P3_PORT" &>/tmp/p3-server-${P3_PORT}.log &
P3_PID=$!

# 等模型加载完成
for i in $(seq 1 120); do
  if curl -s --noproxy 127.0.0.1 "http://127.0.0.1:$P3_PORT/health" 2>/dev/null | grep -q ok; then
    echo "  P3 server ready (PID $P3_PID, ${i}x2s)"
    return 0 2>/dev/null || exit 0
  fi
  if ! kill -0 "$P3_PID" 2>/dev/null; then
    echo "ERROR: P3 server died during startup. Check /tmp/p3-server-${P3_PORT}.log"
    return 1 2>/dev/null || exit 1
  fi
  sleep 2
done

echo "ERROR: P3 server failed to start within 240s"
kill "$P3_PID" 2>/dev/null
return 1 2>/dev/null || exit 1
