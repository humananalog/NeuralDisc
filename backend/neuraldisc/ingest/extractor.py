"""Recursive disc/folder extractor with provenance and SHA-256."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from neuraldisc.config import IMAGE_EXTENSIONS, MEDIA_EXTENSIONS, VIDEO_EXTENSIONS, Settings, get_settings
from neuraldisc.db.database import session_scope
from neuraldisc.db.models import Disc, MediaItem
from neuraldisc.processing.quality import evaluate_path
from neuraldisc.utils.hashing import sha256_file
from neuraldisc.utils.logging import get_logger

log = get_logger(__name__)


@dataclass
class ExtractedFile:
    source_path: Path
    staging_path: Path
    library_path: Path
    relative_path: str
    filename: str
    media_type: str
    sha256: str
    file_size: int
    seq: int


@dataclass
class RejectedFile:
    path: Path
    code: str
    reason: str


@dataclass
class ExtractResult:
    disc_id: str
    volume_name: str
    provenance_dir: str
    files: list[ExtractedFile] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: int = 0
    rejected: list[RejectedFile] = field(default_factory=list)


def file_is_readable(path: Path) -> tuple[bool, str | None]:
    """Return whether *path* can actually be opened for reading.

    Optical discs and odd mounts often list files that ``stat`` but fail on
    ``open`` (permissions, I/O errors, broken UDF entries). Import scanning
    must skip these instead of queuing them as copy errors.
    """
    try:
        if not path.is_file():
            return False, "not a regular file"
        if not os.access(path, os.R_OK):
            return False, "permission denied"
        with path.open("rb") as f:
            f.read(1)
        return True, None
    except OSError as exc:
        return False, str(exc) or exc.__class__.__name__


def media_type_for(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    return None


def is_media_file(path: Path) -> bool:
    return path.suffix.lower() in MEDIA_EXTENSIONS


def safe_volume_slug(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_" else "_" for c in name.strip())
    cleaned = cleaned.strip("_") or "unknown_volume"
    return cleaned[:80]


def make_provenance_name(volume_name: str, when: datetime | None = None) -> str:
    when = when or datetime.now(timezone.utc)
    stamp = when.strftime("%Y%m%d_%H%M%S")
    return f"{safe_volume_slug(volume_name)}_{stamp}"


def copy_with_sha256(
    src: Path,
    dest: Path,
    *,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[str, int]:
    """Copy file and compute SHA-256 of destination.

    ``should_cancel`` is checked between chunks so cooperative cancel can
    abort a large copy within ~1 MiB instead of waiting for the whole file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    with src.open("rb") as rf, dest.open("wb") as wf:
        h = __import__("hashlib").sha256()
        size = 0
        while True:
            if should_cancel and should_cancel():
                dest.unlink(missing_ok=True)
                raise InterruptedError("copy cancelled")
            chunk = rf.read(1024 * 1024)
            if not chunk:
                break
            wf.write(chunk)
            h.update(chunk)
            size += len(chunk)
    if should_cancel and should_cancel():
        dest.unlink(missing_ok=True)
        raise InterruptedError("copy cancelled")
    # Verify by re-reading dest
    verify = sha256_file(dest)
    if verify != h.hexdigest():
        dest.unlink(missing_ok=True)
        raise IOError(f"Checksum mismatch after copy: {src}")
    return verify, size


