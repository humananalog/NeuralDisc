"""Quality gate unit + ingest integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image


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


def _jpeg(path: Path, size: tuple[int, int], color=(80, 120, 40)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "JPEG", quality=85)


def test_rejects_tiny_image(library, tmp_path: Path):
    from neuraldisc.ingest.extractor import Extractor
    from neuraldisc.db.database import session_scope
    from neuraldisc.db.models import MediaItem

    disc = tmp_path / "mixed"
    _jpeg(disc / "good_photo.jpg", (1600, 1200))
    _jpeg(disc / "favicon_like.jpg", (32, 32))
    _jpeg(disc / "web_thumb.jpg", (200, 150))
    # vector-ish naming + tiny
    _jpeg(disc / "icons" / "button.png", (64, 64), (10, 10, 10))
    (disc / "logo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>")

    result = Extractor().extract(disc, volume_name="MIX", process_after=True)
    assert len(result.files) == 1
    assert result.files[0].filename == "good_photo.jpg"
    assert len(result.rejected) >= 3

    codes = {r.code for r in result.rejected}
    assert codes & {
        "too_small",
        "file_too_small",
        "web_format_too_small",
        "junk_path",
        "junk_dir",
        "vector_or_blocked",
    }
    assert "vector_or_blocked" in codes

    with session_scope() as session:
        items = (
            session.query(MediaItem)
            .filter(MediaItem.lifecycle == "library")
            .all()
        )
        assert len(items) == 1
        assert items[0].filename == "good_photo.jpg"


def test_rejects_junk_path_names(library, tmp_path: Path):
    from neuraldisc.processing.quality import evaluate_path
    from neuraldisc.config import get_settings

    s = get_settings()
    path = tmp_path / "downloads" / "reddit_meme_thumb.jpg"
    _jpeg(path, (900, 700))
    v = evaluate_path(path, s)
    assert v.rejected
    assert v.code in {"junk_path", "junk_dir"}


def test_accepts_camera_size(library, tmp_path: Path):
    from neuraldisc.processing.quality import evaluate_path, evaluate_dimensions
    from neuraldisc.config import get_settings

    s = get_settings()
    path = tmp_path / "IMG_1234.JPG"
    _jpeg(path, (3000, 2000))
    assert evaluate_path(path, s).accepted
    assert evaluate_dimensions(3000, 2000, s).accepted
