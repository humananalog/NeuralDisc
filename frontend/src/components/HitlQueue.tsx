"use client";

import { useCallback, useEffect, useState } from "react";
import { api, mediaSrc, type HitlItem } from "@/lib/api";
import { cn, confidenceColor } from "@/lib/utils";
import { Check, Pencil, Trash2, Sparkles } from "lucide-react";

export function HitlQueue() {
  const [queue, setQueue] = useState<HitlItem[]>([]);
  const [index, setIndex] = useState(0);
  const [flash, setFlash] = useState(false);
  const [editing, setEditing] = useState(false);
  const [caption, setCaption] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const items = await api.hitlQueue(100);
      setQueue(items);
      setIndex(0);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load queue");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const current = queue[index] || null;
  const media = current?.media;

  useEffect(() => {
    if (media?.analysis?.caption_short) {
      setCaption(media.analysis.caption_short);
    } else {
      setCaption("");
    }
    setEditing(false);
  }, [media?.id, media?.analysis?.caption_short]);

  const resolve = useCallback(
    async (resolution: string, extra: Record<string, unknown> = {}) => {
      if (!current) return;
      try {
        await api.resolveHitl(current.id, { resolution, ...extra });
        setFlash(true);
        setTimeout(() => setFlash(false), 400);
        setQueue((q) => {
          const next = q.filter((x) => x.id !== current.id);
          return next;
        });
        setIndex((i) => Math.min(i, Math.max(0, queue.length - 2)));
      } catch (e) {
        setError(e instanceof Error ? e.message : "Resolve failed");
      }
    },
    [current, queue.length],
  );

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (editing && e.key !== "Escape") return;
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;

      switch (e.key) {
        case "j":
        case "ArrowDown":
          e.preventDefault();
          setIndex((i) => Math.min(i + 1, Math.max(0, queue.length - 1)));
          break;
        case "k":
        case "ArrowUp":
          e.preventDefault();
          setIndex((i) => Math.max(i - 1, 0));
          break;
        case "a":
          e.preventDefault();
          void resolve("accepted");
          break;
        case "e":
          e.preventDefault();
          setEditing(true);
          break;
        case "r":
          e.preventDefault();
          void resolve("rejected");
          break;
        case "f":
          e.preventDefault();
          if (media) void api.updateMedia(media.id, { flag: !media.flag });
          break;
        case "1":
        case "2":
        case "3":
        case "4":
        case "5":
          e.preventDefault();
          if (media) void api.updateMedia(media.id, { rating: Number(e.key) });
          break;
        case " ":
          e.preventDefault();
          setIndex((i) => Math.min(i + 1, Math.max(0, queue.length - 1)));
          break;
        case "Escape":
          setEditing(false);
          break;
        case "Enter":
          if (editing) {
            e.preventDefault();
            void resolve("edited", {
              caption_short: caption,
              suggested_tags: media?.analysis?.suggested_tags,
            });
          }
          break;
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [queue.length, resolve, editing, caption, media]);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-[var(--text-muted)]">
        Loading review queue…
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center text-[var(--danger)]">
        {error}
      </div>
    );
  }

  if (!current || !media) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-[var(--text-muted)]">
        <Check className="h-8 w-8 text-[var(--success)]" />
        <p className="text-[15px] text-[var(--text-primary)]">Queue clear</p>
        <p className="text-[12px]">All items reviewed. Ingest another disc to continue.</p>
      </div>
    );
  }

  const src = mediaSrc(media.preview_url || media.thumb_url || media.original_url);
  const conf = media.analysis?.confidence;

  return (
    <div className="flex h-full min-h-0">
      {/* Queue list */}
      <div className="flex w-56 shrink-0 flex-col border-r border-[var(--border)] bg-[var(--bg-elevated)]">
        <div className="border-b border-[var(--border)] px-3 py-2 text-[11px] uppercase tracking-wider text-[var(--text-muted)]">
          Queue · {queue.length}
        </div>
        <div className="flex-1 overflow-y-auto">
          {queue.map((item, i) => (
            <button
              key={item.id}
              onClick={() => setIndex(i)}
              className={cn(
                "flex w-full items-center gap-2 border-b border-[var(--border)]/50 px-2 py-1.5 text-left text-[11px]",
                i === index ? "bg-[var(--bg-selected)]" : "hover:bg-[var(--bg-hover)]",
              )}
            >
              <div className="h-10 w-10 shrink-0 overflow-hidden rounded-sm bg-black">
                {item.media?.thumb_url && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={mediaSrc(item.media.thumb_url)}
                    alt=""
                    className="h-full w-full object-cover"
                  />
                )}
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-[var(--text-primary)]">
                  {item.media?.filename}
                </div>
                <div className="text-[var(--text-muted)]">{item.queue_type}</div>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Main preview */}
      <div
        className={cn(
          "flex min-w-0 flex-1 flex-col bg-black",
          flash && "nd-flash-ok",
        )}
      >
        <div className="relative flex flex-1 items-center justify-center">
          {src ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={src}
              alt={media.filename}
              className="max-h-full max-w-full object-contain"
            />
          ) : (
            <span className="text-[var(--text-muted)]">No preview</span>
          )}
        </div>
        <div className="flex gap-1 overflow-x-auto border-t border-[var(--border)] bg-[var(--bg-base)] p-2">
          {queue.slice(Math.max(0, index - 4), index + 8).map((item) => (
            <button
              key={item.id}
              onClick={() => setIndex(queue.indexOf(item))}
              className={cn(
                "h-14 w-14 shrink-0 overflow-hidden rounded-sm",
                item.id === current.id && "ring-2 ring-[var(--accent)]",
              )}
            >
              {item.media?.thumb_url && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={mediaSrc(item.media.thumb_url)}
                  alt=""
                  className="h-full w-full object-cover"
                />
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Actions + AI panel */}
      <div className="flex w-[360px] shrink-0 flex-col border-l border-[var(--border)] bg-[var(--bg-elevated)]">
        <div className="border-b border-[var(--border)] px-3 py-2">
          <div className="truncate text-[13px] font-medium">{media.filename}</div>
          <div className="text-[11px] text-[var(--text-muted)]">{current.queue_type}</div>
        </div>

        <div className="flex-1 space-y-3 overflow-y-auto p-3">
          <div className={cn(media.analysis?.human_edited ? "nd-human-field" : "nd-ai-field")}>
            <div className="mb-1 flex items-center gap-1 text-[11px] text-[var(--ai)]">
              <Sparkles className="h-3 w-3" />
              AI fields
            </div>
            {editing ? (
              <textarea
                autoFocus
                value={caption}
                onChange={(e) => setCaption(e.target.value)}
                className="w-full rounded border border-[var(--border-strong)] bg-[var(--bg-base)] p-2 text-[13px]"
                rows={3}
              />
            ) : (
              <p className="text-[13px]">{media.analysis?.caption_short || "No caption"}</p>
            )}
            {media.analysis?.description && (
              <p className="mt-1 text-[12px] text-[var(--text-secondary)]">
                {media.analysis.description}
              </p>
            )}
            {conf != null && (
              <div className="mt-2 flex items-center gap-2">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--bg-hover)]">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${Math.round(conf * 100)}%`,
                      background: confidenceColor(conf),
                    }}
                  />
                </div>
                <span className="font-mono text-[11px]" style={{ color: confidenceColor(conf) }}>
                  {Math.round(conf * 100)}%
                </span>
              </div>
            )}
            {media.analysis?.suggested_tags && (
              <div className="mt-2 flex flex-wrap gap-1">
                {media.analysis.suggested_tags.map((t) => (
                  <span
                    key={t}
                    className="rounded-full border border-[var(--border)] px-2 py-0.5 text-[10px]"
                  >
                    {t}
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="rounded-md border border-[var(--border)] p-2 text-[11px] text-[var(--text-muted)]">
            <div className="mb-1 font-medium text-[var(--text-secondary)]">Keyboard</div>
            <div className="grid grid-cols-2 gap-x-2 gap-y-0.5 font-mono">
              <span>j/k</span><span>next/prev</span>
              <span>a</span><span>accept</span>
              <span>e</span><span>edit</span>
              <span>r</span><span>reject</span>
              <span>1–5</span><span>rate</span>
              <span>f</span><span>flag</span>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-2 border-t border-[var(--border)] p-3">
          <ActionBtn
            tone="success"
            onClick={() =>
              editing
                ? resolve("edited", { caption_short: caption })
                : resolve("accepted")
            }
            icon={<Check className="h-4 w-4" />}
            label="Accept"
          />
          <ActionBtn
            tone="ai"
            onClick={() => setEditing((v) => !v)}
            icon={<Pencil className="h-4 w-4" />}
            label="Edit"
          />
          <ActionBtn
            tone="danger"
            onClick={() => resolve("rejected")}
            icon={<Trash2 className="h-4 w-4" />}
            label="Reject"
          />
        </div>
      </div>
    </div>
  );
}

function ActionBtn({
  label,
  icon,
  onClick,
  tone,
}: {
  label: string;
  icon: React.ReactNode;
  onClick: () => void;
  tone: "success" | "danger" | "ai";
}) {
  const color =
    tone === "success"
      ? "border-[var(--success)]/40 text-[var(--success)] hover:bg-[var(--success)]/10"
      : tone === "danger"
        ? "border-[var(--danger)]/40 text-[var(--danger)] hover:bg-[var(--danger)]/10"
        : "border-[var(--ai)]/40 text-[var(--ai)] hover:bg-[var(--ai)]/10";
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex flex-col items-center gap-1 rounded-md border py-2 text-[11px] transition-colors",
        color,
      )}
    >
      {icon}
      {label}
    </button>
  );
}
