# smartbiblia

CLI d'installation des **skills** et **serveurs MCP**
[smartbiblia](https://github.com/smartbiblia-solutions/agentic-stack) dans un
workspace agent (Claude Code, Claude Desktop, Codex, OpenClaw, Hermes…).

La CLI ne contient aucune copie des skills : elle lit le catalogue sur GitHub à
chaque appel et télécharge le dossier demandé. Le package reste minuscule, et
une skill corrigée est disponible sans republier la CLI.

## Installation

Rien à installer de façon permanente — [`uvx`](https://docs.astral.sh/uv/)
exécute directement depuis PyPI :

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
(`search-records-sudoc`). C'est délibéré : un runtime d'agent apparie le nom du
dossier et le champ `name` du frontmatter, et un dossier mal nommé peut ne pas
être chargé. Les deux formes sont acceptées en argument.

## Commandes

### Lister

```bash
smartbiblia list                  # skills et serveurs MCP
smartbiblia list --kind mcp       # seulement les serveurs MCP
smartbiblia list --tag french
```

### Consulter le détail

```bash
smartbiblia info sudoc
smartbiblia info primo            # variables d'environnement, port, entrypoint
```

### Installer

```bash
smartbiblia add sudoc                     # → ./skills/search-records-sudoc/
smartbiblia add openalex --claude         # → ~/.claude/skills/search-works-openalex/
smartbiblia add sudoc --dest ./mon-projet/skills
smartbiblia add sudoc --force             # écraser sans confirmation

smartbiblia add openalex --kind mcp       # → ./mcp/openalex/
```

`--kind` n'est nécessaire que si un même nom existe des deux côtés. Sans
`--force`, une destination existante demande confirmation.

### Mettre à jour, désinstaller

```bash
smartbiblia update sudoc
smartbiblia remove sudoc
```

`update` vide le dossier avant de le réécrire : un fichier supprimé en amont
(un vieux prompt, un schéma renommé) ne survit pas à la mise à jour et ne peut
donc pas être relu par l'agent.

### Brancher un serveur MCP sur un client

```bash
smartbiblia mcp-config openalex                    # bloc stdio, script local
smartbiblia mcp-config openalex --transport http   # bloc HTTP + commande de lancement
smartbiblia mcp-config sudoc-sru --remote          # exécution depuis GitHub, sans installation
```

La sortie est un bloc `mcpServers` à coller dans la configuration du client
(Claude Desktop, Claude Code, Codex…). Les variables d'environnement attendues
sont pré-remplies à vide — la CLI n'écrit jamais de clé.

### Vérifier la version et la source

```bash
smartbiblia version               # version de la CLI et branche du catalogue lue
```

## Variables d'environnement de la CLI

| Variable | Effet |
|---|---|
| `SMARTBIBLIA_GITHUB_TOKEN` | Jeton GitHub optionnel : relève la limite de 60 requêtes/heure de l'API anonyme |
| `SMARTBIBLIA_BRANCH` | Branche source du catalogue (défaut `main`) — utile pour tester une branche |
| `SMARTBIBLIA_GITHUB_ORG` / `SMARTBIBLIA_GITHUB_REPO` | Pointer la CLI sur un fork |

## Configuration des skills installées

La plupart des skills fonctionnent sans configuration : les valeurs par défaut
sont dans `cli.py`. Quand un `scripts/.env.example` est présent, copiez-le en
`scripts/.env` et ajustez. Une clé d'API n'est requise que pour les skills qui
la déclarent — `smartbiblia info <nom>` le dit.

## Voir aussi

Cette page documente les commandes ; le contenu du catalogue est décrit ailleurs.

| Document | Contenu |
|---|---|
| [`../README.md`](../README.md) | Le dépôt, la liste des skills, les conventions communes *(en)* |
| [`../mcp/README.md`](../mcp/README.md) | Les cinq serveurs MCP, leurs outils et leurs ports *(en)* |
| `../skills/<skill>/SKILL.md` | Ce que fait une skill, quand l'utiliser, ce qu'elle renvoie |
| [`DEPLOYMENT.md`](DEPLOYMENT.md) | Publier une nouvelle version de la CLI sur PyPI |
