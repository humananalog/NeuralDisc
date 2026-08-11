"""Settings API — library root configuration."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "NeuralDisc"
    prefs = tmp_path / "prefs_home" / ".neuraldisc"
    prefs.mkdir(parents=True)
    monkeypatch.setenv("NEURALDISC_LIBRARY_ROOT", str(root))
    monkeypatch.setattr("neuraldisc.prefs.APP_DIR", prefs)
    monkeypatch.setattr("neuraldisc.prefs.SETTINGS_FILE", prefs / "settings.toml")

    from neuraldisc.config import reset_settings
    from neuraldisc.db.database import reset_engine

    reset_settings()
    reset_engine()

    from neuraldisc.api.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c, tmp_path
    reset_engine()
    reset_settings()


def test_get_settings(client):
    c, _ = client
    r = c.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert "library_root" in data
    assert data["quality_enabled"] is True


def test_update_library_root(client):
    c, tmp = client
    new_root = tmp / "ExternalSSD" / "NeuralDisc"
    r = c.patch(
        "/api/settings",
        json={"library_root": str(new_root), "create_if_missing": True},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["library_root"] == str(new_root)
    assert new_root.exists()
    assert (new_root / "db").exists() or (new_root / "library").exists()

    # Persisted
    from neuraldisc.prefs import load_prefs

    prefs = load_prefs()
    assert prefs.get("library_root") == str(new_root)


def test_check_path(client):
    c, tmp = client
    p = tmp / "somewhere"
    r = c.post("/api/settings/check-path", json={"path": str(p), "create_if_missing": True})
    assert r.status_code == 200
    assert r.json()["ok"] is True
