/**
 * PipelineRunner implementation backed by FastAPI REST API.
 */

import type { ChunkId, EpisodeId, StageName } from "../../types";
import type { PipelineRunner } from "../../ports/runner";
import { apiPost } from "./http-client";

interface FlowRunResponse {
  flow_run_id: string;
}

export class ApiPipelineRunner implements PipelineRunner {
  async run(epId: EpisodeId): Promise<{ flowRunId: string }> {
    const res = await apiPost<FlowRunResponse>(
      `/episodes/${encodeURIComponent(epId)}/run`,
    );
    return { flowRunId: res.flow_run_id };
  }

  async retry(
    epId: EpisodeId,
    cid: ChunkId,
    fromStage: StageName,
    cascade = true,
  ): Promise<{ flowRunId: string }> {
    const res = await apiPost<FlowRunResponse>(
      `/episodes/${encodeURIComponent(epId)}/chunks/${encodeURIComponent(cid)}/retry`,
      { from_stage: fromStage, cascade },
    );
    return { flowRunId: res.flow_run_id };
  }

  async finalizeTake(
    epId: EpisodeId,
    cid: ChunkId,
    takeId: string,
  ): Promise<{ flowRunId: string }> {
    const res = await apiPost<FlowRunResponse>(
      `/episodes/${encodeURIComponent(epId)}/chunks/${encodeURIComponent(cid)}/finalize-take`,
      { take_id: takeId },
    );
    return { flowRunId: res.flow_run_id };
  }
}
