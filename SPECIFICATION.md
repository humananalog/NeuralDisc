# NeuralDisc – Full System Specification & Architecture

**Version:** 0.1.0  
**Target Hardware:** Mac Mini M4, 24 GB unified memory  
**Primary Storage:** 1 TB external SSD  
**Last Updated:** 2026-08-11  
**Status:** Authoritative specification for Grok Build sessions

---

## 1. Project Vision & Non-Negotiables

NeuralDisc is a fully autonomous, local-first photo & video library system that turns a stack of old DVDs and CDs into a high-quality, searchable, Lightroom-class archive.

**North-star user experience**

1. Insert a DVD or CD (or click “Import Disc”).
2. The system detects the media, extracts every image and video, preserves provenance and original metadata, runs local vision-language analysis, generates embeddings, detects duplicates, and proposes organisation.
3. The user reviews a clean Human-in-the-Loop (HITL) queue, accepts/rejects/edits AI decisions, and only then commits permanent organisation or deletion.

**Hard constraints**

- Zero cloud APIs for inference or storage.
- Everything must run on Apple Silicon with MLX.
- Prefer open-source components with permissive licences (Apache-2.0, MIT, BSD, etc.).
- Crash-resistant pipeline with checkpoints and resume.
- The library remains usable offline even if the web app is not running (sidecar files + SQLite).

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Optical Media Layer                          │
│  (macOS diskutil / Disk Arbitration + Python watchers)              │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     Ingestion & Staging Service                     │
│  - Detect volume, filesystem type, label                            │
│  - Recursive extract (images + video)                               │
│  - Copy to staging with provenance                                  │
│  - Error logging (bad sectors, unreadable files)                    │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Background Job System                            │
│  (RQ + Redis  or  pure asyncio + filesystem queues)                  │
│  Jobs: metadata → VLM → embeddings → duplicates → organisation     │
└───────────┬───────────────────────────────┬─────────────────────────┘
            │                               │
            ▼                               ▼
┌───────────────────────┐     ┌───────────────────────────────────────┐
│  Media Processing     │     │  AI / ML Layer (Apple MLX)            │
│  - EXIF / ffprobe     │     │  - mlx-vlm (Qwen2.5-VL / Qwen3-VL)    │
│  - Thumbnails         │     │  - MLX CLIP / SigLIP / DINOv2         │
│  - Keyframes (video)  │     │  - Structured JSON output             │
│  - Perceptual hashes  │     │  - Batch inference where possible     │
└───────────────────────┘     └───────────────────────────────────────┘
            │                               │
            └───────────────┬───────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     Persistence Layer                               │
│  - SQLite (relational + FTS5)                                       │
│  - LanceDB or Chroma (vector store)                                 │
│  - Sidecar JSON / XMP next to originals                             │
│  - Immutable originals + derivatives                                │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     FastAPI Backend                                 │
│  REST + WebSocket (progress, job status)                            │
│  HITL endpoints, search, collections, stats                         │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│               Next.js Frontend (App Router)                         │
│  Timeline · Grid · Map · People · Albums · Search · HITL Queue      │
│  Tailwind + shadcn/ui · Keyboard-first · Responsive                 │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Recommended Technology Stack (with rationale)

| Layer              | Choice                                      | Why (for M4 24 GB)                                      |
|--------------------|---------------------------------------------|---------------------------------------------------------|
| Language           | Python 3.12+                                | Best MLX / media ecosystem                              |
| Web framework      | FastAPI                                     | Async, typed, excellent OpenAPI, WebSocket support      |
| Job queue          | RQ + Redis (preferred) or pure asyncio + FS | Simple, reliable, easy resume; Redis is lightweight     |
| Relational DB      | SQLite + FTS5                               | Zero ops, excellent performance on SSD, portable        |
| Vector store       | LanceDB                                     | Arrow-native, multimodal-friendly, local-first, fast    |
| VLM                | mlx-vlm + Qwen2.5-VL-7B-Instruct-4bit (or latest Qwen3-VL 4-bit) | Fits comfortably in 24 GB with headroom |
| Embeddings         | MLX-compatible CLIP / SigLIP / DINOv2       | High quality, Apple Silicon optimised                   |
| Image processing   | Pillow, OpenCV, imagehash, rawpy (if needed)| Mature, fast                                            |
| Video              | ffmpeg / ffprobe (via Python wrappers)      | Industry standard                                       |
| Frontend           | Next.js 15 (App Router) + TypeScript + Tailwind + shadcn/ui | Modern, fast, excellent DX                    |
| Optical media      | macOS `diskutil`, `hdiutil`, Disk Arbitration + Python | Native, reliable                             |

