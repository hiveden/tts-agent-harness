/**
 * PipelineRunner port — pipeline operations.
 *
 * All methods return { flowRunId: string } (Prefect flow run ID).
 */

import type { ChunkId, EpisodeId, StageName } from "../types";

export interface PipelineRunner {
  run(epId: EpisodeId): Promise<{ flowRunId: string }>;

  retry(
    epId: EpisodeId,
    cid: ChunkId,
    fromStage: StageName,
    cascade?: boolean,
  ): Promise<{ flowRunId: string }>;

  finalizeTake(
    epId: EpisodeId,
    cid: ChunkId,
    takeId: string,
  ): Promise<{ flowRunId: string }>;
}
