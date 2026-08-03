#!/usr/bin/env python3
"""
Standalone Gradio demo of the Primo MCP server, deployable as a Hugging Face Space.

This app imports nothing from the parent folder: the Space root is this folder,
so `mcp_server.py` does not exist there. It re-implements two of the server's
tools — `search_catalog` and `get_record` — against the same Primo REST
endpoints, under the same names, with the same argument names and the same
response shape.

The canonical MCP endpoint remains `../mcp_server.py`. These tools are a
hand-kept copy: change one, change the other.

Unlike the server, a missing credential does not stop the process: the app
starts, shows a banner and answers every call with an `error` payload.

Local run:
    uv run --with 'gradio[mcp]>=6,<7' --with httpx app.py

Environment:
    PRIMO_API_KEY        Primo API key (required for any live call)
    PRIMO_VID            view id, e.g. INST:VIEW (required)
    PRIMO_SCOPE          search scope (required)
    PRIMO_TAB            tab name (optional)
    PRIMO_REGION         gateway region: na eu ap ca cn (default na)
    PRIMO_BASE_URL       full gateway base URL, overrides PRIMO_REGION
    PRIMO_INST           institution code (on-premise Primo only)
    PRIMO_LANG           UI language (default en)
    GRADIO_SERVER_NAME   bind address (default 0.0.0.0)
    GRADIO_SERVER_PORT   port (default 7860)
    GRADIO_MCP_SERVER    "false" disables the demo MCP endpoint (default true)
"""

from __future__ import annotations

import os
import re
from typing import Any

import gradio as gr
import httpx

# ── Configuration ─────────────────────────────────────────────────────────────

REGION_HOSTS = {
    "na": "https://api-na.hosted.exlibrisgroup.com",
    "eu": "https://api-eu.hosted.exlibrisgroup.com",
    "ap": "https://api-ap.hosted.exlibrisgroup.com",
    "ca": "https://api-ca.hosted.exlibrisgroup.com",
    "cn": "https://api-cn.hosted.exlibrisgroup.com.cn",
}

API_KEY = os.environ.get("PRIMO_API_KEY", "")
DEFAULT_VID = os.environ.get("PRIMO_VID", "")
DEFAULT_SCOPE = os.environ.get("PRIMO_SCOPE", "")
DEFAULT_TAB = os.environ.get("PRIMO_TAB", "")
DEFAULT_INST = os.environ.get("PRIMO_INST", "")
DEFAULT_LANG = os.environ.get("PRIMO_LANG", "en")

BASE_URL = (
    os.environ.get("PRIMO_BASE_URL", "").rstrip("/")
    or REGION_HOSTS.get(os.environ.get("PRIMO_REGION", "na").lower(), REGION_HOSTS["na"])
)

Q_FIELDS = ("any", "title", "creator", "sub", "usertag")
Q_PRECISIONS = ("contains", "exact", "begins_with")
SORT_OPTIONS = ("rank", "title", "author", "date", "date_d", "date_a")

# A Space has no command line: connector policy is constant here.
REQUEST_TIMEOUT = 25.0

# Clamped harder than the canonical server (which allows 50): this endpoint is
# public and every call spends the operator's Primo API quota.
MAX_RESULTS = 10

# The API key never leaves this process: it goes into the query string of an
# outgoing request and is never echoed into a payload or an error message.
CONFIGURED = bool(API_KEY and DEFAULT_VID and DEFAULT_SCOPE)

MISSING_CONFIG = (
    "This deployment has no Primo credentials. Set PRIMO_API_KEY, PRIMO_VID and "
    "PRIMO_SCOPE (and PRIMO_TAB if your view needs one) in the Space settings."
)

# One module-level pooled client for the process.
HTTP = httpx.Client(
    timeout=REQUEST_TIMEOUT,
    follow_redirects=True,
    headers={"Accept": "application/json"},
)


