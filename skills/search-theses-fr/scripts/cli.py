#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ['httpx']
# ///
"""theses.fr API CLI — French doctoral theses, defended and in progress.

- Dataservice: https://www.data.gouv.fr/dataservices/api-interroger-les-donnees-de-theses-fr
- OpenAPI:     https://theses.fr/api/v1/recherche/openapi.yaml
- Endpoints:   https://theses.fr/api/v1/theses , https://theses.fr/api/v1/personnes

Designed for agent use: strict JSON on stdout, always exit 0, upstream failures
reported in `error`. The service is public and anonymous — no environment
variable, no key. Timeout, retry count and backoff are constants below:
properties of the connector, not of the installation.

Five subcommands:
  search     /theses/recherche/ — Lucene `q`, the only filtering that works.
  get        /theses/these/{id} — one record, with the bilingual résumés.
  persons    /personnes/recherche/ — authors, directors, jury members.
  facets     /theses/facets/ — the establishment and status values `q` accepts.
  organisme  /theses/organisme/{ppn} — an establishment's theses, by its role.

Two gotchas the API documents but does not honour, both verified live:
  - the `filtres` parameter is inert; every filter goes through `q`.
  - search hits carry NO résumé; use --hydrate, or `get`.

Run:
  uv run skills/search-theses-fr/scripts/cli.py search --q 'discipline:(informatique)' --etab COAZ
  uv run skills/search-theses-fr/scripts/cli.py get --id 2021COAZ4028
  uv run skills/search-theses-fr/scripts/cli.py persons --q Precioso
  uv run skills/search-theses-fr/scripts/cli.py facets --q informatique
  uv run skills/search-theses-fr/scripts/cli.py organisme --ppn 241345251
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.parse
from typing import Any

import httpx


BASE_URL = "https://theses.fr/api/v1/theses"
PERSONS_URL = "https://theses.fr/api/v1/personnes"

HTTP_TIMEOUT = 20.0
MAX_RETRIES = 3
BACKOFF_BASE = 1.0
BACKOFF_FACTOR = 2.0
JITTER_MAX = 0.25
RETRIED_STATUS = {429, 500, 502, 503, 504}

MAX_ROWS = 500
TRI_VALUES = ("pertinence", "dateAsc", "dateDesc", "auteursAsc", "auteursDesc",
              "disciplineAsc", "disciplineDesc")
ACCESSIBLE_VALUES = ("oui", "non")

# /theses/organisme/{ppn} answers one list per role the establishment plays,
# each doubled into a defended and an in-preparation bucket, and each capped
# upstream at 100 records. Keys are the response's own, minus the "EnCours"
# suffix that distinguishes the two buckets.
ORGANISME_ROLES = ("etabSoutenance", "etabCotutelle",
                   "partenaireRecherche", "ecoleDoctorale")

# One pooled client for the process: httpx.get() would rebuild the client — and
# replay the TLS handshake — on every call, which --hydrate makes N times over.
HTTP = httpx.Client(
    timeout=HTTP_TIMEOUT,
    follow_redirects=True,
    headers={"User-Agent": "smartbiblia-theses-skill/0.2", "Accept": "application/json"},
)


# ── HTTP ──────────────────────────────────────────────────────────────────────

def _sleep_backoff(attempt: int) -> None:
    delay = BACKOFF_BASE * (BACKOFF_FACTOR ** (attempt - 1))
    time.sleep(delay + random.random() * JITTER_MAX)


def _http_get(url: str, params: list[tuple[str, str]] | None,
              as_text: bool) -> tuple[Any, str | None]:
    """Return (payload, error). Never raises — the error is data."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = HTTP.get(url, params=params)

            if resp.status_code in RETRIED_STATUS and attempt < MAX_RETRIES:
                _sleep_backoff(attempt)
                continue

            if resp.status_code >= 400:
                return None, f"HTTP {resp.status_code} on {url}"

            # An unknown identifier answers 200 with an empty body rather than
            # a 404, so emptiness is the only "not found" signal there is.
            if not resp.content.strip():
                return None, f"No record found (empty response) on {url}"

            if as_text:
                return resp.text, None

            try:
                return resp.json(), None
            except ValueError:
                ctype = resp.headers.get("content-type", "")
                return None, f"Non-JSON response (content-type={ctype}). Snippet: {resp.text[:300]}"

        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt == MAX_RETRIES:
                return None, f"Request failed: {exc}"
            _sleep_backoff(attempt)

    return None, "Request failed (exhausted retries)"


