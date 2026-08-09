#!/usr/bin/env python3
"""
Standalone Gradio demo of the Primo MCP server, deployable as a Hugging Face Space.

The credential settings are supplied **per request**, resolved in this order:

    1. the Configuration tab      (browser visitors)
    2. an `X-Primo-*` request header  (MCP clients, see MCP_HEADERS below)
    3. the process environment    (what the Space operator set, if anything)

Unlike the server, a missing credential does not stop the process: the app
starts, shows a banner and answers every call with an `error` payload.

Local run:
    uv run --with 'gradio[mcp]>=6,<7' --with httpx app.py

Environment (all optional — they are only the fallback layer):
    PRIMO_API_KEY        Primo API key
    PRIMO_VID            view id, e.g. INST:VIEW
    PRIMO_SCOPE          search scope
    PRIMO_TAB            tab name
    PRIMO_REGION         gateway region: na eu ap ca cn (default na)
    PRIMO_BASE_URL       full gateway base URL, overrides PRIMO_REGION
    PRIMO_INST           institution code
    PRIMO_LANG           UI language (default en)
    GRADIO_SERVER_NAME   bind address (default 0.0.0.0)
    GRADIO_SERVER_PORT   port (default 7860)
    GRADIO_MCP_SERVER    "false" disables the demo MCP endpoint (default true)
"""

from __future__ import annotations

import os
import re
from typing import Any, Optional

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

# The environment is the *fallback* layer only. Every request resolves its own
# configuration on top of these; none of them is ever mutated.
ENV_API_KEY = os.environ.get("PRIMO_API_KEY", "")
ENV_VID = os.environ.get("PRIMO_VID", "")
ENV_SCOPE = os.environ.get("PRIMO_SCOPE", "")
ENV_TAB = os.environ.get("PRIMO_TAB", "")
ENV_INST = os.environ.get("PRIMO_INST", "")
ENV_LANG = os.environ.get("PRIMO_LANG", "en")
ENV_REGION = os.environ.get("PRIMO_REGION", "na")
ENV_BASE_URL = os.environ.get("PRIMO_BASE_URL", "").rstrip("/")

# What an MCP client sends to override the deployment's settings for one call.
# Gradio injects a `gr.Header`-typed argument from the request headers, keeps it
# out of the tool's input schema — so a model never holds the key — and lists it
# under `meta.headers` at /gradio_api/mcp/schema so a client knows to send it.
MCP_HEADERS = (
    "X-Primo-Api-Key", "X-Primo-Vid", "X-Primo-Tab", "X-Primo-Scope",
    "X-Primo-Inst", "X-Primo-Lang", "X-Primo-Region", "X-Primo-Base-Url",
)

# Bounds a creation year has to fall inside to count as a bound at all.
YEAR_MIN, YEAR_MAX = 1000, 2999

Q_FIELDS = ("any", "title", "creator", "sub", "usertag")
Q_PRECISIONS = ("contains", "exact", "begins_with")
SORT_OPTIONS = ("rank", "title", "author", "date", "date_d", "date_a")
AVAILABILITY_OPTIONS = ("available", "online_resources", "physical_item")

# A Space has no command line: connector policy is constant here.
REQUEST_TIMEOUT = 25.0

# Clamped harder than the canonical server (which allows 50 per page and paging
# to ~2000): this endpoint is public and every call can spend the operator's
# Primo API quota.
MAX_RESULTS = 10
MAX_OFFSET = 200

MISSING_KEY = (
    "No Primo API key for this call. Paste one in the Configuration tab, send it "
    "as the X-Primo-Api-Key header, or set PRIMO_API_KEY in the Space settings."
)

MISSING_TARGET = (
    "Missing {missing}. Set it in the Configuration tab, send it as the "
    "X-Primo-{header} header, or pass it as a tool argument — it must name a view "
    "of the institution the API key is bound to."
)

# One module-level pooled client for the process.
HTTP = httpx.Client(
    timeout=REQUEST_TIMEOUT,
    follow_redirects=True,
    headers={"Accept": "application/json"},
)


