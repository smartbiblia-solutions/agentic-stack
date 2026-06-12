#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ['fastmcp>=2.0', 'requests']
# ///

"""
Sudoc SRU MCP server.

Expose le catalogue Sudoc (Système Universitaire de Documentation, ABES)
via le protocole MCP. Toutes les interrogations passent par le service SRU
public de l'Abes : https://www.sudoc.abes.fr/cbs/sru/
Aucune clé API requise.

Trois façons de lancer le serveur :

  # 1. Zero-install — exécution directe depuis GitHub (uv télécharge tout)
  uv run https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/sudoc-sru/server_mcp.py \
      --transport stdio

  # 2. Local stdio — le client lance le processus (recommandé pour desktop/IDE)
  uv run /chemin/vers/mcp/sudoc-sru/server_mcp.py --transport stdio

  # 3. Local HTTP — un seul serveur, plusieurs clients connectés par URL
  uv run /chemin/vers/mcp/sudoc-sru/server_mcp.py \
      --host 0.0.0.0 --port 8012 --transport streamable-http

Options:
    --host          TEXT    Bind host                    [default: 0.0.0.0]
    --port          INT     Bind port                    [default: 8012]
    --transport     TEXT    stdio | sse | streamable-http [default: streamable-http]
    --http-timeout  FLOAT   Timeout par requête (s)      [default: 30.0]
    --max-retries   INT     Tentatives par requête       [default: 3]
    --backoff-base  FLOAT   Base du backoff exponentiel  [default: 1.0]
    --backoff-factor FLOAT  Multiplicateur de backoff    [default: 2.0]
    --jitter-max    FLOAT   Gigue max par retry (s)      [default: 0.25]
    --trace                 Inclure le journal HTTP dans les réponses

Protocole SRU — règle d'encodage critique :
    Dans une requête SRU, le signe `=` est RÉSERVÉ aux paramètres d'URL
    (operation=searchRetrieve, etc.). Pour exprimer la relation index=terme
    à l'intérieur du paramètre `query=`, il faut obligatoirement encoder
    `=` en `%3D`. Exemple : query=mti%3Djardins
    Les outils de ce serveur acceptent la syntaxe naturelle (`mti=jardins`)
    et appliquent l'encodage automatiquement.
"""

from __future__ import annotations

import argparse
import os
import random
import re
import time
import xml.etree.ElementTree as ET
from typing import Any

import requests
from fastmcp import FastMCP


# ══════════════════════════════════════════════════════════════════════════════
# SECTION : CLI args & config
# ══════════════════════════════════════════════════════════════════════════════

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Sudoc SRU MCP server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--host",           default=os.environ.get("MCP_HOST", "0.0.0.0"))
    p.add_argument("--port",           type=int,   default=int(os.environ.get("MCP_PORT", "8012")))
    p.add_argument("--transport",      default=os.environ.get("MCP_TRANSPORT", "streamable-http"),
                   choices=["stdio", "sse", "streamable-http"])
    p.add_argument("--http-timeout",   type=float, default=float(os.environ.get("HTTP_TIMEOUT",  "30.0")))
    p.add_argument("--max-retries",    type=int,   default=int(os.environ.get("MAX_RETRIES",   "3")))
    p.add_argument("--backoff-base",   type=float, default=float(os.environ.get("BACKOFF_BASE",  "1.0")))
    p.add_argument("--backoff-factor", type=float, default=float(os.environ.get("BACKOFF_FACTOR","2.0")))
    p.add_argument("--jitter-max",     type=float, default=float(os.environ.get("JITTER_MAX",   "0.25")))
    p.add_argument("--trace",          action="store_true",
                   default=os.environ.get("MCP_TRACE", "").lower() in ("1", "true", "yes"),
                   help="Include HTTP trace events in every tool response")
    return p.parse_args()


args = _parse_args()

HTTP_TIMEOUT   = args.http_timeout
MAX_RETRIES    = max(1, args.max_retries)
BACKOFF_BASE   = max(0.0, args.backoff_base)
BACKOFF_FACTOR = max(1.0, args.backoff_factor)
JITTER_MAX     = max(0.0, args.jitter_max)
TRACE_DEFAULT  = args.trace

SRU_BASE_URL = "https://www.sudoc.abes.fr/cbs/sru/"
SRU_NS       = {"srw": "http://www.loc.gov/zing/srw/"}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION : SRU query encoding
# ══════════════════════════════════════════════════════════════════════════════
#
# Règle absolue du protocole SRU (ABES) :
#   Le `=` dans une clause de recherche doit TOUJOURS être encodé %3D.
#   Sans cela, le serveur confond l'opérateur de recherche avec le séparateur
#   de paramètre URL et renvoie une erreur ou zéro résultat.
#
# Tableau complet des encodages :
#   =    → %3D   (OBLIGATOIRE après chaque clé d'index)
#   |    → %7C   (opérateur booléen OU)
#   "    → %22   (expression exacte)
#   ,    → %2C   (index PER : Nom,Prénom)
#   /    → %2F   (index COT : cotes)
#   >=   → %3E%3D (date supérieure ou égale)
#   <=   → %3C%3D (date inférieure ou égale)
#   >    → %3E   (date strictement supérieure)
#   <    → %3C   (date strictement inférieure)
#   *              (troncature — passé tel quel, accepté par le serveur)
#   -              (tirets dans identifiants — passé tel quel)
#   espace → +    (entre tokens, hors phrases quotées)

