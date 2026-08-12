"use client";

import { useEffect, useState } from "react";
import { Disc3 } from "lucide-react";
import { api } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { formatBytes } from "@/lib/utils";

/**
 * Apple-style sheet after a disc finishes copying.
 * Ask: insert next disc, or finished for now.
 * Auto-eject may already have freed the drive; otherwise offer Eject.
 */
export function DiscReadyDialog() {
  const prompt = useAppStore((s) => s.discReadyPrompt);
  const continueNextDisc = useAppStore((s) => s.continueNextDisc);
  const finishDiscSession = useAppStore((s) => s.finishDiscSession);
  const [visible, setVisible] = useState(false);
  const [newVolumeHint, setNewVolumeHint] = useState<string | null>(null);
  const [ejecting, setEjecting] = useState(false);
  const [ejectError, setEjectError] = useState<string | null>(null);
  const [manualEjected, setManualEjected] = useState(false);

  // Enter animation
  useEffect(() => {
    if (!prompt) {
      setVisible(false);
      setNewVolumeHint(null);
      setEjectError(null);
      setManualEjected(false);
      return;
    }
    const id = requestAnimationFrame(() => setVisible(true));
    return () => cancelAnimationFrame(id);
  }, [prompt]);

  // Light mount poll while dialog is open — hint when a new disc appears
  useEffect(() => {
    if (!prompt) return;
    let cancelled = false;
    let baseline: Set<string> | null = null;

    const tick = async () => {
      try {
        const list = await api.importVolumes(false);
        const paths = new Set(list.map((v) => v.path));
        if (baseline === null) {
          baseline = paths;
        } else {
          for (const p of paths) {
            if (!baseline.has(p)) {
              const vol = list.find((v) => v.path === p);
              if (!cancelled) {
                setNewVolumeHint(vol?.name || p.split("/").pop() || "New disc");
              }
              break;
            }
          }
        }
      } catch {
        /* offline */
      }
      if (!cancelled) setTimeout(tick, 4000);
    };

    tick();
    return () => {
      cancelled = true;
    };
  }, [prompt]);

  // Escape → finished (don’t trap the user)
  useEffect(() => {
    if (!prompt) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        finishDiscSession();
      } else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        continueNextDisc();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [prompt, finishDiscSession, continueNextDisc]);

  if (!prompt) return null;

  const alreadyEjected =
    manualEjected ||
    (prompt.ejectedPaths.length > 0 &&
      prompt.sourcePaths.every(
        (p) => prompt.ejectedPaths.includes(p) || !p.startsWith("/Volumes/"),
      ));
  const ejectPath =
    prompt.sourcePaths.find((p) => p.startsWith("/Volumes/")) ||
    prompt.sourcePaths[0] ||
    null;

  const stats =
    prompt.copied > 0
      ? `${prompt.copied.toLocaleString()} file${prompt.copied === 1 ? "" : "s"}` +
        (prompt.bytesCopied > 0 ? ` · ${formatBytes(prompt.bytesCopied)}` : "")
      : null;

  const onEject = async () => {
    if (!ejectPath || ejecting) return;
    setEjecting(true);
    setEjectError(null);
    try {
      await api.ejectVolume(ejectPath);
      setManualEjected(true);
    } catch (err) {
      setEjectError(err instanceof Error ? err.message : "Eject failed");
    } finally {
      setEjecting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-6"
      role="presentation"
    >
      <div
        className={`absolute inset-0 bg-black/55 backdrop-blur-md transition-opacity duration-300 ${
          visible ? "opacity-100" : "opacity-0"
        }`}
        onClick={() => finishDiscSession()}
        aria-hidden
      />

      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="disc-ready-title"
        aria-describedby="disc-ready-desc"
        data-blocking-shortcuts="true"
        className={`relative w-full max-w-[340px] overflow-hidden rounded-[22px] border border-white/[0.08] bg-[#1c1c1e]/92 shadow-[0_24px_80px_rgba(0,0,0,0.55)] backdrop-blur-xl transition-all duration-300 ${
          visible ? "translate-y-0 scale-100 opacity-100" : "translate-y-3 scale-[0.98] opacity-0"
        }`}
      >
        <div className="px-7 pb-2 pt-8 text-center">
          <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-full bg-white/[0.06]">
            <Disc3 className="h-7 w-7 text-[var(--accent)]" strokeWidth={1.5} />
          </div>
          <h2
            id="disc-ready-title"
            className="text-[20px] font-semibold tracking-tight text-white"
          >
            {alreadyEjected ? "Drive free" : "Disc ready"}
          </h2>
          <p
            id="disc-ready-desc"
            className="mt-2 text-[13px] leading-relaxed text-white/55"
          >
            <span className="font-medium text-white/80">{prompt.label}</span>
            {stats ? ` — ${stats} copied.` : " was copied."}
            <br />
            {alreadyEjected
              ? "Drive ejected. Insert the next disc — or finish for now."
              : "Eject this disc, then insert the next one — or finish for now."}
            <br />
            Classification continues in the background.
          </p>
          {ejectError && (
            <p className="mt-3 text-[12px] text-red-400">{ejectError}</p>
          )}
          {newVolumeHint && (
            <p className="mt-3 text-[12px] font-medium text-[var(--accent)]">
              Detected: {newVolumeHint}
            </p>
          )}
        </div>

        <div className="mt-5 flex flex-col border-t border-white/[0.08]">
          {!alreadyEjected && ejectPath && (
            <>
              <button
                type="button"
                disabled={ejecting}
                onClick={() => void onEject()}
                className="px-5 py-3.5 text-[16px] font-semibold text-white/90 transition hover:bg-white/[0.04] active:bg-white/[0.06] disabled:opacity-50"
              >
                {ejecting ? "Ejecting…" : "Eject disc"}
              </button>
              <div className="h-px bg-white/[0.08]" />
            </>
          )}
          <button
            type="button"
            onClick={() => continueNextDisc()}
            className="px-5 py-3.5 text-[16px] font-semibold text-[var(--accent-hover)] transition hover:bg-white/[0.04] active:bg-white/[0.06]"
          >
            {newVolumeHint ? "Import next disc" : "Insert next disc"}
          </button>
          <div className="h-px bg-white/[0.08]" />
          <button
            type="button"
            onClick={() => finishDiscSession()}
            className="px-5 py-3.5 text-[16px] font-normal text-white/70 transition hover:bg-white/[0.04] active:bg-white/[0.06]"
          >
            Finished
          </button>
        </div>
      </div>
    </div>
  );
}
