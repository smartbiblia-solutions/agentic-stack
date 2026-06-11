#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ['httpx', 'python-dotenv']
# ///

# ──────────────────────────────────────────────────────────────────────────────
# Standalone skill CLI file.
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

# ══════════════════════════════════════════════════════════════════════════════
# SECTION : core
# ══════════════════════════════════════════════════════════════════════════════

"""
Connector OpenAlex — Serveur MCP autonome
Base mondiale de publications académiques : https://docs.openalex.org

Pluggable sur n'importe quel hôte MCP.

Variables d'environnement :
  OPENALEX_API_KEY           (optionnel selon policy OpenAlex / vos quotas)

  # Robustesse / perf (recommandé pour usage agentique)
  OPENALEX_HTTP_TIMEOUT      (float, défaut 15.0)
  OPENALEX_MAX_RETRIES       (int, défaut 2)
  OPENALEX_BACKOFF_BASE      (float, défaut 1.0)    # seconds
  OPENALEX_BACKOFF_FACTOR    (float, défaut 2.0)    # multiplier
  OPENALEX_JITTER_MAX        (float, défaut 0.25)  # seconds random jitter added on retry
  OPENALEX_TRACE             ("0"|"1", défaut "0")  # inclure un journal d'exécution dans les retours
"""


import asyncio
import os
import random
import time
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

OPENALEX_BASE = "https://api.openalex.org"
OPENALEX_WORKS = f"{OPENALEX_BASE}/works"
OPENALEX_AUTHORS = f"{OPENALEX_BASE}/authors"
OPENALEX_INSTITUTIONS = f"{OPENALEX_BASE}/institutions"
OPENALEX_TEXT = f"{OPENALEX_BASE}/text"

API_KEY = os.getenv("OPENALEX_API_KEY", "")

# ---- Env-tunable networking knobs (agent-friendly defaults) -----------------

def _env_float(name: str, default: float) -> float:
    """Read a float environment variable with a safe default fallback."""
    v = os.getenv(name, "").strip()
    if not v:
        return default
    try:
        return float(v)
    except ValueError:
        return default

def _env_int(name: str, default: int) -> int:
    """Read an integer environment variable with a safe default fallback."""
    v = os.getenv(name, "").strip()
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        return default

HTTP_TIMEOUT = _env_float("OPENALEX_HTTP_TIMEOUT", 15.0)
MAX_RETRIES = max(1, _env_int("OPENALEX_MAX_RETRIES", 2))
BACKOFF_BASE = max(0.0, _env_float("OPENALEX_BACKOFF_BASE", 1.0))
BACKOFF_FACTOR = max(1.0, _env_float("OPENALEX_BACKOFF_FACTOR", 2.0))
JITTER_MAX = max(0.0, _env_float("OPENALEX_JITTER_MAX", 0.25))
TRACE_DEFAULT = os.getenv("OPENALEX_TRACE", "0").strip() in ("1", "true", "True", "yes", "YES")

SELECT_FIELDS = ",".join([
    "id", "title", "authorships", "abstract_inverted_index",
    "doi", "publication_date", "publication_year",
    "primary_location", "best_oa_location", "open_access",
    "cited_by_count", "type", "topics", "keywords",
    "referenced_works_count", "cited_by_api_url",
])


# ── HTTP client avec retry / backoff (instrumentable) ────────────────────────

def _should_retry(status_code: int) -> bool:
    """Return True when the HTTP status should trigger a retry."""
    return status_code in (429, 403, 500, 502, 503, 504)

def _backoff_sleep_seconds(attempt: int) -> float:
    """Compute exponential backoff delay with optional random jitter."""
    base = BACKOFF_BASE * (BACKOFF_FACTOR ** attempt)
    jitter = random.uniform(0.0, JITTER_MAX) if JITTER_MAX > 0 else 0.0
    return base + jitter

