/** Shared helpers for media grids (Library, Timeline, Map, …). */

import type { MediaItem } from "@/lib/api";

/** Merge rotate API results into local items with cache-busted derivative URLs. */
export function mergeRotatedMediaItems(
  prev: MediaItem[],
  updated: MediaItem[],
): MediaItem[] {
  const now = Date.now();
  const byId = new Map(updated.map((m) => [m.id, m]));
  return prev.map((x) => {
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
  });
}

export function patchMediaItems(
  prev: MediaItem[],
  updated: MediaItem[],
): MediaItem[] {
  const byId = new Map(updated.map((m) => [m.id, m]));
  return prev.map((x) => byId.get(x.id) ?? x);
}
