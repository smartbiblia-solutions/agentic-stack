#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ['fastmcp>=3.4,<4', 'httpx']
# ///
"""OpenCitations MCP server.

Exposes the two OpenCitations REST APIs to agent clients: Meta v1 (bibliographic
metadata of the documents involved in citations) and Index v2 (the citation
entities themselves). Both are CC0 and usable anonymously; a token only raises
the quota.

Three API facts shape every tool here, all verified against the live service:
  - there is NO search operation — every entry point is a known identifier, so
    works are discovered elsewhere (OpenAlex, HAL) and explained here;
  - the list endpoints have no pagination and no server-side limit: one work
    returned 24 354 edges / 9.9 MB, and very large works answer HTTP 500 after
    four minutes. The cheap count endpoint is called first, and a list beyond
    MAX_LISTABLE_EDGES is refused with its count instead of attempted;
  - the server sometimes answers HTTP 200 with truncated, invalid JSON; that is
    retried once, then reported in `error`.

Transport is a flag: --transport stdio | http | sse (default http;
"streamable-http" is accepted as an alias of "http"). Add --stateless to serve
HTTP with a new transport per request, so no session is pinned to a replica —
what a load-balanced or multi-worker deployment needs. Incompatible with sse.

  uv run mcp_server.py --transport stdio
  uv run mcp_server.py --host 0.0.0.0 --port 8018 --transport http
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import re
import time
from typing import Any, Literal

import httpx
from fastmcp import FastMCP


API_URL = os.environ.get("OPENCITATIONS_API_URL", "https://api.opencitations.net").rstrip("/")
API_KEY = os.environ.get("OPENCITATIONS_API_KEY", "").strip()

META = f"{API_URL}/meta/v1"
INDEX = f"{API_URL}/index/v2"

SOURCE = "opencitations"
USER_AGENT = "smartbiblia-opencitations-mcp/0.1"
RETRIED_STATUS = {429, 500, 502, 503, 504}

# Above this many edges the upstream list endpoint is unusable: minutes of
# latency, or HTTP 500. Refuse early and return the count instead.
MAX_LISTABLE_EDGES = 5000
MAX_RESULTS_CAP = 500
# `/metadata/{ids}` joins identifiers with `__`; the only real bound is URL
# length, so batch conservatively.
METADATA_BATCH = 10


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OpenCitations MCP server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default=os.environ.get("MCP_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MCP_PORT", "8018")))
    parser.add_argument(
        "--transport",
        default=os.environ.get("MCP_TRANSPORT", "http"),
        choices=["stdio", "http", "sse", "streamable-http"],
        help='Transport ("streamable-http" is an alias of "http")',
    )
    parser.add_argument(
        "--stateless",
        action="store_true",
        default=os.environ.get("MCP_STATELESS", "").lower() in ("1", "true", "yes"),
        help="Stateless HTTP: new transport per request, no session affinity",
    )
    # A citation list is measured in megabytes, hence the wide default timeout.
    parser.add_argument("--http-timeout", type=float, default=60.0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--backoff-base", type=float, default=1.0)
    parser.add_argument("--backoff-factor", type=float, default=2.0)
    parser.add_argument("--jitter-max", type=float, default=0.25)
    parser.add_argument("--trace", action="store_true", default=False)
    ns = parser.parse_args()
    # FastMCP raises on this combination; fail here instead, with a usage message.
    if ns.stateless and ns.transport == "sse":
        parser.error("--stateless is not supported by the sse transport; use --transport http")
    return ns


args = _parse_args()

HTTP_TIMEOUT = args.http_timeout
MAX_RETRIES = max(1, args.max_retries)
BACKOFF_BASE = max(0.0, args.backoff_base)
BACKOFF_FACTOR = max(1.0, args.backoff_factor)
JITTER_MAX = max(0.0, args.jitter_max)
TRACE_DEFAULT = args.trace

mcp = FastMCP(
    name="opencitations",
    instructions=(
        "OpenCitations connector — citation counts, citing and cited works, and "
        "open bibliographic metadata, from OpenCitations Meta v1 and Index v2 "
        "(CC0, no key). Identifier-driven: there is no search operation. Bring a "
        "DOI, PMID, OMID or ORCID obtained elsewhere. Call get_citation_counts "
        "before listing: heavily cited works cannot be listed at all."
    ),
)

_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}
if API_KEY:
    # OpenCitations expects the raw token, with no scheme prefix.
    _HEADERS["authorization"] = API_KEY

# One pooled client for the process. Opening an AsyncClient per call would
# rebuild the connection pool — and replay the TLS handshake — every time.
HTTP = httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True, headers=_HEADERS)


# ── HTTP ──────────────────────────────────────────────────────────────────────

def _backoff_sleep_seconds(attempt: int) -> float:
    base = BACKOFF_BASE * (BACKOFF_FACTOR ** attempt)
    return base + (random.uniform(0.0, JITTER_MAX) if JITTER_MAX > 0 else 0.0)


async def _get_json(
    url: str, *, trace: bool = False,
) -> tuple[Any, str | None, list[dict[str, Any]]]:
    """GET with bounded retries. Returns (payload, error, trace_events).

    Never raises: an upstream failure is a successful tool call carrying
    `error`, so a client reads the failure instead of a protocol exception.
    """
    events: list[dict[str, Any]] = []
    for attempt in range(1, MAX_RETRIES + 1):
        t0 = time.perf_counter()
        try:
            if trace:
                events.append({"event": "http_request", "url": url, "attempt": attempt})
            resp = await HTTP.get(url)
            if trace:
                events.append({"event": "http_response", "status_code": resp.status_code,
                               "attempt": attempt, "bytes": len(resp.content),
                               "elapsed_ms": int((time.perf_counter() - t0) * 1000)})

            if resp.status_code in RETRIED_STATUS and attempt < MAX_RETRIES:
                await asyncio.sleep(_backoff_sleep_seconds(attempt))
                continue
            if resp.status_code >= 400:
                # A rejected token answers 403 with a plain-text body.
                return None, f"HTTP {resp.status_code} on {url}: {resp.text[:200].strip()}", events

            try:
                return resp.json(), None, events
            except ValueError:
                # Truncated payloads arrive with HTTP 200; one more try is worth it.
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(_backoff_sleep_seconds(attempt))
                    continue
                return None, (f"Truncated or non-JSON response from {url} "
                              f"({len(resp.content)} bytes). The work is probably too "
                              f"large for the upstream list endpoint."), events

        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if trace:
                events.append({"event": "http_error", "attempt": attempt, "message": str(exc)})
            if attempt == MAX_RETRIES:
                return None, f"Request failed: {exc}", events
            await asyncio.sleep(_backoff_sleep_seconds(attempt))

    return None, "Request failed (exhausted retries)", events


# ── Normalization ─────────────────────────────────────────────────────────────

_AGENT_RE = re.compile(r"^\s*(?P<name>.*?)\s*(?:\[(?P<ids>[^\]]*)\])?\s*$")
_TIMESPAN_RE = re.compile(r"^(?P<sign>-?)P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)D)?$")


def _identifiers(raw: str | None) -> dict[str, str]:
    """`"doi:10.1/x omid:br/061"` -> `{"doi": "10.1/x", "omid": "br/061"}`."""
    out: dict[str, str] = {}
    for token in (raw or "").split():
        scheme, sep, value = token.partition(":")
        if sep and value and scheme not in out:
            out[scheme] = value
    return out


def _agents(raw: str | None) -> list[dict[str, Any]]:
    """`"Peroni, Silvio [orcid:0000-…]; Shotton, David [omid:ra/06…]"` -> records."""
    agents: list[dict[str, Any]] = []
    for chunk in (raw or "").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = _AGENT_RE.match(chunk)
        name = (m.group("name") or "").strip() if m else chunk
        ids = _identifiers(m.group("ids") if m else None)
        if name:
            agents.append({"name": name, "orcid": ids.get("orcid"), "omid": ids.get("omid")})
    return agents


def _venue(raw: str | None) -> dict[str, Any] | None:
    """`"Journal of Documentation [issn:0022-0418 omid:br/06…]"` -> title + ids."""
    if not (raw or "").strip():
        return None
    m = _AGENT_RE.match(raw or "")
    title = (m.group("name") or "").strip() if m else (raw or "").strip()
    ids = _identifiers(m.group("ids") if m else None)
    return {"title": title or None, "issn": ids.get("issn"), "omid": ids.get("omid")}


def _timespan_days(raw: str | None) -> int | None:
    """`"P6Y0M1D"` -> 2191. Approximate: 365-day years, 30-day months."""
    m = _TIMESPAN_RE.match((raw or "").strip())
    if not m:
        return None
    years, months, days = (int(g) if g else 0 for g in m.groups()[1:])
    total = years * 365 + months * 30 + days
    return -total if m.group("sign") else total


def _work_url(ids: dict[str, str]) -> str | None:
    if "doi" in ids:
        return f"https://doi.org/{ids['doi']}"
    if "omid" in ids:
        return f"https://opencitations.net/meta/{ids['omid']}"
    if "pmid" in ids:
        return f"https://pubmed.ncbi.nlm.nih.gov/{ids['pmid']}/"
    return None


def _normalize_meta(rec: dict[str, Any]) -> dict[str, Any]:
    """A Meta record, in the shape the bibliographic connectors share.

    `abstract` is always null — Meta carries none — but is kept so results merge
    with OpenAlex/HAL/Sudoc/Primo hits on `doi`.
    """
    ids = _identifiers(rec.get("id"))
    date = (rec.get("pub_date") or "").strip() or None
    venue = _venue(rec.get("venue"))
    return {
        "source": SOURCE,
        "id": ids.get("omid") or ids.get("doi") or (rec.get("id") or "").strip() or None,
        "url": _work_url(ids),
        "title": (rec.get("title") or "").strip() or None,
        "authors": _agents(rec.get("author")),
        "abstract": None,
        "doi": ids.get("doi"),
        "year": date[:4] if date else None,
        "date": date,
        "doc_type": (rec.get("type") or "").strip() or None,
        "journal": venue["title"] if venue else None,
        "venue": venue,
        "publisher": _agents(rec.get("publisher")),
        "editors": _agents(rec.get("editor")),
        "volume": (rec.get("volume") or "").strip() or None,
        "issue": (rec.get("issue") or "").strip() or None,
        "page": (rec.get("page") or "").strip() or None,
        "identifiers": ids,
        "raw": rec,
    }


def _normalize_edge(rec: dict[str, Any]) -> dict[str, Any]:
    """A citation edge. Its own record family — not a bibliographic record."""
    oci = (rec.get("oci") or "").strip() or None
    return {
        "source": SOURCE,
        "id": oci,
        "url": f"https://opencitations.net/index/ci/{oci}" if oci else None,
        "citing": _identifiers(rec.get("citing")),
        "cited": _identifiers(rec.get("cited")),
        "creation": (rec.get("creation") or "").strip() or None,
        "timespan": (rec.get("timespan") or "").strip() or None,
        "timespan_days": _timespan_days(rec.get("timespan")),
        "journal_sc": (rec.get("journal_sc") or "").strip() or None,
        "author_sc": (rec.get("author_sc") or "").strip() or None,
        "raw": rec,
    }


def _envelope(command: str, **extra: Any) -> dict[str, Any]:
    return {"source": SOURCE, "command": command,
            "total_found": None, "returned": 0, "results": [], **extra, "error": None}


# ── Shared helpers ────────────────────────────────────────────────────────────

async def _count(kind: str, identifier: str, *, trace: bool) -> tuple[
        int | None, str | None, list[dict[str, Any]]]:
    """kind is "citation" or "reference"."""
    payload, error, events = await _get_json(f"{INDEX}/{kind}-count/{identifier}", trace=trace)
    if error:
        return None, error, events
    if not isinstance(payload, list) or not payload:
        return 0, None, events
    try:
        return int(payload[0].get("count", 0)), None, events
    except (AttributeError, TypeError, ValueError):
        return None, f"Unreadable {kind} count for {identifier}", events


def _pick_lookup_id(ids: dict[str, str]) -> str | None:
    for scheme in ("doi", "pmid", "omid"):
        if scheme in ids:
            return f"{scheme}:{ids[scheme]}"
    return None


async def _hydrate(edges: list[dict[str, Any]], side: str, *, trace: bool) -> tuple[
        str | None, list[dict[str, Any]]]:
    """Attach a `<side>_work` Meta record to each edge, batched by METADATA_BATCH."""
    wanted: dict[str, Any] = {}
    order: list[str] = []
    for edge in edges:
        key = _pick_lookup_id(edge[side])
        if key and key not in wanted:
            wanted[key] = None
            order.append(key)

    errors: list[str] = []
    events: list[dict[str, Any]] = []
    for start in range(0, len(order), METADATA_BATCH):
        batch = order[start:start + METADATA_BATCH]
        payload, error, evs = await _get_json(f"{META}/metadata/{'__'.join(batch)}", trace=trace)
        events.extend(evs)
        if error:
            errors.append(error)
            continue
        for rec in payload if isinstance(payload, list) else []:
            record = _normalize_meta(rec)
            for scheme, value in record["identifiers"].items():
                key = f"{scheme}:{value}"
                if key in wanted and wanted[key] is None:
                    wanted[key] = record

    for edge in edges:
        key = _pick_lookup_id(edge[side])
        edge[f"{side}_work"] = wanted.get(key) if key else None

    return ("; ".join(errors) if errors else None), events


async def _list_edges(
    command: str,
    identifier: str,
    max_results: int,
    sort: str | None,
    exclude_self_citations: bool,
    hydrate: bool,
    trace: bool | None,
) -> dict[str, Any]:
    """`get_citations` and `get_references` differ only by endpoint and by which
    end of the edge carries the other work."""
    endpoint, count_kind, side = {
        "get_citations": ("citations", "citation", "citing"),
        "get_references": ("references", "reference", "cited"),
    }[command]

    include_trace = TRACE_DEFAULT if trace is None else trace
    rows = max(1, min(int(max_results), MAX_RESULTS_CAP))
    out = _envelope(command, id=identifier)
    events: list[dict[str, Any]] = []

    total, error, evs = await _count(count_kind, identifier, trace=include_trace)
    events.extend(evs)
    out["total_found"] = total
    if error:
        out["error"] = error
        if include_trace:
            out["trace"] = events
        return out

    if total and total > MAX_LISTABLE_EDGES:
        out["error"] = (
            f"{total} results exceed the safe listing threshold of {MAX_LISTABLE_EDGES}: "
            f"the OpenCitations list endpoint has no pagination and fails or times out "
            f"at this size. Use total_found, or narrow the question to a smaller work."
        )
        if include_trace:
            out["trace"] = events
        return out

    if not total:
        if include_trace:
            out["trace"] = events
        return out

    payload, error, evs = await _get_json(f"{INDEX}/{endpoint}/{identifier}", trace=include_trace)
    events.extend(evs)
    if error:
        out["error"] = error
        if include_trace:
            out["trace"] = events
        return out

    edges = [_normalize_edge(r) for r in payload if isinstance(r, dict)] \
        if isinstance(payload, list) else []

    if exclude_self_citations:
        kept = [e for e in edges if e["journal_sc"] != "yes" and e["author_sc"] != "yes"]
        out["excluded_self_citations"] = len(edges) - len(kept)
        edges = kept

    if sort:
        field, _, direction = sort.partition("-")
        edges.sort(key=lambda e: e[field] or "", reverse=(direction == "desc"))

    edges = edges[:rows]

    if hydrate and edges:
        out["error"], evs = await _hydrate(edges, side, trace=include_trace)
        events.extend(evs)

    out["results"] = edges
    out["returned"] = len(edges)
    if include_trace:
        out["trace"] = events
    return out


# ── Tools ─────────────────────────────────────────────────────────────────────

SortField = Literal["creation-asc", "creation-desc", "timespan_days-asc", "timespan_days-desc"]


@mcp.tool
async def get_citation_counts(ids: list[str], trace: bool | None = None) -> dict[str, Any]:
    """
    Count the citations received and the references made by one or more works.

    The cheap call, and the one to make first: it is the only reliable way to
    know whether `get_citations` or `get_references` can run at all on a given
    work. Above ~5 000 edges the upstream list endpoint fails, and those tools
    will return the count with an explanatory error instead of a list.

    Domain rules:
      - Identifiers carry their scheme prefix and must be `doi:`, `pmid:` or
        `omid:`. The three give identical results for the same work.
      - An unknown identifier is not an error: it answers with counts of 0. Zero
        and "absent from OpenCitations" are indistinguishable here.
      - Counts include journal and author self-citations. Use
        `get_citations(exclude_self_citations=True)` to quantify them.

    Args:
        ids: Identifiers with their scheme prefix, e.g. ["doi:10.1108/jd-12-2013-0166", "pmid:2942070"].
        trace: Include the HTTP trace in the response.

    Returns:
        {
          "source": "opencitations",
          "command": "get_citation_counts",
          "total_found": int,
          "returned": int,
          "results": [
            {"source": "opencitations", "id": str, "url": str | null,
             "citation_count": int | null, "reference_count": int | null}
          ],
          "error": str | null
        }
    """
    include_trace = TRACE_DEFAULT if trace is None else trace
    out = _envelope("get_citation_counts")
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    events: list[dict[str, Any]] = []

    for identifier in ids:
        citations, err_c, evs_c = await _count("citation", identifier, trace=include_trace)
        references, err_r, evs_r = await _count("reference", identifier, trace=include_trace)
        events.extend(evs_c + evs_r)
        errors.extend(e for e in (err_c, err_r) if e)
        results.append({
            "source": SOURCE,
            "id": identifier,
            "url": _work_url(_identifiers(identifier)),
            "citation_count": citations,
            "reference_count": references,
        })

    out["results"] = results
    out["returned"] = len(results)
    out["total_found"] = len(results)
    if errors:
        out["error"] = "; ".join(errors)
    if include_trace:
        out["trace"] = events
    return out


@mcp.tool
async def get_citations(
    id: str,
    max_results: int = 20,
    sort: SortField | None = None,
    exclude_self_citations: bool = False,
    hydrate: bool = False,
    trace: bool | None = None,
) -> dict[str, Any]:
    """
    List the works citing a given work — the incoming citation edges.

    Use `get_citation_counts` first for the count alone; use `get_references`
    for the other direction. There is no search tool on this server: a work is
    discovered elsewhere and identified here.

    Domain rules:
      - The API has no pagination and no server-side limit, so the whole set is
        downloaded and `max_results` clamps client-side. It saves tokens, not
        bandwidth: 24 354 edges / 9.9 MB was measured on one work.
      - Above 5 000 citations the list is refused, and the response carries
        `total_found` plus an explanatory `error`.
      - `sort` is applied client-side. The API's own `sort` and `filter`
        parameters take over a minute and return truncated JSON at scale.
      - `journal_sc` and `author_sc` mark journal and author self-citations;
        `exclude_self_citations` drops both and reports how many in
        `excluded_self_citations`.

    Args:
        id: Identifier with its scheme prefix: "doi:…", "pmid:…" or "omid:br/…".
        max_results: Clamp applied after the download, capped at 500.
        sort: Client-side ordering, by citing-work date or by publication gap.
        exclude_self_citations: Drop edges where journal_sc or author_sc is "yes".
        hydrate: Attach `citing_work`, the Meta record of the citing work. One extra request per 10 works.
        trace: Include the HTTP trace in the response.

    Returns:
        {
          "source": "opencitations",
          "command": "get_citations",
          "id": str,
          "total_found": int | null,      // the true count, before any clamp
          "returned": int,
          "results": [
            {"source": "opencitations", "id": "<oci>", "url": str,
             "citing": {"doi": str, "omid": str, ...},
             "cited":  {"doi": str, "omid": str, ...},
             "creation": "YYYY-MM-DD" | null,
             "timespan": "PnYnMnD" | null, "timespan_days": int | null,
             "journal_sc": "yes" | "no" | null, "author_sc": "yes" | "no" | null,
             "citing_work": { /* Meta record, only with hydrate=True */ },
             "raw": { }}
          ],
          "error": str | null
        }
    """
    return await _list_edges("get_citations", id, max_results, sort,
                             exclude_self_citations, hydrate, trace)


@mcp.tool
async def get_references(
    id: str,
    max_results: int = 20,
    sort: SortField | None = None,
    exclude_self_citations: bool = False,
    hydrate: bool = False,
    trace: bool | None = None,
) -> dict[str, Any]:
    """
    List the works cited by a given work — the outgoing citation edges.

    The reference list as OpenCitations knows it, which is what its publisher
    deposited: it can be shorter than the printed bibliography. With
    `hydrate=True` it becomes a ready-made corpus around a seed paper.

    Domain rules are those of `get_citations`, in the other direction: no
    pagination, client-side clamp and sort, refusal above 5 000 edges. Reference
    lists are rarely that large, so the guard almost never fires here.

    Args:
        id: Identifier with its scheme prefix: "doi:…", "pmid:…" or "omid:br/…".
        max_results: Clamp applied after the download, capped at 500.
        sort: Client-side ordering, by citing-work date or by publication gap.
        exclude_self_citations: Drop edges where journal_sc or author_sc is "yes".
        hydrate: Attach `cited_work`, the Meta record of the cited work. One extra request per 10 works.
        trace: Include the HTTP trace in the response.

    Returns:
        Same envelope and edge shape as `get_citations`, with "command":
        "get_references" and, under hydrate, `cited_work` instead of
        `citing_work`.
    """
    return await _list_edges("get_references", id, max_results, sort,
                             exclude_self_citations, hydrate, trace)


@mcp.tool
async def lookup_metadata(ids: list[str], trace: bool | None = None) -> dict[str, Any]:
    """
    Resolve identifiers to open bibliographic records from OpenCitations Meta.

    Use it to turn a DOI, PMID, PMC id, ISBN, OpenAlex id or OMID into a
    citable record — title, authors with their ORCIDs, date, venue, publisher,
    pagination — under CC0. Records merge with OpenAlex, HAL, Sudoc and Primo
    results on `doi`.

    Domain rules:
      - OpenCitations Meta carries **no abstract and no full text**. `abstract`
        is always null, and is present only so the record shape matches its
        siblings. For an abstract, go to OpenAlex or HAL.
      - An ISSN returns the journal itself, repeated once per record held —
        never its articles. There is no way to enumerate a journal's works.
      - Identifiers are batched 10 per upstream request; DOIs are
        case-insensitive.
      - An unknown identifier yields no row rather than an error.

    Args:
        ids: Identifiers with their scheme prefix: "doi:", "pmid:", "pmcid:", "isbn:", "issn:", "openalex:" or "omid:br/…".
        trace: Include the HTTP trace in the response.

    Returns:
        {
          "source": "opencitations",
          "command": "lookup_metadata",
          "total_found": int,
          "returned": int,
          "results": [
            {"source": "opencitations", "id": str, "url": str | null,
             "title": str | null,
             "authors": [{"name": str, "orcid": str | null, "omid": str | null}],
             "abstract": null,
             "doi": str | null, "year": str | null, "date": str | null,
             "doc_type": str | null, "journal": str | null,
             "venue": {"title": str, "issn": str | null, "omid": str | null} | null,
             "publisher": [ ], "editors": [ ],
             "volume": str | null, "issue": str | null, "page": str | null,
             "identifiers": {"doi": str, "omid": str, ...},
             "raw": { }}
          ],
          "error": str | null
        }
    """
    include_trace = TRACE_DEFAULT if trace is None else trace
    out = _envelope("lookup_metadata")
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    events: list[dict[str, Any]] = []

    for start in range(0, len(ids), METADATA_BATCH):
        batch = ids[start:start + METADATA_BATCH]
        payload, error, evs = await _get_json(
            f"{META}/metadata/{'__'.join(batch)}", trace=include_trace)
        events.extend(evs)
        if error:
            errors.append(error)
            continue
        results.extend(_normalize_meta(r) for r in payload if isinstance(r, dict))

    out["results"] = results
    out["returned"] = len(results)
    out["total_found"] = len(results)
    if errors:
        out["error"] = "; ".join(errors)
    if include_trace:
        out["trace"] = events
    return out


@mcp.tool
async def list_works_by_person(
    person_id: str,
    role: Literal["author", "editor"] = "author",
    max_results: int = 50,
    trace: bool | None = None,
) -> dict[str, Any]:
    """
    List the works an ORCID is attached to, as author or as editor.

    The only listing operation OpenCitations offers, and the only tool here that
    starts from a person rather than a work. It is exact — matching is on the
    identifier, not on a name — so it never suffers the homonym problem, but it
    only covers what the index has linked to that ORCID.

    Domain rules:
      - `person_id` is an ORCID (`orcid:0000-…`) or a Meta agent OMID
        (`omid:ra/…`). A bare name is not accepted; there is no name search.
      - The upstream response is unpaginated: `total_found` is its true size and
        `max_results` clamps client-side.
      - Large ORCIDs occasionally return truncated JSON with HTTP 200; the call
        is retried once, then reported in `error`.

    Args:
        person_id: "orcid:0000-0003-0530-4305" or "omid:ra/0605".
        role: Which role to list — "author" or "editor". They are different upstream endpoints.
        max_results: Clamp applied after the download, capped at 500.
        trace: Include the HTTP trace in the response.

    Returns:
        {
          "source": "opencitations",
          "command": "list_works_by_person",
          "person_id": str, "role": "author" | "editor",
          "total_found": int | null,
          "returned": int,
          "results": [ /* Meta records, same shape as lookup_metadata */ ],
          "error": str | null
        }
    """
    include_trace = TRACE_DEFAULT if trace is None else trace
    rows = max(1, min(int(max_results), MAX_RESULTS_CAP))
    out = _envelope("list_works_by_person", person_id=person_id, role=role)

    payload, error, events = await _get_json(f"{META}/{role}/{person_id}", trace=include_trace)
    if error:
        out["error"] = error
        if include_trace:
            out["trace"] = events
        return out

    records = [_normalize_meta(r) for r in payload if isinstance(r, dict)] \
        if isinstance(payload, list) else []
    out["total_found"] = len(records)
    out["results"] = records[:rows]
    out["returned"] = len(out["results"])
    if include_trace:
        out["trace"] = events
    return out


if __name__ == "__main__":
    if args.transport == "stdio":
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
