#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ['fastmcp>=3.4,<4', 'httpx']
# ///

"""
Dewey classifier MCP server.

Exposes the `humatheque-dewey-classifier-api` service over MCP: rank Dewey
classes against a French doctoral thesis — its title, its subject keywords, its
abstract — by semantic similarity, so a cataloguer or an agent gets a shortlist
to confirm. The vocabulary is the reduced Dewey list French thesis cataloguing
uses in the Sudoc, 98 classes, not the full schedules.

This server is a transport adapter. The taxonomy, the embedding model, the
ranking and the scores all live in the API; nothing is computed here, and no host
but the API is called.

Four ways to run:

  # 1. Zero-install — run directly from GitHub (uv fetches everything)
  uv run https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/dewey-classifier-api/mcp_server.py \
      --transport stdio

  # 2. Local stdio — client launches the process (recommended for desktop/IDE apps)
  uv run /path/to/mcp/dewey-classifier-api/mcp_server.py --transport stdio

  # 3. Local HTTP — run once, connect multiple clients by URL
  uv run /path/to/mcp/dewey-classifier-api/mcp_server.py \
      --host 0.0.0.0 --port 8019 --transport http

  # 4. Stateless HTTP — no session affinity, for load-balanced / multi-replica deploys
  uv run /path/to/mcp/dewey-classifier-api/mcp_server.py --transport http --stateless

Options:
    --api-url       TEXT    API base URL
                            [default: https://dewey-classifier.smartbiblia.fr]
                            (also reads DEWEY_API_URL)
    --host          TEXT    Bind host            [default: 0.0.0.0]
    --port          INT     Bind port            [default: 8019]
    --transport     TEXT    stdio | http | sse   [default: http]
                            ("streamable-http" is accepted as an alias of "http")
    --stateless             Stateless HTTP: a new transport per request, so no
                            session is pinned to a replica. Incompatible with sse.
    --http-timeout  FLOAT   Request timeout (s)  [default: 120.0]
    --max-retries   INT     Retry attempts       [default: 2]
    --backoff-base  FLOAT   Backoff base (s)     [default: 1.0]
    --backoff-factor FLOAT  Backoff multiplier   [default: 2.0]
    --jitter-max    FLOAT   Max retry jitter (s) [default: 0.25]
    --trace                 Include API trace in tool responses

The credential is read from DEWEY_API_KEY and sent as `X-API-Key`. It is never a
tool argument, never logged, and never echoed into a payload or a trace event.
The public deployment currently runs without a key.

Domain gotchas:
    The first request against a cold deployment downloads the embedding model and
    builds the taxonomy index; budget tens of seconds. The default timeout is
    120s for that reason. Warm calls answer in well under a second.

    The scores are cosine similarities, not calibrated probabilities. With
    e5-style models they cluster high (~0.7-0.9) even for weak matches, so read
    the ranking and the gap between rank 1 and rank 2 — never the absolute value.
    `local` and `albert` scores are on different scales and must not be compared.

    The taxonomy is the thesis one, and coarse by design: the ten Dewey main
    classes and their tens divisions, plus the finer entries the Sudoc thesis rule
    keeps (004, 020, 060, 070, 090, 796, 944). It holds no `005.13`, because a
    thesis record does not carry one — the service answers with the division-level
    indice and a cataloguer refines from there.

    Any text is accepted and any text gets an answer, but a document that is not a
    thesis is being matched against a list built for theses: read the result as a
    coarse discipline hint rather than as a Dewey number.

    An operator can edit the taxonomy, so `list_dewey_classes` reads it back from
    the live deployment rather than from a list hard-coded here.
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
        description="MCP server for the humatheque-dewey-classifier-api service.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # Deployment plumbing: env defaults so a container is configured without
    # rewriting its entrypoint.
    p.add_argument(
        "--api-url",
        default=os.environ.get("DEWEY_API_URL", "https://dewey-classifier.smartbiblia.fr"),
    )
    p.add_argument("--host",       default=os.environ.get("MCP_HOST", "0.0.0.0"))
    p.add_argument("--port",       type=int, default=int(os.environ.get("MCP_PORT", "8019")))
    p.add_argument("--transport",  default=os.environ.get("MCP_TRANSPORT", "http"),
                   choices=["stdio", "http", "sse", "streamable-http"],
                   help='Transport ("streamable-http" is an alias of "http")')
    p.add_argument("--stateless",  action="store_true",
                   default=os.environ.get("MCP_STATELESS", "").lower() in ("1", "true", "yes"),
                   help="Stateless HTTP: new transport per request, no session affinity")
    # Connector tuning: flags only, never environment variables.
    p.add_argument("--http-timeout",   type=float, default=120.0)
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
API_KEY = os.environ.get("DEWEY_API_KEY", "")

HTTP_TIMEOUT   = max(1.0, args.http_timeout)
MAX_RETRIES    = max(1, args.max_retries)
BACKOFF_BASE   = max(0.0, args.backoff_base)
BACKOFF_FACTOR = max(1.0, args.backoff_factor)
JITTER_MAX     = max(0.0, args.jitter_max)
TRACE_DEFAULT  = args.trace
RETRIED_STATUS = {429, 500, 502, 503, 504}

# Caps applied before the request, so a mistake fails here instead of costing a
# round trip. The API itself bounds neither.
MAX_TEXTS = 50
MAX_TOP_K = 100

# One pooled client for the process. An AsyncClient per call would rebuild the
# connection pool — and replay the TLS handshake — every time.
HTTP = httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True)

# Mirror the API's own closed enums, so a wrong value fails in the client.
ClassificationType = Literal["multi-label", "single-label"]
Method = Literal["local", "albert"]


# ── The one host this server calls ────────────────────────────────────────────

def _backoff(attempt: int) -> float:
    return BACKOFF_BASE * (BACKOFF_FACTOR**attempt) + random.uniform(0.0, JITTER_MAX)


async def _post_api(
    path: str, payload: dict, *, trace: bool
) -> tuple[dict | None, str | None, list[dict]]:
    """
    Call the API. Returns (data, error, trace_events) — never raises.

    The API answers HTTP 200 with a full payload, or a `detail` string with a 4xx;
    it has no partial-success mode. A 4xx comes back here as an `error` string so
    the model reads the failure instead of a protocol exception.
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
    name="dewey-classifier-api",
    instructions=(
        "Assigns Dewey classes to French doctoral theses — their titles, "
        "subject keywords, abstracts — by semantic similarity against the "
        "reduced Dewey list French thesis cataloguing uses in the Sudoc. That "
        "list, 98 classes deep, is the whole vocabulary: no finer indice exists "
        "here, and a text that is not a thesis is still ranked against it. "
        "Multilingual on the input side; the class labels are French. It returns "
        "a ranked shortlist with similarity scores, not a decision: the scores "
        "are cosine similarities that cluster high even for weak matches, so "
        "read the ranking and let a human confirm the indice. Use "
        "`list_dewey_classes` to see which classes the deployment actually holds "
        "before filtering with `codes`."
    ),
)


