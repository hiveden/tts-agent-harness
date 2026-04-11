"use client";

import { useEffect, useState, useMemo, useCallback } from "react";
import type { ChunkEdit, EditBatch } from "@/lib/types";
import type { StageName } from "@/lib/types";
import {
  useEpisodes,
  useEpisode,
  useEpisodeLogs,
  runEpisode,
  retryChunk,
  finalizeTake,
  applyEdits as apiApplyEdits,
  createEpisode,
  deleteEpisode,
  duplicateEpisode,
  archiveEpisode,
  getAudioUrl,
} from "@/lib/hooks";
import { EpisodeSidebar } from "@/components/EpisodeSidebar";
import { EpisodeHeader } from "@/components/EpisodeHeader";
import { EditBanner } from "@/components/EditBanner";
import { ChunksTable } from "@/components/ChunksTable";
import { LogViewer } from "@/components/LogViewer";
import { NewEpisodeDialog } from "@/components/NewEpisodeDialog";
import { StageProgress } from "@/components/StageProgress";
import { EpisodeStageBar } from "@/components/EpisodeStageBar";
import { HelpDialog } from "@/components/HelpDialog";
import { ScriptPreview } from "@/components/ScriptPreview";
import { StageLogDrawer } from "@/components/StageLogDrawer";
import { TtsConfigBar } from "@/components/TtsConfigBar";

