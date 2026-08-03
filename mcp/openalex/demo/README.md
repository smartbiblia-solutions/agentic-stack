---
title: OpenAlex MCP Demo
emoji: 🔎
colorFrom: indigo
colorTo: blue
sdk: gradio
sdk_version: 6.22.0
app_file: app.py
pinned: false
short_description: Search 250M scholarly works through the openalex MCP tools.
---

# OpenAlex MCP demo

A standalone Gradio demo of the
[`openalex`](https://github.com/smartbiblia-solutions/agentic-stack/tree/main/mcp/openalex)
MCP server: search ~250 million scholarly works, or classify a title or abstract
into OpenAlex topics.

The **canonical MCP endpoint is `mcp_server.py`** one folder up, with the full
tool set (`search_works`, `lookup_by_doi`, `get_citing_works`, `classify_text`)
and no tightened result limits. This app exposes two of them at
`/gradio_api/mcp/sse`; that endpoint is demo-grade and secondary. Set
`GRADIO_MCP_SERVER=false` wherever the real server is reachable, so clients
cannot bind to the wrong one.

## It is standalone

`app.py` imports nothing from the parent folder — this folder is the Space root,
so `mcp_server.py` does not exist here. The two tools are a **hand-kept copy** of
the canonical ones: same names, same argument names and types, same response
shape including `error`. **Change one, change the other.**

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

| Variable | Effect |
|---|---|
| `OPENALEX_API_KEY` | Optional. Sent as the `api_key` query parameter; without it the demo uses the anonymous pool |
| `GRADIO_SERVER_NAME` / `GRADIO_SERVER_PORT` | Bind address and port (default `0.0.0.0:7860`) |
| `GRADIO_MCP_SERVER` | `false` disables the demo MCP endpoint (default `true`) |

Secrets go in the Space settings, never in this repo. A public Space spends the
key of whoever deployed it, on every visitor.

## Deploy

```bash
git remote add space https://huggingface.co/spaces/<owner>/<space-name>
git subtree push --prefix=mcp/openalex/demo space main
```
