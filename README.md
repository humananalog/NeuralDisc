# NeuralDisc

**Fully autonomous, local-first photo & video library for Apple Silicon.**

**Current release: [v0.3.7](CHANGELOG.md)** · [Changelog](CHANGELOG.md)

NeuralDisc transforms decades of personal media locked on physical DVDs and CDs into a modern, searchable, Lightroom-class digital archive — completely offline, privacy-first, and purpose-built for Apple Silicon.

Insert a disc. The system **copies to staging on your library SSD** (so you can eject and rotate discs quickly), then classifies in the background with quality gates, EXIF, optional local vision-language models, embeddings, and duplicate detection. **AI decisions stand by default** — browse, edit captions, and manage trash in the Library after inference.

---

## Quick start

```bash
# Prerequisites (exiftool is required for all EXIF)
brew install ffmpeg python@3.12 exiftool

# Backend
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
neuraldisc init
neuraldisc serve --host 127.0.0.1 --port 8000   # http://127.0.0.1:8000/docs

# Frontend (second terminal) — use 3020 (not 3000)
cd frontend && npm install && npm run dev -- --port 3020 --hostname 127.0.0.1
# → http://127.0.0.1:3020

# Or both:
./scripts/dev.sh

# Ingest a folder or disc
neuraldisc ingest /Volumes/YOUR_DISC
./scripts/ingest_sample.sh
```

Set the library on your **target SSD** in **Settings** or:

```bash
export NEURALDISC_LIBRARY_ROOT=/Volumes/YourSSD/NeuralDisc
```

Import **staging always lives under that root** — never system temp.

See **[docs/RUNBOOK.md](docs/RUNBOOK.md)** for full setup, env vars, testing, and ops.

---

## Why NeuralDisc exists

Physical media collections are fragile, scattered, and increasingly inaccessible. NeuralDisc gives individuals a reliable, private way to liberate and organise those collections without sending a single byte to the cloud.

Designed for the **Mac Mini M4 (24 GB)** and a local external SSD:

- Complete data sovereignty  
- Apple Silicon performance via MLX  
- Production-grade reliability and resumability  
- A modern, keyboard-friendly UI (Lightroom / Immich hybrid)

## Core capabilities (v0.3)

| Capability | Description |
|---|---|
| **Copy-first import** | Serial disc queue → parallel copy to `library/staging` → **eject when copy done**; classify in background |
| **Archives on disc** | Zip/tar (rar/7z if available) with photos/video → expand on library SSD → same pipeline |
| **Background process** | Global staging processor: EXIF → blur → derivatives → VLM → promote (never blocks next disc copy) |
| **Target-volume staging** | Temp files only under `library_root` on the library SSD |
| **Quality gates** | Reject icons, tiny web junk, extreme aspect ratios; optional quarantine |
| **Blur detection** | Laplacian variance; flag for later attention in Library |
| **exiftool-only metadata** | Date, camera, GPS — no Pillow EXIF path |
| **Auto-rotate** | EXIF bake + content upright; **batch auto-rotate** on multi-select |
| **Duplicates** | SHA-256 + pHash; keep-best single / batch / all groups |
| **Inference** | Dedicated page: queue heuristics, batch VLM, re-analyse, **Release MLX** for other apps |
| **Jobs + auto-resume** | Progress, cancel, resume; reap stale workers; supervisor keeps staging/import/inference from sitting idle |
| **Smart albums** | Auto-organise from EXIF + AI captions/scenes |
| **Catalogue delete** | Trash (soft) + permanent purge with confirmation; restore |
| **Modern Web UI** | Live sidebar counts, filters, lightbox, collapsible import dock |

## Repository layout

```
backend/neuraldisc/   # FastAPI + ingest + pipeline + AI + catalogue
frontend/             # Next.js App Router UI
scripts/              # dev + sample ingest
tests/                # pytest
docs/                 # RUNBOOK, API reference
SPECIFICATION.md      # Architecture (authoritative)
UI_UX.md              # Design system (authoritative)
CHANGELOG.md          # Version history
RELEASE_NOTES.md      # Human release summary
```

## Documentation

| Document | Purpose |
|----------|---------|
| **[RELEASE_NOTES.md](RELEASE_NOTES.md)** | v0.3.0 release summary |
| **[CHANGELOG.md](CHANGELOG.md)** | Keep-a-Changelog history |
| **[docs/RUNBOOK.md](docs/RUNBOOK.md)** | Setup, env, quality gates, testing |
| **[docs/API.md](docs/API.md)** | REST endpoints |
| **[SPECIFICATION.md](SPECIFICATION.md)** | Architecture, schema, pipeline, phases |
| **[UI_UX.md](UI_UX.md)** | Visual system, shortcuts, components |

## Hardware target

- Mac Mini M4, 24 GB unified memory  
- 1 TB+ external SSD as primary library  
- Optical drive (internal or USB)

## Project status

**v0.3.0 — Copy-first pipeline + inference + smart albums**, Phase 5 hardening ongoing:

| Area | Status |
|------|--------|
| Ingest: serial copy → staging; background process/promote | Done |
| SQLite + FTS5 + WAL | Done |
| Derivatives, blur, quality, auto-orient | Done |
| Duplicates + keep-best batch | Done |
| FastAPI + jobs + cancel + resume + stale reap | Done |
| Next.js library, inference, duplicates, import, settings | Done |
| AI auto-accept (no HITL queue); edit/trash in Library | Done |
| Lightbox, live nav counts, trash/permanent delete | Done |
| Full mlx-vlm on every file by default | Optional (settings) |
| Face clustering / MapLibre tiles | Planned |

## Author

**Alex Huther**  
Hong Kong  
[huther.pro](https://huther.pro) · [humananalog.ai](https://humananalog.ai)

## Licence

MIT (see `backend/pyproject.toml`).  
Components are chosen with permissive open-source licences in mind.

---

*Built for people who still have the discs — and want them back as a living, searchable library.*