# ── Per-request configuration ─────────────────────────────────────────────────


def _cfg(
    api_key: str | None = None,
    vid: str | None = None,
    tab: str | None = None,
    scope: str | None = None,
    inst: str | None = None,
    lang: str | None = None,
    region: str | None = None,
    base_url: str | None = None,
) -> dict[str, str]:
    """
    Resolve one request's configuration: supplied value first, environment second.
    Returned as a plain dict passed down the call chain — never assigned to a
    module global, because one process serves every visitor of the Space.
    """
    def pick(value: str | None, fallback: str) -> str:
        return (value or "").strip() or fallback

    explicit_base = pick(base_url, ENV_BASE_URL).rstrip("/")
    resolved_region = pick(region, ENV_REGION).lower()

    return {
        "api_key": pick(api_key, ENV_API_KEY),
        "vid": pick(vid, ENV_VID),
        "tab": pick(tab, ENV_TAB),
        "scope": pick(scope, ENV_SCOPE),
        "inst": pick(inst, ENV_INST),
        "lang": pick(lang, ENV_LANG) or "en",
        "base_url": explicit_base or REGION_HOSTS.get(resolved_region, REGION_HOSTS["na"]),
    }


def _check(cfg: dict[str, str]) -> str | None:
    """The one error a call cannot proceed past. Never names the key's value."""
    if not cfg["api_key"]:
        return MISSING_KEY
    missing = [n for n in ("vid", "scope") if not cfg[n]]
    if missing:
        return MISSING_TARGET.format(
            missing=" and ".join(missing),
            header="/X-Primo-".join(n.capitalize() for n in missing),
        )
    return None


def _base_params(cfg: dict[str, str]) -> dict[str, Any]:
    params: dict[str, Any] = {
        "vid": cfg["vid"],
        "scope": cfg["scope"],
        "lang": cfg["lang"],
        "apikey": cfg["api_key"],
    }
    if cfg["tab"]:
        params["tab"] = cfg["tab"]
    if cfg["inst"]:
        params["inst"] = cfg["inst"]
    return params


def _redact(params: dict) -> dict:
    """The request as sent, minus the credential — safe to show in the UI."""
    return {k: ("REDACTED" if k == "apikey" else v) for k, v in params.items()}


def _request_url(url: str, params: dict) -> str:
    """
    The exact URL httpx will fetch, with the key redacted — paste it in a browser,
    swap the key back in, and you are comparing like for like.
    """
    return str(httpx.URL(url, params=_redact(params)))


def _get(url: str, params: dict, sink: dict | None = None) -> tuple[dict | None, str | None]:
    """GET returning (payload, error). Never raises — the demo answers with data."""
    if sink is not None:
        sink["request_url"] = _request_url(url, params)
    try:
        resp = HTTP.get(url, params=params)
        if sink is not None:
            sink["http_status"] = resp.status_code
        if resp.status_code in (401, 403):
            return None, (
                f"Primo returned HTTP {resp.status_code} (unauthorized). Check the API "
                f"key and that vid/scope/tab belong to its institution."
            )
        resp.raise_for_status()
        data = resp.json()
        if sink is not None and isinstance(data, dict):
            # What came back, so an empty result set can be told apart from a
            # response this code failed to read.
            sink["response_keys"] = sorted(data)
            sink["response_info"] = data.get("info")
            sink["docs_count"] = len(data.get("docs") or [])
        return data, None
    except httpx.HTTPStatusError as exc:
        return None, f"Primo returned HTTP {exc.response.status_code}"
    except httpx.TimeoutException:
        return None, f"Primo timed out after {REQUEST_TIMEOUT:g}s"
    except Exception as exc:  # noqa: BLE001 - never crash the Space
        return None, f"cannot reach Primo: {exc}"


# ── query building ────────────────────────────────────────────────────────────


def _build_q(query: str, field: str, precision: str = "contains") -> str:
    field = field if field in Q_FIELDS else "any"
    precision = precision if precision in Q_PRECISIONS else "contains"
    return f"{field},{precision},{query.replace(';', ' ').strip()}"


