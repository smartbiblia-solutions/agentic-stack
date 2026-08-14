#!/usr/bin/env python3
"""
Standalone Gradio demo of the theses.fr MCP server, deployable as a Hugging
Face Space.

The five tools mirror the canonical `mcp_server.py` — same names, same
arguments, same envelope. The only deliberate narrowing is `max_results`,
clamped to 10 instead of 200.

Local run:
    uv run --with 'gradio[mcp]>=6,<7' --with httpx app.py

Environment:
    THESES_FR_API_URL   API base URL (default the public theses.fr API)
    GRADIO_SERVER_NAME  bind address (default 0.0.0.0)
    GRADIO_SERVER_PORT  port (default 7860)
    GRADIO_MCP_SERVER   "false" disables the demo MCP endpoint (default true)
"""

from __future__ import annotations

import os
import urllib.parse
from typing import Any

import gradio as gr
import httpx

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_URL = os.environ.get("THESES_FR_API_URL", "https://theses.fr/api/v1").rstrip("/")

USER_AGENT = "smartbiblia-theses-fr-demo/0.1"

STATUS_VALUES = ("soutenue", "enCours")
ACCESSIBLE_VALUES = ("oui", "non")
TRI_VALUES = ("pertinence", "dateDesc", "dateAsc", "auteursAsc", "auteursDesc",
              "disciplineAsc", "disciplineDesc")
ORGANISME_ROLES = ("etabSoutenance", "etabCotutelle",
                   "partenaireRecherche", "ecoleDoctorale")

PERSONS_URL = "personnes"

# A Space has no command line: connector policy is constant here.
REQUEST_TIMEOUT = 20.0

# Clamped harder than the canonical server: this endpoint is public, and each
# hydrated hit costs one extra upstream request.
MAX_RESULTS = 10

# One module-level pooled client for the process.
HTTP = httpx.Client(
    timeout=REQUEST_TIMEOUT,
    follow_redirects=True,
    headers={"Accept": "application/json", "User-Agent": USER_AGENT},
)


def _get(path: str, params: list[tuple[str, str]] | None = None) -> tuple[Any, str | None]:
    """GET returning (payload, error). Never raises — the demo answers with data."""
    url = f"{BASE_URL}/{path.lstrip('/')}"
    try:
        resp = HTTP.get(url, params=params or [])
        resp.raise_for_status()
        # An unknown identifier answers 200 with an empty body rather than a
        # 404, so emptiness is the only "not found" signal there is.
        if not resp.content.strip():
            return None, "No record found (empty response)"
        return resp.json(), None
    except httpx.HTTPStatusError as exc:
        return None, f"theses.fr returned HTTP {exc.response.status_code}"
    except httpx.TimeoutException:
        return None, f"theses.fr timed out after {REQUEST_TIMEOUT:g}s"
    except Exception as exc:  # noqa: BLE001 - never crash the Space
        return None, f"cannot reach theses.fr: {exc}"


def _get_text(path: str) -> tuple[str | None, str | None]:
    """GET a plain-text endpoint returning (text, error). An empty body is 'not found'."""
    url = f"{BASE_URL}/{path.lstrip('/')}"
    try:
        resp = HTTP.get(url)
        resp.raise_for_status()
        text = (resp.text or "").strip()
        return (text, None) if text else (None, "empty response")
    except httpx.HTTPStatusError as exc:
        return None, f"theses.fr returned HTTP {exc.response.status_code}"
    except httpx.TimeoutException:
        return None, f"theses.fr timed out after {REQUEST_TIMEOUT:g}s"
    except Exception as exc:  # noqa: BLE001 - never crash the Space
        return None, f"cannot reach theses.fr: {exc}"


def _clean(v: Any) -> str | None:
    if isinstance(v, list):
        v = v[0] if v else None
    if v is None:
        return None
    return str(v).strip() or None


def _year(date: str | None) -> int | None:
    """dateSoutenance is DD/MM/YYYY, and null for a thesis still in progress."""
    if not date or len(date) < 4:
        return None
    try:
        return int(date[-4:])
    except ValueError:
        return None


