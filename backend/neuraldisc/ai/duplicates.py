"""Multi-stage duplicate detection: exact → pHash → embedding.

Also provides keep-best resolution for single groups and batch selection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from neuraldisc.ai.embeddings import cosine_similarity, get_vector
from neuraldisc.config import Settings
from neuraldisc.db.models import DuplicateGroup, DuplicateMember, HitlQueueItem, MediaItem
from neuraldisc.processing.catalogue import soft_delete_media
from neuraldisc.processing.hashes import hamming_hex
from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)


def find_duplicates_for_media(
    session: Session, media: MediaItem, settings: Settings
) -> DuplicateGroup | None:
    """Find or create a duplicate group for this media item."""
    # 1. Exact SHA-256
    exact = (
        session.query(MediaItem)
        .filter(MediaItem.sha256 == media.sha256, MediaItem.id != media.id)
        .all()
    )
    if exact:
        return _attach_group(session, media, exact, method="exact", similarity=1.0)

    # 2. Perceptual hash
    if media.phash:
        near: list[tuple[MediaItem, float]] = []
        candidates = (
            session.query(MediaItem)
            .filter(MediaItem.phash.isnot(None), MediaItem.id != media.id)
            .all()
        )
        for other in candidates:
            if not other.phash:
                continue
            dist = hamming_hex(media.phash, other.phash)
            if dist <= settings.phash_threshold:
                sim = 1.0 - (dist / 64.0)
                near.append((other, sim))
        if near:
            others = [m for m, _ in near]
            sim = max(s for _, s in near)
            return _attach_group(session, media, others, method="phash", similarity=sim)

    # 3. Embedding similarity
    vec = get_vector(media.id)
    if vec is not None:
        semantic: list[tuple[MediaItem, float]] = []
        others = session.query(MediaItem).filter(MediaItem.id != media.id).all()
        for other in others:
            ov = get_vector(other.id)
            if ov is None:
                continue
            sim = cosine_similarity(vec, ov)
            if sim >= settings.embedding_similarity_threshold:
                semantic.append((other, sim))
        if semantic:
            best_sim = max(s for _, s in semantic)
            return _attach_group(
                session,
                media,
                [m for m, _ in semantic],
                method="embedding",
                similarity=best_sim,
            )

    return None


def _attach_group(
    session: Session,
    media: MediaItem,
    others: list[MediaItem],
    method: str,
    similarity: float,
) -> DuplicateGroup:
    # Reuse existing group of any member
    existing_group: DuplicateGroup | None = None
    for o in others:
        member = (
            session.query(DuplicateMember)
            .filter(DuplicateMember.media_id == o.id)
            .first()
        )
        if member:
            existing_group = session.get(DuplicateGroup, member.group_id)
            break

    if existing_group is None:
        existing_group = DuplicateGroup(
            method=method,
            created_at=datetime.now(timezone.utc),
        )
        session.add(existing_group)
        session.flush()
        for o in others:
            session.add(
                DuplicateMember(
                    group_id=existing_group.id,
                    media_id=o.id,
                    similarity=similarity,
                )
            )
            o.is_duplicate = True

    # Add current media if not already a member
    already = (
        session.query(DuplicateMember)
        .filter(
            DuplicateMember.group_id == existing_group.id,
            DuplicateMember.media_id == media.id,
        )
        .first()
    )
    if not already:
        session.add(
            DuplicateMember(
                group_id=existing_group.id,
                media_id=media.id,
                similarity=similarity,
            )
        )
    media.is_duplicate = True
    session.flush()

    # Score best version
    members = (
        session.query(MediaItem)
        .join(DuplicateMember, DuplicateMember.media_id == MediaItem.id)
        .filter(DuplicateMember.group_id == existing_group.id)
        .all()
    )
    if not members:
        members = [media, *others]
    best = max(members, key=_best_score)
    for m in members:
        m.best_of_group = m.id == best.id
    existing_group.best_media_id = best.id
    existing_group.method = method
    # No HITL queue — resolve dups in Duplicates UI; AI keep-best is source of truth until then

    session.flush()
    log.info(
        "duplicate_group",
        group_id=existing_group.id,
        method=method,
        members=len(members),
        best=best.id,
    )
    return existing_group


def _best_score(m: MediaItem) -> float:
    """Higher is better. Prefers resolution, sharpness, quality, EXIF richness."""
    if (m.lifecycle or "library") in ("trash", "rejected"):
        return -1.0
    res = float((m.width or 0) * (m.height or 0))
    quality = m.quality_score if m.quality_score is not None else 0.5
    # Sharpness: blur_score is Laplacian variance — higher = sharper
    sharpness = 1.0
    if m.blur_score is not None:
        # Normalize loosely around typical thresholds (~80–500)
        sharpness = 0.4 + min(1.6, max(0.0, m.blur_score) / 250.0)
    if m.is_blurry:
        sharpness *= 0.35
    exif = 1.0
    if m.taken_at:
        exif += 0.12
    if m.camera_make:
        exif += 0.06
    if m.gps_lat is not None:
        exif += 0.05
    if m.rating and m.rating > 0:
        exif += 0.04 * m.rating
    if m.flag:
        exif *= 0.85  # slight penalty for user-flagged
    # Prefer library lifecycle over staging
    life = 1.0 if (m.lifecycle or "library") == "library" else 0.9
    return res * quality * sharpness * exif * life


def pick_best(members: list[MediaItem]) -> MediaItem | None:
    active = [
        m
        for m in members
        if (m.lifecycle or "library") not in ("trash", "rejected")
    ]
    if not active:
        return None
    return max(active, key=_best_score)


@dataclass
class KeepBestResult:
    groups_resolved: int = 0
    kept: list[str] = field(default_factory=list)
    trashed: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    details: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "groups_resolved": self.groups_resolved,
            "kept": self.kept,
            "trashed": self.trashed,
            "rejected": self.rejected,
            "skipped": self.skipped,
            "kept_count": len(self.kept),
            "trashed_count": len(self.trashed),
            "details": self.details,
        }


def keep_best_among(
    session: Session,
    members: list[MediaItem],
    *,
    group: DuplicateGroup | None = None,
    trash_losers: bool = True,
    source: str = "group",
) -> KeepBestResult:
    """Keep the single best image among members; reject/trash the rest.

    Catalogue pattern: winner → accepted + best_of_group; losers → trash (soft)
    or hitl rejected if trash_losers is False.
    """
    result = KeepBestResult()
    active = [
        m
        for m in members
        if (m.lifecycle or "library") not in ("trash", "rejected")
    ]
    if len(active) < 2:
        for m in active:
            result.skipped.append(m.id)
        return result

    best = pick_best(active)
    if best is None:
        return result

    now = datetime.now(timezone.utc)
    loser_ids: list[str] = []

    for m in active:
        if m.id == best.id:
            m.hitl_status = "accepted"
            m.best_of_group = True
            m.is_duplicate = False  # sole survivor from this resolution
            m.updated_at = now
            result.kept.append(m.id)
        else:
            m.best_of_group = False
            m.hitl_status = "rejected"
            m.updated_at = now
            loser_ids.append(m.id)
            if trash_losers:
                soft_delete_media(session, m)
                result.trashed.append(m.id)
            else:
                result.rejected.append(m.id)

    if group is not None:
        group.best_media_id = best.id
        result.groups_resolved = 1
        # Drop trashed/rejected losers from the group so the UI no longer lists them
        if loser_ids:
            session.query(DuplicateMember).filter(
                DuplicateMember.group_id == group.id,
                DuplicateMember.media_id.in_(loser_ids),
            ).delete(synchronize_session=False)
        # If fewer than 2 library members remain, dissolve the group entirely
        _prune_group_if_resolved(session, group.id)

    # Resolve open HITL for everyone in the set
    all_ids = [m.id for m in active]
    for item in (
        session.query(HitlQueueItem)
        .filter(
            HitlQueueItem.media_id.in_(all_ids),
            HitlQueueItem.resolved_at.is_(None),
        )
        .all()
    ):
        item.resolved_at = now
        item.resolution = "keep_best" if item.media_id == best.id else "rejected_keep_best"

    session.flush()
    result.details.append(
        {
            "source": source,
            "group_id": group.id if group else None,
            "kept": best.id,
            "losers": loser_ids,
            "method": group.method if group else "selection",
        }
    )
    log.info(
        "keep_best",
        source=source,
        group_id=group.id if group else None,
        kept=best.id,
        losers=len(loser_ids),
        trash=trash_losers,
    )
    return result


def keep_best_for_group(
    session: Session,
    group_id: str,
    *,
    trash_losers: bool = True,
) -> KeepBestResult:
    group = session.get(DuplicateGroup, group_id)
    if not group:
        return KeepBestResult()
    members = (
        session.query(MediaItem)
        .join(DuplicateMember, DuplicateMember.media_id == MediaItem.id)
        .filter(DuplicateMember.group_id == group_id)
        .all()
    )
    # Re-score best before resolving
    best = pick_best(members)
    if best:
        for m in members:
            m.best_of_group = m.id == best.id
        group.best_media_id = best.id
        session.flush()
    return keep_best_among(
        session, members, group=group, trash_losers=trash_losers, source="group"
    )


def keep_best_batch(
    session: Session,
    *,
    group_ids: list[str] | None = None,
    media_ids: list[str] | None = None,
    all_groups: bool = False,
    trash_losers: bool = True,
) -> KeepBestResult:
    """Resolve keep-best across many groups or a multi-select batch.

    Modes (priority):
    1. ``all_groups`` — every duplicate group in the library
    2. ``group_ids`` — listed groups
    3. ``media_ids`` — batch selection:
       - Cluster selected items by existing duplicate groups
       - For each cluster with ≥2 selected members, keep best among **selected**
       - Selected items with no group membership form one ad-hoc cluster if ≥2
    """
    merged = KeepBestResult()

    def _merge(partial: KeepBestResult) -> None:
        merged.groups_resolved += partial.groups_resolved
        merged.kept.extend(partial.kept)
        merged.trashed.extend(partial.trashed)
        merged.rejected.extend(partial.rejected)
        merged.skipped.extend(partial.skipped)
        merged.details.extend(partial.details)

    target_group_ids: list[str] = []
    if all_groups:
        target_group_ids = [gid for (gid,) in session.query(DuplicateGroup.id).all()]
    elif group_ids:
        target_group_ids = list(dict.fromkeys(group_ids))

    if target_group_ids:
        for gid in target_group_ids:
            _merge(keep_best_for_group(session, gid, trash_losers=trash_losers))
        return merged

    if not media_ids:
        return merged

    ids = list(dict.fromkeys(media_ids))
    items = session.query(MediaItem).filter(MediaItem.id.in_(ids)).all()
    by_id = {m.id: m for m in items}

    # Map media → group
    memberships = (
        session.query(DuplicateMember)
        .filter(DuplicateMember.media_id.in_(ids))
        .all()
    )
    group_to_selected: dict[str, list[MediaItem]] = {}
    in_group: set[str] = set()
    for mem in memberships:
        m = by_id.get(mem.media_id)
        if not m:
            continue
        group_to_selected.setdefault(mem.group_id, []).append(m)
        in_group.add(m.id)

    # Resolve each group cluster (among selected members only; ≥2)
    for gid, selected_members in group_to_selected.items():
        # Prefer full group resolution when user selected ≥2 from that group
        # so keep-best is against the true best_of_group candidate set they care about
        if len(selected_members) < 2:
            # Single pick from a group: skip auto-trash of unselected siblings
            for m in selected_members:
                merged.skipped.append(m.id)
            continue
        group = session.get(DuplicateGroup, gid)
        # Use full group members if most of the group is selected; else selected only
        full = (
            session.query(MediaItem)
            .join(DuplicateMember, DuplicateMember.media_id == MediaItem.id)
            .filter(DuplicateMember.group_id == gid)
            .all()
        )
        full_active = [
            m
            for m in full
            if (m.lifecycle or "library") not in ("trash", "rejected")
        ]
        selected_set = {m.id for m in selected_members}
        # If selection covers the whole active group, resolve full group;
        # otherwise resolve among selection only (user chose a subset).
        pool = full_active if selected_set >= {m.id for m in full_active} else selected_members
        _merge(
            keep_best_among(
                session,
                pool,
                group=group,
                trash_losers=trash_losers,
                source="selection_group",
            )
        )

    # Ad-hoc: selected items not in any duplicate group
    ad_hoc = [by_id[i] for i in ids if i not in in_group and i in by_id]
    if len(ad_hoc) >= 2:
        _merge(
            keep_best_among(
                session,
                ad_hoc,
                group=None,
                trash_losers=trash_losers,
                source="selection_adhoc",
            )
        )
    else:
        for m in ad_hoc:
            merged.skipped.append(m.id)

    return merged


def _is_active_lifecycle(lifecycle: str | None) -> bool:
    return (lifecycle or "library") not in ("trash", "rejected")


def _prune_group_if_resolved(session: Session, group_id: str) -> bool:
    """Remove group when fewer than 2 non-trash members remain. Returns True if deleted."""
    members = (
        session.query(MediaItem)
        .join(DuplicateMember, DuplicateMember.media_id == MediaItem.id)
        .filter(DuplicateMember.group_id == group_id)
        .all()
    )
    alive = [m for m in members if _is_active_lifecycle(m.lifecycle)]
    if len(alive) >= 2:
        return False
    # Clear duplicate flag on remaining survivors
    for m in alive:
        m.is_duplicate = False
        m.best_of_group = False
    session.query(DuplicateMember).filter(DuplicateMember.group_id == group_id).delete(
        synchronize_session=False
    )
    g = session.get(DuplicateGroup, group_id)
    if g:
        session.delete(g)
    session.flush()
    log.info("duplicate_group_pruned", group_id=group_id, remaining=len(alive))
    return True


def prune_resolved_duplicate_groups(session: Session) -> dict:
    """Dissolve groups that no longer have ≥2 library members (e.g. after trash)."""
    groups = session.query(DuplicateGroup).all()
    pruned = 0
    for g in groups:
        if _prune_group_if_resolved(session, g.id):
            pruned += 1
    # Also strip trashed members from still-active groups so UI doesn't show ghosts
    trashed_members = (
        session.query(DuplicateMember)
        .join(MediaItem, MediaItem.id == DuplicateMember.media_id)
        .filter(MediaItem.lifecycle.in_(("trash", "rejected")))
        .all()
    )
    stripped = 0
    for mem in trashed_members:
        session.delete(mem)
        stripped += 1
    session.flush()
    # Re-prune after stripping
    for g in session.query(DuplicateGroup).all():
        if _prune_group_if_resolved(session, g.id):
            pruned += 1
    log.info("duplicate_groups_cleanup", pruned=pruned, stripped=stripped)
    return {"pruned": pruned, "stripped": stripped}


def list_duplicate_groups(
    session: Session,
    *,
    include_resolved: bool = False,
    prune: bool = True,
) -> list[dict]:
    """List duplicate groups.

    By default only **active** groups (≥2 non-trash members) are returned and
    resolved/ghost groups are pruned so counts match the UI.
    """
    if prune:
        try:
            prune_resolved_duplicate_groups(session)
        except Exception as exc:  # noqa: BLE001
            log.debug("prune_on_list_failed", error=str(exc))

    groups = session.query(DuplicateGroup).order_by(DuplicateGroup.created_at.desc()).all()
    out = []
    for g in groups:
        members = (
            session.query(MediaItem, DuplicateMember.similarity)
            .join(DuplicateMember, DuplicateMember.media_id == MediaItem.id)
            .filter(DuplicateMember.group_id == g.id)
            .all()
        )
        # Default: only library members in the payload
        visible = [
            (m, sim)
            for m, sim in members
            if include_resolved or _is_active_lifecycle(m.lifecycle)
        ]
        alive_n = sum(1 for m, _ in members if _is_active_lifecycle(m.lifecycle))
        is_active = alive_n >= 2
        if not include_resolved and not is_active:
            continue
        out.append(
            {
                "id": g.id,
                "method": g.method,
                "best_media_id": g.best_media_id,
                "created_at": g.created_at.isoformat() if g.created_at else None,
                "active": is_active,
                "members": [
                    {
                        "media_id": m.id,
                        "filename": m.filename,
                        "similarity": sim,
                        "best_of_group": m.best_of_group,
                        "width": m.width,
                        "height": m.height,
                        "quality_score": m.quality_score,
                        "blur_score": m.blur_score,
                        "is_blurry": bool(m.is_blurry),
                        "lifecycle": m.lifecycle or "library",
                        "library_path": m.library_path,
                        "thumb_url": f"/api/media/{m.id}/thumb",
                    }
                    for m, sim in visible
                ],
            }
        )
    return out


def duplicate_summary(session: Session, *, prune: bool = True) -> dict:
    """Top-line counts for the Duplicates page header / sidebar badge.

    ``prune=False`` for hot paths (nav / stats polls) — pruning walks every
    group and must not run on a 2s UI timer during imports.
    """
    # Prune ghosts first so counts match what the list returns
    if prune:
        try:
            prune_resolved_duplicate_groups(session)
        except Exception as exc:  # noqa: BLE001
            log.debug("prune_on_summary_failed", error=str(exc))
    groups = list_duplicate_groups(session, include_resolved=True, prune=False)
    active_groups = 0
    resolved_groups = 0
    total_members = 0
    active_members = 0
    unique_media: set[str] = set()
    active_unique: set[str] = set()
    best_count = 0
    trashable = 0  # non-best active members (potential keep-best savings)
    by_method: dict[str, int] = {}
    total_bytes_active = 0
    trashable_bytes = 0

    for g in groups:
        method = g.get("method") or "unknown"
        by_method[method] = by_method.get(method, 0) + 1
        members = g.get("members") or []
        alive = [m for m in members if (m.get("lifecycle") or "library") not in ("trash", "rejected")]
        total_members += len(members)
        for m in members:
            mid = m.get("media_id")
            if mid:
                unique_media.add(mid)
        if len(alive) >= 2:
            active_groups += 1
            active_members += len(alive)
            for m in alive:
                mid = m.get("media_id")
                if mid:
                    active_unique.add(mid)
                if m.get("best_of_group"):
                    best_count += 1
                else:
                    trashable += 1
        else:
            resolved_groups += 1

    # Optional file sizes from DB for active duplicate media
    if active_unique:
        rows = (
            session.query(MediaItem.id, MediaItem.file_size, MediaItem.best_of_group)
            .filter(MediaItem.id.in_(list(active_unique)))
            .all()
        )
        for mid, size, is_best in rows:
            sz = int(size or 0)
            total_bytes_active += sz
            if not is_best:
                trashable_bytes += sz

    return {
        "groups": len(groups),
        "active_groups": active_groups,
        "resolved_groups": resolved_groups,
        "total_members": total_members,
        "active_members": active_members,
        "unique_media": len(unique_media),
        "active_unique_media": len(active_unique),
        "best_count": best_count,
        "trashable": trashable,
        "by_method": by_method,
        "active_bytes": total_bytes_active,
        "trashable_bytes": trashable_bytes,
    }
