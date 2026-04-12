import type { StageName } from "./types";

export interface StageInfo {
  title: string;
  description: string;
  inputs: string;
  outputs: string;
  failure: string;
}

export const STAGE_INFO: Record<StageName, StageInfo> = {
  p1: {
    title: "P1 · 脚本切分",
    description: "将 script.json 的 segments 按句切分成 chunks。每个 chunk 是一个独立的合成单元。",
    inputs: "script.json（MinIO）",
    outputs: "chunks 列表（DB）",
    failure: "script.json 格式错误 / MinIO 读取失败",
  },
  p1c: {
    title: "P1c · 输入校验",
    description: "校验 chunks 合法性，在 TTS 调用前拦截可预见的问题",
    inputs: "chunks 列表（DB）",
    outputs: "校验通过 / 错误报告",
    failure: "chunk 文本为空 / 字段缺失 / 格式不合规",
  },
  p2: {
    title: "P2 · TTS 合成",
    description: "调用 Fish Audio S2-Pro API，将 chunk 的 text_normalized 合成为 WAV 音频。参数从 episode.config 读取（temperature / top_p / speed / reference_id）。",
    inputs: "chunk.textNormalized + episode.config",
    outputs: "WAV 音频（MinIO）+ take 记录（DB）",
    failure: "Fish API 401（key 无效）/ 429（限流）/ 超时 / 空响应",
  },
  p2c: {
    title: "P2c · 格式校验",
    description: "校验 WAV 文件格式合法性，在 ASR 之前拦截坏文件",
    inputs: "take WAV 音频（MinIO）",
    outputs: "校验通过 / 错误报告",
    failure: "WAV 文件损坏 / 采样率不符 / 空文件",
  },
  p2v: {
    title: "P2v · 内容验证",
    description: "ASR 转写 + 原文比对做质量校验，同时产出 transcript",
    inputs: "take WAV 音频 + chunk.textNormalized",
    outputs: "transcript.json（MinIO）+ 质量评分",
    failure: "ASR 转写失败 / 内容偏差超阈值",
  },
  p3: {
    title: "P3 · WhisperX 转写",
    description: "将合成的 WAV 音频发送到 WhisperX 服务，获取 word-level 时间戳的 transcript。用于后续字幕生成。",
    inputs: "take WAV 音频（MinIO）",
    outputs: "transcript.json（MinIO）— 含每个字的 start/end/score",
    failure: "WhisperX 服务不可用 / 音频格式不支持 / 空 transcript",
  },
  p5: {
    title: "P5 · 字幕生成",
    description: "根据 transcript 的 word 时间戳，按字符数加权分配时间，生成 SRT 格式字幕文件。字幕来源优先用 subtitleText，否则用 text（去掉控制标记）。",
    inputs: "transcript.json + chunk.subtitleText / chunk.text",
    outputs: "subtitle.srt（MinIO）",
    failure: "transcript 为空 / chunk 无 selected_take",
  },
  p6: {
    title: "P6 · 音频拼接",
    description: "将所有 chunk 的 WAV 按 shot 顺序拼接成一个完整的 episode 音频，同时合并字幕并偏移时间戳。chunk 间插入 200ms 静音，shot 间 500ms。",
    inputs: "所有 chunk 的 take WAV + subtitle SRT",
    outputs: "final/episode.wav + final/episode.srt（MinIO）",
    failure: "某 chunk 无 selected_take / ffmpeg 错误 / MinIO 写入失败",
  },
  p6v: {
    title: "P6v · 端到端验证",
    description: "最终产物完整性校验，检查字幕覆盖率和时间戳",
    inputs: "final/episode.wav + final/episode.srt",
    outputs: "校验通过 / 错误报告",
    failure: "字幕覆盖率不足 / 时间戳 gap/overlap 超阈值",
  },
};
