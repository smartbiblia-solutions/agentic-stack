#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ['httpx']
# ///
"""HAL Search API CLI (collection-first).

- Docs: https://api.archives-ouvertes.fr/docs/search
- Endpoint: https://api.archives-ouvertes.fr/search/
- Reference endpoints: https://api.archives-ouvertes.fr/ref/

This CLI is designed for agent/LLM usage:
- strict JSON output on stdout
- retries/backoff for transient HTTP errors
- collection-first scoping (recommended)

The service is public and anonymous: no environment variable, no key. Timeout,
retry count and backoff are constants below — properties of the connector, not
of the installation.

Run:
  uv run skills/search-records-hal/scripts/cli.py search --collection XXX --q 'text:test'
  uv run skills/search-records-hal/scripts/cli.py list-portals --contains these
  uv run skills/search-records-hal/scripts/cli.py lookup-ref --ref structure --q 'text:CRIStAL'

"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple


def _pick_first(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, list):
        return str(v[0]) if v else None
    return str(v)


def normalize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize HAL 'doc' into an OpenAlex-like record shape."""
    hal_id = doc.get("halId_s") or _pick_first(doc.get("halId_s"))
    uri = doc.get("uri_s") or _pick_first(doc.get("uri_s"))

    title = _pick_first(doc.get("title_s")) or _pick_first(doc.get("title_t"))

    # HAL often returns authFullName_s as list
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
    except Exception:
        year = None

    date = _pick_first(doc.get("publicationDate_s")) or _pick_first(doc.get("producedDate_s"))

    doi = doc.get("doiId_s") or _pick_first(doc.get("doiId_s"))

    doc_type = doc.get("docType_s") or _pick_first(doc.get("docType_s"))

    journal = _pick_first(doc.get("journalTitle_s")) or _pick_first(doc.get("journalTitle_t"))

    # best-effort OA url: use fileMain_s or openAccessFile_s if present
    pdf_url = _pick_first(doc.get("fileMain_s")) or _pick_first(doc.get("openAccessFile_s"))

    return {
        "source": "hal",
        "id": hal_id,
        "hal_id": hal_id,
        "title": title,
        "authors": authors_list,
        "abstract": _pick_first(doc.get("abstract_s")) or _pick_first(doc.get("abstract_t")),
        "doi": doi,
        "pdf_url": pdf_url,
        "url": uri,
        "source_url": uri,
        "year": year,
        "date": date,
        "doc_type": doc_type,
        "journal": journal,
        "raw": doc,
    }

