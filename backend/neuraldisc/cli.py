"""NeuralDisc CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from neuraldisc import __version__
from neuraldisc.config import apply_library_root, get_settings
from neuraldisc.db.database import create_all, init_engine, session_scope
from neuraldisc.db.models import Disc, MediaItem
from neuraldisc.ingest.detector import VolumeWatcher, list_mounted_volumes, probe_volume
from neuraldisc.ingest.extractor import Extractor
from neuraldisc.utils.logging import setup_logging

app = typer.Typer(
    name="neuraldisc",
    help="NeuralDisc — local-first photo & video library for Apple Silicon",
    no_args_is_help=True,
)
console = Console()


def _bootstrap(library_root: Optional[Path] = None) -> None:
    if library_root:
        apply_library_root(library_root)
    settings = get_settings()
    setup_logging(settings.logs_dir)
    settings.ensure_layout()
    init_engine(settings)
    create_all()


@app.callback()
def main(
    library: Optional[Path] = typer.Option(
        None,
        "--library",
        "-L",
        help="Library root (default: ~/NeuralDisc or NEURALDISC_LIBRARY_ROOT)",
        envvar="NEURALDISC_LIBRARY_ROOT",
    ),
) -> None:
    if library:
        apply_library_root(library)


@app.command()
def version() -> None:
    """Print version."""
    console.print(f"NeuralDisc {__version__}")


@app.command()
def init(
    library: Optional[Path] = typer.Option(None, "--library", "-L"),
) -> None:
    """Create library folder structure and database."""
    _bootstrap(library)
    s = get_settings()
    console.print(f"[green]Library ready at[/green] {s.library_root}")
    console.print(f"  SQLite: {s.sqlite_path}")


@app.command()
def ingest(
    path: Path = typer.Argument(..., help="Path to disc mount or folder of media"),
    volume_name: Optional[str] = typer.Option(None, "--name", "-n"),
    no_process: bool = typer.Option(False, "--no-process", help="Skip post-ingest pipeline"),
    library: Optional[Path] = typer.Option(None, "--library", "-L"),
) -> None:
    """Ingest media from a disc volume or directory."""
    _bootstrap(library)
    path = path.expanduser().resolve()
    if not path.exists():
        console.print(f"[red]Path not found:[/red] {path}")
        raise typer.Exit(1)

    name = volume_name
    uuid = None
    fs = None
    if path.is_dir() and str(path).startswith("/Volumes"):
        info = probe_volume(path)
        name = name or info.name
        uuid = info.volume_uuid
        fs = info.filesystem

    console.print(f"Ingesting [bold]{path}[/bold] as [cyan]{name or path.name}[/cyan]…")
    result = Extractor().extract(
        path,
        volume_name=name,
        volume_uuid=uuid,
        filesystem=fs,
        process_after=not no_process,
    )
    console.print(
        f"[green]Done.[/green] disc_id={result.disc_id}  "
        f"files={len(result.files)}  rejected={len(result.rejected)}  "
        f"errors={len(result.errors)}"
    )
    console.print(f"Provenance: {result.provenance_dir}")
    if result.rejected:
        console.print(
            f"[yellow]Quality gate rejected {len(result.rejected)} files "
            f"(too small / vector / web junk)[/yellow]"
        )
        for r in result.rejected[:15]:
            console.print(f"  [dim]×[/dim] {r.path.name}: {r.code} — {r.reason}")
        if len(result.rejected) > 15:
            console.print(f"  … and {len(result.rejected) - 15} more")
    if result.errors:
        for e in result.errors[:10]:
            console.print(f"  [yellow]![/yellow] {e}")


@app.command("watch")
def watch_volumes(
    optical_only: bool = typer.Option(False, "--optical-only"),
    library: Optional[Path] = typer.Option(None, "--library", "-L"),
) -> None:
    """Watch /Volumes for new media and auto-ingest."""
    _bootstrap(library)

    def on_volume(info) -> None:  # type: ignore[no-untyped-def]
        console.print(f"[cyan]New volume:[/cyan] {info.name} @ {info.path}")
        try:
            result = Extractor().extract(
                info.path,
                volume_name=info.name,
                volume_uuid=info.volume_uuid,
                filesystem=info.filesystem,
                process_after=True,
            )
            console.print(
                f"  Ingested {len(result.files)} files (disc {result.disc_id})"
            )
        except Exception as exc:  # noqa: BLE001
            console.print(f"  [red]Ingest failed:[/red] {exc}")

    watcher = VolumeWatcher(on_volume=on_volume, optical_only=optical_only)
    console.print("Watching /Volumes — Ctrl+C to stop")
    try:
        watcher.run()
    except KeyboardInterrupt:
        console.print("\nStopped.")


@app.command("volumes")
def volumes_cmd() -> None:
    """List currently mounted volumes."""
    table = Table("Path", "Name", "UUID", "FS", "Optical", "Ejectable")
    for v in list_mounted_volumes():
        table.add_row(
            str(v.path),
            v.name,
            v.volume_uuid or "",
            v.filesystem or "",
            "yes" if v.is_optical else "",
            "yes" if v.is_ejectable else "",
        )
    console.print(table)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port", "-p"),
    reload: bool = typer.Option(False, "--reload"),
    library: Optional[Path] = typer.Option(None, "--library", "-L"),
) -> None:
    """Start the FastAPI backend."""
    _bootstrap(library)
    console.print(f"API → http://{host}:{port}  docs → http://{host}:{port}/docs")
    uvicorn.run(
        "neuraldisc.api.main:app",
        host=host,
        port=port,
        reload=reload,
        timeout_keep_alive=30,
        limit_concurrency=100,
    )


@app.command()
def stats(
    library: Optional[Path] = typer.Option(None, "--library", "-L"),
) -> None:
    """Print library statistics."""
    _bootstrap(library)
    with session_scope() as session:
        discs = session.query(Disc).count()
        media = session.query(MediaItem).count()
        pending = (
            session.query(MediaItem).filter(MediaItem.hitl_status == "pending").count()
        )
    s = get_settings()
    console.print(
        json.dumps(
            {
                "library_root": str(s.library_root),
                "discs": discs,
                "media": media,
                "pending_review": pending,
            },
            indent=2,
        )
    )


@app.command("repair-dates")
def repair_dates(
    library: Optional[Path] = typer.Option(None, "--library", "-L"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report changes without writing"),
    all_items: bool = typer.Option(
        False,
        "--all",
        help="Re-check every item (default: only import-dated / missing taken_at)",
    ),
    reorganise: bool = typer.Option(
        True,
        "--reorganise/--no-reorganise",
        help="Rebuild year/event smart albums after updates",
    ),
) -> None:
    """Fix taken_at that was set to import/copy time instead of capture/EXIF/path date."""
    _bootstrap(library)
    from neuraldisc.processing.dates_repair import repair_taken_at

    with session_scope() as session:
        result = repair_taken_at(
            session,
            dry_run=dry_run,
            only_suspicious=not all_items,
        )
    # Separate transaction: organise must not roll back date fixes on failure
    org = None
    if reorganise and not dry_run and (result.updated or result.cleared):
        from neuraldisc.processing.organisation import auto_organise

        with session_scope() as session:
            org = auto_organise(session, min_members=2).as_dict()
    payload: dict = {"dry_run": dry_run, **result.as_dict()}
    if org is not None:
        payload["organise"] = org
    console.print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    app()
