#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "sentence-transformers>=3.0.0",
# ]
# ///
"""Qualinka/Paprika IdRef authority-resolution CLI."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


FIND_RA_ENDPOINT = "https://qualinka.idref.fr/data/find-ra-idref/api/v2/debug/req"
ATTRRA_ENDPOINT = "https://qualinka.idref.fr/data/attrra/api/v2/req"
REFERENCES_ENDPOINT = "https://www.idref.fr/services/references/{ppn}.json"
RETRIED_STATUS = {429, 500, 502, 503, 504}
USER_AGENT = "smartbiblia-resolve-authorities-idref/0.1"

EMBEDDER = None
EMBEDDING_CACHE: dict[str, list[float]] = {}


@dataclass
class EvidenceScore:
    name: float = 0.0
    attrra_source: float = 0.0
    attrra_note: float = 0.0
    references: float = 0.0
    context_match: float = 0.0
    final: float = 0.0


@dataclass
class Candidate:
    ppn: str
    first_name: str | None = None
    last_name: str | None = None
    attrra: dict[str, Any] | None = None
    references: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)
    score: EvidenceScore = field(default_factory=EvidenceScore)
    evidence: dict[str, Any] = field(default_factory=dict)


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def write_json(payload: dict[str, Any]) -> int:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


def normalize_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def name_similarity(left: Any, right: Any) -> float:
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    if not left_norm and not right_norm:
        return 1.0
    if not left_norm or not right_norm:
        return 0.0
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    intersection = left_tokens & right_tokens
    token_f1 = 2 * len(intersection) / (len(left_tokens) + len(right_tokens))
    char_ratio = SequenceMatcher(None, left_norm, right_norm).ratio()
    return 0.6 * token_f1 + 0.4 * char_ratio


def text_vector(value: str) -> dict[str, float]:
    vector: dict[str, float] = {}
    for token in normalize_text(value).split():
        if len(token) > 2:
            vector[token] = vector.get(token, 0.0) + 1.0
    return vector


def cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(left[token] * right[token] for token in set(left) & set(right))
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def lexical_similarity(left: str, right: str) -> float:
    return cosine_similarity(text_vector(left), text_vector(right))


def load_embedder(model_name: str) -> Any:
    global EMBEDDER
    if EMBEDDER is None:
        from sentence_transformers import SentenceTransformer

        EMBEDDER = SentenceTransformer(model_name)
    return EMBEDDER


def embedding_vector(text: str, model_name: str) -> list[float]:
    cache_key = f"{model_name}\0{text}"
    if cache_key not in EMBEDDING_CACHE:
        model = load_embedder(model_name)
        EMBEDDING_CACHE[cache_key] = model.encode(text, normalize_embeddings=True).tolist()
    return EMBEDDING_CACHE[cache_key]


def semantic_similarity(left: str, right: str, embedding_model: str | None) -> float:
    if not left.strip() or not right.strip():
        return 0.0
    if not embedding_model:
        return lexical_similarity(left, right)
    left_vec = embedding_vector(left, embedding_model)
    right_vec = embedding_vector(right, embedding_model)
    return max(0.0, sum(a * b for a, b in zip(left_vec, right_vec)))


def request_json(args: argparse.Namespace, url: str) -> tuple[Any | None, str | None]:
    timeout = args.timeout
    retries = args.retries
    backoff = args.backoff
    factor = args.backoff_factor
    if args.trace:
        print(f"[GET] {url}", file=sys.stderr)
    last_error = None
    for attempt in range(retries + 1):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urlopen(request, timeout=timeout) as response:
                payload = response.read().decode("utf-8")
            return json.loads(payload), None
        except HTTPError as exc:
            last_error = f"HTTP {exc.code}: {exc.reason}"
            if exc.code not in RETRIED_STATUS:
                break
        except URLError as exc:
            last_error = f"URL error: {exc.reason}"
        except Exception as exc:
            last_error = str(exc)
        if attempt < retries:
            time.sleep(backoff * (factor ** attempt))
    return None, last_error


def parse_person_name(full_name: str) -> tuple[str, str]:
    cleaned = re.sub(r"\s+", " ", full_name.strip())
    if "," in cleaned:
        last, first = [part.strip() for part in cleaned.split(",", 1)]
        return first, last
    particles = {"de", "du", "des", "del", "della", "van", "von", "le", "la"}
    parts = cleaned.split()
    if len(parts) <= 1:
        return "", cleaned
    last_start = len(parts) - 1
    while last_start > 0 and normalize_text(parts[last_start - 1]) in particles:
        last_start -= 1
    return " ".join(parts[:last_start]), " ".join(parts[last_start:])


def resolved_name(args: argparse.Namespace) -> tuple[str, str, str, str]:
    parsed_first, parsed_last = parse_person_name(args.name or "")
    first = args.first_name or parsed_first
    last = args.last_name or parsed_last
    return first, last, parsed_first, parsed_last


def common_authority_record(ppn: str, first_name: Any = None, last_name: Any = None) -> dict[str, Any]:
    title = " ".join(str(part) for part in (first_name, last_name) if part)
    return {
        "source": "idref",
        "id": ppn,
        "ppn": ppn,
        "title": title or None,
        "authors": None,
        "abstract": None,
        "doi": None,
        "pdf_url": None,
        "url": f"https://www.idref.fr/{ppn}",
        "year": None,
        "date": None,
        "doc_type": "authority-person",
        "journal": None,
        "first_name": first_name,
        "last_name": last_name,
    }


def find_person(args: argparse.Namespace) -> tuple[list[Candidate], dict[str, Any]]:
    first, last, parsed_first, parsed_last = resolved_name(args)
    if not last:
        return [], {
            "source": "qualinka_find_ra_idref",
            "query": {"name": args.name, "first_name": first, "last_name": last},
            "found": 0,
            "returned": 0,
            "results": [],
            "error": "Missing last name.",
        }
    query = {"lastName": last}
    if first:
        query["firstName"] = first
    url = f"{FIND_RA_ENDPOINT}?{urlencode(query)}"
    payload, error = request_json(args, url)
    if error or not isinstance(payload, list):
        return [], {
            "source": "qualinka_find_ra_idref",
            "query": {
                "name": args.name,
                "first_name": first,
                "last_name": last,
                "parsed_first_name": parsed_first,
                "parsed_last_name": parsed_last,
            },
            "found": 0,
            "returned": 0,
            "results": [],
            "error": error or "Unexpected response shape.",
        }

    seen = set()
    candidates: list[Candidate] = []
    for block in payload:
        for item in block.get("results", []) if isinstance(block, dict) else []:
            ppn = str(item.get("ppn") or "").strip()
            if not ppn or ppn in seen:
                continue
            seen.add(ppn)
            candidates.append(Candidate(ppn=ppn, first_name=item.get("firstName"), last_name=item.get("lastName")))
            if len(candidates) >= args.max_results:
                break
        if len(candidates) >= args.max_results:
            break

    records = [common_authority_record(c.ppn, c.first_name, c.last_name) for c in candidates]
    return candidates, {
        "source": "qualinka_find_ra_idref",
        "query": {
            "name": args.name,
            "first_name": first,
            "last_name": last,
            "parsed_first_name": parsed_first,
            "parsed_last_name": parsed_last,
        },
        "found": sum(int(block.get("found", 0)) for block in payload if isinstance(block, dict)),
        "returned": len(records),
        "results": records,
        "error": None,
    }


def fetch_attrra(args: argparse.Namespace, ppn: str) -> dict[str, Any]:
    url = f"{ATTRRA_ENDPOINT}?{urlencode({'ra_id': ppn})}"
    payload, error = request_json(args, url)
    return {
        "source": "qualinka_attrra",
        "ppn": ppn,
        "url": f"https://www.idref.fr/{ppn}",
        "record": payload if isinstance(payload, dict) else None,
        "error": error if error else (None if isinstance(payload, dict) else "Unexpected response shape."),
    }


def fetch_references(args: argparse.Namespace, ppn: str) -> dict[str, Any]:
    url = REFERENCES_ENDPOINT.format(ppn=ppn)
    payload, error = request_json(args, url)
    if not error and isinstance(payload, dict):
        roles = payload.get("roles", [])
        if args.max_roles is not None:
            roles = roles[: args.max_roles]
        for role in roles:
            if isinstance(role, dict) and isinstance(role.get("docs"), list):
                role["docs"] = role["docs"][: args.max_docs_per_role]
        payload["roles"] = roles
    return {
        "source": "idref_references",
        "ppn": ppn,
        "roles": payload.get("roles", []) if isinstance(payload, dict) else [],
        "error": error if error else (None if isinstance(payload, dict) else "Unexpected response shape."),
    }


def as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)] if str(value).strip() else []


def preferred_forms(candidate: Candidate) -> list[str]:
    forms = []
    for item in (candidate.attrra or {}).get("preferedform", []):
        if isinstance(item, dict) and item.get("value"):
            forms.append(str(item["value"]))
    joined = " ".join(part for part in [candidate.first_name, candidate.last_name] if part)
    if joined:
        forms.append(joined)
    return forms


def reference_citations(candidate: Candidate) -> list[dict[str, str]]:
    refs = candidate.references or {}
    citations = []
    for role in refs.get("roles", []):
        if not isinstance(role, dict):
            continue
        role_name = str(role.get("role_name") or "")
        for doc in role.get("docs", []):
            if isinstance(doc, dict) and doc.get("citation"):
                citations.append({"role": role_name, "citation": str(doc["citation"])})
    return citations


def context_clues(args: argparse.Namespace) -> list[str]:
    """All free-text disambiguation clues supplied by the caller, source-agnostic.

    `--work` may be repeated (e.g. several titles the person authored). The other
    clues describe who the person is: field/domain, affiliation, role, year, and
    any extra free text passed via `--context`.
    """
    works = list(getattr(args, "work", None) or [])
    parts = [args.name, *works, args.field, args.affiliation, args.role, args.year, args.context]
    return [part for part in parts if part]


def current_context(args: argparse.Namespace) -> str:
    return " ".join(context_clues(args))


def ranked_similarities(query: str, texts: list[str], embedding_model: str | None) -> list[tuple[float, str]]:
    return sorted(
        [(semantic_similarity(query, text, embedding_model), text) for text in texts],
        key=lambda item: item[0],
        reverse=True,
    )


def best_similarity(query: str, texts: list[str], embedding_model: str | None) -> tuple[float, str | None]:
    ranked = ranked_similarities(query, texts, embedding_model)
    return ranked[0] if ranked else (0.0, None)


def top_k_average_similarity(
    query: str,
    texts: list[str],
    embedding_model: str | None,
    top_k: int,
) -> tuple[float, list[str]]:
    ranked = ranked_similarities(query, texts, embedding_model)[:top_k]
    if not ranked:
        return 0.0, []
    return sum(score for score, _ in ranked) / len(ranked), [text for _, text in ranked]


def context_match_score(args: argparse.Namespace, candidate: Candidate) -> float:
    """Exact-substring boost when the caller's affiliation, field, or year appears
    verbatim in the candidate's authority evidence (notes, sources, references)."""
    evidence = " ".join(
        as_text_list((candidate.attrra or {}).get("noteGen"))
        + as_text_list((candidate.attrra or {}).get("source"))
        + [item["citation"] for item in reference_citations(candidate)]
    )
    normalized = normalize_text(evidence)
    score = 0.0
    if args.affiliation and normalize_text(args.affiliation) in normalized:
        score += 0.5
    if args.field and normalize_text(args.field) in normalized:
        score += 0.25
    if args.year and re.search(rf"\b{re.escape(str(args.year))}\b", evidence):
        score += 0.25
    return min(score, 1.0)


