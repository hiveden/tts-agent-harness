/**
 * Service factory — minimal, kept for backward compat with Next.js API routes.
 *
 * The main UI uses hooks.ts which calls FastAPI directly.
 * This factory is only used by legacy Next.js API route handlers.
 */

import type { ChunkStore, EpisodeStore } from "./ports";
import type { PipelineRunner } from "./ports/runner";
import { ApiEpisodeStore, ApiChunkStore, ApiPipelineRunner } from "./adapters/api";

export interface Services {
  episodes: EpisodeStore;
  chunks: ChunkStore;
  runner: PipelineRunner;
}

let _services: Services | null = null;

export function getServices(): Services {
  if (_services) return _services;

  _services = {
    episodes: new ApiEpisodeStore(),
    chunks: new ApiChunkStore(),
    runner: new ApiPipelineRunner(),
  };

  return _services;
}

export function _resetServices(services?: Services): void {
  _services = services ?? null;
}
