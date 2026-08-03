#!/usr/bin/env python3
"""
Standalone Gradio demo of the sudoc-sru MCP server, deployable as a Hugging Face Space.

This app imports nothing from the parent folder: the Space root is this folder,
so `mcp_server.py` does not exist there. It re-implements two of the server's
tools — `search_sudoc` and `lookup_by_ppn` — against the same Abes SRU service,
under the same names, with the same argument names and the same record shape.

The canonical MCP endpoint remains `../mcp_server.py`, which also carries
`lookup_by_isbn`, `count_records` and `scan_index`, the full index reference and
no tightened result limit. These two tools are a hand-kept copy: change one,
change the other.

Local run:
    uv run --with 'gradio[mcp]>=6,<7' --with httpx app.py

Environment:
    GRADIO_SERVER_NAME   bind address (default 0.0.0.0)
    GRADIO_SERVER_PORT   port (default 7860)
    GRADIO_MCP_SERVER    "false" disables the demo MCP endpoint (default true)
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET

import gradio as gr
import httpx

# ── Configuration ─────────────────────────────────────────────────────────────

SRU_BASE_URL = "https://www.sudoc.abes.fr/cbs/sru/"
SRU_NS = {"srw": "http://www.loc.gov/zing/srw/"}

# A Space has no command line: connector policy is constant here.
REQUEST_TIMEOUT = 30.0

# Clamped harder than the canonical server: the Abes SRU service is a shared
# public endpoint and every visitor's click is attributed to this Space's host.
MAX_RESULTS = 10

# One module-level pooled client for the process.
HTTP = httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True)


# ── SRU query encoding ────────────────────────────────────────────────────────
#
# Absolute rule of the Abes SRU protocol: `=` inside a search clause must always
# be encoded as %3D, or the server mistakes the search operator for the URL
# parameter separator and answers with an error or zero results.

def _encode_query(raw: str) -> str:
    """Encode a natural SRU string (`mti=jardins and japonais`) for `&query=`."""
    if "%3D" in raw or "%3d" in raw:  # idempotent: caller already encoded
        return raw
    encoded = raw.replace("=", "%3D")
    encoded = encoded.replace('"', "%22")
    encoded = encoded.replace(",", "%2C")
    encoded = encoded.replace("/", "%2F")
    encoded = encoded.replace("|", "%7C")
    return re.sub(r" +", "+", encoded.strip())


def _build_url(query_encoded: str, *, start_record: int = 1, maximum_records: int = 10) -> str:
    params = (
        "operation=searchRetrieve"
        "&version=1.1"
        "&recordSchema=unimarc"
        f"&maximumRecords={maximum_records}"
        f"&startRecord={start_record}"
    )
    return f"{SRU_BASE_URL}?{params}&query={query_encoded}"


def _get_xml(url: str) -> tuple[ET.Element | None, str | None]:
    """GET returning (xml_root, error). Never raises — the demo answers with data."""
    try:
        resp = HTTP.get(url)
        resp.raise_for_status()
        return ET.fromstring(resp.content.decode("utf-8")), None
    except httpx.HTTPStatusError as exc:
        return None, f"Abes SRU returned HTTP {exc.response.status_code}"
    except httpx.TimeoutException:
        return None, f"Abes SRU timed out after {REQUEST_TIMEOUT:g}s"
    except ET.ParseError as exc:
        return None, f"malformed SRU response: {exc}"
    except Exception as exc:  # noqa: BLE001 - never crash the Space
        return None, f"cannot reach the Abes SRU service: {exc}"


# ── UNIMARC parsing ───────────────────────────────────────────────────────────


def _unimarc_root(record_data_el: ET.Element) -> ET.Element | None:
    for elem in record_data_el.iter():
        if elem.tag.split("}", 1)[-1] == "record":
            if any(child.tag.split("}", 1)[-1] in {"datafield", "controlfield"}
                   for child in elem.iter()):
                return elem
    return None


def _ctrl(record: ET.Element, tag: str) -> str | None:
    for el in record.iter():
        if el.tag.split("}", 1)[-1] == "controlfield" and el.get("tag") == tag:
            return (el.text or "").strip() or None
    return None


def _subfields(record: ET.Element, tag: str, *codes: str) -> list[str]:
    results: list[str] = []
    for df in record.iter():
        if df.tag.split("}", 1)[-1] == "datafield" and df.get("tag") == tag:
            for sf in df:
                if sf.tag.split("}", 1)[-1] == "subfield":
                    if not codes or sf.get("code", "") in codes:
                        v = (sf.text or "").strip()
                        if v:
                            results.append(v)
    return results


def _first(record: ET.Element, tag: str, *codes: str) -> str | None:
    vals = _subfields(record, tag, *codes)
    return vals[0] if vals else None


def _first_in_df(df: ET.Element, code: str) -> str | None:
    for sf in df:
        if sf.tag.split("}", 1)[-1] == "subfield" and sf.get("code") == code:
            return (sf.text or "").strip() or None
    return None


def _format_record(record: ET.Element) -> dict:
    """Convert one UNIMARC record into the normalized dict the server returns."""
    ppn = _ctrl(record, "001")

    title_parts = _subfields(record, "200", "a", "e")
    title = " : ".join(title_parts) if title_parts else None

    authors: list[str] = []
    for tag in ("700", "701"):
        for df in record.iter():
            if df.tag.split("}", 1)[-1] == "datafield" and df.get("tag") == tag:
                lastname = _first_in_df(df, "a")
                firstname = _first_in_df(df, "b")
                if lastname:
                    name = f"{lastname}, {firstname}" if firstname else lastname
                    if name not in authors:
                        authors.append(name)

    corp_authors: list[str] = []
    for tag in ("710", "711"):
        for df in record.iter():
            if df.tag.split("}", 1)[-1] == "datafield" and df.get("tag") == tag:
                name = _first_in_df(df, "a")
                if name and name not in corp_authors:
                    corp_authors.append(name)

    # Year: zone 100 $a positions 9-12, falling back to a year found in 210 $d.
    year: int | None = None
    raw_100a = _first(record, "100", "a")
    if raw_100a and len(raw_100a) >= 13:
        try:
            year = int(raw_100a[9:13])
        except ValueError:
            pass
    if year is None:
        raw_210d = _first(record, "210", "d")
        if raw_210d:
            m = re.search(r"\b(1[0-9]{3}|20[0-9]{2})\b", raw_210d)
            if m:
                year = int(m.group(1))

    thesis: dict | None = None
    for df in record.iter():
        if df.tag.split("}", 1)[-1] == "datafield" and df.get("tag") == "328":
            thesis = {
                "type": _first_in_df(df, "b"),
                "discipline": _first_in_df(df, "d"),
                "institution": _first_in_df(df, "e"),
                "year": _first_in_df(df, "f"),
            }
            break

    subjects: list[str] = []
    subject_tags = {str(t) for t in range(600, 687)}
    for df in record.iter():
        if df.tag.split("}", 1)[-1] == "datafield" and df.get("tag") in subject_tags:
            parts = [
                (sf.text or "").strip() for sf in df
                if sf.tag.split("}", 1)[-1] == "subfield" and (sf.text or "").strip()
            ]
            if parts:
                subjects.append(" -- ".join(parts))

    sudoc_url = f"https://www.sudoc.fr/{ppn}" if ppn else None

    return {
        # Identity anchors, shared by every connector in the repo.
        "source": "sudoc",
        "id": ppn,
        "url": sudoc_url,
        "ppn": ppn,
        "title": title,
        "authors": authors if authors else corp_authors,
        "personal_authors": authors,
        "corporate_authors": corp_authors,
        "year": year,
        "publisher": _first(record, "210", "c"),
        "pub_place": _first(record, "210", "a"),
        "language": _first(record, "101", "a"),
        "isbn": _first(record, "010", "a"),
        "issn": _first(record, "011", "a"),
        "thesis": thesis,
        "subjects": subjects,
        "series": _first(record, "410", "t"),
        "physical_desc": _first(record, "215", "a"),
        "notes": (_subfields(record, "300", "a") + _subfields(record, "320", "a")) or None,
        "urls": _subfields(record, "856", "u") or None,
        "sudoc_url": sudoc_url,
    }


def _records_from(root: ET.Element) -> list[dict]:
    out: list[dict] = []
    for srw_rec in root.findall(".//srw:record", namespaces=SRU_NS):
        rd = srw_rec.find("./srw:recordData", namespaces=SRU_NS)
        if rd is None:
            continue
        unimarc = _unimarc_root(rd)
        if unimarc is not None:
            out.append(_format_record(unimarc))
    return out


# ── MCP tools (the only functions exposed with gr.api) ────────────────────────


def search_sudoc(
    query: str,
    max_results: int = 5,
    doc_type: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
) -> dict:
    """
    Search the French union catalogue Sudoc over the Abes SRU service.

    Args:
        query: Sudoc SRU query, e.g. 'mti=jardins and japonais', 'aut=lagerlof', 'tou="ocre jaune"'. Indexes: mti (title), aut (author), tou (all), nth (thesis subject), sou (subject).
        max_results: Number of records to return, 1-10 on this demo endpoint.
        doc_type: One TDO letter code restricting the document type: b=printed monograph, y=thesis, t=periodical, a=article, o=e-monograph, k=map, m=score, f=manuscript. Leave empty for all.
        year_from: Earliest publication year, e.g. 2010. Leave empty for no lower bound.
        year_to: Latest publication year, e.g. 2024. Leave empty for no upper bound.

    Returns:
        {"source": "sudoc-sru", "command": "search_sudoc", "total_found": int, "returned": int, "query_used": str, "results": [{"source": "sudoc", "id": str, "url": str, "ppn": str, "title": str, "authors": [str], "year": int | null, "publisher": str | null, "sudoc_url": str}], "error": str | null}
    """
    out: dict = {"source": "sudoc-sru", "command": "search_sudoc",
                 "total_found": 0, "returned": 0, "query_used": query,
                 "results": [], "error": None}

    if not (query or "").strip():
        out["error"] = "query is required"
        return out

    # Limitations are natural SRU clauses; encoding happens once, below.
    limitations: list[str] = []
    if doc_type:
        limitations.append(f"tdo={doc_type}")
    if year_from is not None and year_to is not None:
        limitations.append(f"apu={int(year_from)}-{int(year_to)}")
    elif year_from is not None:
        limitations.append(f"apu=>={int(year_from)}")
    elif year_to is not None:
        limitations.append(f"apu=<={int(year_to)}")

    # A limitation can never stand alone in a Sudoc SRU query: it must always
    # accompany at least one search index.
    full_query = query + (" and " + " and ".join(limitations) if limitations else "")
    out["query_used"] = full_query
    encoded = _encode_query(full_query)

    wanted = max(1, min(int(max_results or 5), MAX_RESULTS))
    root, error = _get_xml(_build_url(encoded, start_record=1, maximum_records=wanted))
    if error:
        out["error"] = error
        return out

    el = root.find(".//srw:numberOfRecords", namespaces=SRU_NS)
    out["total_found"] = int(el.text) if el is not None and el.text else 0
    out["results"] = _records_from(root)
    out["returned"] = len(out["results"])
    return out


def lookup_by_ppn(ppn: str) -> dict:
    """
    Fetch one Sudoc record by its PPN, the catalogue's unique record identifier.

    Args:
        ppn: Sudoc PPN, digits only, e.g. "070685045". It is the last segment of a https://www.sudoc.fr/<PPN> URL.

    Returns:
        {"source": "sudoc-sru", "command": "lookup_by_ppn", "total_found": int, "returned": int, "results": [<same record shape as search_sudoc>], "error": str | null}
    """
    out: dict = {"source": "sudoc-sru", "command": "lookup_by_ppn",
                 "total_found": 0, "returned": 0, "results": [], "error": None}

    ppn = (ppn or "").strip()
    if not ppn:
        out["error"] = "ppn is required"
        return out

    encoded = _encode_query(f"ppn={ppn}")
    root, error = _get_xml(_build_url(encoded, start_record=1, maximum_records=1))
    if error:
        out["error"] = error
        return out

    records = _records_from(root)
    if not records:
        out["error"] = f"PPN not found in Sudoc: '{ppn}'"
        return out

    out["total_found"] = 1
    out["returned"] = 1
    out["results"] = records[:1]
    return out


# ── Presentation ──────────────────────────────────────────────────────────────


def _render_records(payload: dict) -> str:
    results = payload.get("results") or []
    if not results:
        return "_Aucune notice / no record matched._"
    lines = [
        f"**{payload.get('returned', len(results))} / {payload.get('total_found', '?')} notices**",
        "",
        "| PPN | Année | Titre | Auteurs | Éditeur |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        authors = ", ".join((r.get("authors") or [])[:3]) or "—"
        ppn = r.get("ppn") or ""
        lines.append(
            "| [{ppn}](https://www.sudoc.fr/{ppn}) | {year} | {title} | {authors} | {publisher} |".format(
                ppn=ppn,
                year=r.get("year") or "—",
                title=(r.get("title") or "Sans titre").replace("|", "\\|"),
                authors=authors.replace("|", "\\|"),
                publisher=(r.get("publisher") or "—").replace("|", "\\|"),
            )
        )
    return "\n".join(lines)


def _run_search(query, max_results, doc_type, year_from, year_to):
    payload = search_sudoc(query, max_results, doc_type or None,
                           int(year_from) if year_from else None,
                           int(year_to) if year_to else None)
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render_records(payload), payload


def _run_lookup(ppn):
    payload = lookup_by_ppn(ppn)
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render_records(payload), payload


# ── UI ────────────────────────────────────────────────────────────────────────

with gr.Blocks(title="Sudoc MCP demo") as demo:
    gr.Markdown(
        "# Sudoc MCP demo\n"
        "Standalone demo of the [`sudoc-sru`](https://github.com/smartbiblia-solutions/agentic-stack/tree/main/mcp/sudoc-sru) "
        "MCP server — the French union catalogue over SRU/UNIMARC. The canonical "
        "MCP endpoint is `mcp_server.py` in that folder; this Space re-implements "
        "two of its tools and re-exposes them at `/gradio_api/mcp/sse` for "
        "clients that cannot run it."
    )

    with gr.Tab("Recherche"):
        query = gr.Textbox(label="Requête SRU", placeholder="mti=jardins and japonais")
        with gr.Row():
            max_results = gr.Slider(1, MAX_RESULTS, value=5, step=1, label="Résultats")
            doc_type = gr.Dropdown(
                label="Type de document (code TDO)",
                choices=[
                    ("Tous", ""),
                    ("b — monographie imprimée", "b"),
                    ("y — thèse", "y"),
                    ("t — périodique", "t"),
                    ("a — article", "a"),
                    ("o — monographie électronique", "o"),
                    ("k — carte", "k"),
                    ("m — partition", "m"),
                    ("f — manuscrit", "f"),
                ],
                value="",
            )
        with gr.Row():
            year_from = gr.Number(label="Année min.", value=None, precision=0)
            year_to = gr.Number(label="Année max.", value=None, precision=0)
        search_btn = gr.Button("Rechercher", variant="primary")
        search_out = gr.Markdown()
        search_raw = gr.JSON(label="Raw tool output")

        gr.Examples(
            examples=[
                ["mti=jardins and japonais", 5, "", None, None],
                ["mti=zzzqwx and introuvable", 3, "", None, None],
            ],
            inputs=[query, max_results, doc_type, year_from, year_to],
            label="Une recherche qui trouve, une qui ne trouve rien",
        )
        search_btn.click(
            _run_search,
            inputs=[query, max_results, doc_type, year_from, year_to],
            outputs=[search_out, search_raw],
            api_name=False,
        )

    with gr.Tab("Notice par PPN"):
        ppn = gr.Textbox(label="PPN", placeholder="070685045")
        lookup_btn = gr.Button("Récupérer", variant="primary")
        lookup_out = gr.Markdown()
        lookup_raw = gr.JSON(label="Raw tool output")

        gr.Examples(
            examples=[["070685045"], ["000000000"]],
            inputs=[ppn],
            label="Un PPN existant, un PPN inconnu",
        )
        lookup_btn.click(
            _run_lookup, inputs=[ppn], outputs=[lookup_out, lookup_raw], api_name=False
        )

    # The only declared MCP tools. Names match the canonical server's.
    gr.api(search_sudoc, api_name="search_sudoc")
    gr.api(lookup_by_ppn, api_name="lookup_by_ppn")


if __name__ == "__main__":
    demo.launch(
        theme=gr.themes.Soft(),  # Gradio 6 moved theme from Blocks() to launch()
        server_name=os.getenv("GRADIO_SERVER_NAME", "0.0.0.0"),
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
        mcp_server=os.getenv("GRADIO_MCP_SERVER", "true").lower() == "true",
    )
