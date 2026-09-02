#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ['httpx', 'python-dotenv']
# ///

"""Thin client for the humatheque-dewey-classifier-api service.

Assigns Dewey classes to French doctoral theses by semantic similarity, from the
metadata a thesis record carries — its title, its subject keywords, its abstract.
The vocabulary is the reduced Dewey list French thesis cataloguing uses in the
Sudoc, 98 classes, which is why the granularity stops at the division level. Text
that is not a thesis is still accepted and still answered, from that same list.

The taxonomy, the embedding model, the ranking and the scores all live in the
API; this file only builds a request, forwards the key, and prints the answer. No
embedding, no ranking, no call to any host but the API.

Usage:
    ./cli.py classify --text "Histoire politique de Buenos Aires au XIXe siècle"
    ./cli.py classify --file sujets-theses.txt --top-k 3 --method albert
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

API_URL = os.getenv("DEWEY_API_URL", "https://dewey-classifier.smartbiblia.fr").rstrip("/")
API_KEY = os.getenv("DEWEY_API_KEY", "")

# Constants, not tunables. The first request against a cold deployment loads the
# sentence-embedding model and builds the taxonomy index, which is why the
# timeout is generous; later requests answer in well under a second.
HTTP_TIMEOUT = 120.0
MAX_RETRIES = 2
BACKOFF_BASE = 1.0
BACKOFF_FACTOR = 2.0
RETRIED_STATUS = {429, 500, 502, 503, 504}

# Clamps applied before the request, so a mistake fails here instead of costing
# a round trip. The API accepts any positive top_k; 98 is the whole thesis list.
MAX_TOP_K = 98
MAX_TEXTS = 50

CLASSIFICATION_TYPES = ["multi-label", "single-label"]
METHODS = ["local", "albert"]

# One pooled client: httpx.post() would rebuild the connection — and the TLS
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
            # The API answers 4xx only on a caller mistake — a bad key, a missing
            # `text`, an unknown method, a `codes` list with nothing known in it.
            # Its `detail` says which.
            last_error = f"HTTP {response.status_code}: {response.text[:300]}"
            if response.status_code not in RETRIED_STATUS:
                break
        except Exception as exc:  # unreachable API, malformed JSON
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < MAX_RETRIES:
            time.sleep(BACKOFF_BASE * (BACKOFF_FACTOR**attempt))
    return None, last_error


def collect_texts(args: argparse.Namespace) -> tuple[list[str], str | None]:
    """Gather the texts to classify from --text and --file, in that order."""
    texts = [t.strip() for t in (args.text or []) if t and t.strip()]
    if args.file:
        try:
            with open(args.file, encoding="utf-8") as handle:
                texts += [line.strip() for line in handle if line.strip()]
        except OSError as exc:
            return [], f"cannot read --file {args.file}: {exc}"
    if not texts:
        return [], "no text to classify: pass --text (repeatable) or --file"
    if len(texts) > MAX_TEXTS:
        return [], f"{len(texts)} texts given; this client sends at most {MAX_TEXTS} per call"
    return texts, None


def cmd_classify(args: argparse.Namespace) -> None:
    # Every key is present on failure too, so a caller reads one shape.
    reply: dict[str, Any] = {
        "source": None,
        "command": "classify",
        "api_url": API_URL,
        "method": args.method,
        "model": None,
        "classification_type": args.classification_type,
        "threshold": args.threshold,
        "count": 0,
        "results": [],
        "error": None,
    }

    texts, error = collect_texts(args)
    if error:
        reply["error"] = error
        emit(reply)
        return

    body: dict[str, Any] = {
        # A single text stays a string, so the API's own echo matches what was sent.
        "text": texts[0] if len(texts) == 1 else texts,
        "codes": args.code or None,
        "threshold": args.threshold,
        "classification_type": args.classification_type,
        "top_k": max(1, min(args.top_k, MAX_TOP_K)),
        "method": args.method,
    }
    result, error = call_api("POST", "/classify", body)
    if error:
        reply["error"] = error
        emit(reply)
        return

    # The API's payload is the contract; pass it through, only noting which
    # command and endpoint produced it. Trimming would mean two schemas to keep
    # in step.
    emit({**reply, **result, "command": "classify", "api_url": API_URL, "error": None})


def cmd_health(_: argparse.Namespace) -> None:
    result, error = call_api("GET", "/health")
    emit(
        {
            "command": "health",
            "api_url": API_URL,
            "ok": bool(result and result.get("ok")),
            "error": error,
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Classify French doctoral theses into the reduced Dewey list "
        "used for thesis cataloguing in the Sudoc, through the "
        "humatheque-dewey-classifier-api service.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    classify = sub.add_parser(
        "classify",
        help="Rank Dewey classes against one or several thesis texts.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    classify.add_argument(
        "--text",
        action="append",
        default=[],
        help="A thesis text to classify — a title, subject keywords, an "
        "abstract. Repeatable for a batch, which is cheaper than one call "
        "per text.",
    )
    classify.add_argument(
        "--file",
        default="",
        help="File holding one text per line; appended to any --text values.",
    )
    classify.add_argument(
        "--code",
        action="append",
        default=[],
        help="Restrict the candidate classes to this Dewey code, e.g. 980. "
        "Repeatable. Unknown codes are ignored; a list with none known is a 400.",
    )
    classify.add_argument(
        "--threshold",
        type=float,
        default=0.0,
        help="Drop classes scoring below this. Scores cluster high (~0.7-0.9) "
        "even for weak matches, so prefer --top-k over a cutoff.",
    )
    classify.add_argument(
        "--classification-type",
        choices=CLASSIFICATION_TYPES,
        default="multi-label",
        help="multi-label returns up to --top-k classes; single-label the best one.",
    )
    classify.add_argument(
        "--top-k",
        type=int,
        default=5,
        help=f"Classes to return per text. Clamped to {MAX_TOP_K}, the size of "
        "the thesis list.",
    )
    classify.add_argument(
        "--method",
        choices=METHODS,
        default="local",
        help="local: the deployment's own bi-encoder, always available. "
        "albert: Albert API retrieve-then-rerank; scores are reranker "
        "relevance, not cosine, and are not comparable to local scores.",
    )
    classify.set_defaults(func=cmd_classify)

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
