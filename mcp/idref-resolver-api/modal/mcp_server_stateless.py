"""IdRef resolver MCP server — Modal deployment.

A **standalone duplicate** of the canonical server, `../mcp_server.py`, built on
the shape of Modal's own FastMCP example: nothing is mounted into the image and
nothing is imported from the parent folder. Everything the server needs is
defined inside `make_mcp_server()`, including its runtime imports — Modal loads
this file on the local machine to build the app, where `fastmcp` and `httpx` are
not installed, so a top-level import of either would break `modal deploy`.

The tools below are a **hand-kept copy** of the canonical ones — same names, same
arguments, same envelope. Change one, change the other.

Tools served: `align_person`.

  # Ephemeral deployment that reloads on save
  uvx modal serve mcp/idref-resolver-api/modal/mcp_server_stateless.py

  # List the deployed tools (and optionally call one)
  uvx modal run mcp/idref-resolver-api/modal/mcp_server_stateless.py::test_tool

  # Persistent deployment
  uvx modal deploy mcp/idref-resolver-api/modal/mcp_server_stateless.py

The MCP endpoint is the printed URL with `/mcp/` appended:

    https://<workspace>--smartbiblia-mcp-idref-resolver-api-web.modal.run/mcp/

Modal load-balances one URL across containers that come and go, so the transport
is built **stateless** (`stateless_http=True`): a new transport per request, no
session pinned to a replica — the same mode as
`mcp_server.py --transport http --stateless`. A stateless response carries no
`mcp-session-id` header, which is how to check the mode of a running server.

Environment: IDREF_API_URL — required here; its `http://localhost:8000` default
resolves to nothing inside a Modal container. IDREF_API_KEY — optional, sent as
`X-API-Key` when the API enforces one.
"""

import modal

APP_NAME = "smartbiblia-mcp-idref-resolver-api"

image = modal.Image.debian_slim(python_version="3.12").uv_pip_install(
    "fastapi>=0.115",
    "fastmcp>=3.4,<4",  # keep in step with the pin in ../mcp_server.py
    "httpx",
)

app = modal.App(APP_NAME, image=image)

# Required configuration. Create the Secret before deploying:
#     modal secret create smartbiblia-idref-resolver-api IDREF_API_URL=...
# `required_keys` turns a missing key into a deploy-time error naming it,
# instead of a container that crashes on its first request.
SECRETS: list[modal.Secret] = [
    modal.Secret.from_name(
        "smartbiblia-idref-resolver-api",
        required_keys=["IDREF_API_URL"],
    )
]


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
    from typing import Any, Literal

    import httpx
    from fastmcp import FastMCP

    # ── Config (sourced from CLI args only) ───────────────────────────────────────

    API_BASE_URL = os.environ.get("IDREF_API_URL", "http://localhost:8000").rstrip("/")
    # The credential is read from the environment only: never a tool argument, never
    # echoed into a payload or a trace event.
    API_KEY = os.environ.get("IDREF_API_KEY", "")

    HTTP_TIMEOUT   = 180.0
    MAX_RETRIES    = 2
    BACKOFF_BASE   = 1.0
    BACKOFF_FACTOR = 2.0
    JITTER_MAX     = 0.25
    TRACE_DEFAULT  = False
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

    return mcp


@app.function(secrets=SECRETS, timeout=600)
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

        uvx modal run mcp/idref-resolver-api/modal/mcp_server_stateless.py::test_tool

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