def _names(people: Any) -> list[str]:
    out: list[str] = []
    for p in people or []:
        if isinstance(p, dict):
            full = f"{(p.get('prenom') or '').strip()} {(p.get('nom') or '').strip()}".strip()
            if full:
                out.append(full)
    return out


def _keywords(t: dict) -> list[str]:
    """Free keywords and Rameau headings, merged — both ride along on the hit."""
    out: list[str] = []
    for s in (t.get("sujets") or []) + (t.get("sujetsRameau") or []):
        label = _clean(s.get("libelle")) if isinstance(s, dict) else None
        if label and label not in out:
            out.append(label)
    return out


def _normalize_hit(t: dict) -> dict:
    ident = t.get("nnt") or t.get("id")
    date = _clean(t.get("dateSoutenance"))
    return {
        "source": "theses-fr",
        "id": ident,
        "nnt": t.get("nnt"),
        "title": _clean(t.get("titrePrincipal")),
        "title_en": _clean(t.get("titreEN")),
        "authors": _names(t.get("auteurs")),
        "directors": _names(t.get("directeurs")),
        "abstract": None,          # absent from search hits — hydrate, or get_thesis
        "doi": _clean(t.get("doi")),
        "year": _year(date),
        "date": date,
        "doc_type": "thesis",
        "journal": None,
        "institution": _clean(t.get("etabSoutenanceN")),
        "institution_ppn": _clean(t.get("etabSoutenancePpn")),
        "discipline": _clean(t.get("discipline")),
        "keywords": _keywords(t),
        "status": _clean(t.get("status")),
        "url": f"https://theses.fr/{ident}" if ident else None,
    }


def _normalize_person(p: dict) -> dict:
    return {
        "source": "theses-fr",
        "id": p.get("id"),
        "label": f"{(p.get('prenom') or '').strip()} {(p.get('nom') or '').strip()}".strip(),
        "roles": p.get("roles") or {},
        "has_idref": p.get("has_idref"),
        "theses": p.get("theses") or [],
        "url": f"https://theses.fr/personne/{p.get('id')}" if p.get("id") else None,
        "raw": p,
    }


def _normalize_detail(d: dict) -> dict:
    ident = d.get("nnt") or d.get("numSujet")
    resumes = d.get("resumes") or {}
    titres = d.get("titres") or {}
    date = _clean(d.get("dateSoutenance"))
    etab = d.get("etabSoutenance") or {}
    return {
        "source": "theses-fr",
        "id": ident,
        "nnt": d.get("nnt"),
        "title": _clean(d.get("titrePrincipal")) or _clean(titres.get("fr")) or _clean(titres.get("en")),
        "titles": {k: _clean(v) for k, v in titres.items()},
        "authors": _names(d.get("auteurs")),
        "directors": _names(d.get("directeurs")),
        # English preferred for downstream NLP, French as the fallback.
        "abstract": _clean(resumes.get("en")) or _clean(resumes.get("fr")),
        "abstracts": {k: _clean(v) for k, v in resumes.items()},
        "doi": _clean(d.get("doi")),
        "year": _year(date),
        "date": date,
        "doc_type": "thesis",
        "journal": None,
        "institution": etab.get("nom") if isinstance(etab, dict) else _clean(etab),
        "institution_ppn": etab.get("ppn") if isinstance(etab, dict) else None,
        "code_etab": _clean(d.get("codeEtab")),
        "discipline": _clean(d.get("discipline")),
        "languages": d.get("langues") or [],
        "status": _clean(d.get("status")),
        # "oui" only ever for a defended thesis: the full text is online.
        "accessible": d.get("accessible"),
        "url": f"https://theses.fr/{ident}" if ident else None,
    }


# ── MCP tools (the only functions exposed with gr.api) ────────────────────────


