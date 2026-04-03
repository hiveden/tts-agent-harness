#!/bin/bash
# 启动 P3 WhisperX server，等模型加载完成后返回 PID
#
# 启动前自动清理：
#   1. 检查 PID 文件，杀旧进程
#   2. 检查端口占用，杀占用进程
#
# Usage:
#   source scripts/start-p3-server.sh <port> <venv_activate_path> <script_path> [<work_dir>]
#   echo $P3_PID  # server PID
#
# Caller is responsible for: kill $P3_PID (or call stop-p3-server)

P3_PORT="${1:?Usage: start-p3-server.sh <port> <venv_activate> <script_path> [<work_dir>]}"
VENV_ACTIVATE="${2:?}"
P3_SCRIPT="${3:?}"
P3_WORK_DIR="${4:-.}"
P3_PID_FILE="$P3_WORK_DIR/p3.pid"
P3_LOG="$P3_WORK_DIR/p3-server.log"

if [[ ! -f "$VENV_ACTIVATE" ]]; then
  echo "ERROR: Python venv not found at $VENV_ACTIVATE"
  return 1 2>/dev/null || exit 1
fi

# --- 清理旧进程 ---

# 1. 检查 PID 文件
if [[ -f "$P3_PID_FILE" ]]; then
  OLD_PID=$(cat "$P3_PID_FILE" 2>/dev/null)
  if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "  Killing old P3 server (PID $OLD_PID from pidfile)..."
    kill "$OLD_PID" 2>/dev/null
    sleep 1
    kill -9 "$OLD_PID" 2>/dev/null || true
  fi
  rm -f "$P3_PID_FILE"
fi

# 2. 检查端口占用
PORT_PIDS=$(lsof -ti:"$P3_PORT" 2>/dev/null || true)
if [[ -n "$PORT_PIDS" ]]; then
  echo "  Port $P3_PORT occupied by PID(s): $PORT_PIDS — killing..."
  echo "$PORT_PIDS" | xargs kill 2>/dev/null || true
  sleep 1
  # force kill 残留
  PORT_PIDS=$(lsof -ti:"$P3_PORT" 2>/dev/null || true)
  if [[ -n "$PORT_PIDS" ]]; then
    echo "$PORT_PIDS" | xargs kill -9 2>/dev/null || true
    sleep 1
  fi
fi

# --- 启动 ---

source "$VENV_ACTIVATE"

# 离线模式：跳过 HuggingFace API 版本检查，直接用本地缓存模型
export HF_HUB_OFFLINE=1

mkdir -p "$P3_WORK_DIR"
echo "  Starting P3 WhisperX server on port $P3_PORT..."
python "$P3_SCRIPT" --server --port "$P3_PORT" &>"$P3_LOG" &
P3_PID=$!

# 写 PID 文件
echo "$P3_PID" > "$P3_PID_FILE"

# 等模型加载完成
for i in $(seq 1 120); do
  if curl -s --noproxy 127.0.0.1 "http://127.0.0.1:$P3_PORT/health" 2>/dev/null | grep -q ok; then
    echo "  P3 server ready (PID $P3_PID, ${i}x2s)"
    return 0 2>/dev/null || exit 0
  fi
  if ! kill -0 "$P3_PID" 2>/dev/null; then
    echo "ERROR: P3 server died during startup. Log: $P3_LOG"
    cat "$P3_LOG" | tail -20
    rm -f "$P3_PID_FILE"
    return 1 2>/dev/null || exit 1
  fi
  sleep 2
done

echo "ERROR: P3 server failed to start within 240s. Log: $P3_LOG"
kill "$P3_PID" 2>/dev/null
rm -f "$P3_PID_FILE"
return 1 2>/dev/null || exit 1
