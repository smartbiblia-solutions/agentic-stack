---
title: Sudoc MCP Demo
emoji: 📚
colorFrom: blue
colorTo: green
sdk: gradio
sdk_version: 6.22.0
app_file: app.py
pinned: false
short_description: Search the French union catalogue through the sudoc-sru MCP tools.
---

# Sudoc MCP demo

A standalone Gradio demo of the
[`sudoc-sru`](https://github.com/smartbiblia-solutions/agentic-stack/tree/main/mcp/sudoc-sru)
MCP server: search the French union catalogue (Sudoc) over the Abes SRU service,
fetch records by PPN or ISBN, count a corpus, and browse an index alphabetically.

The **canonical MCP endpoint is `mcp_server.py`** one folder up, with the
complete SRU index reference in its docstrings and no tightened result limit.
This app exposes the same five tools at `/gradio_api/mcp/`; that endpoint is
demo-grade and secondary. Set `GRADIO_MCP_SERVER=false` wherever the real server
is reachable, so clients cannot bind to the wrong one.

| Tool | What it does |
|---|---|
| `search_sudoc` | SRU search with optional TDO and year limitations |
| `lookup_by_ppn` | One record by its Sudoc identifier |
| `lookup_by_isbn` | The records carrying an ISBN-10 or ISBN-13 |
| `count_records` | How many records a query matches, fetching none |
| `scan_index` | Alphabetical browse of an index, with per-term counts |

## It is standalone

`app.py` imports nothing from the parent folder, this folder is the Space root,
so `mcp_server.py` does not exist here. The five tools are a **hand-kept copy**
of the canonical ones — the server has no sixth tool, so the surfaces match tool
for tool: same names, same argument names and types, same record shape including
`error`. **Change one, change the other.**

Two deliberate narrowings, both documented in the tool docstrings: `max_results`
is clamped to 10 instead of 100, and `scan_index`'s `maximum_terms` to 50.

## Run it

```bash
uv run --with 'gradio[mcp]>=6,<7' --with httpx app.py
# http://localhost:7860
```

What it exposes over MCP:

```bash
curl -s localhost:7860/gradio_api/mcp/schema | python3 -m json.tool
```

## Query syntax, in one paragraph

Write `index=term` and let the app encode it: `mti=jardins and japonais`,
`aut=lagerlof`, `tou="ocre jaune"`. Indexes worth knowing: `mti` (title), `aut`
(author), `tou` (everything), `sou` (subject), `nth` (thesis subject), `ppn`.
Booleans are `and` / `or` / `not`, truncation is a trailing `*`.

## Configuration

| Variable | Effect |
|---|---|
| `GRADIO_SERVER_NAME` / `GRADIO_SERVER_PORT` | Bind address and port (default `0.0.0.0:7860`) |
| `GRADIO_MCP_SERVER` | `false` disables the demo MCP endpoint (default `true`) |

The Abes SRU service needs no credential, but it is a shared public endpoint:
every visitor's click is attributed to whoever deployed this Space.

## Deploy

```bash
git remote add space https://huggingface.co/spaces/<owner>/<space-name>
git subtree push --prefix=mcp/sudoc-sru/demo space main
```

## Add this MCP to clients that support Streamable HTTP

Add the following configuration to your MCP config

```
{
  "mcpServers": {
    "sudoc-sru": {
      "url": "http://localhost:7860/gradio_api/mcp/"
    }
  }
}
```

## Gradio live MCP demo

[https://huggingface.co/spaces/Geraldine/sudoc-sru-mcp](https://huggingface.co/spaces/Geraldine/sudoc-sru-mcp)

```
{
  "mcpServers": {
    "sudoc-sru": {
      "url": "https://geraldine-sudoc-sru-mcp.hf.space/gradio_api/mcp/"
    }
  }
}
```
