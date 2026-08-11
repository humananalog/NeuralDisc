# NeuralDisc

**Fully autonomous, local-first photo & video library for Apple Silicon.**

**Current release: [v0.2.0](RELEASE_NOTES.md)** · [Changelog](CHANGELOG.md)

NeuralDisc transforms decades of personal media locked on physical DVDs and CDs into a modern, searchable, Lightroom-class digital archive — completely offline, privacy-first, and purpose-built for Apple Silicon.

Insert a disc. The system detects the media, extracts every image and video, preserves original metadata and provenance, runs local vision-language analysis, generates high-quality embeddings, detects exact and near-duplicates, and proposes intelligent organisation. You remain in full control through a clean Human-in-the-Loop review interface before any permanent decision is made.

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

## Core capabilities (v0.2)

| Capability | Description |
|---|---|
| **High-throughput import** | Stage → quality → EXIF → blur → derivatives → VLM → promote; live UI as items arrive |
| **Target-volume staging** | Temp files only under `library_root` on the library SSD |
| **Quality gates** | Reject icons, tiny web junk, extreme aspect ratios; optional quarantine |
| **Blur detection** | Laplacian variance; flag + HITL priority |
| **exiftool-only metadata** | Date, camera, GPS — no Pillow EXIF path |
| **Auto-rotate** | EXIF bake + content upright; **batch auto-rotate** on multi-select |
| **Duplicates** | SHA-256 + pHash (+ embedding hooks); keep-best single / batch / all groups |
| **Catalogue delete** | Trash (soft) + permanent purge with confirmation; restore |
| **Job cancel** | Cooperative cancel of running import / processing jobs |
| **Local VLM** | mlx-vlm (Qwen3-VL class); HF token encrypted at rest |
| **HITL Review** | Keyboard queue for accept / edit / reject |
| **Modern Web UI** | Live sidebar counts, filters, detail inference, **lightbox** (double-click / Backspace) |

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
| **[RELEASE_NOTES.md](RELEASE_NOTES.md)** | v0.2.0 release summary |
| **[CHANGELOG.md](CHANGELOG.md)** | Keep-a-Changelog history |
| **[docs/RUNBOOK.md](docs/RUNBOOK.md)** | Setup, env, quality gates, testing |
| **[docs/API.md](docs/API.md)** | REST endpoints |
| **[SPECIFICATION.md](SPECIFICATION.md)** | Architecture, schema, pipeline, phases |
| **[UI_UX.md](UI_UX.md)** | Visual system, HITL, shortcuts, components |

## Hardware target

- Mac Mini M4, 24 GB unified memory  
- 1 TB+ external SSD as primary library  
- Optical drive (internal or USB)

## Project status

**v0.2.0 — Phases 0–4 largely shipped**, with Phase 5 hardening in progress:

| Area | Status |
|------|--------|
| Ingest + provenance + stage-first promote | Done |
| SQLite + FTS5 + WAL | Done |
| Derivatives, blur, quality, auto-orient | Done |
| Duplicates + keep-best batch | Done |
| FastAPI + jobs + cancel | Done |
| Next.js library, review, duplicates, import, settings | Done |
| Lightbox, live nav counts, trash/permanent delete | Done |
| Full mlx-vlm on every file by default | Optional (settings) |
| Face clustering / MapLibre / album auto-org | Planned |

## Author

**Alex Huther**  
Hong Kong  
[huther.pro](https://huther.pro) · [humananalog.ai](https://humananalog.ai)

## Licence

MIT (see `backend/pyproject.toml`).  
Components are chosen with permissive open-source licences in mind.

---

*Built for people who still have the discs — and want them back as a living, searchable library.*
