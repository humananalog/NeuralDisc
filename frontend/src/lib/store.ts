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
  importOpen: boolean;
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
};

export const useAppStore = create<AppState>((set, get) => ({
  selectedIds: new Set(),
  activeId: null,
  density: "medium",
  search: "",
  filters: {},
  detailOpen: false,
  jobsOpen: false,
  importOpen: false,
  pendingReview: 0,
  duplicatesCount: 0,
  navCounts: { ...EMPTY_NAV_COUNTS },
  liveImports: [],
  libraryEpoch: 0,
  lastPromotedTotal: 0,

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
      const shouldBump = nextPromoted > prevPromoted || nextPromoted > s.lastPromotedTotal;
      return {
        liveImports: s.liveImports.map((j) =>
          j.jobId === jobId ? { ...j, status } : j,
        ),
        libraryEpoch: shouldBump ? s.libraryEpoch + 1 : s.libraryEpoch,
        lastPromotedTotal: Math.max(s.lastPromotedTotal, nextPromoted),
      };
    }),

  dismissLiveImport: (jobId) =>
    set((s) => ({
      liveImports: s.liveImports.map((j) =>
        j.jobId === jobId ? { ...j, dismissed: true } : j,
      ),
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
}));
