"""macOS volume / optical media detector."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from neuraldisc.config import MEDIA_EXTENSIONS, Settings, get_settings
from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)

# LaunchAgents often omit /usr/sbin — always prefer absolute path
_DISKUTIL = next(
    (p for p in ("/usr/sbin/diskutil", "/sbin/diskutil") if Path(p).is_file()),
    "diskutil",
)


def _diskutil_cmd(*args: str) -> list[str]:
    return [_DISKUTIL, *args]

# Volumes that are never import sources
_SKIP_VOLUME_NAMES = frozenset(
    {
        "macintosh hd",
        "macintosh hd - data",
        "com.apple.timemachine.localsnapshots",
        "recoveryp",
    }
)


@dataclass
class VolumeInfo:
    path: Path
    name: str
    volume_uuid: str | None = None
    filesystem: str | None = None
    is_optical: bool = False
    is_ejectable: bool = False
    is_internal: bool = False
    is_removable: bool = False
    total_bytes: int | None = None
    free_bytes: int | None = None
    protocol: str | None = None
    media_type: str | None = None  # DVD-R, CD-ROM, …
    has_video_ts: bool = False
    media_file_count: int | None = None  # filled optionally
    media_count_capped: bool = False
    kind: str = "volume"  # optical | removable | external | volume


def list_mounted_volumes(
    volumes_path: Path | None = None,
    *,
    count_media: bool = False,
    media_count_limit: int = 5000,
) -> list[VolumeInfo]:
    root = volumes_path or Path("/Volumes")
    if not root.exists():
        return []
    results: list[VolumeInfo] = []
    try:
        entries = sorted(root.iterdir(), key=lambda p: p.name.lower())
    except OSError as exc:
        log.warning("volumes_list_failed", error=str(exc))
        return []

    for entry in entries:
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if entry.name.lower() in _SKIP_VOLUME_NAMES:
            continue
        # Skip Time Machine local snapshots
        if "timemachine" in entry.name.lower() or entry.name.startswith("com.apple."):
            continue
        try:
            info = probe_volume(entry)
        except Exception as exc:  # noqa: BLE001
            log.debug("probe_failed", path=str(entry), error=str(exc))
            info = VolumeInfo(path=entry, name=entry.name)
        if count_media:
            n, capped = count_media_files(entry, limit=media_count_limit)
            info.media_file_count = n
            info.media_count_capped = capped
        results.append(info)

    # Optical / ejectable first, then by name
    results.sort(
        key=lambda v: (
            0 if v.is_optical else 1 if (v.is_ejectable or v.is_removable) else 2,
            v.name.lower(),
        )
    )
    return results


def probe_volume(path: Path) -> VolumeInfo:
    """Probe volume metadata via diskutil when available."""
    info = VolumeInfo(path=path, name=path.name)
    try:
        if (path / "VIDEO_TS").is_dir() or (path / "AUDIO_TS").is_dir():
            info.has_video_ts = True
            info.is_optical = True
            info.kind = "optical"
    except OSError:
        pass

    try:
        proc = subprocess.run(
            _diskutil_cmd("info", str(path)),
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
        if proc.returncode != 0:
            _classify_kind(info)
            return info
        for raw in proc.stdout.splitlines():
            line = raw.strip()
            if line.startswith("Volume Name:"):
                val = line.split(":", 1)[1].strip()
                if val and val != "Not applicable":
                    info.name = val
            elif line.startswith("Volume UUID:"):
                val = line.split(":", 1)[1].strip()
                info.volume_uuid = None if val == "Not applicable" else val
            elif line.startswith("Type (Bundle):") or line.startswith(
                "File System Personality:"
            ):
                info.filesystem = line.split(":", 1)[1].strip()
            elif line.startswith("Protocol:"):
                info.protocol = line.split(":", 1)[1].strip()
                proto = (info.protocol or "").lower()
                if any(x in proto for x in ("disc", "dvd", "cd", "optical", "atapi")):
                    info.is_optical = True
            elif line.startswith("Optical Media Type:") or line.startswith("Media Type:"):
                info.media_type = line.split(":", 1)[1].strip()
                if info.media_type and info.media_type.lower() not in (
                    "generic",
                    "not applicable",
                    "",
                ):
                    mt = info.media_type.upper()
                    if any(x in mt for x in ("DVD", "CD", "BD", "BLU")):
                        info.is_optical = True
            elif line.startswith("Ejectable:"):
                info.is_ejectable = "Yes" in line
            elif line.startswith("Removable Media:"):
                info.is_removable = "Removable" in line or "Yes" in line
                if "Removable" in line:
                    info.is_ejectable = True
            elif line.startswith("Device Location:"):
                loc = line.split(":", 1)[1].strip().lower()
                info.is_internal = "internal" in loc
            elif line.startswith("Disk Size:") or line.startswith("Volume Total Space:"):
                info.total_bytes = _parse_diskutil_size(line)
            elif line.startswith("Volume Free Space:") or line.startswith("Container Free Space:"):
                info.free_bytes = _parse_diskutil_size(line)
            elif "Optical Disc" in line or "Optical Media" in line:
                info.is_optical = True
            elif "DVD" in line or "CD-ROM" in line:
                if any(k in line for k in ("Media Type", "Optical", "Disc Burning")):
                    info.is_optical = True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        log.debug("diskutil_unavailable", error=str(exc))

    _classify_kind(info)
    return info


def _classify_kind(info: VolumeInfo) -> None:
    if info.is_optical or info.has_video_ts:
        info.kind = "optical"
    elif info.is_removable or info.is_ejectable:
        info.kind = "removable"
    elif not info.is_internal:
        info.kind = "external"
    else:
        info.kind = "volume"


def _parse_diskutil_size(line: str) -> int | None:
    """Parse 'Disk Size: 4.7 GB (4700000000 Bytes) (exactly 0 bytes)' style lines."""
    try:
        if "(" in line and "Bytes" in line:
            inner = line.split("(", 1)[1]
            num = inner.split("Bytes", 1)[0].strip().replace(",", "")
            return int(num)
    except (ValueError, IndexError):
        pass
    return None


def count_media_files(path: Path, limit: int = 5000) -> tuple[int, bool]:
    """Count media files under path (capped for responsiveness)."""
    n = 0
    try:
        for p in path.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() in MEDIA_EXTENSIONS:
                n += 1
                if n >= limit:
                    return n, True
    except OSError as exc:
        log.debug("media_count_failed", path=str(path), error=str(exc))
    return n, False


def volume_to_dict(v: VolumeInfo) -> dict:
    return {
        "path": str(v.path),
        "name": v.name,
        "volume_uuid": v.volume_uuid,
        "filesystem": v.filesystem,
        "is_optical": v.is_optical,
        "is_ejectable": v.is_ejectable,
        "is_internal": v.is_internal,
        "is_removable": v.is_removable,
        "total_bytes": v.total_bytes,
        "free_bytes": v.free_bytes,
        "protocol": v.protocol,
        "media_type": v.media_type,
        "has_video_ts": v.has_video_ts,
        "media_file_count": v.media_file_count,
        "media_count_capped": v.media_count_capped,
        "kind": v.kind,
        "mode": "disc" if v.kind in ("optical", "removable") else "folder",
        "importable": True,
    }


def eject_volume(path: Path | str, *, force: bool = False) -> dict[str, Any]:
    """Eject / unmount a volume so the optical drive (player) is free.

    Prefer ``diskutil eject``; fall back to ``unmountDisk``. Never touches
    internal system volumes. Safe to call after copy-only import — files
    already live on the library SSD.
    """
    p = Path(path).expanduser()
    # Check the mount name before resolve — "Macintosh HD" often resolves to /
    mount_name = p.name.lower()
    if mount_name in _SKIP_VOLUME_NAMES or mount_name == "macintosh hd":
        return {"ok": False, "path": str(p), "error": "refusing to eject system volume"}
    if not str(p).startswith("/Volumes/") and not str(p).startswith("/Volumes"):
        return {
            "ok": False,
            "path": str(p),
            "error": "refusing to eject non-/Volumes path",
        }
    try:
        p = p.resolve()
    except OSError:
        pass
    # After resolve, still must be under /Volumes (never /)
    if not str(p).startswith("/Volumes/"):
        return {
            "ok": False,
            "path": str(p),
            "error": "refusing to eject non-/Volumes path",
        }
    if p.name.lower() in _SKIP_VOLUME_NAMES or p.name.lower() == "macintosh hd":
        return {"ok": False, "path": str(p), "error": "refusing to eject system volume"}

    # Prefer eject while still mounted; if already gone, treat as success
    if not p.exists():
        return {"ok": True, "path": str(p), "already_unmounted": True}

    cmds: list[list[str]] = [
        _diskutil_cmd("eject", str(p)),
        _diskutil_cmd("unmountDisk", str(p)),
    ]
    if force:
        cmds.insert(1, _diskutil_cmd("unmountDisk", "force", str(p)))

    if not Path(_DISKUTIL).is_file() and _DISKUTIL == "diskutil":
        return {
            "ok": False,
            "path": str(p),
            "error": "diskutil not found (expected /usr/sbin/diskutil)",
        }

    last_err = ""
    for cmd in cmds:
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except FileNotFoundError:
            return {
                "ok": False,
                "path": str(p),
                "error": f"diskutil not found at {_DISKUTIL}",
            }
        except (OSError, subprocess.TimeoutExpired) as exc:
            last_err = str(exc)
            continue
        if proc.returncode == 0:
            log.info("volume_ejected", path=str(p), cmd=cmd)
            return {
                "ok": True,
                "path": str(p),
                "cmd": " ".join(cmd),
                "stdout": (proc.stdout or "").strip()[:400],
            }
        last_err = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
        # If already unmounted, diskutil may error — check
        if not p.exists():
            return {"ok": True, "path": str(p), "already_unmounted": True}

    log.warning("volume_eject_failed", path=str(p), error=last_err[:300])
    return {"ok": False, "path": str(p), "error": last_err[:400]}


class VolumeWatcher:
    """Poll /Volumes for new optical / ejectable volumes."""

    def __init__(
        self,
        settings: Settings | None = None,
        on_volume: Callable[[VolumeInfo], None] | None = None,
        poll_interval: float = 3.0,
        optical_only: bool = False,
    ) -> None:
        self.settings = settings or get_settings()
        self.on_volume = on_volume
        self.poll_interval = poll_interval
        self.optical_only = optical_only
        self._seen: set[str] = set()
        self._running = False

    def snapshot(self) -> None:
        for v in list_mounted_volumes(self.settings.volumes_path):
            self._seen.add(str(v.path))

    def poll_once(self) -> list[VolumeInfo]:
        current = list_mounted_volumes(self.settings.volumes_path)
        found: list[VolumeInfo] = []
        current_paths = {str(v.path) for v in current}
        for v in current:
            key = str(v.path)
            if key in self._seen:
                continue
            self._seen.add(key)
            if self.optical_only and not (v.is_optical or v.is_ejectable):
                continue
            found.append(v)
            log.info("volume_detected", path=str(v.path), name=v.name, optical=v.is_optical)
            if self.on_volume:
                self.on_volume(v)
        for path in list(self._seen):
            if path not in current_paths:
                self._seen.discard(path)
        return found

    def run(self, stop_after: float | None = None) -> None:
        self._running = True
        self.snapshot()
        log.info("volume_watcher_start", path=str(self.settings.volumes_path))
        start = time.time()
        while self._running:
            self.poll_once()
            if stop_after is not None and (time.time() - start) >= stop_after:
                break
            time.sleep(self.poll_interval)

    def stop(self) -> None:
        self._running = False
