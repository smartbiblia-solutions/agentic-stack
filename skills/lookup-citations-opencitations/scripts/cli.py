#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ['httpx']
# ///
"""OpenCitations CLI — citation counts, citation edges and bibliographic metadata.

Two APIs behind one command: OpenCitations Meta v1 (bibliographic metadata) and
OpenCitations Index v2 (the citation entities themselves).

Subcommands:
  counts           citation and reference counts for one or more identifiers
  citations        the works citing a given work (incoming edges)
  references       the works cited by a given work (outgoing edges)
  metadata         Meta records for one or more identifiers
  works-by-person  the works of an ORCID, as author or as editor

Gotchas, all verified live:
  - There is NO search operation. Every entry point is a known identifier
    (doi:, pmid:, omid:, openalex:, issn:, isbn:, orcid:). Discover works
    elsewhere (search-works-openalex, search-records-hal), then come here.
  - The API has no pagination and no server-side limit: `citations` on a
    heavily cited work returns the whole list — 24 354 edges / 9.9 MB was
    measured. `--max-results` clamps client-side, after the full download.
  - Very large works simply fail upstream (HTTP 500 after 4 minutes). This CLI
    checks the cheap count endpoint first and refuses to list beyond
    MAX_LISTABLE_EDGES, returning the counts and an explanatory `error`.
  - The server sometimes answers HTTP 200 with truncated, invalid JSON. Such a
    response is retried once, then reported as an error, never as a crash.
  - An unknown identifier is HTTP 200 with an empty list, never a 404.

Run:
  uv run cli.py counts doi:10.1108/jd-12-2013-0166
  uv run cli.py citations doi:10.1108/jd-12-2013-0166 --max-results 5 --sort creation-desc
  uv run cli.py references doi:10.1108/jd-12-2013-0166 --hydrate
  uv run cli.py metadata doi:10.1108/jd-12-2013-0166 pmid:2942070
  uv run cli.py works-by-person orcid:0000-0002-8420-0696 --role author
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from typing import Any

import httpx

# ── Configuration ─────────────────────────────────────────────────────────────

API_URL = os.environ.get("OPENCITATIONS_API_URL", "https://api.opencitations.net").rstrip("/")
API_KEY = os.environ.get("OPENCITATIONS_API_KEY", "").strip()

META = f"{API_URL}/meta/v1"
INDEX = f"{API_URL}/index/v2"

SOURCE = "opencitations"

# Connector properties, not installation settings — constants on purpose.
HTTP_TIMEOUT = 60.0          # a citation list can be several megabytes
MAX_RETRIES = 3
BACKOFF_BASE = 1.0
BACKOFF_FACTOR = 2.0
JITTER_MAX = 0.25
RETRIED_STATUS = {429, 500, 502, 503, 504}

# Above this many edges the upstream list endpoint is unusable: it either takes
# minutes or answers HTTP 500. Refuse early and say so.
MAX_LISTABLE_EDGES = 5000

# `/metadata/{ids}` joins identifiers with `__`; the only real bound is URL
# length, so batch conservatively.
METADATA_BATCH = 10

HEADERS = {
    "User-Agent": "smartbiblia-opencitations-skill/0.1",
    "Accept": "application/json",
}
if API_KEY:
    # OpenCitations expects the raw token, with no scheme prefix.
    HEADERS["authorization"] = API_KEY

HTTP = httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True, headers=HEADERS)


# ── HTTP ──────────────────────────────────────────────────────────────────────

def _sleep_backoff(attempt: int) -> None:
    delay = BACKOFF_BASE * (BACKOFF_FACTOR ** (attempt - 1))
    time.sleep(delay + random.random() * JITTER_MAX)


def http_get_json(url: str) -> tuple[Any, str | None]:
    """Return (payload, error). Never raises — the error is data."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = HTTP.get(url)

            if resp.status_code in RETRIED_STATUS and attempt < MAX_RETRIES:
                _sleep_backoff(attempt)
                continue

            if resp.status_code >= 400:
                # A rejected token answers 403 with a plain-text body.
                return None, f"HTTP {resp.status_code} on {url}: {resp.text[:200].strip()}"

            try:
                return resp.json(), None
            except ValueError:
                # Truncated payloads arrive with HTTP 200; one more try is worth it.
                if attempt < MAX_RETRIES:
                    _sleep_backoff(attempt)
                    continue
                return None, (f"Truncated or non-JSON response from {url} "
                              f"({len(resp.content)} bytes). The work is probably too "
                              f"large for the upstream list endpoint.")

        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt == MAX_RETRIES:
                return None, f"Request failed: {exc}"
            _sleep_backoff(attempt)

    return None, "Request failed (exhausted retries)"