def search_theses(
    query: str = "",
    establishment: str | None = None,
    discipline: str | None = None,
    domain: str | None = None,
    author: str | None = None,
    director: str | None = None,
    language: str | None = None,
    accessible: str | None = None,
    status: str | None = None,
    max_results: int = 5,
    sort: str | None = None,
    hydrate: bool = False,
) -> dict:
    """
    Search theses.fr for French doctoral theses, defended or in preparation.

    Args:
        query: Raw Lucene query, e.g. "titrePrincipal:(informatique)". Empty matches everything.
        establishment: Establishment short code, e.g. "COAZ" — compiled to codeEtab:(COAZ), which also finds theses in preparation.
        discipline: Discipline, free text, e.g. "informatique".
        domain: Thematic domain, one of the controlled "Domaines thématiques" labels, e.g. "Informatique".
        author: Author name tokens, e.g. "Benoît Audelan". Never quoted upstream.
        director: Supervisor name tokens, e.g. "Frédéric Precioso".
        language: ISO code of the writing language, e.g. "fr" or "en".
        accessible: "oui" for theses whose full text is online, "non" otherwise. Defended theses only.
        status: "soutenue" (defended) or "enCours" (in preparation). Empty for both.
        max_results: Number of theses to return, 1-10 on this demo endpoint.
        sort: Ordering — "pertinence", "dateDesc", "dateAsc", "auteursAsc", "auteursDesc", "disciplineAsc" or "disciplineDesc".
        hydrate: Fetch each hit's résumé, which the search index does not carry. One extra request per hit.

    Returns:
        {"source": "theses-fr", "command": "search_theses", "query_used": str, "total_found": int | null, "returned": int, "results": [{"source": str, "id": str, "title": str, "authors": [str], "abstract": str | null, "doi": str | null, "year": int | null, "institution": str | null, "keywords": [str], "url": str}], "hydrated": bool, "error": str | null}
    """
    out: dict = {
        "source": "theses-fr", "command": "search_theses", "query_used": "*",
        "total_found": None, "returned": 0, "results": [],
        "hydrated": bool(hydrate), "error": None,
    }

    if status and status not in STATUS_VALUES:
        out["error"] = "status must be one of " + ", ".join(STATUS_VALUES)
        return out
    if accessible and accessible not in ACCESSIBLE_VALUES:
        out["error"] = "accessible must be one of " + ", ".join(ACCESSIBLE_VALUES)
        return out
    if sort and sort not in TRI_VALUES:
        out["error"] = "sort must be one of " + ", ".join(TRI_VALUES)
        return out

    # theses.fr's own `filtres` parameter is inert; every constraint goes into q.
    # Quoting is per-field: a controlled label like oaiSetNames must be quoted,
    # a person-name field must not — its tokens are stored in no fixed order.
    clauses = []
    if query and query.strip():
        clauses.append(f"({query.strip()})")
    if establishment:
        clauses.append(f"codeEtab:({establishment.upper()})")   # case-sensitive upstream
    if discipline:
        clauses.append(f"discipline:({discipline})")
    if domain:
        clauses.append(f'oaiSetNames:("{domain}")')
    if author:
        clauses.append(f"auteursNP:({author})")
    if director:
        clauses.append(f"directeursNP:({director})")
    if language:
        clauses.append(f"langues:({language})")
    if accessible:
        clauses.append(f"accessible:({accessible})")
    if status:
        clauses.append(f"status:({status})")
    q = " AND ".join(clauses) if clauses else "*"
    out["query_used"] = q

    rows = max(1, min(int(max_results or 5), MAX_RESULTS))
    params = [("q", q), ("nombre", str(rows)), ("debut", "0")]
    if sort:
        params.append(("tri", sort))
    data, error = _get("theses/recherche/", params)
    if error or not isinstance(data, dict):
        out["error"] = error or "unexpected response shape from theses.fr"
        return out

    results = [_normalize_hit(t) for t in data.get("theses") or [] if isinstance(t, dict)]
    out["total_found"] = data.get("totalHits")

    if hydrate:
        for r in results:
            ident = r.get("id")
            if not ident:
                continue
            detail, d_error = _get(f"theses/these/{urllib.parse.quote(str(ident))}")
            if d_error or not isinstance(detail, dict):
                r["hydrate_error"] = d_error or "unexpected record response shape"
                continue
            normalized = _normalize_detail(detail)
            r["abstract"] = normalized["abstract"]
            r["abstracts"] = normalized["abstracts"]

    out["returned"] = len(results)
    out["results"] = results
    return out


