"""SQLAlchemy ORM models matching SPECIFICATION.md §5."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Disc(Base):
    __tablename__ = "discs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    volume_name: Mapped[str] = mapped_column(String(512), nullable=False)
    volume_uuid: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    filesystem: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    inserted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    extracted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|extracting|processed|error
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_log: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    media_items: Mapped[list[MediaItem]] = relationship(back_populates="disc")


class MediaItem(Base):
    __tablename__ = "media_items"
    __table_args__ = (
        Index("ix_media_sha256", "sha256"),
        Index("ix_media_taken_at", "taken_at"),
        Index("ix_media_hitl", "hitl_status"),
        Index("ix_media_type", "media_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    disc_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("discs.id"), nullable=True)
    original_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    library_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    media_type: Mapped[str] = mapped_column(String(16), nullable=False)  # image|video
    mime_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    phash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    dhash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    taken_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    camera_make: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    camera_model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    gps_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gps_lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    orientation: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    blur_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_blurry: Mapped[bool] = mapped_column(Boolean, default=False)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    best_of_group: Mapped[bool] = mapped_column(Boolean, default=False)
    hitl_status: Mapped[str] = mapped_column(String(32), default="accepted")
    # staging = in temp until classified; library = promoted; rejected = purged;
    # trash = soft-deleted (catalogue best practice — restorable until permanent purge)
    lifecycle: Mapped[str] = mapped_column(String(32), default="library")
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_rotated: Mapped[bool] = mapped_column(Boolean, default=False)
    rotation_degrees: Mapped[int] = mapped_column(Integer, default=0)  # cumulative CW bake
    rating: Mapped[int] = mapped_column(Integer, default=0)
    flag: Mapped[bool] = mapped_column(Boolean, default=False)
    colour_label: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    disc: Mapped[Optional[Disc]] = relationship(back_populates="media_items")
    analysis: Mapped[Optional[MediaAnalysis]] = relationship(
        back_populates="media", uselist=False
    )
    embedding_meta: Mapped[Optional[EmbeddingMeta]] = relationship(
        back_populates="media", uselist=False
    )


class MediaAnalysis(Base):
    __tablename__ = "media_analysis"

    media_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("media_items.id"), primary_key=True
    )
    caption_short: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scene_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    people_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    people_desc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    objects: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    suggested_tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    estimated_era: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    model_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    analysed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    human_edited: Mapped[bool] = mapped_column(Boolean, default=False)

    media: Mapped[MediaItem] = relationship(back_populates="analysis")


class EmbeddingMeta(Base):
    __tablename__ = "embeddings"

    media_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("media_items.id"), primary_key=True
    )
    model_name: Mapped[str] = mapped_column(String(256), nullable=False)
    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    media: Mapped[MediaItem] = relationship(back_populates="embedding_meta")


class DuplicateGroup(Base):
    __tablename__ = "duplicate_groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    method: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    best_media_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("media_items.id"), nullable=True
    )

    members: Mapped[list[DuplicateMember]] = relationship(back_populates="group")


class DuplicateMember(Base):
    __tablename__ = "duplicate_members"
    __table_args__ = (UniqueConstraint("group_id", "media_id"),)

    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("duplicate_groups.id"), primary_key=True
    )
    media_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("media_items.id"), primary_key=True
    )
    similarity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    group: Mapped[DuplicateGroup] = relationship(back_populates="members")


class HitlQueueItem(Base):
    __tablename__ = "hitl_queue"
    __table_args__ = (Index("ix_hitl_priority", "priority", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    media_id: Mapped[str] = mapped_column(String(36), ForeignKey("media_items.id"), nullable=False)
    queue_type: Mapped[str] = mapped_column(String(64), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)


class Album(Base):
    """User album, AI-proposed album, or smart collection (dynamic rules).

    kind:
      - album  — fixed membership via album_items (user or auto-materialized)
      - smart  — membership resolved from rules_json at query time
    auto_key:
      - stable id for auto-generated entries, e.g. year:2007, camera:panasonic-dmc-fx7
    """

    __tablename__ = "albums"
    __table_args__ = (Index("ix_albums_auto_key", "auto_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_ai_proposed: Mapped[bool] = mapped_column(Boolean, default=False)
    kind: Mapped[str] = mapped_column(String(32), default="album")  # album | smart
    auto_key: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    rules_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # smart filters
    source: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )  # user | auto_year | auto_camera | auto_scene | auto_event | auto_disc | smart_*
    cover_media_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    items: Mapped[list[AlbumItem]] = relationship(back_populates="album")


class AlbumItem(Base):
    __tablename__ = "album_items"
    __table_args__ = (UniqueConstraint("album_id", "media_id"),)

    album_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("albums.id"), primary_key=True
    )
    media_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("media_items.id"), primary_key=True
    )
    position: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    album: Mapped[Album] = relationship(back_populates="items")


class Job(Base):
    """In-process / FS job tracking when Redis is unavailable."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
