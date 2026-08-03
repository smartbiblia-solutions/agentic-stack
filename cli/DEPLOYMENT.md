# smartbiblia CLI — développement et publication

## Choix architectural

Le package PyPI est **uniquement la CLI**. Les skills et serveurs MCP ne sont
pas embarqués : ils sont récupérés depuis GitHub au moment du `add`.

Conséquences, toutes voulues :

- le package pèse une dizaine de kilo-octets ;
- corriger une skill ne demande pas de republier la CLI ;
- `update` est une simple réextraction ;
- le catalogue en ligne fait autorité — c'est lui, et non la version installée
  de la CLI, qui détermine ce qui est disponible.

Corollaire : **une modification de `catalog.toml` est en production dès qu'elle
est sur `main`**, y compris pour les CLI déjà installées. Les champs
`description`, `maturity`, `path`, `tags` sont lus par la 0.1.0 encore
déployée ; ne les retirez pas, ajoutez à côté.

## Fichiers

| Fichier | Rôle |
|---|---|
| `src/smartbiblia/catalog.toml` | Index des skills et des serveurs MCP. Source de vérité, lu depuis GitHub. |
| `src/smartbiblia/installer.py` | Téléchargement GitHub (tarball, client httpx poolé, cache par processus). |
| `src/smartbiblia/cli.py` | Commandes Typer : `list`, `info`, `add`, `update`, `remove`, `mcp-config`, `version`. |

## Ajouter une entrée au catalogue

1. Créer le dossier dans `skills/<nom-canonique>/` ou `mcp/<nom-canonique>/`.
2. Ajouter la table correspondante dans `catalog.toml` :
   - clé de table = alias court utilisé en ligne de commande ;
   - `name` = nom canonique, **identique** au nom du dossier et au champ `name`
     du frontmatter ;
   - `path` = chemin dans le repo ;
   - pour un MCP : `entrypoint`, `port`, `env`, `env_required`.
3. Pousser sur `main`. `smartbiblia list` la voit immédiatement.

## Test local

```bash
cd cli
uv sync
uv run smartbiblia list
uv run smartbiblia info primo
uv run smartbiblia mcp-config openalex --remote
```

Pour tester une branche avant fusion :

```bash
SMARTBIBLIA_BRANCH=ma-branche uv run smartbiblia list
```

Pour installer sans consommer le quota GitHub anonyme (60 requêtes/heure) :

```bash
export SMARTBIBLIA_GITHUB_TOKEN=ghp_…
```

## Publication

```bash
# 1. Bump : pyproject.toml [project].version ET src/smartbiblia/__init__.py
# 2. Build
uv build

# 3. Test du wheel produit
uvx --from dist/smartbiblia-0.2.0-py3-none-any.whl smartbiblia list

# 4. Publication
uv publish   # ou : python -m twine upload dist/*
```

Vérification après publication :

```bash
uvx smartbiblia@latest version
uvx smartbiblia add sudoc --dest /tmp/test-skills
```