def _build_qinclude(facets: list[tuple[str, str]]) -> str | None:
    clauses = [f"{cat},exact,{val}" for cat, val in facets if cat and val]
    return "|,|".join(clauses) if clauses else None


def _year_bound(value: Any) -> int | None:
    """
    A creation-year bound, or None when there is none.
    An empty `gr.Number(precision=0)` does not always arrive as None — Gradio
    coerces it to `0` — and a model calling the tool can send `0` just as
    easily. Either one used to reach the facet builder as a real bound and
    produce `facet_searchcreationdate,exact,[0 TO 0]`, which Primo applies
    literally: zero records, HTTP 200, no error, nothing to diagnose. Anything
    outside a plausible year means "no bound".
    """
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year if YEAR_MIN <= year <= YEAR_MAX else None


def _parse_facets(raw_facets: Any) -> list[dict]:
    out: list[dict] = []
    if not isinstance(raw_facets, list):
        return out
    for facet in raw_facets:
        if not isinstance(facet, dict):
            continue
        values = [
            {"value": v.get("value"), "count": v.get("count")}
            for v in (facet.get("values") or []) if isinstance(v, dict)
        ]
        out.append({"name": facet.get("name"), "values": values})
    return out


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


# ── Core operations (shared by the UI and the MCP tools) ──────────────────────


def _search(cfg: dict[str, str], query: str, field: str, precision: str,
            max_results: int, offset: int, sort: str,
            resource_type: str | None, language: str | None, library: str | None,
            collection: str | None, availability: str | None,
            year_from: int | None, year_to: int | None,
            full_text_only: bool, return_facets: bool,
            request_sink: dict | None = None) -> dict:
    # `request_sink`, when given, receives the redacted request. The UI fills one
    # and displays it: a search that returns 0 records with no error is otherwise
    # undiagnosable. It is never part of the tool payload, which stays canonical.
    out: dict = {"source": "primo", "command": "search_catalog",
                 "total_found": 0, "returned": 0, "offset": 0,
                 "query_used": "", "vid": cfg["vid"],
                 "results": [], "error": None}

    config_error = _check(cfg)
    if config_error:
        out["error"] = config_error
        return out
    if not (query or "").strip():
        out["error"] = "query is required"
        return out

    facets: list[tuple[str, str]] = []
    if resource_type:
        facets.append(("facet_rtype", resource_type))
    if language:
        facets.append(("facet_lang", language))
    if library:
        facets.append(("facet_library", library))
    if collection:
        facets.append(("facet_domain", collection))
    if availability:
        facets.append(("facet_tlevel", availability))
    start_year, end_year = _year_bound(year_from), _year_bound(year_to)
    if start_year is not None or end_year is not None:
        start = str(start_year) if start_year is not None else "*"
        end = str(end_year) if end_year is not None else "*"
        facets.append(("facet_searchcreationdate", f"[{start} TO {end}]"))

    params = _base_params(cfg)
    params.update({
        "q": _build_q(query, field or "any", precision or "contains"),
        "offset": max(0, min(int(offset or 0), MAX_OFFSET)),
        "limit": max(1, min(int(max_results or 5), MAX_RESULTS)),
        "sort": sort if sort in SORT_OPTIONS else "rank",
        "pcAvailability": "false" if full_text_only else "true",
    })
    qinc = _build_qinclude(facets)
    if qinc:
        params["qInclude"] = qinc
    out["query_used"] = params["q"]
    out["offset"] = params["offset"]

    url = f"{cfg['base_url']}/primo/v1/search"
    if request_sink is not None:
        request_sink["params"] = _redact(params)

    data, error = _get(url, params, request_sink)
    if error:
        out["error"] = error
        return out

    docs = data.get("docs", []) or []
    info = data.get("info", {}) or {}
    out["total_found"] = info.get("total", info.get("totalResultsLocal", len(docs)))
    out["returned"] = len(docs)
    out["results"] = [_format_doc(d) for d in docs]
    if return_facets:
        out["facets"] = _parse_facets(data.get("facets"))
    return out


