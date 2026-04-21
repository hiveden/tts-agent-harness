# 竞品分析：Pixelle-Video TTS 模块

> 源项目：https://github.com/AIDC-AI/Pixelle-Video
> 分析日期：2026-04-21
> 对标范围：TTS 合成 + 字幕对齐 + 视频拼接管线

## 一、定位对比

| 维度 | **Pixelle-Video** | **tts-agent-harness（本项目）** |
|------|-------------------|--------------------------------|
| 项目目标 | AI 全自动短视频一键生成（选题 → 成片） | 确定性 TTS + 字幕生产管线，专注"可控交付" |
| 用户场景 | 内容创作者一键出片 | 工程/播客流程中，per-shot WAV + 精准字幕交给下游 Remotion |
| 产品形态 | ComfyUI 工作流 + Windows 一键包 | Web UI + FastAPI + Prefect + PostgreSQL + MinIO |
| Stars | 4.7k | —（内部工具） |

## 二、TTS 引擎

| | Pixelle-Video | 本项目 |
|---|---|---|
| 默认引擎 | **Edge-TTS**（微软云端免费）为主，另支持 Index-TTS / ComfyUI / RunningHub 工作流 | **Fish Audio S2-Pro** 单一商用 API |
| 音色 | 30 个预置音色（10 语言，`tts_voices.py`） | Fish 声音克隆 `reference_id`（单音色） |
| 自定义参数 | voice / speed / reference audio | `normalize: false`（S2-Pro 原样处理） |
| 稳定性 | Edge-TTS 服务偶发不稳，近期 "locked edge-tts version to fix" | Fish API 稳定，但英文缩写/品牌名发音不稳 |

**差异点**：Pixelle 走"多引擎 + 免费音色"路线拉低门槛；本项目押注 Fish S2-Pro 的音质和声音克隆，牺牲多样性换质量。

## 三、音频-字幕对齐（核心差异）

这是两个项目架构哲学差异最大的地方。

### Pixelle-Video：**不做字幕对齐**

- `services/tts_service.py` 只返回音频文件路径，**无 word-level timing、无 ASR、无 SRT**。
- `frame_processor.py` 的同步策略极简：
  1. TTS 合成 → `ffmpeg.probe()` 取时长
  2. 把 `duration` 传给视频生成工作流，**让视频时长 = 音频时长**
  3. 文案通过 HTML 模板**烧录进画面**（`frame.narration` → 静态文字层）
- 结论：**"一句话 = 一个 shot = 一张带字画面"**，不存在"字幕卡按字滚动"的概念。

### 本项目：**字符级锚定 + 插值对齐 + 可编辑字幕卡**

- P2v WhisperX 转写 → `asr_normalize.py` 简繁归一 → `char_alignment.py` 字符级锚定 → `p5_logic.py` 插值生成 cue
- 字幕 cue 结构化存 `chunks.metadata.subtitle_cues`，前端 karaoke 按 cue 精确高亮
- ASR 错听严重 chunk 可通过 `SubtitleTimingEditor` 手动微调
- 输出 `subtitles.json` 交给 Remotion 做动态字幕

**对比结论**：

- Pixelle 的"字幕"本质是**静态图层文字**，不需要对齐，实现成本极低但下游丧失动画自由度。
- 本项目的字幕是**结构化时间轴数据**，承担了 Pixelle 完全不做的复杂度（ASR + 对齐 + 人工兜底），换来可编辑性与 Remotion 的精细动画能力。

## 四、Pipeline 对比

