#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "requests",
# ]
# ///

# ──────────────────────────────────────────────────────────────────────────────
# Sudoc SRU skill CLI
# Catalogue du Système Universitaire de Documentation (France) via protocole SRU
# Documentation : https://www.sudoc.abes.fr / https://abes.fr
# ──────────────────────────────────────────────────────────────────────────────

"""
Connector Sudoc SRU — CLI autonome (runs with `uv run`)
Interroge le catalogue Sudoc via le protocole SRU 1.1.
Données encodées UTF-8, format UNIMARC encapsulé en XML.

Variables d'environnement :
  SUDOC_HTTP_TIMEOUT     (float, défaut 30.0)
  SUDOC_MAX_RETRIES      (int,   défaut 3)
  SUDOC_BACKOFF_BASE     (float, défaut 1.0)
  SUDOC_BACKOFF_FACTOR   (float, défaut 2.0)
  SUDOC_JITTER_MAX       (float, défaut 0.25)
  SUDOC_TRACE            ("0"|"1", défaut "0")
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import time
import xml.etree.ElementTree as ET
from typing import Any

import requests

# ══════════════════════════════════════════════════════════════════════════════
# SECTION : config
# ══════════════════════════════════════════════════════════════════════════════

SRU_BASE_URL = "https://www.sudoc.abes.fr/cbs/sru/"
SRU_NS = {"srw": "http://www.loc.gov/zing/srw/"}

def _env_float(name: str, default: float) -> float:
    v = os.getenv(name, "").strip()
    try:
        return float(v) if v else default
    except ValueError:
        return default

def _env_int(name: str, default: int) -> int:
    v = os.getenv(name, "").strip()
    try:
        return int(v) if v else default
    except ValueError:
        return default

HTTP_TIMEOUT   = _env_float("SUDOC_HTTP_TIMEOUT",   30.0)
MAX_RETRIES    = max(1, _env_int("SUDOC_MAX_RETRIES", 3))
BACKOFF_BASE   = max(0.0, _env_float("SUDOC_BACKOFF_BASE",   1.0))
BACKOFF_FACTOR = max(1.0, _env_float("SUDOC_BACKOFF_FACTOR", 2.0))
JITTER_MAX     = max(0.0, _env_float("SUDOC_JITTER_MAX",     0.25))
TRACE_DEFAULT  = os.getenv("SUDOC_TRACE", "0").strip() in ("1", "true", "True", "yes")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION : SRU query encoding
# ══════════════════════════════════════════════════════════════════════════════

# ── Critical: the `=` sign must ALWAYS be encoded %3D in SRU query clauses. ──
# The SRU base URL already uses plain `=` for parameter assignment (key=value).
# Everything inside the `query=` value uses %3D for index–term relations.
#
# Encoding map (from the ABES guide):
#   =   → %3D  (mandatory, index-term separator)
#   >   → %3E  (date: strictly greater than)
#   >=  → %3E%3D  (date: greater than or equal)
#   <   → %3C  (date: strictly less than)
#   <=  → %3C%3D  (date: less than or equal)
#   |   → %7C  (boolean OR)
#   "   → %22  (exact phrase)
#   ,   → %2C  (PER index: lastname,firstname)
#   -   → %2D  (hyphens in identifiers – optional but safe)
#   *   → %2A  (truncation – optional, * is usually safe in URLs)
#   /   → %2F  (shelf marks in COT index)
#
# The `and` operator can be written as `+` (URL-safe), `and`, or a plain space.
# The `or`  operator can be written as `|` or `%7C`.
# The `not` operator is written literally as `not`.

def encode_query(raw: str) -> str:
    """
    Encode a raw SRU query string for safe inclusion after `&query=` in the URL.

    Rules applied:
    - The caller writes natural SRU syntax, e.g.:  mti=jardins and japonais
    - We encode `=` → %3D ONLY inside index=term positions (not in operators).
    - Spaces between tokens become `+` (except inside quoted phrases).
    - `|` → %7C, `"` → %22, `,` → %2C, `/` → %2F.
    - `>`, `<`, `>=`, `<=` (date comparisons) get encoded only when following
      a %3D (i.e., they are part of a value like apu%3D>2010).

    For maximum safety and predictability, callers may also pass
    pre-encoded strings (e.g., `mti%3Djardins+japonais`) — this function is
    idempotent for already-encoded `%3D`.
    """
    # Already encoded by caller — pass through as-is.
    if "%3D" in raw or "%3d" in raw:
        return raw

    # Replace = with %3D (all occurrences inside the query value)
    encoded = raw.replace("=", "%3D")

    # Encode remaining special chars that are not safe in query strings
    encoded = encoded.replace('"', "%22")
    encoded = encoded.replace(",", "%2C")
    encoded = encoded.replace("/", "%2F")
    encoded = encoded.replace("|", "%7C")

    # Compress multiple spaces to single, then replace with +
    encoded = re.sub(r" +", "+", encoded.strip())

    # Keep * and - as-is (widely accepted in SRU; guide shows them unencoded)
    # Keep > and < as-is (httpx/requests does NOT percent-encode these in params)
    return encoded


def build_sru_url(
    query_encoded: str,
    *,
    start_record: int = 1,
    maximum_records: int = 10,
) -> str:
    """Assemble a full SRU searchRetrieve URL."""
    params = (
        f"operation=searchRetrieve"
        f"&version=1.1"
        f"&recordSchema=unimarc"
        f"&maximumRecords={maximum_records}"
        f"&startRecord={start_record}"
    )
    return f"{SRU_BASE_URL}?{params}&query={query_encoded}"


# ══════════════════════════════════════════════════════════════════════════════
# SECTION : HTTP layer with retry / backoff
# ══════════════════════════════════════════════════════════════════════════════

def _backoff_sleep(attempt: int) -> float:
    base = BACKOFF_BASE * (BACKOFF_FACTOR ** attempt)
    jitter = random.uniform(0.0, JITTER_MAX) if JITTER_MAX > 0 else 0.0
    return base + jitter

def _should_retry(status_code: int) -> bool:
    return status_code in (429, 500, 502, 503, 504)

def _get_xml(
    url: str,
    *,
    max_retries: int | None = None,
    timeout: float | None = None,
    trace: bool = False,
) -> tuple[ET.Element, list[dict]]:
    """
    GET a URL and return parsed XML root + optional trace events.
    Retries on transient errors with exponential backoff.
    """
    _max = MAX_RETRIES if max_retries is None else max(1, int(max_retries))
    _timeout = HTTP_TIMEOUT if timeout is None else float(timeout)
    trace_events: list[dict] = []
    started = time.perf_counter()

    last_status: int | None = None
    last_error: str | None = None

    for attempt in range(_max):
        t0 = time.perf_counter()
        if trace:
            trace_events.append({
                "event": "http_request",
                "method": "GET",
                "url": url,
                "attempt": attempt + 1,
                "max_retries": _max,
                "timeout_s": _timeout,
            })
        try:
            resp = requests.get(url, timeout=_timeout)
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

            if _should_retry(resp.status_code) and attempt < _max - 1:
                sleep_s = _backoff_sleep(attempt)
                if trace:
                    trace_events.append({
                        "event": "http_retry_sleep",
                        "status_code": resp.status_code,
                        "sleep_s": round(sleep_s, 3),
                    })
                time.sleep(sleep_s)
                continue

            resp.raise_for_status()

        except requests.exceptions.Timeout as e:
            last_error = f"timeout: {e}"
            if trace:
                trace_events.append({
                    "event": "http_timeout",
                    "attempt": attempt + 1,
                    "elapsed_ms": int((time.perf_counter() - t0) * 1000),
                })
            if attempt < _max - 1:
                sleep_s = _backoff_sleep(attempt)
                if trace:
                    trace_events.append({"event": "http_retry_sleep", "reason": "timeout", "sleep_s": round(sleep_s, 3)})
                time.sleep(sleep_s)
                continue
            raise

        except requests.exceptions.RequestException as e:
            last_error = str(e)
            if trace:
                trace_events.append({"event": "http_error", "attempt": attempt + 1, "message": str(e)})
            raise

    raise RuntimeError(
        f"Sudoc SRU: failed after {_max} attempts on {url} "
        f"(status={last_status}, error={last_error})"
    )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION : UNIMARC parsing helpers
# ══════════════════════════════════════════════════════════════════════════════

def _unimarc_root(record_data_el: ET.Element) -> ET.Element | None:
    """Extract the UNIMARC <record> element from a <srw:recordData> wrapper."""
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
    """Return text of a UNIMARC control field by tag."""
    for el in record.iter():
        if el.tag.split("}", 1)[-1] == "controlfield" and el.get("tag") == tag:
            return (el.text or "").strip() or None
    return None


def _subfields(record: ET.Element, tag: str, *codes: str) -> list[str]:
    """
    Collect subfield values for a given datafield tag and subfield code(s).
    Returns a flat list of all matching values across all repetitions of the field.
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


