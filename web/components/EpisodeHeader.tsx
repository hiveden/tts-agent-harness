"use client";

import { useEffect, useRef, useState } from "react";
import type { Episode, EpisodeStatus } from "@/lib/types";

interface Props {
  episode: Episode;
  running: boolean;
  onRun: () => void;
}

const STATUS_BADGE: Record<
  EpisodeStatus,
  { bg: string; fg: string; br: string; label: string }
> = {
  done: {
    bg: "bg-emerald-50",
    fg: "text-emerald-700",
    br: "border-emerald-200",
    label: "done",
  },
  running: {
    bg: "bg-blue-50",
    fg: "text-blue-700",
    br: "border-blue-200",
    label: "running",
  },
  ready: {
    bg: "bg-neutral-50",
    fg: "text-neutral-600",
    br: "border-neutral-200",
    label: "ready",
  },
  failed: {
    bg: "bg-red-50",
    fg: "text-red-700",
    br: "border-red-200",
    label: "failed",
  },
  empty: {
    bg: "bg-neutral-50",
    fg: "text-neutral-500",
    br: "border-neutral-200",
    label: "empty",
  },
};

interface ConfirmConfig {
  variant: "blue" | "amber" | "red";
  label: string;
  title: string;
  body: string;
  action: string;
}

function getRunConfirm(status: EpisodeStatus): ConfirmConfig {
  switch (status) {
    case "ready":
    case "empty":
      return {
        variant: "blue",
        label: "Generate",
        title: "Start generation",
        body: "This will run the full TTS pipeline (P1-P6). It may take several minutes.",
        action: "Start",
      };
    case "failed":
      return {
        variant: "amber",
        label: "Retry",
        title: "Retry failed pipeline",
        body: "The previous pipeline run failed. Retry will restart from the beginning, skipping already-completed chunks.",
        action: "Retry",
      };
    case "done":
      return {
        variant: "red",
        label: "Re-run",
        title: "Re-run completed episode",
        body: "This episode is already done. Re-running will re-synthesize all chunks. To fix specific chunks, use the edit workflow instead.",
        action: "Confirm re-run",
      };
    case "running":
    default:
      return {
        variant: "blue",
        label: "Run",
        title: "",
        body: "",
        action: "",
      };
  }
}

export function EpisodeHeader({
  episode,
  running,
  onRun,
}: Props) {
  const badge = STATUS_BADGE[episode.status] ?? STATUS_BADGE.ready;
  const runDisabled = running;

  const confirm = getRunConfirm(episode.status);
  const [popoverOpen, setPopoverOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!popoverOpen) return;
    const onDocClick = (e: MouseEvent) => {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(e.target as Node)
      ) {
        setPopoverOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [popoverOpen]);

  useEffect(() => {
    if (!popoverOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPopoverOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [popoverOpen]);

  const handleRunClick = () => {
    if (runDisabled) return;
    setPopoverOpen(true);
  };

  const handleConfirm = () => {
    setPopoverOpen(false);
    onRun();
  };

  const variantClasses = {
    blue: {
      btn: "bg-neutral-900 text-white hover:bg-neutral-800",
      bar: "border-blue-200 bg-blue-50",
      icon: "text-blue-600",
      action: "bg-blue-600 text-white hover:bg-blue-700",
    },
    amber: {
      btn: "bg-amber-600 text-white hover:bg-amber-700",
      bar: "border-amber-200 bg-amber-50",
      icon: "text-amber-600",
      action: "bg-amber-600 text-white hover:bg-amber-700",
    },
    red: {
      btn: "bg-neutral-900 text-white hover:bg-neutral-800",
      bar: "border-red-200 bg-red-50",
      icon: "text-red-600",
      action: "bg-red-600 text-white hover:bg-red-700",
    },
  }[confirm.variant];

  // Compute total duration from selected takes
  const totalDurationS = episode.chunks.reduce((sum, c) => {
    const selectedTake = c.takes.find((t) => t.id === c.selectedTakeId);
    return sum + (selectedTake?.durationS ?? 0);
  }, 0);

  return (
    <div className="px-6 py-3 border-b border-neutral-200 bg-white shrink-0">
      <div className="flex items-center gap-3 mb-2">
        <h2 className="text-lg font-semibold">{episode.title}</h2>
        <span className="text-xs text-neutral-400 font-mono">{episode.id}</span>
        <span
          className={`text-xs px-2 py-0.5 rounded-full border ${badge.bg} ${badge.fg} ${badge.br}`}
        >
          {badge.label}
        </span>
        <span className="ml-auto text-[11px] text-neutral-400 font-mono">
          {episode.chunks.length} chunks · {totalDurationS.toFixed(1)}s
        </span>
      </div>
      <div className="flex gap-2">
        <div className="relative" ref={popoverRef}>
          <button
            type="button"
            onClick={handleRunClick}
            disabled={runDisabled}
            className={`px-3 py-1.5 text-sm rounded ${variantClasses.btn} ${
              runDisabled ? "opacity-50 cursor-not-allowed" : ""
            }`}
          >
            {confirm.label}
          </button>

          {popoverOpen && !runDisabled && (
            <div
              className={`absolute left-0 top-full mt-2 w-80 z-30 rounded-lg border shadow-lg ${variantClasses.bar}`}
            >
              <div className="p-3">
                <div className="flex items-start gap-2 mb-2">
                  <span className={`text-base ${variantClasses.icon}`}>
                    {confirm.variant === "red" ? "!" : "i"}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-neutral-900">
                      {confirm.title}
                    </div>
                  </div>
                </div>
                <p className="text-xs text-neutral-700 leading-relaxed mb-3">
                  {confirm.body}
                </p>
                <div className="flex gap-2 justify-end">
                  <button
                    type="button"
                    onClick={() => setPopoverOpen(false)}
                    className="px-2.5 py-1 text-xs text-neutral-600 hover:bg-white/60 rounded"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={handleConfirm}
                    className={`px-3 py-1 text-xs rounded ${variantClasses.action}`}
                  >
                    {confirm.action}
                  </button>
                </div>
              </div>
              <div
                className={`absolute -top-1.5 left-4 w-3 h-3 rotate-45 border-t border-l ${variantClasses.bar}`}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
