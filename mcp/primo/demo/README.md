---
title: Primo MCP Demo
emoji: 🏛️
colorFrom: gray
colorTo: purple
sdk: gradio
sdk_version: 6.22.0
app_file: app.py
pinned: false
short_description: Search an institutional Primo discovery instance.
---

# Primo MCP demo

A standalone Gradio demo of the
[`primo`](https://github.com/smartbiblia-solutions/agentic-stack/tree/main/mcp/primo)
MCP server: search an institutional Primo (Ex Libris) discovery layer, or fetch
one record by its identifier.

The **canonical MCP endpoint is `mcp_server.py`** one folder up, with no
tightened result limit. The server has exactly two tools, and this app exposes
both — `search_catalog` and `get_record` — at `/gradio_api/mcp/`; that endpoint
is demo-grade and secondary. Set `GRADIO_MCP_SERVER=false` wherever the real
server is reachable, so clients cannot bind to the wrong one.

## It is standalone

`app.py` imports nothing from the parent folder, this folder is the Space root,
so `mcp_server.py` does not exist here. The two tools are a **hand-kept copy** of
the canonical ones — the server has no third tool, so the surfaces match tool for
tool: same names, same argument names and types, same record shape including
`error`. **Change one, change the other.**

Both tools carry the canonical signature in full — every facet argument, the
paging `offset`, `full_text_only`, `return_facets` and the `vid` / `tab` /
`scope` overrides. Only the limits are tighter: `max_results` caps at 10 instead
of 50, and `offset` at 200.

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

Primo is **credentialed**, and institution-scoped: nothing runs without an API
key plus a `vid` and a `scope` naming a view of that key's institution. The
server reads the key from `PRIMO_API_KEY` and takes the rest from `--region` /
`--base-url` / `--vid` / `--tab` / `--scope` / `--inst` / `--lang`. **A Space has
neither a command line nor a `.env`**, so every one of those is supplied per
request instead, resolved in this order:

1. the **Configuration tab** — the first tab in the UI, for browser visitors
2. an **`X-Primo-*` request header** — for MCP clients
3. the **process environment** — whatever the Space operator set, as fallback

Nothing is held in a module-level global. A Space serves every visitor from one
process, so a key typed by one of them must never leak into another's request:
each call resolves its own configuration and discards it.

Without a key the app still starts and every call returns an `error` naming what
is missing — a Space degrades, it does not crash.

### Configuration tab

One input per server setting: API key (masked), gateway region, base-URL
override, `vid`, `tab`, `scope`, institution code, language. **Check
configuration** reports the gateway that would be called and whether a key is
present — it never echoes the key, not even partially. The non-secret boxes are
pre-filled from the environment; the key box never is, because the operator's
Space secret is not for visitors to read back.

### Environment (the fallback layer)

All optional — they are only what a call falls back to.

| Variable | Effect |
|---|---|
| `PRIMO_API_KEY` | Ex Libris API key |
| `PRIMO_VID` | Default view id, e.g. `33BUB_INST:BUB` |
| `PRIMO_TAB` | Default search tab, e.g. `Everything` |
| `PRIMO_SCOPE` | Default search scope, e.g. `MyInst_and_CI` |
| `PRIMO_REGION` | Gateway region: `na` `eu` `ap` `ca` `cn` (default `na`) |
| `PRIMO_BASE_URL` | Full gateway base URL, overrides `PRIMO_REGION` |
| `PRIMO_INST` | Default institution code, e.g. `MyUni` |
| `PRIMO_LANG` | Interface language (default `en`) |
| `GRADIO_SERVER_NAME` / `GRADIO_SERVER_PORT` | Bind address and port |
| `GRADIO_MCP_SERVER` | `false` disables the demo MCP endpoint |

## Deploy

```bash
git remote add space https://huggingface.co/spaces/<owner>/<space-name>
git subtree push --prefix=mcp/primo/demo space main
```

## Add this MCP to clients that support Streamable HTTP

Add the following configuration to your MCP config

```
{
  "mcpServers": {
    "primo": {
      "url": "http://localhost:7860/gradio_api/mcp/",
	  "headers": {
	    "X-Primo-Api-Key": "<your-personal-access-token>"
        "X-Primo-Vid": "33BUB_INST:BUB"    # replace by your value
        "X-Primo-Scope": "MyInst_and_CI"
        "X-Primo-Tab": "Everything"
		"X-Primo-Inst": "X_INST"
        "X-Primo-Region": "eu"             # or X-Primo-Base-Url for a full gateway URL
        "X-Primo-Lang": "en"
		}
    }
  }
}
```

## Gradio live MCP demo

[https://huggingface.co/spaces/Geraldine/exlibris-primo-mcp](https://huggingface.co/spaces/Geraldine/exlibris-primo-mcp)

```
{
  "mcpServers": {
    "primo": {
      "url": "https://geraldine-exlibris-primo-mcp.hf.space/gradio_api/mcp/",
	  "headers": {
	    "X-Primo-Api-Key": "<your-personal-access-token>"
        "X-Primo-Vid": "33BUB_INST:BUB"   # replace by your value
        "X-Primo-Scope": "MyInst_and_CI"
        "X-Primo-Tab": "Everything"
		"X-Primo-Inst": "X_INST"
        "X-Primo-Region": "eu"            # or X-Primo-Base-Url for a full gateway URL
        "X-Primo-Lang": "en"
		}
    }
  }
}
```