def _first_subfield(record: ET.Element, tag: str, *codes: str) -> str | None:
    """Return the first matching subfield value, or None."""
    vals = _subfields(record, tag, *codes)
    return vals[0] if vals else None


def _first_subfield_from_tags(record: ET.Element, tags: tuple[str, ...], *codes: str) -> str | None:
    """Return the first matching subfield value from the first available tag."""
    for tag in tags:
        value = _first_subfield(record, tag, *codes)
        if value:
            return value
    return None


def _join_subfields(record: ET.Element, tag: str, *codes: str, sep: str = " ") -> str | None:
    """Join all subfield values for a given tag into a single string."""
    vals = _subfields(record, tag, *codes)
    return sep.join(vals) if vals else None


def _format_record(record: ET.Element) -> dict:
    """
    Convert a UNIMARC <record> element to a normalised Python dict.

    UNIMARC field mapping used:
      001        → PPN (Sudoc record number)
      010 $a     → ISBN
      011 $a     → ISSN
      100 $a     → date coded (publication year extracted from positions 9-12)
      101 $a     → language code
      200 $a $e  → title (main title + subtitle)
      214 $a $c $d → place / publisher / publication year
      210 $a $c $d → legacy place / publisher / publication year fallback
      215 $a     → physical description
      300 $a     → general notes
      320 $a     → bibliographic notes
      328 $b $d $e $f → thesis note (type, discipline, institution, year)
      410 $t     → series title
      500 $a $m  → uniform title (for translations etc.)
      600–686    → subject headings (VMA/MSU equivalent)
      700 $a $b  → primary personal author (lastname, firstname)
      701 $a $b  → additional personal authors
      710 $a     → primary corporate author
      711 $a     → additional corporate authors
      856 $u     → URL (electronic resources)
    """
    ppn = _ctrl(record, "001")

    # ── Title ────────────────────────────────────────────────────────────────
    title_parts = _subfields(record, "200", "a", "e")
    title = " : ".join(title_parts) if title_parts else None

    # ── Authors ──────────────────────────────────────────────────────────────
    authors: list[str] = []
    for tag in ("700", "701"):
        for df in record.iter():
            if df.tag.split("}", 1)[-1] == "datafield" and df.get("tag") == tag:
                lastname = _first_subfield_in_df(df, "a")
                firstname = _first_subfield_in_df(df, "b")
                if lastname:
                    name = f"{lastname}, {firstname}" if firstname else lastname
                    if name not in authors:
                        authors.append(name)

    # Corporate / collective authors
    corp_authors: list[str] = []
    for tag in ("710", "711"):
        for df in record.iter():
            if df.tag.split("}", 1)[-1] == "datafield" and df.get("tag") == tag:
                name = _first_subfield_in_df(df, "a")
                if name and name not in corp_authors:
                    corp_authors.append(name)

    # ── Publication year (from coded field 100 $a, positions 9-12) ───────────
    year: int | None = None
    raw_100a = _first_subfield(record, "100", "a")
    if raw_100a and len(raw_100a) >= 13:
        try:
            year = int(raw_100a[9:13])
        except ValueError:
            pass

    publication_tags = ("214", "210")

    # Fallback: try publication statement $d. Sudoc records can carry either
    # current UNIMARC 214 or legacy 210 depending on their cataloging date.
    if year is None:
        raw_publication_date = _first_subfield_from_tags(record, publication_tags, "d")
        if raw_publication_date:
            m = re.search(r"\b(1[0-9]{3}|20[0-9]{2})\b", raw_publication_date)
            if m:
                year = int(m.group(1))

    # ── Publisher / place ────────────────────────────────────────────────────
    publisher = _first_subfield_from_tags(record, publication_tags, "c")
    pub_place = _first_subfield_from_tags(record, publication_tags, "a")

    # ── Language ─────────────────────────────────────────────────────────────
    language = _first_subfield(record, "101", "a")

    # ── ISBN / ISSN ──────────────────────────────────────────────────────────
    isbn = _first_subfield(record, "010", "a")
    issn = _first_subfield(record, "011", "a")

    # ── Thesis note (tag 328) ────────────────────────────────────────────────
    thesis: dict | None = None
    for df in record.iter():
        if df.tag.split("}", 1)[-1] == "datafield" and df.get("tag") == "328":
            t_type  = _first_subfield_in_df(df, "b")
            t_disc  = _first_subfield_in_df(df, "d")
            t_inst  = _first_subfield_in_df(df, "e")
            t_year  = _first_subfield_in_df(df, "f")
            thesis = {
                "type":        t_type,
                "discipline":  t_disc,
                "institution": t_inst,
                "year":        t_year,
            }
            break  # take only the first 328

    # ── Subject headings (600-686) ────────────────────────────────────────────
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

    # ── URLs (856 $u) ─────────────────────────────────────────────────────────
    urls = _subfields(record, "856", "u")

    # ── Notes ────────────────────────────────────────────────────────────────
    notes = _subfields(record, "300", "a") + _subfields(record, "320", "a")

    # ── Series ───────────────────────────────────────────────────────────────
    series = _first_subfield(record, "410", "t")

    # ── Physical description ─────────────────────────────────────────────────
    physical_desc = _first_subfield(record, "215", "a")

    return {
        "source": "sudoc",
        "ppn": ppn,
        "title": title,
        "authors": authors if authors else corp_authors,
        "personal_authors": authors,
        "corporate_authors": corp_authors,
        "year": year,
        "publisher": publisher,
        "pub_place": pub_place,
        "language": language,
        "isbn": isbn,
        "issn": issn,
        "thesis": thesis,
        "subjects": subjects,
        "series": series,
        "physical_desc": physical_desc,
        "notes": notes if notes else None,
        "urls": urls if urls else None,
        "sudoc_url": f"https://www.sudoc.fr/{ppn}" if ppn else None,
    }


