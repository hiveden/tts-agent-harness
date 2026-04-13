# TTS Agent Harness

确定性视频脚本转语音加字幕生产工具。输入脚本 JSON，输出 per-shot WAV + 时间对齐字幕。

## 架构

```
浏览器 → Next.js (3010) → FastAPI (8100) → Prefect Tasks
                                              ↓
                                     PostgreSQL + MinIO
```

Pipeline: **P1 → P1c → P2 → P2c → P2v → P5 → P6 → P6v**

## 快速开始

```bash
# 1. 启动基础设施
make dev          # PostgreSQL + MinIO + Prefect (Docker)

# 2. 配置
cp .env.dev .env  # 编辑 FISH_TTS_KEY

# 3. 启动服务
make serve        # API :8100 + Web :3010

# 4. 打开浏览器
make open         # → http://localhost:3010
```

## 使用流程

1. 上传 script.json 创建 episode
2. 点击 Run 执行全量 pipeline
3. 逐 chunk 听音频，不满意可编辑后重试
4. 全部满意后导出（per-shot WAV + 字幕 zip）

## 脚本格式

```json
{
  "title": "Episode Title",
  "segments": [
    { "id": 1, "type": "hook", "text": "要朗读的文本，可含 [break] 控制标记。" },
    { "id": 2, "type": "content", "text": "正文内容。" }
  ]
}
```

`text` 同时用于 TTS 输入和字幕来源。S2-Pro 控制标记（`[break]`/`[breath]`/phoneme）P5 自动 strip。

## 导出格式（Remotion 消费）

```
episode.zip/
  shot01.wav, shot02.wav, ...
  subtitles.json   — {shot_id: [{id, text, start, end}]}
  durations.json   — [{id, duration_s, file}]
```

## 环境变量（.env）

| 变量 | 必需 | 说明 |
|------|------|------|
| `FISH_TTS_KEY` | 是 | Fish Audio API 密钥 |
| `FISH_TTS_REFERENCE_ID` | 否 | 声音克隆 ID |
| `DATABASE_URL` | 否 | PostgreSQL（默认 localhost:55432）|
| `MINIO_ENDPOINT` | 否 | MinIO（默认 localhost:59000）|

## 技术栈

- **TTS**: Fish Audio S2-Pro
- **ASR**: WhisperX（本地）
- **后端**: FastAPI + Prefect + SQLAlchemy
- **前端**: Next.js + Zustand + Tailwind CSS + Radix UI
- **存储**: PostgreSQL + MinIO
- **音频**: ffmpeg

## 测试

```bash
cd server && python -m pytest tests/ -x   # Python 单元测试
cd web && npx tsc --noEmit                 # TypeScript 类型检查
cd web && npx playwright test              # E2E 测试
```

## 文档

见 [docs/README.md](docs/README.md)

## License

MIT
