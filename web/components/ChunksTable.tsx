"use client";

import { useState } from "react";
import type { Chunk, ChunkEdit, EditBatch, StageName } from "@/lib/types";
import { ChunkRow, type DirtyType, type DisplayMode } from "./ChunkRow";
import { ChunkEditor } from "./ChunkEditor";

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
}: Props) {
  const [displayMode, setDisplayMode] = useState<DisplayMode>("subtitle");

  if (chunks.length === 0) {
    return (
      <div className="px-6 py-12 text-center text-sm text-neutral-400">
        还没有 chunks。点 Run 开始第一次合成。
      </div>
    );
  }

  return (
    <table className="w-full text-sm">
      <thead className="text-[11px] text-neutral-400 uppercase tracking-wide">
        <tr className="border-b border-neutral-100">
          <th className="text-left font-medium px-6 py-2 w-44">ID</th>
          <th className="text-left font-medium py-2 w-12">St</th>
          <th className="text-left font-medium py-2 w-16">Dur</th>
          <th className="text-left font-medium py-2 w-12">Play</th>
          <th className="text-left font-medium py-2 pr-6">
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
          </th>
          <th className="text-right font-medium py-2 pr-6 w-12">Edit</th>
        </tr>
      </thead>
      <tbody>
        {chunks.map((c) => {
          const isEditing = editing === c.id;
          const edit = edits[c.id];
          const dirty = computeDirty(edit);
          return (
            <RowGroup
              key={c.id}
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
            />
          );
        })}
      </tbody>
    </table>
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