async def _get_with_backoff(
    url: str,
    params: dict,
    *,
    max_retries: int | None = None,
    timeout: float | None = None,
    trace: bool = True,
) -> tuple[dict, list[dict]]:
    """
    Execute a GET request with retries, timeout control, and optional trace logs.
    Returns a tuple: (response_json, trace_events).
    """
    max_retries = MAX_RETRIES if max_retries is None else max(1, int(max_retries))
    timeout = HTTP_TIMEOUT if timeout is None else float(timeout)

    trace_events: list[dict] = []
    started = time.perf_counter()

    async with httpx.AsyncClient(timeout=timeout) as client:
        last_status: int | None = None
        last_error: str | None = None

        for attempt in range(max_retries):
            t0 = time.perf_counter()
            try:
                if trace:
                    trace_events.append({
                        "event": "http_request",
                        "method": "GET",
                        "url": url,
                        "attempt": attempt + 1,
                        "max_retries": max_retries,
                        "timeout_s": timeout,
                        "params": params,
                    })

                resp = await client.get(url, params=params)
                last_status = resp.status_code

                if trace:
                    trace_events.append({
                        "event": "http_response",
                        "status_code": resp.status_code,
                        "attempt": attempt + 1,
                        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
                    })

                if resp.status_code == 200:
                    data = resp.json()
                    if trace:
                        trace_events.append({
                            "event": "http_success",
                            "attempt": attempt + 1,
                            "total_elapsed_ms": int((time.perf_counter() - started) * 1000),
                        })
                    return data, trace_events

                if _should_retry(resp.status_code) and attempt < max_retries - 1:
                    sleep_s = _backoff_sleep_seconds(attempt)
                    if trace:
                        trace_events.append({
                            "event": "http_retry_sleep",
                            "status_code": resp.status_code,
                            "attempt": attempt + 1,
                            "sleep_s": round(sleep_s, 3),
                        })
                    await asyncio.sleep(sleep_s)
                    continue

                resp.raise_for_status()

            except httpx.TimeoutException as e:
                last_error = f"timeout: {e}"
                if trace:
                    trace_events.append({
                        "event": "http_timeout",
                        "attempt": attempt + 1,
                        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
                        "message": str(e),
                    })
                if attempt < max_retries - 1:
                    sleep_s = _backoff_sleep_seconds(attempt)
                    if trace:
                        trace_events.append({
                            "event": "http_retry_sleep",
                            "reason": "timeout",
                            "attempt": attempt + 1,
                            "sleep_s": round(sleep_s, 3),
                        })
                    await asyncio.sleep(sleep_s)
                    continue
                raise

            except httpx.HTTPError as e:
                last_error = f"http_error: {e}"
                if trace:
                    trace_events.append({
                        "event": "http_error",
                        "attempt": attempt + 1,
                        "message": str(e),
                    })
                raise

        raise RuntimeError(f"OpenAlex : échec après {max_retries} tentatives sur {url} (status={last_status}, error={last_error})")


# ── Formatage ─────────────────────────────────────────────────────────────────

def _reconstruct_abstract(inverted_index: dict | None) -> str | None:
    """Rebuild plain-text abstract from OpenAlex inverted index format."""
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