# ── Normalization ─────────────────────────────────────────────────────────────

_AGENT_RE = re.compile(r"^\s*(?P<name>.*?)\s*(?:\[(?P<ids>[^\]]*)\])?\s*$")
_TIMESPAN_RE = re.compile(r"^(?P<sign>-?)P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)D)?$")


def parse_identifiers(raw: str | None) -> dict[str, str]:
    """`"doi:10.1/x omid:br/061"` → `{"doi": "10.1/x", "omid": "br/061"}`.

    First occurrence of a scheme wins; the untouched string stays in `raw`.
    """
    out: dict[str, str] = {}
    for token in (raw or "").split():
        scheme, sep, value = token.partition(":")
        if sep and value and scheme not in out:
            out[scheme] = value
    return out


def parse_agents(raw: str | None) -> list[dict[str, Any]]:
    """`"Peroni, Silvio [orcid:0000-…]; Shotton, David [omid:ra/06…]"` → records."""
    agents = []
    for chunk in (raw or "").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = _AGENT_RE.match(chunk)
        name = (m.group("name") or "").strip() if m else chunk
        ids = parse_identifiers(m.group("ids") if m else None)
        if not name:
            continue
        agents.append({"name": name, "orcid": ids.get("orcid"), "omid": ids.get("omid")})
    return agents


def parse_venue(raw: str | None) -> dict[str, Any] | None:
    """`"Journal of Documentation [issn:0022-0418 omid:br/06…]"` → title + ids."""
    if not (raw or "").strip():
        return None
    m = _AGENT_RE.match(raw or "")
    title = (m.group("name") or "").strip() if m else (raw or "").strip()
    ids = parse_identifiers(m.group("ids") if m else None)
    return {"title": title or None, "issn": ids.get("issn"), "omid": ids.get("omid")}


def parse_timespan_days(raw: str | None) -> int | None:
    """`"P6Y0M1D"` → 2191. Approximate: 365-day years, 30-day months."""
    m = _TIMESPAN_RE.match((raw or "").strip())
    if not m:
        return None
    years, months, days = (int(g) if g else 0 for g in m.groups()[1:])
    total = years * 365 + months * 30 + days
    return -total if m.group("sign") else total


def _work_url(ids: dict[str, str]) -> str | None:
    if "doi" in ids:
        return f"https://doi.org/{ids['doi']}"
    if "omid" in ids:
        return f"https://opencitations.net/meta/{ids['omid']}"
    if "pmid" in ids:
        return f"https://pubmed.ncbi.nlm.nih.gov/{ids['pmid']}/"
    return None


def normalize_meta(rec: dict[str, Any]) -> dict[str, Any]:
    """A Meta record, in the shape the bibliographic connectors share.

    `abstract` is always null: OpenCitations Meta does not carry abstracts. It
    is kept so results merge with OpenAlex/HAL/Sudoc/Primo hits on `doi`.
    """
    ids = parse_identifiers(rec.get("id"))
    date = (rec.get("pub_date") or "").strip() or None
    venue = parse_venue(rec.get("venue"))
    return {
        "source": SOURCE,
        "id": ids.get("omid") or ids.get("doi") or (rec.get("id") or "").strip() or None,
        "url": _work_url(ids),
        "title": (rec.get("title") or "").strip() or None,
        "authors": parse_agents(rec.get("author")),
        "abstract": None,
        "doi": ids.get("doi"),
        "year": date[:4] if date else None,
        "date": date,
        "doc_type": (rec.get("type") or "").strip() or None,
        "journal": venue["title"] if venue else None,
        "venue": venue,
        "publisher": parse_agents(rec.get("publisher")),
        "editors": parse_agents(rec.get("editor")),
        "volume": (rec.get("volume") or "").strip() or None,
        "issue": (rec.get("issue") or "").strip() or None,
        "page": (rec.get("page") or "").strip() or None,
        "identifiers": ids,
        "raw": rec,
    }


