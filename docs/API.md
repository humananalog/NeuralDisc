# NeuralDisc HTTP API

Base URL (local): `http://127.0.0.1:8000`  
Interactive docs: `http://127.0.0.1:8000/docs`

All responses are JSON unless serving media files. Frontend proxies `/api/*` via Next.js rewrites.

## Health & stats

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Status, version, library root, DB + exiftool |
| GET | `/api/stats` | Library totals (media, HITL, duplicates, GPS, storage, …) |
| GET | `/api/stats/nav` | Sidebar counters for every nav section |

## Media

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/media` | List library items. Query: `q`, `media_type`, `hitl_status`, `is_duplicate`, `is_blurry`, `trash`, `sort`, `limit`, `offset` |
| GET | `/api/media/{id}` | Full detail + analysis |
| PATCH | `/api/media/{id}` | Rating, flag, HITL, caption edits |
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

## Import

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/import` | Start job. Modes: `disc`, `media`, `folder`, `batch` |
| GET | `/api/import/{job_id}` | Live import status |
| GET | `/api/import/live` | All in-memory live imports |
| GET | `/api/import/suggestions/volumes` | Mounted volumes + media counts |

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
| GET | `/api/jobs` | Recent jobs |
| GET | `/api/jobs/{id}` | One job |
| POST | `/api/jobs/{id}/cancel` | Cooperative cancel (import / post-ingest) |

## HITL

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/hitl/queue` | Pending review items |
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
| GET | `/api/albums` | Albums |
| POST | `/api/albums` | Create album |

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
