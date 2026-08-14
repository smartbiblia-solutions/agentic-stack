---
title: Recherche Data Gouv MCP Demo
emoji: 🇫🇷
colorFrom: blue
colorTo: red
sdk: gradio
sdk_version: 6.22.0
app_file: app.py
pinned: false
short_description: Search French research datasets through the recherche-data-gouv MCP tools.
---

# Recherche Data Gouv MCP demo

A standalone Gradio demo of the
[`recherche-data-gouv`](https://github.com/smartbiblia-solutions/agentic-stack/tree/main/mcp/recherche-data-gouv)
MCP server: search the French national research data repository (a Dataverse
instance), or read its usage metrics.

The **canonical MCP endpoint is `mcp_server.py`** one folder up, with the full
argument lists and no tightened result limit. This app exposes the same three
tools at `/gradio_api/mcp/`; that endpoint is demo-grade and secondary. Set
`GRADIO_MCP_SERVER=false` wherever the real server is reachable, so clients
cannot bind to the wrong one.

| Tool | What it does |
|---|---|
| `search` | Solr search over datasets, dataverses and files |
| `metrics` | Dataverse Metrics counters, total or broken down |
| `metadatablocks` | The instance's metadata blocks, or one block schema |

## It is standalone

`app.py` imports nothing from the parent folder, this folder is the Space root,
so `mcp_server.py` does not exist here. The three tools are a **hand-kept copy**
of the canonical ones — the server has no fourth tool, so the surfaces match tool
for tool: same names, same response shape including `error`. **Change one, change
the other.**

Two deliberate narrowings, both documented in the tool docstrings: `per_page` is
clamped to 10 instead of 1000, and each tool keeps the handful of arguments a
browser form can express (`search` drops `filters`, `subtree`, `sort`, facets and
entity ids; `metrics` drops `parent_alias`, `data_location`, `country` and the
Make Data Count family). Everything kept behaves exactly as it does upstream.

A note on the metrics breakdowns: `bySubject` and `monthly` exist on `datasets`,
`byCategory` on `dataverses`, `byType` on `files`. The other combinations answer
HTTP 404 upstream, which comes back in `error` — the demo does not pre-filter the
dropdown, because the mapping is the API's, not the demo's.

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

Read access is public — no credential.

| Variable | Effect |
|---|---|
| `RECHERCHE_DATA_GOUV_API_URL` | Dataverse base URL (default `https://entrepot.recherche.data.gouv.fr/api`) |
| `GRADIO_SERVER_NAME` / `GRADIO_SERVER_PORT` | Bind address and port (default `0.0.0.0:7860`) |
| `GRADIO_MCP_SERVER` | `false` disables the demo MCP endpoint (default `true`) |

## Deploy

```bash
git remote add space https://huggingface.co/spaces/<owner>/<space-name>
git subtree push --prefix=mcp/recherche-data-gouv/demo space main
```

## Add this MCP to clients that support Streamable HTTP

Add the following configuration to your MCP config

```
{
  "mcpServers": {
    "recherche-data-gouv": {
      "url": "http://localhost:7860/gradio_api/mcp/"
    }
  }
}
```

## Gradio live MCP demo

[https://huggingface.co/spaces/Geraldine/recherche-data-gouv-mcp](https://huggingface.co/spaces/Geraldine/recherche-data-gouv-mcp)

```
{
  "mcpServers": {
    "recherche-data-gouv": {
      "url": "https://geraldine-recherche-data-gouv-mcp.hf.space/gradio_api/mcp/"
    }
  }
}
```
