# OpenAlex MCP Server

An [MCP](https://modelcontextprotocol.io) server that gives AI agents access to
**[OpenAlex](https://openalex.org)**, the world's largest open bibliographic
database (~250 million scholarly works). It wraps the
[OpenAlex REST API](https://docs.openalex.org/api-entities/works).

## Tools

| Tool | Purpose |
|---|---|
| `search_works` | Keyword search with filters on date, open access, author (name or ORCID), and institution (name or ROR URL). Authors and institutions are resolved automatically. |
| `search_semantic` | Meaning-based search: ranks works by semantic proximity to a descriptive text or an abstract, so a paper matches without sharing the words used to ask for it. |
| `lookup_by_doi` | Resolve one or more DOIs to full OpenAlex records. Batched at 50 per request. |
| `get_citing_works` | Fetch works that cite a given OpenAlex work, sorted by citation count. |
| `classify_text` | Classify a title or abstract into academic topics and keywords. |

`search_semantic` wraps OpenAlex's vector search, and inherits three limits from
that endpoint: at most 50 results with no paging past them, `total_found` always
`null` (OpenAlex reports the result cap there, not a corpus count), and date
bounds given as years — `year_from` / `year_to`, because the
`from_publication_date` / `to_publication_date` that `search_works` accepts are
rejected. It also allows roughly one call per second. Reach for it when no
keyword names the subject cleanly; run it alongside `search_works` and merge on
`doi` when recall matters.

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
- *"What topics does this title and abstract belong to?"* → `classify_text`
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

**OpenAlex API key.** The API is free and open. An API key is recommended to avoid rate limits.
See [rate limits & authentication](https://docs.openalex.org/how-to-use-the-api/rate-limits-and-authentication).

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
It is optional for OpenAlex (it buys you the polite pool).

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

- **`403` from OpenAlex** — missing or invalid API key. Anonymous requests are
  aggressively rate-limited; always pass a key.
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

[`demo/`](demo/) holds a **standalone** Gradio app that re-implements
`search_works`, `search_semantic` and `classify_text` against the same OpenAlex
endpoints and wraps
them in a browser UI. 

See this [README file](./demo/README.md)

---

## See also

- Companion skill: [`skills/search-works-openalex`](../../skills/search-works-openalex/SKILL.md)
- OpenAlex API docs: <https://docs.openalex.org>
- MCP protocol: <https://modelcontextprotocol.io>