def get_thesis(id: str) -> dict:
    """
    Fetch one theses.fr record, including its bilingual résumés.

    Args:
        id: NNT, e.g. "2021COAZ4028", or subject number of a thesis in preparation, e.g. "s68236".

    Returns:
        {"source": "theses-fr", "command": "get_thesis", "query_used": str, "total_found": null, "returned": int, "results": [{"source": str, "id": str, "title": str, "titles": object, "authors": [str], "abstract": str | null, "abstracts": object, "doi": str | null, "year": int | null, "institution": str | null, "url": str}], "error": str | null}
    """
    out: dict = {
        "source": "theses-fr", "command": "get_thesis", "query_used": id,
        "total_found": None, "returned": 0, "results": [], "error": None,
    }
    if not id or not id.strip():
        out["error"] = "id is required — an NNT or a subject number"
        return out

    data, error = _get(f"theses/these/{urllib.parse.quote(id.strip())}")
    if error or not isinstance(data, dict):
        out["error"] = error or "unexpected response shape from theses.fr"
        return out
    out["returned"] = 1
    out["results"] = [_normalize_detail(data)]
    return out


def search_persons(query: str, max_results: int = 10, start: int = 0) -> dict:
    """
    Search the theses.fr person index: authors, supervisors, rapporteurs and jury members.

    Use this to find a doctoral supervisor and the theses they took part in — the thesis index has no working author-name field, so this is the only reliable path from a name to the records.

    Args:
        query: Free-text name, e.g. "Precioso". A surname alone works best.
        max_results: Number of people to return, 1-10 on this demo endpoint.
        start: Offset into the result set, for paging.

    Returns:
        {"source": "theses-fr", "command": "search_persons", "query_used": str, "total_found": int | null, "returned": int, "results": [{"source": str, "id": str, "label": str, "roles": object, "has_idref": bool, "theses": [str], "url": str | null}], "error": str | null}
    """
    out: dict = {
        "source": "theses-fr", "command": "search_persons", "query_used": query,
        "total_found": None, "returned": 0, "results": [], "error": None,
    }
    if not (query or "").strip():
        out["error"] = "query is required — a person's name"
        return out

    rows = max(1, min(int(max_results or 10), MAX_RESULTS))
    params = [("q", query.strip()), ("nombre", str(rows)), ("debut", str(max(0, int(start or 0))))]
    data, error = _get(f"{PERSONS_URL}/recherche/", params)
    if error or not isinstance(data, dict):
        out["error"] = error or "unexpected response shape from theses.fr"
        return out

    people = [p for p in data.get("personnes") or [] if isinstance(p, dict)]
    out["total_found"] = data.get("totalHits")
    out["returned"] = len(people)
    out["results"] = [_normalize_person(p) for p in people]
    return out


def list_facets(query: str = "*", limit: int = 25) -> dict:
    """
    List the facet values a query accepts, with their counts.

    Use it before filtering by establishment, doctoral school or discipline: those fields are matched on their exact label, and no reference endpoint enumerates them. Counts are relative to `query`. Facets returned upstream: Statut, Établissements, Écoles doctorales, Domaines thématiques, Disciplines, Langues.

    Args:
        query: The query the facets are counted over. "*" covers the whole corpus.
        limit: Maximum buckets per facet; 0 returns every one.

    Returns:
        {"source": "theses-fr", "command": "list_facets", "query_used": str, "total_found": int, "returned": int, "results": [{"source": str, "id": str, "label": str, "url": null, "buckets": [{"value": str, "count": int}]}], "error": str | null}
    """
    out: dict = {
        "source": "theses-fr", "command": "list_facets", "query_used": query or "*",
        "total_found": 0, "returned": 0, "results": [], "error": None,
    }

    data, error = _get("theses/facets/", [("q", (query or "*").strip() or "*")])
    if error or not isinstance(data, list):
        out["error"] = error or "unexpected response shape from theses.fr"
        return out

    lim = int(limit or 0)
    results = []
    for facet in data:
        if not isinstance(facet, dict):
            continue
        buckets = [{"value": c.get("name"), "count": c.get("value")}
                   for c in facet.get("checkboxes") or [] if isinstance(c, dict)]
        results.append({
            "source": "theses-fr", "id": facet.get("name"),
            "label": facet.get("name"), "url": None,
            "buckets": buckets[:lim] if lim > 0 else buckets,
        })
    out["total_found"] = len(results)
    out["returned"] = len(results)
    out["results"] = results
    return out


