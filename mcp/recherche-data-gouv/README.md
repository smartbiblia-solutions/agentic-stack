# Recherche Data Gouv MCP Server

An [MCP](https://modelcontextprotocol.io) server that gives AI agents access to
**[Recherche Data Gouv](https://entrepot.recherche.data.gouv.fr)** — the French
national research data repository, built on
[Dataverse](https://dataverse.org). It wraps the public read endpoints of the
[Dataverse Native API](https://guides.dataverse.org/en/latest/api/native-api.html):
Search, Metrics, and metadata blocks.

## Tools

| Tool | Purpose |
|---|---|
| `search` | Search datasets, dataverses and files, with type filters, subtree scoping, facets, sorting and pagination. |
| `metrics` | Fetch repository usage metrics (datasets, downloads, unique downloads, tree…), optionally broken down by month, past days or category. Also exposes Make Data Count metrics. |
| `metadatablocks` | List the repository's metadata blocks, or retrieve the full schema of one block. |

**No API key is required** — the server only reads public endpoints.

The server is a single self-contained file, `mcp_server.py`, with inline
[PEP 723](https://peps.python.org/pep-0723/) dependencies (`fastmcp`, `httpx`)
that [`uv`](https://docs.astral.sh/uv/) installs automatically on first run.

---

## Example prompts

Once the server is connected, these are the kinds of request it answers:

- *"Find datasets about qualité de l'air, most recent first."* → `search`
- *"Search only inside the dataverse of my institution, datasets only."* → `search` with `subtree` and a type filter
- *"Which subjects and keywords dominate the results for 'biodiversité'?"* → `search`, reading the facets
- *"Find the files named like a CSV codebook inside this dataset."* → `search` with the file type
- *"How many datasets does the repository hold, and how many were published each month in 2024?"* → `metrics`
- *"How many downloads, and how many unique downloads, over the past 30 days?"* → `metrics`
- *"Which metadata blocks exist, and what fields does the citation block define?"* → `metadatablocks`

---

## Prerequisites

**`uv`** (handles Python + dependencies automatically):

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

---

## Option 1 — Local install

### 1. Clone and run

```bash
git clone --filter=blob:none --sparse https://github.com/smartbiblia-solutions/agentic-stack.git mcp
cd mcp
git sparse-checkout set mcp/recherche-data-gouv
```

Start the server with the transport of your choice:

```bash
# stdio — the client launches and manages the process
uv run mcp/recherche-data-gouv/mcp_server.py --transport stdio

# sse — persistent server, SSE endpoint
uv run mcp/recherche-data-gouv/mcp_server.py \
  --host 0.0.0.0 --port 8014 --transport sse
# → endpoint: http://localhost:8014/sse

# http — persistent server, HTTP endpoint (recommended for HTTP mode)
uv run mcp/recherche-data-gouv/mcp_server.py \
  --host 0.0.0.0 --port 8014 --transport http
# → endpoint: http://localhost:8014/mcp

# Add --stateless to serve HTTP without sessions: a new transport per
# request, so nothing is pinned to a replica. Needed behind a load
# balancer or with several uvicorn workers; rejected with --transport sse.
```

### 1.1 Claude Code

```bash
# stdio (no persistent server needed — Claude Code manages the process)
claude mcp add recherche-data-gouv -- \
  uv run /ABS/PATH/mcp/recherche-data-gouv/mcp_server.py --transport stdio

# sse (start the server first with --transport sse)
claude mcp add --transport sse recherche-data-gouv http://localhost:8014/sse

# streamable-http (start the server first with --transport http)
claude mcp add --transport http recherche-data-gouv http://localhost:8014/mcp
```

Check status: `claude mcp list` or `/mcp` inside a session.

### 1.2 Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
or `%AppData%\Claude\claude_desktop_config.json` (Windows).

**stdio** (Claude Desktop launches the process — no server to start):

```jsonc
{
  "mcpServers": {
    "recherche-data-gouv": {
      "command": "uv",
      "args": [
        "run",
        "/ABS/PATH/mcp/recherche-data-gouv/mcp_server.py",
        "--transport", "stdio"
      ]
    }
  }
}
```

**http** (start the server first, then point Claude Desktop at it):

```jsonc
{
  "mcpServers": {
    "recherche-data-gouv": {
      "url": "http://localhost:8014/mcp"
    }
  }
}
```

On Windows, use escaped backslashes in the path:
`"C:\\ABS\\PATH\\mcp\\recherche-data-gouv\\mcp_server.py"`.
Restart Claude Desktop after saving; tools appear under the plug icon.

### 1.3 Cursor / VS Code / other `mcp.json` clients

**stdio** (Cursor: `~/.cursor/mcp.json` — VS Code: `.vscode/mcp.json`):

```jsonc
{
  "mcpServers": {
    "recherche-data-gouv": {
      "command": "uv",
      "args": [
        "run", "/ABS/PATH/mcp/recherche-data-gouv/mcp_server.py",
        "--transport", "stdio"
      ]
    }
  }
}
```

**http** (start the server first):

```jsonc
{
  "mcpServers": {
    "recherche-data-gouv": {
      "url": "http://localhost:8014/mcp"
    }
  }
}
```

### 1.4 Docker

```bash
docker build -t mcp-recherche-data-gouv ./mcp/recherche-data-gouv
docker run -p 8014:8014 mcp-recherche-data-gouv

# Or start every MCP server at once
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
claude mcp add recherche-data-gouv -- \
  uv run https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/recherche-data-gouv/mcp_server.py \
  --transport stdio
```

### 2.2 Claude Desktop

```jsonc
{
  "mcpServers": {
    "recherche-data-gouv": {
      "command": "uv",
      "args": [
        "run",
        "https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/recherche-data-gouv/mcp_server.py",
        "--transport", "stdio"
      ]
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
    "recherche-data-gouv": {
      "command": "uv",
      "args": [
        "run",
        "https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/recherche-data-gouv/mcp_server.py",
        "--transport", "stdio"
      ]
    }
  }
}
```

---

## Configuration

| Flag | Default | Notes |
|---|---|---|
| `--base-url` | `https://entrepot.recherche.data.gouv.fr/api` | Dataverse API base URL. Also reads `RECHERCHE_DATA_GOUV_API_URL`. `/api` is appended if missing. |
| `--host` | `0.0.0.0` | Bind host (HTTP/SSE modes). Also reads `MCP_HOST`. |
| `--port` | `8014` | Bind port (HTTP/SSE modes). Also reads `MCP_PORT`. |
| `--transport` | `http` | `stdio` \| `http` \| `sse`. `streamable-http` is accepted as an alias of `http`. Also reads `MCP_TRANSPORT`. |
| `--stateless` | off | Stateless HTTP: a new transport per request, so no session is pinned to a replica — required behind a load balancer or with several uvicorn workers. Rejected with `sse`. Also reads `MCP_STATELESS`. |
| `--http-timeout` | `20.0` | Request timeout in seconds. |
| `--max-retries` | `2` | Retry attempts on transient errors (429, 5xx). |
| `--backoff-base` | `1.0` | Exponential backoff base in seconds. |
| `--backoff-factor` | `2.0` | Backoff multiplier. |
| `--jitter-max` | `0.25` | Max random jitter per retry in seconds. |
| `--trace` | off | Include an HTTP trace log in every tool response. |

Because `--base-url` is configurable, this server also works against any other
Dataverse instance (Harvard Dataverse, an institutional repository…) that
exposes the same public endpoints.

See full reference: `uv run mcp_server.py --help`.

---

## Verify

```bash
# HTTP/SSE mode: check the endpoint is live (a 307/406 is normal without a handshake)
curl -i http://localhost:8014/mcp    # http
curl -i http://localhost:8014/sse    # sse

# stdio mode: check via the client's MCP panel
# In Claude Code: /mcp
```

---

## Troubleshooting

- **Empty results** — the default `q` is `*`; narrow with `q` and `types`
  (`dataset`, `dataverse`, `file`) rather than assuming the record is absent.
- **`metrics` raises on `breakdown`** — `pastDays` and `toMonth` both require a
  `value` (a number of days, or a `YYYY-MM` month).
- **Unknown category or metric** — `category` must be one of `dataverses`,
  `datasets`, `files`, `downloads`, `filedownloads`, `uniquedownloads`,
  `uniquefiledownloads`, `tree`; Make Data Count metrics are `viewsTotal`,
  `viewsUnique`, `downloadsTotal`, `downloadsUnique`, `citations`.
- **First run is slow** — `uv` is resolving and caching dependencies; subsequent
  runs start in under a second. Set `UV_CACHE_DIR` to a writable directory if
  needed.
- **stdio mode: server not found** — ensure `uv` is on the client's `PATH`
  and check the client's MCP logs. In stdio mode, the server logs to **stderr**
  only; **stdout** is reserved for the MCP protocol.

---

## Browser demo / Hugging Face Space

[`demo/`](demo/) holds a **standalone** Gradio app that re-implements **every**
tool of `mcp_server.py` — `search`, `metrics` and `metadatablocks` — against the
same upstream and wraps them in a browser UI. Same names, same response shape;
only the argument surface and the result caps may be narrower, and each
narrowing is stated in the tool docstring and in
[`demo/README.md`](./demo/README.md). Change one, change the other.

---

## See also

- Server index: [`mcp/README.md`](../README.md)
- Recherche Data Gouv: <https://entrepot.recherche.data.gouv.fr>
- Dataverse Native API: <https://guides.dataverse.org/en/latest/api/native-api.html>
- MCP protocol: <https://modelcontextprotocol.io>