def score_candidate(args: argparse.Namespace, candidate: Candidate) -> None:
    forms = preferred_forms(candidate)
    candidate.score.name = max((name_similarity(args.name, form) for form in forms), default=0.0)
    query = current_context(args)
    sources = as_text_list((candidate.attrra or {}).get("source"))
    notes = as_text_list((candidate.attrra or {}).get("noteGen"))
    ref_texts = [item["citation"] for item in reference_citations(candidate)]
    embedding_model = args.embedding_model or None

    candidate.score.attrra_source, best_source = best_similarity(query, sources, embedding_model)
    candidate.score.attrra_note, best_note = best_similarity(query, notes, embedding_model)
    candidate.score.references, best_refs = top_k_average_similarity(
        query,
        ref_texts,
        embedding_model,
        args.reference_top_k,
    )
    candidate.score.context_match = context_match_score(args, candidate)
    candidate.score.final = (
        0.40 * candidate.score.name
        + 0.25 * candidate.score.attrra_source
        + 0.15 * candidate.score.attrra_note
        + 0.15 * candidate.score.references
        + 0.05 * candidate.score.context_match
    )
    candidate.evidence = {
        "preferred_forms": forms,
        "best_attrra_source": best_source,
        "best_attrra_note": best_note,
        "best_references": best_refs,
    }


