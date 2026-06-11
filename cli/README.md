# smartbiblia

CLI d'installation des skills [smartbiblia](https://github.com/smartbiblia-solutions/agentic-stack)
dans un workspace agent.

> Pour les MCP servers (OpenAlex, Sudoc SRU, Primo), voir les READMEs dans `mcp/` —
> ils s'installent via `git clone` ou `uv run <url>` directement, sans passer par cette CLI.

## Installation

Aucune installation permanente requise — utilise [`uvx`](https://docs.astral.sh/uv/) pour lancer directement depuis PyPI :

```bash
uvx smartbiblia list
```

Ou installe globalement :

```bash
uv tool install smartbiblia
# puis :
smartbiblia list
```

## Commandes

### Lister les skills disponibles

```bash
smartbiblia list
smartbiblia list --tag french
smartbiblia list --tag open-access
```

### Consulter le détail d'une skill

```bash
smartbiblia info idref
smartbiblia info synthesize
```

### Installer une skill

```bash
# Installe dans ./skills/idref/
smartbiblia add idref

# Dossier personnalisé
smartbiblia add sudoc --dest ./mon-projet/skills
```

### Mettre à jour une skill installée

```bash
smartbiblia update idref
smartbiblia update synthesize
```

## Développement local

```bash
cd cli/
uv sync
uv run smartbiblia list
```

### Publier sur PyPI

```bash
uv build
uv publish
```

> **Note :** mettre à jour `GITHUB_REPO` dans `installer.py` si le repo est renommé.
