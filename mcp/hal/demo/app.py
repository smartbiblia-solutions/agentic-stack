#!/usr/bin/env python3
"""
Standalone Gradio demo of the hal MCP server, deployable as a Hugging Face Space.

Local run:
    uv run --with 'gradio[mcp]>=6,<7' --with httpx app.py

Environment:
    GRADIO_SERVER_NAME   bind address (default 0.0.0.0)
    GRADIO_SERVER_PORT   port (default 7860)
    GRADIO_MCP_SERVER    "false" disables the demo MCP endpoint (default true)

`search_hal`, `list_portals` and `lookup_reference` are a hand-kept copy of the
canonical `mcp_server.py` tools — same names, same argument names and types, same
response shape. Change one, change the other. The only narrowing is `max_results`,
capped at 25 instead of 100.
"""

from __future__ import annotations

import os
import urllib.parse
from typing import Any

import gradio as gr
import httpx

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_URL = "https://api.archives-ouvertes.fr/search/"
REF_BASE_URL = "https://api.archives-ouvertes.fr/ref/"

# A Space has no command line: connector policy is constant here.
REQUEST_TIMEOUT = 20.0

# Clamped harder than the canonical server (100): the CCSD API is a shared
# public endpoint and every visitor's click is attributed to this Space's host.
MAX_RESULTS = 25
MAX_FACET_LIMIT = 200

# AuréHAL references `lookup_reference` accepts. `instance` is deliberately
# absent: it ignores q and rows and always returns the whole list of portals, so
# `list_portals` filters it client-side instead.
REF_ENDPOINTS = (
    "structure",
    "author",
    "journal",
    "anrproject",
    "europeanproject",
    "domain",
)

# One module-level pooled client for the process.
HTTP = httpx.Client(
    timeout=REQUEST_TIMEOUT,
    follow_redirects=True,
    headers={"User-Agent": "smartbiblia-hal-demo/0.1"},
)


def _get_json(url: str, sink: dict | None = None) -> tuple[dict | None, str | None]:
    """
    GET returning (json, error). Never raises — the demo answers with data.

    `sink`, when given, receives the exact URL fetched plus what came back. HAL
    needs no credential, so the URL is shown in clear: paste it in a browser and
    you are comparing like for like. It is never part of the tool payload, which
    stays canonical.
    """
    if sink is not None:
        sink["request_url"] = url
    try:
        resp = HTTP.get(url)
        if sink is not None:
            sink["http_status"] = resp.status_code
        if resp.status_code >= 400:
            # HAL answers a malformed Solr query with 400/500 and an HTML or
            # {"error": …} body. Carry the first line of it: "HTTP 500" alone
            # says nothing, the body usually names the offending field.
            if sink is not None:
                sink["response_body"] = resp.text[:1000]
            detail = " ".join(resp.text.split())[:300]
            return None, (
                f"HAL API returned HTTP {resp.status_code}"
                + (f" — {detail}" if detail else "")
            )
        data = resp.json()
        if sink is not None and isinstance(data, dict):
            # What came back, so an empty result set can be told apart from a
            # response this code failed to read.
            sink["response_keys"] = sorted(data)
            response = data.get("response") or {}
            if isinstance(response, dict):
                sink["num_found"] = response.get("numFound")
                sink["docs_count"] = len(response.get("docs") or [])
        return data, None
    except httpx.TimeoutException:
        return None, f"HAL API timed out after {REQUEST_TIMEOUT:g}s"
    except ValueError as exc:
        return None, f"malformed HAL response: {exc}"
    except Exception as exc:  # noqa: BLE001 - never crash the Space
        return None, f"HAL API unreachable: {exc}"


# ── Normalization ─────────────────────────────────────────────────────────────

def _pick_first(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, list):
        return str(v[0]) if v else None
    return str(v)


