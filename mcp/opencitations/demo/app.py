#!/usr/bin/env python3
"""
Standalone Gradio demo of the OpenCitations MCP server, deployable as a Hugging
Face Space.

The five tools mirror the canonical `mcp_server.py` — same names, same arguments,
same envelope. The deliberate narrowings are the result caps (25 instead of 500)
and the listing threshold (2 000 edges instead of 5 000): this Space is public,
and the upstream list endpoint downloads every edge before anything is cut.

Local run:
    uv run --with 'gradio[mcp]>=6,<7' --with httpx app.py

Environment:
    OPENCITATIONS_API_URL  API base URL (default the public OpenCitations API)
    OPENCITATIONS_API_KEY  optional token — raises the quota, nothing else
    GRADIO_SERVER_NAME     bind address (default 0.0.0.0)
    GRADIO_SERVER_PORT     port (default 7860)
    GRADIO_MCP_SERVER      "false" disables the demo MCP endpoint (default true)
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

import gradio as gr
import httpx

# ── Configuration ─────────────────────────────────────────────────────────────

API_URL = os.environ.get("OPENCITATIONS_API_URL", "https://api.opencitations.net").rstrip("/")
API_KEY = os.environ.get("OPENCITATIONS_API_KEY", "").strip()

META = f"{API_URL}/meta/v1"
INDEX = f"{API_URL}/index/v2"

SOURCE = "opencitations"
USER_AGENT = "smartbiblia-opencitations-demo/0.1"

SORT_VALUES = ("creation-asc", "creation-desc", "timespan_days-asc", "timespan_days-desc")

# A Space has no command line: connector policy is constant here.
REQUEST_TIMEOUT = 45.0
MAX_RETRIES = 2
BACKOFF_SECONDS = 1.0
RETRIED_STATUS = {429, 500, 502, 503, 504}

# Clamped harder than the canonical server (500 results, 5 000 edges): this Space
# is public, and every listed work is downloaded whole before being cut.
MAX_RESULTS = 25
MAX_LISTABLE_EDGES = 2000
# `/metadata/{ids}` joins identifiers with `__`; the only real bound is URL
# length, so batch conservatively.
METADATA_BATCH = 10

_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}
if API_KEY:
    # OpenCitations expects the raw token, with no scheme prefix.
    _HEADERS["authorization"] = API_KEY

# One module-level pooled client for the process.
HTTP = httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True, headers=_HEADERS)


def _get_json(url: str) -> tuple[Any, str | None]:
    """GET returning (payload, error). Never raises — the demo answers with data."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = HTTP.get(url)
            if resp.status_code in RETRIED_STATUS and attempt < MAX_RETRIES:
                time.sleep(BACKOFF_SECONDS * attempt)
                continue
            if resp.status_code >= 400:
                # A rejected token answers 403 with a plain-text body.
                return None, f"HTTP {resp.status_code} on {url}: {resp.text[:200].strip()}"
            try:
                return resp.json(), None
            except ValueError:
                # Truncated payloads arrive with HTTP 200; one more try is worth it.
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_SECONDS * attempt)
                    continue
                return None, (f"Truncated or non-JSON response from {url} "
                              f"({len(resp.content)} bytes). The work is probably too "
                              f"large for the upstream list endpoint.")
        except httpx.TimeoutException:
            if attempt == MAX_RETRIES:
                return None, f"OpenCitations timed out after {REQUEST_TIMEOUT:g}s"
            time.sleep(BACKOFF_SECONDS * attempt)
        except Exception as exc:  # noqa: BLE001 - never crash the Space
            return None, f"cannot reach OpenCitations: {exc}"
    return None, "Request failed (exhausted retries)"


# ── Normalization (a hand-kept copy of the canonical server's) ────────────────

_AGENT_RE = re.compile(r"^\s*(?P<name>.*?)\s*(?:\[(?P<ids>[^\]]*)\])?\s*$")
_TIMESPAN_RE = re.compile(r"^(?P<sign>-?)P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)D)?$")


