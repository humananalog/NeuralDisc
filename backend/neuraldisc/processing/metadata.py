"""EXIF / media metadata extraction via **exiftool only**.

NeuralDisc requires Phil Harvey's ExifTool for all still-image and container
metadata. Pillow is not used for EXIF. Install:

    brew install exiftool
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)


class ExifToolNotFoundError(RuntimeError):
    """Raised when the exiftool binary is missing from PATH."""


class ExifToolError(RuntimeError):
    """Raised when exiftool fails on a file."""


@dataclass
class MediaMetadata:
    width: int | None = None
    height: int | None = None
    mime_type: str | None = None
    taken_at: datetime | None = None
    taken_at_source: str | None = None  # exif|path|mtime|birthtime
    camera_make: str | None = None
    camera_model: str | None = None
    gps_lat: float | None = None
    gps_lon: float | None = None
    orientation: int | None = None
    duration_ms: int | None = None
    lens: str | None = None
    iso: int | None = None
    focal_length: str | None = None
    exposure_time: str | None = None
    f_number: str | None = None
    software: str | None = None
    raw: dict[str, Any] | None = None
    source: str = "exiftool"


# Capture / digitization times — NEVER FileModifyDate / ModifyDate (often copy time)
_CAPTURE_DATE_KEYS = (
    "DateTimeOriginal",
    "SubSecDateTimeOriginal",
    "DateTimeDigitized",
    "CreateDate",
    "DateCreated",
    "MediaCreateDate",
    "TrackCreateDate",
    "DateTimeCreated",
    "GPSDateTime",
    "ContentCreateDate",
    "DateTime",
)

# DD-MM-YYYY, YYYY-MM-DD, YYYYMMDD in folder/file names (e.g. "Gleniff … 28-02-2005")
_PATH_DATE_RES = (
    re.compile(
        r"(?<!\d)(?P<d>\d{1,2})[-_./ ](?P<m>\d{1,2})[-_./ ](?P<y>19\d{2}|20\d{2})(?!\d)"
    ),
    re.compile(
        r"(?<!\d)(?P<y>19\d{2}|20\d{2})[-_./](?P<m>\d{1,2})[-_./](?P<d>\d{1,2})(?!\d)"
    ),
    re.compile(r"(?<!\d)(?P<y>19\d{2}|20\d{2})(?P<m>\d{2})(?P<d>\d{2})(?!\d)"),
)


@lru_cache(maxsize=1)
def find_exiftool() -> str:
    """Resolve absolute path to exiftool, or raise ExifToolNotFoundError."""
    path = shutil.which("exiftool")
    if not path:
        # Common Homebrew locations on Apple Silicon / Intel
        for candidate in (
            "/opt/homebrew/bin/exiftool",
            "/usr/local/bin/exiftool",
        ):
            if Path(candidate).is_file():
                path = candidate
                break
    if not path:
        raise ExifToolNotFoundError(
            "exiftool is required but was not found on PATH. "
            "Install with: brew install exiftool"
        )
    return path


def exiftool_available() -> bool:
    try:
        find_exiftool()
        return True
    except ExifToolNotFoundError:
        return False


def exiftool_version() -> str | None:
    try:
        binary = find_exiftool()
        proc = subprocess.run(
            [binary, "-ver"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip() or None
    except (ExifToolNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def require_exiftool() -> str:
    """Hard requirement check (import / API startup)."""
    binary = find_exiftool()
    ver = exiftool_version()
    log.info("exiftool_ready", path=binary, version=ver)
    return binary


def extract_metadata(
    path: Path,
    media_type: str,
    *,
    original_relpath: str | None = None,
) -> MediaMetadata:
    """Extract metadata using exiftool for images and videos.

    ``original_relpath`` (disc-relative path) is used to recover dates from
    folder names when EXIF has no capture time (common on burned discs).
    """
    del media_type  # both handled by exiftool
    return _exiftool_extract(path, original_relpath=original_relpath)


def extract_metadata_batch(
    paths: list[Path],
    *,
    original_relpaths: dict[str, str] | None = None,
) -> dict[str, MediaMetadata]:
    """Batch exiftool call for higher throughput during import."""
    if not paths:
        return {}
    binary = find_exiftool()
    args = [
        binary,
        "-json",
        "-n",
        "-G1",  # group names help disambiguate
        "-a",  # allow duplicate tags
        "--",
        *[str(p) for p in paths],
    ]
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=max(60, 5 * len(paths)),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExifToolError(f"exiftool timed out on batch of {len(paths)}") from exc

    if proc.returncode not in (0, 1) or not proc.stdout.strip():
        # returncode 1 can mean warnings; still parse if JSON present
        if not proc.stdout.strip():
            raise ExifToolError(
                f"exiftool batch failed (code {proc.returncode}): "
                f"{(proc.stderr or '')[:400]}"
            )

    try:
        rows = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ExifToolError("exiftool returned invalid JSON") from exc

    orig_map = original_relpaths or {}
    out: dict[str, MediaMetadata] = {}
    for row in rows:
        src = row.get("SourceFile") or row.get("File:FileName")
        if not src:
            continue
        # SourceFile may be relative; resolve against each path
        key = str(Path(src).resolve()) if Path(src).exists() else src
        rel = orig_map.get(key) or orig_map.get(str(src)) or orig_map.get(Path(src).name)
        out[key] = _parse_exiftool_row(row, path=Path(src), original_relpath=rel)
        # also index by basename match
        out[Path(src).name] = out[key]
    return out


def _exiftool_extract(
    path: Path, *, original_relpath: str | None = None
) -> MediaMetadata:
    binary = find_exiftool()
    path = path.resolve()
    try:
        proc = subprocess.run(
            [
                binary,
                "-json",
                "-n",  # numeric GPS / orientation
                "-G1",
                "-a",
                "--",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExifToolError(f"exiftool timed out: {path.name}") from exc
    except FileNotFoundError as exc:
        find_exiftool.cache_clear()
        raise ExifToolNotFoundError(
            "exiftool is required but was not found. Install: brew install exiftool"
        ) from exc

    # 0 = ok, 1 = minor warnings (still usable)
    if proc.returncode not in (0, 1):
        raise ExifToolError(
            f"exiftool failed on {path.name} (code {proc.returncode}): "
            f"{(proc.stderr or proc.stdout or '')[:300]}"
        )
    if not proc.stdout.strip():
        raise ExifToolError(f"exiftool returned empty output for {path.name}")

    try:
        data = json.loads(proc.stdout)[0]
    except (json.JSONDecodeError, IndexError, TypeError) as exc:
        raise ExifToolError(f"exiftool JSON parse error for {path.name}") from exc

    return _parse_exiftool_row(data, path=path, original_relpath=original_relpath)


def _parse_exiftool_row(
    data: dict[str, Any],
    *,
    path: Path | None = None,
    original_relpath: str | None = None,
) -> MediaMetadata:
    """Map exiftool -json (-G1 -n) keys into MediaMetadata."""
    # Flatten Group:Tag → prefer EXIF/Composite/File
    flat = _flatten_exiftool(data)

    meta = MediaMetadata(raw=data, source="exiftool")
    meta.width = _as_int(
        flat.get("ImageWidth")
        or flat.get("ExifImageWidth")
        or flat.get("SourceImageWidth")
    )
    meta.height = _as_int(
        flat.get("ImageHeight")
        or flat.get("ExifImageHeight")
        or flat.get("SourceImageHeight")
    )
    meta.camera_make = _as_str(flat.get("Make"))
    meta.camera_model = _as_str(flat.get("Model"))
    meta.orientation = _as_int(flat.get("Orientation"))
    meta.mime_type = _as_str(flat.get("MIMEType"))
    meta.lens = _as_str(flat.get("LensModel") or flat.get("LensID") or flat.get("Lens"))
    meta.iso = _as_int(flat.get("ISO") or flat.get("ISOSpeedRatings"))
    meta.focal_length = _as_str(flat.get("FocalLength"))
    meta.exposure_time = _as_str(flat.get("ExposureTime") or flat.get("ShutterSpeed"))
    meta.f_number = _as_str(flat.get("FNumber") or flat.get("Aperture"))
    meta.software = _as_str(flat.get("Software"))

    taken, src = _resolve_taken_at(
        flat, path=path, original_relpath=original_relpath
    )
    meta.taken_at = taken
    meta.taken_at_source = src

    lat = flat.get("GPSLatitude")
    lon = flat.get("GPSLongitude")
    if lat is not None and lon is not None:
        try:
            meta.gps_lat = float(lat)
            meta.gps_lon = float(lon)
            # -n should already be signed; still honour ref if present
            lat_ref = flat.get("GPSLatitudeRef")
            lon_ref = flat.get("GPSLongitudeRef")
            if lat_ref == "S":
                meta.gps_lat = -abs(meta.gps_lat)
            if lon_ref == "W":
                meta.gps_lon = -abs(meta.gps_lon)
        except (TypeError, ValueError):
            pass

    if "Duration" in flat and flat["Duration"] is not None:
        try:
            d = float(flat["Duration"])
            # exiftool -n Duration is seconds
            meta.duration_ms = int(d * 1000) if d < 1e6 else int(d)
        except (TypeError, ValueError):
            pass

    return meta


def _resolve_taken_at(
    flat: dict[str, Any],
    *,
    path: Path | None = None,
    original_relpath: str | None = None,
) -> tuple[datetime | None, str | None]:
    """Pick capture time: EXIF capture tags → path date → filesystem times.

    Deliberately ignores FileModifyDate / ModifyDate — those become the import
    clock after a naive copy and produced thousands of wrong \"today\" dates.
    """
    for key in _CAPTURE_DATE_KEYS:
        if key in flat and flat[key] is not None:
            dt = _parse_exif_dt(str(flat[key]))
            if dt and _plausible_capture_date(dt):
                return dt, f"exif:{key}"

    path_hint = original_relpath or (str(path) if path else None)
    if path_hint:
        dt = parse_date_from_path(path_hint)
        if dt and _plausible_capture_date(dt):
            return dt, "path"

    if path is not None:
        try:
            st = path.stat()
        except OSError:
            return None, None
        # Prefer birthtime (macOS) when it looks historical
        birth = getattr(st, "st_birthtime", None)
        if birth:
            dt = datetime.fromtimestamp(birth, tz=timezone.utc)
            if _plausible_capture_date(dt) and not _looks_like_import_clock(dt):
                return dt, "birthtime"
        dt = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
        if _plausible_capture_date(dt) and not _looks_like_import_clock(dt):
            return dt, "mtime"

    return None, None


def parse_date_from_path(text: str) -> datetime | None:
    """Extract a calendar date from folder/file path segments."""
    # Prefer directory parts over filename (folder often holds the shoot date)
    parts = list(Path(text.replace("\\", "/")).parts)
    # Search from deepest parent to root, then filename
    ordered = list(reversed(parts[:-1])) + ([parts[-1]] if parts else [])
    for part in ordered:
        for rx in _PATH_DATE_RES:
            m = rx.search(part)
            if not m:
                continue
            try:
                y = int(m.group("y"))
                mo = int(m.group("m"))
                d = int(m.group("d"))
                dt = datetime(y, mo, d, tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
            if _plausible_capture_date(dt):
                return dt
    return None


def _plausible_capture_date(dt: datetime) -> bool:
    year = dt.year
    return 1970 <= year <= datetime.now(timezone.utc).year + 1


def _looks_like_import_clock(dt: datetime) -> bool:
    """True when timestamp is within ~2 days of now (likely copy/import time)."""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return abs((now - dt).total_seconds()) < 2 * 86400


def _flatten_exiftool(data: dict[str, Any]) -> dict[str, Any]:
    """Turn {'EXIF:Make': 'Canon', 'Make': 'Canon'} into simple keys."""
    flat: dict[str, Any] = {}
    for k, v in data.items():
        if k in ("SourceFile", "ExifToolVersion"):
            continue
        if ":" in k:
            _group, tag = k.split(":", 1)
            # Prefer first non-empty; Composite often best for GPS
            if tag not in flat or flat[tag] in (None, ""):
                flat[tag] = v
            # Prefer EXIF/Composite over File for dates
            if tag in flat and _group in ("Composite", "EXIF", "QuickTime", "XMP"):
                flat[tag] = v
        else:
            if k not in flat or flat[k] in (None, ""):
                flat[k] = v
    return flat


def _parse_exif_dt(value: str) -> datetime | None:
    value = value.strip()
    # Strip trailing timezone like +08:00 or Z after space-separated date
    for fmt in (
        "%Y:%m:%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y:%m:%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y:%m:%d %H:%M:%S.%f",
    ):
        try:
            cleaned = value
            if cleaned.endswith("Z") and "%z" not in fmt and "Z" not in fmt:
                cleaned = cleaned[:-1]
            # ExifTool may use +08:00 — fromisoformat handles some; strptime needs +0800
            if len(cleaned) > 19 and cleaned[-3] == ":":
                # 2007:07:15 13:42:05+08:00
                maybe = cleaned[:-3] + cleaned[-2:]
                try:
                    dt = datetime.strptime(maybe.replace("+00:00", "+0000"), fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt
                except ValueError:
                    pass
            dt = datetime.strptime(cleaned.replace("+00:00", "+0000"), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return _parse_isoish(value)


def _parse_isoish(value: str) -> datetime | None:
    value = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(value.replace(":", "-", 2) if value[4:5] == ":" else value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        m = re.match(r"(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})", value)
        if m:
            y, mo, d, h, mi, s = map(int, m.groups())
            return datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)
    return None


def _as_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _as_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None
