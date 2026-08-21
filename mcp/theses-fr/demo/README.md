---
title: theses.fr MCP Demo
emoji: 🎓
colorFrom: indigo
colorTo: red
sdk: gradio
sdk_version: 6.22.0
app_file: app.py
pinned: false
short_description: Search French doctoral theses through the theses-fr API.
---

# theses.fr MCP demo

A standalone Gradio demo of the
[`theses-fr`](https://github.com/smartbiblia-solutions/agentic-stack/tree/main/mcp/theses-fr)
MCP server: search the French national register of doctoral theses (ABES), fetch
one thesis with its bilingual résumés, find a supervisor, enumerate the facet
labels, or read an institution's whole doctoral footprint.

The **canonical MCP endpoint is `mcp_server.py`** one folder up, with a date
range on `search_theses`, an `--trace` mode and no tightened result limit. This
app exposes the same five tools at `/gradio_api/mcp/`; that endpoint is
demo-grade and secondary. Set `GRADIO_MCP_SERVER=false` wherever the real server
is reachable, so clients cannot bind to the wrong one.

| Tool | What it does |
|---|---|
| `search_theses` | Lucene search, with the filters compiled into `q` |
| `get_thesis` | One record by NNT or subject number, with its résumés |
| `search_persons` | Name → people, their roles and their theses |
| `list_facets` | The exact facet labels a query accepts, with counts |
| `search_by_organisme` | An organisation's theses, grouped by its role |

## Deliberate narrowings

Deliberate narrowings, documented in the tool docstrings: `max_results` is
clamped to 10 instead of 200, and `search_by_organisme`'s `role` is a plain `str`
validated in the function rather than a `Literal`, because Gradio builds the MCP
schema from the annotations and a bad value should come back in `error` rather
than as a transport failure.

## Three API facts the demo inherits

- theses.fr's `filtres` parameter is inert, so every constraint is compiled into
  one Lucene `q`.
- Search hits carry **no résumé** — it lives on the record endpoint only. Hence
  the `hydrate` argument, one extra request per hit, and the `get_thesis` tab.
- The establishment filter is `codeEtab:(COAZ)`, upper-cased because the field is
  case-sensitive. The older `nnt:*COAZ*` idiom only matches defended theses (1 568
  against 2 706 for Université Côte d'Azur), since a thesis in preparation has no
  NNT yet.

Quoting is per-field and the demo compiles it for you: `oaiSetNames` (the
« Domaine thématique » box) must be quoted, `auteursNP` / `directeursNP` must
not. `accessible` describes the online full text and only ever matches defended
theses — combined with `enCours` it returns nothing.

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

theses.fr is public and anonymous — no credential.

| Variable | Effect |
|---|---|
| `THESES_FR_API_URL` | API base URL (default `https://theses.fr/api/v1`) |
| `GRADIO_SERVER_NAME` / `GRADIO_SERVER_PORT` | Bind address and port (default `0.0.0.0:7860`) |
| `GRADIO_MCP_SERVER` | `false` disables the demo MCP endpoint (default `true`) |

## Deploy

```bash
git remote add space https://huggingface.co/spaces/<owner>/<space-name>
git subtree push --prefix=mcp/theses-fr/demo space main
```

## Add this MCP to clients that support Streamable HTTP

Add the following configuration to your MCP config

```
{
  "mcpServers": {
    "theses-fr": {
      "url": "http://localhost:7860/gradio_api/mcp/"
    }
  }
}
```

## Gradio live MCP demo

[https://huggingface.co/spaces/Geraldine/theses.fr-MCP](https://huggingface.co/spaces/Geraldine/theses.fr-MCP)

```
{
  "mcpServers": {
    "theses-fr": {
      "url": "https://geraldine-theses-fr-mcp.hf.space/gradio_api/mcp/"
    }
  }
}
```
