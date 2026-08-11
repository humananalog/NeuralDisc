"""Blur detector unit tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


def test_sharp_vs_blurry(tmp_path: Path):
    from neuraldisc.processing.blur import detect_blur

    # Sharp: high-frequency checkerboard
    sharp = tmp_path / "sharp.jpg"
    arr = np.indices((400, 400)).sum(axis=0) % 2 * 255
    Image.fromarray(arr.astype(np.uint8), mode="L").convert("RGB").save(sharp, "JPEG", quality=95)

    # Blurry: same after strong Gaussian
    blurry = tmp_path / "blurry.jpg"
    im = Image.open(sharp).filter(ImageFilter.GaussianBlur(radius=8))
    im.save(blurry, "JPEG", quality=95)

    s = detect_blur(sharp, threshold=80.0)
    b = detect_blur(blurry, threshold=80.0)
    assert s is not None and b is not None
    assert s.score > b.score
    assert b.is_blurry is True
    # checkerboard should be sharp
    assert s.is_blurry is False


def test_blur_in_pipeline(tmp_path: Path, monkeypatch):
    from neuraldisc.config import reset_settings, get_settings
    from neuraldisc.db.database import reset_engine, init_engine, create_all, session_scope
    from neuraldisc.db.models import MediaItem
    from neuraldisc.ingest.extractor import Extractor
    from PIL import Image, ImageFilter

    root = tmp_path / "NeuralDisc"
    monkeypatch.setenv("NEURALDISC_LIBRARY_ROOT", str(root))
    monkeypatch.setenv("NEURALDISC_BLUR_ENABLED", "true")
    monkeypatch.setenv("NEURALDISC_BLUR_THRESHOLD", "80")
    reset_settings()
    reset_engine()
    s = get_settings()
    s.ensure_layout()
    init_engine(s)
    create_all()

    disc = tmp_path / "disc"
    disc.mkdir()
    sharp = disc / "sharp.jpg"
    arr = np.indices((600, 800)).sum(axis=0) % 2 * 255
    Image.fromarray(arr.astype(np.uint8), mode="L").convert("RGB").save(sharp, "JPEG", quality=95)
    blur = disc / "blur.jpg"
    Image.open(sharp).filter(ImageFilter.GaussianBlur(12)).save(blur, "JPEG", quality=95)

    Extractor().extract(disc, volume_name="BLURTEST", process_after=True)

    with session_scope() as session:
        items = {m.filename: m for m in session.query(MediaItem).all()}
        assert "sharp.jpg" in items
        assert "blur.jpg" in items
        assert items["blur.jpg"].is_blurry is True
        assert items["blur.jpg"].flag is True
        assert items["blur.jpg"].blur_score is not None
        assert items["sharp.jpg"].is_blurry is False
        assert items["sharp.jpg"].blur_score is not None
        assert items["sharp.jpg"].blur_score > items["blur.jpg"].blur_score

    reset_engine()
    reset_settings()
