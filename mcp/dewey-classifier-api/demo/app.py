#!/usr/bin/env python3
"""
Standalone Gradio demo of the Dewey classifier MCP server, deployable as
a Hugging Face Space.

Like the server, this app is a transport adapter: the taxonomy, the model, the
ranking and the scores all come from the API, and no host but the API is called.
Unlike the server, a missing or unreachable API does not stop the process — the
call comes back with `error` set and `results` empty.

Local run:
    uv run --with 'gradio[mcp]>=6,<7' --with httpx app.py

Environment:
    DEWEY_API_URL        API base URL (default https://dewey-classifier.smartbiblia.fr)
    DEWEY_API_KEY        sent as X-API-Key; never a tool argument, never echoed back
    GRADIO_SERVER_NAME   bind address (default 0.0.0.0)
    GRADIO_SERVER_PORT   port (default 7860)
    GRADIO_MCP_SERVER    "false" disables the demo MCP endpoint (default true)
"""

from __future__ import annotations

import os
from typing import Any

import gradio as gr
import httpx

# ── Configuration ─────────────────────────────────────────────────────────────

API_BASE_URL = os.environ.get(
    "DEWEY_API_URL", "https://dewey-classifier.smartbiblia.fr"
).rstrip("/")

# The credential is read from the environment only: never a tool argument, never
# echoed into a payload.
API_KEY = os.environ.get("DEWEY_API_KEY", "")

# A Space has no command line: connector policy is constant here. The first call
# against a cold classifier loads its embedding model, hence the generous budget.
REQUEST_TIMEOUT = 120.0

# Clamped harder than the canonical server (which allows 50 texts and top_k 100):
# this endpoint is public and every call spends the operator's classifier capacity.
MAX_TEXTS = 10
MAX_TOP_K = 20

# The API's own closed enums. Gradio builds the MCP schema from the annotations,
# so these stay plain `str` in the signatures and are validated inside the
# function: a bad value belongs in `error`, not in a transport failure.
CLASSIFICATION_TYPES = ("multi-label", "single-label")
METHODS = ("local", "albert")

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


def classify_text(
    texts: list[str],
    codes: list[str] | None = None,
    top_k: int = 5,
    classification_type: str = "multi-label",
    threshold: float = 0.0,
    method: str = "local",
) -> dict:
    """
    Rank Dewey classes against one or several theses.

    The candidate classes are the reduced Dewey list French thesis cataloguing
    uses in the Sudoc — 98 entries, main classes and tens divisions plus a few
    finer ones — so the answer is a division-level indice, not a full call number.
    Text that is not a thesis is accepted and answered from that same list; read
    it as a coarse discipline hint.

    The scores are cosine similarities, not probabilities: they cluster high
    (~0.7-0.9) even for weak matches, so the signal is the ranking and the gap
    between rank 1 and rank 2, never the absolute value. `local` and `albert`
    scores live on different scales and must not be compared.

    Args:
        texts: The texts to classify — thesis titles, subject keywords, abstracts. One entry per thesis, at most 10 on this demo endpoint. Results come back in the order sent.
        codes: Restrict the candidate classes to these Dewey codes, e.g. ["940", "944"]. Omit to rank against the whole list; a code absent from thesis practice is not in it, and a list with no known code is an error.
        top_k: Classes to return per text, 1-20 on this demo endpoint. Ignored when classification_type is "single-label".
        classification_type: "multi-label" returns up to top_k classes, "single-label" the best one only.
        threshold: Drop classes scoring below this (-1.0 to 1.0). Leave at 0.0 unless you have calibrated a cutoff for this exact method.
        method: "local" uses the deployment's own bi-encoder and always works. "albert" adds an Albert API rerank: usually sharper, slower, and it needs the deployment to hold an Albert key.

    Returns:
        {"source": "dewey-classifier-api", "command": "classify_text", "pipeline": str | null, "method": str | null, "model": str | null, "classification_type": str | null, "threshold": float | null, "count": int, "results": [{"text": str, "classes": [{"dewey": str | null, "label": str, "score": float}]}], "error": str | null}
    """
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
        reply["error"] = "texts must hold at least one non-empty string"
        return reply
    if len(clean) > MAX_TEXTS:
        reply["error"] = (
            f"{len(clean)} texts given; this demo endpoint sends at most {MAX_TEXTS} per call"
        )
        return reply
    if classification_type not in CLASSIFICATION_TYPES:
        reply["error"] = "classification_type must be one of " + ", ".join(CLASSIFICATION_TYPES)
        return reply
    if method not in METHODS:
        reply["error"] = "method must be one of " + ", ".join(METHODS)
        return reply

    payload = {
        # A single text stays a string, so the API's own echo matches what was sent.
        "text": clean[0] if len(clean) == 1 else clean,
        "codes": [c.strip() for c in (codes or []) if c and c.strip()] or None,
        "threshold": float(threshold),
        "classification_type": classification_type,
        "top_k": max(1, min(int(top_k or 5), MAX_TOP_K)),
        "method": method,
    }

    result, error = _post("/classify", payload)
    if error:
        reply["error"] = error
        return reply

    reply.update(
        pipeline=result.get("source"),
        method=result.get("method", method),
        model=result.get("model"),
        classification_type=result.get("classification_type", classification_type),
        threshold=result.get("threshold", threshold),
        count=result.get("count", 0),
        results=result.get("results") or [],
    )
    return reply


