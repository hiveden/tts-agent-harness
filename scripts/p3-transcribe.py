#!/usr/bin/env python3
"""
P3 — WhisperX Agent（HTTP Server + Batch 模式）

两种运行方式：
  1. Server 模式：加载模型后常驻，暴露 HTTP 接口供 P4 retry 调用
     python scripts/p3-transcribe.py --server --port 5555

  2. Client 模式（通过 p3-client.js 或直接 curl）：
     curl -X POST http://localhost:5555/transcribe \
       -H 'Content-Type: application/json' \
       -d '{"audio_path": "...", "chunk_id": "...", "text": "...", "text_normalized": "...", "outdir": "..."}'

Server 启动后打印 "READY" 到 stdout，调用方以此判断模型加载完成。
"""

import argparse
import json
import os
import sys
import signal
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

import torch
import whisperx

DEVICE = "cpu"
LANGUAGE = "zh"
BATCH_SIZE = 8
COMPUTE_TYPE = "int8"

# 全局模型引用（server 模式下共享）
_model = None
_align_model = None
_align_metadata = None


def load_models():
    global _model, _align_model, _align_metadata
    if _model is not None:
        return

    print("  Loading WhisperX model...", flush=True)
    _model = whisperx.load_model(
        "large-v3",
        device=DEVICE,
        compute_type=COMPUTE_TYPE,
        language=LANGUAGE,
    )

    print("  Loading alignment model...", flush=True)
    _align_model, _align_metadata = whisperx.load_align_model(
        language_code=LANGUAGE,
        device=DEVICE,
    )
    print("  Models loaded.", flush=True)


def transcribe_audio(audio_path: str) -> dict:
    """转写单个音频文件，返回 WhisperX 结果"""
    audio = whisperx.load_audio(audio_path)
    result = _model.transcribe(audio, batch_size=BATCH_SIZE, language=LANGUAGE)
    result = whisperx.align(
        result["segments"],
        _align_model,
        _align_metadata,
        audio,
        device=DEVICE,
        return_char_alignments=False,
    )
    return result


def format_output(chunk_id, shot_id, text, text_normalized, result):
    """将 WhisperX 结果格式化为标准输出"""
    output = {
        "chunk_id": chunk_id,
        "shot_id": shot_id,
        "original_text": text,
        "original_normalized": text_normalized,
        "segments": [],
    }

    full_text_parts = []
    for seg in result.get("segments", []):
        seg_out = {
            "text": seg.get("text", "").strip(),
            "start": round(seg.get("start", 0), 3),
            "end": round(seg.get("end", 0), 3),
            "words": [],
        }
        for w in seg.get("words", []):
            seg_out["words"].append({
                "word": w.get("word", ""),
                "start": round(w.get("start", 0), 3),
                "end": round(w.get("end", 0), 3),
            })
        output["segments"].append(seg_out)
        full_text_parts.append(seg_out["text"])

    output["full_transcribed_text"] = "".join(full_text_parts)
    return output


# =============================================================
# HTTP Server 模式
# =============================================================

class TranscribeHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/transcribe":
            self._handle_transcribe()
        elif self.path == "/health":
            self._respond(200, {"status": "ok"})
        else:
            self._respond(404, {"error": "not found"})

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, {"status": "ok"})
        else:
            self._respond(404, {"error": "not found"})

    def _handle_transcribe(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))

            audio_path = body["audio_path"]
            chunk_id = body.get("chunk_id", "unknown")
            shot_id = body.get("shot_id", "")
            text = body.get("text", "")
            text_normalized = body.get("text_normalized", "")
            outdir = body.get("outdir", "")

            if not os.path.exists(audio_path):
                self._respond(400, {"error": f"audio not found: {audio_path}"})
                return

            print(f"  [TRANSCRIBE] {chunk_id}...", flush=True)
            result = transcribe_audio(audio_path)
            output = format_output(chunk_id, shot_id, text, text_normalized, result)

            # 如果指定了 outdir，写入文件
            if outdir:
                os.makedirs(outdir, exist_ok=True)
                out_path = os.path.join(outdir, f"{chunk_id}.json")
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(output, f, ensure_ascii=False, indent=2)
                print(f"    → {out_path}", flush=True)

            print(f"    转写: {output['full_transcribed_text'][:60]}...", flush=True)
            self._respond(200, output)

        except Exception as e:
            print(f"    [ERROR] {e}", flush=True)
            self._respond(500, {"error": str(e)})

    def _respond(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def log_message(self, format, *args):
        pass  # 静默 HTTP 日志


def run_server(port):
    load_models()
    import socket
    class ReusableHTTPServer(HTTPServer):
        allow_reuse_address = True
        allow_reuse_port = True
    server = ReusableHTTPServer(("127.0.0.1", port), TranscribeHandler)

    def shutdown(sig, frame):
        print("\n  P3 server shutting down.", flush=True)
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # READY 信号 — 调用方通过检测这行判断模型加载完成
    print(f"READY on port {port}", flush=True)
    server.serve_forever()


# =============================================================
# Batch 模式（通过 HTTP 调用 server，或直接本地处理）
# =============================================================

def run_batch(chunks_path, audiodir, outdir, chunk_id=None, server_url=None):
    """Batch 转写：如果有 server_url 走 HTTP，否则本地加载模型"""
    chunks = json.loads(open(chunks_path).read())
    os.makedirs(outdir, exist_ok=True)

    if chunk_id:
        to_process = [c for c in chunks if c["id"] == chunk_id]
    else:
        to_process = [c for c in chunks if c.get("status") == "synth_done"]

    if not to_process:
        print("No chunks to process")
        return

    print(f"=== P3: Transcribing {len(to_process)} chunk(s) ===\n")

    if server_url:
        _batch_via_http(chunks, to_process, audiodir, outdir, server_url)
    else:
        load_models()
        _batch_local(chunks, to_process, audiodir, outdir)

    # 回写 chunks.json
    with open(chunks_path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)

    ok = sum(1 for c in to_process if c.get("status") == "transcribed")
    print(f"\n=== Done: {ok}/{len(to_process)} transcribed ===")

    failed = len(to_process) - ok
    if failed > 0:
        print(f"  {failed} chunk(s) failed transcription")
        sys.exit(1)


def _batch_local(chunks, to_process, audiodir, outdir):
    for chunk in to_process:
        audio_path = os.path.join(audiodir, f"{chunk['id']}.wav")
        if not os.path.exists(audio_path):
            print(f"  [SKIP] {chunk['id']}: {audio_path} not found")
            chunk["status"] = "transcribe_failed"
            chunk["error"] = f"audio not found: {audio_path}"
            continue

        print(f"  [TRANSCRIBE] {chunk['id']}...")
        try:
            result = transcribe_audio(audio_path)
            output = format_output(
                chunk["id"], chunk.get("shot_id", ""),
                chunk["text"], chunk["text_normalized"], result
            )

            out_path = os.path.join(outdir, f"{chunk['id']}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)

            print(f"    → {out_path}")
            print(f"    转写: {output['full_transcribed_text'][:60]}...")
            chunk["status"] = "transcribed"

        except Exception as e:
            print(f"    [ERROR] {chunk['id']}: {e}")
            chunk["status"] = "transcribe_failed"
            chunk["error"] = str(e)


def _batch_via_http(chunks, to_process, audiodir, outdir, server_url):
    import urllib.request
    # 本地 server 不走代理
    os.environ["no_proxy"] = "127.0.0.1,localhost"

    for chunk in to_process:
        audio_path = os.path.abspath(os.path.join(audiodir, f"{chunk['id']}.wav"))
        if not os.path.exists(audio_path):
            print(f"  [SKIP] {chunk['id']}: {audio_path} not found")
            chunk["status"] = "transcribe_failed"
            chunk["error"] = f"audio not found: {audio_path}"
            continue

        print(f"  [TRANSCRIBE via HTTP] {chunk['id']}...")
        try:
            body = json.dumps({
                "audio_path": audio_path,
                "chunk_id": chunk["id"],
                "shot_id": chunk.get("shot_id", ""),
                "text": chunk["text"],
                "text_normalized": chunk["text_normalized"],
                "outdir": os.path.abspath(outdir),
            }).encode()

            req = urllib.request.Request(
                f"{server_url}/transcribe",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read())

            if "error" in result:
                raise Exception(result["error"])

            print(f"    转写: {result['full_transcribed_text'][:60]}...")
            chunk["status"] = "transcribed"

        except Exception as e:
            print(f"    [ERROR] {chunk['id']}: {e}")
            chunk["status"] = "transcribe_failed"
            chunk["error"] = str(e)


# =============================================================
# Entry
# =============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="P3: WhisperX Agent")
    parser.add_argument("--server", action="store_true", help="Run as HTTP server")
    parser.add_argument("--port", type=int, default=5555, help="Server port (default: 5555)")
    parser.add_argument("--chunks", default=None, help="Path to chunks.json (batch mode)")
    parser.add_argument("--audiodir", default=None, help="Directory with chunk WAV files")
    parser.add_argument("--outdir", default=None, help="Output directory for transcription JSON")
    parser.add_argument("--chunk", default=None, help="Process only this chunk ID")
    parser.add_argument("--server-url", default=None, help="P3 server URL for batch-via-HTTP mode")
    args = parser.parse_args()

    if args.server:
        run_server(args.port)
    elif args.chunks and args.audiodir and args.outdir:
        run_batch(args.chunks, args.audiodir, args.outdir, args.chunk, args.server_url)
    else:
        parser.print_help()
        sys.exit(1)
