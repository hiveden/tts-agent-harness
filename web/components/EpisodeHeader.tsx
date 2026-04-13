"use client";

import { useState } from "react";
import { useTheme } from "next-themes";
import { Sun, Moon } from "lucide-react";
import type { Episode, EpisodeStatus } from "@/lib/types";
import { getApiUrl } from "@/lib/api-client";

interface Props {
  episode: Episode;
  running: boolean;
  onRun: (mode: string) => void;
  onViewScript?: () => void;
  failedCount?: number;
}

const STATUS_BADGE: Record<
  EpisodeStatus,
  { bg: string; fg: string; br: string; label: string }
> = {
  done: { bg: "bg-emerald-50 dark:bg-emerald-900/30", fg: "text-emerald-700 dark:text-emerald-400", br: "border-emerald-200 dark:border-emerald-800", label: "done" },
  running: { bg: "bg-blue-50 dark:bg-blue-900/30", fg: "text-blue-700 dark:text-blue-400", br: "border-blue-200 dark:border-blue-800", label: "running" },
  ready: { bg: "bg-neutral-50 dark:bg-neutral-800", fg: "text-neutral-600 dark:text-neutral-400", br: "border-neutral-200 dark:border-neutral-700", label: "ready" },
  failed: { bg: "bg-red-50 dark:bg-red-900/30", fg: "text-red-700 dark:text-red-400", br: "border-red-200 dark:border-red-800", label: "failed" },
  empty: { bg: "bg-neutral-50 dark:bg-neutral-800", fg: "text-neutral-500 dark:text-neutral-400", br: "border-neutral-200 dark:border-neutral-700", label: "empty" },
};

export function EpisodeHeader({ episode, running, onRun, onViewScript, failedCount = 0 }: Props) {
  const badge = STATUS_BADGE[episode.status] ?? STATUS_BADGE.ready;
  const [menuOpen, setMenuOpen] = useState(false);
  const { theme, setTheme } = useTheme();

  const totalDurationS = episode.chunks.reduce((sum, c) => {
    const selectedTake = c.takes.find((t) => t.id === c.selectedTakeId);
    return sum + (selectedTake?.durationS ?? 0);
  }, 0);

  // D-03: Button config per status
  const primaryButton = (() => {
    if (running) return { label: "运行中...", disabled: true, mode: "" };
    switch (episode.status) {
      case "empty":
        return { label: "切分", disabled: false, mode: "chunk_only" };
      case "ready":
        return { label: "合成全部", disabled: false, mode: "synthesize" };
      case "failed":
        return { label: `重试失败 (${failedCount})`, disabled: failedCount === 0, mode: "retry_failed" };
      case "done":
        return { label: "完成 ✓", disabled: true, mode: "" };
      default:
        return { label: "Run", disabled: true, mode: "" };
    }
  })();

  return (
    <div className="px-6 py-3 border-b border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 shrink-0">
      <div className="flex items-center gap-3 mb-2">
        <h2 className="text-lg font-semibold">{episode.title}</h2>
        <span className="text-xs text-neutral-400 dark:text-neutral-500 font-mono">{episode.id}</span>
        <span className={`text-xs px-2 py-0.5 rounded-full border ${badge.bg} ${badge.fg} ${badge.br}`}>
          {badge.label}
        </span>
        <span className="ml-auto text-[11px] text-neutral-400 dark:text-neutral-500 font-mono">
          {episode.chunks.length} chunks · {totalDurationS.toFixed(1)}s
        </span>
        <button
          type="button"
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          className="w-7 h-7 rounded-full flex items-center justify-center hover:bg-neutral-100 dark:hover:bg-neutral-800 text-neutral-500 dark:text-neutral-400"
          title="Toggle dark mode"
        >
          {theme === "dark" ? <Sun size={14} /> : <Moon size={14} />}
        </button>
      </div>
      <div className="flex gap-2 items-center">
        {/* Primary action button */}
        <button
          type="button"
          onClick={() => onRun(primaryButton.mode)}
          disabled={primaryButton.disabled}
          className={`px-3 py-1.5 text-sm rounded ${
            primaryButton.disabled
              ? "bg-neutral-200 dark:bg-neutral-700 text-neutral-400 cursor-not-allowed"
              : "bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 hover:bg-neutral-800 dark:hover:bg-neutral-200"
          }`}
        >
          {primaryButton.label}
        </button>

        {/* Menu for secondary actions */}
        <div className="relative">
          <button
            type="button"
            onClick={() => setMenuOpen(!menuOpen)}
            className="px-2 py-1.5 text-sm rounded border border-neutral-300 dark:border-neutral-600 text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800"
          >
            ⋯
          </button>
          {menuOpen && (
            <div className="absolute left-0 top-full mt-1 w-48 bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-md shadow-lg dark:shadow-neutral-900 z-30">
              <button
                type="button"
                onClick={() => { setMenuOpen(false); onViewScript?.(); }}
                className="w-full text-left px-3 py-2 text-xs text-neutral-700 dark:text-neutral-300 hover:bg-neutral-50 dark:hover:bg-neutral-700 rounded-t-md"
              >
                查看脚本
              </button>
              <a
                href={`${getApiUrl()}/episodes/${episode.id}/script`}
                download={`${episode.id}-script.json`}
                onClick={() => setMenuOpen(false)}
                className="block w-full text-left px-3 py-2 text-xs text-neutral-700 dark:text-neutral-300 hover:bg-neutral-50 dark:hover:bg-neutral-700"
              >
                下载脚本 (.json)
              </a>
              {episode.status === "done" && (
                <a
                  href={`${getApiUrl()}/episodes/${episode.id}/export`}
                  download
                  onClick={() => setMenuOpen(false)}
                  className="block w-full text-left px-3 py-2 text-xs text-neutral-700 dark:text-neutral-300 hover:bg-neutral-50 dark:hover:bg-neutral-700"
                >
                  导出产物 (zip)
                </a>
              )}
              {episode.status === "failed" && !running && (
                <button
                  type="button"
                  onClick={() => { setMenuOpen(false); onRun("synthesize"); }}
                  className="w-full text-left px-3 py-2 text-xs text-neutral-700 dark:text-neutral-300 hover:bg-neutral-50 dark:hover:bg-neutral-700"
                >
                  合成全部（跳过已完成）
                </button>
              )}
              {!running && (
                <button
                  type="button"
                  onClick={() => {
                    if (confirm("确认重新生成？\n会清空所有已有产物重新开始。")) {
                      setMenuOpen(false);
                      onRun("regenerate");
                    }
                  }}
                  className="w-full text-left px-3 py-2 text-xs text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/30 rounded-b-md"
                >
                  重新生成（清空重来）
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