def _format_result(work: dict) -> dict:
    """Normalize a raw OpenAlex work payload into the project response schema."""
    authors = []
    author_details = []
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
    doi = raw_doi.replace("https://doi.org/", "") if isinstance(raw_doi, str) and raw_doi else None
    openalex_id = (work.get("id") or "").replace("https://openalex.org/", "")
    publication_date = work.get("publication_date")
    publication_year = work.get("publication_year")
    source_url = work.get("id")

    return {
        "source": "openalex",
        # Canonical cross-skill keys expected by the literature-review-agent.
        "id": openalex_id,
        "openalex_id": openalex_id,
        "title": work.get("title"),
        "authors": authors,
        "author_details": author_details,
        "abstract": _reconstruct_abstract(work.get("abstract_inverted_index")),
        "doi": doi,
        "pdf_url": best_oa.get("pdf_url") or best_oa.get("landing_page_url"),
        "url": source_url,
        "source_url": source_url,
        "year": publication_year,
        "date": publication_date or str(publication_year or ""),
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


# ── Résolution d'IDs (pattern 2 étapes recommandé) ───────────────────────────

async def _resolve_author_id(name_or_orcid: str, *, trace: bool = False) -> tuple[str | None, list[dict]]:
    """Resolve an author name or ORCID into an OpenAlex author identifier."""
    t: list[dict] = []
    if "orcid.org" in name_or_orcid or name_or_orcid.startswith("0000-"):
        orcid = (
            name_or_orcid if name_or_orcid.startswith("https://")
            else f"https://orcid.org/{name_or_orcid}"
        )
        try:
            data, t2 = await _get_with_backoff(f"{OPENALEX_BASE}/authors/{orcid}", {"api_key": API_KEY}, trace=trace)
            t.extend(t2)
            return (data.get("id", "").replace("https://openalex.org/", "") or None), t
        except Exception:
            return None, t

    data, t2 = await _get_with_backoff(
        OPENALEX_AUTHORS,
        {"search": name_or_orcid, "per-page": 1, "api_key": API_KEY},
        trace=trace,
    )
    t.extend(t2)
    results = data.get("results", [])
    resolved = (results[0].get("id") or "").replace("https://openalex.org/", "") if results else ""
    return (resolved or None), t


async def _resolve_institution_id(name_or_ror: str, *, trace: bool = False) -> tuple[str | None, list[dict]]:
    """Resolve an institution name or ROR URL into an OpenAlex institution ID."""
    t: list[dict] = []
    if "ror.org" in name_or_ror:
        try:
            data, t2 = await _get_with_backoff(f"{OPENALEX_BASE}/institutions/{name_or_ror}", {"api_key": API_KEY}, trace=trace)
            t.extend(t2)
            return (data.get("id", "").replace("https://openalex.org/", "") or None), t
        except Exception:
            return None, t

    data, t2 = await _get_with_backoff(
        OPENALEX_INSTITUTIONS,
        {"search": name_or_ror, "per-page": 1, "api_key": API_KEY},
        trace=trace,
    )
    t.extend(t2)
    results = data.get("results", [])
    resolved = (results[0].get("id") or "").replace("https://openalex.org/", "") if results else ""
    return (resolved or None), t


async def search(
    query: str,
    max_results: int = 15,
    date_from: str | None = None,
    date_to: str | None = None,
    filter_open_access: bool = False,
    sort_by: str = "publication_date:desc",
    author: str | None = None,
    institution: str | None = None,
    *,
    trace: bool | None = None,
    http_timeout: float | None = None,
    max_retries: int | None = None,
) -> dict:
    """Search OpenAlex works with optional date, OA, author, and institution filters."""
    trace_effective = TRACE_DEFAULT if trace is None else bool(trace)
    trace_events: list[dict] = []

    filters = []
    if date_from:
        filters.append(f"from_publication_date:{date_from}")
    if date_to:
        filters.append(f"to_publication_date:{date_to}")
    if filter_open_access:
        filters.append("is_oa:true")

    if author:
        author_id, t = await _resolve_author_id(author, trace=trace_effective)
        trace_events.extend(t)
        if author_id:
            filters.append(f"authorships.author.id:{author_id}")
        else:
            out = {"total_found": 0, "returned": 0, "results": [],
                   "error": f"Auteur introuvable dans OpenAlex : '{author}'",
                   "query_used": query, "filters_used": filters}
            if trace_effective:
                out["trace"] = trace_events
            return out

    if institution:
        inst_id, t = await _resolve_institution_id(institution, trace=trace_effective)
        trace_events.extend(t)
        if inst_id:
            filters.append(f"authorships.institutions.id:{inst_id}")
        else:
            out = {"total_found": 0, "returned": 0, "results": [],
                   "error": f"Institution introuvable dans OpenAlex : '{institution}'",
                   "query_used": query, "filters_used": filters}
            if trace_effective:
                out["trace"] = trace_events
            return out

    params: dict[str, Any] = {
        "search": query,
        "per-page": min(max_results, 200),
        "sort": sort_by,
        "select": SELECT_FIELDS,
        "api_key": API_KEY,
    }
    if filters:
        params["filter"] = ",".join(filters)

    data, t = await _get_with_backoff(
        OPENALEX_WORKS,
        params,
        max_retries=max_retries,
        timeout=http_timeout,
        trace=trace_effective,
    )
    trace_events.extend(t)
    results = data.get("results", [])
    out = {
        "total_found": data.get("meta", {}).get("count", 0),
        "returned": len(results),
        "results": [_format_result(r) for r in results],
        "query_used": query,
        "filters_used": filters,
    }
    if trace_effective:
        out["trace"] = trace_events
    return out


async def batch_lookup_by_doi(
    dois: list[str],
    *,
    trace: bool | None = None,
    http_timeout: float | None = None,
    max_retries: int | None = None,
) -> dict:
    """Resolve one or more DOIs and return normalized OpenAlex work records."""
    trace_effective = TRACE_DEFAULT if trace is None else bool(trace)
    trace_events: list[dict] = []

    if not dois:
        out = {"total_found": 0, "returned": 0, "results": []}
        if trace_effective:
            out["trace"] = trace_events
        return out

    all_results = []
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
            "api_key": API_KEY,
        }
        data, t = await _get_with_backoff(
            OPENALEX_WORKS,
            params,
            max_retries=max_retries,
            timeout=http_timeout,
            trace=trace_effective,
        )
        trace_events.extend(t)
        all_results.extend(data.get("results", []))
        if i + 50 < len(dois):
            await asyncio.sleep(0.15)

    out = {
        "total_found": len(all_results),
        "returned": len(all_results),
        "results": [_format_result(r) for r in all_results],
    }
    if trace_effective:
        out["trace"] = trace_events
    return out