def _identifiers(raw: str | None) -> dict[str, str]:
    """`"doi:10.1/x omid:br/061"` -> `{"doi": "10.1/x", "omid": "br/061"}`."""
    out: dict[str, str] = {}
    for token in (raw or "").split():
        scheme, sep, value = token.partition(":")
        if sep and value and scheme not in out:
            out[scheme] = value
    return out


def _agents(raw: str | None) -> list[dict[str, Any]]:
    """`"Peroni, Silvio [orcid:0000-…]; Shotton, David [omid:ra/06…]"` -> records."""
    agents: list[dict[str, Any]] = []
    for chunk in (raw or "").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = _AGENT_RE.match(chunk)
        name = (m.group("name") or "").strip() if m else chunk
        ids = _identifiers(m.group("ids") if m else None)
        if name:
            agents.append({"name": name, "orcid": ids.get("orcid"), "omid": ids.get("omid")})
    return agents


def _venue(raw: str | None) -> dict[str, Any] | None:
    """`"Journal of Documentation [issn:0022-0418 omid:br/06…]"` -> title + ids."""
    if not (raw or "").strip():
        return None
    m = _AGENT_RE.match(raw or "")
    title = (m.group("name") or "").strip() if m else (raw or "").strip()
    ids = _identifiers(m.group("ids") if m else None)
    return {"title": title or None, "issn": ids.get("issn"), "omid": ids.get("omid")}


def _timespan_days(raw: str | None) -> int | None:
    """`"P6Y0M1D"` -> 2191. Approximate: 365-day years, 30-day months."""
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


def _normalize_meta(rec: dict[str, Any]) -> dict[str, Any]:
    """A Meta record. `abstract` is always null — Meta carries none — but is kept
    so results merge with OpenAlex/HAL/Sudoc/Primo hits on `doi`."""
    ids = _identifiers(rec.get("id"))
    date = (rec.get("pub_date") or "").strip() or None
    venue = _venue(rec.get("venue"))
    return {
        "source": SOURCE,
        "id": ids.get("omid") or ids.get("doi") or (rec.get("id") or "").strip() or None,
        "url": _work_url(ids),
        "title": (rec.get("title") or "").strip() or None,
        "authors": _agents(rec.get("author")),
        "abstract": None,
        "doi": ids.get("doi"),
        "year": date[:4] if date else None,
        "date": date,
        "doc_type": (rec.get("type") or "").strip() or None,
        "journal": venue["title"] if venue else None,
        "venue": venue,
        "publisher": _agents(rec.get("publisher")),
        "editors": _agents(rec.get("editor")),
        "volume": (rec.get("volume") or "").strip() or None,
        "issue": (rec.get("issue") or "").strip() or None,
        "page": (rec.get("page") or "").strip() or None,
        "identifiers": ids,
        "raw": rec,
    }


def _normalize_edge(rec: dict[str, Any]) -> dict[str, Any]:
    """A citation edge. Its own record family — not a bibliographic record."""
    oci = (rec.get("oci") or "").strip() or None
    return {
        "source": SOURCE,
        "id": oci,
        "url": f"https://opencitations.net/index/ci/{oci}" if oci else None,
        "citing": _identifiers(rec.get("citing")),
        "cited": _identifiers(rec.get("cited")),
        "creation": (rec.get("creation") or "").strip() or None,
        "timespan": (rec.get("timespan") or "").strip() or None,
        "timespan_days": _timespan_days(rec.get("timespan")),
        "journal_sc": (rec.get("journal_sc") or "").strip() or None,
        "author_sc": (rec.get("author_sc") or "").strip() or None,
        "raw": rec,
    }


def _envelope(command: str, **extra: Any) -> dict[str, Any]:
    return {"source": SOURCE, "command": command,
            "total_found": None, "returned": 0, "results": [], **extra, "error": None}


def _count(kind: str, identifier: str) -> tuple[int | None, str | None]:
    """kind is "citation" or "reference"."""
    payload, error = _get_json(f"{INDEX}/{kind}-count/{identifier}")
    if error:
        return None, error
    if not isinstance(payload, list) or not payload:
        return 0, None
    try:
        return int(payload[0].get("count", 0)), None
    except (AttributeError, TypeError, ValueError):
        return None, f"Unreadable {kind} count for {identifier}"


