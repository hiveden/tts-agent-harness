/**
 * EpisodeStore implementation backed by FastAPI REST API.
 */

import type { Episode, EpisodeId, EpisodeSummary } from "../../types";
import type { EpisodeStore } from "../../ports/store";
import { apiDelete, apiGet, apiPostForm } from "./http-client";
import type { RawEpisodeDetail, RawEpisodeSummary } from "./mappers";
import { mapEpisodeDetail, mapEpisodeSummary } from "./mappers";

export class ApiEpisodeStore implements EpisodeStore {
  async list(): Promise<EpisodeSummary[]> {
    const raw = await apiGet<RawEpisodeSummary[]>("/episodes");
    return raw.map(mapEpisodeSummary);
  }

  async get(id: EpisodeId): Promise<Episode | null> {
    try {
      const raw = await apiGet<RawEpisodeDetail>(
        `/episodes/${encodeURIComponent(id)}`,
      );
      return mapEpisodeDetail(raw);
    } catch (err: unknown) {
      if (
        err &&
        typeof err === "object" &&
        "status" in err &&
        (err as { status: number }).status === 404
      ) {
        return null;
      }
      throw err;
    }
  }

  async create(id: EpisodeId, scriptFile: File): Promise<Episode> {
    const fd = new FormData();
    fd.append("id", id);
    fd.append("script", scriptFile);
    const raw = await apiPostForm<RawEpisodeDetail>("/episodes", fd);
    return mapEpisodeDetail(raw);
  }

  async delete(id: EpisodeId): Promise<void> {
    await apiDelete(`/episodes/${encodeURIComponent(id)}`);
  }
}
