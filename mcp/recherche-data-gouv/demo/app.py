#!/usr/bin/env python3
"""
Standalone Gradio demo of the Recherche Data Gouv MCP server, deployable as a
Hugging Face Space.

Local run:
    uv run --with 'gradio[mcp]>=6,<7' --with httpx app.py

Environment:
    RECHERCHE_DATA_GOUV_API_URL   API base URL (default the public entrepôt)
    GRADIO_SERVER_NAME            bind address (default 0.0.0.0)
    GRADIO_SERVER_PORT            port (default 7860)
    GRADIO_MCP_SERVER             "false" disables the demo MCP endpoint (default true)
"""

from __future__ import annotations

import os
from typing import Any

import gradio as gr
import httpx

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_URL = os.environ.get(
    "RECHERCHE_DATA_GOUV_API_URL",
    "https://entrepot.recherche.data.gouv.fr/api",
).rstrip("/")

USER_AGENT = "smartbiblia-recherche-data-gouv-demo/0.1"

SEARCH_TYPES = ("dataset", "dataverse", "file")

METRIC_CATEGORIES = (
    "dataverses", "datasets", "files", "downloads",
    "filedownloads", "uniquedownloads", "uniquefiledownloads", "tree",
)

# `pastDays` and `toMonth` need a companion `value` in the path; the demo keeps
# the breakdowns that stand on their own.
METRIC_BREAKDOWNS = ("monthly", "byCategory", "bySubject", "byType")

# A Space has no command line: connector policy is constant here.
REQUEST_TIMEOUT = 20.0

# Clamped harder than the canonical server: this endpoint is public.
MAX_RESULTS = 10

# One module-level pooled client for the process.
HTTP = httpx.Client(
    timeout=REQUEST_TIMEOUT,
    follow_redirects=True,
    headers={"Accept": "application/json", "User-Agent": USER_AGENT},
)


def _get(path: str, params: list[tuple[str, str]] | None = None) -> tuple[Any, str | None]:
    """GET returning (payload, error). Never raises — the demo answers with data."""
    url = f"{BASE_URL}/{path.lstrip('/')}"
    try:
        resp = HTTP.get(url, params=params or [])
        resp.raise_for_status()
        return resp.json(), None
    except httpx.HTTPStatusError as exc:
        return None, f"Recherche Data Gouv returned HTTP {exc.response.status_code}"
    except httpx.TimeoutException:
        return None, f"Recherche Data Gouv timed out after {REQUEST_TIMEOUT:g}s"
    except Exception as exc:  # noqa: BLE001 - never crash the Space
        return None, f"cannot reach Recherche Data Gouv: {exc}"


def _normalize_search_item(item: dict) -> dict:
    """Map one Dataverse search item onto the record shape the server returns."""
    return {
        "source": "recherche-data-gouv",
        "id": item.get("global_id") or item.get("identifier") or item.get("entity_id"),
        "type": item.get("type"),
        "title": item.get("name"),
        "name": item.get("name"),
        "description": item.get("description"),
        "authors": item.get("authors") or [],
        "subjects": item.get("subjects") or [],
        "url": item.get("url"),
        "global_id": item.get("global_id"),
        "identifier": item.get("identifier"),
        "published_at": item.get("published_at"),
        "publisher": item.get("publisher"),
        "citation": item.get("citation"),
        "dataverse_alias": item.get("identifier_of_dataverse"),
        "dataverse_name": item.get("name_of_dataverse"),
        "file_count": item.get("fileCount"),
        "version_state": item.get("versionState"),
    }


# ── MCP tools (the only functions exposed with gr.api) ────────────────────────


