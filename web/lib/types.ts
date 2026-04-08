/**
 * Domain types — TTS Harness MVP
 *
 * 这是面向 frontend 和 Route Handler 的"干净"业务类型,
 * 与 chunks.json 的原始字段(snake_case)解耦。
 *
 * 规则:
 * - 全部 camelCase
 * - 允许 metadata: Record<string, unknown> 留扩展位
 * - 任何字段添加只增不删
 * - 这个文件不能 import 任何 adapter 实现
 */

// ============================================================
// IDs
// ============================================================

export type EpisodeId = string;
export type ChunkId = string;
export type ShotId = string;
export type TakeId = string;
export type JobId = string;

// ============================================================
// Status enums
// ============================================================

/** Episode 整体状态(从文件系统推断,不是 chunks.json 字段) */
export type EpisodeStatus =
  | "empty" // 没 script.json
  | "ready" // 有 script,未跑 pipeline
  | "running" // pipeline 进行中
  | "failed" // 上次 exit !== 0
  | "done"; // 有完整 output

/** Chunk 工作流状态(对应 chunks.json status 字段) */
export type ChunkStatus =
  | "pending"
  | "synth_done"
  | "transcribed"
  | "failed";

// ============================================================
// Take (multi-take 支持)
// ============================================================

/** 一次合成的音频。multi-take 时一个 chunk 可能有多个 take */
export interface Take {
  id: TakeId;
  /** 文件名(相对 .work/<ep>/audio/),不含路径 */
  file: string;
  durationS: number;
  createdAt: string; // ISO ts
  /** 合成参数(temperature/top_p/seed 等),扩展用 */
  params?: Record<string, unknown>;
}

// ============================================================
// Chunk
// ============================================================

export interface Chunk {
  id: ChunkId;
  shotId: ShotId;
  /** 在 shot 内的序号(从 1 开始) */
  index: number;

  // —— 三个文本字段 ——
  /** 原文(P1 切分后,只读参考) */
  text: string;
  /** TTS 朗读用,改了触发 P2/P3/P5/P6 */
  textNormalized: string;
  /** 字幕显示用(可选),改了只触发 P5/P6 */
  subtitleText: string | null;

  // —— 状态与产物 ——
  status: ChunkStatus;
  /** 全部 take 列表(MVP 大多 chunk 只有 1 个) */
  takes: Take[];
  /** 当前生效的 take id;P5/P6 拼接时使用 */
  selectedTakeId: TakeId | null;

  // —— 元信息 ——
  charCount: number;
  /** 边界 hash(由 shotId + index + text 计算,变了 → 失效下游) */
  boundaryHash?: string;

  /** 扩展位:任何 adapter 想多带的信息塞这里 */
  metadata: Record<string, unknown>;
}

// ============================================================
// Episode
// ============================================================

export interface Episode {
  id: EpisodeId;
  status: EpisodeStatus;
  /** 当前 stage 的 opaque 描述,前端只显示不解析 */
  currentStage: string | null;
  /** 全部 chunks(读详情时返回) */
  chunks: Chunk[];
  /** 全部 chunk 时长之和 */
  totalDurationS: number;
  createdAt: string;
  updatedAt: string;
  metadata: Record<string, unknown>;
}

/** 列表项,无 chunks(给 sidebar 用) */
export interface EpisodeSummary {
  id: EpisodeId;
  status: EpisodeStatus;
  currentStage: string | null;
  chunkCount: number;
  updatedAt: string;
}

// ============================================================
// Edits / Apply
// ============================================================

/** 单个 chunk 的编辑。两个字段都可选,只填想改的 */
export interface ChunkEdit {
  /** 改了 → 触发 P2 + P3 + P5 + P6 */
  textNormalized?: string;
  /** 改了 → 只触发 P5 + P6 */
  subtitleText?: string;
}

/** 批量 Apply 的载荷 */
export type EditBatch = Record<ChunkId, ChunkEdit>;

// ============================================================
// Job / Operation
// ============================================================

/** PipelineRunner 的所有方法都返回这个,代表"已开始执行" */
export interface OperationResult {
  jobId: JobId;
  startedAt: string;
}

export type JobState =
  | "queued"
  | "running"
  | "done"
  | "failed"
  | "canceled";

export interface JobStatus {
  id: JobId;
  state: JobState;
  startedAt: string;
  finishedAt: string | null;
  exitCode: number | null;
  error: string | null;
  /** 如果属于某个 episode */
  episodeId?: EpisodeId;
}

// ============================================================
// Errors
// ============================================================

/** Adapter / Domain 层抛错时,给 Route Handler 转 HTTP code 用 */
export class DomainError extends Error {
  constructor(
    message: string,
    public code:
      | "not_found"
      | "lock_busy"
      | "invalid_state"
      | "invalid_input"
      | "internal",
    public details?: unknown,
  ) {
    super(message);
    this.name = "DomainError";
  }
}
