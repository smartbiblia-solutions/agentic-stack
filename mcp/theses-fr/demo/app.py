#!/usr/bin/env python3
"""
Standalone Gradio demo of the theses.fr MCP server, deployable as a Hugging
Face Space.

The six tools are the canonical `mcp_server.py` ones — same names, same
arguments, same envelope — through `theses_core.py`, which is generated from
the server by `../scripts/sync_copies.py` (the Space is pushed from this folder
alone, so it cannot import the server). This file only adds the Gradio layer.
Two deliberate narrowings: `max_results` is clamped to 10, and enumerated
arguments are plain `str` validated here rather than `Literal`, so that a bad
value comes back in `error` instead of as a transport failure.

Local run:
    uv run --with 'gradio[mcp]>=6,<7' --with httpx app.py

Environment:
    THESES_FR_ETABLISSEMENTS  path or URL of the establishment referential
                              (default: the copy on the repository's main branch)
    GRADIO_SERVER_NAME        bind address (default 0.0.0.0)
    GRADIO_SERVER_PORT        port (default 7860)
    GRADIO_MCP_SERVER         "false" disables the demo MCP endpoint (default true)
"""

from __future__ import annotations

import os
import re
from typing import Any

import gradio as gr

import theses_core as core

STATUS_VALUES = ("soutenue", "enCours")
SORT_VALUES = ("pertinence", "dateDesc", "dateAsc", "auteursAsc", "auteursDesc",
               "disciplineAsc", "disciplineDesc")
ROLE_VALUES = ("etabSoutenance", "etabCotutelle", "partenaireRecherche", "ecoleDoctorale")
FACET_VALUES = ("Statut", "Établissements", "Écoles doctorales",
                "Domaines thématiques", "Disciplines", "Langues")

# Clamped harder than the canonical server: this endpoint is public.
MAX_RESULTS = 10


def _doc(fn: Any, note: str | None = None) -> str:
    """The canonical tool's docstring, with the demo's narrowing before Args."""
    doc = fn.__doc__ or ""
    if note:
        # Indented or not: Python 3.13 strips docstring indentation at compile time.
        doc = re.sub(r"\n([ \t]*)Args:", lambda m: f"\n{m[1]}{note}\n\n{m[1]}Args:", doc, count=1)
    return doc


def _invalid(command: str, name: str, value: str, allowed: tuple[str, ...]) -> dict:
    return {"source": "theses-fr", "command": command, "total_found": None, "returned": 0,
            "results": [], "error": f"{name} must be one of {', '.join(allowed)} — got {value!r}"}


def _opt(value: str | None) -> str | None:
    return (value or "").strip() or None


# ── MCP tools (the only functions exposed with gr.api) ────────────────────────

async def search_theses(
    topic: str = "",
    establishment: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    discipline: str | None = None,
    author: str | None = None,
    director: str | None = None,
    online: bool | None = None,
    language: str | None = None,
    domain: str | None = None,
    organisation_ppn: str | None = None,
    organisation_role: str = "any",
    include_predecessors: bool = False,
    query: str = "",
    sort: str | None = None,
    max_results: int = 10,
    start: int = 0,
    with_abstracts: bool = False,
) -> dict:
    status, sort = _opt(status), _opt(sort)
    organisation_role = _opt(organisation_role) or "any"
    if status and status not in STATUS_VALUES:
        return _invalid("search_theses", "status", status, STATUS_VALUES)
    if sort and sort not in SORT_VALUES:
        return _invalid("search_theses", "sort", sort, SORT_VALUES)
    if organisation_role not in (*ROLE_VALUES, "any"):
        return _invalid("search_theses", "organisation_role", organisation_role, (*ROLE_VALUES, "any"))
    return await core.search_theses(
        topic=topic or "", establishment=_opt(establishment), status=status,
        date_from=_opt(date_from), date_to=_opt(date_to), discipline=_opt(discipline),
        author=_opt(author), director=_opt(director), online=online,
        language=_opt(language), domain=_opt(domain), organisation_ppn=_opt(organisation_ppn),
        organisation_role=organisation_role, include_predecessors=bool(include_predecessors),
        query=query or "", sort=sort, max_results=max(1, min(int(max_results or 10), MAX_RESULTS)),
        start=max(0, int(start or 0)), with_abstracts=bool(with_abstracts),
    )


