"""Secure local secret store for API tokens.

Security model:
  - Secrets live ONLY under ~/.neuraldisc/ (never in the library tree or git)
  - File modes 0600 (owner read/write only)
  - Values encrypted at rest with Fernet; key in master.key (0600)
  - API never returns raw secrets — only masked previews + configured flags
  - Loaded into process env (HF_TOKEN, etc.) for model downloads

Do not log secret values.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)

APP_DIR = Path.home() / ".neuraldisc"
SECRETS_FILE = APP_DIR / "secrets.enc"
MASTER_KEY_FILE = APP_DIR / ".master.key"

# Known secret slots
SECRET_KEYS = frozenset(
    {
        "huggingface_token",
        "openai_api_key",  # reserved for future
        "generic_api_key",
    }
)

# Env vars set when secrets load
ENV_MAP = {
    "huggingface_token": ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"),
}


def _ensure_secure_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(APP_DIR, stat.S_IRWXU)  # 0700
    except OSError:
        pass


def _chmod_private(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        pass


def _get_or_create_fernet():
    """Return Fernet instance; create master key if missing."""
    from cryptography.fernet import Fernet

    _ensure_secure_dir()
    if MASTER_KEY_FILE.exists():
        key = MASTER_KEY_FILE.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        MASTER_KEY_FILE.write_bytes(key + b"\n")
        _chmod_private(MASTER_KEY_FILE)
        log.info("secrets_master_key_created", path=str(MASTER_KEY_FILE))
    _chmod_private(MASTER_KEY_FILE)
    return Fernet(key)


def _load_raw() -> dict[str, str]:
    if not SECRETS_FILE.exists():
        return {}
    try:
        f = _get_or_create_fernet()
        data = f.decrypt(SECRETS_FILE.read_bytes())
        obj = json.loads(data.decode("utf-8"))
        if not isinstance(obj, dict):
            return {}
        return {str(k): str(v) for k, v in obj.items() if k in SECRET_KEYS and v}
    except Exception as exc:  # noqa: BLE001
        log.warning("secrets_load_failed", error=type(exc).__name__)
        return {}


def _save_raw(data: dict[str, str]) -> None:
    _ensure_secure_dir()
    f = _get_or_create_fernet()
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    SECRETS_FILE.write_bytes(f.encrypt(payload))
    _chmod_private(SECRETS_FILE)
    log.info("secrets_saved", keys=list(data.keys()))


def mask_secret(value: str | None) -> str | None:
    """Return a safe preview: prefix…last4."""
    if not value:
        return None
    v = value.strip()
    if len(v) <= 8:
        return "••••••••"
    # HF tokens look like hf_xxx — keep prefix hint
    if v.startswith("hf_"):
        return f"hf_…{v[-4:]}"
    return f"{v[:3]}…{v[-4:]}"


def get_secret(key: str) -> str | None:
    if key not in SECRET_KEYS:
        return None
    # Env override (highest priority for ops)
    env_keys = ENV_MAP.get(key, ())
    for ek in env_keys:
        if os.environ.get(ek):
            return os.environ[ek]
    if key == "huggingface_token" and os.environ.get("NEURALDISC_HUGGINGFACE_TOKEN"):
        return os.environ["NEURALDISC_HUGGINGFACE_TOKEN"]
    return _load_raw().get(key)


def set_secret(key: str, value: str | None) -> None:
    """Set or clear a secret. Empty / None deletes it."""
    if key not in SECRET_KEYS:
        raise ValueError(f"Unknown secret key: {key}")
    data = _load_raw()
    if value is None or not str(value).strip():
        data.pop(key, None)
    else:
        data[key] = str(value).strip()
    _save_raw(data)
    apply_secrets_to_environ()


def list_secret_status() -> dict[str, dict[str, Any]]:
    """Public status only — never raw values."""
    data = _load_raw()
    out: dict[str, dict[str, Any]] = {}
    for key in sorted(SECRET_KEYS):
        # Prefer live env for mask if present
        val = get_secret(key)
        out[key] = {
            "configured": bool(val),
            "masked": mask_secret(val) if val else None,
        }
    return out


def apply_secrets_to_environ() -> None:
    """Export secrets into process env for huggingface_hub / mlx downloads."""
    data = _load_raw()
    for key, env_names in ENV_MAP.items():
        val = data.get(key) or get_secret(key)
        if not val:
            continue
        for ek in env_names:
            os.environ[ek] = val
    # Also support direct env already set — leave as-is
    hf = get_secret("huggingface_token")
    if hf:
        os.environ.setdefault("HF_TOKEN", hf)
        os.environ.setdefault("HUGGING_FACE_HUB_TOKEN", hf)


def secrets_file_secure() -> bool:
    """True if secrets + key files exist with owner-only permissions."""
    for p in (SECRETS_FILE, MASTER_KEY_FILE):
        if not p.exists():
            continue
        mode = p.stat().st_mode & 0o777
        if mode & 0o077:  # group/other bits set
            return False
    return True
