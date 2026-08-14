"""HAL MCP server — Modal deployment.

A **standalone duplicate** of the canonical server, `../mcp_server.py`, built on
the shape of Modal's own FastMCP example: nothing is mounted into the image and
nothing is imported from the parent folder. Everything the server needs is
defined inside `make_mcp_server()`, including its runtime imports — Modal loads
this file on the local machine to build the app, where `fastmcp` and `httpx` are
not installed, so a top-level import of either would break `modal deploy`.

The tools below are a **hand-kept copy** of the canonical ones — same names, same
arguments, same envelope. Change one, change the other.

Tools served: `search_hal`, `list_portals`, `lookup_reference`.

  # Ephemeral deployment that reloads on save
  uvx modal serve mcp/hal/modal/mcp_server_stateless.py

  # List the deployed tools (and optionally call one)
  uvx modal run mcp/hal/modal/mcp_server_stateless.py::test_tool

  # Persistent deployment
  uvx modal deploy mcp/hal/modal/mcp_server_stateless.py

The MCP endpoint is the printed URL with `/mcp/` appended:

    https://<workspace>--smartbiblia-mcp-hal-web.modal.run/mcp/

Modal load-balances one URL across containers that come and go, so the transport
is built **stateless** (`stateless_http=True`): a new transport per request, no
session pinned to a replica — the same mode as
`mcp_server.py --transport http --stateless`. A stateless response carries no
`mcp-session-id` header, which is how to check the mode of a running server.

Environment: none. The CCSD search and reference APIs are public and anonymous.
"""

import modal

APP_NAME = "smartbiblia-mcp-hal"

image = modal.Image.debian_slim(python_version="3.12").uv_pip_install(
    "fastapi>=0.115",
    "fastmcp>=3.4,<4",  # keep in step with the pin in ../mcp_server.py
    "httpx",
)

app = modal.App(APP_NAME, image=image)

# No credential to pass. `SECRETS` stays declared so the two functions below
# read the same as every other server in this repository.
SECRETS: list[modal.Secret] = []


