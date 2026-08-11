"""Pydantic request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    version: str
    library_root: str
    db_ok: bool
    exiftool_ok: bool = False
    exiftool_version: Optional[str] = None


class DiscOut(BaseModel):
    id: str
    volume_name: str
    volume_uuid: Optional[str] = None
    filesystem: Optional[str] = None
    inserted_at: Optional[datetime] = None
    extracted_at: Optional[datetime] = None
    status: str
    notes: Optional[str] = None
    source_path: Optional[str] = None
    media_count: int = 0

    model_config = {"from_attributes": True}


class AnalysisOut(BaseModel):
    caption_short: Optional[str] = None
    description: Optional[str] = None
    scene_type: Optional[str] = None
    people_count: Optional[int] = None
    people_desc: Optional[str] = None
    objects: list[str] = Field(default_factory=list)
    suggested_tags: list[str] = Field(default_factory=list)
    estimated_era: Optional[str] = None
    confidence: Optional[float] = None
    model_name: Optional[str] = None
    model_version: Optional[str] = None
    analysed_at: Optional[datetime] = None
    human_edited: bool = False


class MediaOut(BaseModel):
    id: str
    disc_id: Optional[str] = None
    filename: str
    media_type: str
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration_ms: Optional[int] = None
    sha256: str
    phash: Optional[str] = None
    taken_at: Optional[datetime] = None
    camera_make: Optional[str] = None
    camera_model: Optional[str] = None
    gps_lat: Optional[float] = None
    gps_lon: Optional[float] = None
    orientation: Optional[int] = None
    quality_score: Optional[float] = None
    blur_score: Optional[float] = None
    is_blurry: bool = False
    is_duplicate: bool = False
    best_of_group: bool = False
    hitl_status: str
    lifecycle: str = "library"
    deleted_at: Optional[datetime] = None
    auto_rotated: bool = False
    rotation_degrees: int = 0
    rating: int = 0
    flag: bool = False
    colour_label: Optional[str] = None
    library_path: Optional[str] = None
    original_path: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    thumb_url: Optional[str] = None
    preview_url: Optional[str] = None
    original_url: Optional[str] = None
    analysis: Optional[AnalysisOut] = None

    model_config = {"from_attributes": True}


class MediaDeleteRequest(BaseModel):
    """Catalogue delete — soft by default, permanent with explicit flag."""

    permanent: bool = False
    ids: list[str] = Field(default_factory=list)


class MediaDeleteResponse(BaseModel):
    deleted: list[str] = Field(default_factory=list)
    trashed: list[str] = Field(default_factory=list)
    restored: list[str] = Field(default_factory=list)
    mode: str = "trash"
    count: int = 0


class MediaRotateRequest(BaseModel):
    """mode: auto | cw | ccw | 180  (cw/ccw = 90°)."""

    mode: str = "auto"


class MediaRotateResponse(BaseModel):
    media: MediaOut
    changed: bool
    method: str
    degrees_applied: int


class MediaBatchRotateRequest(BaseModel):
    """Rotate many images (selection bar). mode: auto | cw | ccw | 180."""

    ids: list[str] = Field(default_factory=list)
    mode: str = "auto"
    # User-triggered auto-rotate uses aggressive content detection
    aggressive: bool = True


class MediaBatchRotateResponse(BaseModel):
    mode: str
    rotated: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)
    failed: list[dict] = Field(default_factory=list)
    count_rotated: int = 0
    count_unchanged: int = 0
    count_failed: int = 0
    items: list[MediaOut] = Field(default_factory=list)


class MediaListResponse(BaseModel):
    items: list[MediaOut]
    total: int
    offset: int
    limit: int


class HitlItemOut(BaseModel):
    id: str
    media_id: str
    queue_type: str
    priority: int
    created_at: Optional[datetime] = None
    media: Optional[MediaOut] = None


class HitlResolveRequest(BaseModel):
    resolution: str  # accepted | rejected | edited | deferred
    caption_short: Optional[str] = None
    description: Optional[str] = None
    suggested_tags: Optional[list[str]] = None
    rating: Optional[int] = None
    flag: Optional[bool] = None


class MediaUpdateRequest(BaseModel):
    hitl_status: Optional[str] = None
    rating: Optional[int] = None
    flag: Optional[bool] = None
    colour_label: Optional[str] = None
    caption_short: Optional[str] = None
    description: Optional[str] = None
    suggested_tags: Optional[list[str]] = None


class IngestRequest(BaseModel):
    path: str
    volume_name: Optional[str] = None
    process: bool = True


class IngestResponse(BaseModel):
    disc_id: str
    volume_name: str
    files: int
    rejected: int = 0
    reject_samples: list[str] = Field(default_factory=list)
    errors: list[str]
    provenance_dir: str


class JobOut(BaseModel):
    id: str
    job_type: str
    status: str
    progress: float
    total: int
    completed: int
    message: Optional[str] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class StatsOut(BaseModel):
    total_media: int
    total_images: int
    total_videos: int
    total_discs: int
    pending_review: int
    accepted: int
    rejected: int
    duplicates: int
    blurry: int = 0
    storage_bytes: int
    has_gps: int
    albums: int = 0
    people: int = 0
    timeline: int = 0
    trash: int = 0
    jobs_active: int = 0
    duplicate_groups: int = 0


class NavCountsOut(BaseModel):
    """Sidebar badge counts for every left-nav section."""

    library: int = 0
    timeline: int = 0
    grid: int = 0
    map: int = 0
    people: int = 0
    albums: int = 0
    duplicates: int = 0
    review: int = 0
    jobs: int = 0
    stats: int = 0
    settings: int = 0
    images: int = 0
    videos: int = 0
    discs: int = 0
    trash: int = 0


class AlbumOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    is_ai_proposed: bool = False
    created_at: Optional[datetime] = None
    item_count: int = 0
    cover_media_id: Optional[str] = None

    model_config = {"from_attributes": True}


class AlbumCreate(BaseModel):
    name: str
    description: Optional[str] = None
    media_ids: list[str] = Field(default_factory=list)


class SearchRequest(BaseModel):
    q: str = ""
    media_type: Optional[str] = None
    hitl_status: Optional[str] = None
    is_duplicate: Optional[bool] = None
    rating_min: Optional[int] = None
    has_gps: Optional[bool] = None
    disc_id: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    tags: Optional[list[str]] = None
    offset: int = 0
    limit: int = 50
    sort: str = "taken_at_desc"


class DuplicateGroupOut(BaseModel):
    id: str
    method: Optional[str] = None
    best_media_id: Optional[str] = None
    created_at: Optional[str] = None
    members: list[dict[str, Any]]
