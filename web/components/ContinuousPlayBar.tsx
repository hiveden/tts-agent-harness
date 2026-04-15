"use client";

import { useHarnessStore } from "@/lib/store";

const RATE_OPTIONS = [1, 1.25, 1.5, 2] as const;

export function ContinuousPlayBar() {
  const continuousPlay = useHarnessStore((s) => s.continuousPlay);
  const playingChunkId = useHarnessStore((s) => s.playingChunkId);
  const playbackRate = useHarnessStore((s) => s.playbackRate);
  const playAll = useHarnessStore((s) => s.playAll);
  const stopAll = useHarnessStore((s) => s.stopAll);
  const setPlaybackRate = useHarnessStore((s) => s.setPlaybackRate);

  const isActive = continuousPlay && playingChunkId !== null;

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={isActive ? stopAll : playAll}
        className={`px-2 py-0.5 rounded text-xs font-medium transition-colors ${
          isActive
            ? "bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 hover:bg-neutral-700 dark:hover:bg-neutral-200"
            : "bg-neutral-100 dark:bg-neutral-800 text-neutral-600 dark:text-neutral-300 hover:bg-neutral-200 dark:hover:bg-neutral-700"
        }`}
        title={isActive ? "停止连播" : "连续播放全部"}
      >
        {isActive ? "⏹ 停止" : "▶ 连播"}
      </button>
      <div className="flex items-center rounded bg-neutral-100 dark:bg-neutral-800 overflow-hidden">
        {RATE_OPTIONS.map((rate) => (
          <button
            key={rate}
            type="button"
            onClick={() => setPlaybackRate(rate)}
            className={`px-1.5 py-0.5 text-[11px] font-medium transition-colors ${
              playbackRate === rate
                ? "bg-neutral-900 dark:bg-white text-white dark:text-neutral-900"
                : "text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200"
            }`}
          >
            {rate}x
          </button>
        ))}
      </div>
    </div>
  );
}
