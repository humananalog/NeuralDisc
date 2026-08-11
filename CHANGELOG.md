# Changelog

All notable changes to NeuralDisc are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.3.5] — 2026-08-11

### Fixed
- Import cancel stuck on "Cancelling…": honor cancel during scan, interrupt in-flight copies between chunks, skip cancelled jobs waiting in the serial queue, and **Force cancel** (second click / `?force=true`) for stale limbo
- Do not auto-resume imports that were mid-cancel across API restart

## [0.3.4] — 2026-08-11

### Fixed
- Import scan skips unreadable files/dirs (permission / I/O) instead of queuing them as copy errors; archives scanned the same way

## [0.3.3] — 2026-08-11

### Added
- Shared Lightroom-style keyboard shortcuts across Library grid, lightbox, and Collections (`0–5` rate, `[` `]` rotate, `f`/`p`/`u` flag, arrows/`j`/`k` nav, `Delete`, `?` help)

### Changed
- Shortcut cheat sheet overlay (`?`) and button titles that show the key bindings

## [0.3.2] — 2026-08-11

### Fixed
- Infinite inference job spam: VLM JSON was truncating (`max_tokens` too low) so the same ~15 images stayed `vlm-failed` and auto-chain/supervisor kept spawning identical batches
- Raise VLM token budget, salvage truncated JSON, cap auto-retries (`vlm-gave-up`), and stop chaining when a batch makes no progress

## [0.3.1] — 2026-08-11

### Fixed
- Albums page hydration error from nested `<button>` (delete control inside card)

## [0.3.0] — 2026-08-11

### Added
- **Archive expansion on import**: zip/tar (and rar/7z if tools present) that contain images/video are unpacked to staging and processed
- **Copy-first import pipeline**: serial disc queue, parallel copy to `library/staging`, job completes when copy finishes (fast optical rotation)
- **Global staging processor**: background EXIF / blur / derivatives / VLM / promote without blocking the next disc copy
- `GET /api/import/process/status`, `POST /api/import/process/wake`
- **Job resume** for interrupted/failed imports (drain staging + re-scan, skip existing SHA-256)
- **Inference** page: coverage, queue filters, batch run, single re-analyse, **Release MLX** (`POST /api/inference/release`)
- VLM session refcount + force-release after inference/import process batches (peer apps on Metal)
- **Smart collections & auto albums** from EXIF + VLM (years, cameras, scenes, events, discs)
- Job **stale recovery** on API restart + live-worker registry (import + inference) + Jobs UI Clear stale / Reap orphans
- **Auto-resume supervisor**: keep staging drain, resume interrupted imports, re-queue post-ingest, auto-start inference when VLM on + queue non-empty
- **Heuristic re-queue**: SQL-backed queue of all failed-VLM/heuristic items; chain batches until drained; `POST /api/inference/requeue-heuristic`
- Collapsible **import modal** (minimize to dock) + live panel process status
- Immediate **thumbnail refresh** after rotate (versioned URLs + no-cache derivatives)
- App version badge in sidebar + Settings (UI `0.3.0` aligned with backend)

### Changed
- **Removed HITL Review** as a primary workflow — AI accepts by default; `/review` redirects to Library
- Promote sets `hitl_status=accepted`; startup auto-accepts legacy pending HITL rows
- Import defaults: `import_copy_only=true`, `import_copy_serial=true`

### Fixed
- Duplicates page showing ghost images when active count was 0 (prune resolved groups)
- React duplicate-key warning on repeated AI tags (`celebration`, etc.)
- Permanent delete FK failures; delete modal stuck open
- Inference jobs incorrectly marked STALE (workers not registered)
- Manual “Clear stale” skipped young orphan jobs

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

[0.3.5]: https://github.com/humananalog/NeuralDisc/releases/tag/v0.3.5
[0.3.4]: https://github.com/humananalog/NeuralDisc/releases/tag/v0.3.4
[0.3.3]: https://github.com/humananalog/NeuralDisc/releases/tag/v0.3.3
[0.3.2]: https://github.com/humananalog/NeuralDisc/releases/tag/v0.3.2
[0.3.1]: https://github.com/humananalog/NeuralDisc/releases/tag/v0.3.1
[0.3.0]: https://github.com/humananalog/NeuralDisc/releases/tag/v0.3.0
[0.2.0]: https://github.com/humananalog/NeuralDisc/releases/tag/v0.2.0
[0.1.0]: https://github.com/humananalog/NeuralDisc/tree/main
