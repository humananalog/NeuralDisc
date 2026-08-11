# NeuralDisc — SOTA UI / UX Specification

**Version:** 0.1.0  
**Status:** Authoritative design reference for the web application  
**Target feel:** Contemporary Lightroom Classic + Immich hybrid, optimised for keyboard power users and high-volume personal archives  
**Last Updated:** 2026-08-11  

This document defines the visual language, information architecture, interaction patterns, and component behaviour for the NeuralDisc web application. It is the single source of truth for frontend implementation and design decisions.

---

## 1. Design Philosophy

NeuralDisc is a **tool for serious personal archival**, not a social feed or consumer gallery.

### Core principles

1. **Content first, chrome second**  
   Photos and videos dominate the screen. UI chrome is quiet, dark, and retractable.

2. **Keyboard is first-class**  
   Every frequent action has a single-key or chord shortcut. Mouse is supported; keyboard is preferred for review workflows.

3. **Human remains in control**  
   AI proposals are clearly labelled, confidence is visible, and irreversible actions (especially delete) require deliberate confirmation.

4. **Speed feels native**  
   Instant filtering, progressive image loading, virtualised grids, and optimistic UI updates. The interface should never feel like it is waiting on a network.

5. **Dark-by-default, photography-first**  
   True dark theme with careful contrast for long review sessions. Light theme available but secondary.

6. **Density without clutter**  
   Information-dense where useful (metadata, confidence, duplicate status), sparse where the image must breathe.

7. **Local-first honesty**  
   No artificial “cloud” metaphors. Status indicators reflect real local jobs, queue depth, and storage.

---

## 2. Visual Design System

### Colour palette (dark theme — primary)

| Token | Hex | Usage |
|-------|-----|-------|
| `--bg-base` | `#0a0a0b` | Application background |
| `--bg-elevated` | `#141416` | Cards, panels, sidebars |
| `--bg-hover` | `#1c1c1f` | Hover states |
| `--bg-selected` | `#2563eb22` | Selected items (blue tint) |
| `--border` | `#27272a` | Subtle borders |
| `--border-strong` | `#3f3f46` | Active / focus borders |
| `--text-primary` | `#fafafa` | Primary text |
| `--text-secondary` | `#a1a1aa` | Secondary / metadata |
| `--text-muted` | `#71717a` | Tertiary |
| `--accent` | `#3b82f6` | Primary actions, focus rings |
| `--accent-hover` | `#60a5fa` | Accent hover |
| `--success` | `#22c55e` | Accepted / best version |
| `--warning` | `#eab308` | Low confidence / review needed |
| `--danger` | `#ef4444` | Delete / reject |
| `--ai` | `#a855f7` | AI-generated content indicators |

Light theme mirrors the same structure with inverted luminance and slightly warmer neutrals.

### Typography

- **UI text**: Inter or system UI font stack (SF Pro on macOS)
- **Monospace** (hashes, paths, confidence scores): JetBrains Mono or SF Mono
- Scale: 12 / 13 / 14 / 16 / 18 / 24 / 32 — tight leading for dense panels

### Spacing & density

- Base unit: 4 px
- Grid gap default: 4–8 px (user-adjustable thumbnail density)
- Sidebar width: 280–320 px
- Detail panel: 360–420 px

### Elevation & depth

Prefer subtle borders and background shifts over heavy shadows. Soft ambient occlusion only on floating panels and modals.

### Iconography

Lucide icons (via shadcn/ui). Consistent 16 / 20 / 24 px sizes. Stroke weight 1.5–2 px.

---

## 3. Information Architecture

### Primary navigation (left rail or top tabs)

- **Library** (default) — all media
- **Timeline** — chronological
- **Grid** — pure visual grid
- **Map** — GPS-aware (hidden when no geo data)
- **People** — face clusters (Phase 3+)
- **Albums** — user + AI-proposed collections
- **Duplicates** — dedicated management surface
- **Review** — HITL queue (badge shows pending count)
- **Jobs** — background processing status
- **Stats** — library health dashboard

### Global chrome

- Top bar: search (full-text + semantic), view density, sort, filter chips, job progress indicator
- Left rail: navigation + facet filters (collapsible)
- Right panel (contextual): selection details, metadata, AI analysis, HITL actions

### Selection model

- Single click = select
- Cmd/Ctrl + click = toggle
- Shift + click = range
- Drag-select on grid
- “Select all matching current filters” action

---

## 4. Core Views — Detailed Specification

### 4.1 Timeline View

- Grouped by day / month / year with sticky date headers
- Justified or masonry layout option
- Hover reveals quick actions (rate, flag, open)
- Scroll performance: virtualised rows + progressive JPEG loading
- Date scrubber on the right edge (Lightroom-style)

### 4.2 Grid View

- Uniform thumbnail size (user-controlled: small / medium / large / custom)
- Aspect-ratio aware or square crop toggle
- Overlay badges: AI confidence, duplicate status, HITL status, rating stars, flag
- Infinite / virtualised scrolling
- Keyboard navigation (arrow keys + Enter to open)

### 4.3 Detail / Loupe View

- Full-resolution (or high-quality preview) with zoom (scroll / pinch / +/-)
- Side-by-side compare mode (for duplicates)
- Filmstrip at bottom for rapid sequential review
- Metadata + AI panel (collapsible)
- Non-destructive rating, flags, colour labels

### 4.4 HITL Review Queue (highest priority surface)

This is the primary work surface after a disc is processed.

**Layout**
- Large central media area
- Left: queue list (thumbnail + status + confidence)
- Right: AI analysis panel + action buttons
- Bottom: filmstrip of current queue page

