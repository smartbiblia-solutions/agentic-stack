#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ['httpx', 'python-dotenv']
# ///

"""
Connecteur OpenAlex — CLI autonome.
Base mondiale de publications académiques : https://docs.openalex.org

Quatre sous-commandes : search, batch-lookup-by-doi, get-citing-works,
classify-text. Sortie : JSON strict sur stdout, code de sortie toujours 0 —
les erreurs remontent dans le champ `error`.

Variable d'environnement :
  OPENALEX_API_KEY   (optionnel — « polite pool », limites de taux plus hautes)

Le délai d'attente, le nombre de tentatives et le backoff sont des constantes
ci-dessous : ce sont des propriétés du connecteur, pas de l'installation.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

OPENALEX_BASE = "https://api.openalex.org"
OPENALEX_WORKS = f"{OPENALEX_BASE}/works"
OPENALEX_AUTHORS = f"{OPENALEX_BASE}/authors"
OPENALEX_INSTITUTIONS = f"{OPENALEX_BASE}/institutions"
OPENALEX_TEXT = f"{OPENALEX_BASE}/text"

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

SELECT_FIELDS = ",".join([
    "id", "title", "authorships", "abstract_inverted_index",
    "doi", "publication_date", "publication_year",
    "primary_location", "best_oa_location", "open_access",
    "cited_by_count", "type", "topics", "keywords",
    "referenced_works_count", "cited_by_api_url",
])


# ── Client HTTP ───────────────────────────────────────────────────────────────

def _with_key(params: dict[str, Any]) -> dict[str, Any]:
    """Ajoute la clé API si elle est configurée. Une clé vide envoyée en
    paramètre est rejetée par OpenAlex : on l'omet plutôt."""
    return {**params, "api_key": API_KEY} if API_KEY else dict(params)


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
            "openalex_id": (author.get("id", "") or "").replace("https://openalex.org/", ""),
            "institutions": [i.get("display_name", "") for i in a.get("institutions", [])],
        })

    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    best_oa = work.get("best_oa_location") or {}

    raw_doi = work.get("doi") or None
    doi = raw_doi.replace("https://doi.org/", "") if isinstance(raw_doi, str) and raw_doi else None
    openalex_id = (work.get("id") or "").replace("https://openalex.org/", "")
    publication_date = work.get("publication_date")
    publication_year = work.get("publication_year")
    source_url = work.get("id")

    return {
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
        "journal": source.get("display_name"),
        "cited_by_count": work.get("cited_by_count", 0),
        "referenced_works_count": work.get("referenced_works_count", 0),
        "is_open_access": (work.get("open_access") or {}).get("is_oa", False),
        "oa_status": (work.get("open_access") or {}).get("oa_status"),
        "topics": [
            t.get("display_name", "") for t in work.get("topics", [])
            if t.get("score", 0) > 0.3
        ][:5],
        "keywords": [k.get("display_name", "") for k in work.get("keywords", [])],
        "cited_by_api_url": work.get("cited_by_api_url"),
    }


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
        return (data.get("id", "") or "").replace("https://openalex.org/", "") or None

    data = get_json(OPENALEX_AUTHORS, {"search": name_or_orcid, "per-page": 1})
    results = data.get("results", [])
    if not results:
        return None
    return (results[0].get("id") or "").replace("https://openalex.org/", "") or None


def _resolve_institution_id(name_or_ror: str) -> str | None:
    """Résout un nom d'institution ou une URL ROR en identifiant OpenAlex."""
    if "ror.org" in name_or_ror:
        try:
            data = get_json(f"{OPENALEX_INSTITUTIONS}/{name_or_ror}")
        except Exception:
            return None
        return (data.get("id", "") or "").replace("https://openalex.org/", "") or None

    data = get_json(OPENALEX_INSTITUTIONS, {"search": name_or_ror, "per-page": 1})
    results = data.get("results", [])
    if not results:
        return None
    return (results[0].get("id") or "").replace("https://openalex.org/", "") or None


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
) -> dict:
    """Recherche de travaux, avec filtres date / accès ouvert / auteur / institution."""
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
                    "error": f"Institution introuvable dans OpenAlex : '{institution}'",
                    "query_used": query, "filters_used": filters}
        filters.append(f"authorships.institutions.id:{inst_id}")

    params: dict[str, Any] = {
        "search": query,
        "per-page": min(max_results, 200),
        "sort": sort_by,
        "select": SELECT_FIELDS,
    }
    if filters:
        params["filter"] = ",".join(filters)

    data = get_json(OPENALEX_WORKS, params)
    results = data.get("results", [])
    return {
        "total_found": data.get("meta", {}).get("count", 0),
        "returned": len(results),
        "results": [_format_result(r) for r in results],
        "query_used": query,
        "filters_used": filters,
        "error": None,
    }


