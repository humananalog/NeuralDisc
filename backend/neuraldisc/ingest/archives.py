"""Expand archives that contain photos/videos during import.

On disc media it is common to find ``.zip`` / ``.tar.gz`` / etc. full of
camera JPEGs. When such an archive is found we extract **only media members**
onto the library staging volume (never unpack onto the optical disc), then
feed those files into the normal copy/process pipeline.

Supported (stdlib, always available):
  - ZIP family: ``.zip``, ``.zipx``, ``.cbz``
  - TAR family: ``.tar``, ``.tar.gz``, ``.tgz``, ``.tar.bz2``, ``.tbz2``,
    ``.tar.xz``, ``.txz``

Best-effort (optional tools):
  - ``.rar`` / ``.7z`` via ``7z`` or ``unar`` on PATH if installed
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from neuraldisc.config import MEDIA_EXTENSIONS, Settings
from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)

# Compound suffixes checked first (longest match)
_COMPOUND_ARCHIVE_SUFFIXES = (
    ".tar.gz",
    ".tar.bz2",
    ".tar.xz",
    ".tgz",
    ".tbz2",
    ".txz",
)

_SIMPLE_ARCHIVE_SUFFIXES = frozenset(
    {
        ".zip",
        ".zipx",
        ".cbz",  # comic book zip — often full of images
        ".cbr",  # rar comics — best-effort
        ".tar",
        ".rar",
        ".7z",
    }
)

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._\-+=@()\[\] ]+")


@dataclass
class ArchiveExpandResult:
    archive: Path
    media_files: list[Path]
    skipped_non_media: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and len(self.media_files) > 0


def is_archive_path(path: Path) -> bool:
    name = path.name.lower()
    if any(name.endswith(s) for s in _COMPOUND_ARCHIVE_SUFFIXES):
        return True
    return path.suffix.lower() in _SIMPLE_ARCHIVE_SUFFIXES


def archive_suffix(path: Path) -> str:
    name = path.name.lower()
    for s in _COMPOUND_ARCHIVE_SUFFIXES:
        if name.endswith(s):
            return s
    return path.suffix.lower()


def is_media_member(name: str) -> bool:
    """True if archive member path looks like library media."""
    # zip uses / separators
    base = name.rsplit("/", 1)[-1]
    if not base or base.startswith("."):
        return False
    # Skip macOS resource forks / junk
    if "__MACOSX" in name.replace("\\", "/"):
        return False
    if base.startswith("._"):
        return False
    ext = Path(base).suffix.lower()
    return ext in MEDIA_EXTENSIONS


def _safe_rel_path(member: str) -> Path | None:
    """Reject zip-slip paths; return a relative Path or None."""
    # Normalise separators
    raw = member.replace("\\", "/").lstrip("/")
    if not raw or raw.endswith("/"):
        return None
    parts: list[str] = []
    for part in raw.split("/"):
        if part in ("", ".", ".."):
            if part == "..":
                return None  # path traversal
            continue
        # Soft-sanitise each segment (keep readable names)
        cleaned = _SAFE_NAME_RE.sub("_", part).strip(" .")
        if not cleaned or cleaned in (".", ".."):
            return None
        parts.append(cleaned[:180])
    if not parts:
        return None
    return Path(*parts)


def scan_archives(root: Path, *, mode: str = "disc") -> list[Path]:
    """Find archive files under root (or the file itself)."""
    if root.is_file():
        return [root] if is_archive_path(root) else []
    if not root.is_dir():
        return []
    found: list[Path] = []
    if mode == "media":
        # Non-recursive: only archives sitting in the folder
        for p in sorted(root.iterdir()):
            if p.is_file() and is_archive_path(p):
                found.append(p)
        return found
    for p in sorted(root.rglob("*")):
        if p.is_file() and is_archive_path(p):
            found.append(p)
    return found


def archive_has_media(path: Path) -> bool:
    """Cheap peek: does the archive list any media members?"""
    try:
        kind = archive_suffix(path)
        if kind in (".zip", ".zipx", ".cbz"):
            with zipfile.ZipFile(path, "r") as zf:
                return any(
                    is_media_member(i.filename) and not i.is_dir()
                    for i in zf.infolist()
                )
        if kind in (
            ".tar",
            ".tar.gz",
            ".tgz",
            ".tar.bz2",
            ".tbz2",
            ".tar.xz",
            ".txz",
        ):
            with tarfile.open(path, "r:*") as tf:
                for m in tf.getmembers():
                    if m.isfile() and is_media_member(m.name):
                        return True
            return False
        # rar/7z — try listing via 7z
        if kind in (".rar", ".7z", ".cbr"):
            return _external_list_has_media(path)
    except Exception as exc:  # noqa: BLE001
        log.warning("archive_peek_failed", path=str(path), error=str(exc))
    return False


def expand_archive_media(
    archive: Path,
    dest_root: Path,
    *,
    settings: Settings | None = None,
    max_files: int | None = None,
    max_total_bytes: int | None = None,
) -> ArchiveExpandResult:
    """Extract media members from *archive* into *dest_root*.

    Only files with media extensions are written. Paths are sanitized
    against zip-slip. Returns absolute paths of extracted files.
    """
    if settings is None:
        from neuraldisc.config import get_settings

        settings = get_settings()
    max_files = (
        max_files if max_files is not None else settings.import_archive_max_files
    )
    max_total_bytes = (
        max_total_bytes
        if max_total_bytes is not None
        else settings.import_archive_max_bytes
    )

    dest_root = dest_root.resolve()
    dest_root.mkdir(parents=True, exist_ok=True)

    kind = archive_suffix(archive)
    try:
        if kind in (".zip", ".zipx", ".cbz"):
            return _extract_zip(
                archive, dest_root, max_files=max_files, max_total_bytes=max_total_bytes
            )
        if kind in (
            ".tar",
            ".tar.gz",
            ".tgz",
            ".tar.bz2",
            ".tbz2",
            ".tar.xz",
            ".txz",
        ):
            return _extract_tar(
                archive, dest_root, max_files=max_files, max_total_bytes=max_total_bytes
            )
        if kind in (".rar", ".7z", ".cbr"):
            return _extract_external(
                archive, dest_root, max_files=max_files, max_total_bytes=max_total_bytes
            )
        return ArchiveExpandResult(
            archive=archive, media_files=[], error=f"unsupported archive type {kind}"
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("archive_expand_failed", path=str(archive), error=str(exc))
        return ArchiveExpandResult(archive=archive, media_files=[], error=str(exc))


def _extract_zip(
    archive: Path,
    dest_root: Path,
    *,
    max_files: int,
    max_total_bytes: int,
) -> ArchiveExpandResult:
    media: list[Path] = []
    skipped = 0
    total = 0
    with zipfile.ZipFile(archive, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            if not is_media_member(info.filename):
                skipped += 1
                continue
            rel = _safe_rel_path(info.filename)
            if rel is None:
                skipped += 1
                continue
            if len(media) >= max_files:
                log.warning(
                    "archive_max_files",
                    path=str(archive),
                    max_files=max_files,
                )
                break
            size = int(info.file_size or 0)
            if total + size > max_total_bytes:
                log.warning(
                    "archive_max_bytes",
                    path=str(archive),
                    max_total_bytes=max_total_bytes,
                )
                break
            out = dest_root / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            # Stream extract (avoid zipfile.extract path bugs)
            with zf.open(info, "r") as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
            media.append(out)
            total += size
    return ArchiveExpandResult(
        archive=archive, media_files=media, skipped_non_media=skipped
    )


def _extract_tar(
    archive: Path,
    dest_root: Path,
    *,
    max_files: int,
    max_total_bytes: int,
) -> ArchiveExpandResult:
    media: list[Path] = []
    skipped = 0
    total = 0
    with tarfile.open(archive, "r:*") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            if not is_media_member(member.name):
                skipped += 1
                continue
            rel = _safe_rel_path(member.name)
            if rel is None:
                skipped += 1
                continue
            if len(media) >= max_files:
                log.warning("archive_max_files", path=str(archive), max_files=max_files)
                break
            size = int(member.size or 0)
            if total + size > max_total_bytes:
                log.warning(
                    "archive_max_bytes",
                    path=str(archive),
                    max_total_bytes=max_total_bytes,
                )
                break
            out = dest_root / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            extracted = tf.extractfile(member)
            if extracted is None:
                skipped += 1
                continue
            with extracted, open(out, "wb") as dst:
                shutil.copyfileobj(extracted, dst, length=1024 * 1024)
            media.append(out)
            total += size
    return ArchiveExpandResult(
        archive=archive, media_files=media, skipped_non_media=skipped
    )


def _find_external_tool() -> list[str] | None:
    for cmd in ("7z", "7zz", "unar"):
        path = shutil.which(cmd)
        if path:
            return [path]
    return None


def _external_list_has_media(archive: Path) -> bool:
    tool = _find_external_tool()
    if not tool:
        log.info("archive_tool_missing", path=str(archive), kind=archive_suffix(archive))
        return False
    binary = tool[0]
    try:
        if binary.endswith("unar") or Path(binary).name == "unar":
            # unar has no great list; try 7z-style via lsar if present
            lsar = shutil.which("lsar")
            if not lsar:
                # Assume might have media — extract will filter
                return True
            r = subprocess.run(
                [lsar, str(archive)],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            return any(is_media_member(line.strip()) for line in r.stdout.splitlines())
        # 7z l
        r = subprocess.run(
            [binary, "l", "-ba", str(archive)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        for line in r.stdout.splitlines():
            # last token is often the name
            parts = line.split()
            if not parts:
                continue
            name = parts[-1]
            if is_media_member(name):
                return True
    except Exception as exc:  # noqa: BLE001
        log.warning("archive_external_list_failed", path=str(archive), error=str(exc))
    return False


def _extract_external(
    archive: Path,
    dest_root: Path,
    *,
    max_files: int,
    max_total_bytes: int,
) -> ArchiveExpandResult:
    tool = _find_external_tool()
    if not tool:
        return ArchiveExpandResult(
            archive=archive,
            media_files=[],
            error="no 7z/unar on PATH for rar/7z",
        )
    binary = tool[0]
    scratch = dest_root / "_raw"
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        if Path(binary).name in ("7z", "7zz"):
            cmd = [binary, "x", f"-o{scratch}", "-y", str(archive)]
        else:
            # unar
            cmd = [binary, "-o", str(scratch), "-f", str(archive)]
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
        if r.returncode != 0:
            return ArchiveExpandResult(
                archive=archive,
                media_files=[],
                error=f"extract failed ({r.returncode}): {(r.stderr or r.stdout)[:200]}",
            )
    except Exception as exc:  # noqa: BLE001
        return ArchiveExpandResult(archive=archive, media_files=[], error=str(exc))

    # Move only media into dest_root (flatten-safe relative paths)
    media: list[Path] = []
    skipped = 0
    total = 0
    for p in sorted(scratch.rglob("*")):
        if not p.is_file():
            continue
        try:
            rel_in = p.relative_to(scratch)
        except ValueError:
            continue
        if not is_media_member(str(rel_in).replace(os.sep, "/")):
            skipped += 1
            continue
        rel = _safe_rel_path(str(rel_in).replace(os.sep, "/"))
        if rel is None:
            skipped += 1
            continue
        if len(media) >= max_files:
            break
        size = p.stat().st_size
        if total + size > max_total_bytes:
            break
        out = dest_root / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            p.unlink(missing_ok=True)
        else:
            shutil.move(str(p), str(out))
        media.append(out)
        total += size

    # Drop raw extract tree
    shutil.rmtree(scratch, ignore_errors=True)
    return ArchiveExpandResult(
        archive=archive, media_files=media, skipped_non_media=skipped
    )


def expand_archives_for_import(
    archives: Iterable[Path],
    staging_root: Path,
    *,
    settings: Settings,
    source_root: Path | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> list[tuple[Path, str, str]]:
    """Expand archives into staging and return work tuples (src, rel, media_type).

    ``rel`` is a provenance-friendly path like ``archives/holiday.zip/IMG_001.JPG``.
    """
    from neuraldisc.ingest.extractor import media_type_for

    work: list[tuple[Path, str, str]] = []
    for i, archive in enumerate(archives):
        if not archive.is_file():
            continue
        if not settings.import_expand_archives:
            continue
        # Size guard on the archive itself
        try:
            if archive.stat().st_size > settings.import_archive_max_bytes:
                log.warning(
                    "archive_too_large_skip",
                    path=str(archive),
                    size=archive.stat().st_size,
                )
                continue
        except OSError:
            continue

        if not archive_has_media(archive):
            log.info("archive_no_media", path=str(archive))
            continue

        try:
            if source_root and source_root.is_dir():
                try:
                    arc_rel = archive.relative_to(source_root)
                except ValueError:
                    arc_rel = Path(archive.name)
            else:
                arc_rel = Path(archive.name)
        except Exception:  # noqa: BLE001
            arc_rel = Path(archive.name)

        # Unique extract folder under staging
        safe_stem = _SAFE_NAME_RE.sub("_", archive.stem)[:80] or "archive"
        dest = staging_root / "_archives" / f"{i:03d}_{safe_stem}"
        if on_progress:
            on_progress(f"Expanding archive {archive.name}…")
        log.info("archive_expand_start", path=str(archive), dest=str(dest))
        result = expand_archive_media(archive, dest, settings=settings)
        if not result.ok:
            log.warning(
                "archive_expand_empty",
                path=str(archive),
                error=result.error,
            )
            continue
        for f in result.media_files:
            mtype = media_type_for(f)
            if not mtype:
                continue
            try:
                inner = f.relative_to(dest)
            except ValueError:
                inner = Path(f.name)
            rel = str(Path("archives") / arc_rel / inner)
            work.append((f, rel, mtype))
        log.info(
            "archive_expand_done",
            path=str(archive),
            media=len(result.media_files),
            skipped=result.skipped_non_media,
        )
    return work
