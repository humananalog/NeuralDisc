"""Auto-resume supervisor smoke tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "NeuralDisc"
    monkeypatch.setenv("NEURALDISC_LIBRARY_ROOT", str(root))
    monkeypatch.setenv("NEURALDISC_VLM_ENABLED", "false")
    monkeypatch.setenv("NEURALDISC_AUTO_RESUME_ENABLED", "true")
    monkeypatch.setenv("NEURALDISC_AUTO_RESUME_INFERENCE", "false")
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


def test_supervisor_status_and_tick(client: TestClient):
    r = client.get("/api/jobs/supervisor")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "supervisor" in body
    assert "staging_pending" in body

    r = client.post("/api/jobs/supervisor/tick")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert "actions" in r.json()


def test_recovery_pass_wakes_staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NEURALDISC_LIBRARY_ROOT", str(tmp_path / "lib"))
    monkeypatch.setenv("NEURALDISC_AUTO_RESUME_ENABLED", "true")
    monkeypatch.setenv("NEURALDISC_AUTO_RESUME_INFERENCE", "false")
    from neuraldisc.config import get_settings, reset_settings
    from neuraldisc.db.database import create_all, init_engine, reset_engine, session_scope
    from neuraldisc.db.models import MediaItem
    from neuraldisc.jobs.supervisor import run_recovery_pass

    reset_settings()
    reset_engine()
    s = get_settings()
    s.ensure_layout()
    init_engine(s)
    create_all()

    with session_scope() as session:
        session.add(
            MediaItem(
                filename="orphan.jpg",
                original_path="orphan.jpg",
                media_type="image",
                library_path=str(tmp_path / "missing.jpg"),
                sha256="a" * 64,
                lifecycle="staging",
                hitl_status="accepted",
            )
        )

    actions = run_recovery_pass(s)
    assert any("staging" in a for a in actions)

    reset_engine()
    reset_settings()