def normalize_edge(rec: dict[str, Any]) -> dict[str, Any]:
    """A citation edge. Its own record family — not a bibliographic record."""
    oci = (rec.get("oci") or "").strip() or None
    return {
        "source": SOURCE,
        "id": oci,
        "url": f"https://opencitations.net/index/ci/{oci}" if oci else None,
        "citing": parse_identifiers(rec.get("citing")),
        "cited": parse_identifiers(rec.get("cited")),
        "creation": (rec.get("creation") or "").strip() or None,
        "timespan": (rec.get("timespan") or "").strip() or None,
        "timespan_days": parse_timespan_days(rec.get("timespan")),
        "journal_sc": (rec.get("journal_sc") or "").strip() or None,
        "author_sc": (rec.get("author_sc") or "").strip() or None,
        "raw": rec,
    }


def envelope(**extra: Any) -> dict[str, Any]:
    """The universal envelope, in key order, with the extras a command adds."""
    return {"total_found": None, "returned": 0, "results": [], **extra, "error": None}


# ── Shared helpers ────────────────────────────────────────────────────────────

def _count(kind: str, identifier: str) -> tuple[int | None, str | None]:
    """kind is "citation" or "reference". Returns (count, error)."""
    payload, err = http_get_json(f"{INDEX}/{kind}-count/{identifier}")
    if err:
        return None, err
    if not isinstance(payload, list) or not payload:
        return 0, None
    try:
        return int(payload[0].get("count", 0)), None
    except (AttributeError, TypeError, ValueError):
        return None, f"Unreadable {kind} count for {identifier}: {payload!r:.200}"


def _pick_lookup_id(ids: dict[str, str]) -> str | None:
    for scheme in ("doi", "pmid", "omid"):
        if scheme in ids:
            return f"{scheme}:{ids[scheme]}"
    return None


def _hydrate(edges: list[dict[str, Any]], side: str) -> str | None:
    """Attach a `<side>_work` Meta record to each edge. Returns an error string."""
    wanted, order = {}, []
    for edge in edges:
        key = _pick_lookup_id(edge[side])
        if key and key not in wanted:
            wanted[key] = None
            order.append(key)

    errors = []
    for start in range(0, len(order), METADATA_BATCH):
        batch = order[start:start + METADATA_BATCH]
        payload, err = http_get_json(f"{META}/metadata/{'__'.join(batch)}")
        if err:
            errors.append(err)
            continue
        for rec in payload if isinstance(payload, list) else []:
            record = normalize_meta(rec)
            for scheme, value in record["identifiers"].items():
                key = f"{scheme}:{value}"
                if key in wanted and wanted[key] is None:
                    wanted[key] = record

    for edge in edges:
        key = _pick_lookup_id(edge[side])
        edge[f"{side}_work"] = wanted.get(key) if key else None

    return "; ".join(errors) if errors else None


def _list_edges(a: argparse.Namespace, kind: str) -> dict[str, Any]:
    """`citations` and `references` differ only by endpoint and by which end
    of the edge carries the other work."""
    endpoint, count_kind, side = {
        "citations": ("citations", "citation", "citing"),
        "references": ("references", "reference", "cited"),
    }[kind]

    out = envelope(source=SOURCE, command=kind, id=a.id)

    total, err = _count(count_kind, a.id)
    out["total_found"] = total
    if err:
        out["error"] = err
        return out

    if total == 0:
        return out

    if total is not None and total > MAX_LISTABLE_EDGES:
        out["error"] = (
            f"{total} {kind} exceed the safe listing threshold of {MAX_LISTABLE_EDGES}: "
            f"the OpenCitations list endpoint has no pagination and fails or times out "
            f"at this size. Use total_found, or narrow the question to a smaller work."
        )
        return out

    payload, err = http_get_json(f"{INDEX}/{endpoint}/{a.id}")
    if err:
        out["error"] = err
        return out

    edges = [normalize_edge(r) for r in payload if isinstance(r, dict)] \
        if isinstance(payload, list) else []

    if a.exclude_self_citations:
        kept = [e for e in edges if e["journal_sc"] != "yes" and e["author_sc"] != "yes"]
        out["excluded_self_citations"] = len(edges) - len(kept)
        edges = kept

    if a.sort:
        field, _, direction = a.sort.partition("-")
        edges.sort(key=lambda e: e[field] or "", reverse=(direction == "desc"))

    edges = edges[:a.max_results]

    if a.hydrate and edges:
        out["error"] = _hydrate(edges, side)

    out["results"] = edges
    out["returned"] = len(edges)
    return out


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_counts(a: argparse.Namespace) -> dict[str, Any]:
    out = envelope(source=SOURCE, command="counts")
    results, errors = [], []
    for identifier in a.ids:
        citations, err_c = _count("citation", identifier)
        references, err_r = _count("reference", identifier)
        errors.extend(e for e in (err_c, err_r) if e)
        ids = parse_identifiers(identifier)
        results.append({
            "source": SOURCE,
            "id": identifier,
            "url": _work_url(ids),
            "citation_count": citations,
            "reference_count": references,
        })
    out["results"] = results
    out["returned"] = len(results)
    out["total_found"] = len(results)
    if errors:
        out["error"] = "; ".join(errors)
    return out


