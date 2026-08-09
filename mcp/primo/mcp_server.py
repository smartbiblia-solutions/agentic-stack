#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ['fastmcp>=3.4,<4', 'httpx']
# ///

"""
Primo MCP server.

Exposes an Ex Libris / Clarivate Primo (or Primo VE) discovery layer to AI
agents through the public `primoSearch` REST API
(GET /primo/v1/search and /primo/v1/pnxs).
Documentation: https://developers.exlibrisgroup.com/primo/apis/

Primo APIs are institution-scoped: one API key is bound to a single
institution + environment, and every search must name the view (vid), tab,
scope and institution code (inst) configured in that institution's Primo Back
Office. These are supplied as server defaults (CLI flags / env) and may be
overridden per tool call; the API key itself comes from PRIMO_API_KEY only.

Three ways to run:

  # 1. Zero-install — run directly from GitHub (uv fetches everything)
  uv run https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/primo/mcp_server.py \
      --vid INST:VIEW --tab TAB --scope SCOPE --inst INST \
      --region eu --transport stdio

  # 2. Local stdio — client launches the process (recommended for desktop/IDE apps)
  uv run /path/to/mcp/primo/mcp_server.py \
      --vid INST:VIEW --tab TAB --scope SCOPE --inst INST --transport stdio

  # 3. Local HTTP — run once, connect multiple clients by URL
  uv run /path/to/mcp/primo/mcp_server.py \
      --vid INST:VIEW --tab TAB --scope SCOPE --inst INST \
      --host 0.0.0.0 --port 8013 --transport http

  # 4. Stateless HTTP — no session affinity, for load-balanced / multi-replica deploys
  uv run /path/to/mcp/primo/mcp_server.py \
      --vid INST:VIEW --tab TAB --scope SCOPE --inst INST \
      --transport http --stateless

Environment:
    PRIMO_API_KEY           Required API key. Environment only — never a flag:
                            argv is visible in process listings. The server
                            exits at startup when it is unset.

Options:
    --region        TEXT    Gateway region: na eu ap ca cn      [default: na]
    --base-url      TEXT    Full API gateway base URL (overrides --region)
    --vid           TEXT    Default view id (e.g. INST:VIEW)     [recommended]
    --tab           TEXT    Default tab name                     [recommended]
    --scope         TEXT    Default scope name                   [recommended]
    --inst          TEXT    Default institution code             [recommended]
    --lang          TEXT    Default UI language                  [default: en]
    --host          TEXT    Bind host                            [default: 0.0.0.0]
    --port          INT     Bind port                            [default: 8013]
    --transport     TEXT    stdio | http | sse                   [default: http]
                            ("streamable-http" is accepted as an alias of "http")
    --stateless             Stateless HTTP: a new transport per request, so no
                            session is pinned to a replica. Incompatible with sse.
    --http-timeout  FLOAT   Request timeout (s)                  [default: 30.0]
    --max-retries   INT     Retry attempts                       [default: 3]
    --backoff-base  FLOAT   Backoff base (s)                     [default: 1.0]
    --backoff-factor FLOAT  Backoff multiplier                   [default: 2.0]
    --jitter-max    FLOAT   Max retry jitter (s)                 [default: 0.25]
    --trace                 Include HTTP trace in tool responses
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import re
import time
from typing import Any

import httpx
from fastmcp import FastMCP


# ── CLI args ──────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Primo MCP server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--region",         default=os.environ.get("PRIMO_REGION", "na"),
                   help="Gateway region: na eu ap ca cn")
    p.add_argument("--base-url",       default=os.environ.get("PRIMO_BASE_URL"),
                   help="Full API gateway base URL (overrides --region)")
    p.add_argument("--vid",            default=os.environ.get("PRIMO_VID"),
                   help="Default view id, e.g. INST:VIEW")
    p.add_argument("--tab",            default=os.environ.get("PRIMO_TAB"),
                   help="Default tab name")
    p.add_argument("--scope",          default=os.environ.get("PRIMO_SCOPE"),
                   help="Default scope name")
    p.add_argument("--inst",           default=os.environ.get("PRIMO_INST"),
                   help="Default institution code")
    p.add_argument("--lang",           default=os.environ.get("PRIMO_LANG", "en"),
                   help="Default UI language")
    p.add_argument("--host",           default=os.environ.get("MCP_HOST", "0.0.0.0"))
    p.add_argument("--port",           type=int,   default=int(os.environ.get("MCP_PORT", "8013")))
    p.add_argument("--transport",      default=os.environ.get("MCP_TRANSPORT", "http"),
                   choices=["stdio", "http", "sse", "streamable-http"],
                   help='Transport ("streamable-http" is an alias of "http")')
    p.add_argument("--stateless",      action="store_true",
                   default=os.environ.get("MCP_STATELESS", "").lower() in ("1", "true", "yes"),
                   help="Stateless HTTP: new transport per request, no session affinity")
    # Tuning is a property of the connector, not of the installation: flags only,
    # never environment variables.
    p.add_argument("--http-timeout",   type=float, default=30.0)
    p.add_argument("--max-retries",    type=int,   default=3)
    p.add_argument("--backoff-base",   type=float, default=1.0)
    p.add_argument("--backoff-factor", type=float, default=2.0)
    p.add_argument("--jitter-max",     type=float, default=0.25)
    p.add_argument("--trace",          action="store_true", default=False)
    ns = p.parse_args()
    # FastMCP raises on this combination; fail here instead, with a usage message.
    if ns.stateless and ns.transport == "sse":
        p.error("--stateless is not supported by the sse transport; use --transport http")
    return ns


args = _parse_args()

# ── Config ────────────────────────────────────────────────────────────────────

# Credentials come from the environment only — never a flag, because argv is
# visible in process listings and shell history.
API_KEY = os.environ.get("PRIMO_API_KEY") or ""

if not API_KEY:
    raise SystemExit(
        "Error: Primo API key is required. "
        "Set the PRIMO_API_KEY environment variable."
    )

REGION_HOSTS = {
    "na": "https://api-na.hosted.exlibrisgroup.com",
    "eu": "https://api-eu.hosted.exlibrisgroup.com",
    "ap": "https://api-ap.hosted.exlibrisgroup.com",
    "ca": "https://api-ca.hosted.exlibrisgroup.com",
    "cn": "https://api-cn.hosted.exlibrisgroup.com.cn",
}

DEFAULT_VID    = args.vid
DEFAULT_TAB    = args.tab
DEFAULT_SCOPE  = args.scope
DEFAULT_INST   = args.inst
DEFAULT_LANG   = args.lang
HTTP_TIMEOUT   = args.http_timeout
MAX_RETRIES    = max(1, args.max_retries)
BACKOFF_BASE   = max(0.0, args.backoff_base)
BACKOFF_FACTOR = max(1.0, args.backoff_factor)
JITTER_MAX     = max(0.0, args.jitter_max)
TRACE_DEFAULT  = args.trace

BASE_URL = (args.base_url.rstrip("/") if args.base_url
            else REGION_HOSTS.get(args.region.lower(), REGION_HOSTS["na"]))

Q_FIELDS = ("any", "title", "creator", "sub", "usertag")
Q_PRECISIONS = ("contains", "exact", "begins_with")
SORT_OPTIONS = ("rank", "title", "author", "date", "date_d", "date_a")

# Bounds a creation year has to fall inside to count as a bound at all.
YEAR_MIN, YEAR_MAX = 1000, 2999


# ── HTTP client with retry / backoff ──────────────────────────────────────────

# One pooled client for the process. Opening an AsyncClient per call would
# rebuild the connection pool — and replay the TLS handshake — every time.
HTTP = httpx.AsyncClient(
    timeout=HTTP_TIMEOUT,
    follow_redirects=True,
    headers={"Accept": "application/json"},
)


def _should_retry(status_code: int) -> bool:
    return status_code in (429, 500, 502, 503, 504)


def _backoff_sleep_seconds(attempt: int) -> float:
    base = BACKOFF_BASE * (BACKOFF_FACTOR ** attempt)
    jitter = random.uniform(0.0, JITTER_MAX) if JITTER_MAX > 0 else 0.0
    return base + jitter


async def _get(url: str, params: dict, *, trace: bool = False) -> tuple[dict, list[dict]]:
    """GET with exponential backoff. Returns (response_json, trace_events)."""
    trace_events: list[dict] = []
    started = time.perf_counter()
    safe_params = {k: ("***" if k == "apikey" else v) for k, v in params.items()}

    last_status: int | None = None
    last_error: str | None = None

    for attempt in range(MAX_RETRIES):
        t0 = time.perf_counter()
        try:
            if trace:
                trace_events.append({
                    "event": "http_request", "method": "GET", "url": url,
                    "attempt": attempt + 1, "max_retries": MAX_RETRIES, "params": safe_params,
                })

            resp = await HTTP.get(url, params=params)
            last_status = resp.status_code

            if trace:
                trace_events.append({
                    "event": "http_response", "status_code": resp.status_code,
                    "attempt": attempt + 1,
                    "elapsed_ms": int((time.perf_counter() - t0) * 1000),
                })

            if resp.status_code == 200:
                if trace:
                    trace_events.append({
                        "event": "http_success", "attempt": attempt + 1,
                        "total_elapsed_ms": int((time.perf_counter() - started) * 1000),
                    })
                return resp.json(), trace_events

            if resp.status_code in (401, 403):
                raise RuntimeError(
                    f"Primo API returned {resp.status_code} (unauthorized). "
                    f"Check the API key and that vid/scope/tab belong to its institution."
                )

            if _should_retry(resp.status_code) and attempt < MAX_RETRIES - 1:
                sleep_s = _backoff_sleep_seconds(attempt)
                if trace:
                    trace_events.append({
                        "event": "http_retry_sleep", "status_code": resp.status_code,
                        "attempt": attempt + 1, "sleep_s": round(sleep_s, 3),
                    })
                await asyncio.sleep(sleep_s)
                continue

            resp.raise_for_status()

        except httpx.TimeoutException as e:
            last_error = f"timeout: {e}"
            if trace:
                trace_events.append({
                    "event": "http_timeout", "attempt": attempt + 1,
                    "elapsed_ms": int((time.perf_counter() - t0) * 1000), "message": str(e),
                })
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(_backoff_sleep_seconds(attempt))
                continue
            raise

        except httpx.HTTPError as e:
            last_error = f"http_error: {e}"
            if trace:
                trace_events.append({"event": "http_error", "attempt": attempt + 1, "message": str(e)})
            raise

    raise RuntimeError(
        f"Primo: failed after {MAX_RETRIES} attempts on {url} "
        f"(status={last_status}, error={last_error})"
    )


# ── query / facet building ────────────────────────────────────────────────────

def _build_q(query: str, field: str, precision: str) -> str:
    field = field if field in Q_FIELDS else "any"
    precision = precision if precision in Q_PRECISIONS else "contains"
    value = query.replace(";", " ").strip()
    return f"{field},{precision},{value}"


def _build_qinclude(facets: list[tuple[str, str]]) -> str | None:
    clauses = [f"{cat},exact,{val}" for cat, val in facets if cat and val]
    return "|,|".join(clauses) if clauses else None


def _year_bound(value: Any) -> int | None:
    """
    A creation-year bound, or None when there is none.

    A caller that means "no bound" may send `0` rather than omitting the
    argument. Taken literally that builds
    `facet_searchcreationdate,exact,[0 TO 0]`, which Primo applies as written:
    zero records, HTTP 200, no error to read. Anything outside a plausible year
    means "no bound".
    """
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year if YEAR_MIN <= year <= YEAR_MAX else None


# ── PNX parsing helpers ───────────────────────────────────────────────────────

def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    head = value.split("$$", 1)[0].strip()
    return head or None


def _first(d: dict, *keys: str) -> str | None:
    for k in keys:
        vals = d.get(k)
        if isinstance(vals, list):
            for v in vals:
                cleaned = _clean(v) if isinstance(v, str) else None
                if cleaned:
                    return cleaned
        elif isinstance(vals, str):
            cleaned = _clean(vals)
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


SERVER_NAME = "primo"


def _envelope(
    command: str,
    results: list[dict] | None = None,
    *,
    total_found: int | None = 0,
    error: str | None = None,
    **extra: Any,
) -> dict:
    """
    Build the envelope every tool of this server returns.

    `results` is always an array and `error` is always present (null on success),
    so an agent reads a degraded upstream out of the payload instead of having to
    catch a protocol fault. `total_found` is null when the source cannot count.
    """
    items = list(results or [])
    out: dict = {
        "source": SERVER_NAME,
        "command": command,
        "total_found": total_found,
        "returned": len(items),
        "results": items,
        "error": error,
    }
    out.update(extra)
    return out


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


def _resolve_target(
    vid: str | None, scope: str | None, tab: str | None, inst: str | None = None,
) -> tuple[str, str, str | None, str | None]:
    """Resolve view/scope/tab/inst from per-call args falling back to server defaults."""
    v = vid or DEFAULT_VID
    s = scope or DEFAULT_SCOPE
    t = tab or DEFAULT_TAB
    i = inst or DEFAULT_INST
    missing = [n for n, val in (("vid", v), ("scope", s)) if not val]
    if missing:
        raise RuntimeError(
            f"Missing {', '.join(missing)}. Set them as server defaults "
            f"(--vid/--scope/--tab/--inst) or pass them to the tool."
        )
    return v, s, t, i


# ── MCP server ────────────────────────────────────────────────────────────────

mcp = FastMCP(
    name="primo",
    instructions=(
        "Ex Libris / Clarivate Primo discovery connector — search an institution's "
        "library catalog and discovery index, and fetch full PNX records. "
        "All queries run against one institution's configured view "
        "(vid/scope/tab/inst)."
    ),
)


@mcp.tool
async def search_catalog(
    query: str,
    field: str = "any",
    precision: str = "contains",
    max_results: int = 15,
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
    inst: str | None = None,
) -> dict:
    """
    Search an Ex Libris Primo discovery layer (library catalog + discovery index).

    Args:
        query: Free-text search term(s).
        field: Search field — any, title, creator, sub (subject), usertag.
        precision: Match precision — contains, exact, begins_with.
        max_results: Records to return (1-50; the API caps a single page at 50).
        offset: Result offset for paging (max ~2000 recommended).
        sort: rank, title, author, date, date_d (newest), date_a (oldest).
        resource_type: Filter by resource type facet (e.g. books, articles, journals).
        language: Filter by language facet (e.g. eng, fre).
        library: Filter by holding library facet.
        collection: Filter by collection/domain facet.
        availability: Filter by availability facet (available, online_resources, physical_item).
        year_from: Lower bound creation year (inclusive).
        year_to: Upper bound creation year (inclusive).
        full_text_only: If true, only records with full text/availability (pcAvailability=false).
        return_facets: If true, include facet buckets in the response.
        vid: Override the server's default view id (INST:VIEW).
        tab: Override the server's default tab.
        scope: Override the server's default scope.
        inst: Override the server's default institution code.

    Returns:
        {"source": "primo", "command": "search_catalog", "total_found": int,
         "returned": int, "results": [record, ...], "error": str | null,
         "offset": int, "query_used": str, "vid": str}
        Plus "facets" when return_facets is true.
    """
    trace = TRACE_DEFAULT
    v, s, t, i = _resolve_target(vid, scope, tab, inst)

    inc: list[tuple[str, str]] = []
    if resource_type:
        inc.append(("facet_rtype", resource_type))
    if language:
        inc.append(("facet_lang", language))
    if library:
        inc.append(("facet_library", library))
    if collection:
        inc.append(("facet_domain", collection))
    if availability:
        inc.append(("facet_tlevel", availability))
    start_year, end_year = _year_bound(year_from), _year_bound(year_to)
    if start_year is not None or end_year is not None:
        start = str(start_year) if start_year is not None else "*"
        end = str(end_year) if end_year is not None else "*"
        inc.append(("facet_searchcreationdate", f"[{start} TO {end}]"))

    params: dict[str, Any] = {
        "vid": v,
        "scope": s,
        "q": _build_q(query, field, precision),
        "lang": DEFAULT_LANG,
        "offset": max(0, offset),
        "limit": max(1, min(max_results, 50)),
        "sort": sort if sort in SORT_OPTIONS else "rank",
        "pcAvailability": "false" if full_text_only else "true",
        "apikey": API_KEY,
    }
    if t:
        params["tab"] = t
    if i:
        params["inst"] = i
    qinc = _build_qinclude(inc)
    if qinc:
        params["qInclude"] = qinc

    try:
        data, tevents = await _get(f"{BASE_URL}/primo/v1/search", params, trace=trace)
    except (RuntimeError, httpx.HTTPError) as e:
        return _envelope("search_catalog", error=str(e),
                         offset=params["offset"], query_used=params["q"], vid=v)

    docs = data.get("docs", []) or []
    info = data.get("info", {}) or {}

    out = _envelope(
        "search_catalog",
        [_format_doc(d) for d in docs],
        total_found=info.get("total", info.get("totalResultsLocal", len(docs))),
        offset=params["offset"],
        query_used=params["q"],
        vid=v,
    )
    if return_facets:
        out["facets"] = _parse_facets(data.get("facets"))
    if trace:
        out["trace"] = tevents
    return out


@mcp.tool
async def get_record(
    record_id: str,
    context: str = "L",
    vid: str | None = None,
    scope: str | None = None,
    inst: str | None = None,
) -> dict:
    """
    Fetch a single Primo PNX record by its recordid.

    Args:
        record_id: Primo recordid (the control.recordid value, e.g. "alma990001234").
        context: "L" for a local institution record, "PC" for a Central Discovery
                 Index (CDI) record.
        vid: Override the server's default view id (INST:VIEW).
        scope: Override the server's default scope.
        inst: Override the server's default institution code.

    Returns:
        {"source": "primo", "command": "get_record", "total_found": int,
         "returned": int, "results": [record], "error": str | null}
        `results` holds at most one record; `error` explains an empty one.
    """
    trace = TRACE_DEFAULT
    v, s, _, i = _resolve_target(vid, scope, None, inst)
    context = (context or "L").upper()

    params: dict[str, Any] = {"vid": v, "scope": s, "lang": DEFAULT_LANG, "apikey": API_KEY}
    if i:
        params["inst"] = i

    url = f"{BASE_URL}/primo/v1/pnxs/{context}/{record_id}"
    try:
        data, tevents = await _get(url, params, trace=trace)
    except (RuntimeError, httpx.HTTPError) as e:
        return _envelope("get_record",
                         error=f"Record not found in Primo: '{record_id}' ({e})")

    doc = data
    if "docs" in data and isinstance(data["docs"], list):
        doc = data["docs"][0] if data["docs"] else None
    if not doc or "pnx" not in doc:
        out = _envelope("get_record",
                        error=f"Record not found in Primo: '{record_id}'")
        if trace:
            out["trace"] = tevents
        return out

    out = _envelope("get_record", [_format_doc(doc)], total_found=1)
    if trace:
        out["trace"] = tevents
    return out


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if args.transport == "stdio":
        # Local launch by a desktop/IDE client that speaks MCP over stdio.
        # host/port are irrelevant in this mode.
        mcp.run(transport="stdio")
    else:
        # stateless_http=True builds a fresh transport per request, so no session
        # is pinned to a replica — required behind a load balancer or several
        # uvicorn workers. Off by default: a single long-lived process is cheaper
        # stateful, and stdio clients never reach this branch.
        mcp.run(
            transport=args.transport,
            host=args.host,
            port=args.port,
            stateless_http=args.stateless,
        )