def make_mcp_server():
    """Build the FastMCP server served by `web()`.

    The body is `../mcp_server.py` without its argparse layer: each tuning flag
    becomes the constant below at exactly its default value, which is what
    `uv run mcp_server.py` with no flag selects. Endpoint and credentials stay
    environment-based, so a `modal.Secret` configures this deployment the way
    `.env` configures the container.
    """
    import os
    import random
    import time
    import urllib.parse
    from typing import Any

    import httpx
    from fastmcp import FastMCP

    HTTP_TIMEOUT   = 20.0
    MAX_RETRIES    = 3
    BACKOFF_BASE   = 1.0
    BACKOFF_FACTOR = 2.0
    JITTER_MAX     = 0.25
    TRACE_DEFAULT  = False

    BASE_URL     = "https://api.archives-ouvertes.fr/search/"
    REF_BASE_URL = "https://api.archives-ouvertes.fr/ref/"

    # AureHAL references that answer with a regular Solr envelope
    # (`response.numFound` + `response.docs`) and honour q / fl / rows / start / sort.
    # `instance` is deliberately absent: it ignores q and rows and always returns the
    # full list of portals, so `list_portals` filters it client-side instead.
    REF_ENDPOINTS = (
        "structure",
        "author",
        "journal",
        "anrproject",
        "europeanproject",
        "domain",
    )

    # Hard ceilings. HAL answers much larger `rows` values, but a tool result is
    # model context: a runaway page costs the caller its whole window.
    MAX_ROWS        = 100
    MAX_FACET_LIMIT = 500


    # ══════════════════════════════════════════════════════════════════════════════
    # SECTION: HTTP layer — retry / backoff (synchronous, httpx)
    # ══════════════════════════════════════════════════════════════════════════════

    # One pooled client for the process: httpx.get() would rebuild the pool — and
    # replay the TLS handshake — on every call.
    HTTP = httpx.Client(
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": "smartbiblia-hal-mcp/0.1"},
    )


    def _should_retry(status_code: int) -> bool:
        """HTTP codes worth a retry (transient failures)."""
        return status_code in (429, 500, 502, 503, 504)


    def _backoff_sleep(attempt: int) -> float:
        """Exponential delay with random jitter."""
        base = BACKOFF_BASE * (BACKOFF_FACTOR ** attempt)
        jitter = random.uniform(0.0, JITTER_MAX) if JITTER_MAX > 0 else 0.0
        return base + jitter


    def _get_json(url: str, *, trace: bool = False) -> tuple[dict, list[dict]]:
        """
        Synchronous GET with exponential retry. Returns (json_obj, trace_events).

        Retried statuses: 429, 500, 502, 503, 504; timeouts are retried too.
        Raises RuntimeError when every attempt fails — the caller turns that into an
        `error` field rather than letting it surface as a protocol error.
        """
        trace_events: list[dict] = []
        started = time.perf_counter()
        last_status: int | None = None
        last_error: str | None = None

        for attempt in range(MAX_RETRIES):
            t0 = time.perf_counter()
            if trace:
                trace_events.append({
                    "event": "http_request", "method": "GET", "url": url,
                    "attempt": attempt + 1, "max_retries": MAX_RETRIES,
                    "timeout_s": HTTP_TIMEOUT,
                })
            try:
                resp = HTTP.get(url)
                last_status = resp.status_code

                if trace:
                    trace_events.append({
                        "event": "http_response",
                        "status_code": resp.status_code,
                        "attempt": attempt + 1,
                        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
                    })

                if resp.status_code == 200:
                    try:
                        obj = resp.json()
                    except ValueError as e:
                        ctype = resp.headers.get("content-type", "")
                        raise RuntimeError(
                            f"non-JSON response (content-type={ctype}): {e}"
                        ) from e
                    if trace:
                        trace_events.append({
                            "event": "http_success",
                            "total_elapsed_ms": int((time.perf_counter() - started) * 1000),
                        })
                    return obj, trace_events

                if _should_retry(resp.status_code) and attempt < MAX_RETRIES - 1:
                    sleep_s = _backoff_sleep(attempt)
                    if trace:
                        trace_events.append({
                            "event": "http_retry_sleep",
                            "status_code": resp.status_code,
                            "attempt": attempt + 1,
                            "sleep_s": round(sleep_s, 3),
                        })
                    time.sleep(sleep_s)
                    continue

                raise RuntimeError(f"HTTP {resp.status_code} on {url}")

            except httpx.TimeoutException as e:
                last_error = f"timeout: {e}"
                if trace:
                    trace_events.append({
                        "event": "http_timeout", "attempt": attempt + 1,
                        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
                    })
                if attempt < MAX_RETRIES - 1:
                    sleep_s = _backoff_sleep(attempt)
                    if trace:
                        trace_events.append({
                            "event": "http_retry_sleep", "reason": "timeout",
                            "sleep_s": round(sleep_s, 3),
                        })
                    time.sleep(sleep_s)
                    continue
                raise RuntimeError(f"HAL API: {last_error}") from e

            except httpx.HTTPError as e:
                last_error = str(e)
                if trace:
                    trace_events.append({
                        "event": "http_error", "attempt": attempt + 1, "message": str(e),
                    })
                raise RuntimeError(f"HAL API: {last_error}") from e

        raise RuntimeError(
            f"HAL API: failed after {MAX_RETRIES} attempts on {url} "
            f"(status={last_status}, error={last_error})"
        )


    # ══════════════════════════════════════════════════════════════════════════════
    # SECTION: normalization
    # ══════════════════════════════════════════════════════════════════════════════
    #
    # Solr returns almost every field as a list, even when a single value is stored.
    # `_pick_first` collapses that, and the untouched document stays under `raw` so
    # nothing the normalization drops is lost to the caller.

    def _pick_first(v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, list):
            return str(v[0]) if v else None
        return str(v)


    def _format_doc(doc: dict) -> dict:
        """
        Normalize a HAL document into the shared bibliographic record shape.

        Field names align with the OpenAlex / Sudoc / Primo connectors — `title`,
        `authors`, `abstract`, `doi`, `year`, `date`, `doc_type`, `journal` — so
        results from several of them merge and deduplicate on `doi`.
        """
        hal_id = _pick_first(doc.get("halId_s"))
        uri = _pick_first(doc.get("uri_s"))

        authors = doc.get("authFullName_s")
        if authors is None:
            authors = doc.get("authFullName_t")
        if isinstance(authors, str):
            authors_list = [authors]
        elif isinstance(authors, list):
            authors_list = [str(a) for a in authors]
        else:
            authors_list = []

        year = doc.get("publicationDateY_i")
        try:
            year = int(year) if year is not None else None
        except (TypeError, ValueError):
            year = None

        return {
            "source": "hal",
            "id": hal_id,
            "hal_id": hal_id,
            "title": _pick_first(doc.get("title_s")) or _pick_first(doc.get("title_t")),
            "authors": authors_list,
            "abstract": _pick_first(doc.get("abstract_s")) or _pick_first(doc.get("abstract_t")),
            "doi": _pick_first(doc.get("doiId_s")),
            "pdf_url": _pick_first(doc.get("fileMain_s")) or _pick_first(doc.get("openAccessFile_s")),
            "url": uri,
            "source_url": uri,
            "year": year,
            "date": _pick_first(doc.get("publicationDate_s")) or _pick_first(doc.get("producedDate_s")),
            "doc_type": _pick_first(doc.get("docType_s")),
            "journal": _pick_first(doc.get("journalTitle_s")) or _pick_first(doc.get("journalTitle_t")),
            "raw": doc,
        }


    def _format_ref_doc(ref: str, doc: dict) -> dict:
        """
        Normalize an AuréHAL reference entry into a minimal record.

        The reference endpoints do not share a schema: a structure, an author and a
        journal have almost nothing in common. Only the identity anchors are unified
        — `id`, `label`, `url` — and the source entry is kept verbatim under `raw`,
        because that is where the field needed by the next query lives (`docid` for
        `structId_i`, `code` for a collection or portal path).
        """
        label = (
            _pick_first(doc.get("label_s"))
            or _pick_first(doc.get("name"))
            or _pick_first(doc.get("fullName_s"))
            or _pick_first(doc.get("title_s"))
            or _pick_first(doc.get("code_s"))
            or _pick_first(doc.get("code"))
        )
        return {
            "source": "hal",
            "ref": ref,
            "id": _pick_first(doc.get("docid")) or _pick_first(doc.get("id")),
            "label": label,
            "code": _pick_first(doc.get("code")) or _pick_first(doc.get("code_s")),
            "acronym": _pick_first(doc.get("acronym_s")),
            "url": _pick_first(doc.get("url_s")) or _pick_first(doc.get("url")),
            "raw": doc,
        }


    def _format_facets(facet_counts: dict | None) -> dict[str, list[dict]]:
        """
        Turn Solr's flat `[value, count, value, count, …]` lists into buckets.

        Solr encodes a facet as one alternating array; every consumer has to unpack
        it the same way, so the server does it once and publishes
        `{field: [{"value": …, "count": …}]}`. The untouched Solr block stays under
        `facets_raw` for what this shape would lose (pivots, ranges, queries).
        """
        out: dict[str, list[dict]] = {}
        for field, flat in ((facet_counts or {}).get("facet_fields") or {}).items():
            buckets: list[dict] = []
            if isinstance(flat, list):
                for i in range(0, len(flat) - 1, 2):
                    buckets.append({"value": flat[i], "count": flat[i + 1]})
            out[field] = buckets
        return out


    def _scope_url(collection: str | None, portal: str | None) -> tuple[str, dict]:
        """
        Build the scoped `/search/` path.

        HAL scopes by path segment, and the case tells the two apart: a **collection**
        code is uppercase (`/search/FRANCE-GRILLES/`), a **portal** code is lowercase
        (`/search/tel/`). A collection wins when both are given, so the behaviour
        stays deterministic.
        """
        if collection:
            code = collection.strip("/")
            return urllib.parse.urljoin(BASE_URL, f"{code}/"), {"type": "collection", "value": code}
        if portal:
            code = portal.strip("/")
            return urllib.parse.urljoin(BASE_URL, f"{code}/"), {"type": "portal", "value": code}
        return BASE_URL, {"type": "global", "value": None}


    # ══════════════════════════════════════════════════════════════════════════════
    # SECTION: MCP server
    # ══════════════════════════════════════════════════════════════════════════════

    mcp = FastMCP(
        name="hal",
        instructions=(
            "HAL connector that searches over the French national open repository (CCSD): "
            "articles, conference papers, theses, reports, preprints, book chapters, "
            "software and datasets deposited by French research institutions. "
            "The search API is a Solr index, so queries use Solr syntax and can be "
            "scoped to a collection (uppercase code) or a portal (lowercase code), "
            "faceted, pivoted and sorted. Use `list_portals` to discover a portal "
            "code and `lookup_reference` to resolve a laboratory, an author, a "
            "journal or a project into the identifier that filters a search."
        ),
    )

    SERVER_NAME = "hal"


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

        `results` is always an array and `error` always present (null on success), so
        an agent reads an upstream failure in the payload instead of catching a
        protocol error. `total_found` is null when the source cannot count.
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


    # ── Tool 1 : search ───────────────────────────────────────────────────────────

    @mcp.tool
    def search_hal(
        query: str = "*:*",
        collection: str | None = None,
        portal: str | None = None,
        filters: list[str] | None = None,
        fields: str = "halId_s,title_s,authFullName_s,doiId_s,publicationDateY_i,docType_s,uri_s",
        max_results: int = 15,
        start: int = 0,
        sort: str | None = None,
        facet_fields: list[str] | None = None,
        facet_mincount: int = 1,
        facet_limit: int = 20,
        facet_sort: str | None = None,
        facet_prefix: str | None = None,
        facet_pivot: list[str] | None = None,
        group_field: str | None = None,
        group_limit: int = 1,
    ) -> dict:
        """
        Search HAL documents through the CCSD Solr search API.

        Returns normalized bibliographic records (title, authors, abstract, DOI,
        year, document type, journal, HAL URI) plus, when asked, facet buckets.

        ─── Scoping comes first ───────────────────────────────────────────────────

        A global search covers the whole national repository — over 3 million
        deposits — and rarely gives a precise answer. Scope it:

          collection="FRANCE-GRILLES"   a HAL collection, code is UPPERCASE
          portal="tel"                  a HAL portal/instance, code is lowercase

        A collection wins when both are given. Use `list_portals` to find a portal
        code; collections have no reference endpoint and are discovered from a
        facet: facet_fields=["collCodeName_fs"] on a global search.

        ─── Query syntax ──────────────────────────────────────────────────────────

        Solr syntax, unencoded — this tool encodes the URL itself.

          text:asie                      default index, `asie` alone means the same
          title_t:"mémoire collective"   phrase on a searchable text field
          authFullName_t:dupont AND publicationDateY_i:2023
          doiId_id:10.1145/3459637.3482468

        `text` aggregates title, authors, abstract, keywords, journal, conference,
        identifiers and project names. `text_fulltext` adds the indexed full text of
        deposited PDFs — use it when the term belongs in the body, not the metadata.

        ─── Field suffixes decide what a field can do ─────────────────────────────

        Using a field outside its capability is the single most common cause of an
        empty result set with no error:

          _s      display (fields) + facet + sort, NOT searchable
          _t      searchable text only, not returnable, not facetable
          _sci    display + facet + search + sort
          _i      int/long/double — display + facet + search + sort
          _bool   display + facet + search + sort
          _fs     facetString — display + facet, not searchable
          _id     identifier match only (ignores - _ /), not returnable
          _tdate  ISO 8601 — display + search + sort, NOT facetable
          _sort   sort only

        Rule of thumb: **search on `_t`, return and facet on `_s`, sort on
        `_i`/`_s`, match identifiers on `_id`.**

        Fields worth knowing — search side → return/facet side:
          title_t → title_s · abstract_t → abstract_s · keyword_t → keyword_s
          authFullName_t, authLastName_t → authFullName_s, authIdHal_s
          structure_t, structName_t → structId_i, structIdName_fs
          collection_t → collCode_s, collCodeName_fs · portal → instance_s
          journal_t → journalTitle_s, journalIssn_s, journalId_i
          conference_t → conferenceTitle_s, conferenceStartDateY_i
          domain_t → domain_s · language_s · docType_s
          halId_id, doiId_id, arxivId_id, pubmedId_id, nntId_id, isbn_id
          openAccess_bool, fileMain_s, files_s, licence_s
          anrProject_t → anrProjectReference_s · europeanProject_t → europeanProjectReference_s

        Five date families answer different questions — `publicationDate*`
        (published), `producedDate*` (written), `submittedDate*` (deposited),
        `releasedDate*` (made visible), `defenseDate*` (thesis defence). Each exists
        as `_s`, `_tdate` and split `Y_i` / `M_i` / `D_i`; year filters and
        histograms use the `Y_i` form.

        Document types (`docType_s`): ART COMM POSTER PROCEEDINGS ISSUE OUV COUV
        BLOG NOTICE TRAD PATENT REPORT (RESREPORT TECHREPORT FUNDREPORT
        EXPERTREPORT DMP) THESE ETABTHESE HDR MEM LECTURE UNDEFINED (PREPRINT
        WORKINGPAPER) IMG VIDEO SON MAP SOFTWARE OTHER.

        Args:
            query: Solr query string. Defaults to "*:*" (everything in scope).

            collection: HAL collection code, uppercase, e.g. "FRANCE-GRILLES".
                        Takes precedence over `portal`.

            portal: HAL portal/instance code, lowercase, e.g. "tel" or "uvsq".

            filters: Solr filter queries applied on top of `query`, e.g.
                     ["publicationDateY_i:[2020 TO 2024]", "docType_s:ART"].
                     Filters do not affect scoring and are cached by Solr — prefer
                     them over stacking clauses into `query`.

            fields: Comma-separated list of fields to return (Solr `fl`). Keep it
                    short: a full HAL document is large and every field lands in the
                    model's context.

            max_results: Documents to return, 0–100. Use 0 with `facet_fields` to
                         get counts only, with no records at all.

            start: Offset for paging (Solr `start`).

            sort: Sort clause, e.g. "publicationDateY_i desc" or "submittedDate_tdate desc".
                  Only sortable fields work — see the suffix table above.

            facet_fields: Fields to facet on, e.g. ["docType_s"] or
                          ["publicationDateY_i"] for a year histogram.

            facet_mincount: Drop facet values below this count (default 1).

            facet_limit: Max values per facet field, capped at 500. Use -1 for every
                         value (a year histogram needs it).

            facet_sort: "count" (most frequent first) or "index"
                        (alphabetical/chronological — what a year histogram wants).

            facet_prefix: Keep only facet values starting with this prefix, e.g.
                          "81173_" on structHasAuthIdHal_fs to list the authors
                          affiliated with structure 81173.

            facet_pivot: Comma-separated field chains for pivot (nested) facets,
                         e.g. ["docType_s,publicationDateY_i"] for types by year, or
                         ["title_s,docType_s,halId_s"] with facet_mincount=2 to spot
                         duplicate deposits.

            group_field: Collapse results by this field (Solr grouping), e.g.
                         "docType_s". The grouped payload is returned verbatim
                         under `grouped`.

            group_limit: Documents kept per group (default 1).

        Returns:
            {
              "source": "hal", "command": "search_hal",
              "total_found": int,          # matching documents in scope
              "returned":    int,
              "error":       str | null,
              "query_used":  str,
              "filters_used": [str],
              "scope": {"type": "collection"|"portal"|"global", "value": str|null},
              "results": [
                {
                  "source": "hal", "id": str|null, "hal_id": str|null,
                  "title": str|null, "authors": [str], "abstract": str|null,
                  "doi": str|null, "pdf_url": str|null, "url": str|null,
                  "year": int|null, "date": str|null, "doc_type": str|null,
                  "journal": str|null,
                  "raw": {...}            # the HAL document, untouched
                }, ...
              ],
              "facets": {                 # one entry per requested facet field,
                "docType_s": [            # empty array = asked, nothing matched
                  {"value": "ART", "count": 412}, ...
                ]
              },
              "facets_raw": {...},        # only when facets were requested
              "facet_pivot": {...},       # only when facet_pivot was requested
              "grouped": {...}            # only when group_field was requested
            }
        """
        trace = TRACE_DEFAULT
        filters = filters or []
        facet_fields = facet_fields or []
        facet_pivot = facet_pivot or []

        rows = max(0, min(int(max_results), MAX_ROWS))
        f_limit = int(facet_limit)
        if f_limit >= 0:
            f_limit = min(f_limit, MAX_FACET_LIMIT)

        scope_url, scope = _scope_url(collection, portal)

        fl = ",".join(p.strip() for p in fields.split(",") if p.strip()) or "halId_s,title_s,uri_s"

        params: list[tuple[str, str]] = [("q", query)]
        params += [("fq", f) for f in filters]
        params += [("fl", fl), ("rows", str(rows)), ("start", str(max(0, int(start))))]
        if sort:
            params.append(("sort", sort))

        if facet_fields or facet_pivot:
            params.append(("facet", "true"))
            params += [("facet.field", ff) for ff in facet_fields]
            params += [("facet.pivot", fp) for fp in facet_pivot]
            params.append(("facet.mincount", str(facet_mincount)))
            params.append(("facet.limit", str(f_limit)))
            if facet_sort:
                params.append(("facet.sort", facet_sort))
            if facet_prefix:
                params.append(("facet.prefix", facet_prefix))

        if group_field:
            params.append(("group", "true"))
            params.append(("group.field", group_field))
            params.append(("group.limit", str(group_limit)))

        params.append(("wt", "json"))
        url = scope_url + "?" + urllib.parse.urlencode(params, doseq=True)

        extra: dict = {
            "query_used": query,
            "filters_used": filters,
            "scope": scope,
            # One bucket list per requested facet field, always present — an empty
            # array means "asked, nothing matched", not the same thing as "not asked".
            "facets": {ff: [] for ff in facet_fields},
        }

        try:
            obj, tevents = _get_json(url, trace=trace)
        except RuntimeError as e:
            return _envelope("search_hal", error=str(e), source_url=url, **extra)

        resp = obj.get("response") or {}
        docs = resp.get("docs") or []
        records = [_format_doc(d) for d in docs]

        if "facet_counts" in obj:
            facet_counts = obj.get("facet_counts") or {}
            extra["facets"].update(_format_facets(facet_counts))
            extra["facets_raw"] = facet_counts
            pivots = facet_counts.get("facet_pivot")
            if pivots:
                extra["facet_pivot"] = pivots
        if "grouped" in obj:
            extra["grouped"] = obj.get("grouped")

        out = _envelope(
            "search_hal", records,
            total_found=int(resp.get("numFound", 0)),
            **extra,
        )
        if trace:
            out["trace"] = tevents
        return out


    # ── Tool 2 : portals ──────────────────────────────────────────────────────────

    @mcp.tool
    def list_portals(contains: str | None = None,
                     include_deprecated: bool = False,
                     max_results: int = 0) -> dict:
        """
        List HAL portals (instances), i.e. the lowercase codes `search_hal` accepts
        as `portal`.

        A portal is an institutional or thematic view of HAL — `tel` for theses,
        `uvsq`, `inria`, `univ-lille`… — and scoping a search to one is usually the
        difference between a usable answer and three million documents.

        `/ref/instance/` ignores every query parameter and always answers with the
        whole list, so the filtering happens in this server rather than upstream.
        That is why there is a dedicated tool instead of a `lookup_reference` value:
        the reference behaves differently from all the others.

        Args:
            contains: Case-insensitive substring matched literally against the
                      portal code and its French name. Accents are **not** folded:
                      the theses portal is `tel` / "TEL - Thèses en ligne", so
                      "thèses" matches it and "these" does not. When in doubt, call
                      with no filter and scan the codes.

            include_deprecated: Also return portals flagged deprecated. Off by
                                default — a deprecated portal still answers, but its
                                content is frozen.

            max_results: Truncate the list. 0 (default) returns every match.

        Returns:
            {
              "source": "hal", "command": "list_portals",
              "total_found": int,        # matches before truncation
              "returned":    int,
              "error":       str | null,
              "results": [
                {
                  "source": "hal", "ref": "instance",
                  "id":    str|null,     # docid
                  "label": str|null,     # human-readable portal name
                  "code":  str|null,     # what to pass as `portal`
                  "url":   str|null,
                  "raw":   {...}
                }, ...
              ]
            }
        """
        trace = TRACE_DEFAULT
        url = REF_BASE_URL + "instance/?wt=json"

        try:
            obj, tevents = _get_json(url, trace=trace)
        except RuntimeError as e:
            return _envelope("list_portals", error=str(e), total_found=None, source_url=url)

        docs = (obj.get("response") or {}).get("docs") or []
        needle = contains.lower() if contains else None

        kept: list[dict] = []
        for d in docs:
            # `deprecated` comes back as the string "true"/"false", not a bool.
            if not include_deprecated and str(d.get("deprecated", "")).lower() == "true":
                continue
            if needle:
                haystack = f"{d.get('code', '')} {d.get('name', '')}".lower()
                if needle not in haystack:
                    continue
            kept.append(_format_ref_doc("instance", d))

        total = len(kept)
        if max_results and max_results > 0:
            kept = kept[:max_results]

        out = _envelope("list_portals", kept, total_found=total, query_used=contains)
        if trace:
            out["trace"] = tevents
        return out


    # ── Tool 3 : references ───────────────────────────────────────────────────────

    @mcp.tool
    def lookup_reference(
        reference: str,
        query: str = "*:*",
        filters: list[str] | None = None,
        fields: str = "*",
        max_results: int = 15,
        start: int = 0,
        sort: str | None = None,
    ) -> dict:
        """
        Query an AureHAL reference — the authority files behind HAL deposits.

        This is how an ambiguous name becomes the identifier that filters a search:
        a laboratory acronym becomes a `structId_i`, a journal title becomes a
        `journalId_i`, an ANR acronym becomes an `anrProjectReference_s`. Resolve
        first, then filter — a free-text affiliation search matches the string as
        typed by each depositor, an identifier matches the entity.

        Available references (`reference`):
          structure        laboratories, institutions, teams, departments
          author           author forms, with their idHAL and external identifiers
          journal          journals, with ISSN and journal id
          anrproject       ANR-funded projects
          europeanproject  European (FP7 / H2020 / Horizon Europe) projects
          domain           HAL scientific domains

        Portals live in their own reference and behave differently — use
        `list_portals`. Collections have no reference at all: facet a search on
        `collCodeName_fs` to enumerate them.

        Worked patterns:
          reference="structure", query="acronym_t:CRIStAL", filters=["valid_s:VALID"]
              → docid 410272, then search_hal(query="structId_i:410272")
          reference="structure", query="parentDocid_i:300297"
              → every sub-structure of an institution
          reference="author", query="structureId_i:81173",
              fields="docid,label_s,idHal_s,*_id"
              → author forms attached to a structure
          reference="journal", query="title_t:scientometrics"
              → journal id and ISSN

        Note that the AuréHAL entries are *declarations*, not deduplicated truth:
        filter on `valid_s:VALID` to skip the forms flagged as incorrect or merged,
        and expect several entries for one real-world entity.

        Args:
            reference: One of structure, author, journal, anrproject,
                       europeanproject, domain.

            query: Solr query string. Defaults to "*:*". The searchable fields
                   differ per reference — `acronym_t`, `text`, `name_t`,
                   `parentDocid_i`, `structureId_i` are the common ones.

            filters: Solr filter queries, e.g. ["valid_s:VALID"].

            fields: Comma-separated fields to return; "*" (default) returns the
                    whole entry, which is usually what you want here because the
                    useful field varies by reference.

            max_results: Entries to return, 0–100. HAL itself defaults to 30 when
                         the parameter is absent — this tool always sends one.

            start: Offset for paging.

            sort: Sort clause, e.g. "docid asc".

        Returns:
            {
              "source": "hal", "command": "lookup_reference",
              "total_found": int | null,
              "returned":    int,
              "error":       str | null,
              "reference":   str,
              "query_used":  str,
              "filters_used": [str],
              "results": [
                {
                  "source": "hal", "ref": str,
                  "id":      str|null,   # docid — the value to reuse as a filter
                  "label":   str|null,
                  "code":    str|null,
                  "acronym": str|null,
                  "url":     str|null,
                  "raw":     {...}       # the reference entry, untouched
                }, ...
              ]
            }
        """
        trace = TRACE_DEFAULT
        filters = filters or []

        if reference not in REF_ENDPOINTS:
            return _envelope(
                "lookup_reference",
                total_found=None,
                error=(f"Unknown reference {reference!r}. Available: "
                       f"{', '.join(REF_ENDPOINTS)}. Portals: use list_portals."),
                reference=reference,
            )

        rows = max(0, min(int(max_results), MAX_ROWS))

        params: list[tuple[str, str]] = [("q", query)]
        params += [("fq", f) for f in filters]
        params += [("fl", fields), ("rows", str(rows)), ("start", str(max(0, int(start))))]
        if sort:
            params.append(("sort", sort))
        params.append(("wt", "json"))

        url = REF_BASE_URL + f"{reference}/?" + urllib.parse.urlencode(params, doseq=True)

        try:
            obj, tevents = _get_json(url, trace=trace)
        except RuntimeError as e:
            return _envelope("lookup_reference", error=str(e), total_found=None,
                             reference=reference, query_used=query,
                             filters_used=filters, source_url=url)

        resp = obj.get("response") or {}
        docs = resp.get("docs") or []
        num_found = resp.get("numFound")

        out = _envelope(
            "lookup_reference",
            [_format_ref_doc(reference, d) for d in docs],
            total_found=int(num_found) if num_found is not None else None,
            reference=reference,
            query_used=query,
            filters_used=filters,
        )
        if trace:
            out["trace"] = tevents
        return out


    # ══════════════════════════════════════════════════════════════════════════════
    # SECTION: entrypoint
    # ══════════════════════════════════════════════════════════════════════════════

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

        uvx modal run mcp/hal/modal/mcp_server_stateless.py::test_tool

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
