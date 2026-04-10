/**
 * Type mappers: FastAPI snake_case -> frontend camelCase.
 *
 * Thin mapping only — no complex data reshaping.
 */

import type {
  Chunk,
  ChunkStatus,
  Episode,
  EpisodeStatus,
  EpisodeSummary,
  StageRun,
  StageName,
  StageStatus,
  Take,
} from "../../types";

// ---------------------------------------------------------------------------
// Raw backend response shapes
// ---------------------------------------------------------------------------

export interface RawEpisodeSummary {
  id: string;
  title: string;
  status: EpisodeStatus;
  chunk_count: number;
  done_count: number;
  failed_count: number;
  updated_at: string;
}

export interface RawTake {
  id: string;
  chunk_id: string;
  audio_uri: string;
  duration_s: number;
  params: Record<string, unknown>;
  created_at: string;
}

export interface RawStageRun {
  chunk_id: string;
  stage: string;
  status: string;
  attempt: number;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  error: string | null;
  log_uri: string | null;
  prefect_task_run_id: string | null;
  stale: boolean;
}

export interface RawChunkDetail {
  id: string;
  episode_id: string;
  shot_id: string;
  idx: number;
  text: string;
  text_normalized: string;
  subtitle_text: string | null;
  status: ChunkStatus;
  selected_take_id: string | null;
  boundary_hash: string | null;
  char_count: number;
  last_edited_at: string | null;
  extra_metadata: Record<string, unknown>;
  takes: RawTake[];
  stage_runs: RawStageRun[];
}

export interface RawEpisodeDetail {
  id: string;
  title: string;
  description: string | null;
  status: EpisodeStatus;
  script_uri: string;
  config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  extra_metadata: Record<string, unknown>;
  chunks: RawChunkDetail[];
}

// ---------------------------------------------------------------------------
// Mappers
// ---------------------------------------------------------------------------

export function mapTake(raw: RawTake): Take {
  return {
    id: raw.id,
    audioUri: raw.audio_uri,
    durationS: raw.duration_s,
    params: raw.params,
    createdAt: raw.created_at,
  };
}

export function mapStageRun(raw: RawStageRun): StageRun {
  return {
    stage: raw.stage as StageName,
    status: raw.status as StageStatus,
    attempt: raw.attempt,
    startedAt: raw.started_at ?? undefined,
    finishedAt: raw.finished_at ?? undefined,
    durationMs: raw.duration_ms ?? undefined,
    error: raw.error ?? undefined,
    logUri: raw.log_uri ?? undefined,
    stale: raw.stale,
  };
}

export function mapChunk(raw: RawChunkDetail): Chunk {
  return {
    id: raw.id,
    episodeId: raw.episode_id,
    shotId: raw.shot_id,
    idx: raw.idx,
    text: raw.text,
    textNormalized: raw.text_normalized,
    subtitleText: raw.subtitle_text,
    status: raw.status,
    selectedTakeId: raw.selected_take_id,
    boundaryHash: raw.boundary_hash ?? undefined,
    charCount: raw.char_count,
    lastEditedAt: raw.last_edited_at ?? undefined,
    metadata: raw.extra_metadata ?? {},
    takes: raw.takes.map(mapTake),
    stageRuns: raw.stage_runs.map(mapStageRun),
  };
}

export function mapEpisodeDetail(raw: RawEpisodeDetail): Episode {
  return {
    id: raw.id,
    title: raw.title,
    description: raw.description,
    status: raw.status,
    scriptUri: raw.script_uri,
    config: raw.config,
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
    metadata: raw.extra_metadata ?? {},
    chunks: raw.chunks.map(mapChunk),
  };
}

export function mapEpisodeSummary(raw: RawEpisodeSummary): EpisodeSummary {
  return {
    id: raw.id,
    title: raw.title,
    status: raw.status,
    chunkCount: raw.chunk_count,
    doneCount: raw.done_count,
    failedCount: raw.failed_count,
    updatedAt: raw.updated_at,
  };
}
