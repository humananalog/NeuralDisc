"use client";

import { useEffect, useRef } from "react";
import { api, type MediaItem } from "@/lib/api";
import { isBlockingOverlay, isTypingTarget } from "@/lib/shortcuts";

export type RotateMode = "auto" | "cw" | "ccw" | "180";

type Options = {
  /** When false, listener is idle (e.g. wrong page). Default true. */
  enabled?: boolean;
  /** Ordered ids in the current view (grid / album / lightbox strip). */
  orderedIds: string[];
  itemsById: Map<string, MediaItem>;
  /** Prefer multi-select; fall back to active / lightbox focus. */
  getTargetIds: () => string[];
  lightboxOpen?: boolean;
  detailOpen?: boolean;
  /** Patch local state after rating/flag updates. */
  onItemsPatched: (items: MediaItem[]) => void;
  /** Batch or single rotate — caller owns busy UI. */
  onRotate: (ids: string[], mode: RotateMode) => void | Promise<void>;
  onRequestDelete?: () => void;
  onSelectId?: (id: string) => void;
  onOpenDetail?: () => void;
  onCloseDetail?: () => void;
  onOpenLightbox?: (id: string) => void;
  onCloseLightbox?: () => void;
  onClearSelection?: () => void;
  onSelectAll?: () => void;
  onToggleHelp?: () => void;
};

/**
 * App-wide Lightroom-style media keys (rate, flag, rotate, nav, delete).
 * Safe to mount from MediaGrid; skips when typing or a blocking dialog is open.
 */
export function useMediaShortcuts(opts: Options) {
  const optsRef = useRef(opts);
  optsRef.current = opts;

  useEffect(() => {
    if (opts.enabled === false) return;

    const onKey = (e: KeyboardEvent) => {
      const o = optsRef.current;
      if (o.enabled === false) return;
      if (isTypingTarget(e.target)) return;
      if (isBlockingOverlay()) return;

      const meta = e.metaKey || e.ctrlKey;
      const key = e.key;

      // Help
      if (key === "?" || (key === "/" && e.shiftKey)) {
        e.preventDefault();
        o.onToggleHelp?.();
        return;
      }

      // Select all
      if (meta && key.toLowerCase() === "a") {
        e.preventDefault();
        o.onSelectAll?.();
        return;
      }

      // Escape — layered close
      if (key === "Escape") {
        if (o.lightboxOpen) {
          e.preventDefault();
          o.onCloseLightbox?.();
          return;
        }
        if (o.detailOpen) {
          e.preventDefault();
          o.onCloseDetail?.();
          return;
        }
        e.preventDefault();
        o.onClearSelection?.();
        return;
      }

      // Backspace — lightbox toggle (NeuralDisc convention; Delete trashes)
      if (key === "Backspace") {
        e.preventDefault();
        if (o.lightboxOpen) {
          o.onCloseLightbox?.();
          return;
        }
        const id = o.getTargetIds()[0];
        if (id) o.onOpenLightbox?.(id);
        return;
      }

      if (key === "Delete") {
        e.preventDefault();
        if (o.getTargetIds().length) o.onRequestDelete?.();
        return;
      }

      if (key === "Enter") {
        e.preventDefault();
        const id = o.getTargetIds()[0];
        if (id) {
          o.onSelectId?.(id);
          o.onOpenDetail?.();
        }
        return;
      }

      // Navigate selection / lightbox
      const go =
        key === "ArrowRight" || key === "j" || key === "J"
          ? 1
          : key === "ArrowLeft" || key === "k" || key === "K"
            ? -1
            : 0;
      if (go !== 0 && !meta) {
        const ids = o.orderedIds;
        if (!ids.length) return;
        const focus =
          o.getTargetIds()[0] ||
          (o.lightboxOpen ? ids[0] : null);
        const idx = focus ? ids.indexOf(focus) : -1;
        const nextIdx =
          idx < 0
            ? go > 0
              ? 0
              : ids.length - 1
            : Math.max(0, Math.min(ids.length - 1, idx + go));
        const nextId = ids[nextIdx];
        if (!nextId || nextId === focus) return;
        e.preventDefault();
        o.onSelectId?.(nextId);
        if (o.lightboxOpen) o.onOpenLightbox?.(nextId);
        return;
      }

      const targets = o.getTargetIds();
      if (!targets.length) return;

      // Rating 0–5
      if (key >= "0" && key <= "5" && !meta && !e.altKey) {
        // In lightbox, bare 0 also resets zoom — prefer rating when targets exist
        e.preventDefault();
        const rating = Number(key);
        void (async () => {
          const updated: MediaItem[] = [];
          for (const id of targets) {
            try {
              updated.push(await api.updateMedia(id, { rating }));
            } catch {
              /* keep going */
            }
          }
          if (updated.length) o.onItemsPatched(updated);
        })();
        return;
      }

      // Flag: f toggle, p pick, u unflag
      const lower = key.toLowerCase();
      if ((lower === "f" || lower === "p" || lower === "u") && !meta) {
        e.preventDefault();
        void (async () => {
          const updated: MediaItem[] = [];
          for (const id of targets) {
            const cur = o.itemsById.get(id);
            let flag: boolean;
            if (lower === "u") flag = false;
            else if (lower === "p") flag = true;
            else flag = !(cur?.flag ?? false);
            try {
              updated.push(await api.updateMedia(id, { flag }));
            } catch {
              /* */
            }
          }
          if (updated.length) o.onItemsPatched(updated);
        })();
        return;
      }

      // Rotate [ ] — Shift for auto / 180
      if (key === "[" || key === "]") {
        e.preventDefault();
        let mode: RotateMode;
        if (e.shiftKey) {
          mode = key === "[" ? "auto" : "180";
        } else {
          mode = key === "[" ? "ccw" : "cw";
        }
        const imageIds = targets.filter((id) => {
          const m = o.itemsById.get(id);
          return !m || m.media_type === "image";
        });
        if (imageIds.length) void o.onRotate(imageIds, mode);
        return;
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [opts.enabled]);
}