def _first_subfield_in_df(df: ET.Element, code: str) -> str | None:
    """Return the first subfield text with the given code inside a datafield element."""
    for sf in df:
        if sf.tag.split("}", 1)[-1] == "subfield" and sf.get("code") == code:
            return (sf.text or "").strip() or None
    return None


# ══════════════════════════════════════════════════════════════════════════════
# SECTION : SRU operations
# ══════════════════════════════════════════════════════════════════════════════

def count_records(
    query: str,
    *,
    trace: bool | None = None,
    http_timeout: float | None = None,
    max_retries: int | None = None,
) -> dict:
    """
    Return the total number of records matching a SRU query without fetching them.
    Useful for estimating corpus size before a full fetch.
    """
    trace_eff = TRACE_DEFAULT if trace is None else bool(trace)
    encoded = encode_query(query)
    url = build_sru_url(encoded, start_record=1, maximum_records=1)

    root, tevents = _get_xml(url, max_retries=max_retries, timeout=http_timeout, trace=trace_eff)
    el = root.find(".//srw:numberOfRecords", namespaces=SRU_NS)
    n = int(el.text) if el is not None and el.text else 0

    out: dict = {"query": query, "total_found": n, "url_used": url}
    if trace_eff:
        out["trace"] = tevents
    return out