def _pick_lookup_id(ids: dict[str, str]) -> str | None:
    for scheme in ("doi", "pmid", "omid"):
        if scheme in ids:
            return f"{scheme}:{ids[scheme]}"
    return None


def _hydrate(edges: list[dict[str, Any]], side: str) -> str | None:
    """Attach a `<side>_work` Meta record to each edge, batched by METADATA_BATCH."""
    wanted: dict[str, Any] = {}
    order: list[str] = []
    for edge in edges:
        key = _pick_lookup_id(edge[side])
        if key and key not in wanted:
            wanted[key] = None
            order.append(key)

    errors: list[str] = []
    for start in range(0, len(order), METADATA_BATCH):
        batch = order[start:start + METADATA_BATCH]
        payload, error = _get_json(f"{META}/metadata/{'__'.join(batch)}")
        if error:
            errors.append(error)
            continue
        for rec in payload if isinstance(payload, list) else []:
            record = _normalize_meta(rec)
            for scheme, value in record["identifiers"].items():
                key = f"{scheme}:{value}"
                if key in wanted and wanted[key] is None:
                    wanted[key] = record

    for edge in edges:
        key = _pick_lookup_id(edge[side])
        edge[f"{side}_work"] = wanted.get(key) if key else None

    return "; ".join(errors) if errors else None


# ── MCP tools (the only functions exposed with gr.api) ────────────────────────


def get_citation_counts(ids: list[str]) -> dict:
    """
    Count the citations received and the references made by one or more works.

    The cheap call, and the one to make first: it is the only reliable way to
    know whether `get_citations` can run at all on a given work. Above a few
    thousand edges the upstream list endpoint fails, and `get_citations` returns
    the count with an explanatory error instead of a list.

    Args:
        ids: Identifiers with their scheme prefix, e.g. ["doi:10.1108/jd-12-2013-0166", "pmid:2942070"]. An unknown identifier answers with counts of 0 rather than an error.

    Returns:
        {"source": "opencitations", "command": "get_citation_counts", "total_found": int, "returned": int, "results": [{"source": str, "id": str, "url": str | null, "citation_count": int | null, "reference_count": int | null}], "error": str | null}
    """
    out = _envelope("get_citation_counts")
    results: list[dict[str, Any]] = []
    errors: list[str] = []

    for identifier in ids or []:
        identifier = (identifier or "").strip()
        if not identifier:
            continue
        citations, err_c = _count("citation", identifier)
        references, err_r = _count("reference", identifier)
        errors.extend(e for e in (err_c, err_r) if e)
        results.append({
            "source": SOURCE,
            "id": identifier,
            "url": _work_url(_identifiers(identifier)),
            "citation_count": citations,
            "reference_count": references,
        })

    out["results"] = results
    out["returned"] = len(results)
    out["total_found"] = len(results)
    if errors:
        out["error"] = "; ".join(errors)
    return out


