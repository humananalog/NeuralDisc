"use client";

import { useEffect, useState } from "react";
import {
  X,
  Star,
  Flag,
  Sparkles,
  Trash2,
  RotateCw,
  RotateCcw,
  RefreshCw,
  MapPin,
  Loader2,
} from "lucide-react";
import { api, mediaSrc, type MediaItem } from "@/lib/api";
import { cn, confidenceColor, formatBytes, formatDate } from "@/lib/utils";
import { DeleteConfirmModal } from "./DeleteConfirmModal";
import { useAppStore } from "@/lib/store";

type Props = {
  item: MediaItem;
  onClose: () => void;
  onUpdated?: (m: MediaItem) => void;
  onDeleted?: (id: string) => void;
};

export function DetailPanel({ item: initial, onClose, onUpdated, onDeleted }: Props) {
  const [item, setItem] = useState<MediaItem>(initial);
  const [busy, setBusy] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [cacheBust, setCacheBust] = useState(0);
  const bumpLibrary = useAppStore((s) => s.bumpLibrary);

  // Always fetch full detail (including complete inference) when selection changes
  useEffect(() => {
    let cancelled = false;
    setItem(initial);
    setLoadingDetail(true);
    setError(null);
    (async () => {
      try {
        const full = await api.mediaOne(initial.id);
        if (!cancelled) {
          setItem(full);
          onUpdated?.(full);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load details");
        }
      } finally {
        if (!cancelled) setLoadingDetail(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload when id changes
  }, [initial.id]);

  const src = mediaSrc(item.preview_url || item.thumb_url || item.original_url);
  const previewSrc = src
    ? `${src}${src.includes("?") ? "&" : "?"}cb=${cacheBust}`
    : "";
  const a = item.analysis;
  const isAi = a && !a.human_edited;
  const inTrash = item.lifecycle === "trash";

  async function patch(body: Record<string, unknown>) {
    setBusy(true);
    setError(null);
    try {
      const m = await api.updateMedia(item.id, body);
      setItem(m);
      onUpdated?.(m);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Update failed");
    } finally {
      setBusy(false);
    }
  }

  async function rotate(mode: "auto" | "cw" | "ccw" | "180") {
    setBusy(true);
    setError(null);
    try {
      const res = await api.rotateMedia(item.id, mode);
      const stamp = res.media.updated_at || new Date().toISOString();
      const t = Date.now();
      const bump = (url?: string | null) => {
        if (!url) return url ?? null;
        const base = url.split("?")[0];
        return `${base}?v=${encodeURIComponent(stamp)}&t=${t}`;
      };
      const next = {
        ...res.media,
        updated_at: stamp,
        thumb_url: bump(res.media.thumb_url) ?? res.media.thumb_url,
        preview_url: bump(res.media.preview_url) ?? res.media.preview_url,
      };
      setItem(next);
      onUpdated?.(next);
      setCacheBust((n) => n + 1 + t);
      if (!res.changed && mode === "auto") {
        setError("Already upright (EXIF + content check)");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Rotate failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(permanent: boolean) {
    setBusy(true);
    setError(null);
    try {
      await api.deleteMedia(item.id, permanent);
      setDeleteOpen(false);
      onDeleted?.(item.id);
      bumpLibrary();
      onClose();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Delete failed";
      setError(msg);
      // Keep modal open; rethrow so DeleteConfirmModal shows the error
      throw e instanceof Error ? e : new Error(msg);
    } finally {
      setBusy(false);
    }
  }

  async function handleRestore() {
    setBusy(true);
    setError(null);
    try {
      const m = await api.restoreMedia(item.id);
      setItem(m);
      onUpdated?.(m);
      bumpLibrary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Restore failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside className="flex w-[400px] shrink-0 flex-col border-l border-[var(--border)] bg-[var(--bg-elevated)]">
      <div className="flex items-center justify-between border-b border-[var(--border)] px-3 py-2">
        <span className="truncate text-[13px] font-medium" title={item.filename}>
          {item.filename}
        </span>
        <button
          onClick={onClose}
          className="rounded p-1 text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
          aria-label="Close detail"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="relative aspect-[4/3] bg-black">
        {previewSrc ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={previewSrc}
            src={previewSrc}
            alt={item.filename}
            className="h-full w-full object-contain"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-[var(--text-muted)]">
            No preview
          </div>
        )}
        {loadingDetail && (
          <div className="absolute right-2 top-2 rounded-full bg-black/50 p-1.5">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-white" />
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-1 border-b border-[var(--border)] px-2 py-2">
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            disabled={busy || inTrash}
            onClick={() => patch({ rating: item.rating === n ? 0 : n })}
            title={`Rate ${n}★ (${n}) · 0 clears`}
            className="text-amber-400/80 hover:text-amber-300 disabled:opacity-40"
          >
            <Star
              className={cn("h-4 w-4", item.rating >= n && "fill-current")}
              strokeWidth={1.5}
            />
          </button>
        ))}
        <button
          disabled={busy || inTrash}
          onClick={() => patch({ flag: !item.flag })}
          className={cn(
            "rounded p-1",
            item.flag ? "text-[var(--danger)]" : "text-[var(--text-muted)]",
          )}
          title={item.flag ? "Unflag (u)" : "Flag / pick (f · p)"}
        >
          <Flag className={cn("h-4 w-4", item.flag && "fill-current")} />
        </button>

        <div className="mx-1 h-4 w-px bg-[var(--border)]" />

        {item.media_type === "image" && !inTrash && (
          <>
            <IconBtn
              title="Auto-rotate (⇧[)"
              disabled={busy}
              onClick={() => rotate("auto")}
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </IconBtn>
            <IconBtn title="Rotate 90° left ([)" disabled={busy} onClick={() => rotate("ccw")}>
              <RotateCcw className="h-3.5 w-3.5" />
            </IconBtn>
            <IconBtn title="Rotate 90° right (])" disabled={busy} onClick={() => rotate("cw")}>
              <RotateCw className="h-3.5 w-3.5" />
            </IconBtn>
          </>
        )}

        <div className="ml-auto flex items-center gap-1">
          {inTrash ? (
            <button
              type="button"
              disabled={busy}
              onClick={handleRestore}
              className="rounded-md border border-[var(--border)] px-2 py-1 text-[11px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
            >
              Restore
            </button>
          ) : null}
          <button
            type="button"
            disabled={busy}
            onClick={() => setDeleteOpen(true)}
            className="inline-flex items-center gap-1 rounded-md border border-[var(--danger)]/40 px-2 py-1 text-[11px] text-[var(--danger)] hover:bg-[var(--danger)]/10"
          >
            <Trash2 className="h-3 w-3" />
            {inTrash ? "Delete forever" : "Delete"}
          </button>
        </div>
      </div>

      {error && (
        <div className="mx-3 mt-2 rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-2 py-1.5 text-[11px] text-[var(--danger)]">
          {error}
        </div>
      )}

      <div className="flex-1 space-y-4 overflow-y-auto p-3 text-[12px]">
        <Section title="Metadata">
          <Row label="Taken" value={formatDate(item.taken_at)} />
          <Row
            label="Camera"
            value={[item.camera_make, item.camera_model].filter(Boolean).join(" ") || "—"}
          />
          <Row
            label="Size"
            value={
              item.width && item.height ? `${item.width}×${item.height}` : "—"
            }
          />
          <Row label="File" value={item.file_size ? formatBytes(item.file_size) : "—"} />
          <Row label="Type" value={item.mime_type || item.media_type} />

          <Row label="Lifecycle" value={item.lifecycle || "library"} />
          <Row
            label="Sharpness"
            value={
              item.blur_score != null
                ? `${item.blur_score.toFixed(1)}${item.is_blurry ? " · BLURRY" : " · OK"}`
                : "—"
            }
          />
          <Row
            label="Orientation"
            value={
              item.orientation != null
                ? `EXIF ${item.orientation}${item.auto_rotated ? " · auto-rotated" : ""}${
                    item.rotation_degrees
                      ? ` · ${item.rotation_degrees}° baked`
                      : ""
                  }`
                : item.auto_rotated
                  ? `Upright${item.rotation_degrees ? ` · ${item.rotation_degrees}°` : ""}`
                  : "—"
            }
          />
          {(item.gps_lat != null || item.gps_lon != null) && (
            <Row
              label="GPS"
              value={`${item.gps_lat?.toFixed(5) ?? "?"}, ${item.gps_lon?.toFixed(5) ?? "?"}`}
            />
          )}
          <Row label="SHA-256" value={item.sha256.slice(0, 20) + "…"} mono />
          {item.phash && <Row label="pHash" value={item.phash} mono />}
          <Row label="Imported" value={formatDate(item.created_at)} />
          {item.deleted_at && <Row label="Trashed" value={formatDate(item.deleted_at)} />}
          {item.library_path && (
            <Row label="Path" value={item.library_path.split("/").slice(-3).join("/")} mono />
          )}
        </Section>

        {item.is_blurry && (
          <div className="rounded-md border border-[var(--warning)]/40 bg-[var(--warning)]/10 px-2.5 py-2 text-[12px] text-[var(--warning)]">
            Flagged as blurry (Laplacian score {item.blur_score?.toFixed(1) ?? "?"} below
            threshold). Flag or trash if you disagree.
          </div>
        )}

        {item.is_duplicate && (
          <div className="rounded-md border border-[var(--accent)]/30 bg-[var(--accent)]/10 px-2.5 py-2 text-[12px] text-[var(--text-secondary)]">
            Marked as duplicate
            {item.best_of_group ? " · best of group" : ""}.
          </div>
        )}

        {a ? (
          <Section
            title={
              <span className="flex items-center gap-1.5">
                AI Inference
                {isAi && <Sparkles className="h-3 w-3 text-[var(--ai)]" />}
                {a.human_edited && (
                  <span className="text-[10px] text-[var(--success)]">human-edited</span>
                )}
              </span>
            }
          >
            <div className={cn(isAi ? "nd-ai-field" : "nd-human-field", "space-y-2.5")}>
              <p className="text-[13px] font-medium text-[var(--text-primary)]">
                {a.caption_short || "No caption"}
              </p>
              {a.description && (
                <p className="leading-relaxed text-[var(--text-secondary)]">{a.description}</p>
              )}

              {a.confidence != null && (
                <div className="flex items-center gap-2">
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--bg-hover)]">
                    <div
                      className="h-full rounded-full transition-all"
                      style={{
                        width: `${Math.round(a.confidence * 100)}%`,
                        background: confidenceColor(a.confidence),
                      }}
                    />
                  </div>
                  <span
                    className="font-mono text-[11px]"
                    style={{ color: confidenceColor(a.confidence) }}
                  >
                    {Math.round(a.confidence * 100)}%
                  </span>
                </div>
              )}

              <div className="space-y-0.5 rounded-md border border-[var(--border)]/60 bg-[var(--bg-base)]/40 px-2 py-1.5">
                <Row label="Scene" value={a.scene_type || "—"} />
                <Row
                  label="People"
                  value={
                    a.people_count != null
                      ? `${a.people_count}${a.people_desc ? ` · ${a.people_desc}` : ""}`
                      : a.people_desc || "—"
                  }
                />
                <Row label="Era" value={a.estimated_era || "—"} />
                <Row label="Model" value={a.model_name || "—"} mono />
                {a.model_version && <Row label="Version" value={a.model_version} mono />}
                <Row label="Analysed" value={formatDate(a.analysed_at)} />
              </div>

              {a.objects?.length > 0 && (
                <div>
                  <div className="mb-1 text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
                    Objects
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {uniqueLabels(a.objects).map((o) => (
                      <span
                        key={`obj-${o}`}
                        className="rounded-full border border-[var(--border)] bg-[var(--bg-base)] px-2 py-0.5 text-[10px] text-[var(--text-secondary)]"
                      >
                        {o}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {a.suggested_tags?.length > 0 && (
                <div>
                  <div className="mb-1 text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
                    Suggested tags
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {uniqueLabels(a.suggested_tags).map((t) => (
                      <span
                        key={`tag-${t}`}
                        className="rounded-full border border-[var(--ai)]/30 bg-[var(--ai)]/10 px-2 py-0.5 text-[10px] text-[var(--ai)]"
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </Section>
        ) : (
          !loadingDetail && (
            <Section title="AI Inference">
              <p className="text-[var(--text-muted)]">
                No VLM analysis yet. Enable VLM in Settings and reprocess, or wait for import
                pipeline.
              </p>
            </Section>
          )
        )}

        {(item.gps_lat != null || item.gps_lon != null) && (
          <Section title="Location">
            <div className="flex items-start gap-2 text-[var(--text-secondary)]">
              <MapPin className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--text-muted)]" />
              <span className="font-mono text-[11px]">
                {item.gps_lat?.toFixed(6)}, {item.gps_lon?.toFixed(6)}
              </span>
            </div>
          </Section>
        )}
      </div>

      {deleteOpen && (
        <DeleteConfirmModal
          count={1}
          filenames={[item.filename]}
          permanentDefault={inTrash}
          onCancel={() => setDeleteOpen(false)}
          onConfirm={handleDelete}
          busy={busy}
        />
      )}
    </aside>
  );
}

/** Dedupe case-insensitively while preserving first-seen label (stable React keys). */
function uniqueLabels(labels: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of labels) {
    const t = String(raw ?? "").trim();
    if (!t) continue;
    const k = t.toLowerCase();
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(t);
  }
  return out;
}

function IconBtn({
  children,
  title,
  disabled,
  onClick,
}: {
  children: React.ReactNode;
  title: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onClick={onClick}
      className="rounded p-1 text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] disabled:opacity-40"
    >
      {children}
    </button>
  );
}

function Section({
  title,
  children,
}: {
  title: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h3 className="mb-1.5 text-[11px] font-medium uppercase tracking-wider text-[var(--text-muted)]">
        {title}
      </h3>
      {children}
    </section>
  );
}

function Row({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex justify-between gap-2 py-0.5">
      <span className="shrink-0 text-[var(--text-muted)]">{label}</span>
      <span
        className={cn(
          "min-w-0 truncate text-right text-[var(--text-secondary)]",
          mono && "font-mono text-[11px]",
        )}
        title={value}
      >
        {value}
      </span>
    </div>
  );
}
