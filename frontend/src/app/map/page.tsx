"use client";

import { useEffect, useState } from "react";
import { api, type MediaItem } from "@/lib/api";
import { MediaThumbnail } from "@/components/MediaThumbnail";

export default function MapPage() {
  const [items, setItems] = useState<MediaItem[]>([]);

  useEffect(() => {
    api
      .media({ limit: 200, has_gps: true })
      .then((d) => setItems(d.items))
      .catch(() => {});
  }, []);

  return (
    <div className="flex h-full flex-col p-4">
      <h1 className="mb-2 text-[16px] font-semibold">Map</h1>
      <p className="mb-4 text-[12px] text-[var(--text-muted)]">
        Full map tiles (MapLibre) land in a later phase. GPS-tagged items:
      </p>
      {items.length === 0 ? (
        <p className="text-[var(--text-muted)]">No GPS-tagged media yet.</p>
      ) : (
        <div className="flex flex-wrap gap-2 overflow-y-auto">
          {items.map((item) => (
            <div key={item.id} className="space-y-1">
              <MediaThumbnail item={item} size={112} />
              <div className="font-mono text-[10px] text-[var(--text-muted)]">
                {item.gps_lat?.toFixed(4)}, {item.gps_lon?.toFixed(4)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
