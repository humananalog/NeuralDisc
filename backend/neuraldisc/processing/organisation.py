"""Smart collections + auto albums from EXIF and VLM inference.

Auto-naming uses human-readable titles derived from:
  - EXIF: year, month, camera, disc/provenance
  - Inference: scene_type, primary tags, people

Smart collections store JSON rules and resolve membership dynamically.
Auto albums materialize members (idempotent via auto_key).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from neuraldisc.db.models import Album, AlbumItem, Disc, MediaAnalysis, MediaItem
from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)

_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _aware_taken_at(dt: datetime | None) -> datetime:
    """Sort key helper — SQLite may return naive datetimes."""
    if dt is None:
        return _EPOCH
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# Minimum members to create an auto album / smart collection
MIN_ALBUM = 2
MIN_SCENE = 3
MIN_TAG = 3
EVENT_GAP_DAYS = 3


def _library_filter():
    return or_(MediaItem.lifecycle == "library", MediaItem.lifecycle.is_(None))


def _slug(parts: Iterable[str]) -> str:
    s = "-".join(p.strip().lower() for p in parts if p and str(p).strip())
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:200] or "untitled"


def _title_case_scene(raw: str) -> str:
    t = raw.replace("_", " ").replace("-", " ").strip()
    if not t or t.lower() in ("unknown", "none", "n/a"):
        return ""
    return " ".join(w.capitalize() for w in t.split())


def _month_name(dt: datetime) -> str:
    return dt.strftime("%B %Y")


def _loads_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except json.JSONDecodeError:
        pass
    return []


@dataclass
class OrgResult:
    albums_created: int = 0
    albums_updated: int = 0
    smart_created: int = 0
    smart_updated: int = 0
    members_linked: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "albums_created": self.albums_created,
            "albums_updated": self.albums_updated,
            "smart_created": self.smart_created,
            "smart_updated": self.smart_updated,
            "members_linked": self.members_linked,
            "details": self.details[:50],
        }


def resolve_smart_media_ids(session: Session, rules: dict[str, Any], limit: int = 2000) -> list[str]:
    """Evaluate smart-collection rules → media ids (library only)."""
    q = (
        session.query(MediaItem.id)
        .outerjoin(MediaAnalysis, MediaAnalysis.media_id == MediaItem.id)
        .filter(_library_filter())
    )

    if rules.get("media_type"):
        q = q.filter(MediaItem.media_type == rules["media_type"])
    if rules.get("year") is not None:
        # SQLite: strftime
        q = q.filter(func.strftime("%Y", MediaItem.taken_at) == str(rules["year"]))
    if rules.get("year_month"):
        q = q.filter(func.strftime("%Y-%m", MediaItem.taken_at) == str(rules["year_month"]))
    if rules.get("camera_make"):
        q = q.filter(MediaItem.camera_make.ilike(f"%{rules['camera_make']}%"))
    if rules.get("camera_model"):
        q = q.filter(MediaItem.camera_model.ilike(f"%{rules['camera_model']}%"))
    if rules.get("disc_id"):
        q = q.filter(MediaItem.disc_id == rules["disc_id"])
    if rules.get("has_gps") is True:
        q = q.filter(MediaItem.gps_lat.isnot(None))
    if rules.get("has_gps") is False:
        q = q.filter(MediaItem.gps_lat.is_(None))
    if rules.get("is_blurry") is True:
        q = q.filter(MediaItem.is_blurry.is_(True))
    if rules.get("is_duplicate") is True:
        q = q.filter(MediaItem.is_duplicate.is_(True))
    if rules.get("hitl_status"):
        q = q.filter(MediaItem.hitl_status == rules["hitl_status"])
    if rules.get("scene_type"):
        q = q.filter(MediaAnalysis.scene_type.ilike(f"%{rules['scene_type']}%"))
    if rules.get("estimated_era"):
        q = q.filter(MediaAnalysis.estimated_era.ilike(f"%{rules['estimated_era']}%"))
    if rules.get("people_min") is not None:
        q = q.filter(MediaAnalysis.people_count >= int(rules["people_min"]))
    if rules.get("people_max") is not None:
        q = q.filter(MediaAnalysis.people_count <= int(rules["people_max"]))
    if rules.get("tag"):
        # JSON list stored as text — simple LIKE
        tag = str(rules["tag"])
        q = q.filter(MediaAnalysis.suggested_tags.ilike(f"%{tag}%"))
    if rules.get("q"):
        term = f"%{rules['q']}%"
        q = q.filter(
            or_(
                MediaItem.filename.ilike(term),
                MediaAnalysis.caption_short.ilike(term),
                MediaAnalysis.description.ilike(term),
            )
        )

    q = q.order_by(MediaItem.taken_at.desc().nullslast(), MediaItem.created_at.desc())
    return [r[0] for r in q.limit(limit).all()]


def _upsert_album(
    session: Session,
    *,
    auto_key: str,
    name: str,
    description: str,
    source: str,
    kind: str,
    rules: dict[str, Any] | None,
    media_ids: list[str],
    is_ai: bool = True,
    materialize: bool = True,
) -> tuple[Album, bool]:
    """Create or update album by auto_key. Returns (album, created)."""
    album = session.query(Album).filter(Album.auto_key == auto_key).first()
    created = False
    now = datetime.now(timezone.utc)
    rules_s = json.dumps(rules) if rules else None

    if album is None:
        album = Album(
            name=name,
            description=description,
            is_ai_proposed=is_ai,
            kind=kind,
            auto_key=auto_key,
            rules_json=rules_s,
            source=source,
            created_at=now,
            updated_at=now,
        )
        session.add(album)
        session.flush()
        created = True
    else:
        album.name = name
        album.description = description
        album.kind = kind
        album.rules_json = rules_s
        album.source = source
        album.is_ai_proposed = is_ai
        album.updated_at = now

    if materialize and kind == "album":
        # Replace membership
        session.query(AlbumItem).filter(AlbumItem.album_id == album.id).delete(
            synchronize_session=False
        )
        for i, mid in enumerate(media_ids):
            session.add(AlbumItem(album_id=album.id, media_id=mid, position=i))
        album.cover_media_id = media_ids[0] if media_ids else None
    elif kind == "smart":
        # Cover from first resolved id
        album.cover_media_id = media_ids[0] if media_ids else album.cover_media_id

    session.flush()
    return album, created


def auto_organise(
    session: Session,
    *,
    include_years: bool = True,
    include_months: bool = True,
    include_cameras: bool = True,
    include_scenes: bool = True,
    include_tags: bool = True,
    include_discs: bool = True,
    include_events: bool = True,
    include_people: bool = True,
    include_smart: bool = True,
    min_members: int = MIN_ALBUM,
) -> OrgResult:
    """Build auto-named albums + smart collections from library media."""
    result = OrgResult()

    items = (
        session.query(MediaItem)
        .options(joinedload(MediaItem.analysis))
        .filter(_library_filter())
        .order_by(MediaItem.taken_at.asc().nullslast())
        .all()
    )
    if not items:
        return result

    discs = {d.id: d for d in session.query(Disc).all()}

    # --- Group buckets ---
    by_year: dict[str, list[MediaItem]] = defaultdict(list)
    by_month: dict[str, list[MediaItem]] = defaultdict(list)
    by_camera: dict[str, list[MediaItem]] = defaultdict(list)
    by_scene: dict[str, list[MediaItem]] = defaultdict(list)
    by_tag: dict[str, list[MediaItem]] = defaultdict(list)
    by_disc: dict[str, list[MediaItem]] = defaultdict(list)
    with_people: list[MediaItem] = []
    with_gps: list[MediaItem] = []

    for m in items:
        if m.taken_at:
            y = str(m.taken_at.year)
            ym = m.taken_at.strftime("%Y-%m")
            by_year[y].append(m)
            by_month[ym].append(m)
        cam_parts = [p for p in (m.camera_make, m.camera_model) if p]
        if cam_parts:
            cam_key = " ".join(cam_parts)
            by_camera[cam_key].append(m)
        if m.disc_id:
            by_disc[m.disc_id].append(m)
        if m.gps_lat is not None:
            with_gps.append(m)
        a = m.analysis
        if a:
            scene = _title_case_scene(a.scene_type or "")
            if scene:
                by_scene[scene].append(m)
            if a.people_count and a.people_count > 0:
                with_people.append(m)
            for tag in _loads_list(a.suggested_tags)[:8]:
                if len(tag) >= 2:
                    by_tag[tag.lower()].append(m)

    def _commit_album(
        auto_key: str,
        name: str,
        description: str,
        source: str,
        members: list[MediaItem],
        *,
        kind: str = "album",
        rules: dict | None = None,
        min_n: int | None = None,
    ) -> None:
        thr = min_n if min_n is not None else min_members
        if len(members) < thr:
            return
        # Prefer dated order for materialization
        ordered = sorted(members, key=lambda x: _aware_taken_at(x.taken_at))
        ids = [m.id for m in ordered]
        # Cover: best rated then sharpest then first
        cover_src = max(
            ordered,
            key=lambda x: (
                x.rating or 0,
                0 if x.is_blurry else 1,
                x.blur_score or 0,
                (x.width or 0) * (x.height or 0),
            ),
        )
        ids = [cover_src.id] + [i for i in ids if i != cover_src.id]
        album, created = _upsert_album(
            session,
            auto_key=auto_key,
            name=name,
            description=description,
            source=source,
            kind=kind,
            rules=rules,
            media_ids=ids,
            materialize=(kind == "album"),
        )
        if kind == "smart":
            if created:
                result.smart_created += 1
            else:
                result.smart_updated += 1
        else:
            if created:
                result.albums_created += 1
            else:
                result.albums_updated += 1
            result.members_linked += len(ids)
        result.details.append(
            {
                "auto_key": auto_key,
                "name": name,
                "kind": kind,
                "source": source,
                "count": len(ids),
                "created": created,
            }
        )

    # EXIF years
    if include_years:
        for y, members in sorted(by_year.items()):
            _commit_album(
                f"year:{y}",
                name=y,
                description=f"All library photos and videos from {y} (EXIF date).",
                source="auto_year",
                members=members,
            )

    # EXIF months
    if include_months:
        for ym, members in sorted(by_month.items()):
            try:
                dt = datetime.strptime(ym + "-01", "%Y-%m-%d")
                title = _month_name(dt)
            except ValueError:
                title = ym
            _commit_album(
                f"month:{ym}",
                name=title,
                description=f"Media taken in {title} (EXIF date).",
                source="auto_month",
                members=members,
            )

    # EXIF cameras
    if include_cameras:
        for cam, members in sorted(by_camera.items(), key=lambda kv: -len(kv[1])):
            _commit_album(
                f"camera:{_slug([cam])}",
                name=cam,
                description=f"Shot with {cam} (EXIF camera make/model).",
                source="auto_camera",
                members=members,
            )

    # Disc / provenance
    if include_discs:
        for did, members in by_disc.items():
            disc = discs.get(did)
            label = disc.volume_name if disc else f"Disc {did[:8]}"
            _commit_album(
                f"disc:{did}",
                name=label,
                description=f"Imported from disc “{label}” (provenance).",
                source="auto_disc",
                members=members,
            )

    # Inference scenes
    if include_scenes:
        for scene, members in sorted(by_scene.items(), key=lambda kv: -len(kv[1])):
            _commit_album(
                f"scene:{_slug([scene])}",
                name=scene,
                description=f"AI scene type: {scene}.",
                source="auto_scene",
                members=members,
                min_n=MIN_SCENE,
            )

    # Inference tags (top tags only)
    if include_tags:
        top_tags = sorted(by_tag.items(), key=lambda kv: -len(kv[1]))[:40]
        for tag, members in top_tags:
            # unique media
            uniq: dict[str, MediaItem] = {m.id: m for m in members}
            if len(uniq) < MIN_TAG:
                continue
            nice = tag.replace("_", " ").title()
            _commit_album(
                f"tag:{_slug([tag])}",
                name=f"#{nice}" if not nice.startswith("#") else nice,
                description=f"AI suggested tag “{tag}”.",
                source="auto_tag",
                members=list(uniq.values()),
                min_n=MIN_TAG,
            )

    # People (any people_count > 0)
    if include_people and len(with_people) >= min_members:
        _commit_album(
            "people:with-people",
            name="People",
            description="Media where AI detected one or more people.",
            source="auto_people",
            members=with_people,
        )

    # Events: cluster consecutive dated media (gap > EVENT_GAP_DAYS starts new event)
    if include_events:
        dated = [m for m in items if m.taken_at]
        dated.sort(key=lambda m: _aware_taken_at(m.taken_at))
        clusters: list[list[MediaItem]] = []
        cur: list[MediaItem] = []
        for m in dated:
            if not cur:
                cur = [m]
                continue
            prev = cur[-1].taken_at
            gap = (m.taken_at - prev) if prev and m.taken_at else timedelta(days=999)
            if gap <= timedelta(days=EVENT_GAP_DAYS):
                cur.append(m)
            else:
                if len(cur) >= min_members:
                    clusters.append(cur)
                cur = [m]
        if len(cur) >= min_members:
            clusters.append(cur)

        for cluster in clusters:
            starts = [m.taken_at for m in cluster if m.taken_at]
            if not starts:
                continue
            t0, t1 = min(starts), max(starts)
            if t0.date() == t1.date():
                title = t0.strftime("%-d %b %Y") if hasattr(t0, "strftime") else str(t0.date())
                # Portable day format
                title = f"{t0.day} {t0.strftime('%b %Y')}"
            else:
                if t0.year == t1.year and t0.month == t1.month:
                    title = f"{t0.day}–{t1.day} {t0.strftime('%b %Y')}"
                elif t0.year == t1.year:
                    title = f"{t0.strftime('%b')}–{t1.strftime('%b %Y')}"
                else:
                    title = f"{t0.year}–{t1.year}"

            # Enrich with dominant scene
            scenes: dict[str, int] = defaultdict(int)
            for m in cluster:
                if m.analysis and m.analysis.scene_type:
                    sc = _title_case_scene(m.analysis.scene_type)
                    if sc:
                        scenes[sc] += 1
            scene_bit = ""
            if scenes:
                top_scene = max(scenes.items(), key=lambda kv: kv[1])[0]
                if scenes[top_scene] >= max(2, len(cluster) // 4):
                    scene_bit = f" · {top_scene}"

            name = f"{title}{scene_bit}"
            key = f"event:{t0.strftime('%Y%m%d')}-{t1.strftime('%Y%m%d')}-{len(cluster)}"
            _commit_album(
                key,
                name=name,
                description=(
                    f"Auto event cluster {t0.date()} → {t1.date()} "
                    f"({len(cluster)} items, gap ≤ {EVENT_GAP_DAYS} days)."
                ),
                source="auto_event",
                members=cluster,
            )

    # --- Built-in smart collections (dynamic rules) ---
    if include_smart:
        smart_defs = [
            (
                "smart:recent-pending",
                "Needs review",
                "Pending HITL items in the library.",
                {"hitl_status": "pending"},
            ),
            (
                "smart:blurry",
                "Blurry shots",
                "Flagged soft / out-of-focus images.",
                {"is_blurry": True},
            ),
            (
                "smart:has-gps",
                "On the map",
                "Media with EXIF GPS coordinates.",
                {"has_gps": True},
            ),
            (
                "smart:videos",
                "Videos",
                "All video items in the library.",
                {"media_type": "video"},
            ),
            (
                "smart:photos",
                "All photos",
                "All still images in the library.",
                {"media_type": "image"},
            ),
            (
                "smart:duplicates",
                "Duplicates",
                "Items marked as duplicates.",
                {"is_duplicate": True},
            ),
            (
                "smart:people",
                "With people (smart)",
                "AI people_count ≥ 1 (dynamic).",
                {"people_min": 1},
            ),
        ]
        # Year smart collections for each year present
        for y in sorted(by_year.keys()):
            smart_defs.append(
                (
                    f"smart:year:{y}",
                    f"Year {y} (live)",
                    f"Dynamic smart collection for EXIF year {y}.",
                    {"year": int(y)},
                )
            )

        for auto_key, name, desc, rules in smart_defs:
            ids = resolve_smart_media_ids(session, rules)
            if not ids and auto_key.startswith("smart:year:"):
                continue
            # Always keep structural smarts even if empty? Skip empty year; keep utility ones
            if not ids and auto_key in (
                "smart:blurry",
                "smart:duplicates",
                "smart:videos",
                "smart:has-gps",
                "smart:people",
            ):
                # still create so they appear when data arrives
                pass
            album, created = _upsert_album(
                session,
                auto_key=auto_key,
                name=name,
                description=desc,
                source="smart_builtin",
                kind="smart",
                rules=rules,
                media_ids=ids,
                materialize=False,
            )
            if created:
                result.smart_created += 1
            else:
                result.smart_updated += 1
            result.details.append(
                {
                    "auto_key": auto_key,
                    "name": name,
                    "kind": "smart",
                    "source": "smart_builtin",
                    "count": len(ids),
                    "created": created,
                }
            )

    session.flush()
    log.info(
        "auto_organise_done",
        albums_created=result.albums_created,
        albums_updated=result.albums_updated,
        smart_created=result.smart_created,
        smart_updated=result.smart_updated,
        members=result.members_linked,
    )
    return result


def album_member_ids(session: Session, album: Album, limit: int = 2000) -> list[str]:
    """Resolve members for fixed album or smart collection."""
    if (album.kind or "album") == "smart" and album.rules_json:
        try:
            rules = json.loads(album.rules_json)
        except json.JSONDecodeError:
            rules = {}
        return resolve_smart_media_ids(session, rules, limit=limit)
    rows = (
        session.query(AlbumItem.media_id)
        .filter(AlbumItem.album_id == album.id)
        .order_by(AlbumItem.position.asc().nullslast())
        .limit(limit)
        .all()
    )
    return [r[0] for r in rows]
