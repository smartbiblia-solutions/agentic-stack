# Sudoc SRU MCP Server

An [MCP](https://modelcontextprotocol.io) server that gives AI agents access to
the **[Sudoc](https://www.sudoc.abes.fr)** — the union catalogue of French higher
education and research libraries, maintained by [ABES](https://www.abes.fr).
It uses the public [SRU service](https://www.sudoc.abes.fr/cbs/sru/).
**No API key required.**

The catalogue covers books, theses, serials, manuscripts, maps, and electronic
resources, with holdings from all French universities.

## Tools

| Tool | Purpose |
|---|---|
| `search_sudoc` | Full-text and index-based search with filters on document type, language, country, and publication date. Supports all Sudoc SRU indexes (title, author, RAMEAU subject, PPN, NNT, ISBN, etc.). Handles pagination automatically. |
| `lookup_by_ppn` | Fetch a single record by its PPN (Pica Production Number — the Sudoc unique identifier). |
| `lookup_by_isbn` | Fetch records matching an ISBN-10 or ISBN-13 (hyphens optional). |
| `count_records` | Count results for a query without fetching records — useful for corpus sizing or query validation. |
| `scan_index` | Browse an index alphabetically from a given term — useful for discovering normalised forms before writing a precise query. |

The server is a single self-contained file, `server_mcp.py`, with inline
[PEP 723](https://peps.python.org/pep-0723/) dependencies (`fastmcp`, `requests`)
that [`uv`](https://docs.astral.sh/uv/) installs automatically on first run.

> **SRU encoding note.** The Sudoc SRU protocol requires `=` inside a query
> to be encoded as `%3D`. This server handles that automatically — write queries
> in natural syntax (`mti=jardins`); encoding is applied transparently.

---

## Prerequisites

**`uv`** only — no API key, no registration:

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
git clone https://github.com/smartbiblia-solutions/agentic-stack.git
cd agent-skills
```

Start the server with the transport of your choice:

```bash
# stdio — the client launches and manages the process
uv run mcp/sudoc-sru/server_mcp.py --transport stdio

# sse — persistent server, SSE endpoint
uv run mcp/sudoc-sru/server_mcp.py \
  --host 0.0.0.0 --port 8012 --transport sse
# → endpoint: http://localhost:8012/sse

# streamable-http — persistent server, HTTP endpoint (recommended for HTTP mode)
uv run mcp/sudoc-sru/server_mcp.py \
  --host 0.0.0.0 --port 8012 --transport streamable-http
# → endpoint: http://localhost:8012/mcp
```

### 1.1 Claude Code

```bash
# stdio (no persistent server needed — Claude Code manages the process)
claude mcp add sudoc -- \
  uv run /ABS/PATH/mcp/sudoc-sru/server_mcp.py --transport stdio

# sse (start the server first with --transport sse)
claude mcp add --transport sse sudoc http://localhost:8012/sse

# streamable-http (start the server first with --transport streamable-http)
claude mcp add --transport http sudoc http://localhost:8012/mcp
```

Check status: `claude mcp list` or `/mcp` inside a session.

### 1.2 Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
or `%AppData%\Claude\claude_desktop_config.json` (Windows).

**stdio** (Claude Desktop launches the process — no server to start):

```jsonc
{
  "mcpServers": {
    "sudoc": {
      "command": "uv",
      "args": [
        "run",
        "/ABS/PATH/mcp/sudoc-sru/server_mcp.py",
        "--transport", "stdio"
      ]
    }
  }
}
```

**streamable-http** (start the server first, then point Claude Desktop at it):

```jsonc
{
  "mcpServers": {
    "sudoc": {
      "url": "http://localhost:8012/mcp"
    }
  }
}
```

On Windows, use escaped backslashes in the path:
`"C:\\ABS\\PATH\\mcp\\sudoc-sru\\server_mcp.py"`.
Restart Claude Desktop after saving; tools appear under the plug icon.

### 1.3 Cursor / VS Code / other `mcp.json` clients

**stdio** (Cursor: `~/.cursor/mcp.json` — VS Code: `.vscode/mcp.json`):

```jsonc
{
  "mcpServers": {
    "sudoc": {
      "command": "uv",
      "args": [
        "run", "/ABS/PATH/mcp/sudoc-sru/server_mcp.py",
        "--transport", "stdio"
      ]
    }
  }
}
```

**streamable-http** (start the server first):

```jsonc
{
  "mcpServers": {
    "sudoc": {
      "url": "http://localhost:8012/mcp"
    }
  }
}
```

### 1.4 Docker

```bash
docker build -t mcp-sudoc-sru ./mcp/sudoc-sru
docker run -p 8012:8012 mcp-sudoc-sru

# Or start all three MCP servers at once
cp mcp/.env.example mcp/.env
docker compose -f mcp/compose.yml up --build
```

---

## Option 2 — Zero-install

`uv` can run a script directly from a URL — no clone, no local files.
Dependencies are resolved automatically on first run and cached locally.

```bash
# stdio
uv run https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/sudoc-sru/server_mcp.py \
  --transport stdio

# streamable-http
uv run https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/sudoc-sru/server_mcp.py \
  --host 0.0.0.0 --port 8012 --transport streamable-http
# → endpoint: http://localhost:8012/mcp
```

### 2.1 Claude Code

```bash
# stdio — one command, no server to start
claude mcp add sudoc -- \
  uv run https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/sudoc-sru/server_mcp.py \
  --transport stdio

# streamable-http — start the zero-install server first, then register it
claude mcp add --transport http sudoc http://localhost:8012/mcp
```

### 2.2 Claude Desktop

**stdio** — Claude Desktop fetches and launches the script directly from GitHub:

```jsonc
{
  "mcpServers": {
    "sudoc": {
      "command": "uv",
      "args": [
        "run",
        "https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/sudoc-sru/server_mcp.py",
        "--transport", "stdio"
      ]
    }
  }
}
```

### 2.3 Cursor / VS Code / other `mcp.json` clients

```jsonc
{
  "mcpServers": {
    "sudoc": {
      "command": "uv",
      "args": [
        "run",
        "https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/sudoc-sru/server_mcp.py",
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
| `--host` | `0.0.0.0` | Bind host (HTTP/SSE modes). |
| `--port` | `8012` | Bind port (HTTP/SSE modes). |
| `--transport` | `streamable-http` | `stdio` \| `sse` \| `streamable-http`. |
| `--http-timeout` | `30.0` | Request timeout in seconds. The Sudoc SRU can be slow on complex queries. |
| `--max-retries` | `3` | Retry attempts on transient errors (429, 5xx, timeout). |
| `--backoff-base` | `1.0` | Exponential backoff base in seconds. |
| `--backoff-factor` | `2.0` | Backoff multiplier. |
| `--jitter-max` | `0.25` | Max random jitter per retry in seconds. |
| `--trace` | off | Include an HTTP trace log in every tool response. |

See full reference: `uv run server_mcp.py --help`.

---

## Verify

```bash
# HTTP/SSE mode: check the endpoint is live (a 307/406 is normal without a handshake)
curl -i http://localhost:8012/mcp    # streamable-http
curl -i http://localhost:8012/sse    # sse

# stdio mode: check via the client's MCP panel
# In Claude Code: /mcp
```

---

## Troubleshooting

- **Zero results despite a valid query** — the most common cause is `=` not
  being encoded as `%3D`. When using the server's tools this is automatic;
  only relevant if you build raw SRU URLs yourself.
- **Zero results on an accented query** — Sudoc is more permissive without
  accents: `mti=memoires` matches both `mémoires` and `memoires`. Prefer the
  unaccented form for broader coverage.
- **Slow responses** — the Sudoc SRU can be sluggish during peak hours.
  Increase `--http-timeout` if you hit timeouts regularly. A 200 ms courtesy
  pause is applied between paginated requests to avoid hammering the service.
- **`scan_index` returns no terms** — verify the index key is valid (see the
  `search_sudoc` tool docstring for the full index list).
- **First run is slow** — `uv` is resolving and caching dependencies; subsequent
  runs start in under a second.

---

## See also

- Companion skill: [`skills/search-records-sudoc`](../../skills/search-records-sudoc/SKILL.md)
- Sudoc SRU documentation: <https://documentation.abes.fr/sudoc/manuels/administration/aidewebservices/index.html#SRU>
- MCP protocol: <https://modelcontextprotocol.io>
