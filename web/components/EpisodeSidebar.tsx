"use client";

import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import type { EpisodeSummary, EpisodeStatus } from "@/lib/types";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";

interface Props {
  episodes: EpisodeSummary[];
  selectedId: string | null;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onSelect: (id: string) => void;
  onNewEpisode: () => void;
  onDelete?: (id: string) => void;
  onDuplicate?: (id: string) => void;
  onArchive?: (id: string) => void;
  error?: Error | null;
}

const STATUS_DOT: Record<EpisodeStatus, string> = {
  done: "bg-emerald-500",
  running: "bg-blue-500 animate-pulse",
  ready: "bg-neutral-300 dark:bg-neutral-600",
  failed: "bg-red-500",
  empty: "bg-neutral-200 dark:bg-neutral-600",
};

export function EpisodeSidebar({
  episodes, selectedId, collapsed, onToggleCollapse, onSelect, onNewEpisode, onDelete, onDuplicate, onArchive, error,
}: Props) {
  // Collapsed: narrow strip with expand button
  if (collapsed) {
    return (
      <aside className="w-10 border-r border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 flex flex-col items-center shrink-0">
        <button
          type="button"
          onClick={onToggleCollapse}
          className="w-10 h-10 flex items-center justify-center text-neutral-500 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 border-b border-neutral-100 dark:border-neutral-700 shrink-0"
          title="展开侧边栏"
        >
          <PanelLeftOpen size={14} />
        </button>
        <div className="flex-1 overflow-y-auto py-1.5 flex flex-col items-center gap-0.5 w-full">
          {episodes.map((ep) => {
            const sel = ep.id === selectedId;
            const dotClass = STATUS_DOT[ep.status] ?? "bg-neutral-300";
            return (
              <button
                key={ep.id}
                type="button"
                onClick={() => onSelect(ep.id)}
                className={`w-8 h-8 rounded flex items-center justify-center shrink-0 ${
                  sel
                    ? "bg-neutral-900 dark:bg-white"
                    : "hover:bg-neutral-100 dark:hover:bg-neutral-800"
                }`}
                title={`${ep.title} (${ep.status})`}
              >
                <span className={`w-2 h-2 rounded-full ${dotClass}`} />
              </button>
            );
          })}
        </div>
        <div className="py-2 text-[9px] text-neutral-400 dark:text-neutral-500 font-mono">
          {episodes.length}
        </div>
      </aside>
    );
  }

  return (
    <aside className="w-56 border-r border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 flex flex-col shrink-0">
      <div className="px-3 py-3 flex items-center justify-between border-b border-neutral-100 dark:border-neutral-700">
        <span className="text-xs font-medium text-neutral-500 dark:text-neutral-400 uppercase tracking-wide">Episodes</span>
        <div className="flex items-center gap-1">
          <button type="button" onClick={onNewEpisode} className="text-xs px-2 py-1 rounded hover:bg-neutral-100 dark:hover:bg-neutral-800 text-neutral-600 dark:text-neutral-400">+ New</button>
          <button
            type="button"
            onClick={onToggleCollapse}
            className="w-6 h-6 rounded flex items-center justify-center text-neutral-400 dark:text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800"
            title="折叠侧边栏"
          >
            <PanelLeftClose size={12} />
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-1.5">
        {error ? (
          <div className="p-3 text-xs text-red-500 text-center">
            <div className="mb-1">加载失败</div>
            <div className="text-[10px] text-red-400 font-mono">{error.message}</div>
          </div>
        ) : null}
        {episodes.map((ep) => {
          const sel = ep.id === selectedId;
          const dotClass = STATUS_DOT[ep.status] ?? "bg-neutral-300";
          const suffix = ep.status === "running" ? "..." : ep.status === "done" ? `${ep.doneCount}/${ep.chunkCount}` : ep.status;
          const hasMenu = onDelete || onDuplicate || onArchive;
          return (
            <div key={ep.id} className={`w-full text-left px-2.5 py-2 rounded flex items-center gap-2 mb-0.5 ${sel ? "bg-neutral-900 text-white dark:bg-white dark:text-neutral-900" : "hover:bg-neutral-100 dark:hover:bg-neutral-800"}`}>
              <button type="button" onClick={() => onSelect(ep.id)} className="flex items-center gap-2 flex-1 min-w-0 cursor-pointer">
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dotClass}`} />
                <span className="font-medium text-sm truncate">{ep.title}</span>
                <span className={`ml-auto text-[11px] font-mono ${sel ? "text-neutral-300 dark:text-neutral-600" : "text-neutral-400 dark:text-neutral-500"}`}>{suffix}</span>
              </button>
              {hasMenu && (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <button type="button" className={`w-5 h-5 text-[11px] rounded flex items-center justify-center shrink-0 ${sel ? "hover:bg-white/20 text-neutral-300 dark:hover:bg-black/20 dark:text-neutral-600" : "hover:bg-neutral-200 dark:hover:bg-neutral-700 text-neutral-400 dark:text-neutral-500"}`}>⋯</button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    {onDuplicate && <DropdownMenuItem onClick={() => onDuplicate(ep.id)}>复制</DropdownMenuItem>}
                    {onArchive && <DropdownMenuItem onClick={() => onArchive(ep.id)}>归档</DropdownMenuItem>}
                    {(onDuplicate || onArchive) && onDelete && <DropdownMenuSeparator />}
                    {onDelete && <DropdownMenuItem destructive onClick={() => onDelete(ep.id)}>删除</DropdownMenuItem>}
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            </div>
          );
        })}
      </div>
      <div className="p-3 border-t border-neutral-100 dark:border-neutral-700 text-[11px] text-neutral-400 dark:text-neutral-500 font-mono">{episodes.length} episodes</div>
    </aside>
  );
}
