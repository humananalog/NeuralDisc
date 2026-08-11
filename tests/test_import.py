"""High-throughput import pipeline tests."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from PIL import Image


@pytest.fixture()
def library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "NeuralDisc"
    monkeypatch.setenv("NEURALDISC_LIBRARY_ROOT", str(root))
    monkeypatch.setenv("NEURALDISC_IMPORT_COPY_WORKERS", "2")
    monkeypatch.setenv("NEURALDISC_IMPORT_PROCESS_WORKERS", "2")
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


def _photo(path: Path, size=(1400, 1000), color=(40, 90, 160)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "JPEG", quality=92)


def test_import_stages_then_promotes(library, tmp_path: Path):
    from neuraldisc.ingest.importer import ImportSource, start_import, get_import_progress
    from neuraldisc.db.database import session_scope
    from neuraldisc.db.models import MediaItem, HitlQueueItem

    disc = tmp_path / "dvd"
    _photo(disc / "A.jpg", color=(10, 20, 30))
    _photo(disc / "B.jpg", color=(200, 10, 10))
    _photo(disc / "tiny.jpg", size=(64, 64))  # quality reject

    job_id = start_import([ImportSource(path=disc, name="TESTDVD", mode="folder")])

    # Wait for completion
    deadline = time.time() + 30
    progress = None
    while time.time() < deadline:
        progress = get_import_progress(job_id)
        if progress and progress.status in {"completed", "failed"}:
            break
        time.sleep(0.1)

    assert progress is not None
    assert progress.status == "completed", progress.error or progress.message
    assert progress.promoted == 2
    assert progress.rejected >= 1

    with session_scope() as session:
        lib = session.query(MediaItem).filter(MediaItem.lifecycle == "library").all()
        assert len(lib) == 2
        for m in lib:
            assert "originals" in m.library_path or "by-provenance" in m.library_path
            assert Path(m.library_path).exists()
        # HITL only for promoted
        pending = (
            session.query(HitlQueueItem)
            .filter(HitlQueueItem.resolved_at.is_(None))
            .count()
        )
        assert pending == 2


def test_import_api(library, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from fastapi.testclient import TestClient
    from neuraldisc.config import reset_settings
    from neuraldisc.db.database import reset_engine
    from neuraldisc.api.main import create_app

    disc = tmp_path / "pack"
    _photo(disc / "shot.jpg")

    app = create_app()
    with TestClient(app) as client:
        r = client.post(
            "/api/import",
            json={"mode": "media", "path": str(disc), "volume_name": "PACK"},
        )
        assert r.status_code == 200, r.text
        job_id = r.json()["job_id"]

        deadline = time.time() + 30
        status = None
        while time.time() < deadline:
            r = client.get(f"/api/import/{job_id}")
            assert r.status_code == 200
            status = r.json()
            if status["status"] in {"completed", "failed"}:
                break
            time.sleep(0.1)

        assert status is not None
        assert status["status"] == "completed"
        assert status["promoted"] >= 1


def test_import_skips_unreadable_files(library, tmp_path: Path):
    """Unreadable media must be skipped at scan time, not queued as copy errors."""
    import os
    import stat

    from neuraldisc.ingest.importer import ImportSource, start_import, get_import_progress
    from neuraldisc.db.database import session_scope
    from neuraldisc.db.models import MediaItem
    from neuraldisc.ingest.staging_processor import ensure_processor_running, wake_processor
    from neuraldisc.config import get_settings

    disc = tmp_path / "dvd_perms"
    disc.mkdir()
    _photo(disc / "good.jpg", color=(10, 20, 30))
    bad = disc / "locked.jpg"
    _photo(bad, color=(200, 10, 10))
    os.chmod(bad, 0)

    try:
        job_id = start_import([ImportSource(path=disc, name="PERMS", mode="folder")])
        deadline = time.time() + 30
        progress = None
        while time.time() < deadline:
            progress = get_import_progress(job_id)
            if progress and progress.status in {"completed", "failed"}:
                break
            time.sleep(0.1)

        assert progress is not None
        assert progress.status == "completed", progress.error or progress.message
        assert progress.errors == 0
        assert progress.copied == 1
        assert progress.rejected >= 1
        assert any("unreadable" in s for s in progress.reject_samples)

        # Wait for background promote of the one readable file
        ensure_processor_running(get_settings())
        wake_processor()
        promo_deadline = time.time() + 45
        while time.time() < promo_deadline:
            with session_scope() as session:
                n = (
                    session.query(MediaItem)
                    .filter(MediaItem.lifecycle == "library")
                    .count()
                )
            if n >= 1:
                break
            time.sleep(0.2)

        with session_scope() as session:
            lib = session.query(MediaItem).filter(MediaItem.lifecycle == "library").all()
            assert len(lib) == 1
            assert lib[0].filename == "good.jpg"
            locked = (
                session.query(MediaItem)
                .filter(MediaItem.filename == "locked.jpg")
                .count()
            )
            assert locked == 0
    finally:
        os.chmod(bad, stat.S_IRUSR | stat.S_IWUSR)