def status_for_ranked(ranked: list[Candidate], accept_threshold: float, margin_threshold: float) -> str:
    if not ranked:
        return "not_found"
    if ranked[0].score.final < accept_threshold:
        return "low_confidence"
    if len(ranked) > 1 and ranked[0].score.final - ranked[1].score.final < margin_threshold:
        return "ambiguous"
    return "accepted"


def candidate_to_json(candidate: Candidate) -> dict[str, Any]:
    return {
        "ppn": candidate.ppn,
        "first_name": candidate.first_name,
        "last_name": candidate.last_name,
        "url": f"https://www.idref.fr/{candidate.ppn}",
        "score": {
            "final": round(candidate.score.final, 4),
            "name": round(candidate.score.name, 4),
            "attrra_source": round(candidate.score.attrra_source, 4),
            "attrra_note": round(candidate.score.attrra_note, 4),
            "references": round(candidate.score.references, 4),
            "context_match": round(candidate.score.context_match, 4),
        },
        "evidence": candidate.evidence,
        "errors": candidate.errors,
    }


def cmd_find_person(args: argparse.Namespace) -> int:
    _, payload = find_person(args)
    return write_json(payload)


def cmd_attrra(args: argparse.Namespace) -> int:
    return write_json(fetch_attrra(args, args.ppn))


