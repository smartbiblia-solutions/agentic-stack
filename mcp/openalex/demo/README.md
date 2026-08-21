---
title: OpenAlex MCP Demo
emoji: 🔎
colorFrom: indigo
colorTo: blue
sdk: gradio
sdk_version: 6.22.0
app_file: app.py
pinned: false
short_description: Search scholarly works through the openalex database.
---

# OpenAlex MCP demo

A standalone Gradio demo of the
[`openalex`](https://github.com/smartbiblia-solutions/agentic-stack/tree/main/mcp/openalex)
MCP server: search ~250 million scholarly works by keyword or by meaning, resolve
DOIs, follow forward citations, or classify a title or abstract into OpenAlex
topics.

The **canonical MCP endpoint is `mcp_server.py`** one folder up, with no
tightened result limits. This app serves the same five tools — `search_works`,
`search_semantic`, `lookup_by_doi`, `get_citing_works`, `classify_text` — at
`/gradio_api/mcp/`; that endpoint is demo-grade and secondary. Set
`GRADIO_MCP_SERVER=false` wherever the real server is reachable, so clients
cannot bind to the wrong one.

## Deliberate narrowings

`search_works` carries the canonical signature in full — `date_from`, `date_to`,
`sort_by`, `author` and `institution` included, with the same name/ORCID and
name/ROR resolution before filtering. Only `max_results` is clamped harder (10
instead of 200), and each record carries fewer fields because the demo requests a
narrower `select`.

`search_semantic` likewise carries the canonical signature — `year_from`,
`year_to` and `filter_open_access` — clamped to 10 results instead of 50. Its
arguments are years rather than dates, and its `total_found` is always `null`,
because that is what the OpenAlex vector endpoint imposes: it reports the result
cap, never a count. Results carry an extra `relevance_score`.

`lookup_by_doi` takes the same `dois` list and normalizes short DOIs to
`https://doi.org/…` the same way. The canonical server pages through as many
50-DOI batches as it is given; here one batch is the cap, 25 DOIs per call.

`get_citing_works` and `classify_text` carry the canonical signatures unchanged,
`max_results` clamped to 10 aside.

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

The server reads its key from `OPENALEX_API_KEY`. **A Space has no `.env`**, so
the key is supplied per request instead, resolved in this order:

1. the **Configuration tab** — the first tab in the UI, for browser visitors
2. the **`X-Openalex-Api-Key` request header** — for MCP clients
3. the **process environment** — whatever the Space operator set, as fallback

Nothing is held in a module-level global. A Space serves every visitor from one
process, so a key typed by one of them must never leak into another's request:
each call resolves its own key and discards it.

OpenAlex needs no credential, so an unconfigured Space works — on the anonymous
pool, with its lower rate limit. A key only buys throughput.

### Configuration tab

A single masked input for the key, plus **Check configuration**, which reports
which pool a call would use without ever echoing the key. It is never pre-filled
from the environment: the operator's Space secret is not for visitors to read
back.

### Environment (the fallback layer)

| Variable | Effect |
|---|---|
| `OPENALEX_API_KEY` | Optional fallback key, sent as the `api_key` query parameter |
| `GRADIO_SERVER_NAME` / `GRADIO_SERVER_PORT` | Bind address and port (default `0.0.0.0:7860`) |
| `GRADIO_MCP_SERVER` | `false` disables the demo MCP endpoint (default `true`) |

Secrets go in the Space settings, never in this repo. A public Space spends the
key of whoever deployed it, on every visitor — leaving it unset lets each user
bring their own instead.

## Deploy

```bash
git remote add space https://huggingface.co/spaces/<owner>/<space-name>
git subtree push --prefix=mcp/openalex/demo space main
```

## Add this MCP to clients that support Streamable HTTP

Add the following configuration to your MCP config

```
{
  "mcpServers": {
    "openalex": {
      "url": "http://localhost:7860/gradio_api/mcp/",
	  "headers": {
	    "X-Openalex-Api-Key": "<your-personal-access-token>"
		}
    }
  }
}
```

## Gradio live MCP demo

[https://huggingface.co/spaces/Geraldine/openalex-mcp](https://huggingface.co/spaces/Geraldine/openalex-mcp)

```
{
  "mcpServers": {
    "openalex": {
      "url": "https://geraldine-openalex-mcp.hf.space/gradio_api/mcp/",
	  "headers": {
	    "X-Openalex-Api-Key": "<your-personal-access-token>"
		}
    }
  }
}
```

