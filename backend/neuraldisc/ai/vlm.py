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
- Prefer specific tags (e.g. "ferry", "harbour") over generic ones.
- If the image is blurry or low quality, lower quality_score and still describe content.
"""

_model_lock = threading.Lock()
_model_cache: dict[str, Any] = {}


def analyse_media(session: Session, media: MediaItem, settings: Settings) -> MediaAnalysis | None:
    if media.analysis:
        return media.analysis

    result: dict[str, Any] | None = None
    model_name = "heuristic-fallback"
    model_version = "0.1.0"

    if settings.vlm_enabled:
        image_path = Path(media.library_path)
        # Prefer preview derivative for speed if available
        preview = settings.previews_dir / f"{media.id}.jpg"
        if preview.exists():
            image_path = preview
        result = _run_mlx_vlm(image_path, settings)
        if result:
            model_name = settings.vlm_model
            model_version = "mlx-vlm"

    if result is None:
        if settings.vlm_enabled:
            log.warning("vlm_fallback_heuristic", media_id=media.id)
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
    if media.analysis:
        session.delete(media.analysis)
        session.flush()
        media.analysis = None
    return analyse_media(session, media, settings)


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
    """Load and cache model/processor/config once per process."""
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
        log.info("vlm_loaded", model=key)
        return model, processor, config


def _run_mlx_vlm(path: Path, settings: Settings) -> dict[str, Any] | None:
    try:
        from mlx_vlm import generate  # type: ignore
        from mlx_vlm.prompt_utils import apply_chat_template  # type: ignore

        model, processor, config = _get_model(settings)
        formatted = apply_chat_template(
            processor, config, VLM_PROMPT, num_images=1
        )
        with _model_lock:
            out = generate(
                model,
                processor,
                formatted,
                [str(path)],
                verbose=False,
                max_tokens=640,
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
            log.warning("vlm_json_parse_failed", sample=text[:200])
        return parsed
    except Exception as exc:  # noqa: BLE001
        log.warning("mlx_vlm_failed", error=str(exc), path=str(path))
        return None


def _parse_json_blob(text: str) -> dict[str, Any] | None:
    text = text.strip()
    # Strip markdown fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0:
        return None
    blob = text[start : end + 1]
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        # Try fixing trailing commas
        fixed = re.sub(r",\s*}", "}", blob)
        fixed = re.sub(r",\s*]", "]", fixed)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            return None


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
    """Report whether VLM can run."""
    try:
        import mlx  # noqa: F401
        import mlx_vlm  # noqa: F401

        mlx_ok = True
    except ImportError as exc:
        return {"available": False, "error": f"import failed: {exc}", "enabled": settings.vlm_enabled}

    return {
        "available": True,
        "enabled": settings.vlm_enabled,
        "model": settings.vlm_model,
        "loaded": settings.vlm_model in _model_cache,
        "mlx_ok": mlx_ok,
    }
