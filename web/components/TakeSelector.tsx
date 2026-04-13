"use client";

import type { Take } from "@/lib/types";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

interface Props {
  takes: Take[];
  selectedTakeId: string | null;
  onPreview?: (takeId: string) => void;
  onUse?: (takeId: string) => void;
}

/**
 * Multi-take 切换器。只在 takes.length > 1 时渲染。
 * MVP 简化:list 风格,每 take 一行,显示 duration 和按钮。
 */
export function TakeSelector({
  takes,
  selectedTakeId,
  onPreview,
  onUse,
}: Props) {
  if (takes.length <= 1) return null;

  return (
    <div className="mt-1.5 border border-neutral-200 dark:border-neutral-700 rounded bg-neutral-50 dark:bg-neutral-800 p-1.5 text-[11px]">
      <div className="text-[10px] uppercase tracking-wide text-neutral-400 dark:text-neutral-500 mb-1 px-1 flex items-center gap-1">
        Takes ({takes.length})
        <TooltipProvider delayDuration={200}>
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="inline-flex items-center justify-center w-3 h-3 rounded-full border border-neutral-300 text-[8px] font-bold cursor-help hover:border-neutral-500">?</span>
            </TooltipTrigger>
            <TooltipContent side="right">
              <p>每次合成（P2）会生成一个 Take。</p>
              <p className="mt-1">▶ 试听某个 Take</p>
              <p>Use 设为当前版本（会重跑 P3→P5）</p>
              <p className="mt-1 text-neutral-400">✓ current 表示当前选中的 Take</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>
      {takes.map((t, i) => {
        const isSelected = t.id === selectedTakeId;
        return (
          <div
            key={t.id}
            className={`flex items-center gap-2 px-1.5 py-1 rounded ${
              isSelected ? "bg-white dark:bg-neutral-900 border border-emerald-200 dark:border-emerald-800" : ""
            }`}
          >
            <span className="font-mono text-neutral-500">#{i + 1}</span>
            {isSelected ? (
              <span className="text-emerald-600 text-[10px]">✓ current</span>
            ) : null}
            <span className="font-mono text-neutral-400">
              {t.durationS.toFixed(2)}s
            </span>
            <div className="ml-auto flex gap-1">
              <button
                type="button"
                onClick={() => onPreview?.(t.id)}
                className="px-1.5 py-0.5 rounded hover:bg-neutral-200 dark:hover:bg-neutral-700 text-neutral-600 dark:text-neutral-400"
                title="Preview"
              >
                ▶
              </button>
              {!isSelected ? (
                <button
                  type="button"
                  onClick={() => onUse?.(t.id)}
                  className="px-1.5 py-0.5 rounded bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 hover:bg-neutral-800 dark:hover:bg-neutral-200"
                >
                  Use
                </button>
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}
