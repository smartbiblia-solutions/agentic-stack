---
title: HAL MCP Demo
emoji: 🔎
colorFrom: indigo
colorTo: yellow
sdk: gradio
sdk_version: 6.22.0
app_file: app.py
pinned: false
short_description: Search HAL, the French national open repository.
---

# HAL MCP demo

A standalone Gradio demo of the
[`hal`](https://github.com/smartbiblia-solutions/agentic-stack/tree/main/mcp/hal)
MCP server: search HAL (Hyper Articles en Ligne), the French national open
repository operated by the CCSD, list its portals, and resolve its AuréHAL
authority files.

The **canonical MCP endpoint is `mcp_server.py`** one folder up, with the
complete field reference, pivot facets, grouping, paging and no tightened result
limit. This app serves the same three tools — `search_hal`, `list_portals`,
`lookup_reference` — at `/gradio_api/mcp/`; that endpoint is demo-grade and
secondary. Set `GRADIO_MCP_SERVER=false` wherever the real server is
reachable, so clients cannot bind to the wrong one.

## It is standalone

`app.py` imports nothing from the parent folder, this folder is the Space root,
so `mcp_server.py` does not exist here. The three tools are a **hand-kept copy**
of the canonical ones — same names, same argument names and types, same record
shape including `error` — so the surfaces match tool for tool. **Change one,
change the other.**

The demo signature is a subset, not a variant: `search_hal` keeps `query`,
`collection`, `portal`, `filters`, `fields`, `max_results`, `facet_fields`,
`facet_limit` and `sort`, and drops the arguments a browser demo has no use for
(`start`, `facet_sort`, `facet_prefix`, `facet_pivot`, `group_field`,
`group_limit`). Limits are tighter: `max_results` caps at 25 instead of 100 and
`facet_limit` at 200 instead of 500. `list_portals` and `lookup_reference` carry
the canonical signatures in full, `max_results` aside.

## Two things that surprise everyone

- **Scope first.** A global HAL query answers over three million documents.
  Pass a collection code (UPPERCASE, e.g. `FRANCE-GRILLES`) or a portal code
  (lowercase, e.g. `tel`) — HAL tells the two apart by the case of the path
  segment.
- **The field suffix decides what a field can do.** `_t` is searchable but not
  returnable, `_s` is returnable, facetable and sortable but *not* searchable,
  `_id` matches identifiers only, `_tdate` cannot be faceted. Querying outside
  a field's capability returns zero results **with no error**: `title_s:japon`
  finds nothing, `title_t:japon` finds deposits. Open the Debug accordion when a
  query comes back empty — the URL is what tells the two cases apart.

## Debugging a failing call

Every tab carries a **🔍 Debug** accordion under the results. It shows the exact
URL sent to `api.archives-ouvertes.fr`, the HTTP status, and — when HAL answers
4xx/5xx — the first 1000 characters of its body, which is where Solr names the
offending field. Nothing is redacted: HAL takes no credential, so the URL can be
pasted straight into a browser to compare like for like.

Errors are *rendered*, not raised: a failed call still fills the debug panel,
which is when it is most needed.

## Run it

```bash
uv run --with 'gradio[mcp]>=6,<7' --with httpx app.py
# http://localhost:7860
```

What it exposes over MCP:

```bash
curl -s localhost:7860/gradio_api/mcp/schema | python3 -m json.tool
```

## Configuration

HAL is **public and anonymous** — no API key, no institutional identifier,
nothing to configure. The Space runs as it stands.

| Variable | Effect |
|---|---|
| `GRADIO_SERVER_NAME` / `GRADIO_SERVER_PORT` | Bind address and port |
| `GRADIO_MCP_SERVER` | `false` disables the demo MCP endpoint |

## Deploy

```bash
git remote add space https://huggingface.co/spaces/<owner>/<space-name>
git subtree push --prefix=mcp/hal/demo space main
```

## Add this MCP to clients that support Streamable HTTP

Add the following configuration to your MCP config

```
{
  "mcpServers": {
    "hal": {
      "url": "http://localhost:7860/gradio_api/mcp/"
    }
  }
}
```

## Gradio live MCP demo

[https://huggingface.co/spaces/Geraldine/HAL-MCP](https://huggingface.co/spaces/Geraldine/HAL-MCP)

```
{
  "mcpServers": {
    "hal": {
      "url": "https://geraldine-hal-mcp.hf.space/gradio_api/mcp/"
    }
  }
}
```