def http_get_json(url: str, params: list[tuple[str, str]] | None = None) -> tuple[Any, str | None]:
    return _http_get(url, params, as_text=False)


def http_get_text(url: str) -> tuple[str | None, str | None]:
    """For /theses/getorganismename/{ppn}, which answers text/plain, not JSON."""
    return _http_get(url, None, as_text=True)


# ── Normalization ─────────────────────────────────────────────────────────────

def _clean(v: Any) -> str | None:
    if isinstance(v, list):
        v = v[0] if v else None
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _year(date: str | None) -> int | None:
    """dateSoutenance is DD/MM/YYYY, and null for a thesis still in progress."""
    if not date or len(date) < 4:
        return None
    try:
        return int(date[-4:])
    except ValueError:
        return None


def _person_names(people: Any) -> list[str]:
    out: list[str] = []
    for p in people or []:
        if isinstance(p, dict):
            full = f"{(p.get('prenom') or '').strip()} {(p.get('nom') or '').strip()}".strip()
            if full:
                out.append(full)
        elif p:
            out.append(str(p))
    return out


def _person_name(p: Any) -> str | None:
    """One person — `presidentJury` is a bare object, not a list."""
    names = _person_names([p]) if isinstance(p, dict) else []
    return names[0] if names else None


def _org_names(orgs: Any) -> list[str]:
    """Establishments, doctoral schools and laboratories are all {ppn, nom, type}."""
    return [n for o in orgs or [] if isinstance(o, dict)
            for n in [_clean(o.get("nom"))] if n]


def _dedup(values: list[str | None]) -> list[str]:
    out: list[str] = []
    for v in values:
        if v and v not in out:
            out.append(v)
    return out


def _hit_keywords(t: dict[str, Any]) -> list[str]:
    """Free keywords (`sujets`) and Rameau headings (`sujetsRameau`), merged.

    Both are on the search hit already, so a caller can screen on subject
    matter without paying for hydration.
    """
    entries = (t.get("sujets") or []) + (t.get("sujetsRameau") or [])
    return _dedup([_clean(s.get("libelle")) for s in entries if isinstance(s, dict)])


def _detail_keywords(d: dict[str, Any]) -> list[str]:
    """The record endpoint carries the same keywords under `mapSujets`.

    Shape is {language: [{keyword, type, query}]}, mixing free and Rameau terms;
    flattened here to match the search hit's `keywords`.
    """
    return _dedup([_clean(e.get("keyword"))
                   for entries in (d.get("mapSujets") or {}).values()
                   for e in entries or [] if isinstance(e, dict)])


def normalize_search_hit(t: dict[str, Any]) -> dict[str, Any]:
    """Normalize a /recherche hit.

    `nnt` is null while a thesis is in progress; `id` then carries the subject
    number (`s68236`), and both address the detail endpoint. `titreEN` is not
    reliably an English title — records exist where it holds the discipline —
    so it is exposed as-is and never promoted to `title`.
    """
    ident = t.get("nnt") or t.get("id")
    date = _clean(t.get("dateSoutenance"))
    return {
        "source": "theses-fr",
        "id": ident,
        "nnt": t.get("nnt"),
        "record_id": t.get("id"),
        "title": _clean(t.get("titrePrincipal")),
        "title_en": _clean(t.get("titreEN")),
        "authors": _person_names(t.get("auteurs")),
        "directors": _person_names(t.get("directeurs")),
        "abstract": None,          # absent from search hits — use --hydrate or `get`
        "doi": _clean(t.get("doi")),
        "year": _year(date),
        "date": date,
        "doc_type": "thesis",
        "journal": None,           # a thesis has none; kept so the record merges
        "institution": _clean(t.get("etabSoutenanceN")),
        "institution_ppn": _clean(t.get("etabSoutenancePpn")),
        "discipline": _clean(t.get("discipline")),
        # The only date an in-progress thesis has; never a defense date.
        "date_first_registration": _clean(t.get("datePremiereInscriptionDoctorat")),
        "doctoral_schools": _org_names(t.get("ecolesDoctorale")),
        "research_partners": _org_names(t.get("partenairesDeRecherche")),
        "keywords": _hit_keywords(t),
        "rapporteurs": _person_names(t.get("rapporteurs")),
        "jury": _person_names(t.get("examinateurs")),
        "president": _person_name(t.get("president")),
        "status": _clean(t.get("status")),
        "url": f"https://theses.fr/{ident}" if ident else None,
        "raw": t,
    }


