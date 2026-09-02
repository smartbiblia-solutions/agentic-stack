"""Dewey classifier MCP server — Modal deployment.

A **standalone duplicate** of the canonical server, `../mcp_server.py`, built on
the shape of Modal's own FastMCP example: nothing is mounted into the image and
nothing is imported from the parent folder. Everything the server needs is
defined inside `make_mcp_server()`, including its runtime imports — Modal loads
this file on the local machine to build the app, where `fastmcp` and `httpx` are
not installed, so a top-level import of either would break `modal deploy`.

The tools below are a **hand-kept copy** of the canonical ones — same names, same
arguments, same envelope. Change one, change the other.

Tools served: `classify_text`, `list_dewey_classes`.

The service classifies French doctoral theses against the reduced Dewey list
thesis cataloguing uses in the Sudoc — 98 classes, no finer indice. Any text is
answered from that same list.

  # Ephemeral deployment that reloads on save
  uvx modal serve mcp/dewey-classifier-api/modal/mcp_server_stateless.py

  # List the deployed tools (and optionally call one)
  uvx modal run mcp/dewey-classifier-api/modal/mcp_server_stateless.py::test_tool

  # Persistent deployment
  uvx modal deploy mcp/dewey-classifier-api/modal/mcp_server_stateless.py

The MCP endpoint is the printed URL with `/mcp/` appended:

    https://<workspace>--smartbiblia-mcp-dewey-classifier-api-web.modal.run/mcp/

Modal load-balances one URL across containers that come and go, so the transport
is built **stateless** (`stateless_http=True`): a new transport per request, no
session pinned to a replica — the same mode as
`mcp_server.py --transport http --stateless`. A stateless response carries no
`mcp-session-id` header, which is how to check the mode of a running server.

Environment: DEWEY_API_URL — where the classifier runs; defaults to the public
SmartBibl.IA deployment, so a Secret holding only that default is enough to start.
DEWEY_API_KEY — optional, sent as `X-API-Key` when the API enforces one.

Note that this deployment is a proxy: the classification itself still happens in
the Dewey API, and the first call against a cold classifier takes tens of seconds
while it loads its embedding model. The Modal function timeout is set accordingly.
"""

import modal

APP_NAME = "smartbiblia-mcp-dewey-classifier-api"

image = modal.Image.debian_slim(python_version="3.12").uv_pip_install(
    "fastapi>=0.115",
    "fastmcp>=3.4,<4",  # keep in step with the pin in ../mcp_server.py
    "httpx",
)

app = modal.App(APP_NAME, image=image)

# Required configuration. Create the Secret before deploying:
#     modal secret create smartbiblia-dewey-classifier-api \
#         DEWEY_API_URL=https://dewey-classifier.smartbiblia.fr
# `required_keys` turns a missing key into a deploy-time error naming it,
# instead of a container that crashes on its first request.
SECRETS: list[modal.Secret] = [
    modal.Secret.from_name(
        "smartbiblia-dewey-classifier-api",
        required_keys=["DEWEY_API_URL"],
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

    API_BASE_URL = os.environ.get(
        "DEWEY_API_URL", "https://dewey-classifier.smartbiblia.fr"
    ).rstrip("/")
    # The credential is read from the environment only: never a tool argument,
    # never echoed into a payload or a trace event.
    API_KEY = os.environ.get("DEWEY_API_KEY", "")

    # The canonical server's flag defaults, frozen as constants.
    HTTP_TIMEOUT = 120.0
    MAX_RETRIES = 2
    BACKOFF_BASE = 1.0
    BACKOFF_FACTOR = 2.0
    JITTER_MAX = 0.25
    TRACE_DEFAULT = False
    RETRIED_STATUS = {429, 500, 502, 503, 504}

    # Caps applied before the request, so a mistake fails here instead of costing
    # a round trip. The API itself bounds neither.
    MAX_TEXTS = 50
    MAX_TOP_K = 100

    HTTP = httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True)

    # Mirror the API's own closed enums, so a wrong value fails in the client.
    ClassificationType = Literal["multi-label", "single-label"]
    Method = Literal["local", "albert"]

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

    # ── MCP app ───────────────────────────────────────────────────────────────

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


@app.function(secrets=SECRETS, timeout=600)
async def test_tool(tool_name: str | None = None, arguments: str | None = None):
    """List the tools this deployment serves, and optionally call one.

        uvx modal run mcp/dewey-classifier-api/modal/mcp_server_stateless.py::test_tool
        uvx modal run mcp/dewey-classifier-api/modal/mcp_server_stateless.py::test_tool \
            --tool-name classify_text \
            --arguments '{"texts": ["Histoire du livre au XVIIIe siecle"], "top_k": 3}'

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
