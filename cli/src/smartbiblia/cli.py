"""
smartbiblia — installe les skills et les serveurs MCP smartbiblia dans un
workspace agent.

Le catalogue est lu depuis GitHub à chaque appel : la CLI ne contient aucune
copie des skills, seulement de quoi les récupérer.

    smartbiblia list [--kind skill|mcp] [--tag <tag>]
    smartbiblia info <nom>
    smartbiblia add <nom> [--dest <path>] [--claude] [--force]
    smartbiblia update <nom> [--dest <path>] [--claude]
    smartbiblia remove <nom> [--dest <path>] [--claude]
    smartbiblia mcp-config <nom> [--transport stdio|http] [--dest <path>]
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Optional

import tomllib
import typer
from rich import print
from rich.console import Console
from rich.table import Table

from . import __version__
from .installer import BRANCH, fetch_catalog_raw, fetch_path, raw_url, repo_url

app = typer.Typer(
    name="smartbiblia",
    help=(
        "Installe les skills et serveurs MCP smartbiblia dans ton workspace agent. "
        "Le catalogue est récupéré depuis GitHub à chaque appel."
    ),
    no_args_is_help=True,
)
console = Console()

SKILL_DEST = Path("skills")
MCP_DEST = Path("mcp")
CLAUDE_SKILLS = Path.home() / ".claude" / "skills"

MATURITY_COLOR = {"stable": "green", "beta": "yellow", "experimental": "red"}


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

def _load_catalog() -> dict:
    try:
        return tomllib.loads(fetch_catalog_raw())
    except Exception as exc:
        print(f"[red]Impossible de charger le catalogue : {exc}[/red]")
        print(f"[dim]Source : {repo_url()} (branche {BRANCH})[/dim]")
        raise typer.Exit(1)


def _entries(catalog: dict, kind: Optional[str] = None) -> list[tuple[str, str, dict]]:
    """Aplatit le catalogue en (kind, alias, meta), skills d'abord."""
    out: list[tuple[str, str, dict]] = []
    for k in ("skill", "mcp"):
        if kind and k != kind:
            continue
        section = "skills" if k == "skill" else "mcp"
        for alias, meta in catalog.get(section, {}).items():
            out.append((k, alias, meta))
    return out


def _resolve(catalog: dict, name: str, kind: Optional[str] = None) -> tuple[str, str, dict]:
    """Résout un alias court OU un nom canonique. Retourne (kind, alias, meta)."""
    matches = [
        (k, alias, meta)
        for k, alias, meta in _entries(catalog, kind)
        if name in (alias, meta.get("name", alias))
    ]
    if not matches:
        print(f"[red]'{name}' est introuvable dans le catalogue.[/red]")
        print("[dim]Voir [bold]smartbiblia list[/bold] pour les noms disponibles.[/dim]")
        raise typer.Exit(1)
    if len(matches) > 1:
        kinds = ", ".join(f"--kind {k}" for k, _, _ in matches)
        print(f"[red]'{name}' existe en plusieurs types. Précisez : {kinds}[/red]")
        raise typer.Exit(1)
    return matches[0]


def _canonical(meta: dict, alias: str) -> str:
    """Nom du dossier d'installation.

    Toujours le nom canonique, jamais l'alias : un runtime d'agent apparie le
    nom du dossier et le champ `name` du frontmatter, et un dossier `sudoc/`
    contenant `name: search-records-sudoc` peut ne pas être chargé.
    """
    return meta.get("name", alias)


def _default_dest(kind: str, dest: Optional[Path], claude: bool) -> Path:
    if dest is not None:
        return dest
    if claude:
        if kind != "skill":
            print("[red]--claude ne s'applique qu'aux skills.[/red]")
            raise typer.Exit(1)
        return CLAUDE_SKILLS
    return SKILL_DEST if kind == "skill" else MCP_DEST


def _frontmatter_name(skill_md: Path) -> Optional[str]:
    """Lit le `name:` du frontmatter sans dépendre d'un parseur YAML."""
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"^name:\s*(\S+)\s*$", text, re.MULTILINE)
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

