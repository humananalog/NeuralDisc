"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutGrid,
  Clock,
  Map,
  Users,
  Images,
  Copy,
  CheckSquare,
  Activity,
  BarChart3,
  Disc3,
  Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/lib/store";
import type { NavCounts } from "@/lib/api";

type NavKey = keyof NavCounts;

const NAV: Array<{
  href: string;
  label: string;
  icon: typeof Images;
  countKey: NavKey;
  /** Highlight when non-zero (action needed) */
  alert?: boolean;
}> = [
  { href: "/library", label: "Library", icon: Images, countKey: "library" },
  { href: "/timeline", label: "Timeline", icon: Clock, countKey: "timeline" },
  { href: "/grid", label: "Grid", icon: LayoutGrid, countKey: "grid" },
  { href: "/map", label: "Map", icon: Map, countKey: "map" },
  { href: "/people", label: "People", icon: Users, countKey: "people" },
  { href: "/albums", label: "Albums", icon: Images, countKey: "albums" },
  {
    href: "/duplicates",
    label: "Duplicates",
    icon: Copy,
    countKey: "duplicates",
    alert: true,
  },
  {
    href: "/review",
    label: "Review",
    icon: CheckSquare,
    countKey: "review",
    alert: true,
  },
  { href: "/jobs", label: "Jobs", icon: Activity, countKey: "jobs", alert: true },
  { href: "/stats", label: "Stats", icon: BarChart3, countKey: "stats" },
  { href: "/settings", label: "Settings", icon: Settings, countKey: "settings" },
];

function formatCount(n: number): string {
  if (n > 999_999) return `${Math.round(n / 1_000_000)}M`;
  if (n > 9999) return `${Math.round(n / 1000)}k`;
  if (n > 999) return "999+";
  return String(n);
}

export function Sidebar() {
  const pathname = usePathname();
  const navCounts = useAppStore((s) => s.navCounts);

  return (
    <aside className="flex h-full w-[280px] shrink-0 flex-col border-r border-[var(--border)] bg-[var(--bg-elevated)]">
      <div className="flex items-center gap-2 border-b border-[var(--border)] px-4 py-4">
        <Disc3 className="h-5 w-5 text-[var(--accent)]" strokeWidth={1.75} />
        <div className="min-w-0 flex-1">
          <div className="text-[15px] font-semibold tracking-tight">NeuralDisc</div>
          <div className="truncate text-[11px] text-[var(--text-muted)]">
            {navCounts.library > 0
              ? `${navCounts.library.toLocaleString()} in library`
              : "Local archive"}
            {navCounts.images > 0 || navCounts.videos > 0
              ? ` · ${navCounts.images} img · ${navCounts.videos} vid`
              : ""}
          </div>
        </div>
      </div>

      <nav className="flex-1 space-y-0.5 overflow-y-auto p-2">
        {NAV.map(({ href, label, icon: Icon, countKey, alert }) => {
          const active = pathname === href || pathname.startsWith(href + "/");
          const n = navCounts[countKey] ?? 0;
          const hasItems = n > 0;
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-2.5 rounded-md px-3 py-2 text-[13px] transition-colors",
                active
                  ? "bg-[var(--bg-selected)] text-[var(--text-primary)]"
                  : "text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]",
              )}
            >
              <Icon className="h-4 w-4 shrink-0" strokeWidth={1.75} />
              <span className="flex-1 truncate">{label}</span>
              <span
                className={cn(
                  "min-w-[1.5rem] rounded-full px-1.5 py-0.5 text-center text-[10px] font-medium tabular-nums",
                  hasItems && alert
                    ? countKey === "duplicates"
                      ? "bg-[var(--warning)] text-white"
                      : countKey === "jobs"
                        ? "bg-[var(--accent)] text-white"
                        : "bg-[var(--accent)] text-white"
                    : hasItems
                      ? active
                        ? "bg-[var(--bg-hover)] text-[var(--text-primary)]"
                        : "bg-[var(--bg-base)] text-[var(--text-secondary)]"
                      : "text-[var(--text-muted)]",
                )}
                title={`${label}: ${n.toLocaleString()}`}
              >
                {formatCount(n)}
              </span>
            </Link>
          );
        })}
      </nav>

      <div className="space-y-1 border-t border-[var(--border)] p-3 text-[11px] text-[var(--text-muted)]">
        {navCounts.trash > 0 && (
          <div className="flex justify-between gap-2">
            <span>Trash</span>
            <span className="tabular-nums text-[var(--text-secondary)]">
              {navCounts.trash.toLocaleString()}
            </span>
          </div>
        )}
        <div>Privacy-first · Apple Silicon · Offline</div>
      </div>
    </aside>
  );
}