def batch_lookup_by_doi(dois: list[str]) -> dict:
    """Résout une liste de DOI en notices normalisées (lots de 50)."""
    if not dois:
        return {"total_found": 0, "returned": 0, "results": [], "error": None}

    all_results = []
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
        if i + 50 < len(dois):
            time.sleep(0.15)

    return {
        "total_found": len(all_results),
        "returned": len(all_results),
        "results": [_format_result(r) for r in all_results],
        "error": None,
    }


def get_citing_works(openalex_id: str, max_results: int = 20) -> dict:
    """Retourne les travaux qui citent un travail donné, les plus cités d'abord."""
    clean_id = openalex_id.replace("https://openalex.org/", "")
    data = get_json(OPENALEX_WORKS, {
        "filter": f"cites:{clean_id}",
        "per-page": min(max_results, 200),
        "sort": "cited_by_count:desc",
        "select": SELECT_FIELDS,
    })
    results = data.get("results", [])
    return {
        "total_found": data.get("meta", {}).get("count", 0),
        "returned": len(results),
        "results": [_format_result(r) for r in results],
        "cited_work_id": clean_id,
        "error": None,
    }


def classify_text(text: str) -> dict:
    """Classe un titre ou un résumé via l'endpoint /text d'OpenAlex."""
    text = text.strip()
    if len(text) < 20:
        return {"topics": [], "keywords": [], "error": "Texte trop court (minimum 20 caractères)"}

    data = get_json(OPENALEX_TEXT, {"title": text[:2000]})
    return {
        "topics": [
            {
                "name": t.get("display_name"),
                "score": t.get("score"),
                "field": (t.get("subfield") or {}).get("display_name"),
                "domain": (t.get("domain") or {}).get("display_name"),
            }
            for t in data.get("topics", [])
        ],
        "keywords": [k.get("display_name") for k in data.get("keywords", [])],
        "error": None,
    }


# ── Façade CLI ────────────────────────────────────────────────────────────────

def _print(data: object) -> int:
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="openalex", description="Recherche et analyse de publications via OpenAlex."
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    ap_s = sub.add_parser("search", help="Recherche plein texte de travaux")
    ap_s.add_argument("--query", required=True)
    ap_s.add_argument("--max-results", type=int, default=15)
    ap_s.add_argument("--date-from", default=None)
    ap_s.add_argument("--date-to", default=None)
    ap_s.add_argument("--oa", action="store_true")
    ap_s.add_argument("--sort-by", default="publication_date:desc")
    ap_s.add_argument("--author", default=None)
    ap_s.add_argument("--institution", default=None)

    ap_b = sub.add_parser("batch-lookup-by-doi", help="Résout un ou plusieurs DOI")
    ap_b.add_argument("--doi", action="append", default=[], help="Répétable")
    ap_b.add_argument("--doi-file", default=None, help="Fichier texte, un DOI par ligne")

    ap_c = sub.add_parser("get-citing-works", help="Travaux citant un travail donné")
    ap_c.add_argument("--openalex-id", required=True)
    ap_c.add_argument("--max-results", type=int, default=20)

    ap_t = sub.add_parser("classify-text", help="Classe un texte par thématique")
    ap_t.add_argument("--text", default=None)
    ap_t.add_argument("--file", default=None)

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
            ))

        if args.cmd == "batch-lookup-by-doi":
            dois = list(args.doi or [])
            if args.doi_file:
                with open(args.doi_file, "r", encoding="utf-8") as f:
                    dois.extend([ln.strip() for ln in f if ln.strip()])
            return _print(batch_lookup_by_doi(dois))

        if args.cmd == "get-citing-works":
            return _print(get_citing_works(args.openalex_id, args.max_results))

        if args.cmd == "classify-text":
            text = (args.text or "").strip()
            if not text and args.file:
                with open(args.file, "r", encoding="utf-8") as f:
                    text = f.read().strip()
            return _print(classify_text(text))
    except Exception as exc:
        # Contrat du corpus : l'erreur est une donnée, pas un code de sortie.
        return _print({"total_found": 0, "returned": 0, "results": [], "error": str(exc)})

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
