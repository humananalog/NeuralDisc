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

### Import a disc (copy-first)

Default pipeline (`import_copy_only=true`, `import_copy_serial=true`):

1. Insert disc (or open Import → select volume/folder). Prefer **full disc** for optical media.  
2. Scan finds loose media **and** archives (zip/tar/…). Archives that contain photos/video are expanded onto the library SSD (not onto the disc).  
3. Copy runs in a **serial queue** (one disc at a time) into `library/staging/…` on the **library SSD**.  
4. When copy finishes, **optical discs auto-eject** (`auto_eject=true`) so the drive is free; the import job is **complete for that disc** — insert the next.  
5. A **global staging processor** classifies and promotes in the background (does not hold the optical drive).  
6. Library fills as items promote. Use **Inference** to upgrade heuristic captions; **Duplicates** for keep-best.  
7. AI accepts by default — edit captions / trash in **Library** when you care.

Archives: `.zip` / `.cbz` / `.tar` / `.tar.gz` / … (stdlib). `.rar` / `.7z` if `7z` or `unar` is on PATH.

Optional env:

```bash
export NEURALDISC_AUTO_EJECT=false   # keep disc mounted after copy
```

```bash
export NEURALDISC_IMPORT_COPY_ONLY=true      # default: copy decoupled from process
export NEURALDISC_IMPORT_COPY_SERIAL=true    # default: one disc at a time
export NEURALDISC_VLM_ENABLED=true           # local mlx-vlm during process / Inference
```

`GET /api/import/process/status` — background queue depth and last message.

### Fix rotation

1. Select one or more images.  
2. **Auto-rotate** (EXIF + content).  
3. Or use ↺ / ↻ for 90° steps.  
4. Double-click / Backspace for lightbox; Esc to close.

### Delete safely

1. **Delete** → Trash by default (restorable; filter **Trash**).  
2. Permanent: check “Delete permanently” (type `DELETE` if ≥10 items).  
3. Permanent purge clears FKs, FTS, files, derivatives.

### Inference & MLX

1. Enable VLM in Settings (+ HF token if the model is gated).  
2. **Inference** page: queue heuristics / pending; **Run** batch or **Re-run** one item.  
3. After jobs finish, MLX is **released** automatically; or click **Release MLX** for peer apps.  
4. `POST /api/inference/release` if scripting.

### Local ports (Mac Mini coexistence)

| Service | Port |
|---------|------|
| NeuralDisc UI | **3020** |
| NeuralDisc API | **8020** |
| mineru | 8000 |
| vllm-mlx | 8010 |
| ViniMidas MCP | 3100 |

LaunchAgents (KeepAlive): `com.humananalog.neuraldisc.api` · `com.humananalog.neuraldisc.ui`

```bash
launchctl kickstart -k gui/$(id -u)/com.humananalog.neuraldisc.api
launchctl kickstart -k gui/$(id -u)/com.humananalog.neuraldisc.ui
# logs: ~/logs/neuraldisc/
```

UI proxies `/api/*` → `http://127.0.0.1:8020` via `NEURALDISC_API_URL` / `frontend/.env.local`.

### Coexistence with ViniMidas (peer MLX plane lease)

On the shared Mac Mini, **ViniMidas owns the Metal slot** (`:8088` mlx_lm). NeuralDisc must take a short-TTL **peer lease** via ViniMidas MCP HTTP before loading in-process mlx-vlm. NeuralDisc never writes Supabase `runtime_plane_holds` and never binds/kills `:8088`.

```bash
# From Mac Mini .env.local (or a NeuralDisc-only copy of the secret)
export VINIMIDAS_MCP_HTTP_URL=http://127.0.0.1:3100
export VINIMIDAS_MCP_HTTP_SECRET=…   # same Bearer as other MCP tools

export NEURALDISC_MLX_PEER_ID=neuraldisc          # must be allowlisted on ViniMidas
export NEURALDISC_MLX_LEASE_TTL_MS=600000         # 10m default
export NEURALDISC_MLX_LEASE_RENEW_INTERVAL_MS=300000  # renew ≤ TTL/2
export NEURALDISC_MLX_LEASE_MAX_WAIT_MS=120000
# Optional: force on/off (default = lease when secret is set)
# export NEURALDISC_MLX_LEASE_REQUIRED=1
```

Lifecycle:

1. Inference / import VLM paths call `acquire_mlx_plane_lease` (`peer_id=neuraldisc`).  
2. Background renew while the batch holds Metal.  
3. On job end or **Release MLX**: unload weights + clear Metal cache + `release_mlx_plane_lease`.  
4. If Vinimidas steals the plane (renew fails / non-peer holder): NeuralDisc unloads immediately and retries later.  
5. Crash / missed renew: TTL expiry frees the plane without manual cleanup.

Inspect: `GET /api/inference/plane-lease` · status includes `plane_lease` on `GET /api/inference/status`.  
Busy plane: reanalyse returns **503** with `blocker`; batch jobs fail with `mlx_plane_busy:…` and leave items pending.

Solo Mac without ViniMidas: leave the secret unset (or `NEURALDISC_MLX_LEASE_REQUIRED=0`).

### Jobs: cancel, resume, stale, auto-resume

1. **Cancel** — cooperative stop between files.  
2. **Resume** — interrupted imports: drain staging + re-scan, skip existing SHA-256.  
3. **Clear stale / Reap orphans** — close `running`/`queued` rows with no live worker (e.g. after API restart). Safe: library media stays.  
4. **Auto-resume supervisor** (default on) — every ~30s and on API start (covers crash / LaunchAgent restart):  
   - wake staging processor if `lifecycle=staging` rows remain  
   - resume interrupted/failed **import** jobs (one at a time)  
   - re-queue interrupted **post_ingest**  
   - when VLM is enabled, start **inference** batches for pending/heuristic library items  

Optical scan uses cheap size/path gates only; dimension quality gates run after copy on the library SSD so the drive is not stalled by PIL.

```bash
# Toggle
export NEURALDISC_AUTO_RESUME_ENABLED=true
export NEURALDISC_AUTO_RESUME_INFERENCE=true
export NEURALDISC_AUTO_RESUME_INTERVAL_SEC=30

# Inspect / nudge
curl -s http://127.0.0.1:8020/api/jobs/supervisor
curl -s -X POST http://127.0.0.1:8020/api/jobs/supervisor/tick
```

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
