"use client";

import { useEffect } from "react";
import useSWR from "swr";
import type {
  AttemptRecord,
  Chunk,
  ChunkEdit,
  Episode,
  EpisodeSummary,
  StageName,
  StageRun,
  StageStatus,
  Take,
  VerifyScores,
} from "./types";
import type { components } from "./gen/openapi";
import { api, getApiUrl } from "./api-client";
import { connectSSE } from "./sse-client";
import type { StageEventData } from "./sse-client";

function apiError(err: unknown): Error {
  if (typeof err === "object" && err !== null && "detail" in err) {
    return new Error((err as { detail: string }).detail);
  }
  return new Error(typeof err === "string" ? err : JSON.stringify(err));
}

// ---------------------------------------------------------------------------
// Type aliases from generated OpenAPI schemas
// ---------------------------------------------------------------------------

type ApiEpisodeSummary = components["schemas"]["EpisodeSummary"];
type ApiEpisodeDetail = components["schemas"]["EpisodeDetail"];
type ApiChunkDetail = components["schemas"]["ChunkDetail"];
type ApiTakeView = components["schemas"]["TakeView"];
type ApiStageRunView = components["schemas"]["StageRunView"];

// ---------------------------------------------------------------------------
// Converters: generated API types → frontend domain types
//
// Backend outputs camelCase so most fields pass through, but the generated
// OpenAPI schema lags the backend in two ways:
//   1. `locked` is missing from EpisodeSummary/EpisodeDetail (server sends
//      it, schema hasn't been regenerated).
//   2. StageRunView.stage is typed `string` upstream; we narrow to StageName.
//   3. Nullable fields (`string | null`) are mapped to optional (`string?`).
//
// We read the extra fields via a structural lookup + runtime guard rather
// than a blanket `as unknown as` cast so actual schema drift fails loudly.
// ---------------------------------------------------------------------------

const STAGE_NAMES: ReadonlySet<string> = new Set<StageName>([
  "p1",
  "p1c",
  "p2",
  "p2c",
  "p2v",
  "p5",
  "p6",
  "p6v",
]);

function readLocked(raw: Record<string, unknown>): boolean {
  const v = raw["locked"];
  // Backend always sends `locked`; default to false only if truly missing
  // (old API responses during migration). Don't throw — UI just treats as
  // unlocked, which is the safe fallback.
  return typeof v === "boolean" ? v : false;
}

function ensureStageName(stage: string): StageName {
  if (!STAGE_NAMES.has(stage)) {
    throw new Error(`unknown stage name from API: ${stage}`);
  }
  return stage as StageName;
}

function toStageRun(raw: ApiStageRunView): StageRun {
  return {
    stage: ensureStageName(raw.stage),
    status: raw.status as StageStatus,
    attempt: raw.attempt,
    startedAt: raw.startedAt ?? undefined,
    finishedAt: raw.finishedAt ?? undefined,
    durationMs: raw.durationMs ?? undefined,
    error: raw.error ?? undefined,
    logUri: raw.logUri ?? undefined,
    stale: raw.stale,
  };
}

function toTake(raw: ApiTakeView): Take {
  return {
    id: raw.id,
    audioUri: raw.audioUri,
    durationS: raw.durationS,
    params: raw.params,
    createdAt: raw.createdAt,
  };
}

function toChunk(raw: ApiChunkDetail): Chunk {
  const metadata = raw.metadata ?? {};
  // attemptHistory / verifyScores / verifyDiagnosis live inside metadata
  // on the wire; surface them at the top level of the frontend Chunk.
  const meta = metadata as Record<string, unknown>;
  return {
    id: raw.id,
    episodeId: raw.episodeId,
    shotId: raw.shotId,
    idx: raw.idx,
    text: raw.text,
    textNormalized: raw.textNormalized,
    subtitleText: raw.subtitleText,
    status: raw.status,
    selectedTakeId: raw.selectedTakeId,
    boundaryHash: raw.boundaryHash ?? undefined,
    charCount: raw.charCount,
    lastEditedAt: raw.lastEditedAt ?? undefined,
    metadata,
    takes: raw.takes.map(toTake),
    stageRuns: raw.stageRuns.map(toStageRun),
    attemptHistory: meta.attemptHistory as AttemptRecord[] | undefined,
    verifyScores: meta.verifyScores as VerifyScores | undefined,
    verifyDiagnosis: meta.verifyDiagnosis as Chunk["verifyDiagnosis"],
  };
}