| 阶段 | Pixelle-Video `StandardPipeline` | 本项目 |
|------|----------------------------------|--------|
| 1 | setup_environment | — |
| 2 | generate_content（LLM 写脚本） | 用户上传 `script.json` |
| 3 | determine_title | — |
| 4 | plan_visuals（LLM 生图 prompt） | — |
| 5 | initialize_storyboard | P1 切分 + P1c 校验 |
| 6 | **produce_assets（TTS + 图像 + 渲帧）** | P2 合成 + P2c 校验 + **P2v 转写验证**（Pixelle 无） |
| 7 | post_production（拼接 + BGM） | **P5 字幕对齐**（Pixelle 无）+ P6 拼接 + P6v 端到端验证 |
| 8 | finalize | 导出 zip 给 Remotion |

**关键缺失**：Pixelle 没有 P2v（转写验证）和 P5（字幕对齐）。它不需要，因为"字幕 = 画面贴图"。

## 五、确定性与可编辑性

| | Pixelle-Video | 本项目 |
|---|---|---|
| 流程性质 | 端到端黑盒生成 | 分 stage 确定性，可逐 chunk 重试/编辑 |
| 单 chunk 重试 | 不突出 | UI 上 ✎ 编辑 text 重跑 P2；⏱ 微调 cue |
| 状态机 | 隐式 | 显式 `pending → synth_done → verified → done` |
| 日志可追溯 | 未见规范 | `grep chunk=X` 追全链路 |

## 六、架构与工程

| | Pixelle-Video | 本项目 |
|---|---|---|
| 技术栈 | ComfyUI 工作流 + Python services | FastAPI + Prefect + PostgreSQL + MinIO + React |
| 存储 | 文件系统 + history_manager | PG + 对象存储（MinIO） |
| 并发 | RunningHub 多 frame 并行 | Prefect task 并行 |
| 前端 | 无（CLI/配置为主） | Web UI 含 karaoke 预览 + 字幕微调 |

## 七、可借鉴与差异化定位

### 可以借鉴 Pixelle 的点

1. **多引擎适配层** — 本项目目前锁 Fish 单一引擎，`CLAUDE.md` 明确写"当前只支持"。可以参考 Pixelle 的 `tts_service.py` 抽象一个 provider 接口，后续加 Edge-TTS 作为免费 fallback，对比音质。
2. **音频时长驱动视频时长** — Pixelle 的 `media_params["duration"] = frame.duration` 思路简洁，可在本项目 P6 拼接阶段复用（虽然我们已经有 padding/gap 处理）。
3. **音色预设体系** — `tts_voices.py` 的 locale/gender/label 三元组 schema 很干净，如果本项目后续开放多 `reference_id`，可参考其数据结构。

### 本项目的核心差异化优势

1. **字幕是一等公民** —— 字符级对齐 + 人工微调，Pixelle 这条路径根本不存在。
2. **生产级确定性** —— 状态机、stage 校验、结构化日志，面向"交付给下游 Remotion"而不是"一键出成品"。
3. **可重跑粒度** —— chunk 级编辑 + 重试，Pixelle 是整 pipeline 重跑。

### 结论

两个项目不在同一赛道。Pixelle 是消费级"AI 出片机"，靠 Edge-TTS 的免费音色和烧录字幕压缩实现成本；本项目是工程级"素材加工厂"，TTS 后的 ASR 验证 + 字符对齐字幕才是护城河。

若向 Pixelle 方向扩展，优先引入**多 TTS provider 抽象**；其他组件（字幕 / 管线 / 验证）本项目更成熟。

## 附：参考文件清单

Pixelle-Video 侧：
- `pixelle_video/services/tts_service.py` — TTS 服务封装
- `pixelle_video/services/frame_processor.py` — 音视频同步核心
- `pixelle_video/services/video.py` — ffmpeg 拼接
- `pixelle_video/pipelines/standard.py` — 8 阶段 pipeline
- `pixelle_video/tts_voices.py` — 30 音色配置

本项目侧：
- `server/flows/tasks/p2_synth.py` / `p2v_verify.py` / `p5_subtitles.py`
- `server/core/char_alignment.py` / `asr_normalize.py` / `p5_logic.py`
- `docs/design-p5-subtitle-alignment.md`