def _record(cfg: dict[str, str], record_id: str, context: str,
            request_sink: dict | None = None) -> dict:
    out: dict = {"source": "primo", "command": "get_record",
                 "total_found": 0, "returned": 0, "results": [], "error": None}

    config_error = _check(cfg)
    if config_error:
        out["error"] = config_error
        return out
    record_id = (record_id or "").strip()
    if not record_id:
        out["error"] = "record_id is required"
        return out

    ctx = (context or "L").upper()
    params = _base_params(cfg)
    params.pop("tab", None)  # the pnxs endpoint takes no tab
    url = f"{cfg['base_url']}/primo/v1/pnxs/{ctx}/{record_id}"
    if request_sink is not None:
        request_sink["params"] = _redact(params)

    data, error = _get(url, params, request_sink)
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


# ── MCP tools (the only functions exposed with gr.api) ────────────────────────
#
# The `x_primo_*` arguments are request headers, not tool arguments: Gradio fills
# them from the incoming HTTP request, hides them from the input schema, and
# advertises them under `meta.headers`. They are how an MCP client points this
# endpoint at its own Primo without the model ever seeing the credential.


def search_catalog(
    query: str,
    field: str = "any",
    precision: str = "contains",
    max_results: int = 5,
    offset: int = 0,
    sort: str = "rank",
    resource_type: str | None = None,
    language: str | None = None,
    library: str | None = None,
    collection: str | None = None,
    availability: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    full_text_only: bool = False,
    return_facets: bool = False,
    vid: str | None = None,
    tab: str | None = None,
    scope: str | None = None,
    x_primo_api_key: Optional[gr.Header] = None,
    x_primo_vid: Optional[gr.Header] = None,
    x_primo_tab: Optional[gr.Header] = None,
    x_primo_scope: Optional[gr.Header] = None,
    x_primo_inst: Optional[gr.Header] = None,
    x_primo_lang: Optional[gr.Header] = None,
    x_primo_region: Optional[gr.Header] = None,
    x_primo_base_url: Optional[gr.Header] = None,
) -> dict:
    """
    Search an Ex Libris Primo discovery layer (library catalogue and discovery index).
    Primo is institution-scoped. The API key and the gateway come from the
    X-Primo-* request headers listed in this tool's meta.headers, falling back to
    what the deployment configured; the view can also be set per call below.
    Args:
        query: Free-text search terms, e.g. "histoire de la lecture".
        field: Field searched — any, title, creator, sub (subject) or usertag.
        precision: Match precision — contains, exact or begins_with.
        max_results: Number of records to return, 1-10 on this demo endpoint.
        offset: Result offset for paging, 0-200 on this demo endpoint.
        sort: Result order — rank, title, author, date, date_d (newest) or date_a (oldest).
        resource_type: Resource-type facet, e.g. books, articles, journals. Empty for all types.
        language: Language facet, three-letter code, e.g. eng, fre. Empty for all languages.
        library: Holding-library facet, an institution-specific code. Empty for all libraries.
        collection: Collection or domain facet, an institution-specific code. Empty for all.
        availability: Availability facet — available, online_resources or physical_item.
        year_from: Earliest creation year, inclusive. Empty for no lower bound.
        year_to: Latest creation year, inclusive. Empty for no upper bound.
        full_text_only: Keep only records with full text or a holding (pcAvailability=false).
        return_facets: Include the facet buckets Primo returned, under a "facets" key.
        vid: View id (INST:VIEW) to search. Empty uses the X-Primo-Vid header or the deployment default.
        tab: Tab name to search. Empty uses the X-Primo-Tab header or the deployment default.
        scope: Search scope name. Empty uses the X-Primo-Scope header or the deployment default.
    Returns:
        {"source": "primo", "command": "search_catalog", "total_found": int, "returned": int, "offset": int, "query_used": str, "vid": str, "results": [{"source": "primo", "record_id": str, "title": str, "authors": [str], "year": int | null, "publisher": str | null, "doc_type": str | null, "record_url": str | null}], "error": str | null}
    """
    cfg = _cfg(
        api_key=x_primo_api_key,
        vid=vid or x_primo_vid,
        tab=tab or x_primo_tab,
        scope=scope or x_primo_scope,
        inst=x_primo_inst,
        lang=x_primo_lang,
        region=x_primo_region,
        base_url=x_primo_base_url,
    )
    return _search(cfg, query, field, precision, max_results, offset, sort,
                   resource_type, language, library, collection, availability,
                   year_from, year_to, full_text_only, return_facets)


