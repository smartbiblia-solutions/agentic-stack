---
title: OpenCitations MCP Demo
emoji: 🔗
colorFrom: yellow
colorTo: gray
sdk: gradio
sdk_version: 6.22.0
app_file: app.py
pinned: false
short_description: Open citation counts and citing works from OpenCitations.
---

# OpenCitations MCP demo

A standalone Gradio demo of the
[`opencitations`](https://github.com/smartbiblia-solutions/agentic-stack/tree/main/mcp/opencitations)
MCP server: count the citations a work receives and the references it makes,
list the citing works and the cited ones — with journal and author self-citations
marked, and optionally each work's CC0 bibliographic record — resolve identifiers
to Meta records, and list everything an ORCID is attached to.

The **canonical MCP endpoint is `mcp_server.py`** one folder up, with no
tightened result limits. This app serves the same five tools —
`get_citation_counts`, `get_citations`, `get_references`, `lookup_metadata`,
`list_works_by_person` — at `/gradio_api/mcp/`; that endpoint is demo-grade and
secondary. Set `GRADIO_MCP_SERVER=false` wherever the
real server is reachable, so clients cannot bind to the wrong one.

## Deliberate narrowings

The one signature difference is `sort` and `role`, typed as plain `str` here
rather than the canonical `Literal`, and validated at the top of the function:
Gradio builds the MCP schema from the Python annotations, and a demo that
refused an out-of-range value at parse time would answer with a transport error
instead of the envelope every other failure uses.

## Three API facts the demo inherits

- **There is no search.** OpenCitations is entirely identifier-driven: bring a
  DOI, PMID or OMID found elsewhere (OpenAlex, HAL, Crossref). Nothing here
  discovers a work from a subject.
- **The list endpoints have no pagination and no server-side limit.** The whole
  citation set is downloaded and cut client-side, so `get_citation_counts` comes
  first: above the listing threshold the call is refused with its count and an
  explanatory `error` rather than attempted. One measured work returned 24 354
  edges / 9.9 MB, and very large works answer HTTP 500 after four minutes.
- **Sorting is client-side.** The API's own `sort` and `filter` parameters take
  over a minute and come back as truncated JSON at scale.

Two more quirks worth knowing: a truncated body can arrive with HTTP 200 (it is
retried once, then reported in `error`), and an unknown identifier is not an
error — it answers with counts of 0, indistinguishable from a work genuinely
absent from the index.

This demo clamps harder than the canonical server: **25 results** instead of 500,
and a **2 000-edge** listing threshold instead of 5 000. `lookup_metadata`
batches identifiers 10 per upstream request, as the canonical server does.

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

OpenCitations is CC0 and usable anonymously; a token only raises the quota
(180 requests/minute without one). An unset key is not an error.

| Variable | Effect |
|---|---|
| `OPENCITATIONS_API_URL` | API base URL (default `https://api.opencitations.net`) |
| `OPENCITATIONS_API_KEY` | Optional token, sent raw in the `authorization` header |
| `GRADIO_SERVER_NAME` / `GRADIO_SERVER_PORT` | Bind address and port (default `0.0.0.0:7860`) |
| `GRADIO_MCP_SERVER` | `false` disables the demo MCP endpoint (default `true`) |

## Deploy

```bash
git remote add space https://huggingface.co/spaces/<owner>/<space-name>
git subtree push --prefix=mcp/opencitations/demo space main
```

## Add this MCP to clients that support Streamable HTTP

Add the following configuration to your MCP config

```
{
  "mcpServers": {
    "opencitations": {
      "url": "http://localhost:7860/gradio_api/mcp/"
    }
  }
}
```
