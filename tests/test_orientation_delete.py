"""Auto-orient + catalogue trash/permanent delete."""

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


def _ingest_image(client: TestClient, tmp_path: Path, name: str = "shot.jpg", size=(1200, 800), color=(20, 80, 160)):
    disc = tmp_path / "media"
    disc.mkdir(exist_ok=True)
    Image.new("RGB", size, color).save(disc / name, "JPEG")
    r = client.post(
        "/api/discs/ingest",
        json={"path": str(disc), "volume_name": "T", "process": True},
    )
    assert r.status_code == 200
    items = client.get("/api/media").json()["items"]
    assert items
    return items[0]


def test_soft_delete_and_restore(client: TestClient, tmp_path: Path):
    item = _ingest_image(client, tmp_path)
    mid = item["id"]

    r = client.delete(f"/api/media/{mid}")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "trash"
    assert mid in body["trashed"]

    # Gone from library
    lib = client.get("/api/media").json()
    assert all(i["id"] != mid for i in lib["items"])

    # Present in trash
    trash = client.get("/api/media", params={"trash": True}).json()
    assert any(i["id"] == mid for i in trash["items"])

    # Restore
    r = client.post(f"/api/media/{mid}/restore")
    assert r.status_code == 200
    assert r.json()["lifecycle"] == "library"

    lib = client.get("/api/media").json()
    assert any(i["id"] == mid for i in lib["items"])


def test_permanent_delete(client: TestClient, tmp_path: Path):
    item = _ingest_image(client, tmp_path, name="gone.jpg")
    mid = item["id"]
    path = item.get("library_path")

    r = client.delete(f"/api/media/{mid}", params={"permanent": True})
    assert r.status_code == 200
    assert r.json()["mode"] == "permanent"

    r = client.get(f"/api/media/{mid}")
    assert r.status_code == 404

    if path:
        assert not Path(path).exists()


def test_permanent_delete_with_duplicate_fk(client: TestClient, tmp_path: Path):
    """Permanent delete must clear duplicate_groups.best_media_id FK."""
    disc = tmp_path / "dupdel"
    disc.mkdir()
    img = Image.new("RGB", (1200, 900), (11, 22, 33))
    img.save(disc / "a.jpg", "JPEG")
    img.save(disc / "b.jpg", "JPEG")
    r = client.post(
        "/api/discs/ingest",
        json={"path": str(disc), "volume_name": "DupDel", "process": True},
    )
    assert r.status_code == 200
    items = client.get("/api/media").json()["items"]
    assert len(items) >= 2
    ids = [i["id"] for i in items[:2]]

    r = client.post(
        "/api/media/batch-delete",
        json={"ids": ids, "permanent": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "permanent"
    assert body["count"] >= 1
    for mid in body["deleted"]:
        assert client.get(f"/api/media/{mid}").status_code == 404


def test_batch_delete(client: TestClient, tmp_path: Path):
    a = _ingest_image(client, tmp_path, name="a.jpg", color=(1, 2, 3))
    # Second file needs a fresh folder or same folder re-ingest
    disc = tmp_path / "media2"
    disc.mkdir()
    Image.new("RGB", (1000, 800), (9, 9, 9)).save(disc / "b.jpg", "JPEG")
    client.post("/api/discs/ingest", json={"path": str(disc), "volume_name": "T2", "process": True})
    items = client.get("/api/media").json()["items"]
    ids = [i["id"] for i in items[:2]]
    assert len(ids) >= 1

    r = client.post("/api/media/batch-delete", json={"ids": ids, "permanent": False})
    assert r.status_code == 200
    assert r.json()["count"] >= 1

    trash = client.get("/api/media", params={"trash": True}).json()
    trash_ids = {i["id"] for i in trash["items"]}
    assert any(i in trash_ids for i in ids)


def test_auto_orient_module(tmp_path: Path):
    from neuraldisc.processing.orientation import auto_orient_image, rotate_image

    # Create sideways image with EXIF Orientation=6 (90 CW)
    src = tmp_path / "side.jpg"
    im = Image.new("RGB", (400, 200), (200, 50, 50))
    # Landscape pixels; Orientation 6 means display as portrait
    exif = im.getexif()
    exif[274] = 6
    im.save(src, "JPEG", exif=exif)

    result = auto_orient_image(src, content_fallback=False)
    assert result.changed is True
    assert result.method == "exif"
    assert result.orientation_after == 1
    # After orient 6 bake, dimensions swap
    assert result.width == 200
    assert result.height == 400

    # Manual rotate
    r2 = rotate_image(src, 90)
    assert r2.changed is True
    assert r2.degrees_applied == 90


def test_rotate_api(client: TestClient, tmp_path: Path):
    item = _ingest_image(client, tmp_path, name="rot.jpg")
    mid = item["id"]

    r = client.post(f"/api/media/{mid}/rotate", json={"mode": "cw"})
    assert r.status_code == 200
    body = r.json()
    assert body["changed"] is True
    assert body["degrees_applied"] == 90
    assert body["media"]["id"] == mid
