"use client";

import type { VerifyScores } from "@/lib/types";

interface Props {
  scores: VerifyScores;
}

interface ScoreEntry {
  key: keyof Omit<VerifyScores, "weightedScore">;
  label: string;
}

const ENTRIES: ScoreEntry[] = [
  { key: "durationRatio", label: "时长/字数比" },
  { key: "silence", label: "静音检测" },
  { key: "phoneticDistance", label: "音素距离" },
  { key: "charRatio", label: "字符比" },
  { key: "asrConfidence", label: "ASR置信度" },
];

function scoreColor(v: number): string {
  if (v >= 0.7) return "bg-emerald-500";
  if (v >= 0.5) return "bg-amber-400";
  return "bg-red-500";
}

function scoreIcon(v: number): string {
  if (v >= 0.7) return "\u2713";
  if (v >= 0.5) return "\u25B3";
  return "\u2717";
}

function scoreIconColor(v: number): string {
  if (v >= 0.7) return "text-emerald-600";
  if (v >= 0.5) return "text-amber-500";
  return "text-red-500";
}

export function VerifyScoreBar({ scores }: Props) {
  const pass = scores.weightedScore >= 0.7;

  return (
    <div className="space-y-1 text-[11px]">
      {ENTRIES.map(({ key, label }) => {
        const v = scores[key];
        const pct = Math.min(100, Math.max(0, v * 100));
        return (
          <div key={key} className="flex items-center gap-1.5">
            <span className="w-[80px] text-neutral-500 truncate">{label}</span>
            <span className={`w-4 text-center font-bold ${scoreIconColor(v)}`}>
              {scoreIcon(v)}
            </span>
            <div className="w-[120px] h-2 bg-neutral-200 dark:bg-neutral-700 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full ${scoreColor(v)}`}
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="w-8 text-right font-mono text-neutral-600">
              {v.toFixed(2)}
            </span>
          </div>
        );
      })}
      <div className="border-t border-neutral-200 dark:border-neutral-700 pt-1 mt-1 flex items-center gap-1.5">
        <span className="w-[80px] text-neutral-600 dark:text-neutral-400 font-medium">综合</span>
        <span className="w-4" />
        <span className="font-mono font-bold text-neutral-700 dark:text-neutral-300">
          {scores.weightedScore.toFixed(2)}
        </span>
        <span
          className={`ml-1 px-1.5 py-0.5 rounded text-[10px] font-bold ${
            pass
              ? "bg-emerald-100 text-emerald-700"
              : "bg-red-100 text-red-700"
          }`}
        >
          {pass ? "PASS" : "FAIL"}
        </span>
      </div>
    </div>
  );
}
