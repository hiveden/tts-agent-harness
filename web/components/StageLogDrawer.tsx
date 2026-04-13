"use client";

import type { StageName, StageRun } from "@/lib/types";
import { STAGE_INFO } from "@/lib/stage-info";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetClose } from "@/components/ui/sheet";

interface StageContext {
  request?: Record<string, unknown>;
  response?: Record<string, unknown>;
  skipped?: boolean;
  reason?: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  chunkId: string;
  stage: StageName;
  stageRun: StageRun | undefined;
  log: string;
  logLoading: boolean;
  logError: string | null;
  context: StageContext | null;
  onRetry: (cascade: boolean) => void;
  retrying?: boolean;
}

const STAGE_LABELS: Record<StageName, string> = {
  p1: "P1", p1c: "P1c", p2: "P2", p2c: "P2c", p2v: "P2v",
  p5: "P5", p6: "P6", p6v: "P6v",
};

function statusBadge(sr: StageRun | undefined) {
  const base = "text-[10px] font-mono uppercase px-1.5 py-0.5 rounded tracking-wide";
  const status = sr?.status ?? "pending";
  switch (status) {
    case "pending": return <span className={`${base} bg-neutral-200 dark:bg-neutral-700 text-neutral-600 dark:text-neutral-400`}>pending</span>;
    case "running": return <span className={`${base} bg-blue-500 text-white animate-pulse`}>running</span>;
    case "ok": return <span className={`${base} bg-emerald-500 text-white`}>ok</span>;
    case "failed": return <span className={`${base} bg-red-500 text-white`}>failed</span>;
  }
}

/**
 * Stage log drawer — pure UI component.
 * No fetch, no hooks, no API calls.
 * Data (log, stageRun) and actions (onRetry) are passed as props.
 */