class Extractor:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_layout()

    def extract(
        self,
        source: Path,
        volume_name: str | None = None,
        volume_uuid: str | None = None,
        filesystem: str | None = None,
        process_after: bool = True,
    ) -> ExtractResult:
        source = source.resolve()
        if not source.exists():
            raise FileNotFoundError(f"Source path does not exist: {source}")

        name = volume_name or source.name
        when = datetime.now(timezone.utc)
        provenance = make_provenance_name(name, when)
        staging_root = self.settings.staging_dir / provenance
        staging_root.mkdir(parents=True, exist_ok=True)

        result = ExtractResult(disc_id="", volume_name=name, provenance_dir=provenance)

        with session_scope() as session:
            disc = Disc(
                volume_name=name,
                volume_uuid=volume_uuid,
                filesystem=filesystem,
                inserted_at=when,
                status="extracting",
                source_path=str(source),
            )
            session.add(disc)
            session.flush()
            result.disc_id = disc.id
            disc_id = disc.id

        log.info("extract_start", disc_id=disc_id, source=str(source), provenance=provenance)

        candidates: list[Path] = []
        if source.is_file() and (is_media_file(source) or source.suffix.lower()):
            # Include known media + blocked formats so we can log quality rejects
            if is_media_file(source) or source.suffix.lower() in {
                ".svg",
                ".eps",
                ".ai",
                ".pdf",
                ".ico",
                ".icns",
            }:
                candidates = [source]
        else:
            walk_exts = MEDIA_EXTENSIONS | {
                ".svg",
                ".svgz",
                ".eps",
                ".ai",
                ".pdf",
                ".ico",
                ".icns",
                ".emf",
                ".wmf",
            }
            for p in sorted(source.rglob("*")):
                if p.is_file() and p.suffix.lower() in walk_exts:
                    candidates.append(p)

        # Expand zip/tar archives that contain media (extract onto staging)
        work_extra: list[tuple[Path, str]] = []  # path, provenance rel
        if self.settings.import_expand_archives:
            from neuraldisc.ingest.archives import (
                expand_archives_for_import,
                is_archive_path,
                scan_archives,
            )

            if source.is_file() and is_archive_path(source):
                archives = [source]
            else:
                archives = scan_archives(source, mode="folder")
            if archives:
                expanded = expand_archives_for_import(
                    archives,
                    staging_root,
                    settings=self.settings,
                    source_root=source if source.is_dir() else source.parent,
                )
                for f, rel, _mtype in expanded:
                    work_extra.append((f, rel))

        seq = 0
        for src in candidates:
            mtype = media_type_for(src)
            try:
                rel = str(src.relative_to(source)) if source.is_dir() else src.name
            except ValueError:
                rel = src.name

            ok, why = file_is_readable(src)
            if not ok:
                result.rejected.append(
                    RejectedFile(
                        path=src,
                        code="unreadable",
                        reason=why or "cannot open for reading",
                    )
                )
                result.skipped += 1
                log.info("extract_skip_unreadable", path=str(src), reason=why)
                continue

            # Quality gate BEFORE copy — junk never enters originals/
            if self.settings.quality_enabled:
                verdict = evaluate_path(src, self.settings)
                if verdict.rejected:
                    result.rejected.append(
                        RejectedFile(
                            path=src,
                            code=verdict.code or "rejected",
                            reason=verdict.reason or "quality gate",
                        )
                    )
                    result.skipped += 1
                    log.info(
                        "quality_reject",
                        path=str(src),
                        code=verdict.code,
                        reason=verdict.reason,
                    )
                    if self.settings.quality_quarantine_rejects:
                        _quarantine_copy(
                            src,
                            self.settings.quarantine_dir / provenance / "rejected" / src.name,
                        )
                    continue

            if mtype is None:
                result.skipped += 1
                continue

            seq += 1
            dest_name = f"{seq:04d}_{src.name}"
            staging_path = staging_root / dest_name
            try:
                # Stay in staging until processed & classified
                digest, size = copy_with_sha256(src, staging_path)
                ef = ExtractedFile(
                    source_path=src,
                    staging_path=staging_path,
                    library_path=staging_path,  # points at staging until promote
                    relative_path=rel,
                    filename=src.name,
                    media_type=mtype,
                    sha256=digest,
                    file_size=size,
                    seq=seq,
                )
                result.files.append(ef)
            except Exception as exc:  # noqa: BLE001
                msg = f"{src}: {exc}"
                result.errors.append(msg)
                log.error("extract_file_error", path=str(src), error=str(exc))
                try:
                    _quarantine_copy(
                        src, self.settings.quarantine_dir / provenance / src.name
                    )
                except Exception:  # noqa: BLE001
                    pass

        # Files expanded from archives (already on staging volume)
        for src, rel in work_extra:
            mtype = media_type_for(src)
            if mtype is None:
                result.skipped += 1
                continue
            if self.settings.quality_enabled:
                verdict = evaluate_path(src, self.settings)
                if verdict.rejected:
                    result.rejected.append(
                        RejectedFile(
                            path=src,
                            code=verdict.code or "rejected",
                            reason=verdict.reason or "quality gate",
                        )
                    )
                    result.skipped += 1
                    continue
            seq += 1
            dest_name = f"{seq:04d}_{src.name}"
            staging_path = staging_root / dest_name
            try:
                digest, size = copy_with_sha256(src, staging_path)
                result.files.append(
                    ExtractedFile(
                        source_path=src,
                        staging_path=staging_path,
                        library_path=staging_path,
                        relative_path=rel,
                        filename=src.name,
                        media_type=mtype,
                        sha256=digest,
                        file_size=size,
                        seq=seq,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"{src}: {exc}")
                log.error("extract_archive_member_error", path=str(src), error=str(exc))

        # Persist media rows — lifecycle=staging
        with session_scope() as session:
            disc = session.get(Disc, disc_id)
            if disc is None:
                raise RuntimeError(f"Disc {disc_id} vanished")
            for ef in result.files:
                item = MediaItem(
                    disc_id=disc_id,
                    original_path=ef.relative_path,
                    library_path=str(ef.library_path),
                    filename=ef.filename,
                    media_type=ef.media_type,
                    file_size=ef.file_size,
                    sha256=ef.sha256,
                    hitl_status="accepted",
                    lifecycle="staging",
                )
                session.add(item)
            disc.status = "extracting" if process_after else "processed"
            disc.extracted_at = datetime.now(timezone.utc)
            reject_summary = ""
            if result.rejected:
                by_code: dict[str, int] = {}
                for r in result.rejected:
                    by_code[r.code] = by_code.get(r.code, 0) + 1
                reject_summary = "; rejected " + ", ".join(
                    f"{n}×{c}" for c, n in sorted(by_code.items())
                )
                disc.error_log = "\n".join(
                    ([disc.error_log] if disc.error_log else [])
                    + [f"REJECT {r.code}: {r.path.name} — {r.reason}" for r in result.rejected[:200]]
                )
            if result.errors:
                prev = disc.error_log or ""
                disc.error_log = (prev + "\n" if prev else "") + "\n".join(result.errors)
            disc.notes = (
                f"{len(result.files)} staged, {len(result.errors)} errors, "
                f"{len(result.rejected)} quality-rejected{reject_summary}"
            )

        log.info(
            "extract_complete",
            disc_id=disc_id,
            files=len(result.files),
            errors=len(result.errors),
            rejected=len(result.rejected),
        )

        if process_after and result.files:
            from neuraldisc.processing.pipeline import enqueue_post_ingest

            enqueue_post_ingest(disc_id)
            with session_scope() as session:
                disc = session.get(Disc, disc_id)
                if disc:
                    disc.status = "processed"

        return result


def _quarantine_copy(src: Path, dest: Path) -> None:
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.exists():
            shutil.copy2(src, dest)
    except OSError as exc:
        log.debug("quarantine_failed", path=str(src), error=str(exc))
