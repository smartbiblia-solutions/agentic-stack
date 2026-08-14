# Install smartbiblia skills and MCP servers (agent runbook)

You are a coding agent. Follow this runbook top to bottom. Every command is
non-interactive unless marked otherwise. Stop and report at the first step whose
verification fails.

This file is the only install procedure in the repository. Per-skill and
per-server documentation (`skills/<name>/SKILL.md`, `mcp/<name>/README.md`)
describes *what a component does*, not how to obtain it.

---

## What you are installing

| Kind | What it is | Where it lands | How the agent uses it |
|---|---|---|---|
| **Skill** | A folder: `SKILL.md`, sometimes `prompts/`, `schemas/`, `scripts/cli.py` | your agent's skills directory | The runtime loads `SKILL.md`; where there is a `scripts/cli.py`, the agent shells out to `uv run …/cli.py` |
| **MCP server** | A single `mcp_server.py` | anywhere; referenced from your MCP client config | The client speaks MCP over stdio or HTTP |

Nothing is `pip install`ed. Every script carries [PEP 723](https://peps.python.org/pep-0723/)
inline dependencies and runs under `uv` with no install step and no virtualenv
of your own.

`cli/` holds `smartbiblia`, the installer published on PyPI. You run it with
`uvx`; you do not clone this repository to use it.

---

## Prerequisites

```bash
uv --version    # required — https://docs.astral.sh/uv/
```

If `uv` is missing:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Nothing else is required. Do **not** create a virtualenv, do **not** `pip install`
anything, do **not** install Python separately — `uv` provisions interpreters and
dependencies per script.

Docker is needed only for the multi-server compose deployment (step 6, optional).

---

## 1. Read the catalogue

The catalogue is the authoritative inventory. It is fetched from `main` on every
CLI invocation, so it is current even for an older installed CLI. Read it
directly rather than trusting any list embedded in documentation — including the
snapshot in this file:

```bash
curl -sL https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/cli/src/smartbiblia/catalog.toml
```

Or, equivalently and already structured:

```bash
uvx smartbiblia list --json
```

```json
{
  "catalog_version": 2,
  "source": "https://github.com/smartbiblia-solutions/agentic-stack",
  "branch": "main",
  "returned": 15,
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

`alias` is what you pass on the command line, `name` is the folder that gets
created, and `ambiguous: true` marks a name that needs `--kind` (see below).
MCP entries carry `entrypoint`, `port`, `env` and `env_required` as well.

`--json` also accepts `--kind` and `--tag`:

```bash
uvx smartbiblia list --kind mcp --json
uvx smartbiblia list --tag french --json
```

**Never parse the default output of `list`** — it is a Rich table that wraps
unreadably below ~120 columns. Use `--json`, or the raw TOML above.

### Snapshot (non-authoritative — the catalogue on `main` wins)

Skills:

| Alias | Canonical name | Maturity |
|---|---|---|
| `openalex` | `search-works-openalex` | stable |
| `sudoc` | `search-records-sudoc` | stable |
| `hal` | `search-records-hal` | stable |
| `search-idref` | `search-authorities-idref` | experimental |
| `resolve-idref` | `resolve-persons-idref` | beta |
| `generate-queries` | `generate-search-queries` | stable |
| `synthesize` | `synthesize-literature` | stable |
| `convert-unimarc` | `convert-records-unimarc` | stable |
| `dmp` | `write-data-management-plan` | experimental |

MCP servers:

| Alias | Port | Keys required |
|---|---|---|
| `openalex` | 8011 | none (`OPENALEX_API_KEY` recommended) |
| `sudoc-sru` | 8012 | none |
| `primo` | 8013 | `PRIMO_API_KEY`, `PRIMO_VID`, `PRIMO_TAB`, `PRIMO_SCOPE` |
| `recherche-data-gouv` | 8014 | none |
| `idref-resolver-api` | 8015 | `IDREF_API_URL` |
| `hal` | 8016 | none |

> **Ambiguous aliases.** `openalex` and `hal` name both a skill and an MCP
> server. Every command below that takes one of them **must** carry
> `--kind skill` or `--kind mcp`, or the CLI exits 1 with
> `'openalex' existe en plusieurs types`.

---

## 2. Choose skill or MCP server

Install a **skill** when your runtime loads skill folders (Claude Code, Claude
Desktop, OpenClaw, Codex with a skills directory) and you are happy shelling out
to a CLI. It is the lighter path: no process to keep alive, no client config.

Install an **MCP server** when your client speaks MCP and you want typed tools
in the model's tool list rather than a shell command.

Both exist for OpenAlex, Sudoc and HAL, over the same upstream APIs. Installing
both is redundant — pick one per source.

---

## 3. Install a skill

Pick the destination your runtime actually reads:

```bash
# Claude Code / Claude Desktop, user-wide
uvx smartbiblia add sudoc --claude --force

# a project-local skills directory
uvx smartbiblia add sudoc --dest .claude/skills --force

# the default: ./skills/ in the current directory
uvx smartbiblia add sudoc --force
```

`--force` overwrites without prompting — always pass it, otherwise the CLI
blocks on an interactive confirmation when the folder already exists.

For an ambiguous alias, pin the kind:

```bash
uvx smartbiblia add openalex --kind skill --claude --force
```

The skill is installed under its **canonical** name, never the alias
(`search-records-sudoc/`, not `sudoc/`). This is deliberate: agent runtimes
match the folder name against the `name:` field in the `SKILL.md` frontmatter,
and a mismatch can silently fail to load.

A skill is installed when `SKILL.md` is there. That is the whole check: the
runtime loads the folder, and there is nothing else to prove. Many skills
contain only `SKILL.md` and some Markdown — a folder without `scripts/` is a
supported shape, not a broken install.

---

## 4. Install an MCP server

Three deployment shapes. Pick one.

### 4a. stdio, no local install (simplest)

The client runs the server straight from GitHub. Nothing is written to disk;
`uv` caches the script and its dependencies.

```bash
uvx smartbiblia mcp-config sudoc-sru --transport stdio --remote
```

This prints a ready-to-paste block:

```json
{
  "mcpServers": {
    "smartbiblia-sudoc-sru": {
      "command": "uv",
      "args": [
        "run",
        "https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/sudoc-sru/mcp_server.py",
        "--transport",
        "stdio"
      ]
    }
  }
}
```

Merge it into your client's config file — **merge, never overwrite**: that file
holds other servers. Typical locations:

| Client | Config file |
|---|---|
| Claude Code | `.mcp.json` (project) or `~/.claude.json` (user) |
| Claude Desktop (macOS) | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Claude Desktop (Windows) | `%APPDATA%\Claude\claude_desktop_config.json` |
| Cursor / VS Code | `.cursor/mcp.json` / `.vscode/mcp.json` |

Claude Code can also do the merge for you:

```bash
claude mcp add smartbiblia-sudoc-sru -- \
  uv run https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/sudoc-sru/mcp_server.py --transport stdio
```

### 4b. stdio, installed locally

Pin the version by downloading the server, so an upstream change on `main`
cannot alter behaviour under you:

```bash
uvx smartbiblia add sudoc-sru --kind mcp --force      # → ./mcp/sudoc-sru/
uvx smartbiblia mcp-config sudoc-sru --transport stdio
```

The second command emits the same block with an absolute local path.

### 4c. HTTP (long-running server)

```bash
uvx smartbiblia add openalex --kind mcp --force
uv run mcp/openalex/mcp_server.py --transport http --host 127.0.0.1 --port 8011
```

then

```bash
uvx smartbiblia mcp-config openalex --transport http
```

which prints `{"type": "http", "url": "http://127.0.0.1:8011/mcp"}`.

`--transport` accepts `stdio | http | sse`; `streamable-http` is an alias of
`http`. All of `--transport`, `--host` and `--port` also read `MCP_TRANSPORT`,
`MCP_HOST`, `MCP_PORT`, so a container configures without changing the
entrypoint.

Add `--stateless` (or `MCP_STATELESS=true`) when running several replicas behind
a load balancer: it creates a new transport per request so no session is pinned
to a replica. It is rejected with `--transport sse`. A stateless response carries
no `mcp-session-id` header — that is the quickest way to check which mode a
running server is in.

Timeouts, retries and backoff are **CLI flags** (`--help` lists them), never
environment variables.

---

## 5. Supply credentials

Read `env` and `env_required` for the server from the catalogue, or:

```bash
uvx smartbiblia info primo
```

Servers with an empty `env_required` work with no configuration at all — Sudoc,
HAL and Recherche Data Gouv are fully public. `OPENALEX_API_KEY` is optional but
recommended (it buys a higher rate limit).

Two servers cannot start usefully without values you must obtain from the user
or the environment — **do not invent them, and do not guess an institutional
endpoint**:

- `primo`: `PRIMO_API_KEY`, `PRIMO_VID`, `PRIMO_TAB`, `PRIMO_SCOPE` — from the
  institution's Ex Libris developer account.
- `idref-resolver-api`: `IDREF_API_URL` — the base URL of a deployed resolver.

Pass them in the `env` object of the client config block (`mcp-config` already
emits the keys with empty values for you to fill), or export them in the
server's environment.

Never write a secret into a file that is committed, into a tool response, or
into a trace event. Only empty `.env.example` files belong in git.

### Verify

Restart the MCP client, then confirm the tools are listed. From a shell, for an
HTTP server:

```bash
curl -s -X POST http://127.0.0.1:8011/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | head -c 400
```

A JSON-RPC result containing a `tools` array means the server is up. MCP tool
failures follow the same errors-as-data rule as the skills: a dict with
`source`, `command` and `error` rather than an exception. `--trace` adds a
`trace` array, with secrets redacted.

---

## 6. Optional: all servers at once, in Docker

Only when the user asked for a deployment rather than a local client:

```bash
cp mcp/.env.example mcp/.env      # then fill in the keys you have
docker compose -f mcp/compose.yml up --build
```

Ports: openalex 8011, sudoc-sru 8012, primo 8013, recherche-data-gouv 8014,
idref-resolver-api 8015, hal 8016. Endpoints at `http://localhost:<port>/mcp`.

---

## Lifecycle

```bash
uvx smartbiblia list --kind skill --tag french --json
uvx smartbiblia info sudoc
uvx smartbiblia update sudoc --claude          # reinstall from main
uvx smartbiblia remove sudoc --claude --force
```

`update` **empties the folder before rewriting it** — any local edit inside an
installed skill is lost. Keep modifications outside the installed tree.

To test a branch before it reaches `main`:

```bash
SMARTBIBLIA_BRANCH=my-branch uvx smartbiblia list
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `'openalex' existe en plusieurs types` | alias names both a skill and a server | add `--kind skill` or `--kind mcp` |
| `'x' est introuvable dans le catalogue` | wrong alias | `uvx smartbiblia list --json` |
| `list` output is a wall of `…` | Rich table wrapping in a narrow terminal | use `--json` |
| `Impossible de charger le catalogue` | no network, or GitHub is down | retry; check `SMARTBIBLIA_BRANCH` is a real branch |
| `FileNotFoundError` during `add` | `path` in the catalogue points at a renamed folder | report it — it is a repository bug, not a local one |
| The command hangs | interactive overwrite/delete confirmation | pass `--force` |
| Skill installed but the runtime ignores it | folder name ≠ `name:` in the frontmatter | never rename the installed folder; reinstall with `add --force` |
| Exit 0 but `"error"` is non-null | upstream API failed | this is by design — retry later, do not reinstall |
| MCP server starts, client shows no tools | client not restarted, or config merged into the wrong file | restart; re-check the config path in the table above |
| `ValueError` on start | `--stateless` combined with `--transport sse` | drop one of the two |
| `uv run` fails on a raw GitHub URL | old `uv` | upgrade: `uv self update` |

---

## Report success

When done, report to the user, concisely:

1. what was installed (canonical names, kind) and to which directory or config file;
2. the verification command you ran and whether `error` was `null`;
3. any `env_required` variable still unset, and what it blocks;
4. anything you deliberately skipped.

If a step failed, report the exact command, its exit code and its first lines of
output. Do not retry an install more than twice, and never work around a failure
by editing files inside an installed skill.
