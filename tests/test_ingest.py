"""Ingest + pipeline tests against synthetic media."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image

# Use isolated library before importing app modules that cache settings
TEST_ROOT = Path(__file__).resolve().parent / "_tmp_library"


@pytest.fixture()
def library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "NeuralDisc"
    monkeypatch.setenv("NEURALDISC_LIBRARY_ROOT", str(root))
    from neuraldisc.config import reset_settings, get_settings
    from neuraldisc.db.database import reset_engine, init_engine, create_all

    reset_settings()
    reset_engine()
    settings = get_settings()
    settings.ensure_layout()
    init_engine(settings)
    create_all()
    yield settings
    reset_engine()
    reset_settings()


def _make_jpeg(path: Path, color: tuple[int, int, int] = (40, 120, 200), size=(1200, 900)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "JPEG", quality=90)


def test_extract_folder(library, tmp_path: Path):
    from neuraldisc.ingest.extractor import Extractor
    from neuraldisc.db.database import session_scope
    from neuraldisc.db.models import Disc, MediaItem

    disc_dir = tmp_path / "fake_disc"
    _make_jpeg(disc_dir / "IMG_001.JPG", (10, 20, 30))
    _make_jpeg(disc_dir / "sub" / "IMG_002.JPG", (200, 10, 10))
    (disc_dir / "readme.txt").write_text("ignore me")

    result = Extractor().extract(disc_dir, volume_name="TESTDISC", process_after=True)
    assert result.disc_id
    assert len(result.files) == 2
    assert len(result.errors) == 0

    with session_scope() as session:
        disc = session.get(Disc, result.disc_id)
        assert disc is not None
        assert disc.status == "processed"
        items = session.query(MediaItem).filter(MediaItem.disc_id == result.disc_id).all()
        assert len(items) == 2
        for item in items:
            assert item.sha256
            assert Path(item.library_path).exists()
            # pipeline should have set dimensions
            assert item.width == 1200
            assert item.height == 900
            assert item.hitl_status == "pending"
            assert item.phash is not None


def test_exact_duplicate_detection(library, tmp_path: Path):
    from neuraldisc.ingest.extractor import Extractor
    from neuraldisc.db.database import session_scope
    from neuraldisc.db.models import MediaItem, DuplicateGroup

    src = tmp_path / "dup_disc"
    _make_jpeg(src / "a.jpg", (50, 50, 50))
    # identical copy
    data = (src / "a.jpg").read_bytes()
    (src / "b.jpg").write_bytes(data)

    Extractor().extract(src, volume_name="DUPS", process_after=True)

    with session_scope() as session:
        items = session.query(MediaItem).all()
        assert len(items) == 2
        assert all(i.is_duplicate for i in items)
        groups = session.query(DuplicateGroup).all()
        assert len(groups) >= 1
        assert groups[0].method == "exact"


def test_cli_init(library):
    from neuraldisc.config import get_settings

    s = get_settings()
    assert s.sqlite_path.parent.exists()
    assert s.originals_dir.exists()
