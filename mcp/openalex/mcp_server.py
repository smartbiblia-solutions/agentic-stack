#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ['fastmcp>=3.4,<4', 'httpx']
# ///

"""
OpenAlex MCP server.

Exposes the OpenAlex REST API to AI agents through MCP.
Documentation: https://help.openalex.org/

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
    OPENALEX_API_KEY        Optional API key. Environment only — never a flag:
                            argv is visible in process listings.
    OPENALEX_API_URL        Optional API base, for a mirror or a proxy.

Since February 2026 OpenAlex meters usage as a daily budget and ignores
`mailto`: the polite pool is gone. Anonymous access gets $0.10/day, a free key
$1.00/day. Single-entity lookups and autocomplete are free at either level,
which is why `lookup_by_doi` and `resolve_entity` cost nothing to lean on.
Every billable response carries `cost_usd`.

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
import re
import sys
import time
import urllib.parse
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

OPENALEX_BASE         = (os.environ.get("OPENALEX_API_URL") or "https://api.openalex.org").rstrip("/")
OPENALEX_WORKS        = f"{OPENALEX_BASE}/works"
OPENALEX_AUTHORS      = f"{OPENALEX_BASE}/authors"
OPENALEX_INSTITUTIONS = f"{OPENALEX_BASE}/institutions"
OPENALEX_AUTOCOMPLETE = f"{OPENALEX_BASE}/autocomplete"
OPENALEX_QUERY        = f"{OPENALEX_BASE}/query"

SELECT_FIELDS = ",".join([
    "id", "title", "authorships", "abstract_inverted_index",
    "doi", "publication_date", "publication_year",
    "primary_location", "best_oa_location", "open_access",
    "cited_by_count", "type", "topics", "primary_topic", "keywords",
    "referenced_works_count", "cited_by_api_url",
    "fwci", "citation_normalized_percentile", "is_retracted", "language",
    "awards", "is_xpac",
])

# `per-page` is documented at 100. 200 is still accepted (201 answers HTTP 400)
# but marked deprecated: align on the documented maximum rather than on the
# server's residual tolerance.
MAX_PER_PAGE = 100

# Bounds specific to `search.semantic`, verified against the API:
#   - `per-page` above 50 answers HTTP 400;
#   - `meta.count` is always 50 — the cap of the vector ranking, not a corpus
#     count, which is why `total_found` comes back null;
#   - text beyond 2000 characters is truncated before embedding.
SEMANTIC_MAX_RESULTS = 50
SEMANTIC_MAX_CHARS = 2000

# `search.semantic` refuses to be combined with `search`, and rejects two
# filters that would mean pre-filtering hundreds of millions of vectors:
# `cited_by_count` and `last_known_institutions.country_code`.
# `from_publication_date` / `to_publication_date` are rejected too — which is
# why this tool bounds by `publication_year` and names its arguments
# `year_from` / `year_to`, so the difference is visible in the schema a model
# reads. `authorships.institutions.lineage` is accepted, hence the
# `institution` argument.

# Entities accepted by /autocomplete/<entity>.
AUTOCOMPLETE_ENTITIES = (
    "works", "authors", "sources", "institutions",
    "topics", "publishers", "funders", "keywords",
)

# Levels of the "aboutness" hierarchy, widest first, each with the filter key
# to feed back into `search_works` or `group_by`.
HIERARCHY_LEVELS = {
    "domains": "topics.domain.id",
    "fields": "topics.field.id",
    "subfields": "topics.subfield.id",
    "topics": "topics.id",
}

QUERY_FORMS = ("oql", "oqo", "oxurl")
CORPUS_CHOICES = ("core", "expansion", "all")


# ── HTTP client with retry / backoff ──────────────────────────────────────────

# One pooled client for the process. Opening an AsyncClient per call would
# rebuild the connection pool — and replay the TLS handshake — every time.
HTTP = httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True)


def _redact(message: Any) -> str:
    """Strip the API key from an error message.

    httpx puts the full URL, query parameters included, in `str(exc)`. Without
    this filter a 4xx copies the key into the payload the agent will log.
    """
    text = str(message)
    if API_KEY:
        text = text.replace(API_KEY, "***")
    return re.sub(r"(api_key=)[^&\s'\"]+", r"\1***", text)


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
                # The key never reaches a trace event: it is stripped here, not
                # at the point where the trace is returned.
                safe_params = {k: ("***" if k == "api_key" else v)
                               for k, v in request_params.items()}
                trace_events.append({
                    "event": "http_request", "method": "GET", "url": url,
                    "attempt": attempt + 1, "max_retries": MAX_RETRIES,
                    "params": safe_params,
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
                    "message": _redact(e),
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
                trace_events.append({"event": "http_error", "attempt": attempt + 1,
                                     "message": _redact(e)})
            raise

    raise RuntimeError(
        f"OpenAlex: failed after {MAX_RETRIES} attempts on {url} "
        f"(status={last_status}, error={_redact(last_error)})"
    )


# ── Identifiers ───────────────────────────────────────────────────────────────

def _short_id(value: str | None) -> str | None:
    """Reduce an OpenAlex URL to its short identifier.

    https://openalex.org/W123           -> W123
    https://openalex.org/fields/17      -> 17
    https://openalex.org/subfields/1707 -> 1707
    """
    if not value:
        return None
    tail = str(value).rstrip("/").rsplit("/", 1)[-1]
    return tail or None


def _meta_cost(data: dict) -> float | None:
    return (data.get("meta") or {}).get("cost_usd")


def _meta_oql(data: dict) -> str | None:
    """The OQL the API says it compiled — how to check a filter was understood,
    and how to get back to OQL from an ordinary request."""
    return ((data.get("meta") or {}).get("x_query") or {}).get("oql")


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


def _format_topic(topic: dict | None) -> dict | None:
    """Flatten an OpenAlex topic, keeping the identifier at every level: those
    are what feed back into a filter, not the display names."""
    if not topic:
        return None
    out: dict[str, Any] = {
        "id": _short_id(topic.get("id")),
        "display_name": topic.get("display_name"),
        "score": topic.get("score"),
    }
    for level in ("subfield", "field", "domain"):
        node = topic.get(level) or {}
        out[level] = {
            "id": _short_id(node.get("id")),
            "display_name": node.get("display_name"),
        } if node else None
    return out


def _format_work(work: dict) -> dict:
    authors, author_details = [], []
    for a in work.get("authorships", []):
        author = a.get("author", {})
        name = author.get("display_name", "")
        authors.append(name)
        author_details.append({
            "name": name,
            "orcid": author.get("orcid"),
            "openalex_id": _short_id(author.get("id")),
            "institutions": [i.get("display_name", "") for i in a.get("institutions", [])],
        })

    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    best_oa = work.get("best_oa_location") or {}
    raw_doi = work.get("doi") or None
    doi = raw_doi.replace("https://doi.org/", "") if isinstance(raw_doi, str) else None
    openalex_id = _short_id(work.get("id"))
    percentile = work.get("citation_normalized_percentile") or {}

    record = {
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
        "source_url": work.get("id"),
        "year": work.get("publication_year"),
        "date": work.get("publication_date") or str(work.get("publication_year") or ""),
        "doc_type": work.get("type"),
        "language": work.get("language"),
        "journal": source.get("display_name"),
        "cited_by_count": work.get("cited_by_count", 0),
        "referenced_works_count": work.get("referenced_works_count", 0),
        "is_open_access": (work.get("open_access") or {}).get("is_oa", False),
        "oa_status": (work.get("open_access") or {}).get("oa_status"),
        "is_retracted": work.get("is_retracted"),
        # Field- and year-normalized indicators: the only ones comparable across
        # disciplines.
        "fwci": work.get("fwci"),
        "citation_percentile": percentile.get("value"),
        "is_in_top_1_percent": percentile.get("is_in_top_1_percent"),
        "is_in_top_10_percent": percentile.get("is_in_top_10_percent"),
        # Topics as objects carrying ids, so a result turns back into a filter.
        "primary_topic": _format_topic(work.get("primary_topic")),
        "topics": [_format_topic(t) for t in work.get("topics", [])],
        "keywords": [k.get("display_name", "") for k in work.get("keywords", [])],
        "funders": sorted({
            (aw.get("funder") or {}).get("display_name")
            for aw in (work.get("awards") or [])
            if (aw.get("funder") or {}).get("display_name")
        }),
        "cited_by_api_url": work.get("cited_by_api_url"),
    }
    # `is_xpac` only means something outside the core corpus: expose it only
    # when the API returned it.
    if work.get("is_xpac") is not None:
        record["is_xpac"] = work.get("is_xpac")
    return record


# ── ID resolution ─────────────────────────────────────────────────────────────

async def _resolve_author_id(name_or_orcid: str, *, trace: bool = False) -> tuple[str | None, list[dict]]:
    """Resolve an author name or ORCID to an OpenAlex author ID."""
    events: list[dict] = []
    if "orcid.org" in name_or_orcid or name_or_orcid.startswith("0000-"):
        orcid = name_or_orcid if name_or_orcid.startswith("https://") else f"https://orcid.org/{name_or_orcid}"
        try:
            data, t = await _get(f"{OPENALEX_AUTHORS}/{orcid}", {}, trace=trace)
            events.extend(t)
            return _short_id(data.get("id")), events
        except Exception:
            return None, events

    data, t = await _get(OPENALEX_AUTHORS, {"search": name_or_orcid, "per-page": 1}, trace=trace)
    events.extend(t)
    results = data.get("results", [])
    return (_short_id(results[0].get("id")) if results else None), events


async def _resolve_institution_id(name_or_ror: str, *, trace: bool = False) -> tuple[str | None, list[dict]]:
    """Resolve an institution name or ROR URL to an OpenAlex institution ID.

    Autocomplete goes first: it is free, faster, and ranks by prominence where
    `?search=` ranks by textual relevance.
    """
    events: list[dict] = []
    if "ror.org" in name_or_ror:
        try:
            data, t = await _get(f"{OPENALEX_INSTITUTIONS}/{name_or_ror}", {}, trace=trace)
            events.extend(t)
            return _short_id(data.get("id")), events
        except Exception:
            return None, events

    try:
        data, t = await _get(f"{OPENALEX_AUTOCOMPLETE}/institutions", {"q": name_or_ror}, trace=trace)
        events.extend(t)
        results = data.get("results", [])
        if results:
            return _short_id(results[0].get("id")), events
    except Exception:
        pass

    data, t = await _get(OPENALEX_INSTITUTIONS, {"search": name_or_ror, "per-page": 1}, trace=trace)
    events.extend(t)
    results = data.get("results", [])
    return (_short_id(results[0].get("id")) if results else None), events


# ── Topic filters ─────────────────────────────────────────────────────────────

def _topic_filters(
    topic: str | None,
    subfield: str | None,
    field: str | None,
    domain: str | None,
    scope: str,
) -> list[str]:
    """Translate the topic arguments into OpenAlex filters.

    `scope="any"` queries all three topics of a work (`topics.*`, recall);
    `scope="primary"` keeps only the main one (`primary_topic.*`, precision).
    The two key families are symmetric.
    """
    prefix = "primary_topic" if scope == "primary" else "topics"
    out = []
    if topic:
        out.append(f"{prefix}.id:{_short_id(topic)}")
    if subfield:
        out.append(f"{prefix}.subfield.id:{_short_id(subfield)}")
    if field:
        out.append(f"{prefix}.field.id:{_short_id(field)}")
    if domain:
        out.append(f"{prefix}.domain.id:{_short_id(domain)}")
    return out


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
    Build the envelope every record tool of this server returns.

    `results` is always an array and `error` is always present (null on success),
    so an agent reads a degraded upstream out of the payload instead of having to
    catch a protocol fault. `total_found` is null when the source cannot count.

    Three tools answer in their own documented shape instead, because they
    return no records: `classify_text`, `group_by` and `translate_query`.
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
    instructions=(
        "OpenAlex connector — 250M+ scholarly works, their authors, "
        "institutions, funders and topics.\n\n"
        "Search by keyword (search_works) or by meaning (search_semantic); "
        "resolve DOIs (lookup_by_doi, free); follow citations (get_citing_works).\n\n"
        "Two tools make the others accurate and should usually come first: "
        "resolve_entity turns a name — institution, author, journal, funder — "
        "into the OpenAlex id AND the filter key that id belongs in, for free; "
        "browse_topics locates a subject in the 4-level hierarchy "
        "(4 domains / 26 fields / 252 subfields / 4516 topics). "
        "classify_text does the same from a text rather than a name.\n\n"
        "group_by answers 'how many', 'top N' and trend questions in one call "
        "without downloading any record. translate_query converts between "
        "OpenAlex query language, its JSON form and a REST URL, and validates "
        "a query before you pay to run it.\n\n"
        "Filter institutions on lineage (the default): it covers the "
        "institution and the labs attached to it. Usage is metered as a daily "
        "budget — $0.10/day anonymous, $1/day with a free key — so prefer the "
        "free tools when an identifier is already known; every billable "
        "response reports cost_usd."
    ),
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
    institution_scope: str = "lineage",
    topic: str | None = None,
    subfield: str | None = None,
    field: str | None = None,
    domain: str | None = None,
    topic_scope: str = "any",
    corpus: str = "core",
    exact: bool = False,
    cursor: str | None = None,
) -> dict:
    """
    Search OpenAlex for academic works by keyword query.

    Query syntax: "phrase in quotes", "near each other"~5, fuzzy~2,
    AND/OR/NOT in uppercase. Wildcards (* and ?) work only with exact=true,
    which also disables stemming — right for a gene symbol or a standard
    reference, wrong for an ordinary subject search.

    Args:
        query: Free-text search query.
        max_results: Number of results to return (max 100).
        date_from: Lower publication date bound (YYYY-MM-DD).
        date_to: Upper publication date bound (YYYY-MM-DD).
        filter_open_access: If true, return only open-access works.
        sort_by: Sort field, e.g. "cited_by_count:desc" or "publication_date:desc".
        author: Author name or ORCID (resolved automatically).
        institution: Institution name or ROR URL (resolved automatically).
        institution_scope: "lineage" (default) matches the institution and every
            lab, hospital and unit attached to it — what OpenAlex's own query
            language compiles "institution is …" to, and almost always what a
            user means. "exact" matches only works whose affiliation resolved to
            that one entity, and will miss a CNRS-affiliated lab.
        topic: Topic id, e.g. "T10601". Get one from browse_topics or classify_text.
        subfield: Subfield id, e.g. "1702".
        field: Field id, e.g. "17".
        domain: Domain id, e.g. "3".
        topic_scope: "any" (default) filters on all three topics a work carries —
            recall; "primary" keeps only works whose main subject it is —
            precision. The two counts routinely differ by a factor of three.
        corpus: "core" (default, ~320M curated works), "expansion" (~190M mostly
            datasets and repository records) or "all". Works only.
        exact: Use search.exact — no stemming, wildcards allowed.
        cursor: "*" to start deep paging, then the next_cursor of the previous
            response. Basic paging stops at 10,000 results.

    Returns:
        {"source": "openalex", "command": "search_works", "total_found": int,
         "returned": int, "results": [work, ...], "error": str | null,
         "query_used": str, "filters_used": [str], "corpus": str,
         "oql": str | null, "next_cursor": str | null, "cost_usd": float | null}
    """
    trace = TRACE_DEFAULT
    trace_events: list[dict] = []
    filters: list[str] = []

    if corpus not in CORPUS_CHOICES:
        return _envelope("search_works", query_used=query, filters_used=filters,
                         error=f"corpus must be one of {', '.join(CORPUS_CHOICES)}")
    if institution_scope not in ("lineage", "exact"):
        return _envelope("search_works", query_used=query, filters_used=filters,
                         error='institution_scope must be "lineage" or "exact"')
    if topic_scope not in ("any", "primary"):
        return _envelope("search_works", query_used=query, filters_used=filters,
                         error='topic_scope must be "any" or "primary"')

    if date_from:
        filters.append(f"from_publication_date:{date_from}")
    if date_to:
        filters.append(f"to_publication_date:{date_to}")
    if filter_open_access:
        filters.append("is_oa:true")

    def _fail(message: str) -> dict:
        out = _envelope("search_works", error=_redact(message),
                        query_used=query, filters_used=filters,
                        corpus=corpus, oql=None, next_cursor=None, cost_usd=None)
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
                return _fail(
                    f"Institution not found in OpenAlex: '{institution}'. "
                    "Autocomplete is diacritic-sensitive — try the accented "
                    "spelling, or pass a ROR."
                )
            key = ("authorships.institutions.lineage" if institution_scope == "lineage"
                   else "authorships.institutions.id")
            filters.append(f"{key}:{inst_id}")
    except (RuntimeError, httpx.HTTPError) as e:
        return _fail(str(e))

    filters.extend(_topic_filters(topic, subfield, field, domain, topic_scope))

    params: dict[str, Any] = {
        "search.exact" if exact else "search": query,
        "per-page": max(1, min(max_results, MAX_PER_PAGE)),
        "sort": sort_by,
        "select": SELECT_FIELDS,
    }
    if filters:
        params["filter"] = ",".join(filters)
    if corpus != "core":
        params["corpus"] = corpus
    if cursor:
        params["cursor"] = cursor

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
        corpus=corpus,
        oql=_meta_oql(data),
        next_cursor=data.get("meta", {}).get("next_cursor"),
        cost_usd=_meta_cost(data),
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
    institution: str | None = None,
    corpus: str = "core",
) -> dict:
    """
    Search OpenAlex by meaning rather than by keyword.

    Ranks works by semantic proximity to a descriptive text, so a paper matches
    even when it shares none of the words used to ask for it. Give it a sentence
    or a whole abstract — it is built for abstract-length input, not for two
    keywords. Use search_works instead when a keyword genuinely names the subject;
    running both and merging on doi is usually better than choosing.

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
        institution: Institution name or ROR (resolved automatically, filtered on
            lineage). Topic filters are not accepted by this endpoint.
        corpus: "core" (default), "expansion" or "all".

    Returns:
        {"source": "openalex", "command": "search_semantic", "total_found": null,
         "returned": int, "results": [work with "relevance_score", ...],
         "error": str | null, "query_used": str, "filters_used": [str],
         "corpus": str, "truncated": bool, "cost_usd": float | null}
    """
    trace = TRACE_DEFAULT
    trace_events: list[dict] = []
    text = (text or "").strip()
    filters: list[str] = []

    def _fail(message: str) -> dict:
        out = _envelope("search_semantic", total_found=None, error=_redact(message),
                        query_used=text[:SEMANTIC_MAX_CHARS], filters_used=filters,
                        corpus=corpus, truncated=len(text) > SEMANTIC_MAX_CHARS,
                        cost_usd=None)
        if trace:
            out["trace"] = trace_events
        return out

    if len(text) < 20:
        return _fail("Text too short (minimum 20 characters)")
    if corpus not in CORPUS_CHOICES:
        return _fail(f"corpus must be one of {', '.join(CORPUS_CHOICES)}")

    year_filter = _semantic_year_filter(year_from, year_to)
    if year_filter:
        filters.append(year_filter)
    if filter_open_access:
        filters.append("is_oa:true")
    if institution:
        try:
            inst_id, t = await _resolve_institution_id(institution, trace=trace)
            trace_events.extend(t)
        except (RuntimeError, httpx.HTTPError) as e:
            return _fail(str(e))
        if not inst_id:
            return _fail(f"Institution not found in OpenAlex: '{institution}'")
        filters.append(f"authorships.institutions.lineage:{inst_id}")

    params: dict[str, Any] = {
        "search.semantic": text[:SEMANTIC_MAX_CHARS],
        "per-page": max(1, min(max_results, SEMANTIC_MAX_RESULTS)),
        "select": SELECT_FIELDS + ",relevance_score",
    }
    if filters:
        params["filter"] = ",".join(filters)
    if corpus != "core":
        params["corpus"] = corpus

    try:
        data, t = await _get(OPENALEX_WORKS, params, trace=trace)
    except (RuntimeError, httpx.HTTPError) as e:
        return _fail(str(e))

    trace_events.extend(t)
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
        corpus=corpus,
        truncated=len(text) > SEMANTIC_MAX_CHARS,
        cost_usd=_meta_cost(data),
    )
    if trace:
        out["trace"] = trace_events
    return out


@mcp.tool
async def lookup_by_doi(dois: list[str]) -> dict:
    """
    Resolve one or more DOIs to full OpenAlex work records.

    Free: single-entity lookups are not billed. When the identifier is known,
    this is always cheaper than searching for it.

    Args:
        dois: List of DOIs in any format (short: "10.xxx/…" or full URL).
              Batched at 50 per request, which also keeps each URL under the
              API's ~4 KB limit.

    Returns:
        {"source": "openalex", "command": "lookup_by_doi", "total_found": int,
         "returned": int, "results": [work, ...], "error": str | null,
         "requested": int, "cost_usd": float | null}
        `requested` minus `returned` is how many DOIs went unmatched.
    """
    trace = TRACE_DEFAULT
    trace_events: list[dict] = []

    if not dois:
        return _envelope("lookup_by_doi", error="dois is required",
                         requested=0, cost_usd=None)

    all_results: list[dict] = []
    total_cost = 0.0
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
            out = _envelope("lookup_by_doi", error=_redact(e),
                            requested=len(dois), cost_usd=None)
            if trace:
                out["trace"] = trace_events
            return out
        trace_events.extend(t)
        all_results.extend(data.get("results", []))
        total_cost += _meta_cost(data) or 0.0
        if i + 50 < len(dois):
            await asyncio.sleep(0.15)

    out = _envelope(
        "lookup_by_doi",
        [_format_work(r) for r in all_results],
        total_found=len(all_results),
        error=None if all_results else f"No OpenAlex work matched the {len(dois)} DOI(s) given",
        requested=len(dois),
        cost_usd=round(total_cost, 6) or None,
    )
    if trace:
        out["trace"] = trace_events
    return out


@mcp.tool
async def get_citing_works(
    openalex_id: str,
    max_results: int = 20,
    cursor: str | None = None,
) -> dict:
    """
    Fetch works that cite a given OpenAlex work, sorted by citation count.

    Args:
        openalex_id: OpenAlex work ID — short form (W2741809807) or full URL.
        max_results: Number of citing works to return (max 100).
        cursor: "*" to start deep paging, then the next_cursor of the previous
            response. Basic paging stops at 10,000 results.

    Returns:
        {"source": "openalex", "command": "get_citing_works", "total_found": int,
         "returned": int, "results": [work, ...], "error": str | null,
         "cited_work_id": str, "next_cursor": str | null, "cost_usd": float | null}
    """
    trace = TRACE_DEFAULT
    clean_id = _short_id(openalex_id)
    params: dict[str, Any] = {
        "filter": f"cites:{clean_id}",
        "per-page": max(1, min(max_results, MAX_PER_PAGE)),
        "sort": "cited_by_count:desc",
        "select": SELECT_FIELDS,
    }
    if cursor:
        params["cursor"] = cursor
    try:
        data, t = await _get(OPENALEX_WORKS, params, trace=trace)
    except (RuntimeError, httpx.HTTPError) as e:
        return _envelope("get_citing_works", error=_redact(e),
                         cited_work_id=clean_id, next_cursor=None, cost_usd=None)

    results = data.get("results", [])
    out = _envelope(
        "get_citing_works",
        [_format_work(r) for r in results],
        total_found=data.get("meta", {}).get("count", 0),
        cited_work_id=clean_id,
        next_cursor=data.get("meta", {}).get("next_cursor"),
        cost_usd=_meta_cost(data),
    )
    if trace:
        out["trace"] = t
    return out


# ── classify_text ─────────────────────────────────────────────────────────────

CLASSIFY_LEVELS = (
    ("topics", "topics.id", lambda t: t),
    ("subfields", "topics.subfield.id", lambda t: t.get("subfield")),
    ("fields", "topics.field.id", lambda t: t.get("field")),
    ("domains", "topics.domain.id", lambda t: t.get("domain")),
)


def _aggregate_level(works: list[tuple[dict, float]], node_of) -> list[dict]:
    """Aggregate one level of the hierarchy over a sample of works.

    A work is weighted by its semantic relevance_score; within a work, a topic
    is weighted by its own score. The product keeps a weakly relevant work from
    counting as much as a close match.
    """
    acc: dict[str, dict] = {}
    for work, weight in works:
        seen: set[str] = set()
        for topic in work.get("topics") or []:
            node = node_of(topic) or {}
            node_id = _short_id(node.get("id"))
            if not node_id:
                continue
            entry = acc.setdefault(node_id, {
                "id": node_id,
                "display_name": node.get("display_name"),
                "score": 0.0,
                "works": 0,
            })
            entry["score"] += weight * float(topic.get("score") or 0.0)
            if node_id not in seen:
                entry["works"] += 1
                seen.add(node_id)
    total = sum(e["score"] for e in acc.values()) or 1.0
    ranked = sorted(acc.values(), key=lambda e: e["score"], reverse=True)
    for entry in ranked:
        entry["score"] = round(entry["score"] / total, 4)
    return ranked


@mcp.tool
async def classify_text(text: str, max_works: int = 25) -> dict:
    """
    Place a text in the OpenAlex topic hierarchy.

    OpenAlex retired its /text classification endpoint. This tool rebuilds the
    capability: one semantic search finds the nearest works, then their topics
    are aggregated weighted by relevance and rolled up to subfields, fields and
    domains. It costs a tenth of what /text did, and it returns real OpenAlex
    identifiers at all four levels plus the filter_keys needed to reuse them —
    which /text did not. Feed the ids straight back into search_works.

    Args:
        text: Text to classify (minimum 20 characters, truncated at 2000).
        max_works: Neighbouring works the classification is aggregated from (max 50).

    Returns:
        Its own shape, not the record envelope — this tool returns no records:
        {"source": "openalex", "command": "classify_text", "query_used": str,
         "truncated": bool, "based_on_works": int,
         "topics":    [{"id", "display_name", "score", "works"}, ...],
         "subfields": [...], "fields": [...], "domains": [...],
         "keywords": [str], "filter_keys": {level: filter_key},
         "cost_usd": float | null, "error": str | null}
    """
    trace = TRACE_DEFAULT
    text = (text or "").strip()

    def _fail(message: str) -> dict:
        return {
            "source": SERVER_NAME, "command": "classify_text",
            "query_used": text[:SEMANTIC_MAX_CHARS],
            "truncated": len(text) > SEMANTIC_MAX_CHARS, "based_on_works": 0,
            "topics": [], "subfields": [], "fields": [], "domains": [],
            "keywords": [], "filter_keys": {}, "cost_usd": None,
            "error": _redact(message),
        }

    if len(text) < 20:
        return _fail("Text too short (minimum 20 characters)")

    try:
        data, t = await _get(OPENALEX_WORKS, {
            "search.semantic": text[:SEMANTIC_MAX_CHARS],
            "per-page": max(1, min(max_works, SEMANTIC_MAX_RESULTS)),
            "select": "id,relevance_score,topics,keywords",
        }, trace=trace)
    except (RuntimeError, httpx.HTTPError) as e:
        return _fail(str(e))

    results = data.get("results", [])
    weighted = [(w, float(w.get("relevance_score") or 0.0)) for w in results]

    keyword_scores: dict[str, float] = {}
    for work, weight in weighted:
        for kw in work.get("keywords") or []:
            name = kw.get("display_name")
            if name:
                keyword_scores[name] = keyword_scores.get(name, 0.0) + weight * float(
                    kw.get("score") or 1.0
                )
    keywords = [
        k for k, _ in sorted(keyword_scores.items(), key=lambda kv: kv[1], reverse=True)
    ][:15]

    out: dict[str, Any] = {
        "source": SERVER_NAME,
        "command": "classify_text",
        "query_used": text[:SEMANTIC_MAX_CHARS],
        "truncated": len(text) > SEMANTIC_MAX_CHARS,
        "based_on_works": len(results),
    }
    for name, _filter_key, node_of in CLASSIFY_LEVELS:
        out[name] = _aggregate_level(weighted, node_of)[:10]
    out["keywords"] = keywords
    # The filter key per level: what makes the verdict actionable without the
    # agent having to guess the syntax.
    out["filter_keys"] = {name: key for name, key, _ in CLASSIFY_LEVELS}
    out["cost_usd"] = _meta_cost(data)
    out["error"] = None if results else "No neighbouring work found for this text"
    if trace:
        out["trace"] = t
    return out


# ── resolve_entity ────────────────────────────────────────────────────────────

# Stop-words and generic organisation words: present in thousands of names,
# they distinguish nothing. Removing them is what makes "université de
# Strasbourg" widen to "Strasbourg" rather than to "universite", which would
# match the first Vrije Universiteit in the index.
GENERIC_TOKENS = {
    "universite", "université", "university", "universität", "universiteit",
    "universidad", "universita", "institut", "institute", "college", "school",
    "laboratoire", "laboratory", "centre", "center", "national", "research",
    "hospital", "hopital", "ecole", "faculty", "faculte", "department",
    "departement", "the", "and", "for", "des", "les", "del", "della",
}


def _distinctive_token(query: str) -> str | None:
    """The longest word once generics are dropped. None if none is left, or if
    the query had only one word to begin with."""
    tokens = [t for t in re.split(r"[^\w]+", query, flags=re.UNICODE) if len(t) > 3]
    candidates = [t for t in tokens if t.lower() not in GENERIC_TOKENS]
    if not candidates or len(tokens) == 1:
        return None
    best = max(candidates, key=len)
    return best if best.lower() != query.lower() else None


def _shape_entity(r: dict, entity_type: str) -> dict:
    return {
        "source": SERVER_NAME,
        "id": _short_id(r.get("id")),
        "url": r.get("id"),
        "display_name": r.get("display_name"),
        "entity_type": r.get("entity_type") or entity_type.rstrip("s"),
        "hint": r.get("hint"),
        "external_id": r.get("external_id"),
        "works_count": r.get("works_count"),
        "cited_by_count": r.get("cited_by_count"),
        # Supplied by /autocomplete; absent on the full-text fallback, where the
        # API does not compute it.
        "filter_key": r.get("filter_key"),
    }


@mcp.tool
async def resolve_entity(
    query: str,
    entity_type: str = "institutions",
    max_results: int = 5,
) -> dict:
    """
    Resolve a name to an OpenAlex entity — id, external id, and filter key.

    Free, ~200 ms. Backed by /autocomplete, which returns a `filter_key`
    alongside each suggestion: the API itself telling you which filter that
    identifier belongs in ("authorships.institutions.lineage" for an
    institution, "topics.id" for a topic). Run this before filtering on a name.

    Autocomplete is prefix-based and diacritic-sensitive, and the two combine
    badly: "strasbourg" alone finds nothing because it is not a prefix of the
    name, and "universite de stras" finds nothing either because the name is
    spelled "Université". "université de stras" finds it on the first try.

    When the prefix match is empty, a widened search is tried and what it finds
    goes into `suggestions`, never into `results`, with `error` still set:
    silently substituting a neighbouring entity would hand a wrong id to a
    filter that will not contest it. The caller chooses.

    Args:
        query: Partial name — the beginning of it, accents included.
        entity_type: One of works, authors, sources, institutions, topics,
            publishers, funders, keywords.
        max_results: Number of candidates to return.

    Returns:
        {"source": "openalex", "command": "resolve_entity", "total_found": int,
         "returned": int, "results": [entity, ...], "suggestions": [entity, ...],
         "error": str | null, "query_used": str, "entity_type": str,
         "widened_query": str | null, "cost_usd": null}
    """
    trace = TRACE_DEFAULT
    query = (query or "").strip()

    def _fail(message: str, *, suggestions: list[dict] | None = None,
              widened: str | None = None) -> dict:
        return _envelope("resolve_entity", error=message,
                         suggestions=suggestions or [], query_used=query,
                         entity_type=entity_type, widened_query=widened,
                         cost_usd=None)

    if not query:
        return _fail("query is required")
    if entity_type not in AUTOCOMPLETE_ENTITIES:
        return _fail(f"entity_type must be one of {', '.join(AUTOCOMPLETE_ENTITIES)}")

    try:
        data, t = await _get(f"{OPENALEX_AUTOCOMPLETE}/{entity_type}", {"q": query}, trace=trace)
        results = data.get("results", [])
    except (RuntimeError, httpx.HTTPError) as e:
        return _fail(_redact(e))

    if not results:
        # Full-text fallback on the entity endpoint, reshaped like /autocomplete
        # so the caller has one schema to read.
        try:
            data, t = await _get(f"{OPENALEX_BASE}/{entity_type}", {
                "search": query, "per-page": max(1, min(max_results, MAX_PER_PAGE)),
            }, trace=trace)
            results = [
                {
                    "id": r.get("id"),
                    "display_name": r.get("display_name"),
                    "hint": r.get("description") if isinstance(r.get("description"), str) else None,
                    "external_id": (r.get("ids") or {}).get("ror")
                    or (r.get("ids") or {}).get("orcid")
                    or (r.get("ids") or {}).get("wikidata"),
                    "works_count": r.get("works_count"),
                    "cited_by_count": r.get("cited_by_count"),
                    "entity_type": entity_type.rstrip("s"),
                    "filter_key": None,
                }
                for r in data.get("results", [])
            ]
        except Exception:
            results = []

    if results:
        out = _envelope(
            "resolve_entity",
            [_shape_entity(r, entity_type) for r in results[:max_results]],
            total_found=len(results),
            suggestions=[],
            query_used=query,
            entity_type=entity_type,
            widened_query=None,
            cost_usd=None,
        )
        if trace:
            out["trace"] = t
        return out

    suggestions: list[dict] = []
    token = _distinctive_token(query)
    if token:
        try:
            data, _t = await _get(f"{OPENALEX_AUTOCOMPLETE}/{entity_type}", {"q": token}, trace=trace)
            suggestions = [_shape_entity(r, entity_type)
                           for r in data.get("results", [])[:max_results]]
        except Exception:
            suggestions = []

    hint = (
        f" Widened to '{token}': {len(suggestions)} candidate(s) in `suggestions`, "
        "to be checked before use." if suggestions else ""
    )
    return _fail(
        f"No '{entity_type}' entity for '{query}'. Autocomplete is "
        "diacritic-sensitive and prefix-based: try the accented spelling, a "
        "single distinctive word, or an external id (ROR, ORCID)." + hint,
        suggestions=suggestions,
        widened=token,
    )


@mcp.tool
async def browse_topics(
    level: str = "topics",
    query: str | None = None,
    field: str | None = None,
    domain: str | None = None,
    max_results: int = 25,
) -> dict:
    """
    Explore the OpenAlex "aboutness" hierarchy.

    Four levels: 4 domains → 26 fields → 252 subfields → 4,516 topics. Each
    record carries the short id, its parent levels, works_count, and the
    filter_key for that level — feed the id back into search_works or group_by.

    Args:
        level: "domains", "fields", "subfields" or "topics" (default).
        query: Full-text search within the level. Without it, results come back
            ordered by works_count.
        field: Restrict to a field id, e.g. "17".
        domain: Restrict to a domain id, e.g. "3".
        max_results: Number of entries to return (max 100).

    Returns:
        {"source": "openalex", "command": "browse_topics", "total_found": int,
         "returned": int, "results": [topic-like, ...], "error": str | null,
         "level": str, "query_used": str | null, "filters_used": [str],
         "cost_usd": float | null}
    """
    trace = TRACE_DEFAULT
    if level not in HIERARCHY_LEVELS:
        return _envelope("browse_topics",
                         error=f"level must be one of {', '.join(HIERARCHY_LEVELS)}",
                         level=level, query_used=query, filters_used=[], cost_usd=None)

    params: dict[str, Any] = {"per-page": max(1, min(max_results, MAX_PER_PAGE))}
    if query:
        params["search"] = query
    filters = []
    if field:
        filters.append(f"field.id:{_short_id(field)}")
    if domain:
        filters.append(f"domain.id:{_short_id(domain)}")
    if filters:
        params["filter"] = ",".join(filters)
    if not query:
        params["sort"] = "works_count:desc"

    try:
        data, t = await _get(f"{OPENALEX_BASE}/{level}", params, trace=trace)
    except (RuntimeError, httpx.HTTPError) as e:
        return _envelope("browse_topics", error=_redact(e), level=level,
                         query_used=query, filters_used=filters, cost_usd=None)

    formatted = []
    for r in data.get("results", []):
        record = {
            "source": SERVER_NAME,
            "id": _short_id(r.get("id")),
            "url": r.get("id"),
            "display_name": r.get("display_name"),
            "level": level.rstrip("s"),
            "description": r.get("description"),
            "keywords": r.get("keywords") or [],
            "works_count": r.get("works_count"),
            "cited_by_count": r.get("cited_by_count"),
            "filter_key": HIERARCHY_LEVELS[level],
        }
        for parent in ("subfield", "field", "domain"):
            node = r.get(parent)
            if node:
                record[parent] = {
                    "id": _short_id(node.get("id")),
                    "display_name": node.get("display_name"),
                }
        formatted.append(record)

    out = _envelope(
        "browse_topics",
        formatted,
        total_found=data.get("meta", {}).get("count", 0),
        level=level,
        query_used=query,
        filters_used=filters,
        cost_usd=_meta_cost(data),
    )
    if trace:
        out["trace"] = t
    return out


@mcp.tool
async def group_by(
    dimension: str,
    query: str | None = None,
    filters: str | None = None,
    entity: str = "works",
    include_unknown: bool = False,
    max_groups: int = 100,
) -> dict:
    """
    Count along a dimension without retrieving any record.

    Answers "how many", "which are the top" and "how has it evolved" in one
    call, at the price of a single request whatever the size of the set being
    aggregated — the cheapest way to frame a corpus before walking it.

    Args:
        dimension: Any filter key, e.g. "publication_year", "type",
            "open_access.oa_status", "topics.field.id",
            "authorships.institutions.lineage".
        query: Restrict to a keyword search.
        filters: Raw OpenAlex filter string, comma-separated, e.g.
            "authorships.institutions.lineage:I68947357,is_oa:true".
        entity: Entity endpoint to aggregate, "works" by default.
        include_unknown: Also count records with no value for the dimension.
        max_groups: Groups to return (max 100). `groups_count` reports the real
            number of distinct groups, which can exceed it — narrow the filters
            rather than paging.

    Returns:
        Its own shape, not the record envelope — this tool returns no records:
        {"source": "openalex", "command": "group_by", "entity": str,
         "dimension": str, "query_used": str | null, "filters_used": str | null,
         "total_found": int, "groups_count": int,
         "groups": [{"key", "key_url", "key_display_name", "count"}, ...],
         "oql": str | null, "cost_usd": float | null, "error": str | null}
        `total_found` is the number of records aggregated, not the number of groups.
    """
    trace = TRACE_DEFAULT

    def _shell(**over: Any) -> dict:
        out = {
            "source": SERVER_NAME, "command": "group_by", "entity": entity,
            "dimension": dimension, "query_used": query, "filters_used": filters,
            "total_found": None, "groups_count": None, "groups": [],
            "oql": None, "cost_usd": None, "error": None,
        }
        out.update(over)
        return out

    if not dimension:
        return _shell(error="dimension is required")

    key = f"{dimension}:include_unknown" if include_unknown else dimension
    params: dict[str, Any] = {
        "group_by": key,
        "per-page": max(1, min(max_groups, MAX_PER_PAGE)),
    }
    if query:
        params["search"] = query
    if filters:
        params["filter"] = filters

    try:
        data, t = await _get(f"{OPENALEX_BASE}/{entity}", params, trace=trace)
    except (RuntimeError, httpx.HTTPError) as e:
        return _shell(error=_redact(e))

    groups = [
        {
            "key": _short_id(g.get("key")) if str(g.get("key", "")).startswith("http")
            else g.get("key"),
            "key_url": g.get("key") if str(g.get("key", "")).startswith("http") else None,
            "key_display_name": g.get("key_display_name"),
            "count": g.get("count"),
        }
        for g in data.get("group_by", [])
    ]
    meta = data.get("meta", {})
    out = _shell(
        total_found=meta.get("count"),
        groups_count=meta.get("groups_count"),
        groups=groups,
        oql=_meta_oql(data),
        cost_usd=_meta_cost(data),
    )
    if trace:
        out["trace"] = t
    return out


@mcp.tool
async def translate_query(query: str, form: str = "oql") -> dict:
    """
    Translate a query between OQL, OQO and a REST URL, and validate it.

    Three forms of the same query: OQL (readable text, "works where institution
    is Sorbonne Université"), OQO (a JSON object) and oxurl (the REST URL).
    `form` names what you are giving it. Translation never touches the index and
    is billed at the cheapest rate — a thousandth of what running the wrong
    search would cost — so it is the way to check a filter before paying for it,
    and how you discover that "institution is X" compiles to
    authorships.institutions.lineage rather than .id.

    Args:
        query: The query, in the form named by `form`.
        form: "oql" (default), "oqo" or "oxurl" — the form of the INPUT.

    Returns:
        Its own shape, not the record envelope — this tool returns no records:
        {"source": "openalex", "command": "translate_query", "form": str,
         "query_used": str, "valid": bool, "oql": str | null,
         "oql_oneline": str | null, "oqo": object | null, "oxurl": str | null,
         "api_url": str | null, "diagnostics": [...], "error": str | null}
        An invalid query comes back valid:false with the parser's own message in
        `error` and the full list in `diagnostics` — a diagnosis, not a fault.
    """
    trace = TRACE_DEFAULT
    query = (query or "").strip()

    def _shell(**over: Any) -> dict:
        out = {
            "source": SERVER_NAME, "command": "translate_query", "form": form,
            "query_used": query, "valid": False, "oql": None, "oql_oneline": None,
            "oqo": None, "oxurl": None, "api_url": None, "diagnostics": [],
            "error": None,
        }
        out.update(over)
        return out

    if not query:
        return _shell(error="query is required")
    if form not in QUERY_FORMS:
        return _shell(error=f"form must be one of {', '.join(QUERY_FORMS)}")

    # The query is a path segment, not a parameter: /query/oql?q=… is read as an
    # identifier and answers "OpenAlex ID format not recognized".
    url = f"{OPENALEX_QUERY}/{form}/{urllib.parse.quote(query, safe='')}"
    try:
        data, t = await _get(url, {}, trace=trace)
    except httpx.HTTPStatusError as exc:
        # A query that does not parse answers 400 with a structured body: that
        # is a diagnosis, not an outage. Any other status is an outage — an
        # exhausted budget answers 429, and its body is not a diagnosis.
        if exc.response.status_code != 400:
            return _shell(error=_redact(exc))
        try:
            data, t = exc.response.json(), []
        except Exception:
            return _shell(error=_redact(exc))
    except (RuntimeError, httpx.HTTPError) as e:
        return _shell(error=_redact(e))

    # Two shapes depending on the status: 200 returns `diagnostics` (empty when
    # all is well), 400 returns `validation.errors`. Reduce them to one list.
    validation = data.get("validation") or {}
    diagnostics = data.get("diagnostics") or validation.get("errors") or []
    valid = data.get("valid")
    if valid is None:
        valid = validation.get("valid")
    if valid is None:
        valid = bool(data.get("oql") or data.get("oxurl") or data.get("oqo"))

    first_message = None
    if diagnostics:
        first = diagnostics[0]
        first_message = first.get("message") if isinstance(first, dict) else str(first)

    # `oql_render_v2` is a render tree meant for editors: thousands of tokens an
    # agent does nothing with. Not returned.
    out = _shell(
        valid=bool(valid),
        oql=data.get("oql"),
        oql_oneline=data.get("oql_oneline"),
        oqo=data.get("oqo"),
        oxurl=data.get("oxurl"),
        api_url=f"{OPENALEX_BASE}{data['oxurl']}" if data.get("oxurl") else None,
        diagnostics=diagnostics,
        error=None if valid else (
            first_message or data.get("message") or "Query could not be translated"
        ),
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