def _encode_query(raw: str) -> str:
    """
    Encode une chaîne SRU naturelle pour une inclusion sûre après `&query=`.

    Le appelant écrit la syntaxe naturelle, ex. : ``mti=jardins and japonais``
    ou ``aut=zola and mti=nana``. Cette fonction :
      1. Encode `=` → %3D (le changement le plus critique)
      2. Encode `"` → %22, `,` → %2C, `/` → %2F, `|` → %7C
      3. Remplace les espaces par `+`

    Idempotente : si la chaîne contient déjà `%3D`, elle est renvoyée telle
    quelle (le appelant a déjà encodé manuellement).
    """
    # Déjà encodé — passer en l'état
    if "%3D" in raw or "%3d" in raw:
        return raw

    encoded = raw.replace("=", "%3D")
    encoded = encoded.replace('"', "%22")
    encoded = encoded.replace(",", "%2C")
    encoded = encoded.replace("/", "%2F")
    encoded = encoded.replace("|", "%7C")
    encoded = re.sub(r" +", "+", encoded.strip())
    return encoded


def _build_url(
    query_encoded: str,
    *,
    start_record: int = 1,
    maximum_records: int = 10,
) -> str:
    """Assemble l'URL SRU searchRetrieve complète."""
    params = (
        f"operation=searchRetrieve"
        f"&version=1.1"
        f"&recordSchema=unimarc"
        f"&maximumRecords={maximum_records}"
        f"&startRecord={start_record}"
    )
    return f"{SRU_BASE_URL}?{params}&query={query_encoded}"


# ══════════════════════════════════════════════════════════════════════════════
# SECTION : HTTP layer — retry / backoff (synchrone, requests)
# ══════════════════════════════════════════════════════════════════════════════

def _backoff_sleep(attempt: int) -> float:
    """Délai exponentiel avec gigue aléatoire."""
    base = BACKOFF_BASE * (BACKOFF_FACTOR ** attempt)
    jitter = random.uniform(0.0, JITTER_MAX) if JITTER_MAX > 0 else 0.0
    return base + jitter


def _should_retry(status_code: int) -> bool:
    """Codes HTTP qui méritent un retry (erreurs transitoires)."""
    return status_code in (429, 500, 502, 503, 504)


def _get_xml(
    url: str,
    *,
    trace: bool = False,
) -> tuple[ET.Element, list[dict]]:
    """
    GET synchrone avec retry exponentiel. Renvoie (xml_root, trace_events).

    Codes retriés : 429, 500, 502, 503, 504. Les timeouts sont aussi retriés.
    Lève RuntimeError si toutes les tentatives échouent.
    """
    trace_events: list[dict] = []
    started = time.perf_counter()
    last_status: int | None = None
    last_error:  str | None = None

    for attempt in range(MAX_RETRIES):
        t0 = time.perf_counter()
        if trace:
            trace_events.append({
                "event": "http_request", "method": "GET", "url": url,
                "attempt": attempt + 1, "max_retries": MAX_RETRIES,
                "timeout_s": HTTP_TIMEOUT,
            })
        try:
            resp = requests.get(url, timeout=HTTP_TIMEOUT)
            last_status = resp.status_code

            if trace:
                trace_events.append({
                    "event": "http_response",
                    "status_code": resp.status_code,
                    "attempt": attempt + 1,
                    "elapsed_ms": int((time.perf_counter() - t0) * 1000),
                })

            if resp.status_code == 200:
                root = ET.fromstring(resp.content.decode("utf-8"))
                if trace:
                    trace_events.append({
                        "event": "http_success",
                        "total_elapsed_ms": int((time.perf_counter() - started) * 1000),
                    })
                return root, trace_events

            if _should_retry(resp.status_code) and attempt < MAX_RETRIES - 1:
                sleep_s = _backoff_sleep(attempt)
                if trace:
                    trace_events.append({
                        "event": "http_retry_sleep",
                        "status_code": resp.status_code,
                        "attempt": attempt + 1,
                        "sleep_s": round(sleep_s, 3),
                    })
                time.sleep(sleep_s)
                continue

            resp.raise_for_status()

        except requests.exceptions.Timeout as e:
            last_error = f"timeout: {e}"
            if trace:
                trace_events.append({
                    "event": "http_timeout", "attempt": attempt + 1,
                    "elapsed_ms": int((time.perf_counter() - t0) * 1000),
                })
            if attempt < MAX_RETRIES - 1:
                sleep_s = _backoff_sleep(attempt)
                if trace:
                    trace_events.append({
                        "event": "http_retry_sleep", "reason": "timeout",
                        "sleep_s": round(sleep_s, 3),
                    })
                time.sleep(sleep_s)
                continue
            raise

        except requests.exceptions.RequestException as e:
            last_error = str(e)
            if trace:
                trace_events.append({
                    "event": "http_error", "attempt": attempt + 1, "message": str(e),
                })
            raise

    raise RuntimeError(
        f"Sudoc SRU : échec après {MAX_RETRIES} tentatives sur {url} "
        f"(status={last_status}, error={last_error})"
    )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION : UNIMARC parsing