def search(
    query: str,
    max_results: int = 15,
    *,
    doc_type: str | None = None,
    language: str | None = None,
    lang_major: str | None = None,
    country: str | None = None,
    country_major: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    year_exact: int | None = None,
    trace: bool | None = None,
    http_timeout: float | None = None,
    max_retries: int | None = None,
) -> dict:
    """
    Search the Sudoc catalogue and return normalised records.

    Parameters
    ----------
    query : str
        SRU query using Sudoc index keys. Natural syntax accepted:
        e.g. ``"mti=jardins and japonais"`` or ``"aut=lagerlof and mti=troll"``.
        The `=` signs will be encoded to %3D automatically.
        Supports boolean operators: and (+), or (|), not.
        Supports truncation: * (e.g. ``"mti=orthod*"``).
        Phrase indexes require the full form or truncation.

    max_results : int
        Maximum number of records to return (hard-capped at 1000 by the server).
        Internally paginates in batches of 100.

    doc_type : str | None
        Sudoc TDO code appended to the query.
        Values: a(articles) b(monographs) f(manuscripts) g(musical recordings)
                i(still images) k(maps) m(scores) n(non-musical recordings)
                o(e-monographs) t(serials) v(audiovisual) x(multimedia) y(theses)

    language : str | None
        ISO 639-2/3 language code for LAI index (most languages).
        e.g. ``"dan"`` for Danish, ``"ara"`` for Arabic, ``"jpn"`` for Japanese.

    lang_major : str | None
        Language code for LAN limitation (10 major languages only).
        Values: ger eng spa fre ita lat dut pol por rus

    country : str | None
        ISO 3166 country code for PAI index (most countries).
        e.g. ``"se"`` for Sweden, ``"jp"`` for Japan.

    country_major : str | None
        Country code for PAY limitation (11 major countries).
        Values: de be ca es us fr it nl gb ru ch

    year_from : int | None
        Inclusive lower bound for publication year (APU >= year_from).

    year_to : int | None
        Inclusive upper bound for publication year (APU <= year_to).

    year_exact : int | None
        Exact publication year (APU = year_exact). Overrides year_from/year_to.
    """
    trace_eff = TRACE_DEFAULT if trace is None else bool(trace)
    trace_events: list[dict] = []

    # ── Build the full query by appending limitations ─────────────────────────
    # Limitations (TDO, LAN, LAI, PAY, PAI, APU) MUST always be combined with
    # at least one regular index. We combine them with `and`.
    limitations: list[str] = []

    if doc_type:
        limitations.append(f"tdo={doc_type}")
    if lang_major:
        limitations.append(f"lan={lang_major}")
    elif language:
        limitations.append(f"lai={language}")
    if country_major:
        limitations.append(f"pay={country_major}")
    elif country:
        limitations.append(f"pai={country}")

    if year_exact is not None:
        limitations.append(f"apu={year_exact}")
    else:
        if year_from is not None and year_to is not None:
            # Range shorthand: apu=1995-2000
            limitations.append(f"apu={year_from}-{year_to}")
        elif year_from is not None:
            # >= encoded: apu=>= year_from  (will become %3E%3D after encode_query)
            limitations.append(f"apu=>={year_from}")
        elif year_to is not None:
            limitations.append(f"apu=<={year_to}")

    full_query = query
    if limitations:
        full_query = query + " and " + " and ".join(limitations)

    encoded = encode_query(full_query)

    # ── First call: get total count ────────────────────────────────────────────
    count_url = build_sru_url(encoded, start_record=1, maximum_records=1)
    root_c, t = _get_xml(count_url, max_retries=max_retries, timeout=http_timeout, trace=trace_eff)
    trace_events.extend(t)
    count_el = root_c.find(".//srw:numberOfRecords", namespaces=SRU_NS)
    total = int(count_el.text) if count_el is not None and count_el.text else 0

    if total == 0:
        out: dict = {
            "total_found": 0,
            "returned": 0,
            "results": [],
            "query_used": full_query,
        }
        if trace_eff:
            out["trace"] = trace_events
        return out

    # ── Paginate to collect up to max_results records ─────────────────────────
    to_fetch = min(max_results, total, 1000)
    batch_size = min(100, to_fetch)
    records: list[dict] = []

    for start in range(1, to_fetch + 1, batch_size):
        this_batch = min(batch_size, to_fetch - len(records))
        url = build_sru_url(encoded, start_record=start, maximum_records=this_batch)
        root_r, t = _get_xml(url, max_retries=max_retries, timeout=http_timeout, trace=trace_eff)
        trace_events.extend(t)

        for srw_rec in root_r.findall(".//srw:record", namespaces=SRU_NS):
            rd = srw_rec.find("./srw:recordData", namespaces=SRU_NS)
            if rd is None:
                continue
            unimarc = _unimarc_root(rd)
            if unimarc is not None:
                records.append(_format_record(unimarc))

        if len(records) >= to_fetch:
            break

        # Small courtesy pause between pages
        time.sleep(0.2)

    out = {
        "total_found": total,
        "returned": len(records),
        "results": records,
        "query_used": full_query,
    }
    if trace_eff:
        out["trace"] = trace_events
    return out