@app.command("list")
def list_cmd(
    kind: Annotated[Optional[str], typer.Option("--kind", "-k", help="skill | mcp")] = None,
    tag: Annotated[Optional[str], typer.Option("--tag", "-t", help="Filtrer par tag")] = None,
):
    """Liste les skills et serveurs MCP disponibles."""
    if kind and kind not in ("skill", "mcp"):
        print("[red]--kind attend 'skill' ou 'mcp'.[/red]")
        raise typer.Exit(1)

    catalog = _load_catalog()

    table = Table(title=f"smartbiblia — catalogue ({repo_url()})", highlight=True)
    table.add_column("Type", style="magenta", no_wrap=True)
    table.add_column("Nom", style="cyan bold", no_wrap=True)
    table.add_column("Installé sous", style="dim", no_wrap=True)
    table.add_column("Maturité", no_wrap=True)
    table.add_column("Description")

    shown = 0
    for k, alias, meta in _entries(catalog, kind):
        if tag and tag not in meta.get("tags", []):
            continue
        maturity = meta.get("maturity", "")
        color = MATURITY_COLOR.get(maturity, "white")
        canonical = _canonical(meta, alias)
        table.add_row(
            k,
            alias,
            canonical if canonical != alias else "—",
            f"[{color}]{maturity}[/{color}]",
            meta.get("description", ""),
        )
        shown += 1

    console.print(table)
    if not shown:
        print("[yellow]Aucune entrée ne correspond à ce filtre.[/yellow]")
        return
    print("[dim]La colonne « Nom » est l'alias à passer aux commandes ; "
          "« Installé sous » est le nom canonique du dossier créé.[/dim]")


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------

@app.command()
def info(
    name: Annotated[str, typer.Argument(help="Alias ou nom canonique")],
    kind: Annotated[Optional[str], typer.Option("--kind", "-k", help="skill | mcp")] = None,
):
    """Affiche le détail d'une entrée du catalogue."""
    catalog = _load_catalog()
    k, alias, meta = _resolve(catalog, name, kind)
    canonical = _canonical(meta, alias)

    print(f"\n[bold cyan]{alias}[/bold cyan] [dim]({k})[/dim]")
    print(f"[bold]Description   :[/bold] {meta.get('description', '')}")
    print(f"[bold]Nom canonique :[/bold] {canonical}")
    print(f"[bold]Maturité      :[/bold] {meta.get('maturity', '')}")
    print(f"[bold]Tags          :[/bold] {', '.join(meta.get('tags', []))}")
    print(f"[bold]Chemin repo   :[/bold] {meta.get('path', '')}")

    if k == "mcp":
        print(f"[bold]Entrypoint    :[/bold] {meta.get('entrypoint', 'mcp_server.py')}")
        print(f"[bold]Port HTTP     :[/bold] {meta.get('port', '')}")
        env = meta.get("env", [])
        required = set(meta.get("env_required", []))
        if env:
            rendered = ", ".join(f"{e}[red]*[/red]" if e in required else e for e in env)
            print(f"[bold]Variables     :[/bold] {rendered}")
            if required:
                print("[dim]* obligatoire[/dim]")
        else:
            print("[bold]Variables     :[/bold] aucune (accès public)")

    dest = SKILL_DEST if k == "skill" else MCP_DEST
    print(f"\n[dim]Installation : smartbiblia add {alias}  →  {dest / canonical}[/dim]\n")


# ---------------------------------------------------------------------------
# add / update / remove
# ---------------------------------------------------------------------------

@app.command()
def add(
    name: Annotated[str, typer.Argument(help="Alias ou nom canonique (ex: sudoc, openalex)")],
    dest: Annotated[Optional[Path], typer.Option("--dest", "-d", help="Dossier parent (défaut: ./skills ou ./mcp)")] = None,
    claude: Annotated[bool, typer.Option("--claude", help="Installer dans ~/.claude/skills")] = False,
    kind: Annotated[Optional[str], typer.Option("--kind", "-k", help="skill | mcp")] = None,
    force: Annotated[bool, typer.Option("--force", "-f", help="Écraser sans confirmation")] = False,
):
    """Installe une skill ou un serveur MCP dans le workspace courant."""
    catalog = _load_catalog()
    k, alias, meta = _resolve(catalog, name, kind)
    canonical = _canonical(meta, alias)
    target = _default_dest(k, dest, claude) / canonical

    if target.exists() and not force:
        if not typer.confirm(f"{target} existe déjà. Écraser ?", default=False):
            raise typer.Exit(0)

    with console.status(f"Téléchargement de [cyan]{canonical}[/cyan] depuis GitHub…"):
        try:
            written = fetch_path(meta["path"], target, clean=True)
        except Exception as exc:
            print(f"[red]Erreur lors du téléchargement : {exc}[/red]")
            raise typer.Exit(1)

    print(f"[green]✓ {k} [bold]{canonical}[/bold] installé dans [bold]{target}[/bold][/green] "
          f"[dim]({len(written)} fichiers)[/dim]")

    if k == "skill":
        declared = _frontmatter_name(target / "SKILL.md")
        if declared and declared != canonical:
            print(f"[yellow]⚠ Le frontmatter déclare name: {declared} alors que le dossier "
                  f"est {canonical}. Certains runtimes refusent de charger la skill.[/yellow]")
        env_example = target / "scripts" / ".env.example"
        if env_example.exists():
            print(f"[dim]Configuration optionnelle : cp {env_example} {target / 'scripts' / '.env'}[/dim]")
    else:
        required = meta.get("env_required", [])
        if required:
            print(f"[yellow]Variables obligatoires avant lancement : {', '.join(required)}[/yellow]")
        print(f"[dim]Configuration client : smartbiblia mcp-config {alias}[/dim]")


