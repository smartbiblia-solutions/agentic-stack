# smartbiblia

CLI d'installation des **skills** et **serveurs MCP**
[smartbiblia](https://github.com/smartbiblia-solutions/agentic-stack) dans un
workspace agent (Claude Code, Claude Desktop, Codex, OpenClaw, Hermes, PI …).

La CLI ne contient aucune copie des skills : elle lit le catalogue sur GitHub à
chaque appel et télécharge le dossier demandé.

## Installation

[`uvx`](https://docs.astral.sh/uv/) exécute directement depuis PyPI :

```bash
uvx smartbiblia list
```

Ou en outil global :

```bash
uv tool install smartbiblia
smartbiblia list
```

## Ce que la CLI installe

| Type | Contenu | Destination par défaut |
|---|---|---|
| `skill` | `SKILL.md`, `scripts/`, `prompts/`, `schemas/`, `references/` | `./skills/<nom-canonique>/` |
| `mcp` | `mcp_server.py`, `Dockerfile`, `README.md` | `./mcp/<nom-canonique>/` |

**Alias et nom canonique.** En ligne de commande on écrit l'alias court
(`sudoc`), mais l'installation crée le dossier sous le nom canonique
(`search-records-sudoc`). Les deux formes sont acceptées en argument.

## Référence des commandes

Sept commandes, sans sous-commandes imbriquées. `<nom>` accepte toujours
l'alias court **ou** le nom canonique.

| Commande | Rôle | Sortie |
|---|---|---|
| [`list`](#list) | Lister le catalogue | Table Rich, ou JSON avec `--json` |
| [`info`](#info) | Détailler une entrée | Texte |
| [`add`](#add) | Installer | Fichiers écrits + résumé |
| [`update`](#update) | Réinstaller depuis GitHub | idem `add` |
| [`remove`](#remove) | Désinstaller | Confirmation |
| [`mcp-config`](#mcp-config) | Bloc de configuration client | JSON |
| [`version`](#version) | Version de la CLI et branche lue | Texte |

Options globales de Typer, disponibles partout : `--help`,
`--install-completion`, `--show-completion`.

### `list`

```bash
smartbiblia list [--kind skill|mcp] [--tag <tag>] [--json]
```

| Option | Raccourci | Défaut | Effet |
|---|---|---|---|
| `--kind` | `-k` | *(les deux)* | Restreint à `skill` ou `mcp`. Toute autre valeur : sortie 1 |
| `--tag` | `-t` | *(aucun)* | Ne garde que les entrées portant ce tag (correspondance exacte) |
| `--json` | — | `false` | Sortie JSON stricte sur stdout, pour lecture machine |

```bash
smartbiblia list                     # skills et serveurs MCP
smartbiblia list --kind mcp
smartbiblia list --tag french --json
```

La sortie JSON a cette forme :

```json
{
  "catalog_version": 2,
  "source": "https://github.com/smartbiblia-solutions/agentic-stack",
  "branch": "main",
  "returned": 19,
  "entries": [
    {
      "kind": "skill",
      "alias": "sudoc",
      "name": "search-records-sudoc",
      "ambiguous": false,
      "description": "…",
      "path": "skills/search-records-sudoc",
      "maturity": "stable",
      "tags": ["catalog", "french", "unimarc", "abes", "sudoc"]
    }
  ]
}
```

`returned` vaut le nombre d'entrées du catalogue au moment de l'appel — le
catalogue fait foi, ne pas lire un total figé dans cet exemple. `alias` est ce
qu'on passe en ligne de commande, `name` le dossier créé.
`ambiguous: true` signale un nom qui désigne à la fois une skill et un serveur
MCP : ces entrées-là exigent `--kind`. Les entrées MCP portent en plus
`entrypoint`, `port`, `env` et `env_required`.

### `info`

```bash
smartbiblia info <nom> [--kind skill|mcp]
```

Affiche description, nom canonique, maturité, tags, chemin dans le dépôt et la
commande d'installation. Pour un serveur MCP, ajoute l'entrypoint, le port et
les variables d'environnement.

```bash
smartbiblia info sudoc
smartbiblia info primo
smartbiblia info openalex --kind mcp
```

### `add`

```bash
smartbiblia add <nom> [--dest <path>] [--claude] [--kind skill|mcp] [--force]
```

| Option | Raccourci | Défaut | Effet |
|---|---|---|---|
| `--dest` | `-d` | `./skills` ou `./mcp` | Dossier **parent** ; le dossier de l'entrée y est créé |
| `--claude` | — | `false` | Installe dans `~/.claude/skills`. Refusé pour un serveur MCP |
| `--kind` | `-k` | *(déduit)* | Obligatoire si le nom est ambigu |
| `--force` | `-f` | `false` | Écrase sans demander confirmation |

```bash
smartbiblia add sudoc                        # → ./skills/search-records-sudoc/
smartbiblia add sudoc --claude               # → ~/.claude/skills/search-records-sudoc/
smartbiblia add sudoc --dest ./mon-projet/skills
smartbiblia add openalex --kind mcp --force  # → ./mcp/openalex/
```

Le dossier est toujours créé sous le **nom canonique**, jamais sous l'alias.
Sans `--force`, une destination existante ouvre une confirmation interactive :
un agent non interactif doit passer `--force`.

Après installation, la CLI vérifie que le `name:` du frontmatter correspond au
nom du dossier et avertit sinon, signale un `scripts/.env.example` à copier, et
rappelle les variables obligatoires d'un serveur MCP.

### `update`

```bash
smartbiblia update <nom> [--dest <path>] [--claude] [--kind skill|mcp]
```

Équivaut à `add --force`. **Le dossier est vidé avant réécriture** : un fichier
supprimé en amont (un vieux prompt, un schéma renommé) ne survit pas à la mise
à jour, de même pour une modification locale.

### `remove`

```bash
smartbiblia remove <nom> [--dest <path>] [--claude] [--kind skill|mcp] [--force]
```

Supprime le dossier. Sans `--force`, demande confirmation. Une destination
absente n'est pas une erreur : message et sortie 0.

### `mcp-config`

```bash
smartbiblia mcp-config <nom> [--transport stdio|http] [--dest <path>] [--remote]
```

| Option | Raccourci | Défaut | Effet |
|---|---|---|---|
| `--transport` | `-t` | `stdio` | `stdio` ou `http`. Toute autre valeur : sortie 1 |
| `--dest` | `-d` | `./mcp` | Dossier parent d'installation, pour calculer le chemin absolu du script |
| `--remote` | — | `false` | Pointe l'URL brute GitHub au lieu d'un chemin local, aucune installation requise |

```bash
smartbiblia mcp-config openalex                    # bloc stdio, script local
smartbiblia mcp-config openalex --transport http   # bloc HTTP + commande de lancement
smartbiblia mcp-config sudoc-sru --remote          # exécution depuis GitHub
```

`<nom>` est résolu dans la section `mcp` uniquement : pas besoin de `--kind`,
même pour `openalex` ou `hal`.

La sortie est un bloc `mcpServers` à **fusionner** dans la configuration du
client (Claude Desktop, Claude Code, Codex…) quand ce fichier contient d'autres
serveurs. Les variables d'environnement attendues sont pré-remplies à vide.

## Configuration des skills installées

La plupart des skills fonctionnent sans configuration et les valeurs par défaut
sont dans `cli.py`. Quand un `scripts/.env.example` est présent, copiez-le en
`scripts/.env` et ajustez. Une clé d'API n'est requise que pour les skills qui
la déclarent dans `smartbiblia info <nom>`.

## Voir aussi

| Document | Contenu |
|---|---|
| [`../README.md`](../README.md) | Le dépôt, la liste des skills, les conventions communes *(en)* |
| [`../mcp/README.md`](../mcp/README.md) | Les serveurs MCP avec leurs instructions d'installation *(en)* |
| [`../INSTALL_FOR_AGENTS.md`](../INSTALL_FOR_AGENTS.md) | Le runbook d'installation, pour être exécuté par un agent *(en)* |
| `../skills/<skill>/SKILL.md` | Ce que fait une skill, quand l'utiliser, ce qu'elle renvoie |
