# Agentic Stack

Reusable **skills** and **MCP servers** for AI agents working on libraries,
scholarly information, and research workflows, plus a CLI that installs them
into an agent workspace.

```text
agentic-stack/
├── skills/     # agent skills: SKILL.md + a self-contained uv CLI
├── mcp/        # MCP servers: one mcp_server.py + Dockerfile per source
└── cli/        # `smartbiblia`, the installer published on PyPI
```

Everything here targets the same domain (French and international
bibliographic sources) and everything is designed to be readable by an agent
first: strict JSON on stdout, one response envelope whatever the source, and
errors returned as data rather than as a crash.

> **You are an agent asked to install any of this?** Go to
> [`INSTALL_FOR_AGENTS.md`](INSTALL_FOR_AGENTS.md) and follow it top to bottom.

### Where the documentation lives

Each fact has one home; the others link to it.

| Document | Answers |
|---|---|
| this file | What is in the repo, how its pieces fit together, and the conventions that hold everywhere |
| [`INSTALL_FOR_AGENTS.md`](INSTALL_FOR_AGENTS.md) | The install runbook, written for an agent to execute top to bottom |
| [`cli/README.md`](cli/README.md) | Every `smartbiblia` command and flag *(fr)* |
| [`mcp/README.md`](mcp/README.md) | The servers, their tools and ports, how to run them, MCP-specific conventions |
| `mcp/<server>/README.md` | Setting that server up in Claude Code, Claude Desktop, Cursor/VS Code; full flag reference; troubleshooting |
| `skills/<skill>/SKILL.md` | What that skill does, when to use it, what it returns |

---

## Skills

