"use client";

import { useEffect, useMemo, useState } from "react";
import { Square, AlertTriangle, Eraser, Play } from "lucide-react";
import { api, type Job } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/lib/store";

function isActive(status: string) {
  return status === "running" || status === "queued";
}

function isResumable(j: Job) {
  return (
    (j.job_type === "import" || j.job_type === "post_ingest") &&
    ["interrupted", "failed", "cancelled"].includes(j.status)
  );
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [cancelling, setCancelling] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [reaping, setReaping] = useState(false);
  const [resuming, setResuming] = useState<Set<string>>(new Set());
  const trackImport = useAppStore((s) => s.trackImport);

  const refresh = () =>
    api
      .jobs()
      .then(setJobs)
      .catch(() => {});

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 1500);
    return () => clearInterval(id);
  }, []);

  const staleCount = useMemo(
    () => jobs.filter((j) => j.stale || (isActive(j.status) && j.has_live_worker === false)).length,
    [jobs],
  );

  async function cancel(jobId: string) {
    setError(null);
    setCancelling((s) => new Set(s).add(jobId));
    try {
      await api.cancelJob(jobId);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Cancel failed");
    } finally {
      setCancelling((s) => {
        const n = new Set(s);
        n.delete(jobId);
        return n;
      });
    }
  }

  async function resume(job: Job) {
    setError(null);
    setMsg(null);
    setResuming((s) => new Set(s).add(job.id));
    try {
      const res = await api.resumeJob(job.id);
      setMsg(res.message || "Resume started");
      if (job.job_type === "import") {
        trackImport(res.job_id, `Resume ${job.job_type}`);
      }
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Resume failed");
    } finally {
      setResuming((s) => {
        const n = new Set(s);
        n.delete(job.id);
        return n;
      });
    }
  }

  async function reapStale(force = false) {
    setReaping(true);
    setError(null);
    setMsg(null);
    try {
      const res = await api.reapStaleJobs(force);
      setMsg(
        res.count
          ? `Closed ${res.count} stale job${res.count === 1 ? "" : "s"} as interrupted`
          : "No stale jobs found",
      );
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Reap failed");
    } finally {
      setReaping(false);
    }
  }

  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-[16px] font-semibold">Background jobs</h1>
          <p className="mt-0.5 text-[12px] text-[var(--text-muted)]">
            In-process workers · cancel stops between files · restart marks orphans as interrupted
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {staleCount > 0 && (
            <button
              type="button"
              disabled={reaping}
              onClick={() => void reapStale(false)}
              className="inline-flex items-center gap-1.5 rounded-md border border-[var(--warning)]/50 bg-[var(--warning)]/10 px-2.5 py-1.5 text-[11px] font-medium text-[var(--warning)] hover:bg-[var(--warning)]/20 disabled:opacity-40"
            >
              <AlertTriangle className="h-3.5 w-3.5" />
              {reaping ? "Cleaning…" : `Clear ${staleCount} stale`}
            </button>
          )}
          <button
            type="button"
            disabled={reaping}
            onClick={() => void reapStale(true)}
            className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] px-2.5 py-1.5 text-[11px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] disabled:opacity-40"
            title="Close every queued/running job that has no live worker (same as Clear stale)"
          >
            <Eraser className="h-3.5 w-3.5" />
            Reap orphans
          </button>
        </div>
      </div>

      {staleCount > 0 && (
        <div className="mb-3 rounded-md border border-[var(--warning)]/40 bg-[var(--warning)]/10 px-3 py-2 text-[12px] text-[var(--warning)]">
          {staleCount} job{staleCount === 1 ? "" : "s"} still marked running/queued but no worker
          is attached (usually after API restart). Safe to clear — already-promoted media stays in
          the library.
        </div>
      )}
      {msg && (
        <p className="mb-3 text-[12px] text-[var(--success)]">
          {msg}{" "}
          <button type="button" className="underline opacity-80" onClick={() => setMsg(null)}>
            dismiss
          </button>
        </p>
      )}
      {error && <p className="mb-3 text-[12px] text-[var(--danger)]">{error}</p>}
      {jobs.length === 0 && (
        <p className="text-[var(--text-muted)]">No jobs yet.</p>
      )}
      <div className="space-y-2">
        {jobs.map((j) => {
          const active = isActive(j.status);
          const stale = Boolean(j.stale);
          const busy = cancelling.has(j.id);
          return (
            <div
              key={j.id}
              className={cn(
                "rounded-lg border bg-[var(--bg-elevated)] p-3",
                stale
                  ? "border-[var(--warning)]/50"
                  : "border-[var(--border)]",
              )}
            >
              <div className="flex items-center justify-between gap-2 text-[13px]">
                <span className="font-medium">
                  {j.job_type}
                  {stale && (
                    <span className="ml-2 rounded bg-[var(--warning)]/20 px-1.5 py-0.5 text-[10px] font-medium uppercase text-[var(--warning)]">
                      stale
                    </span>
                  )}
                </span>
                <div className="flex items-center gap-2">
                  <Status status={j.status} />
                  {isResumable(j) && (
                    <button
                      type="button"
                      disabled={resuming.has(j.id)}
                      onClick={() => void resume(j)}
                      className="inline-flex items-center gap-1 rounded-md border border-[var(--success)]/40 px-2 py-1 text-[11px] text-[var(--success)] hover:bg-[var(--success)]/10 disabled:opacity-40"
                      title="Drain staging + re-scan sources, skip files already imported"
                    >
                      <Play className="h-3 w-3 fill-current" />
                      {resuming.has(j.id) ? "…" : "Resume"}
                    </button>
                  )}
                  {(active || stale) && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void cancel(j.id)}
                      className="inline-flex items-center gap-1 rounded-md border border-[var(--danger)]/40 px-2 py-1 text-[11px] text-[var(--danger)] hover:bg-[var(--danger)]/10 disabled:opacity-40"
                    >
                      <Square className="h-3 w-3 fill-current" />
                      {busy ? "…" : stale ? "Close" : "Cancel"}
                    </button>
                  )}
                </div>
              </div>
              <p className="mt-1 text-[12px] text-[var(--text-secondary)]">
                {j.message || "—"}
              </p>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[var(--bg-hover)]">
                <div
                  className={cn(
                    "h-full rounded-full transition-all",
                    j.status === "cancelled" || j.status === "interrupted"
                      ? "bg-[var(--warning)]"
                      : j.status === "failed"
                        ? "bg-[var(--danger)]"
                        : "bg-[var(--accent)]",
                  )}
                  style={{ width: `${Math.round((j.progress || 0) * 100)}%` }}
                />
              </div>
              <div className="mt-1 font-mono text-[11px] text-[var(--text-muted)]">
                {j.completed}/{j.total}
                {j.has_live_worker === true && (
                  <span className="ml-2 text-[var(--accent)]">live worker</span>
                )}
                {j.error && (
                  <span className="ml-2 text-[var(--danger)]">{j.error}</span>
                )}
                <span className="ml-2 opacity-50">{j.id.slice(0, 8)}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Status({ status }: { status: string }) {
  const color =
    status === "completed"
      ? "text-[var(--success)]"
      : status === "failed"
        ? "text-[var(--danger)]"
        : status === "cancelled" || status === "interrupted"
          ? "text-[var(--warning)]"
          : status === "running"
            ? "text-[var(--accent)]"
            : "text-[var(--text-muted)]";
  return (
    <span className={cn("text-[11px] uppercase tracking-wide", color)}>
      {status}
    </span>
  );
}