def get_record(
    record_id: str,
    context: str = "L",
    vid: str | None = None,
    scope: str | None = None,
    x_primo_api_key: Optional[gr.Header] = None,
    x_primo_vid: Optional[gr.Header] = None,
    x_primo_scope: Optional[gr.Header] = None,
    x_primo_inst: Optional[gr.Header] = None,
    x_primo_lang: Optional[gr.Header] = None,
    x_primo_region: Optional[gr.Header] = None,
    x_primo_base_url: Optional[gr.Header] = None,
) -> dict:
    """
    Fetch one Primo record by its recordid.
    The API key and the gateway come from the X-Primo-* request headers listed in
    this tool's meta.headers, falling back to what the deployment configured.
    Args:
        record_id: Primo recordid, the control.recordid value returned by search_catalog, e.g. "alma990001234".
        context: "L" for a local institution record, "PC" for a Central Discovery Index record.
        vid: View id (INST:VIEW) to read from. Empty uses the X-Primo-Vid header or the deployment default.
        scope: Search scope name. Empty uses the X-Primo-Scope header or the deployment default.
    Returns:
        {"source": "primo", "command": "get_record", "total_found": int, "returned": int, "results": [<same record shape as search_catalog>], "error": str | null}
    """
    cfg = _cfg(
        api_key=x_primo_api_key,
        vid=vid or x_primo_vid,
        scope=scope or x_primo_scope,
        inst=x_primo_inst,
        lang=x_primo_lang,
        region=x_primo_region,
        base_url=x_primo_base_url,
    )
    return _record(cfg, record_id, context)


# ── Presentation ──────────────────────────────────────────────────────────────


def _render(payload: dict) -> str:
    if payload.get("error"):
        return f"⚠️ **{payload['error']}**"
    results = payload.get("results") or []
    if not results:
        return (
            f"_Primo answered, and matched **{payload.get('total_found', 0)}** records "
            "for this query. Open the debug panel below to see the exact URL sent._"
        )
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
    facets = payload.get("facets")
    if facets:
        lines += ["", "**Facets** — " + ", ".join(
            f"{f.get('name')} ({len(f.get('values') or [])})" for f in facets
        )]
    return "\n".join(lines)


