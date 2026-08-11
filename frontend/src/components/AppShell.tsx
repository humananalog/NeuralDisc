"use client";

import { useEffect } from "react";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { ImportModal } from "./ImportModal";
import { ImportLivePanel } from "./ImportLivePanel";
import { api } from "@/lib/api";
import { useAppStore } from "@/lib/store";

export function AppShell({ children }: { children: React.ReactNode }) {
  const setNavCounts = useAppStore((s) => s.setNavCounts);
  const libraryEpoch = useAppStore((s) => s.libraryEpoch);
  const liveImports = useAppStore((s) => s.liveImports);
  const importActive = liveImports.some(
    (j) =>
      !j.dismissed &&
      (!j.status ||
        (j.status.status !== "completed" &&
          j.status.status !== "failed" &&
          j.status.status !== "cancelled")),
  );

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const counts = await api.navCounts();
        if (!cancelled) setNavCounts(counts);
      } catch {
        /* offline */
      }
    };
    tick();
    // Faster badge updates while an import is streaming in
    const id = setInterval(tick, importActive ? 2000 : 5000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [setNavCounts, importActive, libraryEpoch]);

  return (
    <div className="flex h-screen overflow-hidden bg-[var(--bg-base)] text-[var(--text-primary)]">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="min-h-0 flex-1 overflow-hidden">{children}</main>
      </div>
      <ImportModal />
      <ImportLivePanel />
    </div>
  );
}
