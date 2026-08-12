"use client";

import { create } from "zustand";
import type { ImportStatus, MediaItem, NavCounts } from "./api";
import { EMPTY_NAV_COUNTS } from "./api";

type Density = "small" | "medium" | "large";

export type LiveImport = {
  jobId: string;
  label: string;
  status: ImportStatus | null;
  dismissed: boolean;
};

/** Shown when a disc copy finishes — ask next disc vs finished */
export type DiscReadyPrompt = {
  jobId: string;
  label: string;
  copied: number;
  bytesCopied: number;
  total: number;
};

type AppState = {
  selectedIds: Set<string>;
  activeId: string | null;
  density: Density;
  search: string;
  filters: {
    media_type?: string;
    hitl_status?: string;
    is_duplicate?: boolean;
    is_blurry?: boolean;
    trash?: boolean;
  };
  detailOpen: boolean;
  jobsOpen: boolean;
  /** Full import dialog visible (blocks center of screen) */
  importOpen: boolean;
  /**
   * Import session minimized to a dock chip — form state is kept,
   * library UI is free. Expand via chip or Import button.
   */
  importMinimized: boolean;
  pendingReview: number;
  /** Active duplicate groups count for sidebar badge */
  duplicatesCount: number;
  /** All left-nav section counters */
  navCounts: NavCounts;

  /** Active import jobs for the live dock panel */
  liveImports: LiveImport[];
  /** Bumps when new library media may have arrived — views subscribe and refresh */
  libraryEpoch: number;
  lastPromotedTotal: number;

  /** Modal after disc copy completes */
  discReadyPrompt: DiscReadyPrompt | null;
  /** Job IDs already shown the next-disc prompt this session */
  discReadyAck: Set<string>;

  select: (id: string, multi?: boolean, range?: boolean, orderedIds?: string[]) => void;
  clearSelection: () => void;
  setActive: (id: string | null) => void;
  setDensity: (d: Density) => void;
  setSearch: (q: string) => void;
  setFilter: (key: keyof AppState["filters"], value: string | boolean | undefined) => void;
  clearFilters: () => void;
  setDetailOpen: (v: boolean) => void;
  setJobsOpen: (v: boolean) => void;
  setImportOpen: (v: boolean) => void;
  setImportMinimized: (v: boolean) => void;
  /** Open full import dialog (clears minimized). */
  expandImport: () => void;
  /** Collapse dialog to dock chip; keep form state. */
  minimizeImport: () => void;
  /** Fully close import UI (caller may reset form). */
  closeImport: () => void;
  setPendingReview: (n: number) => void;
  setDuplicatesCount: (n: number) => void;
  setNavCounts: (c: NavCounts) => void;
  selectAll: (items: MediaItem[]) => void;

  trackImport: (jobId: string, label: string) => void;
  updateLiveImport: (jobId: string, status: ImportStatus) => void;
  dismissLiveImport: (jobId: string) => void;
  bumpLibrary: () => void;
  setLastPromotedTotal: (n: number) => void;
  hasActiveImport: () => boolean;

  clearDiscReadyPrompt: () => void;
  /** Open import picker for the next disc */
  continueNextDisc: () => void;
  /** User is done inserting discs for now */
  finishDiscSession: () => void;
};

function isDiscCopyReady(status: ImportStatus | null | undefined): boolean {
  if (!status) return false;
  if (status.status === "failed" || status.status === "cancelled") return false;
  if (status.disc_ready) return true;
  if (status.phase === "copied") return true;
  return status.status === "completed" && Boolean(status.copy_only);
}

