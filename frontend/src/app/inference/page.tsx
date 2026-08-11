"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Brain,
  Play,
  RefreshCw,
  Sparkles,
  AlertCircle,
  CheckCircle2,
} from "lucide-react";
import { api, type MediaItem } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/lib/store";
import Link from "next/link";

type InfStatus = {
  vlm_enabled: boolean;
  vlm_model: string;
  total_library: number;
  with_analysis: number;
  pending: number;
  heuristic: number;
  vlm_done: number;
  queue: number;
  coverage_pct: number;
  vlm_pct: number;
  vlm_loaded?: boolean;
  vlm_refcount?: number;
  metal?: {
    available?: boolean;
    active_bytes?: number;
    cache_bytes?: number;
    peak_bytes?: number;
  };
  active_job: {
    id: string;
    status: string;
    progress: number;
    completed: number;
    total: number;
    message?: string | null;
  } | null;
};

type QueueItem = MediaItem & { inference_state: string };

export default function InferencePage() {
  const [status, setStatus] = useState<InfStatus | null>(null);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [queueTotal, setQueueTotal] = useState(0);
  const [mode, setMode] = useState<"all" | "pending" | "heuristic">("all");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runningId, setRunningId] = useState<string | null>(null);
  const [releasing, setReleasing] = useState(false);
  const setNavCounts = useAppStore((s) => s.setNavCounts);

  const load = useCallback(async () => {
    try {
      const [st, q] = await Promise.all([
        api.inferenceStatus(),
        api.inferenceQueue(mode, 60),
      ]);
      setStatus(st);
      setQueue(q.items as QueueItem[]);
      setQueueTotal(q.total);
      if (st.active_job) setRunningId(st.active_job.id);
      try {
        setNavCounts(await api.navCounts());
      } catch {
        /* */
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load inference status");
    }
  }, [mode, setNavCounts]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!runningId && !status?.active_job) return;
    const id = setInterval(() => void load(), 2000);
    return () => clearInterval(id);
  }, [runningId, status?.active_job, load]);

  async function runBatch() {
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      // Prefer full requeue of all heuristic / failed-VLM items
      const res = await api.requeueHeuristic(500);
      setMsg(res.message);
      if (res.job_id) setRunningId(res.job_id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start inference");
    } finally {
      setBusy(false);
    }
  }

  async function reanalyse(id: string) {
    setBusy(true);
    setError(null);
    try {
      const res = await api.reanalyseMedia(id);
      setMsg(
        res.ok
          ? `Re-analysed · model ${res.model_name || "?"}${
              res.vlm_released ? " · MLX released" : ""
            }`
          : "Re-analyse returned empty",
      );
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Re-analyse failed");
    } finally {
      setBusy(false);
    }
  }

  async function releaseMlx() {
    setReleasing(true);
    setError(null);
    try {
      const res = await api.releaseInference();
      const mb = (n?: number | null) =>
        n != null ? `${(n / (1024 * 1024)).toFixed(0)} MB` : "?";
      setMsg(
        res.released
          ? `MLX released · models cleared · Metal ${mb(res.metal_active_before)} → ${mb(res.metal_active_after)}`
          : `MLX still in use (refcount ${res.refcount ?? "?"})`,
      );
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Release failed");
    } finally {
      setReleasing(false);
    }
  }

  const st = status;
  const job = st?.active_job;

  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-[16px] font-semibold">
            <Brain className="h-5 w-5 text-[var(--ai)]" />
            Inference
          </h1>
          <p className="mt-0.5 text-[12px] text-[var(--text-muted)]">
            VLM / analysis coverage, queue, and batch re-run
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => void load()}
            className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] px-2.5 py-1.5 text-[11px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", busy && "animate-spin")} />
            Refresh
          </button>
          <button
            type="button"
            disabled={releasing || busy}
            onClick={() => void releaseMlx()}
            title="Unload VLM and clear Metal cache so other apps (e.g. mlx_lm :8088) can use MLX"
            className="inline-flex items-center gap-1.5 rounded-md border border-[var(--warning)]/40 px-2.5 py-1.5 text-[11px] text-[var(--warning)] hover:bg-[var(--warning)]/10 disabled:opacity-40"
          >
            {releasing ? "Releasing…" : "Release MLX"}
          </button>
          <button
            type="button"
            disabled={busy || (st?.queue ?? 0) === 0}
            onClick={() => void runBatch()}
            className="inline-flex items-center gap-1.5 rounded-md bg-[var(--ai)] px-3 py-1.5 text-[12px] font-medium text-white hover:opacity-90 disabled:opacity-40"
          >
            <Play className="h-3.5 w-3.5" />
            {busy ? "Starting…" : "Re-queue all heuristics"}
          </button>
        </div>
      </div>

      {msg && (
        <div className="mb-3 rounded-md border border-[var(--success)]/40 bg-[var(--success)]/10 px-3 py-2 text-[12px] text-[var(--success)]">
          {msg}
        </div>
      )}
      {error && (
        <div className="mb-3 rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-3 py-2 text-[12px] text-[var(--danger)]">
          {error}
        </div>
      )}

      {/* Status cards */}
      <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Library" value={st?.total_library ?? "—"} />
        <Stat label="Analysed" value={st?.with_analysis ?? "—"} tone="success" />
        <Stat label="Pending" value={st?.pending ?? "—"} tone="warning" />
        <Stat label="Heuristic" value={st?.heuristic ?? "—"} />
        <Stat label="VLM done" value={st?.vlm_done ?? "—"} tone="ai" />
        <Stat label="Queue" value={st?.queue ?? "—"} tone="accent" />
      </div>

      <div className="mb-4 grid gap-3 md:grid-cols-2">
        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)] p-3">
          <div className="mb-2 text-[11px] font-medium uppercase tracking-wider text-[var(--text-muted)]">
            Model
          </div>
          <div className="flex items-center gap-2 text-[13px]">
            {st?.vlm_enabled ? (
              <CheckCircle2 className="h-4 w-4 text-[var(--success)]" />
            ) : (
              <AlertCircle className="h-4 w-4 text-[var(--warning)]" />
            )}
            <span>
              VLM {st?.vlm_enabled ? "enabled" : "disabled"} ·{" "}
              <span className="font-mono text-[11px] text-[var(--text-secondary)]">
                {st?.vlm_model || "—"}
              </span>
            </span>
          </div>
          <p className="mt-2 text-[11px] text-[var(--text-muted)]">
            Coverage {st?.coverage_pct ?? 0}% analysed · {st?.vlm_pct ?? 0}% real VLM
            {!st?.vlm_enabled && " · enable VLM in Settings for full inference"}
          </p>
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            Model{" "}
            <span className={st?.vlm_loaded ? "text-[var(--warning)]" : "text-[var(--success)]"}>
              {st?.vlm_loaded ? "loaded in process" : "unloaded"}
            </span>
            {st?.metal?.active_bytes != null && (
              <>
                {" "}
                · Metal active{" "}
                {(st.metal.active_bytes / (1024 * 1024)).toFixed(0)} MB
              </>
            )}
            {" · free after jobs for :8088 / other apps"}
          </p>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[var(--bg-hover)]">
            <div
              className="h-full rounded-full bg-[var(--ai)] transition-all"
              style={{ width: `${Math.min(100, st?.vlm_pct ?? 0)}%` }}
            />
          </div>
        </div>

        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)] p-3">
          <div className="mb-2 text-[11px] font-medium uppercase tracking-wider text-[var(--text-muted)]">
            Active inference job
          </div>
          {job ? (
            <>
              <div className="text-[13px] text-[var(--text-primary)]">
                {job.status} · {job.completed}/{job.total}
              </div>
              <p className="mt-1 text-[12px] text-[var(--text-secondary)]">
                {job.message || "—"}
              </p>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[var(--bg-hover)]">
                <div
                  className="h-full rounded-full bg-[var(--accent)] transition-all"
                  style={{ width: `${Math.round((job.progress || 0) * 100)}%` }}
                />
              </div>
              <Link
                href="/jobs"
                className="mt-2 inline-block text-[11px] text-[var(--accent)] hover:underline"
              >
                Open Jobs →
              </Link>
            </>
          ) : (
            <p className="text-[12px] text-[var(--text-muted)]">No inference job running</p>
          )}
        </div>
      </div>

      {/* Queue */}
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-[13px] font-semibold">
          Queue{" "}
          <span className="font-normal text-[var(--text-muted)]">
            ({queueTotal} matching)
          </span>
        </h2>
        <div className="flex rounded-md border border-[var(--border)] p-0.5 text-[11px]">
          {(
            [
              ["all", "All open"],
              ["pending", "No analysis"],
              ["heuristic", "Heuristic only"],
            ] as const
          ).map(([k, label]) => (
            <button
              key={k}
              type="button"
              onClick={() => setMode(k)}
              className={cn(
                "rounded px-2.5 py-1",
                mode === k
                  ? "bg-[var(--bg-selected)] text-[var(--text-primary)]"
                  : "text-[var(--text-muted)]",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {queue.length === 0 ? (
        <p className="py-8 text-center text-[12px] text-[var(--text-muted)]">
          Queue empty for this filter.
        </p>
      ) : (
        <div className="space-y-1.5">
          {queue.map((m) => (
            <div
              key={m.id}
              className="flex items-center gap-3 rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)] px-2 py-1.5"
            >
              <div className="h-12 w-12 shrink-0 overflow-hidden rounded bg-[var(--bg-hover)]">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={m.thumb_url || `/api/media/${m.id}/thumb`}
                  alt=""
                  className="h-full w-full object-cover"
                />
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-[12px] font-medium">{m.filename}</div>
                <div className="text-[10px] text-[var(--text-muted)]">
                  <StateBadge state={m.inference_state} />
                  {m.analysis?.model_name && (
                    <span className="ml-2 font-mono">{m.analysis.model_name}</span>
                  )}
                  {m.analysis?.caption_short && (
                    <span className="ml-2 text-[var(--text-secondary)]">
                      {m.analysis.caption_short}
                    </span>
                  )}
                </div>
              </div>
              <button
                type="button"
                disabled={busy}
                onClick={() => void reanalyse(m.id)}
                className="inline-flex shrink-0 items-center gap-1 rounded-md border border-[var(--ai)]/40 px-2 py-1 text-[10px] text-[var(--ai)] hover:bg-[var(--ai)]/10 disabled:opacity-40"
              >
                <Sparkles className="h-3 w-3" />
                Re-run
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone?: "success" | "warning" | "ai" | "accent";
}) {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)] px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
        {label}
      </div>
      <div
        className={cn(
          "text-[18px] font-semibold tabular-nums",
          tone === "success" && "text-[var(--success)]",
          tone === "warning" && "text-[var(--warning)]",
          tone === "ai" && "text-[var(--ai)]",
          tone === "accent" && "text-[var(--accent)]",
        )}
      >
        {value}
      </div>
    </div>
  );
}

function StateBadge({ state }: { state: string }) {
  return (
    <span
      className={cn(
        "rounded px-1 py-0.5 text-[9px] font-medium uppercase",
        state === "pending" && "bg-[var(--warning)]/20 text-[var(--warning)]",
        state === "heuristic" && "bg-[var(--bg-hover)] text-[var(--text-secondary)]",
        state === "vlm" && "bg-[var(--ai)]/20 text-[var(--ai)]",
      )}
    >
      {state}
    </span>
  );
}