def search_by_organisme(ppn: str, role: str | None = None) -> dict:
    """
    List an organisation's theses, grouped by the role it played in each.

    Use this for an establishment's full doctoral footprint — the one view a query cannot assemble. search_theses(establishment=…) only ever finds the *awarding* establishment; this endpoint also returns the theses where the organisation was a cotutelle partner, a research partner (a laboratory) or the doctoral school.

    `ppn` is the organisation's IdRef PPN — the `institution_ppn` of any of its records — not the short `codeEtab`. Upstream caps every role bucket at 100 records whatever its counter says, so `total_found` is routinely far larger than `returned`; read `totals` for the true per-role figures. A person's PPN answers 200 with every bucket empty, so this tool resolves the organisation's name first and reports `error` when there is none.

    Args:
        ppn: IdRef PPN of the organisation, e.g. "241035694".
        role: Keep a single role — etabSoutenance, etabCotutelle, partenaireRecherche or ecoleDoctorale. Empty for all four.

    Returns:
        {"source": "theses-fr", "command": "search_by_organisme", "query_used": str, "total_found": int, "returned": int, "results": [<same record shape as search_theses, each with "role" and "in_progress">], "organisme": {"ppn": str, "name": str | null}, "totals": object, "role": str | null, "error": str | null}
    """
    out: dict = {
        "source": "theses-fr", "command": "search_by_organisme", "query_used": ppn,
        "total_found": 0, "returned": 0, "results": [],
        "organisme": {"ppn": ppn, "name": None}, "totals": {},
        "role": role or None, "error": None,
    }

    ppn = (ppn or "").strip()
    if not ppn:
        out["error"] = "ppn is required — the organisation's IdRef PPN"
        return out
    if role and role not in ORGANISME_ROLES:
        out["error"] = "role must be one of " + ", ".join(ORGANISME_ROLES)
        return out

    name, name_error = _get_text(f"theses/getorganismename/{urllib.parse.quote(ppn)}")
    if name_error is not None:
        out["error"] = (f"No organisation found for PPN {ppn} — getorganismename "
                        "returned nothing, so this PPN is probably a person; "
                        "try search_persons.")
        return out
    out["organisme"]["name"] = _clean(name)

    data, error = _get(f"theses/organisme/{urllib.parse.quote(ppn)}")
    if error or not isinstance(data, dict):
        out["error"] = error or "unexpected response shape from theses.fr"
        return out

    roles = (role,) if role else ORGANISME_ROLES
    results: list[dict] = []
    total = 0
    for r in roles:
        for key, in_progress in ((r, False), (f"{r}EnCours", True)):
            count = data.get(f"totalHits{key}")
            if isinstance(count, int):
                out["totals"][key] = count
                total += count
            for t in data.get(key) or []:
                if not isinstance(t, dict):
                    continue
                record = _normalize_hit(t)
                record["role"] = r
                record["in_progress"] = in_progress
                results.append(record)

    out["total_found"] = total
    out["returned"] = len(results)
    out["results"] = results
    return out


# ── Presentation ──────────────────────────────────────────────────────────────


def _render_search(payload: dict) -> str:
    results = payload.get("results") or []
    if not results:
        return "_Aucune thèse ne correspond._"
    lines = [
        f"**{payload.get('returned', len(results))} sur {payload.get('total_found', '?')} thèses** "
        f"— `{payload.get('query_used')}`",
        "",
        "| Titre | Auteur·rice | Établissement | Soutenance |",
        "|---|---|---|---|",
    ]
    for r in results:
        title = (r.get("title") or "Sans titre").replace("|", "\\|")
        url = r.get("url")
        authors = ", ".join(r.get("authors") or []) or "—"
        lines.append(
            "| {title} | {authors} | {etab} | {date} |".format(
                title=f"[{title}]({url})" if url else title,
                authors=authors.replace("|", "\\|"),
                etab=(r.get("institution") or "—").replace("|", "\\|"),
                date=r.get("date") or "en cours",
            )
        )
    if payload.get("hydrated"):
        first = next((r for r in results if r.get("abstract")), None)
        if first:
            lines += ["", "**Résumé du premier résultat**", "", first["abstract"][:1200]]
    return "\n".join(lines)


