"""SOTA local vision-language analysis via mlx-vlm (Qwen2.5-VL).

Classifies every photo/keyframe into structured fields:
  scene_type, people_count, people_desc, objects, tags, caption, era, quality.

Requires: pip install mlx mlx-vlm  and  NEURALDISC_VLM_ENABLED=true
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from neuraldisc.config import Settings
from neuraldisc.db.models import MediaAnalysis, MediaItem
from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)

# Canonical scene taxonomy (model should pick closest; free text allowed as fallback)
SCENE_TAXONOMY = [
    "portrait",
    "group_photo",
    "family",
    "indoor",
    "outdoor",
    "landscape",
    "cityscape",
    "beach",
    "water",
    "boat",
    "travel",
    "food",
    "restaurant",
    "party",
    "celebration",
    "sports",
    "nature",
    "architecture",
    "document",
    "screenshot",
    "pet",
    "vehicle",
    "night",
    "sunset",
    "other",
]

VLM_PROMPT = f"""You are an expert photo archivist. Analyse this photograph carefully.
Return ONLY a single valid JSON object (no markdown fences, no commentary) with exactly these keys:

{{
  "caption_short": "concise 5-12 word English caption",
  "description": "1-3 sentence description of what is happening, setting, and notable details",
  "scene_type": "one primary label from: {', '.join(SCENE_TAXONOMY)}",
  "people_count": 0,
  "people_desc": "ages/genders/roles/pose if any people, else empty string",
  "objects": ["salient objects, max 12, lowercase"],
  "suggested_tags": ["search tags, max 15, lowercase, include scene + objects + activities"],
  "estimated_era": "decade like 2000s or unknown",
  "quality_score": 0.0,
  "confidence": 0.0
}}