def list_dewey_classes() -> dict:
    """
    List every Dewey class this deployment can actually assign.

    What comes back is the reduced Dewey list French thesis cataloguing uses in
    the Sudoc, as the operator's own file holds it — a property of the deployment
    and of thesis practice, not of Dewey. The service has no listing endpoint: this asks
    `/classify` for the full ranking of a throwaway text, which returns every class
    exactly once. The scores of that placeholder are meaningless and are dropped.

    Returns:
        {"source": "dewey-classifier-api", "command": "list_dewey_classes", "count": int, "classes": [{"dewey": str | null, "label": str}], "error": str | null}
    """
    reply: dict[str, Any] = {
        "source": "dewey-classifier-api",
        "command": "list_dewey_classes",
        "count": 0,
        "classes": [],
        "error": None,
    }
    result, error = _post(
        "/classify",
        {
            "text": "taxonomy",
            "threshold": -1.0,
            "classification_type": "multi-label",
            # `top_k` is unbounded server-side, so asking for far more than the
            # taxonomy holds simply returns all of it.
            "top_k": 10000,
            "method": "local",
        },
    )
    if error:
        reply["error"] = error
        return reply

    entries = (result.get("results") or [{}])[0].get("classes") or []
    reply["classes"] = sorted(
        ({"dewey": c.get("dewey"), "label": c.get("label")} for c in entries),
        key=lambda c: c["dewey"] or "",
    )
    reply["count"] = len(reply["classes"])
    return reply


# ── Presentation ──────────────────────────────────────────────────────────────


def _render(payload: dict) -> str:
    lines: list[str] = []
    if payload.get("error"):
        lines.append(f"> ⚠️ {payload['error']}\n")
    model = payload.get("model")
    if model:
        lines.append(
            f"**{payload.get('count', 0)} texte(s)** — `{payload.get('method')}` · `{model}`\n"
        )

    for entry in payload.get("results") or []:
        text = (entry.get("text") or "").replace("|", "\\|")
        lines += [f"### {text}", "", "| Indice | Libellé | Score |", "|---|---|---|"]
        classes = entry.get("classes") or []
        if not classes:
            lines.append("| — | _aucune classe au-dessus du seuil_ | — |")
        for cls in classes:
            score = cls.get("score")
            score_txt = f"{score:.4f}" if isinstance(score, (int, float)) else "—"
            label = (cls.get("label") or "—").replace("|", "\\|")
            lines.append(f"| `{cls.get('dewey') or '—'}` | {label} | {score_txt} |")
        lines.append("")

    if payload.get("results"):
        lines.append(
            "_Les scores sont des similarités cosinus, pas des probabilités : ils "
            "restent élevés même pour un rapprochement faible. Lisez le classement "
            "et l'écart entre le 1er et le 2e, jamais la valeur absolue._"
        )
    return "\n".join(lines)


def _run(texts_block, codes_text, top_k, classification_type, threshold, method):
    texts = [line.strip() for line in (texts_block or "").splitlines() if line.strip()]
    codes = [c.strip() for c in (codes_text or "").replace(",", " ").split() if c.strip()]
    payload = classify_text(
        texts=texts,
        codes=codes,
        top_k=top_k,
        classification_type=classification_type,
        threshold=threshold,
        method=method,
    )
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render(payload), payload


