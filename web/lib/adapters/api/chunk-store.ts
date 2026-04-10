/**
 * ChunkStore implementation backed by FastAPI REST API.
 */

import type { EditBatch, EpisodeId } from "../../types";
import type { ChunkStore } from "../../ports/store";
import { apiPost } from "./http-client";

export class ApiChunkStore implements ChunkStore {
  async applyEdits(epId: EpisodeId, edits: EditBatch): Promise<void> {
    const entries = Object.entries(edits);
    for (const [cid, edit] of entries) {
      const body: Record<string, unknown> = {};
      if (edit.textNormalized !== undefined) {
        body.text_normalized = edit.textNormalized;
      }
      if (edit.subtitleText !== undefined) {
        body.subtitle_text = edit.subtitleText;
      }
      await apiPost(
        `/episodes/${encodeURIComponent(epId)}/chunks/${encodeURIComponent(cid)}/edit`,
        body,
      );
    }
  }
}
