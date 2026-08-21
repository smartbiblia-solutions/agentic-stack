---
title: IdRef Resolver MCP Demo
emoji: 🧭
colorFrom: purple
colorTo: pink
sdk: gradio
sdk_version: 6.22.0
app_file: app.py
pinned: false
short_description: Align a person to an IdRef PPN through the idref-resolver-api service.
---

# IdRef Resolver MCP demo

A standalone Gradio demo of the
[`idref-resolver-api`](https://github.com/smartbiblia-solutions/agentic-stack/tree/main/mcp/idref-resolver-api)
MCP server: decide *which* IdRef authority record is a given person, from free
clues (affiliation, discipline, titles), with a confidence score and the right
to abstain.

The **canonical MCP endpoint is `mcp_server.py`** one folder up, with no
tightened candidate limit. The server has exactly one tool, and this app exposes
that same `align_person` at
`/gradio_api/mcp/`; that endpoint is demo-grade and secondary. Set
`GRADIO_MCP_SERVER=false` wherever the real server is reachable, so clients
cannot bind to the wrong one.

## Deliberate narrowings

Two deliberate narrowings, documented in the docstring: `max_candidates` is
clamped to 30 instead of 100, and `max_returned_candidates` to 10 instead of 20.

## Reading the verdict

`status` is the field that matters. `accepted` means the alignment is safe to
use; `ambiguous` means several candidates are too close to separate;
`no_match` means nothing plausible was found. An abstention is a correct answer,
not a failure — `best_ppn` is `null` and the reason is in the payload.

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

The demo calls the idref-resolver-api service. Without a reachable endpoint it still
starts and every call returns an `error` — a Space must degrade, not crash.

| Variable | Required | Effect |
|---|---|---|
| `IDREF_API_URL` | yes | Base URL of the alignment API, e.g. `https://…/` (no trailing slash needed) |
| `IDREF_API_KEY` | no | Sent as `X-API-Key` when the deployment requires it |
| `GRADIO_SERVER_NAME` / `GRADIO_SERVER_PORT` | no | Bind address and port |
| `GRADIO_MCP_SERVER` | no | `false` disables the demo MCP endpoint |

> **Deploy this one private, or with a key issued for it alone.** Each alignment
> runs embeddings upstream; every visitor spends your budget. Secrets go in the
> Space settings, never in this repo.

## Deploy

```bash
git remote add space https://huggingface.co/spaces/<owner>/<space-name>
git subtree push --prefix=mcp/idref-resolver-api/demo space main
```

## Add this MCP to clients that support Streamable HTTP

Add the following configuration to your MCP config

```
{
  "mcpServers": {
    "idref-resolver-api": {
      "url": "http://localhost:7860/gradio_api/mcp/"
    }
  }
}
```
