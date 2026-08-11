"""API smoke tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "NeuralDisc"
    monkeypatch.setenv("NEURALDISC_LIBRARY_ROOT", str(root))
    from neuraldisc.config import reset_settings
    from neuraldisc.db.database import reset_engine

    reset_settings()
    reset_engine()

    from neuraldisc.api.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c
    reset_engine()
    reset_settings()


def test_health(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] in ("ok", "degraded")
    assert data["db_ok"] is True


def test_ingest_and_list(client: TestClient, tmp_path: Path):
    disc = tmp_path / "media"
    disc.mkdir()
    Image.new("RGB", (1200, 900), (90, 10, 200)).save(disc / "shot.jpg", "JPEG")

    r = client.post("/api/discs/ingest", json={"path": str(disc), "volume_name": "API", "process": True})
    assert r.status_code == 200
    body = r.json()
    assert body["files"] == 1

    r = client.get("/api/media")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    assert data["items"][0]["filename"] == "shot.jpg"

    mid = data["items"][0]["id"]
    r = client.get(f"/api/media/{mid}")
    assert r.status_code == 200

    r = client.get("/api/hitl/queue")
    assert r.status_code == 200
    assert len(r.json()) >= 1

    r = client.get("/api/stats")
    assert r.status_code == 200
    assert r.json()["total_media"] >= 1