def _list() -> tuple[str, dict]:
    payload = list_dewey_classes()
    if payload.get("error"):
        raise gr.Error(payload["error"])
    lines = [f"**{payload['count']} classes servies par ce déploiement**", "", "| Indice | Libellé |", "|---|---|"]
    lines += [
        f"| `{c['dewey'] or '—'}` | {(c['label'] or '—').replace('|', chr(92) + '|')} |"
        for c in payload["classes"]
    ]
    return "\n".join(lines), payload


# ── UI ────────────────────────────────────────────────────────────────────────

with gr.Blocks(title="Dewey classifier MCP demo") as demo:
    gr.Markdown(
        "# Classification Dewey des thèses — démo MCP\n"
        "Démo autonome du serveur MCP "
        "[`dewey-classifier-api`](https://github.com/smartbiblia-solutions/agentic-stack/tree/main/mcp/dewey-classifier-api) : "
        "proposer un indice Dewey pour une thèse — son titre, ses mots-clés, son "
        "résumé — par similarité sémantique. Le vocabulaire est la liste Dewey "
        "réduite utilisée pour le catalogage des thèses dans le Sudoc (98 classes) : "
        "un autre type de document reçoit quand même une réponse, mais prise dans "
        "cette liste-là. Le résultat est un classement à confirmer, pas une cote."
    )

    with gr.Tab("Classer"):
        with gr.Row():
            with gr.Column():
                texts_block = gr.Textbox(
                    label="Sujets de thèse à classer (un par ligne)",
                    lines=5,
                    placeholder="Histoire politique de Buenos Aires au XIXe siècle",
                )
                with gr.Row():
                    method = gr.Radio(list(METHODS), value="local", label="Méthode")
                    classification_type = gr.Radio(
                        list(CLASSIFICATION_TYPES), value="multi-label", label="Type"
                    )
                top_k = gr.Slider(1, MAX_TOP_K, value=5, step=1, label="Classes par texte")
                with gr.Accordion("Restreindre / filtrer", open=False):
                    codes_text = gr.Textbox(
                        label="Indices candidats (séparés par des espaces)",
                        placeholder="940 944 950",
                    )
                    threshold = gr.Slider(
                        -1.0, 1.0, value=0.0, step=0.01, label="Seuil de score"
                    )
                classify_btn = gr.Button("Classer", variant="primary")
            with gr.Column():
                table_out = gr.Markdown()
                raw_out = gr.JSON(label="Sortie brute de l'outil")

        inputs = [texts_block, codes_text, top_k, classification_type, threshold, method]

        gr.Examples(
            examples=[
                ["Histoire politique de Buenos Aires au XIXe siècle", "", 5,
                 "multi-label", 0.0, "local"],
                ["Les manuscrits enluminés de la Bibliothèque nationale\n"
                 "Deep learning for protein structure prediction\n"
                 "Politique monétaire et inflation dans la zone euro", "", 3,
                 "multi-label", 0.0, "local"],
                ["Le catharisme en Languedoc au XIIIe siècle", "", 1,
                 "single-label", 0.0, "local"],
                ["La Résistance dans le Vercors, 1943-1944", "930 940 944 950", 3,
                 "multi-label", 0.0, "local"],
                ["Grammaire comparée des langues romanes", "", 5,
                 "multi-label", 0.0, "albert"],
            ],
            inputs=inputs,
            label="Un sujet, un lot de trois sujets, une classe unique, un choix "
                  "restreint à quatre indices, puis le rerank Albert",
        )
        classify_btn.click(_run, inputs=inputs, outputs=[table_out, raw_out], api_name=False)

    with gr.Tab("Taxonomie"):
        gr.Markdown(
            "Les classes que ce déploiement peut réellement attribuer : la liste "
            "Dewey réduite du catalogage des thèses dans le Sudoc, telle que "
            "l'exploitant la sert — pas la Dewey complète."
        )
        list_btn = gr.Button("Lister les classes", variant="primary")
        classes_out = gr.Markdown()
        classes_raw = gr.JSON(label="Sortie brute de l'outil")
        list_btn.click(_list, inputs=None, outputs=[classes_out, classes_raw], api_name=False)

    # The only declared MCP tools. The names match the canonical server's.
    gr.api(classify_text, api_name="classify_text")
    gr.api(list_dewey_classes, api_name="list_dewey_classes")


if __name__ == "__main__":
    demo.launch(
        theme=gr.themes.Soft(),  # Gradio 6 moved theme from Blocks() to launch()
        server_name=os.getenv("GRADIO_SERVER_NAME", "0.0.0.0"),
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
        mcp_server=os.getenv("GRADIO_MCP_SERVER", "true").lower() == "true",
    )
