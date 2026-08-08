#!/usr/bin/env python3
"""
Standalone Gradio demo of the OpenAlex MCP server, deployable as a Hugging Face Space.

The three tools mirror the canonical `mcp_server.py` signatures argument for
argument, author and institution resolution included.

The OpenAlex key setting is supplied **per request**, resolved in this order:

    1. the Configuration tab            (browser visitors)
    2. the `X-Openalex-Api-Key` header  (MCP clients)
    3. the process environment          (what the Space operator set, if anything)

OpenAlex is usable anonymously, so an unconfigured Space still works, on the
shared anonymous pool, with its lower rate limit.

Local run:
    uv run --with 'gradio[mcp]>=6,<7' --with httpx app.py

Environment:
    OPENALEX_API_KEY     optional fallback key, sent as the `api_key` query parameter
    GRADIO_SERVER_NAME   bind address (default 0.0.0.0)
    GRADIO_SERVER_PORT   port (default 7860)
    GRADIO_MCP_SERVER    "false" disables the demo MCP endpoint (default true)
"""

from __future__ import annotations

import os
from typing import Optional

import gradio as gr
import httpx

# ── Configuration ─────────────────────────────────────────────────────────────

# The environment is the *fallback* layer only. Every request resolves its own
# key on top of it; this is never mutated.
ENV_API_KEY = os.environ.get("OPENALEX_API_KEY", "")

# What an MCP client sends to use its own key for one call. Gradio injects a
# `gr.Header`-typed argument from the request headers, keeps it out of the tool's
# input schema — so a model never holds the key — and advertises it under
# `meta.headers` at /gradio_api/mcp/schema so a client knows to send it.
MCP_HEADERS = ("X-Openalex-Api-Key",)

OPENALEX_BASE = "https://api.openalex.org"
OPENALEX_WORKS = f"{OPENALEX_BASE}/works"
OPENALEX_AUTHORS = f"{OPENALEX_BASE}/authors"
OPENALEX_INSTITUTIONS = f"{OPENALEX_BASE}/institutions"
OPENALEX_TEXT = f"{OPENALEX_BASE}/text"

SELECT_FIELDS = ",".join([
    "id", "title", "authorships", "doi", "publication_date", "publication_year",
    "primary_location", "best_oa_location", "open_access", "cited_by_count", "type",
])

SORT_OPTIONS = (
    "publication_date:desc",
    "publication_date:asc",
    "cited_by_count:desc",
    "relevance_score:desc",
)

# A Space has no command line: connector policy is constant here.
REQUEST_TIMEOUT = 20.0

# Clamped harder than the canonical server (which allows 200): this endpoint is
# public and every call spends the operator's OpenAlex budget.
MAX_RESULTS = 10

# `search.semantic` truncates beyond 2000 characters before embedding, caps at
# 50 results (the canonical server's limit) and reports `meta.count: 50` on every
# response — a cap, not a corpus count, hence `total_found: null`. It also
# rejects `from_publication_date` / `to_publication_date`, so this tool bounds by
# `publication_year` and names its arguments `year_from` / `year_to`.
SEMANTIC_MAX_CHARS = 2000

# One module-level pooled client for the process.
HTTP = httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True)


def _key(api_key: str | None) -> str:
    """This request's key: the one supplied, else the deployment's, else none."""
    return (api_key or "").strip() or ENV_API_KEY


def _get(url: str, params: dict, api_key: str | None = None) -> tuple[dict | None, str | None]:
    """GET returning (payload, error). Never raises — the demo answers with data."""
    request_params = dict(params)
    key = _key(api_key)
    if key:
        request_params["api_key"] = key
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


# ── ID resolution ─────────────────────────────────────────────────────────────


def _resolve_author_id(name_or_orcid: str, api_key: str | None = None) -> str | None:
    """Resolve an author name or ORCID to an OpenAlex author ID, or None."""
    if "orcid.org" in name_or_orcid or name_or_orcid.startswith("0000-"):
        orcid = (name_or_orcid if name_or_orcid.startswith("https://")
                 else f"https://orcid.org/{name_or_orcid}")
        data, _ = _get(f"{OPENALEX_AUTHORS}/{orcid}", {}, api_key)
        if not data:
            return None
        return (data.get("id", "") or "").replace("https://openalex.org/", "") or None

    data, _ = _get(OPENALEX_AUTHORS, {"search": name_or_orcid, "per-page": 1}, api_key)
    results = (data or {}).get("results", [])
    resolved = (results[0].get("id") or "").replace("https://openalex.org/", "") if results else ""
    return resolved or None