def _list_edges(
    command: str,
    id: str,
    max_results: int,
    sort: str | None,
    exclude_self_citations: bool,
    hydrate: bool,
) -> dict:
    """`get_citations` and `get_references` differ only by endpoint and by which
    end of the edge carries the other work."""
    endpoint, count_kind, side = {
        "get_citations": ("citations", "citation", "citing"),
        "get_references": ("references", "reference", "cited"),
    }[command]

    identifier = (id or "").strip()
    out = _envelope(command, id=identifier)
    if not identifier:
        out["error"] = "id is required — a DOI, PMID or OMID with its scheme prefix"
        return out
    if sort and sort not in SORT_VALUES:
        out["error"] = "sort must be one of " + ", ".join(SORT_VALUES)
        return out

    rows = max(1, min(int(max_results or 20), MAX_RESULTS))

    total, error = _count(count_kind, identifier)
    out["total_found"] = total
    if error:
        out["error"] = error
        return out
    if total and total > MAX_LISTABLE_EDGES:
        out["error"] = (
            f"{total} results exceed this demo's listing threshold of {MAX_LISTABLE_EDGES}: "
            f"the OpenCitations list endpoint has no pagination and fails or times out "
            f"at this size. Use total_found, or narrow the question to a smaller work."
        )
        return out
    if not total:
        return out

    payload, error = _get_json(f"{INDEX}/{endpoint}/{identifier}")
    if error:
        out["error"] = error
        return out

    edges = [_normalize_edge(r) for r in payload if isinstance(r, dict)] \
        if isinstance(payload, list) else []

    if exclude_self_citations:
        kept = [e for e in edges if e["journal_sc"] != "yes" and e["author_sc"] != "yes"]
        out["excluded_self_citations"] = len(edges) - len(kept)
        edges = kept

    if sort:
        field, _, direction = sort.partition("-")
        edges.sort(key=lambda e: e[field] or "", reverse=(direction == "desc"))

    edges = edges[:rows]

    if hydrate and edges:
        out["error"] = _hydrate(edges, side)

    out["results"] = edges
    out["returned"] = len(edges)
    return out


def get_citations(
    id: str,
    max_results: int = 20,
    sort: str | None = None,
    exclude_self_citations: bool = False,
    hydrate: bool = False,
) -> dict:
    """
    List the works citing a given work — the incoming citation edges.

    There is no search operation on OpenCitations: a work is discovered
    elsewhere (OpenAlex, HAL) and identified here. The API has no pagination and
    no server-side limit, so the whole set is downloaded and `max_results`
    clamps client-side; `sort` is applied client-side too.

    Args:
        id: Identifier with its scheme prefix: "doi:…", "pmid:…" or "omid:br/…".
        max_results: Clamp applied after the download, 1-25 on this demo endpoint.
        sort: Client-side ordering — "creation-asc", "creation-desc", "timespan_days-asc" or "timespan_days-desc".
        exclude_self_citations: Drop edges where journal_sc or author_sc is "yes", and report how many in excluded_self_citations.
        hydrate: Attach `citing_work`, the OpenCitations Meta record of the citing work. One extra request per 10 works.

    Returns:
        {"source": "opencitations", "command": "get_citations", "id": str, "total_found": int | null, "returned": int, "results": [{"source": str, "id": "<oci>", "url": str, "citing": object, "cited": object, "creation": str | null, "timespan": str | null, "timespan_days": int | null, "journal_sc": str | null, "author_sc": str | null, "citing_work": object, "raw": object}], "error": str | null}
    """
    return _list_edges("get_citations", id, max_results, sort,
                       exclude_self_citations, hydrate)


def get_references(
    id: str,
    max_results: int = 20,
    sort: str | None = None,
    exclude_self_citations: bool = False,
    hydrate: bool = False,
) -> dict:
    """
    List the works cited by a given work — the outgoing citation edges.

    The reference list as OpenCitations knows it, which is what its publisher
    deposited: it can be shorter than the printed bibliography. With
    `hydrate=True` it becomes a ready-made corpus around a seed paper.

    Domain rules are those of `get_citations`, in the other direction: no
    pagination, client-side clamp and sort. Reference lists are rarely large
    enough for the listing threshold to fire.

    Args:
        id: Identifier with its scheme prefix: "doi:…", "pmid:…" or "omid:br/…".
        max_results: Clamp applied after the download, 1-25 on this demo endpoint.
        sort: Client-side ordering — "creation-asc", "creation-desc", "timespan_days-asc" or "timespan_days-desc".
        exclude_self_citations: Drop edges where journal_sc or author_sc is "yes", and report how many in excluded_self_citations.
        hydrate: Attach `cited_work`, the OpenCitations Meta record of the cited work. One extra request per 10 works.

    Returns:
        Same envelope and edge shape as get_citations, with "command": "get_references" and, under hydrate, `cited_work` instead of `citing_work`.
    """
    return _list_edges("get_references", id, max_results, sort,
                       exclude_self_citations, hydrate)


