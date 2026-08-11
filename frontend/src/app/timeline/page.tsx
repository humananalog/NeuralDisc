"use client";

import { useEffect, useMemo, useState } from "react";
import { api, type MediaItem } from "@/lib/api";
import { MediaThumbnail } from "@/components/MediaThumbnail";
import { formatDate } from "@/lib/utils";
import { useAppStore } from "@/lib/store";

export default function TimelinePage() {
  const [items, setItems] = useState<MediaItem[]>([]);
  const select = useAppStore((s) => s.select);
  const selectedIds = useAppStore((s) => s.selectedIds);
  const libraryEpoch = useAppStore((s) => s.libraryEpoch);
  const liveImports = useAppStore((s) => s.liveImports);
  const importActive = liveImports.some(
    (j) =>
      !j.dismissed &&
      (!j.status ||
        (j.status.status !== "completed" &&
          j.status.status !== "failed" &&
          j.status.status !== "cancelled")),
  );

  useEffect(() => {
    const load = () =>
      api
        .media({ limit: 200, sort: "taken_at_desc" })
        .then((d) => setItems(d.items))
        .catch(() => {});
    load();
    if (!importActive) return;
    const id = setInterval(load, 2000);
    return () => clearInterval(id);
  }, [libraryEpoch, importActive]);

  const groups = useMemo(() => {
    const map = new Map<string, MediaItem[]>();
    for (const item of items) {
      const key = item.taken_at
        ? new Date(item.taken_at).toISOString().slice(0, 10)
        : "Unknown date";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(item);
    }
    return Array.from(map.entries());
  }, [items]);

  return (
    <div className="h-full overflow-y-auto px-4 pb-8">
      {groups.map(([day, dayItems]) => (
        <section key={day} className="mb-6">
          <h2 className="sticky top-0 z-10 bg-[var(--bg-base)]/95 py-2 text-[13px] font-medium backdrop-blur">
            {day === "Unknown date" ? day : formatDate(day)}
            <span className="ml-2 text-[11px] font-normal text-[var(--text-muted)]">
              {dayItems.length}
            </span>
          </h2>
          <div className="flex flex-wrap gap-1.5">
            {dayItems.map((item) => (
              <MediaThumbnail
                key={item.id}
                item={item}
                size={120}
                selected={selectedIds.has(item.id)}
                onClick={(e) =>
                  select(
                    item.id,
                    e.metaKey || e.ctrlKey,
                    e.shiftKey,
                    dayItems.map((x) => x.id),
                  )
                }
              />
            ))}
          </div>
        </section>
      ))}
      {items.length === 0 && (
        <div className="flex h-64 items-center justify-center text-[var(--text-muted)]">
          No timeline items yet
        </div>
      )}
    </div>
  );
}
