# NeuralDisc HTTP API

Base URL (local Mac Mini): `http://127.0.0.1:8020`  
Interactive docs: `http://127.0.0.1:8020/docs`  
UI: `http://127.0.0.1:3020` (proxies `/api/*` → API)

All responses are JSON unless serving media files. Frontend proxies `/api/*` via Next.js rewrites.

## Health & stats

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Status, version, library root, DB + exiftool |
| GET | `/api/stats` | Library totals (media, duplicates, GPS, storage, …) |
| GET | `/api/stats/nav` | Sidebar counters (`review` always 0 — HITL removed) |

## Media

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/media` | List library items. Query: `q`, `media_type`, `hitl_status`, `is_duplicate`, `is_blurry`, `trash`, `sort`, `limit`, `offset` |
| GET | `/api/media/{id}` | Full detail + analysis |
| PATCH | `/api/media/{id}` | Rating, flag, caption edits |
| DELETE | `/api/media/{id}?permanent=` | Soft-delete (default) or permanent |
| POST | `/api/media/batch-delete` | Body: `{ ids, permanent }` |
| POST | `/api/media/{id}/restore` | Restore from trash |
| POST | `/api/media/batch-restore` | Body: `{ ids }` |
| POST | `/api/media/{id}/rotate` | Body: `{ mode: auto\|cw\|ccw\|180 }` |
| POST | `/api/media/batch-rotate` | Body: `{ ids, mode, aggressive }` |
| GET | `/api/media/{id}/thumb` | JPEG thumbnail |
| GET | `/api/media/{id}/preview` | JPEG preview |
| GET | `/api/media/{id}/original` | Original file |

**Default list filter:** `lifecycle` is `library` (excludes staging, rejected, trash). Use `trash=true` for trash.

## Import (copy-first)

Default: **serial copy** to `library/staging`, then **background process**. Import job completes when copy finishes (`disc_ready`); optical volumes may auto-eject (`ejected_paths`).

Scan on `/Volumes` uses cheap size/path gates only. Dimension quality, VLM, promote, and duplicate grouping run on the library SSD after copy.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/import` | Start/enqueue copy job. Modes: `disc`, `media`, `folder`, `batch` |
| GET | `/api/import/{job_id}` | Status (`phase`, `copied`, `disc_ready`, `copy_only`, `source_paths`, `ejected_paths`, …) |
| POST | `/api/import/eject` | Body `{ path, force? }` — eject/unmount a `/Volumes/…` path after copy |
| GET | `/api/import/live` | In-memory live copy jobs |
| GET | `/api/import/suggestions/volumes` | Mounted volumes + media counts |
| GET | `/api/import/process/status` | Background staging processor (pending, promoted session) |
| POST | `/api/import/process/wake` | Nudge processor |

## Inference

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/inference/status` | Coverage, queue size, VLM loaded, Metal memory, active job |
| GET | `/api/inference/queue` | `mode=pending\|heuristic\|all` |
| POST | `/api/inference/run` | Batch re-analyse (`limit`, `force_heuristic` default true) |
| POST | `/api/inference/requeue-heuristic` | Re-queue **all** heuristic / failed-VLM library items |
| POST | `/api/inference/{media_id}/reanalyse` | One item (`keep_loaded` default false → release MLX) |
| POST | `/api/inference/release` | Unload VLM + clear Metal cache |

## Duplicates

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/duplicates` | Groups + members |
| GET | `/api/duplicates/summary` | Active groups, trashable count, recoverable bytes |
| POST | `/api/duplicates/{id}/keep-best` | Keep best in one group; trash losers |
| POST | `/api/duplicates/keep-best-batch` | `{ media_ids }` \| `{ group_ids }` \| `{ all_groups: true }` |

## Jobs

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/jobs` | Recent jobs (+ `stale`, `has_live_worker`) |
| GET | `/api/jobs/{id}` | One job |
| GET | `/api/jobs/live` | In-process worker ids |
| POST | `/api/jobs/{id}/cancel` | Cooperative cancel; closes orphan jobs immediately |
| POST | `/api/jobs/{id}/resume` | Resume interrupted import |
| POST | `/api/jobs/reap-stale` | Close active jobs with no live worker; triggers auto-resume pass |
| GET | `/api/jobs/supervisor` | Auto-resume supervisor + staging process state |
| POST | `/api/jobs/supervisor/tick` | Force one auto-resume pass |

## HITL (legacy)

Review UI removed. AI accepts on promote. Endpoints remain for compatibility but queue is empty after startup auto-accept.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/hitl/queue` | Legacy pending items (usually empty) |
| GET | `/api/hitl/count` | Pending count |
| POST | `/api/hitl/{id}/resolve` | Accept / reject / edit / defer |
| POST | `/api/hitl/batch/accept` | Accept many media IDs |

## Settings & secrets

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/settings` | Library paths, quality, VLM flags, free space |
| PATCH | `/api/settings` | Update library_root, quality, VLM |
| POST | `/api/settings/check-path` | Validate library path |
| GET | `/api/settings/volumes` | Volume suggestions |
| GET/PUT | `/api/settings/secrets` | Encrypted secrets (e.g. Hugging Face token) |
| DELETE | `/api/settings/secrets/{key}` | Clear a secret |

## Discs & albums

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/discs` | Ingested discs |
| POST | `/api/discs/ingest` | Sync ingest path (legacy/simple) |
| GET | `/api/albums` | Albums + smart collections (`?kind=album\|smart`) |
| POST | `/api/albums` | Create fixed album |
| POST | `/api/albums/smart` | Create smart collection (auto-name from rules if name omitted) |
| POST | `/api/albums/auto-organise` | Build auto-named albums from EXIF + inference + smart defaults |
| GET | `/api/albums/{id}` | Album detail |
| GET | `/api/albums/{id}/media` | Members (dynamic for smart) |
| DELETE | `/api/albums/{id}` | Delete collection (not media) |

## WebSocket

| Path | Description |
|------|-------------|
| `/ws/jobs` | Job snapshot stream (optional clients) |

## Lifecycle values

| Value | Meaning |
|-------|---------|
| `staging` | In import staging; not listed in library |
| `library` | Promoted catalogue item |
| `trash` | Soft-deleted; restorable |
| `rejected` | Quality/HITL rejected |
