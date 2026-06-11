#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ['fastmcp>=2.0', 'httpx']
# ///
"""Recherche Data Gouv MCP server.

Exposes public Dataverse Search, Metrics, and metadata-block GET endpoints for
Recherche Data Gouv. No API key is required for public reads.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import time
from typing import Any

import httpx
from fastmcp import FastMCP


DEFAULT_BASE_URL = "https://entrepot.recherche.data.gouv.fr/api"
USER_AGENT = "smartbiblia-recherche-data-gouv-mcp/0.1"
RETRIED_STATUS = {429, 500, 502, 503, 504}
METRIC_CATEGORIES = {
    "dataverses",
    "datasets",
    "files",
    "downloads",
    "filedownloads",
    "uniquedownloads",
    "uniquefiledownloads",
    "tree",
}
METRIC_BREAKDOWNS = {"monthly", "pastDays", "toMonth", "byCategory", "bySubject", "byType"}
MAKE_DATA_COUNT_METRICS = {
    "viewsTotal",
    "viewsUnique",
    "downloadsTotal",
    "downloadsUnique",
    "citations",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recherche Data Gouv MCP server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Dataverse API base URL")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8014)
    parser.add_argument("--transport", default="streamable-http", choices=["stdio", "sse", "streamable-http"])
    parser.add_argument("--http-timeout", type=float, default=20.0)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--backoff-base", type=float, default=1.0)
    parser.add_argument("--backoff-factor", type=float, default=2.0)
    parser.add_argument("--jitter-max", type=float, default=0.25)
    parser.add_argument("--trace", action="store_true", default=False)
    return parser.parse_args()


args = _parse_args()

BASE_URL = args.base_url.rstrip("/")
if not BASE_URL.endswith("/api"):
    BASE_URL = f"{BASE_URL}/api"
HTTP_TIMEOUT = args.http_timeout
MAX_RETRIES = max(1, args.max_retries)
BACKOFF_BASE = max(0.0, args.backoff_base)
BACKOFF_FACTOR = max(1.0, args.backoff_factor)
JITTER_MAX = max(0.0, args.jitter_max)
TRACE_DEFAULT = args.trace

mcp = FastMCP("recherche-data-gouv")


def _backoff_sleep_seconds(attempt: int) -> float:
    base = BACKOFF_BASE * (BACKOFF_FACTOR ** attempt)
    jitter = random.uniform(0.0, JITTER_MAX) if JITTER_MAX > 0 else 0.0
    return base + jitter


async def _get_json(path: str, params: list[tuple[str, str]] | None = None, *, trace: bool = False) -> tuple[Any, list[dict[str, Any]]]:
    trace_events: list[dict[str, Any]] = []
    started = time.perf_counter()
    url = f"{BASE_URL}/{path.lstrip('/')}"
    request_params = params or []

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
        last_status: int | None = None
        last_error: str | None = None
        for attempt in range(MAX_RETRIES):
            t0 = time.perf_counter()
            try:
                if trace:
                    trace_events.append({
                        "event": "http_request",
                        "method": "GET",
                        "url": url,
                        "params": request_params,
                        "attempt": attempt + 1,
                        "max_retries": MAX_RETRIES,
                    })
                resp = await client.get(url, params=request_params, headers={"Accept": "application/json"})
                last_status = resp.status_code
                if trace:
                    trace_events.append({
                        "event": "http_response",
                        "status_code": resp.status_code,
                        "attempt": attempt + 1,
                        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
                    })

                if resp.status_code == 200:
                    if trace:
                        trace_events.append({
                            "event": "http_success",
                            "attempt": attempt + 1,
                            "total_elapsed_ms": int((time.perf_counter() - started) * 1000),
                        })
                    return resp.json(), trace_events

                if resp.status_code in RETRIED_STATUS and attempt < MAX_RETRIES - 1:
                    sleep_s = _backoff_sleep_seconds(attempt)
                    if trace:
                        trace_events.append({
                            "event": "http_retry_sleep",
                            "status_code": resp.status_code,
                            "sleep_s": round(sleep_s, 3),
                        })
                    await asyncio.sleep(sleep_s)
                    continue

                resp.raise_for_status()

            except httpx.TimeoutException as exc:
                last_error = f"timeout: {exc}"
                if trace:
                    trace_events.append({"event": "http_timeout", "attempt": attempt + 1, "message": str(exc)})
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(_backoff_sleep_seconds(attempt))
                    continue
                raise
            except httpx.HTTPError as exc:
                last_error = f"http_error: {exc}"
                if trace:
                    trace_events.append({"event": "http_error", "attempt": attempt + 1, "message": str(exc)})
                raise

    raise RuntimeError(
        f"Recherche Data Gouv: failed after {MAX_RETRIES} attempts on {url} "
        f"(status={last_status}, error={last_error})"
    )


def _normalize_search_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "recherche-data-gouv",
        "id": item.get("global_id") or item.get("identifier") or item.get("entity_id"),
        "type": item.get("type"),
        "title": item.get("name"),
        "name": item.get("name"),
        "description": item.get("description"),
        "authors": item.get("authors") or [],
        "subjects": item.get("subjects") or [],
        "url": item.get("url"),
        "global_id": item.get("global_id"),
        "identifier": item.get("identifier"),
        "published_at": item.get("published_at"),
        "created_at": item.get("createdAt"),
        "updated_at": item.get("updatedAt"),
        "publisher": item.get("publisher"),
        "citation": item.get("citation"),
        "dataverse_alias": item.get("identifier_of_dataverse"),
        "dataverse_name": item.get("name_of_dataverse"),
        "file_count": item.get("fileCount"),
        "version_state": item.get("versionState"),
        "raw": item,
    }


def _add_repeated(params: list[tuple[str, str]], name: str, values: list[str] | None) -> None:
    for value in values or []:
        if value is not None:
            params.append((name, str(value)))


@mcp.tool
async def search(
    q: str = "*",
    types: list[str] | None = None,
    filters: list[str] | None = None,
    subtree: list[str] | None = None,
    metadata_fields: list[str] | None = None,
    per_page: int = 10,
    start: int = 0,
    sort: str | None = None,
    order: str | None = None,
    show_facets: bool = False,
    show_relevance: bool = False,
    show_entity_ids: bool = False,
    trace: bool | None = None,
) -> dict[str, Any]:
    """Search public Recherche Data Gouv Dataverse records."""
    params: list[tuple[str, str]] = [("q", q), ("per_page", str(per_page)), ("start", str(start))]
    _add_repeated(params, "type", types)
    _add_repeated(params, "fq", filters)
    _add_repeated(params, "subtree", subtree)
    _add_repeated(params, "metadata_fields", metadata_fields)
    if sort:
        params.append(("sort", sort))
    if order:
        params.append(("order", order))
    if show_facets:
        params.append(("show_facets", "true"))
    if show_relevance:
        params.append(("show_relevance", "true"))
    if show_entity_ids:
        params.append(("show_entity_ids", "true"))

    include_trace = TRACE_DEFAULT if trace is None else trace
    data, trace_events = await _get_json("search", params, trace=include_trace)
    payload = data.get("data", {}) if isinstance(data, dict) else {}
    items = payload.get("items") or []
    out = {
        "source": "recherche-data-gouv",
        "command": "search",
        "status": data.get("status") if isinstance(data, dict) else None,
        "query_used": payload.get("q", q),
        "total_found": payload.get("total_count", 0),
        "returned": len(items),
        "start": payload.get("start", start),
        "count_in_response": payload.get("count_in_response", len(items)),
        "spelling_alternatives": payload.get("spelling_alternatives") or {},
        "facets": payload.get("facets") or {},
        "results": [_normalize_search_item(item) for item in items if isinstance(item, dict)],
        "error": None,
    }
    if include_trace:
        out["trace"] = trace_events
    return out


def _metric_path(
    category: str,
    breakdown: str | None,
    value: str | None,
    make_data_count_metric: str | None,
) -> str:
    if make_data_count_metric:
        if make_data_count_metric not in MAKE_DATA_COUNT_METRICS:
            raise ValueError(
                "make_data_count_metric must be one of "
                + ", ".join(sorted(MAKE_DATA_COUNT_METRICS))
            )
        path = f"info/metrics/makeDataCount/{make_data_count_metric}"
    else:
        if category not in METRIC_CATEGORIES:
            raise ValueError("category must be one of " + ", ".join(sorted(METRIC_CATEGORIES)))
        path = f"info/metrics/{category}"

    if breakdown:
        if breakdown not in METRIC_BREAKDOWNS:
            raise ValueError("breakdown must be one of " + ", ".join(sorted(METRIC_BREAKDOWNS)))
        path = f"{path}/{breakdown}"
        if breakdown in {"pastDays", "toMonth"}:
            if not value:
                raise ValueError(f"value is required for breakdown {breakdown}")
            path = f"{path}/{value}"
    return path


@mcp.tool
async def metrics(
    category: str = "downloads",
    breakdown: str | None = None,
    value: str | None = None,
    make_data_count_metric: str | None = None,
    parent_alias: str | None = None,
    data_location: str | None = None,
    country: str | None = None,
    format: str | None = None,
    trace: bool | None = None,
) -> dict[str, Any]:
    """Fetch public Dataverse Metrics API values."""
    path = _metric_path(category, breakdown, value, make_data_count_metric)
    params: list[tuple[str, str]] = []
    if parent_alias:
        params.append(("parentAlias", parent_alias))
    if data_location:
        params.append(("dataLocation", data_location))
    if country:
        params.append(("country", country))
    if format:
        params.append(("format", format))

    include_trace = TRACE_DEFAULT if trace is None else trace
    data, trace_events = await _get_json(path, params, trace=include_trace)
    out = {
        "source": "recherche-data-gouv",
        "command": "metrics",
        "category": category,
        "breakdown": breakdown,
        "value": value,
        "make_data_count_metric": make_data_count_metric,
        "data": data,
        "error": None,
    }
    if include_trace:
        out["trace"] = trace_events
    return out


@mcp.tool
async def metadatablocks(block: str | None = None, trace: bool | None = None) -> dict[str, Any]:
    """List Dataverse metadata blocks or retrieve one block schema."""
    path = "metadatablocks" if not block else f"metadatablocks/{block}"
    include_trace = TRACE_DEFAULT if trace is None else trace
    data, trace_events = await _get_json(path, [], trace=include_trace)
    out = {
        "source": "recherche-data-gouv",
        "command": "metadatablocks",
        "block": block,
        "data": data,
        "error": None,
    }
    if include_trace:
        out["trace"] = trace_events
    return out


if __name__ == "__main__":
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport=args.transport, host=args.host, port=args.port)