def normalize_ref_doc(ref: str, doc: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a HAL *reference* entry (AuréHAL) into a minimal record.

    The reference endpoints do not share the document schema: a structure, an
    author and a journal have almost nothing in common. Only the three identity
    anchors are unified — `id`, `label`, `url` — and the source document is kept
    verbatim under `raw`, because it is where the useful field for the next
    query lives (e.g. `docid` for `structId_i`, `code` for a portal path).
    """
    label = (
        _pick_first(doc.get("label_s"))
        or _pick_first(doc.get("name"))
        or _pick_first(doc.get("fullName_s"))
        or _pick_first(doc.get("title_s"))
        or _pick_first(doc.get("code_s"))
        or _pick_first(doc.get("code"))
    )
    ref_id = _pick_first(doc.get("docid")) or _pick_first(doc.get("id"))
    url = _pick_first(doc.get("url_s")) or _pick_first(doc.get("url"))

    return {
        "source": "hal",
        "ref": ref,
        "id": ref_id,
        "label": label,
        "code": _pick_first(doc.get("code")) or _pick_first(doc.get("code_s")),
        "acronym": _pick_first(doc.get("acronym_s")),
        "url": url,
        "raw": doc,
    }


def normalize_facets(facet_counts: Optional[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Turn Solr's flat `[value, count, value, count, …]` lists into buckets.

    Solr encodes a facet as one alternating array; every consumer has to unpack
    it the same way, so the CLI does it once and publishes
    `{field: [{"value": …, "count": …}]}`. The untouched Solr block stays under
    `facets_raw` for anything this shape would lose (pivots, ranges, queries).
    """
    out: Dict[str, List[Dict[str, Any]]] = {}
    for field, flat in ((facet_counts or {}).get("facet_fields") or {}).items():
        buckets: List[Dict[str, Any]] = []
        if isinstance(flat, list):
            for i in range(0, len(flat) - 1, 2):
                buckets.append({"value": flat[i], "count": flat[i + 1]})
        out[field] = buckets
    return out


import httpx


BASE_URL = "https://api.archives-ouvertes.fr/search/"
REF_BASE_URL = "https://api.archives-ouvertes.fr/ref/"

# AuréHAL reference endpoints that answer with a regular Solr envelope
# (`response.numFound` + `response.docs`) and honour q/fl/rows/start/sort.
# `instance` is deliberately absent: it ignores q and rows and always returns
# the full list of portals, so `list-portals` filters it client-side instead.
REF_ENDPOINTS = (
    "structure",
    "author",
    "journal",
    "anrproject",
    "europeanproject",
    "domain",
)

HTTP_TIMEOUT = 20.0
MAX_RETRIES = 3
BACKOFF_BASE = 1.0
BACKOFF_FACTOR = 2.0
JITTER_MAX = 0.25
RETRIED_STATUS = {429, 500, 502, 503, 504}

# One pooled client for the process: httpx.get() would rebuild the client — and
# replay the TLS handshake — on every call.
HTTP = httpx.Client(
    timeout=HTTP_TIMEOUT,
    follow_redirects=True,
    headers={"User-Agent": "smartbiblia-hal-skill/0.3"},
)


def _sleep_backoff(attempt: int) -> None:
    delay = BACKOFF_BASE * (BACKOFF_FACTOR ** (attempt - 1))
    time.sleep(delay + random.random() * JITTER_MAX)


def http_get_json(url: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Return (json_obj, error). Never raises — the error is data."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = HTTP.get(url)

            if resp.status_code in RETRIED_STATUS and attempt < MAX_RETRIES:
                _sleep_backoff(attempt)
                continue

            if resp.status_code >= 400:
                return None, f"HTTP {resp.status_code} on {url}"

            try:
                return resp.json(), None
            except Exception:
                ctype = resp.headers.get("content-type", "")
                snippet = resp.text[:300]
                return None, f"Non-JSON response (content-type={ctype}). Snippet: {snippet}"

        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt == MAX_RETRIES:
                return None, f"Request failed: {exc}"
            _sleep_backoff(attempt)

    return None, "Request failed (exhausted retries)"


def build_scope_url(collection: Optional[str], portal: Optional[str]) -> Tuple[str, Dict[str, Any]]:
    if collection:
        # Collection codes are case-sensitive and typically uppercase.
        return urllib.parse.urljoin(BASE_URL, f"{collection.strip('/')}/"), {"type": "collection", "value": collection}
    if portal:
        return urllib.parse.urljoin(BASE_URL, f"{portal.strip('/')}/"), {"type": "portal", "value": portal}
    return BASE_URL, {"type": "global", "value": None}


def normalize_fl(fl: str) -> str:
    parts = [p.strip() for p in fl.split(",") if p.strip()]
    return ",".join(parts) if parts else "halId_s,title_s,uri_s"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="hal", add_help=True)
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("search", help="Search HAL via /search/ (Solr)")
    ps.add_argument("--collection", help="HAL collection code (recommended)")
    ps.add_argument("--portal", help="HAL portal instance (alternative to collection)")
    ps.add_argument("--q", default="*:*", help="Solr query string (q=)")
    ps.add_argument("--fq", action="append", default=[], help="Solr filter query (repeatable)")
    ps.add_argument("--fl", default="halId_s,title_s,uri_s", help="Fields list (comma-separated)")
    ps.add_argument("--rows", type=int, default=15)
    ps.add_argument("--start", type=int, default=0)
    ps.add_argument("--sort", default=None)

    ps.add_argument("--facet-field", action="append", default=[], help="Enable facets on field (repeatable)")
    ps.add_argument("--facet-mincount", type=int, default=1)
    ps.add_argument("--facet-limit", type=int, default=20)
    ps.add_argument(
        "--facet-sort",
        choices=["count", "index"],
        default=None,
        help="Facet ordering: count (most frequent first) or index (alphabetical/chronological)",
    )
    ps.add_argument(
        "--facet-prefix",
        default=None,
        help="Keep only facet values starting with this prefix, e.g. '81173_' on structHasAuthIdHal_fs",
    )
    ps.add_argument(
        "--facet-pivot",
        action="append",
        default=[],
        help="Comma-separated field chain for a pivot facet, e.g. 'title_s,docType_s,halId_s' (repeatable)",
    )

    ps.add_argument("--group-field", default=None, help="Enable grouping by field")
    ps.add_argument("--group-limit", type=int, default=1)

    ps.add_argument(
        "--wt",
        default="json",
        choices=["json", "xml", "xml-tei", "bibtex", "endnote", "rss", "atom", "csv"],
    )
    ps.add_argument("--indent", action="store_true")

    pl = sub.add_parser("list-portals", help="List HAL portals (instances) from /ref/instance/")
    pl.add_argument(
        "--contains",
        default=None,
        help="Case-insensitive substring filter on the portal code or name",
    )
    pl.add_argument("--include-deprecated", action="store_true",
                    help="Also return portals flagged deprecated (excluded by default)")
    pl.add_argument("--rows", type=int, default=0, help="Truncate the list; 0 returns every match")

    pr = sub.add_parser("lookup-ref", help="Query an AuréHAL reference endpoint (/ref/<ref>/)")
    pr.add_argument("--ref", required=True, choices=list(REF_ENDPOINTS),
                    help="Reference to query. Use list-portals for the instance reference.")
    pr.add_argument("--q", default="*:*", help="Solr query string (q=)")
    pr.add_argument("--fq", action="append", default=[], help="Solr filter query (repeatable)")
    pr.add_argument("--fl", default="*", help="Fields list (comma-separated); '*' returns the whole entry")
    pr.add_argument("--rows", type=int, default=15)
    pr.add_argument("--start", type=int, default=0)
    pr.add_argument("--sort", default=None)

    return p.parse_args()


def cmd_search(a: argparse.Namespace) -> Dict[str, Any]:
    if a.collection and a.portal:
        # collection wins; keep deterministic behavior
        portal_used = None
    else:
        portal_used = a.portal

    scope_url, scope = build_scope_url(a.collection, portal_used)

    params: List[Tuple[str, str]] = []
    params.append(("q", a.q))

    for f in a.fq:
        params.append(("fq", f))

    params.append(("fl", normalize_fl(a.fl)))
    params.append(("rows", str(a.rows)))
    params.append(("start", str(a.start)))

    if a.sort:
        params.append(("sort", a.sort))

    if a.facet_field or a.facet_pivot:
        params.append(("facet", "true"))
        for ff in a.facet_field:
            params.append(("facet.field", ff))
        for fp in a.facet_pivot:
            params.append(("facet.pivot", fp))
        params.append(("facet.mincount", str(a.facet_mincount)))
        params.append(("facet.limit", str(a.facet_limit)))
        if a.facet_sort:
            params.append(("facet.sort", a.facet_sort))
        if a.facet_prefix:
            params.append(("facet.prefix", a.facet_prefix))

    if a.group_field:
        params.append(("group", "true"))
        params.append(("group.field", a.group_field))
        params.append(("group.limit", str(a.group_limit)))

    params.append(("wt", a.wt))
    if a.indent:
        params.append(("indent", "true"))

    url = scope_url + "?" + urllib.parse.urlencode(params, doseq=True)

    out: Dict[str, Any] = {
        "total_found": 0,
        "returned": 0,
        "results": [],
        "query_used": a.q,
        "filters_used": a.fq,
        "scope": scope,
        "params": {
            "rows": a.rows,
            "start": a.start,
            "sort": a.sort,
            "wt": a.wt,
            "fl": normalize_fl(a.fl),
            "facet_fields": a.facet_field,
            "facet_pivot": a.facet_pivot,
            "group_field": a.group_field,
        },
        # One bucket list per requested facet field, always present — an empty
        # array means "asked, no value matched", which is not the same thing as
        # "not asked".
        "facets": {ff: [] for ff in a.facet_field},
        "error": None,
    }

    if a.wt != "json":
        out["error"] = "wt != json: this CLI currently expects JSON output. Use --wt json for structured output."
        out["source_url"] = url
        return out

    obj, err = http_get_json(url)
    if err:
        out["error"] = err
        out["source_url"] = url
        return out

    try:
        resp = obj.get("response", {})
        docs = resp.get("docs", [])
        out["total_found"] = int(resp.get("numFound", 0))
        out["returned"] = len(docs)
        out["results"] = [normalize_doc(d) for d in docs]
        if "facet_counts" in obj:
            facet_counts = obj.get("facet_counts") or {}
            out["facets"].update(normalize_facets(facet_counts))
            out["facets_raw"] = facet_counts
            pivots = facet_counts.get("facet_pivot")
            if pivots:
                out["facet_pivot"] = pivots
        if "grouped" in obj:
            out["grouped"] = obj.get("grouped")
        return out
    except Exception as e:
        out["error"] = f"Failed to parse HAL JSON response: {e}"
        out["source_url"] = url
        return out


def cmd_list_portals(a: argparse.Namespace) -> Dict[str, Any]:
    """List HAL portals, i.e. the lowercase codes accepted by `--portal`.

    `/ref/instance/` ignores q, fq and rows and always answers with the whole
    list, so the filtering happens here rather than in the query string.
    """
    url = REF_BASE_URL + "instance/?wt=json"

    out: Dict[str, Any] = {
        "total_found": None,
        "returned": 0,
        "results": [],
        "query_used": a.contains,
        "params": {
            "contains": a.contains,
            "include_deprecated": a.include_deprecated,
            "rows": a.rows,
        },
        "error": None,
    }

    obj, err = http_get_json(url)
    if err:
        out["error"] = err
        out["source_url"] = url
        return out

    try:
        docs = (obj.get("response", {}) or {}).get("docs", []) or []
        needle = a.contains.lower() if a.contains else None

        kept: List[Dict[str, Any]] = []
        for d in docs:
            # `deprecated` comes back as the string "true"/"false", not a bool.
            if not a.include_deprecated and str(d.get("deprecated", "")).lower() == "true":
                continue
            if needle:
                haystack = f"{d.get('code', '')} {d.get('name', '')}".lower()
                if needle not in haystack:
                    continue
            kept.append(normalize_ref_doc("instance", d))

        out["total_found"] = len(kept)
        if a.rows and a.rows > 0:
            kept = kept[: a.rows]
        out["returned"] = len(kept)
        out["results"] = kept
        return out
    except Exception as e:
        out["error"] = f"Failed to parse HAL instance list: {e}"
        out["source_url"] = url
        return out


def cmd_lookup_ref(a: argparse.Namespace) -> Dict[str, Any]:
    """Query an AuréHAL reference (structures, authors, journals, projects…).

    This is how a collection code, a `structId_i`, a journal id or an ANR
    reference is resolved before it is used as a filter in `search`.
    """
    params: List[Tuple[str, str]] = [("q", a.q)]
    for f in a.fq:
        params.append(("fq", f))
    params.append(("fl", a.fl))
    params.append(("rows", str(a.rows)))
    params.append(("start", str(a.start)))
    if a.sort:
        params.append(("sort", a.sort))
    params.append(("wt", "json"))

    url = REF_BASE_URL + f"{a.ref}/?" + urllib.parse.urlencode(params, doseq=True)

    out: Dict[str, Any] = {
        "total_found": None,
        "returned": 0,
        "results": [],
        "query_used": a.q,
        "filters_used": a.fq,
        "ref": a.ref,
        "params": {"rows": a.rows, "start": a.start, "sort": a.sort, "fl": a.fl},
        "error": None,
    }

    obj, err = http_get_json(url)
    if err:
        out["error"] = err
        out["source_url"] = url
        return out

    try:
        resp = obj.get("response", {}) or {}
        docs = resp.get("docs", []) or []
        num_found = resp.get("numFound")
        out["total_found"] = int(num_found) if num_found is not None else None
        out["returned"] = len(docs)
        out["results"] = [normalize_ref_doc(a.ref, d) for d in docs]
        return out
    except Exception as e:
        out["error"] = f"Failed to parse HAL reference JSON response: {e}"
        out["source_url"] = url
        return out


def main() -> None:
    a = parse_args()

    if a.cmd == "search":
        out = cmd_search(a)
    elif a.cmd == "list-portals":
        out = cmd_list_portals(a)
    elif a.cmd == "lookup-ref":
        out = cmd_lookup_ref(a)
    else:
        out = {"error": f"Unknown command: {a.cmd}"}

    json.dump(out, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
