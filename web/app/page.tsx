"use client";

import { useEffect, useCallback, useState, useMemo } from "react";
import useSWR from "swr";
import type { Episode, StageName } from "@/lib/types";
import { useHarnessStore } from "@/lib/store";
import { useEpisodes, useEpisode, useEpisodeLogs, getAudioUrl } from "@/lib/hooks";
import { getApiUrl } from "@/lib/api-client";

import { EpisodeSidebar } from "@/components/EpisodeSidebar";
import { EpisodeHeader } from "@/components/EpisodeHeader";
import { EditBanner } from "@/components/EditBanner";
import { ChunksTable } from "@/components/ChunksTable";
import { LogViewer } from "@/components/LogViewer";
import { NewEpisodeDialog } from "@/components/NewEpisodeDialog";
import { HelpDialog } from "@/components/HelpDialog";
import { StageProgress } from "@/components/StageProgress";
import { EpisodeStageBar } from "@/components/EpisodeStageBar";
import { TtsConfigBar } from "@/components/TtsConfigBar";
import { StageLogDrawer } from "@/components/StageLogDrawer";

export default function Page() {
  // --- Store state ---
  const store = useHarnessStore();

  // --- Server state (SWR) ---
  const { data: episodes, mutate: mutateList } = useEpisodes();
  const { data: episode, mutate: mutateDetail } = useEpisode(store.selectedId);
  const { data: logLines } = useEpisodeLogs(store.selectedId);

  // --- Derived ---
  const running = episode?.status === "running";
  const failedCount = episode?.chunks.filter((c) => c.status === "failed").length ?? 0;
  const dirtyCount = store.dirtyCount();

  // --- Mutate helpers (bridge store actions → SWR refresh) ---
  const withRefresh = useCallback(
    (fn: (...args: never[]) => Promise<void>) =>
      async (...args: never[]) => {
        try {
          await fn(...args);
          await mutateDetail();
          await mutateList();
        } catch (e) {
          alert(`操作失败: ${(e as Error).message}`);
        }
      },
    [mutateDetail, mutateList],
  );

  // --- Keyboard shortcuts ---
  useEffect(() => {
    if (!episode?.chunks.length) return;
    const chunks = episode.chunks;
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const cur = store.playingChunkId;
      const idx = cur ? chunks.findIndex((c) => c.id === cur) : 0;
      const safe = idx < 0 ? 0 : idx;
      if (e.key === " " || e.code === "Space") { e.preventDefault(); const c = chunks[safe]; if (c) store.togglePlay(c.id); }
      else if (e.key === "j") { e.preventDefault(); const n = Math.min(chunks.length - 1, safe + 1); if (cur) store.togglePlay(chunks[n]?.id ?? cur); }
      else if (e.key === "k") { e.preventDefault(); const p = Math.max(0, safe - 1); if (cur) store.togglePlay(chunks[p]?.id ?? cur); }
      else if (e.key === "e") { e.preventDefault(); const c = chunks[safe]; if (c) store.startEditing(c.id); }
      else if (e.key === "Escape") { if (store.editing) store.cancelEditing(); else if (store.drawerOpen) store.closeDrawer(); else if (store.playingChunkId) store.togglePlay(store.playingChunkId); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [episode?.chunks, store]);

  // --- NewEpisode dialog state (local — only used here) ---
  const [newEpOpen, setNewEpOpen] = useState(false);
  const [synthesizingCid, setSynthesizingCid] = useState<string | null>(null);

  return (
    <div className="h-screen flex flex-col bg-neutral-50 text-neutral-900 overflow-hidden">
      {/* Header */}
      <header className="h-12 border-b border-neutral-200 bg-white flex items-center px-4 shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded bg-neutral-900 flex items-center justify-center text-white text-xs font-bold">T</div>
          <h1 className="font-semibold text-sm">TTS Harness</h1>
          <span className="text-xs text-neutral-400 ml-1">v2</span>
        </div>
        <div className="ml-auto flex items-center gap-3">
          <span className="text-xs text-neutral-500 font-mono">localhost:3010</span>
          <button type="button" onClick={() => store.setHelpOpen(true)} title="Help"
            className="w-6 h-6 rounded-full border border-neutral-300 text-neutral-500 hover:bg-neutral-100 text-xs font-semibold">?</button>
        </div>
      </header>

      <div className="flex-1 flex overflow-hidden">
        {/* Sidebar */}
        <EpisodeSidebar
          episodes={episodes ?? []}
          selectedId={store.selectedId}
          onSelect={store.selectEpisode}
          onNewEpisode={() => setNewEpOpen(true)}
          onDelete={async (id) => { if (confirm(`确认删除 ${id}？`)) { await store.deleteEpisode(id); await mutateList(); } }}
          onDuplicate={async (id) => { const newId = prompt(`复制 ${id} 到新 ID:`, `${id}-copy`); if (newId?.trim()) { await store.duplicateEpisode(id, newId.trim()); await mutateList(); } }}
          onArchive={async (id) => { if (confirm(`归档 ${id}？`)) { await store.archiveEpisode(id); await mutateList(); } }}
        />

        {/* Main content */}
        <main className="flex-1 flex flex-col overflow-hidden">
          {episode ? (
            <>
              <EpisodeHeader
                episode={episode}
                running={running}
                onRun={async (mode) => { await store.runEpisode(mode); await mutateDetail(); await mutateList(); }}
                failedCount={failedCount}
              />
              <TtsConfigBar
                episodeId={episode.id}
                config={episode.config}
                onConfigSaved={() => mutateDetail()}
                onUpdateConfig={store.updateConfig}
              />
              <StageProgress
                status={episode.status}
                running={running}
                currentStage={running ? (episode.chunks.find(c => c.stageRuns.find(sr => sr.status === "running"))?.stageRuns.find(sr => sr.status === "running")?.stage.toUpperCase() ?? null) : null}
                totalChunks={episode.chunks.length}
              />
              {episode.chunks.length > 0 && (
                <EpisodeStageBar
                  chunks={episode.chunks}
                  onStageRetry={async (stage: StageName) => {
                    const failed = episode.chunks.filter(c => c.stageRuns.find(sr => sr.stage === stage)?.status === "failed");
                    if (!failed.length || !confirm(`重跑 ${failed.length} 个失败的 ${stage.toUpperCase()}？`)) return;
                    for (const c of failed) await store.retryChunk(episode.id, c.id, stage, true);
                    await mutateDetail();
                  }}
                />
              )}
              <EditBanner
                ttsCount={dirtyCount.tts}
                subCount={dirtyCount.sub}
                onApply={async () => { await store.applyEdits(episode.id); await mutateDetail(); }}
                onDiscard={store.discardEdits}
              />
              <div className="flex-1 overflow-y-auto bg-white">
                {episode.chunks.length === 0 ? (
                  <div className="px-6 py-12 text-center text-sm text-neutral-400">还没有 chunks。点按钮开始。</div>
                ) : (
                  <>
                    <div className="px-6 py-2 sticky top-0 bg-white border-b border-neutral-100 flex items-center z-10">
                      <h3 className="text-xs font-medium text-neutral-500 uppercase tracking-wide">Chunks</h3>
                      <span className="ml-2 text-[11px] text-neutral-400">{episode.chunks.length} items</span>
                    </div>
                    <ChunksTable
                      episodeId={episode.id}
                      chunks={episode.chunks}
                      edits={store.edits}
                      editing={store.editing}
                      playingChunkId={store.playingChunkId}
                      onPlay={store.togglePlay}
                      onEdit={store.startEditing}
                      onCancelEdit={store.cancelEditing}
                      onStage={store.stageEdit}
                      onStageClick={(cid, stage) => store.openDrawer(cid, stage)}
                      onPreviewTake={(_cid, takeId) => {
                        const chunk = episode.chunks.find(c => c.takes.find(t => t.id === takeId));
                        const take = chunk?.takes.find(t => t.id === takeId);
                        if (take) store.previewTake(take.audioUri);
                      }}
                      onUseTake={async (cid, takeId) => { await store.finalizeTake(episode.id, cid, takeId); await mutateDetail(); }}
                      onSynthesize={async (cid) => {
                        setSynthesizingCid(cid);
                        try {
                          await store.retryChunk(episode.id, cid, "p2", false);
                          await mutateDetail();
                          // Auto-play after synthesis
                          store.togglePlay(cid);
                        } catch (e) {
                          alert(`合成失败: ${(e as Error).message}`);
                        } finally {
                          setSynthesizingCid(null);
                        }
                      }}
                      synthesizingCid={synthesizingCid}
                      getAudioUrl={getAudioUrl}
                    />
                  </>
                )}
              </div>
              <LogViewer log={logLines ?? []} />
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center text-sm text-neutral-400">Select an episode from the sidebar</div>
          )}
        </main>
      </div>

      {/* Dialogs */}
      <NewEpisodeDialog
        open={newEpOpen}
        onClose={() => setNewEpOpen(false)}
        onCreate={async (id, file) => { await store.createEpisode(id, file); await mutateList(); store.selectEpisode(id); setNewEpOpen(false); }}
      />
      <HelpDialog open={store.helpOpen} onClose={() => store.setHelpOpen(false)} />

      {/* Stage Log Drawer */}
      {store.drawerOpen && store.selectedId && episode && <DrawerWithContext
        episodeId={store.selectedId}
        episode={episode}
        drawerOpen={store.drawerOpen}
        onClose={store.closeDrawer}
        onRetry={async (cascade) => {
          await store.retryChunk(store.selectedId!, store.drawerOpen!.cid, store.drawerOpen!.stage, cascade);
          await mutateDetail();
          store.closeDrawer();
        }}
      />}
    </div>
  );
}


// Wrapper that fetches stage context for the drawer
function DrawerWithContext({ episodeId, episode, drawerOpen, onClose, onRetry }: {
  episodeId: string;
  episode: Episode;
  drawerOpen: { cid: string; stage: StageName };
  onClose: () => void;
  onRetry: (cascade: boolean) => Promise<void>;
}) {
  const { data: ctxData } = useSWR(
    `api:stage-context:${episodeId}:${drawerOpen.cid}:${drawerOpen.stage}`,
    async () => {
      const r = await fetch(`${getApiUrl()}/episodes/${encodeURIComponent(episodeId)}/chunks/${encodeURIComponent(drawerOpen.cid)}/stage-context?stage=${encodeURIComponent(drawerOpen.stage)}`);
      if (!r.ok) return null;
      const d = await r.json();
      return d.found ? d.payload : null;
    },
  );

  const chunk = episode.chunks.find(c => c.id === drawerOpen.cid);
  const stageRun = chunk?.stageRuns.find(sr => sr.stage === drawerOpen.stage);

  return (
    <StageLogDrawer
      open
      onClose={onClose}
      chunkId={drawerOpen.cid}
      stage={drawerOpen.stage}
      stageRun={stageRun}
      log=""
      logLoading={false}
      logError={null}
      context={ctxData ?? null}
      onRetry={onRetry}
    />
  );
}