def lookup_by_ppn(
    ppn: str,
    *,
    trace: bool | None = None,
    http_timeout: float | None = None,
    max_retries: int | None = None,
) -> dict:
    """
    Fetch a single Sudoc record by its PPN (Pica Production Number).
    Returns the normalised record dict, or an error if not found.
    """
    trace_eff = TRACE_DEFAULT if trace is None else bool(trace)
    encoded = encode_query(f"ppn={ppn}")
    url = build_sru_url(encoded, start_record=1, maximum_records=1)
    root, tevents = _get_xml(url, max_retries=max_retries, timeout=http_timeout, trace=trace_eff)

    recs = root.findall(".//srw:record", namespaces=SRU_NS)
    result: dict | None = None
    for srw_rec in recs:
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
        out = {"total_found": 0, "returned": 0, "results": [],
               "error": f"PPN not found in Sudoc: '{ppn}'"}

    if trace_eff:
        out["trace"] = tevents
    return out


def lookup_by_isbn(
    isbn: str,
    *,
    trace: bool | None = None,
    http_timeout: float | None = None,
    max_retries: int | None = None,
) -> dict:
    """
    Fetch Sudoc record(s) by ISBN (hyphens optional; ISBN-10 and ISBN-13 both accepted).
    Note: one ISBN may match multiple records (different editions, holdings, etc.).
    """
    trace_eff = TRACE_DEFAULT if trace is None else bool(trace)
    # Strip hyphens — Sudoc accepts both forms but the clean form is more reliable
    clean_isbn = isbn.replace("-", "")
    encoded = encode_query(f"isb={clean_isbn}")
    url = build_sru_url(encoded, start_record=1, maximum_records=10)
    root, tevents = _get_xml(url, max_retries=max_retries, timeout=http_timeout, trace=trace_eff)

    records = []
    count_el = root.find(".//srw:numberOfRecords", namespaces=SRU_NS)
    total = int(count_el.text) if count_el is not None and count_el.text else 0

    for srw_rec in root.findall(".//srw:record", namespaces=SRU_NS):
        rd = srw_rec.find("./srw:recordData", namespaces=SRU_NS)
        if rd is not None:
            unimarc = _unimarc_root(rd)
            if unimarc is not None:
                records.append(_format_record(unimarc))

    out: dict = {
        "total_found": total,
        "returned": len(records),
        "results": records,
        "isbn_queried": isbn,
    }
    if trace_eff:
        out["trace"] = tevents
    return out


