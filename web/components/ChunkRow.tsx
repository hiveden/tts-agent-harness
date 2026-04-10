"use client";

import { useEffect, useRef, useState } from "react";
import type { Chunk, ChunkEdit, ChunkStatus } from "@/lib/types";
import { getDisplaySubtitle, stripControlMarkers } from "@/lib/utils";
import { getAudioUrl } from "@/lib/hooks";
import { KaraokeSubtitle } from "./KaraokeSubtitle";
import { TakeSelector } from "./TakeSelector";

export type DirtyType = null | "tts" | "subtitle" | "both";
export type DisplayMode = "subtitle" | "tts";

interface Props {
  episodeId: string;
  chunk: Chunk;
  displayMode: DisplayMode;
  isPlaying: boolean;
  isEditing: boolean;
  dirty: DirtyType;
  edit?: ChunkEdit;
  onPlay: () => void;
  onEdit: () => void;
  onCancelEdit: () => void;
}

function statusIcon(status: ChunkStatus) {
  switch (status) {
    case "transcribed":
    case "synth_done":
      return <span className="text-emerald-500">✓</span>;
    case "pending":
      return <span className="text-neutral-300">○</span>;
    case "failed":
      return <span className="text-red-500">✗</span>;
    default:
      return <span className="text-neutral-300">○</span>;
  }
}

export function ChunkRow({
  episodeId,
  chunk,
  displayMode,
  isPlaying,
  isEditing,
  dirty,
  edit,
  onPlay,
  onEdit,
  onCancelEdit,
}: Props) {
  void episodeId; // kept for future use
  const isDirty = dirty !== null;
  const hasSubField = chunk.subtitleText != null;
  const audioRef = useRef<HTMLAudioElement>(null);
  const [currentTime, setCurrentTime] = useState(0);

  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;
    if (isPlaying) {
      el.play().catch((e) => {
        console.warn("audio play failed", e);
      });
    } else {
      el.pause();
    }
  }, [isPlaying]);

  const currentTakeForUrl = chunk.takes.find((t) => t.id === chunk.selectedTakeId);
  const cacheBust = currentTakeForUrl?.createdAt
    ? `?v=${encodeURIComponent(currentTakeForUrl.createdAt)}`
    : `?v=${chunk.charCount}`;
  const audioUrl =
    chunk.selectedTakeId &&
    currentTakeForUrl &&
    (chunk.status === "synth_done" || chunk.status === "transcribed")
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

  const canPlay =
    (chunk.status === "synth_done" || chunk.status === "transcribed") &&
    !isDirty;

  const handleSeek = (timeS: number) => {
    if (!canPlay) return;
    const el = audioRef.current;
    const target = Math.max(0, Math.min(durationS, timeS));
    if (el) {
      el.currentTime = target;
      setCurrentTime(target);
    }
    if (!isPlaying) onPlay();
  };

  const rowBg = isPlaying
    ? "bg-blue-50 shadow-[inset_3px_0_0_#2563eb]"
    : isEditing
      ? "bg-neutral-50"
      : isDirty
        ? "bg-amber-50/30 hover:bg-amber-50/50"
        : "hover:bg-neutral-50";

  let dirtyBadge: string | null = null;
  if (dirty === "tts") dirtyBadge = "TTS dirty";
  else if (dirty === "subtitle") dirtyBadge = "SUB dirty";
  else if (dirty === "both") dirtyBadge = "TTS+SUB dirty";

  const baseColor = isDirty ? "text-amber-900" : "text-neutral-700";

  return (
    <tr className={`border-b border-neutral-100 ${rowBg}`}>
      <td className="px-6 py-2.5 font-mono text-[11px] text-neutral-500 align-top">
        {chunk.id}
        {hasSubField ? (
          <span
            className="ml-1 text-[9px] text-purple-500"
            title="subtitle_text set"
          >
            ◆
          </span>
        ) : null}
      </td>
      <td className="py-2.5 align-top">{statusIcon(chunk.status)}</td>
      <td className="py-2.5 align-top text-[11px] text-neutral-500 font-mono">
        {durationS > 0 ? `${durationS.toFixed(1)}s` : "--"}
      </td>
      <td className="py-2.5 align-top">
        <button
          type="button"
          onClick={onPlay}
          disabled={!canPlay}
          title={isDirty ? "Has staged changes, Apply first" : ""}
          className={`w-7 h-7 inline-flex items-center justify-center rounded ${
            canPlay
              ? "hover:bg-neutral-200 text-neutral-700"
              : "text-neutral-300 cursor-not-allowed"
          } ${isPlaying ? "bg-neutral-900 text-white hover:bg-neutral-800" : ""}`}
        >
          {isPlaying ? "⏸" : "▶"}
        </button>
      </td>
      <td className="py-2.5 pr-6 align-top">
        <div className="flex items-start flex-wrap">
          <div className="flex-1 min-w-0">
            <KaraokeSubtitle
              text={displayText}
              durationS={durationS}
              isPlaying={isPlaying}
              currentTime={currentTime}
              baseColorClass={baseColor}
              onSeek={canPlay ? handleSeek : undefined}
            />
          </div>
          {dirtyBadge ? (
            <span className="ml-2 text-[10px] px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded shrink-0">
              {dirtyBadge}
            </span>
          ) : null}
        </div>
        {chunk.takes.length > 1 ? (
          <TakeSelector
            takes={chunk.takes}
            selectedTakeId={chunk.selectedTakeId}
          />
        ) : null}
        {audioUrl ? (
          <audio
            key={audioUrl}
            ref={audioRef}
            src={audioUrl}
            preload="none"
            onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
            onEnded={() => {
              setCurrentTime(0);
              onPlay();
            }}
            className="hidden"
          />
        ) : null}
      </td>
      <td className="py-2.5 pr-6 align-top text-right">
        <button
          type="button"
          onClick={isEditing ? onCancelEdit : onEdit}
          title={isEditing ? "Close edit" : "Edit"}
          className={`w-7 h-7 inline-flex items-center justify-center rounded ${
            isEditing
              ? "bg-neutral-900 text-white hover:bg-neutral-800"
              : "hover:bg-neutral-200 text-neutral-700"
          }`}
        >
          {isEditing ? "✕" : "✎"}
        </button>
      </td>
    </tr>
  );
}
