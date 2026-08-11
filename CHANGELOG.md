# Changelog

All notable changes to NeuralDisc are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.2.0] — 2026-08-11

First full application release: local library backend, Next.js UI, high-throughput import, catalogue operations, and HITL foundations.

### Added

#### Ingest & processing
- Stage-first import pipeline: scan → quality gate → copy to **library staging on target volume** → EXIF (exiftool-only) → blur → derivatives → VLM → promote to originals
- Auto-detect mounted volumes (optical first); full-disc import from UI
- Parallel copy + process workers with SQLite WAL, busy timeout, and write lock
- Live import progress API (`/api/import`, `/api/import/live`) and dock panel
- Quality gates for junk rejection (resolution, size, aspect, path heuristics, quarantine)
- Laplacian blur detection with HITL priority and flags
- **SOTA auto-orient**: EXIF bake + aggressive content upright detection (user batch auto-rotate)
- Manual 90°/180° rotate for single items and multi-select batches

#### Catalogue
- Soft-delete (**Trash**) + permanent purge with FK-safe cleanup
- Batch trash / permanent delete / restore
- Delete confirmation modal (type DELETE for large permanent batches)
- Multi-stage duplicates (exact SHA-256, pHash, embedding hooks)
- **Keep best** per group, batch selection, and all-groups resolution (losers → Trash)
- Live top filters (photos, video, pending, duplicates, blurry, trash)

#### API
- Media list/detail/patch, thumb/preview/original
- Batch rotate, batch delete, restore
- Duplicates list + keep-best + keep-best-batch + summary counts
- Jobs list + **cooperative cancel** (`POST /api/jobs/{id}/cancel`)
- Settings: library root on target SSD, quality prefs, HF token via Fernet secrets store (`~/.neuraldisc/`)
- Nav counts for sidebar badges (`GET /api/stats/nav`)
- Stats, discs, albums, HITL queue, health

#### Web UI (http://127.0.0.1:3020)
- App shell: sidebar with **live counters** on every section, top bar filters, jobs hint
- Library / Grid with density, multi-select, keep-best, auto-rotate, delete
- Detail panel: full metadata + VLM inference, rating, flag, rotate, delete/restore
- **Lightbox**: double-click or Backspace expands image in-app; Esc/Backspace close; ←/→ navigate; zoom
- Duplicates page with top counts, select-all, keep-best batch / all groups
- Import modal + live dock; Jobs page with cancel; Settings; Review HITL queue
- Timeline, Map (GPS list), Albums, Stats, People placeholder

#### Ops & tests
- CLI: `init`, `serve`, `ingest`, `watch`, `volumes`, `stats`
- `scripts/dev.sh`, sample disc fixtures
- Pytest: API, import, quality, blur, orientation/delete, keep-best batch, job cancel, settings

### Fixed
- Permanent delete IntegrityError on `duplicate_groups.best_media_id`
- Delete modal stuck open after failed confirmation (Escape/X/Cancel always available)
- Top filters not reloading grid live
- Single-click detail + full inference fetch
- Content auto-rotate when EXIF Orientation=1 but pixels sideways (e.g. P1160841.JPG)

### Security
- Hugging Face token and secrets encrypted at rest under `~/.neuraldisc/` (never logged in full)

## [0.1.0] — 2026-08

- Authoritative SPECIFICATION.md and UI_UX.md
- Project README and documentation scaffold

---

[0.2.0]: https://github.com/humananalog/NeuralDisc/releases/tag/v0.2.0
[0.1.0]: https://github.com/humananalog/NeuralDisc/tree/main
