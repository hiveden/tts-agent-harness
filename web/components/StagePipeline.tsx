"use client";

import type { StageName, StageRun } from "@/lib/types";
import { STAGE_ORDER, CHUNK_STAGE_ORDER, getStageRun } from "@/lib/types";

interface Props {
  stageRuns: StageRun[];
  onStageClick?: (stage: StageName) => void;
  compact?: boolean;
}

const FULL_LABELS: Record<StageName, string> = {
  p1: "P1",
  p1c: "P1c",
  p2: "P2",
  p2c: "P2c",
  p2v: "P2v",
  p5: "P5",
  p6: "P6",
  p6v: "P6v",
};

const COMPACT_LABELS: Record<StageName, string> = {
  p1: "P1",
  p1c: "1c",
  p2: "P2",
  p2c: "2c",
  p2v: "2v",
  p5: "P5",
  p6: "P6",
  p6v: "6v",
};

const GATE_STAGES = new Set<StageName>(["p1c", "p2c", "p2v", "p6v"]);

function isGate(stage: StageName): boolean {
  return GATE_STAGES.has(stage);
}

function stageColorClasses(sr: StageRun | undefined): string {
  if (!sr || sr.status === "pending") return "bg-neutral-200 dark:bg-neutral-700 text-neutral-500 dark:text-neutral-400";
  if (sr.status === "running") return "bg-blue-500 text-white animate-pulse";
  if (sr.status === "ok") return "bg-emerald-500 text-white";
  return "bg-red-500 text-white";
}

function formatDuration(ms: number | undefined): string {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function buildTitle(stage: StageName, sr: StageRun | undefined): string {
  const label = FULL_LABELS[stage];
  if (!sr) return `${label}: pending`;
  const parts: string[] = [`${label}: ${sr.status}`];
  if (sr.stale) parts.push("stale — upstream updated");
  if (sr.attempt > 1) parts.push(`attempt ${sr.attempt}`);
  if (sr.durationMs != null) parts.push(formatDuration(sr.durationMs));
  if (sr.status === "failed" && sr.error) parts.push(sr.error);
  return parts.join(" · ");
}

export function StagePipeline({
  stageRuns,
  onStageClick,
  compact = false,
}: Props) {
  const labels = compact ? COMPACT_LABELS : FULL_LABELS;
  const pillSize = compact
    ? "h-5 px-1.5 text-[10px]"
    : "h-6 px-2 text-xs";
  const clickable = Boolean(onStageClick);

  return (
    <div className="inline-flex items-center">
      {(compact ? CHUNK_STAGE_ORDER : STAGE_ORDER).map((stage, idx) => {
        const sr = getStageRun(stageRuns, stage);
        const color = stageColorClasses(sr);
        const hover = clickable ? "cursor-pointer hover:brightness-110" : "";
        const title = buildTitle(stage, sr);
        const isFailed = sr?.status === "failed";
        const isRunning = sr?.status === "running";
        const isStale = !!sr?.stale;
        const showAttemptBadge = (sr?.attempt ?? 0) > 1;

        const gate = isGate(stage);
        const stages = compact ? CHUNK_STAGE_ORDER : STAGE_ORDER;
        const prevGate = idx > 0 && isGate(stages[idx - 1]);
        const connectorWidth = gate || prevGate ? "w-1" : "w-2";

        return (
          <div key={stage} className="inline-flex items-center">
            {idx > 0 && (
              <span aria-hidden className={`inline-block h-px ${connectorWidth} bg-neutral-300 dark:bg-neutral-600`} />
            )}
            <button
              type="button"
              title={title}
              onClick={onStageClick ? () => onStageClick(stage) : undefined}
              disabled={!clickable}
              className={[
                "relative inline-flex items-center gap-1 font-mono font-semibold uppercase tracking-wide transition",
                gate ? "rounded-sm text-[9px] h-4 px-1" : `rounded-full ${pillSize}`,
                color,
                hover,
                clickable ? "" : "cursor-default",
                isStale ? "ring-2 ring-amber-500 ring-offset-1" : "",
              ]
                .filter(Boolean)
                .join(" ")}
            >
              <span>{labels[stage]}</span>
              {isFailed && <span aria-label="failed" className="leading-none">⚠</span>}
              {isStale && !isFailed && <span aria-label="stale" className="leading-none text-[11px]">⟳</span>}
              {isRunning && <span aria-hidden className="inline-block h-1.5 w-1.5 rounded-full bg-white/90" />}
              {showAttemptBadge && (
                <sup
                  aria-label={`attempt ${sr!.attempt}`}
                  className="absolute -top-1 -right-1 rounded-full bg-neutral-900 px-1 text-[9px] font-bold leading-tight text-white"
                >
                  {sr!.attempt}
                </sup>
              )}
            </button>
          </div>
        );
      })}
    </div>
  );
}
