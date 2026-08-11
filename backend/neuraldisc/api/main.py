"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from neuraldisc import __version__
from neuraldisc.api.routes import albums, discs, duplicates, hitl, jobs, media, stats
from neuraldisc.api.routes import import_routes
from neuraldisc.api.routes import settings as settings_routes
from neuraldisc.api.schemas import HealthResponse
from neuraldisc.config import get_settings
from neuraldisc.db.database import create_all, get_engine, init_engine, session_scope
from neuraldisc.db.models import Job
from neuraldisc.utils.logging import get_logger, setup_logging

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    cfg = get_settings()
    setup_logging(cfg.logs_dir)
    cfg.ensure_layout()
    init_engine(cfg)
    create_all()
    from neuraldisc.processing.metadata import exiftool_available, exiftool_version, require_exiftool
    from neuraldisc.secrets_store import apply_secrets_to_environ, list_secret_status

    apply_secrets_to_environ()
    sec = list_secret_status()
    log.info(
        "secrets_loaded",
        huggingface=sec.get("huggingface_token", {}).get("configured", False),
    )

    if not exiftool_available():
        log.error(
            "exiftool_missing",
            hint="brew install exiftool — required for all EXIF extraction",
        )
    else:
        require_exiftool()
        log.info("exiftool_ok", version=exiftool_version())
    log.info(
        "neuraldisc_api_start",
        version=__version__,
        library=str(cfg.library_root),
    )
    yield
    log.info("neuraldisc_api_stop")


def create_app() -> FastAPI:
    cfg = get_settings()
    app = FastAPI(
        title="NeuralDisc",
        version=__version__,
        description="Local-first photo & video library for Apple Silicon",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins + ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(media.router)
    app.include_router(hitl.router)
    app.include_router(discs.router)
    app.include_router(jobs.router)
    app.include_router(stats.router)
    app.include_router(albums.router)
    app.include_router(duplicates.router)
    app.include_router(settings_routes.router)
    app.include_router(import_routes.router)

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        from neuraldisc.processing.metadata import exiftool_available, exiftool_version

        s = get_settings()
        db_ok = True
        try:
            get_engine()
            with session_scope() as session:
                session.query(Job).limit(1).all()
        except Exception:  # noqa: BLE001
            db_ok = False
        et_ok = exiftool_available()
        ok = db_ok and et_ok
        return HealthResponse(
            status="ok" if ok else "degraded",
            version=__version__,
            library_root=str(s.library_root),
            db_ok=db_ok,
            exiftool_ok=et_ok,
            exiftool_version=exiftool_version() if et_ok else None,
        )

    @app.websocket("/ws/jobs")
    async def jobs_ws(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                # Client can ping; we push job snapshot
                await websocket.receive_text()
                with session_scope() as session:
                    rows = (
                        session.query(Job)
                        .order_by(Job.created_at.desc())
                        .limit(20)
                        .all()
                    )
                    payload = [
                        {
                            "id": j.id,
                            "job_type": j.job_type,
                            "status": j.status,
                            "progress": j.progress,
                            "total": j.total,
                            "completed": j.completed,
                            "message": j.message,
                        }
                        for j in rows
                    ]
                await websocket.send_json({"jobs": payload})
        except WebSocketDisconnect:
            pass

    return app


app = create_app()
