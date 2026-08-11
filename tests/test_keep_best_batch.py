"""Batch keep-best for duplicate groups and multi-select."""

from __future__ import annotations

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


def test_keep_best_batch_media_ids(client: TestClient, tmp_path: Path):
    # Exact duplicate pair: same pixels → same sha → one group
    disc = tmp_path / "dups"
    disc.mkdir()
    img = Image.new("RGB", (1400, 1000), (40, 90, 180))
    img.save(disc / "a.jpg", "JPEG", quality=95)
    img.save(disc / "b.jpg", "JPEG", quality=95)
    # Lower-res near copy for a second ad-hoc-ish case is still exact if same
    Image.new("RGB", (800, 600), (200, 20, 20)).save(disc / "c.jpg", "JPEG")
    Image.new("RGB", (800, 600), (200, 20, 20)).save(disc / "d.jpg", "JPEG")

    r = client.post(
        "/api/discs/ingest",
        json={"path": str(disc), "volume_name": "Dups", "process": True},
    )
    assert r.status_code == 200

    items = client.get("/api/media", params={"limit": 50}).json()["items"]
    assert len(items) >= 4
    ids = [i["id"] for i in items]

    r = client.post(
        "/api/duplicates/keep-best-batch",
        json={"media_ids": ids, "trash_losers": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kept_count"] >= 1
    assert body["trashed_count"] >= 1

    # Winners still in library
    lib = client.get("/api/media").json()
    lib_ids = {i["id"] for i in lib["items"]}
    for kid in body["kept"]:
        assert kid in lib_ids

    # Losers in trash
    trash = client.get("/api/media", params={"trash": True}).json()
    trash_ids = {i["id"] for i in trash["items"]}
    for tid in body["trashed"]:
        assert tid in trash_ids


def test_keep_best_all_groups(client: TestClient, tmp_path: Path):
    disc = tmp_path / "dups2"
    disc.mkdir()
    im = Image.new("RGB", (1100, 900), (10, 10, 10))
    im.save(disc / "x1.jpg", "JPEG")
    im.save(disc / "x2.jpg", "JPEG")

    client.post(
        "/api/discs/ingest",
        json={"path": str(disc), "volume_name": "D2", "process": True},
    )
    groups = client.get("/api/duplicates").json()
    assert len(groups) >= 1

    r = client.post(
        "/api/duplicates/keep-best-batch",
        json={"all_groups": True, "trash_losers": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["groups_resolved"] >= 1
    assert body["kept_count"] >= 1
