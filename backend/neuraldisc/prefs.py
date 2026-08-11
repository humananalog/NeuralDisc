"""Persistent app preferences (outside the library tree).

Library root must live here so the user can switch targets without a
chicken-and-egg problem (config inside the library cannot point at itself).

Default file: ~/.neuraldisc/settings.toml
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)

APP_DIR = Path.home() / ".neuraldisc"
SETTINGS_FILE = APP_DIR / "settings.toml"

# Keys we persist (subset of Settings fields)
PERSISTABLE = frozenset(
    {
        "library_root",
        "quality_enabled",
        "quality_min_short_edge",
        "quality_min_long_edge",
        "quality_min_megapixels",
        "quality_min_image_bytes",
        "quality_min_web_format_bytes",
        "quality_min_video_bytes",
        "quality_min_video_short_edge",
        "quality_max_aspect_ratio",
        "quality_reject_animated_gif",
        "quality_reject_junk_paths",
        "quality_quarantine_rejects",
        "blur_enabled",
        "blur_threshold",
        "blur_auto_flag",
        "blur_hitl_priority",
        "vlm_enabled",
        "vlm_model",
        "embeddings_enabled",
        "thumb_size",
        "preview_size",
    }
)


def prefs_path() -> Path:
    return SETTINGS_FILE


def load_prefs() -> dict[str, Any]:
    path = SETTINGS_FILE
    if not path.exists():
        return {}
    try:
        if sys.version_info >= (3, 11):
            import tomllib

            with path.open("rb") as f:
                data = tomllib.load(f)
        else:
            import tomli

            with path.open("rb") as f:
                data = tomli.load(f)
        if not isinstance(data, dict):
            return {}
        return {k: v for k, v in data.items() if k in PERSISTABLE}
    except Exception as exc:  # noqa: BLE001
        log.warning("prefs_load_failed", path=str(path), error=str(exc))
        return {}


def save_prefs(updates: dict[str, Any]) -> dict[str, Any]:
    """Merge updates into prefs file and return full prefs."""
    current = load_prefs()
    for key, value in updates.items():
        if key not in PERSISTABLE:
            continue
        if isinstance(value, Path):
            value = str(value)
        current[key] = value
    APP_DIR.mkdir(parents=True, exist_ok=True)
    body = _to_toml(current)
    SETTINGS_FILE.write_text(body, encoding="utf-8")
    log.info("prefs_saved", path=str(SETTINGS_FILE), keys=list(updates.keys()))
    return current


def apply_prefs_to_environ(prefs: dict[str, Any] | None = None) -> None:
    """Inject prefs into env so pydantic Settings picks them up.

    Priority: process env (tests / explicit export) > ~/.neuraldisc/settings.toml
    > defaults. Settings UI and CLI call ``force_environ`` + ``save_prefs`` so the
    chosen library target (and its staging/temp) sticks across restarts when env
    is unset. Do **not** export NEURALDISC_LIBRARY_ROOT in launch scripts unless
    you intend to override Settings.
    """
    prefs = prefs if prefs is not None else load_prefs()
    for key, value in prefs.items():
        env_key = f"NEURALDISC_{key.upper()}"
        if env_key in os.environ:
            continue
        if isinstance(value, Path):
            value = str(value)
        if isinstance(value, bool):
            os.environ[env_key] = "true" if value else "false"
        else:
            os.environ[env_key] = str(value)


def force_environ(updates: dict[str, Any]) -> None:
    """Force-set env vars (used after Settings UI save)."""
    for key, value in updates.items():
        if key not in PERSISTABLE:
            continue
        env_key = f"NEURALDISC_{key.upper()}"
        if isinstance(value, Path):
            value = str(value)
        if isinstance(value, bool):
            os.environ[env_key] = "true" if value else "false"
        else:
            os.environ[env_key] = str(value)


def _to_toml(data: dict[str, Any]) -> str:
    lines = [
        "# NeuralDisc application preferences",
        "# Edited via the Settings UI or manually.",
        "",
    ]
    for key in sorted(data.keys()):
        val = data[key]
        if isinstance(val, bool):
            lines.append(f"{key} = {'true' if val else 'false'}")
        elif isinstance(val, int):
            lines.append(f"{key} = {val}")
        elif isinstance(val, float):
            lines.append(f"{key} = {val}")
        else:
            s = str(val).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key} = "{s}"')
    lines.append("")
    return "\n".join(lines)
