"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Sparkles,
  Layers,
  RefreshCw,
  Camera,
  Calendar,
  MapPin,
  Tag,
  Users,
  Disc3,
  Trash2,
  X,
} from "lucide-react";
import { api, type Album, type MediaItem } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/lib/store";
import { useMediaShortcuts } from "@/hooks/useMediaShortcuts";
import { MediaLightbox } from "@/components/MediaLightbox";
import { ShortcutsHelp } from "@/components/ShortcutsHelp";

type FilterTab = "all" | "album" | "smart";

export default function AlbumsPage() {
  const [albums, setAlbums] = useState<Album[]>([]);
  const [tab, setTab] = useState<FilterTab>("all");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<Album | null>(null);
  const [media, setMedia] = useState<MediaItem[]>([]);
  const [mediaLoading, setMediaLoading] = useState(false);
  const [focusId, setFocusId] = useState<string | null>(null);
  const [lightboxId, setLightboxId] = useState<string | null>(null);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const setNavCounts = useAppStore((s) => s.setNavCounts);
  const bumpLibrary = useAppStore((s) => s.bumpLibrary);

  const load = useCallback(async () => {
    try {
      const list = await api.albums();
      setAlbums(list);
      try {
        const nav = await api.navCounts();
        setNavCounts(nav);
      } catch {
        /* */
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load albums");
    }
  }, [setNavCounts]);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(() => {
    if (tab === "all") return albums;
    return albums.filter((a) => (a.kind || "album") === tab);
  }, [albums, tab]);

  const stats = useMemo(() => {
    const smart = albums.filter((a) => a.kind === "smart").length;
    const fixed = albums.length - smart;
    const auto = albums.filter(
      (a) => a.is_ai_proposed || (a.source || "").startsWith("auto"),
    ).length;
    return { smart, fixed, auto, total: albums.length };
  }, [albums]);

  async function runAutoOrganise() {
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const res = await api.autoOrganiseAlbums({});
      setMsg(
        `Created ${res.albums_created} albums · updated ${res.albums_updated} · ` +
          `${res.smart_created + res.smart_updated} smart · ${res.members_linked} members linked`,
      );
      setAlbums(res.albums.length ? res.albums : await api.albums());
      bumpLibrary();
      try {
        setNavCounts(await api.navCounts());
      } catch {
        /* */
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Auto-organise failed");
    } finally {
      setBusy(false);
    }
  }

  async function openAlbum(a: Album) {
    setActive(a);
    setMediaLoading(true);
    setMedia([]);
    setFocusId(null);
    setLightboxId(null);
    try {
      const data = await api.albumMedia(a.id, 120);
      setMedia(data.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load album");
    } finally {
      setMediaLoading(false);
    }
  }

  async function removeAlbum(a: Album, e: React.MouseEvent) {
    e.stopPropagation();
    if (!confirm(`Delete “${a.name}”? Membership only — media stays in the library.`)) return;
    try {
      await api.deleteAlbum(a.id);
      if (active?.id === a.id) {
        setActive(null);
        setMedia([]);
      }
      setAlbums((prev) => prev.filter((x) => x.id !== a.id));
      bumpLibrary();
      try {
        setNavCounts(await api.navCounts());
      } catch {
        /* */
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  }

  const orderedIds = useMemo(() => media.map((m) => m.id), [media]);
  const itemsById = useMemo(() => new Map(media.map((m) => [m.id, m])), [media]);
  const lightboxItem = lightboxId
    ? media.find((m) => m.id === lightboxId) || null
    : null;

  useMediaShortcuts({
    enabled: Boolean(active) && media.length > 0 && !shortcutsOpen,
    orderedIds,
    itemsById,
    lightboxOpen: Boolean(lightboxId),
    detailOpen: false,
    getTargetIds: () => {
      if (lightboxId) return [lightboxId];
      if (focusId) return [focusId];
      return [];
    },
    onItemsPatched: (updated) => {
      const byId = new Map(updated.map((m) => [m.id, m]));
      setMedia((prev) => prev.map((x) => byId.get(x.id) ?? x));
    },
    onRotate: async (ids, mode) => {
      try {
        const res = await api.batchRotateMedia(ids, mode, true);
        const byId = new Map(res.items.map((m) => [m.id, m]));
        setMedia((prev) => prev.map((x) => byId.get(x.id) ?? x));
        bumpLibrary();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Rotate failed");
      }
    },
    onSelectId: (id) => setFocusId(id),
    onOpenLightbox: (id) => {
      setFocusId(id);
      setLightboxId(id);
    },
    onCloseLightbox: () => setLightboxId(null),
    onClearSelection: () => setFocusId(null),
    onToggleHelp: () => setShortcutsOpen((v) => !v),
  });

  function sourceIcon(a: Album) {
    const s = (a.source || "").toLowerCase();
    if (s.includes("camera")) return <Camera className="h-2.5 w-2.5" />;
    if (s.includes("year") || s.includes("month") || s.includes("date"))
      return <Calendar className="h-2.5 w-2.5" />;
    if (s.includes("place") || s.includes("geo") || s.includes("gps"))
      return <MapPin className="h-2.5 w-2.5" />;
    if (s.includes("tag") || s.includes("scene")) return <Tag className="h-2.5 w-2.5" />;
    if (s.includes("people") || s.includes("person")) return <Users className="h-2.5 w-2.5" />;
    if (s.includes("disc")) return <Disc3 className="h-2.5 w-2.5" />;
    return <Layers className="h-2.5 w-2.5" />;
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] px-4 py-3">
        <div>
          <h1 className="text-[16px] font-semibold">Collections</h1>
          <p className="text-[12px] text-[var(--text-muted)]">
            {stats.total} total · {stats.fixed} albums · {stats.smart} smart · {stats.auto} auto
            {" · "}
            <button
              type="button"
              onClick={() => setShortcutsOpen(true)}
              className="font-mono text-[var(--text-secondary)] hover:underline"
            >
              ?
            </button>
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-md border border-[var(--border)] p-0.5 text-[11px]">
            {(
              [
                ["all", "All"],
                ["album", "Albums"],
                ["smart", "Smart"],
              ] as const
            ).map(([k, label]) => (
              <button
                key={k}
                type="button"
                onClick={() => setTab(k)}
                className={cn(
                  "rounded px-2.5 py-1",
                  tab === k
                    ? "bg-[var(--bg-selected)] text-[var(--text-primary)]"
                    : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]",
                )}
              >
                {label}
              </button>
            ))}
          </div>
          <button
            type="button"
            disabled={busy}
            onClick={() => void runAutoOrganise()}
            className="inline-flex items-center gap-1.5 rounded-md bg-[var(--ai)] px-3 py-1.5 text-[12px] font-medium text-white hover:opacity-90 disabled:opacity-40"
          >
            <Sparkles className={cn("h-3.5 w-3.5", busy && "animate-pulse")} />
            {busy ? "Organising…" : "Auto-organise"}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void load()}
            className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-2 py-1.5 text-[11px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
          >
            <RefreshCw className={cn("h-3 w-3", busy && "animate-spin")} />
            Refresh
          </button>
        </div>
      </div>

      {msg && (
        <div className="mx-4 mt-3 rounded-md border border-[var(--success)]/40 bg-[var(--success)]/10 px-3 py-2 text-[12px] text-[var(--success)]">
          {msg}
          <button type="button" className="ml-2 underline opacity-80" onClick={() => setMsg(null)}>
            dismiss
          </button>
        </div>
      )}
      {error && (
        <div className="mx-4 mt-3 rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-3 py-2 text-[12px] text-[var(--danger)]">
          {error}
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1 overflow-y-auto p-4">
          {filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 py-16 text-center text-[var(--text-muted)]">
              <Sparkles className="h-8 w-8 opacity-40" />
              <p className="text-[14px] text-[var(--text-secondary)]">No collections yet</p>
              <p className="max-w-md text-[12px]">
                Click <strong className="text-[var(--text-primary)]">Auto-organise</strong> to
                create auto-named albums from EXIF (year, month, camera, disc) and inference
                (scene, tags, people, events), plus live smart collections.
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5">
              {filtered.map((a) => (
                <div
                  key={a.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => void openAlbum(a)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      void openAlbum(a);
                    }
                  }}
                  className={cn(
                    "group cursor-pointer overflow-hidden rounded-lg border bg-[var(--bg-elevated)] text-left transition-colors",
                    active?.id === a.id
                      ? "border-[var(--accent)] ring-1 ring-[var(--accent)]/40"
                      : "border-[var(--border)] hover:border-[var(--border-strong)]",
                  )}
                >
                  <div className="relative aspect-[4/3] bg-[var(--bg-hover)]">
                    {a.cover_media_id ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={`/api/media/${a.cover_media_id}/thumb`}
                        alt=""
                        className="h-full w-full object-cover"
                      />
                    ) : (
                      <div className="flex h-full items-center justify-center text-[var(--text-muted)]">
                        <Layers className="h-6 w-6 opacity-40" />
                      </div>
                    )}
                    <div className="absolute left-1.5 top-1.5 flex gap-1">
                      <span
                        className={cn(
                          "inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide backdrop-blur-sm",
                          a.kind === "smart"
                            ? "bg-[var(--ai)]/90 text-white"
                            : "bg-black/55 text-white",
                        )}
                      >
                        {sourceIcon(a)}
                        {a.kind === "smart" ? "Smart" : "Album"}
                      </span>
                    </div>
                    <button
                      type="button"
                      onClick={(e) => void removeAlbum(a, e)}
                      className="absolute right-1.5 top-1.5 rounded-full bg-black/50 p-1 text-white/80 opacity-0 transition-opacity hover:bg-black/70 hover:text-white group-hover:opacity-100"
                      title="Delete collection"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                  <div className="p-2.5">
                    <div className="truncate text-[13px] font-medium" title={a.name}>
                      {a.name}
                    </div>
                    <div className="mt-0.5 flex items-center justify-between gap-1 text-[11px] text-[var(--text-muted)]">
                      <span>
                        {a.item_count} item{a.item_count === 1 ? "" : "s"}
                      </span>
                      {a.is_ai_proposed && (
                        <span className="text-[var(--ai)]">auto</span>
                      )}
                    </div>
                    {a.description && (
                      <p className="mt-1 line-clamp-2 text-[10px] text-[var(--text-muted)]">
                        {a.description}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {active && (
          <aside className="flex w-[min(100%,420px)] shrink-0 flex-col border-l border-[var(--border)] bg-[var(--bg-elevated)]">
            <div className="flex items-start justify-between gap-2 border-b border-[var(--border)] px-3 py-2.5">
              <div className="min-w-0">
                <div className="truncate text-[14px] font-semibold">{active.name}</div>
                <div className="text-[11px] text-[var(--text-muted)]">
                  {(active.kind || "album") === "smart" ? "Smart collection" : "Album"}
                  {active.source ? ` · ${active.source}` : ""}
                  {" · "}
                  {mediaLoading ? "…" : `${media.length} shown`}
                  {" · "}
                  <span className="text-[var(--text-secondary)]">1–5 · [ ] · f</span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => {
                  setActive(null);
                  setMedia([]);
                  setFocusId(null);
                  setLightboxId(null);
                }}
                className="rounded p-1 text-[var(--text-muted)] hover:bg-[var(--bg-hover)]"
                aria-label="Close"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            {active.description && (
              <p className="border-b border-[var(--border)] px-3 py-2 text-[11px] text-[var(--text-secondary)]">
                {active.description}
              </p>
            )}
            {active.rules && (
              <div className="border-b border-[var(--border)] px-3 py-2 font-mono text-[10px] text-[var(--text-muted)]">
                rules: {JSON.stringify(active.rules)}
              </div>
            )}
            <div className="flex-1 overflow-y-auto p-2">
              {mediaLoading ? (
                <p className="p-4 text-center text-[12px] text-[var(--text-muted)]">Loading…</p>
              ) : media.length === 0 ? (
                <p className="p-4 text-center text-[12px] text-[var(--text-muted)]">No items</p>
              ) : (
                <div className="grid grid-cols-3 gap-1.5">
                  {media.map((m) => (
                    <button
                      key={m.id}
                      type="button"
                      onClick={() => setFocusId(m.id)}
                      onDoubleClick={() => {
                        setFocusId(m.id);
                        setLightboxId(m.id);
                      }}
                      className={cn(
                        "overflow-hidden rounded border bg-[var(--bg-base)] text-left",
                        focusId === m.id
                          ? "border-[var(--accent)] ring-1 ring-[var(--accent)]/40"
                          : "border-[var(--border)]",
                      )}
                      title={`${m.filename} · ${m.rating}★`}
                    >
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={m.thumb_url || `/api/media/${m.id}/thumb`}
                        alt={m.filename}
                        className="aspect-square w-full object-cover"
                      />
                    </button>
                  ))}
                </div>
              )}
            </div>
          </aside>
        )}
      </div>

      {lightboxItem && (
        <MediaLightbox
          item={lightboxItem}
          items={media}
          onClose={() => setLightboxId(null)}
          onNavigate={(id) => {
            setFocusId(id);
            setLightboxId(id);
          }}
        />
      )}
      <ShortcutsHelp open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
    </div>
  );
}