export default function Page() {
  const [selectedId, setSelectedId] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    return window.localStorage.getItem("tts-harness:selectedEpisode");
  });
  const [edits, setEdits] = useState<EditBatch>({});
  const [editing, setEditing] = useState<string | null>(null);
  const [playingChunkId, setPlayingChunkId] = useState<string | null>(null);
  const [newEpOpen, setNewEpOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState<{ cid: string; stage: StageName } | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);

  const { data: episodes, mutate: mutateList } = useEpisodes();
  const { data: episode, mutate: mutateDetail } = useEpisode(selectedId);
  const { data: logLines } = useEpisodeLogs(selectedId);

  const dirtyCount = useMemo(() => {
    let tts = 0;
    let sub = 0;
    for (const e of Object.values(edits)) {
      if (e.textNormalized !== undefined) tts++;
      if (e.subtitleText !== undefined) sub++;
    }
    return { tts, sub };
  }, [edits]);

  const handleSelect = (id: string) => {
    setSelectedId(id);
    if (typeof window !== "undefined") window.localStorage.setItem("tts-harness:selectedEpisode", id);
    setEdits({});
    setEditing(null);
    setPlayingChunkId(null);
  };

  const handleRun = async (mode: string) => {
    if (!selectedId || !mode) return;
    try {
      await runEpisode(selectedId, mode);
      await mutateDetail();
      await mutateList();
    } catch (e) {
      alert(`Run failed: ${(e as Error).message}`);
    }
  };

  const handleApply = async () => {
    if (!selectedId) return;
    if (Object.keys(edits).length === 0) return;
    try {
      await apiApplyEdits(selectedId, edits);
      setEdits({});
      setPlayingChunkId(null);
      await mutateDetail();
    } catch (e) {
      alert(`Apply failed: ${(e as Error).message}`);
    }
  };

  const handleStage = (cid: string, draft: ChunkEdit) => {
    setEdits((prev) => {
      const next = { ...prev };
      if (Object.keys(draft).length === 0) {
        delete next[cid];
      } else {
        next[cid] = draft;
      }
      return next;
    });
    setEditing(null);
    if (playingChunkId === cid) setPlayingChunkId(null);
  };

  const handleCreateEp = async (id: string, file: File) => {
    try {
      await createEpisode(id, file);
      await mutateList();
      setSelectedId(id);
    } catch (e) {
      alert(`Create failed: ${(e as Error).message}`);
    }
  };

  const handleDeleteEp = async (id: string) => {
    if (!confirm(`确认删除 ${id}？此操作不可撤销。`)) return;
    try {
      await deleteEpisode(id);
      if (selectedId === id) setSelectedId(null);
      await mutateList();
    } catch (e) { alert(`Delete failed: ${(e as Error).message}`); }
  };

  const handleDuplicateEp = async (id: string) => {
    const newId = prompt(`复制 ${id} 到新 ID:`, `${id}-copy`);
    if (!newId?.trim()) return;
    try {
      await duplicateEpisode(id, newId.trim());
      await mutateList();
      setSelectedId(newId.trim());
    } catch (e) { alert(`Duplicate failed: ${(e as Error).message}`); }
  };

  const handleArchiveEp = async (id: string) => {
    if (!confirm(`归档 ${id}？会从列表中隐藏。`)) return;
    try {
      await archiveEpisode(id);
      if (selectedId === id) setSelectedId(null);
      await mutateList();
    } catch (e) { alert(`Archive failed: ${(e as Error).message}`); }
  };

  // Keyboard shortcuts
  const handlePlay = useCallback((cid: string) => {
    setPlayingChunkId((prev) => (prev === cid ? null : cid));
  }, []);

  useEffect(() => {
    if (!episode?.chunks.length) return;
    const chunks = episode.chunks;
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const curIdx = playingChunkId ? chunks.findIndex((c) => c.id === playingChunkId) : 0;
      const safe = curIdx < 0 ? 0 : curIdx;
      if (e.key === " " || e.code === "Space") { e.preventDefault(); const c = chunks[safe]; if (c) handlePlay(c.id); }
      else if (e.key === "j") { e.preventDefault(); const next = Math.min(chunks.length - 1, safe + 1); if (playingChunkId) setPlayingChunkId(chunks[next]?.id ?? null); }
      else if (e.key === "k") { e.preventDefault(); const prev = Math.max(0, safe - 1); if (playingChunkId) setPlayingChunkId(chunks[prev]?.id ?? null); }
      else if (e.key === "e") { e.preventDefault(); const c = chunks[safe]; if (c) setEditing((p) => (p === c.id ? null : c.id)); }
      else if (e.key === "Escape") { if (editing) setEditing(null); else if (drawerOpen) setDrawerOpen(null); else if (playingChunkId) setPlayingChunkId(null); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [episode?.chunks, playingChunkId, editing, drawerOpen, handlePlay]);

  const running = episode?.status === "running";
  const failedCount = episode?.chunks.filter((c) => c.status === "failed").length ?? 0;

  return (
    <div className="h-screen flex flex-col bg-neutral-50 text-neutral-900 overflow-hidden">
      <header className="h-12 border-b border-neutral-200 bg-white flex items-center px-4 shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded bg-neutral-900 flex items-center justify-center text-white text-xs font-bold">
            T
          </div>
          <h1 className="font-semibold text-sm">TTS Harness</h1>
          <span className="text-xs text-neutral-400 ml-1">v2</span>
        </div>
        <div className="ml-auto flex items-center gap-3">
          <span className="text-xs text-neutral-500 font-mono">localhost:3010</span>
          <button type="button" onClick={() => setHelpOpen(true)} title="Help"
            className="w-6 h-6 rounded-full border border-neutral-300 text-neutral-500 hover:bg-neutral-100 text-xs font-semibold">?</button>
        </div>
      </header>

      <div className="flex-1 flex overflow-hidden">
        <EpisodeSidebar
          episodes={episodes ?? []}
          selectedId={selectedId}
          onSelect={handleSelect}
          onNewEpisode={() => setNewEpOpen(true)}
          onDelete={handleDeleteEp}
          onDuplicate={handleDuplicateEp}
          onArchive={handleArchiveEp}
        />
        <main className="flex-1 flex flex-col overflow-hidden">
          {episode ? (
            <>
              <EpisodeHeader
                episode={episode}
                running={running}
                onRun={handleRun}
                failedCount={failedCount}
              />
              <TtsConfigBar
                episodeId={episode.id}
                config={episode.config}
                onConfigSaved={() => mutateDetail()}
              />
              <StageProgress
                status={episode.status}
                running={running}
                currentStage={null}
                totalChunks={episode.chunks.length}
              />
              {episode.chunks.length > 0 && (
                <EpisodeStageBar
                  chunks={episode.chunks}
                  onStageRetry={async (stage: StageName) => {
                    const failed = episode.chunks.filter(
                      (c) => c.stageRuns.find((sr) => sr.stage === stage)?.status === "failed"
                    );
                    if (failed.length === 0) return;
                    if (!confirm(`重跑 ${failed.length} 个失败的 ${stage.toUpperCase()} chunk？`)) return;
                    try {
                      for (const c of failed) {
                        await retryChunk(episode.id, c.id, stage, true);
                      }
                      await mutateDetail();
                    } catch (e) {
                      alert(`Retry failed: ${(e as Error).message}`);
                    }
                  }}
                />
              )}
              <EditBanner
                ttsCount={dirtyCount.tts}
                subCount={dirtyCount.sub}
                onApply={handleApply}
                onDiscard={() => setEdits({})}
              />
              <div className="flex-1 overflow-y-auto bg-white">
                {episode.chunks.length === 0 ? (
                  <div className="px-6 py-12 text-center text-sm text-neutral-400">
                    还没有 chunks。点 Generate 开始。
                  </div>
                ) : (
                  <>
                    <div className="px-6 py-2 sticky top-0 bg-white border-b border-neutral-100 flex items-center z-10">
                      <h3 className="text-xs font-medium text-neutral-500 uppercase tracking-wide">
                        Chunks
                      </h3>
                      <span className="ml-2 text-[11px] text-neutral-400">
                        {episode.chunks.length} items
                      </span>
                    </div>
                    <ChunksTable
                      episodeId={episode.id}
                      chunks={episode.chunks}
                      edits={edits}
                      editing={editing}
                      playingChunkId={playingChunkId}
                      onPlay={(cid) =>
                        setPlayingChunkId((prev) => (prev === cid ? null : cid))
                      }
                      onEdit={(cid) =>
                        setEditing((prev) => (prev === cid ? null : cid))
                      }
                      onCancelEdit={() => setEditing(null)}
                      onStage={handleStage}
                      onStageClick={(cid, stage) => setDrawerOpen({ cid, stage })}
                      onPreviewTake={(cid, takeId) => {
                        // Play this take's audio
                        const chunk = episode.chunks.find(c => c.id === cid);
                        const take = chunk?.takes.find(t => t.id === takeId);
                        if (take) {
                          const audio = new Audio(getAudioUrl(take.audioUri));
                          audio.play().catch(() => {});
                        }
                      }}
                      onUseTake={async (cid, takeId) => {
                        try {
                          await finalizeTake(episode.id, cid, takeId);
                          await mutateDetail();
                        } catch (e) {
                          alert(`Finalize failed: ${(e as Error).message}`);
                        }
                      }}
                    />
                  </>
                )}
              </div>
              <LogViewer log={logLines ?? []} />
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center text-sm text-neutral-400">
              Select an episode from the sidebar
            </div>
          )}
        </main>
      </div>

      <NewEpisodeDialog
        open={newEpOpen}
        onClose={() => setNewEpOpen(false)}
        onCreate={handleCreateEp}
      />
      <HelpDialog open={helpOpen} onClose={() => setHelpOpen(false)} />

      {drawerOpen && selectedId && episode && (() => {
        const chunk = episode.chunks.find((c) => c.id === drawerOpen.cid);
        const stageRun = chunk?.stageRuns.find((sr) => sr.stage === drawerOpen.stage);
        return (
          <StageLogDrawer
            open
            onClose={() => setDrawerOpen(null)}
            episodeId={selectedId}
            chunkId={drawerOpen.cid}
            stage={drawerOpen.stage}
            stageRun={stageRun}
            onAfterRetry={() => {
              mutateDetail();
              setDrawerOpen(null);
            }}
          />
        );
      })()}
    </div>
  );
}
