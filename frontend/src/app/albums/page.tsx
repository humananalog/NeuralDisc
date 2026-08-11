"use client";

import { useEffect, useState } from "react";
import { api, type Album } from "@/lib/api";

export default function AlbumsPage() {
  const [albums, setAlbums] = useState<Album[]>([]);

  useEffect(() => {
    api.albums().then(setAlbums).catch(() => {});
  }, []);

  return (
    <div className="h-full overflow-y-auto p-4">
      <h1 className="mb-4 text-[16px] font-semibold">Albums</h1>
      {albums.length === 0 ? (
        <p className="text-[var(--text-muted)]">
          No albums yet. Create collections after reviewing media.
        </p>
      ) : (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {albums.map((a) => (
            <div
              key={a.id}
              className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)]"
            >
              <div className="aspect-video bg-[var(--bg-hover)]">
                {a.cover_media_id && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={`/api/media/${a.cover_media_id}/thumb`}
                    alt=""
                    className="h-full w-full object-cover"
                  />
                )}
              </div>
              <div className="p-2">
                <div className="text-[13px] font-medium">{a.name}</div>
                <div className="text-[11px] text-[var(--text-muted)]">
                  {a.item_count} items
                  {a.is_ai_proposed && " · AI proposed"}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
