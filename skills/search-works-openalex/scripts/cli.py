#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ['httpx', 'python-dotenv']
# ///

"""
Connecteur OpenAlex — CLI autonome.
Base mondiale de publications académiques : https://help.openalex.org

Neuf sous-commandes : search, search-semantic, batch-lookup-by-doi,
get-citing-works, classify-text, resolve-entity, browse-topics, group-by,
translate-query. Sortie : JSON strict sur stdout, code de sortie toujours 0 —
les erreurs remontent dans le champ `error`.

Variables d'environnement :
  OPENALEX_API_KEY   (optionnel — relève le budget quotidien, cf. SKILL.md)
  OPENALEX_API_URL   (optionnel — base de l'API, pour un miroir ou un proxy)

Depuis février 2026 OpenAlex facture à l'appel sur un budget quotidien et
ignore `mailto` : le « polite pool » n'existe plus. Sans clé le budget est de
0,10 $/jour, avec une clé gratuite de 1 $/jour. `meta.cost_usd` est remonté
dans `cost_usd` sur chaque réponse pour que l'appelant suive sa consommation.

Le délai d'attente, le nombre de tentatives et le backoff sont des constantes
ci-dessous : ce sont des propriétés du connecteur, pas de l'installation.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.parse
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

OPENALEX_BASE = os.getenv("OPENALEX_API_URL", "https://api.openalex.org").rstrip("/")
OPENALEX_WORKS = f"{OPENALEX_BASE}/works"
OPENALEX_AUTHORS = f"{OPENALEX_BASE}/authors"
OPENALEX_INSTITUTIONS = f"{OPENALEX_BASE}/institutions"
OPENALEX_AUTOCOMPLETE = f"{OPENALEX_BASE}/autocomplete"
OPENALEX_QUERY = f"{OPENALEX_BASE}/query"

API_KEY = os.getenv("OPENALEX_API_KEY", "").strip()

HTTP_TIMEOUT = 15.0
MAX_RETRIES = 3
BACKOFF_BASE = 1.0
BACKOFF_FACTOR = 2.0
JITTER_MAX = 0.25
RETRIED_STATUS = {429, 403, 500, 502, 503, 504}

# Un seul client poolé pour le processus : httpx.get() reconstruirait le client
# — et rejouerait la poignée de main TLS — à chaque appel.
HTTP = httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True)

# `per-page` documenté à 100. La valeur 200 est encore acceptée (201 renvoie
# HTTP 400) mais elle est marquée dépréciée : on s'aligne sur le maximum
# documenté plutôt que sur la tolérance résiduelle du serveur.
MAX_PER_PAGE = 100

SELECT_FIELDS = ",".join([
    "id", "title", "authorships", "abstract_inverted_index",
    "doi", "publication_date", "publication_year",
    "primary_location", "best_oa_location", "open_access",
    "cited_by_count", "type", "topics", "primary_topic", "keywords",
    "referenced_works_count", "cited_by_api_url",
    "fwci", "citation_normalized_percentile", "is_retracted", "language",
    "awards", "is_xpac",
])

# Bornes propres à `search.semantic`, vérifiées contre l'API :
#   - `per-page` au-delà de 50 renvoie HTTP 400 ;
#   - `meta.count` vaut toujours 50, c'est le plafond de la recherche
#     vectorielle et non un décompte du corpus — d'où `total_found: null` ;
#   - au-delà de 2000 caractères le texte est tronqué avant plongement.
SEMANTIC_MAX_RESULTS = 50
SEMANTIC_MAX_CHARS = 2000

# `search.semantic` refuse d'être combiné à `search` et n'accepte qu'une liste
# fermée de filtres, que l'API énumère elle-même dans son message d'erreur 400 :
#   author.id, authorships.author.id, authorships.institutions.id,
#   authorships.institutions.lineage, funders.id, has_abstract, has_fulltext,
#   institution.id, institutions.id, is_oa, is_retracted, language,
#   open_access.is_oa, primary_location.license, primary_location.source.id,
#   publication_year, type
# `from_publication_date` / `to_publication_date` en sont absents : le bornage
# temporel de cette sous-commande passe donc par `publication_year`, ce qui est
# aussi pourquoi ses options s'appellent --year-from / --year-to et non
# --date-from / --date-to comme celles de `search`.
# Les filtres thématiques (`topics.id` & co.) n'y figurent pas non plus : sur
# `search-semantic` les options --topic/--field/... sont donc refusées.

# Entités acceptées par /autocomplete/<entity>.
AUTOCOMPLETE_ENTITIES = (
    "works", "authors", "sources", "institutions",
    "topics", "publishers", "funders", "keywords",
)

# Niveaux de la hiérarchie « aboutness », du plus large au plus fin, avec la
# clé de filtre à réinjecter dans `search --filter` ou `group-by`.
HIERARCHY_LEVELS = {
    "domains": "topics.domain.id",
    "fields": "topics.field.id",
    "subfields": "topics.subfield.id",
    "topics": "topics.id",
}

QUERY_FORMS = ("oql", "oqo", "oxurl")

CORPUS_CHOICES = ("core", "expansion", "all")


# ── Client HTTP ───────────────────────────────────────────────────────────────

def _with_key(params: dict[str, Any]) -> dict[str, Any]:
    """Ajoute la clé API si elle est configurée. Une clé vide envoyée en
    paramètre est rejetée par OpenAlex : on l'omet plutôt."""
    return {**params, "api_key": API_KEY} if API_KEY else dict(params)


def _redact(message: str) -> str:
    """Retire la clé API d'un message d'erreur.

    httpx met l'URL complète dans `str(exc)`, paramètres compris : sans ce
    filtre, une réponse 4xx recopie la clé sur stdout, c'est-à-dire dans le
    JSON que l'agent va journaliser.
    """
    text = str(message)
    if API_KEY:
        text = text.replace(API_KEY, "***")
    return re.sub(r"(api_key=)[^&\s'\"]+", r"\1***", text)