def normalize_detail(d: dict[str, Any]) -> dict[str, Any]:
    """Normalize a /these/{id} record — the only shape carrying the résumés."""
    ident = d.get("nnt") or d.get("numSujet")
    resumes = d.get("resumes") or {}
    titres = d.get("titres") or {}
    date = _clean(d.get("dateSoutenance"))
    etab = d.get("etabSoutenance") or {}
    return {
        "source": "theses-fr",
        "id": ident,
        "nnt": d.get("nnt"),
        "record_id": d.get("numSujet"),
        "title": _clean(d.get("titrePrincipal")) or _clean(titres.get("fr")) or _clean(titres.get("en")),
        "titles": {k: _clean(v) for k, v in titres.items()},
        "authors": _person_names(d.get("auteurs")),
        "directors": _person_names(d.get("directeurs")),
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
        # The short establishment code — the value `search --etab` filters on.
        "code_etab": _clean(d.get("codeEtab")),
        "discipline": _clean(d.get("discipline")),
        "date_first_registration": _clean(d.get("datePremiereInscriptionDoctorat")),
        "doctoral_schools": _org_names(d.get("ecolesDoctorales")),
        "research_partners": _org_names(d.get("partenairesRecherche")),
        "cotutelle": _org_names(d.get("etabCotutelle")),
        "keywords": _detail_keywords(d),
        "rapporteurs": _person_names(d.get("rapporteurs")),
        "jury": _person_names(d.get("membresJury")),
        "president": _person_name(d.get("presidentJury")),
        "languages": d.get("langues") or [],
        "status": _clean(d.get("status")),
        "is_defended": d.get("isSoutenue"),
        # "oui" only ever for a defended thesis: the online availability of the
        # defense version, and what `search --accessible oui` filters on.
        "accessible": d.get("accessible"),
        "url": f"https://theses.fr/{ident}" if ident else None,
        "raw": d,
    }


def normalize_person(p: dict[str, Any]) -> dict[str, Any]:
    """Normalize a /personnes hit.

    `roles` is a dict of role label -> number of theses, and `theses` the list
    of identifiers to feed back into `get`.
    """
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


def envelope(**extra: Any) -> dict[str, Any]:
    """The universal envelope, in key order, with the extras a command adds."""
    return {"total_found": None, "returned": 0, "results": [], **extra, "error": None}


# ── Commands ──────────────────────────────────────────────────────────────────

def build_query(a: argparse.Namespace) -> str:
    """Assemble the Lucene `q`. The API's own `filtres` parameter is inert.

    Quoting is per-field and not negotiable, all three verified live:
      - `oaiSetNames` is a controlled label and must be quoted — unquoted,
        "Agronomie, agriculture et médecine vétérinaire" returns 0 instead of
        3 248;
      - `auteursNP` / `directeursNP` must NOT be quoted: the field holds name
        tokens in no fixed order, so the phrase "Frédéric Precioso" returns 0
        while the bare tokens return the 23 expected records;
      - `codeEtab` is case-sensitive, hence the upper().
    """
    clauses: list[str] = []
    if a.q:
        clauses.append(f"({a.q})")
    if a.etab:
        clauses.append(f"codeEtab:({a.etab.upper()})")
    if a.discipline:
        clauses.append(f"discipline:({a.discipline})")
    if a.domain:
        clauses.append(f'oaiSetNames:("{a.domain}")')
    if a.author:
        clauses.append(f"auteursNP:({a.author})")
    if a.director:
        clauses.append(f"directeursNP:({a.director})")
    if a.language:
        clauses.append(f"langues:({a.language})")
    if a.accessible:
        clauses.append(f"accessible:({a.accessible})")
    if a.date_from or a.date_to:
        clauses.append(f"dateSoutenance:([{a.date_from or '*'} TO {a.date_to or '*'}])")
    if a.status:
        clauses.append(f"status:({a.status})")
    return " AND ".join(clauses) if clauses else "*"


