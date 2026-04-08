/**
 * Service factory — 唯一拼装 adapter 的地方
 *
 * Route Handler 全部通过 getServices() 取实例,
 * 切换 adapter 只改这里。
 *
 * Wave 0 阶段:全部返回 stub(throw not implemented),
 * Wave 1 BACKEND agent 会把 legacy adapter 接进来。
 */

import type {
  AudioService,
  ChunkStore,
  EpisodeStore,
  ExportService,
  LockManager,
  LogTailer,
  PipelineRunner,
  PreviewService,
  ProgressSource,
} from "./ports";

export interface Services {
  episodes: EpisodeStore;
  chunks: ChunkStore;
  runner: PipelineRunner;
  locks: LockManager;
  progress: ProgressSource;
  logs: LogTailer;
  audio: AudioService;
  preview: PreviewService;
  export: ExportService;
}

let _services: Services | null = null;

/** 单例 — Route Handler 全部走这个 */
export function getServices(): Services {
  if (_services) return _services;

  // ────────────────────────────────────────────────────────
  // Wave 0 stub: 全部 throw,等 BACKEND agent 接 legacy adapter
  // 接好之后这里改成:
  //
  //   const locks   = new InMemoryLockManager();
  //   const chunks  = new LegacyChunkStore(locks);
  //   const episodes = new LegacyEpisodeStore(chunks);
  //   ...
  //
  // ────────────────────────────────────────────────────────

  const notImplemented = (name: string) => {
    return new Proxy({} as Record<string, unknown>, {
      get: () => {
        throw new Error(
          `${name} not implemented yet (Wave 0 stub). ` +
            `BACKEND agent should wire LegacyAdapter in factory.ts`,
        );
      },
    });
  };

  _services = {
    episodes: notImplemented("EpisodeStore") as unknown as EpisodeStore,
    chunks: notImplemented("ChunkStore") as unknown as ChunkStore,
    runner: notImplemented("PipelineRunner") as unknown as PipelineRunner,
    locks: notImplemented("LockManager") as unknown as LockManager,
    progress: notImplemented("ProgressSource") as unknown as ProgressSource,
    logs: notImplemented("LogTailer") as unknown as LogTailer,
    audio: notImplemented("AudioService") as unknown as AudioService,
    preview: notImplemented("PreviewService") as unknown as PreviewService,
    export: notImplemented("ExportService") as unknown as ExportService,
  };

  return _services;
}

/** 测试用:重置单例(允许换 mock) */
export function _resetServices(services?: Services): void {
  _services = services ?? null;
}