def _render_detail(payload: dict) -> str:
    results = payload.get("results") or []
    if not results:
        return "_Aucun enregistrement._"
    r = results[0]
    lines = [
        f"### {r.get('title') or 'Sans titre'}",
        "",
        f"- **Auteur·rice** : {', '.join(r.get('authors') or []) or '—'}",
        f"- **Direction** : {', '.join(r.get('directors') or []) or '—'}",
        f"- **Établissement** : {r.get('institution') or '—'}",
        f"- **Discipline** : {r.get('discipline') or '—'}",
        f"- **Soutenance** : {r.get('date') or 'en cours'}",
        f"- **DOI** : {r.get('doi') or '—'}",
        f"- **theses.fr** : {r.get('url') or '—'}",
    ]
    for lang, text in (r.get("abstracts") or {}).items():
        if text:
            lines += ["", f"**Résumé ({lang})**", "", text[:2000]]
    return "\n".join(lines)


def _render_persons(payload: dict) -> str:
    results = payload.get("results") or []
    if not results:
        return "_Aucune personne ne correspond._"
    lines = [
        f"**{payload.get('returned', len(results))} sur {payload.get('total_found', '?')} personnes**",
        "",
        "| Personne | IdRef | Rôles | Thèses |",
        "|---|---|---|---|",
    ]
    for r in results:
        roles = ", ".join(f"{k} ({v})" for k, v in (r.get("roles") or {}).items()) or "—"
        label = (r.get("label") or "—").replace("|", "\\|")
        url = r.get("url")
        lines.append(
            "| {label} | {idref} | {roles} | {n} |".format(
                label=f"[{label}]({url})" if url else label,
                idref=r.get("id") if r.get("has_idref") else "—",
                roles=roles.replace("|", "\\|"),
                n=len(r.get("theses") or []),
            )
        )
    lines += ["", "_Les identifiants listés sous `theses` se passent tels quels à `get_thesis`._"]
    return "\n".join(lines)


def _render_facets(payload: dict) -> str:
    results = payload.get("results") or []
    if not results:
        return "_Aucune facette._"
    lines = [f"**{len(results)} facettes** — `{payload.get('query_used')}`", ""]
    for f in results:
        buckets = f.get("buckets") or []
        lines += [f"### {f.get('label')} ({len(buckets)} valeurs affichées)", "",
                  "| Valeur | Thèses |", "|---|---|"]
        for b in buckets:
            lines.append(
                "| {v} | {c} |".format(
                    v=str(b.get("value") or "—").replace("|", "\\|"),
                    c=b.get("count") if b.get("count") is not None else "—",
                )
            )
        lines.append("")
    lines.append("_Une valeur se recopie telle quelle dans les champs Établissement, "
                 "Discipline ou Domaine de l'onglet Recherche._")
    return "\n".join(lines)


def _render_organisme(payload: dict) -> str:
    org = payload.get("organisme") or {}
    totals = payload.get("totals") or {}
    lines = [
        f"### {org.get('name') or '—'}",
        "",
        f"PPN `{org.get('ppn')}` — **{payload.get('total_found', 0)} thèses** au total, "
        f"{payload.get('returned', 0)} rapatriées (l'API plafonne chaque rôle à 100).",
        "",
        "| Rôle | Thèses |",
        "|---|---|",
    ]
    for k, v in totals.items():
        lines.append(f"| `{k}` | {v} |")
    results = payload.get("results") or []
    if results:
        lines += ["", "| Rôle | Titre | Soutenance |", "|---|---|---|"]
        for r in results[:25]:
            title = (r.get("title") or "Sans titre").replace("|", "\\|")
            url = r.get("url")
            lines.append(
                "| {role} | {title} | {date} |".format(
                    role=r.get("role") or "—",
                    title=f"[{title}]({url})" if url else title,
                    date=r.get("date") or "en cours",
                )
            )
        if len(results) > 25:
            lines.append(f"| … | _{len(results) - 25} de plus dans la sortie brute_ | |")
    return "\n".join(lines)


