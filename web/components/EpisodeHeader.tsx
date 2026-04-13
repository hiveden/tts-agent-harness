"use client";

import { useTheme } from "@/components/Providers";
import { Sun, Moon } from "lucide-react";
import type { Episode, EpisodeStatus } from "@/lib/types";
import { getApiUrl } from "@/lib/api-client";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";

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
  const { resolvedTheme, setTheme } = useTheme();

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
          onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
          className="w-7 h-7 rounded-full flex items-center justify-center hover:bg-neutral-100 dark:hover:bg-neutral-800 text-neutral-500 dark:text-neutral-400"
          title="Toggle dark mode"
        >
          {resolvedTheme === "dark" ? <Sun size={14} /> : <Moon size={14} />}
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
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="px-2 py-1.5 text-sm rounded border border-neutral-300 dark:border-neutral-600 text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800"
            >
              ⋯
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            <DropdownMenuItem onClick={() => onViewScript?.()}>
              查看脚本
            </DropdownMenuItem>
            <DropdownMenuItem asChild>
              <a
                href={`${getApiUrl()}/episodes/${episode.id}/script`}
                download={`${episode.id}-script.json`}
              >
                下载脚本 (.json)
              </a>
            </DropdownMenuItem>
            {episode.status === "done" && (
              <DropdownMenuItem asChild>
                <a
                  href={`${getApiUrl()}/episodes/${episode.id}/export`}
                  download
                >
                  导出产物 (.zip)
                </a>
              </DropdownMenuItem>
            )}
            {episode.status === "failed" && !running && (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => onRun("synthesize")}>
                  合成全部（跳过已完成）
                </DropdownMenuItem>
              </>
            )}
            {!running && (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  destructive
                  onClick={() => {
                    if (confirm("确认重新生成？\n会清空所有已有产物重新开始。")) {
                      onRun("regenerate");
                    }
                  }}
                >
                  重新生成（清空重来）
                </DropdownMenuItem>
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}
