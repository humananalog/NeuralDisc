"use client";

import { useEffect } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { cn, formatBytes } from "@/lib/utils";
import {
  Loader2,
  X,
  CheckCircle2,
  AlertCircle,
  Disc3,
  ChevronRight,
} from "lucide-react";

/**
 * Docked live import status — stays visible after the import modal closes
 * so the main library can show newly classified images as they arrive.
 */
export function ImportLivePanel() {
  const liveImports = useAppStore((s) => s.liveImports);
  const updateLiveImport = useAppStore((s) => s.updateLiveImport);
  const dismissLiveImport = useAppStore((s) => s.dismissLiveImport);
  const setPendingReview = useAppStore((s) => s.setPendingReview);
  const bumpLibrary = useAppStore((s) => s.bumpLibrary);

  const visible = liveImports.filter((j) => !j.dismissed);
  const terminal = (s?: string | null) =>
    s === "completed" || s === "failed" || s === "cancelled";
  const active = visible.filter((j) => !j.status || !terminal(j.status.status));

  // Poll active jobs + hydrate from /api/import/live
  useEffect(() => {
    if (visible.length === 0) return;
    let cancelled = false;

    const tick = async () => {
      try {
        // Prefer tracked job ids
        for (const job of visible) {
          if (job.status && terminal(job.status.status)) {
            continue;
          }
          try {
            const s = await api.importStatus(job.jobId);
            if (!cancelled) updateLiveImport(job.jobId, s);
          } catch {
            /* job may only be in /live */
          }
        }
        // Also pick up any live jobs we didn't track (e.g. after refresh)
        try {
          const live = await api.importLive();
          if (!cancelled) {
            for (const s of live) {
              const known = useAppStore.getState().liveImports.some((j) => j.jobId === s.job_id);
              if (!known && !terminal(s.status)) {
                useAppStore.getState().trackImport(s.job_id, "Import");
              }
              updateLiveImport(s.job_id, s);
            }
          }
        } catch {
          /* offline */
        }

        try {
          const { pending } = await api.hitlCount();
          if (!cancelled) setPendingReview(pending);
        } catch {
          /* */
        }
      } finally {
        if (!cancelled && active.length > 0) {
          setTimeout(tick, 900);
        }
      }
    };

    tick();
    return () => {
      cancelled = true;
    };
  }, [
    // re-run when set of job ids / running state changes
    visible.map((j) => j.jobId).join(","),
    active.length,
    updateLiveImport,
    setPendingReview,
  ]);

  if (visible.length === 0) return null;

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-40 flex w-[min(100vw-2rem,360px)] flex-col gap-2">
      {visible.map((job) => {
        const s = job.status;
        const running = !s || !terminal(s.status);
        const pct =
          s && s.total > 0
            ? Math.round(((s.promoted + s.rejected) / s.total) * 100)
            : s?.status === "completed"
              ? 100
              : 0;

        return (
          <div
            key={job.jobId}
            className="pointer-events-auto overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--bg-elevated)]/95 shadow-2xl backdrop-blur-md"
          >
            <div className="flex items-start gap-2 border-b border-[var(--border)] px-3 py-2">
              <div className="mt-0.5 text-[var(--accent)]">
                {running ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : s?.status === "failed" ? (
                  <AlertCircle className="h-4 w-4 text-[var(--danger)]" />
                ) : s?.status === "cancelled" ? (
                  <AlertCircle className="h-4 w-4 text-[var(--warning)]" />
                ) : (
                  <CheckCircle2 className="h-4 w-4 text-[var(--success)]" />
                )}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5 text-[12px] font-medium">
                  <Disc3 className="h-3.5 w-3.5 shrink-0 text-[var(--text-muted)]" />
                  <span className="truncate">{job.label}</span>
                </div>
                <div className="text-[10px] text-[var(--text-muted)]">
                  {running
                    ? s?.cancel_requested
                      ? "Cancelling…"
                      : "Live import · library updates as files classify"
                    : s?.status}
                </div>
              </div>
              <button
                type="button"
                onClick={() => {
                  dismissLiveImport(job.jobId);
                  bumpLibrary();
                }}
                className="rounded p-1 text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
                aria-label="Dismiss"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>

            <div className="space-y-2 px-3 py-2.5">
              {s ? (
                <>
                  <div className="h-1.5 overflow-hidden rounded-full bg-[var(--bg-hover)]">
                    <div
                      className={cn(
                        "h-full rounded-full transition-all duration-300",
                        s.status === "failed" ? "bg-[var(--danger)]" : "bg-[var(--accent)]",
                      )}
                      style={{ width: `${Math.max(pct, running ? 2 : 0)}%` }}
                    />
                  </div>
                  <p className="line-clamp-2 text-[11px] text-[var(--text-secondary)]">
                    {s.message || s.phase}
                  </p>
                  <div className="grid grid-cols-3 gap-1 text-[10px] text-[var(--text-muted)]">
                    <div>
                      <div className="text-[var(--text-muted)]">In library</div>
                      <div className="font-mono text-[12px] text-[var(--success)]">
                        {s.promoted}
                      </div>
                    </div>
                    <div>
                      <div>Rejected</div>
                      <div className="font-mono text-[12px] text-[var(--warning)]">
                        {s.rejected}
                      </div>
                    </div>
                    <div>
                      <div>Rate</div>
                      <div className="font-mono text-[12px] text-[var(--text-primary)]">
                        ~{Math.round(s.items_per_hour)}/h
                      </div>
                    </div>
                  </div>
                  {s.bytes_copied > 0 && (
                    <div className="text-[10px] text-[var(--text-muted)]">
                      {formatBytes(s.bytes_copied)} copied · {s.copied}/{s.total} files
                    </div>
                  )}
                  {s.staging_dir && (
                    <div className="truncate font-mono text-[9px] text-[var(--text-muted)]" title={s.staging_dir}>
                      temp → {s.staging_dir}
                    </div>
                  )}
                </>
              ) : (
                <p className="text-[11px] text-[var(--text-muted)]">Starting…</p>
              )}

              <div className="flex gap-2 pt-0.5">
                {running && (
                  <button
                    type="button"
                    disabled={!!s?.cancel_requested}
                    onClick={async () => {
                      try {
                        await api.cancelJob(job.jobId);
                        const st = await api.importStatus(job.jobId);
                        updateLiveImport(job.jobId, st);
                      } catch {
                        /* may finish race */
                      }
                    }}
                    className="inline-flex flex-1 items-center justify-center rounded-md border border-[var(--danger)]/40 px-2 py-1.5 text-[11px] text-[var(--danger)] hover:bg-[var(--danger)]/10 disabled:opacity-50"
                  >
                    {s?.cancel_requested ? "Cancelling…" : "Cancel job"}
                  </button>
                )}
                <Link
                  href="/library"
                  onClick={() => bumpLibrary()}
                  className="inline-flex flex-1 items-center justify-center gap-1 rounded-md border border-[var(--border)] px-2 py-1.5 text-[11px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
                >
                  Library
                  <ChevronRight className="h-3 w-3" />
                </Link>
                {!running && (
                  <Link
                    href="/review"
                    className="inline-flex flex-1 items-center justify-center gap-1 rounded-md bg-[var(--accent)]/15 px-2 py-1.5 text-[11px] text-[var(--accent)] hover:bg-[var(--accent)]/25"
                  >
                    Review queue
                    <ChevronRight className="h-3 w-3" />
                  </Link>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
