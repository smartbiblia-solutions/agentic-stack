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

A Gradio demo of the
[`theses-fr`](https://github.com/smartbiblia-solutions/agentic-stack/tree/main/mcp/theses-fr)
MCP server: search the French national register of doctoral theses (ABES) by
subject, establishment, person or organisation, resolve an establishment's code
and lineage, fetch one thesis with both résumés and its full-text link, find a
supervisor, count theses per facet, or profile an organisation.

The tools **are** the canonical server's: `theses_core.py` is generated from
`../mcp_server.py` by `../scripts/sync_copies.py` (this folder is pushed to the
Space alone, so the app cannot import the server) and `app.py` only adds the
Gradio layer. The canonical MCP endpoint remains `mcp_server.py`; the demo's
endpoint at `/gradio_api/mcp/` is demo-grade. Set `GRADIO_MCP_SERVER=false`
wherever the real server is reachable, so clients cannot bind to the wrong one.

| Tool | What it does |
|---|---|
| `search_theses` | Subject (`topic`, stemmed over titles, résumés, keywords), establishment by name/code/PPN, status, dates, people by accented name or PPN, organisation role… |
| `resolve_establishment` | Name, acronym or code → `codeEtab`, PPN, predecessors and successors, live thesis count |
| `get_thesis` | One record by NNT or subject number: jury, both résumés, checked full-text links |
| `search_persons` | Name → people, their roles and their theses |
| `list_facets` | Thesis counts per facet value for a subject, one facet at a time, filterable |
| `search_by_organisme` | An organisation's thesis counts per role, with a few samples |

## Deliberate narrowings

- `max_results` is capped at 10 — the tool descriptions say so.
- Enumerated arguments (`status`, `sort`, `organisation_role`, `facet`, `role`)
  are plain `str` validated in `app.py` rather than `Literal`: Gradio builds the
  MCP schema from the annotations, and a bad value should come back in `error`
  rather than as a transport failure.
- Gradio's MCP endpoint has no server-level `instructions`; the workflow hints
  of the canonical server live in each tool description instead.

## Change it

Tool behaviour belongs to `../mcp_server.py`. Change it there, then:

```bash
python3 mcp/theses-fr/scripts/sync_copies.py   # rewrites demo/theses_core.py and modal/
```

Never edit `theses_core.py` by hand. `app.py` holds only the wrappers, the
Markdown renderers and the UI.

The establishment referential (`../etablissements.json`) is not in this folder:
the core fetches it from the repository's `main` branch on first use. Set
`THESES_FR_ETABLISSEMENTS` to a path or URL to point it elsewhere.

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
| `THESES_FR_ETABLISSEMENTS` | Path or URL of the establishment referential (default: the repository copy on `main`) |
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
