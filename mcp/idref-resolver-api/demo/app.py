#!/usr/bin/env python3
"""
Standalone Gradio demo of the IdRef resolver MCP server, deployable as
a Hugging Face Space.

Like the server, this app is a transport adapter: every score, threshold and
status comes from the API, and no host but the API is called. Unlike the server,
a missing or unreachable API does not stop the process — the call comes back with
`error` set and `status` null.

Local run:
    uv run --with 'gradio[mcp]>=6,<7' --with httpx app.py

Environment:
    IDREF_API_URL        API base URL (default http://localhost:8000)
    IDREF_API_KEY        sent as X-API-Key; never a tool argument, never echoed back
    GRADIO_SERVER_NAME   bind address (default 0.0.0.0)
    GRADIO_SERVER_PORT   port (default 7860)
    GRADIO_MCP_SERVER    "false" disables the demo MCP endpoint (default true)
"""

from __future__ import annotations

import os
from typing import Any, Literal

import gradio as gr
import httpx

# ── Configuration ─────────────────────────────────────────────────────────────

API_BASE_URL = os.environ.get("IDREF_API_URL", "http://localhost:8000").rstrip("/")

# The credential is read from the environment only: never a tool argument, never
# echoed into a payload.
API_KEY = os.environ.get("IDREF_API_KEY", "")

# A Space has no command line: connector policy is constant here. An alignment
# fans out to as many as 41 upstream ABES requests, so the budget is generous.
REQUEST_TIMEOUT = 180.0

# Clamped harder than the canonical server (which allows 100 / 20): this endpoint
# is public and every call spends the operator's API budget.
MAX_CANDIDATES = 30
MAX_RETURNED = 10

# Mirrors the API's `EmbeddingModel` Literal. A closed enum there is a closed
# enum here, so a wrong value fails in the client instead of costing a round trip.
EMBEDDING_MODELS = (
    "lexical", "lexical-idf", "albert-bge-m3", "granite", "qwen", "minilm",
)
EmbeddingModel = Literal[
    "lexical", "lexical-idf", "albert-bge-m3", "granite", "qwen", "minilm"
]

# One module-level pooled client for the process.
HTTP = httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True)


def _post(path: str, payload: dict) -> tuple[dict | None, str | None]:
    """POST returning (data, error). Never raises — the demo answers with data."""
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    try:
        resp = HTTP.post(f"{API_BASE_URL}{path}", json=payload, headers=headers)
    except httpx.TimeoutException:
        return None, f"the API did not answer within {REQUEST_TIMEOUT:g}s"
    except httpx.HTTPError as exc:
        return None, f"cannot reach the API at {API_BASE_URL}: {exc}"
    if resp.status_code >= 400:
        # Surface the API's own detail; never echo the key back.
        return None, f"API {resp.status_code}: {resp.text[:300]}"
    try:
        return resp.json(), None
    except ValueError:
        return None, f"API returned a non-JSON body: {resp.text[:200]}"


# ── MCP tools (the only functions exposed with gr.api) ────────────────────────


