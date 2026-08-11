# NeuralDisc

**Fully autonomous, local-first photo & video library for Apple Silicon.**

NeuralDisc transforms decades of personal media locked on physical DVDs and CDs into a modern, searchable, Lightroom-class digital archive — completely offline, privacy-first, and purpose-built for Apple Silicon.

Insert a disc. The system detects the media, extracts every image and video, preserves original metadata and provenance, runs local vision-language analysis, generates high-quality embeddings, detects exact and near-duplicates, and proposes intelligent organisation. You remain in full control through a clean Human-in-the-Loop review interface before any permanent decision is made.

---

## Why NeuralDisc exists

Physical media collections are fragile, scattered, and increasingly inaccessible. NeuralDisc was created to give individuals a reliable, private, and high-quality way to liberate and organise those collections without sending a single byte to the cloud.

It is designed from the ground up for the Mac Mini M4 (24 GB) and a local external SSD, prioritising:

- Complete data sovereignty
- Apple Silicon performance via MLX
- Production-grade reliability and resumability
- A modern, keyboard-friendly interface that feels like a contemporary Lightroom / Immich hybrid

## Core Capabilities

| Capability | Description |
|---|---|
| **Disc Ingestion** | Automatic detection and recursive extraction of images & video from data discs, hybrid discs, and video DVDs |
| **Provenance Tracking** | Every file retains original disc label, volume identity, extraction timestamp, and path |
| **Local VLM Analysis** | Scene description, tagging, people/objects, quality scoring, and captions via mlx-vlm (Qwen2.5-VL / Qwen3-VL class) |
| **Embeddings & Search** | High-quality visual embeddings for semantic search and near-duplicate detection |
| **Multi-stage Deduplication** | Exact (SHA-256) → perceptual hash → embedding similarity, with “best version” proposals |
| **Video Support** | Keyframe extraction, VLM captioning of key moments, timeline summaries |
| **HITL Review** | Dedicated queue for approving/editing AI tags, merging duplicates, and final keep/delete decisions |
| **Modern Web UI** | Timeline, Grid, Map, Albums, Search, and powerful filtering — all local |

## Architecture & Design Documents

| Document | Purpose |
|----------|---------|
| **[SPECIFICATION.md](SPECIFICATION.md)** | Full system architecture, data model, technology choices, folder layout, database schema, processing pipeline, and phased implementation plan |
| **[UI_UX.md](UI_UX.md)** | SOTA UI/UX specification — design philosophy, visual system, information architecture, HITL interaction model, keyboard shortcuts, performance targets, and component strategy |

## Hardware Target

- Mac Mini M4, 24 GB unified memory
- 1 TB (or larger) external SSD as primary library location
- Optical drive (internal or external USB)

## Project Status

Architecture, system specification, and SOTA UI/UX design complete.  
Implementation begins with **Phase 0** (project skeleton + robust disc ingestion).

## Author

**Alex Huther**  
Hong Kong  
[huther.pro](https://huther.pro) · [humananalog.ai](https://humananalog.ai)

## Licence

To be determined (likely Apache-2.0 or MIT).  
All components are chosen with permissive open-source licences in mind.

---

*Built for people who still have the discs — and want them back as a living, searchable library.*
