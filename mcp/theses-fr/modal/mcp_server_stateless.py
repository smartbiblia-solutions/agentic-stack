"""theses.fr MCP server — Modal deployment.

A **standalone duplicate** of the canonical server, `../mcp_server.py`, built on
the shape of Modal's own FastMCP example: nothing is mounted into the image and
nothing is imported from the parent folder. Everything the server needs is
defined inside `make_mcp_server()`, including its runtime imports — Modal loads
this file on the local machine to build the app, where `fastmcp` and `httpx` are
not installed, so a top-level import of either would break `modal deploy`.

The tools below are a **hand-kept copy** of the canonical ones — same names, same
arguments, same envelope. Change one, change the other.

Tools served: `search_theses`, `get_thesis`, `search_persons`, `list_facets`, `search_by_organisme`.

  # Ephemeral deployment that reloads on save
  uvx modal serve mcp/theses-fr/modal/mcp_server_stateless.py

  # List the deployed tools (and optionally call one)
  uvx modal run mcp/theses-fr/modal/mcp_server_stateless.py::test_tool

  # Persistent deployment
  uvx modal deploy mcp/theses-fr/modal/mcp_server_stateless.py

The MCP endpoint is the printed URL with `/mcp/` appended:

    https://<workspace>--smartbiblia-mcp-theses-fr-web.modal.run/mcp/

Modal load-balances one URL across containers that come and go, so the transport
is built **stateless** (`stateless_http=True`): a new transport per request, no
session pinned to a replica — the same mode as
`mcp_server.py --transport http --stateless`. A stateless response carries no
`mcp-session-id` header, which is how to check the mode of a running server.

Environment: none. The theses.fr search API is public and anonymous.
"""

import modal

