"""Database engine, sessions, and schema initialisation."""

from __future__ import annotations

import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from neuraldisc.config import Settings, get_settings
from neuraldisc.db.models import Base
from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None

# SQLite allows one writer. Serialize session_scope so import + staging +
# supervisor never open overlapping write transactions.
_WRITE_LOCK = threading.RLock()

FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS media_fts USING fts5(
    media_id UNINDEXED,
    filename,
    caption_short,
    description,
    scene_type,
    people_desc,
    objects,
    suggested_tags,
    camera_make,
    camera_model,
    tokenize='porter unicode61'
);
"""


def get_database_url(sqlite_path: Path) -> str:
    return f"sqlite:///{sqlite_path}"


def init_engine(settings: Settings | None = None) -> Engine:
    global _engine, _SessionLocal
    settings = settings or get_settings()
    settings.ensure_layout()
    url = get_database_url(settings.sqlite_path)
    # NullPool: avoid QueuePool connection storms on SQLite
    _engine = create_engine(
        url,
        connect_args={
            "check_same_thread": False,
            "timeout": 120.0,
        },
        poolclass=NullPool,
    )

    @event.listens_for(_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):  # type: ignore[no-untyped-def]
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=120000")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA wal_autocheckpoint=1000")
        cursor.close()

    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        return init_engine()
    return _engine


def create_all(engine: Engine | None = None) -> None:
    eng = engine or get_engine()
    Base.metadata.create_all(bind=eng)
    with eng.begin() as conn:
        conn.execute(text(FTS_DDL))
        _ensure_column(conn, "media_items", "lifecycle", "TEXT DEFAULT 'library'")
        _ensure_column(conn, "media_items", "blur_score", "REAL")
        _ensure_column(conn, "media_items", "is_blurry", "BOOLEAN DEFAULT 0")
        _ensure_column(conn, "media_items", "deleted_at", "TIMESTAMP")
        _ensure_column(conn, "media_items", "auto_rotated", "BOOLEAN DEFAULT 0")
        _ensure_column(conn, "media_items", "rotation_degrees", "INTEGER DEFAULT 0")
        _ensure_column(conn, "albums", "kind", "TEXT DEFAULT 'album'")
        _ensure_column(conn, "albums", "auto_key", "TEXT")
        _ensure_column(conn, "albums", "rules_json", "TEXT")
        _ensure_column(conn, "albums", "source", "TEXT")
        _ensure_column(conn, "albums", "cover_media_id", "TEXT")
        _ensure_column(conn, "albums", "updated_at", "TIMESTAMP")
    log.info("database_schema_ready", path=str(eng.url))


def _ensure_column(conn, table: str, column: str, col_def: str) -> None:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    names = {r[1] for r in rows}
    if column not in names:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"))
        log.info("schema_column_added", table=table, column=column)


def is_sqlite_locked(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "database is locked" in msg or "database is busy" in msg


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Session with a process-wide write lock.

    Keep bodies short — never EXIF / VLM / large file I/O inside this context.
    """
    if _SessionLocal is None:
        init_engine()
    assert _SessionLocal is not None

    _WRITE_LOCK.acquire()
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        _WRITE_LOCK.release()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency — shares the process-wide write lock."""
    if _SessionLocal is None:
        init_engine()
    assert _SessionLocal is not None
    _WRITE_LOCK.acquire()
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        _WRITE_LOCK.release()


def reset_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