def _resolve_institution_id(name_or_ror: str, api_key: str | None = None) -> str | None:
    """Resolve an institution name or ROR URL to an OpenAlex institution ID, or None."""
    if "ror.org" in name_or_ror:
        data, _ = _get(f"{OPENALEX_INSTITUTIONS}/{name_or_ror}", {}, api_key)
        if not data:
            return None
        return (data.get("id", "") or "").replace("https://openalex.org/", "") or None

    data, _ = _get(OPENALEX_INSTITUTIONS, {"search": name_or_ror, "per-page": 1}, api_key)
    results = (data or {}).get("results", [])
    resolved = (results[0].get("id") or "").replace("https://openalex.org/", "") if results else ""
    return resolved or None


# ── Core operations (shared by the UI and the MCP tools) ──────────────────────


def _search_works(
    api_key: str | None,
    query: str,
    max_results: int = 5,
    date_from: str | None = None,
    date_to: str | None = None,
    filter_open_access: bool = False,
    sort_by: str = "publication_date:desc",
    author: str | None = None,
    institution: str | None = None,
) -> dict:
    out: dict = {"source": "openalex", "command": "search_works",
                 "total_found": 0, "returned": 0, "results": [],
                 "query_used": query, "filters_used": [], "error": None}

    if not (query or "").strip():
        out["error"] = "query is required"
        return out

    filters: list[str] = []
    if date_from:
        filters.append(f"from_publication_date:{date_from}")
    if date_to:
        filters.append(f"to_publication_date:{date_to}")
    if filter_open_access:
        filters.append("is_oa:true")

    if author:
        author_id = _resolve_author_id(author, api_key)
        if not author_id:
            out["error"] = f"Author not found in OpenAlex: '{author}'"
            out["filters_used"] = filters
            return out
        filters.append(f"authorships.author.id:{author_id}")

    if institution:
        inst_id = _resolve_institution_id(institution, api_key)
        if not inst_id:
            out["error"] = f"Institution not found in OpenAlex: '{institution}'"
            out["filters_used"] = filters
            return out
        filters.append(f"authorships.institutions.id:{inst_id}")

    params: dict = {
        "search": query,
        "per-page": max(1, min(int(max_results or 5), MAX_RESULTS)),
        "sort": sort_by if sort_by in SORT_OPTIONS else "publication_date:desc",
        "select": SELECT_FIELDS,
    }
    if filters:
        params["filter"] = ",".join(filters)

    out["filters_used"] = filters

    data, error = _get(OPENALEX_WORKS, params, api_key)
    if error:
        out["error"] = error
        return out

    results = data.get("results", [])
    out["total_found"] = (data.get("meta") or {}).get("count", 0)
    out["returned"] = len(results)
    out["results"] = [_format_work(r) for r in results]
    return out


def _semantic_year_filter(year_from: int | None, year_to: int | None) -> str | None:
    """Year bound as a `publication_year` filter. OpenAlex's `>` and `<` are
    exclusive, hence the one-year offset."""
    if year_from and year_to:
        return f"publication_year:{year_from}-{year_to}"
    if year_from:
        return f"publication_year:>{year_from - 1}"
    if year_to:
        return f"publication_year:<{year_to + 1}"
    return None


def _search_semantic(
    api_key: str | None,
    text: str,
    max_results: int = 5,
    year_from: int | None = None,
    year_to: int | None = None,
    filter_open_access: bool = False,
) -> dict:
    out: dict = {"source": "openalex", "command": "search_semantic",
                 "total_found": None, "returned": 0, "results": [],
                 "query_used": (text or "").strip()[:SEMANTIC_MAX_CHARS],
                 "filters_used": [], "truncated": False,
                 "cost_usd": None, "error": None}

    text = (text or "").strip()
    if len(text) < 20:
        out["error"] = "Text too short (minimum 20 characters)"
        return out
    out["truncated"] = len(text) > SEMANTIC_MAX_CHARS

    filters: list[str] = []
    year_filter = _semantic_year_filter(year_from, year_to)
    if year_filter:
        filters.append(year_filter)
    if filter_open_access:
        filters.append("is_oa:true")
    out["filters_used"] = filters

    params: dict = {
        "search.semantic": text[:SEMANTIC_MAX_CHARS],
        "per-page": max(1, min(int(max_results or 5), MAX_RESULTS)),
        "select": SELECT_FIELDS + ",relevance_score",
    }
    if filters:
        params["filter"] = ",".join(filters)

    data, error = _get(OPENALEX_WORKS, params, api_key)
    if error:
        out["error"] = error
        return out

    results = []
    for work in data.get("results", []):
        record = _format_work(work)
        record["relevance_score"] = work.get("relevance_score")
        results.append(record)
    out["returned"] = len(results)
    out["results"] = results
    out["cost_usd"] = (data.get("meta") or {}).get("cost_usd")
    return out


