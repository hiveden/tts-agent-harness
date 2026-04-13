"use client";

import { useState, useRef, useCallback } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { Chunk, ChunkEdit, EditBatch, StageName } from "@/lib/types";
import { ChunkRow, type DirtyType, type DisplayMode } from "./ChunkRow";
import { ChunkEditor } from "./ChunkEditor";
import { GRID_COLS } from "./chunks-grid";

interface Props {
  episodeId: string;
  chunks: Chunk[];
  edits: EditBatch;
  editing: string | null;
  playingChunkId: string | null;
  onPlay: (cid: string) => void;
  onEdit: (cid: string) => void;
  onCancelEdit: () => void;
  onStage: (cid: string, draft: ChunkEdit) => void;
  onStageClick?: (cid: string, stage: StageName) => void;
  onPreviewTake?: (cid: string, takeId: string) => void;
  onUseTake?: (cid: string, takeId: string) => void;
  onSynthesize?: (cid: string) => void;
  synthesizingCid?: string | null;
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

export function ChunksTable({
  episodeId,
  chunks,
  edits,
  editing,
  playingChunkId,
  onPlay,
  onEdit,
  onCancelEdit,
  onStage,
  onStageClick,
  onPreviewTake,
  onUseTake,
  onSynthesize,
  synthesizingCid,
  getAudioUrl,
}: Props) {
  const [displayMode, setDisplayMode] = useState<DisplayMode>("subtitle");
  const parentRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: chunks.length,
    getScrollElement: () => parentRef.current,
    estimateSize: useCallback(
      (index: number) => {
        const c = chunks[index];
        // Expanded editor rows are taller
        if (editing === c?.id) return 320;
        return 60;
      },
      [chunks, editing],
    ),
    overscan: 5,
  });

  if (chunks.length === 0) {
    return (
      <div className="px-6 py-12 text-center text-sm text-neutral-400">
        还没有 chunks。点 Run 开始第一次合成。
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Sticky header */}
      <div
        className="grid text-[11px] text-neutral-400 uppercase tracking-wide border-b border-neutral-100 shrink-0"
        style={{ gridTemplateColumns: GRID_COLS }}
      >
        <div className="text-left font-medium px-6 py-2">ID</div>
        <div className="text-left font-medium py-2">St</div>
        <div className="text-left font-medium py-2">Dur</div>
        <div className="text-left font-medium py-2">Play</div>
        <div className="text-left font-medium py-2 pr-6">
          <div className="flex items-center gap-2">
            <span>{displayMode === "subtitle" ? "Subtitle" : "TTS Source"}</span>
            <div className="inline-flex rounded border border-neutral-200 overflow-hidden normal-case">
              <button
                type="button"
                onClick={() => setDisplayMode("subtitle")}
                className={`px-1.5 py-0.5 text-[10px] font-normal ${
                  displayMode === "subtitle"
                    ? "bg-neutral-900 text-white"
                    : "bg-white text-neutral-500 hover:bg-neutral-100"
                }`}
              >
                字幕
              </button>
              <button
                type="button"
                onClick={() => setDisplayMode("tts")}
                className={`px-1.5 py-0.5 text-[10px] font-normal border-l border-neutral-200 ${
                  displayMode === "tts"
                    ? "bg-neutral-900 text-white"
                    : "bg-white text-neutral-500 hover:bg-neutral-100"
                }`}
              >
                TTS源
              </button>
            </div>
          </div>
        </div>
        <div className="text-right font-medium py-2 pr-6">Edit</div>
      </div>

      {/* Virtual scroll container */}
      <div ref={parentRef} className="flex-1 overflow-y-auto">
        <div
          style={{
            height: `${virtualizer.getTotalSize()}px`,
            width: "100%",
            position: "relative",
          }}
        >
          {virtualizer.getVirtualItems().map((virtualRow) => {
            const c = chunks[virtualRow.index];
            const isEditing = editing === c.id;
            const edit = edits[c.id];
            const dirty = computeDirty(edit);
            return (
              <div
                key={c.id}
                data-index={virtualRow.index}
                ref={virtualizer.measureElement}
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  width: "100%",
                  transform: `translateY(${virtualRow.start}px)`,
                }}
              >
                <RowGroup
                  episodeId={episodeId}
                  chunk={c}
                  displayMode={displayMode}
                  isEditing={isEditing}
                  isPlaying={playingChunkId === c.id}
                  dirty={dirty}
                  edit={edit}
                  onPlay={() => onPlay(c.id)}
                  onEdit={() => onEdit(c.id)}
                  onCancelEdit={onCancelEdit}
                  onStage={(draft) => onStage(c.id, draft)}
                  onStageClick={onStageClick ? (stage) => onStageClick(c.id, stage) : undefined}
                  onPreviewTake={onPreviewTake ? (takeId) => onPreviewTake(c.id, takeId) : undefined}
                  onUseTake={onUseTake ? (takeId) => onUseTake(c.id, takeId) : undefined}
                  onSynthesize={onSynthesize ? () => onSynthesize(c.id) : undefined}
                  synthesizing={synthesizingCid === c.id}
                  getAudioUrl={getAudioUrl}
                />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

interface RowGroupProps {
  episodeId: string;
  chunk: Chunk;
  displayMode: DisplayMode;
  isEditing: boolean;
  isPlaying: boolean;
  dirty: DirtyType;
  edit: ChunkEdit | undefined;
  onPlay: () => void;
  onEdit: () => void;
  onCancelEdit: () => void;
  onStage: (draft: ChunkEdit) => void;
  onStageClick?: (stage: StageName) => void;
  onPreviewTake?: (takeId: string) => void;
  onUseTake?: (takeId: string) => void;
  onSynthesize?: () => void;
  synthesizing?: boolean;
  getAudioUrl: (uri: string) => string;
}

function RowGroup({
  episodeId,
  chunk,
  displayMode,
  isEditing,
  isPlaying,
  dirty,
  edit,
  onPlay,
  onEdit,
  onCancelEdit,
  onStage,
  onStageClick,
  onPreviewTake,
  onUseTake,
  onSynthesize,
  synthesizing,
  getAudioUrl,
}: RowGroupProps) {
  return (
    <>
      <ChunkRow
        episodeId={episodeId}
        chunk={chunk}
        displayMode={displayMode}
        isPlaying={isPlaying}
        isEditing={isEditing}
        dirty={dirty}
        edit={edit}
        onPlay={onPlay}
        onEdit={onEdit}
        onCancelEdit={onCancelEdit}
        onStageClick={onStageClick}
        onPreviewTake={onPreviewTake}
        onUseTake={onUseTake}
        onSynthesize={onSynthesize}
        synthesizing={synthesizing}
        getAudioUrl={getAudioUrl}
      />
      {isEditing ? (
        <ChunkEditor
          chunk={chunk}
          initialDraft={edit}
          onStage={onStage}
          onCancel={onCancelEdit}
        />
      ) : null}
    </>
  );
}