def _run_search(query, establishment, discipline, domain, author, director,
                language, accessible, status, max_results, sort, hydrate):
    payload = search_theses(query, establishment or None, discipline or None,
                            domain or None, author or None, director or None,
                            language or None, accessible or None, status or None,
                            max_results, sort or None, hydrate)
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render_search(payload), payload


def _run_get(id_value):
    payload = get_thesis(id_value)
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render_detail(payload), payload


def _run_persons(query, max_results):
    payload = search_persons(query, int(max_results))
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render_persons(payload), payload


def _run_facets(query, limit):
    payload = list_facets(query, int(limit))
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render_facets(payload), payload


def _run_organisme(ppn_value, role):
    payload = search_by_organisme(ppn_value, role or None)
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render_organisme(payload), payload


# ── UI ────────────────────────────────────────────────────────────────────────

with gr.Blocks(title="theses.fr MCP demo") as demo:
    gr.Markdown(
        "# theses.fr MCP demo\n"
        "Démo autonome du serveur MCP "
        "[`theses-fr`](https://github.com/smartbiblia-solutions/agentic-stack/tree/main/mcp/theses-fr) "
        ", le registre national des thèses de doctorat françaises (ABES).\n\n"
        "Les résultats de recherche ne portent **jamais** de résumé : cochez "
        "« Récupérer les résumés », ou consultez une thèse par son identifiant."
    )

    with gr.Tab("Recherche"):
        query = gr.Textbox(label="Requête (syntaxe Lucene)", value="",
                           placeholder="titrePrincipal:informatique")
        with gr.Row():
            establishment = gr.Textbox(label="Code établissement", value="", placeholder="COAZ")
            discipline = gr.Textbox(label="Discipline", value="", placeholder="informatique")
            domain = gr.Textbox(label="Domaine thématique", value="", placeholder="Informatique")
        with gr.Row():
            author = gr.Textbox(label="Auteur·rice", value="", placeholder="Benoît Audelan")
            director = gr.Textbox(label="Direction", value="", placeholder="Frédéric Precioso")
            language = gr.Textbox(label="Langue (code ISO)", value="", placeholder="fr")
        with gr.Row():
            status = gr.Dropdown([""] + list(STATUS_VALUES), value="", label="Statut")
            accessible = gr.Dropdown([""] + list(ACCESSIBLE_VALUES), value="",
                                     label="Texte intégral en ligne (thèses soutenues)")
            sort = gr.Dropdown([""] + list(TRI_VALUES), value="", label="Tri")
        with gr.Row():
            max_results = gr.Slider(1, MAX_RESULTS, value=5, step=1, label="Résultats")
            hydrate = gr.Checkbox(label="Récupérer les résumés (1 requête par thèse)", value=False)
        search_btn = gr.Button("Rechercher", variant="primary")
        search_out = gr.Markdown()
        search_raw = gr.JSON(label="Sortie brute de l'outil")

        search_inputs = [query, establishment, discipline, domain, author, director,
                         language, accessible, status, max_results, sort, hydrate]

        gr.Examples(
            examples=[
                ["titrePrincipal:(sobriété énergétique)", "", "", "", "", "", "", "",
                 "", 5, "dateDesc", False],
                ["", "COAZ", "", "Informatique", "", "Precioso", "", "oui",
                 "soutenue", 5, "dateDesc", True],
                ["", "", "informatique", "", "", "", "en", "", "soutenue", 5,
                 "dateDesc", False],
                ["", "", "chimie", "", "", "", "", "", "enCours", 5, "", False],
                ["", "", "", "", "Audelan", "", "", "", "", 5, "", True],
            ],
            inputs=search_inputs,
            label="Titre, établissement + direction + texte intégral, discipline en anglais, "
                  "thèses en préparation, auteur·rice avec résumé",
        )
        search_btn.click(
            _run_search,
            inputs=search_inputs,
            outputs=[search_out, search_raw],
            api_name=False,
        )

    with gr.Tab("Une thèse"):
        id_value = gr.Textbox(label="NNT ou numéro de sujet", value="2021COAZ4028")
        get_btn = gr.Button("Consulter", variant="primary")
        get_out = gr.Markdown()
        get_raw = gr.JSON(label="Sortie brute de l'outil")

        gr.Examples(
            examples=[["2021COAZ4028"], ["2023UPASG024"], ["s68236"]],
            inputs=[id_value],
            label="Une thèse soutenue, une autre, une thèse en préparation",
        )
        get_btn.click(_run_get, inputs=[id_value], outputs=[get_out, get_raw], api_name=False)

    with gr.Tab("Personnes"):
        gr.Markdown(
            "L'index des thèses n'a pas de champ de nom d'auteur·rice exploitable : "
            "c'est par ici qu'on part d'un nom pour arriver aux notices."
        )
        person_query = gr.Textbox(label="Nom", value="", placeholder="Precioso")
        person_rows = gr.Slider(1, MAX_RESULTS, value=5, step=1, label="Résultats")
        person_btn = gr.Button("Chercher", variant="primary")
        person_out = gr.Markdown()
        person_raw = gr.JSON(label="Sortie brute de l'outil")

        gr.Examples(
            examples=[["Precioso", 5], ["Bengio", 5], ["Charpak", 5]],
            inputs=[person_query, person_rows],
            label="Un directeur de thèse, un homonyme fréquent, un nom rare",
        )
        person_btn.click(
            _run_persons,
            inputs=[person_query, person_rows],
            outputs=[person_out, person_raw],
            api_name=False,
        )

    with gr.Tab("Facettes"):
        gr.Markdown(
            "Établissements, écoles doctorales, disciplines et domaines sont "
            "appariés sur leur libellé exact : cet onglet les énumère, avec "
            "leurs effectifs, pour la requête de votre choix."
        )
        facet_query = gr.Textbox(label="Requête (Lucene)", value="*")
        facet_limit = gr.Slider(0, 50, value=10, step=1,
                                label="Valeurs par facette (0 = toutes)")
        facet_btn = gr.Button("Lister", variant="primary")
        facet_out = gr.Markdown()
        facet_raw = gr.JSON(label="Sortie brute de l'outil")

        gr.Examples(
            examples=[
                ["*", 10],
                ["discipline:(informatique)", 10],
                ["codeEtab:(COAZ)", 5],
            ],
            inputs=[facet_query, facet_limit],
            label="Tout le corpus, une discipline, un établissement",
        )
        facet_btn.click(
            _run_facets,
            inputs=[facet_query, facet_limit],
            outputs=[facet_out, facet_raw],
            api_name=False,
        )

    with gr.Tab("Organismes"):
        gr.Markdown(
            "Le PPN IdRef d'un organisme — pas son `codeEtab`. C'est la seule vue "
            "qui rassemble les thèses soutenues, en cotutelle, en partenariat de "
            "recherche et rattachées à une école doctorale."
        )
        org_ppn = gr.Textbox(label="PPN IdRef", value="", placeholder="241035694")
        org_role = gr.Dropdown([""] + list(ORGANISME_ROLES), value="", label="Rôle (optionnel)")
        org_btn = gr.Button("Consulter", variant="primary")
        org_out = gr.Markdown()
        org_raw = gr.JSON(label="Sortie brute de l'outil")

        gr.Examples(
            examples=[
                ["241035694", ""],
                ["241035694", "partenaireRecherche"],
                ["059079800", "ecoleDoctorale"],
                ["059205717", "partenaireRecherche"],
            ],
            inputs=[org_ppn, org_role],
            label="Une université tous rôles, la même en partenariat, une école "
                  "doctorale, un laboratoire",
        )
        org_btn.click(
            _run_organisme,
            inputs=[org_ppn, org_role],
            outputs=[org_out, org_raw],
            api_name=False,
        )

    # The only declared MCP tools. Names match the canonical server's.
    gr.api(search_theses, api_name="search_theses")
    gr.api(get_thesis, api_name="get_thesis")
    gr.api(search_persons, api_name="search_persons")
    gr.api(list_facets, api_name="list_facets")
    gr.api(search_by_organisme, api_name="search_by_organisme")


if __name__ == "__main__":
    demo.launch(
        theme=gr.themes.Soft(),  # Gradio 6 moved theme from Blocks() to launch()
        server_name=os.getenv("GRADIO_SERVER_NAME", "0.0.0.0"),
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
        mcp_server=os.getenv("GRADIO_MCP_SERVER", "true").lower() == "true",
    )
