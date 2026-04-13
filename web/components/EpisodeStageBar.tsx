"use client";

import type { Chunk, StageName } from "@/lib/types";

interface Props {
  chunks: Chunk[];
  onStageRetry?: (stage: StageName) => void;
}

/** Stages to display at episode level (skip p1/p6 — they're episode-scoped, not per-chunk). */
const CHUNK_STAGES: StageName[] = ["p2", "p2c", "p2v", "p5"];

const GATE_STAGES = new Set<StageName>(["p1c", "p2c", "p2v", "p6v"]);

interface StageAgg {
  total: number;
  ok: number;
  failed: number;
  running: number;
  pending: number;
}

function aggregate(chunks: Chunk[], stage: StageName): StageAgg {
  const agg: StageAgg = { total: chunks.length, ok: 0, failed: 0, running: 0, pending: 0 };
  for (const c of chunks) {
    const sr = c.stageRuns.find((r) => r.stage === stage);
    if (!sr || sr.status === "pending") agg.pending++;
    else if (sr.status === "ok") agg.ok++;
    else if (sr.status === "failed") agg.failed++;
    else if (sr.status === "running") agg.running++;
  }
  return agg;
}

function pillColor(agg: StageAgg): string {
  if (agg.running > 0) return "bg-blue-500 text-white animate-pulse";
  if (agg.failed > 0) return "bg-red-100 text-red-700 border border-red-300";
  if (agg.ok === agg.total && agg.total > 0) return "bg-emerald-500 text-white";
  if (agg.ok > 0) return "bg-emerald-100 text-emerald-700 border border-emerald-300";
  return "bg-neutral-200 text-neutral-500";
}

function pillLabel(stage: StageName, agg: StageAgg): string {
  const label = stage.toUpperCase();
  if (agg.running > 0) return `${label}...`;
  if (agg.failed > 0) return `${label} ⚠${agg.failed}`;
  if (agg.ok === agg.total && agg.total > 0) return `${label} ✓`;
  if (agg.ok > 0) return `${label} ${agg.ok}/${agg.total}`;
  return label;
}

/**
 * Episode-level stage progress bar (D-06).
 *
 * Aggregates per-chunk stageRuns into a pipeline overview:
 *   P2 [17/20 ⚠3] ─── P3 [17/17 ✓] ─── P5 [17/17 ✓]
 *
 * Clicking a stage with failures triggers onStageRetry.
 */
export function EpisodeStageBar({ chunks, onStageRetry }: Props) {
  if (chunks.length === 0) return null;

  return (
    <div className="px-6 py-1.5 border-b border-neutral-100 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 flex items-center gap-1 shrink-0">
      <span className="text-[10px] text-neutral-400 dark:text-neutral-500 mr-2 uppercase tracking-wide">Pipeline</span>
      {CHUNK_STAGES.map((stage, idx) => {
        const agg = aggregate(chunks, stage);
        const color = pillColor(agg);
        const label = pillLabel(stage, agg);
        const clickable = agg.failed > 0 && onStageRetry;
        return (
          <div key={stage} className="inline-flex items-center">
            {idx > 0 && <span className="inline-block w-3 h-px bg-neutral-300 dark:bg-neutral-600 mx-0.5" />}
            <button
              type="button"
              disabled={!clickable}
              onClick={clickable ? () => onStageRetry(stage) : undefined}
              title={
                agg.failed > 0
                  ? `${agg.failed} failed — click to retry`
                  : `${agg.ok}/${agg.total} complete`
              }
              className={`inline-flex items-center px-2 py-0.5 ${
                GATE_STAGES.has(stage) ? "rounded-sm text-[9px]" : "rounded-full text-[10px]"
              } font-mono font-semibold ${color} ${
                clickable ? "cursor-pointer hover:brightness-110" : "cursor-default"
              }`}
            >
              {label}
            </button>
          </div>
        );
      })}
    </div>
  );
}
