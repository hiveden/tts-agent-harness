# CLAUDE.md — TTS Agent Harness

确定性视频脚本转语音加字幕生产工具。输入脚本 JSON，输出 per-shot WAV + 时间对齐字幕。

**当前只支持**：Fish Audio TTS（S2-Pro）+ WhisperX（本地）。

## 架构速查

```
Web UI → FastAPI → Prefect Tasks → PostgreSQL + MinIO
```

### Pipeline

```
P1 切分 → P1c 校验 → P2 TTS合成 → P2c WAV校验 → P2v 转写验证 → P5 字幕 → P6 拼接 → P6v 端到端验证
```

| Task (server/flows/tasks/) | 作用 | 确定性 |
|----------------------------|------|--------|
| `p1_chunk.py` | 按句切分 script.json | 是 |
| `p1c_check.py` | 校验 chunks 合法性 | 是 |
| `p2_synth.py` | Fish TTS S2-Pro 合成 WAV | 否（API） |
| `p2c_check.py` | WAV 格式校验 | 是 |
| `p2v_verify.py` | WhisperX 转写 + 原文比对 | 否（模型） |
| `p5_subtitles.py` | 字符级锚定+插值字幕对齐，生成 SRT | 是 |
| `p6_concat.py` | ffmpeg 拼接 + padding/gap + 字幕偏移 | 是 |
| `p6v_check.py` | 端到端验证：覆盖率/gap/overlap | 是 |

核心逻辑在 `server/core/`：
- `p5_logic.py` / `char_alignment.py` / `asr_normalize.py` — 字幕时间对齐（设计见 `docs/design-p5-subtitle-alignment.md`）
- `p6_logic.py` — 拼接 offset 计算
- `p2v_scoring.py` — ASR 转写打分

### 状态机

```
pending → synth_done → verified → done (P6 完成)
```

## 运行方式

```bash
# 启动基础设施（PostgreSQL + MinIO + Prefect）
make dev

# 启动 API + Web UI
make serve

# 打开浏览器
make open   # → http://localhost:3010
```

### 操作流程

1. Web UI 上传 script.json 创建 episode
2. 点击 Run 执行全量 pipeline
3. 逐 chunk 听音频，不满意可编辑 text 后重试（✎ 按钮）
4. 字幕时间不满意可手动微调（⏱ 按钮 → `SubtitleTimingEditor`），常用于 ASR 严重错听的极端 case
5. 全部满意后导出（per-shot WAV + 字幕 zip）

## 环境变量（.env，不进 git）

| 变量 | 必需 | 说明 |
|------|------|------|
| `FISH_TTS_KEY` | 是 | Fish TTS API 密钥 |
| `FISH_TTS_REFERENCE_ID` | 否 | 声音克隆 ID（不设则用默认声音） |
| `DATABASE_URL` | 否 | PostgreSQL 连接串（默认 localhost:55432） |
| `MINIO_ENDPOINT` | 否 | MinIO 地址（默认 localhost:59000） |

## 测试

```bash
# Python 单元测试（server 端）
cd server && python -m pytest tests/ -x

# TypeScript 类型检查（前端）
cd web && npx tsc --noEmit

# E2E 测试
cd web && npx playwright test
```

## 开发约定

- chunk 的 `text` 同时用于 TTS 输入和字幕来源
- P5 自动 strip `[break]`/`[breath]`/`[long break]`/phoneme 控制标记后再生成字幕
- P2 发送 `normalize: false`，让 S2-Pro 引擎原样处理文本
- stage task 不管 `episode.status` — 生命周期由 orchestration 层（API 路由 / Prefect flow）负责
- 所有 stage 日志遵循格式 `<STAGE> <phase> chunk=<id>|episode=<id> key=val`；`grep chunk=X` 可追踪单 chunk 全链路
- 字幕 cue 数据在 `chunks.metadata.subtitle_cues`（`[{start, end, text}]`），前端 karaoke 按 cue 边界精确高亮（cue 内字符匀速近似）

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

## 导出产物（Remotion 消费）

导出 zip 应包含：
- `<shot>.wav` — per-shot 拼接音频
- `durations.json` — `[{id, duration_s, file}]`
- `subtitles.json` — `{shot_id: [{id, text, start, end}]}`（shot-level 时间偏移）

下游项目：`astral-video`（Remotion），通过 `createSkeletonSchema()` 消费。

## 已知限制

- Fish TTS（S2-Pro）对英文缩写/品牌名的发音不稳定
- 遇到发音问题靠人工修改 text_normalized 重做
- Whisper 中文模型默认倾向繁体输出；`asr_normalize.py` 做 zhconv 简繁归一化后才参与字符对齐
- ASR 错听率 < 5% 时字幕自动对齐即可；错听严重的 chunk 需用 ⏱ 工具手动微调 cue 时间

## 归档

旧版 CLI 脚本（`run.sh` + `scripts/*.js`）已移至 `_archive/`，不再使用。
