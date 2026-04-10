/**
 * Storage ports — episode CRUD + chunk edits.
 */

import type {
  EditBatch,
  Episode,
  EpisodeId,
  EpisodeSummary,
} from "../types";

export interface EpisodeStore {
  list(): Promise<EpisodeSummary[]>;
  get(id: EpisodeId): Promise<Episode | null>;
  create(id: EpisodeId, scriptFile: File): Promise<Episode>;
  delete(id: EpisodeId): Promise<void>;
}

export interface ChunkStore {
  applyEdits(epId: EpisodeId, edits: EditBatch): Promise<void>;
}
