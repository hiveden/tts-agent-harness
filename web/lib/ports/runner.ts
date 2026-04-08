/**
 * PipelineRunner port — pipeline 的全部业务操作集中在这一个接口
 *
 * MVP 实现: LegacyPipelineRunner (spawn run.sh + p2-synth.js)
 * 未来扩展: NodeOrchestratorRunner / TemporalRunner
 *
 * 所有方法返回 OperationResult 而非阻塞,符合 async job 模型。
 * 进度查询走 ProgressSource。
 */

import type {
  ChunkId,
  EditBatch,
  EpisodeId,
  JobId,
  JobStatus,
  OperationResult,
} from "../types";

export interface PipelineRunner {
  /** 跑全量 pipeline (P1 → P6) */
  runFull(
    epId: EpisodeId,
    options?: {
      /** "fresh" = 从 P1 重切;"text-only" = 只更新 text 不重切边界 */
      mode?: "fresh" | "text-only";
      /** hash mismatch 时是否强制 */
      force?: boolean;
    },
  ): Promise<OperationResult>;

  /**
   * 批量重做。
   * 根据 dirty 类型决定走哪些 stage:
   *   有 textNormalized 改动 → P2 + P3 + P5 + P6
   *   只有 subtitleText 改动 → P5 + P6
   */
  applyEdits(
    epId: EpisodeId,
    edits: EditBatch,
  ): Promise<OperationResult>;

  /**
   * 单 chunk 重试 N 次,生成 N 个新 take。
   * 不走 P3/P5/P6,等用户 finalize 才跑。
   * 用 chunk lock,不占全局 lock,允许多 chunk 同时 retry。
   */
  retryChunk(
    epId: EpisodeId,
    cid: ChunkId,
    options: {
      count: number;
      params?: Record<string, unknown>;
    },
  ): Promise<OperationResult>;

  /**
   * 用户在 TakeSelector 选定 take 后调用。
   * 同步 selected_take 到 chunks.json,跑 P3 + P5 + P6。
   */
  finalizeTake(
    epId: EpisodeId,
    cid: ChunkId,
  ): Promise<OperationResult>;

  /** 取消正在跑的 job(MVP 可不实现,留接口) */
  cancel(jobId: JobId): Promise<void>;

  /** 查询 job 状态 */
  getJobStatus(jobId: JobId): Promise<JobStatus>;
}