def lookup_metadata(ids: list[str]) -> dict:
    """
    Resolve identifiers to open bibliographic records from OpenCitations Meta.

    Turns a DOI, PMID, PMC id, ISBN, OpenAlex id or OMID into a citable record —
    title, authors with their ORCIDs, date, venue, publisher, pagination — under
    CC0. Records merge with OpenAlex, HAL, Sudoc and Primo results on `doi`.

    Domain rules:
      - Meta carries no abstract and no full text. `abstract` is always null, and
        is present only so the record shape matches its siblings.
      - An ISSN returns the journal itself, never its articles.
      - Identifiers are batched 10 per upstream request; DOIs are case-insensitive.
      - An unknown identifier yields no row rather than an error.

    Args:
        ids: Identifiers with their scheme prefix: "doi:", "pmid:", "pmcid:", "isbn:", "issn:", "openalex:" or "omid:br/…".

    Returns:
        {"source": "opencitations", "command": "lookup_metadata", "total_found": int, "returned": int, "results": [{"source": str, "id": str, "url": str | null, "title": str | null, "authors": [{"name": str, "orcid": str | null, "omid": str | null}], "abstract": null, "doi": str | null, "year": str | null, "date": str | null, "doc_type": str | null, "journal": str | null, "venue": object | null, "publisher": [], "editors": [], "volume": str | null, "issue": str | null, "page": str | null, "identifiers": object, "raw": object}], "error": str | null}
    """
    out = _envelope("lookup_metadata")
    cleaned = [i.strip() for i in (ids or []) if (i or "").strip()]
    if not cleaned:
        out["error"] = "ids is required — identifiers with their scheme prefix"
        return out

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for start in range(0, len(cleaned), METADATA_BATCH):
        batch = cleaned[start:start + METADATA_BATCH]
        payload, error = _get_json(f"{META}/metadata/{'__'.join(batch)}")
        if error:
            errors.append(error)
            continue
        results.extend(_normalize_meta(r) for r in payload
                       if isinstance(payload, list) and isinstance(r, dict))

    out["results"] = results
    out["returned"] = len(results)
    out["total_found"] = len(results)
    if errors:
        out["error"] = "; ".join(errors)
    return out


def list_works_by_person(
    person_id: str,
    role: str = "author",
    max_results: int = 25,
) -> dict:
    """
    List the works an ORCID is attached to, as author or as editor.

    The only listing operation OpenCitations offers, and the only tool here that
    starts from a person rather than a work. Matching is on the identifier, not
    on a name, so it never suffers the homonym problem — but it only covers what
    the index has linked to that ORCID.

    Args:
        person_id: "orcid:0000-0003-0530-4305" or a Meta agent OMID, "omid:ra/0605". A bare name is not accepted; there is no name search.
        role: Which role to list — "author" or "editor". They are different upstream endpoints.
        max_results: Clamp applied after the download, 1-25 on this demo endpoint.

    Returns:
        {"source": "opencitations", "command": "list_works_by_person", "person_id": str, "role": str, "total_found": int | null, "returned": int, "results": [ /* Meta records, same shape as lookup_metadata */ ], "error": str | null}
    """
    identifier = (person_id or "").strip()
    role = (role or "author").strip() or "author"
    out = _envelope("list_works_by_person", person_id=identifier, role=role)
    if not identifier:
        out["error"] = "person_id is required — an ORCID or a Meta agent OMID"
        return out
    if role not in ("author", "editor"):
        out["error"] = 'role must be "author" or "editor"'
        return out

    rows = max(1, min(int(max_results or 25), MAX_RESULTS))
    payload, error = _get_json(f"{META}/{role}/{identifier}")
    if error:
        out["error"] = error
        return out

    records = [_normalize_meta(r) for r in payload if isinstance(r, dict)] \
        if isinstance(payload, list) else []
    out["total_found"] = len(records)
    out["results"] = records[:rows]
    out["returned"] = len(out["results"])
    return out


# ── Presentation ──────────────────────────────────────────────────────────────