def cmd_search(a: argparse.Namespace) -> dict[str, Any]:
    q = build_query(a)
    rows = max(1, min(a.rows, MAX_ROWS))
    params = [("q", q), ("nombre", str(rows)), ("debut", str(a.start))]
    if a.sort:
        params.append(("tri", a.sort))

    out = envelope(query_used=q,
                   params={"rows": rows, "start": a.start, "sort": a.sort},
                   hydrated=bool(a.hydrate))

    obj, err = http_get_json(f"{BASE_URL}/recherche/", params)
    if err:
        out["error"] = err
        return out
    if not isinstance(obj, dict):
        out["error"] = "Unexpected response shape from /theses/recherche/"
        return out

    results = [normalize_search_hit(t) for t in obj.get("theses") or []]
    out["total_found"] = obj.get("totalHits")

    if a.hydrate:
        for r in results:
            ident = r.get("id")
            if not ident:
                continue
            d_obj, d_err = http_get_json(f"{BASE_URL}/these/{urllib.parse.quote(str(ident))}")
            if d_err or not isinstance(d_obj, dict):
                r["hydrate_error"] = d_err or "unexpected detail response shape"
                continue
            det = normalize_detail(d_obj)
            # Only the fields the search projection genuinely lacks: keywords,
            # partners, jury and schools already ride along on the hit.
            for field in ("abstract", "abstracts", "titles", "languages",
                          "code_etab", "accessible", "cotutelle", "is_defended"):
                r[field] = det[field]

    out["returned"] = len(results)
    out["results"] = results
    return out


def cmd_get(a: argparse.Namespace) -> dict[str, Any]:
    out = envelope(query_used=a.id)
    obj, err = http_get_json(f"{BASE_URL}/these/{urllib.parse.quote(a.id)}")
    if err:
        out["error"] = err
        return out
    if not isinstance(obj, dict):
        out["error"] = "Unexpected response shape from /theses/these/"
        return out
    out["returned"] = 1
    out["results"] = [normalize_detail(obj)]
    return out


def cmd_persons(a: argparse.Namespace) -> dict[str, Any]:
    rows = max(1, min(a.rows, MAX_ROWS))
    params = [("q", a.q), ("nombre", str(rows)), ("debut", str(a.start))]
    out = envelope(query_used=a.q, params={"rows": rows, "start": a.start})

    obj, err = http_get_json(f"{PERSONS_URL}/recherche/", params)
    if err:
        out["error"] = err
        return out
    if not isinstance(obj, dict):
        out["error"] = "Unexpected response shape from /personnes/recherche/"
        return out

    people = obj.get("personnes") or []
    out["total_found"] = obj.get("totalHits")
    out["returned"] = len(people)
    out["results"] = [normalize_person(p) for p in people]
    return out


def cmd_facets(a: argparse.Namespace) -> dict[str, Any]:
    """List the facet values available for a query.

    This is how the string to put in `etabSoutenanceN:` is discovered: the
    establishment facet is named by label ("Aix-Marseille", "Lorient"), and
    there is no reference endpoint that enumerates them.
    """
    out = envelope(query_used=a.q)
    obj, err = http_get_json(f"{BASE_URL}/facets/", [("q", a.q)])
    if err:
        out["error"] = err
        return out
    if not isinstance(obj, list):
        out["error"] = "Unexpected response shape from /theses/facets/"
        return out

    results = []
    for facet in obj:
        if not isinstance(facet, dict):
            continue
        buckets = [{"value": c.get("name"), "count": c.get("value")}
                   for c in facet.get("checkboxes") or [] if isinstance(c, dict)]
        if a.limit > 0:
            buckets = buckets[: a.limit]
        results.append({"source": "theses-fr", "id": facet.get("name"),
                        "label": facet.get("name"), "url": None, "buckets": buckets})
    out["total_found"] = len(results)
    out["returned"] = len(results)
    out["results"] = results
    return out


