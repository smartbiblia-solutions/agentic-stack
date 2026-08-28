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
DOIs, follow forward citations, classify a text into OpenAlex topics, resolve a
name to an identifier, browse the topic hierarchy, count along any dimension, and
translate a query between OpenAlex's own query language and a REST URL.

The **canonical MCP endpoint is `mcp_server.py`** one folder up, with no
tightened result limits. This app serves the same nine tools — `search_works`,
`search_semantic`, `lookup_by_doi`, `get_citing_works`, `classify_text`,
`resolve_entity`, `browse_topics`, `group_by`, `translate_query` — at
`/gradio_api/mcp/`; that endpoint is demo-grade and secondary. Set
`GRADIO_MCP_SERVER=false` wherever the real server is reachable, so clients
cannot bind to the wrong one.

## Deliberate narrowings

Every tool carries the canonical signature. What the demo narrows is result
caps, because this endpoint is public and every billable call spends the
operator's daily OpenAlex budget.

`search_works` keeps `date_from`, `date_to`, `sort_by`, `author`, `institution`,
`institution_scope`, the four topic-hierarchy arguments, `topic_scope`, `corpus`
and `exact`, with the same name/ORCID and name/ROR resolution before filtering.
Only `max_results` is clamped harder (10 instead of 100), and each record carries
fewer fields because the demo requests a narrower `select`.

`search_semantic` likewise carries the canonical signature — `year_from`,
`year_to`, `filter_open_access` and `institution` — clamped to 10 results instead
of 50. Its arguments are years rather than dates, and its `total_found` is always
`null`, because that is what the OpenAlex vector endpoint imposes: it reports the
result cap, never a count. Results carry an extra `relevance_score`.

`lookup_by_doi` takes the same `dois` list and normalizes short DOIs to
`https://doi.org/…` the same way. The canonical server pages through as many
50-DOI batches as it is given; here one batch is the cap, 25 DOIs per call.

`get_citing_works`, `resolve_entity` and `browse_topics` carry the canonical
signatures with `max_results` clamped to 10. `group_by` caps `max_groups` at 50
instead of 100 — an output-size limit rather than a spending one, since one
aggregation costs the same whatever it counts; `groups_count` still reports the
real number of distinct groups. `classify_text` and `translate_query` are
unchanged.

Arguments the canonical server declares as closed `Literal`s — `corpus`,
`institution_scope`, `topic_scope`, `entity_type`, `level`, `form` — are plain
`str` here and validated inside the function: Gradio builds the MCP schema from
the annotations, and a bad value belongs in `error` rather than in a transport
failure. The accepted values are named in each docstring.

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

OpenAlex needs no credential, so an unconfigured Space works. Since February 2026
the API meters a **daily budget** rather than a request rate, and ignores
`mailto`: anonymous callers get **$0.10/day** per IP — shared here by every
visitor of the Space — and a free key raises it to **$1.00/day**. Both reset at
midnight UTC. Lookups by identifier and `/autocomplete` are free at either level;
a keyword or semantic search costs $0.001, everything else $0.0001. Every
billable response reports what it spent in `cost_usd`, and an exhausted budget
comes back as `error`, not as a crash:

```
Insufficient budget. This request costs $0.001 but you only have $0 remaining.
Resets at midnight UTC.
```

### Configuration tab

A single masked input for the key, plus **Check configuration**, which reports
which budget a call would use without ever echoing the key. It is never
pre-filled from the environment: the operator's Space secret is not for visitors
to read back.

### Environment (the fallback layer)

| Variable | Effect |
|---|---|
| `OPENALEX_API_KEY` | Optional fallback key, sent as the `api_key` query parameter |
| `GRADIO_SERVER_NAME` / `GRADIO_SERVER_PORT` | Bind address and port (default `0.0.0.0:7860`) |
| `GRADIO_MCP_SERVER` | `false` disables the demo MCP endpoint (default `true`) |

Secrets go in the Space settings, never in this repo. A public Space spends the
budget of whoever deployed it, on every visitor — leaving it unset drops the
Space to the $0.10/day anonymous budget and lets each user bring their own key
instead.

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

