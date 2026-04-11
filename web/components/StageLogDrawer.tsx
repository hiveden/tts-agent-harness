"use client";

import { useEffect, useState } from "react";
import type { StageName, StageRun } from "@/lib/types";

interface Props {
  open: boolean;
  onClose: () => void;
  episodeId: string;
  chunkId: string;
  stage: StageName;
  stageRun: StageRun | undefined;
  onAfterRetry?: () => void;
  hasUnsavedEdits?: boolean;
  unsavedEditSource?: "editor" | "staged" | null;
}

const STAGE_LABELS: Record<StageName, string> = {
  p1: "P1", p2: "P2", check2: "CHECK2",
  p3: "P3", check3: "CHECK3", p5: "P5", p6: "P6",
};

function statusBadge(sr: StageRun | undefined) {
  const base = "text-[10px] font-mono uppercase px-1.5 py-0.5 rounded tracking-wide";
  const status = sr?.status ?? "pending";
  switch (status) {
    case "pending": return <span className={`${base} bg-neutral-200 text-neutral-600`}>pending</span>;
    case "running": return <span className={`${base} bg-blue-500 text-white animate-pulse`}>running</span>;
    case "ok": return <span className={`${base} bg-emerald-500 text-white`}>ok</span>;
    case "failed": return <span className={`${base} bg-red-500 text-white`}>failed</span>;
  }
}

export function StageLogDrawer({
  open, onClose, episodeId, chunkId, stage, stageRun,
  onAfterRetry, hasUnsavedEdits = false, unsavedEditSource = null,
}: Props) {
  const [log, setLog] = useState("");
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);

  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8100";

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setFetchError(null);
    setLog("");
    fetch(`${apiBase}/episodes/${encodeURIComponent(episodeId)}/chunks/${encodeURIComponent(chunkId)}/log?stage=${encodeURIComponent(stage)}`)
      .then(async (r) => {
        if (cancelled) return;
        if (r.status === 404) { setLog(""); return; }
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = await r.json();
        if (!cancelled) setLog(data.content ?? "");
      })
      .catch((e: unknown) => { if (!cancelled) setFetchError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [open, episodeId, chunkId, stage, apiBase]);

  if (!open) return null;

  const doRetry = async (cascade: boolean) => {
    if (retrying) return;
    setRetrying(true);
    try {
      const r = await fetch(`${apiBase}/episodes/${encodeURIComponent(episodeId)}/chunks/${encodeURIComponent(chunkId)}/retry`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ from_stage: stage, cascade }),
      });
      if (!r.ok) { const msg = await r.text().catch(() => ""); throw new Error(`HTTP ${r.status}${msg ? ` — ${msg}` : ""}`); }
      onAfterRetry?.();
      onClose();
    } catch (e: unknown) {
      alert(`Retry failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setRetrying(false);
    }
  };

  const attempt = stageRun?.attempt ?? 0;
  const durationMs = stageRun?.durationMs;

  return (
    <>
      <div className="fixed inset-0 bg-black/20 z-30" onClick={onClose} aria-hidden />
      <div className="fixed right-0 top-0 h-full w-[30rem] bg-white shadow-2xl z-40 flex flex-col">
        <div className="h-12 border-b border-neutral-200 flex items-center px-4 gap-2 shrink-0">
          <span className="font-mono text-xs text-neutral-700">{chunkId}</span>
          <span className="text-neutral-300">·</span>
          <span className="font-mono text-xs font-semibold">{STAGE_LABELS[stage]}</span>
          <span className="ml-1">{statusBadge(stageRun)}</span>
          <button type="button" onClick={onClose} className="ml-auto w-7 h-7 inline-flex items-center justify-center rounded hover:bg-neutral-100 text-neutral-500" title="关闭">✕</button>
        </div>

        {stageRun?.status === "failed" && stageRun.error ? (
          <div className="px-4 py-2 bg-red-50 border-b border-red-200 text-xs text-red-700 shrink-0">
            <div className="font-semibold mb-0.5">Error</div>
            <div className="font-mono whitespace-pre-wrap break-words">{stageRun.error}</div>
          </div>
        ) : null}

        {loading ? (
          <div className="flex-1 flex items-center justify-center text-xs text-neutral-400">加载日志中…</div>
        ) : log !== "" ? (
          <pre className="text-xs font-mono whitespace-pre-wrap p-4 overflow-auto flex-1 bg-neutral-50">{log}</pre>
        ) : (
          <div className="flex-1 overflow-auto p-4 text-xs">
            {stageRun ? (
              <div className="space-y-2">
                <div className="text-neutral-500">Stage 执行信息（日志文件暂不可用）</div>
                <table className="text-[11px] w-full">
                  <tbody className="divide-y divide-neutral-100">
                    <tr><td className="py-1 text-neutral-400 w-24">Status</td><td className="py-1 font-mono">{stageRun.status}</td></tr>
                    <tr><td className="py-1 text-neutral-400">Attempt</td><td className="py-1 font-mono">{stageRun.attempt}</td></tr>
                    {stageRun.startedAt && <tr><td className="py-1 text-neutral-400">Started</td><td className="py-1 font-mono">{stageRun.startedAt}</td></tr>}
                    {stageRun.finishedAt && <tr><td className="py-1 text-neutral-400">Finished</td><td className="py-1 font-mono">{stageRun.finishedAt}</td></tr>}
                    {stageRun.durationMs != null && <tr><td className="py-1 text-neutral-400">Duration</td><td className="py-1 font-mono">{stageRun.durationMs}ms</td></tr>}
                    {stageRun.error && <tr><td className="py-1 text-neutral-400">Error</td><td className="py-1 font-mono text-red-600 whitespace-pre-wrap">{stageRun.error}</td></tr>}
                    {stageRun.stale && <tr><td className="py-1 text-neutral-400">Stale</td><td className="py-1 text-amber-600">上游已更新，此 stage 未同步</td></tr>}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="text-neutral-400 text-center mt-8">暂无日志</div>
            )}
          </div>
        )}

        {hasUnsavedEdits ? (
          <div className="px-4 py-2.5 bg-amber-50 border-t border-amber-200 text-xs text-amber-900 shrink-0">
            <div className="font-semibold mb-0.5">未保存改动</div>
            <div className="leading-relaxed">
              {unsavedEditSource === "editor"
                ? "编辑器打开中，请先保存或取消。"
                : "有 staged 改动，请先 Apply。"}
            </div>
          </div>
        ) : null}

        <div className="border-t border-neutral-200 px-4 py-3 shrink-0 flex items-center gap-3">
          <div className="text-[11px] text-neutral-400 font-mono">
            attempt {attempt}{durationMs != null ? ` · ${durationMs}ms` : ""}
          </div>
          <div className="ml-auto flex items-center gap-3">
            <button type="button" onClick={() => doRetry(false)} disabled={retrying || hasUnsavedEdits}
              className={`text-xs ${retrying || hasUnsavedEdits ? "text-neutral-400 cursor-not-allowed" : "text-neutral-600 hover:text-neutral-900 hover:underline"}`}>
              仅重跑 {STAGE_LABELS[stage]}
            </button>
            <button type="button" onClick={() => doRetry(true)} disabled={retrying || hasUnsavedEdits}
              className={`px-3 py-1.5 text-xs rounded ${retrying || hasUnsavedEdits ? "bg-neutral-200 text-neutral-400 cursor-not-allowed" : "bg-neutral-900 text-white hover:bg-neutral-800"}`}>
              {retrying ? "Retrying…" : `从 ${STAGE_LABELS[stage]} 起重跑 ⇣`}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