async def resolve_establishment(name: str, max_results: int = 5) -> dict:
    return await core.resolve_establishment(name or "", max(1, min(int(max_results or 5), MAX_RESULTS)))


async def get_thesis(id: str) -> dict:
    return await core.get_thesis(id or "")


async def search_persons(name: str, max_results: int = 10, start: int = 0) -> dict:
    if not (name or "").strip():
        return {"source": "theses-fr", "command": "search_persons", "total_found": None,
                "returned": 0, "results": [], "error": "name is required — a person's name"}
    return await core.search_persons(name.strip(), max(1, min(int(max_results or 10), MAX_RESULTS)),
                                     max(0, int(start or 0)))


async def list_facets(topic: str = "", query: str = "", facet: str | None = None,
                      contains: str | None = None, limit: int = 15) -> dict:
    facet = _opt(facet)
    if facet and facet not in FACET_VALUES:
        return _invalid("list_facets", "facet", facet, FACET_VALUES)
    return await core.list_facets(topic or "", query or "", facet, _opt(contains), int(limit or 15))


async def search_by_organisme(ppn: str, role: str | None = None, status: str | None = None,
                              max_results: int = 5) -> dict:
    role, status = _opt(role), _opt(status)
    if role and role not in ROLE_VALUES:
        return _invalid("search_by_organisme", "role", role, ROLE_VALUES)
    if status and status not in STATUS_VALUES:
        return _invalid("search_by_organisme", "status", status, STATUS_VALUES)
    if not (ppn or "").strip():
        return _invalid("search_by_organisme", "ppn", ppn or "", ("an organisation's IdRef PPN",))
    return await core.search_by_organisme(ppn, role, status, max(0, min(int(max_results or 0), MAX_RESULTS)))


_NARROW = (f"On this demo endpoint, `max_results` is capped at {MAX_RESULTS}, "
           "whatever the range stated below.")
search_theses.__doc__ = _doc(core.search_theses, _NARROW)
resolve_establishment.__doc__ = _doc(core.resolve_establishment)
get_thesis.__doc__ = _doc(core.get_thesis)
search_persons.__doc__ = _doc(core.search_persons, _NARROW)
list_facets.__doc__ = _doc(core.list_facets)
search_by_organisme.__doc__ = _doc(core.search_by_organisme, _NARROW)


# ── Presentation ──────────────────────────────────────────────────────────────

# Gradio negotiates the iframe height with the parent page and stops honouring
# growth after a few increases, so on a Space a long Markdown block ends up
# unreachable. Bound what the Markdown shows; the raw JSON beside it carries
# everything the tool returned.
MAX_FACET_VALUES = 8
MAX_FACET_LABEL = 60
MAX_ABSTRACT_CHARS = 800


def _esc(text: Any) -> str:
    return str(text if text not in (None, "") else "—").replace("|", "\\|")


def _excerpt(text: str, limit: int = MAX_ABSTRACT_CHARS) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + " […]"


def _link(label: str, url: str | None) -> str:
    return f"[{_esc(label)}]({url})" if url else _esc(label)


def _when(r: dict) -> str:
    if r.get("defense_date"):
        return r["defense_date"]
    if r.get("first_registration_date"):
        return f"en cours (inscr. {r['first_registration_date']})"
    return "en cours" if r.get("status") == "enCours" else "—"


def _render_search(payload: dict) -> str:
    lines = [f"**{payload.get('returned', 0)} sur {payload.get('total_found', '?')} thèses** "
             f"— `{payload.get('query_used', '')}`"]
    if resolved := payload.get("establishment_resolved"):
        lines += ["", "Établissement : " + ", ".join(f"{k} = `{v}`" for k, v in resolved.items())]
    results = payload.get("results") or []
    if not results:
        return "\n".join(lines + ["", f"_{payload.get('hint') or 'Aucune thèse ne correspond.'}_"])
    lines += ["", "| Titre | Auteur·rice | Établissement | Soutenance |", "|---|---|---|---|"]
    for r in results:
        lines.append(f"| {_link(r.get('title') or 'Sans titre', r.get('url'))} "
                     f"| {_esc(', '.join(r.get('authors') or []))} "
                     f"| {_esc(r.get('institution'))} | {_esc(_when(r))} |")
    first = next((r for r in results if r.get("abstract_fr") or r.get("abstract_en")), None)
    if first:
        lang = "fr" if first.get("abstract_fr") else "en"
        lines += ["", f"**Résumé du premier résultat ({lang})**", "",
                  _excerpt(first[f"abstract_{lang}"])]
    return "\n".join(lines)


