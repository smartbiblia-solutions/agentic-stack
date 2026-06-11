"""
smartbiblia — CLI d'installation de skills pour agents.

Usage:
    smartbiblia list [--tag <tag>]
    smartbiblia add <name> [--dest <path>] [--force]
    smartbiblia info <name>
    smartbiblia update <name> [--dest <path>]
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import tomllib
import typer
from rich import print
from rich.table import Table
from rich.console import Console

from .installer import fetch_catalog_raw, fetch_path

app = typer.Typer(
    name="smartbiblia",
    help="Installe les skills smartbiblia dans ton workspace agent.",
    no_args_is_help=True,
)
console = Console()


def _load_catalog() -> dict:
    try:
        raw = fetch_catalog_raw()
        return tomllib.loads(raw)
    except Exception as exc:
        print(f"[red]Impossible de charger le catalogue : {exc}[/red]")
        raise typer.Exit(1)


def _resolve(catalog: dict, name: str) -> dict:
    meta = catalog.get("skills", {}).get(name)
    if not meta:
        print(f"[red]Skill '{name}' introuvable dans le catalogue.[/red]")
        print(f"[dim]Utilisez [bold]smartbiblia list[/bold] pour voir les skills disponibles.[/dim]")
        raise typer.Exit(1)
    return meta


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

@app.command("list")
def list_cmd(
    tag: Annotated[Optional[str], typer.Option("--tag", "-t", help="Filtrer par tag")] = None,
):
    """Liste les skills disponibles."""
    catalog = _load_catalog()

    table = Table(title="smartbiblia — skills disponibles", show_lines=False, highlight=True)
    table.add_column("Nom", style="cyan bold", no_wrap=True)
    table.add_column("Maturité")
    table.add_column("Description")

    for name, meta in catalog.get("skills", {}).items():
        if tag and tag not in meta.get("tags", []):
            continue
        maturity = meta.get("maturity", "")
        color = {"stable": "green", "beta": "yellow", "experimental": "red"}.get(maturity, "white")
        table.add_row(
            name,
            f"[{color}]{maturity}[/{color}]",
            meta.get("description", ""),
        )

    console.print(table)


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------

@app.command()
def info(
    name: Annotated[str, typer.Argument(help="Nom de la skill")],
):
    """Affiche les détails d'une skill."""
    catalog = _load_catalog()
    meta = _resolve(catalog, name)

    print(f"\n[bold cyan]{name}[/bold cyan]")
    print(f"[bold]Description :[/bold] {meta.get('description', '')}")
    print(f"[bold]Maturité    :[/bold] {meta.get('maturity', '')}")
    print(f"[bold]Tags        :[/bold] {', '.join(meta.get('tags', []))}")
    print(f"[bold]Chemin repo :[/bold] {meta.get('path', '')}")
    print()


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------

@app.command()
def add(
    name: Annotated[str, typer.Argument(help="Nom de la skill (ex: idref, sudoc, synthesize)")],
    dest: Annotated[Optional[Path], typer.Option("--dest", "-d", help="Dossier de destination (défaut: ./skills/)")] = None,
    force: Annotated[bool, typer.Option("--force", "-f", help="Écraser sans confirmation")] = False,
):
    """Installe une skill dans le workspace courant."""
    catalog = _load_catalog()
    meta = _resolve(catalog, name)

    target: Path = (dest or Path("skills")) / name

    if target.exists() and not force:
        overwrite = typer.confirm(f"{target} existe déjà. Écraser ?", default=False)
        if not overwrite:
            raise typer.Exit(0)

    with console.status(f"Téléchargement de la skill [cyan]{name}[/cyan]…"):
        try:
            fetch_path(meta["path"], target)
        except Exception as exc:
            print(f"[red]Erreur lors du téléchargement : {exc}[/red]")
            raise typer.Exit(1)

    print(f"[green]✓ Skill [bold]{name}[/bold] installée dans [bold]{target}[/bold][/green]")


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

@app.command()
def update(
    name: Annotated[str, typer.Argument(help="Nom de la skill à mettre à jour")],
    dest: Annotated[Optional[Path], typer.Option("--dest", "-d")] = None,
):
    """Met à jour une skill déjà installée (réinstalle depuis GitHub)."""
    add(name=name, dest=dest, force=True)
    print(f"[dim]Mise à jour terminée.[/dim]")