# ══════════════════════════════════════════════════════════════════════════════
#
# Le format renvoyé par le SRU Sudoc est l'UNIMARC encapsulé en XML.
# Structure d'une notice :
#
#   <srw:record>
#     <srw:recordData>
#       <record>
#         <controlfield tag="001">PPN</controlfield>
#         <datafield tag="200" ind1=" " ind2=" ">
#           <subfield code="a">Titre principal</subfield>
#           <subfield code="e">Sous-titre</subfield>
#         </datafield>
#         ...
#       </record>
#     </srw:recordData>
#   </srw:record>
#
# Correspondance des zones UNIMARC utilisées ici :
#   001        → PPN (identifiant Sudoc)
#   010 $a     → ISBN
#   011 $a     → ISSN
#   100 $a     → données codées (année extraite positions 9-12)
#   101 $a     → code langue (ISO 639-2)
#   200 $a $e  → titre principal + sous-titre
#   210 $a $c $d → lieu / éditeur / date de publication
#   215 $a     → description physique
#   300 $a     → notes générales
#   320 $a     → notes bibliographiques
#   328 $b $d $e $f → note de thèse (type, discipline, établissement, année)
#   410 $t     → titre de la collection / série
#   600–686    → points d'accès sujet (équivalents VMA/MSU)
#   700 $a $b  → auteur personne principal (Nom, Prénom)
#   701 $a $b  → auteurs personnes supplémentaires
#   710 $a     → collectivité auteur principale
#   711 $a     → collectivités auteurs supplémentaires
#   856 $u     → URL (ressources électroniques)

def _unimarc_root(record_data_el: ET.Element) -> ET.Element | None:
    """Extrait l'élément <record> UNIMARC depuis le wrapper <srw:recordData>."""
    for elem in record_data_el.iter():
        local = elem.tag.split("}", 1)[-1]
        if local == "record":
            has_marc = any(
                child.tag.split("}", 1)[-1] in {"datafield", "controlfield"}
                for child in elem.iter()
            )
            if has_marc:
                return elem
    return None


def _ctrl(record: ET.Element, tag: str) -> str | None:
    """Retourne le texte d'un champ de contrôle UNIMARC (ex. 001)."""
    for el in record.iter():
        if el.tag.split("}", 1)[-1] == "controlfield" and el.get("tag") == tag:
            return (el.text or "").strip() or None
    return None


def _subfields(record: ET.Element, tag: str, *codes: str) -> list[str]:
    """
    Collecte les valeurs de sous-champs pour un tag donné et des codes donnés.
    Retourne une liste plate de toutes les occurrences (répétitions incluses).
    """
    results = []
    for df in record.iter():
        if df.tag.split("}", 1)[-1] == "datafield" and df.get("tag") == tag:
            for sf in df:
                if sf.tag.split("}", 1)[-1] == "subfield":
                    code = sf.get("code", "")
                    if not codes or code in codes:
                        v = (sf.text or "").strip()
                        if v:
                            results.append(v)
    return results


def _first(record: ET.Element, tag: str, *codes: str) -> str | None:
    """Premier sous-champ correspondant, ou None."""
    vals = _subfields(record, tag, *codes)
    return vals[0] if vals else None


def _first_in_df(df: ET.Element, code: str) -> str | None:
    """Premier sous-champ de code donné dans un élément datafield déjà isolé."""
    for sf in df:
        if sf.tag.split("}", 1)[-1] == "subfield" and sf.get("code") == code:
            return (sf.text or "").strip() or None
    return None