def _render_establishments(payload: dict) -> str:
    results = payload.get("results") or []
    if not results:
        return f"_{payload.get('hint') or 'Aucun établissement ne correspond.'}_"
    lines = ["| Code | Établissement | PPN | Période | Thèses | Avant → après |", "|---|---|---|---|---|---|"]
    for r in results:
        period = f"{r.get('from') or '…'} – {r.get('until') or '…'}"
        lineage = (", ".join(p["code"] for p in r.get("predecessors", [])) or "—") + " → " + \
                  (", ".join(s["code"] for s in r.get("successors", [])) or "—")
        lines.append(f"| `{r['code']}` | {_esc(r.get('name'))} | {_esc(r.get('ppn'))} "
                     f"| {period} | {_esc(r.get('theses_count'))} | {lineage} |")
    lines += ["", "_Le code se passe à l'onglet Recherche (champ Établissement), "
                  "le PPN à l'onglet Organismes._"]
    return "\n".join(lines)


def _render_detail(payload: dict) -> str:
    r = payload.get("result")
    if not r:
        return "_Aucun enregistrement._"
    inst = r.get("institution") or {}
    jury = r.get("jury") or {}
    lines = [
        f"### {r.get('title') or 'Sans titre'}",
        "",
        f"- **Auteur·rice** : {', '.join(r.get('authors') or []) or '—'}",
        f"- **Direction** : {', '.join(r.get('directors') or []) or '—'}",
        f"- **Établissement** : {inst.get('name') or '—'} (`{inst.get('code') or '—'}`)",
        f"- **Discipline** : {r.get('discipline') or '—'}",
        f"- **Soutenance** : {_when(r)}",
        f"- **Jury** : présidence {jury.get('president') or '—'} ; rapport "
        f"{', '.join(jury.get('rapporteurs') or []) or '—'}",
        f"- **Texte intégral** : {r.get('fulltext_url') or ('en ligne' if r.get('online') else 'non accessible')}",
        f"- **theses.fr** : {r.get('url') or '—'}",
    ]
    for lang, label in (("fr", "Résumé"), ("en", "Abstract")):
        if text := r.get(f"abstract_{lang}"):
            lines += ["", f"**{label}**", "", _excerpt(text)]
    if r.get("missing"):
        lines += ["", f"_{r['missing']}_"]
    return "\n".join(lines)


def _render_persons(payload: dict) -> str:
    results = payload.get("results") or []
    if not results:
        return "_Aucune personne ne correspond._"
    lines = [f"**{payload.get('returned', 0)} sur {payload.get('total_found', '?')} personnes**", "",
             "| Personne | IdRef | Rôles | Thèses |", "|---|---|---|---|"]
    for r in results:
        roles = ", ".join(f"{k} ({v})" for k, v in (r.get("roles") or {}).items())
        lines.append(f"| {_link(r.get('name') or '—', r.get('url'))} | {_esc(r.get('idref_ppn'))} "
                     f"| {_esc(roles)} | {r.get('theses_count', 0)} |")
    lines += ["", "_Un PPN IdRef se passe tel quel au champ Direction ou Auteur·rice de "
                  "l'onglet Recherche : c'est la requête exacte, sans homonymes._"]
    return "\n".join(lines)


def _render_facets(payload: dict) -> str:
    results = payload.get("results") or []
    if not results:
        return "_Aucune facette._"
    lines = [f"`{payload.get('query_used')}`", "",
             "| Facette | Valeurs | Les plus fréquentes |", "|---|---|---|"]
    for f in results:
        values = f.get("values") or []
        top = " · ".join(f"{_esc(_excerpt(str(v.get('value') or '—'), MAX_FACET_LABEL))} ({v.get('count')})"
                         for v in values[:MAX_FACET_VALUES]) or "—"
        if f.get("values_total", 0) > MAX_FACET_VALUES:
            top += f" · … +{f['values_total'] - MAX_FACET_VALUES}"
        lines.append(f"| {f.get('facet')} | {f.get('values_total', 0)} | {top} |")
    return "\n".join(lines)


