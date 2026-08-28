# OpenAlex MCP Server

An [MCP](https://modelcontextprotocol.io) server that gives AI agents access to
**[OpenAlex](https://openalex.org)**, the world's largest open bibliographic
database (~250 million scholarly works). It wraps the
[OpenAlex REST API](https://docs.openalex.org/api-entities/works).

## Tools

| Tool | Purpose | Cost |
|---|---|---|
| `search_works` | Keyword search, with filters on date, open access, author (name or ORCID), institution (name or ROR) and the four levels of the topic hierarchy. Authors and institutions are resolved automatically. | $0.001 |
| `search_semantic` | Meaning-based search: ranks works by semantic proximity to a descriptive text or an abstract, so a paper matches without sharing the words used to ask for it. | $0.001 |
| `lookup_by_doi` | Resolve one or more DOIs to full OpenAlex records. Batched at 50 per request. | free |
| `get_citing_works` | Fetch works that cite a given OpenAlex work, sorted by citation count. | $0.0001 |
| `classify_text` | Place a text in the topic hierarchy — topics, subfields, fields, domains, each with its id and the filter key to reuse it. | $0.001 |
| `resolve_entity` | Turn a name — institution, author, source, funder, publisher, topic — into its OpenAlex id, its external id (ROR, ORCID) **and the filter key that id belongs in**. | free |
| `browse_topics` | Walk the aboutness hierarchy: 4 domains → 26 fields → 252 subfields → 4,516 topics. | $0.0001 |
| `group_by` | Count along any dimension without retrieving a single record — "how many", "top N", trends, in one request. | $0.0001 |
| `translate_query` | Convert between OpenAlex query language (OQL), its JSON form (OQO) and a REST URL, and validate a query before paying to run it. | $0.0001 |

Two of them make the other seven accurate and are free, so reach for them first:
`resolve_entity` before filtering on any name, `browse_topics` (or
`classify_text`) before filtering on a subject. Both hand back the **filter key**
along with the id, which is how you find out that "institution is X" belongs in
`authorships.institutions.lineage` — the filter that also catches the labs,
hospitals and UMRs attached to that institution — rather than in
`authorships.institutions.id`, which does not. `search_works` filters on lineage
by default for that reason; pass `institution_scope="exact"` to narrow.

`search_semantic` wraps OpenAlex's vector search, and inherits three limits from
that endpoint: at most 50 results with no paging past them, `total_found` always
`null` (OpenAlex reports the result cap there, not a corpus count), and date
bounds given as years — `year_from` / `year_to`, because the
`from_publication_date` / `to_publication_date` that `search_works` accepts are
rejected. It also allows roughly one call per second. Reach for it when no
keyword names the subject cleanly; run it alongside `search_works` and merge on
`doi` when recall matters.

`classify_text` replaces the `/text` endpoint OpenAlex retired: one semantic
search, then the topics of the nearest works aggregated by relevance and rolled
up the hierarchy. It costs a tenth of what `/text` did and, unlike `/text`,
returns identifiers you can feed straight back into `search_works`.

The server is a single self-contained file, `mcp_server.py`, with inline
[PEP 723](https://peps.python.org/pep-0723/) dependencies (`fastmcp`, `httpx`)
that [`uv`](https://docs.astral.sh/uv/) installs automatically on first run.

---

## Example prompts

Once the server is connected, these are the kinds of request it answers:

- *"Find open-access papers on graph neural networks for molecular property prediction published since 2022."* → `search_works`
- *"List what Silvio Peroni (ORCID 0000-0003-0530-4305) published between 2020 and 2024."* → `search_works`, which resolves the author itself
- *"Here is an abstract — find papers about the same idea, even if they use none of these words."* → `search_semantic`
- *"Resolve these twelve DOIs and tell me which ones are open access."* → `lookup_by_doi`, batched at 50 per request
- *"Who cites 10.1038/s41586-020-2649-2? Most-cited citing papers first."* → `get_citing_works`
- *"What is this abstract about, in OpenAlex's own vocabulary?"* → `classify_text`
- *"What is the OpenAlex id for the Université de Strasbourg?"* → `resolve_entity`
- *"Which subfields sit under the Computer Science field?"* → `browse_topics`
- *"How many works has Sorbonne Université published per year since 2015, and what share is open access?"* → `group_by`, twice, with no record downloaded
- *"Is `works where institution is Sorbonne Université and publication year > 2020` a valid query, and what REST URL does it compile to?"* → `translate_query`
- *"Search both ways for 'urban heat island mitigation' and merge the results."* → `search_works` + `search_semantic`, deduplicated on `doi`

---

## Prerequisites

**`uv`** (handles Python + dependencies automatically):

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**OpenAlex API key — optional, and worth ten times the anonymous budget.**
Since February 2026 OpenAlex meters usage as a **daily spend** and ignores
`mailto`; the polite pool no longer exists. Anonymous access gets **$0.10/day**,
a free key **$1.00/day**, both resetting at midnight UTC. Single-entity lookups
and autocomplete are free at either level, which is why `lookup_by_doi` and
`resolve_entity` cost nothing to lean on. Every billable tool response carries
`cost_usd`, so an agent can see what it just spent. Get a key at
[openalex.org/pricing](https://openalex.org/pricing); see
[authentication](https://help.openalex.org/api/authentication/).

---

## Option 1 — Local install

### 1. Clone and run

```bash
git clone --filter=blob:none --sparse https://github.com/smartbiblia-solutions/agentic-stack.git mcp
cd mcp
git sparse-checkout set mcp/openalex
```

Start the server with the transport of your choice:

```bash
# stdio — the client launches and manages the process
uv run mcp/openalex/mcp_server.py \
  --transport stdio

# sse — persistent server, SSE endpoint
uv run mcp/openalex/mcp_server.py \
  --host 0.0.0.0 --port 8011 --transport sse
# → endpoint: http://localhost:8011/sse

# http — persistent server, HTTP endpoint (recommended for HTTP mode)
uv run mcp/openalex/mcp_server.py \
  --host 0.0.0.0 --port 8011 --transport http
# → endpoint: http://localhost:8011/mcp

# Add --stateless to serve HTTP without sessions: a new transport per
# request, so nothing is pinned to a replica. Needed behind a load
# balancer or with several uvicorn workers; rejected with --transport sse.
```

### 1.1 Claude Code

```bash
# stdio (no persistent server needed — Claude Code manages the process)
claude mcp add openalex -- \
  uv run /ABS/PATH/mcp/openalex/mcp_server.py \
  --transport stdio

# sse (start the server first with --transport sse)
claude mcp add --transport sse openalex http://localhost:8011/sse

# streamable-http (start the server first with --transport http)
claude mcp add --transport http openalex http://localhost:8011/mcp
```

Check status: `claude mcp list` or `/mcp` inside a session.

### 1.2 Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
or `%AppData%\Claude\claude_desktop_config.json` (Windows).

**stdio** (Claude Desktop launches the process — no server to start):

```jsonc
{
  "mcpServers": {
    "openalex": {
      "command": "uv",
      "args": [
        "run",
        "/ABS/PATH/mcp/openalex/mcp_server.py",
        "--transport", "stdio"
      ],
      "env": { "OPENALEX_API_KEY": "YOUR_OPENALEX_KEY" }
    }
  }
}
```

**http** (start the server first, then point Claude Desktop at it):

```jsonc
{
  "mcpServers": {
    "openalex": {
      "url": "http://localhost:8011/mcp"
    }
  }
}
```

On Windows, use escaped backslashes in the path:
`"C:\\ABS\\PATH\\mcp\\openalex\\mcp_server.py"`.
Restart Claude Desktop after saving; tools appear under the plug icon.

### 1.3 Cursor / VS Code / other `mcp.json` clients

**stdio** (Cursor: `~/.cursor/mcp.json` — VS Code: `.vscode/mcp.json`):

```jsonc
{
  "mcpServers": {
    "openalex": {
      "command": "uv",
      "args": [
        "run", "/ABS/PATH/mcp/openalex/mcp_server.py",
        "--transport", "stdio"
      ],
      "env": { "OPENALEX_API_KEY": "YOUR_OPENALEX_KEY" }
    }
  }
}
```

**http** (start the server first):

```jsonc
{
  "mcpServers": {
    "openalex": {
      "url": "http://localhost:8011/mcp"
    }
  }
}
```

### 1.4 Docker

```bash
docker build -t mcp-openalex ./mcp/openalex
docker run -p 8011:8011 -e OPENALEX_API_KEY=YOUR_OPENALEX_KEY mcp-openalex

# Or start every MCP server at once
cp mcp/.env.example mcp/.env   # fill in OPENALEX_API_KEY
docker compose -f mcp/compose.yml up --build
```

---

## Option 2 — Zero-install (stdio only)

`uv` can run a script directly from a URL — no clone, no local files.
This works as a true single-step zero-install **only with `stdio`**: the client
config embeds the `uv run <url>` command and the client manages the process itself.

For `sse` or `http`, `uv run <url>` still starts a local server on
localhost — you would then need to register the endpoint separately, which is
equivalent to Option 1 HTTP mode (just without cloning first).

### 2.1 Claude Code

```bash
claude mcp add openalex -- \
  uv run https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/openalex/mcp_server.py \
  --transport stdio
```

Check status: `claude mcp list` or `/mcp` inside a session.

### 2.2 Claude Desktop

```jsonc
{
  "mcpServers": {
    "openalex": {
      "command": "uv",
      "args": [
        "run",
        "https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/openalex/mcp_server.py",
        "--transport", "stdio"
      ],
      "env": { "OPENALEX_API_KEY": "YOUR_OPENALEX_KEY" }
    }
  }
}
```

Restart Claude Desktop after saving; tools appear under the plug icon.

### 2.3 Cursor / VS Code / other `mcp.json` clients

(Cursor: `~/.cursor/mcp.json` — VS Code: `.vscode/mcp.json`)

```jsonc
{
  "mcpServers": {
    "openalex": {
      "command": "uv",
      "args": [
        "run",
        "https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/openalex/mcp_server.py",
        "--transport", "stdio"
      ],
      "env": { "OPENALEX_API_KEY": "YOUR_OPENALEX_KEY" }
    }
  }
}
```

---

## Configuration

| Flag | Default | Notes |
|---|---|---|
| `--host` | `0.0.0.0` | Bind host (HTTP/SSE modes). |
| `--port` | `8011` | Bind port (HTTP/SSE modes). |
| `--transport` | `http` | `stdio` \| `http` \| `sse`. `streamable-http` is accepted as an alias of `http`. Also reads `MCP_TRANSPORT`. |
| `--stateless` | off | Stateless HTTP: a new transport per request, so no session is pinned to a replica — required behind a load balancer or with several uvicorn workers. Rejected with `sse`. Also reads `MCP_STATELESS`. |
| `--http-timeout` | `15.0` | Request timeout in seconds. |
| `--max-retries` | `2` | Retry attempts on transient errors (429, 5xx). |
| `--backoff-base` | `1.0` | Exponential backoff base in seconds. |
| `--backoff-factor` | `2.0` | Backoff multiplier. |
| `--jitter-max` | `0.25` | Max random jitter per retry in seconds. |
| `--trace` | off | Include an HTTP trace log in every tool response. |

The API key is read from the `OPENALEX_API_KEY` environment variable only —
never a flag, because `argv` is visible in process listings and shell history.
It is optional for OpenAlex, and raises the daily budget from $0.10 to $1.00.

See full reference: `uv run mcp_server.py --help`.

---

## Verify

```bash
# HTTP/SSE mode: check the endpoint is live (a 307/406 is normal without a handshake)
curl -i http://localhost:8011/mcp    # http
curl -i http://localhost:8011/sse    # sse

# stdio mode: check via the client's MCP panel
# In Claude Code: /mcp
```

---

## Troubleshooting

- **"Insufficient budget … Resets at midnight UTC"** — the daily spend is
  spent. Set `OPENALEX_API_KEY` to raise it from $0.10 to $1.00, or wait for the
  reset. The free tools (`lookup_by_doi`, `resolve_entity`) keep working.
- **`429` from OpenAlex** — too many requests in too short a window, or an
  exhausted budget surfacing as a rate limit. The server already retries twice
  with backoff; space out bulk work, and prefer `group_by` over walking pages.
- **`403` from OpenAlex** — invalid API key.
- **Empty results** — OpenAlex does not index all publications. Try a broader
  query or verify coverage on [openalex.org](https://openalex.org) directly.
- **Author/institution not resolved** — automatic resolution does a best-effort
  search; ambiguous names may return the wrong entity. Pass an ORCID or ROR URL
  for exact matching.
- **First run is slow** — `uv` is resolving and caching dependencies; subsequent
  runs start in under a second. Set `UV_CACHE_DIR` to a writable directory if
  needed.
- **stdio mode: server not found** — ensure `uv` is on the client's `PATH`
  and check the client's MCP logs. In stdio mode, the server logs to **stderr**
  only; **stdout** is reserved for the MCP protocol.

---

## Browser demo / Hugging Face Space

[`demo/`](demo/) holds a **standalone** Gradio app that re-implements **every**
tool of `mcp_server.py` — the nine listed above — against the same upstream and
wraps them in a browser UI. Same names, same response shape; only the argument surface
and the result caps may be narrower, and each narrowing is stated in the tool
docstring and in [`demo/README.md`](./demo/README.md). Change one, change the
other.

---

## Serverless deployment (Modal)

[`modal/`](modal/) holds a **standalone duplicate** of this server, deployed as
an autoscaling HTTPS endpoint — no container to run, no host to rent. It serves
the same nine tools under the same names, with the transport built stateless
because Modal replaces containers between requests.

```bash
uvx modal serve  mcp/openalex/modal/mcp_server_stateless.py   # ephemeral, reloads on save
uvx modal deploy mcp/openalex/modal/mcp_server_stateless.py   # persistent
uvx modal run    mcp/openalex/modal/mcp_server_stateless.py::test_tool   # list served tools
```

The MCP endpoint is the printed URL with `/mcp/` appended. See
[`modal/README.md`](./modal/README.md).

---

## Keeping the copies in step

The skill CLI, this server, `modal/` and `demo/` implement the same nine
capabilities and import nothing from each other. Change one, change all four in
the same commit; [`PARITY.md`](./PARITY.md) is the checklist, and says what each
copy is allowed to differ on.

---

## See also

- Companion skill: [`skills/search-works-openalex`](../../skills/search-works-openalex/SKILL.md)
- Parity checklist across the four copies: [`PARITY.md`](./PARITY.md)
- OpenAlex API docs: <https://docs.openalex.org>
- MCP protocol: <https://modelcontextprotocol.io>