@mcp.tool
async def classify_text(
    texts: list[str],
    codes: list[str] | None = None,
    top_k: int = 5,
    classification_type: ClassificationType = "multi-label",
    threshold: float = 0.0,
    method: Method = "local",
    trace: bool = False,
) -> dict:
    """
    Rank Dewey classes against one or several theses.

    Use this tool whenever a thesis must be placed in a Dewey class from its
    metadata alone: "à quelle classe Dewey correspond ce titre de thèse",
    "classify this dissertation abstract", "propose un indice pour ces sujets de
    thèse", indexing triage for a batch of new deposits. The input is free text in
    any language — the model is multilingual — and the returned labels are French.

    The candidate classes are the reduced Dewey list French thesis cataloguing
    uses in the Sudoc — 98 entries, the main classes and their tens divisions plus
    a few finer ones — and the service is tuned on thesis metadata. Text that is
    not a thesis is accepted and answered from that same list; say so when you
    report the result, and treat it as a coarse discipline hint.

    Do not use it to look up a known Dewey code's meaning, to search a catalogue,
    or to obtain a precise shelfmark: the answer is a division-level indice, not a
    full call number.

    Domain rules:
      - The scores are cosine similarities, not probabilities. They cluster high
        (~0.7-0.9) even for weak matches, so the signal is the *ranking* and the
        gap between rank 1 and rank 2, never the absolute value. Do not report a
        score as a confidence percentage.
      - Leave `threshold` at 0.0 and control the answer with `top_k`. A cutoff
        tuned on one text does not transfer to another.
      - `local` and `albert` scores live on different scales — the second is a
        cross-encoder relevance, often two orders of magnitude smaller. Never
        compare or merge scores across methods.
      - Pass every text in one call. The service embeds a batch far faster than
        the same texts one at a time.
      - `codes` restricts the candidates. Unknown codes are dropped silently, but
        a list in which nothing is known is a hard 400: check with
        `list_dewey_classes` first.

    Args:
        texts: The texts to classify — thesis titles, subject keywords,
               abstracts. One entry per thesis; at most 50 per call. Results come
               back in the order sent, each echoing its own text.
        codes: Restrict the candidate classes to these Dewey codes, e.g.
               ["940", "944"]. Omit to rank against the whole list. A code that
               is valid in Dewey but absent from thesis practice is not here.
        top_k: Classes to return per text. Ignored when classification_type is
               "single-label". Capped at 100 by this server.
        classification_type: "multi-label" returns up to top_k classes;
                             "single-label" returns the best one only.
        threshold: Drop classes scoring below this (-1.0 to 1.0). Leave at 0.0
                   unless you have calibrated a cutoff for this exact method.
        method: "local" uses the deployment's own bi-encoder and always works.
                "albert" adds an Albert API retrieve-then-rerank pass: usually a
                sharper ranking, slower, and it requires the deployment to hold an
                Albert key.
        trace: Include the API round trips in the reply. No secret is ever traced.

    Returns:
        {
          "source": "dewey-classifier-api",
          "command": "classify_text",
          "pipeline": str | null,        # the API's own "source", e.g. "embedding_classification"
          "method": str | null,
          "model": str | null,           # e.g. "intfloat/multilingual-e5-large"
          "classification_type": str | null,
          "threshold": float | null,
          "count": int,                  # number of TEXTS answered, not of classes
          "results": [                   # one entry per input text, in order
            {
              "text": str,
              "classes": [ {"dewey": str | null, "label": str, "score": float} ]
            }
          ],
          "error": str | null,           # unreachable API, 4xx, or a client-side check
          "trace": [ ... ]               # only when trace=true
        }

    The tool never raises. An unreachable API, a rejected request (422), a refused
    key (401), an unknown method and a `codes` list with nothing known in it (400)
    all come back with `error` set and `results` empty, so the failure is readable
    as data. An empty `classes` array is not a failure: it means `threshold`
    filtered everything.
    """
    include_trace = trace or TRACE_DEFAULT
    reply: dict[str, Any] = {
        "source": "dewey-classifier-api",
        "command": "classify_text",
        "pipeline": None,
        "method": method,
        "model": None,
        "classification_type": classification_type,
        "threshold": threshold,
        "count": 0,
        "results": [],
        "error": None,
    }

    clean = [t.strip() for t in (texts or []) if t and t.strip()]
    if not clean:
        reply["error"] = "no text to classify: `texts` must hold at least one non-empty string"
        if include_trace:
            reply["trace"] = []
        return reply
    if len(clean) > MAX_TEXTS:
        reply["error"] = (
            f"{len(clean)} texts given; this server sends at most {MAX_TEXTS} per call"
        )
        if include_trace:
            reply["trace"] = []
        return reply

    payload: dict[str, Any] = {
        # A single text stays a string, so the API's own echo matches what was sent.
        "text": clean[0] if len(clean) == 1 else clean,
        "codes": codes or None,
        "threshold": threshold,
        "classification_type": classification_type,
        "top_k": max(1, min(top_k, MAX_TOP_K)),
        "method": method,
    }
    result, error, trace_events = await _post_api("/classify", payload, trace=include_trace)

    reply["error"] = error
    if result is not None:
        reply.update(
            pipeline=result.get("source"),
            method=result.get("method", method),
            model=result.get("model"),
            classification_type=result.get("classification_type", classification_type),
            threshold=result.get("threshold", threshold),
            count=result.get("count", 0),
            results=result.get("results") or [],
        )
    if include_trace:
        reply["trace"] = trace_events
    return reply


