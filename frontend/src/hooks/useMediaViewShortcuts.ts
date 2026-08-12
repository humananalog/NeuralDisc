"use client";

import { useCallback, useMemo, useState } from "react";
import { api, type MediaItem } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import {
  useMediaShortcuts,
  type RotateMode,
} from "@/hooks/useMediaShortcuts";
import { mergeRotatedMediaItems, patchMediaItems } from "@/lib/mediaPatch";

type Options = {
  items: MediaItem[];
  setItems: React.Dispatch<React.SetStateAction<MediaItem[]>>;
  /** Override navigation order (e.g. flattened timeline days). Default: items order. */
  orderedIds?: string[];
  enabled?: boolean;
};

/**
 * Lightroom-style keys ([ ] rotate, rate, flag, nav) for any thumbnail grid
 * that uses the global selection store.
 */
export function useMediaViewShortcuts({
  items,
  setItems,
  orderedIds: orderedIdsProp,
  enabled = true,
}: Options) {
  const select = useAppStore((s) => s.select);
  const selectedIds = useAppStore((s) => s.selectedIds);
  const activeId = useAppStore((s) => s.activeId);
  const clearSelection = useAppStore((s) => s.clearSelection);
  const selectAll = useAppStore((s) => s.selectAll);
  const detailOpen = useAppStore((s) => s.detailOpen);
  const setDetailOpen = useAppStore((s) => s.setDetailOpen);
  const bumpLibrary = useAppStore((s) => s.bumpLibrary);

  const [lightboxId, setLightboxId] = useState<string | null>(null);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [rotateError, setRotateError] = useState<string | null>(null);

  const orderedIds = useMemo(
    () => orderedIdsProp ?? items.map((m) => m.id),
    [orderedIdsProp, items],
  );
  const itemsById = useMemo(
    () => new Map(items.map((m) => [m.id, m])),
    [items],
  );

  const openLightbox = useCallback(
    (id: string) => {
      select(id);
      setLightboxId(id);
    },
    [select],
  );

  const closeLightbox = useCallback(() => setLightboxId(null), []);

  const handleRotate = useCallback(
    async (ids: string[], mode: RotateMode) => {
      setRotateError(null);
      try {
        const res = await api.batchRotateMedia(ids, mode, true);
        setItems((prev) => mergeRotatedMediaItems(prev, res.items));
        bumpLibrary();
      } catch (e) {
        setRotateError(e instanceof Error ? e.message : "Rotate failed");
      }
    },
    [setItems, bumpLibrary],
  );

  useMediaShortcuts({
    enabled: enabled && items.length > 0 && !shortcutsOpen,
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
    onItemsPatched: (updated) => {
      setItems((prev) => patchMediaItems(prev, updated));
    },
    onRotate: (ids, mode) => void handleRotate(ids, mode),
    onSelectId: (id) => select(id),
    onOpenDetail: () => setDetailOpen(true),
    onCloseDetail: () => setDetailOpen(false),
    onOpenLightbox: openLightbox,
    onCloseLightbox: closeLightbox,
    onClearSelection: clearSelection,
    onSelectAll: () => selectAll(items),
    onToggleHelp: () => setShortcutsOpen((v) => !v),
  });

  const lightboxItem = lightboxId
    ? items.find((m) => m.id === lightboxId) || null
    : null;
  const detailItem = activeId ? itemsById.get(activeId) || null : null;

  return {
    lightboxId,
    lightboxItem,
    openLightbox,
    closeLightbox,
    shortcutsOpen,
    setShortcutsOpen,
    detailOpen,
    setDetailOpen,
    detailItem,
    rotateError,
    orderedIds,
  };
}