def cmd_references(args: argparse.Namespace) -> int:
    return write_json(fetch_references(args, args.ppn))


def cmd_align_person(args: argparse.Namespace) -> int:
    candidates, search_payload = find_person(args)
    if search_payload.get("error"):
        return write_json({
            "source": "idref_qualinka_alignment",
            "query": alignment_query(args),
            "candidate_search": search_payload,
            "status": "not_found",
            "best_ppn": None,
            "best_candidate": None,
            "candidates": [],
            "error": search_payload["error"],
        })

    for candidate in candidates:
        attrra_payload = fetch_attrra(args, candidate.ppn)
        refs_payload = fetch_references(args, candidate.ppn)
        candidate.attrra = attrra_payload.get("record")
        candidate.references = {"roles": refs_payload.get("roles", [])}
        for payload in (attrra_payload, refs_payload):
            if payload.get("error"):
                candidate.errors.append(str(payload["error"]))
        score_candidate(args, candidate)

    ranked = sorted(candidates, key=lambda item: item.score.final, reverse=True)
    status = status_for_ranked(ranked, args.accept_threshold, args.margin_threshold)
    return write_json({
        "source": "idref_qualinka_alignment",
        "query": alignment_query(args),
        "candidate_search": search_payload,
        "status": status,
        "best_ppn": ranked[0].ppn if status == "accepted" else None,
        "best_candidate": candidate_to_json(ranked[0]) if ranked else None,
        "candidates": [candidate_to_json(candidate) for candidate in ranked],
        "error": None,
    })


def alignment_query(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "name": args.name,
        "first_name": args.first_name,
        "last_name": args.last_name,
        "works": list(getattr(args, "work", None) or []),
        "field": args.field,
        "affiliation": args.affiliation,
        "role": args.role,
        "year": args.year,
        "context": args.context,
    }