def _render_organisme(payload: dict) -> str:
    org = payload.get("organisme") or {}
    lines = [f"### {org.get('name') or '—'}", "",
             f"PPN `{org.get('ppn')}` — **{payload.get('total_found', 0)} thèses** au total.", "",
             "| Rôle | Soutenues | En préparation |", "|---|---|---|"]
    for role, counts in (payload.get("totals") or {}).items():
        lines.append(f"| `{role}` | {counts.get('soutenue', 0)} | {counts.get('enCours', 0)} |")
    if results := payload.get("results") or []:
        lines += ["", "| Rôle | Titre | Soutenance |", "|---|---|---|"]
        for r in results:
            lines.append(f"| {r.get('role') or '—'} | {_link(r.get('title') or 'Sans titre', r.get('url'))} "
                         f"| {_esc(_when(r))} |")
    lines += ["", "_Pour lister ou filtrer ces thèses, onglet Recherche : PPN de l'organisme "
                  "et rôle._"]
    return "\n".join(lines)


def _show(payload: dict, render) -> tuple[str, dict]:
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return render(payload), payload


async def _run_search(topic, establishment, status, date_from, date_to, discipline, author,
                      director, online, language, domain, organisation_ppn, organisation_role,
                      include_predecessors, query, sort, max_results, with_abstracts):
    online_flag = {"oui": True, "non": False}.get(online)
    payload = await search_theses(topic, establishment, status, date_from, date_to, discipline,
                                  author, director, online_flag, language, domain,
                                  organisation_ppn, organisation_role or "any",
                                  include_predecessors, query, sort, int(max_results), 0,
                                  with_abstracts)
    return _show(payload, _render_search)


async def _run_resolve(name):
    return _show(await resolve_establishment(name), _render_establishments)


async def _run_get(id_value):
    return _show(await get_thesis(id_value), _render_detail)


async def _run_persons(name, max_results):
    return _show(await search_persons(name, int(max_results)), _render_persons)


async def _run_facets(topic, facet, contains, limit):
    return _show(await list_facets(topic, "", facet, contains, int(limit)), _render_facets)


async def _run_organisme(ppn_value, role, status):
    return _show(await search_by_organisme(ppn_value, role, status, MAX_RESULTS), _render_organisme)


# ── UI ────────────────────────────────────────────────────────────────────────

