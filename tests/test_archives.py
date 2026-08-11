"""Archive expansion for disc import."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from PIL import Image


def _make_jpeg(path: Path, color: tuple[int, int, int] = (40, 120, 200)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (640, 480), color)
    img.save(path, format="JPEG", quality=85)


def test_zip_with_images_is_detected_and_expanded(tmp_path: Path):
    from neuraldisc.ingest.archives import (
        archive_has_media,
        expand_archive_media,
        is_archive_path,
        is_media_member,
    )

    assert is_media_member("vacation/IMG_001.JPG")
    assert not is_media_member("__MACOSX/._IMG_001.JPG")
    assert not is_media_member("readme.txt")

    loose = tmp_path / "loose.jpg"
    _make_jpeg(loose)

    zpath = tmp_path / "photos.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.write(loose, arcname="album/P1000001.JPG")
        zf.writestr("notes.txt", "hello")
        zf.writestr("__MACOSX/._P1000001.JPG", b"junk")

    assert is_archive_path(zpath)
    assert archive_has_media(zpath)

    dest = tmp_path / "out"
    result = expand_archive_media(zpath, dest)
    assert result.ok
    assert len(result.media_files) == 1
    assert result.media_files[0].name == "P1000001.JPG"
    assert result.media_files[0].exists()
    assert result.media_files[0].stat().st_size > 1000


def test_zip_slip_rejected(tmp_path: Path):
    from neuraldisc.ingest.archives import expand_archive_media

    zpath = tmp_path / "evil.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        # path traversal attempt
        zf.writestr("../escape.jpg", b"not a real jpeg but name is media-like")
        zf.writestr("safe/ok.jpg", b"x" * 100)

    dest = tmp_path / "safe_out"
    result = expand_archive_media(zpath, dest)
    # ../escape should be rejected; ok.jpg may fail media quality later but path is ok
    for f in result.media_files:
        assert dest in f.resolve().parents or f.resolve().parent == dest.resolve()
        assert ".." not in f.parts


def test_empty_zip_no_media(tmp_path: Path):
    from neuraldisc.ingest.archives import archive_has_media, expand_archive_media

    zpath = tmp_path / "docs.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("readme.md", "# hi")
    assert not archive_has_media(zpath)
    dest = tmp_path / "out2"
    result = expand_archive_media(zpath, dest)
    assert not result.ok
    assert result.media_files == []


def test_expand_archives_for_import_work_tuples(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from neuraldisc.config import reset_settings
    from neuraldisc.ingest.archives import expand_archives_for_import, scan_archives

    lib = tmp_path / "lib"
    monkeypatch.setenv("NEURALDISC_LIBRARY_ROOT", str(lib))
    reset_settings()
    from neuraldisc.config import get_settings

    settings = get_settings()
    settings.ensure_layout()

    jpg = tmp_path / "src" / "a.jpg"
    _make_jpeg(jpg)
    zpath = tmp_path / "src" / "pack.zip"
    zpath.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.write(jpg, arcname="nested/shot.jpg")

    archives = scan_archives(tmp_path / "src", mode="folder")
    assert zpath in archives or any(a.name == "pack.zip" for a in archives)

    staging = settings.staging_dir / "test_prov"
    work = expand_archives_for_import(
        archives,
        staging,
        settings=settings,
        source_root=tmp_path / "src",
    )
    assert len(work) >= 1
    src, rel, mtype = work[0]
    assert src.exists()
    assert mtype == "image"
    assert "archives" in rel.replace("\\", "/")
