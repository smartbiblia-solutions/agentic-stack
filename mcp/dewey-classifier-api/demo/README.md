---
title: Dewey Classifier MCP Demo
emoji: 📚
colorFrom: indigo
colorTo: yellow
sdk: gradio
sdk_version: 6.22.0
app_file: app.py
pinned: false
short_description: Propose a Dewey class for a French thesis, from the Sudoc thesis list, through the humatheque-dewey-classifier-api service.
---

# Dewey Classifier MCP demo

A standalone Gradio demo of the
[`dewey-classifier-api`](https://github.com/smartbiblia-solutions/agentic-stack/tree/main/mcp/dewey-classifier-api)
MCP server: given the metadata of a French doctoral thesis — its title, its
subject keywords, its abstract — rank the Dewey classes it most resembles, so a
cataloguer gets a shortlist to confirm rather than a blank field.

The vocabulary is the reduced Dewey list French thesis cataloguing uses in the
Sudoc — 98 classes, listed in the **Taxonomie** tab. Any text is accepted, but a
document that is not a thesis is ranked against that same list, so read its
answer as a coarse discipline hint.

The **canonical MCP endpoint is `mcp_server.py`** one folder up, with looser
caps. The server has two tools, and this app exposes those same `classify_text`
and `list_dewey_classes` at `/gradio_api/mcp/`; that endpoint is demo-grade and
secondary. Set `GRADIO_MCP_SERVER=false` wherever the real server is reachable,
so clients cannot bind to the wrong one.

## Deliberate narrowings

Two, both documented in the tool docstrings: `texts` is capped at 10 entries per
call instead of 50, and `top_k` at 20 instead of 100. Every other argument
behaves exactly as it does on the canonical server.

## Reading the answer

**The scores are cosine similarities, not probabilities.** With e5-style models
they cluster high — 0.7 to 0.9 — even when the match is weak, so `0.82` is not
"82 % sure". What carries information is the *ranking* and the gap between rank 1
and rank 2. Leave the threshold at 0 and control the answer with the number of
classes returned.

`local` and `albert` scores are on **different scales**: the second is a
cross-encoder relevance, often two orders of magnitude smaller and far more
sharply separated. Never compare or merge the two.

The list is coarse on purpose: it is the thesis-cataloguing one — the ten Dewey
main classes and their tens divisions, plus the finer entries that rule keeps
(`004`, `020`, `060`, `070`, `090`, `796`, `944`). There is no `005.13` in it,
because a thesis record does not carry one. The service answers with the
division-level indice; the shelfmark is still a human decision. The
**Taxonomie** tab lists exactly what the deployment holds.

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

The demo calls the humatheque-dewey-classifier-api service. Without a reachable
endpoint it still starts and every call returns an `error` — a Space must
degrade, not crash.

| Variable | Required | Effect |
|---|---|---|
| `DEWEY_API_URL` | no | Base URL of the classifier. Defaults to the public deployment `https://dewey-classifier.smartbiblia.fr` |
| `DEWEY_API_KEY` | no | Sent as `X-API-Key` when the deployment requires it |
| `GRADIO_SERVER_NAME` / `GRADIO_SERVER_PORT` | no | Bind address and port |
| `GRADIO_MCP_SERVER` | no | `false` disables the demo MCP endpoint |

> Every classification runs an embedding pass upstream; a public Space spends the
> classifier's capacity on every visitor. Point `DEWEY_API_URL` at a deployment
> you are willing to expose, and put any key in the Space settings, never in this
> repo.

## Deploy

```bash
git remote add space https://huggingface.co/spaces/<owner>/<space-name>
git subtree push --prefix=mcp/dewey-classifier-api/demo space main
```

## Add this MCP to clients that support Streamable HTTP

Add the following configuration to your MCP config:

```json
{
  "mcpServers": {
    "dewey-classifier-api": {
      "url": "http://localhost:7860/gradio_api/mcp/"
    }
  }
}
```
