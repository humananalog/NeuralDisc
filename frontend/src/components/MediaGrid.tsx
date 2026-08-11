"use client";

import { useEffect, useMemo, useState, useCallback, useRef } from "react";
import { Trash2, Sparkles, RefreshCw, RotateCw, RotateCcw } from "lucide-react";
import { api, type MediaItem } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { useMediaShortcuts, type RotateMode } from "@/hooks/useMediaShortcuts";
import { MediaThumbnail } from "./MediaThumbnail";
import { DetailPanel } from "./DetailPanel";
import { DeleteConfirmModal } from "./DeleteConfirmModal";
import { MediaLightbox } from "./MediaLightbox";
import { ShortcutsHelp } from "./ShortcutsHelp";

const SIZE_MAP = { small: 96, medium: 144, large: 208 };

export function MediaGrid({ sort = "taken_at_desc" }: { sort?: string }) {
  const density = useAppStore((s) => s.density);
  const search = useAppStore((s) => s.search);
  const filters = useAppStore((s) => s.filters);
  const selectedIds = useAppStore((s) => s.selectedIds);
  const select = useAppStore((s) => s.select);
  const clearSelection = useAppStore((s) => s.clearSelection);
  const selectAll = useAppStore((s) => s.selectAll);
  const setDetailOpen = useAppStore((s) => s.setDetailOpen);
  const detailOpen = useAppStore((s) => s.detailOpen);
  const activeId = useAppStore((s) => s.activeId);
  const libraryEpoch = useAppStore((s) => s.libraryEpoch);
  const liveImports = useAppStore((s) => s.liveImports);
  const bumpLibrary = useAppStore((s) => s.bumpLibrary);

  const importActive = liveImports.some(
    (j) =>
      !j.dismissed &&
      (!j.status ||
        (j.status.status !== "completed" &&
          j.status.status !== "failed" &&
          j.status.status !== "cancelled")),
  );

  // During live import, show newest classified first so they stream into view
  const effectiveSort = importActive ? "created_at_desc" : sort;

  // Stable key so filter changes always retrigger load (object identity alone is fragile)
  const filterKey = useMemo(
    () =>
      JSON.stringify({
        media_type: filters.media_type ?? null,
        hitl_status: filters.hitl_status ?? null,
        is_duplicate: filters.is_duplicate ?? null,
        is_blurry: filters.is_blurry ?? null,
        trash: filters.trash ?? null,
      }),
    [filters],
  );

  const [items, setItems] = useState<MediaItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [livePulse, setLivePulse] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newCount, setNewCount] = useState(0);
  const [batchDeleteOpen, setBatchDeleteOpen] = useState(false);
  const [batchBusy, setBatchBusy] = useState(false);
  const [keepBestBusy, setKeepBestBusy] = useState(false);
  const [keepBestMsg, setKeepBestMsg] = useState<string | null>(null);
  const [rotateBusy, setRotateBusy] = useState(false);
  const [rotateMsg, setRotateMsg] = useState<string | null>(null);
  /** Per-id thumb remount epoch after rotate */
  const [thumbEpoch, setThumbEpoch] = useState<Record<string, number>>({});
  /** Expanded in-app viewer (double-click / Backspace) */
  const [lightboxId, setLightboxId] = useState<string | null>(null);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const knownIds = useRef<Set<string>>(new Set());
  const firstLoad = useRef(true);

  const size = SIZE_MAP[density];
  const orderedIds = useMemo(() => items.map((i) => i.id), [items]);
  const itemsById = useMemo(() => new Map(items.map((i) => [i.id, i])), [items]);

  const load = useCallback(
    async (opts?: { silent?: boolean }) => {
      const silent = opts?.silent ?? false;
      if (!silent) {
        setLoading(true);
        setError(null);
      }
      try {
        const data = await api.media({
          limit: 200,
          q: search || undefined,
          media_type: filters.media_type,
          hitl_status: filters.hitl_status,
          is_duplicate: filters.is_duplicate,
          is_blurry: filters.is_blurry,
          trash: filters.trash === true ? true : undefined,
          sort: filters.trash ? "deleted_at_desc" : effectiveSort,
        });

        const nextIds = new Set(data.items.map((i) => i.id));
        if (!firstLoad.current && knownIds.current.size > 0) {
          let arrived = 0;
          for (const id of nextIds) {
            if (!knownIds.current.has(id)) arrived += 1;
          }
          if (arrived > 0) {
            setNewCount((c) => c + arrived);
            setLivePulse(true);
            setTimeout(() => setLivePulse(false), 1200);
          }
        }
        knownIds.current = nextIds;
        firstLoad.current = false;

        setItems(data.items);
        setTotal(data.total);
      } catch (e) {
        if (!silent) {
          setError(e instanceof Error ? e.message : "Failed to load media");
        }
      } finally {
        if (!silent) setLoading(false);
      }
    },
    // filterKey captures all filter fields; search & sort complete the live query
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [search, filterKey, effectiveSort],
  );

  // Live filters + search: reload whenever the query surface changes
  useEffect(() => {
    const delay = search ? 200 : 0;
    const t = setTimeout(() => {
      void load({ silent: false });
    }, delay);
    return () => clearTimeout(t);
  }, [load, search, filterKey, effectiveSort]);

  // Live: when import promotes items (libraryEpoch) or while import running
  useEffect(() => {
    if (libraryEpoch === 0 && !importActive) return;
    void load({ silent: true });
  }, [libraryEpoch, load, importActive]);

  useEffect(() => {
    if (!importActive) return;
    const id = setInterval(() => {
      void load({ silent: true });
    }, 1500);
    return () => clearInterval(id);
  }, [importActive, load]);

  const active = items.find((i) => i.id === activeId) || null;
  const showPanel = detailOpen && active;
  const lightboxItem = lightboxId
    ? items.find((i) => i.id === lightboxId) || active
    : null;

  const selectedItems = useMemo(
    () => items.filter((i) => selectedIds.has(i.id)),
    [items, selectedIds],
  );

  const openLightbox = useCallback(
    (id: string) => {
      select(id);
      setLightboxId(id);
    },
    [select],
  );

  const closeLightbox = useCallback(() => {
    setLightboxId(null);
  }, []);

  function applyRotatedMedia(updated: MediaItem[]) {
    const now = Date.now();
    const byId = new Map(updated.map((m) => [m.id, m]));
    setThumbEpoch((prev) => {
      const next = { ...prev };
      for (const m of updated) next[m.id] = (next[m.id] || 0) + 1 + (now % 1000);
      return next;
    });
    setItems((prev) =>
      prev.map((x) => {
        const u = byId.get(x.id);
        if (!u) return x;
        const stamp = u.updated_at || new Date().toISOString();
        const bump = (url?: string | null) => {
          if (!url) return url;
          const base = url.split("?")[0];
          return `${base}?v=${encodeURIComponent(stamp)}&t=${now}`;
        };
        return {
          ...u,
          updated_at: stamp,
          thumb_url: bump(u.thumb_url) ?? u.thumb_url,
          preview_url: bump(u.preview_url) ?? u.preview_url,
        };
      }),
    );
  }

  const patchItems = useCallback((updated: MediaItem[]) => {
    const byId = new Map(updated.map((m) => [m.id, m]));
    setItems((prev) => prev.map((x) => byId.get(x.id) ?? x));
  }, []);

  const handleBatchRotate = useCallback(
    async (mode: RotateMode = "auto", idsOverride?: string[]) => {
      const sourceIds = idsOverride ?? selectedItems.map((i) => i.id);
      const ids = sourceIds.filter((id) => {
        const m = itemsById.get(id);
        return !m || m.media_type === "image";
      });
      if (!ids.length) {
        setError("Select one or more images to rotate");
        return;
      }
      setRotateBusy(true);
      setRotateMsg(null);
      setError(null);
      try {
        const res = await api.batchRotateMedia(ids, mode, true);
        applyRotatedMedia(res.items);
        bumpLibrary();
        const failHint =
          res.count_failed > 0 ? ` · ${res.count_failed} failed` : "";
        setRotateMsg(
          mode === "auto"
            ? `Auto-rotate: fixed ${res.count_rotated}, already upright ${res.count_unchanged}${failHint}`
            : `Rotated ${res.count_rotated} image${res.count_rotated === 1 ? "" : "s"}${failHint}`,
        );
        window.setTimeout(() => void load({ silent: true }), 400);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Batch rotate failed");
      } finally {
        setRotateBusy(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [selectedItems, itemsById, bumpLibrary, load],
  );

  useMediaShortcuts({
    enabled: !batchDeleteOpen && !shortcutsOpen,
    orderedIds,
    itemsById,
    lightboxOpen: Boolean(lightboxId),
    detailOpen,
    getTargetIds: () => {
      if (lightboxId) return [lightboxId];
      if (selectedIds.size > 0) return [...selectedIds];
      if (activeId) return [activeId];
      return [];
    },
    onItemsPatched: patchItems,
    onRotate: (ids, mode) => void handleBatchRotate(mode, ids),
    onRequestDelete: () => {
      if (selectedIds.size === 0 && (lightboxId || activeId)) {
        const id = lightboxId || activeId;
        if (id) select(id);
      }
      setBatchDeleteOpen(true);
    },
    onSelectId: (id) => select(id),
    onOpenDetail: () => setDetailOpen(true),
    onCloseDetail: () => setDetailOpen(false),
    onOpenLightbox: openLightbox,
    onCloseLightbox: closeLightbox,
    onClearSelection: clearSelection,
    onSelectAll: () => selectAll(items),
    onToggleHelp: () => setShortcutsOpen((v) => !v),
  });

  async function handleBatchDelete(permanent: boolean) {
    const ids =
      selectedIds.size > 0
        ? [...selectedIds]
        : lightboxId
          ? [lightboxId]
          : activeId
            ? [activeId]
            : [];
    if (!ids.length) return;
    setBatchBusy(true);
    setError(null);
    try {
      const res = await api.batchDeleteMedia(ids, permanent);
      const removed = new Set([...res.deleted, ...res.trashed]);
      setItems((prev) => prev.filter((x) => !removed.has(x.id)));
      setTotal((t) => Math.max(0, t - removed.size));
      clearSelection();
      setDetailOpen(false);
      closeLightbox();
      bumpLibrary();
      setBatchDeleteOpen(false);
      void load({ silent: true });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Batch delete failed";
      setError(msg);
      throw e instanceof Error ? e : new Error(msg);
    } finally {
      setBatchBusy(false);
    }
  }

  async function handleKeepBestBatch() {
    const ids = [...selectedIds];
    if (ids.length < 2) {
      setError("Select at least 2 images to keep the best");
      return;
    }
    setKeepBestBusy(true);
    setKeepBestMsg(null);
    setError(null);
    try {
      const res = await api.keepBestBatch({
        media_ids: ids,
        trash_losers: true,
      });
      const trashed = new Set(res.trashed);
      const kept = new Set(res.kept);
      setItems((prev) => prev.filter((x) => !trashed.has(x.id)));
      setTotal((t) => Math.max(0, t - res.trashed_count));
      if (kept.size) {
        clearSelection();
        for (const id of kept) {
          select(id, true, false, [...kept]);
        }
      } else {
        clearSelection();
      }
      setDetailOpen(false);
      bumpLibrary();
      setKeepBestMsg(
        `Kept ${res.kept_count} · trashed ${res.trashed_count} worse duplicate${
          res.trashed_count === 1 ? "" : "s"
        }${res.groups_resolved ? ` · ${res.groups_resolved} group(s)` : ""}`,
      );
      void load({ silent: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Keep best failed");
    } finally {
      setKeepBestBusy(false);
    }
  }

  const canKeepBest = selectedIds.size >= 2;
  const selectedImageCount = selectedItems.filter((i) => i.media_type === "image").length;
  const anyBusy = batchBusy || keepBestBusy || rotateBusy;
  const deleteCount =
    selectedIds.size > 0
      ? selectedIds.size
      : lightboxId || activeId
        ? 1
        : 0;

  return (
    <div className="flex h-full min-h-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center justify-between gap-2 px-4 py-2 text-[12px] text-[var(--text-muted)]">
          <span className="flex items-center gap-2">
            {loading ? "Loading…" : `${total.toLocaleString()} items`}
            {importActive && (
              <span
                className={cnLive(
                  "inline-flex items-center gap-1 rounded-full border border-[var(--accent)]/40 bg-[var(--accent)]/10 px-2 py-0.5 text-[10px] font-medium text-[var(--accent)]",
                  livePulse && "nd-flash-ok",
                )}
              >
                <span className="relative flex h-1.5 w-1.5">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--accent)] opacity-60" />
                  <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-[var(--accent)]" />
                </span>
                Live · newest first
              </span>
            )}
            {newCount > 0 && (
              <button
                type="button"
                onClick={() => setNewCount(0)}
                className="rounded-full bg-[var(--success)]/15 px-2 py-0.5 text-[10px] text-[var(--success)]"
              >
                +{newCount} new
              </button>
            )}
            <button
              type="button"
              onClick={() => setShortcutsOpen(true)}
              className="rounded border border-[var(--border)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--text-muted)] hover:border-[var(--border-strong)] hover:text-[var(--text-secondary)]"
              title="Keyboard shortcuts (?)"
            >
              ?
            </button>
          </span>
          {selectedIds.size > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[var(--text-secondary)]">
                {selectedIds.size} selected
                {selectedImageCount > 0 && selectedImageCount !== selectedIds.size
                  ? ` · ${selectedImageCount} images`
                  : ""}
              </span>
              <button
                type="button"
                disabled={selectedImageCount < 1 || anyBusy}
                onClick={() => void handleBatchRotate("auto")}
                title="Auto-rotate selected (⇧[)"
                className="inline-flex items-center gap-1 rounded-md border border-[var(--accent)]/40 px-2 py-1 text-[11px] text-[var(--accent)] hover:bg-[var(--accent)]/10 disabled:opacity-40"
              >
                <RefreshCw className={cnSpin(rotateBusy && "animate-spin", "h-3 w-3")} />
                {rotateBusy ? "Rotating…" : "Auto-rotate"}
              </button>
              <button
                type="button"
                disabled={selectedImageCount < 1 || anyBusy}
                onClick={() => void handleBatchRotate("ccw")}
                title="Rotate 90° left ([)"
                className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-1.5 py-1 text-[11px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] disabled:opacity-40"
              >
                <RotateCcw className="h-3 w-3" />
              </button>
              <button
                type="button"
                disabled={selectedImageCount < 1 || anyBusy}
                onClick={() => void handleBatchRotate("cw")}
                title="Rotate 90° right (])"
                className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-1.5 py-1 text-[11px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] disabled:opacity-40"
              >
                <RotateCw className="h-3 w-3" />
              </button>
              <button
                type="button"
                disabled={!canKeepBest || anyBusy}
                onClick={() => void handleKeepBestBatch()}
                title={
                  canKeepBest
                    ? "Keep the best image in each duplicate cluster; trash the rest"
                    : "Select 2+ images"
                }
                className="inline-flex items-center gap-1 rounded-md border border-[var(--success)]/40 px-2 py-1 text-[11px] text-[var(--success)] hover:bg-[var(--success)]/10 disabled:opacity-40"
              >
                <Sparkles className="h-3 w-3" />
                {keepBestBusy ? "Keeping best…" : "Keep best"}
              </button>
              <button
                type="button"
                disabled={anyBusy}
                onClick={() => setBatchDeleteOpen(true)}
                title="Delete (Del)"
                className="inline-flex items-center gap-1 rounded-md border border-[var(--danger)]/40 px-2 py-1 text-[11px] text-[var(--danger)] hover:bg-[var(--danger)]/10 disabled:opacity-40"
              >
                <Trash2 className="h-3 w-3" />
                Delete
              </button>
              <button
                type="button"
                onClick={clearSelection}
                className="text-[11px] text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
              >
                Clear
              </button>
            </div>
          )}
        </div>

        {(keepBestMsg || rotateMsg) && (
          <div className="mx-4 mb-2 rounded-md border border-[var(--success)]/40 bg-[var(--success)]/10 px-3 py-2 text-[12px] text-[var(--success)]">
            {rotateMsg || keepBestMsg}
            <button
              type="button"
              className="ml-2 underline opacity-80"
              onClick={() => {
                setKeepBestMsg(null);
                setRotateMsg(null);
              }}
            >
              dismiss
            </button>
          </div>
        )}

        {error && (
          <div className="mx-4 mb-2 rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-3 py-2 text-[12px] text-[var(--danger)]">
            {error.includes("Failed to fetch") || error.includes("ECONNREFUSED")
              ? "Backend offline — start with: neuraldisc serve"
              : error}
          </div>
        )}

        {!loading && items.length === 0 && !error && (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 text-[var(--text-muted)]">
            <p className="text-[14px]">
              {importActive
                ? "Waiting for first classified images…"
                : "No items match filters"}
            </p>
            <p className="text-[12px]">
              {importActive
                ? "As files pass quality + EXIF they appear here automatically."
                : "Use Import to add a disc or folder."}
            </p>
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-3 pb-24">
          <div
            className="flex flex-wrap content-start"
            style={{ gap: density === "small" ? 4 : 6 }}
          >
            {items.map((item) => (
              <MediaThumbnail
                key={item.id}
                item={item}
                size={size}
                refreshKey={thumbEpoch[item.id] || 0}
                selected={selectedIds.has(item.id)}
                onClick={(e) => {
                  const multi = e.metaKey || e.ctrlKey;
                  const range = e.shiftKey;
                  select(item.id, multi, range, orderedIds);
                  if (!multi && !range) {
                    setDetailOpen(true);
                  }
                }}
                onDoubleClick={() => {
                  openLightbox(item.id);
                }}
              />
            ))}
          </div>
        </div>
      </div>

      {lightboxItem && (
        <MediaLightbox
          item={lightboxItem}
          items={items}
          onClose={closeLightbox}
          onNavigate={(id) => {
            select(id);
            setLightboxId(id);
          }}
        />
      )}

      {showPanel && active && (
        <DetailPanel
          item={active}
          onClose={() => setDetailOpen(false)}
          onUpdated={(m) => {
            applyRotatedMedia([m]);
          }}
          onDeleted={(id) => {
            setItems((prev) => prev.filter((x) => x.id !== id));
            setTotal((t) => Math.max(0, t - 1));
            clearSelection();
          }}
        />
      )}

      {batchDeleteOpen && deleteCount > 0 && (
        <DeleteConfirmModal
          count={deleteCount}
          filenames={
            selectedItems.length
              ? selectedItems.map((i) => i.filename)
              : [
                  items.find((i) => i.id === (lightboxId || activeId))?.filename ||
                    "1 item",
                ]
          }
          permanentDefault={filters.trash === true}
          busy={batchBusy}
          onCancel={() => setBatchDeleteOpen(false)}
          onConfirm={handleBatchDelete}
        />
      )}

      <ShortcutsHelp open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
    </div>
  );
}

function cnLive(...parts: Array<string | false | undefined>) {
  return parts.filter(Boolean).join(" ");
}

function cnSpin(...parts: Array<string | false | undefined>) {
  return parts.filter(Boolean).join(" ");
}
