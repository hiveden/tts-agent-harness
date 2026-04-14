"use client";

import { memo, useCallback, useState } from "react";
import type { Chunk, ChunkEdit, ChunkStatus, StageName } from "@/lib/types";
import { getDisplaySubtitle, stripControlMarkers } from "@/lib/utils";
import { useHarnessStore } from "@/lib/store";
import { useAudioPlayer } from "@/hooks/useAudioPlayer";
import { KaraokeSubtitle } from "./KaraokeSubtitle";
import { RetryRow } from "./RetryRow";
import { StagePipeline } from "./StagePipeline";
import { VerifyScoreBar } from "./VerifyScoreBar";
import { TakeSelector } from "./TakeSelector";
import { GRID_COLS } from "./chunks-grid";

export type DirtyType = null | "tts" | "subtitle" | "both";
export type DisplayMode = "subtitle" | "tts";

interface Props {
  chunk: Chunk;
  displayMode: DisplayMode;
  onStageClick?: (stage: StageName) => void;
  onPreviewTake?: (takeId: string) => void;
  onUseTake?: (takeId: string) => void;
  onSynthesize?: () => void;
  synthesizing?: boolean;
  getAudioUrl: (uri: string) => string;
}

function computeDirty(edit: ChunkEdit | undefined): DirtyType {
  if (!edit) return null;
  const hasTts = edit.textNormalized !== undefined;
  const hasSub = edit.subtitleText !== undefined;
  if (hasTts && hasSub) return "both";
  if (hasTts) return "tts";
  if (hasSub) return "subtitle";
  return null;
}

function statusIcon(status: ChunkStatus) {
  switch (status) {
    case "verified":
      return <span className="text-emerald-500">✓</span>;
    case "synth_done":
      return <span className="text-blue-500">◐</span>;
    case "needs_review":
      return <span className="text-amber-500">🔍</span>;
    case "pending":
      return <span className="text-neutral-300 dark:text-neutral-600">○</span>;
    case "failed":
      return <span className="text-red-500">✗</span>;
    default:
      return <span className="text-neutral-300 dark:text-neutral-600">○</span>;
  }
}

