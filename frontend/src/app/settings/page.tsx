"use client";

import { useCallback, useEffect, useState } from "react";
import {
  api,
  type AppSettings,
  type PathCheck,
  type VolumeSuggestion,
} from "@/lib/api";
import { cn, formatBytes } from "@/lib/utils";
import { APP_VERSION } from "@/lib/version";
import {
  FolderOpen,
  HardDrive,
  CheckCircle2,
  AlertCircle,
  Save,
  KeyRound,
  Eye,
  EyeOff,
  Trash2,
  Shield,
} from "lucide-react";

export default function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [libraryPath, setLibraryPath] = useState("");
  const [volumes, setVolumes] = useState<VolumeSuggestion[]>([]);
  const [check, setCheck] = useState<PathCheck | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ tone: "ok" | "err"; text: string } | null>(null);
  const [hfToken, setHfToken] = useState("");
  const [showHf, setShowHf] = useState(false);
  const [savingSecret, setSavingSecret] = useState(false);
  const [quality, setQuality] = useState({
    quality_enabled: true,
    quality_min_short_edge: 480,
    quality_min_long_edge: 640,
    quality_min_megapixels: 0.35,
    quality_reject_animated_gif: true,
    quality_reject_junk_paths: true,
    quality_quarantine_rejects: true,
  });

  const load = useCallback(async () => {
    try {
      const s = await api.settings();
      setSettings(s);
      setLibraryPath(s.library_root);
      setQuality({
        quality_enabled: s.quality_enabled,
        quality_min_short_edge: s.quality_min_short_edge,
        quality_min_long_edge: s.quality_min_long_edge,
        quality_min_megapixels: s.quality_min_megapixels,
        quality_reject_animated_gif: s.quality_reject_animated_gif,
        quality_reject_junk_paths: s.quality_reject_junk_paths,
        quality_quarantine_rejects: s.quality_quarantine_rejects,
      });
      // Never pre-fill secret fields with real values
      setHfToken("");
    } catch (e) {
      setMessage({
        tone: "err",
        text: e instanceof Error ? e.message : "Failed to load settings",
      });
    }
  }, []);

  useEffect(() => {
    load();
    api.volumes().then(setVolumes).catch(() => {});
  }, [load]);

  async function validatePath(path: string) {
    try {
      const r = await api.checkPath(path, false);
      setCheck(r);
      return r;
    } catch (e) {
      setCheck(null);
      setMessage({
        tone: "err",
        text: e instanceof Error ? e.message : "Path check failed",
      });
      return null;
    }
  }

  async function saveLibrary() {
    setSaving(true);
    setMessage(null);
    try {
      const s = await api.updateSettings({
        library_root: libraryPath.trim(),
        create_if_missing: true,
      });
      setSettings(s);
      setLibraryPath(s.library_root);
      setMessage({
        tone: "ok",
        text: `Library root set to ${s.library_root}`,
      });
      await validatePath(s.library_root);
    } catch (e) {
      setMessage({
        tone: "err",
        text: e instanceof Error ? e.message : "Save failed",
      });
    } finally {
      setSaving(false);
    }
  }

  async function saveQuality() {
    setSaving(true);
    setMessage(null);
    try {
      const s = await api.updateSettings(quality);
      setSettings(s);
      setMessage({ tone: "ok", text: "Quality settings saved" });
    } catch (e) {
      setMessage({
        tone: "err",
        text: e instanceof Error ? e.message : "Save failed",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-3xl space-y-8">
        <header>
          <h1 className="text-[18px] font-semibold tracking-tight">Settings</h1>
          <p className="mt-1 text-[13px] text-[var(--text-muted)]">
            Configure where NeuralDisc stores your archive. Path is saved to{" "}
            <code className="text-[var(--text-secondary)]">~/.neuraldisc/settings.toml</code>
            {" "}and survives restarts.
          </p>
        </header>

        {message && (
          <div
            className={cn(
              "flex items-start gap-2 rounded-md border px-3 py-2 text-[13px]",
              message.tone === "ok"
                ? "border-[var(--success)]/40 bg-[var(--success)]/10 text-[var(--success)]"
                : "border-[var(--danger)]/40 bg-[var(--danger)]/10 text-[var(--danger)]",
            )}
          >
            {message.tone === "ok" ? (
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
            ) : (
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            )}
            <span className="break-all">{message.text}</span>
          </div>
        )}

        {/* Library location */}
        <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)] p-4">
          <div className="mb-3 flex items-center gap-2">
            <FolderOpen className="h-4 w-4 text-[var(--accent)]" />
            <h2 className="text-[14px] font-medium">Library folder</h2>
          </div>
          <p className="mb-3 text-[12px] text-[var(--text-muted)]">
            Target root for <strong className="text-[var(--text-primary)]">everything</strong>:
            originals, <strong className="text-[var(--text-primary)]">staging/temp during import</strong>,
            derivatives, quarantine, SQLite, and logs. Nothing is written to the Mac internal disk
            or <code className="text-[var(--text-secondary)]">/tmp</code>. Prefer an external SSD
            such as <code className="text-[var(--text-secondary)]">/Volumes/MySSD/NeuralDisc</code>.
          </p>

          <label className="mb-1 block text-[11px] uppercase tracking-wider text-[var(--text-muted)]">
            Absolute path
          </label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              value={libraryPath}
              onChange={(e) => {
                setLibraryPath(e.target.value);
                setCheck(null);
              }}
              onBlur={() => libraryPath.trim() && validatePath(libraryPath.trim())}
              spellCheck={false}
              className="min-w-0 flex-1 rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 font-mono text-[13px] text-[var(--text-primary)] focus:border-[var(--border-strong)] focus:outline-none"
              placeholder="/Volumes/ExternalSSD/NeuralDisc"
            />
            <button
              type="button"
              onClick={() => validatePath(libraryPath.trim())}
              className="rounded-md border border-[var(--border)] px-3 py-2 text-[12px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
            >
              Check
            </button>
            <button
              type="button"
              disabled={saving || !libraryPath.trim()}
              onClick={saveLibrary}
              className="inline-flex items-center justify-center gap-1.5 rounded-md bg-[var(--accent)] px-3 py-2 text-[12px] font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-50"
            >
              <Save className="h-3.5 w-3.5" />
              Save &amp; use
            </button>
          </div>

          {check && (
            <div
              className={cn(
                "mt-3 rounded-md border px-3 py-2 text-[12px]",
                check.ok
                  ? "border-[var(--success)]/30 text-[var(--text-secondary)]"
                  : "border-[var(--warning)]/40 text-[var(--warning)]",
              )}
            >
              <div className="font-medium text-[var(--text-primary)]">{check.message}</div>
              <div className="mt-1 font-mono text-[11px] text-[var(--text-muted)]">{check.path}</div>
              {check.free_bytes != null && (
                <div className="mt-1">
                  Free space: {formatBytes(check.free_bytes)}
                  {check.total_bytes != null && ` / ${formatBytes(check.total_bytes)}`}
                </div>
              )}
            </div>
          )}

          {settings && (
            <dl className="mt-4 grid grid-cols-1 gap-2 text-[12px] sm:grid-cols-2">
              <Info label="Current root" value={settings.library_root} mono />
              <Info
                label="Status"
                value={
                  settings.library_writable
                    ? settings.library_exists
                      ? "Exists · writable"
                      : "Missing · will create"
                    : "Not writable"
                }
              />
              <Info
                label="Staging / temp (import)"
                value={settings.staging_dir || `${settings.library_root}/library/staging`}
                mono
              />
              <Info
                label="Temp on target"
                value={
                  settings.temp_on_target === false
                    ? "ERROR — staging not under library!"
                    : "Yes — all temp under library folder"
                }
              />
              <Info label="Originals" value={settings.originals_dir} mono />
              <Info
                label="Quarantine"
                value={
                  settings.quarantine_dir || `${settings.library_root}/library/quarantine`
                }
                mono
              />
              <Info
                label="Derivatives"
                value={
                  settings.derivatives_dir ||
                  `${settings.library_root}/library/derivatives`
                }
                mono
              />
              <Info label="Database" value={settings.sqlite_path} mono />
              <Info label="Media in DB" value={String(settings.media_count)} />
              <Info label="Discs ingested" value={String(settings.disc_count)} />
              {settings.free_bytes != null && (
                <Info label="Free space" value={formatBytes(settings.free_bytes)} />
              )}
              <Info label="Prefs file" value={settings.prefs_file} mono />
            </dl>
          )}

          {volumes.length > 0 && (
            <div className="mt-4">
              <div className="mb-2 flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-[var(--text-muted)]">
                <HardDrive className="h-3.5 w-3.5" />
                Suggestions
              </div>
              <div className="flex flex-wrap gap-1.5">
                {volumes.slice(0, 12).map((v) => (
                  <button
                    key={v.path + v.name}
                    type="button"
                    onClick={() => {
                      setLibraryPath(v.path);
                      setCheck(null);
                      void validatePath(v.path);
                    }}
                    className="rounded-full border border-[var(--border)] px-2.5 py-1 text-[11px] text-[var(--text-secondary)] hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
                    title={v.path}
                  >
                    {v.name}
                    {v.is_optical && " · optical"}
                  </button>
                ))}
              </div>
            </div>
          )}
        </section>

        {/* Quality gates */}
        <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)] p-4">
          <h2 className="mb-1 text-[14px] font-medium">Quality gates</h2>
          <p className="mb-4 text-[12px] text-[var(--text-muted)]">
            Reject tiny web junk, vectors, and low-value downloads before they enter the library.
          </p>

          <div className="space-y-3">
            <Toggle
              label="Enable quality filtering"
              checked={quality.quality_enabled}
              onChange={(v) => setQuality((q) => ({ ...q, quality_enabled: v }))}
            />
            <Toggle
              label="Reject animated GIFs"
              checked={quality.quality_reject_animated_gif}
              onChange={(v) => setQuality((q) => ({ ...q, quality_reject_animated_gif: v }))}
            />
            <Toggle
              label="Reject junk path names (thumb, favicon, meme, …)"
              checked={quality.quality_reject_junk_paths}
              onChange={(v) => setQuality((q) => ({ ...q, quality_reject_junk_paths: v }))}
            />
            <Toggle
              label="Quarantine rejected files"
              checked={quality.quality_quarantine_rejects}
              onChange={(v) => setQuality((q) => ({ ...q, quality_quarantine_rejects: v }))}
            />

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <NumberField
                label="Min short edge (px)"
                value={quality.quality_min_short_edge}
                onChange={(v) => setQuality((q) => ({ ...q, quality_min_short_edge: v }))}
              />
              <NumberField
                label="Min long edge (px)"
                value={quality.quality_min_long_edge}
                onChange={(v) => setQuality((q) => ({ ...q, quality_min_long_edge: v }))}
              />
              <NumberField
                label="Min megapixels"
                value={quality.quality_min_megapixels}
                step={0.05}
                onChange={(v) => setQuality((q) => ({ ...q, quality_min_megapixels: v }))}
              />
            </div>
          </div>

          <button
            type="button"
            disabled={saving}
            onClick={saveQuality}
            className="mt-4 inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] px-3 py-2 text-[12px] text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
          >
            <Save className="h-3.5 w-3.5" />
            Save quality settings
          </button>
        </section>

        {/* API tokens — encrypted at rest */}
        <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)] p-4">
          <div className="mb-2 flex items-center gap-2">
            <KeyRound className="h-4 w-4 text-[var(--accent)]" />
            <h2 className="text-[14px] font-medium">API tokens &amp; keys</h2>
          </div>
          <p className="mb-3 text-[12px] text-[var(--text-muted)]">
            Stored encrypted under <code className="text-[var(--text-secondary)]">~/.neuraldisc/</code>{" "}
            (mode 0600). Never written to the library folder or git. The UI only shows a masked
            preview — full values are never returned by the API.
          </p>

          <div className="mb-3 flex flex-wrap items-center gap-2 text-[11px]">
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-full border px-2 py-0.5",
                settings?.secrets?.huggingface_token?.configured
                  ? "border-[var(--success)]/40 text-[var(--success)]"
                  : "border-[var(--border)] text-[var(--text-muted)]",
              )}
            >
              <Shield className="h-3 w-3" />
              Hugging Face:{" "}
              {settings?.secrets?.huggingface_token?.configured
                ? settings.secrets.huggingface_token.masked || "configured"
                : "not set"}
            </span>
            {settings?.secrets_secure === false && (
              <span className="text-[var(--danger)]">Warning: secret file permissions too open</span>
            )}
          </div>

          <label className="mb-1 block text-[11px] uppercase tracking-wider text-[var(--text-muted)]">
            Hugging Face token
          </label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <div className="relative min-w-0 flex-1">
              <input
                type={showHf ? "text" : "password"}
                value={hfToken}
                onChange={(e) => setHfToken(e.target.value)}
                autoComplete="off"
                autoCorrect="off"
                spellCheck={false}
                name="hf-token"
                placeholder={
                  settings?.secrets?.huggingface_token?.configured
                    ? "•••• paste new token to replace"
                    : "hf_…"
                }
                className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 pr-10 font-mono text-[13px]"
              />
              <button
                type="button"
                onClick={() => setShowHf((v) => !v)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                aria-label={showHf ? "Hide token" : "Show token"}
              >
                {showHf ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
            <button
              type="button"
              disabled={savingSecret || !hfToken.trim()}
              onClick={async () => {
                setSavingSecret(true);
                setMessage(null);
                try {
                  const st = await api.putSecret("huggingface_token", hfToken.trim());
                  setHfToken("");
                  setSettings((s) =>
                    s
                      ? {
                          ...s,
                          secrets: st.secrets,
                          secrets_secure: st.secrets_secure,
                        }
                      : s,
                  );
                  setMessage({
                    tone: "ok",
                    text: "Hugging Face token saved (encrypted). Used for model downloads.",
                  });
                } catch (e) {
                  setMessage({
                    tone: "err",
                    text: e instanceof Error ? e.message : "Failed to save token",
                  });
                } finally {
                  setSavingSecret(false);
                }
              }}
              className="inline-flex items-center justify-center gap-1.5 rounded-md bg-[var(--accent)] px-3 py-2 text-[12px] font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-50"
            >
              <Save className="h-3.5 w-3.5" />
              Save token
            </button>
            {settings?.secrets?.huggingface_token?.configured && (
              <button
                type="button"
                disabled={savingSecret}
                onClick={async () => {
                  if (!confirm("Remove Hugging Face token from this machine?")) return;
                  setSavingSecret(true);
                  try {
                    const st = await api.deleteSecret("huggingface_token");
                    setSettings((s) =>
                      s
                        ? {
                            ...s,
                            secrets: st.secrets,
                            secrets_secure: st.secrets_secure,
                          }
                        : s,
                    );
                    setMessage({ tone: "ok", text: "Hugging Face token removed" });
                  } catch (e) {
                    setMessage({
                      tone: "err",
                      text: e instanceof Error ? e.message : "Delete failed",
                    });
                  } finally {
                    setSavingSecret(false);
                  }
                }}
                className="inline-flex items-center gap-1 rounded-md border border-[var(--danger)]/40 px-3 py-2 text-[12px] text-[var(--danger)] hover:bg-[var(--danger)]/10"
              >
                <Trash2 className="h-3.5 w-3.5" />
                Clear
              </button>
            )}
          </div>
          <p className="mt-2 text-[11px] text-[var(--text-muted)]">
            Required for authenticated Hugging Face model downloads (VLM / embeddings). Token is
            never shown again after save.
          </p>
        </section>

        {settings && (
          <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)] p-4">
            <h2 className="mb-2 text-[14px] font-medium">Metadata tooling</h2>
            <dl className="grid grid-cols-1 gap-2 text-[12px] sm:grid-cols-2">
              <div className="rounded-md border border-[var(--border)]/60 bg-[var(--bg-base)] px-2.5 py-2">
                <dt className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
                  exiftool
                </dt>
                <dd
                  className={
                    settings.exiftool_ok ? "text-[var(--success)]" : "text-[var(--danger)]"
                  }
                >
                  {settings.exiftool_ok
                    ? `OK · v${settings.exiftool_version || "?"}`
                    : "Missing — brew install exiftool (required)"}
                </dd>
              </div>
              {settings.exiftool_path && (
                <div className="rounded-md border border-[var(--border)]/60 bg-[var(--bg-base)] px-2.5 py-2">
                  <dt className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
                    Path
                  </dt>
                  <dd className="break-all font-mono text-[11px] text-[var(--text-secondary)]">
                    {settings.exiftool_path}
                  </dd>
                </div>
              )}
            </dl>
            <p className="mt-2 text-[11px] text-[var(--text-muted)]">
              All EXIF (date, camera, GPS, lens) is read only via ExifTool. Pillow is not used
              for metadata.
            </p>
          </section>
        )}

        {settings && (
          <p className="text-[11px] text-[var(--text-muted)]">
            API v{settings.version} · UI v{APP_VERSION} · local-first · no cloud
          </p>
        )}
      </div>
    </div>
  );
}

function Info({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="rounded-md border border-[var(--border)]/60 bg-[var(--bg-base)] px-2.5 py-2">
      <dt className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">{label}</dt>
      <dd
        className={cn(
          "mt-0.5 break-all text-[var(--text-secondary)]",
          mono && "font-mono text-[11px]",
        )}
      >
        {value}
      </dd>
    </div>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-3 text-[13px]">
      <span className="text-[var(--text-secondary)]">{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative h-5 w-9 shrink-0 rounded-full transition-colors",
          checked ? "bg-[var(--accent)]" : "bg-[var(--border-strong)]",
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform",
            checked ? "left-4" : "left-0.5",
          )}
        />
      </button>
    </label>
  );
}

function NumberField({
  label,
  value,
  onChange,
  step = 1,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  step?: number;
}) {
  return (
    <label className="block text-[12px]">
      <span className="text-[11px] text-[var(--text-muted)]">{label}</span>
      <input
        type="number"
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-1 w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-2 py-1.5 font-mono text-[13px]"
      />
    </label>
  );
}
