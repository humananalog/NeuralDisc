"use client";

import { useEffect, useState } from "react";
import { Square } from "lucide-react";
import { api, type Job } from "@/lib/api";
import { cn } from "@/lib/utils";

function isActive(status: string) {
  return status === "running" || status === "queued";
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [cancelling, setCancelling] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const tick = () =>
      api
        .jobs()
        .then(setJobs)
        .catch(() => {});
    tick();
    const id = setInterval(tick, 1500);
    return () => clearInterval(id);
  }, []);

  async function cancel(jobId: string) {
    setError(null);
    setCancelling((s) => new Set(s).add(jobId));
    try {
      await api.cancelJob(jobId);
      const next = await api.jobs();
      setJobs(next);
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

  return (
    <div className="h-full overflow-y-auto p-4">
      <h1 className="mb-1 text-[16px] font-semibold">Background jobs</h1>
      <p className="mb-4 text-[12px] text-[var(--text-muted)]">
        Running imports and processing — cancel stops work between files
      </p>
      {error && (
        <p className="mb-3 text-[12px] text-[var(--danger)]">{error}</p>
      )}
      {jobs.length === 0 && (
        <p className="text-[var(--text-muted)]">No jobs yet.</p>
      )}
      <div className="space-y-2">
        {jobs.map((j) => {
          const active = isActive(j.status);
          const busy = cancelling.has(j.id);
          return (
            <div
              key={j.id}
              className="rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)] p-3"
            >
              <div className="flex items-center justify-between gap-2 text-[13px]">
                <span className="font-medium">{j.job_type}</span>
                <div className="flex items-center gap-2">
                  <Status status={j.status} />
                  {active && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void cancel(j.id)}
                      className="inline-flex items-center gap-1 rounded-md border border-[var(--danger)]/40 px-2 py-1 text-[11px] text-[var(--danger)] hover:bg-[var(--danger)]/10 disabled:opacity-40"
                    >
                      <Square className="h-3 w-3 fill-current" />
                      {busy ? "Cancelling…" : "Cancel"}
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
                    j.status === "cancelled"
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
        : status === "cancelled"
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
