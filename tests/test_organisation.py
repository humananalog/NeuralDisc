"""Auto albums + smart collections from EXIF / inference."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from PIL import Image
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "NeuralDisc"
    monkeypatch.setenv("NEURALDISC_LIBRARY_ROOT", str(root))
    monkeypatch.setenv("NEURALDISC_VLM_ENABLED", "false")
    monkeypatch.setenv("NEURALDISC_EMBEDDINGS_ENABLED", "false")
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


def test_auto_organise_creates_named_albums(client: TestClient, tmp_path: Path):
    disc = tmp_path / "media"
    disc.mkdir()
    for i, color in enumerate([(20, 40, 80), (90, 10, 10), (10, 120, 40), (200, 200, 20)]):
        Image.new("RGB", (1000, 800), color).save(disc / f"shot_{i}.jpg", "JPEG")

    r = client.post(
        "/api/discs/ingest",
        json={"path": str(disc), "volume_name": "BoatTrip", "process": True},
    )
    assert r.status_code == 200

    r = client.post("/api/albums/auto-organise", json={"min_members": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["albums_created"] + body["albums_updated"] + body["smart_created"] >= 1

    albums = client.get("/api/albums").json()
    assert len(albums) >= 1
    # Disc-named album or smart collection exists
    names = {a["name"] for a in albums}
    kinds = {a["kind"] for a in albums}
    assert "smart" in kinds or any("Boat" in n or "Photos" in n or "All" in n for n in names)

    # Open first album media
    aid = albums[0]["id"]
    r = client.get(f"/api/albums/{aid}/media")
    assert r.status_code == 200
    assert "items" in r.json()


def test_smart_collection_auto_name(client: TestClient):
    r = client.post(
        "/api/albums/smart",
        json={"rules": {"media_type": "image"}, "name": None},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "smart"
    assert body["name"]  # auto-named
    assert body["rules"]["media_type"] == "image"
