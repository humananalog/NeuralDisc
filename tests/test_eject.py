"""Tests for volume eject guards (no real diskutil)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from neuraldisc.ingest.detector import eject_volume


def test_eject_refuses_non_volumes_path(tmp_path: Path) -> None:
    result = eject_volume(tmp_path / "somewhere")
    assert result["ok"] is False
    assert "refusing" in (result.get("error") or "").lower()


def test_eject_refuses_system_volume() -> None:
    result = eject_volume("/Volumes/Macintosh HD")
    assert result["ok"] is False
    assert "system" in (result.get("error") or "").lower()


def test_eject_already_unmounted() -> None:
    missing = Path("/Volumes/__neuraldisc_no_such_disc__")
    assert not missing.exists()
    result = eject_volume(missing)
    assert result["ok"] is True
    assert result.get("already_unmounted") is True


def test_eject_calls_diskutil() -> None:
    fake = Path("/Volumes/TestDiscOptical")

    def fake_run(cmd, **_kwargs):
        assert cmd[0].endswith("diskutil") or cmd[0] == "diskutil"
        assert cmd[1] == "eject"
        return SimpleNamespace(returncode=0, stdout="Disk ejected", stderr="")

    with (
        patch("neuraldisc.ingest.detector.subprocess.run", side_effect=fake_run) as run,
        patch.object(Path, "exists", return_value=True),
        patch.object(Path, "resolve", return_value=fake),
    ):
        result = eject_volume("/Volumes/TestDiscOptical")
    assert result["ok"] is True
    assert run.called
