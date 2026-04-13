"use client";

import { memo, useCallback, useRef, useState } from "react";
import type { Chunk, StageName } from "@/lib/types";
import { useHarnessStore } from "@/lib/store";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ChunkRow, type DisplayMode } from "./ChunkRow";
import { ChunkEditor } from "./ChunkEditor";
import { GRID_COLS } from "./chunks-grid";

interface Props {
  episodeId: string;
  chunks: Chunk[];
  onStageClick?: (cid: string, stage: StageName) => void;
  onPreviewTake?: (cid: string, takeId: string) => void;
  onUseTake?: (cid: string, takeId: string) => void;
  onSynthesize?: (cid: string) => void;
  synthesizingCid?: string | null;
  getAudioUrl: (uri: string) => string;
}

export function ChunksTable({
  episodeId,
  chunks,
  onStageClick,
  onPreviewTake,
  onUseTake,
  onSynthesize,
  synthesizingCid,
  getAudioUrl,
}: Props) {
  void episodeId;
  const [displayMode, setDisplayMode] = useState<DisplayMode>("subtitle");
  const parentRef = useRef<HTMLDivElement>(null);
  const editing = useHarnessStore((s) => s.editing);

  const virtualizer = useVirtualizer({
    count: chunks.length,
    getScrollElement: () => parentRef.current,
    estimateSize: useCallback(
      (index: number) => {
        const c = chunks[index];
        if (editing === c?.id) return 320;
        return 60;
      },
      [chunks, editing],
    ),
    overscan: 5,
  });

  if (chunks.length === 0) {
    return (
      <div className="px-6 py-12 text-center text-sm text-neutral-400 dark:text-neutral-500">
        还没有 chunks。点 Run 开始第一次合成。
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Sticky header */}
      <div
        className="grid text-[11px] text-neutral-400 dark:text-neutral-500 uppercase tracking-wide border-b border-neutral-100 dark:border-neutral-700 shrink-0"
        style={{ gridTemplateColumns: GRID_COLS }}
      >
        <div className="text-left font-medium px-6 py-2">ID</div>
        <div className="text-left font-medium py-2">St</div>
        <div className="text-left font-medium py-2">Dur</div>
        <div className="text-left font-medium py-2">Play</div>
        <div className="text-left font-medium py-2 pr-6">
          <div className="flex items-center gap-2">
            <span>{displayMode === "subtitle" ? "Subtitle" : "TTS Source"}</span>
            <div className="inline-flex rounded border border-neutral-200 dark:border-neutral-700 overflow-hidden normal-case">
              <button
                type="button"
                onClick={() => setDisplayMode("subtitle")}
                className={`px-1.5 py-0.5 text-[10px] font-normal ${
                  displayMode === "subtitle"
                    ? "bg-neutral-900 dark:bg-white text-white dark:text-neutral-900"
                    : "bg-white dark:bg-neutral-800 text-neutral-500 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-700"
                }`}
              >
                字幕
              </button>
              <button
                type="button"
                onClick={() => setDisplayMode("tts")}
                className={`px-1.5 py-0.5 text-[10px] font-normal border-l border-neutral-200 dark:border-neutral-700 ${
                  displayMode === "tts"
                    ? "bg-neutral-900 dark:bg-white text-white dark:text-neutral-900"
                    : "bg-white dark:bg-neutral-800 text-neutral-500 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-700"
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
                  chunk={c}
                  displayMode={displayMode}
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
  chunk: Chunk;
  displayMode: DisplayMode;
  onStageClick?: (stage: StageName) => void;
  onPreviewTake?: (takeId: string) => void;
  onUseTake?: (takeId: string) => void;
  onSynthesize?: () => void;
  synthesizing?: boolean;
  getAudioUrl: (uri: string) => string;
}

const RowGroup = memo(function RowGroup({
  chunk,
  displayMode,
  onStageClick,
  onPreviewTake,
  onUseTake,
  onSynthesize,
  synthesizing,
  getAudioUrl,
}: RowGroupProps) {
  const isEditing = useHarnessStore((s) => s.editing === chunk.id);
  const edit = useHarnessStore((s) => s.edits[chunk.id]);
  const stageEdit = useHarnessStore((s) => s.stageEdit);
  const cancelEditing = useHarnessStore((s) => s.cancelEditing);

  return (
    <>
      <ChunkRow
        chunk={chunk}
        displayMode={displayMode}
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
          onStage={(draft) => stageEdit(chunk.id, draft)}
          onCancel={cancelEditing}
        />
      ) : null}
    </>
  );
}, (prev, next) => {
  return prev.chunk === next.chunk
    && prev.displayMode === next.displayMode
    && prev.synthesizing === next.synthesizing
    && prev.onStageClick === next.onStageClick
    && prev.onPreviewTake === next.onPreviewTake
    && prev.onUseTake === next.onUseTake
    && prev.onSynthesize === next.onSynthesize
    && prev.getAudioUrl === next.getAudioUrl;
});