export function StageLogDrawer({
  open, onClose, chunkId, stage, stageRun,
  log, logLoading, logError, context, onRetry, retrying = false,
}: Props) {
  const attempt = stageRun?.attempt ?? 0;
  const durationMs = stageRun?.durationMs;

  return (
    <Sheet open={open} onOpenChange={(v) => { if (!v) onClose(); }}>
      <SheetContent side="right">
        <SheetHeader>
          <SheetTitle className="sr-only">{STAGE_LABELS[stage]} — {chunkId}</SheetTitle>
          <span className="font-mono text-xs text-neutral-700 dark:text-neutral-300">{chunkId}</span>
          <span className="text-neutral-300 dark:text-neutral-600">·</span>
          <span className="font-mono text-xs font-semibold">{STAGE_LABELS[stage]}</span>
          <span className="ml-1">{statusBadge(stageRun)}</span>
          <SheetClose asChild>
            <button type="button" className="ml-auto w-7 h-7 inline-flex items-center justify-center rounded hover:bg-neutral-100 dark:hover:bg-neutral-800 text-neutral-500 dark:text-neutral-400" title="关闭">✕</button>
          </SheetClose>
        </SheetHeader>

        {/* Stage description */}
        {(() => {
          const info = STAGE_INFO[stage];
          return (
            <details className="border-b border-neutral-200 dark:border-neutral-700 text-xs shrink-0" open>
              <summary className="px-4 py-2 bg-neutral-50 dark:bg-neutral-800 cursor-pointer hover:bg-neutral-100 dark:hover:bg-neutral-700 text-neutral-700 dark:text-neutral-300 font-semibold flex items-center gap-1.5">
                <span className="text-neutral-400">ℹ</span>
                <span>{info.title}</span>
              </summary>
              <div className="px-4 py-2.5 bg-white dark:bg-neutral-900 text-neutral-700 dark:text-neutral-300 space-y-1.5">
                <p className="leading-relaxed">{info.description}</p>
                <div className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-[11px] mt-2">
                  <span className="text-neutral-400">输入</span>
                  <span className="text-neutral-600">{info.inputs}</span>
                  <span className="text-neutral-400">输出</span>
                  <span className="text-neutral-600">{info.outputs}</span>
                  <span className="text-neutral-400">失败原因</span>
                  <span className="text-neutral-600">{info.failure}</span>
                </div>
              </div>
            </details>
          );
        })()}

        {stageRun?.status === "failed" ? (
          <div className="px-4 py-2 bg-red-50 border-b border-red-200 text-xs text-red-700 shrink-0">
            <div className="font-semibold mb-0.5">Error</div>
            <div className="font-mono whitespace-pre-wrap break-words">
              {stageRun.error
                || (context as Record<string, unknown>)?.error as string
                || "未知错误（查看日志获取详情）"}
            </div>
          </div>
        ) : null}

        {logLoading ? (
          <div className="flex-1 flex items-center justify-center text-xs text-neutral-400">加载日志中…</div>
        ) : log !== "" ? (
          <pre className="text-xs font-mono whitespace-pre-wrap p-4 overflow-auto flex-1 bg-neutral-50 dark:bg-neutral-800 dark:text-neutral-300">{log}</pre>
        ) : (
          <div className="flex-1 overflow-auto p-4 text-xs">
            {stageRun ? (
              <div className="space-y-2">
                <div className="text-neutral-500">Stage 执行信息</div>
                <table className="text-[11px] w-full">
                  <tbody className="divide-y divide-neutral-100">
                    <tr><td className="py-1 text-neutral-400 w-24">Status</td><td className="py-1 font-mono">{stageRun.status}</td></tr>
                    <tr><td className="py-1 text-neutral-400">Attempt</td><td className="py-1 font-mono">{stageRun.attempt}</td></tr>
                    {stageRun.startedAt && <tr><td className="py-1 text-neutral-400">Started</td><td className="py-1 font-mono">{stageRun.startedAt}</td></tr>}
                    {stageRun.finishedAt && <tr><td className="py-1 text-neutral-400">Finished</td><td className="py-1 font-mono">{stageRun.finishedAt}</td></tr>}
                    {stageRun.durationMs != null && <tr><td className="py-1 text-neutral-400">Duration</td><td className="py-1 font-mono">{stageRun.durationMs}ms</td></tr>}
                    {/* Error already shown in the red banner above — no duplicate here */}
                    {stageRun.stale && <tr><td className="py-1 text-neutral-400">Stale</td><td className="py-1 text-amber-600">上游已更新</td></tr>}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="text-neutral-400 text-center mt-8">暂无信息</div>
            )}
            {context && !context.skipped && (
              <div className="mt-4 space-y-3">
                {context.request && (
                  <div>
                    <div className="text-neutral-500 font-semibold text-[11px] mb-1">Request 参数</div>
                    <pre className="text-[10px] font-mono bg-neutral-100 dark:bg-neutral-800 rounded p-2 whitespace-pre-wrap overflow-auto max-h-40">
                      {JSON.stringify(context.request, null, 2)}
                    </pre>
                  </div>
                )}
                {context.response && (
                  <div>
                    <div className="text-neutral-500 dark:text-neutral-400 font-semibold text-[11px] mb-1">Response 产物</div>
                    <pre className="text-[10px] font-mono bg-neutral-100 dark:bg-neutral-800 rounded p-2 whitespace-pre-wrap overflow-auto max-h-40">
                      {JSON.stringify(context.response, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            )}
            {context?.skipped && (
              <div className="mt-4 text-xs text-neutral-500">
                ⏭ 已跳过 — {context.reason ?? "已有 selected_take"}
              </div>
            )}
          </div>
        )}

        <div className="border-t border-neutral-200 dark:border-neutral-700 px-4 py-3 shrink-0 flex items-center gap-3">
          <div className="text-[11px] text-neutral-400 dark:text-neutral-500 font-mono">
            attempt {attempt}{durationMs != null ? ` · ${durationMs}ms` : ""}
          </div>
          <div className="ml-auto flex items-center gap-3">
            <button type="button" onClick={() => onRetry(false)} disabled={retrying}
              className={`text-xs ${retrying ? "text-neutral-400 cursor-not-allowed" : "text-neutral-600 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-100 hover:underline"}`}>
              仅重跑 {STAGE_LABELS[stage]}
            </button>
            <button type="button" onClick={() => onRetry(true)} disabled={retrying}
              className={`px-3 py-1.5 text-xs rounded ${retrying ? "bg-neutral-200 dark:bg-neutral-700 text-neutral-400 cursor-not-allowed" : "bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 hover:bg-neutral-800 dark:hover:bg-neutral-200"}`}>
              {retrying ? "Retrying…" : `从 ${STAGE_LABELS[stage]} 起重跑 ⇣`}
            </button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