Rules:
- people_count is an integer count of distinct people visible (0 if none).
- quality_score 0-1 for photographic quality (focus, exposure, composition).
- confidence 0-1 for how sure you are about the analysis.
- caption_short: concise 5-12 word English caption (strict word limit)
- description: at most 2 short sentences
- Prefer specific tags (e.g. "ferry", "harbour") over generic ones.
- If the image is blurry or low quality, lower quality_score and still describe content.
- Keep the entire JSON under ~600 tokens; never omit closing braces.
"""

_model_lock = threading.Lock()
_model_cache: dict[str, Any] = {}
# Reference count for nested batch/single analysis so we only release when idle
_load_refcount = 0
_load_refcount_lock = threading.Lock()


def _vlm_failure_attempts(model_version: str | None) -> int:
    """Parse attempt count from model_version like ``vlm-failed`` / ``vlm-failed:3``."""
    if not model_version:
        return 0
    v = model_version.lower().strip()
    if v.startswith("vlm-gave-up"):
        return 10_000
    if v == "vlm-failed":
        return 1
    if v.startswith("vlm-failed:"):
        try:
            return max(1, int(v.split(":", 1)[1]))
        except ValueError:
            return 1
    return 0


def analyse_media(
    session: Session,
    media: MediaItem,
    settings: Settings,
    *,
    prior_vlm_failures: int = 0,
    precomputed: dict[str, Any] | None = None,
    precomputed_model: tuple[str, str] | None = None,
) -> MediaAnalysis | None:
    if media.analysis:
        return media.analysis

    result: dict[str, Any] | None = precomputed
    model_name = "heuristic-fallback"
    model_version = "0.1.0"
    if precomputed is not None and precomputed_model:
        model_name, model_version = precomputed_model

    if result is None and settings.vlm_enabled:
        from neuraldisc.mlx_plane_lease import MlxPlaneLeaseError, ensure_lease_held

        try:
            ensure_lease_held(vlm_enabled=True, purpose="vlm_batch")
        except MlxPlaneLeaseError as exc:
            # Do not write heuristic — leave pending so we retry when plane is free
            log.warning(
                "vlm_deferred_no_lease",
                media_id=media.id,
                reason=exc.reason,
                blocker=exc.blocker,
            )
            return None

        image_path = Path(media.library_path)
        # Prefer preview derivative for speed if available
        preview = settings.previews_dir / f"{media.id}.jpg"
        if preview.exists():
            image_path = preview
        try:
            result = _run_mlx_vlm(image_path, settings)
        except MlxPlaneLeaseError as exc:
            log.warning(
                "vlm_deferred_no_lease",
                media_id=media.id,
                reason=exc.reason,
                blocker=exc.blocker,
            )
            return None
        if result:
            model_name = settings.vlm_model
            model_version = "mlx-vlm"

    if result is None:
        if settings.vlm_enabled:
            attempts = max(0, int(prior_vlm_failures)) + 1
            max_auto = max(1, int(getattr(settings, "vlm_auto_retry_max", 2) or 2))
            log.warning(
                "vlm_fallback_heuristic",
                media_id=media.id,
                attempts=attempts,
                max_auto=max_auto,
            )
            model_name = "heuristic-fallback"
            # After max auto retries, leave the auto-chain queue (manual re-run still ok)
            if attempts >= max_auto:
                model_version = "vlm-gave-up"
            else:
                model_version = f"vlm-failed:{attempts}"
        result = _heuristic_analysis(media)

    result = _normalize_result(result, media)

    analysis = MediaAnalysis(
        media_id=media.id,
        caption_short=result.get("caption_short"),
        description=result.get("description"),
        scene_type=result.get("scene_type"),
        people_count=result.get("people_count"),
        people_desc=result.get("people_desc"),
        objects=json.dumps(result.get("objects") or [], ensure_ascii=False),
        suggested_tags=json.dumps(result.get("suggested_tags") or [], ensure_ascii=False),
        estimated_era=result.get("estimated_era"),
        confidence=float(result.get("confidence") or 0.5),
        model_name=model_name,
        model_version=model_version,
        analysed_at=datetime.now(timezone.utc),
    )
    qs = result.get("quality_score")
    if qs is not None:
        media.quality_score = float(qs)
    session.add(analysis)
    session.flush()
    return analysis


def reanalyse_media(session: Session, media: MediaItem, settings: Settings) -> MediaAnalysis | None:
    """Force re-run VLM (delete existing analysis)."""
    prior = 0
    if media.analysis is not None:
        prior = _vlm_failure_attempts(media.analysis.model_version)
    # Use bulk delete to avoid SQLAlchemy relationship nulling the PK on MediaAnalysis
    session.query(MediaAnalysis).filter(MediaAnalysis.media_id == media.id).delete(
        synchronize_session=False
    )
    session.expire(media, ["analysis"])
    media.analysis = None
    session.flush()
    return analyse_media(session, media, settings, prior_vlm_failures=prior)


def _heuristic_analysis(media: MediaItem) -> dict[str, Any]:
    tags: list[str] = [media.media_type]
    if media.camera_make:
        tags.append(media.camera_make.lower())
    if media.camera_model:
        tags.append(media.camera_model.lower().replace(" ", "-"))
    if media.gps_lat is not None:
        tags.append("geo-tagged")
    if media.taken_at:
        tags.append(str(media.taken_at.year))
        era = f"{(media.taken_at.year // 10) * 10}s"
    else:
        era = "unknown"

    quality = 0.5
    if media.width and media.height:
        mp = (media.width * media.height) / 1_000_000
        quality = min(1.0, 0.35 + mp / 12.0)
    if media.is_blurry:
        quality = min(quality, 0.35)

    stem = Path(media.filename).stem.replace("_", " ")
    caption = f"{media.media_type.title()}: {stem}"
    return {
        "caption_short": caption[:120],
        "description": f"Imported {media.media_type} '{media.filename}'"
        + (f" from {media.camera_make} {media.camera_model}" if media.camera_make else "")
        + ".",
        "scene_type": "other",
        "people_count": 0,
        "people_desc": "",
        "objects": [],
        "suggested_tags": tags,
        "estimated_era": era,
        "quality_score": round(quality, 3),
        "confidence": 0.25,
    }


def _get_model(settings: Settings) -> tuple[Any, Any, Any]:
    """Load and cache model/processor/config once per process.

    Requires a valid peer MLX plane lease when lease gating is active.
    """
    from neuraldisc.mlx_plane_lease import (
        MlxPlaneLeaseError,
        current_lease,
        ensure_lease_held,
        lease_required,
    )

    if lease_required(vlm_enabled=settings.vlm_enabled):
        ensure_lease_held(vlm_enabled=True, purpose="vlm_batch")
        if current_lease() is None:
            raise MlxPlaneLeaseError(
                "Cannot load VLM without an active MLX plane lease",
                reason="no_lease",
            )

    key = settings.vlm_model
    with _model_lock:
        if key in _model_cache:
            return _model_cache[key]
        from mlx_vlm import load  # type: ignore
        from mlx_vlm.utils import load_config  # type: ignore

        log.info("vlm_loading", model=key)
        model, processor = load(key)
        config = load_config(key)
        _model_cache[key] = (model, processor, config)
        try:
            import mlx.core as mx

            active = mx.metal.get_active_memory() if mx.metal.is_available() else None
            log.info("vlm_loaded", model=key, metal_active_bytes=active)
        except Exception:  # noqa: BLE001
            log.info("vlm_loaded", model=key)
        return model, processor, config


def release_vlm(
    *, force: bool = False, release_plane_lease: bool = True
) -> dict[str, Any]:
    """Unload VLM weights, clear MLX Metal cache, and drop peer plane lease.

    Call after inference batches so ViniMidas / peers can reclaim unified memory.
    Safe to call when nothing is loaded.
    """
    global _load_refcount
    with _load_refcount_lock:
        if not force and _load_refcount > 0:
            return {
                "released": False,
                "reason": "in_use",
                "refcount": _load_refcount,
                "loaded": list(_model_cache.keys()),
            }

    freed_models: list[str] = []
    with _model_lock:
        freed_models = list(_model_cache.keys())
        _model_cache.clear()

    # Drop Python refs then clear Metal allocator cache
    import gc

    gc.collect()
    metal_before = metal_after = None
    try:
        import mlx.core as mx

        if mx.metal.is_available():
            metal_before = mx.metal.get_active_memory()
            mx.clear_cache()
            mx.metal.clear_cache()
            gc.collect()
            metal_after = mx.metal.get_active_memory()
    except Exception as exc:  # noqa: BLE001
        log.warning("mlx_clear_cache_failed", error=str(exc))

    with _load_refcount_lock:
        if force:
            _load_refcount = 0

    plane_lease: dict[str, Any] = {"released": False, "reason": "skipped"}
    if release_plane_lease:
        try:
            from neuraldisc.mlx_plane_lease import release as release_lease

            plane_lease = release_lease()
        except Exception as exc:  # noqa: BLE001
            log.warning("mlx_plane_lease_release_failed", error=str(exc))
            plane_lease = {"released": False, "error": str(exc)}

    log.info(
        "vlm_released",
        models=freed_models,
        force=force,
        metal_before=metal_before,
        metal_after=metal_after,
        plane_lease=plane_lease.get("released"),
    )
    return {
        "released": True,
        "models": freed_models,
        "metal_active_before": metal_before,
        "metal_active_after": metal_after,
        "refcount": _load_refcount,
        "plane_lease": plane_lease,
    }


class vlm_session:
    """Acquire peer lease, keep model loaded for a batch, release MLX on exit."""

    def __init__(
        self,
        *,
        release_on_exit: bool = True,
        purpose: str = "vlm_batch",
        holder_id: str | None = None,
    ) -> None:
        self.release_on_exit = release_on_exit
        self.purpose = purpose
        self.holder_id = holder_id

    def __enter__(self) -> "vlm_session":
        global _load_refcount
        from neuraldisc.config import get_settings
        from neuraldisc.mlx_plane_lease import (
            acquire,
            current_lease,
            ensure_lease_held,
        )

        settings = get_settings()
        if settings.vlm_enabled:
            if self.holder_id and current_lease() is None:
                acquire(self.holder_id, purpose=self.purpose)
            else:
                ensure_lease_held(vlm_enabled=True, purpose=self.purpose)
        with _load_refcount_lock:
            _load_refcount += 1
        return self

    def __exit__(self, *exc: object) -> None:
        global _load_refcount
        with _load_refcount_lock:
            _load_refcount = max(0, _load_refcount - 1)
            still = _load_refcount
        if self.release_on_exit and still == 0:
            release_vlm(force=True)


def _run_mlx_vlm(path: Path, settings: Settings) -> dict[str, Any] | None:
    try:
        from mlx_vlm import generate  # type: ignore
        from mlx_vlm.prompt_utils import apply_chat_template  # type: ignore

        model, processor, config = _get_model(settings)
        formatted = apply_chat_template(
            processor, config, VLM_PROMPT, num_images=1
        )
        max_tokens = max(256, int(getattr(settings, "vlm_max_tokens", 1536) or 1536))
        with _model_lock:
            out = generate(
                model,
                processor,
                formatted,
                [str(path)],
                verbose=False,
                max_tokens=max_tokens,
                temp=0.2,
            )
        # mlx-vlm may return str or object with .text
        if hasattr(out, "text"):
            text = out.text
        elif isinstance(out, tuple) and out:
            text = str(out[0])
        else:
            text = out if isinstance(out, str) else str(out)
        parsed = _parse_json_blob(text)
        if parsed is None:
            log.warning("vlm_json_parse_failed", sample=text[:200], chars=len(text))
        return parsed
    except Exception as exc:  # noqa: BLE001
        from neuraldisc.mlx_plane_lease import MlxPlaneLeaseError

        if isinstance(exc, MlxPlaneLeaseError):
            log.warning(
                "mlx_vlm_lease_blocked",
                error=str(exc),
                reason=exc.reason,
                path=str(path),
            )
            raise
        log.warning("mlx_vlm_failed", error=str(exc), path=str(path))
        return None


def _parse_json_blob(text: str) -> dict[str, Any] | None:
    text = text.strip()
    # Strip markdown fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    if start < 0:
        return None
    end = text.rfind("}")
    blob = text[start : end + 1] if end > start else text[start:]
    parsed = _loads_json_lenient(blob)
    if parsed is not None:
        return parsed
    # Truncated generation: close open strings / brackets and retry
    repaired = _repair_truncated_json(blob)
    if repaired and repaired != blob:
        return _loads_json_lenient(repaired)
    return None


def _loads_json_lenient(blob: str) -> dict[str, Any] | None:
    try:
        data = json.loads(blob)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        fixed = re.sub(r",\s*}", "}", blob)
        fixed = re.sub(r",\s*]", "]", fixed)
        try:
            data = json.loads(fixed)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def _repair_truncated_json(blob: str) -> str | None:
    """Best-effort close of truncated model JSON (common when max_tokens cuts mid-string)."""
    if not blob or not blob.lstrip().startswith("{"):
        return None
    s = blob.rstrip()
    # If we ended mid-string, close the quote
    in_string = False
    escape = False
    for ch in s:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
    if in_string:
        s += '"'
    s = re.sub(r",\s*$", "", s)
    # Count unmatched braces/brackets outside strings (approx after close)
    opens_brace = s.count("{") - s.count("}")
    opens_brack = s.count("[") - s.count("]")
    if opens_brack > 0:
        s += "]" * opens_brack
    if opens_brace > 0:
        s += "}" * opens_brace
    return s


def _normalize_result(result: dict[str, Any], media: MediaItem) -> dict[str, Any]:
    """Coerce types and fill gaps from EXIF."""
    out = dict(result)

    # people_count
    pc = out.get("people_count", 0)
    try:
        out["people_count"] = int(pc)
    except (TypeError, ValueError):
        out["people_count"] = 0

    # lists
    for key in ("objects", "suggested_tags"):
        val = out.get(key) or []
        if isinstance(val, str):
            val = [v.strip() for v in val.split(",") if v.strip()]
        if not isinstance(val, list):
            val = []
        out[key] = [str(x).strip().lower() for x in val if str(x).strip()][:15]

    # scene
    scene = str(out.get("scene_type") or "other").strip().lower().replace(" ", "_")
    if scene not in SCENE_TAXONOMY:
        # map common synonyms
        synonyms = {
            "group": "group_photo",
            "people": "group_photo",
            "sea": "water",
            "ocean": "water",
            "lake": "water",
            "ship": "boat",
            "yacht": "boat",
            "dinner": "food",
            "meal": "food",
            "party": "party",
            "city": "cityscape",
            "building": "architecture",
        }
        scene = synonyms.get(scene, "other")
    out["scene_type"] = scene

    # era from EXIF if model said unknown
    era = str(out.get("estimated_era") or "unknown")
    if era in ("unknown", "", "none") and media.taken_at:
        era = f"{(media.taken_at.year // 10) * 10}s"
    out["estimated_era"] = era

    # scores
    for key in ("quality_score", "confidence"):
        try:
            v = float(out.get(key) or 0.5)
            out[key] = max(0.0, min(1.0, v))
        except (TypeError, ValueError):
            out[key] = 0.5

    if media.is_blurry:
        out["quality_score"] = min(float(out["quality_score"]), 0.4)
        tags = out["suggested_tags"]
        if "blurry" not in tags:
            tags.append("blurry")

    # Enrich tags with scene
    tags = out["suggested_tags"]
    if scene and scene not in tags and scene != "other":
        tags.insert(0, scene)
    out["suggested_tags"] = tags[:15]

    cap = str(out.get("caption_short") or "").strip()
    if not cap:
        cap = f"{scene.replace('_', ' ').title()} photo"
    out["caption_short"] = cap[:160]
    out["description"] = str(out.get("description") or cap)[:800]
    out["people_desc"] = str(out.get("people_desc") or "")[:400]

    return out


def vlm_status(settings: Settings) -> dict[str, Any]:
    """Report whether VLM can run and current Metal memory use."""
    try:
        import mlx  # noqa: F401
        import mlx_vlm  # noqa: F401

        mlx_ok = True
    except ImportError as exc:
        return {"available": False, "error": f"import failed: {exc}", "enabled": settings.vlm_enabled}

    metal: dict[str, Any] = {}
    try:
        import mlx.core as mx

        if mx.metal.is_available():
            metal = {
                "available": True,
                "active_bytes": mx.metal.get_active_memory(),
                "cache_bytes": mx.metal.get_cache_memory(),
                "peak_bytes": mx.metal.get_peak_memory(),
            }
        else:
            metal = {"available": False}
    except Exception as exc:  # noqa: BLE001
        metal = {"available": False, "error": str(exc)}

    from neuraldisc.mlx_plane_lease import lease_status

    return {
        "available": True,
        "enabled": settings.vlm_enabled,
        "model": settings.vlm_model,
        "loaded": settings.vlm_model in _model_cache,
        "loaded_models": list(_model_cache.keys()),
        "refcount": _load_refcount,
        "mlx_ok": mlx_ok,
        "metal": metal,
        "plane_lease": lease_status(vlm_enabled=settings.vlm_enabled),
    }