**Rejected alternatives (and why)**

- Postgres + pgvector: overkill for single-machine local use; adds Docker complexity.
- Celery: heavier than needed; RQ is sufficient.
- Cloud embeddings / OpenAI vision: violates privacy constraint.
- Electron desktop app: web UI on local network is simpler and more flexible.

---

## 4. External SSD Folder Structure (Canonical)

```
/Volumes/<ExternalSSD>/NeuralDisc/
├── library/
│   ├── originals/                    # Immutable source files
│   │   └── by-provenance/
│   │       └── {volume_label}_{YYYYMMDD_HHMMSS}/
│   │           ├── 0001_IMG_1234.JPG
│   │           ├── 0002_VID_5678.MP4
│   │           └── ...
│   ├── organised/                    # Final user-approved structure (created only after HITL)
│   │   ├── 2008/
│   │   ├── 2009/
│   │   └── events/
│   ├── derivatives/
│   │   ├── thumbs/                   # 400px JPEG
│   │   ├── previews/                 # 1600px JPEG
│   │   └── keyframes/                # Video keyframes
│   └── staging/                      # Temporary extraction area (cleaned after successful ingest)
├── db/
│   ├── neuraldisc.sqlite
│   ├── neuraldisc.sqlite-wal
│   └── lancedb/                      # Vector store
├── logs/
│   ├── ingest/
│   ├── jobs/
│   └── errors/
├── config/
│   ├── settings.toml
│   └── models/                       # Optional local model cache overrides
└── exports/                          # User-triggered exports
```

**Provenance rule:** Every original file keeps an immutable record of the disc volume name, serial (if available), extraction timestamp, and original path on the disc.

---

## 5. Database Schema Outline (SQLite)

### Core tables

```sql
-- One row per physical disc / import session
CREATE TABLE discs (
    id              TEXT PRIMARY KEY,          -- UUID
    volume_name     TEXT NOT NULL,
    volume_uuid     TEXT,
    filesystem      TEXT,
    inserted_at     DATETIME NOT NULL,
    extracted_at    DATETIME,
    status          TEXT NOT NULL,             -- pending | extracting | processed | error
    notes           TEXT,
    error_log       TEXT
);

-- One row per media file
CREATE TABLE media_items (
    id              TEXT PRIMARY KEY,          -- UUID
    disc_id         TEXT REFERENCES discs(id),
    original_path   TEXT NOT NULL,             -- path inside the disc
    library_path    TEXT NOT NULL,             -- path under originals/
    filename        TEXT NOT NULL,
    media_type      TEXT NOT NULL,             -- image | video
    mime_type       TEXT,
    file_size       INTEGER,
    width           INTEGER,
    height          INTEGER,
    duration_ms     INTEGER,                   -- video only
    sha256          TEXT NOT NULL,
    phash           TEXT,                      -- perceptual hash
    dhash           TEXT,
    taken_at        DATETIME,                  -- from EXIF or best estimate
    camera_make     TEXT,
    camera_model    TEXT,
    gps_lat         REAL,
    gps_lon         REAL,
    orientation     INTEGER,
    quality_score   REAL,                      -- 0–1 from VLM
    is_duplicate    BOOLEAN DEFAULT FALSE,
    best_of_group   BOOLEAN DEFAULT FALSE,
    hitl_status     TEXT DEFAULT 'pending',    -- pending | accepted | rejected | edited
    created_at      DATETIME NOT NULL,
    updated_at      DATETIME NOT NULL
);

-- VLM structured output
CREATE TABLE media_analysis (
    media_id        TEXT PRIMARY KEY REFERENCES media_items(id),
    caption_short   TEXT,
    description     TEXT,
    scene_type      TEXT,
    people_count    INTEGER,
    people_desc     TEXT,
    objects         TEXT,                      -- JSON array
    suggested_tags  TEXT,                      -- JSON array
    estimated_era   TEXT,
    confidence      REAL,
    model_name      TEXT,
    model_version   TEXT,
    analysed_at     DATETIME
);

-- Embeddings metadata (actual vectors live in LanceDB)
CREATE TABLE embeddings (
    media_id        TEXT PRIMARY KEY REFERENCES media_items(id),
    model_name      TEXT NOT NULL,
    dim             INTEGER NOT NULL,
    created_at      DATETIME NOT NULL
);

-- Duplicate groups
CREATE TABLE duplicate_groups (
    id              TEXT PRIMARY KEY,
    created_at      DATETIME NOT NULL,
    method          TEXT,                      -- exact | phash | embedding
    best_media_id   TEXT REFERENCES media_items(id)
);

CREATE TABLE duplicate_members (
    group_id        TEXT REFERENCES duplicate_groups(id),
    media_id        TEXT REFERENCES media_items(id),
    similarity      REAL,
    PRIMARY KEY (group_id, media_id)
);

-- HITL review queue
CREATE TABLE hitl_queue (
    id              TEXT PRIMARY KEY,
    media_id        TEXT REFERENCES media_items(id),
    queue_type      TEXT NOT NULL,             -- new_item | duplicate | low_confidence | organisation
    priority        INTEGER DEFAULT 100,
    created_at      DATETIME NOT NULL,
    resolved_at     DATETIME,
    resolution      TEXT                       -- accepted | rejected | edited | deferred
);

-- Simple albums / collections (user-created or AI-proposed)
CREATE TABLE albums (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    is_ai_proposed  BOOLEAN DEFAULT FALSE,
    created_at      DATETIME NOT NULL
);

CREATE TABLE album_items (
    album_id        TEXT REFERENCES albums(id),
    media_id        TEXT REFERENCES media_items(id),
    position        INTEGER,
    PRIMARY KEY (album_id, media_id)
);
```

