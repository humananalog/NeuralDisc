/** Browser API client — routes via Next.js rewrites to FastAPI. */

export type Analysis = {
  caption_short?: string | null;
  description?: string | null;
  scene_type?: string | null;
  people_count?: number | null;
  people_desc?: string | null;
  objects: string[];
  suggested_tags: string[];
  estimated_era?: string | null;
  confidence?: number | null;
  model_name?: string | null;
  model_version?: string | null;
  analysed_at?: string | null;
  human_edited: boolean;
};

export type MediaItem = {
  id: string;
  disc_id?: string | null;
  filename: string;
  media_type: string;
  mime_type?: string | null;
  file_size?: number | null;
  width?: number | null;
  height?: number | null;
  duration_ms?: number | null;
  sha256: string;
  phash?: string | null;
  taken_at?: string | null;
  camera_make?: string | null;
  camera_model?: string | null;
  gps_lat?: number | null;
  gps_lon?: number | null;
  orientation?: number | null;
  quality_score?: number | null;
  blur_score?: number | null;
  is_blurry: boolean;
  is_duplicate: boolean;
  best_of_group: boolean;
  hitl_status: string;
  lifecycle?: string;
  deleted_at?: string | null;
  auto_rotated?: boolean;
  rotation_degrees?: number;
  rating: number;
  flag: boolean;
  colour_label?: string | null;
  library_path?: string | null;
  original_path?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  thumb_url?: string | null;
  preview_url?: string | null;
  original_url?: string | null;
  analysis?: Analysis | null;
};

export type MediaDeleteResult = {
  deleted: string[];
  trashed: string[];
  restored: string[];
  mode: string;
  count: number;
};

export type MediaRotateResult = {
  media: MediaItem;
  changed: boolean;
  method: string;
  degrees_applied: number;
};

export type MediaListResponse = {
  items: MediaItem[];
  total: number;
  offset: number;
  limit: number;
};

export type HitlItem = {
  id: string;
  media_id: string;
  queue_type: string;
  priority: number;
  created_at?: string | null;
  media?: MediaItem | null;
};

export type Job = {
  id: string;
  job_type: string;
  status: string;
  progress: number;
  total: number;
  completed: number;
  message?: string | null;
  error?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
};

export type Stats = {
  total_media: number;
  total_images: number;
  total_videos: number;
  total_discs: number;
  pending_review: number;
  accepted: number;
  rejected: number;
  duplicates: number;
  blurry?: number;
  storage_bytes: number;
  has_gps: number;
  albums?: number;
  people?: number;
  timeline?: number;
  trash?: number;
  jobs_active?: number;
  duplicate_groups?: number;
};

/** Left-nav counters for every sidebar section */
export type NavCounts = {
  library: number;
  timeline: number;
  grid: number;
  map: number;
  people: number;
  albums: number;
  duplicates: number;
  review: number;
  jobs: number;
  stats: number;
  settings: number;
  images: number;
  videos: number;
  discs: number;
  trash: number;
};

export const EMPTY_NAV_COUNTS: NavCounts = {
  library: 0,
  timeline: 0,
  grid: 0,
  map: 0,
  people: 0,
  albums: 0,
  duplicates: 0,
  review: 0,
  jobs: 0,
  stats: 0,
  settings: 0,
  images: 0,
  videos: 0,
  discs: 0,
  trash: 0,
};

export type Disc = {
  id: string;
  volume_name: string;
  status: string;
  notes?: string | null;
  media_count: number;
  inserted_at?: string | null;
  extracted_at?: string | null;
};

export type Album = {
  id: string;
  name: string;
  description?: string | null;
  is_ai_proposed: boolean;
  item_count: number;
  cover_media_id?: string | null;
  created_at?: string | null;
};

export type DuplicateGroup = {
  id: string;
  method?: string | null;
  best_media_id?: string | null;
  created_at?: string | null;
  members: Array<{
    media_id: string;
    filename: string;
    similarity?: number | null;
    best_of_group: boolean;
    width?: number | null;
    height?: number | null;
    quality_score?: number | null;
  }>;
};

export type MediaQuery = {
  offset?: number;
  limit?: number;
  q?: string;
  media_type?: string;
  hitl_status?: string;
  is_duplicate?: boolean;
  is_blurry?: boolean;
  rating_min?: number;
  has_gps?: boolean;
  disc_id?: string;
  flag?: boolean;
  trash?: boolean;
  lifecycle?: string;
  sort?: string;
};