def scan_index(
    index_key: str,
    term: str,
    *,
    maximum_terms: int = 25,
    response_position: int = 1,
    trace: bool | None = None,
    http_timeout: float | None = None,
    max_retries: int | None = None,
) -> dict:
    """
    Browse a Sudoc index alphabetically starting from `term` (SRU scan operation).
    Useful for discovering valid terms, checking spelling, or debugging zero results.

    Parameters
    ----------
    index_key : str
        Sudoc index key, e.g. ``"mti"``, ``"aut"``, ``"vma"``.
    term : str
        Starting term to scan from.
    maximum_terms : int
        Number of index terms to return (default 25, server default 10).
    response_position : int
        Position of `term` in the returned list (default 1 = first item).
    """
    trace_eff = TRACE_DEFAULT if trace is None else bool(trace)

    scan_clause = f"{index_key}%3D{term}"
    url = (
        f"{SRU_BASE_URL}?operation=scan&version=1.1"
        f"&scanClause={scan_clause}"
        f"&responsePosition={response_position}"
        f"&maximumTerms={maximum_terms}"
    )
    root, tevents = _get_xml(url, max_retries=max_retries, timeout=http_timeout, trace=trace_eff)

    # Parse scan response: terms are in <srw:terms><srw:term><srw:value> ...
    terms: list[dict] = []
    for term_el in root.findall(".//{http://www.loc.gov/zing/srw/}term"):
        value_el = term_el.find("{http://www.loc.gov/zing/srw/}value")
        count_el = term_el.find("{http://www.loc.gov/zing/srw/}numberOfRecords")
        terms.append({
            "term":    (value_el.text or "").strip() if value_el is not None else None,
            "count":   int(count_el.text) if count_el is not None and count_el.text else None,
        })

    out: dict = {
        "index": index_key,
        "start_term": term,
        "terms": terms,
    }
    if trace_eff:
        out["trace"] = tevents
    return out


# ══════════════════════════════════════════════════════════════════════════════
# SECTION : CLI facade
# ══════════════════════════════════════════════════════════════════════════════

