"use client";

import type { AttemptRecord, StageName } from "@/lib/types";

interface Props {
  attempt: AttemptRecord;
  attemptIndex: number;
  isCurrent: boolean;
  isRunning?: boolean;
  onPlay?: () => void;
  onUse?: () => void;
  onStageClick?: (stage: StageName) => void;
}

const RETRY_STAGES: StageName[] = ["p2", "p2c", "p2v"];

function pillColor(
  stage: StageName,
  verdict: "pass" | "fail",
  isRunning: boolean,
): string {
  if (stage === "p2v") {
    if (isRunning) return "bg-blue-500 text-white animate-pulse";
    return verdict === "pass"
      ? "bg-emerald-500 text-white"
      : "bg-red-500 text-white";
  }
  return "bg-neutral-300 text-neutral-600";
}

function diagnosisSummary(attempt: AttemptRecord): string | null {
  const d = attempt.diagnosis;
  if (!d) return null;
  const parts: string[] = [];
  if (d.type) parts.push(d.type);
  if (d.missing?.length) parts.push(`missing: ${d.missing.join(", ")}`);
  if (d.extra?.length) parts.push(`extra: ${d.extra.join(", ")}`);
  if (d.lowConfidenceWords?.length)
    parts.push(`low-conf: ${d.lowConfidenceWords.join(", ")}`);
  return parts.length > 0 ? parts.join(" | ") : null;
}

function repairAction(attempt: AttemptRecord): string | null {
  if (attempt.verdict === "pass") return null;
  if (attempt.level >= 2) return "needs_review";
  return `L${attempt.level + 1}`;
}

export function RetryRow({
  attempt,
  attemptIndex,
  isCurrent,
  isRunning = false,
  onPlay,
  onUse,
  onStageClick,
}: Props) {
  const durationS = (attempt.durationMs / 1000).toFixed(1);
  const diag = diagnosisSummary(attempt);
  const repair = repairAction(attempt);

  const rowBg = isRunning
    ? "bg-[#f5f9ff]"
    : isCurrent && attempt.verdict === "pass"
      ? "bg-[#f0fdf4]"
      : "bg-[#fcfcfc]";

  return (
    <div
      className={`flex items-center gap-2 px-2 py-1 text-[11px] border-b border-neutral-100 ${rowBg}`}
    >
      {/* rr-indent: attempt # + level + dashed connector */}
      <div className="flex items-center gap-1 w-[172px] shrink-0">
        <span className="font-mono text-neutral-400">
          #{attemptIndex}
        </span>
        <span className="font-mono text-neutral-400">
          L{attempt.level}
        </span>
        <span className="flex-1 border-b border-dashed border-neutral-300" />
      </div>

      {/* rr-pipeline: mini P2/P2c/P2v pills */}
      <div className="flex items-center gap-0.5 shrink-0">
        {RETRY_STAGES.map((stage) => {
          const color = pillColor(stage, attempt.verdict, isRunning);
          const clickable = Boolean(onStageClick);
          return (
            <button
              key={stage}
              type="button"
              onClick={onStageClick ? () => onStageClick(stage) : undefined}
              disabled={!clickable}
              className={[
                "inline-flex items-center justify-center font-mono font-semibold uppercase tracking-wide rounded-sm",
                "h-3.5 px-1 text-[8px]",
                color,
                clickable ? "cursor-pointer hover:brightness-110" : "cursor-default",
              ].join(" ")}
            >
              {stage === "p2" ? "P2" : stage === "p2c" ? "2c" : "2v"}
            </button>
          );
        })}
      </div>

      {/* rr-take: Take label + duration + play + use */}
      <div className="flex items-center gap-1.5 shrink-0">
        <span className="font-mono text-neutral-500">
          Take #{attemptIndex}
        </span>
        <span className="font-mono text-neutral-400">{durationS}s</span>
        <button
          type="button"
          onClick={onPlay}
          className="px-1 py-0.5 rounded hover:bg-neutral-200 text-neutral-600 text-[10px]"
          title="Preview"
        >
          ▶
        </button>
        {isCurrent ? (
          <span className="text-emerald-600 text-[10px] font-medium">
            ✓ current
          </span>
        ) : (
          <button
            type="button"
            onClick={onUse}
            className="px-1.5 py-0.5 rounded bg-neutral-900 text-white hover:bg-neutral-800 text-[10px]"
          >
            Use
          </button>
        )}
      </div>

      {/* rr-verdict: PASS/FAIL + score + diagnosis + repair action */}
      <div className="flex items-center gap-1.5 flex-1 min-w-0">
        <span
          className={`font-mono font-bold text-[10px] ${
            attempt.verdict === "pass" ? "text-emerald-600" : "text-red-600"
          }`}
        >
          {attempt.verdict.toUpperCase()}
        </span>
        <span className="font-mono text-neutral-500 text-[10px]">
          {attempt.scores.weightedScore.toFixed(2)}
        </span>
        {diag && (
          <span
            className="text-neutral-400 text-[10px] truncate"
            title={diag}
          >
            {diag}
          </span>
        )}
        {repair && (
          <span className="text-amber-600 text-[10px] font-medium shrink-0">
            → {repair}
          </span>
        )}
      </div>
    </div>
  );
}