def align_person(
    name: str,
    works: list[str] | None = None,
    field: str = "",
    affiliation: str = "",
    year: str = "",
    context: str = "",
    embedding_model: EmbeddingModel = "lexical-idf",
    max_candidates: int = 20,
    accept_threshold: float = 0.65,
    margin_threshold: float = 0.08,
    max_returned_candidates: int = 5,
) -> dict:
    """
    Align a person to an IdRef PPN from their name plus any disambiguating context.

    `best_ppn` is populated only when `status == "accepted"`. On any other status the
    alignment abstained: report the abstention, do not fall back to the top candidate's
    PPN. Raising a threshold makes the service stricter, i.e. more abstentions.

    Args:
        name: Full person name, e.g. "Valérie Robert". Required.
        works: Titles of documents the person is linked to. Often decisive.
        field: Discipline or subject area, e.g. "sociologie des sciences".
        affiliation: Institution, laboratory or place, e.g. "Université de Nancy".
        year: A relevant year as a string, e.g. "2003".
        context: Any other free text — a biographical note, an abstract.
        embedding_model: How texts are compared — lexical, lexical-idf, albert-bge-m3, granite, qwen or minilm.
        max_candidates: Candidate authorities to enrich and score, 1-30 on this demo endpoint.
        accept_threshold: Minimum final score for "accepted" (0.0-1.0).
        margin_threshold: Minimum lead over the runner-up for "accepted" (0.0-1.0).
        max_returned_candidates: Ranked candidates to include in the reply, 0-10 on this demo endpoint.

    Returns:
        {"source": "idref-resolver-api", "command": "align_person", "status": "accepted" | "ambiguous" | "low_confidence" | "not_found" | null, "best_ppn": str | null, "best_candidate": object | null, "candidates": [object], "candidates_scored": int, "similarity": object | null, "error": str | null}
    """
    reply: dict[str, Any] = {
        "source": "idref-resolver-api",
        "command": "align_person",
        "status": None,
        "best_ppn": None,
        "best_candidate": None,
        "candidates": [],
        "candidates_scored": 0,
        "similarity": None,
        "error": None,
    }

    if not (name or "").strip():
        reply["error"] = "name is required"
        return reply
    if embedding_model not in EMBEDDING_MODELS:
        reply["error"] = "embedding_model must be one of " + ", ".join(EMBEDDING_MODELS)
        return reply

    payload = {
        "name": name.strip(),
        "works": [w for w in (works or []) if w],
        "field": field or "",
        "affiliation": affiliation or "",
        "role": "",
        "year": str(year or ""),
        "context": context or "",
        "embedding_model": embedding_model,
        "max_candidates": max(1, min(int(max_candidates or 20), MAX_CANDIDATES)),
        "accept_threshold": float(accept_threshold),
        "margin_threshold": float(margin_threshold),
    }

    result, error = _post("/align/person", payload)
    if error:
        reply["error"] = error
        return reply

    ranked = result.get("candidates") or []
    reply.update(
        status=result.get("status"),
        best_ppn=result.get("best_ppn"),
        best_candidate=result.get("best_candidate"),
        candidates=ranked[: max(0, min(int(max_returned_candidates or 5), MAX_RETURNED))],
        candidates_scored=len(ranked),
        similarity=result.get("similarity"),
        error=result.get("error"),
    )
    return reply


# ── Presentation ──────────────────────────────────────────────────────────────

VERDICTS = {
    "accepted": "✅ **Accepté** — un PPN est retenu.",
    "ambiguous": "🤔 **Ambigu** — plusieurs autorités se tiennent ; l'outil s'abstient.",
    "low_confidence": "⚠️ **Confiance insuffisante** — le meilleur score reste sous le seuil.",
    "not_found": "❌ **Aucune autorité candidate** pour ce nom.",
}


def _render(payload: dict) -> str:
    lines: list[str] = []
    status = payload.get("status")
    lines.append(VERDICTS.get(status, f"**Statut** — `{status}`"))
    if payload.get("best_ppn"):
        ppn = payload["best_ppn"]
        lines.append(f"\n**PPN retenu** — [{ppn}](https://www.idref.fr/{ppn})")
    elif status:
        lines.append(
            "\n_Abstention : ne retenez pas le premier candidat comme s'il avait "
            "été accepté. Une abstention est une réponse._"
        )
    if payload.get("error"):
        lines.append(f"\n> ⚠️ {payload['error']}")

    candidates = payload.get("candidates") or []
    if candidates:
        lines += [
            "",
            f"**{len(candidates)} candidats affichés sur {payload.get('candidates_scored', '?')} évalués**",
            "",
            "| PPN | Score final | Forme retenue |",
            "|---|---|---|",
        ]
        for c in candidates:
            ppn = c.get("ppn") or "—"
            score = ((c.get("score") or {}).get("final"))
            score_txt = f"{score:.3f}" if isinstance(score, (int, float)) else "—"
            forms = ((c.get("evidence") or {}).get("preferred_forms") or [])
            form = (forms[0] if forms else "—").replace("|", "\\|")
            link = f"[{ppn}](https://www.idref.fr/{ppn})" if ppn != "—" else "—"
            lines.append(f"| {link} | {score_txt} | {form} |")
    return "\n".join(lines)