def _get(url: str, params: dict) -> tuple[dict | None, str | None]:
    """GET returning (payload, error). Never raises — the demo answers with data."""
    try:
        resp = HTTP.get(url, params=params)
        if resp.status_code in (401, 403):
            return None, (
                f"Primo returned HTTP {resp.status_code} (unauthorized). Check the API "
                f"key and that vid/scope/tab belong to its institution."
            )
        resp.raise_for_status()
        return resp.json(), None
    except httpx.HTTPStatusError as exc:
        return None, f"Primo returned HTTP {exc.response.status_code}"
    except httpx.TimeoutException:
        return None, f"Primo timed out after {REQUEST_TIMEOUT:g}s"
    except Exception as exc:  # noqa: BLE001 - never crash the Space
        return None, f"cannot reach Primo: {exc}"


def _base_params() -> dict[str, Any]:
    params: dict[str, Any] = {
        "vid": DEFAULT_VID,
        "scope": DEFAULT_SCOPE,
        "lang": DEFAULT_LANG,
        "apikey": API_KEY,
    }
    if DEFAULT_TAB:
        params["tab"] = DEFAULT_TAB
    if DEFAULT_INST:
        params["inst"] = DEFAULT_INST
    return params


# ── query building ────────────────────────────────────────────────────────────


def _build_q(query: str, field: str, precision: str = "contains") -> str:
    field = field if field in Q_FIELDS else "any"
    precision = precision if precision in Q_PRECISIONS else "contains"
    return f"{field},{precision},{query.replace(';', ' ').strip()}"


def _build_qinclude(facets: list[tuple[str, str]]) -> str | None:
    clauses = [f"{cat},exact,{val}" for cat, val in facets if cat and val]
    return "|,|".join(clauses) if clauses else None


# ── PNX parsing ───────────────────────────────────────────────────────────────


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    return (value.split("$$", 1)[0].strip()) or None


def _first(d: dict, *keys: str) -> str | None:
    for k in keys:
        vals = d.get(k)
        if isinstance(vals, str):
            vals = [vals]
        if not isinstance(vals, list):
            continue
        for v in vals:
            cleaned = _clean(v) if isinstance(v, str) else None
            if cleaned:
                return cleaned
    return None