@app.command()
def update(
    name: Annotated[str, typer.Argument(help="Alias ou nom canonique")],
    dest: Annotated[Optional[Path], typer.Option("--dest", "-d")] = None,
    claude: Annotated[bool, typer.Option("--claude", help="Dans ~/.claude/skills")] = False,
    kind: Annotated[Optional[str], typer.Option("--kind", "-k", help="skill | mcp")] = None,
):
    """Met à jour une entrée déjà installée (réinstalle depuis GitHub).

    Le dossier est vidé avant réécriture : un fichier supprimé en amont ne
    survit pas à la mise à jour.
    """
    add(name=name, dest=dest, claude=claude, kind=kind, force=True)


@app.command()
def remove(
    name: Annotated[str, typer.Argument(help="Alias ou nom canonique")],
    dest: Annotated[Optional[Path], typer.Option("--dest", "-d")] = None,
    claude: Annotated[bool, typer.Option("--claude", help="Dans ~/.claude/skills")] = False,
    kind: Annotated[Optional[str], typer.Option("--kind", "-k", help="skill | mcp")] = None,
    force: Annotated[bool, typer.Option("--force", "-f", help="Supprimer sans confirmation")] = False,
):
    """Désinstalle une skill ou un serveur MCP du workspace."""
    import shutil

    catalog = _load_catalog()
    k, alias, meta = _resolve(catalog, name, kind)
    canonical = _canonical(meta, alias)
    target = _default_dest(k, dest, claude) / canonical

    if not target.exists():
        print(f"[yellow]{target} n'existe pas — rien à supprimer.[/yellow]")
        raise typer.Exit(0)
    if not force and not typer.confirm(f"Supprimer {target} ?", default=False):
        raise typer.Exit(0)

    shutil.rmtree(target)
    print(f"[green]✓ {target} supprimé[/green]")


# ---------------------------------------------------------------------------
# mcp-config
# ---------------------------------------------------------------------------

@app.command("mcp-config")
def mcp_config(
    name: Annotated[str, typer.Argument(help="Alias du serveur MCP")],
    transport: Annotated[str, typer.Option("--transport", "-t", help="stdio | http")] = "stdio",
    dest: Annotated[Optional[Path], typer.Option("--dest", "-d", help="Dossier parent d'installation")] = None,
    remote: Annotated[bool, typer.Option("--remote", help="Exécuter depuis GitHub, sans installation locale")] = False,
):
    """Affiche le bloc de configuration à coller dans un client MCP.

    Le format `mcpServers` est celui de Claude Desktop, Claude Code, Codex et
    de la plupart des clients ; adaptez la clé racine si le vôtre diffère.
    """
    if transport not in ("stdio", "http"):
        print("[red]--transport attend 'stdio' ou 'http'.[/red]")
        raise typer.Exit(1)

    catalog = _load_catalog()
    k, alias, meta = _resolve(catalog, name, "mcp")
    canonical = _canonical(meta, alias)
    entrypoint = meta.get("entrypoint", "mcp_server.py")
    port = meta.get("port", 8000)

    if remote:
        script = f"{raw_url(meta['path'])}/{entrypoint}"
    else:
        script = str(((dest or MCP_DEST) / canonical / entrypoint).resolve())

    env = {var: "" for var in meta.get("env", [])}

    if transport == "stdio":
        block = {
            "mcpServers": {
                f"smartbiblia-{canonical}": {
                    "command": "uv",
                    "args": ["run", script, "--transport", "stdio"],
                    **({"env": env} if env else {}),
                }
            }
        }
    else:
        block = {
            "mcpServers": {
                f"smartbiblia-{canonical}": {
                    "type": "http",
                    "url": f"http://127.0.0.1:{port}/mcp",
                }
            }
        }

    console.print_json(json.dumps(block))

    if transport == "http":
        print(f"\n[dim]Lancer d'abord le serveur :\n"
              f"  uv run {script} --transport streamable-http --host 127.0.0.1 --port {port}[/dim]")
    required = meta.get("env_required", [])
    if required:
        print(f"[yellow]Renseignez au moins : {', '.join(required)}[/yellow]")


# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------

@app.command()
def version():
    """Affiche la version de la CLI et la source du catalogue."""
    print(f"smartbiblia {__version__}")
    print(f"[dim]catalogue : {repo_url()} (branche {BRANCH})[/dim]")