export type AppSettings = {
  version: string;
  prefs_file: string;
  library_root: string;
  library_exists: boolean;
  library_writable: boolean;
  sqlite_path: string;
  db_exists: boolean;
  originals_dir: string;
  staging_dir?: string;
  quarantine_dir?: string;
  derivatives_dir?: string;
  free_bytes?: number | null;
  total_bytes?: number | null;
  media_count: number;
  disc_count: number;
  temp_on_target?: boolean;
  quality_enabled: boolean;
  quality_min_short_edge: number;
  quality_min_long_edge: number;
  quality_min_megapixels: number;
  quality_min_image_bytes: number;
  quality_min_web_format_bytes: number;
  quality_min_video_bytes: number;
  quality_min_video_short_edge: number;
  quality_max_aspect_ratio: number;
  quality_reject_animated_gif: boolean;
  quality_reject_junk_paths: boolean;
  quality_quarantine_rejects: boolean;
  vlm_enabled: boolean;
  embeddings_enabled: boolean;
  thumb_size: number;
  preview_size: number;
  exiftool_ok?: boolean;
  exiftool_version?: string | null;
  exiftool_path?: string | null;
  secrets?: Record<string, { configured: boolean; masked?: string | null }>;
  secrets_secure?: boolean;
};

export type SecretsStatus = {
  secrets: Record<string, { configured: boolean; masked?: string | null }>;
  secrets_secure: boolean;
  secrets_dir: string;
};

export type PathCheck = {
  path: string;
  exists: boolean;
  is_dir: boolean;
  writable: boolean;
  free_bytes?: number | null;
  total_bytes?: number | null;
  message: string;
  ok: boolean;
};

export type VolumeSuggestion = {
  path: string;
  name: string;
  is_optical: boolean;
  is_ejectable: boolean;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text();
    let msg = text || res.statusText;
    try {
      const j = JSON.parse(text) as { detail?: unknown };
      if (typeof j.detail === "string") msg = j.detail;
      else if (Array.isArray(j.detail))
        msg = j.detail
          .map((d) => (typeof d === "object" && d && "msg" in d ? String((d as { msg: string }).msg) : String(d)))
          .join("; ");
    } catch {
      /* plain text */
    }
    throw new Error(msg || `HTTP ${res.status}`);
  }
  // 204 / empty body
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

