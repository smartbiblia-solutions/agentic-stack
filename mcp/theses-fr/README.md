# theses.fr MCP Server

An [MCP](https://modelcontextprotocol.io) server that gives AI agents access to
**[theses.fr](https://theses.fr)**, the French national register of doctoral
theses, run by [ABES](https://abes.fr). It wraps the public
[theses.fr search API](https://www.data.gouv.fr/dataservices/api-interroger-les-donnees-de-theses-fr):
defended theses, theses in preparation, the people attached to them, and the
facet values a query accepts.

## Tools

| Tool | Purpose |
|---|---|
| `search_theses` | Search theses by establishment code, discipline, thematic domain, author or supervisor name, language, online availability, date range and status — with sorting, pagination and optional résumé hydration. |
| `get_thesis` | Fetch one record with its bilingual résumés, by NNT or by subject number. |
| `search_persons` | Search the person index — authors, supervisors, rapporteurs, jury members — with their roles and thesis identifiers. |
| `list_facets` | List the facet values a query accepts (establishments, doctoral schools, thematic domains, disciplines, languages…), with counts. |
| `search_by_organisme` | List an organisation's theses grouped by the role it played — awarding establishment, cotutelle, research partner, doctoral school. |

**No API key is required** — the service is public and anonymous.

The server is a single self-contained file, `mcp_server.py`, with inline
[PEP 723](https://peps.python.org/pep-0723/) dependencies (`fastmcp`, `httpx`)
that [`uv`](https://docs.astral.sh/uv/) installs automatically on first run.

---

## Three API facts that shape every call

All verified against the live service, and all worth knowing before writing a
query:

1. **`filtres` does not filter.** The documented `filtres` parameter leaves the
   hit count untouched, whatever syntax it is given. Every constraint the tools
   accept is therefore compiled into one Lucene `q` and ANDed together.
2. **Search hits carry no résumé.** `/recherche/` returns a lightweight
   projection; the abstract lives on the record endpoint only. Hence
   `search_theses(hydrate=True)` — one extra request per hit, capped at 50 —
   and `get_thesis`. Everything else the record adds beyond the résumés
   (keywords, jury, doctoral schools, partners) already rides along on the hit.
3. **`codeEtab` is the establishment filter, not `nnt`.** `establishment="COAZ"`
   compiles to `codeEtab:(COAZ)` — 2 706 theses. The older `nnt:*COAZ*` idiom
   returns 1 568: exactly the defended subset, because a thesis in preparation
   has no NNT.

Two further traps the tools work around: an unknown identifier answers HTTP 200
with an **empty body** rather than 404 (surfaced as `error: "No record found…"`),
and `titreEN` is not reliably an English title, so it is returned as `title_en`
and never promoted to `title`.

---

## Example prompts

Once the server is connected, these are the kinds of request it answers:

- *"Find theses on énergies marines renouvelables defended at Université Côte d'Azur since 2020."* → `search_theses`
- *"Which theses on that subject are currently in preparation?"* → `search_theses` with `status="enCours"`
- *"Give me the full record and both résumés for NNT 2021COAZ4028."* → `get_thesis`
- *"Find the last ten defended theses with their full text online, and include the abstracts."* → `search_theses` with `accessible="oui"` and `hydrate=True`
- *"Which theses did Frédéric Precioso supervise, and who sat on their juries?"* → `search_persons`
- *"What doctoral schools and disciplines appear for this query, with counts?"* → `list_facets`
- *"List everything Université de Lille was involved in, split by the role it played — awarding institution, cotutelle, doctoral school."* → `search_by_organisme`

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
git sparse-checkout set mcp/theses-fr
```

Start the server with the transport of your choice:

```bash
# stdio — the client launches and manages the process
uv run mcp/theses-fr/mcp_server.py --transport stdio

# sse — persistent server, SSE endpoint
uv run mcp/theses-fr/mcp_server.py \
  --host 0.0.0.0 --port 8017 --transport sse
# → endpoint: http://localhost:8017/sse

# http — persistent server, HTTP endpoint (recommended for HTTP mode)
uv run mcp/theses-fr/mcp_server.py \
  --host 0.0.0.0 --port 8017 --transport http
# → endpoint: http://localhost:8017/mcp

# Add --stateless to serve HTTP without sessions: a new transport per
# request, so nothing is pinned to a replica. Needed behind a load
# balancer or with several uvicorn workers; rejected with --transport sse.
```

### 1.1 Claude Code

```bash
# stdio (no persistent server needed — Claude Code manages the process)
claude mcp add theses-fr -- \
  uv run /ABS/PATH/mcp/theses-fr/mcp_server.py --transport stdio

# sse (start the server first with --transport sse)
claude mcp add --transport sse theses-fr http://localhost:8017/sse

# streamable-http (start the server first with --transport http)
claude mcp add --transport http theses-fr http://localhost:8017/mcp
```

Check status: `claude mcp list` or `/mcp` inside a session.

### 1.2 Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
or `%AppData%\Claude\claude_desktop_config.json` (Windows).

**stdio** (Claude Desktop launches the process — no server to start):

```jsonc
{
  "mcpServers": {
    "theses-fr": {
      "command": "uv",
      "args": [
        "run",
        "/ABS/PATH/mcp/theses-fr/mcp_server.py",
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
    "theses-fr": {
      "url": "http://localhost:8017/mcp"
    }
  }
}
```

On Windows, use escaped backslashes in the path:
`"C:\\ABS\\PATH\\mcp\\theses-fr\\mcp_server.py"`.
Restart Claude Desktop after saving; tools appear under the plug icon.

### 1.3 Cursor / VS Code / other `mcp.json` clients

**stdio** (Cursor: `~/.cursor/mcp.json` — VS Code: `.vscode/mcp.json`):

```jsonc
{
  "mcpServers": {
    "theses-fr": {
      "command": "uv",
      "args": [
        "run", "/ABS/PATH/mcp/theses-fr/mcp_server.py",
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
    "theses-fr": {
      "url": "http://localhost:8017/mcp"
    }
  }
}
```

### 1.4 Docker

```bash
docker build -t mcp-theses-fr ./mcp/theses-fr
docker run -p 8017:8017 mcp-theses-fr

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
claude mcp add theses-fr -- \
  uv run https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/theses-fr/mcp_server.py \
  --transport stdio
```

### 2.2 Claude Desktop

```jsonc
{
  "mcpServers": {
    "theses-fr": {
      "command": "uv",
      "args": [
        "run",
        "https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/theses-fr/mcp_server.py",
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
    "theses-fr": {
      "command": "uv",
      "args": [
        "run",
        "https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/theses-fr/mcp_server.py",
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
| `--port` | `8017` | Bind port (HTTP/SSE modes). Also reads `MCP_PORT`. |
| `--transport` | `http` | `stdio` \| `http` \| `sse`. `streamable-http` is accepted as an alias of `http`. Also reads `MCP_TRANSPORT`. |
| `--stateless` | off | Stateless HTTP: a new transport per request, so no session is pinned to a replica — required behind a load balancer or with several uvicorn workers. Rejected with `sse`. Also reads `MCP_STATELESS`. |
| `--http-timeout` | `20.0` | Request timeout in seconds. |
| `--max-retries` | `3` | Retry attempts on transient errors (429, 5xx). |
| `--backoff-base` | `1.0` | Exponential backoff base in seconds. |
| `--backoff-factor` | `2.0` | Backoff multiplier. |
| `--jitter-max` | `0.25` | Max random jitter per retry in seconds. |
| `--trace` | off | Include an HTTP trace log in every tool response. |

There is no endpoint or credential variable: theses.fr is a single public host.

See full reference: `uv run mcp_server.py --help`.

---

## Query syntax

`q` is Lucene over an Elasticsearch index. Most constraints have a dedicated
`search_theses` argument; the raw `query` covers the rest. Fields verified to
work:

| Field | Example | Argument |
|---|---|---|
| `titrePrincipal` | `titrePrincipal:(informatique)` | — (`titreEN` is returned but not searchable) |
| `resumes.fr` / `resumes.en` | `resumes.fr:(microbiote)` | — (bare `resumes.*` is a **400**) |
| `codeEtab` | `codeEtab:(COAZ)` — case-sensitive | `establishment` |
| `discipline` | `discipline:(informatique)` — free text, ~4000 values | `discipline` |
| `oaiSetNames` | `oaiSetNames:("Informatique")` — the 98 controlled *Domaines thématiques* labels, **quoted** | `domain` |
| `auteursNP` / `directeursNP` | `directeursNP:(Frédéric Precioso)` — name tokens, **never quoted** | `author` / `director` |
| `rapporteursNP`, `membresJuryNP`, `presidentJuryNP` | `membresJuryNP:(Bouveyron)` | — |
| `auteursPpn`, `directeursPpn`, `ecolesDoctoralesPpn`, `partenairesRecherchePpn` | `directeursPpn:(060582952)` — exact, no homonyms | — |
| `sujetsLibelle` / `sujetsRameauLibelle` | `sujetsRameauLibelle:("Apprentissage automatique")` | — |
| `langues` | `langues:(en)` | `language` |
| `accessible` | `accessible:(oui)` — online full text; defended theses only | `accessible` |
| `status` | `status:(soutenue)` (or `enCours`) | `status` |
| `dateSoutenance` | `dateSoutenance:([2024-01-01 TO 2025-12-31])` — ISO bounds, though results render `DD/MM/YYYY` | `date_from` / `date_to` |
| `datePremiereInscriptionDoctorat` | `datePremiereInscriptionDoctorat:([2023-01-01 TO *])` | — |
| `dateInsertionDansES` | `dateInsertionDansES:([2026-08-01 TO *])` — index date, for incremental sync | — |
| `numSujet` | `numSujet:(s68236)` | — |

Quoting cuts both ways. A controlled label must be quoted — unquoted
`Aix-Marseille` or an unquoted `oaiSetNames` value is tokenized and matches far
more, or nothing at all. A person name must **not** be:
`directeursNP:("Frédéric Precioso")` returns 0, the unquoted form returns 14.
Nested paths do not work (`auteurs.nom:Dupont` returns zero) — the flat `*NP`
and `*Ppn` fields are how a person is queried here. Use `search_persons` to turn
a name into a PPN, and `list_facets` to learn the exact label a field query
needs.

---

## Verify

```bash
# HTTP/SSE mode: check the endpoint is live (a 307/406 is normal without a handshake)
curl -i http://localhost:8017/mcp    # http
curl -i http://localhost:8017/sse    # sse

# Which mode is it in? A stateless response carries no mcp-session-id header.
curl -sD- -o /dev/null -X POST http://localhost:8017/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"c","version":"1"}}}' \
  | grep -i mcp-session-id

# stdio mode: check via the client's MCP panel
# In Claude Code: /mcp
```

---

## Troubleshooting

- **`abstract` is null on every hit** — expected: search hits carry no résumé.
  Pass `hydrate=True`, or call `get_thesis`. Many records have no résumé at all,
  and stay null after hydration.
- **`hydrate_error` on one record** — that single detail fetch failed; the other
  hits are unaffected.
- **Zero results from a query you believe correct** — malformed Lucene comes back
  as 200 with zero hits rather than 400. Re-check quoting and accents before
  concluding the corpus is empty, and use `list_facets` for exact labels.
- **`get_thesis` says "No record found (empty response)"** — theses.fr answers
  200 with an empty body for an unknown identifier. Check the NNT, or use the
  subject number (`s68236`) for a thesis still in preparation.
- **A filter seems ignored** — `filtres` is inert upstream; only `q` filters.
- **An establishment returns only defended theses** — the query is using
  `nnt:*CODE*`. Use `establishment=` (i.e. `codeEtab`), which also finds theses
  in preparation. `codeEtab` is case-sensitive; the tool upper-cases for you.
- **A person-name query returns zero** — it is quoted. `directeursNP` holds name
  tokens in no fixed order, so the phrase never matches; drop the quotes, or use
  `author=` / `director=`.
- **`accessible="oui"` with `status="enCours"` returns zero** — always, by
  construction: only a defended thesis has an online full text.
- **`search_by_organisme` returns far fewer records than `total_found`** —
  upstream caps each role bucket at 100. `totals` still reports the true counts;
  use `search_theses(establishment=…)` with paging for an exhaustive listing.
- **`search_by_organisme` says the PPN is probably a person** — it is an IdRef
  PPN, but of a person, not an organisation. Take an organisation PPN from a
  record's `institution_ppn`.
- **First run is slow** — `uv` is resolving and caching dependencies; subsequent
  runs start in under a second. Set `UV_CACHE_DIR` to a writable directory if
  needed.
- **stdio mode: server not found** — ensure `uv` is on the client's `PATH`
  and check the client's MCP logs. In stdio mode, the server logs to **stderr**
  only; **stdout** is reserved for the MCP protocol.

---

## Browser demo / Hugging Face Space

[`demo/`](demo/) holds a **standalone** Gradio app that re-implements
`search_theses` and `get_thesis` against the same upstream and wraps them in a
browser UI.

See this [README file](./demo/README.md)

---

## See also

- Server index: [`mcp/README.md`](../README.md)
- Companion skill: [`skills/search-theses-fr`](../../skills/search-theses-fr) — the same source as a CLI skill
- theses.fr: <https://theses.fr>
- API documentation: <https://documentation.abes.fr/aidethesespro/index.html#PrincipeAPI>
- OpenAPI: <https://theses.fr/api/v1/recherche/openapi.yaml>
- MCP protocol: <https://modelcontextprotocol.io>
