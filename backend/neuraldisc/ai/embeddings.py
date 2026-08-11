"""Embedding generation — MLX CLIP when available, else deterministic placeholder."""

from __future__ import annotations

import hashlib
import struct
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session

from neuraldisc.config import Settings
from neuraldisc.db.models import EmbeddingMeta, MediaItem
from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)

# In-memory vector store for Phase 1/2 without LanceDB
_VECTORS: dict[str, np.ndarray] = {}
_DIM = 512


def generate_embedding(
    session: Session, media: MediaItem, settings: Settings
) -> EmbeddingMeta | None:
    if media.embedding_meta:
        return media.embedding_meta

    vector: np.ndarray | None = None
    model_name = "hash-embedding-v1"
    if settings.embeddings_enabled:
        vector = _mlx_clip_embed(Path(media.library_path), settings)
        if vector is not None:
            model_name = settings.embedding_model

    if vector is None:
        vector = _hash_embedding(media)

    _VECTORS[media.id] = vector
    # Optional LanceDB write
    _try_lancedb_write(media.id, vector, settings)

    meta = EmbeddingMeta(
        media_id=media.id,
        model_name=model_name,
        dim=int(vector.shape[0]),
        created_at=datetime.now(timezone.utc),
    )
    session.add(meta)
    session.flush()
    return meta


def get_vector(media_id: str) -> np.ndarray | None:
    return _VECTORS.get(media_id)


def all_vectors() -> dict[str, np.ndarray]:
    return dict(_VECTORS)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _hash_embedding(media: MediaItem) -> np.ndarray:
    """Deterministic pseudo-embedding from content hash + attributes (dev/fallback)."""
    seed = media.sha256.encode("utf-8")
    if media.phash:
        seed += media.phash.encode("utf-8")
    rng_seed = int(hashlib.sha256(seed).hexdigest()[:16], 16) % (2**32)
    rng = np.random.default_rng(rng_seed)
    vec = rng.standard_normal(_DIM).astype(np.float32)
    # Bias by resolution / type so similar metadata correlates slightly
    if media.width and media.height:
        vec[0] += np.log1p(media.width * media.height) / 20.0
    if media.media_type == "video":
        vec[1] += 0.5
    vec /= np.linalg.norm(vec) + 1e-9
    return vec


def _mlx_clip_embed(path: Path, settings: Settings) -> np.ndarray | None:
    try:
        # Placeholder for real MLX CLIP / SigLIP integration
        log.info("mlx_clip_not_wired", path=str(path), model=settings.embedding_model)
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning("embedding_failed", error=str(exc))
        return None


def _try_lancedb_write(media_id: str, vector: np.ndarray, settings: Settings) -> None:
    try:
        import lancedb  # type: ignore

        settings.lancedb_dir.mkdir(parents=True, exist_ok=True)
        db = lancedb.connect(str(settings.lancedb_dir))
        data = [{"media_id": media_id, "vector": vector.tolist()}]
        if "image_embeddings" in db.table_names():
            tbl = db.open_table("image_embeddings")
            tbl.add(data)
        else:
            db.create_table("image_embeddings", data)
    except Exception:
        # Optional dependency / first-run
        pass


def load_vectors_from_session(session: Session) -> None:
    """No-op for hash store; embeddings recreated on process. Reserved for LanceDB load."""
    del session
