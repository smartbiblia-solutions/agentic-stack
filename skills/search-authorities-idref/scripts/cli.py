#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ['httpx']
# ///

"""Search IdRef authority records and their linked bibliography.

Wraps two public ABES endpoints: the Solr authority index, and the `references`
micro web service that lists the documents attached to an authority. Both are
anonymous — this skill reads no credential and no endpoint from the environment.

Usage:
    ./cli.py search --index persname_t --text 'Victor Hugo' --max-results 5
    ./cli.py search --query 'persname_t:(Bourdieu AND Pierre)'
    ./cli.py get --ppn 027715078
    ./cli.py references --ppn 02686018X
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from typing import Any

import httpx

SOLR_URL = "https://www.idref.fr/Sru/Solr"
REFERENCES_URL = "https://www.idref.fr/services/references/{ppn}.json"
DEFAULT_FIELDS = "id,ppn_z,recordtype_z,affcourt_z"

# Constants, not tunables: they describe the connector, not the installation.
HTTP_TIMEOUT = 20.0
MAX_RETRIES = 2
BACKOFF_BASE = 1.0
BACKOFF_FACTOR = 2.0
JITTER_MAX = 0.25
RETRIED_STATUS = {429, 500, 502, 503, 504}

# One pooled client: httpx.get() would rebuild the connection — and the TLS
# handshake — on every call.
HTTP = httpx.Client(
    timeout=HTTP_TIMEOUT,
    follow_redirects=True,
    headers={"User-Agent": "smartbiblia-search-authorities-idref/0.1"},
)


def emit(payload: dict[str, Any]) -> None:
    """Strict JSON on stdout, always exit 0: a failure is data, not a stack trace."""
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def get_json(url: str, params: dict[str, str] | None = None) -> tuple[Any, str | None]:
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = HTTP.get(url, params=params, headers={"Accept": "application/json"})
            if response.status_code < 400:
                try:
                    return response.json(), None
                except json.JSONDecodeError:
                    # IdRef answers a malformed Solr query with 200 and an empty
                    # body rather than a 4xx. Deterministic, so do not retry.
                    return None, (
                        f"IdRef returned a non-JSON body (HTTP {response.status_code}); "
                        "the query is most likely malformed: "
                        f"{response.text[:200] or '<empty body>'}"
                    )
            last_error = f"HTTP {response.status_code}: {response.text[:300]}"
            if response.status_code not in RETRIED_STATUS:
                break
        except Exception as exc:  # unreachable host, timeout, transport error
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < MAX_RETRIES:
            time.sleep(BACKOFF_BASE * (BACKOFF_FACTOR**attempt) + random.uniform(0, JITTER_MAX))
    return None, last_error


def normalize_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """Map a Solr authority document onto the common record schema.

    An authority is a name, not a publication, so most bibliographic fields are
    structurally null — they are kept so records merge with those of the other
    search-* skills without transformation.
    """
    ppn = doc.get("ppn_z") or doc.get("ppn") or doc.get("id")
    recordtype = doc.get("recordtype_z")
    return {
        "source": "idref",
        "id": ppn,
        "ppn": ppn,
        "title": doc.get("affcourt_z") or doc.get("affcourt_r") or doc.get("title"),
        "authors": None,
        "abstract": None,
        "doi": None,
        "pdf_url": None,
        "url": f"https://www.idref.fr/{ppn}" if ppn else None,
        "year": None,
        "date": None,
        "doc_type": recordtype,
        "journal": None,
        "recordtype": recordtype,
        "solr_id": doc.get("id"),
        "raw": doc,
    }


def build_query(index: str | None, text: str | None, query: str | None) -> str:
    if query:
        return query
    if not text:
        raise ValueError("Either --query or --index/--text must be provided")
    idx = index or "all"
    words = text.split()
    if len(words) > 1:
        return f'{idx}:({" AND ".join(words)})'
    return f"{idx}:{text}"


def solr_search(query: str, rows: int, start: int, sort: str, fields: str) -> tuple[list[dict], dict, str | None]:
    params = {
        "q": query,
        "wt": "json",
        "sort": sort,
        "version": "2.2",
        "start": str(start),
        "rows": str(rows),
        "indent": "on",
        "fl": fields,
    }
    data, error = get_json(SOLR_URL, params)
    if error:
        return [], {}, error
    response = (data or {}).get("response") or {}
    docs = [d for d in (response.get("docs") or []) if isinstance(d, dict)]
    return [normalize_doc(d) for d in docs], response, None


def cmd_search(args: argparse.Namespace) -> int:
    try:
        query = build_query(args.index, args.text, args.query)
    except ValueError as exc:
        emit({"source": "idref", "query": None, "total_found": 0, "returned": 0,
              "start": 0, "results": [], "error": str(exc)})
        return 0

    results, response, error = solr_search(
        query, args.max_results, args.start, args.sort, args.fields
    )
    emit({
        "source": "idref",
        "query": query,
        "total_found": int(response.get("numFound", 0) or 0),
        "returned": len(results),
        "start": int(response.get("start", args.start) or 0),
        "results": results,
        "error": error,
    })
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    ppn = args.ppn.strip()
    results, _response, error = solr_search(f"ppn_z:{ppn}", 1, 0, "score desc", args.fields)
    emit({
        "source": "idref",
        "ppn": ppn,
        "result": results[0] if results else None,
        "error": error,
    })
    return 0


def as_list(value: Any) -> list[Any]:
    """The micro service drops the list when a role or a doc is alone."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def cmd_references(args: argparse.Namespace) -> int:
    ppn = args.ppn.strip()
    data, error = get_json(REFERENCES_URL.format(ppn=ppn))
    if error:
        emit({"source": "idref", "ppn": ppn, "roles": [], "error": error})
        return 0

    # The payload is wrapped in a referential-named envelope, usually "sudoc".
    envelope = data.get("sudoc") or next(iter(data.values()), None) if isinstance(data, dict) else None
    result = envelope.get("result") or {} if isinstance(envelope, dict) else {}

    roles_raw = as_list(result.get("role"))
    if args.max_roles is not None:
        roles_raw = roles_raw[: args.max_roles]

    roles = []
    for role in roles_raw:
        if not isinstance(role, dict):
            continue
        role_docs = as_list(role.get("doc"))
        if args.max_docs_per_role is not None:
            role_docs = role_docs[: args.max_docs_per_role]
        roles.append({
            "role_name": role.get("roleName"),
            "marc21_code": role.get("marc21Code"),
            "unimarc_code": role.get("unimarcCode"),
            "count": int(role.get("count", 0) or 0),
            "docs": [
                {
                    "citation": d.get("citation"),
                    "referentiel": d.get("referentiel"),
                    "id": d.get("id"),
                    "ppn": d.get("ppn"),
                    "url": d.get("URL"),
                    "uri": d.get("URI"),
                    "raw": d,
                }
                for d in role_docs
                if isinstance(d, dict)
            ],
        })

    emit({"source": "idref", "ppn": ppn, "roles": roles, "error": None})
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="IdRef authority search and references CLI")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("search", help="Search IdRef authorities via Solr")
    s.add_argument("--query", help="Raw Solr query, e.g. 'persname_t:(Bourdieu AND Pierre)'")
    s.add_argument("--index", default="all", help="Solr index for a simple search (default: all)")
    s.add_argument("--text", help="Plain text to search in --index")
    s.add_argument("--max-results", type=int, default=10, help="Rows to return (default: 10)")
    s.add_argument("--start", type=int, default=0, help="Offset for pagination")
    s.add_argument("--sort", default="score desc", help="Solr sort, e.g. 'affcourt_z asc'")
    s.add_argument("--fields", default=DEFAULT_FIELDS, help=f"Comma-separated Solr fl (default: {DEFAULT_FIELDS})")
    s.set_defaults(func=cmd_search)

    g = sub.add_parser("get", help="Fetch one authority by PPN")
    g.add_argument("--ppn", required=True, help="IdRef PPN")
    g.add_argument("--fields", default=DEFAULT_FIELDS, help=f"Comma-separated Solr fl (default: {DEFAULT_FIELDS})")
    g.set_defaults(func=cmd_get)

    r = sub.add_parser("references", help="Fetch linked bibliographic references by PPN")
    r.add_argument("--ppn", required=True, help="IdRef PPN")
    r.add_argument("--max-roles", type=int, default=None, help="Limit role groups (default: all)")
    r.add_argument("--max-docs-per-role", type=int, default=10, help="Limit documents per role (default: 10)")
    r.set_defaults(func=cmd_references)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
