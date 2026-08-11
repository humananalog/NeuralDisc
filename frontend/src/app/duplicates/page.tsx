"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckSquare, Sparkles, Square, Copy, Layers, Trash2, HardDrive } from "lucide-react";
import { api, type DuplicateGroup, type DuplicateSummary } from "@/lib/api";
import { cn, formatBytes } from "@/lib/utils";
import { useAppStore } from "@/lib/store";

const EMPTY_SUMMARY: DuplicateSummary = {
  groups: 0,
  active_groups: 0,
  resolved_groups: 0,
  total_members: 0,
  active_members: 0,
  unique_media: 0,
  active_unique_media: 0,
  best_count: 0,
  trashable: 0,
  by_method: {},
  active_bytes: 0,
  trashable_bytes: 0,
};

export default function DuplicatesPage() {
  const [groups, setGroups] = useState<DuplicateGroup[]>([]);
  const [summary, setSummary] = useState<DuplicateSummary>(EMPTY_SUMMARY);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const bumpLibrary = useAppStore((s) => s.bumpLibrary);
  const setNavCounts = useAppStore((s) => s.setNavCounts);

  const load = useCallback(async () => {
    try {
      const [g, s, nav] = await Promise.all([
        api.duplicates(),
        api.duplicatesSummary(),
        api.navCounts().catch(() => null),
      ]);
      setGroups(g);
      setSummary(s);
      if (nav) setNavCounts(nav);
      setSelected((prev) => {
        const ids = new Set(g.map((x) => x.id));
        const next = new Set<string>();
        for (const id of prev) if (ids.has(id)) next.add(id);
        return next;
      });
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    }
  }, [setNavCounts]);

  useEffect(() => {
    void load();
  }, [load]);

  const activeGroups = useMemo(
    () =>
      groups.filter((g) => {
        if ((g as { active?: boolean }).active === false) return false;
        const alive = g.members.filter(
          (m) =>
            (m as { lifecycle?: string }).lifecycle !== "trash" &&
            (m as { lifecycle?: string }).lifecycle !== "rejected",
        );
        return alive.length >= 2;
      }),
    [groups],
  );

  // Default: only show active groups (matches top counts). Hide ghosts with 0/1 library member.
  const visibleGroups = activeGroups;

  function toggleGroup(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function selectAll() {
    setSelected(new Set(activeGroups.map((g) => g.id)));
  }

  function clearSel() {
    setSelected(new Set());
  }

  async function keepBestOne(groupId: string) {
    setBusy(true);
    setError(null);
    try {
      const res = await api.keepBest(groupId);
      setMsg(
        `Kept 1 · trashed ${res.trashed?.length ?? res.rejected ?? 0} worse copies`,
      );
      bumpLibrary();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Keep best failed");
    } finally {
      setBusy(false);
    }
  }

  async function keepBestSelected() {
    if (selected.size === 0) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.keepBestBatch({
        group_ids: [...selected],
        trash_losers: true,
      });
      setMsg(
        `Batch: kept ${res.kept_count} · trashed ${res.trashed_count} · ${res.groups_resolved} group(s)`,
      );
      clearSel();
      bumpLibrary();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Batch keep best failed");
    } finally {
      setBusy(false);
    }
  }

  async function keepBestAll() {
    if (activeGroups.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.keepBestBatch({
        all_groups: true,
        trash_losers: true,
      });
      setMsg(
        `All groups: kept ${res.kept_count} · trashed ${res.trashed_count} · ${res.groups_resolved} group(s)`,
      );
      clearSel();
      bumpLibrary();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Keep best all failed");
    } finally {
      setBusy(false);
    }
  }

  const methodBits = Object.entries(summary.by_method || {});

  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-[16px] font-semibold">Duplicate groups</h1>
          <p className="mt-0.5 text-[12px] text-[var(--text-muted)]">
            Review near-identical photos and keep the best version in each cluster
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {activeGroups.length > 0 && (
            <>
              <button
                type="button"
                disabled={busy}
                onClick={selected.size === activeGroups.length ? clearSel : selectAll}
                className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-2.5 py-1.5 text-[11px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] disabled:opacity-40"
              >
                {selected.size === activeGroups.length ? (
                  <CheckSquare className="h-3.5 w-3.5" />
                ) : (
                  <Square className="h-3.5 w-3.5" />
                )}
                {selected.size === activeGroups.length ? "Clear" : "Select all"}
              </button>
              <button
                type="button"
                disabled={busy || selected.size === 0}
                onClick={() => void keepBestSelected()}
                className="inline-flex items-center gap-1 rounded-md border border-[var(--success)]/40 px-2.5 py-1.5 text-[11px] font-medium text-[var(--success)] hover:bg-[var(--success)]/10 disabled:opacity-40"
              >
                <Sparkles className="h-3.5 w-3.5" />
                {busy
                  ? "Working…"
                  : `Keep best on ${selected.size || "…"} selected`}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void keepBestAll()}
                className="inline-flex items-center gap-1 rounded-md bg-[var(--success)] px-2.5 py-1.5 text-[11px] font-medium text-white hover:bg-[var(--success)]/90 disabled:opacity-40"
              >
                <Sparkles className="h-3.5 w-3.5" />
                Keep best — all groups
              </button>
            </>
          )}
        </div>
      </div>

      {/* Top count strip */}
      <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <CountCard
          icon={<Layers className="h-3.5 w-3.5" />}
          label="Active groups"
          value={summary.active_groups}
          accent
        />
        <CountCard
          icon={<Copy className="h-3.5 w-3.5" />}
          label="Duplicate items"
          value={summary.active_unique_media}
        />
        <CountCard
          icon={<Copy className="h-3.5 w-3.5" />}
          label="In groups (slots)"
          value={summary.active_members}
        />
        <CountCard
          icon={<Sparkles className="h-3.5 w-3.5" />}
          label="Marked best"
          value={summary.best_count}
          tone="success"
        />
        <CountCard
          icon={<Trash2 className="h-3.5 w-3.5" />}
          label="Can trash"
          value={summary.trashable}
          tone="warning"
        />
        <CountCard
          icon={<HardDrive className="h-3.5 w-3.5" />}
          label="Recoverable"
          value={
            summary.trashable_bytes > 0
              ? formatBytes(summary.trashable_bytes)
              : "—"
          }
          tone="warning"
        />
      </div>

      {(methodBits.length > 0 || summary.resolved_groups > 0) && (
        <div className="mb-4 flex flex-wrap items-center gap-2 text-[11px] text-[var(--text-muted)]">
          <span>
            {summary.groups} total groups
            {summary.resolved_groups > 0
              ? ` · ${summary.resolved_groups} resolved`
              : ""}
          </span>
          {methodBits.map(([method, n], i) => (
            <span
              key={`${method}-${i}`}
              className="rounded-full border border-[var(--border)] px-2 py-0.5 font-mono text-[10px] text-[var(--text-secondary)]"
            >
              {method}: {n}
            </span>
          ))}
        </div>
      )}

      {msg && (
        <div className="mb-3 rounded-md border border-[var(--success)]/40 bg-[var(--success)]/10 px-3 py-2 text-[12px] text-[var(--success)]">
          {msg}
          <button
            type="button"
            className="ml-2 underline opacity-80"
            onClick={() => setMsg(null)}
          >
            dismiss
          </button>
        </div>
      )}
      {error && <p className="mb-3 text-[12px] text-[var(--danger)]">{error}</p>}
      {visibleGroups.length === 0 && !error && (
        <p className="text-[var(--text-muted)]">
          {summary.active_groups === 0
            ? "No active duplicate groups. Keep-best winners stay in the library; trash copies are hidden here."
            : "No duplicate groups detected."}
        </p>
      )}

      <div className="space-y-4">
        {visibleGroups.map((g) => {
          const alive = g.members.filter(
            (m) =>
              (m as { lifecycle?: string }).lifecycle !== "trash" &&
              (m as { lifecycle?: string }).lifecycle !== "rejected",
          );
          const isActive = alive.length >= 2;
          const isSel = selected.has(g.id);
          return (
            <div
              key={g.id}
              className={cn(
                "rounded-lg border bg-[var(--bg-elevated)] p-3",
                isSel
                  ? "border-[var(--accent)] ring-1 ring-[var(--accent)]/30"
                  : "border-[var(--border)]",
              )}
            >
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-[12px]">
                <div className="flex items-center gap-2">
                  {isActive && (
                    <button
                      type="button"
                      onClick={() => toggleGroup(g.id)}
                      className="text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                      aria-label={isSel ? "Deselect group" : "Select group"}
                    >
                      {isSel ? (
                        <CheckSquare className="h-4 w-4 text-[var(--accent)]" />
                      ) : (
                        <Square className="h-4 w-4" />
                      )}
                    </button>
                  )}
                  <span className="text-[var(--text-secondary)]">
                    Method:{" "}
                    <span className="font-mono text-[var(--text-primary)]">
                      {g.method}
                    </span>
                    {" · "}
                    {g.members.length} members
                    {!isActive && " · resolved"}
                  </span>
                </div>
                {isActive && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void keepBestOne(g.id)}
                    className="rounded-md border border-[var(--success)]/40 px-2.5 py-1 text-[11px] text-[var(--success)] hover:bg-[var(--success)]/10 disabled:opacity-40"
                  >
                    Keep best
                  </button>
                )}
              </div>
              <div className="flex flex-wrap gap-2">
                {alive.map((m) => (
                    <div
                      key={m.media_id}
                      className={cn(
                        "w-36 rounded border p-2 text-[11px]",
                        m.best_of_group
                          ? "border-[var(--success)] ring-1 ring-[var(--success)]/40"
                          : "border-[var(--border)]",
                      )}
                    >
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={`/api/media/${m.media_id}/thumb`}
                        alt={m.filename}
                        className="mb-1 aspect-square w-full rounded-sm object-cover"
                      />
                      <div className="truncate font-medium">{m.filename}</div>
                      <div className="text-[var(--text-muted)]">
                        {m.width && m.height ? `${m.width}×${m.height}` : "—"}
                        {m.similarity != null &&
                          ` · ${Math.round(m.similarity * 100)}%`}
                      </div>
                      {m.best_of_group && (
                        <div className="mt-0.5 text-[var(--success)]">Best</div>
                      )}
                    </div>
                  ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function CountCard({
  icon,
  label,
  value,
  accent,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: number | string;
  accent?: boolean;
  tone?: "success" | "warning";
}) {
  return (
    <div
      className={cn(
        "rounded-lg border px-3 py-2.5",
        accent
          ? "border-[var(--warning)]/40 bg-[var(--warning)]/10"
          : "border-[var(--border)] bg-[var(--bg-elevated)]",
      )}
    >
      <div className="mb-1 flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
        {icon}
        {label}
      </div>
      <div
        className={cn(
          "text-[20px] font-semibold tabular-nums tracking-tight",
          tone === "success" && "text-[var(--success)]",
          tone === "warning" && "text-[var(--warning)]",
          accent && "text-[var(--warning)]",
          !tone && !accent && "text-[var(--text-primary)]",
        )}
      >
        {value}
      </div>
    </div>
  );
}
