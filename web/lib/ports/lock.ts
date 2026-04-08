/**
 * LockManager port — 三 scope 锁
 *
 * scope 设计:
 *   global  : 占用 P3 sidecar(整集 run / Apply / finalize)
 *   episode : 同一 episode 内的串行(预留,MVP 不用)
 *   chunk   : 同一 chunk 不能同时 retry × 2(multi-take 并发用)
 *
 * 不冲突规则:
 *   global   ←→  episode/chunk : 互斥
 *   episode  ←→  其他 episode    : 不互斥
 *   chunk    ←→  其他 chunk     : 不互斥(允许并行)
 *   chunk    ←→  同 chunk        : 互斥
 *
 * MVP 实现: InMemoryLockManager(单进程 Map)
 * 未来扩展: RedisLockManager(多进程)
 */

import type { ChunkId, EpisodeId } from "../types";

export type LockScope =
  | { type: "global" }
  | { type: "episode"; episodeId: EpisodeId }
  | { type: "chunk"; episodeId: EpisodeId; chunkId: ChunkId };

export interface LockManager {
  /**
   * 取得锁。
   * 失败抛 LockBusyError。
   */
  acquire(scope: LockScope, owner: string): Promise<LockHandle>;

  /** 检查是否被占用(不抢) */
  isBusy(scope: LockScope): Promise<boolean>;

  /** 列出当前所有持有的锁(debug 用) */
  list(): Promise<LockInfo[]>;
}

export interface LockHandle {
  release(): Promise<void>;
}

export interface LockInfo {
  scope: LockScope;
  owner: string;
  acquiredAt: string;
}

export class LockBusyError extends Error {
  constructor(
    public scope: LockScope,
    public heldBy: LockInfo,
  ) {
    super(
      `Lock busy: ${JSON.stringify(scope)} (held by ${heldBy.owner} since ${heldBy.acquiredAt})`,
    );
    this.name = "LockBusyError";
  }
}