with gr.Blocks(title="theses.fr MCP demo") as demo:
    gr.Markdown(
        "# theses.fr MCP demo\n"
        "Démo autonome du serveur MCP "
        "[`theses-fr`](https://github.com/smartbiblia-solutions/agentic-stack/tree/main/mcp/theses-fr)"
        " : le registre national des thèses de doctorat françaises (ABES).\n\n"
        "Le sujet se cherche en mots simples (racinisés, sur titres, résumés et mots-clés) ; "
        "l'établissement se donne par son nom, son code ou son PPN."
    )

    with gr.Tab("Recherche"):
        topic = gr.Textbox(label="Sujet (mots simples, OR entre les variantes)", value="",
                           placeholder="énergies marines renouvelables")
        with gr.Row():
            establishment = gr.Textbox(label="Établissement (nom, code ou PPN)", value="",
                                       placeholder="Université Côte d'Azur")
            include_predecessors = gr.Checkbox(label="Inclure les anciens codes", value=False)
            status = gr.Dropdown([""] + list(STATUS_VALUES), value="", label="Statut")
        with gr.Row():
            date_from = gr.Textbox(label="Soutenue à partir de", value="", placeholder="2020")
            date_to = gr.Textbox(label="Soutenue jusqu'à", value="", placeholder="2024-12-31")
            online = gr.Dropdown(["", "oui", "non"], value="", label="Texte intégral en ligne")
        with gr.Row():
            author = gr.Textbox(label="Auteur·rice (nom accentué ou PPN)", value="")
            director = gr.Textbox(label="Direction (nom accentué ou PPN)", value="",
                                  placeholder="Frédéric Precioso")
            discipline = gr.Textbox(label="Discipline", value="", placeholder="informatique")
        with gr.Accordion("Filtres avancés", open=False):
            with gr.Row():
                language = gr.Textbox(label="Langue (code ISO)", value="", placeholder="en")
                domain = gr.Textbox(label="Domaine thématique", value="", placeholder="Informatique")
                sort = gr.Dropdown([""] + list(SORT_VALUES), value="", label="Tri")
            with gr.Row():
                organisation_ppn = gr.Textbox(label="PPN d'un organisme", value="",
                                              placeholder="241035694")
                organisation_role = gr.Dropdown(["any"] + list(ROLE_VALUES), value="any",
                                                label="Rôle de l'organisme")
            query = gr.Textbox(label="Lucene brut (expert, combiné par AND)", value="",
                               placeholder='sujetsRameauLibelle:("Énergie éolienne")')
        with gr.Row():
            max_results = gr.Slider(1, MAX_RESULTS, value=5, step=1, label="Résultats")
            with_abstracts = gr.Checkbox(label="Ajouter les résumés (tronqués)", value=False)
        search_btn = gr.Button("Rechercher", variant="primary")
        search_out = gr.Markdown()
        search_raw = gr.JSON(label="Sortie brute de l'outil")

        search_inputs = [topic, establishment, status, date_from, date_to, discipline, author,
                         director, online, language, domain, organisation_ppn, organisation_role,
                         include_predecessors, query, sort, max_results, with_abstracts]
        gr.Examples(
            examples=[
                ["énergies marines renouvelables", "", "enCours", "", "", "", "", "", "", "", "",
                 "", "any", False, "", "", 5, False],
                ["éolien", "Université Côte d'Azur", "soutenue", "2020", "", "", "", "", "", "",
                 "", "", "any", False, "", "dateDesc", 5, True],
                ["", "", "", "", "", "", "", "Frédéric Precioso", "", "", "", "", "any", False,
                 "", "dateDesc", 5, False],
                ["apprentissage automatique", "COAZ", "", "", "", "", "", "", "", "", "", "",
                 "any", True, "", "", 5, False],
                ["", "", "", "", "", "", "", "", "", "", "", "241035694", "partenaireRecherche",
                 False, "", "dateDesc", 5, False],
            ],
            inputs=search_inputs,
            label="Sujet en préparation, sujet + établissement + date, directeur, "
                  "établissement avec ses prédécesseurs, organisme partenaire",
        )
        search_btn.click(_run_search, inputs=search_inputs, outputs=[search_out, search_raw],
                         api_name=False)

    with gr.Tab("Établissements"):
        gr.Markdown("Nom, sigle ou code → code établissement, PPN et lignée (fusions).")
        etab_name = gr.Textbox(label="Nom, sigle ou code", value="", placeholder="UCA")
        etab_btn = gr.Button("Résoudre", variant="primary")
        etab_out = gr.Markdown()
        etab_raw = gr.JSON(label="Sortie brute de l'outil")
        gr.Examples(examples=[["UCA"], ["Paris-Saclay"], ["Université de Nice"], ["EHESS"]],
                    inputs=[etab_name], label="Un sigle ambigu, une fusion, un ancien nom, un sigle")
        etab_btn.click(_run_resolve, inputs=[etab_name], outputs=[etab_out, etab_raw],
                       api_name=False)

    with gr.Tab("Notice"):
        id_value = gr.Textbox(label="NNT ou numéro de sujet", value="2021COAZ4028")
        get_btn = gr.Button("Consulter", variant="primary")
        get_out = gr.Markdown()
        get_raw = gr.JSON(label="Sortie brute de l'outil")
        gr.Examples(examples=[["2021COAZ4028"], ["2022SORUL001"], ["s312947"], ["2099ZZZZ0001"]],
                    inputs=[id_value],
                    label="En ligne, non accessible, en préparation, inexistante")
        get_btn.click(_run_get, inputs=[id_value], outputs=[get_out, get_raw], api_name=False)

    with gr.Tab("Personnes"):
        gr.Markdown("Index des personnes : rôles et thèses d'un·e auteur·rice, directeur·rice "
                    "ou membre de jury.")
        person_name = gr.Textbox(label="Nom", value="", placeholder="Precioso")
        person_rows = gr.Slider(1, MAX_RESULTS, value=5, step=1, label="Résultats")
        person_btn = gr.Button("Chercher", variant="primary")
        person_out = gr.Markdown()
        person_raw = gr.JSON(label="Sortie brute de l'outil")
        gr.Examples(examples=[["Precioso", 5], ["Turletti", 5], ["Bengio", 5]],
                    inputs=[person_name, person_rows], label="Deux directeurs, un homonyme fréquent")
        person_btn.click(_run_persons, inputs=[person_name, person_rows],
                         outputs=[person_out, person_raw], api_name=False)

    with gr.Tab("Facettes"):
        gr.Markdown("Répartition des thèses d'un sujet par établissement, discipline, domaine…")
        facet_topic = gr.Textbox(label="Sujet (vide = tout le corpus)", value="",
                                 placeholder="biofouling")
        with gr.Row():
            facet_name = gr.Dropdown([""] + list(FACET_VALUES), value="", label="Facette")
            facet_contains = gr.Textbox(label="Valeurs contenant", value="")
            facet_limit = gr.Slider(1, 50, value=10, step=1, label="Valeurs par facette")
        facet_btn = gr.Button("Lister", variant="primary")
        facet_out = gr.Markdown()
        facet_raw = gr.JSON(label="Sortie brute de l'outil")
        gr.Examples(
            examples=[["biofouling", "Établissements", "", 10], ["", "Établissements", "Côte d'Azur", 10],
                      ["intelligence artificielle", "Disciplines", "", 10], ["", "", "", 5]],
            inputs=[facet_topic, facet_name, facet_contains, facet_limit],
            label="Établissements d'un sujet, un nom affiché, disciplines d'un sujet, tout le corpus",
        )
        facet_btn.click(_run_facets, inputs=[facet_topic, facet_name, facet_contains, facet_limit],
                        outputs=[facet_out, facet_raw], api_name=False)

    with gr.Tab("Organismes"):
        gr.Markdown("Profil d'un organisme par son PPN IdRef : nombre de thèses par rôle "
                    "(établissement, cotutelle, partenaire de recherche, école doctorale).")
        org_ppn = gr.Textbox(label="PPN IdRef", value="", placeholder="241035694")
        with gr.Row():
            org_role = gr.Dropdown([""] + list(ROLE_VALUES), value="", label="Rôle (optionnel)")
            org_status = gr.Dropdown([""] + list(STATUS_VALUES), value="",
                                     label="Statut des exemples (optionnel)")
        org_btn = gr.Button("Consulter", variant="primary")
        org_out = gr.Markdown()
        org_raw = gr.JSON(label="Sortie brute de l'outil")
        gr.Examples(
            examples=[["241035694", "", ""], ["241035694", "partenaireRecherche", ""],
                      ["059079800", "ecoleDoctorale", ""], ["059205717", "partenaireRecherche", ""]],
            inputs=[org_ppn, org_role, org_status],
            label="Une université tous rôles, la même en partenariat, une école doctorale, un laboratoire",
        )
        org_btn.click(_run_organisme, inputs=[org_ppn, org_role, org_status],
                      outputs=[org_out, org_raw], api_name=False)

    # The only declared MCP tools. Names match the canonical server's.
    gr.api(search_theses, api_name="search_theses")
    gr.api(resolve_establishment, api_name="resolve_establishment")
    gr.api(get_thesis, api_name="get_thesis")
    gr.api(search_persons, api_name="search_persons")
    gr.api(list_facets, api_name="list_facets")
    gr.api(search_by_organisme, api_name="search_by_organisme")


if __name__ == "__main__":
    demo.launch(
        theme=gr.themes.Soft(),  # Gradio 6 moved theme from Blocks() to launch()
        server_name=os.getenv("GRADIO_SERVER_NAME", "0.0.0.0"),
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
        mcp_server=os.getenv("GRADIO_MCP_SERVER", "true").lower() == "true",
    )
