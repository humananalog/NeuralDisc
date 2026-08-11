"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, Trash2, X } from "lucide-react";
import { cn } from "@/lib/utils";

type Props = {
  count: number;
  filenames?: string[];
  /** When true, default to permanent purge (e.g. already in trash). */
  permanentDefault?: boolean;
  busy?: boolean;
  error?: string | null;
  onCancel: () => void;
  onConfirm: (permanent: boolean) => void | Promise<void>;
};

/**
 * Catalogue-style delete confirmation.
 * Soft-delete (Trash) is default; permanent requires explicit opt-in.
 * Batches of 10+ require typing DELETE (UI_UX.md).
 */
export function DeleteConfirmModal({
  count,
  filenames = [],
  permanentDefault = false,
  busy = false,
  error = null,
  onCancel,
  onConfirm,
}: Props) {
  const [permanent, setPermanent] = useState(permanentDefault);
  const [confirmText, setConfirmText] = useState("");
  const [localBusy, setLocalBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const isBusy = busy || localBusy;
  const needsTypeConfirm = permanent && count >= 10;
  const typeOk = !needsTypeConfirm || confirmText.trim().toUpperCase() === "DELETE";
  const displayError = localError || error;

  // Escape always closes (even while busy so the UI never traps the user)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  async function handleConfirm() {
    if (isBusy || !typeOk) return;
    setLocalError(null);
    setLocalBusy(true);
    try {
      await onConfirm(permanent);
      // Parent is responsible for closing on success
    } catch (e) {
      setLocalError(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setLocalBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/55 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div
        className="w-full max-w-md rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)] shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3 border-b border-[var(--border)] px-4 py-3">
          <div
            className={cn(
              "mt-0.5 rounded-full p-2",
              permanent
                ? "bg-[var(--danger)]/15 text-[var(--danger)]"
                : "bg-[var(--warning)]/15 text-[var(--warning)]",
            )}
          >
            {permanent ? (
              <AlertTriangle className="h-4 w-4" />
            ) : (
              <Trash2 className="h-4 w-4" />
            )}
          </div>
          <div className="min-w-0 flex-1">
            <h2
              id="delete-title"
              className="text-[14px] font-semibold text-[var(--text-primary)]"
            >
              {permanent
                ? `Permanently delete ${count} item${count === 1 ? "" : "s"}?`
                : `Move ${count} item${count === 1 ? "" : "s"} to Trash?`}
            </h2>
            <p className="mt-1 text-[12px] text-[var(--text-secondary)]">
              {permanent
                ? "This removes originals, derivatives, and catalogue records. It cannot be undone."
                : "Items leave the library but can be restored from Trash. Files stay on disk until permanently deleted."}
            </p>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="rounded p-1 text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {filenames.length > 0 && (
          <div className="max-h-28 overflow-y-auto border-b border-[var(--border)] px-4 py-2">
            <ul className="space-y-0.5 text-[11px] text-[var(--text-muted)]">
              {filenames.slice(0, 8).map((f) => (
                <li key={f} className="truncate font-mono">
                  {f}
                </li>
              ))}
              {filenames.length > 8 && (
                <li className="text-[var(--text-secondary)]">
                  +{filenames.length - 8} more
                </li>
              )}
            </ul>
          </div>
        )}

        <div className="space-y-3 px-4 py-3">
          {!permanentDefault && (
            <label className="flex cursor-pointer items-start gap-2 text-[12px] text-[var(--text-secondary)]">
              <input
                type="checkbox"
                checked={permanent}
                disabled={isBusy}
                onChange={(e) => setPermanent(e.target.checked)}
                className="mt-0.5"
              />
              <span>
                <span className="font-medium text-[var(--text-primary)]">
                  Delete permanently
                </span>
                <span className="block text-[11px] text-[var(--text-muted)]">
                  Skip Trash and erase files immediately
                </span>
              </span>
            </label>
          )}

          {needsTypeConfirm && (
            <div>
              <label className="mb-1 block text-[11px] text-[var(--text-muted)]">
                Type{" "}
                <span className="font-mono font-semibold text-[var(--danger)]">
                  DELETE
                </span>{" "}
                to confirm
              </label>
              <input
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                disabled={isBusy}
                autoFocus
                className="h-8 w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-2 font-mono text-[13px] text-[var(--text-primary)] focus:border-[var(--danger)] focus:outline-none"
                placeholder="DELETE"
              />
            </div>
          )}

          {displayError && (
            <div className="rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-2.5 py-2 text-[11px] text-[var(--danger)]">
              {displayError}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-[var(--border)] px-4 py-3">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-[var(--border)] px-3 py-1.5 text-[12px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={isBusy || !typeOk}
            onClick={() => void handleConfirm()}
            className={cn(
              "rounded-md px-3 py-1.5 text-[12px] font-medium text-white disabled:opacity-40",
              permanent
                ? "bg-[var(--danger)] hover:bg-[var(--danger)]/90"
                : "bg-[var(--warning)] hover:bg-[var(--warning)]/90",
            )}
          >
            {isBusy ? "Working…" : permanent ? "Delete forever" : "Move to Trash"}
          </button>
        </div>
      </div>
    </div>
  );
}