def _format_doc(doc: dict) -> dict:
    hal_id = _pick_first(doc.get("halId_s"))
    uri = _pick_first(doc.get("uri_s"))

    authors = doc.get("authFullName_s") or doc.get("authFullName_t")
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
    """Unpack Solr's flat `[value, count, …]` arrays into buckets."""
    out: dict[str, list[dict]] = {}
    for field, flat in ((facet_counts or {}).get("facet_fields") or {}).items():
        buckets: list[dict] = []
        if isinstance(flat, list):
            for i in range(0, len(flat) - 1, 2):
                buckets.append({"value": flat[i], "count": flat[i + 1]})
        out[field] = buckets
    return out


# ── Core operations (shared by the UI and the MCP tools) ──────────────────────
#
# The tools below are thin wrappers: the logic lives here so the UI can pass a
# `request_sink` and show the URL it sent, without that argument ever appearing
# in the MCP input schema.


def _do_search(
    query: str,
    collection: str | None,
    portal: str | None,
    filters: list[str] | None,
    fields: str,
    max_results: int,
    facet_fields: list[str] | None,
    facet_limit: int,
    sort: str | None,
    request_sink: dict | None = None,
) -> dict:
    filters = filters or []
    facet_fields = facet_fields or []

    if collection:
        code = collection.strip("/")
        scope_url, scope = urllib.parse.urljoin(BASE_URL, f"{code}/"), {"type": "collection", "value": code}
    elif portal:
        code = portal.strip("/")
        scope_url, scope = urllib.parse.urljoin(BASE_URL, f"{code}/"), {"type": "portal", "value": code}
    else:
        scope_url, scope = BASE_URL, {"type": "global", "value": None}

    out: dict = {
        "source": "hal", "command": "search_hal",
        "total_found": 0, "returned": 0, "results": [],
        "facets": {ff: [] for ff in facet_fields},
        "scope": scope, "query_used": query, "filters_used": filters,
        "error": None,
    }

    rows = max(0, min(int(max_results or 0), MAX_RESULTS))
    f_limit = int(facet_limit)
    if f_limit >= 0:
        f_limit = min(f_limit, MAX_FACET_LIMIT)

    fl = ",".join(p.strip() for p in (fields or "").split(",") if p.strip()) or "halId_s,title_s,uri_s"

    params: list[tuple[str, str]] = [("q", query or "*:*")]
    params += [("fq", f) for f in filters]
    params += [("fl", fl), ("rows", str(rows)), ("start", "0")]
    if sort:
        params.append(("sort", sort))
    if facet_fields:
        params.append(("facet", "true"))
        params += [("facet.field", ff) for ff in facet_fields]
        params.append(("facet.limit", str(f_limit)))
        params.append(("facet.mincount", "1"))
    params.append(("wt", "json"))

    if request_sink is not None:
        request_sink["scope"] = scope
        # A list of pairs, not a dict: `fq` and `facet.field` legitimately repeat.
        request_sink["params"] = [list(p) for p in params]

    obj, error = _get_json(scope_url + "?" + urllib.parse.urlencode(params, doseq=True), request_sink)
    if error:
        out["error"] = error
        return out

    resp = obj.get("response") or {}
    docs = resp.get("docs") or []
    out["total_found"] = int(resp.get("numFound", 0))
    out["results"] = [_format_doc(d) for d in docs]
    out["returned"] = len(out["results"])
    if "facet_counts" in obj:
        out["facets"].update(_format_facets(obj.get("facet_counts")))
    return out


def _do_portals(contains: str | None,
                include_deprecated: bool,
                max_results: int,
                request_sink: dict | None = None) -> dict:
    out: dict = {"source": "hal", "command": "list_portals",
                 "total_found": None, "returned": 0, "results": [],
                 "query_used": contains, "error": None}

    # /ref/instance/ ignores q and rows and always returns the whole list, so
    # the filtering happens here rather than upstream.
    obj, error = _get_json(REF_BASE_URL + "instance/?wt=json", request_sink)
    if error:
        out["error"] = error
        return out

    docs = (obj.get("response") or {}).get("docs") or []
    needle = contains.lower() if contains else None

    kept: list[dict] = []
    for d in docs:
        # `deprecated` comes back as the string "true"/"false", not a bool.
        if not include_deprecated and str(d.get("deprecated", "")).lower() == "true":
            continue
        if needle and needle not in f"{d.get('code', '')} {d.get('name', '')}".lower():
            continue
        kept.append(_format_ref_doc("instance", d))

    out["total_found"] = len(kept)
    if max_results and max_results > 0:
        kept = kept[:max_results]
    out["results"] = kept
    out["returned"] = len(kept)
    return out


