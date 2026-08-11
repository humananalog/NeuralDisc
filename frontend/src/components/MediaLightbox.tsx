"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  X,
  ChevronLeft,
  ChevronRight,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { mediaSrc, type MediaItem } from "@/lib/api";
import { cn, formatDate } from "@/lib/utils";

type Props = {
  item: MediaItem;
  items: MediaItem[];
  onClose: () => void;
  onNavigate: (id: string) => void;
};

/**
 * In-app expanded viewer — fills the main workspace overlay.
 * Open: double-click thumbnail or Backspace on selection.
 * Close: Escape, Backspace, backdrop click, or X.
 * Navigate: ← → when multiple items in the current grid list.
 */
export function MediaLightbox({ item, items, onClose, onNavigate }: Props) {
  const [zoom, setZoom] = useState(1);
  const [loaded, setLoaded] = useState(false);

  const index = useMemo(
    () => items.findIndex((i) => i.id === item.id),
    [items, item.id],
  );
  const hasPrev = index > 0;
  const hasNext = index >= 0 && index < items.length - 1;

  const bust =
    item.updated_at ||
    (item.rotation_degrees ? String(item.rotation_degrees) : "") ||
    "";
  const raw = mediaSrc(
    item.preview_url || item.original_url || item.thumb_url,
  );
  const src =
    raw && bust
      ? `${raw}${raw.includes("?") ? "&" : "?"}v=${encodeURIComponent(bust)}`
      : raw;

  const goPrev = useCallback(() => {
    if (!hasPrev) return;
    setZoom(1);
    setLoaded(false);
    onNavigate(items[index - 1].id);
  }, [hasPrev, index, items, onNavigate]);

  const goNext = useCallback(() => {
    if (!hasNext) return;
    setZoom(1);
    setLoaded(false);
    onNavigate(items[index + 1].id);
  }, [hasNext, index, items, onNavigate]);

  useEffect(() => {
    setZoom(1);
    setLoaded(false);
  }, [item.id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (
        t &&
        (t.tagName === "INPUT" ||
          t.tagName === "TEXTAREA" ||
          t.isContentEditable)
      ) {
        return;
      }
      if (e.key === "Escape" || e.key === "Backspace") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        goPrev();
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        goNext();
      } else if (e.key === "+" || e.key === "=") {
        e.preventDefault();
        setZoom((z) => Math.min(4, z + 0.25));
      } else if (e.key === "-" || e.key === "_") {
        e.preventDefault();
        setZoom((z) => Math.max(0.5, z - 0.25));
      } else if (e.key === "0") {
        e.preventDefault();
        setZoom(1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, goPrev, goNext]);

  // Prevent body scroll while open
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  return (
    <div
      className="fixed inset-0 z-[80] flex flex-col bg-black/92 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={`Expanded: ${item.filename}`}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      {/* Chrome / header */}
      <div className="flex shrink-0 items-center gap-3 border-b border-white/10 px-4 py-2.5 text-white">
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-medium">{item.filename}</div>
          <div className="truncate text-[11px] text-white/50">
            {[
              item.width && item.height ? `${item.width}×${item.height}` : null,
              formatDate(item.taken_at),
              item.camera_model || item.camera_make,
              index >= 0 ? `${index + 1} / ${items.length}` : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))}
            className="rounded-md p-1.5 text-white/70 hover:bg-white/10 hover:text-white"
            title="Zoom out (−)"
            aria-label="Zoom out"
          >
            <ZoomOut className="h-4 w-4" />
          </button>
          <span className="min-w-[3rem] text-center font-mono text-[11px] text-white/60">
            {Math.round(zoom * 100)}%
          </span>
          <button
            type="button"
            onClick={() => setZoom((z) => Math.min(4, z + 0.25))}
            className="rounded-md p-1.5 text-white/70 hover:bg-white/10 hover:text-white"
            title="Zoom in (+)"
            aria-label="Zoom in"
          >
            <ZoomIn className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={onClose}
            className="ml-1 rounded-md p-1.5 text-white/70 hover:bg-white/10 hover:text-white"
            title="Close (Esc / Backspace)"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Image stage — fills remaining viewport inside app */}
      <div
        className="relative flex min-h-0 flex-1 items-center justify-center overflow-auto p-4"
        onClick={(e) => {
          if (e.target === e.currentTarget) onClose();
        }}
        onDoubleClick={() => setZoom((z) => (z === 1 ? 2 : 1))}
      >
        {hasPrev && (
          <button
            type="button"
            onClick={goPrev}
            className="absolute left-3 top-1/2 z-10 -translate-y-1/2 rounded-full border border-white/15 bg-black/50 p-2 text-white/80 hover:bg-black/70 hover:text-white"
            aria-label="Previous"
          >
            <ChevronLeft className="h-5 w-5" />
          </button>
        )}
        {hasNext && (
          <button
            type="button"
            onClick={goNext}
            className="absolute right-3 top-1/2 z-10 -translate-y-1/2 rounded-full border border-white/15 bg-black/50 p-2 text-white/80 hover:bg-black/70 hover:text-white"
            aria-label="Next"
          >
            <ChevronRight className="h-5 w-5" />
          </button>
        )}

        {!loaded && (
          <div className="absolute inset-0 flex items-center justify-center text-[12px] text-white/40">
            Loading…
          </div>
        )}

        {src ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={src}
            alt={item.filename}
            onLoad={() => setLoaded(true)}
            className={cn(
              "max-h-full max-w-full object-contain transition-transform duration-150 select-none",
              !loaded && "opacity-0",
              loaded && "opacity-100",
            )}
            style={{
              transform: `scale(${zoom})`,
              transformOrigin: "center center",
            }}
            draggable={false}
          />
        ) : (
          <div className="text-[13px] text-white/50">No preview available</div>
        )}
      </div>

      <div className="shrink-0 border-t border-white/10 px-4 py-1.5 text-center text-[10px] text-white/40">
        Esc / Backspace close · ← → navigate · double-click zoom · +/− zoom
      </div>
    </div>
  );
}
