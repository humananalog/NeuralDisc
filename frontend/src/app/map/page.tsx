"use client";

import { useEffect, useState } from "react";
import { api, type MediaItem } from "@/lib/api";
import { MediaThumbnail } from "@/components/MediaThumbnail";
import { MediaLightbox } from "@/components/MediaLightbox";
import { DetailPanel } from "@/components/DetailPanel";
import { ShortcutsHelp } from "@/components/ShortcutsHelp";
import { useAppStore } from "@/lib/store";
import { useMediaViewShortcuts } from "@/hooks/useMediaViewShortcuts";
import { mergeRotatedMediaItems } from "@/lib/mediaPatch";

export default function MapPage() {
  const [items, setItems] = useState<MediaItem[]>([]);
  const select = useAppStore((s) => s.select);
  const selectedIds = useAppStore((s) => s.selectedIds);
  const libraryEpoch = useAppStore((s) => s.libraryEpoch);
  const bumpLibrary = useAppStore((s) => s.bumpLibrary);

  useEffect(() => {
    api
      .media({ limit: 200, has_gps: true })
      .then((d) => setItems(d.items))
      .catch(() => {});
  }, [libraryEpoch]);

  const {
    lightboxItem,
    openLightbox,
    closeLightbox,
    shortcutsOpen,
    setShortcutsOpen,
    detailOpen,
    setDetailOpen,
    detailItem,
    rotateError,
  } = useMediaViewShortcuts({ items, setItems });

  return (
    <div className="relative flex h-full flex-col p-4">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div>
          <h1 className="text-[16px] font-semibold">Map</h1>
          <p className="text-[12px] text-[var(--text-muted)]">
            Full map tiles (MapLibre) land in a later phase. GPS-tagged items —
            select +{" "}
            <kbd className="font-mono text-[var(--text-secondary)]">[</kbd>/
            <kbd className="font-mono text-[var(--text-secondary)]">]</kbd> rotate ·{" "}
            <button
              type="button"
              onClick={() => setShortcutsOpen(true)}
              className="font-mono text-[var(--text-secondary)] hover:underline"
            >
              ?
            </button>
          </p>
        </div>
        {rotateError && (
          <p className="text-[11px] text-[var(--danger)]">{rotateError}</p>
        )}
      </div>
      {items.length === 0 ? (
        <p className="text-[var(--text-muted)]">No GPS-tagged media yet.</p>
      ) : (
        <div className="flex flex-wrap gap-2 overflow-y-auto">
          {items.map((item) => (
            <div key={item.id} className="space-y-1">
              <MediaThumbnail
                item={item}
                size={112}
                selected={selectedIds.has(item.id)}
                onClick={(e) =>
                  select(
                    item.id,
                    e.metaKey || e.ctrlKey,
                    e.shiftKey,
                    items.map((x) => x.id),
                  )
                }
                onDoubleClick={() => openLightbox(item.id)}
              />
              <div className="font-mono text-[10px] text-[var(--text-muted)]">
                {item.gps_lat?.toFixed(4)}, {item.gps_lon?.toFixed(4)}
              </div>
            </div>
          ))}
        </div>
      )}

      {lightboxItem && (
        <MediaLightbox
          item={lightboxItem}
          items={items}
          onClose={closeLightbox}
          onNavigate={openLightbox}
        />
      )}
      {detailOpen && detailItem && (
        <DetailPanel
          item={detailItem}
          onClose={() => setDetailOpen(false)}
          onUpdated={(m) => {
            setItems((prev) => mergeRotatedMediaItems(prev, [m]));
            bumpLibrary();
          }}
          onDeleted={() => {
            setItems((prev) => prev.filter((x) => x.id !== detailItem.id));
            setDetailOpen(false);
            bumpLibrary();
          }}
        />
      )}
      <ShortcutsHelp open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
    </div>
  );
}
