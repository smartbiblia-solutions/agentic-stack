#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ['fastmcp>=3.4,<4', 'httpx']
# ///

"""
OpenAlex MCP server.

Exposes the OpenAlex REST API to AI agents through MCP.
Documentation: https://docs.openalex.org

Three ways to run:

  # 1. Zero-install — run directly from GitHub (uv fetches everything)
  uv run https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/openalex/mcp_server.py \
      --transport stdio

  # 2. Local stdio — client launches the process (recommended for desktop/IDE apps)
  uv run /path/to/mcp/openalex/mcp_server.py --transport stdio

  # 3. Local HTTP — run once, connect multiple clients by URL
  uv run /path/to/mcp/openalex/mcp_server.py \
      --host 0.0.0.0 --port 8011 --transport http

  # 4. Stateless HTTP — no session affinity, for load-balanced / multi-replica deploys
  uv run /path/to/mcp/openalex/mcp_server.py --transport http --stateless

Environment:
    OPENALEX_API_KEY        Optional API key (polite pool). Environment only —
                            never a flag: argv is visible in process listings.

Options:
    --host          TEXT    Bind host            [default: 0.0.0.0]
    --port          INT     Bind port            [default: 8011]
    --transport     TEXT    stdio | http | sse   [default: http]
                            ("streamable-http" is accepted as an alias of "http")
    --stateless             Stateless HTTP: a new transport per request, so no
                            session is pinned to a replica. Incompatible with sse.
    --http-timeout  FLOAT   Request timeout (s)  [default: 15.0]
    --max-retries   INT     Retry attempts        [default: 2]
    --backoff-base  FLOAT   Backoff base (s)      [default: 1.0]
    --backoff-factor FLOAT  Backoff multiplier    [default: 2.0]
    --jitter-max    FLOAT   Max retry jitter (s)  [default: 0.25]
    --trace                 Include HTTP trace in tool responses
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
import time
from typing import Any

import httpx
from fastmcp import FastMCP


# ── CLI args (parsed before anything else so globals are correct) ─────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="OpenAlex MCP server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--host",          default=os.environ.get("MCP_HOST", "0.0.0.0"))
    p.add_argument("--port",          type=int,   default=int(os.environ.get("MCP_PORT", "8011")))
    p.add_argument("--transport",     default=os.environ.get("MCP_TRANSPORT", "http"),
                   choices=["stdio", "http", "sse", "streamable-http"],
                   help='Transport ("streamable-http" is an alias of "http")')
    p.add_argument("--stateless",     action="store_true",
                   default=os.environ.get("MCP_STATELESS", "").lower() in ("1", "true", "yes"),
                   help="Stateless HTTP: new transport per request, no session affinity")
    # Tuning is a property of the connector, not of the installation: flags only,
    # never environment variables.
    p.add_argument("--http-timeout",  type=float, default=15.0)
    p.add_argument("--max-retries",   type=int,   default=2)
    p.add_argument("--backoff-base",  type=float, default=1.0)
    p.add_argument("--backoff-factor",type=float, default=2.0)
    p.add_argument("--jitter-max",    type=float, default=0.25)
    p.add_argument("--trace",         action="store_true", default=False)
    ns = p.parse_args()
    # FastMCP raises on this combination; fail here instead, with a usage message.
    if ns.stateless and ns.transport == "sse":
        p.error("--stateless is not supported by the sse transport; use --transport http")
    return ns


args = _parse_args()

# ── Config ────────────────────────────────────────────────────────────────────

# Credentials come from the environment only — never a flag, because argv is
# visible in process listings and shell history.
API_KEY        = os.environ.get("OPENALEX_API_KEY") or None
HTTP_TIMEOUT   = args.http_timeout
MAX_RETRIES    = max(1, args.max_retries)
BACKOFF_BASE   = max(0.0, args.backoff_base)
BACKOFF_FACTOR = max(1.0, args.backoff_factor)
JITTER_MAX     = max(0.0, args.jitter_max)
TRACE_DEFAULT  = args.trace

OPENALEX_BASE         = "https://api.openalex.org"
OPENALEX_WORKS        = f"{OPENALEX_BASE}/works"
OPENALEX_AUTHORS      = f"{OPENALEX_BASE}/authors"
OPENALEX_INSTITUTIONS = f"{OPENALEX_BASE}/institutions"
OPENALEX_TEXT         = f"{OPENALEX_BASE}/text"

SELECT_FIELDS = ",".join([
    "id", "title", "authorships", "abstract_inverted_index",
    "doi", "publication_date", "publication_year",
    "primary_location", "best_oa_location", "open_access",
    "cited_by_count", "type", "topics", "keywords",
    "referenced_works_count", "cited_by_api_url",
])

# Bounds specific to `search.semantic`, verified against the API:
#   - `per-page` above 50 answers HTTP 400;
#   - `meta.count` is always 50 — the cap of the vector ranking, not a corpus
#     count, which is why `total_found` comes back null;
#   - text beyond 2000 characters is truncated before embedding.
SEMANTIC_MAX_RESULTS = 50
SEMANTIC_MAX_CHARS = 2000

# `search.semantic` refuses to be combined with `search`, and accepts only a
# closed filter list which the API enumerates in its own 400 message:
#   author.id, authorships.author.id, authorships.institutions.id, funders.id,
#   has_abstract, has_fulltext, institution.id, institutions.id, is_oa,
#   is_retracted, language, open_access.is_oa, primary_location.license,
#   primary_location.source.id, publication_year, type
# `from_publication_date` / `to_publication_date` are absent from it — the date
# bounds `search_works` takes are rejected here, so this tool bounds by
# `publication_year` and names its arguments `year_from` / `year_to` to make the
# difference visible in the schema a model reads.


# ── HTTP client with retry / backoff ──────────────────────────────────────────

# One pooled client for the process. Opening an AsyncClient per call would
# rebuild the connection pool — and replay the TLS handshake — every time.
HTTP = httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True)


def _should_retry(status_code: int) -> bool:
    return status_code in (429, 403, 500, 502, 503, 504)


def _backoff_sleep_seconds(attempt: int) -> float:
    base = BACKOFF_BASE * (BACKOFF_FACTOR ** attempt)
    jitter = random.uniform(0.0, JITTER_MAX) if JITTER_MAX > 0 else 0.0
    return base + jitter


async def _get(url: str, params: dict, *, trace: bool = False) -> tuple[dict, list[dict]]:
    """GET with exponential backoff. Returns (response_json, trace_events)."""
    request_params = dict(params)
    if API_KEY:
        request_params["api_key"] = API_KEY

    trace_events: list[dict] = []
    started = time.perf_counter()

    last_status: int | None = None
    last_error: str | None = None

    for attempt in range(MAX_RETRIES):
        t0 = time.perf_counter()
        try:
            if trace:
                trace_events.append({
                    "event": "http_request", "method": "GET", "url": url,
                    "attempt": attempt + 1, "max_retries": MAX_RETRIES, "params": request_params,
                })

            resp = await HTTP.get(url, params=request_params)
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
                    "elapsed_ms": int((time.perf_counter() - t0) * 1000),
                    "message": str(e),
                })
            if attempt < MAX_RETRIES - 1:
                sleep_s = _backoff_sleep_seconds(attempt)
                if trace:
                    trace_events.append({
                        "event": "http_retry_sleep", "reason": "timeout",
                        "attempt": attempt + 1, "sleep_s": round(sleep_s, 3),
                    })
                await asyncio.sleep(sleep_s)
                continue
            raise

        except httpx.HTTPError as e:
            last_error = f"http_error: {e}"
            if trace:
                trace_events.append({"event": "http_error", "attempt": attempt + 1, "message": str(e)})
            raise

    raise RuntimeError(
        f"OpenAlex: failed after {MAX_RETRIES} attempts on {url} "
        f"(status={last_status}, error={last_error})"
    )


# ── Formatting ────────────────────────────────────────────────────────────────

def _reconstruct_abstract(inverted_index: dict | None) -> str | None:
    if not inverted_index:
        return None
    try:
        positions: dict[int, str] = {}
        for word, pos_list in inverted_index.items():
            for pos in pos_list:
                positions[pos] = word
        return " ".join(positions[i] for i in sorted(positions))
    except Exception:
        return None


def _format_work(work: dict) -> dict:
    authors, author_details = [], []
    for a in work.get("authorships", []):
        author = a.get("author", {})
        name = author.get("display_name", "")
        authors.append(name)
        author_details.append({
            "name": name,
            "orcid": author.get("orcid"),
            "openalex_id": (author.get("id", "") or "").replace("https://openalex.org/", ""),
            "institutions": [i.get("display_name", "") for i in a.get("institutions", [])],
        })

    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
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
        "author_details": author_details,
        "abstract": _reconstruct_abstract(work.get("abstract_inverted_index")),
        "doi": doi,
        "pdf_url": best_oa.get("pdf_url") or best_oa.get("landing_page_url"),
        "url": work.get("id"),
        "year": work.get("publication_year"),
        "date": work.get("publication_date") or str(work.get("publication_year") or ""),
        "doc_type": work.get("type"),
        "journal": source.get("display_name"),
        "cited_by_count": work.get("cited_by_count", 0),
        "referenced_works_count": work.get("referenced_works_count", 0),
        "is_open_access": (work.get("open_access") or {}).get("is_oa", False),
        "oa_status": (work.get("open_access") or {}).get("oa_status"),
        "topics": [
            t.get("display_name", "") for t in work.get("topics", [])
            if t.get("score", 0) > 0.3
        ][:5],
        "keywords": [k.get("display_name", "") for k in work.get("keywords", [])],
        "cited_by_api_url": work.get("cited_by_api_url"),
    }


# ── ID resolution ─────────────────────────────────────────────────────────────

async def _resolve_author_id(name_or_orcid: str, *, trace: bool = False) -> tuple[str | None, list[dict]]:
    """Resolve an author name or ORCID to an OpenAlex author ID."""
    events: list[dict] = []
    if "orcid.org" in name_or_orcid or name_or_orcid.startswith("0000-"):
        orcid = name_or_orcid if name_or_orcid.startswith("https://") else f"https://orcid.org/{name_or_orcid}"
        try:
            data, t = await _get(f"{OPENALEX_BASE}/authors/{orcid}", {}, trace=trace)
            events.extend(t)
            return (data.get("id", "").replace("https://openalex.org/", "") or None), events
        except Exception:
            return None, events

    data, t = await _get(OPENALEX_AUTHORS, {"search": name_or_orcid, "per-page": 1}, trace=trace)
    events.extend(t)
    results = data.get("results", [])
    resolved = (results[0].get("id") or "").replace("https://openalex.org/", "") if results else ""
    return (resolved or None), events


async def _resolve_institution_id(name_or_ror: str, *, trace: bool = False) -> tuple[str | None, list[dict]]:
    """Resolve an institution name or ROR URL to an OpenAlex institution ID."""
    events: list[dict] = []
    if "ror.org" in name_or_ror:
        try:
            data, t = await _get(f"{OPENALEX_BASE}/institutions/{name_or_ror}", {}, trace=trace)
            events.extend(t)
            return (data.get("id", "").replace("https://openalex.org/", "") or None), events
        except Exception:
            return None, events

    data, t = await _get(OPENALEX_INSTITUTIONS, {"search": name_or_ror, "per-page": 1}, trace=trace)
    events.extend(t)
    results = data.get("results", [])
    resolved = (results[0].get("id") or "").replace("https://openalex.org/", "") if results else ""
    return (resolved or None), events


# ── Response envelope ─────────────────────────────────────────────────────────

SERVER_NAME = "openalex"


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


# ── MCP server ────────────────────────────────────────────────────────────────

mcp = FastMCP(
    name="openalex",
    instructions="OpenAlex connector — search academic publications by keyword or by meaning, resolve DOIs, fetch citations, classify text.",
)


@mcp.tool
async def search_works(
    query: str,
    max_results: int = 15,
    date_from: str | None = None,
    date_to: str | None = None,
    filter_open_access: bool = False,
    sort_by: str = "publication_date:desc",
    author: str | None = None,
    institution: str | None = None,
) -> dict:
    """
    Search OpenAlex for academic works by keyword query.

    Args:
        query: Free-text search query.
        max_results: Number of results to return (max 200).
        date_from: Lower publication date bound (YYYY-MM-DD).
        date_to: Upper publication date bound (YYYY-MM-DD).
        filter_open_access: If true, return only open-access works.
        sort_by: Sort field, e.g. "cited_by_count:desc" or "publication_date:desc".
        author: Author name or ORCID (resolved automatically).
        institution: Institution name or ROR URL (resolved automatically).

    Returns:
        {"source": "openalex", "command": "search_works", "total_found": int,
         "returned": int, "results": [work, ...], "error": str | null,
         "query_used": str, "filters_used": [str]}
    """
    trace = TRACE_DEFAULT
    trace_events: list[dict] = []
    filters: list[str] = []

    if date_from:
        filters.append(f"from_publication_date:{date_from}")
    if date_to:
        filters.append(f"to_publication_date:{date_to}")
    if filter_open_access:
        filters.append("is_oa:true")

    def _fail(message: str) -> dict:
        out = _envelope("search_works", error=message,
                        query_used=query, filters_used=filters)
        if trace:
            out["trace"] = trace_events
        return out

    try:
        if author:
            author_id, t = await _resolve_author_id(author, trace=trace)
            trace_events.extend(t)
            if not author_id:
                return _fail(f"Author not found in OpenAlex: '{author}'")
            filters.append(f"authorships.author.id:{author_id}")

        if institution:
            inst_id, t = await _resolve_institution_id(institution, trace=trace)
            trace_events.extend(t)
            if not inst_id:
                return _fail(f"Institution not found in OpenAlex: '{institution}'")
            filters.append(f"authorships.institutions.id:{inst_id}")
    except (RuntimeError, httpx.HTTPError) as e:
        return _fail(str(e))

    params: dict[str, Any] = {
        "search": query,
        "per-page": min(max_results, 200),
        "sort": sort_by,
        "select": SELECT_FIELDS,
    }
    if filters:
        params["filter"] = ",".join(filters)

    try:
        data, t = await _get(OPENALEX_WORKS, params, trace=trace)
    except (RuntimeError, httpx.HTTPError) as e:
        return _fail(str(e))

    trace_events.extend(t)
    results = data.get("results", [])
    out = _envelope(
        "search_works",
        [_format_work(r) for r in results],
        total_found=data.get("meta", {}).get("count", 0),
        query_used=query,
        filters_used=filters,
    )
    if trace:
        out["trace"] = trace_events
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


@mcp.tool
async def search_semantic(
    text: str,
    max_results: int = 15,
    year_from: int | None = None,
    year_to: int | None = None,
    filter_open_access: bool = False,
) -> dict:
    """
    Search OpenAlex by meaning rather than by keyword.

    Ranks works by semantic proximity to a descriptive text, so a paper matches
    even when it shares none of the words used to ask for it. Give it a sentence
    or a whole abstract — it is built for abstract-length input, not for two
    keywords. Use search_works instead when a keyword genuinely names the subject.

    Three limits come from the endpoint itself: at most 50 results with no paging
    past them, `total_found` always null (OpenAlex reports the cap, not a count),
    and date bounds expressed as years — the from/to dates search_works accepts
    are rejected here. Roughly one call per second is allowed.

    Args:
        text: Descriptive text or abstract, minimum 20 characters, truncated at 2000.
        max_results: Number of works to return (max 50).
        year_from: Earliest publication year, inclusive.
        year_to: Latest publication year, inclusive.
        filter_open_access: If true, return only open-access works.

    Returns:
        {"source": "openalex", "command": "search_semantic", "total_found": null,
         "returned": int, "results": [work with "relevance_score", ...],
         "error": str | null, "query_used": str, "filters_used": [str],
         "truncated": bool, "cost_usd": float | null}
    """
    trace = TRACE_DEFAULT
    text = (text or "").strip()
    filters: list[str] = []

    if len(text) < 20:
        return _envelope("search_semantic", total_found=None,
                         error="Text too short (minimum 20 characters)",
                         query_used=text, filters_used=filters,
                         truncated=False, cost_usd=None)

    year_filter = _semantic_year_filter(year_from, year_to)
    if year_filter:
        filters.append(year_filter)
    if filter_open_access:
        filters.append("is_oa:true")

    params: dict[str, Any] = {
        "search.semantic": text[:SEMANTIC_MAX_CHARS],
        "per-page": max(1, min(max_results, SEMANTIC_MAX_RESULTS)),
        "select": SELECT_FIELDS + ",relevance_score",
    }
    if filters:
        params["filter"] = ",".join(filters)

    try:
        data, t = await _get(OPENALEX_WORKS, params, trace=trace)
    except (RuntimeError, httpx.HTTPError) as e:
        return _envelope("search_semantic", total_found=None, error=str(e),
                         query_used=text[:SEMANTIC_MAX_CHARS], filters_used=filters,
                         truncated=len(text) > SEMANTIC_MAX_CHARS, cost_usd=None)

    results = []
    for work in data.get("results", []):
        record = _format_work(work)
        record["relevance_score"] = work.get("relevance_score")
        results.append(record)

    out = _envelope(
        "search_semantic",
        results,
        total_found=None,
        query_used=text[:SEMANTIC_MAX_CHARS],
        filters_used=filters,
        truncated=len(text) > SEMANTIC_MAX_CHARS,
        cost_usd=data.get("meta", {}).get("cost_usd"),
    )
    if trace:
        out["trace"] = t
    return out


@mcp.tool
async def lookup_by_doi(dois: list[str]) -> dict:
    """
    Resolve one or more DOIs to full OpenAlex work records.

    Args:
        dois: List of DOIs in any format (short: "10.xxx/…" or full URL).
              Batched automatically at 50 per request.

    Returns:
        {"source": "openalex", "command": "lookup_by_doi", "total_found": int,
         "returned": int, "results": [work, ...], "error": str | null}
    """
    trace = TRACE_DEFAULT
    trace_events: list[dict] = []

    if not dois:
        return _envelope("lookup_by_doi", error="dois is required")

    all_results: list[dict] = []
    for i in range(0, len(dois), 50):
        batch = dois[i:i + 50]
        normalized = [
            d if d.startswith("https://doi.org/") else f"https://doi.org/{d}"
            for d in batch
        ]
        params = {
            "filter": "doi:" + "|".join(normalized),
            "per-page": len(batch),
            "select": SELECT_FIELDS,
        }
        try:
            data, t = await _get(OPENALEX_WORKS, params, trace=trace)
        except (RuntimeError, httpx.HTTPError) as e:
            out = _envelope("lookup_by_doi", error=str(e))
            if trace:
                out["trace"] = trace_events
            return out
        trace_events.extend(t)
        all_results.extend(data.get("results", []))
        if i + 50 < len(dois):
            await asyncio.sleep(0.15)

    out = _envelope(
        "lookup_by_doi",
        [_format_work(r) for r in all_results],
        total_found=len(all_results),
        error=None if all_results else f"No OpenAlex work matched the {len(dois)} DOI(s) given",
    )
    if trace:
        out["trace"] = trace_events
    return out


@mcp.tool
async def get_citing_works(openalex_id: str, max_results: int = 20) -> dict:
    """
    Fetch works that cite a given OpenAlex work, sorted by citation count.

    Args:
        openalex_id: OpenAlex work ID — short form (W2741809807) or full URL.
        max_results: Number of citing works to return (max 200).

    Returns:
        {"source": "openalex", "command": "get_citing_works", "total_found": int,
         "returned": int, "results": [work, ...], "error": str | null,
         "cited_work_id": str}
    """
    trace = TRACE_DEFAULT
    clean_id = openalex_id.replace("https://openalex.org/", "")
    params = {
        "filter": f"cites:{clean_id}",
        "per-page": min(max_results, 200),
        "sort": "cited_by_count:desc",
        "select": SELECT_FIELDS,
    }
    try:
        data, t = await _get(OPENALEX_WORKS, params, trace=trace)
    except (RuntimeError, httpx.HTTPError) as e:
        return _envelope("get_citing_works", error=str(e), cited_work_id=clean_id)

    results = data.get("results", [])
    out = _envelope(
        "get_citing_works",
        [_format_work(r) for r in results],
        total_found=data.get("meta", {}).get("count", 0),
        cited_work_id=clean_id,
    )
    if trace:
        out["trace"] = t
    return out


@mcp.tool
async def classify_text(text: str) -> dict:
    """
    Classify a title or abstract into academic topics and keywords via OpenAlex.

    Args:
        text: Text to classify (minimum 20 characters, truncated at 2000).

    Returns:
        {"source": "openalex", "command": "classify_text", "total_found": int,
         "returned": int, "error": str | null, "keywords": [str],
         "results": [{"name": str, "score": float, "field": str | null,
                      "domain": str | null}, ...]}
        One entry per matched topic, best first.
    """
    trace = TRACE_DEFAULT
    text = text.strip()
    if len(text) < 20:
        return _envelope("classify_text",
                         error="Text too short (minimum 20 characters)",
                         keywords=[])

    try:
        data, t = await _get(OPENALEX_TEXT, {"title": text[:2000]}, trace=trace)
    except (RuntimeError, httpx.HTTPError) as e:
        return _envelope("classify_text", error=str(e), keywords=[])

    topics = [
        {
            "name": topic.get("display_name"),
            "score": topic.get("score"),
            "field": (topic.get("subfield") or {}).get("display_name"),
            "domain": (topic.get("domain") or {}).get("display_name"),
        }
        for topic in data.get("topics", [])
    ]
    out = _envelope(
        "classify_text",
        topics,
        total_found=len(topics),
        keywords=[k.get("display_name") for k in data.get("keywords", [])],
    )
    if trace:
        out["trace"] = t
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