**Actions (keyboard-first)**
| Key | Action |
|-----|--------|
| `j` / `↓` | Next item |
| `k` / `↑` | Previous item |
| `a` | Accept AI tags & caption |
| `e` | Edit tags / caption (inline) |
| `r` | Reject / mark for deletion |
| `d` | Open duplicate group if present |
| `f` | Flag |
| `1–5` | Star rating |
| `Space` | Toggle selection / advance |
| `Enter` | Open full detail |
| `Esc` | Exit review / clear selection |

**Visual language**
- AI-generated fields have a subtle purple left border or “AI” badge
- Human overrides turn green and show “edited” indicator
- Confidence meter (0–100 %) with colour coding
- Low-confidence items float higher in the queue by default

**Batch mode**
- Multi-select in the queue list
- “Accept all selected”, “Reject all selected”, “Apply tag to selected”

### 4.5 Duplicate Management

- Group cards showing all members side-by-side or in a scrollable strip
- “Best” version highlighted with green ring + score breakdown
- Side-by-side loupe comparison (sync zoom & pan)
- Actions per group: Keep best, Keep all, Keep selected, Delete others
- Similarity score and detection method (exact / pHash / embedding) displayed

### 4.6 Search

- Single omnibox supporting:
  - Free text (FTS5)
  - Semantic (“photos of beaches at sunset”)
  - Structured filters via chips or natural language
- Results update live
- Hybrid ranking explanation available on hover (“matched on caption + visual similarity 0.91”)

### 4.7 Map View

- Only shown when GPS data exists
- Clustering at low zoom, individual pins at high zoom
- Click pin → thumbnail popup → open in detail
- Filter by visible map area

### 4.8 Albums & Collections

- Grid of album covers (smart cover selection from highest-rated or representative images)
- AI-proposed albums clearly labelled and easy to accept / rename / dismiss
- Drag-and-drop or multi-select add to album

---

## 5. Filtering & Faceting

Always-visible or easily reachable facets:

- Date range (with timeline histogram)
- Media type (photo / video)
- Camera / lens
- Rating / flags
- HITL status (pending / accepted / rejected / edited)
- Duplicate status
- Quality score range
- Tags (AI + human)
- People (later)
- Has GPS
- Source disc

Facets update counts live and can be combined. “Clear all filters” is one click.

---

## 6. Feedback, Progress & Observability

- Global job indicator in the top bar (spinner + “3 discs processing · 1 247 items remaining”)
- Click opens Jobs drawer with per-job progress, ETA, and logs
- Toast notifications for completed discs and critical errors (non-blocking)
- Empty states are helpful and actionable (“No items match filters — clear filters” / “Insert a disc to begin”)
- Skeleton loaders that match final layout (no layout shift)

---

## 7. Performance Targets (Perceived)

| Interaction | Target |
|-------------|--------|
| Thumbnail grid scroll | 60 fps, no jank |
| Filter application | < 100 ms for typical libraries |
| Open detail view | < 150 ms to first meaningful paint |
| HITL advance (j/k) | Instant (pre-fetched neighbours) |
| Semantic search | Progressive results, first batch < 300 ms |

Techniques: virtualisation (react-virtuoso or equivalent), progressive JPEGs, aggressive caching of derivatives, optimistic updates, background pre-fetch of next HITL items.

---

## 8. Accessibility

- Full keyboard operability
- Visible focus rings (accent colour)
- Sufficient contrast (WCAG AA minimum, AAA preferred for text)
- Screen-reader labels on all interactive elements
- Reduced-motion preference respected
- High-contrast mode support

---

## 9. Component Strategy

Primary stack: **Next.js App Router + TypeScript + Tailwind CSS + shadcn/ui**

Custom components built on top of shadcn primitives:

- `MediaThumbnail`
- `MediaGrid` (virtualised)
- `Filmstrip`
- `HitlQueue`
- `DuplicateGroup`
- `ConfidenceBadge`
- `AiField` (with edit/override affordance)
- `FilterChipBar`
- `JobProgress`
- `MetadataPanel`
- `CommandPalette` (Cmd+K for power users)

---

## 10. Responsive Behaviour

Primary target: desktop / laptop on the local network (1920×1080 and above).

Secondary:
- Large tablets (iPad landscape) — usable review surface
- Narrow windows — collapse side panels into drawers

Mobile phones are out of scope for v1 (local network usage is desktop-centric).

---

## 11. Micro-interactions & Delight (restrained)

- Subtle scale + opacity on thumbnail hover
- Smooth spring transitions for panel open/close
- Confidence meter animates on load
- Successful accept briefly flashes green check
- No excessive animation; respect `prefers-reduced-motion`

---

## 12. Implementation Notes for Frontend Team

1. Dark theme tokens live in CSS variables; light theme is a class toggle.
2. All media URLs are local (relative to the FastAPI static / media endpoint).
3. Selection state is global (Zustand or equivalent) so it survives view switches.
4. HITL queue is the default landing page when pending items > 0.
5. Every AI field must support one-click “promote to human” or inline edit.
6. Permanent delete always shows a confirmation modal with count of items affected and a “type DELETE to confirm” for large batches.

---

## 13. Success Criteria for the UI

A user who has just finished processing three old family DVDs should be able to:

1. Open the Review queue and clear 200 items in under 15 minutes using only the keyboard.
2. Resolve a duplicate group of 8 near-identical photos in under 30 seconds.
3. Find “photos of the beach trip in 2009” via semantic search in one interaction.
4. Feel that the interface is calm, fast, and respectful of their media and time.

---

**This document is the design source of truth.**  
Any significant deviation in visual language, interaction model, or HITL flow requires an update to this file.

End of UI / UX Specification.