def cmd_organisme(a: argparse.Namespace) -> dict[str, Any]:
    """An establishment's theses, grouped by the role it played in each.

    This is the one view `q` cannot assemble: `codeEtab` only ever finds the
    awarding establishment, while this endpoint also returns the theses where
    the organisation was a cotutelle partner, a research partner or the
    doctoral school. Each of the eight buckets is capped at 100 upstream, so
    `total_found` is regularly larger than `returned`.
    """
    out = envelope(query_used=a.ppn, organisme={"ppn": a.ppn, "name": None},
                   totals={}, role=a.role)

    # An empty name means the PPN is a person, not an organisation — the only
    # way to tell, since /organisme/ answers 200 with empty buckets either way.
    name, name_err = http_get_text(
        f"{BASE_URL}/getorganismename/{urllib.parse.quote(a.ppn)}")
    if name_err is None:
        out["organisme"]["name"] = _clean(name)
    else:
        out["error"] = (f"No organisation found for PPN {a.ppn} — "
                        "getorganismename returned nothing, so this PPN is "
                        "probably a person; try the `persons` subcommand.")
        return out

    obj, err = http_get_json(f"{BASE_URL}/organisme/{urllib.parse.quote(a.ppn)}")
    if err:
        out["error"] = err
        return out
    if not isinstance(obj, dict):
        out["error"] = "Unexpected response shape from /theses/organisme/"
        return out

    roles = (a.role,) if a.role else ORGANISME_ROLES
    results: list[dict[str, Any]] = []
    total = 0
    for role in roles:
        for key, in_progress in ((role, False), (f"{role}EnCours", True)):
            count = obj.get(f"totalHits{key}")
            if isinstance(count, int):
                out["totals"][key] = count
                total += count
            for t in obj.get(key) or []:
                if not isinstance(t, dict):
                    continue
                rec = normalize_search_hit(t)
                rec["role"] = role
                rec["in_progress"] = in_progress
                results.append(rec)

    out["total_found"] = total
    out["returned"] = len(results)
    out["results"] = results
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="theses", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("search", help="Search theses via /theses/recherche/")
    ps.add_argument("--q", default="", help="Lucene query, e.g. 'discipline:informatique AND status:soutenue'")
    ps.add_argument("--etab", default=None,
                    help="Establishment short code, e.g. COAZ -> codeEtab:(COAZ). "
                         "Unlike nnt:*COAZ*, this also finds theses in progress.")
    ps.add_argument("--discipline", default=None,
                    help="-> discipline:<value>; free text, ~4000 values")
    ps.add_argument("--domain", default=None,
                    help="-> oaiSetNames:(\"<label>\"); one of the 98 'Domaines "
                         "thématiques' facet labels — run `facets` to list them")
    ps.add_argument("--author", default=None, help="-> auteursNP:(<name tokens>)")
    ps.add_argument("--director", default=None, help="-> directeursNP:(<name tokens>)")
    ps.add_argument("--language", default=None, help="-> langues:(<code>), e.g. fr, en")
    ps.add_argument("--accessible", default=None, choices=ACCESSIBLE_VALUES,
                    help="-> accessible:(<value>); online full text. Defended theses only")
    ps.add_argument("--date-from", default=None, help="dateSoutenance lower bound (YYYY-MM-DD)")
    ps.add_argument("--date-to", default=None, help="dateSoutenance upper bound (YYYY-MM-DD)")
    ps.add_argument("--status", default=None, help="-> status:<value>, i.e. soutenue or enCours")
    ps.add_argument("--rows", type=int, default=15, help=f"page size (nombre), clamped to {MAX_ROWS}")
    ps.add_argument("--start", type=int, default=0, help="offset (debut)")
    ps.add_argument("--sort", default=None, choices=TRI_VALUES, help="tri")
    ps.add_argument("--hydrate", action="store_true",
                    help="fetch the résumé of every hit — one extra request each")

    pg = sub.add_parser("get", help="Fetch one thesis by NNT or subject number")
    pg.add_argument("--id", required=True, help="NNT (2021COAZ4028) or subject number (s68236)")

    pp = sub.add_parser("persons", help="Search the /personnes index")
    pp.add_argument("--q", required=True, help="Free-text name query")
    pp.add_argument("--rows", type=int, default=15)
    pp.add_argument("--start", type=int, default=0)

    pf = sub.add_parser("facets", help="List facet values (statuses, establishments) for a query")
    pf.add_argument("--q", default="*", help="The query the facets are counted over")
    pf.add_argument("--limit", type=int, default=25, help="Buckets per facet; 0 returns every one")

    po = sub.add_parser("organisme",
                        help="An establishment's theses by role, via /theses/organisme/{ppn}")
    po.add_argument("--ppn", required=True, help="IdRef PPN of the organisation, e.g. 241345251")
    po.add_argument("--role", default=None, choices=ORGANISME_ROLES,
                    help="Keep one role only; otherwise all four are returned")

    return p.parse_args()


def main() -> None:
    a = parse_args()
    out = {"search": cmd_search, "get": cmd_get, "persons": cmd_persons,
           "facets": cmd_facets, "organisme": cmd_organisme}[a.cmd](a)
    json.dump(out, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
