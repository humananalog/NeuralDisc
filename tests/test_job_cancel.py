"""Job cancellation API."""

from __future__ import annotations

from pathlib import Path

import pytest
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


def test_cancel_queued_job(client: TestClient):
    from neuraldisc.db.database import session_scope
    from neuraldisc.db.models import Job
    from neuraldisc.jobs.control import register_job

    with session_scope() as session:
        job = Job(job_type="import", status="queued", message="waiting")
        session.add(job)
        session.flush()
        jid = job.id
    register_job(jid)

    r = client.post(f"/api/jobs/{jid}/cancel")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["cancel_requested"] is True

    r = client.get(f"/api/jobs/{jid}")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


def test_cancel_completed_rejects(client: TestClient):
    from neuraldisc.db.database import session_scope
    from neuraldisc.db.models import Job

    with session_scope() as session:
        job = Job(job_type="import", status="completed", message="done", progress=1.0)
        session.add(job)
        session.flush()
        jid = job.id

    r = client.post(f"/api/jobs/{jid}/cancel")
    assert r.status_code == 400


def test_duplicates_summary(client: TestClient):
    r = client.get("/api/duplicates/summary")
    assert r.status_code == 200
    data = r.json()
    assert "active_groups" in data
    assert "trashable" in data
    assert data["groups"] == 0