def _run(name, works_text, field, affiliation, year, context,
         embedding_model, max_candidates, accept_threshold, margin_threshold):
    works = [line.strip() for line in (works_text or "").splitlines() if line.strip()]
    payload = align_person(
        name=name,
        works=works,
        field=field,
        affiliation=affiliation,
        year=year,
        context=context,
        embedding_model=embedding_model,
        max_candidates=max_candidates,
        accept_threshold=accept_threshold,
        margin_threshold=margin_threshold,
    )
    if payload.get("error") and payload.get("status") is None:
        raise gr.Error(payload["error"])
    return _render(payload), payload


# ── UI ────────────────────────────────────────────────────────────────────────

with gr.Blocks(title="IdRef resolver MCP demo") as demo:
    gr.Markdown(
        "# IdRef resolver — démo MCP\n"
        "Démo autonome du serveur MCP "
        "[`idref-resolver-api`](https://github.com/smartbiblia-solutions/agentic-stack/tree/main/mcp/idref-resolver-api) "
        ", aligner une autoritéé personne extraite d'un document sur son PPN IdRef, ou "
        "s'abstenir quand l'indice est trop faible. "
    )

    with gr.Row():
        with gr.Column():
            name = gr.Textbox(label="Nom de la personne", placeholder="Valérie Robert")
            works_text = gr.Textbox(
                label="Titres d'œuvres (un par ligne)",
                lines=3,
                placeholder="Nous n'avons jamais été modernes",
            )
            field = gr.Textbox(label="Domaine", placeholder="sociologie des sciences")
            affiliation = gr.Textbox(label="Affiliation", placeholder="Université de Nancy")
            with gr.Row():
                year = gr.Textbox(label="Année", placeholder="2003")
                embedding_model = gr.Dropdown(
                    list(EMBEDDING_MODELS), value="lexical-idf", label="Comparaison"
                )
            context = gr.Textbox(label="Contexte libre", lines=2)
            with gr.Accordion("Seuils", open=False):
                max_candidates = gr.Slider(
                    1, MAX_CANDIDATES, value=20, step=1, label="Candidats évalués"
                )
                accept_threshold = gr.Slider(
                    0.0, 1.0, value=0.65, step=0.01, label="Seuil d'acceptation"
                )
                margin_threshold = gr.Slider(
                    0.0, 1.0, value=0.08, step=0.01, label="Écart minimal au second"
                )
            align_btn = gr.Button("Aligner", variant="primary")
        with gr.Column():
            verdict_out = gr.Markdown()
            raw_out = gr.JSON(label="Sortie brute de l'outil")

    inputs = [name, works_text, field, affiliation, year, context,
              embedding_model, max_candidates, accept_threshold, margin_threshold]

    gr.Examples(
        examples=[
            ["Bruno Latour", "Nous n'avons jamais été modernes", "sociologie des sciences",
             "Sciences Po", "1991", "", "lexical-idf", 20, 0.65, 0.08],
            ["Jean Dupont", "", "", "", "", "", "lexical-idf", 20, 0.65, 0.08],
        ],
        inputs=inputs,
        label="Un cas qui aboutit, et un homonyme où l'outil s'abstient",
    )
    align_btn.click(_run, inputs=inputs, outputs=[verdict_out, raw_out], api_name=False)

    # The only declared MCP tool. The name matches the canonical server's.
    gr.api(align_person, api_name="align_person")


if __name__ == "__main__":
    demo.launch(
        theme=gr.themes.Soft(),  # Gradio 6 moved theme from Blocks() to launch()
        server_name=os.getenv("GRADIO_SERVER_NAME", "0.0.0.0"),
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
        mcp_server=os.getenv("GRADIO_MCP_SERVER", "true").lower() == "true",
    )
