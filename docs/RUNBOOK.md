# NeuralDisc Runbook (Mac Mini M4)

Companion to **[RELEASE_NOTES.md](../RELEASE_NOTES.md)** and **[docs/API.md](API.md)**.

## Prerequisites

```bash
brew install ffmpeg python@3.12 exiftool
# Optional:
brew install redis makemkv
```

**exiftool is mandatory** — all image/video metadata is read only via ExifTool. Imports refuse to start if it is missing.

Node.js 20+ for the web UI.

## Setup

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cd ../frontend
npm install
```

Optional AI stack:

```bash
pip install -e ".[ai]"
export NEURALDISC_VLM_ENABLED=true
export NEURALDISC_EMBEDDINGS_ENABLED=true
# HF token: Settings UI → Secrets, or store via API
```

## Library location (target volume)

Default: `~/NeuralDisc`  
Override: **Settings UI**, or `export NEURALDISC_LIBRARY_ROOT=/Volumes/YourSSD/NeuralDisc`

**All data lives under this root** — including import temp:

```
{library_root}/
  library/
    staging/          ← import temp (NOT /tmp, NOT internal boot SSD)
    originals/by-provenance/
    derivatives/{thumbs,previews,keyframes}/
    quarantine/
  db/
    neuraldisc.sqlite
    lancedb/
  logs/
  config/
  exports/
```

Prefs file `~/.neuraldisc/settings.toml` can override a stale shell env so staging never silently stays on the Mac boot drive.

Secrets (HF token, etc.): encrypted under `~/.neuraldisc/` (never commit).

## Commands

```bash
source backend/.venv/bin/activate

neuraldisc init
neuraldisc ingest /Volumes/MY_DISC
neuraldisc ingest ./data/sample_disc --name SAMPLE
neuraldisc watch
neuraldisc volumes
neuraldisc serve --host 127.0.0.1 --port 8000
neuraldisc stats
```

## Web UI

```bash
# Terminal 1
neuraldisc serve --host 127.0.0.1 --port 8000

# Terminal 2
cd frontend && npm run dev -- --port 3020 --hostname 127.0.0.1
# → http://127.0.0.1:3020
```

Or: `./scripts/dev.sh`

| Service | URL |
|---------|-----|
| UI | http://127.0.0.1:3020 |
| API | http://127.0.0.1:8000 |
| OpenAPI | http://127.0.0.1:8000/docs |

## Day-to-day workflows

### Import a disc

1. Insert disc (or open Import → select volume/folder).  
2. Prefer **full disc** for optical media.  
3. Watch the live dock: files appear in Library as they promote.  
4. Use **Review** for pending HITL; **Duplicates** for keep-best.

### Fix rotation

1. Select one or more images.  
2. **Auto-rotate** (EXIF + content).  
3. Or use ↺ / ↻ for 90° steps.  
4. Double-click / Backspace for lightbox; Esc to close.

### Delete safely

1. **Delete** → Trash by default (restorable; filter **Trash**).  
2. Permanent: check “Delete permanently” (type `DELETE` if ≥10 items).  
3. Permanent purge clears FKs, FTS, files, derivatives.

### Cancel a job

- **Jobs** page → Cancel on running/queued.  
- Live import dock → Cancel job.  
- `POST /api/jobs/{id}/cancel`

## Quality gates (junk rejection)

| Rule | Default |
|------|---------|
| Min short edge | 480 px |
| Min long edge | 640 px |
| Min resolution | 0.35 MP |
| Min image size | 25 KB (40 KB web formats) |
| Min video size | 200 KB |
| Max aspect ratio | 3.5:1 |
| Blocked formats | SVG, EPS, AI, PDF, ICO, … |
| Animated GIF | rejected |
| Junk paths | thumb, favicon, icon, meme, … |

Rejected files → `library/quarantine/` when quarantine enabled.

```bash
export NEURALDISC_QUALITY_MIN_SHORT_EDGE=640
export NEURALDISC_QUALITY_ENABLED=true
export NEURALDISC_BLUR_THRESHOLD=80
export NEURALDISC_VLM_ENABLED=true
```

## Sample ingest

```bash
./scripts/ingest_sample.sh
```

## Tests

```bash
cd /path/to/NeuralDisc
source backend/.venv/bin/activate
# from repo root so tests/ resolve
PYTHONPATH=backend pytest tests/ -q
```

Coverage includes: API smoke, import promote, quality, blur, orientation/delete, keep-best batch, job cancel, settings.

## Phase map (v0.2)

| Phase | Status |
|-------|--------|
| 0 Ingest | Done — stage-first, multi-source, live jobs |
| 1 Metadata + DB + API | Done — exiftool, SQLite FTS, full REST |
| 2 VLM + embeddings | Hooks + optional mlx-vlm; heuristic fallback |
| 3 Duplicates | Done — exact/pHash + keep-best batch |
| 4 Web UI core | Done — library, filters, import, lightbox |
| 5 HITL + hardening | Partial — keyboard review; cancel; trash; more polish ongoing |

## Troubleshooting

| Symptom | Check |
|---------|--------|
| Import fails immediately | `exiftool -ver` on PATH |
| Staging on internal disk | Settings → library_root on external SSD |
| SQLite locked during import | Ensure single API process; busy_timeout is 60s |
| Thumbs wrong after rotate | Hard refresh; thumbs cache-busted via `updated_at` |
| Permanent delete 500 | Fixed in 0.2 (best_media_id FK); update to latest |
| Port 3000 busy | Frontend defaults to **3020** |