Additional FTS5 virtual table on `media_items` + `media_analysis` for full-text search.

LanceDB tables: one for image embeddings, one for video keyframe embeddings (with media_id + keyframe_ts as metadata).

---

## 6. Processing Pipeline (Detailed)

### 6.1 Ingestion

1. Watch for new volumes under `/Volumes` that are optical (or manual “Import Disc” button).
2. Read volume name, UUID, filesystem type.
3. Create `discs` record.
4. Recursively walk the disc:
   - Accept: `.jpg .jpeg .tif .tiff .png .heic .raw .cr2 .nef .arw .dng .mp4 .mov .avi .mkv .m4v` (extensible).
   - For pure video DVDs (VIDEO_TS): use `makemkvcon` (if installed) or fallback to ffmpeg title extraction.
5. Copy to `library/staging/{volume}_{timestamp}/` with sequential prefix for ordering.
6. Compute SHA-256 while copying.
7. Move from staging → `originals/by-provenance/...` only after successful copy + checksum verification.
8. Enqueue subsequent jobs.

### 6.2 Metadata & Derivatives

- Extract EXIF / XMP / IPTC with `exiftool` (preferred) or Pillow + piexif.
- Generate 400 px and 1600 px JPEG derivatives.
- For video: extract keyframes (scene-change detection via ffmpeg + density sampling).

### 6.3 VLM Analysis (mlx-vlm)

Prompt template (structured JSON):

```text
Analyse this photograph/video keyframe. Return ONLY valid JSON with these keys:
{
  "caption_short": "...",
  "description": "...",
  "scene_type": "...",
  "people_count": 0,
  "people_desc": "...",
  "objects": ["..."],
  "suggested_tags": ["..."],
  "estimated_era": "...",
  "quality_score": 0.0-1.0,
  "confidence": 0.0-1.0
}
```

Batch size tuned for 24 GB (typically 2–4 images depending on resolution).

### 6.4 Embeddings & Duplicate Engine

Multi-stage:

1. **Exact** – SHA-256 collision → automatic group.
2. **Near-exact** – pHash / dHash Hamming distance ≤ threshold.
3. **Semantic** – cosine similarity on CLIP/SigLIP/DINO embeddings ≥ configurable threshold (default 0.92).

Propose “best” version using composite score: resolution × quality_score × EXIF completeness.

### 6.5 Organisation Proposals

- Chronological folders from `taken_at`.
- Event clusters via time + embedding proximity.
- Quality tiers (keep / review / low-quality).
- Basic face clustering (InsightFace or MLX face models) – Phase 3+.

All proposals are written to DB and appear in HITL; nothing is moved into `organised/` until user approval.

---

## 7. Web Application Requirements

### Core views

- **Timeline** – chronological masonry / justified grid with date headers.
- **Grid** – classic Lightroom-style with adjustable thumbnail size.
- **Map** – only when GPS present (Leaflet or MapLibre).
- **People** – face clusters (later phase).
- **Albums / Collections**.
- **Search** – full-text (FTS5) + semantic (vector) with hybrid ranking.
- **Duplicates** – side-by-side comparison, group actions.
- **HITL Review Queue** – primary work surface after each disc.

