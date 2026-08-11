"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { cn, formatBytes } from "@/lib/utils";
import {
  X,
  Disc3,
  FolderOpen,
  Layers,
  Play,
  HardDrive,
  Loader2,
  RefreshCw,
  Check,
  Minus,
  Maximize2,
  HardDriveDownload,
} from "lucide-react";

type Mode = "disc" | "media" | "batch";

type MountedVolume = {
  path: string;
  name: string;
  volume_uuid?: string | null;
  filesystem?: string | null;
  is_optical: boolean;
  is_ejectable: boolean;
  is_internal?: boolean;
  is_removable?: boolean;
  total_bytes?: number | null;
  free_bytes?: number | null;
  protocol?: string | null;
  media_type?: string | null;
  has_video_ts?: boolean;
  media_file_count?: number | null;
  media_count_capped?: boolean;
  kind: string;
  mode: string;
  importable?: boolean;
};

export function ImportModal() {
  const open = useAppStore((s) => s.importOpen);
  const minimized = useAppStore((s) => s.importMinimized);
  const expandImport = useAppStore((s) => s.expandImport);
  const minimizeImport = useAppStore((s) => s.minimizeImport);
  const closeImport = useAppStore((s) => s.closeImport);
  const trackImport = useAppStore((s) => s.trackImport);
  const router = useRouter();

  const [mode, setMode] = useState<Mode>("disc");
  const [path, setPath] = useState("");
  const [volumeName, setVolumeName] = useState("");
  const [batchText, setBatchText] = useState("");
  const [volumes, setVolumes] = useState<MountedVolume[]>([]);
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());
  const [scanning, setScanning] = useState(false);
  const [lastScan, setLastScan] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [newPaths, setNewPaths] = useState<Set<string>>(new Set());
  const knownPathsRef = useRef<Set<string>>(new Set());
  /** When true, next open restores session instead of wiping selection */
  const preserveSessionRef = useRef(false);
  /** Track minimize so TopBar “Import · expand” also restores form */
  const wasMinimizedRef = useRef(false);

  const sessionActive = open || minimized;

  function resetForm() {
    setMode("disc");
    setPath("");
    setVolumeName("");
    setBatchText("");
    setSelectedPaths(new Set());
    setError(null);
    setNewPaths(new Set());
    setStarting(false);
  }

  function handleClose() {
    preserveSessionRef.current = false;
    wasMinimizedRef.current = false;
    closeImport();
    resetForm();
  }

  function handleMinimize() {
    preserveSessionRef.current = true;
    wasMinimizedRef.current = true;
    minimizeImport();
  }

  function handleExpand() {
    preserveSessionRef.current = true;
    expandImport();
  }

  useEffect(() => {
    if (minimized) wasMinimizedRef.current = true;
  }, [minimized]);

  /** Full scan with media counts — open / manual Rescan only */
  const refreshVolumes = useCallback(async (opts?: { quiet?: boolean }) => {
    const quiet = opts?.quiet ?? false;
    if (!quiet) setScanning(true);
    try {
      const list = (await api.importVolumes(true)) as MountedVolume[];
      const next = new Set(list.map((v) => v.path));
      const prev = knownPathsRef.current;
      if (prev.size > 0) {
        const arrived = new Set<string>();
        for (const p of next) {
          if (!prev.has(p)) arrived.add(p);
        }
        if (arrived.size) setNewPaths((old) => new Set([...old, ...arrived]));
      }
      knownPathsRef.current = next;
      setVolumes(list);
      if (!quiet) setLastScan(new Date());
    } catch {
      /* offline */
    } finally {
      if (!quiet) setScanning(false);
    }
  }, []);

  /**
   * Lightweight poll: list volumes only (no media file walk).
   * Full rescan only when mount set changes (insert / eject).
   */
  const pollMounts = useCallback(async () => {
    try {
      const list = (await api.importVolumes(false)) as MountedVolume[];
      const next = new Set(list.map((v) => v.path));
      const prev = knownPathsRef.current;
      let changed = next.size !== prev.size;
      if (!changed) {
        for (const p of next) {
          if (!prev.has(p)) {
            changed = true;
            break;
          }
        }
      }
      if (!changed) return;

      const arrived = new Set<string>();
      for (const p of next) {
        if (!prev.has(p)) arrived.add(p);
      }
      if (arrived.size) setNewPaths((old) => new Set([...old, ...arrived]));
      knownPathsRef.current = next;

      // Mount set changed — one full scan for counts/details
      setScanning(true);
      try {
        const full = (await api.importVolumes(true)) as MountedVolume[];
        knownPathsRef.current = new Set(full.map((v) => v.path));
        setVolumes(full);
        setLastScan(new Date());
      } finally {
        setScanning(false);
      }
    } catch {
      /* offline */
    }
  }, []);

  // While dialog is open or minimized: scan mounts so discs still appear when expanded.
  useEffect(() => {
    if (!sessionActive) return;
    const restore = preserveSessionRef.current || wasMinimizedRef.current;
    // Full rescan when opening a fresh session; quiet poll after restore/minimize
    if (open && !restore) {
      knownPathsRef.current = new Set();
      void refreshVolumes({ quiet: false });
    } else if (sessionActive) {
      void refreshVolumes({ quiet: true });
    }
    const id = setInterval(() => {
      void pollMounts();
    }, 12_000);
    return () => clearInterval(id);
  }, [sessionActive, open, refreshVolumes, pollMounts]);

  // Cold open only: clear selection (not when restoring from minimize)
  useEffect(() => {
    if (!open) return;
    if (preserveSessionRef.current || wasMinimizedRef.current) {
      preserveSessionRef.current = false;
      wasMinimizedRef.current = false;
      return;
    }
    setSelectedPaths(new Set());
    setError(null);
    setNewPaths(new Set());
  }, [open]);

  // Escape: minimize when open (free UI), don't hard-close
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        handleMinimize();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const selectedVolumes = useMemo(
    () => volumes.filter((v) => selectedPaths.has(v.path)),
    [volumes, selectedPaths],
  );

  function selectVolume(v: MountedVolume, multi: boolean) {
    setMode("disc");
    setPath(v.path);
    setVolumeName(v.name);
    setSelectedPaths((prev) => {
      const next = new Set(multi ? prev : []);
      if (multi && next.has(v.path)) next.delete(v.path);
      else next.add(v.path);
      // Keep path/name on primary selection
      if (next.size === 1) {
        const only = [...next][0];
        const vol = volumes.find((x) => x.path === only) || v;
        setPath(vol.path);
        setVolumeName(vol.name);
      }
      return next;
    });
  }

  async function startImport(override?: {
    paths?: string[];
    mode?: Mode;
  }) {
    setError(null);
    setStarting(true);
    try {
      const m = override?.mode ?? mode;
      let body: Parameters<typeof api.startImport>[0];
      let label = "Import";

      const multi = override?.paths ?? [...selectedPaths];

      if (multi.length > 1 || (m === "batch" && multi.length >= 1)) {
        const sources =
          multi.length > 0
            ? multi.map((p) => {
                const vol = volumes.find((v) => v.path === p);
                return {
                  path: p,
                  name: vol?.name,
                  mode: "disc" as const,
                };
              })
            : batchText
                .split("\n")
                .map((l) => l.trim())
                .filter(Boolean)
                .map((p) => ({ path: p, mode: "folder" as const }));
        if (!sources.length) throw new Error("Select at least one disc or path");
        body = { mode: "batch", sources };
        label =
          sources.length === 1
            ? ("name" in sources[0] && sources[0].name) || sources[0].path
            : `${sources.length} discs`;
      } else if (m === "batch") {
        const lines = batchText
          .split("\n")
          .map((l) => l.trim())
          .filter(Boolean);
        if (!lines.length) throw new Error("Add at least one path (one per line)");
        body = {
          mode: "batch",
          sources: lines.map((p) => ({ path: p, mode: "folder" })),
        };
        label = `${lines.length} paths`;
      } else if (m === "disc") {
        const p = override?.paths?.[0] || path.trim();
        if (!p) throw new Error("Select a mounted disc or enter a path");
        const vol = volumes.find((v) => v.path === p);
        const name = volumeName.trim() || vol?.name || p;
        body = {
          mode: "disc",
          path: p,
          volume_name: name,
        };
        label = name;
      } else {
        if (!path.trim()) throw new Error("Enter a folder or file path");
        body = {
          mode: "media",
          path: path.trim(),
          volume_name: volumeName.trim() || undefined,
        };
        label = volumeName.trim() || path.trim().split("/").pop() || "Media";
      }
      const res = await api.startImport(body);
      // Track live panel + free the UI immediately
      trackImport(res.job_id, label);
      closeImport();
      resetForm();
      router.push("/library");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed to start");
    } finally {
      setStarting(false);
    }
  }

  const running = starting;
  const optical = volumes.filter((v) => v.kind === "optical" || v.is_optical);
  const other = volumes.filter((v) => !(v.kind === "optical" || v.is_optical));

  const selectionHint =
    selectedPaths.size > 0
      ? `${selectedPaths.size} selected`
      : path.trim()
        ? path.split("/").pop() || "path set"
        : volumes.length
          ? `${volumes.length} volume${volumes.length === 1 ? "" : "s"}`
          : "waiting for media";

  // Minimized dock — library UI free; click to restore full dialog
  if (minimized && !open) {
    return (
      <div className="pointer-events-none fixed bottom-4 left-4 z-40">
        <div className="pointer-events-auto flex max-w-[min(100vw-2rem,320px)] items-center gap-1 rounded-xl border border-[var(--accent)]/40 bg-[var(--bg-elevated)]/95 py-1.5 pl-1.5 pr-1 shadow-2xl backdrop-blur-md">
          <button
            type="button"
            onClick={handleExpand}
            className="group flex min-w-0 flex-1 items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition hover:bg-[var(--bg-selected)]"
            title="Expand import dialog"
          >
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--accent)]/15 text-[var(--accent)]">
              {scanning ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <HardDriveDownload className="h-4 w-4" />
              )}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-[12px] font-medium text-[var(--text-primary)]">
                Import ready
              </span>
              <span className="block truncate text-[10px] text-[var(--text-muted)]">
                {selectionHint}
                {newPaths.size > 0 ? ` · ${newPaths.size} new` : ""}
                {" · expand"}
              </span>
            </span>
            <Maximize2 className="h-3.5 w-3.5 shrink-0 text-[var(--accent)] opacity-80 group-hover:opacity-100" />
          </button>
          <button
            type="button"
            onClick={handleClose}
            className="mr-0.5 rounded p-1.5 text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
            aria-label="Dismiss import session"
            title="Dismiss"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    );
  }

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={(e) => {
        // Backdrop click minimizes (keeps selection) instead of hard-close
        if (e.target === e.currentTarget) handleMinimize();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="import-title"
        className="flex max-h-[92vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--bg-elevated)] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
          <div>
            <h2 id="import-title" className="text-[15px] font-semibold">
              Import media
            </h2>
            <p className="text-[11px] text-[var(--text-muted)]">
              Auto-detects mounted discs — click a disc to select the full volume.
              Minimize to keep browsing the library.
            </p>
          </div>
          <div className="flex items-center gap-0.5">
            <button
              type="button"
              onClick={handleMinimize}
              className="rounded p-1.5 text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
              aria-label="Minimize import — free the UI"
              title="Minimize (Esc) — free UI, keep selection"
            >
              <Minus className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={handleClose}
              className="rounded p-1.5 text-[var(--text-muted)] hover:bg-[var(--bg-hover)]"
              aria-label="Close"
              title="Close and discard"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          {/* Detected media */}
          <section>
            <div className="mb-2 flex items-center justify-between">
              <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-[var(--text-muted)]">
                <Disc3 className="h-3.5 w-3.5 text-[var(--accent)]" />
                Mounted media
                {scanning && (
                  <Loader2 className="h-3 w-3 animate-spin text-[var(--accent)]" />
                )}
                {lastScan && (
                  <span className="normal-case tracking-normal text-[10px]">
                    · scanned {lastScan.toLocaleTimeString()}
                  </span>
                )}
              </div>
              <button
                type="button"
                onClick={() => void refreshVolumes({ quiet: false })}
                disabled={scanning || !!running}
                className="inline-flex items-center gap-1 rounded border border-[var(--border)] px-2 py-1 text-[11px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
              >
                <RefreshCw className={cn("h-3 w-3", scanning && "animate-spin")} />
                Rescan
              </button>
            </div>

            {volumes.length === 0 ? (
              <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--bg-base)] px-4 py-8 text-center">
                <Disc3 className="mx-auto mb-2 h-8 w-8 text-[var(--text-muted)]" />
                <p className="text-[13px] text-[var(--text-primary)]">
                  No removable media detected
                </p>
                <p className="mt-1 text-[12px] text-[var(--text-muted)]">
                  Insert a DVD/CD or mount a USB drive — it will appear here automatically.
                </p>
              </div>
            ) : (
              <div className="space-y-2">
                {optical.length > 0 && (
                  <VolumeGroup
                    title="Optical discs"
                    volumes={optical}
                    selectedPaths={selectedPaths}
                    newPaths={newPaths}
                    disabled={!!running}
                    onSelect={selectVolume}
                    onImportFull={(v) => {
                      selectVolume(v, false);
                      void startImport({ paths: [v.path], mode: "disc" });
                    }}
                  />
                )}
                {other.length > 0 && (
                  <VolumeGroup
                    title={optical.length ? "Other volumes" : "Volumes"}
                    volumes={other}
                    selectedPaths={selectedPaths}
                    newPaths={newPaths}
                    disabled={!!running}
                    onSelect={selectVolume}
                    onImportFull={(v) => {
                      selectVolume(v, false);
                      void startImport({ paths: [v.path], mode: "disc" });
                    }}
                  />
                )}
                <p className="text-[10px] text-[var(--text-muted)]">
                  Click to select · ⌘/Ctrl-click multi-select · Import full disc starts recursive
                  ingest of the whole volume
                </p>
              </div>
            )}
          </section>

          {/* Mode tabs for manual paths */}
          <div className="grid grid-cols-3 gap-1.5">
            <ModeTab
              active={mode === "disc"}
              onClick={() => setMode("disc")}
              icon={<Disc3 className="h-4 w-4" />}
              label="Full disc"
              hint="Selected volume"
            />
            <ModeTab
              active={mode === "media"}
              onClick={() => setMode("media")}
              icon={<FolderOpen className="h-4 w-4" />}
              label="Folder / file"
              hint="Loose media"
            />
            <ModeTab
              active={mode === "batch"}
              onClick={() => setMode("batch")}
              icon={<Layers className="h-4 w-4" />}
              label="Batch paths"
              hint="Manual list"
            />
          </div>

          {mode !== "batch" ? (
            <div className="space-y-3">
              <Field label="Path (auto-filled when you click a disc)">
                <input
                  value={path}
                  onChange={(e) => setPath(e.target.value)}
                  spellCheck={false}
                  disabled={!!running}
                  placeholder="/Volumes/FAMILY_DVD"
                  className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 font-mono text-[13px]"
                />
              </Field>
              <Field label="Label (optional)">
                <input
                  value={volumeName}
                  onChange={(e) => setVolumeName(e.target.value)}
                  disabled={!!running}
                  placeholder="Family holiday 2008"
                  className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-[13px]"
                />
              </Field>
            </div>
          ) : (
            <Field label="Paths — one absolute path per line">
              <textarea
                value={batchText}
                onChange={(e) => setBatchText(e.target.value)}
                disabled={!!running}
                rows={5}
                placeholder={"/Volumes/DISC1\n/Volumes/DISC2"}
                className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 font-mono text-[12px]"
              />
            </Field>
          )}

          {selectedVolumes.length > 0 && (
            <div className="rounded-md border border-[var(--accent)]/30 bg-[var(--bg-selected)] px-3 py-2 text-[12px]">
              <span className="font-medium text-[var(--text-primary)]">
                {selectedVolumes.length} disc{selectedVolumes.length > 1 ? "s" : ""} selected
              </span>
              <span className="text-[var(--text-muted)]">
                {" "}
                — {selectedVolumes.map((v) => v.name).join(", ")}
              </span>
            </div>
          )}

          {error && (
            <div className="rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-3 py-2 text-[12px] text-[var(--danger)]">
              {error}
            </div>
          )}

          <div className="rounded-md border border-[var(--accent)]/25 bg-[var(--accent)]/5 px-3 py-2 text-[11px] text-[var(--text-secondary)]">
            <strong className="text-[var(--text-primary)]">Copy-first pipeline:</strong> files land
            in staging on your library SSD. When copy finishes,{" "}
            <strong className="text-[var(--text-primary)]">eject and insert the next disc</strong>
            — classification (EXIF / VLM / promote) runs in the background and never blocks the
            next copy. Discs are processed in series. Minimize (Esc) frees the UI.
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-[var(--border)] px-4 py-3">
          <button
            type="button"
            onClick={handleMinimize}
            className="mr-auto inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] px-3 py-2 text-[12px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
            title="Collapse to dock — keep browsing"
          >
            <Minus className="h-3.5 w-3.5" />
            Minimize
          </button>
          <button
            type="button"
            onClick={handleClose}
            className="rounded-md px-3 py-2 text-[12px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
          >
            Cancel
          </button>
          {selectedPaths.size > 1 && (
            <button
              type="button"
              disabled={starting}
              onClick={() => startImport({ mode: "batch" })}
              className="inline-flex items-center gap-1.5 rounded-md border border-[var(--accent)] px-3 py-2 text-[12px] font-medium text-[var(--accent)] hover:bg-[var(--bg-selected)] disabled:opacity-50"
            >
              <Layers className="h-3.5 w-3.5" />
              Import {selectedPaths.size} discs
            </button>
          )}
          <button
            type="button"
            disabled={
              starting || (selectedPaths.size === 0 && !path.trim() && mode !== "batch")
            }
            onClick={() => startImport()}
            className="inline-flex items-center gap-1.5 rounded-md bg-[var(--accent)] px-3 py-2 text-[12px] font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-50"
          >
            {starting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Play className="h-3.5 w-3.5" />
            )}
            {starting
              ? "Starting…"
              : selectedPaths.size === 1
                ? "Import full disc"
                : selectedPaths.size > 1
                  ? `Import ${selectedPaths.size} discs`
                  : "Start import"}
          </button>
        </div>
      </div>
    </div>
  );
}

