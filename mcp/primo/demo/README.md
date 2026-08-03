---
title: Primo MCP Demo
emoji: 🏛️
colorFrom: gray
colorTo: purple
sdk: gradio
sdk_version: 6.22.0
app_file: app.py
pinned: false
short_description: Search an institutional Primo discovery layer through its MCP tools.
---

# Primo MCP demo

A standalone Gradio demo of the
[`primo`](https://github.com/smartbiblia-solutions/agentic-stack/tree/main/mcp/primo)
MCP server: search an institutional Primo (Ex Libris) discovery layer, or fetch
one record by its identifier.

The **canonical MCP endpoint is `mcp_server.py`** one folder up, with the full
tool set and no tightened result limit. This app exposes `search_catalog` and
`get_record` at `/gradio_api/mcp/sse`; that endpoint is demo-grade and
secondary. Set `GRADIO_MCP_SERVER=false` wherever the real server is reachable,
so clients cannot bind to the wrong one.

## It is standalone

`app.py` imports nothing from the parent folder — this folder is the Space root,
so `mcp_server.py` does not exist here. The two tools are a **hand-kept copy** of
the canonical ones: same names, same argument names and types, same record shape
including `error`. **Change one, change the other.**

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

Primo is **credentialed**. Without a key and a view, the app still starts and
every call returns an `error` explaining what is missing — a Space must degrade,
not crash.

| Variable | Required | Effect |
|---|---|---|
| `PRIMO_API_KEY` | yes | Ex Libris API key |
| `PRIMO_VID` | yes | View id, e.g. `33BUB_INST:BUB` |
| `PRIMO_TAB` | yes | Search tab, e.g. `Everything` |
| `PRIMO_SCOPE` | yes | Search scope, e.g. `MyInst_and_CI` |
| `PRIMO_REGION` | no | API host region (default `api-eu.hosted.exlibrisgroup.com`) |
| `PRIMO_INST` / `PRIMO_LANG` | no | Institution code and interface language |
| `GRADIO_SERVER_NAME` / `GRADIO_SERVER_PORT` | no | Bind address and port |
| `GRADIO_MCP_SERVER` | no | `false` disables the demo MCP endpoint |

> **Deploy this one private, or with a key issued for it alone.** Every visitor
> spends your Ex Libris quota. Secrets go in the Space settings, never in this
> repo.

## Deploy

```bash
git remote add space https://huggingface.co/spaces/<owner>/<space-name>
git subtree push --prefix=mcp/primo/demo space main
```
