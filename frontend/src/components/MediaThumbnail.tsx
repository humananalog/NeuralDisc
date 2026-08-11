"use client";

import { useEffect, useState } from "react";
import { Star, Flag, Copy, Sparkles, Aperture } from "lucide-react";
import type { MediaItem } from "@/lib/api";
import { mediaSrc } from "@/lib/api";
import { cn, confidenceColor } from "@/lib/utils";

type Props = {
  item: MediaItem;
  selected?: boolean;
  size?: number;
  /** Extra cache-bust token (e.g. after rotate) */
  refreshKey?: string | number;
  onClick?: (e: React.MouseEvent) => void;
  onDoubleClick?: () => void;
};

function assetUrl(item: MediaItem, refreshKey?: string | number): string {
  const raw = mediaSrc(item.thumb_url || item.preview_url);
  if (!raw) return "";
  // thumb_url from API already includes ?v=… after rotate; still append client key
  const bust = [
    item.updated_at,
    item.rotation_degrees,
    item.sha256?.slice(0, 12),
    refreshKey,
  ]
    .filter((x) => x !== undefined && x !== null && x !== "")
    .join("-");
  if (!bust) return raw;
  // If server already put v=, use r= for client epoch so both apply
  const sep = raw.includes("?") ? "&" : "?";
  return `${raw}${sep}r=${encodeURIComponent(bust)}`;
}

export function MediaThumbnail({
  item,
  selected,
  size = 160,
  refreshKey,
  onClick,
  onDoubleClick,
}: Props) {
  const src = assetUrl(item, refreshKey);
  const conf = item.analysis?.confidence;
  // Force <img> remount when src identity changes (reliable after rotate)
  const [imgKey, setImgKey] = useState(src);

  useEffect(() => {
    setImgKey(src);
  }, [src]);

  return (
    <button
      type="button"
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      className={cn(
        "group relative overflow-hidden rounded-sm bg-[var(--bg-elevated)] text-left transition-transform duration-150",
        "hover:scale-[1.02] hover:opacity-100 focus-visible:outline-offset-0",
        selected && "ring-2 ring-[var(--accent)]",
      )}
      style={{ width: size, height: size }}
      aria-label={item.filename}
    >
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          key={imgKey}
          src={src}
          alt={item.filename}
          className="h-full w-full object-cover"
          loading="eager"
          decoding="async"
        />
      ) : (
        <div className="flex h-full w-full items-center justify-center text-[11px] text-[var(--text-muted)]">
          {item.media_type}
        </div>
      )}

      <div className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between p-1">
        <div className="flex gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
          {item.is_duplicate && (
            <Badge>
              <Copy className="h-2.5 w-2.5" />
            </Badge>
          )}
          {item.analysis && !item.analysis.human_edited && (
            <Badge tone="ai">
              <Sparkles className="h-2.5 w-2.5" />
            </Badge>
          )}
        </div>
        <div className="flex gap-0.5">
          {item.is_blurry && (
            <Badge tone="warning" title={`Blur score ${item.blur_score ?? "?"}`}>
              <Aperture className="h-2.5 w-2.5" />
            </Badge>
          )}
          {item.flag && (
            <Badge tone="danger">
              <Flag className="h-2.5 w-2.5" />
            </Badge>
          )}
        </div>
      </div>

      {(item.rating > 0 || conf != null) && (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-center justify-between bg-gradient-to-t from-black/70 to-transparent px-1.5 pb-1 pt-4 text-[10px]">
          <span className="flex items-center gap-0.5 text-amber-300">
            {item.rating > 0 && (
              <>
                <Star className="h-2.5 w-2.5 fill-current" />
                {item.rating}
              </>
            )}
          </span>
          {conf != null && (
            <span style={{ color: confidenceColor(conf) }}>
              {Math.round(conf * 100)}%
            </span>
          )}
        </div>
      )}

      {item.media_type === "video" && (
        <span className="absolute bottom-1 left-1 rounded bg-black/60 px-1 text-[9px] uppercase tracking-wide text-white">
          video
        </span>
      )}
    </button>
  );
}

function Badge({
  children,
  tone = "default",
  title,
}: {
  children: React.ReactNode;
  tone?: "default" | "ai" | "danger" | "warning";
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "flex items-center rounded bg-black/55 p-0.5 text-white backdrop-blur-sm",
        tone === "ai" && "text-[var(--ai)]",
        tone === "danger" && "text-[var(--danger)]",
        tone === "warning" && "text-[var(--warning)]",
      )}
    >
      {children}
    </span>
  );
}