function VolumeGroup({
  title,
  volumes,
  selectedPaths,
  newPaths,
  disabled,
  onSelect,
  onImportFull,
}: {
  title: string;
  volumes: MountedVolume[];
  selectedPaths: Set<string>;
  newPaths: Set<string>;
  disabled?: boolean;
  onSelect: (v: MountedVolume, multi: boolean) => void;
  onImportFull: (v: MountedVolume) => void;
}) {
  return (
    <div>
      <div className="mb-1.5 text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
        {title}
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {volumes.map((v) => {
          const selected = selectedPaths.has(v.path);
          const isNew = newPaths.has(v.path);
          return (
            <button
              key={v.path}
              type="button"
              disabled={disabled}
              onClick={(e) => onSelect(v, e.metaKey || e.ctrlKey)}
              onDoubleClick={() => onImportFull(v)}
              className={cn(
                "relative flex flex-col gap-1 rounded-lg border p-3 text-left transition-colors",
                selected
                  ? "border-[var(--accent)] bg-[var(--bg-selected)] ring-1 ring-[var(--accent)]/40"
                  : "border-[var(--border)] bg-[var(--bg-base)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)]",
                disabled && "opacity-60",
              )}
            >
              <div className="flex items-start gap-2">
                <div
                  className={cn(
                    "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md",
                    v.is_optical
                      ? "bg-[var(--accent)]/15 text-[var(--accent)]"
                      : "bg-[var(--bg-hover)] text-[var(--text-secondary)]",
                  )}
                >
                  {v.is_optical ? (
                    <Disc3 className="h-4 w-4" />
                  ) : (
                    <HardDrive className="h-4 w-4" />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="truncate text-[13px] font-medium text-[var(--text-primary)]">
                      {v.name}
                    </span>
                    {selected && (
                      <Check className="h-3.5 w-3.5 shrink-0 text-[var(--accent)]" />
                    )}
                    {isNew && (
                      <span className="shrink-0 rounded bg-[var(--success)]/20 px-1.5 py-0.5 text-[9px] font-medium uppercase text-[var(--success)]">
                        New
                      </span>
                    )}
                  </div>
                  <div className="truncate font-mono text-[10px] text-[var(--text-muted)]">
                    {v.path}
                  </div>
                </div>
              </div>
              <div className="flex flex-wrap gap-1.5 text-[10px] text-[var(--text-muted)]">
                <Badge>
                  {v.kind === "optical"
                    ? v.media_type || "Optical"
                    : v.kind === "removable"
                      ? "Removable"
                      : v.kind === "external"
                        ? "External"
                        : "Volume"}
                </Badge>
                {v.filesystem && <Badge>{v.filesystem}</Badge>}
                {v.has_video_ts && <Badge>VIDEO_TS</Badge>}
                {v.media_file_count != null && (
                  <Badge>
                    {v.media_file_count}
                    {v.media_count_capped ? "+" : ""} media
                  </Badge>
                )}
                {v.total_bytes != null && <Badge>{formatBytes(v.total_bytes)}</Badge>}
              </div>
              <div className="mt-1 text-[10px] text-[var(--accent)] opacity-80">
                Double-click to import full disc →
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded border border-[var(--border)] px-1.5 py-0.5">
      {children}
    </span>
  );
}

function ModeTab({
  active,
  onClick,
  icon,
  label,
  hint,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  hint: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex flex-col items-start gap-0.5 rounded-lg border px-3 py-2.5 text-left transition-colors",
        active
          ? "border-[var(--accent)] bg-[var(--bg-selected)]"
          : "border-[var(--border)] hover:bg-[var(--bg-hover)]",
      )}
    >
      <span className="flex items-center gap-1.5 text-[12px] font-medium">
        {icon}
        {label}
      </span>
      <span className="text-[10px] text-[var(--text-muted)]">{hint}</span>
    </button>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] uppercase tracking-wider text-[var(--text-muted)]">
        {label}
      </span>
      {children}
    </label>
  );
}