export const useAppStore = create<AppState>((set, get) => ({
  selectedIds: new Set(),
  activeId: null,
  density: "medium",
  search: "",
  filters: {},
  detailOpen: false,
  jobsOpen: false,
  importOpen: false,
  importMinimized: false,
  pendingReview: 0,
  duplicatesCount: 0,
  navCounts: { ...EMPTY_NAV_COUNTS },
  liveImports: [],
  libraryEpoch: 0,
  lastPromotedTotal: 0,
  discReadyPrompt: null,
  discReadyAck: new Set(),

  select: (id, multi = false, range = false, orderedIds = []) => {
    const { selectedIds, activeId } = get();
    const next = new Set(multi || range ? selectedIds : []);
    if (range && activeId && orderedIds.length) {
      const a = orderedIds.indexOf(activeId);
      const b = orderedIds.indexOf(id);
      if (a >= 0 && b >= 0) {
        const [lo, hi] = a < b ? [a, b] : [b, a];
        for (let i = lo; i <= hi; i++) next.add(orderedIds[i]);
      } else {
        next.add(id);
      }
    } else if (multi) {
      if (next.has(id)) next.delete(id);
      else next.add(id);
    } else {
      next.add(id);
    }
    set({ selectedIds: next, activeId: id });
  },

  clearSelection: () => set({ selectedIds: new Set(), activeId: null }),
  setActive: (id) => set({ activeId: id }),
  setDensity: (d) => set({ density: d }),
  setSearch: (q) => set({ search: q }),
  setFilter: (key, value) =>
    set((s) => {
      const filters = { ...s.filters };
      if (value === undefined || value === "") delete filters[key];
      else (filters as Record<string, string | boolean>)[key] = value;
      return { filters };
    }),
  clearFilters: () => set({ filters: {}, search: "" }),
  setDetailOpen: (v) => set({ detailOpen: v }),
  setJobsOpen: (v) => set({ jobsOpen: v }),
  setImportOpen: (v) => set({ importOpen: v }),
  setImportMinimized: (v) => set({ importMinimized: v }),
  expandImport: () => set({ importOpen: true, importMinimized: false }),
  minimizeImport: () => set({ importOpen: false, importMinimized: true }),
  closeImport: () => set({ importOpen: false, importMinimized: false }),
  setPendingReview: (n) => set({ pendingReview: n }),
  setDuplicatesCount: (n) => set({ duplicatesCount: n }),
  setNavCounts: (c) =>
    set({
      navCounts: c,
      pendingReview: c.review,
      duplicatesCount: c.duplicates,
    }),
  selectAll: (items) => set({ selectedIds: new Set(items.map((i) => i.id)) }),

  trackImport: (jobId, label) =>
    set((s) => ({
      liveImports: [
        { jobId, label, status: null, dismissed: false },
        ...s.liveImports.filter((j) => j.jobId !== jobId),
      ],
    })),

  updateLiveImport: (jobId, status) =>
    set((s) => {
      const prev = s.liveImports.find((j) => j.jobId === jobId);
      const prevPromoted = prev?.status?.promoted ?? 0;
      const nextPromoted = status.promoted ?? 0;
      const shouldBump =
        nextPromoted > prevPromoted || nextPromoted > s.lastPromotedTotal;

      const wasReady = isDiscCopyReady(prev?.status);
      const nowReady = isDiscCopyReady(status);
      const shouldPrompt =
        nowReady &&
        !wasReady &&
        !s.discReadyAck.has(jobId) &&
        !(prev?.dismissed) &&
        !s.discReadyPrompt;

      return {
        liveImports: s.liveImports.map((j) =>
          j.jobId === jobId ? { ...j, status } : j,
        ),
        libraryEpoch: shouldBump ? s.libraryEpoch + 1 : s.libraryEpoch,
        lastPromotedTotal: Math.max(s.lastPromotedTotal, nextPromoted),
        discReadyPrompt: shouldPrompt
          ? {
              jobId,
              label: prev?.label || status.message || "Disc",
              copied: status.copied ?? 0,
              bytesCopied: status.bytes_copied ?? 0,
              total: status.total ?? 0,
            }
          : s.discReadyPrompt,
      };
    }),

  dismissLiveImport: (jobId) =>
    set((s) => ({
      liveImports: s.liveImports.map((j) =>
        j.jobId === jobId ? { ...j, dismissed: true } : j,
      ),
      discReadyPrompt:
        s.discReadyPrompt?.jobId === jobId ? null : s.discReadyPrompt,
    })),

  bumpLibrary: () => set((s) => ({ libraryEpoch: s.libraryEpoch + 1 })),
  setLastPromotedTotal: (n) => set({ lastPromotedTotal: n }),
  hasActiveImport: () =>
    get().liveImports.some(
      (j) =>
        !j.dismissed &&
        j.status &&
        j.status.status !== "completed" &&
        j.status.status !== "failed" &&
        j.status.status !== "cancelled",
    ),

  clearDiscReadyPrompt: () => set({ discReadyPrompt: null }),

  continueNextDisc: () => {
    const prompt = get().discReadyPrompt;
    if (!prompt) {
      set({ importOpen: true, importMinimized: false });
      return;
    }
    const ack = new Set(get().discReadyAck);
    ack.add(prompt.jobId);
    set({
      discReadyAck: ack,
      discReadyPrompt: null,
      importOpen: true,
      importMinimized: false,
    });
  },

  finishDiscSession: () => {
    const prompt = get().discReadyPrompt;
    const ack = new Set(get().discReadyAck);
    if (prompt) ack.add(prompt.jobId);
    set((s) => ({
      discReadyAck: ack,
      discReadyPrompt: null,
      liveImports: prompt
        ? s.liveImports.map((j) =>
            j.jobId === prompt.jobId ? { ...j, dismissed: true } : j,
          )
        : s.liveImports,
      libraryEpoch: s.libraryEpoch + 1,
    }));
  },
}));
