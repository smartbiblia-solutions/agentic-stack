#!/usr/bin/env python3
"""
Standalone Gradio demo of the OpenAlex MCP server, deployable as a Hugging Face Space.

This app imports nothing from the parent folder: the Space root is this folder,
so `mcp_server.py` does not exist there. It re-implements two of the server's
tools — `search_works` and `classify_text` — against the same OpenAlex endpoints,
under the same names, with the same argument names and the same response shape.

The canonical MCP endpoint remains `../mcp_server.py`. These tools are a
hand-kept copy: change one, change the other.

Local run:
    uv run --with 'gradio[mcp]>=6,<7' --with httpx app.py

Environment:
    OPENALEX_API_KEY     optional, sent as the `api_key` query parameter
    GRADIO_SERVER_NAME   bind address (default 0.0.0.0)
    GRADIO_SERVER_PORT   port (default 7860)
    GRADIO_MCP_SERVER    "false" disables the demo MCP endpoint (default true)
"""

from __future__ import annotations

import os

import gradio as gr
import httpx

# ── Configuration ─────────────────────────────────────────────────────────────

API_KEY = os.environ.get("OPENALEX_API_KEY", "")

OPENALEX_BASE = "https://api.openalex.org"
OPENALEX_WORKS = f"{OPENALEX_BASE}/works"
OPENALEX_TEXT = f"{OPENALEX_BASE}/text"

SELECT_FIELDS = ",".join([
    "id", "title", "authorships", "doi", "publication_date", "publication_year",
    "primary_location", "best_oa_location", "open_access", "cited_by_count", "type",
])

# A Space has no command line: connector policy is constant here.
REQUEST_TIMEOUT = 20.0

# Clamped harder than the canonical server (which allows 200): this endpoint is
# public and every call spends the operator's OpenAlex budget.
MAX_RESULTS = 10

# One module-level pooled client for the process.
HTTP = httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True)


def _get(url: str, params: dict) -> tuple[dict | None, str | None]:
    """GET returning (payload, error). Never raises — the demo answers with data."""
    request_params = dict(params)
    if API_KEY:
        request_params["api_key"] = API_KEY
    try:
        resp = HTTP.get(url, params=request_params)
        resp.raise_for_status()
        return resp.json(), None
    except httpx.HTTPStatusError as exc:
        return None, f"OpenAlex returned HTTP {exc.response.status_code}"
    except httpx.TimeoutException:
        return None, f"OpenAlex timed out after {REQUEST_TIMEOUT:g}s"
    except Exception as exc:  # noqa: BLE001 - never crash the Space
        return None, f"cannot reach OpenAlex: {exc}"


def _format_work(work: dict) -> dict:
    """Map one OpenAlex work onto the common record schema."""
    authors = [
        (a.get("author") or {}).get("display_name", "")
        for a in work.get("authorships", [])
    ]
    source = (work.get("primary_location") or {}).get("source") or {}
    best_oa = work.get("best_oa_location") or {}
    raw_doi = work.get("doi") or None
    doi = raw_doi.replace("https://doi.org/", "") if isinstance(raw_doi, str) else None
    openalex_id = (work.get("id") or "").replace("https://openalex.org/", "")

    return {
        "source": "openalex",
        "id": openalex_id,
        "openalex_id": openalex_id,
        "title": work.get("title"),
        "authors": authors,
        "doi": doi,
        "pdf_url": best_oa.get("pdf_url") or best_oa.get("landing_page_url"),
        "url": work.get("id"),
        "year": work.get("publication_year"),
        "date": work.get("publication_date") or str(work.get("publication_year") or ""),
        "doc_type": work.get("type"),
        "journal": source.get("display_name"),
        "cited_by_count": work.get("cited_by_count", 0),
        "is_open_access": (work.get("open_access") or {}).get("is_oa", False),
    }


# ── MCP tools (the only functions exposed with gr.api) ────────────────────────


def search_works(
    query: str,
    max_results: int = 5,
    filter_open_access: bool = False,
) -> dict:
    """
    Search OpenAlex for academic works by keyword query.

    Args:
        query: Free-text search over title, abstract and full text, e.g. "multilingual subject indexing".
        max_results: Number of works to return, 1-10 on this demo endpoint.
        filter_open_access: Keep only works with an open-access full text.

    Returns:
        {"source": "openalex", "command": "search_works", "total_found": int, "returned": int, "results": [{"source": "openalex", "id": str, "title": str, "authors": [str], "doi": str | null, "url": str, "year": int | null, "journal": str | null}], "error": str | null}
    """
    out: dict = {"source": "openalex", "command": "search_works",
                 "total_found": 0, "returned": 0, "results": [],
                 "query_used": query, "filters_used": [], "error": None}

    if not (query or "").strip():
        out["error"] = "query is required"
        return out

    filters = ["is_oa:true"] if filter_open_access else []
    params: dict = {
        "search": query,
        "per-page": max(1, min(int(max_results or 5), MAX_RESULTS)),
        "sort": "publication_date:desc",
        "select": SELECT_FIELDS,
    }
    if filters:
        params["filter"] = ",".join(filters)

    data, error = _get(OPENALEX_WORKS, params)
    if error:
        out["error"] = error
        return out

    results = data.get("results", [])
    out["total_found"] = (data.get("meta") or {}).get("count", 0)
    out["returned"] = len(results)
    out["results"] = [_format_work(r) for r in results]
    out["filters_used"] = filters
    return out


