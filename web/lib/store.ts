/**
 * Zustand store — centralized UI state + async actions.
 *
 * Components read state via useHarnessStore(selector).
 * Components trigger actions via store.xxx() — never fetch directly.
 *
 * Server state (episodes, chunks) lives in SWR hooks (hooks.ts).
 * This store only manages CLIENT-SIDE UI state + async commands.
 */

import { create } from "zustand";
import type { ChunkEdit, EditBatch, StageName } from "./types";
import * as api from "./hooks";

interface HarnessState {
  // --- UI state ---
  selectedId: string | null;
  editing: string | null;
  playingChunkId: string | null;
  edits: EditBatch;
  drawerOpen: { cid: string; stage: StageName } | null;
  helpOpen: boolean;
  sidebarCollapsed: boolean;

  // --- UI actions ---
  selectEpisode: (id: string) => void;
  startEditing: (cid: string) => void;
  cancelEditing: () => void;
  togglePlay: (cid: string) => void;
  stageEdit: (cid: string, draft: ChunkEdit) => void;
  discardEdits: () => void;
  openDrawer: (cid: string, stage: StageName) => void;
  closeDrawer: () => void;
  setHelpOpen: (open: boolean) => void;
  setSidebarCollapsed: (collapsed: boolean) => void;

  // --- Computed ---
  dirtyCount: () => { tts: number; sub: number };

  // --- Async actions (call API → update state) ---
  runEpisode: (mode: string, chunkIds?: string[]) => Promise<void>;
  applyEdits: (episodeId: string) => Promise<void>;
  retryChunk: (epId: string, cid: string, stage: StageName, cascade: boolean) => Promise<void>;
  createEpisode: (id: string, file: File) => Promise<void>;
  deleteEpisode: (id: string) => Promise<void>;
  duplicateEpisode: (id: string, newId: string) => Promise<void>;
  archiveEpisode: (id: string) => Promise<void>;
  updateConfig: (epId: string, config: Record<string, unknown>) => Promise<void>;
  finalizeTake: (epId: string, cid: string, takeId: string) => Promise<void>;
  previewTake: (audioUri: string) => void;
}

export const useHarnessStore = create<HarnessState>((set, get) => ({
  // --- Initial state ---
  selectedId: typeof window !== "undefined" ? window.localStorage.getItem("tts-harness:selectedEpisode") : null,
  editing: null,
  playingChunkId: null,
  edits: {},
  drawerOpen: null,
  helpOpen: false,
  sidebarCollapsed: typeof window !== "undefined" ? window.localStorage.getItem("tts-harness:sidebarCollapsed") === "true" : false,

  // --- UI actions ---
  selectEpisode: (id) => {
    set({ selectedId: id, edits: {}, editing: null, playingChunkId: null, drawerOpen: null });
    if (typeof window !== "undefined") window.localStorage.setItem("tts-harness:selectedEpisode", id);
  },

  startEditing: (cid) => set((s) => ({ editing: s.editing === cid ? null : cid })),
  cancelEditing: () => set({ editing: null }),

  togglePlay: (cid) => set((s) => ({ playingChunkId: s.playingChunkId === cid ? null : cid })),

  stageEdit: (cid, draft) => set((s) => {
    const next = { ...s.edits };
    if (Object.keys(draft).length === 0) { delete next[cid]; } else { next[cid] = draft; }
    return { edits: next, editing: null, playingChunkId: s.playingChunkId === cid ? null : s.playingChunkId };
  }),

  discardEdits: () => set({ edits: {} }),

  openDrawer: (cid, stage) => set({ drawerOpen: { cid, stage } }),
  closeDrawer: () => set({ drawerOpen: null }),

  setHelpOpen: (open) => set({ helpOpen: open }),

  setSidebarCollapsed: (collapsed) => {
    set({ sidebarCollapsed: collapsed });
    if (typeof window !== "undefined") window.localStorage.setItem("tts-harness:sidebarCollapsed", String(collapsed));
  },

  // --- Computed ---
  dirtyCount: () => {
    const edits = get().edits;
    let tts = 0, sub = 0;
    for (const e of Object.values(edits)) {
      if (e.textNormalized !== undefined) tts++;
      if (e.subtitleText !== undefined) sub++;
    }
    return { tts, sub };
  },

  // --- Async actions ---
  runEpisode: async (mode, chunkIds) => {
    const id = get().selectedId;
    if (!id) return;
    await api.runEpisode(id, mode, chunkIds);
  },

  applyEdits: async (episodeId) => {
    const edits = get().edits;
    if (Object.keys(edits).length === 0) return;
    await api.applyEdits(episodeId, edits);
    set({ edits: {}, playingChunkId: null });
  },

  retryChunk: async (epId, cid, stage, cascade) => {
    await api.retryChunk(epId, cid, stage, cascade);
  },

  createEpisode: async (id, file) => {
    await api.createEpisode(id, file);
  },

  deleteEpisode: async (id) => {
    await api.deleteEpisode(id);
    if (get().selectedId === id) {
      set({ selectedId: null });
      if (typeof window !== "undefined") window.localStorage.removeItem("tts-harness:selectedEpisode");
    }
  },

  duplicateEpisode: async (id, newId) => {
    await api.duplicateEpisode(id, newId);
    set({ selectedId: newId });
    if (typeof window !== "undefined") window.localStorage.setItem("tts-harness:selectedEpisode", newId);
  },

  archiveEpisode: async (id) => {
    await api.archiveEpisode(id);
    if (get().selectedId === id) {
      set({ selectedId: null });
      if (typeof window !== "undefined") window.localStorage.removeItem("tts-harness:selectedEpisode");
    }
  },

  updateConfig: async (epId, config) => {
    await api.updateConfig(epId, config);
  },

  finalizeTake: async (epId, cid, takeId) => {
    await api.finalizeTake(epId, cid, takeId);
  },

  previewTake: (audioUri) => {
    const audio = new Audio(api.getAudioUrl(audioUri));
    audio.play().catch(() => {});
  },
}));
