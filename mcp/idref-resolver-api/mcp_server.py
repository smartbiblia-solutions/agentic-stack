#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ['fastmcp>=3.4,<4', 'httpx']
# ///

"""
IdRef resolver MCP server.

Exposes the `idref-resolver-api` API over MCP: align a person named in any
document to an IdRef PPN — the French national authority identifier for persons —
or abstain when the evidence is too weak.

This server is a transport adapter. Every score, threshold and status comes from
`POST /align/person`; nothing is computed here, and no host but the API is called.

Four ways to run:

  # 1. Zero-install — run directly from GitHub (uv fetches everything)
  uv run https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/idref-resolver-api/mcp_server.py \
      --transport stdio

  # 2. Local stdio — client launches the process (recommended for desktop/IDE apps)
  uv run /path/to/mcp/idref-resolver-api/mcp_server.py --transport stdio

  # 3. Local HTTP — run once, connect multiple clients by URL
  uv run /path/to/mcp/idref-resolver-api/mcp_server.py \
      --host 0.0.0.0 --port 8015 --transport http

  # 4. Stateless HTTP — no session affinity, for load-balanced / multi-replica deploys
  uv run /path/to/mcp/idref-resolver-api/mcp_server.py --transport http --stateless

Options:
    --api-url       TEXT    API base URL         [default: http://localhost:8000]
                            (also reads IDREF_API_URL)
    --host          TEXT    Bind host            [default: 0.0.0.0]
    --port          INT     Bind port            [default: 8015]
    --transport     TEXT    stdio | http | sse   [default: http]
                            ("streamable-http" is accepted as an alias of "http")
    --stateless             Stateless HTTP: a new transport per request, so no
                            session is pinned to a replica. Incompatible with sse.
    --http-timeout  FLOAT   Request timeout (s)  [default: 180.0]
    --max-retries   INT     Retry attempts       [default: 2]
    --backoff-base  FLOAT   Backoff base (s)     [default: 1.0]
    --backoff-factor FLOAT  Backoff multiplier   [default: 2.0]
    --jitter-max    FLOAT   Max retry jitter (s) [default: 0.25]
    --trace                 Include API trace in tool responses

The credential is read from IDREF_API_KEY and sent as `X-API-Key`. It is never a
tool argument, never logged, and never echoed into a payload or a trace event.

Domain gotchas:
    An alignment fans out to as many as 41 upstream ABES requests, so a call can
    take tens of seconds. The default timeout is 180s; do not lower it below the
    API's own `IDREF_HTTP_TIMEOUT` budget.

    The API answers HTTP 200 with a populated `error` when an upstream degrades,
    and reserves 4xx for caller mistakes. That distinction is passed through: a
    degraded alignment is a successful tool call carrying `error`.

    `best_ppn` is set only when `status == "accepted"`. `best_candidate` is always
    the top of the ranking, so an abstention can still be inspected. Never treat
    `best_candidate.ppn` as an accepted identifier.

    The local embedding models (`granite`, `qwen`, `minilm`) answer 400 unless
    that deployment mounts their directory; `albert-bge-m3` answers 400 without an
    Albert key. `lexical-idf` always works.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import time
from typing import Any, Literal

import httpx
from fastmcp import FastMCP


# ── CLI args (parsed before anything else so globals are correct) ─────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="MCP server for the idref-resolver-api service.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # Deployment plumbing: env defaults so a container is configured without
    # rewriting its entrypoint.
    p.add_argument("--api-url", default=os.environ.get("IDREF_API_URL", "http://localhost:8000"))
    p.add_argument("--host",       default=os.environ.get("MCP_HOST", "0.0.0.0"))
    p.add_argument("--port",       type=int, default=int(os.environ.get("MCP_PORT", "8015")))
    p.add_argument("--transport",  default=os.environ.get("MCP_TRANSPORT", "http"),
                   choices=["stdio", "http", "sse", "streamable-http"],
                   help='Transport ("streamable-http" is an alias of "http")')
    p.add_argument("--stateless",  action="store_true",
                   default=os.environ.get("MCP_STATELESS", "").lower() in ("1", "true", "yes"),
                   help="Stateless HTTP: new transport per request, no session affinity")
    # Connector tuning: flags only, never environment variables.
    p.add_argument("--http-timeout",   type=float, default=180.0)
    p.add_argument("--max-retries",    type=int,   default=2)
    p.add_argument("--backoff-base",   type=float, default=1.0)
    p.add_argument("--backoff-factor", type=float, default=2.0)
    p.add_argument("--jitter-max",     type=float, default=0.25)
    p.add_argument("--trace",          action="store_true", default=False)
    ns = p.parse_args()
    # FastMCP raises on this combination; fail here instead, with a usage message.
    if ns.stateless and ns.transport == "sse":
        p.error("--stateless is not supported by the sse transport; use --transport http")
    return ns


args = _parse_args()

# ── Config (sourced from CLI args only) ───────────────────────────────────────

API_BASE_URL = args.api_url.rstrip("/")
# The credential is read from the environment only: never a tool argument, never
# echoed into a payload or a trace event.
API_KEY = os.environ.get("IDREF_API_KEY", "")

HTTP_TIMEOUT   = max(1.0, args.http_timeout)
MAX_RETRIES    = max(1, args.max_retries)
BACKOFF_BASE   = max(0.0, args.backoff_base)
BACKOFF_FACTOR = max(1.0, args.backoff_factor)
JITTER_MAX     = max(0.0, args.jitter_max)
TRACE_DEFAULT  = args.trace
RETRIED_STATUS = {429, 500, 502, 503, 504}

# One pooled client for the process. An AsyncClient per call would rebuild the
# connection pool — and replay the TLS handshake — every time.
HTTP = httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True)

# Mirrors the API's `EmbeddingModel` Literal. A closed enum there is a closed
# enum here, so a wrong value fails in the client instead of costing a round trip.
EmbeddingModel = Literal["lexical", "lexical-idf", "albert-bge-m3", "granite", "qwen", "minilm"]


# ── The one host this server calls ────────────────────────────────────────────

def _backoff(attempt: int) -> float:
    return BACKOFF_BASE * (BACKOFF_FACTOR**attempt) + random.uniform(0.0, JITTER_MAX)


async def _post_api(
    path: str, payload: dict, *, trace: bool
) -> tuple[dict | None, str | None, list[dict]]:
    """
    Call the API. Returns (data, error, trace_events) — never raises.

    The API answers HTTP 200 with a populated `error` when an upstream degrades,
    and reserves 4xx for caller mistakes. A 4xx comes back here as an `error`
    string so the model reads the failure instead of a protocol exception.
    """
    trace_events: list[dict] = []
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY

    url = f"{API_BASE_URL}{path}"
    for attempt in range(MAX_RETRIES):
        started = time.perf_counter()
        if trace:
            trace_events.append({"event": "api_request", "attempt": attempt + 1, "url": url})
        try:
            resp = await HTTP.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            if trace:
                trace_events.append(
                    {"event": "api_error", "attempt": attempt + 1, "message": str(exc)}
                )
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(_backoff(attempt))
                continue
            return None, f"cannot reach the API at {API_BASE_URL}: {exc}", trace_events

        if trace:
            trace_events.append(
                {
                    "event": "api_response",
                    "attempt": attempt + 1,
                    "status_code": resp.status_code,
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                }
            )
        if resp.status_code in RETRIED_STATUS and attempt < MAX_RETRIES - 1:
            await asyncio.sleep(_backoff(attempt))
            continue
        if resp.status_code >= 400:
            # Surface the API's own detail; never echo the key back.
            return None, f"API {resp.status_code}: {resp.text[:300]}", trace_events
        try:
            return resp.json(), None, trace_events
        except ValueError:
            return None, f"API returned a non-JSON body: {resp.text[:200]}", trace_events

    return None, "retries exhausted without a usable response", trace_events


# ── MCP app ───────────────────────────────────────────────────────────────────

mcp = FastMCP(
    name="idref-resolver-api",
    instructions=(
        "Aligns a person named in a document to an IdRef PPN — the French national "
        "authority identifier for persons — using the Qualinka find-ra-idref and "
        "attrra services and the IdRef linked references, all behind one API. "
        "Give the name plus whatever context you have; the service scores every "
        "candidate authority and either accepts one PPN or abstains with a reason. "
        "It never guesses: an ambiguous or low-confidence answer is a real answer."
    ),
)


@mcp.tool
async def align_person(
    name: str,
    works: list[str] | None = None,
    field: str = "",
    affiliation: str = "",
    role: str = "",
    year: str = "",
    context: str = "",
    embedding_model: EmbeddingModel = "lexical-idf",
    max_candidates: int = 20,
    accept_threshold: float = 0.65,
    margin_threshold: float = 0.08,
    max_returned_candidates: int = 5,
    trace: bool = False,
) -> dict:
    """
    Align a person to an IdRef PPN from their name plus any disambiguating context.

    Use this tool whenever a person mentioned in a catalogue record, a document, a
    bibliography or a web page must be tied to the French national authority file:
    "find the PPN of X", "quel est le PPN de X", "align this author to IdRef",
    "authority control for this name". Pass every clue you have — a name alone
    rarely separates two homonyms, and the extra context is what the score is
    computed from.

    Do not use it to search the IdRef catalogue by subject or to fetch a record
    whose PPN you already know; this tool decides *which* PPN, nothing else.

    Domain rules:
      - `best_ppn` is populated only when `status == "accepted"`. On any other
        status the alignment abstained: report the abstention, do not fall back to
        `best_candidate.ppn`.
      - Raising `accept_threshold` or `margin_threshold` makes the service stricter,
        i.e. more abstentions. Do not lower them to force an answer.
      - `lexical-idf` needs no model and always works. `albert-bge-m3` requires the
        deployment to hold an Albert key; `granite`, `qwen` and `minilm` require the
        model directory to be mounted. A mode the deployment cannot serve comes back
        with `error` naming what is missing.
      - An alignment fans out to as many as 41 upstream requests; a call can take
        tens of seconds.

    Args:
        name: Full person name, e.g. "Valérie Robert". Required.
        works: Titles of documents the person is linked to, e.g.
               ["Nous n'avons jamais été modernes"]. Repeatable and often decisive.
        field: Discipline or subject area, e.g. "sociologie des sciences".
        affiliation: Institution, laboratory or place, e.g. "Université de Nancy".
        role: Role or document type, e.g. "auteur", "directeur de thèse". Excluded
              from the score on purpose; it only enriches the context text.
        year: A relevant year as a string, e.g. "2003".
        context: Any other free text — a biographical note, an abstract.
        embedding_model: How texts are compared. One of lexical, lexical-idf,
                         albert-bge-m3, granite, qwen, minilm.
        max_candidates: Candidate authorities to enrich and score. API clamps to 100.
        accept_threshold: Minimum final score for "accepted" (0.0-1.0).
        margin_threshold: Minimum lead over the runner-up for "accepted" (0.0-1.0).
        max_returned_candidates: How many ranked candidates to include in the reply.
                                 Clamped to 20; the API always scores them all.
        trace: Include the API round trips in the reply. No secret is ever traced.

    Returns:
        {
          "source": "idref-resolver-api",
          "command": "align_person",
          "status": "accepted" | "ambiguous" | "low_confidence" | "not_found" | null,
          "best_ppn": str | null,          # only when status == "accepted"
          "best_candidate": {              # top of the ranking, even on abstention
            "ppn": str,
            "url": str,
            "score": {"final": float, "name": float, "attrra_source": float,
                      "attrra_note": float, "references": float, "clue_match": float},
            "evidence": {"preferred_forms": [str], "best_attrra_source": str | null,
                         "best_attrra_note": str | null, "best_references": [str]},
            "errors": [str]
          } | null,
          "candidates": [ ... ],           # same shape, ranked, truncated
          "candidates_scored": int,        # how many the API actually scored
          "similarity": {"embedding_model": str, "backend": str} | null,
          "error": str | null,             # unreachable API, 4xx, or upstream degradation
          "trace": [ ... ]                 # only when trace=true
        }

    The tool never raises. An unreachable API, a rejected request (422), a refused
    key (401) and an unservable embedding model (400) all come back with `error`
    set and `status` null, so the failure is readable as data.
    """
    include_trace = trace or TRACE_DEFAULT
    payload: dict[str, Any] = {
        "name": name,
        "works": works or [],
        "field": field,
        "affiliation": affiliation,
        "role": role,
        "year": year,
        "context": context,
        "embedding_model": embedding_model,
        "max_candidates": max(1, min(max_candidates, 100)),
        "accept_threshold": accept_threshold,
        "margin_threshold": margin_threshold,
    }
    result, error, trace_events = await _post_api(
        "/align/person", payload, trace=include_trace
    )

    reply: dict[str, Any] = {
        "source": "idref-resolver-api",
        "command": "align_person",
        "status": None,
        "best_ppn": None,
        "best_candidate": None,
        "candidates": [],
        "candidates_scored": 0,
        "similarity": None,
        "error": error,
    }
    if result is not None:
        ranked = result.get("candidates") or []
        reply.update(
            status=result.get("status"),
            best_ppn=result.get("best_ppn"),
            best_candidate=result.get("best_candidate"),
            candidates=ranked[: max(0, min(max_returned_candidates, 20))],
            candidates_scored=len(ranked),
            similarity=result.get("similarity"),
            error=result.get("error"),
        )
    if include_trace:
        reply["trace"] = trace_events
    return reply


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if args.transport == "stdio":
        # Local launch by a desktop/IDE client that speaks MCP over stdio.
        # host/port are irrelevant in this mode.
        mcp.run(transport="stdio")
    else:
        # stateless_http=True builds a fresh transport per request, so no session
        # is pinned to a replica — required behind a load balancer or several
        # uvicorn workers. Off by default: a single long-lived process is cheaper
        # stateful, and stdio clients never reach this branch.
        mcp.run(
            transport=args.transport,
            host=args.host,
            port=args.port,
            stateless_http=args.stateless,
        )
