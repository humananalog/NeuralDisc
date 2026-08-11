"""Stale / orphan job recovery."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "NeuralDisc"
    monkeypatch.setenv("NEURALDISC_LIBRARY_ROOT", str(root))
    monkeypatch.setenv("NEURALDISC_VLM_ENABLED", "false")
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


def test_reap_stale_closes_orphan_running(client: TestClient):
    from neuraldisc.db.database import session_scope
    from neuraldisc.db.models import Job

    with session_scope() as session:
        job = Job(
            job_type="import",
            status="running",
            message="stuck after restart",
            total=100,
            completed=50,
            progress=0.5,
        )
        session.add(job)
        session.flush()
        jid = job.id

    # Manual clear (only_orphans) — no age wait, no live worker
    r = client.post("/api/jobs/reap-stale", params={"force": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] >= 1
    assert any(x["id"] == jid for x in body["reaped"])

    r = client.get(f"/api/jobs/{jid}")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "interrupted"
    assert data["stale"] is False  # no longer active


def test_reap_skips_registered_live_worker(client: TestClient):
    from neuraldisc.db.database import session_scope
    from neuraldisc.db.models import Job
    from neuraldisc.jobs.control import clear_cancel, register_job

    with session_scope() as session:
        job = Job(
            job_type="inference",
            status="running",
            message="live",
            total=10,
            completed=1,
            progress=0.1,
        )
        session.add(job)
        session.flush()
        jid = job.id

    register_job(jid)
    try:
        r = client.post("/api/jobs/reap-stale")
        assert r.status_code == 200
        assert not any(x["id"] == jid for x in r.json()["reaped"])
        r = client.get(f"/api/jobs/{jid}")
        assert r.json()["status"] == "running"
        assert r.json()["has_live_worker"] is True
        assert r.json()["stale"] is False
    finally:
        clear_cancel(jid)


def test_list_marks_stale_flag(client: TestClient):
    from neuraldisc.db.database import session_scope
    from neuraldisc.db.models import Job
    from datetime import datetime, timedelta, timezone

    with session_scope() as session:
        # Old running job without worker — lazy list reap should catch it
        job = Job(
            job_type="import",
            status="running",
            message="zombie",
            total=10,
            completed=1,
            progress=0.1,
            started_at=datetime.now(timezone.utc) - timedelta(hours=5),
            created_at=datetime.now(timezone.utc) - timedelta(hours=5),
        )
        session.add(job)
        session.flush()
        jid = job.id

    # Lazy reap on list should catch old running job
    r = client.get("/api/jobs")
    assert r.status_code == 200
    jobs = r.json()
    mine = next((j for j in jobs if j["id"] == jid), None)
    # Either reaped to interrupted, or still listed as stale
    if mine:
        assert mine["status"] == "interrupted" or mine.get("stale") is True
