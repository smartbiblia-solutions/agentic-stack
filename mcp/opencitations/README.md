# OpenCitations MCP Server

An [MCP](https://modelcontextprotocol.io) server that gives AI agents access to
**[OpenCitations](https://opencitations.net/)**, the community-guided open
infrastructure for scholarly bibliographic and citation data. It wraps both
public APIs:

- **[Meta v1](https://api.opencitations.net/meta/v1)** — the bibliographic
  metadata of the documents involved in citations;
- **[Index v2](https://api.opencitations.net/index/v2)** — the citation entities
  themselves.

All data is **CC0**.

## Tools

| Tool | Purpose |
|---|---|
| `get_citation_counts` | Citations received and references made, for one or more identifiers. The cheap call — make it first. |
| `get_citations` | The works citing a given work, with self-citation flags, client-side sorting and optional metadata hydration. |
| `get_references` | The works cited by a given work, same options. |
| `lookup_metadata` | Resolve DOIs, PMIDs, PMC ids, ISBNs, OpenAlex ids or OMIDs to open bibliographic records. |
| `list_works_by_person` | The works an ORCID is attached to, as author or as editor. |

**No API key is required** — both APIs are public and anonymous. An
`OPENCITATIONS_API_KEY` only raises the quota.

The server is a single self-contained file, `mcp_server.py`, with inline
[PEP 723](https://peps.python.org/pep-0723/) dependencies (`fastmcp`, `httpx`)
that [`uv`](https://docs.astral.sh/uv/) installs automatically on first run.

---

## Three API facts that shape every call

All verified against the live service, and all worth knowing before writing a
query:

1. **There is no search.** No endpoint accepts a query string, a topic, a year
   or an author name in free text — `/meta/v1/search` is a 404. Every entry
   point is an identifier you already hold. Discover works with the OpenAlex or
   HAL servers, then explain their citations here.
2. **The list endpoints have no pagination and no limit.** `get_citations`
   downloads the whole set; `max_results` clamps client-side. One work returned
   **24 354 edges / 9.9 MB in 0.72 s** — and a more cited one answered **HTTP
   500 after 244 seconds**. The server therefore calls the count endpoint first
   and refuses to list beyond **5 000 edges**, returning `total_found` and an
   explanatory `error` rather than hanging.
3. **The API's own `filter` and `sort` are unusable at scale** — 67 to 78
   seconds server-side, and truncated invalid JSON on repeated runs. Sorting and
   self-citation filtering are done client-side, after the download.

Two further traps the tools work around: the service occasionally answers
**HTTP 200 with truncated, invalid JSON** (retried once, then surfaced in
`error`), and an **unknown identifier is HTTP 200** with a count of `0` or an
empty list — never a 404, so absence and zero look identical.

One thing OpenCitations does not have: **abstracts**. `abstract` is always
`null` in a Meta record, and is present only so results merge with the OpenAlex,
HAL, Sudoc and Primo servers on `doi`.

---

## Example prompts

Once the server is connected, these are the kinds of request it answers. Every
one of them starts from an identifier — there is no subject search here; find
the work in OpenAlex or HAL first.

- *"How many citations has 10.1108/jd-12-2013-0166 received, and how many references does it make?"* → `get_citation_counts`
- *"List the works citing it, most recent first, and drop the self-citations."* → `get_citations` with `sort` and `exclude_self_citations`
- *"Give me its reference list with titles, authors and journals."* → `get_references` with `hydrate=True`
- *"How much of this paper's citation count is authors citing themselves?"* → `get_citations`, reading `excluded_self_citations`
- *"Turn these DOIs into citable CC0 records I can put in a bibliography."* → `lookup_metadata`
- *"What does OpenCitations know about ORCID 0000-0003-0530-4305 as an author?"* → `list_works_by_person`
- *"Can I list the citations of the NumPy paper?"* → `get_citation_counts` answers first: 24 354, past the listing threshold, so the count is the answer

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
git sparse-checkout set mcp/opencitations
```

Start the server with the transport of your choice:

```bash
# stdio — the client launches and manages the process
uv run mcp/opencitations/mcp_server.py --transport stdio

# sse — persistent server, SSE endpoint
uv run mcp/opencitations/mcp_server.py \
  --host 0.0.0.0 --port 8018 --transport sse
# → endpoint: http://localhost:8018/sse

# http — persistent server, HTTP endpoint (recommended for HTTP mode)
uv run mcp/opencitations/mcp_server.py \
  --host 0.0.0.0 --port 8018 --transport http
# → endpoint: http://localhost:8018/mcp

# Add --stateless to serve HTTP without sessions: a new transport per
# request, so nothing is pinned to a replica. Needed behind a load
# balancer or with several uvicorn workers; rejected with --transport sse.
```

### 1.1 Claude Code

```bash
# stdio (no persistent server needed — Claude Code manages the process)
claude mcp add opencitations -- \
  uv run /ABS/PATH/mcp/opencitations/mcp_server.py --transport stdio

# sse (start the server first with --transport sse)
claude mcp add --transport sse opencitations http://localhost:8018/sse

# streamable-http (start the server first with --transport http)
claude mcp add --transport http opencitations http://localhost:8018/mcp
```

Check status: `claude mcp list` or `/mcp` inside a session.

### 1.2 Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
or `%AppData%\Claude\claude_desktop_config.json` (Windows).

**stdio** (Claude Desktop launches the process — no server to start):

```jsonc
{
  "mcpServers": {
    "opencitations": {
      "command": "uv",
      "args": [
        "run",
        "/ABS/PATH/mcp/opencitations/mcp_server.py",
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
    "opencitations": {
      "url": "http://localhost:8018/mcp"
    }
  }
}
```

On Windows, use escaped backslashes in the path:
`"C:\\ABS\\PATH\\mcp\\opencitations\\mcp_server.py"`.
Restart Claude Desktop after saving; tools appear under the plug icon.

### 1.3 Cursor / VS Code / other `mcp.json` clients

**stdio** (Cursor: `~/.cursor/mcp.json` — VS Code: `.vscode/mcp.json`):

```jsonc
{
  "mcpServers": {
    "opencitations": {
      "command": "uv",
      "args": [
        "run", "/ABS/PATH/mcp/opencitations/mcp_server.py",
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
    "opencitations": {
      "url": "http://localhost:8018/mcp"
    }
  }
}
```

### 1.4 Docker

```bash
docker build -t mcp-opencitations ./mcp/opencitations
docker run -p 8018:8018 mcp-opencitations

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
claude mcp add opencitations -- \
  uv run https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/opencitations/mcp_server.py \
  --transport stdio
```

### 2.2 Claude Desktop

```jsonc
{
  "mcpServers": {
    "opencitations": {
      "command": "uv",
      "args": [
        "run",
        "https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/opencitations/mcp_server.py",
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
    "opencitations": {
      "command": "uv",
      "args": [
        "run",
        "https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/opencitations/mcp_server.py",
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
| `--host` | `0.0.0.0` | Bind host (HTTP/SSE modes). Also reads `MCP_HOST`. |
| `--port` | `8018` | Bind port (HTTP/SSE modes). Also reads `MCP_PORT`. |
| `--transport` | `http` | `stdio` \| `http` \| `sse`. `streamable-http` is accepted as an alias of `http`. Also reads `MCP_TRANSPORT`. |
| `--stateless` | off | Stateless HTTP: a new transport per request, so no session is pinned to a replica — required behind a load balancer or with several uvicorn workers. Rejected with `sse`. Also reads `MCP_STATELESS`. |
| `--http-timeout` | `60.0` | Request timeout in seconds. Wide on purpose: a citation list is measured in megabytes. |
| `--max-retries` | `3` | Retry attempts on transient errors (429, 5xx) and on a truncated payload. |
| `--backoff-base` | `1.0` | Exponential backoff base in seconds. |
| `--backoff-factor` | `2.0` | Backoff multiplier. |
| `--jitter-max` | `0.25` | Max random jitter per retry in seconds. |
| `--trace` | off | Include an HTTP trace log in every tool response. |

Two environment variables, both optional:

| Variable | Default | Effect |
|---|---|---|
| `OPENCITATIONS_API_URL` | `https://api.opencitations.net` | API root; `/meta/v1` and `/index/v2` are appended |
| `OPENCITATIONS_API_KEY` | *(unset)* | Access token, sent raw in an `authorization` header only when non-empty. Never a tool argument, never logged |

See full reference: `uv run mcp_server.py --help`.

---

## Identifier reference

Everything here starts from an identifier, always prefixed with its scheme.

| Prefix | Accepted by |
|---|---|
| `doi:` | all five tools |
| `pmid:` | all five tools |
| `omid:` | all five tools — `omid:br/…` for a work, `omid:ra/…` for an agent |
| `pmcid:`, `isbn:`, `openalex:` | `lookup_metadata` only |
| `issn:` | `lookup_metadata` only — returns the **journal itself**, not its articles |
| `orcid:` | `list_works_by_person` only |

`doi:`, `pmid:` and `omid:` return identical citation sets for the same work
(verified). DOIs are case-insensitive.

An **OCI** (Open Citation Identifier) names one citation edge and is returned as
the `id` of every result of `get_citations` / `get_references`. The upstream
`/citation/{oci}` endpoint is deliberately **not** exposed: it returns exactly
what those tools already carry.

---

## Verify

```bash
# HTTP/SSE mode: check the endpoint is live (a 307/406 is normal without a handshake)
curl -i http://localhost:8018/mcp    # http
curl -i http://localhost:8018/sse    # sse

# Which mode is it in? A stateless response carries no mcp-session-id header.
curl -sD- -o /dev/null -X POST http://localhost:8018/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"c","version":"1"}}}' \
  | grep -i mcp-session-id

# stdio mode: check via the client's MCP panel
# In Claude Code: /mcp
```

---

## Troubleshooting

- **"There is no search tool"** — correct, and it is not an omission: the API has
  no search operation. Use the `openalex` or `hal` server to find works, then
  bring their DOIs here.
- **`get_citations` returns an empty list with a threshold error** — the work has
  more than 5 000 citations, which the upstream endpoint cannot serve reliably.
  `total_found` is still the true count; use it, or ask the question of a
  smaller work.
- **`total_found: 0, error: null`** — the identifier is unknown to OpenCitations,
  or the work genuinely has no recorded citations. The API answers HTTP 200 in
  both cases and does not distinguish them.
- **"Truncated or non-JSON response"** — the service cut a large payload
  mid-stream. It is retried once automatically; if it persists, the work is too
  large for the list endpoint.
- **`abstract` is null on every record** — expected. OpenCitations Meta carries
  no abstracts at all.
- **An ISSN returns dozens of identical rows** — that is the journal record
  repeated, not its articles. There is no way to enumerate a journal's works.
- **HTTP 403 with a plain-text body** — `OPENCITATIONS_API_KEY` is set to an
  invalid token. Unset it; the API works anonymously.
- **HTTP 429** — the limit is 180 requests per minute per IP. `hydrate` batches
  10 works per request, so it costs two extra calls on 20 edges, not twenty.
- **Counts look stale** — a Varnish cache sits in front; an `age` of several days
  has been observed.
- **First run is slow** — `uv` is resolving and caching dependencies; subsequent
  runs start in under a second. Set `UV_CACHE_DIR` to a writable directory if
  needed.
- **stdio mode: server not found** — ensure `uv` is on the client's `PATH`
  and check the client's MCP logs. In stdio mode, the server logs to **stderr**
  only; **stdout** is reserved for the MCP protocol.

---

## Browser demo / Hugging Face Space

[`demo/`](demo/) holds a **standalone** Gradio app that re-implements
`get_citation_counts` and `get_citations` against the same upstream and wraps
them in a browser UI, with tighter clamps (25 results, 2 000-edge listing
threshold).

See this [README file](./demo/README.md)

---

## See also

- Server index: [`mcp/README.md`](../README.md)
- Companion skill: [`skills/lookup-citations-opencitations`](../../skills/lookup-citations-opencitations) — the same source as a CLI skill, with a verified API digest in its `references/llm.md`
- OpenCitations: <https://opencitations.net>
- Meta API documentation: <https://api.opencitations.net/meta/v1>
- Index API documentation: <https://api.opencitations.net/index/v2>
- MCP protocol: <https://modelcontextprotocol.io>