def _classify_text(api_key: str | None, text: str) -> dict:
    out: dict = {"source": "openalex", "command": "classify_text",
                 "total_found": 0, "returned": 0, "results": [],
                 "keywords": [], "error": None}

    text = (text or "").strip()
    if len(text) < 20:
        out["error"] = "Text too short (minimum 20 characters)"
        return out

    data, error = _get(OPENALEX_TEXT, {"title": text[:2000]}, api_key)
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


# ── MCP tools (the only functions exposed with gr.api) ────────────────────────
#
# `x_openalex_api_key` is a request header, not a tool argument: Gradio fills it
# from the incoming HTTP request, hides it from the input schema, and advertises
# it under `meta.headers`. It is how an MCP client spends its own OpenAlex quota
# without the model ever seeing the credential.


def search_works(
    query: str,
    max_results: int = 5,
    date_from: str | None = None,
    date_to: str | None = None,
    filter_open_access: bool = False,
    sort_by: str = "publication_date:desc",
    author: str | None = None,
    institution: str | None = None,
    x_openalex_api_key: Optional[gr.Header] = None,
) -> dict:
    """
    Search OpenAlex for academic works by keyword query.

    Calls run on the anonymous pool unless an X-Openalex-Api-Key request header is
    sent, or the deployment configured a key of its own.

    Args:
        query: Free-text search over title, abstract and full text, e.g. "multilingual subject indexing".
        max_results: Number of works to return, 1-10 on this demo endpoint.
        date_from: Earliest publication date, inclusive, as YYYY-MM-DD. Empty for no lower bound.
        date_to: Latest publication date, inclusive, as YYYY-MM-DD. Empty for no upper bound.
        filter_open_access: Keep only works with an open-access full text.
        sort_by: Result order, e.g. "publication_date:desc", "cited_by_count:desc" or "relevance_score:desc".
        author: Author name or ORCID, resolved to an OpenAlex id before filtering. Empty for any author.
        institution: Institution name or ROR URL, resolved to an OpenAlex id before filtering. Empty for any.

    Returns:
        {"source": "openalex", "command": "search_works", "total_found": int, "returned": int, "query_used": str, "filters_used": [str], "results": [{"source": "openalex", "id": str, "title": str, "authors": [str], "doi": str | null, "url": str, "year": int | null, "journal": str | null}], "error": str | null}
    """
    return _search_works(x_openalex_api_key, query, max_results, date_from, date_to,
                         filter_open_access, sort_by, author, institution)


def search_semantic(
    text: str,
    max_results: int = 5,
    year_from: int | None = None,
    year_to: int | None = None,
    filter_open_access: bool = False,
    x_openalex_api_key: Optional[gr.Header] = None,
) -> dict:
    """
    Search OpenAlex by meaning rather than by keyword.

    Ranks works by semantic proximity to a descriptive text, so a paper matches even when it shares none of the words used to ask for it. Give it a sentence or a whole abstract, not two keywords. Use search_works instead when a keyword genuinely names the subject.

    Three limits come from the endpoint: no paging past the result cap, "total_found" always null because OpenAlex reports the cap and not a count, and date bounds expressed as years — the from/to dates search_works accepts are rejected here.

    Calls run on the anonymous pool unless an X-Openalex-Api-Key request header is
    sent, or the deployment configured a key of its own.

    Args:
        text: Descriptive text or abstract to match on, minimum 20 characters, truncated at 2000.
        max_results: Number of works to return, 1-10 on this demo endpoint.
        year_from: Earliest publication year, inclusive. Empty for no lower bound.
        year_to: Latest publication year, inclusive. Empty for no upper bound.
        filter_open_access: Keep only works with an open-access full text.

    Returns:
        {"source": "openalex", "command": "search_semantic", "total_found": null, "returned": int, "query_used": str, "filters_used": [str], "truncated": bool, "cost_usd": float | null, "results": [{"source": "openalex", "id": str, "title": str, "authors": [str], "doi": str | null, "url": str, "year": int | null, "journal": str | null, "relevance_score": float | null}], "error": str | null}
    """
    return _search_semantic(x_openalex_api_key, text, max_results, year_from,
                            year_to, filter_open_access)