def classify_text(text: str) -> dict:
    """
    Classify a title or abstract into OpenAlex topics, fields and keywords.

    Args:
        text: Title or abstract to classify, minimum 20 characters, truncated at 2000.

    Returns:
        {"source": "openalex", "command": "classify_text", "total_found": int, "returned": int, "results": [{"name": str, "score": float, "field": str | null, "domain": str | null}], "keywords": [str], "error": str | null}
    """
    out: dict = {"source": "openalex", "command": "classify_text",
                 "total_found": 0, "returned": 0, "results": [],
                 "keywords": [], "error": None}

    text = (text or "").strip()
    if len(text) < 20:
        out["error"] = "Text too short (minimum 20 characters)"
        return out

    data, error = _get(OPENALEX_TEXT, {"title": text[:2000]})
    if error:
        out["error"] = error
        return out

    out["results"] = [
        {
            "name": topic.get("display_name"),
            "score": topic.get("score"),
            "field": (topic.get("subfield") or {}).get("display_name"),
            "domain": (topic.get("domain") or {}).get("display_name"),
        }
        for topic in data.get("topics", [])
    ]
    out["total_found"] = out["returned"] = len(out["results"])
    out["keywords"] = [k.get("display_name") for k in data.get("keywords", [])]
    return out


# ── Presentation ──────────────────────────────────────────────────────────────


def _render_works(payload: dict) -> str:
    results = payload.get("results") or []
    if not results:
        return "_No work matched this query._"
    lines = [
        f"**{payload.get('returned', len(results))} of {payload.get('total_found', '?')} works**",
        "",
        "| Year | Title | Authors | Journal | DOI |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        names = r.get("authors") or []
        authors = ", ".join(names[:3]) or "—"
        if len(names) > 3:
            authors += " et al."
        doi = r.get("doi")
        lines.append(
            "| {year} | [{title}]({url}) | {authors} | {journal} | {doi} |".format(
                year=r.get("year") or "—",
                title=(r.get("title") or "Untitled").replace("|", "\\|"),
                url=r.get("url") or "",
                authors=authors.replace("|", "\\|"),
                journal=(r.get("journal") or "—").replace("|", "\\|"),
                doi=f"[{doi}](https://doi.org/{doi})" if doi else "—",
            )
        )
    return "\n".join(lines)


def _render_topics(payload: dict) -> str:
    topics = payload.get("results") or []
    if not topics:
        return "_No topic returned._"
    lines = ["| Topic | Score | Field | Domain |", "|---|---|---|---|"]
    for t in topics:
        score = t.get("score")
        score_txt = f"{score:.3f}" if isinstance(score, (int, float)) else "—"
        lines.append(
            f"| {t.get('name') or '—'} | {score_txt} "
            f"| {t.get('field') or '—'} | {t.get('domain') or '—'} |"
        )
    keywords = [k for k in (payload.get("keywords") or []) if k]
    if keywords:
        lines += ["", "**Keywords** — " + ", ".join(keywords)]
    return "\n".join(lines)


def _run_search(query: str, max_results: int, open_access: bool):
    payload = search_works(query, max_results, open_access)
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render_works(payload), payload


def _run_classify(text: str):
    payload = classify_text(text)
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render_topics(payload), payload


# ── UI ────────────────────────────────────────────────────────────────────────

with gr.Blocks(title="OpenAlex MCP demo") as demo:
    gr.Markdown(
        "# OpenAlex MCP demo\n"
        "Standalone demo of the [`openalex`](https://github.com/smartbiblia-solutions/agentic-stack/tree/main/mcp/openalex) "
        "MCP server — ~250M scholarly works. The canonical MCP endpoint is "
        "`mcp_server.py` in that folder; this Space re-implements two of its "
        "tools and re-exposes them at `/gradio_api/mcp/sse` for clients that "
        "cannot run it."
    )

    with gr.Tab("Search works"):
        query = gr.Textbox(label="Query", placeholder="multilingual subject indexing")
        with gr.Row():
            max_results = gr.Slider(1, MAX_RESULTS, value=5, step=1, label="Results")
            open_access = gr.Checkbox(label="Open access only", value=False)
        search_btn = gr.Button("Search", variant="primary")
        works_out = gr.Markdown()
        works_raw = gr.JSON(label="Raw tool output")

        gr.Examples(
            examples=[
                ["multilingual subject indexing", 5, False],
                ["qzxwv nonexistent topic string", 3, False],
            ],
            inputs=[query, max_results, open_access],
            label="A hit, and a query that returns nothing",
        )
        search_btn.click(
            _run_search,
            inputs=[query, max_results, open_access],
            outputs=[works_out, works_raw],
            api_name=False,
        )

    with gr.Tab("Classify text"):
        text = gr.Textbox(
            label="Title or abstract",
            lines=4,
            placeholder="Paste a title or abstract of at least 20 characters.",
        )
        classify_btn = gr.Button("Classify", variant="primary")
        topics_out = gr.Markdown()
        topics_raw = gr.JSON(label="Raw tool output")

        gr.Examples(
            examples=[
                ["Automatic subject indexing of library records using transformer language models"],
                ["too short"],
            ],
            inputs=[text],
            label="A classifiable abstract, and an input the tool rejects",
        )
        classify_btn.click(
            _run_classify, inputs=[text], outputs=[topics_out, topics_raw], api_name=False
        )

    # The only declared MCP tools. Names match the canonical server's.
    gr.api(search_works, api_name="search_works")
    gr.api(classify_text, api_name="classify_text")


if __name__ == "__main__":
    demo.launch(
        theme=gr.themes.Soft(),  # Gradio 6 moved theme from Blocks() to launch()
        server_name=os.getenv("GRADIO_SERVER_NAME", "0.0.0.0"),
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
        mcp_server=os.getenv("GRADIO_MCP_SERVER", "true").lower() == "true",
    )
