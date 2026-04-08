/**
 * File services — audio / preview / export
 *
 * 这些接口返回"绝对路径",由 Route Handler 用 Node fs.createReadStream / sendFile 之类发出。
 * Domain 层不直接读文件内容(让 Node 原生处理 range request 等)。
 */

import type { ChunkId, EpisodeId, ShotId, TakeId } from "../types";

export interface AudioService {
  /**
   * 返回某个 chunk 某个 take 的 wav 绝对路径。
   * takeId 省略时返回 selectedTakeId 对应的 take。
   * 文件不存在抛 DomainError("not_found")。
   */
  getTakeFile(
    epId: EpisodeId,
    cid: ChunkId,
    takeId?: TakeId,
  ): Promise<string>;

  /** 返回拼接后的整 shot wav 绝对路径 */
  getShotFile(epId: EpisodeId, shotId: ShotId): Promise<string>;
}

export interface PreviewService {
  /** 返回 v2-preview.html 的绝对路径 */
  getPreviewFile(epId: EpisodeId): Promise<string>;
}

export interface ExportService {
  /** 拷贝产物到目标目录 */
  exportTo(
    epId: EpisodeId,
    targetDir: string,
  ): Promise<ExportResult>;
}

export interface ExportResult {
  filesCopied: number;
  totalBytes: number;
}