A skill is a folder an agent runtime loads: a `SKILL.md` saying what it is, when
to use it and what it returns, plus (only when something must actually run) a
`scripts/cli.py` that [`uv`](https://docs.astral.sh/uv/) executes with no install
step.

The CLI catalogue is the inventory:

```bash
uvx smartbiblia list --kind skill          # what exists, with maturity and tags
uvx smartbiblia list --tag french --json   # filtered, machine-readable
uvx smartbiblia info synthesize            # one skill, in detail
```

They come in four shapes, and the shape tells you where the work happens:

| Shape | The work is done by | Example of what it looks like |
|---|---|---|
| **Retrieval** | `scripts/cli.py` — it calls the API and normalizes the answer | `search-*`, `lookup-*`, `resolve-*`, `convert-*` |
| **Contract pack** | the *agent*, against `prompts/*.md` and `schemas/*.schema.json` it reads directly; the script only validates what the agent produced | `generate-search-queries`, `synthesize-literature` |
| **Markdown-only** | the agent, against `SKILL.md` alone; no script, nothing to install | `write-data-management-plan` |
| **Orchestrator** | the agent, delegating each stage to the skill that owns it | `orchestrate-literature-review` |

They chain, by role rather than by name:

```text
question → search strategy → retrieval (one or more sources)
         → deduplication → screening → summarization → appraisal → synthesis

identity question → authority resolution → authority record → holdings
```

Every `SKILL.md` ends with a `## Composition hints` section placing that skill in
those chains, and its frontmatter carries a `selection` block (`use_when`,
`avoid_when`, `prefer_over`, `combine_with`).

A full review runs the first chain end to end. `orchestrate-literature-review`
owns it: it opens one dated run folder, hands the path to each stage, and every
artefact — queries, records, screening decisions, synthesis — is written into
that one folder rather than loose in the workspace. Each stage also runs
standalone; the orchestrator is a convenience, not a dependency.

---

## MCP servers

The same sources, exposed over [MCP](https://modelcontextprotocol.io) for agents
that prefer a live connection to a shell tool. Which servers exist, and on which
default port, comes from the same catalogue:

```bash
uvx smartbiblia list --kind mcp --json          # names, ports, env, env_required
uv run mcp/openalex/mcp_server.py --transport stdio   # run one from a clone
```

Each server folder also ships a `demo/`: a **standalone** Gradio app that
re-implements the server's tools against the same API, wraps them in a
browser UI, and deploys as a Hugging Face Space with no extra scaffolding:

```bash
cd mcp/openalex/demo
uv run --with 'gradio[mcp]>=6,<7' --with httpx app.py
```

[`mcp/README.md`](mcp/README.md) has the tool inventory, the Docker recipe and
the MCP conventions; each server's own README has per-client setup and the full
flag reference.

---

## Installing into a workspace

The [`smartbiblia`](cli/) CLI reads the catalogue
(`cli/src/smartbiblia/catalog.toml`) from GitHub on every call and downloads the
folder you ask for.

```bash
uvx smartbiblia list                      # browse the catalogue
uvx smartbiblia add sudoc                 # → ./skills/search-records-sudoc/
uvx smartbiblia add sudoc --claude        # → ~/.claude/skills/
uvx smartbiblia add openalex --kind mcp   # → ./mcp/openalex/
```

Short aliases are accepted on the command line, but the installed folder always
carries the canonical name: an agent runtime matches the folder name against the
frontmatter `name`, and a mismatched folder may silently fail to load.

Every command and flag: [`cli/README.md`](cli/README.md).

---

## Conventions

These hold across the repository.

**Naming.** Skills are `<verb>-<object>-<source>`. The folder name, the
frontmatter `name` and the catalogue `name` are the same string, in kebab-case.

**HTTP.** `httpx` only, never `requests`, through **one module-level pooled
client**; never `httpx.get(...)` per call, which replays the TLS handshake
every time. Stdlib `urllib.request` is reserved for places where a dependency
cannot be assumed, such as a container `HEALTHCHECK`.

**Environment variables.** A skill reads at most two: `<SOURCE>_API_URL` and
`<SOURCE>_API_KEY`. Timeouts, retry counts, backoff and jitter are never
tunables but **constants in the code** (they are properties of the connector,
not of the installation). A skill that needs neither an endpoint nor a credential
ships no `.env`, no `.env.example` and no `## Environment variables` section. MCP servers
follow the same rule for the environment, and expose their retry parameters as
CLI flags instead.

**Errors.** A retrieval CLI always exits 0. Upstream failures come back in an
`error` field alongside empty results, so an agent can read the failure instead
of parsing a stack trace.

**Output.** Strict JSON on stdout, in one envelope everywhere:

```jsonc
{"total_found": 1523, "returned": 15, "results": [ /* … */ ], "error": null}
```

`results` is always an array, `error` is always present and `null` on success,
and `total_found` is `null` — not `0` — when the source cannot count. That much
is universal: it is what lets an agent consume a connector it has never seen.

The **record** inside `results` is the source's own data model, anchored only by
`source`, `id`, `url` and a human-readable label. Field names align *within a
family of sources over the same kind of data*: the bibliographic connectors
share `title`, `authors`, `abstract`, `doi`, `year`, `date`, `doc_type`,
`journal` and `raw`, which is what lets OpenAlex, HAL and Sudoc results merge and
deduplicate on `doi` before synthesis. That is a convention of *that family*, not
a schema every skill must fill — a statistical or geospatial connector defines
its own record and is no less compliant.

**Secrets.** Never in source, in a returned payload, or in a trace event. `.env`
files are gitignored; only `.env.example` is committed, always empty.

The conventions that apply to MCP servers alone (the FastMCP pin, the transport
flag, `--stateless`) are in [`mcp/README.md`](mcp/README.md#conventions).

---

## `references/llm.md`

Some skills wrap an API that publishes no `llm.txt`. Those carry a local
documentation snapshot at `skills/<skill-name>/references/llm.md`: a structured,
agent-friendly digest of the API documentation, bundled with the skill so it
stays useful offline and survives upstream doc churn.

---

## Todo

- Skill OpenAlex: rewrite from new OpenAlex documentation and OQL search query.

---

## License

See [LICENSE](LICENSE).