def _num(value) -> int | None:
    """A slider or number box as an int, or None when it carries no usable value."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _summarize_config(api_key, vid, tab, scope, inst, lang, region, base_url) -> str:
    """
    Describe the configuration a call would use. The key is reported as present
    or absent and never echoed — not even partially.
    """
    cfg = _cfg(api_key, vid, tab, scope, inst, lang, region, base_url)
    where = "typed above" if (api_key or "").strip() else (
        "from the Space environment" if ENV_API_KEY else "missing")
    rows = [
        "| Setting | Value |",
        "|---|---|",
        f"| API key | {'✅ set (' + where + ')' if cfg['api_key'] else '❌ ' + where} |",
        f"| Gateway | `{cfg['base_url']}` |",
        f"| View id (vid) | {'`' + cfg['vid'] + '`' if cfg['vid'] else '❌ not set'} |",
        f"| Scope | {'`' + cfg['scope'] + '`' if cfg['scope'] else '❌ not set'} |",
        f"| Tab | {'`' + cfg['tab'] + '`' if cfg['tab'] else '— none'} |",
        f"| Institution code | {'`' + cfg['inst'] + '`' if cfg['inst'] else '— none'} |",
        f"| Language | `{cfg['lang']}` |",
    ]
    problem = _check(cfg)
    rows += ["", f"> ⚠️ {problem}" if problem else "> ✅ Ready to search."]
    return "\n".join(rows)


def _run_search(api_key, cfg_vid, cfg_tab, cfg_scope, cfg_inst, cfg_lang,
                cfg_region, cfg_base_url,
                query, field, precision, max_results, offset, sort, resource_type,
                language, library, collection, availability, year_from, year_to,
                full_text_only, return_facets):
    cfg = _cfg(api_key, cfg_vid, cfg_tab, cfg_scope, cfg_inst, cfg_lang,
               cfg_region, cfg_base_url)
    sent: dict = {}
    payload = _search(
        cfg, query, field, precision, _num(max_results) or 5, _num(offset) or 0, sort,
        resource_type or None, language or None, library or None,
        collection or None, availability or None,
        _num(year_from), _num(year_to), full_text_only, return_facets,
        request_sink=sent,
    )
    # Rendered rather than raised as gr.Error: a raise aborts the outputs, and the
    # debug panel is most needed exactly when the call went wrong.
    return _render(payload), payload, sent


def _run_record(api_key, cfg_vid, cfg_tab, cfg_scope, cfg_inst, cfg_lang,
                cfg_region, cfg_base_url, record_id, context):
    cfg = _cfg(api_key, cfg_vid, cfg_tab, cfg_scope, cfg_inst, cfg_lang,
               cfg_region, cfg_base_url)
    sent: dict = {}
    payload = _record(cfg, record_id, context, request_sink=sent)
    return _render(payload), payload, sent


# ── UI ────────────────────────────────────────────────────────────────────────

with gr.Blocks(title="Primo MCP demo") as demo:
    gr.Markdown(
        "# Primo MCP demo\n"
        "Standalone demo of the [`primo`](https://github.com/smartbiblia-solutions/agentic-stack/tree/main/mcp/primo) "
        "MCP server, search one institution's Ex Libris Primo discovery layer. "
    )

    with gr.Tab("Configuration"):
        gr.Markdown(
            "The MCP server reads these from its environment and its `--region` / "
            "`--vid` / `--tab` / `--scope` flags. A Space has neither, so set them "
            "here — they apply to your browser session only. Anything left blank "
            "falls back to what the Space operator configured."
            + ("" if ENV_API_KEY else
               "\n\n> ⚠️ This deployment ships **no key of its own**: bring your own "
               "Ex Libris key to run anything.")
        )
        api_key_in = gr.Textbox(
            label="Primo API key",
            type="password",
            value="",  # never pre-filled from the environment: it is the operator's secret
            placeholder=("leave blank to use this deployment's key" if ENV_API_KEY
                         else "required — your Ex Libris API key"),
            info="Sent only to the Ex Libris gateway. Never stored, logged or returned.",
        )
        with gr.Row():
            region_in = gr.Dropdown(
                list(REGION_HOSTS), value=(ENV_REGION.lower() if ENV_REGION.lower() in REGION_HOSTS else "na"),
                label="Gateway region",
            )
            base_url_in = gr.Textbox(
                label="Base URL (overrides the region)", value=ENV_BASE_URL,
                placeholder="https://api-eu.hosted.exlibrisgroup.com",
            )
        with gr.Row():
            vid_in = gr.Textbox(label="View id (vid)", value=ENV_VID, placeholder="INST:VIEW")
            tab_in = gr.Textbox(label="Tab", value=ENV_TAB, placeholder="Everything")
            scope_in = gr.Textbox(label="Scope", value=ENV_SCOPE, placeholder="MyInst_and_CI")
        with gr.Row():
            inst_in = gr.Textbox(
                label="Institution code (inst)", value=ENV_INST,
                placeholder="MyUni",
                info="The institution code configured in the Primo Back Office.",
            )
            lang_in = gr.Textbox(label="Interface language", value=ENV_LANG, placeholder="en")

        config_btn = gr.Button("Check configuration", variant="primary")
        config_out = gr.Markdown()

        gr.Markdown(
            "**Calling this Space over MCP** — an MCP client sends the same settings "
            "as request headers on `/gradio_api/mcp/`, so the credential travels in "
            "the transport and never becomes a tool argument the model can see:\n\n"
            "```\n" + "\n".join(f"{h}: …" for h in MCP_HEADERS) + "\n```\n"
            "They are listed under `meta.headers` at `/gradio_api/mcp/schema`. "
            "`vid`, `tab` and `scope` are also plain tool arguments, and take "
            "precedence over their header when both are sent."
        )

    CONFIG_INPUTS = [api_key_in, vid_in, tab_in, scope_in, inst_in, lang_in,
                     region_in, base_url_in]

    with gr.Tab("Search the catalogue"):
        query = gr.Textbox(label="Query", placeholder="histoire de la lecture")
        with gr.Row():
            field = gr.Dropdown(list(Q_FIELDS), value="any", label="Field")
            precision = gr.Dropdown(list(Q_PRECISIONS), value="contains", label="Precision")
            sort = gr.Dropdown(list(SORT_OPTIONS), value="rank", label="Sort")
        with gr.Row():
            max_results = gr.Slider(1, MAX_RESULTS, value=5, step=1, label="Results")
            offset = gr.Slider(0, MAX_OFFSET, value=0, step=1, label="Offset")
        with gr.Row():
            resource_type = gr.Textbox(label="Resource type (facet)", placeholder="books")
            language = gr.Textbox(label="Language (facet)", placeholder="fre")
            availability = gr.Dropdown(
                [""] + list(AVAILABILITY_OPTIONS), value="", label="Availability (facet)"
            )
        with gr.Row():
            library = gr.Textbox(label="Library (facet)", placeholder="MAIN")
            collection = gr.Textbox(label="Collection / domain (facet)")
        with gr.Row():
            year_from = gr.Number(label="Year from", precision=0, value=YEAR_MIN)
            year_to = gr.Number(label="Year to", precision=0, value=YEAR_MAX)
            full_text_only = gr.Checkbox(label="Full text / held only", value=False)
            return_facets = gr.Checkbox(label="Return facets", value=False)

        search_btn = gr.Button("Search", variant="primary")
        search_out = gr.Markdown()
        search_raw = gr.JSON(label="Raw tool output")
        with gr.Accordion("🔍 Debug — request sent and response received (API key redacted)", open=False):
            search_req = gr.JSON()

        gr.Examples(
            examples=[
                ["histoire de la lecture", "any", 5, "books"],
                ["qzxwv titre inexistant", "title", 3, ""],
            ],
            inputs=[query, field, max_results, resource_type],
            label="A hit, and a query that returns nothing",
        )
        search_btn.click(
            _run_search,
            inputs=CONFIG_INPUTS + [
                query, field, precision, max_results, offset, sort, resource_type,
                language, library, collection, availability, year_from, year_to,
                full_text_only, return_facets],
            outputs=[search_out, search_raw, search_req],
            api_name=False,
        )

    with gr.Tab("Fetch a record"):
        record_id = gr.Textbox(label="Record id", placeholder="alma990001234")
        context = gr.Radio(["L", "PC"], value="L", label="Context (L = local, PC = CDI)")
        record_btn = gr.Button("Fetch", variant="primary")
        record_out = gr.Markdown()
        record_raw = gr.JSON(label="Raw tool output")
        with gr.Accordion("🔍 Debug — request sent and response received (API key redacted)", open=False):
            record_req = gr.JSON()

        gr.Examples(
            examples=[["alma990001234", "L"], ["does-not-exist", "L"]],
            inputs=[record_id, context],
            label="A record id from a search above, and one that does not resolve",
        )
        record_btn.click(
            _run_record,
            inputs=CONFIG_INPUTS + [record_id, context],
            outputs=[record_out, record_raw, record_req],
            api_name=False,
        )

    config_btn.click(
        _summarize_config, inputs=CONFIG_INPUTS, outputs=config_out, api_name=False
    )
    demo.load(_summarize_config, inputs=CONFIG_INPUTS, outputs=config_out, api_name=False)

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
