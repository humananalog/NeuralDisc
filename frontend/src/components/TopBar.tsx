"use client";

import { Search, Columns3, Loader2, HardDriveDownload } from "lucide-react";
import { useAppStore } from "@/lib/store";
import { cn } from "@/lib/utils";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export function TopBar() {
  const search = useAppStore((s) => s.search);
  const setSearch = useAppStore((s) => s.setSearch);
  const density = useAppStore((s) => s.density);
  const setDensity = useAppStore((s) => s.setDensity);
  const filters = useAppStore((s) => s.filters);
  const setFilter = useAppStore((s) => s.setFilter);
  const clearFilters = useAppStore((s) => s.clearFilters);
  const setJobsOpen = useAppStore((s) => s.setJobsOpen);
  const expandImport = useAppStore((s) => s.expandImport);
  const importMinimized = useAppStore((s) => s.importMinimized);
  const importOpen = useAppStore((s) => s.importOpen);
  const liveImports = useAppStore((s) => s.liveImports);
  const importActive = liveImports.some(
    (j) =>
      !j.dismissed &&
      (!j.status ||
        (j.status.status !== "completed" &&
          j.status.status !== "failed" &&
          j.status.status !== "cancelled")),
  );
  const livePromoted = liveImports.reduce(
    (n, j) => n + (j.status?.promoted ?? 0),
    0,
  );
  const [jobHint, setJobHint] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const jobs = await api.jobs();
        const active = jobs.filter(
          (j) => j.status === "running" || j.status === "queued",
        );
        if (!cancelled) {
          if (active.length) {
            const j = active[0];
            setJobHint(
              `${active.length} job${active.length > 1 ? "s" : ""} · ${j.message || j.job_type}`,
            );
          } else {
            setJobHint(null);
          }
        }
      } catch {
        /* backend offline */
      }
    };
    tick();
    const id = setInterval(tick, 4000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const hasFilters =
    !!filters.media_type ||
    filters.is_duplicate !== undefined ||
    filters.is_blurry !== undefined ||
    filters.trash === true;

  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b border-[var(--border)] bg-[var(--bg-base)] px-4">
      <div className="relative flex flex-1 items-center">
        <Search className="pointer-events-none absolute left-2.5 h-3.5 w-3.5 text-[var(--text-muted)]" />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search captions, tags, filenames…"
          className="h-8 w-full max-w-xl rounded-md border border-[var(--border)] bg-[var(--bg-elevated)] pl-8 pr-3 text-[13px] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:border-[var(--border-strong)] focus:outline-none"
        />
      </div>

      <div className="flex items-center gap-1.5">
        <FilterChip
          active={filters.media_type === "image"}
          onClick={() =>
            setFilter("media_type", filters.media_type === "image" ? undefined : "image")
          }
        >
          Photos
        </FilterChip>
        <FilterChip
          active={filters.media_type === "video"}
          onClick={() =>
            setFilter("media_type", filters.media_type === "video" ? undefined : "video")
          }
        >
          Video
        </FilterChip>
        <FilterChip
          active={filters.is_duplicate === true}
          onClick={() =>
            setFilter("is_duplicate", filters.is_duplicate === true ? undefined : true)
          }
        >
          Duplicates
        </FilterChip>
        <FilterChip
          active={filters.is_blurry === true}
          onClick={() =>
            setFilter("is_blurry", filters.is_blurry === true ? undefined : true)
          }
        >
          Blurry
        </FilterChip>
        <FilterChip
          active={filters.trash === true}
          onClick={() =>
            setFilter("trash", filters.trash === true ? undefined : true)
          }
        >
          Trash
        </FilterChip>
        {hasFilters && (
          <button
            type="button"
            onClick={clearFilters}
            className="px-2 text-[11px] text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
          >
            Clear
          </button>
        )}
      </div>

      <div className="flex items-center gap-1 rounded-md border border-[var(--border)] p-0.5">
        {(["small", "medium", "large"] as const).map((d) => (
          <button
            key={d}
            onClick={() => setDensity(d)}
            title={`Density: ${d}`}
            className={cn(
              "rounded px-1.5 py-1 text-[11px] capitalize",
              density === d
                ? "bg-[var(--bg-hover)] text-[var(--text-primary)]"
                : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]",
            )}
          >
            {d[0].toUpperCase()}
          </button>
        ))}
        <Columns3 className="mx-1 h-3.5 w-3.5 text-[var(--text-muted)]" />
      </div>

      <button
        type="button"
        onClick={() => expandImport()}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[12px] font-medium text-white",
          importMinimized || importOpen
            ? "bg-[var(--accent)] ring-2 ring-[var(--accent)]/40 hover:bg-[var(--accent-hover)]"
            : "bg-[var(--accent)] hover:bg-[var(--accent-hover)]",
        )}
        title={
          importMinimized
            ? "Expand import dialog"
            : importOpen
              ? "Import dialog is open"
              : "Import media"
        }
      >
        <HardDriveDownload className="h-3.5 w-3.5" strokeWidth={1.75} />
        {importMinimized ? "Import · expand" : "Import"}
      </button>
      {importMinimized && !importActive && (
        <button
          type="button"
          onClick={() => expandImport()}
          className="hidden items-center gap-1.5 rounded-full border border-[var(--accent)]/40 bg-[var(--accent)]/10 px-2.5 py-1 text-[11px] text-[var(--accent)] hover:bg-[var(--accent)]/20 sm:inline-flex"
        >
          Import docked · click to open
        </button>
      )}
      {importActive && (
        <span className="hidden items-center gap-1.5 rounded-full border border-[var(--accent)]/40 bg-[var(--accent)]/10 px-2.5 py-1 text-[11px] text-[var(--accent)] sm:inline-flex">
          <Loader2 className="h-3 w-3 animate-spin" />
          Importing · {livePromoted} in library
        </span>
      )}

      <button
        type="button"
        onClick={() => setJobsOpen(true)}
        className="flex items-center gap-1.5 rounded-md border border-[var(--border)] px-2.5 py-1.5 text-[12px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
      >
        {jobHint ? (
          <>
            <Loader2 className="h-3.5 w-3.5 animate-spin text-[var(--accent)]" />
            <span className="max-w-[180px] truncate">{jobHint}</span>
          </>
        ) : (
          <span>Jobs idle</span>
        )}
      </button>
    </header>
  );
}

function FilterChip({
  children,
  active,
  onClick,
}: {
  children: React.ReactNode;
  active?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "rounded-full border px-2.5 py-1 text-[11px] transition-colors",
        active
          ? "border-[var(--accent)] bg-[var(--bg-selected)] text-[var(--text-primary)]"
          : "border-[var(--border)] text-[var(--text-muted)] hover:border-[var(--border-strong)] hover:text-[var(--text-secondary)]",
      )}
    >
      {children}
    </button>
  );
}
