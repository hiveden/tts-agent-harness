"use client";

import { useEffect, useCallback, useState } from "react";
import useSWR from "swr";
import type { Episode, StageName } from "@/lib/types";
import { useHarnessStore } from "@/lib/store";
import { useEpisodes, useEpisode, useEpisodeLogs, getAudioUrl } from "@/lib/hooks";
import { getApiUrl } from "@/lib/api-client";
import { useConfirm } from "@/hooks/useConfirm";
import { usePrompt } from "@/hooks/usePrompt";
import { useAction } from "@/hooks/useAction";
import { useTheme } from "@/components/Providers";
import { Sun, Moon, KeyRound } from "lucide-react";

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
import { ScriptPreviewDialog } from "@/components/ScriptPreviewDialog";
import { ApiKeyDialog } from "@/components/ApiKeyDialog";

export default function Page() {
  // --- Store state ---
  const store = useHarnessStore();

  // Defer selectedId to client-side only to avoid SSR hydration mismatch
  // (localStorage is unavailable during SSR → selectedId=null on server but non-null on client)
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    // Restore localStorage values after mount (SSR-safe)
    const savedId = localStorage.getItem("tts-harness:selectedEpisode");
    if (savedId) store.selectEpisode(savedId);
    const savedCollapsed = localStorage.getItem("tts-harness:sidebarCollapsed") === "true";
    if (savedCollapsed) store.setSidebarCollapsed(true);
    setMounted(true);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const selectedId = mounted ? store.selectedId : null;

  // --- Server state (SWR) ---
  const { data: episodes, error: episodesError, mutate: mutateList } = useEpisodes();
  const { data: episode, error: episodeError, mutate: mutateDetail } = useEpisode(selectedId);
  const { data: logLines, error: logsError } = useEpisodeLogs(selectedId);

  // --- Derived ---
  const running = episode?.status === "running";
  const failedCount = episode?.chunks.filter((c) =>
    c.status === "failed" || c.stageRuns.some((sr) => sr.status === "failed")
  ).length ?? 0;
  const dirtyCount = store.dirtyCount();

  // --- Action hooks (unified loading / error toast / dedup) ---
  const [execRun, runPending] = useAction(
    useCallback(async (mode: string) => {
      await store.runEpisode(mode);
      await mutateDetail();
      await mutateList();
    }, [store, mutateDetail, mutateList]),
    { errorPrefix: "运行失败" },
  );

  const [execCreate] = useAction(
    useCallback(async (id: string, file: File) => {
      await store.createEpisode(id, file);
      await mutateList();
      store.selectEpisode(id);
      setNewEpOpen(false);
    }, [store, mutateList]),
    { errorPrefix: "创建失败" },
  );

  const [execUseTake] = useAction(
    useCallback(async (cid: string, takeId: string) => {
      await store.finalizeTake(episode!.id, cid, takeId);
      await mutateDetail();
    }, [store, episode, mutateDetail]),
    { errorPrefix: "选定 take 失败" },
  );

  const [execDelete] = useAction(
    useCallback(async (id: string) => {
      await store.deleteEpisode(id);
      await mutateList();
    }, [store, mutateList]),
    { errorPrefix: "删除失败" },
  );

  const [execDuplicate] = useAction(
    useCallback(async (id: string, newId: string) => {
      await store.duplicateEpisode(id, newId);
      await mutateList();
    }, [store, mutateList]),
    { errorPrefix: "复制失败" },
  );

  const [execArchive] = useAction(
    useCallback(async (id: string) => {
      await store.archiveEpisode(id);
      await mutateList();
    }, [store, mutateList]),
    { errorPrefix: "归档失败" },
  );

  const [execCancel, cancelPending] = useAction(
    useCallback(async () => {
      if (!episode) return;
      const res = await fetch(`${getApiUrl()}/episodes/${episode.id}/cancel`, { method: "POST" });
      if (!res.ok) throw new Error(await res.text());
      await mutateDetail();
      await mutateList();
    }, [episode, mutateDetail, mutateList]),
    { errorPrefix: "取消失败" },
  );

  const [execRetry, retrying] = useAction(
    useCallback(async (cascade: boolean) => {
      if (!store.selectedId || !store.drawerOpen) return;
      await store.retryChunk(store.selectedId, store.drawerOpen.cid, store.drawerOpen.stage, cascade);
      await mutateDetail();
      store.closeDrawer();
    }, [store, mutateDetail]),
    { errorPrefix: "重试失败" },
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

  // --- Auto-collapse sidebar on small screens ---
  const sidebarCollapsed = store.sidebarCollapsed;
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const handler = (e: MediaQueryListEvent | MediaQueryList) => {
      if (e.matches) store.setSidebarCollapsed(true);
    };
    handler(mq);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // --- Confirm/Prompt dialog hooks ---
  const [confirmAction, ConfirmDialog] = useConfirm();
  const [promptAction, PromptDialog] = usePrompt();

  // --- NewEpisode dialog state (local — only used here) ---
  const [newEpOpen, setNewEpOpen] = useState(false);
  const [scriptPreviewOpen, setScriptPreviewOpen] = useState(false);
  const [apiKeyOpen, setApiKeyOpen] = useState(false);
  const [synthesizingCid, setSynthesizingCid] = useState<string | null>(null);

  const [execStageRetry] = useAction(
    useCallback(async (stage: StageName) => {
      if (!episode) return;
      const failed = episode.chunks.filter(c => c.stageRuns.find(sr => sr.stage === stage)?.status === "failed");
      if (!failed.length) return;
      const ok = await confirmAction(`重跑 ${failed.length} 个失败的 ${stage.toUpperCase()}？`);
      if (!ok) return;
      for (const c of failed) await store.retryChunk(episode.id, c.id, stage, true);
      await mutateDetail();
    }, [episode, confirmAction, store, mutateDetail]),
    { errorPrefix: "批量重试失败" },
  );

  const [execApply] = useAction(
    useCallback(async () => {
      if (!episode) return;
      await store.applyEdits(episode.id);
      await mutateDetail();
    }, [episode, store, mutateDetail]),
    { errorPrefix: "应用编辑失败" },
  );

  const [execSynthesize] = useAction(
    useCallback(async (cid: string) => {
      if (!episode) return;
      setSynthesizingCid(cid);
      try {
        await store.retryChunk(episode.id, cid, "p2", false);
        await mutateDetail();
        store.togglePlay(cid);
      } finally {
        setSynthesizingCid(null);
      }
    }, [episode, store, mutateDetail]),
    { errorPrefix: "合成失败" },
  );

  function ThemeToggle() {
    const { resolvedTheme, setTheme } = useTheme();
    return (
      <button
        type="button"
        onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
        className="w-7 h-7 rounded-full flex items-center justify-center hover:bg-neutral-100 dark:hover:bg-neutral-800 text-neutral-500 dark:text-neutral-400"
        title="Toggle dark mode"
      >
        {resolvedTheme === "dark" ? <Sun size={14} /> : <Moon size={14} />}
      </button>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-neutral-50 dark:bg-neutral-900 text-neutral-900 dark:text-neutral-100 overflow-hidden">
      {/* Header */}
      <header className="h-12 border-b border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 flex items-center px-4 shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded bg-neutral-900 dark:bg-white flex items-center justify-center text-white dark:text-neutral-900 text-xs font-bold">T</div>
          <h1 className="font-semibold text-sm">TTS Harness</h1>
          <span className="text-xs text-neutral-400 dark:text-neutral-500 ml-1">v2</span>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button type="button" onClick={() => setApiKeyOpen(true)} title="API Key 设置"
            className="w-7 h-7 rounded-full flex items-center justify-center hover:bg-neutral-100 dark:hover:bg-neutral-800 text-neutral-500 dark:text-neutral-400">
            <KeyRound size={14} />
          </button>
          <ThemeToggle />
          <button type="button" onClick={() => store.setHelpOpen(true)} title="Help"
            className="w-6 h-6 rounded-full border border-neutral-300 dark:border-neutral-600 text-neutral-500 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 text-xs font-semibold">?</button>
        </div>
      </header>

      <div className="flex-1 flex overflow-hidden">
        {/* Sidebar */}
        <EpisodeSidebar
          episodes={episodes ?? []}
          selectedId={selectedId}
          collapsed={sidebarCollapsed}
          onToggleCollapse={() => store.setSidebarCollapsed(!sidebarCollapsed)}
          onSelect={store.selectEpisode}
          onNewEpisode={() => setNewEpOpen(true)}
          error={episodesError ?? null}
          onDelete={async (id) => { const ok = await confirmAction(`确认删除 ${id}？`, { destructive: true }); if (ok) await execDelete(id); }}
          onDuplicate={async (id) => { const newId = await promptAction(`复制 ${id} 到新 ID:`, { defaultValue: `${id}-copy` }); if (newId) await execDuplicate(id, newId); }}
          onArchive={async (id) => { const ok = await confirmAction(`归档 ${id}？`); if (ok) await execArchive(id); }}
        />

        {/* Main content */}
        <main className="flex-1 min-w-0 flex flex-col overflow-hidden bg-neutral-50 dark:bg-neutral-900">
          {episode ? (
            <>
              <EpisodeHeader
                episode={episode}
                running={running}
                runPending={runPending}
                onRun={execRun}
                onCancel={execCancel}
                cancelPending={cancelPending}
                onViewScript={() => setScriptPreviewOpen(true)}
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
                  onStageRetry={execStageRetry}
                />
              )}
              <EditBanner
                ttsCount={dirtyCount.tts}
                subCount={dirtyCount.sub}
                onApply={execApply}
                onDiscard={store.discardEdits}
              />
              <div className="flex-1 flex flex-col overflow-hidden bg-white dark:bg-neutral-900">
                {episode.chunks.length === 0 ? (
                  <div className="px-6 py-12 text-center text-sm text-neutral-400 dark:text-neutral-500">还没有 chunks。点按钮开始。</div>
                ) : (
                  <>
                    <div className="px-6 py-2 bg-white dark:bg-neutral-900 border-b border-neutral-100 dark:border-neutral-700 flex items-center z-10 shrink-0">
                      <h3 className="text-xs font-medium text-neutral-500 dark:text-neutral-400 uppercase tracking-wide">Chunks</h3>
                      <span className="ml-2 text-[11px] text-neutral-400 dark:text-neutral-500">{episode.chunks.length} items</span>
                    </div>
                    <ChunksTable
                      episodeId={episode.id}
                      chunks={episode.chunks}
                      onStageClick={(cid, stage) => store.openDrawer(cid, stage)}
                      onPreviewTake={(_cid, takeId) => {
                        const chunk = episode.chunks.find(c => c.takes.find(t => t.id === takeId));
                        const take = chunk?.takes.find(t => t.id === takeId);
                        if (take) store.previewTake(take.audioUri);
                      }}
                      onUseTake={execUseTake}
                      onSynthesize={execSynthesize}
                      synthesizingCid={synthesizingCid}
                      getAudioUrl={getAudioUrl}
                    />
                  </>
                )}
              </div>
              <LogViewer log={logLines ?? []} error={logsError ?? null} />
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center text-sm text-neutral-400 dark:text-neutral-500">
              {episodeError ? (
                <div className="text-center">
                  <div className="text-red-500 mb-2">Failed to load episode</div>
                  <div className="text-xs text-red-400 font-mono max-w-md break-all">{episodeError.message || String(episodeError)}</div>
                  <button type="button" onClick={() => mutateDetail()} className="mt-3 text-xs px-3 py-1 rounded border border-neutral-300 dark:border-neutral-600 hover:bg-neutral-100 dark:hover:bg-neutral-800">Retry</button>
                </div>
              ) : selectedId ? (
                <div className="text-neutral-400">Loading...</div>
              ) : (
                "Select an episode from the sidebar"
              )}
            </div>
          )}
        </main>
      </div>

      {/* Dialogs */}
      <NewEpisodeDialog
        open={newEpOpen}
        onClose={() => setNewEpOpen(false)}
        onCreate={execCreate}
      />
      <HelpDialog open={store.helpOpen} onClose={() => store.setHelpOpen(false)} />
      <ApiKeyDialog open={apiKeyOpen} onClose={() => setApiKeyOpen(false)} />
      {selectedId && (
        <ScriptPreviewDialog
          episodeId={selectedId}
          open={scriptPreviewOpen}
          onClose={() => setScriptPreviewOpen(false)}
        />
      )}

      {/* Confirm / Prompt dialogs */}
      {ConfirmDialog}
      {PromptDialog}

      {/* Stage Log Drawer */}
      {store.drawerOpen && store.selectedId && episode && <DrawerWithContext
        episodeId={store.selectedId}
        episode={episode}
        drawerOpen={store.drawerOpen}
        onClose={store.closeDrawer}
        onRetry={execRetry}
        retrying={retrying}
      />}
    </div>
  );
}


// Wrapper that fetches stage context for the drawer
function DrawerWithContext({ episodeId, episode, drawerOpen, onClose, onRetry, retrying = false }: {
  episodeId: string;
  episode: Episode;
  drawerOpen: { cid: string; stage: StageName };
  onClose: () => void;
  onRetry: (cascade: boolean) => Promise<void>;
  retrying?: boolean;
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
      retrying={retrying}
    />
  );
}
