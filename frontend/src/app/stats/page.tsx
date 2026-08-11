"use client";

import { useEffect, useState } from "react";
import { api, type Stats, type Disc } from "@/lib/api";
import { formatBytes } from "@/lib/utils";

export default function StatsPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [discs, setDiscs] = useState<Disc[]>([]);

  useEffect(() => {
    api.stats().then(setStats).catch(() => {});
    api.discs().then(setDiscs).catch(() => {});
  }, []);

  if (!stats) {
    return (
      <div className="flex h-full items-center justify-center text-[var(--text-muted)]">
        Loading stats…
      </div>
    );
  }

  const cards = [
    { label: "Total media", value: stats.total_media },
    { label: "Photos", value: stats.total_images },
    { label: "Videos", value: stats.total_videos },
    { label: "Discs", value: stats.total_discs },
    { label: "AI accepted", value: stats.accepted },
    { label: "Rejected", value: stats.rejected },
    { label: "Duplicates", value: stats.duplicates },
    { label: "Blurry", value: stats.blurry ?? 0 },
    { label: "GPS tagged", value: stats.has_gps },
    { label: "Storage", value: formatBytes(stats.storage_bytes) },
  ];

  return (
    <div className="h-full overflow-y-auto p-4">
      <h1 className="mb-4 text-[16px] font-semibold">Library health</h1>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
        {cards.map((c) => (
          <div
            key={c.label}
            className="rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)] p-3"
          >
            <div className="text-[11px] uppercase tracking-wider text-[var(--text-muted)]">
              {c.label}
            </div>
            <div className="mt-1 text-[22px] font-semibold tabular-nums">{c.value}</div>
          </div>
        ))}
      </div>

      <h2 className="mb-2 mt-8 text-[14px] font-medium">Discs</h2>
      <div className="space-y-2">
        {discs.map((d) => (
          <div
            key={d.id}
            className="flex items-center justify-between rounded-md border border-[var(--border)] bg-[var(--bg-elevated)] px-3 py-2 text-[13px]"
          >
            <div>
              <div className="font-medium">{d.volume_name}</div>
              <div className="text-[11px] text-[var(--text-muted)]">{d.notes || d.status}</div>
            </div>
            <div className="text-[var(--text-secondary)]">{d.media_count} files</div>
          </div>
        ))}
        {discs.length === 0 && (
          <p className="text-[var(--text-muted)]">No discs ingested yet.</p>
        )}
      </div>
    </div>
  );
}