def search(q: str = "*", type: str | None = None, per_page: int = 5) -> dict:
    """
    Search public Recherche Data Gouv (Dataverse) records: datasets, dataverses and files.

    Args:
        q: Solr query, e.g. "biodiversité" or "authorName:Dupont". "*" matches everything.
        type: Restrict to one entity type — dataset, dataverse or file. Empty for all.
        per_page: Number of records to return, 1-10 on this demo endpoint.

    Returns:
        {"source": "recherche-data-gouv", "command": "search", "query_used": str, "total_found": int, "returned": int, "results": [{"source": str, "id": str, "type": str, "title": str, "authors": [str], "url": str, "published_at": str | null}], "error": str | null}
    """
    out: dict = {
        "source": "recherche-data-gouv", "command": "search",
        "query_used": q or "*", "total_found": 0, "returned": 0,
        "results": [], "error": None,
    }

    params: list[tuple[str, str]] = [
        ("q", (q or "*").strip() or "*"),
        ("per_page", str(max(1, min(int(per_page or 5), MAX_RESULTS)))),
        ("start", "0"),
    ]
    if type:
        if type not in SEARCH_TYPES:
            out["error"] = "type must be one of " + ", ".join(SEARCH_TYPES)
            return out
        params.append(("type", type))

    data, error = _get("search", params)
    if error:
        out["error"] = error
        return out

    payload = data.get("data", {}) if isinstance(data, dict) else {}
    items = [i for i in (payload.get("items") or []) if isinstance(i, dict)]
    out["query_used"] = payload.get("q", out["query_used"])
    out["total_found"] = payload.get("total_count", 0)
    out["returned"] = len(items)
    out["results"] = [_normalize_search_item(i) for i in items]
    return out


def metrics(category: str = "downloads", breakdown: str | None = None) -> dict:
    """
    Fetch a public Dataverse Metrics API counter for the whole Recherche Data Gouv instance.

    Args:
        category: Counter to read — dataverses, datasets, files, downloads, filedownloads, uniquedownloads, uniquefiledownloads or tree.
        breakdown: Optional breakdown of the counter — monthly, byCategory, bySubject or byType. Empty for the total.

    Returns:
        {"source": "recherche-data-gouv", "command": "metrics", "category": str, "breakdown": str | null, "data": object, "error": str | null}
    """
    out: dict = {
        "source": "recherche-data-gouv", "command": "metrics",
        "category": category, "breakdown": breakdown or None,
        "data": None, "error": None,
    }

    if category not in METRIC_CATEGORIES:
        out["error"] = "category must be one of " + ", ".join(METRIC_CATEGORIES)
        return out
    path = f"info/metrics/{category}"
    if breakdown:
        if breakdown not in METRIC_BREAKDOWNS:
            out["error"] = "breakdown must be one of " + ", ".join(METRIC_BREAKDOWNS)
            return out
        path = f"{path}/{breakdown}"

    data, error = _get(path)
    if error:
        out["error"] = error
        return out
    out["data"] = data
    return out


# ── Presentation ──────────────────────────────────────────────────────────────


def _render_search(payload: dict) -> str:
    results = payload.get("results") or []
    if not results:
        return "_Aucun enregistrement ne correspond._"
    lines = [
        f"**{payload.get('returned', len(results))} sur {payload.get('total_found', '?')} enregistrements**",
        "",
        "| Type | Titre | Auteurs | Publié le |",
        "|---|---|---|---|",
    ]
    for r in results:
        names = [a for a in (r.get("authors") or []) if a]
        authors = ", ".join(names[:3]) or "—"
        if len(names) > 3:
            authors += " et al."
        title = (r.get("title") or "Sans titre").replace("|", "\\|")
        url = r.get("url")
        lines.append(
            "| {t} | {title} | {authors} | {pub} |".format(
                t=r.get("type") or "—",
                title=f"[{title}]({url})" if url else title,
                authors=authors.replace("|", "\\|"),
                pub=(r.get("published_at") or "—")[:10],
            )
        )
    return "\n".join(lines)