@mcp.tool
async def list_dewey_classes(trace: bool = False) -> dict:
    """
    List every Dewey class the deployment can actually assign.

    Use this before filtering `classify_text` with `codes`, or whenever the user
    asks what the classifier knows: "quelles classes Dewey sont disponibles",
    "does it have a class for sport", "can it go finer than 940". What comes back
    is the reduced Dewey list French thesis cataloguing uses in the Sudoc, as the
    operator's own file holds it — a property of the deployment and of thesis
    practice, not of Dewey.

    The service has no listing endpoint. This tool asks `/classify` for the full
    ranking of a throwaway text, which returns every class exactly once — so the
    `score` values in the reply are meaningless artefacts of that placeholder and
    are dropped. Only the codes and the labels are returned.

    Args:
        trace: Include the API round trip in the reply. No secret is ever traced.

    Returns:
        {
          "source": "dewey-classifier-api",
          "command": "list_dewey_classes",
          "count": int,
          "classes": [ {"dewey": str | null, "label": str} ],   # sorted by code
          "error": str | null,
          "trace": [ ... ]                                      # only when trace=true
        }

    Codes are three characters, zero-padded ("004", "944"), and labels are French.
    """
    include_trace = trace or TRACE_DEFAULT
    reply: dict[str, Any] = {
        "source": "dewey-classifier-api",
        "command": "list_dewey_classes",
        "count": 0,
        "classes": [],
        "error": None,
    }
    payload = {
        "text": "taxonomy",
        "threshold": -1.0,
        "classification_type": "multi-label",
        # `top_k` is unbounded server-side, so asking for far more than the
        # taxonomy holds simply returns all of it.
        "top_k": 10000,
        "method": "local",
    }
    result, error, trace_events = await _post_api("/classify", payload, trace=include_trace)

    reply["error"] = error
    if result is not None:
        entries = (result.get("results") or [{}])[0].get("classes") or []
        # The scores rank the placeholder text and mean nothing here; drop them.
        reply["classes"] = sorted(
            ({"dewey": c.get("dewey"), "label": c.get("label")} for c in entries),
            key=lambda c: c["dewey"] or "",
        )
        reply["count"] = len(reply["classes"])
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