def _render_counts(payload: dict) -> str:
    results = payload.get("results") or []
    if not results:
        return "_Aucun identifiant._"
    lines = ["| Identifiant | Citations reçues | Références |", "|---|---|---|"]
    for r in results:
        url = r.get("url")
        ident = r.get("id") or "—"
        lines.append(
            "| {ident} | {cit} | {ref} |".format(
                ident=f"[{ident}]({url})" if url else ident,
                cit=r.get("citation_count") if r.get("citation_count") is not None else "—",
                ref=r.get("reference_count") if r.get("reference_count") is not None else "—",
            )
        )
    return "\n".join(lines)


def _render_edges(payload: dict, side: str) -> str:
    """side is "citing" (works citing this one) or "cited" (works it cites)."""
    kind = "citations" if side == "citing" else "références"
    column = "Œuvre citante" if side == "citing" else "Œuvre citée"
    results = payload.get("results") or []
    header = (f"**{payload.get('returned', 0)} arêtes affichées sur "
              f"{payload.get('total_found', '?')} {kind}** — `{payload.get('id')}`")
    excluded = payload.get("excluded_self_citations")
    if excluded is not None:
        header += f" — {excluded} auto-citations écartées"
    if not results:
        return header + f"\n\n_Aucune {kind[:-1]}._"
    lines = [header, "", f"| {column} | Date | Écart | Auto-citation |", "|---|---|---|---|"]
    for r in results:
        work = r.get(f"{side}_work") or {}
        label = (work.get("title") or r.get(side, {}).get("doi")
                 or r.get(side, {}).get("omid") or "—")
        url = work.get("url") or r.get("url")
        days = r.get("timespan_days")
        sc = "journal" if r.get("journal_sc") == "yes" else ""
        if r.get("author_sc") == "yes":
            sc = (sc + " auteur").strip()
        lines.append(
            "| {label} | {date} | {days} | {sc} |".format(
                label=f"[{str(label).replace('|', chr(92) + '|')}]({url})" if url else label,
                date=r.get("creation") or "—",
                days=f"{days} j" if days is not None else "—",
                sc=sc or "—",
            )
        )
    return "\n".join(lines)


def _run_counts(ids_text):
    payload = get_citation_counts([i.strip() for i in (ids_text or "").split(",") if i.strip()])
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render_counts(payload), payload


def _render_meta(payload: dict) -> str:
    results = payload.get("results") or []
    if not results:
        return "_Aucune notice._"
    lines = ["| Titre | Auteurs | Année | Revue | DOI |", "|---|---|---|---|---|"]
    for r in results:
        names = [a.get("name") for a in (r.get("authors") or []) if a.get("name")]
        authors = ", ".join(names[:3]) or "—"
        if len(names) > 3:
            authors += " et al."
        doi = r.get("doi")
        title = (r.get("title") or "Sans titre").replace("|", "\\|")
        url = r.get("url")
        lines.append(
            "| {title} | {authors} | {year} | {journal} | {doi} |".format(
                title=f"[{title}]({url})" if url else title,
                authors=authors.replace("|", "\\|"),
                year=r.get("year") or "—",
                journal=(r.get("journal") or "—").replace("|", "\\|"),
                doi=f"[{doi}](https://doi.org/{doi})" if doi else "—",
            )
        )
    return "\n".join(lines)


def _run_citations(id_value, max_results, sort, exclude_self_citations, hydrate):
    payload = get_citations(id_value, max_results, sort or None,
                            exclude_self_citations, hydrate)
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render_edges(payload, "citing"), payload


def _run_references(id_value, max_results, sort, exclude_self_citations, hydrate):
    payload = get_references(id_value, max_results, sort or None,
                             exclude_self_citations, hydrate)
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render_edges(payload, "cited"), payload


def _run_metadata(ids_text):
    payload = lookup_metadata(
        [i.strip() for i in (ids_text or "").replace("\n", ",").split(",") if i.strip()])
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render_meta(payload), payload


def _run_person(person_id, role, max_results):
    payload = list_works_by_person(person_id, role, max_results)
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render_meta(payload), payload


# ── UI ────────────────────────────────────────────────────────────────────────