def _format_record(record: ET.Element) -> dict:
    """
    Convertit une notice UNIMARC XML en dict Python normalisé.

    Champs extraits : PPN, titre, auteurs (personnes + collectivités), année,
    éditeur, lieu de publication, langue, ISBN, ISSN, note de thèse, sujets
    (RAMEAU), collection/série, description physique, notes, URLs.

    Le champ `sudoc_url` est construit à partir du PPN :
    https://www.sudoc.fr/<PPN>
    """
    ppn = _ctrl(record, "001")

    # ── Titre (200 $a + $e séparés par " : ") ────────────────────────────────
    title_parts = _subfields(record, "200", "a", "e")
    title = " : ".join(title_parts) if title_parts else None

    # ── Auteurs personnes (700 / 701 : $a Nom, $b Prénom) ────────────────────
    authors: list[str] = []
    for tag in ("700", "701"):
        for df in record.iter():
            if df.tag.split("}", 1)[-1] == "datafield" and df.get("tag") == tag:
                lastname  = _first_in_df(df, "a")
                firstname = _first_in_df(df, "b")
                if lastname:
                    name = f"{lastname}, {firstname}" if firstname else lastname
                    if name not in authors:
                        authors.append(name)

    # ── Auteurs collectivités (710 / 711 : $a) ────────────────────────────────
    corp_authors: list[str] = []
    for tag in ("710", "711"):
        for df in record.iter():
            if df.tag.split("}", 1)[-1] == "datafield" and df.get("tag") == tag:
                name = _first_in_df(df, "a")
                if name and name not in corp_authors:
                    corp_authors.append(name)

    # ── Année de publication ──────────────────────────────────────────────────
    # Source primaire : zone 100 $a, positions 9-12 (année de publication)
    year: int | None = None
    raw_100a = _first(record, "100", "a")
    if raw_100a and len(raw_100a) >= 13:
        try:
            year = int(raw_100a[9:13])
        except ValueError:
            pass
    # Fallback : zone 210 $d (date de publication textuelle)
    if year is None:
        raw_210d = _first(record, "210", "d")
        if raw_210d:
            m = re.search(r"\b(1[0-9]{3}|20[0-9]{2})\b", raw_210d)
            if m:
                year = int(m.group(1))

    # ── Note de thèse (328) ───────────────────────────────────────────────────
    # Zone UNIMARC 328 : $b type, $d discipline, $e établissement, $f année
    thesis: dict | None = None
    for df in record.iter():
        if df.tag.split("}", 1)[-1] == "datafield" and df.get("tag") == "328":
            thesis = {
                "type":        _first_in_df(df, "b"),
                "discipline":  _first_in_df(df, "d"),
                "institution": _first_in_df(df, "e"),
                "year":        _first_in_df(df, "f"),
            }
            break  # Une seule zone 328 attendue par notice

    # ── Sujets (600–686 : tous les sous-champs concaténés par " -- ") ─────────
    # Ces zones couvrent les vedettes RAMEAU et MeSH selon la zone utilisée.
    subjects: list[str] = []
    subject_tags = {str(t) for t in range(600, 687)}
    for df in record.iter():
        if df.tag.split("}", 1)[-1] == "datafield" and df.get("tag") in subject_tags:
            parts = []
            for sf in df:
                if sf.tag.split("}", 1)[-1] == "subfield":
                    v = (sf.text or "").strip()
                    if v:
                        parts.append(v)
            if parts:
                subjects.append(" -- ".join(parts))

    return {
        "source":           "sudoc",
        "ppn":              ppn,
        "title":            title,
        # `authors` expose en priorité les auteurs personnes physiques ;
        # si aucun, repli sur les collectivités auteurs.
        "authors":          authors if authors else corp_authors,
        "personal_authors": authors,
        "corporate_authors":corp_authors,
        "year":             year,
        "publisher":        _first(record, "210", "c"),
        "pub_place":        _first(record, "210", "a"),
        "language":         _first(record, "101", "a"),
        "isbn":             _first(record, "010", "a"),
        "issn":             _first(record, "011", "a"),
        "thesis":           thesis,
        "subjects":         subjects,
        "series":           _first(record, "410", "t"),
        "physical_desc":    _first(record, "215", "a"),
        "notes":            (_subfields(record, "300", "a") +
                             _subfields(record, "320", "a")) or None,
        "urls":             _subfields(record, "856", "u") or None,
        "sudoc_url":        f"https://www.sudoc.fr/{ppn}" if ppn else None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# SECTION : helpers SRU internes
# ══════════════════════════════════════════════════════════════════════════════

def _get_total(encoded_query: str, *, trace: bool) -> tuple[int, list[dict]]:
    """
    Exécute une requête SRU avec maximumRecords=1 pour obtenir le nombre total
    de notices correspondantes sans rapatrier les données.
    """
    url = _build_url(encoded_query, start_record=1, maximum_records=1)
    root, tevents = _get_xml(url, trace=trace)
    el = root.find(".//srw:numberOfRecords", namespaces=SRU_NS)
    total = int(el.text) if el is not None and el.text else 0
    return total, tevents


def _fetch_page(
    encoded_query: str,
    *,
    start: int,
    batch: int,
    trace: bool,
) -> tuple[list[dict], list[dict]]:
    """
    Rapatrie une page de résultats SRU et retourne les notices formatées.
    Chaque notice UNIMARC est extraite, parsée et convertie en dict normalisé.
    """
    url = _build_url(encoded_query, start_record=start, maximum_records=batch)
    root, tevents = _get_xml(url, trace=trace)
    records: list[dict] = []
    for srw_rec in root.findall(".//srw:record", namespaces=SRU_NS):
        rd = srw_rec.find("./srw:recordData", namespaces=SRU_NS)
        if rd is None:
            continue
        unimarc = _unimarc_root(rd)
        if unimarc is not None:
            records.append(_format_record(unimarc))
    return records, tevents


def _apply_limitations(query: str, limitations: list[str]) -> str:
    """
    Combine la requête principale avec les limitations Sudoc (TDO, LAN/LAI,
    PAY/PAI, APU) en les reliant par `and`.

    Les limitations ne peuvent pas exister seules dans une requête SRU Sudoc :
    elles doivent toujours être accompagnées d'au moins un index de recherche.
    """
    if not limitations:
        return query
    return query + " and " + " and ".join(limitations)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION : MCP server
# ══════════════════════════════════════════════════════════════════════════════

mcp = FastMCP(
    name="sudoc",
    instructions=(
        "Connecteur Sudoc SRU — interroge le catalogue collectif des bibliothèques "
        "de l'enseignement supérieur et de la recherche français (ABES). "
        "Permet de rechercher des notices bibliographiques (livres, thèses, "
        "périodiques, manuscrits, ressources électroniques…), de résoudre des "
        "PPN ou ISBN, de compter des corpus, et d'explorer les index du catalogue."
    ),
)


# ── Tool 1 : search ───────────────────────────────────────────────────────────

@mcp.tool()
def search_sudoc(
    query: str,
    max_results: int = 15,
    doc_type: str | None = None,
    language: str | None = None,
    lang_major: str | None = None,
    country: str | None = None,
    country_major: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    year_exact: int | None = None,
) -> dict:
    """
    Recherche dans le catalogue Sudoc via le service SRU de l'Abes.

    Retourne une liste de notices bibliographiques normalisées (titre, auteurs,
    année, éditeur, langue, ISBN/ISSN, sujets, note de thèse, URL Sudoc…).

    ─── Syntaxe de requête ────────────────────────────────────────────────────

    Utiliser la syntaxe naturelle `index=terme`. L'encodage SRU (%3D etc.)
    est appliqué automatiquement.

    Opérateurs booléens (priorité égale, s'exécutent gauche à droite) :
      AND  →  `and`, `+`, ou espace simple    (opérateur par défaut)
      OR   →  `or` ou `|`
      NOT  →  `not`
    Parenthèses pour modifier la priorité : `pcp=pcdroit not (fgr=actes congres)`
    Troncature : `*` en fin de terme  →  `mti=orthod*`, `nnt=2018perp*`
    Expression exacte : guillemets  →  `tou="ocre jaune"`, `res="vers blancs"`

    ─── Index disponibles ─────────────────────────────────────────────────────

    Numéros (correspondance exacte) :
      ppn   Numéro de notice Sudoc         ppn=070685045
      isb   ISBN (avec ou sans tirets)     isb=9782070360246
      isn   ISSN                           isn=2558-4278
      num   Tous identifiants              num=DLV-20160831-5586
      nnt   Numéro national de thèse       nnt=2018perp*
      ocn   Numéro WorldCat                ocn=690860108
      sou   Numéro source (corpus)         sou=star*
      bqt   Code bouquet électronique      bqt=2014-110

    Titre :
      mti   Mots du titre (index mot)      mti=jardins japonais
      tco   Titre complet (phrase)         tco=oui-oui*
      tab   Titre abrégé périodique (phrase) tab=nat*
      col   Collection (mot)               col=dunod

    Auteur :
      aut   Mots auteur (mot)              aut=lagerlof
      per   Nom de personne (phrase)       per=eco,umberto  ou  per=eco*
      org   Collectivité auteur (phrase)   org=insee  ou  org="insee rhone*"

    Sujet :
      msu   Mots sujets français (mot)     msu=hominides
      vma   Point d'accès sujet RAMEAU (phrase) vma=abricot*
      fgr   Forme / Genre (mot)            fgr=actes congres
      msa   Mots sujets anglais (mot)      msa=apricot*
      mee   Sujet MeSH anglais (mot)       mee=antivir*

    Notes :
      nth   Note de thèse (mot)            nth=biophysique and lyon
      res   Résumé / sommaire (mot)        res="vers blancs"
      lva   Note livre ancien (mot)        lva=memoires
      fir   Source de financement (mot)    fir=labx
      rec   Note de récompense (mot)       rec=award*

    Exemplaires / holdings :
      rbc   Numéro RCR de bibliothèque     rbc=840079901
      pcp   Plan de Conservation Partagée  pcp=pcdroit
      rpc   Reliure / Provenance           rpc="armes de Dominique*"
      cot   Cote d'exemplaire (phrase)     cot="839.73 EKM"  ou  cot=839.7*

    Général :
      tou   Tous les mots                  tou="ocre jaune"
      edi   Éditeur (mot)                  edi=gallimard

    ─── Index de type phrase ──────────────────────────────────────────────────

    Les index de type phrase (tco, tab, per, org, vma, cot) exigent la forme
    complète et normalisée du terme. En cas de doute, utiliser la troncature :
      per=lagerlof*     au lieu de  per=lagerlof,Selma
      org="insee rhone*"  au lieu de  org="insee rhone-alpes"

    Pour l'index `per`, la virgule entre nom et prénom est encodée
    automatiquement : passer `per=eco,umberto` suffit.

    ─── Remarque sur les accents ──────────────────────────────────────────────

    Rechercher sans accents donne plus de résultats : le Sudoc cherche alors
    les formes accentuées ET non accentuées. Exemple : `mti=memoires` >
    `mti=mémoires`.

    Args:
        query: Requête SRU en syntaxe naturelle. Exemples :
               "mti=jardins and japonais"
               "aut=lagerlof and mti=troll"
               "nth=biophysique and lyon"
               "vma=abricot* or msa=apricot*"
               "pcp=pcdroit not (fgr=actes congres)"
               "rbc=840079901 and sou=star*"
               "per=eco,umberto"  (index phrase, virgule encodée auto)
               "tou=\\"ocre jaune\\""  (expression exacte)

        max_results: Nombre maximum de notices à retourner (défaut 15, max 1000).
                     La pagination interne est gérée automatiquement par paliers
                     de 100 avec un délai de courtoisie de 200 ms entre pages.

        doc_type: Code TDO (type de document) :
                  a=articles  b=monographies imprimées  f=manuscrits
                  g=enreg. sonores musicaux  i=images fixes  k=cartes
                  m=partitions  n=enreg. sonores non musicaux
                  o=monographies électroniques  t=périodiques et collections
                  v=documents audiovisuels  x=objets/multimédia
                  y=thèses (imprimées et électroniques)

        language: Code langue ISO 639-2/3 pour l'index LAI (toutes langues
                  sauf les 10 majeures).
                  Exemples : "dan" (danois), "ara" (arabe), "jpn" (japonais),
                  "swe" (suédois), "por" (portugais — utiliser lang_major).

        lang_major: Code LAN pour les 10 langues majeures uniquement :
                    ger eng spa fre ita lat dut pol por rus
                    NE PAS combiner avec `language` pour la même langue.

        country: Code pays ISO 3166 pour l'index PAI (tous pays sauf les 11
                 majeurs).
                 Exemples : "se" (Suède), "jp" (Japon), "br" (Brésil).

        country_major: Code PAY pour les 11 pays majeurs uniquement :
                       de be ca es us fr it nl gb ru ch
                       NE PAS combiner avec `country` pour le même pays.

        year_from: Borne inférieure inclusive sur l'année de publication (APU>=).

        year_to: Borne supérieure inclusive sur l'année de publication (APU<=).

        year_exact: Année de publication exacte (APU=). Écrase year_from/year_to.

    Returns:
        {
          "total_found": int,       # total dans le Sudoc (peut dépasser returned)
          "returned": int,          # notices dans cette réponse
          "query_used": str,        # requête complète avec limitations
          "results": [
            {
              "source": "sudoc",
              "ppn": str,           # identifiant Sudoc (lien : sudoc.fr/<ppn>)
              "title": str | null,
              "authors": list[str], # "Nom, Prénom" — personnes en priorité,
                                    # collectivités en repli
              "personal_authors": list[str],
              "corporate_authors": list[str],
              "year": int | null,
              "publisher": str | null,
              "pub_place": str | null,
              "language": str | null,   # code ISO 639-2
              "isbn": str | null,
              "issn": str | null,
              "thesis": {           # null si non applicable
                "type": str | null,
                "discipline": str | null,
                "institution": str | null,
                "year": str | null
              },
              "subjects": list[str],    # vedettes RAMEAU / MeSH
              "series": str | null,
              "physical_desc": str | null,
              "notes": list[str] | null,
              "urls": list[str] | null,
              "sudoc_url": str          # https://www.sudoc.fr/<ppn>
            }
          ]
        }
    """
    trace = TRACE_DEFAULT
    trace_events: list[dict] = []

    # ── Construction des limitations ─────────────────────────────────────────
    # Chaque limitation est exprimée comme une clause SRU naturelle (non encore
    # encodée). L'encodage global est appliqué une seule fois par _encode_query.
    limitations: list[str] = []

    if doc_type:
        limitations.append(f"tdo={doc_type}")

    # LAN (10 langues majeures) a priorité sur LAI (toutes autres langues).
    if lang_major:
        limitations.append(f"lan={lang_major}")
    elif language:
        limitations.append(f"lai={language}")

    # PAY (11 pays majeurs) a priorité sur PAI (tous autres pays).
    if country_major:
        limitations.append(f"pay={country_major}")
    elif country:
        limitations.append(f"pai={country}")

    # Dates : year_exact écrase la plage, la plage utilise le raccourci SRU
    # (apu=1995-2000) quand les deux bornes sont présentes.
    if year_exact is not None:
        limitations.append(f"apu={year_exact}")
    else:
        if year_from is not None and year_to is not None:
            limitations.append(f"apu={year_from}-{year_to}")
        elif year_from is not None:
            limitations.append(f"apu=>={year_from}")
        elif year_to is not None:
            limitations.append(f"apu=<={year_to}")

    full_query = _apply_limitations(query, limitations)
    encoded    = _encode_query(full_query)

    # ── Compte total ──────────────────────────────────────────────────────────
    total, t = _get_total(encoded, trace=trace)
    trace_events.extend(t)

    if total == 0:
        out: dict = {
            "total_found": 0, "returned": 0,
            "query_used": full_query, "results": [],
        }
        if trace:
            out["trace"] = trace_events
        return out

    # ── Pagination ────────────────────────────────────────────────────────────
    to_fetch   = min(max_results, total, 1000)
    batch_size = min(100, to_fetch)
    records: list[dict] = []

    for start in range(1, to_fetch + 1, batch_size):
        this_batch = min(batch_size, to_fetch - len(records))
        page, t = _fetch_page(encoded, start=start, batch=this_batch, trace=trace)
        trace_events.extend(t)
        records.extend(page)
        if len(records) >= to_fetch:
            break
        time.sleep(0.2)  # délai de courtoisie entre pages

    out = {
        "total_found": total,
        "returned":    len(records),
        "query_used":  full_query,
        "results":     records,
    }
    if trace:
        out["trace"] = trace_events
    return out


# ── Tool 2 : lookup_by_ppn ────────────────────────────────────────────────────

@mcp.tool()
def lookup_by_ppn(ppn: str) -> dict:
    """
    Récupère une notice Sudoc par son PPN (Pica Production Number).

    Le PPN est l'identifiant unique d'une notice dans le catalogue Sudoc.
    Il figure dans l'URL de la notice : https://www.sudoc.fr/<PPN>
    Il est également retourné dans le champ `ppn` des résultats de search_sudoc.

    Utiliser cet outil quand on dispose déjà de l'identifiant exact (par exemple
    après un search_sudoc ou une recherche manuelle sur sudoc.fr).

    Args:
        ppn: PPN Sudoc, ex. "070685045". Chiffres uniquement, sans espaces.

    Returns:
        {
          "total_found": 1,
          "returned": 1,
          "results": [ <notice normalisée — même schéma que search_sudoc> ]
        }
        Ou si le PPN n'existe pas :
        {
          "total_found": 0, "returned": 0, "results": [],
          "error": "PPN not found in Sudoc: '...'"
        }
    """
    trace = TRACE_DEFAULT
    encoded = _encode_query(f"ppn={ppn}")
    url = _build_url(encoded, start_record=1, maximum_records=1)
    root, tevents = _get_xml(url, trace=trace)

    result: dict | None = None
    for srw_rec in root.findall(".//srw:record", namespaces=SRU_NS):
        rd = srw_rec.find("./srw:recordData", namespaces=SRU_NS)
        if rd is not None:
            unimarc = _unimarc_root(rd)
            if unimarc is not None:
                result = _format_record(unimarc)
                break

    out: dict
    if result:
        out = {"total_found": 1, "returned": 1, "results": [result]}
    else:
        out = {
            "total_found": 0, "returned": 0, "results": [],
            "error": f"PPN not found in Sudoc: '{ppn}'",
        }
    if trace:
        out["trace"] = tevents
    return out


# ── Tool 3 : lookup_by_isbn ───────────────────────────────────────────────────

@mcp.tool()
def lookup_by_isbn(isbn: str) -> dict:
    """
    Récupère les notices Sudoc correspondant à un ISBN (10 ou 13 chiffres).

    Les tirets sont optionnels : "978-2-07-036024-5" et "9782070360245" donnent
    le même résultat. Un ISBN peut correspondre à plusieurs notices dans le
    Sudoc (éditions différentes, support imprimé et électronique, etc.).

    Note : l'index ISB du Sudoc ne couvre que les monographies (livres).
    Pour les ressources sérielles, utiliser l'index `isn` via search_sudoc.

    Args:
        isbn: ISBN-10 ou ISBN-13, avec ou sans tirets.
              Exemples : "978-2-07-036024-5", "2070360245", "9782070360245"

    Returns:
        {
          "total_found": int,
          "returned": int,
          "isbn_queried": str,      # ISBN tel que passé en paramètre
          "results": [ <notices normalisées — même schéma que search_sudoc> ]
        }
    """
    trace = TRACE_DEFAULT
    clean = isbn.replace("-", "")
    encoded = _encode_query(f"isb={clean}")
    url = _build_url(encoded, start_record=1, maximum_records=10)
    root, tevents = _get_xml(url, trace=trace)

    count_el = root.find(".//srw:numberOfRecords", namespaces=SRU_NS)
    total    = int(count_el.text) if count_el is not None and count_el.text else 0

    records: list[dict] = []
    for srw_rec in root.findall(".//srw:record", namespaces=SRU_NS):
        rd = srw_rec.find("./srw:recordData", namespaces=SRU_NS)
        if rd is not None:
            unimarc = _unimarc_root(rd)
            if unimarc is not None:
                records.append(_format_record(unimarc))

    out: dict = {
        "total_found":  total,
        "returned":     len(records),
        "isbn_queried": isbn,
        "results":      records,
    }
    if trace:
        out["trace"] = tevents
    return out


# ── Tool 4 : count_records ────────────────────────────────────────────────────

@mcp.tool()
def count_records(query: str) -> dict:
    """
    Retourne le nombre total de notices correspondant à une requête SRU,
    sans rapatrier les données (une seule requête HTTP, maximumRecords=1).

    Utiliser cet outil pour :
    - Estimer la taille d'un corpus avant un search_sudoc avec max_results élevé.
    - Valider qu'une requête donne des résultats avant de la construire
      davantage.
    - Comparer la couverture de différentes stratégies de recherche.

    Accepte la même syntaxe de requête que search_sudoc (même index,
    mêmes opérateurs, même troncature). Les limitations (TDO, LAN, APU…)
    doivent être incluses manuellement dans `query` si nécessaire :
    ex. "edi=gallimard and tdo=b and lan=fre"

    Args:
        query: Requête SRU en syntaxe naturelle.
               Exemples :
               "aut=zola"
               "pcp=pcmed and tdo=t"
               "edi=gallimard and lan=fre and apu=2000-2023"
               "nth=toulouse and mti=intelligence artificielle and tdo=y"

    Returns:
        {
          "query":       str,   # requête passée en entrée
          "total_found": int,   # nombre total de notices correspondantes
          "url_used":    str    # URL SRU effectivement exécutée (debug)
        }
    """
    trace = TRACE_DEFAULT
    encoded  = _encode_query(query)
    url      = _build_url(encoded, start_record=1, maximum_records=1)
    root, tevents = _get_xml(url, trace=trace)

    el    = root.find(".//srw:numberOfRecords", namespaces=SRU_NS)
    total = int(el.text) if el is not None and el.text else 0

    out: dict = {"query": query, "total_found": total, "url_used": url}
    if trace:
        out["trace"] = tevents
    return out


# ── Tool 5 : scan_index ───────────────────────────────────────────────────────

@mcp.tool()
def scan_index(
    index_key: str,
    term: str,
    maximum_terms: int = 25,
    response_position: int = 1,
) -> dict:
    """
    Explore un index Sudoc par ordre alphabétique à partir d'un terme donné
    (opération SRU `scan`).

    Utilisations typiques :
    - Découvrir les formes normalisées d'un terme dans un index phrase
      (per, org, vma, tco) avant d'écrire une requête exacte.
    - Vérifier qu'un terme existe dans un index et voir ses variantes.
    - Comprendre pourquoi une requête renvoie zéro résultat (le terme
      est peut-être orthographié différemment dans le catalogue).
    - Obtenir les effectifs (nombre de notices) pour chaque terme.

    Exemples d'utilisation :
      index_key="mti", term="paralogue"    → termes titre autour de "paralogue"
      index_key="aut", term="lagerlof"     → variantes du nom "lagerlof"
      index_key="vma", term="abricot"      → vedettes RAMEAU débutant par "abricot"
      index_key="per", term="eco,u"        → noms de personne "Eco, U..."
      index_key="org", term="insee"        → formes normalisées des collectivités "INSEE"
      index_key="edi", term="gallimard"    → éditeurs "gallimard..."

    Index disponibles (voir search_sudoc pour la liste complète) :
      mti aut per org msu vma fgr msa mee nth res lva fir rec
      rbc pcp rpc cot tou edi col tab tco sou

    Args:
        index_key: Clé d'index Sudoc (ex. "mti", "aut", "vma", "per").

        term: Terme de départ pour le balayage alphabétique.
              Pour les index phrase (per, org, vma), passer la forme partielle :
              ex. "eco,u" pour explorer les auteurs "Eco, U...".

        maximum_terms: Nombre de termes à retourner (défaut 25, minimum 1).
                       Le serveur utilise 10 par défaut si ce paramètre est omis.

        response_position: Position du terme `term` dans la liste retournée
                           (défaut 1 = premier élément). Utiliser 5 pour avoir
                           deux termes avant et plusieurs après.

    Returns:
        {
          "index":      str,          # clé d'index interrogée
          "start_term": str,          # terme de départ
          "terms": [
            {
              "term":  str | null,    # forme normalisée dans le catalogue
              "count": int | null     # nombre de notices pour ce terme
            },
            ...
          ]
        }
    """
    trace = TRACE_DEFAULT
    scan_clause = f"{index_key}%3D{term}"
    url = (
        f"{SRU_BASE_URL}?operation=scan&version=1.1"
        f"&scanClause={scan_clause}"
        f"&responsePosition={response_position}"
        f"&maximumTerms={maximum_terms}"
    )
    root, tevents = _get_xml(url, trace=trace)

    terms: list[dict] = []
    for term_el in root.findall(".//{http://www.loc.gov/zing/srw/}term"):
        value_el = term_el.find("{http://www.loc.gov/zing/srw/}value")
        count_el = term_el.find("{http://www.loc.gov/zing/srw/}numberOfRecords")
        terms.append({
            "term":  (value_el.text or "").strip() if value_el is not None else None,
            "count": int(count_el.text) if count_el is not None and count_el.text else None,
        })

    out: dict = {"index": index_key, "start_term": term, "terms": terms}
    if trace:
        out["trace"] = tevents
    return out


# ══════════════════════════════════════════════════════════════════════════════
# SECTION : entrypoint
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if args.transport == "stdio":
        # Lancement par un client desktop/IDE via stdin/stdout.
        # host/port sans effet dans ce mode.
        mcp.run(transport="stdio")
    else:
        mcp.run(
            transport=args.transport,
            host=args.host,
            port=args.port,
        )