def _all(d: dict, *keys: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for k in keys:
        vals = d.get(k)
        if isinstance(vals, str):
            vals = [vals]
        if not isinstance(vals, list):
            continue
        for v in vals:
            if not isinstance(v, str):
                continue
            for piece in v.split(";"):
                cleaned = _clean(piece)
                if cleaned and cleaned not in seen:
                    seen.add(cleaned)
                    out.append(cleaned)
    return out


def _extract_year(*candidates: str | None) -> int | None:
    for c in candidates:
        if not c:
            continue
        m = re.search(r"\b(1[0-9]{3}|20[0-9]{2})\b", c)
        if m:
            return int(m.group(1))
    return None


def _format_doc(doc: dict) -> dict:
    """Map one Primo PNX document onto the record shape the server returns."""
    pnx = doc.get("pnx", {}) or {}
    display = pnx.get("display", {}) or {}
    addata = pnx.get("addata", {}) or {}
    control = pnx.get("control", {}) or {}
    links = pnx.get("links", {}) or {}
    delivery = doc.get("delivery", {}) or {}

    return {
        "source": "primo",
        "record_id": _first(control, "recordid"),
        "title": _first(display, "title"),
        "authors": _all(addata, "au") or _all(display, "creator"),
        "contributors": _all(display, "contributor"),
        "year": _extract_year(_first(addata, "date"), _first(display, "creationdate")),
        "date": _first(addata, "date") or _first(display, "creationdate"),
        "publisher": _first(addata, "pub") or _first(display, "publisher"),
        "pub_place": _first(addata, "cop"),
        "doc_type": _first(display, "type"),
        "format": _first(display, "format"),
        "language": _first(display, "language") or _first(addata, "lang"),
        "isbn": _first(addata, "isbn"),
        "issn": _first(addata, "issn") or _first(addata, "eissn"),
        "doi": _first(addata, "doi"),
        "journal": _first(addata, "jtitle"),
        "is_part_of": _first(display, "ispartof"),
        "subjects": _all(display, "subject") or _all(addata, "subject"),
        "abstract": _first(addata, "abstract") or _first(display, "description"),
        "source_system": _first(control, "sourceid"),
        "source_record_id": _first(control, "sourcerecordid"),
        "link_to_resource": _first(links, "linktorsrc"),
        "openurl": _first(links, "openurl"),
        "thumbnail": _first(links, "thumbnail"),
        "availability": _all(delivery, "deliveryCategory") or _all(delivery, "availability"),
        "context": doc.get("context"),
        "record_url": doc.get("@id"),
    }


# ── MCP tools (the only functions exposed with gr.api) ────────────────────────


def search_catalog(
    query: str,
    field: str = "any",
    max_results: int = 5,
    resource_type: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
) -> dict:
    """
    Search an Ex Libris Primo discovery layer (library catalogue and discovery index).

    Args:
        query: Free-text search terms, e.g. "histoire de la lecture".
        field: Field searched — any, title, creator, sub (subject) or usertag.
        max_results: Number of records to return, 1-10 on this demo endpoint.
        resource_type: Resource-type facet, e.g. books, articles, journals. Empty for all types.
        year_from: Earliest creation year, inclusive. Empty for no lower bound.
        year_to: Latest creation year, inclusive. Empty for no upper bound.

    Returns:
        {"source": "primo", "command": "search_catalog", "total_found": int, "returned": int, "query_used": str, "results": [{"source": "primo", "record_id": str, "title": str, "authors": [str], "year": int | null, "publisher": str | null, "doc_type": str | null, "record_url": str | null}], "error": str | null}
    """
    out: dict = {"source": "primo", "command": "search_catalog",
                 "total_found": 0, "returned": 0, "query_used": "",
                 "results": [], "error": None}

    if not CONFIGURED:
        out["error"] = MISSING_CONFIG
        return out
    if not (query or "").strip():
        out["error"] = "query is required"
        return out

    facets: list[tuple[str, str]] = []
    if resource_type:
        facets.append(("facet_rtype", resource_type))
    if year_from is not None or year_to is not None:
        start = str(year_from) if year_from is not None else "*"
        end = str(year_to) if year_to is not None else "*"
        facets.append(("facet_searchcreationdate", f"[{start} TO {end}]"))

    params = _base_params()
    params.update({
        "q": _build_q(query, field or "any"),
        "offset": 0,
        "limit": max(1, min(int(max_results or 5), MAX_RESULTS)),
        "sort": "rank",
        "pcAvailability": "true",
    })
    qinc = _build_qinclude(facets)
    if qinc:
        params["qInclude"] = qinc
    out["query_used"] = params["q"]

    data, error = _get(f"{BASE_URL}/primo/v1/search", params)
    if error:
        out["error"] = error
        return out

    docs = data.get("docs", []) or []
    info = data.get("info", {}) or {}
    out["total_found"] = info.get("total", info.get("totalResultsLocal", len(docs)))
    out["returned"] = len(docs)
    out["results"] = [_format_doc(d) for d in docs]
    return out


def get_record(record_id: str, context: str = "L") -> dict:
    """
    Fetch one Primo record by its recordid.

    Args:
        record_id: Primo recordid, the control.recordid value returned by search_catalog, e.g. "alma990001234".
        context: "L" for a local institution record, "PC" for a Central Discovery Index record.

    Returns:
        {"source": "primo", "command": "get_record", "total_found": int, "returned": int, "results": [<same record shape as search_catalog>], "error": str | null}
    """
    out: dict = {"source": "primo", "command": "get_record",
                 "total_found": 0, "returned": 0, "results": [], "error": None}

    if not CONFIGURED:
        out["error"] = MISSING_CONFIG
        return out
    record_id = (record_id or "").strip()
    if not record_id:
        out["error"] = "record_id is required"
        return out

    ctx = (context or "L").upper()
    data, error = _get(f"{BASE_URL}/primo/v1/pnxs/{ctx}/{record_id}", _base_params())
    if error:
        out["error"] = f"Record not found in Primo: '{record_id}' ({error})"
        return out

    doc = data
    if isinstance(data.get("docs"), list):
        doc = data["docs"][0] if data["docs"] else None
    if not doc or "pnx" not in doc:
        out["error"] = f"Record not found in Primo: '{record_id}'"
        return out

    out["total_found"] = 1
    out["returned"] = 1
    out["results"] = [_format_doc(doc)]
    return out


# ── Presentation ──────────────────────────────────────────────────────────────


def _render(payload: dict) -> str:
    results = payload.get("results") or []
    if not results:
        return "_No record matched._"
    lines = [
        f"**{payload.get('returned', len(results))} of {payload.get('total_found', '?')} records**",
        "",
        "| Year | Title | Authors | Type | Record id |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        names = r.get("authors") or []
        authors = ", ".join(names[:3]) or "—"
        if len(names) > 3:
            authors += " et al."
        lines.append(
            "| {year} | {title} | {authors} | {doc_type} | `{rid}` |".format(
                year=r.get("year") or "—",
                title=(r.get("title") or "Untitled").replace("|", "\\|"),
                authors=authors.replace("|", "\\|"),
                doc_type=(r.get("doc_type") or "—").replace("|", "\\|"),
                rid=r.get("record_id") or "—",
            )
        )
    return "\n".join(lines)


def _run_search(query, field, max_results, resource_type, year_from, year_to):
    payload = search_catalog(
        query,
        field,
        max_results,
        resource_type or None,
        int(year_from) if year_from else None,
        int(year_to) if year_to else None,
    )
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render(payload), payload


def _run_record(record_id, context):
    payload = get_record(record_id, context)
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render(payload), payload


# ── UI ────────────────────────────────────────────────────────────────────────

with gr.Blocks(title="Primo MCP demo") as demo:
    gr.Markdown(
        "# Primo MCP demo\n"
        "Standalone demo of the [`primo`](https://github.com/smartbiblia-solutions/agentic-stack/tree/main/mcp/primo) "
        "MCP server — search one institution's Ex Libris Primo discovery layer. "
        "The canonical MCP endpoint is `mcp_server.py` in that folder; this Space "
        "re-implements two of its tools and re-exposes them at "
        "`/gradio_api/mcp/sse` for clients that cannot run it."
    )

    if not CONFIGURED:
        gr.Markdown(
            "> ⚠️ **Not configured.** " + MISSING_CONFIG + " Until then every call "
            "returns an `error` payload — the app runs, it just has nothing to query."
        )

    with gr.Tab("Search the catalogue"):
        query = gr.Textbox(label="Query", placeholder="histoire de la lecture")
        with gr.Row():
            field = gr.Dropdown(list(Q_FIELDS), value="any", label="Field")
            max_results = gr.Slider(1, MAX_RESULTS, value=5, step=1, label="Results")
        with gr.Row():
            resource_type = gr.Textbox(label="Resource type (facet)", placeholder="books")
            year_from = gr.Number(label="Year from", precision=0, value=None)
            year_to = gr.Number(label="Year to", precision=0, value=None)
        search_btn = gr.Button("Search", variant="primary")
        search_out = gr.Markdown()
        search_raw = gr.JSON(label="Raw tool output")

        gr.Examples(
            examples=[
                ["histoire de la lecture", "any", 5, "books", None, None],
                ["qzxwv titre inexistant", "title", 3, "", None, None],
            ],
            inputs=[query, field, max_results, resource_type, year_from, year_to],
            label="A hit, and a query that returns nothing",
        )
        search_btn.click(
            _run_search,
            inputs=[query, field, max_results, resource_type, year_from, year_to],
            outputs=[search_out, search_raw],
            api_name=False,
        )

    with gr.Tab("Fetch a record"):
        record_id = gr.Textbox(label="Record id", placeholder="alma990001234")
        context = gr.Radio(["L", "PC"], value="L", label="Context (L = local, PC = CDI)")
        record_btn = gr.Button("Fetch", variant="primary")
        record_out = gr.Markdown()
        record_raw = gr.JSON(label="Raw tool output")

        gr.Examples(
            examples=[["alma990001234", "L"], ["does-not-exist", "L"]],
            inputs=[record_id, context],
            label="A record id from a search above, and one that does not resolve",
        )
        record_btn.click(
            _run_record,
            inputs=[record_id, context],
            outputs=[record_out, record_raw],
            api_name=False,
        )

    # The only declared MCP tools. Names match the canonical server's.
    gr.api(search_catalog, api_name="search_catalog")
    gr.api(get_record, api_name="get_record")


if __name__ == "__main__":
    demo.launch(
        theme=gr.themes.Soft(),  # Gradio 6 moved theme from Blocks() to launch()
        server_name=os.getenv("GRADIO_SERVER_NAME", "0.0.0.0"),
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
        mcp_server=os.getenv("GRADIO_MCP_SERVER", "true").lower() == "true",
    )
