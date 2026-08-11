"""Capture-date resolution: EXIF first, path dates, never FileModifyDate."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest


def test_parse_date_from_path_dd_mm_yyyy():
    from neuraldisc.processing.metadata import parse_date_from_path

    dt = parse_date_from_path("Gleniff Forest Park 28-02-2005/P1010326.jpg")
    assert dt is not None
    assert dt.year == 2005
    assert dt.month == 2
    assert dt.day == 28


def test_parse_date_from_path_yyyy_mm_dd():
    from neuraldisc.processing.metadata import parse_date_from_path

    dt = parse_date_from_path("Holiday/2007-07-15/IMG_0001.JPG")
    assert dt is not None
    assert (dt.year, dt.month, dt.day) == (2007, 7, 15)


def test_parse_date_from_path_compact():
    from neuraldisc.processing.metadata import parse_date_from_path

    dt = parse_date_from_path("trip_20050228/photo.jpg")
    assert dt is not None
    assert (dt.year, dt.month, dt.day) == (2005, 2, 28)


def test_resolve_ignores_file_modify_date():
    from neuraldisc.processing.metadata import _resolve_taken_at

    now = datetime.now(timezone.utc).strftime("%Y:%m:%d %H:%M:%S")
    flat = {
        "FileModifyDate": now,
        "ModifyDate": now,
    }
    taken, src = _resolve_taken_at(
        flat,
        path=None,
        original_relpath="Gleniff Forest Park 28-02-2005/P1010326.jpg",
    )
    assert taken is not None
    assert taken.year == 2005
    assert src == "path"


def test_resolve_prefers_datetime_original():
    from neuraldisc.processing.metadata import _resolve_taken_at

    flat = {
        "DateTimeOriginal": "2005:02:28 14:30:00",
        "FileModifyDate": "2026:08:11 12:00:00",
        "ModifyDate": "2026:08:11 12:00:00",
    }
    taken, src = _resolve_taken_at(
        flat,
        original_relpath="other/folder/P1010326.jpg",
    )
    assert taken is not None
    assert taken.year == 2005
    assert src == "exif:DateTimeOriginal"


def test_repair_updates_suspicious_from_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "NeuralDisc"
    monkeypatch.setenv("NEURALDISC_LIBRARY_ROOT", str(root))
    from neuraldisc.config import reset_settings, get_settings
    from neuraldisc.db.database import reset_engine, init_engine, create_all, session_scope
    from neuraldisc.db.models import MediaItem
    from neuraldisc.processing.dates_repair import repair_taken_at
    from neuraldisc.processing.metadata import MediaMetadata

    reset_settings()
    reset_engine()
    settings = get_settings()
    settings.ensure_layout()
    init_engine(settings)
    create_all()

    lib = settings.originals_dir / "x.jpg"
    lib.parent.mkdir(parents=True, exist_ok=True)
    lib.write_bytes(b"fake")

    import_day = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    with session_scope() as session:
        m = MediaItem(
            original_path="Gleniff Forest Park 28-02-2005/P1010326.jpg",
            library_path=str(lib),
            filename="P1010326.jpg",
            media_type="image",
            sha256="a" * 64,
            taken_at=import_day,
            created_at=import_day,
        )
        session.add(m)
        session.flush()
        mid = m.id

    fake = MediaMetadata(
        taken_at=datetime(2005, 2, 28, tzinfo=timezone.utc),
        taken_at_source="path",
    )
    with patch(
        "neuraldisc.processing.dates_repair.extract_metadata",
        return_value=fake,
    ):
        with session_scope() as session:
            result = repair_taken_at(session, dry_run=False, only_suspicious=True)
            assert result.updated == 1
            row = session.get(MediaItem, mid)
            assert row is not None
            assert row.taken_at is not None
            assert row.taken_at.year == 2005

    reset_engine()
    reset_settings()
