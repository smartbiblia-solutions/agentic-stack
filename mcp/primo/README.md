# Primo MCP Server

An [MCP](https://modelcontextprotocol.io) server that gives AI agents access to
an **Ex Libris / Clarivate Primo (or Primo VE)** discovery layer (library-catalog + discovery-index front-end for institutions running a Primo instance.
It wraps the public [`primoSearch` REST API](https://developers.exlibrisgroup.com/primo/apis/).

## Tools

| Tool | Purpose |
|---|---|
| `search_catalog` | Keyword search of an institution's catalog + Central Discovery Index, with facet filters (resource type, language, library, collection, availability, year range), sorting and paging. |
| `get_record` | Fetch a full PNX record by its `recordid` (`context` `L` = local record, `PC` = Central Discovery Index). |

The server is a single self-contained file, `mcp_server.py`, with inline
[PEP 723](https://peps.python.org/pep-0723/) dependencies (`fastmcp`, `httpx`)
that [`uv`](https://docs.astral.sh/uv/) installs automatically on first run.

---

## Prerequisites

**`uv`** (handles Python + dependencies automatically):

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**Primo API credentials.** Primo APIs are *institution-scoped*. You need:
- An **API key** created in the [Ex Libris Developer Network](https://developers.exlibrisgroup.com/)
  (bound to one institution + environment).
- The **view (`vid`)**, **tab**, **scope**, and **institution code (`inst`)**
  configured in your institution's Primo Back Office (e.g. `vid=MyUni:MyView`,
  `tab=Everything`, `scope=Everything`, `inst=MyUni`).
  Primo VE prefixes the `vid` with the institution code.
- Your **gateway region**: `na` (default), `eu`, `ap`, `ca`, or `cn`.

---

## Option 1 — Local install

### 1. Clone and run

```bash
git clone --filter=blob:none --sparse https://github.com/smartbiblia-solutions/agentic-stack.git mcp
cd mcp
git sparse-checkout set mcp/primo
```

Start the server with the transport of your choice:

```bash
# stdio — the client launches and manages the process
uv run mcp/primo/mcp_server.py \
  --vid MyUni:MyView --tab Everything --scope Everything --inst MyUni \
  --region eu --transport stdio

# sse — persistent server, SSE endpoint
uv run mcp/primo/mcp_server.py \
  --vid MyUni:MyView --tab Everything --scope Everything --inst MyUni \
  --host 0.0.0.0 --port 8013 --region eu --transport sse
# → endpoint: http://localhost:8013/sse

# http — persistent server, HTTP endpoint (recommended for HTTP mode)
uv run mcp/primo/mcp_server.py \
  --vid MyUni:MyView --tab Everything --scope Everything --inst MyUni \
  --host 0.0.0.0 --port 8013 --region eu --transport http
# → endpoint: http://localhost:8013/mcp

# Add --stateless to serve HTTP without sessions: a new transport per
# request, so nothing is pinned to a replica. Needed behind a load
# balancer or with several uvicorn workers; rejected with --transport sse.
```

### 1.1 Claude Code

```bash
# stdio (no persistent server needed — Claude Code manages the process)
claude mcp add primo -- \
  uv run /ABS/PATH/mcp/primo/mcp_server.py \
  --vid MyUni:MyView --tab Everything --scope Everything --inst MyUni \
  --region eu --transport stdio

# sse (start the server first with --transport sse)
claude mcp add --transport sse primo http://localhost:8013/sse

# streamable-http (start the server first with --transport http)
claude mcp add --transport http primo http://localhost:8013/mcp
```

Check status: `claude mcp list` or `/mcp` inside a session.

### 1.2 Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
or `%AppData%\Claude\claude_desktop_config.json` (Windows).

**stdio** (Claude Desktop launches the process — no server to start):

```jsonc
{
  "mcpServers": {
    "primo": {
      "command": "uv",
      "args": [
        "run",
        "/ABS/PATH/mcp/primo/mcp_server.py",
        "--vid", "MyUni:MyView",
        "--tab", "Everything",
        "--scope", "Everything",
        "--inst", "MyUni",
        "--region", "eu",
        "--transport", "stdio"
      ],
      "env": { "PRIMO_API_KEY": "YOUR_PRIMO_KEY" }
    }
  }
}
```

**http** (start the server first, then point Claude Desktop at it):

```jsonc
{
  "mcpServers": {
    "primo": {
      "url": "http://localhost:8013/mcp"
    }
  }
}
```

On Windows, use escaped backslashes in the path:
`"C:\\ABS\\PATH\\mcp\\primo\\mcp_server.py"`.
Restart Claude Desktop after saving; tools appear under the plug icon.

### 1.3 Cursor / VS Code / other `mcp.json` clients

**stdio** (Cursor: `~/.cursor/mcp.json` — VS Code: `.vscode/mcp.json`):

```jsonc
{
  "mcpServers": {
    "primo": {
      "command": "uv",
      "args": [
        "run", "/ABS/PATH/mcp/primo/mcp_server.py",
        "--vid", "MyUni:MyView",
        "--tab", "Everything",
        "--scope", "Everything",
        "--inst", "MyUni",
        "--region", "eu",
        "--transport", "stdio"
      ],
      "env": { "PRIMO_API_KEY": "YOUR_PRIMO_KEY" }
    }
  }
}
```

**http** (start the server first):

```jsonc
{
  "mcpServers": {
    "primo": {
      "url": "http://localhost:8013/mcp"
    }
  }
}
```

### 1.4 Docker

```bash
docker build -t mcp-primo ./mcp/primo
docker run -p 8013:8013 mcp-primo \
  --vid MyUni:MyView --tab Everything --scope Everything --inst MyUni \
  --region eu

# Or start every MCP server at once
cp mcp/.env.example mcp/.env   # fill in API_KEY, DEFAULT_VID, DEFAULT_TAB, etc.
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
claude mcp add primo -- \
  uv run https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/primo/mcp_server.py \
  --vid MyUni:MyView --tab Everything --scope Everything --inst MyUni \
  --region eu --transport stdio
```

Check status: `claude mcp list` or `/mcp` inside a session.

### 2.2 Claude Desktop

```jsonc
{
  "mcpServers": {
    "primo": {
      "command": "uv",
      "args": [
        "run",
        "https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/primo/mcp_server.py",
        "--vid", "MyUni:MyView",
        "--tab", "Everything",
        "--scope", "Everything",
        "--inst", "MyUni",
        "--region", "eu",
        "--transport", "stdio"
      ],
      "env": { "PRIMO_API_KEY": "YOUR_PRIMO_KEY" }
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
    "primo": {
      "command": "uv",
      "args": [
        "run",
        "https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/primo/mcp_server.py",
        "--vid", "MyUni:MyView",
        "--tab", "Everything",
        "--scope", "Everything",
        "--inst", "MyUni",
        "--region", "eu",
        "--transport", "stdio"
      ],
      "env": { "PRIMO_API_KEY": "YOUR_PRIMO_KEY" }
    }
  }
}
```

---

## Configuration

| Flag | Default | Notes |
|---|---|---|
| `--region` | `na` | Gateway region: `na` \| `eu` \| `ap` \| `ca` \| `cn`. |
| `--base-url` | — | Full gateway base URL (overrides `--region`). |
| `--vid` | — | Default view id, e.g. `MyUni:MyView`. Recommended. |
| `--tab` | — | Default tab name. Recommended. |
| `--scope` | — | Default scope name. Recommended. |
| `--inst` | — | Default institution code, e.g. `MyUni`. Recommended. |
| `--lang` | `en` | Default UI language. |
| `--host` | `0.0.0.0` | Bind host (HTTP/SSE modes). |
| `--port` | `8013` | Bind port (HTTP/SSE modes). |
| `--transport` | `http` | `stdio` \| `http` \| `sse`. `streamable-http` is accepted as an alias of `http`. Also reads `MCP_TRANSPORT`. |
| `--stateless` | off | Stateless HTTP: a new transport per request, so no session is pinned to a replica — required behind a load balancer or with several uvicorn workers. Rejected with `sse`. Also reads `MCP_STATELESS`. |
| `--http-timeout` | `30.0` | Request timeout in seconds. |
| `--max-retries` | `3` | Retry attempts on transient errors (429, 5xx). |
| `--backoff-base` | `1.0` | Exponential backoff base in seconds. |
| `--backoff-factor` | `2.0` | Backoff multiplier. |
| `--jitter-max` | `0.25` | Max random jitter per retry in seconds. |
| `--trace` | off | Include an HTTP trace log in every tool response. |

The API key is read from the `PRIMO_API_KEY` environment variable only — never
a flag, because `argv` is visible in process listings and shell history. It is
**required**: the server exits at startup without it.

`--vid`, `--tab`, `--scope`, and `--inst` are server defaults; both tools also
accept per-call overrides. See `uv run mcp_server.py --help` for the full reference.

---

## Verify

```bash
# HTTP/SSE mode: check the endpoint is live (a 307/406 is normal without a handshake)
curl -i http://localhost:8013/mcp    # http
curl -i http://localhost:8013/sse    # sse

# stdio mode: check via the client's MCP panel
# In Claude Code: /mcp
```

---

## Troubleshooting

- **`401`/`403` from Primo** — the API key is wrong, or the `vid`/`scope`/`tab`/`inst`
  do not belong to that key's institution/environment. These errors are not retried.
- **Empty results** — confirm that `vid`, `tab`, `scope`, and `inst` exactly match values
  configured in the Primo Back Office, and that `--region` matches your
  institution's hosting region.
- **First run is slow** — `uv` is resolving and caching dependencies; subsequent
  runs start in under a second. Set `UV_CACHE_DIR` to a writable directory if needed.
- **stdio mode: server not found** — ensure `uv` is on the client's `PATH`
  and check the client's MCP logs. In stdio mode, the server logs to **stderr**
  only; **stdout** is reserved for the MCP protocol.

---

## Browser demo / Hugging Face Space

[`demo/`](demo/) holds a **standalone** Gradio app that re-implements
`search_catalog` and `get_record` against the same upstream and wraps them in a browser
UI. 

See this [README file](./demo/README.md)

---

## See also

- Primo REST API docs: <https://developers.exlibrisgroup.com/primo/apis/>
- MCP protocol: <https://modelcontextprotocol.io>
