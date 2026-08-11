"use client";

import { useEffect } from "react";
import { X } from "lucide-react";
import { MEDIA_SHORTCUTS } from "@/lib/shortcuts";

type Props = {
  open: boolean;
  onClose: () => void;
};

export function ShortcutsHelp({ open, onClose }: Props) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" || e.key === "?" || e.key === "/") {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const groups = MEDIA_SHORTCUTS.reduce<Record<string, typeof MEDIA_SHORTCUTS>>(
    (acc, s) => {
      (acc[s.group] ||= []).push(s);
      return acc;
    },
    {},
  );

  return (
    <div
      className="fixed inset-0 z-[90] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Keyboard shortcuts"
      data-blocking-shortcuts="true"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="max-h-[min(90vh,640px)] w-full max-w-lg overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--bg-elevated)] shadow-xl">
        <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
          <div>
            <h2 className="text-[15px] font-semibold">Keyboard shortcuts</h2>
            <p className="text-[11px] text-[var(--text-muted)]">
              Lightroom-style — work the same in Library grid and lightbox
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="overflow-y-auto px-4 py-3">
          {Object.entries(groups).map(([group, rows]) => (
            <div key={group} className="mb-4 last:mb-0">
              <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                {group}
              </div>
              <ul className="space-y-1">
                {rows.map((row) => (
                  <li
                    key={row.label + row.keys.join()}
                    className="flex items-center justify-between gap-3 text-[12px]"
                  >
                    <span className="text-[var(--text-secondary)]">{row.label}</span>
                    <span className="flex shrink-0 flex-wrap justify-end gap-1">
                      {row.keys.map((k) => (
                        <kbd
                          key={k}
                          className="rounded border border-[var(--border)] bg-[var(--bg-base)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--text-primary)]"
                        >
                          {k}
                        </kbd>
                      ))}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="border-t border-[var(--border)] px-4 py-2 text-center text-[10px] text-[var(--text-muted)]">
          Press <kbd className="rounded border border-[var(--border)] px-1">?</kbd> or{" "}
          <kbd className="rounded border border-[var(--border)] px-1">Esc</kbd> to close
        </div>
      </div>
    </div>
  );
}
