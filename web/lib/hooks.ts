"use client";

import { useEffect } from "react";
import useSWR from "swr";
import type { ChunkEdit, Episode, EpisodeSummary, StageName } from "./types";
import { apiGet, apiPost, apiPostForm, getApiUrl } from "./adapters/api/http-client";
import type { RawEpisodeDetail, RawEpisodeSummary } from "./adapters/api/mappers";
import { mapEpisodeDetail, mapEpisodeSummary } from "./adapters/api/mappers";
import { connectSSE } from "./sse-client";
import type { StageEventData } from "./sse-client";

// ---------------------------------------------------------------------------
// SWR fetchers
// ---------------------------------------------------------------------------

const episodeListFetcher = async (): Promise<EpisodeSummary[]> => {
  const raw = await apiGet<RawEpisodeSummary[]>("/episodes");
  return raw.map(mapEpisodeSummary);
};

const episodeDetailFetcher = async (id: string): Promise<Episode> => {
  const raw = await apiGet<RawEpisodeDetail>(
    `/episodes/${encodeURIComponent(id)}`,
  );
  return mapEpisodeDetail(raw);
};

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
  const swr = useSWR<EpisodeSummary[]>("api:episodes", episodeListFetcher);
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
    () => episodeDetailFetcher(id!),
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
      (_event: StageEventData) => {
        mutate();
      },
      () => {
        // SSE error — SWR polling is fallback
      },
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
// Imperative operations
// ---------------------------------------------------------------------------

export async function createEpisode(id: string, file: File): Promise<void> {
  const fd = new FormData();
  fd.append("id", id);
  fd.append("script", file);
  await apiPostForm("/episodes", fd);
}

export async function deleteEpisode(id: string): Promise<void> {
  const { apiDelete } = await import("./adapters/api/http-client");
  await apiDelete(`/episodes/${encodeURIComponent(id)}`);
}

export async function runEpisode(id: string): Promise<string> {
  const res = await apiPost<{ flow_run_id: string }>(
    `/episodes/${encodeURIComponent(id)}/run`,
  );
  return res.flow_run_id;
}

export async function applyEdits(
  id: string,
  edits: Record<string, ChunkEdit>,
): Promise<void> {
  const entries = Object.entries(edits);
  for (const [cid, edit] of entries) {
    const body: Record<string, unknown> = {};
    if (edit.textNormalized !== undefined) body.text_normalized = edit.textNormalized;
    if (edit.subtitleText !== undefined) body.subtitle_text = edit.subtitleText;
    await apiPost(
      `/episodes/${encodeURIComponent(id)}/chunks/${encodeURIComponent(cid)}/edit`,
      body,
    );

    const fromStage = edit.textNormalized !== undefined ? "p2" : "p5";
    await apiPost(
      `/episodes/${encodeURIComponent(id)}/chunks/${encodeURIComponent(cid)}/retry`,
      { from_stage: fromStage, cascade: true },
    );
  }
}

export async function retryChunk(
  epId: string,
  cid: string,
  fromStage: StageName,
  cascade = true,
): Promise<string> {
  const res = await apiPost<{ flow_run_id: string }>(
    `/episodes/${encodeURIComponent(epId)}/chunks/${encodeURIComponent(cid)}/retry`,
    { from_stage: fromStage, cascade },
  );
  return res.flow_run_id;
}

export async function finalizeTake(
  epId: string,
  cid: string,
  takeId: string,
): Promise<string> {
  const res = await apiPost<{ flow_run_id: string }>(
    `/episodes/${encodeURIComponent(epId)}/chunks/${encodeURIComponent(cid)}/finalize-take`,
    { take_id: takeId },
  );
  return res.flow_run_id;
}

/** Convert a MinIO URI to an accessible URL via the API proxy. */
export function getAudioUrl(audioUri: string): string {
  // audioUri is a MinIO key like "episodes/ch04/audio/shot01_chunk01.wav"
  // Proxy through FastAPI. Encode the full URI as a path param.
  return `${getApiUrl()}/audio/${encodeURIComponent(audioUri)}`;
}