def _sleep(attempt: int) -> None:
    delay = BACKOFF_BASE * (BACKOFF_FACTOR ** (attempt - 1))
    time.sleep(delay + random.uniform(0.0, JITTER_MAX))


def get_json(url: str, params: dict[str, Any] | None = None) -> dict:
    """GET avec retry sur les statuts transitoires. Lève en dernier ressort."""
    params = _with_key(params or {})
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = HTTP.get(url, params=params)
            if resp.status_code in RETRIED_STATUS and attempt < MAX_RETRIES:
                _sleep(attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt == MAX_RETRIES:
                raise
            _sleep(attempt)
    raise RuntimeError(f"OpenAlex : échec après {MAX_RETRIES} tentatives sur {url}")


# ── Identifiants ──────────────────────────────────────────────────────────────

def _short_id(value: str | None) -> str | None:
    """Réduit une URL OpenAlex à son identifiant court.

    https://openalex.org/W123          -> W123
    https://openalex.org/fields/17     -> 17
    https://openalex.org/subfields/1707-> 1707
    """
    if not value:
        return None
    tail = str(value).rstrip("/").rsplit("/", 1)[-1]
    return tail or None


def _meta_cost(data: dict) -> float | None:
    return (data.get("meta") or {}).get("cost_usd")


def _meta_oql(data: dict) -> str | None:
    """L'OQL que l'API dit avoir compilé — utile pour vérifier qu'un filtre a
    bien été compris, et pour repartir en OQL depuis une requête classique."""
    return ((data.get("meta") or {}).get("x_query") or {}).get("oql")


# ── Formatage ─────────────────────────────────────────────────────────────────

def _reconstruct_abstract(inverted_index: dict | None) -> str | None:
    """Reconstruit le résumé en clair depuis l'index inversé d'OpenAlex."""
    if not inverted_index:
        return None
    try:
        positions: dict[int, str] = {}
        for word, pos_list in inverted_index.items():
            for pos in pos_list:
                positions[pos] = word
        return " ".join(positions[i] for i in sorted(positions))
    except Exception:
        return None


def _format_topic(topic: dict | None) -> dict | None:
    """Aplatit un topic OpenAlex en gardant les identifiants de chaque niveau :
    ce sont eux qui se réinjectent en filtre, pas les libellés."""
    if not topic:
        return None
    out: dict[str, Any] = {
        "id": _short_id(topic.get("id")),
        "display_name": topic.get("display_name"),
        "score": topic.get("score"),
    }
    for level in ("subfield", "field", "domain"):
        node = topic.get(level) or {}
        out[level] = {
            "id": _short_id(node.get("id")),
            "display_name": node.get("display_name"),
        } if node else None
    return out


def _format_result(work: dict) -> dict:
    """Normalise une notice OpenAlex brute vers le schéma commun du corpus."""
    authors = []
    author_details = []
    for a in work.get("authorships", []):
        author = a.get("author", {})
        name = author.get("display_name", "")
        authors.append(name)
        author_details.append({
            "name": name,
            "orcid": author.get("orcid"),
            "openalex_id": _short_id(author.get("id")),
            "institutions": [i.get("display_name", "") for i in a.get("institutions", [])],
        })

    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    best_oa = work.get("best_oa_location") or {}

    raw_doi = work.get("doi") or None
    doi = raw_doi.replace("https://doi.org/", "") if isinstance(raw_doi, str) and raw_doi else None
    openalex_id = _short_id(work.get("id"))
    publication_date = work.get("publication_date")
    publication_year = work.get("publication_year")
    source_url = work.get("id")

    percentile = work.get("citation_normalized_percentile") or {}

    record = {
        "source": "openalex",
        # Clés canoniques attendues par les autres skills du corpus.
        "id": openalex_id,
        "openalex_id": openalex_id,
        "title": work.get("title"),
        "authors": authors,
        "author_details": author_details,
        "abstract": _reconstruct_abstract(work.get("abstract_inverted_index")),
        "doi": doi,
        "pdf_url": best_oa.get("pdf_url") or best_oa.get("landing_page_url"),
        "url": source_url,
        "source_url": source_url,
        "year": publication_year,
        "date": publication_date or str(publication_year or ""),
        "doc_type": work.get("type"),
        "language": work.get("language"),
        "journal": source.get("display_name"),
        "cited_by_count": work.get("cited_by_count", 0),
        "referenced_works_count": work.get("referenced_works_count", 0),
        "is_open_access": (work.get("open_access") or {}).get("is_oa", False),
        "oa_status": (work.get("open_access") or {}).get("oa_status"),
        "is_retracted": work.get("is_retracted"),
        # Indicateurs bibliométriques normalisés par champ et par année : les
        # seuls comparables d'une discipline à l'autre.
        "fwci": work.get("fwci"),
        "citation_percentile": percentile.get("value"),
        "is_in_top_1_percent": percentile.get("is_in_top_1_percent"),
        "is_in_top_10_percent": percentile.get("is_in_top_10_percent"),
        # Thématiques : objets avec identifiants, réinjectables en filtre.
        "primary_topic": _format_topic(work.get("primary_topic")),
        "topics": [_format_topic(t) for t in work.get("topics", [])],
        "keywords": [k.get("display_name", "") for k in work.get("keywords", [])],
        "funders": sorted({
            (aw.get("funder") or {}).get("display_name")
            for aw in (work.get("awards") or [])
            if (aw.get("funder") or {}).get("display_name")
        }),
        "cited_by_api_url": work.get("cited_by_api_url"),
    }
    # `is_xpac` ne veut dire quelque chose que hors du corpus « core » : on ne
    # l'expose que lorsque l'API l'a renvoyé.
    if work.get("is_xpac") is not None:
        record["is_xpac"] = work.get("is_xpac")
    return record


# ── Résolution d'identifiants (pattern en deux étapes) ───────────────────────

def _resolve_author_id(name_or_orcid: str) -> str | None:
    """Résout un nom d'auteur ou un ORCID en identifiant OpenAlex."""
    if "orcid.org" in name_or_orcid or name_or_orcid.startswith("0000-"):
        orcid = (
            name_or_orcid if name_or_orcid.startswith("https://")
            else f"https://orcid.org/{name_or_orcid}"
        )
        try:
            data = get_json(f"{OPENALEX_AUTHORS}/{orcid}")
        except Exception:
            return None
        return _short_id(data.get("id"))

    data = get_json(OPENALEX_AUTHORS, {"search": name_or_orcid, "per-page": 1})
    results = data.get("results", [])
    if not results:
        return None
    return _short_id(results[0].get("id"))


def _resolve_institution_id(name_or_ror: str) -> str | None:
    """Résout un nom d'institution ou une URL ROR en identifiant OpenAlex.

    L'autocomplétion passe en premier : elle est gratuite, plus rapide, et
    classe par notoriété là où `?search=` classe par pertinence textuelle.
    """
    if "ror.org" in name_or_ror:
        try:
            data = get_json(f"{OPENALEX_INSTITUTIONS}/{name_or_ror}")
        except Exception:
            return None
        return _short_id(data.get("id"))

    try:
        data = get_json(f"{OPENALEX_AUTOCOMPLETE}/institutions", {"q": name_or_ror})
        results = data.get("results", [])
        if results:
            return _short_id(results[0].get("id"))
    except Exception:
        pass

    data = get_json(OPENALEX_INSTITUTIONS, {"search": name_or_ror, "per-page": 1})
    results = data.get("results", [])
    if not results:
        return None
    return _short_id(results[0].get("id"))


# ── Filtres thématiques ───────────────────────────────────────────────────────

def _topic_filters(
    topic: str | None,
    subfield: str | None,
    field: str | None,
    domain: str | None,
    scope: str,
) -> list[str]:
    """Traduit les options thématiques en filtres OpenAlex.

    `scope=any` interroge les trois topics d'une notice (`topics.*`, rappel) ;
    `scope=primary` ne retient que le topic principal (`primary_topic.*`,
    précision). Les deux familles de clés sont symétriques.
    """
    prefix = "primary_topic" if scope == "primary" else "topics"
    out = []
    if topic:
        out.append(f"{prefix}.id:{_short_id(topic)}")
    if subfield:
        out.append(f"{prefix}.subfield.id:{_short_id(subfield)}")
    if field:
        out.append(f"{prefix}.field.id:{_short_id(field)}")
    if domain:
        out.append(f"{prefix}.domain.id:{_short_id(domain)}")
    return out


# ── Opérations ────────────────────────────────────────────────────────────────

def search(
    query: str,
    max_results: int = 15,
    date_from: str | None = None,
    date_to: str | None = None,
    filter_open_access: bool = False,
    sort_by: str = "publication_date:desc",
    author: str | None = None,
    institution: str | None = None,
    institution_scope: str = "lineage",
    topic: str | None = None,
    subfield: str | None = None,
    field: str | None = None,
    domain: str | None = None,
    topic_scope: str = "any",
    corpus: str | None = None,
    exact: bool = False,
    cursor: str | None = None,
) -> dict:
    """Recherche de travaux : filtres date, accès ouvert, auteur, institution,
    thématique, corpus. `exact` bascule sur `search.exact`, qui seul accepte
    les jokers `*` / `?`."""
    filters = []
    if date_from:
        filters.append(f"from_publication_date:{date_from}")
    if date_to:
        filters.append(f"to_publication_date:{date_to}")
    if filter_open_access:
        filters.append("is_oa:true")

    if author:
        author_id = _resolve_author_id(author)
        if not author_id:
            return {"total_found": 0, "returned": 0, "results": [],
                    "error": f"Auteur introuvable dans OpenAlex : '{author}'",
                    "query_used": query, "filters_used": filters}
        filters.append(f"authorships.author.id:{author_id}")

    if institution:
        inst_id = _resolve_institution_id(institution)
        if not inst_id:
            return {"total_found": 0, "returned": 0, "results": [],
                    "error": (f"Institution introuvable dans OpenAlex : '{institution}'. "
                              "L'autocomplétion est sensible aux diacritiques — "
                              "essayer la forme accentuée, ou passer un ROR."),
                    "query_used": query, "filters_used": filters}
        # `lineage` remonte la hiérarchie : une requête sur une université
        # attrape ses laboratoires et ses UMR. C'est ce que compile OpenAlex
        # lui-même quand on écrit `institution is …` en OQL, d'où le défaut.
        key = ("authorships.institutions.lineage" if institution_scope == "lineage"
               else "authorships.institutions.id")
        filters.append(f"{key}:{inst_id}")

    filters.extend(_topic_filters(topic, subfield, field, domain, topic_scope))

    search_key = "search.exact" if exact else "search"
    params: dict[str, Any] = {
        search_key: query,
        "per-page": max(1, min(max_results, MAX_PER_PAGE)),
        "sort": sort_by,
        "select": SELECT_FIELDS,
    }
    if filters:
        params["filter"] = ",".join(filters)
    if corpus:
        params["corpus"] = corpus
    if cursor:
        # La pagination par curseur et `sort` par pertinence sont exclusives :
        # au-delà de 10 000 notices, seul le curseur passe.
        params["cursor"] = cursor

    data = get_json(OPENALEX_WORKS, params)
    results = data.get("results", [])
    return {
        "total_found": data.get("meta", {}).get("count", 0),
        "returned": len(results),
        "results": [_format_result(r) for r in results],
        "query_used": query,
        "filters_used": filters,
        "corpus": corpus or "core",
        "oql": _meta_oql(data),
        "next_cursor": data.get("meta", {}).get("next_cursor"),
        "cost_usd": _meta_cost(data),
        "error": None,
    }


def _semantic_year_filter(year_from: int | None, year_to: int | None) -> str | None:
    """Borne temporelle exprimée en `publication_year` (les bornes `>` et `<`
    d'OpenAlex sont strictes, d'où le décalage d'un an)."""
    if year_from and year_to:
        return f"publication_year:{year_from}-{year_to}"
    if year_from:
        return f"publication_year:>{year_from - 1}"
    if year_to:
        return f"publication_year:<{year_to + 1}"
    return None


def search_semantic(
    text: str,
    max_results: int = 15,
    year_from: int | None = None,
    year_to: int | None = None,
    filter_open_access: bool = False,
    institution: str | None = None,
    corpus: str | None = None,
) -> dict:
    """Recherche vectorielle : classe le corpus par proximité de sens avec un
    texte descriptif, sans dépendre des mots exacts qu'il emploie."""
    text = (text or "").strip()
    if len(text) < 20:
        return {"total_found": None, "returned": 0, "results": [],
                "error": "Texte trop court (minimum 20 caractères)",
                "query_used": text, "filters_used": []}

    filters = []
    year_filter = _semantic_year_filter(year_from, year_to)
    if year_filter:
        filters.append(year_filter)
    if filter_open_access:
        filters.append("is_oa:true")
    if institution:
        inst_id = _resolve_institution_id(institution)
        if not inst_id:
            return {"total_found": None, "returned": 0, "results": [],
                    "error": f"Institution introuvable dans OpenAlex : '{institution}'",
                    "query_used": text, "filters_used": filters}
        filters.append(f"authorships.institutions.lineage:{inst_id}")

    params: dict[str, Any] = {
        "search.semantic": text[:SEMANTIC_MAX_CHARS],
        "per-page": max(1, min(max_results, SEMANTIC_MAX_RESULTS)),
        "select": SELECT_FIELDS + ",relevance_score",
    }
    if filters:
        params["filter"] = ",".join(filters)
    if corpus:
        params["corpus"] = corpus

    data = get_json(OPENALEX_WORKS, params)
    results = data.get("results", [])
    formatted = []
    for work in results:
        record = _format_result(work)
        record["relevance_score"] = work.get("relevance_score")
        formatted.append(record)

    return {
        # `meta.count` renvoie toujours 50 : c'est le plafond du classement
        # vectoriel, pas un nombre de correspondances. Le déclarer serait mentir
        # sur la taille du gisement, d'où `null`.
        "total_found": None,
        "returned": len(formatted),
        "results": formatted,
        "query_used": text[:SEMANTIC_MAX_CHARS],
        "filters_used": filters,
        "corpus": corpus or "core",
        "truncated": len(text) > SEMANTIC_MAX_CHARS,
        "cost_usd": _meta_cost(data),
        "error": None,
    }


def batch_lookup_by_doi(dois: list[str]) -> dict:
    """Résout une liste de DOI en notices normalisées (lots de 50)."""
    if not dois:
        return {"total_found": 0, "returned": 0, "results": [],
                "cost_usd": None, "error": None}

    all_results = []
    total_cost = 0.0
    for i in range(0, len(dois), 50):
        batch = dois[i:i + 50]
        normalized = [
            d if d.startswith("https://doi.org/") else f"https://doi.org/{d}"
            for d in batch
        ]
        data = get_json(OPENALEX_WORKS, {
            "filter": "doi:" + "|".join(normalized),
            "per-page": len(batch),
            "select": SELECT_FIELDS,
        })
        all_results.extend(data.get("results", []))
        total_cost += _meta_cost(data) or 0.0
        if i + 50 < len(dois):
            time.sleep(0.15)

    return {
        "total_found": len(all_results),
        "returned": len(all_results),
        "results": [_format_result(r) for r in all_results],
        "requested": len(dois),
        "cost_usd": round(total_cost, 6) or None,
        "error": None,
    }


def get_citing_works(
    openalex_id: str,
    max_results: int = 20,
    cursor: str | None = None,
) -> dict:
    """Retourne les travaux qui citent un travail donné, les plus cités d'abord."""
    clean_id = _short_id(openalex_id)
    params: dict[str, Any] = {
        "filter": f"cites:{clean_id}",
        "per-page": max(1, min(max_results, MAX_PER_PAGE)),
        "sort": "cited_by_count:desc",
        "select": SELECT_FIELDS,
    }
    if cursor:
        params["cursor"] = cursor
    data = get_json(OPENALEX_WORKS, params)
    results = data.get("results", [])
    return {
        "total_found": data.get("meta", {}).get("count", 0),
        "returned": len(results),
        "results": [_format_result(r) for r in results],
        "cited_work_id": clean_id,
        "next_cursor": data.get("meta", {}).get("next_cursor"),
        "cost_usd": _meta_cost(data),
        "error": None,
    }


# ── classify-text ─────────────────────────────────────────────────────────────

CLASSIFY_LEVELS = (
    ("topics", "topics.id", lambda t: t),
    ("subfields", "topics.subfield.id", lambda t: t.get("subfield")),
    ("fields", "topics.field.id", lambda t: t.get("field")),
    ("domains", "topics.domain.id", lambda t: t.get("domain")),
)


def _aggregate_level(works: list[tuple[dict, float]], node_of) -> list[dict]:
    """Agrège un niveau de la hiérarchie sur un échantillon de notices.

    Le poids d'une notice est son `relevance_score` sémantique ; à l'intérieur
    d'une notice, celui d'un topic est son propre score. Le produit des deux
    évite qu'une notice faiblement pertinente pèse autant qu'un plein accord.
    """
    acc: dict[str, dict] = {}
    for work, weight in works:
        seen: set[str] = set()
        for topic in work.get("topics") or []:
            node = node_of(topic) or {}
            node_id = _short_id(node.get("id"))
            if not node_id:
                continue
            entry = acc.setdefault(node_id, {
                "id": node_id,
                "display_name": node.get("display_name"),
                "score": 0.0,
                "works": 0,
            })
            entry["score"] += weight * float(topic.get("score") or 0.0)
            if node_id not in seen:
                entry["works"] += 1
                seen.add(node_id)
    total = sum(e["score"] for e in acc.values()) or 1.0
    ranked = sorted(acc.values(), key=lambda e: e["score"], reverse=True)
    for entry in ranked:
        entry["score"] = round(entry["score"] / total, 4)
    return ranked


def classify_text(text: str, max_works: int = 25) -> dict:
    """Classe un texte dans la hiérarchie thématique d'OpenAlex.

    L'endpoint `/text` a été retiré du service (HTTP 500 systématique) et ne
    renvoyait de toute façon que des mots-clés et des `concepts` dépréciés.
    On reconstruit la capacité autrement : une recherche vectorielle place le
    texte dans le corpus, puis on agrège la thématique des notices voisines.
    Le résultat porte de vrais identifiants OpenAlex, réinjectables tels quels
    en filtre — ce que `/text` ne donnait pas — pour un centième du prix.

    Contrat local : cette opération ne renvoie pas de notices, donc pas
    l'enveloppe `{total_found, returned, results}`, mais un verdict.
    """
    text = (text or "").strip()
    if len(text) < 20:
        return {
            "source": "openalex", "command": "classify-text",
            "query_used": text, "based_on_works": 0,
            "topics": [], "subfields": [], "fields": [], "domains": [],
            "keywords": [], "filter_keys": {}, "cost_usd": None,
            "error": "Texte trop court (minimum 20 caractères)",
        }

    data = get_json(OPENALEX_WORKS, {
        "search.semantic": text[:SEMANTIC_MAX_CHARS],
        "per-page": max(1, min(max_works, SEMANTIC_MAX_RESULTS)),
        "select": "id,relevance_score,topics,keywords",
    })
    results = data.get("results", [])
    weighted = [(w, float(w.get("relevance_score") or 0.0)) for w in results]

    keyword_scores: dict[str, float] = {}
    for work, weight in weighted:
        for kw in work.get("keywords") or []:
            name = kw.get("display_name")
            if name:
                keyword_scores[name] = keyword_scores.get(name, 0.0) + weight * float(
                    kw.get("score") or 1.0
                )
    keywords = [
        k for k, _ in sorted(keyword_scores.items(), key=lambda kv: kv[1], reverse=True)
    ][:15]

    out: dict[str, Any] = {
        "source": "openalex",
        "command": "classify-text",
        "query_used": text[:SEMANTIC_MAX_CHARS],
        "truncated": len(text) > SEMANTIC_MAX_CHARS,
        "based_on_works": len(results),
    }
    for name, _filter_key, node_of in CLASSIFY_LEVELS:
        out[name] = _aggregate_level(weighted, node_of)[:10]
    out["keywords"] = keywords
    # La clé de filtre à réutiliser pour chaque niveau : c'est ce qui rend le
    # verdict actionnable sans que l'agent ait à deviner la syntaxe.
    out["filter_keys"] = {name: key for name, key, _ in CLASSIFY_LEVELS}
    out["cost_usd"] = _meta_cost(data)
    out["error"] = None if results else "Aucune notice voisine trouvée pour ce texte"
    return out


# ── resolve-entity ────────────────────────────────────────────────────────────

# Mots outils et génériques d'organisation : présents dans des milliers de
# noms, ils ne distinguent rien. Les retirer est ce qui fait de « université de
# Strasbourg » le jeton « Strasbourg » et non « universite », qui rattacherait
# la requête à la première « Vrije Universiteit » venue.
GENERIC_TOKENS = {
    "universite", "université", "university", "universität", "universiteit",
    "universidad", "universita", "institut", "institute", "college", "school",
    "laboratoire", "laboratory", "centre", "center", "national", "research",
    "hospital", "hopital", "ecole", "faculty", "faculte", "department",
    "departement", "the", "and", "for", "des", "les", "del", "della",
}


def _distinctive_token(query: str) -> str | None:
    """Le mot le plus long une fois les génériques écartés. `None` s'il n'en
    reste aucun, ou si la requête n'en comptait déjà qu'un."""
    tokens = [t for t in re.split(r"[^\w]+", query, flags=re.UNICODE) if len(t) > 3]
    candidates = [t for t in tokens if t.lower() not in GENERIC_TOKENS]
    if not candidates or len(tokens) == 1:
        return None
    best = max(candidates, key=len)
    return best if best.lower() != query.lower() else None


def _autocomplete(entity_type: str, q: str) -> list[dict]:
    data = get_json(f"{OPENALEX_AUTOCOMPLETE}/{entity_type}", {"q": q})
    return data.get("results", [])


def _entity_search(entity_type: str, q: str, limit: int) -> list[dict]:
    """Repli plein texte sur l'endpoint d'entité, remis à la forme
    d'/autocomplete pour que l'appelant n'ait qu'un schéma à lire."""
    data = get_json(f"{OPENALEX_BASE}/{entity_type}", {
        "search": q, "per-page": max(1, min(limit, MAX_PER_PAGE)),
    })

    def ids_of(r):
        return r.get("ids") or {}

    return [
        {
            "id": r.get("id"),
            "display_name": r.get("display_name"),
            "hint": r.get("description") if isinstance(r.get("description"), str) else None,
            "external_id": ids_of(r).get("ror") or ids_of(r).get("orcid")
            or ids_of(r).get("wikidata"),
            "works_count": r.get("works_count"),
            "cited_by_count": r.get("cited_by_count"),
            "entity_type": entity_type.rstrip("s"),
            "filter_key": None,
        }
        for r in data.get("results", [])
    ]


def _shape_entity(r: dict, entity_type: str) -> dict:
    return {
        "source": "openalex",
        "id": _short_id(r.get("id")),
        "url": r.get("id"),
        "display_name": r.get("display_name"),
        "entity_type": r.get("entity_type") or entity_type.rstrip("s"),
        "hint": r.get("hint"),
        "external_id": r.get("external_id"),
        "works_count": r.get("works_count"),
        "cited_by_count": r.get("cited_by_count"),
        # Fourni par /autocomplete ; absent sur le repli plein texte, où l'API
        # ne le calcule pas.
        "filter_key": r.get("filter_key"),
    }


def resolve_entity(query: str, entity_type: str, max_results: int = 5) -> dict:
    """Résout un nom en entité OpenAlex via /autocomplete.

    L'autocomplétion est gratuite et répond en ~200 ms. Chaque résultat porte
    son `filter_key` : la clé de filtre qu'OpenAlex lui-même utiliserait pour
    cette entité — `authorships.institutions.lineage` pour une institution,
    `topics.id` pour un topic. C'est l'étape à faire avant tout filtrage.

    L'index d'autocomplétion est **sensible aux diacritiques** et fonctionne
    par préfixe : « universite de strasbourg » ne renvoie rien là où
    « strasbourg » renvoie l'université. Quand la requête complète ne donne
    rien, une requête élargie est tentée, mais son produit part dans
    `suggestions` et **jamais** dans `results` : substituer silencieusement une
    entité voisine à celle qui était demandée, c'est livrer un identifiant faux
    à un filtre qui ne le contestera pas. L'appelant choisit.
    """
    query = (query or "").strip()
    if not query:
        return {"total_found": 0, "returned": 0, "results": [], "suggestions": [],
                "query_used": query, "entity_type": entity_type,
                "cost_usd": None, "error": "Requête vide"}

    results = _autocomplete(entity_type, query)
    if not results:
        try:
            results = _entity_search(entity_type, query, max_results)
        except Exception:
            results = []

    if results:
        formatted = [_shape_entity(r, entity_type) for r in results[:max_results]]
        return {
            "total_found": len(results),
            "returned": len(formatted),
            "results": formatted,
            "suggestions": [],
            "query_used": query,
            "entity_type": entity_type,
            "cost_usd": None,
            "error": None,
        }

    suggestions: list[dict] = []
    token = _distinctive_token(query)
    if token:
        try:
            suggestions = [
                _shape_entity(r, entity_type)
                for r in _autocomplete(entity_type, token)[:max_results]
            ]
        except Exception:
            suggestions = []

    hint = (
        f" Requête élargie sur '{token}' : {len(suggestions)} piste(s) dans "
        "`suggestions`, à valider avant usage." if suggestions else ""
    )
    return {
        "total_found": 0,
        "returned": 0,
        "results": [],
        "suggestions": suggestions,
        "query_used": query,
        "entity_type": entity_type,
        "widened_query": token,
        "cost_usd": None,
        "error": (
            f"Aucune entité '{entity_type}' pour '{query}'. L'autocomplétion est "
            "sensible aux diacritiques et fonctionne par préfixe : essayer la forme "
            "accentuée, un mot distinctif seul, ou un identifiant externe (ROR, ORCID)."
            + hint
        ),
    }


# ── browse-topics ─────────────────────────────────────────────────────────────

def browse_topics(
    level: str = "topics",
    query: str | None = None,
    field: str | None = None,
    domain: str | None = None,
    max_results: int = 25,
) -> dict:
    """Parcourt la hiérarchie « aboutness » : 4 domaines, 26 champs,
    252 sous-champs, 4 516 topics.

    Les trois niveaux hauts tiennent dans `references/topic-hierarchy.md`, à
    lire sans appel réseau. Cette opération existe pour les 4 516 topics, trop
    nombreux pour un fichier, et pour la recherche par mot-clé.
    """
    params: dict[str, Any] = {
        "per-page": max(1, min(max_results, MAX_PER_PAGE)),
    }
    if query:
        params["search"] = query
    filters = []
    if field:
        filters.append(f"field.id:{_short_id(field)}")
    if domain:
        filters.append(f"domain.id:{_short_id(domain)}")
    if filters:
        params["filter"] = ",".join(filters)
    if not query:
        params["sort"] = "works_count:desc"

    data = get_json(f"{OPENALEX_BASE}/{level}", params)
    results = data.get("results", [])
    formatted = []
    for r in results:
        record = {
            "source": "openalex",
            "id": _short_id(r.get("id")),
            "url": r.get("id"),
            "display_name": r.get("display_name"),
            "level": level.rstrip("s"),
            "description": r.get("description"),
            "keywords": r.get("keywords") or [],
            "works_count": r.get("works_count"),
            "cited_by_count": r.get("cited_by_count"),
            "filter_key": HIERARCHY_LEVELS[level],
        }
        for parent in ("subfield", "field", "domain"):
            node = r.get(parent)
            if node:
                record[parent] = {
                    "id": _short_id(node.get("id")),
                    "display_name": node.get("display_name"),
                }
        formatted.append(record)

    return {
        "total_found": data.get("meta", {}).get("count", 0),
        "returned": len(formatted),
        "results": formatted,
        "level": level,
        "query_used": query,
        "filters_used": filters,
        "cost_usd": _meta_cost(data),
        "error": None,
    }


# ── group-by ──────────────────────────────────────────────────────────────────

def group_by(
    dimension: str,
    query: str | None = None,
    filters: str | None = None,
    entity: str = "works",
    include_unknown: bool = False,
    max_groups: int = 100,
) -> dict:
    """Compte sans rapatrier : renvoie la distribution d'un ensemble le long
    d'une dimension.

    Contrat local : cette opération ne renvoie pas de notices, donc pas
    l'enveloppe `{total_found, returned, results}` mais `groups`.
    Une requête `group_by` coûte le prix d'une recherche, quel que soit le
    nombre de notices agrégées — c'est le moyen le moins cher de cadrer un
    corpus avant de le parcourir.
    """
    key = f"{dimension}:include_unknown" if include_unknown else dimension
    params: dict[str, Any] = {
        "group_by": key,
        "per-page": max(1, min(max_groups, MAX_PER_PAGE)),
    }
    if query:
        params["search"] = query
    if filters:
        params["filter"] = filters

    data = get_json(f"{OPENALEX_BASE}/{entity}", params)
    groups = [
        {
            "key": _short_id(g.get("key")) if str(g.get("key", "")).startswith("http")
            else g.get("key"),
            "key_url": g.get("key") if str(g.get("key", "")).startswith("http") else None,
            "key_display_name": g.get("key_display_name"),
            "count": g.get("count"),
        }
        for g in data.get("group_by", [])
    ]
    meta = data.get("meta", {})
    return {
        "source": "openalex",
        "command": "group-by",
        "entity": entity,
        "dimension": dimension,
        "query_used": query,
        "filters_used": filters,
        # Nombre de notices dans l'ensemble agrégé, pas nombre de groupes.
        "total_found": meta.get("count"),
        "groups_count": meta.get("groups_count"),
        "groups": groups,
        "oql": _meta_oql(data),
        "cost_usd": _meta_cost(data),
        "error": None,
    }


# ── translate-query ───────────────────────────────────────────────────────────

def translate_query(query: str, form: str = "oql") -> dict:
    """Traduit une requête entre ses trois formes et la valide, sans l'exécuter.

    `/query` ne touche pas l'index : la traduction est facturée au tarif le plus
    bas (0,0001 $ l'appel). C'est le moyen le moins cher de vérifier qu'un filtre
    est bien formé avant de payer une recherche, et de découvrir la clé de filtre
    qui correspond à une intention exprimée en OQL.

    Contrat local : renvoie un verdict de traduction, pas des notices.
    """
    query = (query or "").strip()
    if not query:
        return {"source": "openalex", "command": "translate-query", "form": form,
                "valid": False, "oql": None, "oql_oneline": None, "oqo": None,
                "oxurl": None, "diagnostics": [], "error": "Requête vide"}

    # La requête est un segment de chemin, pas un paramètre : /query/oql?q=…
    # est lu comme un identifiant et renvoie « OpenAlex ID format not recognized ».
    url = f"{OPENALEX_QUERY}/{form}/{urllib.parse.quote(query, safe='')}"
    try:
        data = get_json(url)
    except httpx.HTTPStatusError as exc:
        # Une requête qui ne parse pas renvoie 400 avec un corps structuré :
        # c'est un diagnostic, pas une panne.
        try:
            data = exc.response.json()
        except Exception:
            raise

    # Deux formes selon le code : 200 renvoie `diagnostics` (vide si tout va
    # bien), 400 renvoie `validation.errors`. On les ramène à une seule liste.
    validation = data.get("validation") or {}
    diagnostics = data.get("diagnostics") or validation.get("errors") or []
    valid = data.get("valid")
    if valid is None:
        valid = validation.get("valid")
    if valid is None:
        valid = bool(data.get("oql") or data.get("oxurl") or data.get("oqo"))

    first_message = None
    if diagnostics:
        first = diagnostics[0]
        first_message = first.get("message") if isinstance(first, dict) else str(first)

    # `oql_render_v2` est un arbre de rendu destiné aux éditeurs : des milliers
    # de tokens dont un agent ne fait rien. On ne le remonte pas.
    return {
        "source": "openalex",
        "command": "translate-query",
        "form": form,
        "query_used": query,
        "valid": bool(valid),
        "oql": data.get("oql"),
        "oql_oneline": data.get("oql_oneline"),
        "oqo": data.get("oqo"),
        "oxurl": data.get("oxurl"),
        "api_url": f"{OPENALEX_BASE}{data['oxurl']}" if data.get("oxurl") else None,
        "diagnostics": diagnostics,
        "error": None if valid else (
            first_message or data.get("message") or "Requête non traduisible"
        ),
    }


# ── Façade CLI ────────────────────────────────────────────────────────────────

def _print(data: object) -> int:
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


def _read_text(inline: str | None, path: str | None) -> str:
    text = (inline or "").strip()
    if not text and path:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read().strip()
    return text


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="openalex", description="Recherche et analyse de publications via OpenAlex."
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    ap_s = sub.add_parser("search", help="Recherche plein texte de travaux")
    ap_s.add_argument("--query", required=True)
    ap_s.add_argument("--max-results", type=int, default=15,
                      help=f"Max {MAX_PER_PAGE}")
    ap_s.add_argument("--date-from", default=None)
    ap_s.add_argument("--date-to", default=None)
    ap_s.add_argument("--oa", action="store_true")
    ap_s.add_argument("--sort-by", default="publication_date:desc")
    ap_s.add_argument("--author", default=None)
    ap_s.add_argument("--institution", default=None)
    ap_s.add_argument("--institution-scope", choices=("lineage", "exact"),
                      default="lineage",
                      help="lineage (défaut) inclut les entités rattachées")
    ap_s.add_argument("--topic", default=None, help="Identifiant de topic, ex. T10601")
    ap_s.add_argument("--subfield", default=None, help="Identifiant de sous-champ, ex. 1707")
    ap_s.add_argument("--field", default=None, help="Identifiant de champ, ex. 17")
    ap_s.add_argument("--domain", default=None, help="Identifiant de domaine, ex. 3")
    ap_s.add_argument("--topic-scope", choices=("any", "primary"), default="any",
                      help="any (défaut, rappel) ou primary (précision)")
    ap_s.add_argument("--corpus", choices=CORPUS_CHOICES, default=None)
    ap_s.add_argument("--exact", action="store_true",
                      help="Bascule sur search.exact — requis pour les jokers * et ?")
    ap_s.add_argument("--cursor", default=None,
                      help="Curseur de pagination ; '*' pour la première page")

    ap_sem = sub.add_parser(
        "search-semantic",
        help="Recherche vectorielle : par le sens d'un texte, pas par mots-clés",
    )
    ap_sem.add_argument("--text", default=None,
                        help=f"Description ou résumé (min. 20 car., tronqué à {SEMANTIC_MAX_CHARS})")
    ap_sem.add_argument("--file", default=None, help="Fichier texte ; utilisé si --text est absent")
    ap_sem.add_argument("--max-results", type=int, default=15,
                        help=f"Max {SEMANTIC_MAX_RESULTS}")
    ap_sem.add_argument("--year-from", type=int, default=None,
                        help="Année de publication minimale (incluse)")
    ap_sem.add_argument("--year-to", type=int, default=None,
                        help="Année de publication maximale (incluse)")
    ap_sem.add_argument("--oa", action="store_true")
    ap_sem.add_argument("--institution", default=None)
    ap_sem.add_argument("--corpus", choices=CORPUS_CHOICES, default=None)

    ap_b = sub.add_parser("batch-lookup-by-doi", help="Résout un ou plusieurs DOI")
    ap_b.add_argument("--doi", action="append", default=[], help="Répétable")
    ap_b.add_argument("--doi-file", default=None, help="Fichier texte, un DOI par ligne")

    ap_c = sub.add_parser("get-citing-works", help="Travaux citant un travail donné")
    ap_c.add_argument("--openalex-id", required=True)
    ap_c.add_argument("--max-results", type=int, default=20, help=f"Max {MAX_PER_PAGE}")
    ap_c.add_argument("--cursor", default=None)

    ap_t = sub.add_parser(
        "classify-text",
        help="Classe un texte dans la hiérarchie thématique (topics/champs/domaines)",
    )
    ap_t.add_argument("--text", default=None)
    ap_t.add_argument("--file", default=None)
    ap_t.add_argument("--max-works", type=int, default=25,
                      help=f"Notices voisines agrégées (max {SEMANTIC_MAX_RESULTS})")

    ap_r = sub.add_parser(
        "resolve-entity",
        help="Résout un nom en identifiant OpenAlex, avec sa clé de filtre",
    )
    ap_r.add_argument("--query", required=True)
    ap_r.add_argument("--type", dest="entity_type", choices=AUTOCOMPLETE_ENTITIES,
                      default="institutions")
    ap_r.add_argument("--max-results", type=int, default=5)

    ap_h = sub.add_parser("browse-topics", help="Parcourt la hiérarchie thématique")
    ap_h.add_argument("--level", choices=tuple(HIERARCHY_LEVELS), default="topics")
    ap_h.add_argument("--query", default=None, help="Recherche plein texte dans le niveau")
    ap_h.add_argument("--field", default=None, help="Restreint à un champ, ex. 17")
    ap_h.add_argument("--domain", default=None, help="Restreint à un domaine, ex. 3")
    ap_h.add_argument("--max-results", type=int, default=25, help=f"Max {MAX_PER_PAGE}")

    ap_g = sub.add_parser("group-by", help="Compte par dimension, sans rapatrier les notices")
    ap_g.add_argument("--dimension", required=True,
                      help="Ex. primary_topic.field.id, publication_year, type")
    ap_g.add_argument("--query", default=None)
    ap_g.add_argument("--filters", default=None,
                      help="Filtres OpenAlex bruts, ex. 'publication_year:2023,is_oa:true'")
    ap_g.add_argument("--entity", default="works")
    ap_g.add_argument("--include-unknown", action="store_true")
    ap_g.add_argument("--max-groups", type=int, default=100, help=f"Max {MAX_PER_PAGE}")

    ap_q = sub.add_parser(
        "translate-query",
        help="Traduit et valide une requête entre OQL, OQO et URL classique (gratuit)",
    )
    ap_q.add_argument("--query", required=True)
    ap_q.add_argument("--form", choices=QUERY_FORMS, default="oql",
                      help="Forme de la requête fournie")

    args = ap.parse_args()

    try:
        if args.cmd == "search":
            return _print(search(
                query=args.query,
                max_results=args.max_results,
                date_from=args.date_from,
                date_to=args.date_to,
                filter_open_access=args.oa,
                sort_by=args.sort_by,
                author=args.author,
                institution=args.institution,
                institution_scope=args.institution_scope,
                topic=args.topic,
                subfield=args.subfield,
                field=args.field,
                domain=args.domain,
                topic_scope=args.topic_scope,
                corpus=args.corpus,
                exact=args.exact,
                cursor=args.cursor,
            ))

        if args.cmd == "search-semantic":
            return _print(search_semantic(
                text=_read_text(args.text, args.file),
                max_results=args.max_results,
                year_from=args.year_from,
                year_to=args.year_to,
                filter_open_access=args.oa,
                institution=args.institution,
                corpus=args.corpus,
            ))

        if args.cmd == "batch-lookup-by-doi":
            dois = list(args.doi or [])
            if args.doi_file:
                with open(args.doi_file, "r", encoding="utf-8") as f:
                    dois.extend([ln.strip() for ln in f if ln.strip()])
            return _print(batch_lookup_by_doi(dois))

        if args.cmd == "get-citing-works":
            return _print(get_citing_works(args.openalex_id, args.max_results, args.cursor))

        if args.cmd == "classify-text":
            return _print(classify_text(_read_text(args.text, args.file), args.max_works))

        if args.cmd == "resolve-entity":
            return _print(resolve_entity(args.query, args.entity_type, args.max_results))

        if args.cmd == "browse-topics":
            return _print(browse_topics(
                level=args.level, query=args.query, field=args.field,
                domain=args.domain, max_results=args.max_results,
            ))

        if args.cmd == "group-by":
            return _print(group_by(
                dimension=args.dimension, query=args.query, filters=args.filters,
                entity=args.entity, include_unknown=args.include_unknown,
                max_groups=args.max_groups,
            ))

        if args.cmd == "translate-query":
            return _print(translate_query(args.query, args.form))
    except Exception as exc:
        # Contrat du corpus : l'erreur est une donnée, pas un code de sortie —
        # et une donnée d'où la clé API a été retirée.
        return _print({"total_found": 0, "returned": 0, "results": [],
                       "error": _redact(exc)})

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
