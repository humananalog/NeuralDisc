# NeuralDisc

**Fully autonomous, local-first photo & video library for Apple Silicon.**

NeuralDisc turns stacks of old DVDs and CDs into a modern, searchable, Lightroom-class archive — completely offline, privacy-first, and optimised for Mac Mini M4 (24 GB).

Insert a disc → the system extracts, analyses (mlx-vlm + Qwen2.5-VL / Qwen3-VL), generates embeddings, detects duplicates, and proposes organisation. You review everything in a clean Human-in-the-Loop interface before any permanent decision is made.

## Status

Early architecture & specification phase. See **[SPECIFICATION.md](SPECIFICATION.md)** for the complete system design, data model, technology choices, and phased implementation plan.

## Hardware Target

- Mac Mini M4, 24 GB unified memory
- 1 TB external SSD as primary library location
- Optical drive (internal or external)

## Core Principles

- 100 % local — no cloud APIs
- Apple Silicon first (MLX / mlx-vlm)
- Autonomous pipeline + strong HITL gates
- Open-source, permissive licences only
- Library remains usable even when the web app is offline

## Quick Links

- [Full Specification & Architecture](SPECIFICATION.md)
- Phased plan starts with Phase 0 (disc ingestion) → Phase 1 (metadata + DB)

## Licence

To be decided (likely Apache-2.0 or MIT).

---

Built for personal archival of decades of physical media.
