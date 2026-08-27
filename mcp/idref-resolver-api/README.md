# IdRef Resolver MCP Server

An [MCP](https://modelcontextprotocol.io) server that gives AI agents access to
a deployed **idref-resolver-api** API service: given a person named in a document plus
whatever context is available, it returns the matching **IdRef PPN** (the French
national authority identifier for persons) or abstains when the evidence is too
weak.

See the [`idref-resolver-api repo`](https://github.com/smartbiblia-solutions/idref-resolver-api) for self-hosted deployment of the API.

## Tools

| Tool | Purpose |
|---|---|
| `align_person` | Align a person to an IdRef PPN from a name plus optional works, field, affiliation, role, year and free-text context. Returns a status, the accepted PPN when there is one, and the full ranked candidate list with per-signal scores and evidence. |

**The abstention is a real answer.** `best_ppn` is populated only when
`status == "accepted"`; on `ambiguous`, `low_confidence` or `not_found` the
service declined to decide. `best_candidate` is always the top of the ranking so
the decision can be inspected — never treat `best_candidate.ppn` as an accepted
identifier.

The server is a single self-contained file, `mcp_server.py`, with inline
[PEP 723](https://peps.python.org/pep-0723/) dependencies (`fastmcp`, `httpx`)
that [`uv`](https://docs.astral.sh/uv/) installs automatically on first run.

---

## Example prompts

Once the server is connected, these are the kinds of request it answers:

- *"Which IdRef PPN corresponds to the 'Marie Durand' who works on medieval history at Lyon 2?"* → `align_person`
- *"Here is an author with the title of one of her books and her field — align her against IdRef."* → `align_person` with `works` and `field`
- *"Align this list of twenty co-authors and tell me which ones you could not decide."* → one `align_person` call per name, keeping the `ambiguous` and `low_confidence` answers apart
- *"You proposed a PPN — show me the evidence and the runners-up."* → the ranked `candidates` with their per-signal scores
- *"Is this the same person as PPN 026927705, or a homonym?"* → `align_person`, then compare against `best_candidate`

**Read the status before the identifier.** A `best_ppn` exists only when
`status == "accepted"`; on `ambiguous`, `low_confidence` or `not_found` the
service declined to decide, and `best_candidate.ppn` is a lead to check, not an
answer.

---

## Prerequisites

**`uv`** (handles Python + dependencies automatically):

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**A reachable idref-resolver-api deployment**, and its API key if that
deployment enforces one. Set them in the environment:

```bash
export IDREF_API_URL=https://idref.example.org
export IDREF_API_KEY=…          # sent as X-API-Key; never a tool argument
```

`IDREF_API_KEY` is read from the environment only. It is never accepted as a
tool argument, never logged, and never echoed into a payload or a trace event.

---

## Option 1 — Local install

### 1. Clone and run

```bash
git clone --filter=blob:none --sparse https://github.com/smartbiblia-solutions/agentic-stack.git mcp
cd mcp
git sparse-checkout set mcp/idref-resolver-api
```

Start the server with the transport of your choice:

```bash
# stdio — the client launches and manages the process
uv run mcp/idref-resolver-api/mcp_server.py --transport stdio

# sse — persistent server, SSE endpoint
uv run mcp/idref-resolver-api/mcp_server.py \
  --host 0.0.0.0 --port 8015 --transport sse
# → endpoint: http://localhost:8015/sse

# http — persistent server, HTTP endpoint (recommended for HTTP mode)
uv run mcp/idref-resolver-api/mcp_server.py \
  --host 0.0.0.0 --port 8015 --transport http
# → endpoint: http://localhost:8015/mcp

# Add --stateless to serve HTTP without sessions: a new transport per
# request, so nothing is pinned to a replica. Needed behind a load
# balancer or with several uvicorn workers; rejected with --transport sse.
```

### 1.1 Claude Code

```bash
# stdio (no persistent server needed — Claude Code manages the process)
claude mcp add idref-resolver-api \
  --env IDREF_API_URL=https://idref.example.org \
  --env IDREF_API_KEY=YOUR_KEY -- \
  uv run /ABS/PATH/mcp/idref-resolver-api/mcp_server.py --transport stdio

# sse (start the server first with --transport sse)
claude mcp add --transport sse idref-resolver-api http://localhost:8015/sse

# streamable-http (start the server first with --transport http)
claude mcp add --transport http idref-resolver-api http://localhost:8015/mcp
```

Check status: `claude mcp list` or `/mcp` inside a session.

### 1.2 Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
or `%AppData%\Claude\claude_desktop_config.json` (Windows).

**stdio** (Claude Desktop launches the process — no server to start):

```jsonc
{
  "mcpServers": {
    "idref-resolver-api": {
      "command": "uv",
      "args": [
        "run",
        "/ABS/PATH/mcp/idref-resolver-api/mcp_server.py",
        "--transport", "stdio"
      ],
      "env": {
        "IDREF_API_URL": "https://idref.example.org",
        "IDREF_API_KEY": "YOUR_KEY"
      }
    }
  }
}
```

**http** (start the server first, then point Claude Desktop at it):

```jsonc
{
  "mcpServers": {
    "idref-resolver-api": {
      "url": "http://localhost:8015/mcp"
    }
  }
}
```

On Windows, use escaped backslashes in the path:
`"C:\\ABS\\PATH\\mcp\\idref-resolver-api\\mcp_server.py"`.
Restart Claude Desktop after saving; tools appear under the plug icon.

### 1.3 Cursor / VS Code / other `mcp.json` clients

**stdio** (Cursor: `~/.cursor/mcp.json` — VS Code: `.vscode/mcp.json`):

```jsonc
{
  "mcpServers": {
    "idref-resolver-api": {
      "command": "uv",
      "args": [
        "run", "/ABS/PATH/mcp/idref-resolver-api/mcp_server.py",
        "--transport", "stdio"
      ],
      "env": {
        "IDREF_API_URL": "https://idref.example.org",
        "IDREF_API_KEY": "YOUR_KEY"
      }
    }
  }
}
```

**http** (start the server first):

```jsonc
{
  "mcpServers": {
    "idref-resolver-api": {
      "url": "http://localhost:8015/mcp"
    }
  }
}
```

### 1.4 Docker

```bash
docker build -t mcp-idref-resolver-api ./mcp/idref-resolver-api
docker run -p 8015:8015 \
  -e IDREF_API_URL=https://idref.example.org \
  -e IDREF_API_KEY=YOUR_KEY \
  mcp-idref-resolver-api

# Or start every MCP server at once
cp mcp/.env.example mcp/.env   # fill in IDREF_API_URL, IDREF_API_KEY, …
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
claude mcp add idref-resolver-api \
  --env IDREF_API_URL=https://idref.example.org \
  --env IDREF_API_KEY=YOUR_KEY -- \
  uv run https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/idref-resolver-api/mcp_server.py \
  --transport stdio
```

Check status: `claude mcp list` or `/mcp` inside a session.

### 2.2 Claude Desktop

```jsonc
{
  "mcpServers": {
    "idref-resolver-api": {
      "command": "uv",
      "args": [
        "run",
        "https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/idref-resolver-api/mcp_server.py",
        "--transport", "stdio"
      ],
      "env": {
        "IDREF_API_URL": "https://idref.example.org",
        "IDREF_API_KEY": "YOUR_KEY"
      }
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
    "idref-resolver-api": {
      "command": "uv",
      "args": [
        "run",
        "https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/idref-resolver-api/mcp_server.py",
        "--transport", "stdio"
      ],
      "env": {
        "IDREF_API_URL": "https://idref.example.org",
        "IDREF_API_KEY": "YOUR_KEY"
      }
    }
  }
}
```

---

## Configuration

| Flag | Default | Notes |
|---|---|---|
| `--api-url` | `http://localhost:8000` | idref-resolver-api base URL. Also reads `IDREF_API_URL`. |
| `--host` | `0.0.0.0` | Bind host (HTTP/SSE modes). |
| `--port` | `8015` | Bind port (HTTP/SSE modes). |
| `--transport` | `http` | `stdio` \| `http` \| `sse`. `streamable-http` is accepted as an alias of `http`. Also reads `MCP_TRANSPORT`. |
| `--stateless` | off | Stateless HTTP: a new transport per request, so no session is pinned to a replica — required behind a load balancer or with several uvicorn workers. Rejected with `sse`. Also reads `MCP_STATELESS`. |
| `--http-timeout` | `180.0` | Request timeout in seconds. An alignment fans out to as many as 41 upstream ABES requests; do not lower this below the API's own budget. |
| `--max-retries` | `2` | Retry attempts on transient errors (429, 5xx). |
| `--backoff-base` | `1.0` | Exponential backoff base in seconds. |
| `--backoff-factor` | `2.0` | Backoff multiplier. |
| `--jitter-max` | `0.25` | Max random jitter per retry in seconds. |
| `--trace` | off | Include the API round trips in every tool response. No secret is ever traced. |

The credential has no flag: it is read from `IDREF_API_KEY` only, so it never
lands in a process listing or a client config's `args`. See
`uv run mcp_server.py --help` for the full reference.

---

## Verify

```bash
# HTTP/SSE mode: check the endpoint is live (a 307/406 is normal without a handshake)
curl -i http://localhost:8015/mcp    # http
curl -i http://localhost:8015/sse    # sse

# stdio mode: check via the client's MCP panel
# In Claude Code: /mcp
```

---

## Troubleshooting

- **`error: cannot reach the API`** — `IDREF_API_URL` points nowhere, or the
  service is down. The tool still returns HTTP 200 with the failure as data.
- **`API 401`** — `IDREF_API_KEY` is missing or refused by that deployment.
- **`API 400` naming a model** — `albert-bge-m3` needs an Albert key on the API
  side; `granite`, `qwen` and `minilm` need their model directory mounted there.
  `lexical-idf` always works and is the default.
- **A call takes 30-60 s** — expected. One alignment fans out to as many as 41
  upstream ABES requests. Do not lower `--http-timeout` to "fix" it.
- **`status: "ambiguous"` on a common name** — the service is working. Send more
  clues (a work title is the strongest single signal); do not lower
  `--accept-threshold` to force an answer.
- **First run is slow** — `uv` is resolving and caching dependencies; subsequent
  runs start in under a second.

---

## Browser demo / Hugging Face Space

[`demo/`](demo/) holds a **standalone** Gradio app that re-implements **every**
tool of `mcp_server.py` — `align_person` — against the same upstream and wraps
them in a browser UI. Same names, same response shape; only the argument surface
and the result caps may be narrower, and each narrowing is stated in the tool
docstring and in [`demo/README.md`](./demo/README.md). Change one, change the
other.

```bash
cd demo
uv run --with 'gradio[mcp]>=6,<7' --with httpx app.py
# http://localhost:7860
```

Launched with `mcp_server=True`, it also serves its tool at
`/gradio_api/mcp/sse`. That endpoint is **demo-grade and secondary** — the
canonical MCP endpoint is `mcp_server.py`, with the untightened result limits
and the full argument surface. Set `GRADIO_MCP_SERVER=false` wherever the real server
is already reachable, so clients cannot bind to the wrong one.

Check what it exposes:

```bash
curl -s localhost:7860/gradio_api/mcp/schema | python3 -m json.tool
```

`demo/` is a deployable Space as it stands — `demo/README.md` carries the YAML
configuration block, and `demo/requirements.txt` is what the Space installs:

```bash
git remote add space https://huggingface.co/spaces/<owner>/<space-name>
git subtree push --prefix=mcp/idref-resolver-api/demo space main
```

> **Deploy this one private, or with a key issued for it alone.** Each alignment
> costs the API tens of seconds and as many as 41 upstream ABES requests, so a
> public Space spends your budget on every visitor's click. Put `IDREF_API_URL`
> and `IDREF_API_KEY` in the Space settings — never in this repository.

---

## See also

- IdRef: <https://www.idref.fr>
- Companion agent skills: [`resolve-persons-idref`](../../skills/resolve-persons-idref/)
  (same service, CLI shape) and [`search-authorities-idref`](../../skills/search-authorities-idref/)
  (direct IdRef search, no alignment).
- MCP protocol: <https://modelcontextprotocol.io>
