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
| `search_theses` | Search theses by subject (`topic`: stemmed, over titles, résumés and keywords), establishment (name, code or PPN), status, defense dates, discipline, author, supervisor, online availability, language, thematic domain, or any organisation's PPN and role — with sorting, pagination and optional truncated résumés. |
| `resolve_establishment` | Turn a name, acronym or code into the establishment's `codeEtab`, PPN and lineage (former and later codes), with a live thesis count. |
| `get_thesis` | Fetch one record by NNT or subject number: full metadata, jury, both résumés, and the checked full-text links when the thesis is online. |
| `search_persons` | Search the person index — authors, supervisors, rapporteurs, jury members — with their roles and thesis identifiers. |
| `list_facets` | Count theses per facet value (establishments, doctoral schools, thematic domains, disciplines, languages, status) for a query, one facet at a time, filterable by text. |
| `search_by_organisme` | Profile an organisation: how many theses it took part in per role — awarding establishment, cotutelle, research partner, doctoral school — split by status, plus a few samples. |

**No API key is required** — the service is public and anonymous.

The server is one Python file, `mcp_server.py`, with inline
[PEP 723](https://peps.python.org/pep-0723/) dependencies (`fastmcp`, `httpx`)
that [`uv`](https://docs.astral.sh/uv/) installs automatically on first run,
plus the establishment referential `etablissements.json` next to it (fetched
from this repository when the file is absent, e.g. with `uv run <url>`).

---

## API facts that shape every call

All verified against the live service:

1. **A bare query is stemmed; a field query is not.** `q=éolien` and
   `q=éoliens` both return ~1 360 records, over titles, résumés and keywords;
   `titrePrincipal:(éolien)` returns 62 and `titrePrincipal:(eolien)` 6. Hence
   `topic`, compiled as a bare query. Words are ANDed by default.
2. **`filtres` does not filter.** Every constraint is compiled into one Lucene
   `q` and ANDed.
3. **Search hits carry no résumé and no `accessible` flag.** Both live on the
   record endpoint only — hence `get_thesis` and `with_abstracts`.
4. **Nothing maps an establishment name to its code.** `codeEtab:(UCA)` simply
   returns 0. `etablissements.json` (231 ABES codes, PPNs, aliases,
   predecessor/successor codes; built by `scripts/build_etablissements.py`
   from the IdRef/ABES alignment of
   [humatheque-idref-qualinka-api](https://github.com/gegedenice/humatheque-idref-qualinka-api))
   resolves names, and flags ambiguous ones: "UCA" is both Université Côte
   d'Azur and Université Clermont Auvergne.
5. **An unknown identifier answers HTTP 400** on `/theses/these/{id}`.
6. **Full text:** `/api/v1/document/{nnt}` redirects to where the text lives
   (HAL, an institutional repository), `/api/v1/abes/{nnt}` serves the PDF
   ABES holds; both answer 403 for a thesis that is not online.

Responses are deliberately small — no upstream `raw` record, no empty field,
eight keywords per hit, résumés truncated to 600 characters on search. A ten-hit
search is ~7 kB instead of ~37 kB, a record ~6 kB instead of ~15 kB, and an
organisation profile ~4 kB instead of ~1 MB.

Note for maintainers: FastMCP drops every docstring section that opens with a
`Header:` line from the tool description an agent sees (only `Args:` survives,
as parameter descriptions). Write guidance as plain paragraphs.

---

## Example prompts

Once the server is connected, these are the kinds of request it answers:

- *"Find theses on énergies marines renouvelables defended at Université Côte d'Azur since 2020."* → `search_theses(topic=…, establishment="Université Côte d'Azur", status="soutenue", date_from="2020")`
- *"Which theses on that subject are currently in preparation?"* → `search_theses` with `status="enCours"`
- *"Give me the full record and both résumés for NNT 2021COAZ4028."* → `get_thesis`
- *"Which code did Université de Nice use, and what came after it?"* → `resolve_establishment`
- *"Find the last ten defended theses with their full text online, and include the abstracts."* → `search_theses(online=True, sort="dateDesc", with_abstracts=True)`
- *"Which theses did Thierry Turletti supervise?"* → `search_theses(director=…)`, or `search_persons` for every role
- *"Which establishments host theses on biofouling?"* → `list_facets(topic="biofouling", facet="Établissements")`
- *"How many theses was Université Côte d'Azur involved in, and as what?"* → `search_by_organisme`

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
| `--etablissements` | — | Path or URL of the establishment referential. Default: `etablissements.json` next to the script, else the copy on this repository's `main` branch. Also reads `THESES_FR_ETABLISSEMENTS`. |
| `--trace` | off | Include an HTTP trace log in every tool response. |

There is no credential: theses.fr is a single public host.

See full reference: `uv run mcp_server.py --help`.

---

## Query syntax

`q` is Lucene over an Elasticsearch index. `topic` and the dedicated
`search_theses` arguments cover most needs; the raw `query` argument (ANDed with
the rest) covers the others. Fields verified to work:

| Field | Example | Argument |
|---|---|---|
| *(bare words)* | `énergies marines renouvelables` — stemmed, accent-folded, all descriptive fields, ANDed | `topic` |
| `titrePrincipal` | `titrePrincipal:(informatique)` — **not** stemmed | — |
| `resumes.fr` / `resumes.en` | `resumes.fr:(microbiote)` | — |
| `sujetsLibelle` / `sujetsRameauLibelle` | `sujetsRameauLibelle:("Apprentissage automatique")` | — |
| `codeEtab` | `codeEtab:(COAZ)` — case-sensitive | `establishment` |
| `etabSoutenancePpn` / `etabSoutenanceN` | `etabSoutenancePpn:(241035694)` | `establishment` (PPN, or a name the referential lacks) |
| `etabsCotutellePpn`, `partenairesRecherchePpn`, `ecolesDoctoralesPpn` | `partenairesRecherchePpn:(241035694)` | `organisation_ppn` + `organisation_role` |
| `discipline` | `discipline:(informatique)` | `discipline` |
| `oaiSetNames` | `oaiSetNames:("Informatique")` — controlled label, **quoted** | `domain` |
| `auteursNP` / `directeursNP` | `directeursNP:(Thierry Turletti)` — name tokens, **never quoted**; accents not folded for names stored decomposed (see below) | `author` / `director` |
| `auteursPpn` / `directeursPpn` | `directeursPpn:(087273934)` — exact, no homonyms | `author` / `director` given a PPN |
| `rapporteursNP`, `membresJuryNP`, `presidentJuryNP` and their `*Ppn` | `membresJuryNP:(Bouveyron)` | — |
| `langues` | `langues:(en)` | `language` |
| `accessible` | `accessible:(oui)` — online full text; defended theses only | `online` |
| `status` | `status:(soutenue)` or `status:(enCours)` | `status` |
| `dateSoutenance` | `dateSoutenance:([2020-01-01 TO *])` — ISO bounds | `date_from` / `date_to` (`YYYY` accepted) |
| `datePremiereInscriptionDoctorat`, `dateInsertionDansES` | `dateInsertionDansES:([2026-08-01 TO *])` — index date, for incremental sync | — |
| `nnt`, `numSujet` | `numSujet:(s312947)` | — |

`(field1 OR field2):(x)` is not valid — upstream answers 400; write
`field1:(x) OR field2:(x)`. Lucene specials (`+ - ! { } [ ] ^ ~ ? : \ /`) are
escaped in `topic`; quotes (phrase), parentheses (grouping) and `*`
(truncation) are kept.

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

- **Zero results** — `hint` says why: an establishment filter that matches
  nothing at all (wrong code or name — call `resolve_establishment`), field
  queries that are not stemmed (move the words to `topic`), or simply no match,
  which is a valid answer.
- **`error: "… is ambiguous"`** — the establishment name or acronym names
  several establishments; pass one of the codes listed.
- **Theses of a merged university are missing** — the code changed. Set
  `include_predecessors=True`, or see the lineage with `resolve_establishment`.
- **`abstract_fr` / `abstract_en` absent** — the record has none; `missing`
  says so. On search hits they only appear with `with_abstracts=True`.
- **`get_thesis` says "No thesis with identifier …"** — theses.fr answers 400
  for an unknown identifier. A thesis in preparation is usually reached by its
  subject number (`s312947`).
- **HTTP 400 on a search** — malformed Lucene in `query`; the error message
  says what to check.
- **A person filter misses some of their theses** — some records store names
  with decomposed accents (Unicode NFD), which the index does not fold:
  `directeursNP:(Frédéric Precioso)` typed normally finds 14 of his 23 theses.
  `author=` / `director=` search every accented word in both forms, and accept
  an IdRef PPN (`director="087273934"`), the exact way to query a person. An
  unaccented spelling ("Frederic") cannot reach those records: write the
  accents, or use the PPN.
- **A filter seems ignored** — `filtres` is inert upstream; only `q` filters.
- **`resolve_establishment` says the referential is unavailable** — the
  server found no `etablissements.json` and could not fetch the remote copy;
  pass `--etablissements`. Name filters still work, more loosely, through
  `etabSoutenanceN`.
- **First run is slow** — `uv` is resolving and caching dependencies; subsequent
  runs start in under a second. Set `UV_CACHE_DIR` to a writable directory if
  needed.
- **stdio mode: server not found** — ensure `uv` is on the client's `PATH`
  and check the client's MCP logs. In stdio mode, the server logs to **stderr**
  only; **stdout** is reserved for the MCP protocol.

---

## Browser demo / Hugging Face Space

[`demo/`](demo/) holds a Gradio app, deployable as a Hugging Face Space, that
serves the same six tools over MCP (`/gradio_api/mcp/`) and wraps them in a
browser UI. The Space is pushed from `demo/` alone, so the app cannot import
`mcp_server.py`: it imports `demo/theses_core.py`, **generated** from it. The
Modal copy, [`modal/`](modal/), is generated the same way. After any change to
`mcp_server.py`:

```bash
python3 mcp/theses-fr/scripts/sync_copies.py   # rewrites modal/ and demo/theses_core.py
```

---

## See also

- Server index: [`mcp/README.md`](../README.md)
- Companion skill: [`skills/search-theses-fr`](../../skills/search-theses-fr) — the same source as a CLI skill
- theses.fr: <https://theses.fr>
- API documentation: <https://documentation.abes.fr/aidethesesfr/index.html#PrincipeAPI>
- OpenAPI: <https://theses.fr/api/v1/recherche/openapi.yaml>
- MCP protocol: <https://modelcontextprotocol.io>
