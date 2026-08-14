# HAL MCP Server

An [MCP](https://modelcontextprotocol.io) server that gives AI agents access to
**[HAL](https://hal.science)** (Hyper Articles en Ligne), the French national
open repository, operated by the [CCSD](https://www.ccsd.cnrs.fr). It uses the
public [search API](https://api.archives-ouvertes.fr/docs/search) and the
[AuréHAL reference API](https://api.archives-ouvertes.fr/ref/).
**No API key required.**

HAL holds over three million deposits from French research institutions:
articles, conference papers, preprints, theses (`tel`), reports, book chapters,
patents, software and datasets — the majority with full text.

## Tools

| Tool | Purpose |
|---|---|
| `search_hal` | Search documents with Solr syntax, scoped to a collection or a portal, with filters, field selection, sorting, facets (including `facet.prefix` and pivot facets) and grouping. |
| `list_portals` | List HAL portals (instances) — the lowercase codes `search_hal` accepts as `portal`, filtered by substring. |
| `lookup_reference` | Resolve an AureHAL authority entry — structure, author, journal, ANR or European project, domain — into the identifier that filters a search. |

The server is a single self-contained file, `mcp_server.py`, with inline
[PEP 723](https://peps.python.org/pep-0723/) dependencies (`fastmcp`, `httpx`)
that [`uv`](https://docs.astral.sh/uv/) installs automatically on first run.

> **Scope before you search.** A global HAL query answers over three million
> documents and is almost never the useful one. Pass `collection` (uppercase
> code, e.g. `FRANCE-GRILLES`) or `portal` (lowercase code, e.g. `tel`). HAL
> tells the two apart by the case of the path segment.

> **The field suffix decides what a field can do.** `_t` is searchable but not
> returnable, `_s` is returnable, facetable and sortable but *not* searchable,
> `_id` matches identifiers only, `_tdate` cannot be faceted. Using a field
> outside its capability returns an empty result set with no error — the full
> table is in the `search_hal` docstring.

---

## Example prompts

Once the server is connected, these are the kinds of request it answers:

- *"Which HAL portal holds the theses?"* → `list_portals`
- *"Find deposits on sobriété énergétique in the thesis portal, defended between 2020 and 2024."* → `list_portals` then `search_hal`
- *"What is the HAL identifier of the CRIStAL laboratory, and what has it published since 2020?"* → `lookup_reference` then `search_hal` on `structId_i`
- *"Give me a publication-year histogram for the FRANCE-GRILLES collection — counts only, no records."* → `search_hal` with `max_results=0` and a facet
- *"Which HAL collections exist?"* → `search_hal` faceted on `collCodeName_fs`
- *"List the articles produced by ANR project ANR-19-CE23-0001."* → `lookup_reference` (project) then `search_hal`
- *"How many preprints did this laboratory deposit per year, with full text?"* → `search_hal` with filters and a pivot facet

See [`## Usage patterns`](#usage-patterns) below for the exact calls behind
several of these.

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
git clone --filter=blob:none --sparse https://github.com/smartbiblia-solutions/agentic-stack.git mcp
cd mcp
git sparse-checkout set mcp/hal
```

Start the server with the transport of your choice:

```bash
# stdio — the client launches and manages the process
uv run mcp/hal/mcp_server.py --transport stdio

# sse — persistent server, SSE endpoint
uv run mcp/hal/mcp_server.py \
  --host 0.0.0.0 --port 8016 --transport sse
# → endpoint: http://localhost:8016/sse

# http — persistent server, HTTP endpoint (recommended for HTTP mode)
uv run mcp/hal/mcp_server.py \
  --host 0.0.0.0 --port 8016 --transport http
# → endpoint: http://localhost:8016/mcp

# Add --stateless to serve HTTP without sessions: a new transport per
# request, so nothing is pinned to a replica. Needed behind a load
# balancer or with several uvicorn workers; rejected with --transport sse.
```

### 1.1 Claude Code

```bash
# stdio (no persistent server needed — Claude Code manages the process)
claude mcp add hal -- \
  uv run /ABS/PATH/mcp/hal/mcp_server.py --transport stdio

# sse (start the server first with --transport sse)
claude mcp add --transport sse hal http://localhost:8016/sse

# streamable-http (start the server first with --transport http)
claude mcp add --transport http hal http://localhost:8016/mcp
```

Check status: `claude mcp list` or `/mcp` inside a session.

### 1.2 Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
or `%AppData%\Claude\claude_desktop_config.json` (Windows).

**stdio** (Claude Desktop launches the process — no server to start):

```jsonc
{
  "mcpServers": {
    "hal": {
      "command": "uv",
      "args": [
        "run",
        "/ABS/PATH/mcp/hal/mcp_server.py",
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
    "hal": {
      "url": "http://localhost:8016/mcp"
    }
  }
}
```

On Windows, use escaped backslashes in the path:
`"C:\\ABS\\PATH\\mcp\\hal\\mcp_server.py"`.
Restart Claude Desktop after saving; tools appear under the plug icon.

### 1.3 Cursor / VS Code / other `mcp.json` clients

**stdio** (Cursor: `~/.cursor/mcp.json` — VS Code: `.vscode/mcp.json`):

```jsonc
{
  "mcpServers": {
    "hal": {
      "command": "uv",
      "args": [
        "run", "/ABS/PATH/mcp/hal/mcp_server.py",
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
    "hal": {
      "url": "http://localhost:8016/mcp"
    }
  }
}
```

### 1.4 Docker

```bash
docker build -t mcp-hal ./mcp/hal
docker run -p 8016:8016 mcp-hal

# Or start every MCP server at once
cp mcp/.env.example mcp/.env
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
claude mcp add hal -- \
  uv run https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/hal/mcp_server.py \
  --transport stdio
```

Check status: `claude mcp list` or `/mcp` inside a session.

### 2.2 Claude Desktop

```jsonc
{
  "mcpServers": {
    "hal": {
      "command": "uv",
      "args": [
        "run",
        "https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/hal/mcp_server.py",
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
    "hal": {
      "command": "uv",
      "args": [
        "run",
        "https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/hal/mcp_server.py",
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
| `--port` | `8016` | Bind port (HTTP/SSE modes). Also reads `MCP_PORT`. |
| `--transport` | `http` | `stdio` \| `http` \| `sse`. `streamable-http` is accepted as an alias of `http`. Also reads `MCP_TRANSPORT`. |
| `--stateless` | off | Stateless HTTP: a new transport per request, so no session is pinned to a replica — required behind a load balancer or with several uvicorn workers. Rejected with `sse`. Also reads `MCP_STATELESS`. |
| `--http-timeout` | `20.0` | Request timeout in seconds. |
| `--max-retries` | `3` | Retry attempts on transient errors (429, 5xx, timeout). |
| `--backoff-base` | `1.0` | Exponential backoff base in seconds. |
| `--backoff-factor` | `2.0` | Backoff multiplier. |
| `--jitter-max` | `0.25` | Max random jitter per retry in seconds. |
| `--trace` | off | Include an HTTP trace log in every tool response. |

No environment variable carries an endpoint or a credential: the CCSD API is
public and anonymous, so `mcp/.env.example` has nothing to fill in for HAL.

See full reference: `uv run mcp_server.py --help`.

---

## Verify

```bash
# HTTP/SSE mode: check the endpoint is live (a 307/406 is normal without a handshake)
curl -i http://localhost:8016/mcp    # http
curl -i http://localhost:8016/sse    # sse

# stdio mode: check via the client's MCP panel
# In Claude Code: /mcp
```

---

## Usage patterns

**Scope, then search.**

```text
list_portals(contains="thèses")                → code "tel"
search_hal(portal="tel", query="text:sobriété énergétique",
           filters=["defenseDateY_i:[2020 TO 2024]"], max_results=10)
```

**Resolve a laboratory, then filter on its identifier.** A free-text
affiliation search matches the string as each depositor typed it; an identifier
matches the entity.

```text
lookup_reference(reference="structure", query="acronym_t:CRIStAL",
                 filters=["valid_s:VALID"])    → docid 410272
search_hal(query="structId_i:410272",
           filters=["publicationDateY_i:[2020 TO 2024]", "docType_s:ART"])
```

**Counts without records.** `max_results=0` returns facets only.

```text
search_hal(collection="FRANCE-GRILLES", max_results=0,
           facet_fields=["publicationDateY_i"],
           facet_sort="index", facet_limit=-1)   → a year histogram
```

**Enumerate collections**, which have no reference endpoint:

```text
search_hal(max_results=0, facet_fields=["collCodeName_fs"], facet_limit=100)
```

---

## Troubleshooting

- **Zero results on a field that clearly exists** — almost always a suffix
  mismatch. `title_s` is not searchable (use `title_t`), `authFullName_t` is not
  returnable (use `authFullName_s`), `submittedDate_tdate` is not facetable.
  See the capability table in the `search_hal` docstring.
- **Zero results with a portal code** — portal codes are lowercase and
  collection codes uppercase; HAL distinguishes them by the case of the path
  segment, and the wrong case silently scopes to nothing.
- **`list_portals(contains=…)` finds nothing** — the substring is matched
  literally against the code and the French name, accents included: the theses
  portal is `tel` / "TEL - Thèses en ligne", so `thèses` matches while `these`
  and `thesis` do not. Call it with no filter and scan the codes when unsure.
- **A portal search returns fewer documents than expected** — a portal is a view
  over a subset of HAL, not the whole repository. Drop the scope to compare.
- **Several AuréHAL entries for one laboratory** — reference entries are
  depositor declarations, not deduplicated truth. Filter on `valid_s:VALID`,
  and expect merged or superseded forms alongside the current one.
- **First run is slow** — `uv` is resolving and caching dependencies; subsequent
  runs start in under a second.

---

## Browser demo / Hugging Face Space

[`demo/`](demo/) holds a **standalone** Gradio app that re-implements `search_hal`
and `list_portals` against the same upstream and wraps them in a browser UI. 

See this [README file](./demo/README.md)

---

## See also

- Companion skill: [`skills/search-records-hal`](../../skills/search-records-hal/SKILL.md)
- HAL search API documentation: <https://api.archives-ouvertes.fr/docs/search>
- AuréHAL reference API: <https://api.archives-ouvertes.fr/ref/>
- MCP protocol: <https://modelcontextprotocol.io>