with gr.Blocks(title="OpenCitations MCP demo") as demo:
    gr.Markdown(
        "# OpenCitations MCP demo\n"
        "Démo autonome du serveur MCP "
        "[`opencitations`](https://github.com/smartbiblia-solutions/agentic-stack/tree/main/mcp/opencitations) "
        ", les données ouvertes de citation (Index v2) et les métadonnées "
        "bibliographiques CC0 (Meta v1).\n\n"
        "OpenCitations **n'a pas de recherche** : tout part d'un identifiant "
        "connu — DOI, PMID ou OMID. Commencez par les comptes : une œuvre très "
        "citée ne peut pas être listée."
    )

    with gr.Tab("Comptes"):
        ids_text = gr.Textbox(
            label="Identifiants (séparés par des virgules)",
            value="doi:10.1108/jd-12-2013-0166",
            placeholder="doi:10.1108/jd-12-2013-0166, pmid:2942070",
        )
        counts_btn = gr.Button("Compter", variant="primary")
        counts_out = gr.Markdown()
        counts_raw = gr.JSON(label="Sortie brute de l'outil")

        gr.Examples(
            examples=[
                ["doi:10.1108/jd-12-2013-0166"],
                ["doi:10.1108/jd-12-2013-0166, pmid:2942070"],
                ["omid:br/0601"],
            ],
            inputs=[ids_text],
            label="Un DOI, un lot de deux schémas, puis un OMID",
        )
        counts_btn.click(_run_counts, inputs=[ids_text],
                         outputs=[counts_out, counts_raw], api_name=False)

    with gr.Tab("Citations reçues"):
        id_value = gr.Textbox(label="Identifiant", value="doi:10.1108/jd-12-2013-0166",
                              placeholder="doi:… , pmid:… ou omid:br/…")
        with gr.Row():
            max_results = gr.Slider(1, MAX_RESULTS, value=10, step=1, label="Résultats")
            sort = gr.Dropdown([""] + list(SORT_VALUES), value="", label="Tri (côté client)")
        with gr.Row():
            exclude_self = gr.Checkbox(label="Exclure les auto-citations", value=False)
            hydrate = gr.Checkbox(label="Récupérer les métadonnées citantes "
                                        "(1 requête par 10 œuvres)", value=False)
        citations_btn = gr.Button("Lister", variant="primary")
        citations_out = gr.Markdown()
        citations_raw = gr.JSON(label="Sortie brute de l'outil")

        citations_inputs = [id_value, max_results, sort, exclude_self, hydrate]

        gr.Examples(
            examples=[
                ["doi:10.1108/jd-12-2013-0166", 10, "creation-desc", False, True],
                ["doi:10.1108/jd-12-2013-0166", 10, "timespan_days-asc", True, False],
                ["pmid:2942070", 5, "creation-asc", False, False],
            ],
            inputs=citations_inputs,
            label="Avec métadonnées, puis trié par écart et sans auto-citations, "
                  "puis à partir d'un PMID",
        )
        citations_btn.click(_run_citations, inputs=citations_inputs,
                            outputs=[citations_out, citations_raw], api_name=False)

    with gr.Tab("Références citées"):
        gr.Markdown(
            "Le sens inverse : la bibliographie telle qu'OpenCitations la "
            "connaît, c'est-à-dire telle que l'éditeur l'a déposée — elle peut "
            "être plus courte que la bibliographie imprimée."
        )
        ref_id = gr.Textbox(label="Identifiant", value="doi:10.1108/jd-12-2013-0166",
                            placeholder="doi:… , pmid:… ou omid:br/…")
        with gr.Row():
            ref_max = gr.Slider(1, MAX_RESULTS, value=10, step=1, label="Résultats")
            ref_sort = gr.Dropdown([""] + list(SORT_VALUES), value="", label="Tri (côté client)")
        with gr.Row():
            ref_exclude = gr.Checkbox(label="Exclure les auto-citations", value=False)
            ref_hydrate = gr.Checkbox(label="Récupérer les métadonnées citées "
                                            "(1 requête par 10 œuvres)", value=False)
        ref_btn = gr.Button("Lister", variant="primary")
        ref_out = gr.Markdown()
        ref_raw = gr.JSON(label="Sortie brute de l'outil")

        ref_inputs = [ref_id, ref_max, ref_sort, ref_exclude, ref_hydrate]

        gr.Examples(
            examples=[
                ["doi:10.1108/jd-12-2013-0166", 10, "", False, True],
                ["doi:10.1108/jd-12-2013-0166", 25, "creation-asc", False, False],
            ],
            inputs=ref_inputs,
            label="La bibliographie avec ses titres, puis la même dans l'ordre "
                  "chronologique",
        )
        ref_btn.click(_run_references, inputs=ref_inputs,
                      outputs=[ref_out, ref_raw], api_name=False)

    with gr.Tab("Métadonnées"):
        gr.Markdown(
            "OpenCitations Meta : une notice citable sous CC0 pour un "
            "identifiant. **Pas de résumé ni de texte intégral** — `abstract` "
            "est toujours `null`. Un ISSN renvoie la revue elle-même, jamais ses "
            "articles."
        )
        meta_ids = gr.Textbox(
            label="Identifiants (virgules ou retours à la ligne)",
            value="doi:10.1108/jd-12-2013-0166",
            placeholder="doi:… , pmid:… , pmcid:… , isbn:… , issn:… , openalex:… , omid:br/…",
        )
        meta_btn = gr.Button("Résoudre", variant="primary")
        meta_out = gr.Markdown()
        meta_raw = gr.JSON(label="Sortie brute de l'outil")

        gr.Examples(
            examples=[
                ["doi:10.1108/jd-12-2013-0166"],
                ["doi:10.1108/jd-12-2013-0166, pmid:2942070"],
                ["issn:0022-0418"],
            ],
            inputs=[meta_ids],
            label="Un DOI, un lot mêlant DOI et PMID, puis un ISSN (la revue, "
                  "pas ses articles)",
        )
        meta_btn.click(_run_metadata, inputs=[meta_ids],
                       outputs=[meta_out, meta_raw], api_name=False)

    with gr.Tab("Œuvres d'une personne"):
        gr.Markdown(
            "La seule opération de listage d'OpenCitations, et la seule qui "
            "parte d'une personne. L'appariement se fait sur l'identifiant, "
            "jamais sur un nom : pas d'homonymie, mais rien non plus hors de ce "
            "que l'index a rattaché à cet ORCID."
        )
        person_id = gr.Textbox(label="ORCID ou OMID d'agent",
                               value="orcid:0000-0003-0530-4305",
                               placeholder="orcid:0000-… ou omid:ra/…")
        with gr.Row():
            person_role = gr.Radio(["author", "editor"], value="author", label="Rôle")
            person_max = gr.Slider(1, MAX_RESULTS, value=10, step=1, label="Résultats")
        person_btn = gr.Button("Lister", variant="primary")
        person_out = gr.Markdown()
        person_raw = gr.JSON(label="Sortie brute de l'outil")

        gr.Examples(
            examples=[
                ["orcid:0000-0003-0530-4305", "author", 10],
                ["orcid:0000-0003-0530-4305", "editor", 10],
            ],
            inputs=[person_id, person_role, person_max],
            label="Le même ORCID comme auteur, puis comme éditeur scientifique",
        )
        person_btn.click(_run_person, inputs=[person_id, person_role, person_max],
                         outputs=[person_out, person_raw], api_name=False)

    # The only declared MCP tools. Names match the canonical server's.
    gr.api(get_citation_counts, api_name="get_citation_counts")
    gr.api(get_citations, api_name="get_citations")
    gr.api(get_references, api_name="get_references")
    gr.api(lookup_metadata, api_name="lookup_metadata")
    gr.api(list_works_by_person, api_name="list_works_by_person")


if __name__ == "__main__":
    demo.launch(
        theme=gr.themes.Soft(),  # Gradio 6 moved theme from Blocks() to launch()
        server_name=os.getenv("GRADIO_SERVER_NAME", "0.0.0.0"),
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
        mcp_server=os.getenv("GRADIO_MCP_SERVER", "true").lower() == "true",
    )