export const ChunkRow = memo(function ChunkRow({
  chunk,
  displayMode,
  onStageClick,
  onPreviewTake,
  onUseTake,
  onSynthesize,
  synthesizing = false,
  getAudioUrl,
}: Props) {
  // --- Zustand selectors ---
  const isEditing = useHarnessStore((s) => s.editing === chunk.id);
  const edit = useHarnessStore((s) => s.edits[chunk.id]);
  const startEditing = useHarnessStore((s) => s.startEditing);
  const cancelEditing = useHarnessStore((s) => s.cancelEditing);

  const dirty = computeDirty(edit);
  const isDirty = dirty !== null;
  const hasSubField = chunk.subtitleText != null;

  const currentTakeForUrl = chunk.takes.find((t) => t.id === chunk.selectedTakeId);
  const cacheBust = currentTakeForUrl?.createdAt
    ? `?v=${encodeURIComponent(currentTakeForUrl.createdAt)}`
    : `?v=${chunk.charCount}`;
  const audioUrl =
    chunk.selectedTakeId &&
    currentTakeForUrl &&
    (chunk.status === "synth_done" || chunk.status === "verified" || chunk.status === "needs_review")
      ? getAudioUrl(currentTakeForUrl.audioUri) + cacheBust
      : "";

  let displayText: string;
  if (displayMode === "tts") {
    displayText =
      edit?.textNormalized !== undefined
        ? edit.textNormalized
        : chunk.textNormalized;
  } else {
    displayText =
      edit?.subtitleText !== undefined
        ? stripControlMarkers(edit.subtitleText)
        : getDisplaySubtitle(chunk);
  }

  const currentTake = chunk.takes.find((t) => t.id === chunk.selectedTakeId);
  const durationS = currentTake?.durationS ?? 0;

  // --- Audio player (single source of truth for play/pause/seek) ---
  const player = useAudioPlayer(chunk.id, durationS);

  const [verifyExpanded, setVerifyExpanded] = useState(false);
  const toggleVerify = useCallback(() => setVerifyExpanded((v) => !v), []);

  const hasAudio = chunk.status === "synth_done" || chunk.status === "verified" || chunk.status === "needs_review";
  const canPlay = hasAudio && !isDirty;
  const needsSynth = chunk.status === "pending" && !isDirty;

  const onEdit = () => startEditing(chunk.id);

  const { isPlaying } = player;

  const rowBg = isPlaying
    ? "bg-blue-50 dark:bg-blue-900/20 shadow-[inset_3px_0_0_#2563eb]"
    : isEditing
      ? "bg-neutral-50 dark:bg-neutral-800"
      : chunk.status === "needs_review"
        ? "bg-amber-50 dark:bg-amber-900/20 hover:bg-amber-100/60 dark:hover:bg-amber-900/30"
        : isDirty
          ? "bg-amber-50/30 dark:bg-amber-900/10 hover:bg-amber-50/50 dark:hover:bg-amber-900/20"
          : "hover:bg-neutral-50 dark:hover:bg-neutral-800";

  let dirtyBadge: string | null = null;
  if (dirty === "tts") dirtyBadge = "TTS dirty";
  else if (dirty === "subtitle") dirtyBadge = "SUB dirty";
  else if (dirty === "both") dirtyBadge = "TTS+SUB dirty";

  const baseColor = isDirty ? "text-amber-900 dark:text-amber-200" : "text-neutral-700 dark:text-neutral-300";

  return (
    <div
      className={`grid border-b border-neutral-100 dark:border-neutral-700 text-sm ${rowBg}`}
      style={{ gridTemplateColumns: GRID_COLS }}
    >
      <div className="px-6 py-2.5 font-mono text-[11px] text-neutral-500 dark:text-neutral-400 self-start">
        {chunk.id}
        {hasSubField ? (
          <span
            className="ml-1 text-[9px] text-purple-500"
            title="subtitle_text set"
          >
            ◆
          </span>
        ) : null}
      </div>
      <div className="py-2.5 self-start">{statusIcon(chunk.status)}</div>
      <div className="py-2.5 self-start text-[11px] text-neutral-500 dark:text-neutral-400 font-mono">
        {durationS > 0 ? `${durationS.toFixed(1)}s` : "--"}
      </div>
      <div className="py-2.5 self-start">
        {needsSynth ? (
          <button
            type="button"
            onClick={onSynthesize}
            disabled={synthesizing}
            title="合成并播放"
            className={`w-7 h-7 inline-flex items-center justify-center rounded ${
              synthesizing
                ? "text-blue-400 animate-pulse cursor-wait"
                : "hover:bg-blue-100 text-blue-600"
            }`}
          >
            ▸
          </button>
        ) : (
          <button
            type="button"
            onClick={player.toggle}
            disabled={!canPlay}
            title={isDirty ? "Has staged changes, Apply first" : ""}
            className={`w-7 h-7 inline-flex items-center justify-center rounded ${
              canPlay
                ? "hover:bg-neutral-200 dark:hover:bg-neutral-700 text-neutral-700 dark:text-neutral-300"
                : "text-neutral-300 dark:text-neutral-600 cursor-not-allowed"
            } ${isPlaying ? "bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 hover:bg-neutral-800 dark:hover:bg-neutral-200" : ""}`}
          >
            {isPlaying ? "⏸" : "▶"}
          </button>
        )}
      </div>
      <div className="py-2.5 pr-6 self-start">
        <div className="flex items-start flex-wrap">
          <div className="flex-1 min-w-0">
            <KaraokeSubtitle
              text={displayText}
              durationS={durationS}
              isPlaying={isPlaying}
              currentTime={player.currentTime}
              baseColorClass={baseColor}
              onSeek={canPlay ? player.seekTo : undefined}
            />
          </div>
          {dirtyBadge ? (
            <span className="ml-2 text-[10px] px-1.5 py-0.5 bg-amber-100 dark:bg-amber-800/30 text-amber-700 dark:text-amber-300 rounded shrink-0">
              {dirtyBadge}
            </span>
          ) : null}
        </div>
        {chunk.stageRuns.length > 0 && (
          <div className="mt-1">
            <StagePipeline
              stageRuns={chunk.stageRuns}
              onStageClick={onStageClick}
              compact
            />
          </div>
        )}
        {chunk.verifyScores && chunk.verifyScores.weightedScore != null && (
          <div className="mt-1">
            <button
              type="button"
              onClick={toggleVerify}
              className="flex items-center gap-1.5 text-[11px] w-full text-left group"
            >
              <span className="text-neutral-400 dark:text-neutral-500 text-[9px] group-hover:text-neutral-600 dark:group-hover:text-neutral-300 transition-colors">
                {verifyExpanded ? "▾" : "▸"}
              </span>
              <span className="font-mono font-bold text-neutral-600 dark:text-neutral-300">
                {chunk.verifyScores.weightedScore.toFixed(2)}
              </span>
              <span
                className={`px-1 py-0.5 rounded text-[9px] font-bold ${
                  chunk.verifyDiagnosis?.verdict === "fail" || chunk.verifyScores.weightedScore < 0.7
                    ? "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300"
                    : "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300"
                }`}
              >
                {chunk.verifyDiagnosis?.verdict === "fail" || chunk.verifyScores.weightedScore < 0.7 ? "FAIL" : "PASS"}
              </span>
              {chunk.verifyDiagnosis?.detail && (
                <span className="px-1 py-0.5 rounded text-[9px] bg-neutral-100 dark:bg-neutral-700 text-neutral-500 dark:text-neutral-400 truncate max-w-[300px]" title={chunk.verifyDiagnosis.detail}>
                  {chunk.verifyDiagnosis.detail}
                </span>
              )}
            </button>
            {verifyExpanded && (
              <div className="mt-1 pl-3">
                <VerifyScoreBar scores={chunk.verifyScores} />
              </div>
            )}
          </div>
        )}
        {chunk.takes.length > 1 ? (
          <TakeSelector
            takes={chunk.takes}
            selectedTakeId={chunk.selectedTakeId}
            onPreview={onPreviewTake}
            onUse={onUseTake}
          />
        ) : null}
        {chunk.attemptHistory && chunk.attemptHistory.length > 0 && (
          <div className="mt-1 border border-neutral-200 dark:border-neutral-700 rounded overflow-hidden">
            {chunk.attemptHistory.map((att, i) => (
              <RetryRow
                key={`${att.attempt}-${att.timestamp}`}
                attempt={att}
                attemptIndex={i + 1}
                isCurrent={i === chunk.attemptHistory!.length - 1 && att.verdict === "pass"}
                onStageClick={onStageClick}
              />
            ))}
          </div>
        )}
        {audioUrl ? (
          <audio
            key={audioUrl}
            ref={player.ref}
            src={audioUrl}
            preload="metadata"
            className="hidden"
          />
        ) : null}
      </div>
      <div className="py-2.5 pr-6 self-start text-right">
        <button
          type="button"
          onClick={isEditing ? cancelEditing : onEdit}
          title={isEditing ? "Close edit" : "Edit"}
          className={`w-7 h-7 inline-flex items-center justify-center rounded ${
            isEditing
              ? "bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 hover:bg-neutral-800 dark:hover:bg-neutral-200"
              : "hover:bg-neutral-200 dark:hover:bg-neutral-700 text-neutral-700 dark:text-neutral-300"
          }`}
        >
          {isEditing ? "✕" : "✎"}
        </button>
      </div>
    </div>
  );
}, (prev, next) => {
  // Zustand selector handles isPlaying/isEditing/edit re-renders automatically.
  // We only need to compare the props we receive.
  return prev.chunk === next.chunk
    && prev.displayMode === next.displayMode
    && prev.synthesizing === next.synthesizing
    && prev.onStageClick === next.onStageClick
    && prev.onPreviewTake === next.onPreviewTake
    && prev.onUseTake === next.onUseTake
    && prev.onSynthesize === next.onSynthesize
    && prev.getAudioUrl === next.getAudioUrl;
});