def add_common_http_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--timeout", type=float, default=env_float("IDREF_HTTP_TIMEOUT", 20.0))
    parser.add_argument("--retries", type=int, default=env_int("IDREF_MAX_RETRIES", 2))
    parser.add_argument("--backoff", type=float, default=env_float("IDREF_BACKOFF_BASE", 1.0))
    parser.add_argument("--backoff-factor", type=float, default=env_float("IDREF_BACKOFF_FACTOR", 2.0))
    parser.add_argument("--trace", action="store_true", default=os.getenv("IDREF_TRACE", "0") == "1")


def add_name_args(parser: argparse.ArgumentParser, require_name: bool) -> None:
    parser.add_argument("--name", required=require_name, default="", help="Full extracted person name.")
    parser.add_argument("--first-name", default="", help="Override parsed first name.")
    parser.add_argument("--last-name", default="", help="Override parsed last name.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve IdRef person authorities with Qualinka/Paprika.")
    sub = parser.add_subparsers(dest="command", required=True)

    find_parser = sub.add_parser("find-person", help="Find person authority candidates.")
    add_name_args(find_parser, require_name=False)
    find_parser.add_argument("--max-results", type=int, default=20)
    add_common_http_args(find_parser)
    find_parser.set_defaults(func=cmd_find_person)

    attrra_parser = sub.add_parser("attrra", help="Fetch Qualinka attrra authority evidence.")
    attrra_parser.add_argument("--ppn", required=True)
    add_common_http_args(attrra_parser)
    attrra_parser.set_defaults(func=cmd_attrra)

    refs_parser = sub.add_parser("references", help="Fetch IdRef linked references.")
    refs_parser.add_argument("--ppn", required=True)
    refs_parser.add_argument("--max-roles", type=int, default=None)
    refs_parser.add_argument("--max-docs-per-role", type=int, default=10)
    add_common_http_args(refs_parser)
    refs_parser.set_defaults(func=cmd_references)

    align_parser = sub.add_parser(
        "align-person",
        help="Align a person to an IdRef PPN using any disambiguation clues.",
    )
    add_name_args(align_parser, require_name=True)
    # Source-agnostic disambiguation clues. `--work` may be repeated.
    align_parser.add_argument(
        "--work", "--title", "--subtitle", dest="work", action="append", default=None,
        help="Title of a work the person produced (book, article, report, ...). Repeatable.",
    )
    align_parser.add_argument(
        "--field", "--discipline", dest="field", default="",
        help="Field, domain, or discipline the person works in.",
    )
    align_parser.add_argument(
        "--affiliation", "--institution", "--doctoral-school", dest="affiliation", default="",
        help="Institution or organization the person is affiliated with.",
    )
    align_parser.add_argument(
        "--role", "--degree-type", dest="role", default="",
        help="Role or capacity (author, editor, researcher, ...). Low ranking weight.",
    )
    align_parser.add_argument("--year", default="", help="A year associated with the person or work.")
    align_parser.add_argument(
        "--context", default="",
        help="Any extra free-text clues to disambiguate the person.",
    )
    align_parser.add_argument("--max-results", type=int, default=20)
    align_parser.add_argument("--max-candidates", type=int, default=20)
    align_parser.add_argument("--max-roles", type=int, default=None)
    align_parser.add_argument("--max-docs-per-role", type=int, default=20)
    align_parser.add_argument("--reference-top-k", type=int, default=3)
    align_parser.add_argument("--embedding-model", default="")
    align_parser.add_argument("--accept-threshold", type=float, default=0.65)
    align_parser.add_argument("--margin-threshold", type=float, default=0.08)
    add_common_http_args(align_parser)
    align_parser.set_defaults(func=cmd_align_person)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "command", "") == "align-person":
        args.max_results = args.max_candidates
    if getattr(args, "command", "") == "find-person" and not (args.name or args.last_name):
        return write_json({
            "source": "qualinka_find_ra_idref",
            "query": {"name": args.name, "first_name": args.first_name, "last_name": args.last_name},
            "found": 0,
            "returned": 0,
            "results": [],
            "error": "Provide --name or --last-name.",
        })
    try:
        return args.func(args)
    except Exception as exc:
        return write_json({"source": "resolve-authorities-idref", "error": str(exc)})


if __name__ == "__main__":
    raise SystemExit(main())