### HITL Queue UX principles

- Keyboard-first (j/k navigation, a = accept, e = edit, r = reject, space = next).
- Clear visual distinction: AI-generated vs human-overridden.
- Confidence badges.
- Batch select + apply.
- “Keep best / Keep all / Delete selected” for duplicate groups.
- Permanent delete requires explicit confirmation + is logged.

### Non-functional

- Instant filtering & faceting (date, tags, camera, quality, HITL status, duplicate status).
- Library statistics dashboard (total items, discs processed, pending review, storage used).
- Progress WebSocket for long-running jobs.
- Dark mode first (photography-friendly).

---

## 8. Phased Implementation Plan

### Phase 0 – Project Skeleton + Disc Ingestion (Immediate)

**Goal:** Insert a disc → files land correctly in staging/originals with provenance and basic logging.

Deliverables:

- Repo structure (`backend/`, `frontend/`, `scripts/`, `docs/`).
- `pyproject.toml` / `requirements.txt` with pinned versions.
- Disc detection watcher (macOS).
- Recursive extractor with error handling.
- Provenance-aware copy to SSD layout.
- Basic CLI: `neuraldisc ingest --path /Volumes/XXX` and auto-watch mode.
- Logging to `logs/`.
- Homebrew + pip dependency list.

**Success criteria:** Point the system at a real data DVD/CD and obtain a clean `originals/by-provenance/...` tree + SQLite `discs` + `media_items` rows with SHA-256.

### Phase 1 – Metadata, Derivatives & Core Database

- EXIF extraction & normalisation.
- Thumbnail + preview generation.
- Complete SQLite schema + migrations (Alembic or pure SQL).
- FastAPI skeleton with health + media list endpoints.
- Basic job queue (start with RQ + Redis).

### Phase 2 – VLM Tagging + Embeddings

- mlx-vlm integration with Qwen2.5-VL (or current best 4-bit that fits).
- Structured JSON analysis stored in `media_analysis`.
- Embedding generation + LanceDB write.
- Batch inference pipeline with progress.

### Phase 3 – Duplicate Engine + Organisation Proposals

- Full multi-stage duplicate detection.
- “Best version” scoring.
- Event / chronological proposal generation.
- HITL queue population.

### Phase 4 – Web UI Core

- Next.js App Router project.
- Timeline + Grid + Search + basic filtering.
- Media detail view.
- Job progress UI.

### Phase 5 – HITL Polish + Duplicate UI + Production Hardening

- Full HITL review experience with keyboard shortcuts.
- Side-by-side duplicate management.
- Final organisation commit workflow.
- Crash recovery, resume, observability.
- README, deployment scripts, first real disc end-to-end test.

---

## 9. Phase 0 / Phase 1 Concrete Next Steps

### Required Homebrew packages

```bash
brew install ffmpeg exiftool redis
# Optional but recommended for pure video DVDs:
brew install makemkv
```

### Python environment (Apple Silicon)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install mlx mlx-vlm fastapi uvicorn[standard] rq redis pillow opencv-python-headless imagehash python-magic aiofiles pydantic sqlalchemy aiosqlite lancedb exiftool
# plus any mlx-community model download helpers
```

### Immediate implementation order (Phase 0)

1. Create clean repository layout.
2. Implement `backend/ingest/detector.py` – watch `/Volumes` for optical media.
3. Implement `backend/ingest/extractor.py` – recursive walk + safe copy with SHA-256.
4. Implement `backend/db/models.py` + initial SQLite schema.
5. CLI entry point `neuraldisc ingest`.
6. Write comprehensive tests against a synthetic disc image (or real disc).
7. Document exact run commands for M4.

Once Phase 0 is solid and tested on real media, we proceed to Phase 1.

---

## 10. Observability & Reliability

- Structured JSON logging (structlog).
- Every long-running job writes checkpoint files so it can resume after crash or reboot.
- Job status exposed via Redis + WebSocket.
- Error quarantine folder for unreadable files.
- Daily / on-demand integrity check (re-verify SHA-256 of originals).

---

## 11. Extensibility Points

- Model registry so new VLMs or embedding models can be swapped via config.
- Plugin-style analysers (face, object, quality, NSFW, etc.).
- Export adapters (local folder, Immich-compatible, etc.).

---

**This document is the single source of truth.**  
All future Grok Build sessions must treat it as authoritative. Any deviation requires an explicit update to this file.

End of Specification.