def _do_reference(
    reference: str,
    query: str,
    filters: list[str] | None,
    fields: str,
    max_results: int,
    start: int,
    sort: str | None,
    request_sink: dict | None = None,
) -> dict:
    filters = filters or []
    out: dict = {"source": "hal", "command": "lookup_reference",
                 "total_found": None, "returned": 0, "results": [],
                 "reference": reference, "query_used": query,
                 "filters_used": filters, "error": None}

    if reference not in REF_ENDPOINTS:
        out["error"] = (f"Unknown reference {reference!r}. Available: "
                        f"{', '.join(REF_ENDPOINTS)}. Portals: use list_portals.")
        return out

    rows = max(0, min(int(max_results or 0), MAX_RESULTS))

    params: list[tuple[str, str]] = [("q", query or "*:*")]
    params += [("fq", f) for f in filters]
    params += [("fl", fields or "*"), ("rows", str(rows)),
               ("start", str(max(0, int(start or 0))))]
    if sort:
        params.append(("sort", sort))
    params.append(("wt", "json"))

    if request_sink is not None:
        request_sink["reference"] = reference
        request_sink["params"] = [list(p) for p in params]

    url = REF_BASE_URL + f"{reference}/?" + urllib.parse.urlencode(params, doseq=True)
    obj, error = _get_json(url, request_sink)
    if error:
        out["error"] = error
        return out

    resp = obj.get("response") or {}
    docs = resp.get("docs") or []
    num_found = resp.get("numFound")
    out["total_found"] = int(num_found) if num_found is not None else None
    out["results"] = [_format_ref_doc(reference, d) for d in docs]
    out["returned"] = len(out["results"])
    return out


# ── MCP tools (hand-kept copies of the canonical ones) ────────────────────────

def search_hal(
    query: str = "*:*",
    collection: str | None = None,
    portal: str | None = None,
    filters: list[str] | None = None,
    fields: str = "halId_s,title_s,authFullName_s,doiId_s,publicationDateY_i,docType_s,uri_s",
    max_results: int = 10,
    facet_fields: list[str] | None = None,
    facet_limit: int = 20,
    sort: str | None = None,
) -> dict:
    """
    Search HAL, the French national open repository, through the CCSD Solr API.

    Args:
        query: Solr query, e.g. 'text:sobriété énergétique', 'title_t:"apprentissage profond"', 'doiId_id:10.1145/3459637'. Default '*:*' returns everything in scope. The suffix decides what a field does: search on _t, return/facet/sort on _s and _i, match identifiers on _id.
        collection: HAL collection code, UPPERCASE, e.g. 'FRANCE-GRILLES'. Wins over portal.
        portal: HAL portal (instance) code, lowercase, e.g. 'tel' for theses. See list_portals.
        filters: Solr filter queries, e.g. ['publicationDateY_i:[2020 TO 2024]', 'docType_s:ART'].
        fields: Comma-separated fields to return (Solr fl). Keep it short — a full HAL document is large.
        max_results: Documents to return, 0-25 on this demo endpoint. Use 0 with facet_fields for counts only.
        facet_fields: Fields to facet on, e.g. ['docType_s'] or ['publicationDateY_i'] for a year histogram.
        facet_limit: Max values per facet field, up to 200. Use -1 for every value.
        sort: Sort clause, e.g. 'publicationDateY_i desc'. Only sortable fields work.

    Returns:
        {"source": "hal", "command": "search_hal", "total_found": int, "returned": int, "results": [{"source": "hal", "id": str, "hal_id": str, "title": str, "authors": [str], "abstract": str | null, "doi": str | null, "pdf_url": str | null, "url": str, "year": int | null, "date": str | null, "doc_type": str | null, "journal": str | null, "raw": {}}], "facets": {"<field>": [{"value": str, "count": int}]}, "scope": {"type": str, "value": str | null}, "query_used": str, "filters_used": [str], "error": str | null}
    """
    return _do_search(query, collection, portal, filters, fields,
                      max_results, facet_fields, facet_limit, sort)