async def get_citing_works(
    openalex_id: str,
    max_results: int = 20,
    *,
    trace: bool | None = None,
    http_timeout: float | None = None,
    max_retries: int | None = None,
) -> dict:
    """Fetch works that cite a given OpenAlex work ID."""
    trace_effective = TRACE_DEFAULT if trace is None else bool(trace)
    trace_events: list[dict] = []

    clean_id = openalex_id.replace("https://openalex.org/", "")
    params = {
        "filter": f"cites:{clean_id}",
        "per-page": min(max_results, 200),
        "sort": "cited_by_count:desc",
        "select": SELECT_FIELDS,
        "api_key": API_KEY,
    }
    data, t = await _get_with_backoff(
        OPENALEX_WORKS,
        params,
        max_retries=max_retries,
        timeout=http_timeout,
        trace=trace_effective,
    )
    trace_events.extend(t)
    results = data.get("results", [])
    out = {
        "total_found": data.get("meta", {}).get("count", 0),
        "returned": len(results),
        "results": [_format_result(r) for r in results],
        "cited_work_id": clean_id,
    }
    if trace_effective:
        out["trace"] = trace_events
    return out


async def classify_text(
    text: str,
    *,
    trace: bool | None = None,
    http_timeout: float | None = None,
    max_retries: int | None = None,
) -> dict:
    """Classify input text using OpenAlex topic and keyword enrichment endpoint."""
    trace_effective = TRACE_DEFAULT if trace is None else bool(trace)
    trace_events: list[dict] = []

    text = text.strip()
    if len(text) < 20:
        out = {"error": "Texte trop court (minimum 20 caractères)"}
        if trace_effective:
            out["trace"] = trace_events
        return out

    data, t = await _get_with_backoff(
        OPENALEX_TEXT,
        {"title": text[:2000], "api_key": API_KEY},
        max_retries=max_retries,
        timeout=http_timeout,
        trace=trace_effective,
    )
    trace_events.extend(t)
    out = {
        "topics": [
            {
                "name": t.get("display_name"),
                "score": t.get("score"),
                "field": (t.get("subfield") or {}).get("display_name"),
                "domain": (t.get("domain") or {}).get("display_name"),
            }
            for t in data.get("topics", [])
        ],
        "keywords": [k.get("display_name") for k in data.get("keywords", [])],
    }
    if trace_effective:
        out["trace"] = trace_events
    return out

# ══════════════════════════════════════════════════════════════════════════════
# SECTION : facade
# ══════════════════════════════════════════════════════════════════════════════

import argparse
import asyncio
import json


def _print(data: object) -> int:
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="openalex")

    sub = ap.add_subparsers(dest="cmd", required=True)

    ap_s = sub.add_parser("search")
    ap_s.add_argument("--trace", action="store_true", help="Include execution trace in JSON output")
    ap_s.add_argument("--query", required=True)
    ap_s.add_argument("--max-results", type=int, default=15)
    ap_s.add_argument("--date-from", default=None)
    ap_s.add_argument("--date-to", default=None)
    ap_s.add_argument("--oa", action="store_true")
    ap_s.add_argument("--sort-by", default="publication_date:desc")
    ap_s.add_argument("--author", default=None)
    ap_s.add_argument("--institution", default=None)

    ap_b = sub.add_parser("batch-lookup-by-doi")
    ap_b.add_argument("--trace", action="store_true", help="Include execution trace in JSON output")
    ap_b.add_argument("--doi", action="append", default=[], help="Repeatable")
    ap_b.add_argument("--doi-file", default=None, help="Text file with one DOI per line")

    ap_c = sub.add_parser("get-citing-works")
    ap_c.add_argument("--trace", action="store_true", help="Include execution trace in JSON output")
    ap_c.add_argument("--openalex-id", required=True)
    ap_c.add_argument("--max-results", type=int, default=20)

    ap_t = sub.add_parser("classify-text")
    ap_t.add_argument("--trace", action="store_true", help="Include execution trace in JSON output")
    ap_t.add_argument("--text", default=None)
    ap_t.add_argument("--file", default=None)

    args = ap.parse_args()

    common = {"trace": bool(getattr(args, "trace", False))}

    if args.cmd == "search":
        data = asyncio.run(
            search(
                query=args.query,
                max_results=args.max_results,
                date_from=args.date_from,
                date_to=args.date_to,
                filter_open_access=args.oa,
                sort_by=args.sort_by,
                author=args.author,
                institution=args.institution,
                **common,
            )
        )
        return _print(data)

    if args.cmd == "batch-lookup-by-doi":
        dois = list(args.doi or [])
        if args.doi_file:
            with open(args.doi_file, "r", encoding="utf-8") as f:
                dois.extend([ln.strip() for ln in f if ln.strip()])
        data = asyncio.run(batch_lookup_by_doi(dois, **common))
        return _print(data)

    if args.cmd == "get-citing-works":
        data = asyncio.run(get_citing_works(openalex_id=args.openalex_id, max_results=args.max_results, **common))
        return _print(data)

    if args.cmd == "classify-text":
        text = (args.text or "").strip()
        if not text and args.file:
            with open(args.file, "r", encoding="utf-8") as f:
                text = f.read().strip()
        data = asyncio.run(classify_text(text, **common))
        return _print(data)

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