def cmd_citations(a: argparse.Namespace) -> dict[str, Any]:
    return _list_edges(a, "citations")


def cmd_references(a: argparse.Namespace) -> dict[str, Any]:
    return _list_edges(a, "references")


def cmd_metadata(a: argparse.Namespace) -> dict[str, Any]:
    out = envelope(source=SOURCE, command="metadata")
    results, errors = [], []
    for start in range(0, len(a.ids), METADATA_BATCH):
        batch = a.ids[start:start + METADATA_BATCH]
        payload, err = http_get_json(f"{META}/metadata/{'__'.join(batch)}")
        if err:
            errors.append(err)
            continue
        results.extend(normalize_meta(r) for r in payload if isinstance(r, dict))
    out["results"] = results
    out["returned"] = len(results)
    out["total_found"] = len(results)
    if errors:
        out["error"] = "; ".join(errors)
    return out


def cmd_works_by_person(a: argparse.Namespace) -> dict[str, Any]:
    out = envelope(source=SOURCE, command="works-by-person",
                   person_id=a.person_id, role=a.role)
    payload, err = http_get_json(f"{META}/{a.role}/{a.person_id}")
    if err:
        out["error"] = err
        return out
    records = [normalize_meta(r) for r in payload if isinstance(r, dict)] \
        if isinstance(payload, list) else []
    out["total_found"] = len(records)
    out["results"] = records[:a.max_results]
    out["returned"] = len(out["results"])
    return out


# ── Argument parsing ──────────────────────────────────────────────────────────

ID_HELP = ("identifier with its scheme prefix, e.g. doi:10.1108/jd-12-2013-0166, "
           "pmid:2942070 or omid:br/0601")
SORT_CHOICES = ["creation-asc", "creation-desc", "timespan_days-asc", "timespan_days-desc"]


def _add_edge_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("id", help=ID_HELP)
    p.add_argument("--max-results", type=int, default=20,
                   help="clamp applied client-side, after the full download (default 20)")
    p.add_argument("--sort", choices=SORT_CHOICES,
                   help="client-side ordering; the API's own sort is unusable at scale")
    p.add_argument("--exclude-self-citations", action="store_true",
                   help="drop edges where journal_sc or author_sc is yes")
    p.add_argument("--hydrate", action="store_true",
                   help="attach the Meta record of the work at the other end "
                        "(one extra request per 10 works)")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="OpenCitations Meta v1 and Index v2. Identifier-driven: there is no search.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    counts = sub.add_parser("counts", help="citation and reference counts (the cheap call)")
    counts.add_argument("ids", nargs="+", help=ID_HELP)

    _add_edge_args(sub.add_parser("citations", help="works citing this work"))
    _add_edge_args(sub.add_parser("references", help="works cited by this work"))

    meta = sub.add_parser("metadata", help="bibliographic records from OpenCitations Meta")
    meta.add_argument("ids", nargs="+",
                      help="doi:, pmid:, pmcid:, isbn:, issn:, openalex: or omid: identifiers. "
                           "An ISSN returns the journal itself, not its articles.")

    person = sub.add_parser("works-by-person", help="works of an ORCID, as author or editor")
    person.add_argument("person_id", help="orcid:0000-0002-8420-0696 or omid:ra/0605")
    person.add_argument("--role", choices=["author", "editor"], default="author")
    person.add_argument("--max-results", type=int, default=50)

    return p.parse_args()


def main() -> None:
    a = parse_args()
    out = {"counts": cmd_counts, "citations": cmd_citations, "references": cmd_references,
           "metadata": cmd_metadata, "works-by-person": cmd_works_by_person}[a.cmd](a)
    json.dump(out, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