def classify_text(
    text: str,
    x_openalex_api_key: Optional[gr.Header] = None,
) -> dict:
    """
    Classify a title or abstract into OpenAlex topics, fields and keywords.

    Calls run on the anonymous pool unless an X-Openalex-Api-Key request header is
    sent, or the deployment configured a key of its own.

    Args:
        text: Title or abstract to classify, minimum 20 characters, truncated at 2000.

    Returns:
        {"source": "openalex", "command": "classify_text", "total_found": int, "returned": int, "results": [{"name": str, "score": float, "field": str | null, "domain": str | null}], "keywords": [str], "error": str | null}
    """
    return _classify_text(x_openalex_api_key, text)


# ── Presentation ──────────────────────────────────────────────────────────────


def _render_works(payload: dict) -> str:
    results = payload.get("results") or []
    if not results:
        return "_No work matched this query._"
    # Semantic results carry a score, and no total: OpenAlex reports the result
    # cap there rather than a count, so there is nothing honest to put after "of".
    scored = any(r.get("relevance_score") is not None for r in results)
    total = payload.get("total_found")
    header = (f"**{payload.get('returned', len(results))} works**" if total is None
              else f"**{payload.get('returned', len(results))} of {total} works**")
    lines = [
        header,
        "",
        "| Year | Title | Authors | Journal | DOI |" + (" Score |" if scored else ""),
        "|---|---|---|---|---|" + ("---|" if scored else ""),
    ]
    for r in results:
        names = r.get("authors") or []
        authors = ", ".join(names[:3]) or "—"
        if len(names) > 3:
            authors += " et al."
        doi = r.get("doi")
        score = r.get("relevance_score")
        lines.append(
            "| {year} | [{title}]({url}) | {authors} | {journal} | {doi} |".format(
                year=r.get("year") or "—",
                title=(r.get("title") or "Untitled").replace("|", "\\|"),
                url=r.get("url") or "",
                authors=authors.replace("|", "\\|"),
                journal=(r.get("journal") or "—").replace("|", "\\|"),
                doi=f"[{doi}](https://doi.org/{doi})" if doi else "—",
            )
            + (f" {score:.3f} |" if scored and isinstance(score, (int, float))
               else " — |" if scored else "")
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


def _summarize_config(api_key) -> str:
    """
    Describe the key a call would use. Reported as present or absent, never
    echoed — not even partially.
    """
    if (api_key or "").strip():
        return "> ✅ Using the key typed above — your own OpenAlex quota."
    if ENV_API_KEY:
        return "> ✅ Using this deployment's key — you share the operator's quota."
    return (
        "> ℹ️ No key: calls go to the **anonymous pool**, which is rate-limited and "
        "slower under load. Paste a key above to use your own."
    )


def _run_search(api_key, query, max_results, date_from, date_to, open_access,
                sort_by, author, institution):
    payload = _search_works(
        api_key,
        query,
        max_results,
        (date_from or "").strip() or None,
        (date_to or "").strip() or None,
        open_access,
        sort_by,
        (author or "").strip() or None,
        (institution or "").strip() or None,
    )
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render_works(payload), payload


def _run_semantic(api_key, text, max_results, year_from, year_to, open_access):
    payload = _search_semantic(
        api_key,
        text,
        max_results,
        int(year_from) if year_from else None,
        int(year_to) if year_to else None,
        open_access,
    )
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render_works(payload), payload


def _run_classify(api_key, text: str):
    payload = _classify_text(api_key, text)
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render_topics(payload), payload


# ── UI ────────────────────────────────────────────────────────────────────────

with gr.Blocks(title="OpenAlex MCP demo") as demo:
    gr.Markdown(
        "# OpenAlex MCP demo\n"
        "Standalone demo of the [`openalex`](https://github.com/smartbiblia-solutions/agentic-stack/tree/main/mcp/openalex) "
        "MCP server over ~250M scholarly works."
    )

    with gr.Tab("Configuration"):
        gr.Markdown(
            "The MCP server reads its key from the environment. A Space has no "
            "`.env`, so set it here — it applies to your browser session only. "
            "OpenAlex works without a key; one only buys a higher rate limit."
        )
        api_key_in = gr.Textbox(
            label="OpenAlex API key (optional)",
            type="password",
            value="",  # never pre-filled from the environment: it is the operator's secret
            placeholder=("leave blank to use this deployment's key" if ENV_API_KEY
                         else "leave blank to use the anonymous pool"),
            info="Sent only to api.openalex.org. Never stored, logged or returned.",
        )
        config_btn = gr.Button("Check configuration", variant="primary")
        config_out = gr.Markdown()

        gr.Markdown(
            "**Calling this Space over MCP** — an MCP client sends the key as a "
            "request header on `/gradio_api/mcp/`, so it travels in the transport "
            "and never becomes a tool argument the model can see:\n\n"
            "```\n" + "\n".join(f"{h}: …" for h in MCP_HEADERS) + "\n```\n"
            "It is listed under `meta.headers` at `/gradio_api/mcp/schema`."
        )

    with gr.Tab("Search works"):
        query = gr.Textbox(label="Query", placeholder="multilingual subject indexing")
        with gr.Row():
            max_results = gr.Slider(1, MAX_RESULTS, value=5, step=1, label="Results")
            sort_by = gr.Dropdown(list(SORT_OPTIONS), value="publication_date:desc", label="Sort by")
            open_access = gr.Checkbox(label="Open access only", value=False)
        with gr.Row():
            date_from = gr.Textbox(label="Published from (YYYY-MM-DD)", placeholder="2020-01-01")
            date_to = gr.Textbox(label="Published to (YYYY-MM-DD)", placeholder="2024-12-31")
        with gr.Row():
            author = gr.Textbox(label="Author (name or ORCID)", placeholder="0000-0002-1825-0097")
            institution = gr.Textbox(label="Institution (name or ROR URL)", placeholder="Sorbonne Université")
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
            inputs=[api_key_in, query, max_results, date_from, date_to, open_access,
                    sort_by, author, institution],
            outputs=[works_out, works_raw],
            api_name=False,
        )

    with gr.Tab("Semantic search"):
        gr.Markdown(
            "Matches on **meaning**, not on words: describe the subject in a "
            "sentence, or paste a whole abstract. There is no total — OpenAlex "
            "returns a ranked cap, not a count — and the date bounds are years, "
            "which is all this endpoint accepts."
        )
        sem_text = gr.Textbox(
            label="Describe the subject, or paste an abstract",
            lines=4,
            placeholder="Methods for automatically assigning subject headings to "
                        "library catalogue records using neural language models",
        )
        with gr.Row():
            sem_max = gr.Slider(1, MAX_RESULTS, value=5, step=1, label="Results")
            sem_year_from = gr.Number(label="From year", precision=0, value=None)
            sem_year_to = gr.Number(label="To year", precision=0, value=None)
            sem_oa = gr.Checkbox(label="Open access only", value=False)
        sem_btn = gr.Button("Search by meaning", variant="primary")
        sem_out = gr.Markdown()
        sem_raw = gr.JSON(label="Raw tool output")

        gr.Examples(
            examples=[
                ["Deciding whether a citation to a retracted paper endorses it or "
                 "flags it as an example of research misconduct", 5],
                ["too short", 3],
            ],
            inputs=[sem_text, sem_max],
            label="A description the endpoint can embed, and an input it rejects",
        )
        sem_btn.click(
            _run_semantic,
            inputs=[api_key_in, sem_text, sem_max, sem_year_from, sem_year_to, sem_oa],
            outputs=[sem_out, sem_raw],
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
            _run_classify, inputs=[api_key_in, text],
            outputs=[topics_out, topics_raw], api_name=False,
        )

    config_btn.click(_summarize_config, inputs=api_key_in, outputs=config_out, api_name=False)
    demo.load(_summarize_config, inputs=api_key_in, outputs=config_out, api_name=False)

    # The only declared MCP tools. Names match the canonical server's.
    gr.api(search_works, api_name="search_works")
    gr.api(search_semantic, api_name="search_semantic")
    gr.api(classify_text, api_name="classify_text")


if __name__ == "__main__":
    demo.launch(
        theme=gr.themes.Soft(),  # Gradio 6 moved theme from Blocks() to launch()
        server_name=os.getenv("GRADIO_SERVER_NAME", "0.0.0.0"),
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
        mcp_server=os.getenv("GRADIO_MCP_SERVER", "true").lower() == "true",
    )
