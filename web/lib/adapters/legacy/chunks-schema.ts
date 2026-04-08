/**
 * chunks.json raw schema
 *
 * 这是 .work/<ep>/chunks.json 文件的真实字段(snake_case),
 * 与 lib/types.ts 的 domain Chunk 解耦。
 *
 * 规则:
 * - 用 .passthrough() 允许未知字段(向前兼容)
 * - 任何 chunks.json 字段名变化只在这一个文件改
 * - 不导出给 Route Handler / frontend,只在 LegacyChunkStore 内部用
 */

import { z } from "zod";

// ============================================================
// raw chunks.json schema (current production)
// ============================================================

/** 单个 take(multi-take 字段,旧数据可能没有) */
export const rawTakeSchema = z
  .object({
    id: z.string(),
    file: z.string(),
    duration_s: z.number(),
    created_at: z.string(),
    params: z.record(z.string(), z.unknown()).optional(),
  })
  .passthrough();

/** chunks.json 单个 chunk 的原始字段 */
export const rawChunkSchema = z
  .object({
    id: z.string(),
    shot_id: z.string(),
    text: z.string(),
    text_normalized: z.string(),
    subtitle_text: z.string().optional().nullable(),

    sentence_count: z.number().optional(),
    char_count: z.number(),

    status: z.enum(["pending", "synth_done", "transcribed", "failed"]),

    // 旧版本:单 take 直接放 file 字段
    file: z.string().nullable().optional(),
    duration_s: z.number().optional(),

    // 新版本:multi-take
    takes: z.array(rawTakeSchema).optional(),
    selected_take_id: z.string().nullable().optional(),

    boundary_hash: z.string().optional(),
    error: z.string().optional(),

    // 历史字段,允许存在但不再使用
    normalized_history: z.array(z.unknown()).optional(),
  })
  .passthrough();

export const rawChunksFileSchema = z.array(rawChunkSchema);

export type RawChunk = z.infer<typeof rawChunkSchema>;
export type RawTake = z.infer<typeof rawTakeSchema>;

// ============================================================
// 转换:RawChunk → domain Chunk
// ============================================================

import type { Chunk, Take } from "../../types";

export function rawToChunk(raw: RawChunk, index: number): Chunk {
  // 处理 multi-take vs 单 take 兼容
  let takes: Take[];
  let selectedTakeId: string | null;

  if (raw.takes && raw.takes.length > 0) {
    takes = raw.takes.map(rawToTake);
    selectedTakeId = raw.selected_take_id ?? takes[0]?.id ?? null;
  } else if (raw.file) {
    // 旧数据:单 take
    const t: Take = {
      id: "take_1",
      file: raw.file,
      durationS: raw.duration_s ?? 0,
      createdAt: "",
    };
    takes = [t];
    selectedTakeId = "take_1";
  } else {
    takes = [];
    selectedTakeId = null;
  }

  return {
    id: raw.id,
    shotId: raw.shot_id,
    index,
    text: raw.text,
    textNormalized: raw.text_normalized,
    subtitleText: raw.subtitle_text ?? null,
    status: raw.status,
    takes,
    selectedTakeId,
    charCount: raw.char_count,
    boundaryHash: raw.boundary_hash,
    metadata: {},
  };
}

export function rawToTake(raw: RawTake): Take {
  return {
    id: raw.id,
    file: raw.file,
    durationS: raw.duration_s,
    createdAt: raw.created_at,
    params: raw.params,
  };
}

// ============================================================
// 转换:domain Chunk → RawChunk(写回 chunks.json 时用)
// ============================================================

export function chunkToRaw(chunk: Chunk): RawChunk {
  const selected = chunk.takes.find((t) => t.id === chunk.selectedTakeId);
  return {
    id: chunk.id,
    shot_id: chunk.shotId,
    text: chunk.text,
    text_normalized: chunk.textNormalized,
    subtitle_text: chunk.subtitleText,
    char_count: chunk.charCount,
    status: chunk.status,
    // 同时写新旧字段,兼容 P5/P6 的现有读取
    file: selected?.file ?? null,
    duration_s: selected?.durationS,
    takes: chunk.takes.length > 0 ? chunk.takes.map(takeToRaw) : undefined,
    selected_take_id: chunk.selectedTakeId,
    boundary_hash: chunk.boundaryHash,
  };
}

export function takeToRaw(take: Take): RawTake {
  return {
    id: take.id,
    file: take.file,
    duration_s: take.durationS,
    created_at: take.createdAt,
    params: take.params,
  };
}
