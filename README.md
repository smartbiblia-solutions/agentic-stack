# Agentic Stack

Reusable **skills** and **MCP servers** for AI agents working on libraries,
scholarly information, and research workflows — plus a CLI that installs them
into an agent workspace.

```text
agentic-stack/
├── skills/     # agent skills: SKILL.md + a self-contained uv CLI
├── mcp/        # MCP servers: one mcp_server.py + Dockerfile per source
└── cli/        # `smartbiblia`, the installer published on PyPI
```

Everything targets the same domain — French and international bibliographic
sources — and everything is designed to be readable by an agent first: strict
JSON on stdout, one common record schema across sources, and errors returned as
data rather than as a crash.

### Where the documentation lives

Each fact has one home; the others link to it.

| Document | Answers |
|---|---|
| this file | What is in the repo, which skill to reach for, and the conventions that hold everywhere |
| [`cli/README.md`](cli/README.md) | Every `smartbiblia` command and flag *(fr)* |
| [`cli/DEPLOYMENT.md`](cli/DEPLOYMENT.md) | Publishing a new CLI version to PyPI |
| [`mcp/README.md`](mcp/README.md) | The five servers, their tools and ports, how to run them, MCP-specific conventions |
| `mcp/<server>/README.md` | Setting that server up in Claude Code, Claude Desktop, Cursor/VS Code; full flag reference; troubleshooting |
| `skills/<skill>/SKILL.md` | What that skill does, when to use it, what it returns |
| `CLAUDE.md` | Repo guidance for coding agents |

---

## Skills

A skill is a folder with a `SKILL.md` (what it is, when to use it, what it
returns) and, usually, a `scripts/cli.py` that [`uv`](https://docs.astral.sh/uv/)
runs with no install step.

| Skill | Alias | What it does |
|---|---|---|
| [`search-works-openalex`](skills/search-works-openalex/) | `openalex` | Search OpenAlex, resolve DOIs, follow citations, classify text by topic |
| [`search-records-sudoc`](skills/search-records-sudoc/) | `sudoc` | Search the French union catalogue over SRU/UNIMARC: search, PPN/ISBN lookup, counts, index scan |
| [`search-records-hal`](skills/search-records-hal/) | `hal` | Search HAL, the French open repository, collection-first (Solr) |
| [`search-authorities-idref`](skills/search-authorities-idref/) | `search-idref` | Search the French national authority file (Solr), fetch an authority by PPN, list its linked bibliography |
| [`resolve-persons-idref`](skills/resolve-persons-idref/) | `resolve-idref` | Decide *which* IdRef authority is a given person, with a confidence score and a right to abstain |
| [`generate-search-queries`](skills/generate-search-queries/) | `generate-queries` | Turn a research question into 8–15 validated bilingual (EN/FR) queries |
| [`synthesize-literature`](skills/synthesize-literature/) | `synthesize` | Post-retrieval contract pack: PRISMA screening, summarization, appraisal, synthesis |
| [`convert-records-unimarc`](skills/convert-records-unimarc/) | `convert-unimarc` | Convert UNIMARC records between XML, JSON and ISO 2709 |
| [`write-data-management-plan`](skills/write-data-management-plan/) | `dmp` | Write a FAIR-aligned Data Management Plan |

They chain:

```text
generate-search-queries
  → search-works-openalex / search-records-hal / search-records-sudoc
      → synthesize-literature

resolve-persons-idref → search-authorities-idref → search-records-sudoc
```

Each `SKILL.md` ends with a `## Composition hints` section describing where that
skill sits relative to the others.

---

## MCP servers

The same sources, exposed over [MCP](https://modelcontextprotocol.io) for agents
that prefer a live connection to a shell tool: `openalex` (8011), `sudoc-sru`
(8012), `primo` (8013), `recherche-data-gouv` (8014),
`idref-resolver-api` (8015).

```bash
uv run mcp/openalex/mcp_server.py --transport stdio
```

Each server folder also ships a `demo/` — a **standalone** Gradio app that
re-implements two of the server's tools against the same API, wraps them in a
browser UI, and deploys as a Hugging Face Space with no extra scaffolding. It
imports nothing from the folder above it, because `demo/` is the Space root:

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
folder you ask for — it ships no copy of the skills, so a fix lands in users'
hands without republishing the package.

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

These hold across the repository. The two meta-skills that define them —
`create-agent-skill` and `create-mcp-server` — are the source of truth; this is
the short version.

**Naming.** Skills are `<verb>-<object>-<source>`. The folder name, the
frontmatter `name` and the catalogue `name` are the same string, in kebab-case.

**HTTP.** `httpx` only, never `requests`, through **one module-level pooled
client** — never `httpx.get(...)` per call, which replays the TLS handshake
every time. Stdlib `urllib.request` is reserved for places where a dependency
cannot be assumed, such as a container `HEALTHCHECK`.

**Environment variables.** A skill reads at most two: `<SOURCE>_API_URL` and
`<SOURCE>_API_KEY`. Timeouts, retry counts, backoff and jitter are **constants
in the code**, not tunables — they are properties of the connector, not of the
installation. A skill that needs neither an endpoint nor a credential ships no
`.env`, no `.env.example` and no `## Environment variables` section. MCP servers
follow the same rule for the environment, and expose their retry parameters as
CLI flags instead.

**Errors.** A retrieval CLI always exits 0. Upstream failures come back in an
`error` field alongside empty results, so an agent can read the failure instead
of parsing a stack trace.

**Output.** Strict JSON on stdout, normalized to one common record schema
(`source`, `id`, `title`, `authors`, `abstract`, `doi`, `url`, `year`, `date`,
`doc_type`, `journal`, `raw`), so results from OpenAlex, HAL and Sudoc can be
merged and deduplicated on `doi` before synthesis.

**Secrets.** Never in source, in a returned payload, or in a trace event. `.env`
files are gitignored; only `.env.example` is committed, always empty.

The conventions that apply to MCP servers alone — the FastMCP pin, the transport
flag, `--stateless` — are in [`mcp/README.md`](mcp/README.md#conventions).

---

## `references/llm.md`

Some skills wrap an API that publishes no `llm.txt`. Those carry a local
documentation snapshot at `skills/<skill-name>/references/llm.md`: a structured,
agent-friendly digest of the API documentation, bundled with the skill so it
stays useful offline and survives upstream doc churn.

---

## Todo

- Skill OpenAlex: rewrite by wrapping [openalex-cli](https://developers.openalex.org/download/openalex-cli)

---

## License

See [LICENSE](LICENSE).