function toEpisodeSummary(raw: ApiEpisodeSummary): EpisodeSummary {
  return {
    id: raw.id,
    title: raw.title,
    status: raw.status,
    locked: readLocked(raw as unknown as Record<string, unknown>),
    chunkCount: raw.chunkCount,
    doneCount: raw.doneCount,
    failedCount: raw.failedCount,
    updatedAt: raw.updatedAt,
  };
}

function toEpisode(raw: ApiEpisodeDetail): Episode {
  if (!Array.isArray(raw.chunks)) {
    throw new Error("EpisodeDetail.chunks missing or not an array");
  }
  return {
    id: raw.id,
    title: raw.title,
    description: raw.description,
    status: raw.status,
    locked: readLocked(raw as unknown as Record<string, unknown>),
    scriptUri: raw.scriptUri,
    config: raw.config,
    createdAt: raw.createdAt,
    updatedAt: raw.updatedAt,
    metadata: raw.metadata ?? {},
    chunks: raw.chunks.map(toChunk),
  };
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

interface HookResult<T> {
  data: T | undefined;
  error: Error | null;
  isLoading: boolean;
  mutate: () => Promise<unknown>;
}

export function useEpisodes(): HookResult<EpisodeSummary[]> {
  const swr = useSWR<EpisodeSummary[]>("api:episodes", async () => {
    const { data, error } = await api.GET("/episodes");
    if (error) throw apiError(error);
    return (data ?? []).map(toEpisodeSummary);
  });
  return {
    data: swr.data,
    error: (swr.error as Error) ?? null,
    isLoading: swr.isLoading,
    mutate: swr.mutate,
  };
}

export function useEpisode(id: string | null): HookResult<Episode> {
  const swr = useSWR<Episode>(
    id ? `api:episode:${id}` : null,
    async () => {
      const { data, error } = await api.GET("/episodes/{episode_id}", {
        params: { path: { episode_id: id! } },
      });
      if (error) throw apiError(error);
      return toEpisode(data!);
    },
    {
      refreshInterval: (data) => (data?.status === "running" ? 2000 : 0),
    },
  );

  // SSE real-time updates
  const mutate = swr.mutate;
  useEffect(() => {
    if (!id) return;
    const conn = connectSSE(
      id,
      (_event: StageEventData) => { mutate(); },
      () => { /* SSE error — SWR polling is fallback */ },
    );
    return () => conn.close();
  }, [id, mutate]);

  return {
    data: swr.data,
    error: (swr.error as Error) ?? null,
    isLoading: swr.isLoading,
    mutate: swr.mutate,
  };
}

// ---------------------------------------------------------------------------
// Imperative operations (type-safe via openapi-fetch)
// ---------------------------------------------------------------------------

export async function createEpisode(id: string, file: File): Promise<void> {
  const { error } = await api.POST("/episodes", {
    // `as never` here is a known openapi-fetch limitation: its generated
    // body type for multipart endpoints is a string, but we pass the raw
    // object through to bodySerializer which builds the FormData. The
    // runtime payload is correct; the cast only silences the type check.
    body: { id, script: file } as never,
    bodySerializer: (body: Record<string, unknown>) => {
      const fd = new FormData();
      fd.append("id", body.id as string);
      fd.append("script", body.script as File);
      return fd;
    },
  });
  if (error) throw apiError(error);
}

export async function deleteEpisode(id: string): Promise<void> {
  const { error } = await api.DELETE("/episodes/{episode_id}", {
    params: { path: { episode_id: id } },
  });
  if (error) throw apiError(error);
}

export async function duplicateEpisode(
  id: string,
  newId: string,
): Promise<void> {
  const { error } = await api.POST("/episodes/{episode_id}/duplicate", {
    params: { path: { episode_id: id } },
    body: { newId },
  });
  if (error) throw apiError(error);
}

export async function archiveEpisode(id: string): Promise<void> {
  const { error } = await api.POST("/episodes/{episode_id}/archive", {
    params: { path: { episode_id: id } },
  });
  if (error) throw apiError(error);
}

export async function runEpisode(
  id: string,
  mode: string = "synthesize",
  chunkIds?: string[],
  maxChunkChars?: number,
): Promise<string> {
  const body: Record<string, unknown> = { mode, chunkIds: chunkIds ?? null };
  if (maxChunkChars !== undefined) body.maxChunkChars = maxChunkChars;
  const { data, error } = await api.POST("/episodes/{episode_id}/run", {
    params: { path: { episode_id: id } },
    // `body` has a dynamic shape (conditionally includes maxChunkChars). The
    // OpenAPI-generated RunRequest type is stricter; we assert the superset
    // structurally. If schema regenerates with maxChunkChars, drop `as never`.
    body: body as never,
  });
  if (error) throw apiError(error);
  return data!.flowRunId;
}

export async function applyEdits(
  id: string,
  edits: Record<string, ChunkEdit>,
): Promise<void> {
  for (const [cid, edit] of Object.entries(edits)) {
    await api.POST("/episodes/{episode_id}/chunks/{chunk_id}/edit", {
      params: {
        path: { episode_id: id, chunk_id: cid },
        query: {
          text_normalized: edit.textNormalized,
          subtitle_text: edit.subtitleText,
        },
      },
    });

    const fromStage = edit.textNormalized !== undefined ? "p2" : "p5";
    await api.POST("/episodes/{episode_id}/chunks/{chunk_id}/retry", {
      params: {
        path: { episode_id: id, chunk_id: cid },
        query: { from_stage: fromStage, cascade: true },
      },
    });
  }
}

export async function retryChunk(
  epId: string,
  cid: string,
  fromStage: StageName,
  cascade = true,
): Promise<string> {
  const { data, error } = await api.POST(
    "/episodes/{episode_id}/chunks/{chunk_id}/retry",
    {
      params: {
        path: { episode_id: epId, chunk_id: cid },
        query: { from_stage: fromStage, cascade },
      },
    },
  );
  if (error) throw apiError(error);
  return data!.flowRunId;
}

export async function finalizeTake(
  epId: string,
  cid: string,
  takeId: string,
): Promise<string> {
  const { data, error } = await api.POST(
    "/episodes/{episode_id}/chunks/{chunk_id}/finalize-take",
    {
      params: {
        path: { episode_id: epId, chunk_id: cid },
        query: { take_id: takeId },
      },
    },
  );
  if (error) throw apiError(error);
  return data!.flowRunId;
}

/** Convert a MinIO URI to an accessible URL. */
export function getAudioUrl(audioUri: string): string {
  return `${getApiUrl()}/audio/${encodeURIComponent(audioUri)}`;
}

// ---------------------------------------------------------------------------
// Subtitle timing editor — fetch transcript + PUT cues
// ---------------------------------------------------------------------------
//
// These endpoints were added after the last OpenAPI codegen run. Using
// plain fetch + hand-written types keeps us unblocked; the shapes mirror
// server/api/routes/episodes.py::get_chunk_transcript / put_chunk_cues.

export interface TranscriptWord {
  word: string;
  start: number;
  end: number;
  score?: number | null;
}

export interface ChunkTranscript {
  transcript: TranscriptWord[];
  duration_s?: number;
}

export async function fetchChunkTranscript(
  episodeId: string,
  chunkId: string,
): Promise<ChunkTranscript> {
  const url = `${getApiUrl()}/episodes/${encodeURIComponent(episodeId)}/chunks/${encodeURIComponent(chunkId)}/transcript`;
  const res = await fetch(url);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(`transcript fetch failed: ${detail}`);
  }
  return res.json();
}

export async function putChunkCues(
  episodeId: string,
  chunkId: string,
  cues: Array<{ start: number; end: number; text: string }>,
): Promise<{ cuesCount: number; subtitleUri: string }> {
  const url = `${getApiUrl()}/episodes/${encodeURIComponent(episodeId)}/chunks/${encodeURIComponent(chunkId)}/cues`;
  const res = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cues }),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(`PUT cues failed: ${detail}`);
  }
  return res.json();
}

export function useEpisodeLogs(id: string | null, tail = 50) {
  return useSWR<string[]>(
    id ? `api:logs:${id}` : null,
    async () => {
      const { data, error } = await api.GET("/episodes/{episode_id}/logs", {
        params: {
          path: { episode_id: id! },
          query: { tail },
        },
      });
      if (error) throw apiError(error);
      return data?.lines ?? [];
    },
    {
      refreshInterval: 5000,
    },
  );
}

export async function updateConfig(
  id: string,
  config: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const { data, error } = await api.PUT("/episodes/{episode_id}/config", {
    params: { path: { episode_id: id } },
    body: { config },
  });
  if (error) throw apiError(error);
  return data!.config;
}