def _render_metrics(payload: dict) -> str:
    data = payload.get("data")
    label = payload.get("category")
    if payload.get("breakdown"):
        label = f"{label} / {payload['breakdown']}"
    inner = data.get("data") if isinstance(data, dict) else None
    # A total comes back as {"status": "OK", "data": {"count": N}}; a breakdown
    # as a list of buckets.
    if isinstance(inner, dict) and isinstance(inner.get("count"), (int, float)):
        return f"**{label}** — `{inner['count']}`"
    if isinstance(inner, list) and inner:
        keys = [k for k in inner[0] if isinstance(inner[0], dict)]
        lines = ["| " + " | ".join(keys) + " |", "|" + "---|" * len(keys)]
        for row in inner[:25]:
            lines.append("| " + " | ".join(str(row.get(k, "—")) for k in keys) + " |")
        return f"**{label}**\n\n" + "\n".join(lines)
    return f"**{label}** — voir la sortie brute ci-dessous."


def _run_search(q, entity_type, per_page):
    payload = search(q, entity_type or None, per_page)
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render_search(payload), payload


def _run_metrics(category, breakdown):
    payload = metrics(category, breakdown or None)
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render_metrics(payload), payload


# ── UI ────────────────────────────────────────────────────────────────────────

with gr.Blocks(title="Recherche Data Gouv MCP demo") as demo:
    gr.Markdown(
        "# Recherche Data Gouv MCP demo\n"
        "Démo autonome du serveur MCP "
        "[`recherche-data-gouv`](https://github.com/smartbiblia-solutions/agentic-stack/tree/main/mcp/recherche-data-gouv) "
        ", l'entrepôt Dataverse de la recherche française."
    )

    with gr.Tab("Recherche"):
        q = gr.Textbox(label="Requête (syntaxe Solr)", value="*", placeholder="biodiversité")
        with gr.Row():
            entity_type = gr.Dropdown(
                [""] + list(SEARCH_TYPES), value="dataset", label="Type d'entité"
            )
            per_page = gr.Slider(1, MAX_RESULTS, value=5, step=1, label="Résultats")
        search_btn = gr.Button("Rechercher", variant="primary")
        search_out = gr.Markdown()
        search_raw = gr.JSON(label="Sortie brute de l'outil")

        gr.Examples(
            examples=[
                ["biodiversité", "dataset", 5],
                ["qzxwvsansresultat", "dataset", 0],
            ],
            inputs=[q, entity_type, per_page],
            label="Une requête qui trouve, une qui ne trouve rien",
        )
        search_btn.click(
            _run_search,
            inputs=[q, entity_type, per_page],
            outputs=[search_out, search_raw],
            api_name=False,
        )

    with gr.Tab("Métriques"):
        category = gr.Dropdown(
            list(METRIC_CATEGORIES), value="datasets", label="Compteur"
        )
        breakdown = gr.Dropdown(
            [""] + list(METRIC_BREAKDOWNS), value="", label="Ventilation (optionnelle)"
        )
        metrics_btn = gr.Button("Relever", variant="primary")
        metrics_out = gr.Markdown()
        metrics_raw = gr.JSON(label="Sortie brute de l'outil")

        gr.Examples(
            examples=[["datasets", ""], ["datasets", "bySubject"]],
            inputs=[category, breakdown],
            label="Un total, et une ventilation",
        )
        metrics_btn.click(
            _run_metrics,
            inputs=[category, breakdown],
            outputs=[metrics_out, metrics_raw],
            api_name=False,
        )

    # The only declared MCP tools. Names match the canonical server's.
    gr.api(search, api_name="search")
    gr.api(metrics, api_name="metrics")


if __name__ == "__main__":
    demo.launch(
        theme=gr.themes.Soft(),  # Gradio 6 moved theme from Blocks() to launch()
        server_name=os.getenv("GRADIO_SERVER_NAME", "0.0.0.0"),
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
        mcp_server=os.getenv("GRADIO_MCP_SERVER", "true").lower() == "true",
    )
