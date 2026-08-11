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