function qs(params: Record<string, string | number | boolean | undefined | null>) {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export const api = {
  health: () => request<{ status: string; version: string; library_root: string; db_ok: boolean }>("/api/health"),
  stats: () => request<Stats>("/api/stats"),
  navCounts: () => request<NavCounts>("/api/stats/nav"),
  media: (query: MediaQuery = {}) =>
    request<MediaListResponse>(`/api/media${qs(query as Record<string, string | number | boolean>)}`),
  mediaOne: (id: string) => request<MediaItem>(`/api/media/${id}`),
  updateMedia: (id: string, body: Record<string, unknown>) =>
    request<MediaItem>(`/api/media/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteMedia: (id: string, permanent = false) =>
    request<MediaDeleteResult>(
      `/api/media/${id}${qs({ permanent: permanent ? true : undefined })}`,
      { method: "DELETE" },
    ),
  batchDeleteMedia: (ids: string[], permanent = false) =>
    request<MediaDeleteResult>("/api/media/batch-delete", {
      method: "POST",
      body: JSON.stringify({ ids, permanent }),
    }),
  restoreMedia: (id: string) =>
    request<MediaItem>(`/api/media/${id}/restore`, { method: "POST" }),
  batchRestoreMedia: (ids: string[]) =>
    request<MediaDeleteResult>("/api/media/batch-restore", {
      method: "POST",
      body: JSON.stringify({ ids }),
    }),
  rotateMedia: (id: string, mode: "auto" | "cw" | "ccw" | "180" = "auto") =>
    request<MediaRotateResult>(`/api/media/${id}/rotate`, {
      method: "POST",
      body: JSON.stringify({ mode }),
    }),
  /** Batch auto-rotate (or cw/ccw/180) for multi-select. */
  batchRotateMedia: (
    ids: string[],
    mode: "auto" | "cw" | "ccw" | "180" = "auto",
    aggressive = true,
  ) =>
    request<{
      mode: string;
      rotated: string[];
      unchanged: string[];
      failed: Array<{ id: string; error: string; filename?: string }>;
      count_rotated: number;
      count_unchanged: number;
      count_failed: number;
      items: MediaItem[];
    }>("/api/media/batch-rotate", {
      method: "POST",
      body: JSON.stringify({ ids, mode, aggressive }),
    }),
  hitlQueue: (limit = 50) => request<HitlItem[]>(`/api/hitl/queue${qs({ limit })}`),
  hitlCount: () => request<{ pending: number }>("/api/hitl/count"),
  resolveHitl: (id: string, body: Record<string, unknown>) =>
    request<HitlItem>(`/api/hitl/${id}/resolve`, { method: "POST", body: JSON.stringify(body) }),
  batchAccept: (media_ids: string[]) =>
    request<{ updated: number }>("/api/hitl/batch/accept", {
      method: "POST",
      body: JSON.stringify(media_ids),
    }),
  jobs: () => request<Job[]>("/api/jobs"),
  cancelJob: (jobId: string) =>
    request<{
      job_id: string;
      ok: boolean;
      status?: string | null;
      cancel_requested?: boolean;
      message?: string;
      job?: Job;
    }>(`/api/jobs/${jobId}/cancel`, { method: "POST" }),
  discs: () => request<Disc[]>("/api/discs"),
  ingest: (path: string, volume_name?: string) =>
    request<{ disc_id: string; files: number; errors: string[]; volume_name: string }>(
      "/api/discs/ingest",
      { method: "POST", body: JSON.stringify({ path, volume_name, process: true }) },
    ),
  albums: () => request<Album[]>("/api/albums"),
  duplicates: () => request<DuplicateGroup[]>("/api/duplicates"),
  duplicatesSummary: () =>
    request<{
      groups: number;
      active_groups: number;
      resolved_groups: number;
      total_members: number;
      active_members: number;
      unique_media: number;
      active_unique_media: number;
      best_count: number;
      trashable: number;
      by_method: Record<string, number>;
      active_bytes: number;
      trashable_bytes: number;
    }>("/api/duplicates/summary"),
  keepBest: (groupId: string) =>
    request<{
      kept: string;
      rejected: number;
      trashed?: string[];
      kept_count?: number;
      trashed_count?: number;
    }>(`/api/duplicates/${groupId}/keep-best`, {
      method: "POST",
    }),
  /** Keep best across multi-select, many groups, or all groups at once. */
  keepBestBatch: (body: {
    media_ids?: string[];
    group_ids?: string[];
    all_groups?: boolean;
    trash_losers?: boolean;
  }) =>
    request<{
      groups_resolved: number;
      kept: string[];
      trashed: string[];
      rejected: string[];
      skipped: string[];
      kept_count: number;
      trashed_count: number;
      details: Array<{
        source: string;
        group_id?: string | null;
        kept: string;
        losers: string[];
        method?: string | null;
      }>;
    }>("/api/duplicates/keep-best-batch", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  settings: () => request<AppSettings>("/api/settings"),
  updateSettings: (body: Partial<AppSettings> & { create_if_missing?: boolean }) =>
    request<AppSettings>("/api/settings", { method: "PATCH", body: JSON.stringify(body) }),
  checkPath: (path: string, create_if_missing = false) =>
    request<PathCheck>("/api/settings/check-path", {
      method: "POST",
      body: JSON.stringify({ path, create_if_missing }),
    }),
  volumes: () => request<VolumeSuggestion[]>("/api/settings/volumes"),
  secretsStatus: () => request<SecretsStatus>("/api/settings/secrets"),
  putSecret: (key: string, value: string | null) =>
    request<SecretsStatus>("/api/settings/secrets", {
      method: "PUT",
      body: JSON.stringify({ key, value }),
    }),
  deleteSecret: (key: string) =>
    request<SecretsStatus>(`/api/settings/secrets/${encodeURIComponent(key)}`, {
      method: "DELETE",
    }),
  startImport: (body: {
    mode: "disc" | "media" | "folder" | "batch";
    path?: string;
    volume_name?: string;
    sources?: Array<{ path: string; name?: string; mode?: string }>;
  }) =>
    request<{ job_id: string; message: string; sources: number }>("/api/import", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  importStatus: (jobId: string) => request<ImportStatus>(`/api/import/${jobId}`),
  importLive: () => request<ImportStatus[]>("/api/import/live"),
  importVolumes: (countMedia = true) =>
    request<
      Array<{
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
      }>
    >(`/api/import/suggestions/volumes?count_media=${countMedia ? "true" : "false"}`),
};

export type ImportStatus = {
  job_id: string;
  status: string;
  phase: string;
  total: number;
  copied: number;
  processed: number;
  promoted: number;
  rejected: number;
  errors: number;
  bytes_copied: number;
  sources_done: number;
  sources_total: number;
  message: string;
  disc_ids: string[];
  reject_samples: string[];
  items_per_hour: number;
  error?: string | null;
  library_root?: string;
  staging_dir?: string;
  cancel_requested?: boolean;
};

export type DuplicateSummary = {
  groups: number;
  active_groups: number;
  resolved_groups: number;
  total_members: number;
  active_members: number;
  unique_media: number;
  active_unique_media: number;
  best_count: number;
  trashable: number;
  by_method: Record<string, number>;
  active_bytes: number;
  trashable_bytes: number;
};

export function mediaSrc(url?: string | null): string {
  if (!url) return "";
  return url;
}