def list_portals(contains: str | None = None,
                 include_deprecated: bool = False,
                 max_results: int = 0) -> dict:
    """
    List HAL portals (instances), the lowercase codes search_hal accepts as `portal`.

    Args:
        contains: Case-insensitive substring matched literally against the portal code and its French name. Accents are not folded: 'thèses' matches 'TEL - Thèses en ligne', 'these' does not. Leave empty to list every portal.
        include_deprecated: Also return portals flagged deprecated. Off by default.
        max_results: Truncate the list. 0 returns every match.

    Returns:
        {"source": "hal", "command": "list_portals", "total_found": int, "returned": int, "results": [{"source": "hal", "ref": "instance", "id": str | null, "label": str | null, "code": str | null, "url": str | null, "raw": {}}], "error": str | null}
    """
    return _do_portals(contains, include_deprecated, max_results)


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
    Query an AuréHAL reference — the authority files behind HAL deposits.

    This is how an ambiguous name becomes the identifier that filters a search: a
    laboratory acronym becomes a `structId_i`, a journal title becomes a
    `journalId_i`, an ANR acronym becomes an `anrProjectReference_s`. Resolve
    first, then filter — a free-text affiliation search matches the string as
    typed by each depositor, an identifier matches the entity.

    Available references: structure (laboratories, institutions, teams),
    author (author forms with their idHAL), journal (with ISSN and journal id),
    anrproject, europeanproject, domain. Portals live in their own reference and
    behave differently — use list_portals. Collections have no reference at all:
    facet a search on `collCodeName_fs` to enumerate them.

    Worked patterns:
      reference="structure", query="acronym_t:CRIStAL", filters=["valid_s:VALID"]
          → docid 410272, then search_hal(query="structId_i:410272")
      reference="structure", query="parentDocid_i:300297"
          → every sub-structure of an institution
      reference="journal", query="title_t:scientometrics"
          → journal id and ISSN

    AuréHAL entries are *declarations*, not deduplicated truth: filter on
    `valid_s:VALID` to skip forms flagged incorrect or merged, and expect several
    entries for one real-world entity.

    Args:
        reference: One of structure, author, journal, anrproject, europeanproject, domain.
        query: Solr query string. The searchable fields differ per reference — `acronym_t`, `text`, `name_t`, `parentDocid_i`, `structureId_i` are the common ones.
        filters: Solr filter queries, e.g. ["valid_s:VALID"].
        fields: Comma-separated fields to return; "*" returns the whole entry, which is usually what you want here because the useful field varies by reference.
        max_results: Entries to return, 0-25 on this demo endpoint.
        start: Offset for paging.
        sort: Sort clause, e.g. "docid asc".

    Returns:
        {"source": "hal", "command": "lookup_reference", "total_found": int | null, "returned": int, "reference": str, "query_used": str, "filters_used": [str], "results": [{"source": "hal", "ref": str, "id": str | null, "label": str | null, "code": str | null, "acronym": str | null, "url": str | null, "raw": {}}], "error": str | null}
    """
    return _do_reference(reference, query, filters, fields, max_results, start, sort)


# ── Presentation ──────────────────────────────────────────────────────────────

def _render_records(payload: dict) -> str:
    if payload.get("error"):
        return (f"⚠️ **{payload['error']}**\n\n"
                "_Open the debug panel below for the exact URL sent to HAL._")
    results = payload.get("results") or []
    facets = {k: v for k, v in (payload.get("facets") or {}).items() if v}

    lines = [f"**{payload.get('returned', 0)} / {payload.get('total_found', '?')} dépôts**", ""]

    if results:
        lines += ["| HAL ID | Année | Type | Titre | Auteurs |", "|---|---|---|---|---|"]
        for r in results:
            authors = ", ".join((r.get("authors") or [])[:3]) or "—"
            hal_id = r.get("hal_id") or ""
            url = r.get("url") or f"https://hal.science/{hal_id}"
            lines.append(
                "| [{hid}]({url}) | {year} | {dt} | {title} | {authors} |".format(
                    hid=hal_id or "—", url=url,
                    year=r.get("year") or "—",
                    dt=r.get("doc_type") or "—",
                    title=(r.get("title") or "Sans titre").replace("|", "\\|"),
                    authors=authors.replace("|", "\\|"),
                )
            )
    elif not facets:
        return "_Aucun dépôt / no deposit matched._"

    for field, buckets in facets.items():
        lines += ["", f"**Facette `{field}`**", "", "| Valeur | Dépôts |", "|---|---|"]
        for b in buckets[:50]:
            lines.append(f"| {b['value']} | {b['count']} |")

    return "\n".join(lines)


def _render_portals(payload: dict) -> str:
    if payload.get("error"):
        return (f"⚠️ **{payload['error']}**\n\n"
                "_Open the debug panel below for the exact URL sent to HAL._")
    results = payload.get("results") or []
    if not results:
        return "_Aucun portail / no portal matched._"
    lines = [
        f"**{payload.get('returned', 0)} / {payload.get('total_found', '?')} portails**",
        "",
        "| Code | Nom | Site |",
        "|---|---|---|",
    ]
    for r in results:
        url = r.get("url")
        lines.append(
            "| `{code}` | {label} | {site} |".format(
                code=r.get("code") or "—",
                label=(r.get("label") or "—").replace("|", "\\|"),
                site=f"[{url}]({url})" if url else "—",
            )
        )
    return "\n".join(lines)


def _run_search(query, scope_kind, scope_code, max_results, doc_type, year_from, year_to, facet_field):
    filters: list[str] = []
    if doc_type:
        filters.append(f"docType_s:{doc_type}")
    if year_from and year_to:
        filters.append(f"publicationDateY_i:[{int(year_from)} TO {int(year_to)}]")
    elif year_from:
        filters.append(f"publicationDateY_i:[{int(year_from)} TO *]")
    elif year_to:
        filters.append(f"publicationDateY_i:[* TO {int(year_to)}]")

    code = (scope_code or "").strip() or None
    sent: dict = {}
    payload = _do_search(
        query=query or "*:*",
        collection=code if scope_kind == "collection" else None,
        portal=code if scope_kind == "portal" else None,
        filters=filters,
        fields="halId_s,title_s,authFullName_s,doiId_s,publicationDateY_i,docType_s,uri_s",
        max_results=int(max_results or 0),
        facet_fields=[facet_field] if facet_field else None,
        facet_limit=-1 if facet_field == "publicationDateY_i" else 20,
        sort=None,
        request_sink=sent,
    )
    # Rendered rather than raised as gr.Error: a raise aborts the outputs, and
    # the debug panel is most needed exactly when the call went wrong.
    return _render_records(payload), payload, sent


def _render_refs(payload: dict) -> str:
    if payload.get("error"):
        return (f"⚠️ **{payload['error']}**\n\n"
                "_Open the debug panel below for the exact URL sent to HAL._")
    results = payload.get("results") or []
    if not results:
        return "_Aucune entrée / no reference entry matched._"
    lines = [
        f"**{payload.get('returned', 0)} / {payload.get('total_found', '?')} entrées "
        f"`{payload.get('reference')}`**",
        "",
        "| docid | Libellé | Acronyme | Site |",
        "|---|---|---|---|",
    ]
    for r in results:
        url = r.get("url")
        lines.append(
            "| `{docid}` | {label} | {acronym} | {site} |".format(
                docid=r.get("id") or "—",
                label=(r.get("label") or "—").replace("|", "\\|"),
                acronym=(r.get("acronym") or r.get("code") or "—").replace("|", "\\|"),
                site=f"[lien]({url})" if url else "—",
            )
        )
    lines += ["", "_Le `docid` est la valeur à réutiliser comme filtre : "
                  "`structId_i:<docid>`, `journalId_i:<docid>`…_"]
    return "\n".join(lines)


def _run_portals(contains, include_deprecated):
    sent: dict = {}
    payload = _do_portals(contains or None, bool(include_deprecated), 0, request_sink=sent)
    return _render_portals(payload), payload, sent


def _run_reference(reference, query, valid_only, max_results):
    sent: dict = {}
    payload = _do_reference(
        reference=reference,
        query=(query or "").strip() or "*:*",
        filters=["valid_s:VALID"] if valid_only else [],
        fields="*",
        max_results=int(max_results or 0),
        start=0,
        sort=None,
        request_sink=sent,
    )
    return _render_refs(payload), payload, sent


# ── UI ────────────────────────────────────────────────────────────────────────

with gr.Blocks(title="HAL MCP demo") as demo:
    gr.Markdown(
        "# HAL MCP demo\n"
        "Standalone demo of the [`hal`](https://github.com/smartbiblia-solutions/agentic-stack/tree/main/mcp/hal) "
        "MCP server. HAL is the french open repository maintained by the CCSD.\n\n"
    )

    with gr.Tab("Recherche"):
        query = gr.Textbox(label="Requête Solr", placeholder='text:sobriété énergétique')
        with gr.Row():
            scope_kind = gr.Radio(
                label="Périmètre",
                choices=[("Tout HAL", ""), ("Collection (MAJUSCULES)", "collection"),
                         ("Portail (minuscules)", "portal")],
                value="",
            )
            scope_code = gr.Textbox(label="Code du périmètre", placeholder="tel  ·  FRANCE-GRILLES")
        with gr.Row():
            max_results = gr.Slider(0, MAX_RESULTS, value=10, step=1,
                                    label="Résultats (0 = facettes seules)")
            doc_type = gr.Dropdown(
                label="Type de document (docType_s)",
                choices=[
                    ("Tous", ""),
                    ("ART — article", "ART"),
                    ("COMM — communication", "COMM"),
                    ("THESE — thèse", "THESE"),
                    ("OUV — ouvrage", "OUV"),
                    ("COUV — chapitre", "COUV"),
                    ("REPORT — rapport", "REPORT"),
                    ("UNDEFINED — preprint", "UNDEFINED"),
                    ("SOFTWARE — logiciel", "SOFTWARE"),
                ],
                value="",
            )
        with gr.Row():
            year_from = gr.Number(label="Année min.", value=None, precision=0)
            year_to = gr.Number(label="Année max.", value=None, precision=0)
            facet_field = gr.Dropdown(
                label="Facette",
                choices=[("Aucune", ""), ("Type de document", "docType_s"),
                         ("Année de publication", "publicationDateY_i"),
                         ("Collection", "collCodeName_fs"), ("Domaine", "domain_s"),
                         ("Revue", "journalTitle_s")],
                value="",
            )
        search_btn = gr.Button("Rechercher", variant="primary")
        search_out = gr.Markdown()
        search_raw = gr.JSON(label="Raw tool output")
        with gr.Accordion("🔍 Debug — requête envoyée et réponse reçue / request sent and response received", open=False):
            search_req = gr.JSON()

        gr.Examples(
            examples=[
                ["title_t:\"apprentissage profond\"", "portal", "tel", 10, "", None, None, ""],
                ["*:*", "collection", "FRANCE-GRILLES", 0, "", None, None, "publicationDateY_i"],
                ["text:sobriété énergétique", "", "", 10, "ART", 2020, 2024, ""],
            ],
            inputs=[query, scope_kind, scope_code, max_results, doc_type,
                    year_from, year_to, facet_field],
            label="Une thèse cherchée dans un portail · un histogramme par année "
                  "sur une collection · un article filtré par type et par période",
        )
        search_btn.click(
            _run_search,
            inputs=[query, scope_kind, scope_code, max_results, doc_type,
                    year_from, year_to, facet_field],
            outputs=[search_out, search_raw, search_req],
            api_name=False,
        )

    with gr.Tab("Portails"):
        contains = gr.Textbox(label="Filtre (code ou nom)", placeholder="univ")
        include_deprecated = gr.Checkbox(label="Inclure les portails obsolètes", value=False)
        portals_btn = gr.Button("Lister", variant="primary")
        portals_out = gr.Markdown()
        portals_raw = gr.JSON(label="Raw tool output")
        with gr.Accordion("🔍 Debug — requête envoyée et réponse reçue / request sent and response received", open=False):
            portals_req = gr.JSON()

        gr.Examples(
            examples=[["thèses", False], ["univ-lille", False], ["", True]],
            inputs=[contains, include_deprecated],
            label="Un filtre accentué (les accents ne sont pas repliés) · un code "
                  "de portail · la liste complète, obsolètes compris",
        )
        portals_btn.click(
            _run_portals, inputs=[contains, include_deprecated],
            outputs=[portals_out, portals_raw, portals_req], api_name=False,
        )

    with gr.Tab("Référentiels"):
        gr.Markdown(
            "Les référentiels AuréHAL : les fichiers d'autorité derrière les "
            "dépôts. On y résout un acronyme de laboratoire, un titre de revue "
            "ou un projet ANR en **docid**, que l'on réinjecte ensuite comme "
            "filtre dans la recherche (`structId_i:410272`, "
            "`journalId_i:18835`…).\n\n"
            "Les entrées sont des *déclarations*, pas une vérité dédoublonnée : "
            "cochez `valid_s:VALID` pour écarter les formes signalées "
            "incorrectes ou fusionnées. Les portails ont leur propre onglet ; "
            "les collections n'ont pas de référentiel du tout (facetter sur "
            "`collCodeName_fs`)."
        )
        ref_kind = gr.Dropdown(list(REF_ENDPOINTS), value="structure",
                               label="Référentiel")
        ref_query = gr.Textbox(label="Requête Solr", value="*:*",
                               placeholder="acronym_t:CRIStAL")
        with gr.Row():
            ref_valid = gr.Checkbox(label="Seulement les formes valides "
                                          "(valid_s:VALID)", value=False)
            ref_max = gr.Slider(0, MAX_RESULTS, value=15, step=1, label="Résultats")
        ref_btn = gr.Button("Résoudre", variant="primary")
        ref_out = gr.Markdown()
        ref_raw = gr.JSON(label="Raw tool output")
        with gr.Accordion("🔍 Debug — requête envoyée et réponse reçue / request sent and response received", open=False):
            ref_req = gr.JSON()

        gr.Examples(
            examples=[
                ["structure", "acronym_t:CRIStAL", True, 15],
                ["journal", "title_t:scientometrics", False, 15],
                ["anrproject", "text:numérique", False, 15],
                ["domain", "*:*", False, 25],
            ],
            inputs=[ref_kind, ref_query, ref_valid, ref_max],
            label="Un laboratoire par acronyme · une revue par titre · un projet "
                  "ANR en texte libre · l'arbre des domaines",
        )
        ref_btn.click(
            _run_reference, inputs=[ref_kind, ref_query, ref_valid, ref_max],
            outputs=[ref_out, ref_raw, ref_req], api_name=False,
        )

    # The only declared MCP tools. Names match the canonical server's.
    gr.api(search_hal, api_name="search_hal")
    gr.api(list_portals, api_name="list_portals")
    gr.api(lookup_reference, api_name="lookup_reference")


if __name__ == "__main__":
    demo.launch(
        theme=gr.themes.Soft(),  # Gradio 6 moved theme from Blocks() to launch()
        server_name=os.getenv("GRADIO_SERVER_NAME", "0.0.0.0"),
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
        mcp_server=os.getenv("GRADIO_MCP_SERVER", "true").lower() == "true",
    )
