# Release Notes

## NeuralDisc v0.2.0 — First full local library (2026-08-11)

**Fully autonomous, local-first photo & video library for Apple Silicon.**

This release delivers a working end-to-end product: insert (or point at) a disc/folder, import at high throughput onto a target SSD, classify with quality + EXIF + optional local VLM, review in a modern dark UI, fix rotation, resolve duplicates, and manage trash — without cloud dependency.

### Highlights

| Area | What you get |
|------|----------------|
| **Import** | Stage-first pipeline on the **library target volume** (never system `/tmp`). Live panel as files promote. |
| **Quality** | Junk rejection (icons, tiny web assets, extreme aspect ratios). Blur detection. |
| **Metadata** | **exiftool-only** EXIF/GPS/camera. SHA-256 + perceptual hashes. |
| **AI** | mlx-vlm hooks (Qwen3-VL class); HF token stored encrypted. Heuristic fallback when VLM off. |
| **Duplicates** | Exact + pHash groups; **Keep best** one-by-one, multi-select batch, or all groups. |
| **Orientation** | Auto-rotate (EXIF + content) on import and as **batch selection** action. Manual 90°/180°. |
| **Catalogue** | Trash (soft delete) + permanent delete with confirmation. Restore from Trash filter. |
| **Jobs** | Progress tracking; **Cancel** running imports/processing. |
| **UI** | Lightroom/Immich-style dark UI: live sidebar counts, filters, detail inference panel, **lightbox** (double-click / Backspace). |

### Run it

```bash
# Prerequisites
brew install ffmpeg python@3.12 exiftool

# Backend
cd backend && python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
neuraldisc init
neuraldisc serve --host 127.0.0.1 --port 8000

# Frontend (second terminal) — port 3020
cd frontend && npm install && npm run dev -- --port 3020 --hostname 127.0.0.1
# → http://127.0.0.1:3020
```

Optional: `./scripts/dev.sh` · set library root in **Settings** or `NEURALDISC_LIBRARY_ROOT`.

### Ports

| Service | Default |
|---------|---------|
| API + OpenAPI docs | http://127.0.0.1:8000 · `/docs` |
| Web UI | http://127.0.0.1:3020 |

### Breaking / notes for early adopters

- Library layout requires `library/staging` under `library_root` (target SSD).
- Permanent delete is irreversible; soft-delete (Trash) is the default.
- VLM is off by default; enable in Settings + HF token for full captions.
- SQLite WAL; concurrent import writers use busy timeout + serialization.

### Known limitations (next phases)

- People / face clustering not implemented (placeholder page).
- Map is GPS list (full MapLibre tiles later).
- Semantic search embeddings optional / partial.
- Video DVD VIDEO_TS deep rip still limited vs data discs.
- Organisation “commit to albums by event” workflow incomplete.

### Documentation

| Doc | Contents |
|-----|----------|
| [README.md](README.md) | Product overview + quick start |
| [CHANGELOG.md](CHANGELOG.md) | Versioned change history |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | Setup, ops, env, testing |
| [docs/API.md](docs/API.md) | HTTP API surface |
| [SPECIFICATION.md](SPECIFICATION.md) | Architecture & schema |
| [UI_UX.md](UI_UX.md) | Design system & interactions |

### Author

**Alex Huther** · Hong Kong · [huther.pro](https://huther.pro) · [humananalog.ai](https://humananalog.ai)

---

*Tag: `v0.2.0`*
