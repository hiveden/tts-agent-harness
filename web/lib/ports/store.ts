/**
 * Storage ports — episode 列表 + chunks 读写
 *
 * 任何持久化操作都通过这两个接口。
 * MVP 实现: lib/adapters/legacy/store.ts (文件系统 .work/)
 * 未来扩展: SqliteEpisodeStore / SqliteChunkStore
 */

import type {
  Chunk,
  ChunkId,
  EditBatch,
  Episode,
  EpisodeId,
  EpisodeSummary,
  Take,
  TakeId,
} from "../types";

export interface EpisodeStore {
  /** 列出全部 episode(快速,不含 chunks) */
  list(): Promise<EpisodeSummary[]>;

  /** 获取单 episode 完整信息(含 chunks) */
  get(id: EpisodeId): Promise<Episode | null>;

  /**
   * 创建新 episode。把 script.json 落地到磁盘,
   * 但不跑 P1(P1 在第一次 runFull 时跑)。
   */
  create(id: EpisodeId, scriptJson: unknown): Promise<Episode>;

  /** 删除 episode(MVP 不暴露 endpoint,但接口先留) */
  delete(id: EpisodeId): Promise<void>;
}

export interface ChunkStore {
  /** 读取单个 chunk */
  get(epId: EpisodeId, cid: ChunkId): Promise<Chunk | null>;

  /**
   * 应用一批 chunk 的字段更新。
   * - 原子写入 chunks.json
   * - 备份原文件(.bak 或 .v<ts>)
   * - tts dirty 字段会触发该 chunk status 重置为 pending
   */
  applyEdits(epId: EpisodeId, edits: EditBatch): Promise<void>;

  /** 追加一个新 take 到指定 chunk(retry 用) */
  appendTake(epId: EpisodeId, cid: ChunkId, take: Take): Promise<void>;

  /** 切换 selected_take(用户在 TakeSelector 选了某个 take) */
  selectTake(
    epId: EpisodeId,
    cid: ChunkId,
    takeId: TakeId,
  ): Promise<void>;

  /** 删除某个 take(回收磁盘,可选) */
  removeTake(
    epId: EpisodeId,
    cid: ChunkId,
    takeId: TakeId,
  ): Promise<void>;
}
