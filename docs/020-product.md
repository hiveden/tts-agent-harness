# TTS Agent Harness — 产品功能文档

## 产品定位

视频脚本转语音 + 字幕的生产工具。解决的核心问题：**TTS 引擎对中英混合文本的发音不稳定，需要反复调整文本、试听、重试，直到每一句都准确为止**。

传统流程是手动调用 TTS API → 下载音频 → 本地试听 → 修改文本 → 重新调用，循环往复。本工具将这个过程产品化：上传脚本 → 自动合成 → 逐句试听 → 一键修改重试 → 导出成品。

## 目标用户

视频创作者、播客制作者，需要将文字稿批量转为高质量语音，并生成对应的时间轴字幕。

## 核心工作流

```
上传脚本 → 自动切分 → 批量合成 → 逐句质检 → 修改重试 → 导出产物
```

### 1. 上传脚本

输入一个 JSON 格式的视频脚本，包含标题和分段文本：

```json
{
  "title": "AI 基础设施概览",
  "segments": [
    { "id": 1, "type": "hook", "text": "OpenAI 刚发布了 GPT-V..." },
    { "id": 2, "type": "content", "text": "第Ⅱ章，我们来回顾 transformer..." }
  ]
}
```

每个 segment 对应视频的一个镜头（shot），`text` 同时作为 TTS 输入和字幕来源。

### 2. 自动切分（P1）

系统按 segment 将脚本切分为 chunks，每个 chunk 是独立的合成单元。切分后会自动校验格式合法性。

### 3. 批量合成（P2 → P2c → P2v）

点击"合成全部"，系统对每个 chunk 执行：

- **P2 TTS 合成**：调用 Fish Audio S2-Pro API，将文本合成为 WAV 音频
- **P2c WAV 校验**：验证音频格式（采样率、声道数、时长）
- **P2v 转写验证**：用 ASR（Groq Whisper）将音频转写回文字，与原文比对，检测发音偏差

每个 chunk 可以独立重试，不影响其他 chunk。

### 4. 逐句试听与质检

合成完成后，每个 chunk 显示：

- **播放按钮**：试听当前 take 的音频
- **卡拉 OK 字幕**：播放时逐字高亮，可点击任意文字跳转到对应时间点
- **Stage 进度条**：可视化每个处理阶段的状态（完成/失败/运行中）
- **历史 Take 列表**：保留每次合成的结果，可对比不同版本

### 5. 修改文本与重试

当 TTS 发音不准确时（常见于英文缩写、品牌名、中英混合文本）：

1. 点击 chunk 的编辑按钮
2. 修改 TTS 源文本（`text_normalized`），例如：
   - `第Ⅱ章` → `第2章`（罗马数字读错）
   - `transformer` → `trans former`（加空格帮助断词）
   - `USB-C` → `USB type C`（缩写展开）
3. 点击 "Stage Change" 暂存修改
4. 点击 "Apply All" 统一执行
5. 系统只对修改过的 chunk 重新合成，保留未修改的结果

修改后的新 take 会追加到历史列表，可随时切换回之前的版本。

### 6. 字幕生成（P5）

合成通过验证后，系统基于音频时长和字符分布，自动生成时间对齐的逐字字幕。TTS 控制标记（`[break]`、`[breath]`、`[long break]`等）会被自动过滤，不出现在字幕中。

### 7. 拼接与导出（P6）

所有 chunk 验证通过后，系统自动：

- 按 shot 拼接音频，插入 padding 和间隔
- 偏移字幕时间戳，对齐拼接后的时间线
- 打包导出 zip

导出产物：

```
episode-export.zip/
  shot01.wav          — 每个镜头的拼接音频
  shot02.wav
  ...
  durations.json      — [{id, duration_s, file}]
  subtitles.json      — {shot_id: [{id, text, start, end}]}
```

下游可直接被 Remotion 等视频合成框架消费。

## 功能特性

### API Key 管理

- 用户在页面配置自己的 Fish Audio 和 Groq API Key
- Key 通过加密 Cookie 存储在服务端，不会明文传输或出现在日志中
- 保存时自动验证 Key 有效性

### TTS 配置

每个脚本可携带 `tts_config` 覆盖默认参数：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| model | TTS 模型 | s2-pro |
| temperature | 采样温度 | 0.3 |
| top_p | Nucleus sampling | 0.5 |
| speed | 语速（后处理 atempo） | 1.25 |
| reference_id | 声音克隆 ID | 无 |
| normalize | 是否让引擎做文本归一化 | false |

### 控制标记

文本中可插入 S2-Pro 控制标记，用于精细控制语音节奏：

- `[break]` / `[long break]` — 停顿
- `[breath]` / `[inhale]` — 呼吸声
- `[pause]` / `[long pause]` — 兼容写法

这些标记只影响 TTS 合成，字幕生成时会自动过滤。

### Episode 管理

- **创建**：上传 script.json，指定 episode ID
- **锁定/解锁**：锁定后不可修改，防止误操作和自动清理
- **自动清理**：存储超限时按时间顺序删除最旧的未锁定 episode
- **归档**：标记为归档状态

### 主题

支持浅色/深色主题，跟随系统偏好或手动切换。

## 技术架构

```
浏览器 → Caddy (反向代理) → FastAPI + Next.js
                              ↓
                    PostgreSQL + MinIO/Tigris
```

- **TTS 引擎**：Fish Audio S2-Pro
- **ASR 引擎**：Groq Whisper API（线上）/ WhisperX（本地）
- **后端**：FastAPI + SQLAlchemy + Alembic
- **前端**：Next.js 16 + Zustand + Tailwind CSS v4 + Radix UI
- **存储**：PostgreSQL（元数据）+ MinIO/Tigris（音频文件）
- **音频处理**：ffmpeg
- **部署**：Fly.io（东京机房）

## 已知限制

- Fish Audio S2-Pro 对英文缩写和品牌名的发音不稳定，需要人工调整 text_normalized
- 合成速度取决于 Fish Audio API 响应，高峰期可能较慢
- 当前不支持多声音（每个 episode 使用同一个 reference_id）
- 字幕时间戳基于字符加权分配，非精确音素级对齐
