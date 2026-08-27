"""Primo MCP server — Modal deployment.

A **standalone duplicate** of the canonical server, `../mcp_server.py`, built on
the shape of Modal's own FastMCP example: nothing is mounted into the image and
nothing is imported from the parent folder. Everything the server needs is
defined inside `make_mcp_server()`, including its runtime imports — Modal loads
this file on the local machine to build the app, where `fastmcp` and `httpx` are
not installed, so a top-level import of either would break `modal deploy`.

The tools below are a **hand-kept copy** of the canonical ones — same names, same
arguments, same envelope. Change one, change the other.

Tools served: `search_catalog`, `get_record`.

  # Ephemeral deployment that reloads on save
  uvx modal serve mcp/primo/modal/mcp_server_stateless.py

  # List the deployed tools (and optionally call one)
  uvx modal run mcp/primo/modal/mcp_server_stateless.py::test_tool

  # Persistent deployment
  uvx modal deploy mcp/primo/modal/mcp_server_stateless.py

The MCP endpoint is the printed URL with `/mcp/` appended:

    https://<workspace>--smartbiblia-mcp-primo-web.modal.run/mcp/

Modal load-balances one URL across containers that come and go, so the transport
is built **stateless** (`stateless_http=True`): a new transport per request, no
session pinned to a replica — the same mode as
`mcp_server.py --transport http --stateless`. A stateless response carries no
`mcp-session-id` header, which is how to check the mode of a running server.

Environment: PRIMO_API_KEY, PRIMO_VID, PRIMO_TAB, PRIMO_SCOPE — required;
PRIMO_REGION, PRIMO_BASE_URL, PRIMO_INST, PRIMO_LANG — optional. `make_mcp_server()`
raises when the key is missing, so a container without the secret fails at cold
start rather than serving half-configured tools.
"""

import modal

APP_NAME = "smartbiblia-mcp-primo"

image = modal.Image.debian_slim(python_version="3.12").uv_pip_install(
    "fastapi>=0.115",
    "fastmcp>=3.4,<4",  # keep in step with the pin in ../mcp_server.py
    "httpx",
)

app = modal.App(APP_NAME, image=image)

# Required configuration. Create the Secret before deploying:
#     modal secret create smartbiblia-primo PRIMO_API_KEY=... PRIMO_VID=... PRIMO_TAB=... PRIMO_SCOPE=...
# `required_keys` turns a missing key into a deploy-time error naming it,
# instead of a container that crashes on its first request.
SECRETS: list[modal.Secret] = [
    modal.Secret.from_name(
        "smartbiblia-primo",
        required_keys=["PRIMO_API_KEY", "PRIMO_VID", "PRIMO_TAB", "PRIMO_SCOPE"],
    )
]


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
    import re
    import time
    from typing import Any

    import httpx
    from fastmcp import FastMCP

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

    DEFAULT_VID    = os.environ.get("PRIMO_VID")
    DEFAULT_TAB    = os.environ.get("PRIMO_TAB")
    DEFAULT_SCOPE  = os.environ.get("PRIMO_SCOPE")
    DEFAULT_INST   = os.environ.get("PRIMO_INST")
    DEFAULT_LANG   = os.environ.get("PRIMO_LANG", "en")
    HTTP_TIMEOUT   = 30.0
    MAX_RETRIES    = 3
    BACKOFF_BASE   = 1.0
    BACKOFF_FACTOR = 2.0
    JITTER_MAX     = 0.25
    TRACE_DEFAULT  = False

    REGION = os.environ.get("PRIMO_REGION", "na")
    EXPLICIT_BASE_URL = os.environ.get("PRIMO_BASE_URL")

    BASE_URL = (EXPLICIT_BASE_URL.rstrip("/") if EXPLICIT_BASE_URL
                else REGION_HOSTS.get(REGION.lower(), REGION_HOSTS["na"]))

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

        ─── Query syntax ──────────────────────────────────────────────────────────

        Primo's `q` parameter is a triple `field,precision,value`, which this tool
        assembles from the `query`, `field` and `precision` arguments — pass plain
        words in `query`, never a pre-built triple.

          field      any (default, every indexed field) · title · creator (author)
                     · sub (subject) · usertag (reader-supplied tags)
          precision  contains (default, all words in any order) · exact (the whole
                     field matches the value) · begins_with (prefix match)

        A `;` inside `query` is Primo's own separator between several `q` clauses;
        it is replaced by a space here, so one call sends one clause. Split a
        multi-field search into several calls, or narrow it with the facets below.

        ─── Facets ────────────────────────────────────────────────────────────────

        Each facet argument becomes a `qInclude` clause `category,exact,value`,
        and several of them are AND-combined. The category behind each argument —

          resource_type   facet_rtype     books, articles, journals, book_chapters,
                                          dissertations, reviews, newspaper_articles,
                                          images, audios, videos, maps, scores,
                                          databases, web_resources
          language        facet_lang      3-letter ISO 639-2/B code: eng, fre, ger,
                                          spa, ita, lat…
          library         facet_library   institution-specific library code
          collection      facet_domain    institution-specific collection / domain
          availability    facet_tlevel    available, online_resources,
                                          physical_item; some views also expose
                                          open_access and peer_reviewed
          year_from /     facet_searchcreationdate  sent as a range
          year_to                         [<from> TO <to>], an open bound as `*`

        Facet values are exact strings, and `library` and `collection` in
        particular are configured per institution: call once with
        return_facets=True and read the buckets rather than guessing. A year
        outside 1000-2999 is treated as "no bound", so a stray 0 does not silently
        return zero records.

        ─── Sorting, paging, availability ─────────────────────────────────────────

        sort: rank (relevance, default) · title · author · date · date_d (newest
        first) · date_a (oldest first); an unknown value falls back to rank.
        Paging: max_results is capped at 50 by the API, offset walks the result set
        (beyond ~2000 Primo degrades — narrow the query instead).
        full_text_only=True sends pcAvailability=false, keeping only records the
        institution can actually deliver.

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

        There is no query syntax here: the record must already be identified. The
        `recordid` is the `control.recordid` value of a PNX record, returned as the
        `id` of every search_catalog hit — local records typically look like
        "alma99…" and Central Discovery Index records like "cdi_…". The `context`
        must match the record's origin: "L" for a local institution record, "PC"
        for a CDI record. Asking for the wrong one answers "record not found"
        rather than an error.

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

        uvx modal run mcp/primo/modal/mcp_server_stateless.py::test_tool

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
