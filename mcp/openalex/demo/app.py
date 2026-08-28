#!/usr/bin/env python3
"""
Standalone Gradio demo of the OpenAlex MCP server, deployable as a Hugging Face Space.

The nine tools mirror the canonical `mcp_server.py` — same names, same arguments,
same envelope, author and institution resolution included. The deliberate
narrowings are `max_results`, clamped to 10 instead of 100; `dois`, capped at one
batch; and `max_groups`, capped at 50: this endpoint is public and every call
spends the operator's OpenAlex budget.

The OpenAlex key setting is supplied **per request**, resolved in this order:

    1. the Configuration tab            (browser visitors)
    2. the `X-Openalex-Api-Key` header  (MCP clients)
    3. the process environment          (what the Space operator set, if anything)

OpenAlex is usable anonymously, so an unconfigured Space still works — on the
$0.10/day anonymous budget rather than the $1.00/day a free key buys. Since
February 2026 the API meters a daily spend and ignores `mailto`; the polite pool
is gone. Every billable response reports what it cost in `cost_usd`.

Local run:
    uv run --with 'gradio[mcp]>=6,<7' --with httpx app.py

Environment:
    OPENALEX_API_KEY     optional fallback key, sent as the `api_key` query parameter
    GRADIO_SERVER_NAME   bind address (default 0.0.0.0)
    GRADIO_SERVER_PORT   port (default 7860)
    GRADIO_MCP_SERVER    "false" disables the demo MCP endpoint (default true)
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
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
OPENALEX_AUTOCOMPLETE = f"{OPENALEX_BASE}/autocomplete"
OPENALEX_QUERY = f"{OPENALEX_BASE}/query"

SELECT_FIELDS = ",".join([
    "id", "title", "authorships", "doi", "publication_date", "publication_year",
    "primary_location", "best_oa_location", "open_access", "cited_by_count", "type",
    "primary_topic", "topics", "fwci",
])

SORT_OPTIONS = (
    "publication_date:desc",
    "publication_date:asc",
    "cited_by_count:desc",
    "relevance_score:desc",
)

# Closed sets stay plain `str` in the tool signatures and are validated here:
# Gradio builds the MCP schema from the annotations, and a bad value belongs in
# `error`, not in a transport failure.
AUTOCOMPLETE_ENTITIES = (
    "works", "authors", "sources", "institutions",
    "topics", "publishers", "funders", "keywords",
)
HIERARCHY_LEVELS = {
    "domains": "topics.domain.id",
    "fields": "topics.field.id",
    "subfields": "topics.subfield.id",
    "topics": "topics.id",
}
QUERY_FORMS = ("oql", "oqo", "oxurl")
CORPUS_CHOICES = ("core", "expansion", "all")
INSTITUTION_SCOPES = ("lineage", "exact")
TOPIC_SCOPES = ("any", "primary")

# A Space has no command line: connector policy is constant here.
REQUEST_TIMEOUT = 20.0

# Clamped harder than the canonical server (which allows 100): this endpoint is
# public and every call spends the operator's OpenAlex budget.
MAX_RESULTS = 10

# `search.semantic` truncates beyond 2000 characters before embedding, caps at
# 50 results (the canonical server's limit) and reports `meta.count: 50` on every
# response — a cap, not a corpus count, hence `total_found: null`. It also
# rejects `from_publication_date` / `to_publication_date`, so this tool bounds by
# `publication_year` and names its arguments `year_from` / `year_to`.
SEMANTIC_MAX_CHARS = 2000

# The canonical server batches DOIs at 50 per request and pages as many batches as
# it is given. One batch is enough here, and the same clamp reason as MAX_RESULTS.
MAX_DOIS = 25

# `group_by` returns no records, so the cap is about output size rather than
# spend: the canonical server allows 100.
MAX_GROUPS = 50

# One module-level pooled client for the process.
HTTP = httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True)


def _key(api_key: str | None) -> str:
    """This request's key: the one supplied, else the deployment's, else none."""
    return (api_key or "").strip() or ENV_API_KEY


def _redact(message: str, key: str) -> str:
    """Strip the key from an error message before it is returned or displayed."""
    text = str(message)
    if key:
        text = text.replace(key, "***")
    return re.sub(r"(api_key=)[^&\s'\"]+", r"\1***", text)


def _get(url: str, params: dict, api_key: str | None = None,
         *, json_on_error: bool = False) -> tuple[dict | None, str | None]:
    """GET returning (payload, error). Never raises — the demo answers with data.

    `json_on_error` returns the body of a **400** instead of an error string, for
    the endpoints that answer a bad request with a structured diagnosis. Any
    other status stays an error: an exhausted budget answers 429, and its body
    is not a diagnosis.
    """
    request_params = dict(params)
    key = _key(api_key)
    if key:
        request_params["api_key"] = key
    try:
        resp = HTTP.get(url, params=request_params)
        resp.raise_for_status()
        return resp.json(), None
    except httpx.HTTPStatusError as exc:
        if json_on_error and exc.response.status_code == 400:
            try:
                return exc.response.json(), None
            except Exception:  # noqa: BLE001
                pass
        detail = ""
        try:
            body = exc.response.json()
            detail = body.get("message") or body.get("error") or ""
        except Exception:  # noqa: BLE001
            detail = ""
        suffix = f" — {_redact(detail, key)}" if detail else ""
        return None, f"OpenAlex returned HTTP {exc.response.status_code}{suffix}"
    except httpx.TimeoutException:
        return None, f"OpenAlex timed out after {REQUEST_TIMEOUT:g}s"
    except Exception as exc:  # noqa: BLE001 - never crash the Space
        return None, f"cannot reach OpenAlex: {_redact(exc, key)}"


def _short_id(value: str | None) -> str | None:
    """Reduce an OpenAlex URL to its short identifier: .../fields/17 -> 17."""
    if not value:
        return None
    tail = str(value).rstrip("/").rsplit("/", 1)[-1]
    return tail or None


def _meta_cost(data: dict | None) -> float | None:
    return ((data or {}).get("meta") or {}).get("cost_usd")


def _meta_oql(data: dict | None) -> str | None:
    return (((data or {}).get("meta") or {}).get("x_query") or {}).get("oql")


def _format_topic(topic: dict | None) -> dict | None:
    """Flatten a topic, keeping the id at every level: those are what feed back
    into a filter, not the display names."""
    if not topic:
        return None
    out: dict = {
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
    """Map one OpenAlex work onto the common record schema."""
    authors = [
        (a.get("author") or {}).get("display_name", "")
        for a in work.get("authorships", [])
    ]
    source = (work.get("primary_location") or {}).get("source") or {}
    best_oa = work.get("best_oa_location") or {}
    raw_doi = work.get("doi") or None
    doi = raw_doi.replace("https://doi.org/", "") if isinstance(raw_doi, str) else None
    openalex_id = _short_id(work.get("id"))

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
        "fwci": work.get("fwci"),
        "primary_topic": _format_topic(work.get("primary_topic")),
        "topics": [_format_topic(t) for t in work.get("topics", [])],
    }


# ── ID resolution ─────────────────────────────────────────────────────────────


def _resolve_author_id(name_or_orcid: str, api_key: str | None = None) -> str | None:
    """Resolve an author name or ORCID to an OpenAlex author ID, or None."""
    if "orcid.org" in name_or_orcid or name_or_orcid.startswith("0000-"):
        orcid = (name_or_orcid if name_or_orcid.startswith("https://")
                 else f"https://orcid.org/{name_or_orcid}")
        data, _ = _get(f"{OPENALEX_AUTHORS}/{orcid}", {}, api_key)
        return _short_id((data or {}).get("id"))

    data, _ = _get(OPENALEX_AUTHORS, {"search": name_or_orcid, "per-page": 1}, api_key)
    results = (data or {}).get("results", [])
    return _short_id(results[0].get("id")) if results else None


def _resolve_institution_id(name_or_ror: str, api_key: str | None = None) -> str | None:
    """Resolve an institution name or ROR URL to an OpenAlex institution ID.

    Autocomplete goes first: it is free, faster, and ranks by prominence where
    `?search=` ranks by textual relevance.
    """
    if "ror.org" in name_or_ror:
        data, _ = _get(f"{OPENALEX_INSTITUTIONS}/{name_or_ror}", {}, api_key)
        return _short_id((data or {}).get("id"))

    data, _ = _get(f"{OPENALEX_AUTOCOMPLETE}/institutions", {"q": name_or_ror}, api_key)
    results = (data or {}).get("results", [])
    if results:
        return _short_id(results[0].get("id"))

    data, _ = _get(OPENALEX_INSTITUTIONS, {"search": name_or_ror, "per-page": 1}, api_key)
    results = (data or {}).get("results", [])
    return _short_id(results[0].get("id")) if results else None


def _topic_filters(topic, subfield, field, domain, scope: str) -> list[str]:
    """Topic arguments as OpenAlex filters. `any` searches all three topics of a
    work (recall), `primary` only the main one (precision)."""
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
    institution_scope: str = "lineage",
    topic: str | None = None,
    subfield: str | None = None,
    field: str | None = None,
    domain: str | None = None,
    topic_scope: str = "any",
    corpus: str = "core",
    exact: bool = False,
) -> dict:
    out: dict = {"source": "openalex", "command": "search_works",
                 "total_found": 0, "returned": 0, "results": [],
                 "query_used": query, "filters_used": [], "corpus": corpus,
                 "oql": None, "cost_usd": None, "error": None}

    if not (query or "").strip():
        out["error"] = "query is required"
        return out
    if corpus not in CORPUS_CHOICES:
        out["error"] = f"corpus must be one of {', '.join(CORPUS_CHOICES)}"
        return out
    if institution_scope not in INSTITUTION_SCOPES:
        out["error"] = 'institution_scope must be "lineage" or "exact"'
        return out
    if topic_scope not in TOPIC_SCOPES:
        out["error"] = 'topic_scope must be "any" or "primary"'
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
            out["error"] = (
                f"Institution not found in OpenAlex: '{institution}'. "
                "Autocomplete is diacritic-sensitive — try the accented spelling, "
                "or pass a ROR."
            )
            out["filters_used"] = filters
            return out
        key = ("authorships.institutions.lineage" if institution_scope == "lineage"
               else "authorships.institutions.id")
        filters.append(f"{key}:{inst_id}")

    filters.extend(_topic_filters(topic, subfield, field, domain, topic_scope))

    params: dict = {
        "search.exact" if exact else "search": query,
        "per-page": max(1, min(int(max_results or 5), MAX_RESULTS)),
        "sort": sort_by if sort_by in SORT_OPTIONS else "publication_date:desc",
        "select": SELECT_FIELDS,
    }
    if filters:
        params["filter"] = ",".join(filters)
    if corpus != "core":
        params["corpus"] = corpus

    out["filters_used"] = filters

    data, error = _get(OPENALEX_WORKS, params, api_key)
    if error:
        out["error"] = error
        return out

    results = data.get("results", [])
    out["total_found"] = (data.get("meta") or {}).get("count", 0)
    out["returned"] = len(results)
    out["results"] = [_format_work(r) for r in results]
    out["oql"] = _meta_oql(data)
    out["cost_usd"] = _meta_cost(data)
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
    institution: str | None = None,
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
    if institution:
        inst_id = _resolve_institution_id(institution, api_key)
        if not inst_id:
            out["error"] = f"Institution not found in OpenAlex: '{institution}'"
            out["filters_used"] = filters
            return out
        filters.append(f"authorships.institutions.lineage:{inst_id}")
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
    out["cost_usd"] = _meta_cost(data)
    return out


def _lookup_by_doi(api_key: str | None, dois: list[str]) -> dict:
    out: dict = {"source": "openalex", "command": "lookup_by_doi",
                 "total_found": 0, "returned": 0, "results": [],
                 "requested": 0, "cost_usd": None, "error": None}

    cleaned = [d.strip() for d in (dois or []) if (d or "").strip()]
    if not cleaned:
        out["error"] = "dois is required"
        return out
    cleaned = cleaned[:MAX_DOIS]
    out["requested"] = len(cleaned)

    normalized = [
        d if d.startswith("https://doi.org/") else f"https://doi.org/{d}"
        for d in cleaned
    ]
    params = {
        "filter": "doi:" + "|".join(normalized),
        "per-page": len(normalized),
        "select": SELECT_FIELDS,
    }
    data, error = _get(OPENALEX_WORKS, params, api_key)
    if error:
        out["error"] = error
        return out

    results = data.get("results", [])
    out["results"] = [_format_work(r) for r in results]
    out["total_found"] = out["returned"] = len(results)
    out["cost_usd"] = _meta_cost(data)
    if not results:
        out["error"] = f"No OpenAlex work matched the {len(cleaned)} DOI(s) given"
    return out


def _get_citing_works(api_key: str | None, openalex_id: str, max_results: int = 5) -> dict:
    clean_id = _short_id((openalex_id or "").strip()) or ""
    out: dict = {"source": "openalex", "command": "get_citing_works",
                 "total_found": 0, "returned": 0, "results": [],
                 "cited_work_id": clean_id, "cost_usd": None, "error": None}

    if not clean_id:
        out["error"] = "openalex_id is required"
        return out

    params = {
        "filter": f"cites:{clean_id}",
        "per-page": max(1, min(int(max_results or 5), MAX_RESULTS)),
        "sort": "cited_by_count:desc",
        "select": SELECT_FIELDS,
    }
    data, error = _get(OPENALEX_WORKS, params, api_key)
    if error:
        out["error"] = error
        return out

    results = data.get("results", [])
    out["total_found"] = (data.get("meta") or {}).get("count", 0)
    out["returned"] = len(results)
    out["results"] = [_format_work(r) for r in results]
    out["cost_usd"] = _meta_cost(data)
    return out


CLASSIFY_LEVELS = (
    ("topics", "topics.id", lambda t: t),
    ("subfields", "topics.subfield.id", lambda t: t.get("subfield")),
    ("fields", "topics.field.id", lambda t: t.get("field")),
    ("domains", "topics.domain.id", lambda t: t.get("domain")),
)


def _aggregate_level(works: list[tuple[dict, float]], node_of) -> list[dict]:
    """Aggregate one level of the hierarchy over a sample of works: a work counts
    for its semantic relevance, a topic within it for its own score."""
    acc: dict[str, dict] = {}
    for work, weight in works:
        seen: set[str] = set()
        for topic in work.get("topics") or []:
            node = node_of(topic) or {}
            node_id = _short_id(node.get("id"))
            if not node_id:
                continue
            entry = acc.setdefault(node_id, {
                "id": node_id, "display_name": node.get("display_name"),
                "score": 0.0, "works": 0,
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


def _classify_text(api_key: str | None, text: str, max_works: int = 25) -> dict:
    text = (text or "").strip()
    out: dict = {
        "source": "openalex", "command": "classify_text",
        "query_used": text[:SEMANTIC_MAX_CHARS],
        "truncated": len(text) > SEMANTIC_MAX_CHARS, "based_on_works": 0,
        "topics": [], "subfields": [], "fields": [], "domains": [],
        "keywords": [], "filter_keys": {}, "cost_usd": None, "error": None,
    }
    if len(text) < 20:
        out["error"] = "Text too short (minimum 20 characters)"
        return out

    data, error = _get(OPENALEX_WORKS, {
        "search.semantic": text[:SEMANTIC_MAX_CHARS],
        "per-page": max(1, min(int(max_works or 25), 50)),
        "select": "id,relevance_score,topics,keywords",
    }, api_key)
    if error:
        out["error"] = error
        return out

    results = data.get("results", [])
    weighted = [(w, float(w.get("relevance_score") or 0.0)) for w in results]
    out["based_on_works"] = len(results)

    keyword_scores: dict[str, float] = {}
    for work, weight in weighted:
        for kw in work.get("keywords") or []:
            name = kw.get("display_name")
            if name:
                keyword_scores[name] = keyword_scores.get(name, 0.0) + weight * float(
                    kw.get("score") or 1.0
                )
    out["keywords"] = [
        k for k, _ in sorted(keyword_scores.items(), key=lambda kv: kv[1], reverse=True)
    ][:15]

    for name, _filter_key, node_of in CLASSIFY_LEVELS:
        out[name] = _aggregate_level(weighted, node_of)[:10]
    out["filter_keys"] = {name: key for name, key, _ in CLASSIFY_LEVELS}
    out["cost_usd"] = _meta_cost(data)
    if not results:
        out["error"] = "No neighbouring work found for this text"
    return out


# Stop-words and generic organisation words: present in thousands of names, they
# distinguish nothing. Dropping them is what widens "université de Strasbourg" to
# "Strasbourg" rather than to "universite".
GENERIC_TOKENS = {
    "universite", "université", "university", "universität", "universiteit",
    "universidad", "universita", "institut", "institute", "college", "school",
    "laboratoire", "laboratory", "centre", "center", "national", "research",
    "hospital", "hopital", "ecole", "faculty", "faculte", "department",
    "departement", "the", "and", "for", "des", "les", "del", "della",
}


def _distinctive_token(query: str) -> str | None:
    """The longest word once generics are dropped, or None."""
    tokens = [t for t in re.split(r"[^\w]+", query, flags=re.UNICODE) if len(t) > 3]
    candidates = [t for t in tokens if t.lower() not in GENERIC_TOKENS]
    if not candidates or len(tokens) == 1:
        return None
    best = max(candidates, key=len)
    return best if best.lower() != query.lower() else None


def _shape_entity(r: dict, entity_type: str) -> dict:
    return {
        "source": "openalex",
        "id": _short_id(r.get("id")),
        "url": r.get("id"),
        "display_name": r.get("display_name"),
        "entity_type": r.get("entity_type") or entity_type.rstrip("s"),
        "hint": r.get("hint"),
        "external_id": r.get("external_id"),
        "works_count": r.get("works_count"),
        "cited_by_count": r.get("cited_by_count"),
        # Supplied by /autocomplete; absent on the full-text fallback.
        "filter_key": r.get("filter_key"),
    }


def _resolve_entity(api_key: str | None, query: str,
                    entity_type: str = "institutions", max_results: int = 5) -> dict:
    query = (query or "").strip()
    out: dict = {"source": "openalex", "command": "resolve_entity",
                 "total_found": 0, "returned": 0, "results": [], "suggestions": [],
                 "query_used": query, "entity_type": entity_type,
                 "widened_query": None, "cost_usd": None, "error": None}

    if not query:
        out["error"] = "query is required"
        return out
    if entity_type not in AUTOCOMPLETE_ENTITIES:
        out["error"] = f"entity_type must be one of {', '.join(AUTOCOMPLETE_ENTITIES)}"
        return out

    data, error = _get(f"{OPENALEX_AUTOCOMPLETE}/{entity_type}", {"q": query}, api_key)
    if error:
        out["error"] = error
        return out
    results = data.get("results", [])

    if not results:
        # Full-text fallback, reshaped like /autocomplete so the caller reads one
        # schema.
        data, _ = _get(f"{OPENALEX_BASE}/{entity_type}", {
            "search": query, "per-page": max(1, min(int(max_results or 5), MAX_RESULTS)),
        }, api_key)
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
            for r in (data or {}).get("results", [])
        ]

    if results:
        shaped = [_shape_entity(r, entity_type) for r in results[:max(1, int(max_results or 5))]]
        out["total_found"] = len(results)
        out["returned"] = len(shaped)
        out["results"] = shaped
        return out

    # Nothing matched: what a widened search finds goes into `suggestions`, never
    # into `results`, with `error` still set. Substituting a neighbouring entity
    # would hand a wrong id to a filter that will not contest it.
    token = _distinctive_token(query)
    out["widened_query"] = token
    if token:
        data, _ = _get(f"{OPENALEX_AUTOCOMPLETE}/{entity_type}", {"q": token}, api_key)
        out["suggestions"] = [
            _shape_entity(r, entity_type)
            for r in (data or {}).get("results", [])[:max(1, int(max_results or 5))]
        ]
    hint = (f" Widened to '{token}': {len(out['suggestions'])} candidate(s) in "
            "`suggestions`, to be checked before use." if out["suggestions"] else "")
    out["error"] = (
        f"No '{entity_type}' entity for '{query}'. Autocomplete is "
        "diacritic-sensitive and prefix-based: try the accented spelling, a "
        "single distinctive word, or an external id (ROR, ORCID)." + hint
    )
    return out


def _browse_topics(api_key: str | None, level: str = "topics", query: str | None = None,
                   field: str | None = None, domain: str | None = None,
                   max_results: int = 10) -> dict:
    out: dict = {"source": "openalex", "command": "browse_topics",
                 "total_found": 0, "returned": 0, "results": [], "level": level,
                 "query_used": query, "filters_used": [], "cost_usd": None,
                 "error": None}

    if level not in HIERARCHY_LEVELS:
        out["error"] = f"level must be one of {', '.join(HIERARCHY_LEVELS)}"
        return out

    params: dict = {"per-page": max(1, min(int(max_results or 10), MAX_RESULTS))}
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
    out["filters_used"] = filters

    data, error = _get(f"{OPENALEX_BASE}/{level}", params, api_key)
    if error:
        out["error"] = error
        return out

    formatted = []
    for r in data.get("results", []):
        record = {
            "source": "openalex",
            "id": _short_id(r.get("id")),
            "url": r.get("id"),
            "display_name": r.get("display_name"),
            "level": level.rstrip("s"),
            "description": r.get("description"),
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

    out["total_found"] = (data.get("meta") or {}).get("count", 0)
    out["returned"] = len(formatted)
    out["results"] = formatted
    out["cost_usd"] = _meta_cost(data)
    return out


def _group_by(api_key: str | None, dimension: str, query: str | None = None,
              filters: str | None = None, entity: str = "works",
              include_unknown: bool = False, max_groups: int = 20) -> dict:
    out: dict = {"source": "openalex", "command": "group_by", "entity": entity,
                 "dimension": dimension, "query_used": query, "filters_used": filters,
                 "total_found": None, "groups_count": None, "groups": [],
                 "oql": None, "cost_usd": None, "error": None}

    if not (dimension or "").strip():
        out["error"] = "dimension is required"
        return out

    key = f"{dimension}:include_unknown" if include_unknown else dimension
    params: dict = {
        "group_by": key,
        "per-page": max(1, min(int(max_groups or 20), MAX_GROUPS)),
    }
    if query:
        params["search"] = query
    if filters:
        params["filter"] = filters

    data, error = _get(f"{OPENALEX_BASE}/{entity}", params, api_key)
    if error:
        out["error"] = error
        return out

    out["groups"] = [
        {
            "key": _short_id(g.get("key")) if str(g.get("key", "")).startswith("http")
            else g.get("key"),
            "key_url": g.get("key") if str(g.get("key", "")).startswith("http") else None,
            "key_display_name": g.get("key_display_name"),
            "count": g.get("count"),
        }
        for g in data.get("group_by", [])
    ]
    meta = data.get("meta") or {}
    out["total_found"] = meta.get("count")
    out["groups_count"] = meta.get("groups_count")
    out["oql"] = _meta_oql(data)
    out["cost_usd"] = _meta_cost(data)
    return out


def _translate_query(api_key: str | None, query: str, form: str = "oql") -> dict:
    query = (query or "").strip()
    out: dict = {"source": "openalex", "command": "translate_query", "form": form,
                 "query_used": query, "valid": False, "oql": None,
                 "oql_oneline": None, "oqo": None, "oxurl": None, "api_url": None,
                 "diagnostics": [], "error": None}

    if not query:
        out["error"] = "query is required"
        return out
    if form not in QUERY_FORMS:
        out["error"] = f"form must be one of {', '.join(QUERY_FORMS)}"
        return out

    # The query is a path segment, not a parameter: /query/oql?q=… is read as an
    # identifier and answers "OpenAlex ID format not recognized".
    url = f"{OPENALEX_QUERY}/{form}/{urllib.parse.quote(query, safe='')}"
    data, error = _get(url, {}, api_key, json_on_error=True)
    if error:
        out["error"] = error
        return out

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

    # `oql_render_v2` is a render tree meant for editors — thousands of tokens an
    # agent does nothing with. Not returned.
    out.update({
        "valid": bool(valid),
        "oql": data.get("oql"),
        "oql_oneline": data.get("oql_oneline"),
        "oqo": data.get("oqo"),
        "oxurl": data.get("oxurl"),
        "api_url": f"{OPENALEX_BASE}{data['oxurl']}" if data.get("oxurl") else None,
        "diagnostics": diagnostics,
        "error": None if valid else (
            first_message or data.get("message") or "Query could not be translated"
        ),
    })
    return out


# ── MCP tools (the only functions exposed with gr.api) ────────────────────────
#
# `x_openalex_api_key` is a request header, not a tool argument: Gradio fills it
# from the incoming HTTP request, hides it from the input schema, and advertises
# it under `meta.headers`. It is how an MCP client spends its own OpenAlex budget
# without the model ever seeing the credential.
#
# Closed sets are annotated `str` rather than `Literal`, because Gradio builds
# the MCP schema from the annotations and a bad value belongs in `error`, not in
# a transport failure. The accepted values are named in each docstring.


def search_works(
    query: str,
    max_results: int = 5,
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
    x_openalex_api_key: Optional[gr.Header] = None,
) -> dict:
    """
    Search OpenAlex for academic works by keyword query.

    Query syntax: "phrase in quotes", "near each other"~5, fuzzy~2, AND/OR/NOT in uppercase. Wildcards (* and ?) work only with exact=true.

    Calls run on the anonymous daily budget unless an X-Openalex-Api-Key request
    header is sent, or the deployment configured a key of its own.

    Args:
        query: Free-text search over title, abstract and full text, e.g. "multilingual subject indexing".
        max_results: Number of works to return, 1-10 on this demo endpoint.
        date_from: Earliest publication date, inclusive, as YYYY-MM-DD. Empty for no lower bound.
        date_to: Latest publication date, inclusive, as YYYY-MM-DD. Empty for no upper bound.
        filter_open_access: Keep only works with an open-access full text.
        sort_by: Result order, e.g. "publication_date:desc", "cited_by_count:desc" or "relevance_score:desc".
        author: Author name or ORCID, resolved to an OpenAlex id before filtering. Empty for any author.
        institution: Institution name or ROR URL, resolved to an OpenAlex id before filtering. Empty for any.
        institution_scope: "lineage" (default) also matches the labs, hospitals and units attached to the institution — what OpenAlex's own query language compiles "institution is …" to. "exact" matches only that one entity.
        topic: OpenAlex topic id, e.g. "T10601". Get one from browse_topics or classify_text.
        subfield: OpenAlex subfield id, e.g. "1702".
        field: OpenAlex field id, e.g. "17".
        domain: OpenAlex domain id, e.g. "3".
        topic_scope: "any" (default) matches all three topics a work carries — recall; "primary" only its main subject — precision.
        corpus: "core" (default), "expansion" or "all".
        exact: Use search.exact — no stemming, wildcards allowed.

    Returns:
        {"source": "openalex", "command": "search_works", "total_found": int, "returned": int, "query_used": str, "filters_used": [str], "corpus": str, "oql": str | null, "cost_usd": float | null, "results": [{"source": "openalex", "id": str, "title": str, "authors": [str], "doi": str | null, "url": str, "year": int | null, "journal": str | null, "fwci": float | null, "primary_topic": object | null, "topics": [object]}], "error": str | null}
    """
    return _search_works(x_openalex_api_key, query, max_results, date_from, date_to,
                         filter_open_access, sort_by, author, institution,
                         institution_scope, topic, subfield, field, domain,
                         topic_scope, corpus, exact)


def search_semantic(
    text: str,
    max_results: int = 5,
    year_from: int | None = None,
    year_to: int | None = None,
    filter_open_access: bool = False,
    institution: str | None = None,
    x_openalex_api_key: Optional[gr.Header] = None,
) -> dict:
    """
    Search OpenAlex by meaning rather than by keyword.

    Ranks works by semantic proximity to a descriptive text, so a paper matches even when it shares none of the words used to ask for it. Give it a sentence or a whole abstract, not two keywords. Use search_works instead when a keyword genuinely names the subject.

    Three limits come from the endpoint: no paging past the result cap, "total_found" always null because OpenAlex reports the cap and not a count, and date bounds expressed as years — the from/to dates search_works accepts are rejected here. Topic filters are rejected too.

    Calls run on the anonymous daily budget unless an X-Openalex-Api-Key request
    header is sent, or the deployment configured a key of its own.

    Args:
        text: Descriptive text or abstract to match on, minimum 20 characters, truncated at 2000.
        max_results: Number of works to return, 1-10 on this demo endpoint.
        year_from: Earliest publication year, inclusive. Empty for no lower bound.
        year_to: Latest publication year, inclusive. Empty for no upper bound.
        filter_open_access: Keep only works with an open-access full text.
        institution: Institution name or ROR, resolved before filtering, on lineage. Empty for any.

    Returns:
        {"source": "openalex", "command": "search_semantic", "total_found": null, "returned": int, "query_used": str, "filters_used": [str], "truncated": bool, "cost_usd": float | null, "results": [{"source": "openalex", "id": str, "title": str, "authors": [str], "doi": str | null, "url": str, "year": int | null, "journal": str | null, "relevance_score": float | null}], "error": str | null}
    """
    return _search_semantic(x_openalex_api_key, text, max_results, year_from,
                            year_to, filter_open_access, institution)


def lookup_by_doi(
    dois: list[str],
    x_openalex_api_key: Optional[gr.Header] = None,
) -> dict:
    """
    Resolve one or more DOIs to full OpenAlex work records.

    Free — single-entity lookups are not billed. Use this when the DOI is already
    known: it is exact, unlike search_works, and it answers for several DOIs in a
    single call. A DOI OpenAlex does not index is simply absent from the results.

    Args:
        dois: DOIs in any format, short ("10.1038/nature12373") or full URL. Up to 25 per call on this demo endpoint.

    Returns:
        {"source": "openalex", "command": "lookup_by_doi", "total_found": int, "returned": int, "requested": int, "cost_usd": float | null, "results": [{"source": "openalex", "id": str, "title": str, "authors": [str], "doi": str | null, "url": str, "year": int | null, "journal": str | null}], "error": str | null}
    """
    return _lookup_by_doi(x_openalex_api_key, dois)


def get_citing_works(
    openalex_id: str,
    max_results: int = 5,
    x_openalex_api_key: Optional[gr.Header] = None,
) -> dict:
    """
    Fetch the works that cite a given OpenAlex work, most-cited first.

    Forward citation lookup: who built on this paper. Resolve a DOI with
    lookup_by_doi first if you only have one — this tool takes an OpenAlex id.

    Calls run on the anonymous daily budget unless an X-Openalex-Api-Key request
    header is sent, or the deployment configured a key of its own.

    Args:
        openalex_id: OpenAlex work id, short form ("W2741809807") or full URL.
        max_results: Number of citing works to return, 1-10 on this demo endpoint.

    Returns:
        {"source": "openalex", "command": "get_citing_works", "total_found": int, "returned": int, "cited_work_id": str, "cost_usd": float | null, "results": [{"source": "openalex", "id": str, "title": str, "authors": [str], "doi": str | null, "url": str, "year": int | null, "journal": str | null, "cited_by_count": int}], "error": str | null}
    """
    return _get_citing_works(x_openalex_api_key, openalex_id, max_results)


def classify_text(
    text: str,
    max_works: int = 25,
    x_openalex_api_key: Optional[gr.Header] = None,
) -> dict:
    """
    Place a text in the OpenAlex topic hierarchy.

    OpenAlex retired its /text endpoint. This tool rebuilds the capability: one semantic search finds the nearest works, then their topics are aggregated weighted by relevance and rolled up to subfields, fields and domains. It returns real OpenAlex identifiers at all four levels plus the filter keys needed to reuse them — feed the ids straight back into search_works.

    Returns its own shape, not the record envelope: this tool returns no records.

    Calls run on the anonymous daily budget unless an X-Openalex-Api-Key request
    header is sent, or the deployment configured a key of its own.

    Args:
        text: Title or abstract to classify, minimum 20 characters, truncated at 2000.
        max_works: Neighbouring works the classification is aggregated from, 1-50.

    Returns:
        {"source": "openalex", "command": "classify_text", "query_used": str, "truncated": bool, "based_on_works": int, "topics": [{"id": str, "display_name": str, "score": float, "works": int}], "subfields": [object], "fields": [object], "domains": [object], "keywords": [str], "filter_keys": object, "cost_usd": float | null, "error": str | null}
    """
    return _classify_text(x_openalex_api_key, text, max_works)


def resolve_entity(
    query: str,
    entity_type: str = "institutions",
    max_results: int = 5,
    x_openalex_api_key: Optional[gr.Header] = None,
) -> dict:
    """
    Resolve a name to an OpenAlex entity — id, external id, and filter key.

    Free and fast. Backed by /autocomplete, which returns a filter_key alongside each suggestion: the API itself saying which filter that identifier belongs in ("authorships.institutions.lineage" for an institution, "topics.id" for a topic). Run this before filtering on a name.

    Autocomplete is prefix-based and diacritic-sensitive, and the two combine badly: "strasbourg" alone finds nothing because it is not a prefix of the name, and "universite de stras" finds nothing either because the name is spelled "Université". "université de stras" finds it on the first try. When the prefix match is empty, a widened search is tried and what it finds goes into "suggestions", never into "results", with "error" still set — the caller chooses.

    Args:
        query: Partial name — the beginning of it, accents included.
        entity_type: One of works, authors, sources, institutions, topics, publishers, funders, keywords.
        max_results: Number of candidates to return, 1-10 on this demo endpoint.

    Returns:
        {"source": "openalex", "command": "resolve_entity", "total_found": int, "returned": int, "results": [{"source": "openalex", "id": str, "url": str, "display_name": str, "entity_type": str, "hint": str | null, "external_id": str | null, "works_count": int | null, "cited_by_count": int | null, "filter_key": str | null}], "suggestions": [object], "query_used": str, "entity_type": str, "widened_query": str | null, "cost_usd": null, "error": str | null}
    """
    return _resolve_entity(x_openalex_api_key, query, entity_type, max_results)


def browse_topics(
    level: str = "topics",
    query: str | None = None,
    field: str | None = None,
    domain: str | None = None,
    max_results: int = 10,
    x_openalex_api_key: Optional[gr.Header] = None,
) -> dict:
    """
    Explore the OpenAlex "aboutness" hierarchy.

    Four levels: 4 domains, 26 fields, 252 subfields, 4516 topics. Each record carries the short id, its parent levels, works_count and the filter key for that level — feed the id back into search_works or group_by.

    Args:
        level: "domains", "fields", "subfields" or "topics" (default).
        query: Full-text search within the level. Empty returns the level ordered by works_count.
        field: Restrict to a field id, e.g. "17". Empty for no restriction.
        domain: Restrict to a domain id, e.g. "3". Empty for no restriction.
        max_results: Number of entries to return, 1-10 on this demo endpoint.

    Returns:
        {"source": "openalex", "command": "browse_topics", "total_found": int, "returned": int, "results": [{"source": "openalex", "id": str, "url": str, "display_name": str, "level": str, "description": str | null, "works_count": int | null, "filter_key": str, "subfield": object, "field": object, "domain": object}], "level": str, "query_used": str | null, "filters_used": [str], "cost_usd": float | null, "error": str | null}
    """
    return _browse_topics(x_openalex_api_key, level, query, field, domain, max_results)


def group_by(
    dimension: str,
    query: str | None = None,
    filters: str | None = None,
    entity: str = "works",
    include_unknown: bool = False,
    max_groups: int = 20,
    x_openalex_api_key: Optional[gr.Header] = None,
) -> dict:
    """
    Count along a dimension without retrieving any record.

    Answers "how many", "which are the top" and "how has it evolved" in one call, at the price of a single request whatever the size of the set being aggregated — the cheapest way to frame a corpus before walking it.

    Returns its own shape, not the record envelope: this tool returns no records.

    Args:
        dimension: Any OpenAlex filter key, e.g. "publication_year", "type", "open_access.oa_status", "topics.field.id", "authorships.institutions.lineage".
        query: Restrict to a keyword search. Empty aggregates the whole filtered set.
        filters: Raw OpenAlex filter string, comma-separated, e.g. "authorships.institutions.lineage:I68947357,is_oa:true".
        entity: Entity endpoint to aggregate, "works" by default.
        include_unknown: Also count records with no value for the dimension.
        max_groups: Groups to return, 1-50 on this demo endpoint. "groups_count" reports the real number of distinct groups, which can exceed it.

    Returns:
        {"source": "openalex", "command": "group_by", "entity": str, "dimension": str, "query_used": str | null, "filters_used": str | null, "total_found": int | null, "groups_count": int | null, "groups": [{"key": str, "key_url": str | null, "key_display_name": str | null, "count": int}], "oql": str | null, "cost_usd": float | null, "error": str | null}
    """
    return _group_by(x_openalex_api_key, dimension, query, filters, entity,
                     include_unknown, max_groups)


def translate_query(
    query: str,
    form: str = "oql",
    x_openalex_api_key: Optional[gr.Header] = None,
) -> dict:
    """
    Translate a query between OQL, OQO and a REST URL, and validate it.

    Three forms of the same query: OQL (readable text, "works where institution is Sorbonne Université"), OQO (a JSON object) and oxurl (the REST URL). "form" names what you are giving it. Translation never touches the index and is billed at the cheapest rate, so it is the way to check a filter before paying to run it — and how you find out that "institution is X" compiles to authorships.institutions.lineage rather than .id.

    Returns its own shape, not the record envelope: this tool returns no records. An invalid query comes back valid:false with the parser's own message — a diagnosis, not a failure.

    Args:
        query: The query, in the form named by "form".
        form: "oql" (default), "oqo" or "oxurl" — the form of the INPUT.

    Returns:
        {"source": "openalex", "command": "translate_query", "form": str, "query_used": str, "valid": bool, "oql": str | null, "oql_oneline": str | null, "oqo": object | null, "oxurl": str | null, "api_url": str | null, "diagnostics": [object], "error": str | null}
    """
    return _translate_query(x_openalex_api_key, query, form)


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
    cost = payload.get("cost_usd")
    if isinstance(cost, (int, float)):
        header += f" — this call cost ${cost:g}"
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


def _render_classification(payload: dict) -> str:
    """Four levels of the hierarchy, each with the id that turns it into a filter."""
    lines = [f"**Based on {payload.get('based_on_works', 0)} neighbouring works**", ""]
    filter_keys = payload.get("filter_keys") or {}
    for level in ("domains", "fields", "subfields", "topics"):
        entries = payload.get(level) or []
        if not entries:
            continue
        lines += [
            f"### {level.capitalize()} — filter on `{filter_keys.get(level, '')}`",
            "",
            "| id | Name | Share | Works |",
            "|---|---|---|---|",
        ]
        for e in entries[:5]:
            score = e.get("score")
            lines.append(
                f"| `{e.get('id')}` | {(e.get('display_name') or '—')} "
                f"| {score:.1%} | {e.get('works')} |"
                if isinstance(score, (int, float))
                else f"| `{e.get('id')}` | {(e.get('display_name') or '—')} | — | {e.get('works')} |"
            )
        lines.append("")
    keywords = [k for k in (payload.get("keywords") or []) if k]
    if keywords:
        lines += ["**Keywords** — " + ", ".join(keywords[:12])]
    return "\n".join(lines) if len(lines) > 2 else "_Nothing to classify this text against._"


def _render_entities(payload: dict) -> str:
    results = payload.get("results") or []
    suggestions = payload.get("suggestions") or []
    rows = results or suggestions
    if not rows:
        return "_Nothing matched._"
    lines = []
    if not results and suggestions:
        lines += [
            f"> ⚠️ Nothing matched `{payload.get('query_used')}` exactly. These are "
            f"**suggestions** from the widened query `{payload.get('widened_query')}` "
            "— check one before using its id.",
            "",
        ]
    lines += ["| id | Name | Hint | Works | Filter key |", "|---|---|---|---|---|"]
    for r in rows:
        lines.append(
            f"| `{r.get('id')}` | [{r.get('display_name') or '—'}]({r.get('url') or ''}) "
            f"| {(r.get('hint') or '—')} | {r.get('works_count') or '—'} "
            f"| `{r.get('filter_key') or '—'}` |"
        )
    return "\n".join(lines)


def _render_hierarchy(payload: dict) -> str:
    results = payload.get("results") or []
    if not results:
        return "_Nothing at this level matched._"
    lines = [
        f"**{payload.get('returned', 0)} of {payload.get('total_found', 0)} "
        f"{payload.get('level')}** — filter on "
        f"`{(results[0] or {}).get('filter_key', '')}`",
        "",
        "| id | Name | Parent | Works |",
        "|---|---|---|---|",
    ]
    for r in results:
        parent = r.get("subfield") or r.get("field") or r.get("domain") or {}
        lines.append(
            f"| `{r.get('id')}` | [{r.get('display_name') or '—'}]({r.get('url') or ''}) "
            f"| {parent.get('display_name') or '—'} | {r.get('works_count') or '—'} |"
        )
    return "\n".join(lines)


def _render_groups(payload: dict) -> str:
    groups = payload.get("groups") or []
    if not groups:
        return "_No group returned._"
    total = payload.get("total_found")
    count = payload.get("groups_count")
    header = f"**{len(groups)} groups shown**"
    if count:
        header += f" of {count} distinct"
    if total is not None:
        header += f", over {total} records"
    lines = [header, "", "| Key | Label | Count |", "|---|---|---|"]
    for g in groups:
        lines.append(
            f"| `{g.get('key')}` | {g.get('key_display_name') or '—'} | {g.get('count')} |"
        )
    oql = payload.get("oql")
    if oql:
        lines += ["", f"OpenAlex compiled this to: `{oql}`"]
    return "\n".join(lines)


def _render_translation(payload: dict) -> str:
    if not payload.get("valid"):
        lines = [f"> ❌ **Invalid** — {payload.get('error') or 'query not understood'}"]
        for d in (payload.get("diagnostics") or [])[:5]:
            lines.append(f"- {d.get('message') if isinstance(d, dict) else d}")
        return "\n".join(lines)
    lines = ["> ✅ **Valid**", ""]
    if payload.get("oql_oneline") or payload.get("oql"):
        lines += ["**OQL**", "", "```", payload.get("oql_oneline") or payload.get("oql"), "```", ""]
    if payload.get("api_url"):
        lines += ["**REST URL**", "", f"<{payload['api_url']}>", ""]
    if payload.get("oqo"):
        lines += ["**OQO**", "", "```json", json.dumps(payload["oqo"], indent=2, ensure_ascii=False)[:2000], "```"]
    return "\n".join(lines)


def _summarize_config(api_key) -> str:
    """
    Describe the key a call would use. Reported as present or absent, never
    echoed — not even partially.
    """
    if (api_key or "").strip():
        return "> ✅ Using the key typed above — your own $1.00/day OpenAlex budget."
    if ENV_API_KEY:
        return "> ✅ Using this deployment's key — you share the operator's $1.00/day budget."
    return (
        "> ℹ️ No key: calls run on the **anonymous budget**, $0.10/day for this "
        "Space's IP, shared by every visitor and reset at midnight UTC. Paste a "
        "key above to spend your own $1.00/day instead."
    )


def _run(payload: dict, render) -> tuple[str, dict]:
    if payload.get("error") and not (payload.get("results") or payload.get("groups")
                                     or payload.get("suggestions")):
        raise gr.Error(payload["error"])
    return render(payload), payload


def _run_search(api_key, query, max_results, date_from, date_to, open_access,
                sort_by, author, institution, institution_scope, field, topic_scope):
    return _run(_search_works(
        api_key, query, max_results,
        (date_from or "").strip() or None, (date_to or "").strip() or None,
        open_access, sort_by,
        (author or "").strip() or None, (institution or "").strip() or None,
        institution_scope, None, None, (field or "").strip() or None, None,
        topic_scope,
    ), _render_works)


def _run_semantic(api_key, text, max_results, year_from, year_to, open_access, institution):
    return _run(_search_semantic(
        api_key, text, max_results,
        int(year_from) if year_from else None,
        int(year_to) if year_to else None,
        open_access, (institution or "").strip() or None,
    ), _render_works)


def _run_lookup(api_key, dois_text):
    return _run(
        _lookup_by_doi(api_key, (dois_text or "").replace(",", "\n").splitlines()),
        _render_works,
    )


def _run_citing(api_key, openalex_id, max_results):
    return _run(_get_citing_works(api_key, openalex_id, max_results), _render_works)


def _run_classify(api_key, text, max_works):
    return _run(_classify_text(api_key, text, max_works), _render_classification)


def _run_resolve(api_key, query, entity_type, max_results):
    payload = _resolve_entity(api_key, query, entity_type, max_results)
    return _run(payload, _render_entities)


def _run_browse(api_key, level, query, field, domain, max_results):
    return _run(_browse_topics(
        api_key, level, (query or "").strip() or None,
        (field or "").strip() or None, (domain or "").strip() or None, max_results,
    ), _render_hierarchy)


def _run_group(api_key, dimension, query, filters, include_unknown, max_groups):
    return _run(_group_by(
        api_key, dimension, (query or "").strip() or None,
        (filters or "").strip() or None, "works", include_unknown, max_groups,
    ), _render_groups)


def _run_translate(api_key, query, form):
    payload = _translate_query(api_key, query, form)
    # An invalid query is a diagnosis, not a failure: render it rather than
    # raising, so the visitor sees what the parser objected to.
    return _render_translation(payload), payload


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
            "OpenAlex works without a key, on a **$0.10/day** budget shared by "
            "everyone using this Space; a free key raises it to **$1.00/day**, "
            "and both reset at midnight UTC. Lookups by identifier and name "
            "resolution are free either way."
        )
        api_key_in = gr.Textbox(
            label="OpenAlex API key (optional)",
            type="password",
            value="",  # never pre-filled from the environment: it is the operator's secret
            placeholder=("leave blank to use this deployment's key" if ENV_API_KEY
                         else "leave blank to use the anonymous budget"),
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
        with gr.Row():
            inst_scope = gr.Dropdown(
                list(INSTITUTION_SCOPES), value="lineage", label="Institution scope",
                info="lineage also matches attached labs, hospitals and units",
            )
            field_in = gr.Textbox(label="Field id", placeholder="17",
                                  info="from the Browse hierarchy tab")
            topic_scope = gr.Dropdown(
                list(TOPIC_SCOPES), value="any", label="Topic scope",
                info="any = all three topics of a work; primary = its main subject",
            )
        search_btn = gr.Button("Search", variant="primary")
        works_out = gr.Markdown()
        works_raw = gr.JSON(label="Raw tool output")

        gr.Examples(
            examples=[
                ["multilingual subject indexing", 5, False, "", "", "lineage", ""],
                ["knowledge graph", 5, True, "2022-01-01", "", "lineage", ""],
                ["deep learning", 5, False, "", "Yoshua Bengio", "lineage", ""],
                ["CRISPR", 5, False, "", "", "lineage", "17"],
            ],
            inputs=[query, max_results, open_access, date_from, author, inst_scope, field_in],
            label="Keywords alone, narrowed by open access and date, by author, then by field",
        )
        search_btn.click(
            _run_search,
            inputs=[api_key_in, query, max_results, date_from, date_to, open_access,
                    sort_by, author, institution, inst_scope, field_in, topic_scope],
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
        sem_inst = gr.Textbox(label="Institution (name or ROR URL)", placeholder="Sorbonne Université")
        sem_btn = gr.Button("Search by meaning", variant="primary")
        sem_out = gr.Markdown()
        sem_raw = gr.JSON(label="Raw tool output")

        gr.Examples(
            examples=[
                ["Deciding whether a citation to a retracted paper endorses it or "
                 "flags it as an example of research misconduct", 5, None, ""],
                ["Assigning subject headings to library catalogue records "
                 "automatically, with neural language models", 5, 2020, ""],
                ["Transformer architectures for predicting the three-dimensional "
                 "structure of proteins from sequence", 5, 2021, ""],
            ],
            inputs=[sem_text, sem_max, sem_year_from, sem_inst],
            label="A problem description, the same bounded by year, then a third subject",
        )
        sem_btn.click(
            _run_semantic,
            inputs=[api_key_in, sem_text, sem_max, sem_year_from, sem_year_to, sem_oa, sem_inst],
            outputs=[sem_out, sem_raw],
            api_name=False,
        )

    with gr.Tab("Lookup by DOI"):
        gr.Markdown(
            "Exact resolution rather than search: paste DOIs, one per line or "
            f"comma-separated, up to {MAX_DOIS} per call. **Free** — OpenAlex does "
            "not bill lookups by identifier. A DOI it does not index is simply "
            "missing from the table."
        )
        dois_in = gr.Textbox(
            label="DOIs",
            lines=4,
            placeholder="10.1038/nature12373\n10.1371/journal.pone.0000308",
        )
        lookup_btn = gr.Button("Resolve", variant="primary")
        lookup_out = gr.Markdown()
        lookup_raw = gr.JSON(label="Raw tool output")

        gr.Examples(
            examples=[
                ["10.1038/nature12373"],
                ["10.1038/nature12373\n10.1371/journal.pone.0000308"],
                ["https://doi.org/10.1371/journal.pone.0000308"],
            ],
            inputs=[dois_in],
            label="One DOI, a batch of two, and a DOI given as a full URL",
        )
        lookup_btn.click(
            _run_lookup, inputs=[api_key_in, dois_in],
            outputs=[lookup_out, lookup_raw], api_name=False,
        )

    with gr.Tab("Citing works"):
        gr.Markdown(
            "Forward citations: the works that cite a given one, most-cited "
            "first. Takes an OpenAlex id — resolve a DOI in the **Lookup by DOI** "
            "tab first if that is all you have."
        )
        cited_id = gr.Textbox(label="OpenAlex work id", placeholder="W2741809807")
        citing_max = gr.Slider(1, MAX_RESULTS, value=5, step=1, label="Results")
        citing_btn = gr.Button("Find citing works", variant="primary")
        citing_out = gr.Markdown()
        citing_raw = gr.JSON(label="Raw tool output")

        gr.Examples(
            examples=[
                ["W2741809807", 5],
                ["https://openalex.org/W2741809807", 3],
                ["W3177828909", 5],
            ],
            inputs=[cited_id, citing_max],
            label="A short id, the same work as a full URL, and the AlphaFold paper",
        )
        citing_btn.click(
            _run_citing, inputs=[api_key_in, cited_id, citing_max],
            outputs=[citing_out, citing_raw], api_name=False,
        )

    with gr.Tab("Classify text"):
        gr.Markdown(
            "Where does a text sit in OpenAlex's own hierarchy? One semantic "
            "search finds the nearest works, and their topics are aggregated and "
            "rolled up to subfields, fields and domains. Every line carries the "
            "**id** and the **filter key** that turn it back into a search."
        )
        text = gr.Textbox(
            label="Title or abstract",
            lines=4,
            placeholder="Paste a title or abstract of at least 20 characters.",
        )
        classify_max = gr.Slider(5, 50, value=25, step=5, label="Neighbouring works")
        classify_btn = gr.Button("Classify", variant="primary")
        topics_out = gr.Markdown()
        topics_raw = gr.JSON(label="Raw tool output")

        gr.Examples(
            examples=[
                ["Automatic subject indexing of library records using transformer language models", 25],
                ["Sea-level rise projections for the North Atlantic under two emission scenarios", 25],
                ["A randomised trial of cognitive behavioural therapy for chronic insomnia in adults", 25],
            ],
            inputs=[text, classify_max],
            label="Three abstracts from three different domains",
        )
        classify_btn.click(
            _run_classify, inputs=[api_key_in, text, classify_max],
            outputs=[topics_out, topics_raw], api_name=False,
        )

    with gr.Tab("Resolve entity"):
        gr.Markdown(
            "A name in, an **id and a filter key** out — free, and the first step "
            "before filtering on anything named. Autocomplete matches on a "
            "**prefix** and is **accent-sensitive**: `université de stras` finds "
            "the Université de Strasbourg, `universite de strasbourg` finds "
            "nothing at all."
        )
        with gr.Row():
            entity_q = gr.Textbox(label="Name (or the beginning of one)",
                                  placeholder="sorbonne univ")
            entity_type_in = gr.Dropdown(list(AUTOCOMPLETE_ENTITIES),
                                         value="institutions", label="Entity type")
            entity_max = gr.Slider(1, MAX_RESULTS, value=5, step=1, label="Candidates")
        resolve_btn = gr.Button("Resolve", variant="primary")
        entity_out = gr.Markdown()
        entity_raw = gr.JSON(label="Raw tool output")

        gr.Examples(
            examples=[
                ["sorbonne univ", "institutions", 5],
                ["université de stras", "institutions", 5],
                ["nature", "sources", 5],
                ["machine learn", "topics", 5],
            ],
            inputs=[entity_q, entity_type_in, entity_max],
            label="An institution, one with an accent, a journal, and a topic",
        )
        resolve_btn.click(
            _run_resolve, inputs=[api_key_in, entity_q, entity_type_in, entity_max],
            outputs=[entity_out, entity_raw], api_name=False,
        )

    with gr.Tab("Browse hierarchy"):
        gr.Markdown(
            "4 domains → 26 fields → 252 subfields → 4,516 topics. Take an id "
            "from here into the **Search works** tab, or into `group_by`."
        )
        with gr.Row():
            level_in = gr.Dropdown(list(HIERARCHY_LEVELS), value="fields", label="Level")
            browse_q = gr.Textbox(label="Search within the level", placeholder="library science")
            browse_max = gr.Slider(1, MAX_RESULTS, value=10, step=1, label="Results")
        with gr.Row():
            browse_field = gr.Textbox(label="Within field id", placeholder="17")
            browse_domain = gr.Textbox(label="Within domain id", placeholder="3")
        browse_btn = gr.Button("Browse", variant="primary")
        browse_out = gr.Markdown()
        browse_raw = gr.JSON(label="Raw tool output")

        gr.Examples(
            examples=[
                ["domains", "", "", "", 4],
                ["fields", "", "", "", 10],
                ["subfields", "", "17", "", 10],
                ["topics", "library science", "", "", 10],
            ],
            inputs=[level_in, browse_q, browse_field, browse_domain, browse_max],
            label="The four domains, the largest fields, the subfields of field 17, then a topic search",
        )
        browse_btn.click(
            _run_browse,
            inputs=[api_key_in, level_in, browse_q, browse_field, browse_domain, browse_max],
            outputs=[browse_out, browse_raw], api_name=False,
        )

    with gr.Tab("Count / group by"):
        gr.Markdown(
            "Counting without downloading: one request answers *how many*, *top "
            "N* and *how it evolved*, whatever the size of the set. Use an id "
            "from **Resolve entity** in the filter box."
        )
        dimension_in = gr.Textbox(label="Dimension (any filter key)",
                                  placeholder="publication_year")
        with gr.Row():
            group_q = gr.Textbox(label="Keyword search (optional)", placeholder="climate")
            group_filters = gr.Textbox(
                label="Filters (raw, comma-separated)",
                placeholder="authorships.institutions.lineage:I68947357",
            )
        with gr.Row():
            group_unknown = gr.Checkbox(label="Include unknown", value=False)
            group_max = gr.Slider(1, MAX_GROUPS, value=20, step=1, label="Groups")
        group_btn = gr.Button("Count", variant="primary")
        group_out = gr.Markdown()
        group_raw = gr.JSON(label="Raw tool output")

        gr.Examples(
            examples=[
                ["publication_year", "", "authorships.institutions.lineage:I68947357", 20],
                ["open_access.oa_status", "", "authorships.institutions.lineage:I68947357", 10],
                ["topics.field.id", "climate adaptation", "", 15],
                ["type", "", "publication_year:2024", 15],
            ],
            inputs=[dimension_in, group_q, group_filters, group_max],
            label="Output per year for one university, its OA breakdown, fields of a subject, then document types",
        )
        group_btn.click(
            _run_group,
            inputs=[api_key_in, dimension_in, group_q, group_filters, group_unknown, group_max],
            outputs=[group_out, group_raw], api_name=False,
        )

    with gr.Tab("Translate query"):
        gr.Markdown(
            "OpenAlex's own query language, its JSON form, and the REST URL are "
            "three views of one query. Translating is nearly free, so it is how "
            "you check a filter **before** paying to run it — and how you "
            "discover which filter key a phrase compiles to."
        )
        with gr.Row():
            translate_in = gr.Textbox(
                label="Query", scale=4,
                placeholder="works where institution is Sorbonne Université",
            )
            form_in = gr.Dropdown(list(QUERY_FORMS), value="oql", label="Input form")
        translate_btn = gr.Button("Translate", variant="primary")
        translate_out = gr.Markdown()
        translate_raw = gr.JSON(label="Raw tool output")

        gr.Examples(
            examples=[
                ["works where institution is Sorbonne Université", "oql"],
                ["works where publication year is greater than 2020 and is open access is true", "oql"],
                ["/works?filter=publication_year:2024,is_oa:true", "oxurl"],
            ],
            inputs=[translate_in, form_in],
            label="An institution query, a filtered one, and a REST URL read back as OQL",
        )
        translate_btn.click(
            _run_translate, inputs=[api_key_in, translate_in, form_in],
            outputs=[translate_out, translate_raw], api_name=False,
        )

    config_btn.click(_summarize_config, inputs=api_key_in, outputs=config_out, api_name=False)
    demo.load(_summarize_config, inputs=api_key_in, outputs=config_out, api_name=False)

    # The only declared MCP tools. Names match the canonical server's.
    gr.api(search_works, api_name="search_works")
    gr.api(search_semantic, api_name="search_semantic")
    gr.api(lookup_by_doi, api_name="lookup_by_doi")
    gr.api(get_citing_works, api_name="get_citing_works")
    gr.api(classify_text, api_name="classify_text")
    gr.api(resolve_entity, api_name="resolve_entity")
    gr.api(browse_topics, api_name="browse_topics")
    gr.api(group_by, api_name="group_by")
    gr.api(translate_query, api_name="translate_query")


if __name__ == "__main__":
    demo.launch(
        theme=gr.themes.Soft(),  # Gradio 6 moved theme from Blocks() to launch()
        server_name=os.getenv("GRADIO_SERVER_NAME", "0.0.0.0"),
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
        mcp_server=os.getenv("GRADIO_MCP_SERVER", "true").lower() == "true",
    )