APP_NAME = "smartbiblia-mcp-theses-fr"

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
    import asyncio
    import os
    import random
    import time
    import urllib.parse
    from typing import Any, Literal

    import httpx
    from fastmcp import FastMCP

    BASE_URL = "https://theses.fr/api/v1/theses"
    PERSONS_URL = "https://theses.fr/api/v1/personnes"
    USER_AGENT = "smartbiblia-theses-fr-mcp/0.2"
    RETRIED_STATUS = {429, 500, 502, 503, 504}

    MAX_ROWS = 200
    MAX_HYDRATE = 50
    TRI_VALUES = ("pertinence", "dateAsc", "dateDesc", "auteursAsc", "auteursDesc",
                  "disciplineAsc", "disciplineDesc")

    # /theses/organisme/{ppn} answers one list per role the organisation plays, each
    # doubled into a defended and an in-preparation bucket, and each capped upstream
    # at 100 records. Keys are the response's own, minus the "EnCours" suffix that
    # distinguishes the two buckets.
    ORGANISME_ROLES = ("etabSoutenance", "etabCotutelle",
                       "partenaireRecherche", "ecoleDoctorale")

    HTTP_TIMEOUT = 20.0
    MAX_RETRIES = 3
    BACKOFF_BASE = 1.0
    BACKOFF_FACTOR = 2.0
    JITTER_MAX = 0.25
    TRACE_DEFAULT = False

    mcp = FastMCP(
        name="theses-fr",
        instructions=(
            "theses.fr connector — search French doctoral theses (defended and in "
            "preparation), fetch one record with its bilingual résumés by NNT or "
            "subject number, search the person index of supervisors and jury "
            "members, and list the facet values a query accepts. Public, no key."
        ),
    )

    # One pooled client for the process. Opening an AsyncClient per call would
    # rebuild the connection pool — and replay the TLS handshake — every time,
    # which hydrate would then pay once per hit.
    HTTP = httpx.AsyncClient(
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )


    # ── HTTP ──────────────────────────────────────────────────────────────────────

    def _backoff_sleep_seconds(attempt: int) -> float:
        base = BACKOFF_BASE * (BACKOFF_FACTOR ** attempt)
        return base + (random.uniform(0.0, JITTER_MAX) if JITTER_MAX > 0 else 0.0)


    async def _http_get(
        url: str,
        params: list[tuple[str, str]] | None = None,
        *,
        trace: bool = False,
        as_text: bool = False,
    ) -> tuple[Any, str | None, list[dict[str, Any]]]:
        """GET with bounded retries. Returns (payload, error, trace_events).

        Never raises: an upstream failure is a successful tool call carrying
        `error`, so a client reads the failure instead of a protocol exception.
        """
        events: list[dict[str, Any]] = []
        for attempt in range(1, MAX_RETRIES + 1):
            t0 = time.perf_counter()
            try:
                if trace:
                    events.append({"event": "http_request", "url": url,
                                   "params": params or [], "attempt": attempt})
                resp = await HTTP.get(url, params=params)
                if trace:
                    events.append({"event": "http_response", "status_code": resp.status_code,
                                   "attempt": attempt,
                                   "elapsed_ms": int((time.perf_counter() - t0) * 1000)})

                if resp.status_code in RETRIED_STATUS and attempt < MAX_RETRIES:
                    await asyncio.sleep(_backoff_sleep_seconds(attempt))
                    continue
                if resp.status_code >= 400:
                    return None, f"HTTP {resp.status_code} on {url}", events

                # An unknown identifier answers 200 with an empty body rather than
                # a 404, so emptiness is the only "not found" signal there is.
                if not resp.content.strip():
                    return None, f"No record found (empty response) on {url}", events

                if as_text:
                    return resp.text, None, events

                try:
                    return resp.json(), None, events
                except ValueError:
                    ctype = resp.headers.get("content-type", "")
                    return None, f"Non-JSON response (content-type={ctype})", events

            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if trace:
                    events.append({"event": "http_error", "attempt": attempt, "message": str(exc)})
                if attempt == MAX_RETRIES:
                    return None, f"Request failed: {exc}", events
                await asyncio.sleep(_backoff_sleep_seconds(attempt))

        return None, "Request failed (exhausted retries)", events


    async def _get_json(
        url: str,
        params: list[tuple[str, str]] | None = None,
        *,
        trace: bool = False,
    ) -> tuple[Any, str | None, list[dict[str, Any]]]:
        return await _http_get(url, params, trace=trace)


    async def _get_text(
        url: str, *, trace: bool = False,
    ) -> tuple[str | None, str | None, list[dict[str, Any]]]:
        """For /theses/getorganismename/{ppn}, which answers text/plain, not JSON."""
        return await _http_get(url, None, trace=trace, as_text=True)


    # ── Normalization ─────────────────────────────────────────────────────────────

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

        Both ride along on the search hit, so a client can screen on subject matter
        without paying for hydration.
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


    def _normalize_search_hit(t: dict[str, Any]) -> dict[str, Any]:
        ident = t.get("nnt") or t.get("id")
        date = _clean(t.get("dateSoutenance"))
        return {
            "source": "theses-fr",
            "id": ident,
            "nnt": t.get("nnt"),
            "record_id": t.get("id"),
            "title": _clean(t.get("titrePrincipal")),
            # titreEN is not reliably an English title upstream — records exist
            # where it holds the discipline — so it never becomes `title`.
            "title_en": _clean(t.get("titreEN")),
            "authors": _person_names(t.get("auteurs")),
            "directors": _person_names(t.get("directeurs")),
            "abstract": None,          # absent from search hits — hydrate, or get_thesis
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


    def _normalize_detail(d: dict[str, Any]) -> dict[str, Any]:
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
            # The short establishment code — the value `establishment` filters on.
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
            # "oui" only ever for a defended thesis: online availability of the
            # defense version, and what `accessible` filters on.
            "accessible": d.get("accessible"),
            "url": f"https://theses.fr/{ident}" if ident else None,
            "raw": d,
        }


    def _normalize_person(p: dict[str, Any]) -> dict[str, Any]:
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


    def _build_lucene(query: str, establishment: str | None, discipline: str | None,
                      domain: str | None, author: str | None, director: str | None,
                      language: str | None, accessible: str | None,
                      date_from: str | None, date_to: str | None, status: str | None) -> str:
        """Assemble the Lucene `q`. The API's own `filtres` parameter is inert.

        Quoting is per-field and not negotiable, all three verified live:
          - `oaiSetNames` is a controlled label and must be quoted — unquoted,
            "Agronomie, agriculture et médecine vétérinaire" returns 0 instead of
            3 248;
          - `auteursNP` / `directeursNP` must NOT be quoted: the field holds name
            tokens in no fixed order, so the phrase "Frédéric Precioso" returns 0
            while the bare tokens return the 14 expected records;
          - `codeEtab` is case-sensitive, hence the upper().
        """
        clauses: list[str] = []
        if query:
            clauses.append(f"({query})")
        if establishment:
            clauses.append(f"codeEtab:({establishment.upper()})")
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
        if date_from or date_to:
            clauses.append(f"dateSoutenance:([{date_from or '*'} TO {date_to or '*'}])")
        if status:
            clauses.append(f"status:({status})")
        return " AND ".join(clauses) if clauses else "*"


    def _envelope(command: str, **extra: Any) -> dict[str, Any]:
        return {"source": "theses-fr", "command": command,
                "total_found": None, "returned": 0, "results": [], **extra, "error": None}


    # ── Tools ─────────────────────────────────────────────────────────────────────

    @mcp.tool
    async def search_theses(
        query: str = "",
        establishment: str | None = None,
        discipline: str | None = None,
        domain: str | None = None,
        author: str | None = None,
        director: str | None = None,
        language: str | None = None,
        accessible: Literal["oui", "non"] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        status: Literal["soutenue", "enCours"] | None = None,
        max_results: int = 15,
        start: int = 0,
        sort: Literal["pertinence", "dateAsc", "dateDesc", "auteursAsc", "auteursDesc",
                      "disciplineAsc", "disciplineDesc"] | None = None,
        hydrate: bool = False,
        trace: bool | None = None,
    ) -> dict[str, Any]:
        """
        Search theses.fr for French doctoral theses, defended or in preparation.

        Use this tool for any French doctoral coverage question. Use `get_thesis`
        instead when an NNT is already known, and `search_persons` to find a
        supervisor or jury member by name.

        Syntax / domain rules:
          - theses.fr's own `filtres` parameter is inert; every constraint below is
            compiled into one Lucene `q` and ANDed together.
          - `establishment` compiles to `codeEtab:(CODE)`, not to the older
            `nnt:*CODE*`: a thesis in preparation has no NNT, so the wildcard
            silently drops every one of them.
          - Quote multi-word values in a raw `query`: `etabSoutenanceN:"Aix-Marseille"`
            is the phrase, `etabSoutenanceN:Aix-Marseille` over-matches. Person-name
            fields are the exception and must stay unquoted — `directeursNP:(Frédéric
            Precioso)` returns 14 records, the quoted phrase returns 0.
          - Nested paths do not work: `auteurs.nom:Dupont` returns zero. Query a
            person through the flat `auteursNP`/`directeursNP` (name) or
            `auteursPpn`/`directeursPpn` (exact, homonym-free) fields.
          - Other fields worth a raw `query`: `resumes.fr` / `resumes.en` (full-text
            résumé; bare `resumes.*` is an HTTP 400), `sujetsLibelle`,
            `sujetsRameauLibelle`, `ecolesDoctoralesPpn`, `partenairesRecherchePpn`,
            `datePremiereInscriptionDoctorat`, `dateInsertionDansES` (index date,
            for incremental sync), `numSujet`.
          - Search hits never carry a résumé. `hydrate=True` fetches it per hit,
            one extra request each, capped at 50 hits.

        Args:
            query: Raw Lucene query, e.g. 'titrePrincipal:(informatique) OR discipline:(informatique)'. Empty means match all.
            establishment: Establishment short code, e.g. "COAZ" -> codeEtab:(COAZ). Case-insensitive here, upper-cased before sending.
            discipline: Discipline, free text (~4000 values), e.g. "informatique" -> discipline:(informatique).
            domain: Thematic domain -> oaiSetNames:("<label>"). Controlled: one of the 98 "Domaines thématiques" labels from list_facets.
            author: Author name tokens -> auteursNP:(<name>). Order-independent, never quoted.
            director: Supervisor name tokens -> directeursNP:(<name>).
            language: ISO code of the writing language, e.g. "fr", "en" -> langues:(<code>).
            accessible: "oui" for theses whose full text is online -> accessible:(oui). Defended theses only; with status="enCours" it always returns zero.
            date_from: dateSoutenance lower bound, ISO "YYYY-MM-DD", even though results render DD/MM/YYYY.
            date_to: dateSoutenance upper bound, ISO "YYYY-MM-DD".
            status: "soutenue" (defended) or "enCours" (in preparation).
            max_results: Page size, clamped to 200.
            start: Offset into the result set.
            sort: Ordering; anything outside the listed values is ignored upstream.
            hydrate: Fetch each hit's résumé from the record endpoint. Costs one request per hit.
            trace: Include the HTTP trace in the response.

        Returns:
            {
              "source": "theses-fr",
              "command": "search_theses",
              "total_found": int | null,
              "returned": int,
              "results": [
                {
                  "source": "theses-fr", "id": str, "nnt": str | null,
                  "title": str | null, "title_en": str | null,
                  "authors": [str], "directors": [str],
                  "abstract": str | null, "abstracts": {"fr": str, "en": str},
                  "doi": str | null, "year": int | null, "date": str | null,
                  "doc_type": "thesis", "journal": null,
                  "institution": str | null, "institution_ppn": str | null,
                  "discipline": str | null,
                  "date_first_registration": str | null,
                  "doctoral_schools": [str], "research_partners": [str],
                  "keywords": [str], "rapporteurs": [str], "jury": [str],
                  "president": str | null,
                  "status": "soutenue" | "enCours", "url": str | null,
                  "hydrate_error": str,
                  "raw": {}
                }
              ],
              "query_used": str,
              "hydrated": bool,
              "error": str | null
            }

            `abstract` is null on every hit unless hydrate=True — and stays null for
            the many records that carry no résumé at all. `hydrate_error` appears
            only on a hit whose record fetch failed; the others are unaffected.
        """
        include_trace = TRACE_DEFAULT if trace is None else trace
        q = _build_lucene(query, establishment, discipline, domain, author, director,
                          language, accessible, date_from, date_to, status)
        rows = max(1, min(max_results, MAX_ROWS))
        params = [("q", q), ("nombre", str(rows)), ("debut", str(max(0, start)))]
        if sort:
            params.append(("tri", sort))

        out = _envelope("search_theses", query_used=q, hydrated=bool(hydrate))
        data, error, events = await _get_json(f"{BASE_URL}/recherche/", params, trace=include_trace)
        if error or not isinstance(data, dict):
            out["error"] = error or "Unexpected response shape from /theses/recherche/"
            if include_trace:
                out["trace"] = events
            return out

        results = [_normalize_search_hit(t) for t in data.get("theses") or [] if isinstance(t, dict)]
        out["total_found"] = data.get("totalHits")

        if hydrate:
            for r in results[:MAX_HYDRATE]:
                ident = r.get("id")
                if not ident:
                    continue
                detail, d_error, d_events = await _get_json(
                    f"{BASE_URL}/these/{urllib.parse.quote(str(ident))}", trace=include_trace)
                events.extend(d_events)
                if d_error or not isinstance(detail, dict):
                    r["hydrate_error"] = d_error or "unexpected record response shape"
                    continue
                normalized = _normalize_detail(detail)
                # Only the fields the search projection genuinely lacks: keywords,
                # partners, jury and schools already ride along on the hit.
                for field in ("abstract", "abstracts", "titles", "languages",
                              "code_etab", "accessible", "cotutelle", "is_defended"):
                    r[field] = normalized[field]

        out["returned"] = len(results)
        out["results"] = results
        if include_trace:
            out["trace"] = events
        return out


    @mcp.tool
    async def get_thesis(id: str, trace: bool | None = None) -> dict[str, Any]:
        """
        Fetch one thesis record, including its bilingual résumés.

        Use this tool when an identifier is already known — it is the only way to
        obtain a résumé, which the search index does not carry. Use `search_theses`
        to find the identifier first.

        Syntax / domain rules:
          - Accepts an NNT ("2021COAZ4028") or, for a thesis still in preparation,
            a subject number ("s68236"). `nnt` is null on the latter.
          - An unknown identifier answers HTTP 200 with an empty body upstream; it
            comes back here as `error: "No record found …"` and `results: []`.

        Args:
            id: NNT, e.g. "2021COAZ4028", or subject number, e.g. "s68236".
            trace: Include the HTTP trace in the response.

        Returns:
            {
              "source": "theses-fr",
              "command": "get_thesis",
              "total_found": null,
              "returned": 0 | 1,
              "results": [ /* one record, same shape as search_theses, plus
                              "abstracts", "titles", "languages", "code_etab",
                              "is_defended", "accessible" */ ],
              "query_used": str,
              "error": str | null
            }
        """
        include_trace = TRACE_DEFAULT if trace is None else trace
        out = _envelope("get_thesis", query_used=id)
        data, error, events = await _get_json(
            f"{BASE_URL}/these/{urllib.parse.quote(id)}", trace=include_trace)
        if include_trace:
            out["trace"] = events
        if error or not isinstance(data, dict):
            out["error"] = error or "Unexpected response shape from /theses/these/"
            return out
        out["returned"] = 1
        out["results"] = [_normalize_detail(data)]
        return out


    @mcp.tool
    async def search_persons(
        query: str,
        max_results: int = 15,
        start: int = 0,
        trace: bool | None = None,
    ) -> dict[str, Any]:
        """
        Search the theses.fr person index: authors, supervisors, rapporteurs, jury.

        Use this tool to find a doctoral supervisor and the theses they were
        involved in — the thesis index has no working author-name field, so this is
        the only reliable path from a person's name to their records.

        Args:
            query: Free-text name, e.g. "Precioso". Surname alone works best.
            max_results: Page size, clamped to 200.
            start: Offset into the result set.
            trace: Include the HTTP trace in the response.

        Returns:
            {
              "source": "theses-fr",
              "command": "search_persons",
              "total_found": int | null,
              "returned": int,
              "results": [
                {
                  "source": "theses-fr", "id": str, "label": str,
                  "roles": {"Directeur / Directrice": int, ...},
                  "has_idref": bool, "theses": [str],
                  "url": str | null, "raw": {}
                }
              ],
              "query_used": str,
              "error": str | null
            }

            `roles` maps a role label to how many theses it covers. `theses` is a
            list of identifiers ready to pass to get_thesis. When `has_idref` is
            true, `id` is the person's IdRef PPN.
        """
        include_trace = TRACE_DEFAULT if trace is None else trace
        rows = max(1, min(max_results, MAX_ROWS))
        params = [("q", query), ("nombre", str(rows)), ("debut", str(max(0, start)))]

        out = _envelope("search_persons", query_used=query)
        data, error, events = await _get_json(f"{PERSONS_URL}/recherche/", params, trace=include_trace)
        if include_trace:
            out["trace"] = events
        if error or not isinstance(data, dict):
            out["error"] = error or "Unexpected response shape from /personnes/recherche/"
            return out

        people = [p for p in data.get("personnes") or [] if isinstance(p, dict)]
        out["total_found"] = data.get("totalHits")
        out["returned"] = len(people)
        out["results"] = [_normalize_person(p) for p in people]
        return out


    @mcp.tool
    async def list_facets(
        query: str = "*",
        limit: int = 25,
        trace: bool | None = None,
    ) -> dict[str, Any]:
        """
        List the facet values a query accepts, with their counts.

        Use this tool before filtering by establishment, doctoral school or
        discipline: those fields are matched on their exact label, and there is no
        reference endpoint that enumerates them. Counts are relative to `query`.

        Args:
            query: The query the facets are counted over. "*" covers the whole corpus.
            limit: Maximum buckets per facet; 0 returns every one.
            trace: Include the HTTP trace in the response.

        Returns:
            {
              "source": "theses-fr",
              "command": "list_facets",
              "total_found": int,
              "returned": int,
              "results": [
                {
                  "source": "theses-fr", "id": "Établissements",
                  "label": "Établissements", "url": null,
                  "buckets": [{"value": "Aix-Marseille", "count": 951}]
                }
              ],
              "query_used": str,
              "error": str | null
            }

            Facets returned upstream: Statut, Établissements, Écoles doctorales,
            Domaines thématiques, Disciplines, Langues.
        """
        include_trace = TRACE_DEFAULT if trace is None else trace
        out = _envelope("list_facets", query_used=query)
        data, error, events = await _get_json(f"{BASE_URL}/facets/", [("q", query)], trace=include_trace)
        if include_trace:
            out["trace"] = events
        if error or not isinstance(data, list):
            out["error"] = error or "Unexpected response shape from /theses/facets/"
            return out

        results = []
        for facet in data:
            if not isinstance(facet, dict):
                continue
            buckets = [{"value": c.get("name"), "count": c.get("value")}
                       for c in facet.get("checkboxes") or [] if isinstance(c, dict)]
            results.append({"source": "theses-fr", "id": facet.get("name"),
                            "label": facet.get("name"), "url": None,
                            "buckets": buckets[:limit] if limit > 0 else buckets})
        out["total_found"] = len(results)
        out["returned"] = len(results)
        out["results"] = results
        return out


    @mcp.tool
    async def search_by_organisme(
        ppn: str,
        role: Literal["etabSoutenance", "etabCotutelle",
                      "partenaireRecherche", "ecoleDoctorale"] | None = None,
        trace: bool | None = None,
    ) -> dict[str, Any]:
        """
        List an organisation's theses, grouped by the role it played in each.

        Use this tool for an establishment's full doctoral footprint — it is the one
        view a query cannot assemble. `search_theses(establishment=…)` only ever
        finds the *awarding* establishment; this endpoint also returns the theses
        where the organisation was a cotutelle partner, a research partner (a
        laboratory) or the doctoral school. Use `search_theses` instead when an
        exhaustive, pageable listing of what an establishment awarded is what is
        wanted.

        Syntax / domain rules:
          - `ppn` is the organisation's IdRef PPN — the `institution_ppn` of any of
            its records, or a `*Ppn` value under `raw`. Not the short `codeEtab`.
          - Upstream caps every role bucket at 100 records whatever its counter
            says, so `total_found` is routinely far larger than `returned`. Read
            `totals` for the true per-role figures.
          - A person's PPN answers 200 with all buckets empty, indistinguishable
            from an organisation with no theses. This tool disambiguates by
            resolving the name first and reports `error` when there is none.

        Args:
            ppn: IdRef PPN of the organisation, e.g. "241035694".
            role: Keep a single role; omit for all four.
            trace: Include the HTTP trace in the response.

        Returns:
            {
              "source": "theses-fr",
              "command": "search_by_organisme",
              "total_found": int,
              "returned": int,
              "results": [ /* thesis records, same shape as search_theses, each with
                              "role": str and "in_progress": bool */ ],
              "organisme": {"ppn": str, "name": str | null},
              "totals": {"etabSoutenance": int, "etabSoutenanceEnCours": int, ...},
              "role": str | null,
              "query_used": str,
              "error": str | null
            }

            `totals` carries one counter per role and per bucket, the "EnCours"
            suffix marking theses in preparation.
        """
        include_trace = TRACE_DEFAULT if trace is None else trace
        out = _envelope("search_by_organisme", query_used=ppn,
                        organisme={"ppn": ppn, "name": None}, totals={}, role=role)

        name, name_error, events = await _get_text(
            f"{BASE_URL}/getorganismename/{urllib.parse.quote(ppn)}", trace=include_trace)
        if name_error is not None:
            out["error"] = (f"No organisation found for PPN {ppn} — getorganismename "
                            "returned nothing, so this PPN is probably a person; "
                            "try search_persons.")
            if include_trace:
                out["trace"] = events
            return out
        out["organisme"]["name"] = _clean(name)

        data, error, d_events = await _get_json(
            f"{BASE_URL}/organisme/{urllib.parse.quote(ppn)}", trace=include_trace)
        events.extend(d_events)
        if include_trace:
            out["trace"] = events
        if error or not isinstance(data, dict):
            out["error"] = error or "Unexpected response shape from /theses/organisme/"
            return out

        roles = (role,) if role else ORGANISME_ROLES
        results: list[dict[str, Any]] = []
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
                    record = _normalize_search_hit(t)
                    record["role"] = r
                    record["in_progress"] = in_progress
                    results.append(record)

        out["total_found"] = total
        out["returned"] = len(results)
        out["results"] = results
        return out

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

        uvx modal run mcp/theses-fr/modal/mcp_server_stateless.py::test_tool

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