def _print_json(data: object) -> int:
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="sudoc",
        description="Query the Sudoc catalogue via SRU. Output is strict JSON on stdout.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    # ── search ────────────────────────────────────────────────────────────────
    ap_s = sub.add_parser(
        "search",
        help="Search Sudoc by SRU query. Returns normalised UNIMARC records as JSON.",
    )
    ap_s.add_argument(
        "--query", required=True,
        help=(
            "SRU query using Sudoc index keys. Use natural syntax: "
            "'mti=jardins and japonais' or 'aut=zola and mti=nana'. "
            "Supports boolean operators (and/or/not), truncation (*), "
            "and phrase indexes (auto-quoting handled internally)."
        ),
    )
    ap_s.add_argument("--max-results", type=int, default=15, help="Max records to return (default 15, max 1000)")
    ap_s.add_argument("--doc-type",      default=None, help="TDO code: a b f g i k m n o t v x y")
    ap_s.add_argument("--language",      default=None, help="ISO 639-2/3 code for LAI (most languages)")
    ap_s.add_argument("--lang-major",    default=None, help="LAN code for major languages: ger eng spa fre ita lat dut pol por rus")
    ap_s.add_argument("--country",       default=None, help="ISO 3166 code for PAI (most countries)")
    ap_s.add_argument("--country-major", default=None, help="PAY code for major countries: de be ca es us fr it nl gb ru ch")
    ap_s.add_argument("--year-from",  type=int, default=None, help="Lower bound publication year (inclusive)")
    ap_s.add_argument("--year-to",    type=int, default=None, help="Upper bound publication year (inclusive)")
    ap_s.add_argument("--year-exact", type=int, default=None, help="Exact publication year")
    ap_s.add_argument("--trace", action="store_true", help="Include HTTP trace in JSON output")

    # ── lookup-by-ppn ─────────────────────────────────────────────────────────
    ap_p = sub.add_parser("lookup-by-ppn", help="Fetch a single record by Sudoc PPN.")
    ap_p.add_argument("--ppn", required=True, help="Sudoc PPN (e.g. 070685045)")
    ap_p.add_argument("--trace", action="store_true")

    # ── lookup-by-isbn ────────────────────────────────────────────────────────
    ap_i = sub.add_parser("lookup-by-isbn", help="Fetch record(s) by ISBN (10 or 13, hyphens optional).")
    ap_i.add_argument("--isbn", required=True, help="ISBN with or without hyphens")
    ap_i.add_argument("--trace", action="store_true")

    # ── count ─────────────────────────────────────────────────────────────────
    ap_c = sub.add_parser("count", help="Return total number of records matching a query (no data fetched).")
    ap_c.add_argument("--query", required=True, help="SRU query (same syntax as search)")
    ap_c.add_argument("--trace", action="store_true")

    # ── scan ──────────────────────────────────────────────────────────────────
    ap_sc = sub.add_parser(
        "scan",
        help="Browse a Sudoc index alphabetically. Useful for discovering terms and debugging.",
    )
    ap_sc.add_argument("--index", required=True, help="Index key: mti aut per org vma msu edi col nth …")
    ap_sc.add_argument("--term",  required=True, help="Starting term to scan from")
    ap_sc.add_argument("--max-terms",         type=int, default=25, help="Number of terms to return (default 25)")
    ap_sc.add_argument("--response-position", type=int, default=1,  help="Position of --term in the list (default 1)")
    ap_sc.add_argument("--trace", action="store_true")

    args = ap.parse_args()
    common: dict[str, Any] = {"trace": bool(getattr(args, "trace", False))}

    if args.cmd == "search":
        data = search(
            query=args.query,
            max_results=args.max_results,
            doc_type=args.doc_type,
            language=args.language,
            lang_major=args.lang_major,
            country=args.country,
            country_major=args.country_major,
            year_from=args.year_from,
            year_to=args.year_to,
            year_exact=args.year_exact,
            **common,
        )
        return _print_json(data)

    if args.cmd == "lookup-by-ppn":
        return _print_json(lookup_by_ppn(ppn=args.ppn, **common))

    if args.cmd == "lookup-by-isbn":
        return _print_json(lookup_by_isbn(isbn=args.isbn, **common))

    if args.cmd == "count":
        return _print_json(count_records(query=args.query, **common))

    if args.cmd == "scan":
        return _print_json(scan_index(
            index_key=args.index,
            term=args.term,
            maximum_terms=args.max_terms,
            response_position=args.response_position,
            **common,
        ))

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
