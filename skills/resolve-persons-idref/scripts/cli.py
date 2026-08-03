#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ['httpx', 'python-dotenv']
# ///

"""Thin client for the idref-resolver-api service.

Aligns a person to an IdRef PPN. Every score, threshold and status is decided by
the API; this file only builds a request, forwards the key, and prints the
answer. No scoring, no ranking, no call to any host but the API.

Usage:
    ./cli.py align-person --name "Valérie Robert" --affiliation Nancy --year 2003
    ./cli.py health
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

API_URL = os.getenv("IDREF_API_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.getenv("IDREF_API_KEY", "")

# Constants, not tunables. An alignment fans out to as many as 41 upstream ABES
# requests behind the API, so the timeout is generous on purpose; the API does
# its own retrying, so the attempts here only cover reaching it at all.
HTTP_TIMEOUT = 180.0
MAX_RETRIES = 2
BACKOFF_BASE = 1.0
BACKOFF_FACTOR = 2.0
RETRIED_STATUS = {429, 500, 502, 503, 504}

EMBEDDING_MODELS = ["lexical", "lexical-idf", "albert-bge-m3", "granite", "qwen", "minilm"]

# One pooled client: httpx.get() would rebuild the connection — and the TLS
# handshake — on every call.
HTTP = httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True)


def emit(payload: dict[str, Any]) -> None:
    """Strict JSON on stdout, always exit 0: a failure is data, not a stack trace."""
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def call_api(method: str, path: str, body: dict | None = None) -> tuple[Any, str | None]:
    headers = {"Accept": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY

    url = f"{API_URL}{path}"
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = HTTP.request(method, url, json=body, headers=headers)
            if response.status_code < 400:
                return response.json(), None
            # The API answers 4xx only on a caller mistake — a bad key, a malformed
            # body, a mode this deployment cannot serve. Its `detail` says which.
            last_error = f"HTTP {response.status_code}: {response.text[:300]}"
            if response.status_code not in RETRIED_STATUS:
                break
        except Exception as exc:  # unreachable API, malformed JSON
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < MAX_RETRIES:
            time.sleep(BACKOFF_BASE * (BACKOFF_FACTOR**attempt))
    return None, last_error


def cmd_align_person(args: argparse.Namespace) -> None:
    body = {
        "name": args.name,
        "first_name": args.first_name,
        "last_name": args.last_name,
        "works": args.work,
        "field": args.field,
        "affiliation": args.affiliation,
        "role": args.role,
        "year": args.year,
        "context": args.context,
        "embedding_model": args.embedding_model,
        "max_candidates": args.max_candidates,
        "accept_threshold": args.accept_threshold,
        "margin_threshold": args.margin_threshold,
    }
    result, error = call_api("POST", "/align/person", body)
    if error:
        emit(
            {
                "source": "idref_qualinka_alignment",
                "api_url": API_URL,
                "status": None,
                "best_ppn": None,
                "best_candidate": None,
                "candidates": [],
                "error": error,
            }
        )
        return
    # The API's payload is the contract; pass it through, only noting where it
    # came from. Trimming it here would mean two schemas to keep in step.
    emit({**result, "api_url": API_URL})


def cmd_health(_: argparse.Namespace) -> None:
    result, error = call_api("GET", "/health")
    emit({"api_url": API_URL, "ok": bool(result and result.get("ok")), "error": error})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Align a person to an IdRef PPN through the idref-resolver-api service.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    align = sub.add_parser(
        "align-person",
        help="Score IdRef candidates for a person and accept one PPN or abstain.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    align.add_argument("--name", required=True, help="Full person name.")
    align.add_argument("--first-name", default="", help="Override the parsed first name.")
    align.add_argument("--last-name", default="", help="Override the parsed last name.")
    align.add_argument(
        "--work",
        action="append",
        default=[],
        help="Title of a document the person is linked to. Repeatable.",
    )
    align.add_argument("--field", default="", help="Discipline or subject area.")
    align.add_argument("--affiliation", default="", help="Institution, laboratory or place.")
    align.add_argument("--role", default="", help="Role or document type; not scored.")
    align.add_argument("--year", default="", help="A relevant year, e.g. of publication.")
    align.add_argument("--context", default="", help="Any other free-text clue.")
    align.add_argument(
        "--embedding-model",
        choices=EMBEDDING_MODELS,
        default="lexical-idf",
        help="How texts are compared. Non-lexical modes must be deployed on the API.",
    )
    align.add_argument("--max-candidates", type=int, default=20, help="Candidates to score.")
    align.add_argument("--accept-threshold", type=float, default=0.65)
    align.add_argument("--margin-threshold", type=float, default=0.08)
    align.set_defaults(func=cmd_align_person)

    health = sub.add_parser("health", help="Check that the API is reachable.")
    health.set_defaults(func=cmd_health)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        args.func(args)
    finally:
        HTTP.close()


if __name__ == "__main__":
    main()
