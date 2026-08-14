"""Recherche Data Gouv MCP server — Modal deployment.

A **standalone duplicate** of the canonical server, `../mcp_server.py`, built on
the shape of Modal's own FastMCP example: nothing is mounted into the image and
nothing is imported from the parent folder. Everything the server needs is
defined inside `make_mcp_server()`, including its runtime imports — Modal loads
this file on the local machine to build the app, where `fastmcp` and `httpx` are
not installed, so a top-level import of either would break `modal deploy`.

The tools below are a **hand-kept copy** of the canonical ones — same names, same
arguments, same envelope. Change one, change the other.

Tools served: `search`, `metrics`, `metadatablocks`.

  # Ephemeral deployment that reloads on save
  uvx modal serve mcp/recherche-data-gouv/modal/mcp_server_stateless.py

  # List the deployed tools (and optionally call one)
  uvx modal run mcp/recherche-data-gouv/modal/mcp_server_stateless.py::test_tool

  # Persistent deployment
  uvx modal deploy mcp/recherche-data-gouv/modal/mcp_server_stateless.py

The MCP endpoint is the printed URL with `/mcp/` appended:

    https://<workspace>--smartbiblia-mcp-recherche-data-gouv-web.modal.run/mcp/

Modal load-balances one URL across containers that come and go, so the transport
is built **stateless** (`stateless_http=True`): a new transport per request, no
session pinned to a replica — the same mode as
`mcp_server.py --transport http --stateless`. A stateless response carries no
`mcp-session-id` header, which is how to check the mode of a running server.

Environment: RECHERCHE_DATA_GOUV_API_URL — optional, only to point the server
at another Dataverse instance. Public reads, no credential.
"""

import modal

APP_NAME = "smartbiblia-mcp-recherche-data-gouv"

image = modal.Image.debian_slim(python_version="3.12").uv_pip_install(
    "fastapi>=0.115",
    "fastmcp>=3.4,<4",  # keep in step with the pin in ../mcp_server.py
    "httpx",
)

app = modal.App(APP_NAME, image=image)

# Optional configuration. Create the Secret once, then uncomment:
#     modal secret create smartbiblia-recherche-data-gouv RECHERCHE_DATA_GOUV_API_URL=...
# Left out, the server runs on its defaults — which is a working deployment.
SECRETS: list[modal.Secret] = []
# SECRETS = [modal.Secret.from_name("smartbiblia-recherche-data-gouv")]


def make_mcp_server():
    """Build the FastMCP server served by `web()`.

    The body is `../mcp_server.py` without its argparse layer: each tuning flag
    becomes the constant below at exactly its default value, which is what
    `uv run mcp_server.py` with no flag selects. Endpoint and credentials stay
    environment-based, so a `modal.Secret` configures this deployment the way
    `.env` configures the container.
    """
    import asyncio
    import os
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

    BASE_URL = os.environ.get("RECHERCHE_DATA_GOUV_API_URL", DEFAULT_BASE_URL).rstrip("/")
    if not BASE_URL.endswith("/api"):
        BASE_URL = f"{BASE_URL}/api"
    HTTP_TIMEOUT = 20.0
    MAX_RETRIES = 2
    BACKOFF_BASE = 1.0
    BACKOFF_FACTOR = 2.0
    JITTER_MAX = 0.25
    TRACE_DEFAULT = False

    mcp = FastMCP(
        name="recherche-data-gouv",
        instructions=(
            "Recherche Data Gouv connector — search the French national research data "
            "repository (Dataverse), read dataset and dataverse metadata, and fetch "
            "usage metrics. Public reads only; no API key required."
        ),
    )

    # One pooled client for the process. Opening an AsyncClient per call would
    # rebuild the connection pool — and replay the TLS handshake — every time.
    HTTP = httpx.AsyncClient(
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )


    def _backoff_sleep_seconds(attempt: int) -> float:
        base = BACKOFF_BASE * (BACKOFF_FACTOR ** attempt)
        jitter = random.uniform(0.0, JITTER_MAX) if JITTER_MAX > 0 else 0.0
        return base + jitter


    async def _get_json(path: str, params: list[tuple[str, str]] | None = None, *, trace: bool = False) -> tuple[Any, list[dict[str, Any]]]:
        trace_events: list[dict[str, Any]] = []
        started = time.perf_counter()
        url = f"{BASE_URL}/{path.lstrip('/')}"
        request_params = params or []

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
                resp = await HTTP.get(url, params=request_params)
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

    return mcp


@app.function(secrets=SECRETS)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def web():
    """Web gateway for the MCP server."""
    from fastapi import FastAPI

    mcp = make_mcp_server()
    mcp_app = mcp.http_app(transport="streamable-http", stateless_http=True)

    # The MCP app owns a lifespan (session-manager startup); mounting it under a
    # FastAPI parent drops that lifespan unless it is handed over explicitly.
    fastapi_app = FastAPI(lifespan=mcp_app.router.lifespan_context)
    fastapi_app.mount("/", mcp_app, "mcp")

    return fastapi_app


@app.function(secrets=SECRETS)
async def test_tool(tool_name: str | None = None, arguments: str | None = None):
    """List the tools this deployment serves, and optionally call one.

        uvx modal run mcp/recherche-data-gouv/modal/mcp_server_stateless.py::test_tool

    Args:
        tool_name: Tool to call. Only the listing runs when omitted.
        arguments: JSON object of arguments for that tool. Defaults to `{}`.
    """
    import json

    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    # `.aio()`: the blocking accessor warns when called from a coroutine.
    url = await web.get_web_url.aio()
    client = Client(StreamableHttpTransport(url=f"{url}/mcp/"))

    async with client:
        tools = await client.list_tools()
        for tool in tools:
            print(tool.name)

        if tool_name is None:
            return
        if tool_name not in {tool.name for tool in tools}:
            raise Exception(f"could not find tool {tool_name}")

        result = await client.call_tool(
            tool_name, json.loads(arguments) if arguments else {}
        )
        print(result.data)
