"use client";

import { useEffect, useState } from "react";
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
  Minus,
  Maximize2,
} from "lucide-react";

/**
 * Docked live import status — stays visible after the import modal closes
 * so the main library can show newly classified images as they arrive.
 * Collapses to a slim pill so the rest of the UI stays free.
 */
export function ImportLivePanel() {
  const liveImports = useAppStore((s) => s.liveImports);
  const updateLiveImport = useAppStore((s) => s.updateLiveImport);
  const dismissLiveImport = useAppStore((s) => s.dismissLiveImport);
  const bumpLibrary = useAppStore((s) => s.bumpLibrary);
  const expandImport = useAppStore((s) => s.expandImport);
  const [collapsed, setCollapsed] = useState(false);
  const [processHint, setProcessHint] = useState<string | null>(null);

  const visible = liveImports.filter((j) => !j.dismissed);
  const terminal = (s?: string | null) =>
    s === "completed" || s === "failed" || s === "cancelled";
  const active = visible.filter((j) => !j.status || !terminal(j.status.status));

  // Poll copy jobs + background process status
  useEffect(() => {
    let cancelled = false;

    const tick = async () => {
      const liveJobs = useAppStore.getState().liveImports.filter((j) => !j.dismissed);
      const anyActive = liveJobs.some(
        (j) => !j.status || !terminal(j.status.status),
      );
      try {
        for (const job of liveJobs) {
          if (job.status && terminal(job.status.status)) continue;
          try {
            const s = await api.importStatus(job.jobId);
            if (!cancelled) updateLiveImport(job.jobId, s);
          } catch {
            /* job may only be in /live */
          }
        }
        try {
          const live = await api.importLive();
          if (!cancelled) {
            for (const s of live) {
              const known = useAppStore
                .getState()
                .liveImports.some((j) => j.jobId === s.job_id);
              if (!known && !terminal(s.status)) {
                useAppStore.getState().trackImport(s.job_id, "Import");
              }
              updateLiveImport(s.job_id, s);
            }
          }
        } catch {
          /* offline */
        }

        let processBusy = false;
        try {
          const ps = await api.processStatus();
          processBusy = ps.pending > 0 || ps.status === "running";
          if (!cancelled) {
            if (processBusy) {
              setProcessHint(
                `Background process: ${ps.pending} in staging · ${ps.last_message || ps.status}`,
              );
              if (ps.promoted_session > 0) bumpLibrary();
            } else {
              setProcessHint(null);
            }
          }
        } catch {
          /* */
        }

        if (!cancelled) {
          setTimeout(tick, anyActive || processBusy ? 900 : 5000);
        }
      } catch {
        if (!cancelled) setTimeout(tick, 5000);
      }
    };

    tick();
    return () => {
      cancelled = true;
    };
  }, [updateLiveImport, bumpLibrary]);

  if (visible.length === 0 && !processHint) return null;

  const primary = visible[0];
  const primaryStatus = primary?.status;
  const anyRunning = active.length > 0;
  const totalPromoted = visible.reduce((n, j) => n + (j.status?.promoted ?? 0), 0);

  // Slim pill — free UI while import continues in background
  if (collapsed) {
    return (
      <div className="pointer-events-none fixed bottom-4 right-4 z-40">
        <button
          type="button"
          onClick={() => setCollapsed(false)}
          className="pointer-events-auto flex max-w-[min(100vw-2rem,340px)] items-center gap-2 rounded-xl border border-[var(--accent)]/40 bg-[var(--bg-elevated)]/95 px-3 py-2.5 shadow-2xl backdrop-blur-md hover:border-[var(--accent)] hover:bg-[var(--bg-selected)]"
          title="Expand import progress"
        >
          {anyRunning ? (
            <Loader2 className="h-4 w-4 shrink-0 animate-spin text-[var(--accent)]" />
          ) : primaryStatus?.status === "failed" ? (
            <AlertCircle className="h-4 w-4 shrink-0 text-[var(--danger)]" />
          ) : (
            <CheckCircle2 className="h-4 w-4 shrink-0 text-[var(--success)]" />
          )}
          <span className="min-w-0 flex-1 text-left">
            <span className="block truncate text-[12px] font-medium">
              {anyRunning
                ? primaryStatus?.phase === "copying"
                  ? "Copying"
                  : "Importing"
                : primaryStatus?.disc_ready
                  ? "Disc ready"
                  : primaryStatus?.status || "Import"}{" "}
              · {totalPromoted} promoted
            </span>
            <span className="block truncate text-[10px] text-[var(--text-muted)]">
              {processHint || primary?.label}
              {visible.length > 1 ? ` · +${visible.length - 1} more` : ""}
              {" · expand"}
            </span>
          </span>
          <Maximize2 className="h-3.5 w-3.5 shrink-0 text-[var(--accent)]" />
        </button>
      </div>
    );
  }

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-40 flex w-[min(100vw-2rem,360px)] flex-col gap-2">
      {processHint && visible.length === 0 && (
        <div className="pointer-events-auto rounded-xl border border-[var(--border)] bg-[var(--bg-elevated)]/95 px-3 py-2.5 text-[11px] text-[var(--text-secondary)] shadow-2xl backdrop-blur-md">
          <div className="flex items-center gap-2 font-medium text-[var(--text-primary)]">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-[var(--accent)]" />
            Staging processor
          </div>
          <p className="mt-1 text-[10px] text-[var(--text-muted)]">{processHint}</p>
        </div>
      )}
      {visible.map((job) => {
        const s = job.status;
        const running = !s || !terminal(s.status);
        const copyDone = Boolean(s?.disc_ready) || s?.phase === "copied";
        const pct =
          s && s.total > 0
            ? Math.round(
                (((s.copy_only ? s.copied : s.promoted + s.rejected) || 0) / s.total) *
                  100,
              )
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
                      : s?.phase === "copying"
                        ? "Copying to staging · process is separate"
                        : "Live import"
                    : copyDone || s?.disc_ready
                      ? "Copy done — eject / next disc OK"
                      : s?.status}
                </div>
              </div>
              <button
                type="button"
                onClick={() => setCollapsed(true)}
                className="rounded p-1 text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
                aria-label="Collapse progress panel"
                title="Collapse — free UI"
              >
                <Minus className="h-3.5 w-3.5" />
              </button>
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
                      <div className="text-[var(--text-muted)]">Copied</div>
                      <div className="font-mono text-[12px] text-[var(--text-primary)]">
                        {s.copied}
                      </div>
                    </div>
                    <div>
                      <div>Promoted</div>
                      <div className="font-mono text-[12px] text-[var(--success)]">
                        {s.promoted}
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
                  {(copyDone || s.disc_ready) && (
                    <div className="rounded-md border border-[var(--success)]/30 bg-[var(--success)]/10 px-2 py-1.5 text-[10px] text-[var(--success)]">
                      Copy finished — disc is free to eject.
                    </div>
                  )}
                  {processHint && (
                    <div className="text-[10px] text-[var(--text-muted)]">{processHint}</div>
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

              <div className="flex flex-wrap gap-2 pt-0.5">
                {!running && (copyDone || s?.disc_ready) && (
                  <>
                    <button
                      type="button"
                      onClick={() => useAppStore.getState().continueNextDisc()}
                      className="inline-flex flex-1 items-center justify-center rounded-md bg-[var(--accent)] px-2 py-1.5 text-[11px] font-medium text-white hover:bg-[var(--accent-hover)]"
                    >
                      Next disc
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        const st = useAppStore.getState();
                        if (st.discReadyPrompt?.jobId === job.jobId) {
                          st.finishDiscSession();
                        } else {
                          dismissLiveImport(job.jobId);
                          bumpLibrary();
                        }
                      }}
                      className="inline-flex flex-1 items-center justify-center rounded-md border border-[var(--border)] px-2 py-1.5 text-[11px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
                    >
                      Finished
                    </button>
                  </>
                )}
                {running && (
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        const force = Boolean(s?.cancel_requested);
                        await api.cancelJob(job.jobId, { force });
                        const st = await api.importStatus(job.jobId);
                        updateLiveImport(job.jobId, st);
                      } catch {
                        try {
                          await api.cancelJob(job.jobId, { force: true });
                          const st = await api.importStatus(job.jobId);
                          updateLiveImport(job.jobId, st);
                        } catch {
                          /* may finish race */
                        }
                      }
                    }}
                    className="inline-flex flex-1 items-center justify-center rounded-md border border-[var(--danger)]/40 px-2 py-1.5 text-[11px] text-[var(--danger)] hover:bg-[var(--danger)]/10"
                  >
                    {s?.cancel_requested ? "Force cancel" : "Cancel job"}
                  </button>
                )}
                {!running && !(copyDone || s?.disc_ready) && (
                  <button
                    type="button"
                    onClick={() => expandImport()}
                    className="inline-flex flex-1 items-center justify-center gap-1 rounded-md border border-[var(--border)] px-2 py-1.5 text-[11px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
                    title="Open import dialog (another disc)"
                  >
                    Import more
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
                    href="/inference"
                    className="inline-flex flex-1 items-center justify-center gap-1 rounded-md bg-[var(--accent)]/15 px-2 py-1.5 text-[11px] text-[var(--accent)] hover:bg-[var(--accent)]/25"
                  >
                    Inference
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
