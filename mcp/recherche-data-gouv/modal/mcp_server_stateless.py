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
    SITE_URL = BASE_URL[: -len("/api")]  # the web UI root, for human-facing links
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
        """Search public Recherche Data Gouv Dataverse records: datasets, collections and files.

        `q` is Solr syntax — free text, or a field such as `authorName:"Dupont"` or
        `subject:"Agricultural Sciences"`. `types` restricts to "dataset",
        "dataverse" and/or "file"; `filters` are Solr `fq` clauses.

        `subtree` scopes the search to one or more collections **and everything
        beneath them**, recursively: subtree=["inrae"] reaches all 849 of its
        sub-collections. That is what counts a collection's holdings — q="*",
        subtree=["ecoledesponts"], types=["dataset"], per_page=1 returns the count in
        `total_found` without downloading the records. get_collection reports the
        same two numbers directly.

        Collection aliases for `subtree` come from the `identifier` field of a
        types=["dataverse"] hit.
        """
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


    # --- Native API: collections, datasets, files --------------------------------
    #
    # Everything below is a public GET. Unknown aliases and unknown persistent ids
    # are ordinary answers from this repository's point of view, so they come back
    # as an `error` string next to empty results rather than as a transport failure.


    def _error_out(command: str, exc: Exception, trace_events: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
        if isinstance(exc, httpx.HTTPStatusError):
            message = f"HTTP {exc.response.status_code} on {exc.request.url}"
        elif isinstance(exc, httpx.TimeoutException):
            message = f"timeout: {exc}"
        else:
            message = str(exc)
        out: dict[str, Any] = {
            "source": "recherche-data-gouv",
            "command": command,
            "total_found": None,
            "returned": 0,
            "results": [],
            "error": message,
        }
        out.update(extra)
        if trace_events:
            out["trace"] = trace_events
        return out


    def _ok_out(command: str, results: list[dict[str, Any]], total_found: int | None, trace_events: list[dict[str, Any]], include_trace: bool, **extra: Any) -> dict[str, Any]:
        out: dict[str, Any] = {
            "source": "recherche-data-gouv",
            "command": command,
            "total_found": total_found,
            "returned": len(results),
            "results": results,
            "error": None,
        }
        out.update(extra)
        if include_trace:
            out["trace"] = trace_events
        return out


    def _normalize_collection(item: dict[str, Any]) -> dict[str, Any]:
        alias = item.get("alias")
        parent = item.get("isPartOf") if isinstance(item.get("isPartOf"), dict) else {}
        return {
            "source": "recherche-data-gouv",
            "type": "dataverse",
            "id": alias or item.get("id"),
            "entity_id": item.get("id"),
            "alias": alias,
            "name": item.get("name"),
            "affiliation": item.get("affiliation"),
            "description": item.get("description"),
            "url": f"{SITE_URL}/dataverse/{alias}" if alias else None,
            "parent_alias": parent.get("identifier"),
            "parent_name": parent.get("displayName"),
            "dataverse_type": item.get("dataverseType"),
            "creation_date": item.get("creationDate"),
            "contacts": [
                c.get("contactEmail")
                for c in item.get("dataverseContacts") or []
                if isinstance(c, dict) and c.get("contactEmail")
            ],
            "raw": item,
        }


    async def _subtree_total(alias: str, item_type: str, trace: bool) -> tuple[int | None, list[dict[str, Any]]]:
        """How many published objects of one type sit anywhere under a collection."""
        data, events = await _get_json(
            "search",
            [("q", "*"), ("subtree", alias), ("type", item_type), ("per_page", "1")],
            trace=trace,
        )
        payload = data.get("data", {}) if isinstance(data, dict) else {}
        return payload.get("total_count"), events


    @mcp.tool
    async def get_collection(
        identifier: str,
        include_counts: bool = True,
        trace: bool | None = None,
    ) -> dict[str, Any]:
        """Retrieve one Dataverse collection by alias or numeric id.

        `identifier` is an alias such as "ecoledesponts", "inrae" or "root", or the
        numeric id that list_collection_contents returns for a sub-collection.
        Returns the collection's identity card: name, affiliation, description,
        contacts, parent collection.

        With include_counts (the default) it also reports how many published
        datasets and sub-collections sit anywhere beneath it — that is what answers
        "how many datasets does this collection hold?". The counts are recursive:
        they include everything in the sub-tree, not just direct children.

        Aliases come from search(types=["dataverse"]) — the `identifier` field of
        each hit.
        """
        include_trace = TRACE_DEFAULT if trace is None else trace
        events: list[dict[str, Any]] = []
        try:
            data, ev = await _get_json(f"dataverses/{identifier}", [], trace=include_trace)
            events += ev
            record = _normalize_collection(data.get("data", {}) if isinstance(data, dict) else {})
            if include_counts:
                alias = record.get("alias") or identifier
                datasets, ev = await _subtree_total(str(alias), "dataset", include_trace)
                events += ev
                collections, ev = await _subtree_total(str(alias), "dataverse", include_trace)
                events += ev
                record["dataset_count"] = datasets
                record["subcollection_count"] = collections
        except Exception as exc:  # noqa: BLE001 — upstream failures are data here
            return _error_out("get_collection", exc, events, identifier=identifier)

        return _ok_out(
            "get_collection", [record], 1, events, include_trace, identifier=identifier
        )


    def _normalize_content_entry(item: dict[str, Any]) -> dict[str, Any]:
        if item.get("type") == "dataset":
            protocol = item.get("protocol")
            authority = item.get("authority")
            identifier = item.get("identifier")
            pid = f"{protocol}:{authority}/{identifier}" if protocol and authority and identifier else None
            return {
                "source": "recherche-data-gouv",
                "type": "dataset",
                "id": pid or item.get("id"),
                "entity_id": item.get("id"),
                "persistent_id": pid,
                "title": None,  # /contents carries no dataset titles; see the docstring
                "url": item.get("persistentUrl"),
                "publication_date": item.get("publicationDate"),
                "publisher": item.get("publisher"),
                "raw": item,
            }
        return {
            "source": "recherche-data-gouv",
            "type": "dataverse",
            "id": item.get("id"),
            "entity_id": item.get("id"),
            "title": item.get("title"),
            "name": item.get("title"),
            "url": None,  # /contents carries no alias, and the web URL needs one
            "raw": item,
        }


    @mcp.tool
    async def list_collection_contents(
        identifier: str,
        item_type: str | None = None,
        max_items: int = 50,
        trace: bool | None = None,
    ) -> dict[str, Any]:
        """List the direct children of a Dataverse collection: sub-collections and datasets.

        `identifier` is an alias ("ecoledesponts") or a numeric id. `item_type`
        keeps only one kind, "dataverse" or "dataset"; omit it for both.

        This is one hop down the tree, not the whole sub-tree. Two properties of the
        upstream endpoint are worth knowing before choosing it:

        - It has no pagination and ignores any limit, so the whole child list is
          downloaded and `max_items` clamps it here. `total_found` is the untruncated
          count.
        - Dataset entries carry a DOI but no title, and sub-collection entries carry
          a numeric id but no alias. Feed either back into get_collection or
          get_dataset to resolve them.

        For a titled, paginated, recursive listing instead, use
        search(q="*", subtree="<alias>", types=["dataset"]).
        """
        include_trace = TRACE_DEFAULT if trace is None else trace
        if item_type is not None and item_type not in {"dataverse", "dataset"}:
            return _error_out(
                "list_collection_contents",
                ValueError('item_type must be "dataverse", "dataset", or omitted'),
                [],
                identifier=identifier,
            )
        try:
            data, events = await _get_json(f"dataverses/{identifier}/contents", [], trace=include_trace)
        except Exception as exc:  # noqa: BLE001
            return _error_out("list_collection_contents", exc, [], identifier=identifier)

        items = data.get("data") if isinstance(data, dict) else None
        items = [i for i in (items or []) if isinstance(i, dict)]
        if item_type:
            items = [i for i in items if i.get("type") == item_type]
        total = len(items)
        capped = items[: max(0, max_items)]
        return _ok_out(
            "list_collection_contents",
            [_normalize_content_entry(i) for i in capped],
            total,
            events,
            include_trace,
            identifier=identifier,
            item_type=item_type,
            truncated=total > len(capped),
        )


    def _cit_primitive(fields: dict[str, Any], name: str) -> str | None:
        value = (fields.get(name) or {}).get("value")
        return value if isinstance(value, str) else None


    def _cit_compound(fields: dict[str, Any], name: str, *keys: str) -> list[dict[str, Any]]:
        rows = (fields.get(name) or {}).get("value")
        out: list[dict[str, Any]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            entry = {k: (row.get(k) or {}).get("value") for k in keys}
            if any(v for v in entry.values()):
                out.append(entry)
        return out


    def _normalize_dataset(data: dict[str, Any]) -> dict[str, Any]:
        version = data.get("latestVersion") or {}
        blocks = version.get("metadataBlocks") or {}
        fields = {
            f.get("typeName"): f
            for f in (blocks.get("citation") or {}).get("fields", [])
            if isinstance(f, dict)
        }
        subjects = (fields.get("subject") or {}).get("value")
        descriptions = [
            d.get("dsDescriptionValue")
            for d in _cit_compound(fields, "dsDescription", "dsDescriptionValue")
        ]
        license_ = version.get("license")
        if isinstance(license_, dict):
            license_ = license_.get("name")
        return {
            "source": "recherche-data-gouv",
            "type": "dataset",
            "id": version.get("datasetPersistentId") or data.get("persistentUrl"),
            "entity_id": data.get("id"),
            "persistent_id": version.get("datasetPersistentId"),
            "title": _cit_primitive(fields, "title"),
            "authors": _cit_compound(fields, "author", "authorName", "authorAffiliation", "authorIdentifier"),
            "description": "\n\n".join(d for d in descriptions if d) or None,
            "subjects": subjects if isinstance(subjects, list) else [],
            "keywords": [k.get("keywordValue") for k in _cit_compound(fields, "keyword", "keywordValue")],
            "url": data.get("persistentUrl"),
            "publisher": data.get("publisher"),
            "publication_date": data.get("publicationDate"),
            "deposit_date": _cit_primitive(fields, "dateOfDeposit"),
            "depositor": _cit_primitive(fields, "depositor"),
            "production_date": _cit_primitive(fields, "productionDate"),
            "language": (fields.get("language") or {}).get("value"),
            "version": f"{version.get('versionNumber')}.{version.get('versionMinorNumber')}",
            "version_state": version.get("versionState"),
            "last_update": version.get("lastUpdateTime"),
            "license": license_,
            "terms_of_use": version.get("termsOfUse"),
            "file_count": len(version.get("files") or []),
            "metadata_blocks": sorted(blocks.keys()),
        }


    @mcp.tool
    async def get_dataset(
        persistent_id: str,
        include_raw: bool = False,
        trace: bool | None = None,
    ) -> dict[str, Any]:
        """Retrieve the latest published version of one dataset by its persistent id.

        `persistent_id` is the DOI in Dataverse form, e.g. "doi:10.57745/AJT1Z3" —
        the `global_id` of a search hit, or the `persistent_id` of a
        list_collection_contents entry.

        Returns the normalized record: title, authors, description, subjects,
        keywords, dates, version, licence or terms, file count, and which metadata
        blocks the deposit fills. Use list_dataset_files for the files themselves.

        include_raw attaches the untouched upstream payload. It is off by default
        because that payload runs to tens of kilobytes — it embeds every metadata
        block and the whole file list.
        """
        include_trace = TRACE_DEFAULT if trace is None else trace
        try:
            data, events = await _get_json(
                "datasets/:persistentId/", [("persistentId", persistent_id)], trace=include_trace
            )
        except Exception as exc:  # noqa: BLE001
            return _error_out("get_dataset", exc, [], persistent_id=persistent_id)

        payload = data.get("data", {}) if isinstance(data, dict) else {}
        record = _normalize_dataset(payload)
        if include_raw:
            record["raw"] = payload
        return _ok_out(
            "get_dataset", [record], 1, events, include_trace, persistent_id=persistent_id
        )


    def _normalize_file(item: dict[str, Any]) -> dict[str, Any]:
        data_file = item.get("dataFile") or {}
        file_id = data_file.get("id")
        checksum = data_file.get("checksum") or {}
        return {
            "source": "recherche-data-gouv",
            "type": "file",
            "id": file_id,
            "label": item.get("label"),
            "filename": data_file.get("filename"),
            "description": item.get("description") or data_file.get("description"),
            "content_type": data_file.get("contentType"),
            "size_bytes": data_file.get("filesize"),
            "categories": item.get("categories") or [],
            "restricted": item.get("restricted"),
            "persistent_id": data_file.get("persistentId"),
            "url": data_file.get("pidURL"),
            "download_url": f"{BASE_URL}/access/datafile/{file_id}" if file_id else None,
            "checksum_type": checksum.get("type"),
            "checksum": checksum.get("value"),
            "creation_date": data_file.get("creationDate"),
            "raw": item,
        }


    @mcp.tool
    async def list_dataset_files(
        persistent_id: str,
        version: str = ":latest-published",
        max_items: int = 50,
        trace: bool | None = None,
    ) -> dict[str, Any]:
        """List the files of one dataset version, with sizes, checksums and download URLs.

        `persistent_id` is the DOI in Dataverse form, e.g. "doi:10.57745/AJT1Z3".
        `version` accepts ":latest-published" (the default) or an explicit number
        such as "1.0"; draft versions need a credential and are out of reach here.

        Like the collection listing, the upstream endpoint neither paginates nor
        honours a limit, so `max_items` clamps the download here and `total_found`
        reports the untruncated count.

        `download_url` is the public bytes endpoint. This server never fetches it —
        a file is for the caller to download, not for an MCP payload.
        """
        include_trace = TRACE_DEFAULT if trace is None else trace
        try:
            data, events = await _get_json(
                f"datasets/:persistentId/versions/{version}/files",
                [("persistentId", persistent_id)],
                trace=include_trace,
            )
        except Exception as exc:  # noqa: BLE001
            return _error_out(
                "list_dataset_files", exc, [], persistent_id=persistent_id, version=version
            )

        items = data.get("data") if isinstance(data, dict) else None
        items = [i for i in (items or []) if isinstance(i, dict)]
        total = len(items)
        capped = items[: max(0, max_items)]
        return _ok_out(
            "list_dataset_files",
            [_normalize_file(i) for i in capped],
            total,
            events,
            include_trace,
            persistent_id=persistent_id,
            version=version,
            total_size_bytes=sum(
                (i.get("dataFile") or {}).get("filesize") or 0 for i in items
            ),
            truncated=total > len(capped),
        )

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
