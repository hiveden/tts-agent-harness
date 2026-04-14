"use client";

import { useState, useCallback } from "react";
import { Lock } from "lucide-react";
import * as Popover from "@radix-ui/react-popover";
import type { Episode, EpisodeStatus } from "@/lib/types";
import { getApiUrl } from "@/lib/api-client";
import { toast } from "sonner";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";

interface Props {
  episode: Episode;
  running: boolean;
  runPending?: boolean;
  onRun: (mode: string) => void;
  onCancel?: () => void;
  cancelPending?: boolean;
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

export function EpisodeHeader({ episode, running, runPending = false, onRun, onCancel, cancelPending = false, onViewScript, failedCount = 0 }: Props) {
  const badge = STATUS_BADGE[episode.status] ?? STATUS_BADGE.ready;
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [regenConfirmOpen, setRegenConfirmOpen] = useState(false);

  const handleScriptDownload = useCallback(async () => {
    try {
      const res = await fetch(`${getApiUrl()}/episodes/${episode.id}/script`);
      if (!res.ok) throw new Error(await res.text());
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${episode.id}-script.json`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      toast.error("下载失败", { description: (e as Error).message });
    }
  }, [episode.id]);

  const totalDurationS = episode.chunks.reduce((sum, c) => {
    const selectedTake = c.takes.find((t) => t.id === c.selectedTakeId);
    return sum + (selectedTake?.durationS ?? 0);
  }, 0);

  // D-03: Button config per status
  const primaryButton = (() => {
    if (running) return { label: cancelPending ? "取消中…" : "取消", disabled: cancelPending, mode: "__cancel__" };
    switch (episode.status) {
      case "empty":
        return { label: runPending ? "切分中…" : "切分", disabled: runPending, mode: "chunk_only" };
      case "ready":
        return { label: runPending ? "启动中…" : "合成全部", disabled: runPending, mode: "synthesize" };
      case "failed":
        return { label: runPending ? "启动中…" : `重试失败 (${failedCount})`, disabled: failedCount === 0 || runPending, mode: "retry_failed" };
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
      </div>
      <div className="flex gap-2 items-center">
        {episode.locked ? (
          <span className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded bg-neutral-100 dark:bg-neutral-800 text-neutral-500 dark:text-neutral-400">
            <Lock size={12} /> Locked
          </span>
        ) : (
        <>
        {/* Primary action button */}
        {primaryButton.mode === "synthesize" || primaryButton.mode === "__cancel__" ? (
          <Popover.Root open={confirmOpen} onOpenChange={setConfirmOpen}>
            <Popover.Trigger asChild>
              <button
                type="button"
                disabled={primaryButton.disabled}
                className={`px-3 py-1.5 text-sm rounded ${
                  primaryButton.mode === "__cancel__"
                    ? "bg-red-600 text-white hover:bg-red-700"
                    : "bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 hover:bg-neutral-800 dark:hover:bg-neutral-200"
                }`}
              >
                {primaryButton.label}
              </button>
            </Popover.Trigger>
            <Popover.Portal>
              <Popover.Content
                side="bottom"
                align="start"
                sideOffset={6}
                className="z-50 bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-lg shadow-lg dark:shadow-neutral-900 p-3 w-56"
              >
                <p className="text-xs text-neutral-700 dark:text-neutral-300 mb-2.5">
                  {primaryButton.mode === "__cancel__"
                    ? "确认取消？已完成的 chunk 不会回滚。"
                    : "确认合成全部 chunk？"}
                </p>
                <div className="flex gap-2 justify-end">
                  <button
                    type="button"
                    onClick={() => setConfirmOpen(false)}
                    className="px-2.5 py-1 text-xs rounded text-neutral-500 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-700"
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setConfirmOpen(false);
                      if (primaryButton.mode === "__cancel__") onCancel?.();
                      else onRun(primaryButton.mode);
                    }}
                    className={`px-2.5 py-1 text-xs rounded text-white ${
                      primaryButton.mode === "__cancel__"
                        ? "bg-red-600 hover:bg-red-700"
                        : "bg-neutral-900 dark:bg-neutral-100 dark:text-neutral-900 hover:bg-neutral-800 dark:hover:bg-neutral-200"
                    }`}
                  >
                    确认
                  </button>
                </div>
                <Popover.Arrow className="fill-white dark:fill-neutral-800" />
              </Popover.Content>
            </Popover.Portal>
          </Popover.Root>
        ) : (
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
        )}

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
            <DropdownMenuItem onClick={handleScriptDownload}>
              下载脚本 (.json)
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
                  onClick={() => setRegenConfirmOpen(true)}
                >
                  重新生成（清空重来）
                </DropdownMenuItem>
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
        </>
        )}

        {/* Regenerate confirm dialog */}
        <Dialog open={regenConfirmOpen} onOpenChange={setRegenConfirmOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>确认重新生成</DialogTitle>
              <DialogDescription>会清空所有已有产物重新开始，此操作不可撤销。</DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <button
                type="button"
                onClick={() => setRegenConfirmOpen(false)}
                className="px-3 py-1.5 text-xs text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 rounded"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => { setRegenConfirmOpen(false); onRun("regenerate"); }}
                className="px-4 py-1.5 text-xs rounded text-white bg-red-600 hover:bg-red-700"
              >
                确认重新生成
              </button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </div>
  );
}
