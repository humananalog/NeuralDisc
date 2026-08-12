# Release Notes

**Current: [v0.3.12](CHANGELOG.md)** — ports **API :8020** / **UI :3020**, auto-eject, disc-ready UI, optical fast-scan, auto-resume after crash, ViniMidas MLX lease, media shortcuts on all grids. Full ops: **[docs/RUNBOOK.md](docs/RUNBOOK.md)**.

---

## NeuralDisc v0.3.0 — Copy-first discs, inference, smart albums (2026-08-11)

**Version: 0.3.0** (backend + UI) — historical baseline; prefer Changelog for 0.3.1+.

### Highlights

| Area | What you get |
|------|----------------|
| **Copy-first import** | Serial disc queue; parallel file copy to **staging on library SSD**. Job completes when copy finishes → **eject and insert next disc**. |
| **Background process** | Global staging worker: EXIF, blur, derivatives, optional VLM, promote — **does not block** the next copy. |
| **Inference** | Nav section: coverage, heuristic queue, batch/single re-run; **Release MLX** so peer apps (`mlx_lm` :8088, etc.) reclaim GPU. |
| **Resume** | Interrupted imports: drain staging + re-scan sources, skip SHA-256 already in library. |
| **Jobs** | Stale/orphan reap after API restart; live-worker registry for import + inference. |
| **Smart albums** | Auto-organise from EXIF + AI (years, cameras, scenes, events, discs). |
| **AI-first** | No HITL Review queue — AI accepts by default; refine in **Library** after inference. |
| **Import UI** | Collapsible import modal + dock; “disc free” when copy done. |

### Run it

```bash
brew install ffmpeg python@3.12 exiftool

cd backend && python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
neuraldisc init
neuraldisc serve --host 127.0.0.1 --port 8020

cd frontend && npm install && npm run dev -- --port 3020 --hostname 127.0.0.1
# → http://127.0.0.1:3020  ·  API http://127.0.0.1:8020/docs
```

Optional: `./scripts/dev.sh` · `NEURALDISC_LIBRARY_ROOT=/Volumes/YourSSD/NeuralDisc`  
VLM: Settings → enable VLM + HF token; `pip install -e ".[ai]"` if needed.

### Env / pipeline knobs

| Setting | Default | Meaning |
|---------|---------|---------|
| `NEURALDISC_IMPORT_COPY_ONLY` | `true` | Copy ≠ process (fast disc rotation) |
| `NEURALDISC_IMPORT_COPY_SERIAL` | `true` | One disc import at a time |
| `NEURALDISC_IMPORT_COPY_WORKERS` | `6` | Parallel copy threads |
| `NEURALDISC_IMPORT_PROCESS_WORKERS` | `2` | Background classify workers |
| `NEURALDISC_VLM_ENABLED` | `false` | Local mlx-vlm captions |

### Ports

| Service | Default |
|---------|---------|
| API + OpenAPI docs | http://127.0.0.1:8020 · `/docs` |
| Web UI | http://127.0.0.1:3020 |

### Day-to-day disc workflow

1. **Import** full disc → watch **Copied** in the live panel.  
2. When **Disc free / eject OK** → pull disc, queue the next import.  
3. Library fills as the **background processor** promotes files.  
4. **Inference** upgrades heuristic captions when GPU is free; **Release MLX** when done.  
5. **Duplicates** / Library for keep-best, rotate, trash.

### Breaking / notes

- HITL Review nav removed; `/review` redirects to Library. Legacy pending rows auto-accepted on API start.  
- Import job “completed” means **copy finished**, not full VLM coverage.  
- Staging remains under `library_root` only (never `/tmp`).

### Known limitations

- People / face clustering not implemented.  
- Map is GPS list (MapLibre later).  
- Semantic embeddings optional / partial.  
- VIDEO_TS deep rip still limited vs data discs.

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

## NeuralDisc v0.2.0 — First full local library (2026-08-11)

Stage-first import, quality gates, duplicates, trash, jobs cancel, and first Web UI. See git history and [CHANGELOG.md](CHANGELOG.md).

---

*Tags: `v0.3.0` (current) · `v0.2.0`*
