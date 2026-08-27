#!/usr/bin/env python3
"""
Standalone Gradio demo of the Recherche Data Gouv MCP server, deployable as a
Hugging Face Space.

The three tools mirror the canonical `mcp_server.py` — same names, same
envelope. The deliberate narrowings are `per_page`, clamped to 10 instead of
1000, and the argument lists, which keep the handful of parameters a browser
form can express; everything else is passed through untouched.

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

# The web UI root, for human-facing links.
SITE_URL = BASE_URL[: -len("/api")] if BASE_URL.endswith("/api") else BASE_URL

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
# The listing endpoints have no server-side limit, so the cap is the download.
MAX_ITEMS = 25

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


def metadatablocks(block: str | None = None) -> dict:
    """
    List the Dataverse metadata blocks of Recherche Data Gouv, or retrieve one block schema.

    Args:
        block: Name of a single block — citation, geospatial, socialscience, biomedical, journal, astrophysics, semantics or computationalworkflow. Empty lists every block.

    Returns:
        {"source": "recherche-data-gouv", "command": "metadatablocks", "block": str | null, "data": object, "error": str | null}
    """
    out: dict = {
        "source": "recherche-data-gouv", "command": "metadatablocks",
        "block": block or None, "data": None, "error": None,
    }

    path = "metadatablocks" if not block else f"metadatablocks/{block.strip()}"
    data, error = _get(path)
    if error:
        out["error"] = error
        return out
    out["data"] = data
    return out


def _envelope(command: str, **extra: Any) -> dict:
    out: dict = {
        "source": "recherche-data-gouv", "command": command,
        "total_found": None, "returned": 0, "results": [], "error": None,
    }
    out.update(extra)
    return out


def _normalize_collection(item: dict) -> dict:
    alias = item.get("alias")
    parent = item.get("isPartOf") if isinstance(item.get("isPartOf"), dict) else {}
    return {
        "source": "recherche-data-gouv",
        "type": "dataverse",
        "id": alias or item.get("id"),
        "entity_id": item.get("id"),
        "alias": alias,
        "name": item.get("name"),
        "affiliation": item.get("affiliation"),
        "description": item.get("description"),
        "url": f"{SITE_URL}/dataverse/{alias}" if alias else None,
        "parent_alias": parent.get("identifier"),
        "parent_name": parent.get("displayName"),
        "dataverse_type": item.get("dataverseType"),
        "creation_date": item.get("creationDate"),
    }


def _subtree_total(alias: str, item_type: str) -> int | None:
    data, error = _get("search", [("q", "*"), ("subtree", alias), ("type", item_type), ("per_page", "1")])
    if error or not isinstance(data, dict):
        return None
    return (data.get("data") or {}).get("total_count")


def get_collection(identifier: str, include_counts: bool = True) -> dict:
    """
    Retrieve one Recherche Data Gouv (Dataverse) collection by alias or numeric id.

    Args:
        identifier: Collection alias such as "ecoledesponts", "inrae" or "root", or a numeric id.
        include_counts: Also count the datasets and sub-collections held anywhere beneath it.

    Returns:
        {"source": "recherche-data-gouv", "command": "get_collection", "identifier": str, "total_found": int | null, "returned": int, "results": [{"source": str, "type": "dataverse", "id": str, "alias": str, "name": str, "affiliation": str | null, "description": str | null, "url": str, "parent_alias": str | null, "dataset_count": int | null, "subcollection_count": int | null}], "error": str | null}
    """
    out = _envelope("get_collection", identifier=identifier)
    data, error = _get(f"dataverses/{(identifier or '').strip()}")
    if error:
        out["error"] = error
        return out

    record = _normalize_collection(data.get("data", {}) if isinstance(data, dict) else {})
    if include_counts:
        alias = str(record.get("alias") or identifier)
        record["dataset_count"] = _subtree_total(alias, "dataset")
        record["subcollection_count"] = _subtree_total(alias, "dataverse")
    out["total_found"] = 1
    out["returned"] = 1
    out["results"] = [record]
    return out


def _normalize_content_entry(item: dict) -> dict:
    if item.get("type") == "dataset":
        protocol, authority = item.get("protocol"), item.get("authority")
        identifier = item.get("identifier")
        pid = f"{protocol}:{authority}/{identifier}" if protocol and authority and identifier else None
        return {
            "source": "recherche-data-gouv", "type": "dataset",
            "id": pid or item.get("id"), "entity_id": item.get("id"),
            "persistent_id": pid,
            "title": None,  # /contents carries no dataset titles
            "url": item.get("persistentUrl"),
            "publication_date": item.get("publicationDate"),
            "publisher": item.get("publisher"),
        }
    return {
        "source": "recherche-data-gouv", "type": "dataverse",
        "id": item.get("id"), "entity_id": item.get("id"),
        "title": item.get("title"), "name": item.get("title"),
        "url": None,  # /contents carries no alias, and the web URL needs one
    }


def list_collection_contents(identifier: str, item_type: str | None = None, max_items: int = 25) -> dict:
    """
    List the direct children of a collection: its sub-collections and its datasets.

    One hop down the tree, not the whole sub-tree. The upstream endpoint neither
    paginates nor honours a limit, so max_items clamps the answer here and
    total_found reports the untruncated count. Dataset entries carry a DOI but no
    title, and sub-collection entries a numeric id but no alias: feed either back
    into get_dataset or get_collection. This demo caps max_items at 25.

    Args:
        identifier: Collection alias such as "ecoledesponts", or a numeric id.
        item_type: Keep only "dataverse" or only "dataset". Empty for both.
        max_items: Number of children to return, 1-25 on this demo endpoint.

    Returns:
        {"source": "recherche-data-gouv", "command": "list_collection_contents", "identifier": str, "item_type": str | null, "total_found": int, "returned": int, "truncated": bool, "results": [{"source": str, "type": str, "id": str, "persistent_id": str | null, "title": str | null, "url": str | null, "publication_date": str | null}], "error": str | null}
    """
    out = _envelope("list_collection_contents", identifier=identifier, item_type=item_type or None, truncated=False)
    if item_type and item_type not in ("dataverse", "dataset"):
        out["error"] = 'item_type must be "dataverse", "dataset", or empty'
        return out

    data, error = _get(f"dataverses/{(identifier or '').strip()}/contents")
    if error:
        out["error"] = error
        return out

    items = [i for i in ((data.get("data") if isinstance(data, dict) else None) or []) if isinstance(i, dict)]
    if item_type:
        items = [i for i in items if i.get("type") == item_type]
    capped = items[: max(1, min(int(max_items or 25), MAX_ITEMS))]
    out["total_found"] = len(items)
    out["returned"] = len(capped)
    out["truncated"] = len(items) > len(capped)
    out["results"] = [_normalize_content_entry(i) for i in capped]
    return out


def _cit_primitive(fields: dict, name: str) -> str | None:
    value = (fields.get(name) or {}).get("value")
    return value if isinstance(value, str) else None


def _cit_compound(fields: dict, name: str, *keys: str) -> list[dict]:
    rows = (fields.get(name) or {}).get("value")
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        entry = {k: (row.get(k) or {}).get("value") for k in keys}
        if any(v for v in entry.values()):
            out.append(entry)
    return out


def _normalize_dataset(data: dict) -> dict:
    version = data.get("latestVersion") or {}
    blocks = version.get("metadataBlocks") or {}
    fields = {
        f.get("typeName"): f
        for f in (blocks.get("citation") or {}).get("fields", [])
        if isinstance(f, dict)
    }
    subjects = (fields.get("subject") or {}).get("value")
    descriptions = [d.get("dsDescriptionValue") for d in _cit_compound(fields, "dsDescription", "dsDescriptionValue")]
    license_ = version.get("license")
    if isinstance(license_, dict):
        license_ = license_.get("name")
    return {
        "source": "recherche-data-gouv",
        "type": "dataset",
        "id": version.get("datasetPersistentId") or data.get("persistentUrl"),
        "entity_id": data.get("id"),
        "persistent_id": version.get("datasetPersistentId"),
        "title": _cit_primitive(fields, "title"),
        "authors": _cit_compound(fields, "author", "authorName", "authorAffiliation", "authorIdentifier"),
        "description": "\n\n".join(d for d in descriptions if d) or None,
        "subjects": subjects if isinstance(subjects, list) else [],
        "keywords": [k.get("keywordValue") for k in _cit_compound(fields, "keyword", "keywordValue")],
        "url": data.get("persistentUrl"),
        "publisher": data.get("publisher"),
        "publication_date": data.get("publicationDate"),
        "deposit_date": _cit_primitive(fields, "dateOfDeposit"),
        "depositor": _cit_primitive(fields, "depositor"),
        "production_date": _cit_primitive(fields, "productionDate"),
        "language": (fields.get("language") or {}).get("value"),
        "version": f"{version.get('versionNumber')}.{version.get('versionMinorNumber')}",
        "version_state": version.get("versionState"),
        "last_update": version.get("lastUpdateTime"),
        "license": license_,
        "terms_of_use": version.get("termsOfUse"),
        "file_count": len(version.get("files") or []),
        "metadata_blocks": sorted(blocks.keys()),
    }


def get_dataset(persistent_id: str) -> dict:
    """
    Retrieve the latest published version of one dataset by its persistent id.

    The canonical server also offers an include_raw switch that attaches the
    untouched upstream payload; this demo always omits it, because that payload
    embeds every metadata block and the whole file list.

    Args:
        persistent_id: The DOI in Dataverse form, e.g. "doi:10.57745/AJT1Z3".

    Returns:
        {"source": "recherche-data-gouv", "command": "get_dataset", "persistent_id": str, "total_found": int | null, "returned": int, "results": [{"source": str, "type": "dataset", "id": str, "title": str, "authors": [{"authorName": str, "authorAffiliation": str | null}], "description": str | null, "subjects": [str], "keywords": [str], "url": str, "version": str, "license": str | null, "file_count": int, "metadata_blocks": [str]}], "error": str | null}
    """
    out = _envelope("get_dataset", persistent_id=persistent_id)
    data, error = _get("datasets/:persistentId/", [("persistentId", (persistent_id or "").strip())])
    if error:
        out["error"] = error
        return out

    out["total_found"] = 1
    out["returned"] = 1
    out["results"] = [_normalize_dataset(data.get("data", {}) if isinstance(data, dict) else {})]
    return out


def _normalize_file(item: dict) -> dict:
    data_file = item.get("dataFile") or {}
    file_id = data_file.get("id")
    checksum = data_file.get("checksum") or {}
    return {
        "source": "recherche-data-gouv",
        "type": "file",
        "id": file_id,
        "label": item.get("label"),
        "filename": data_file.get("filename"),
        "description": item.get("description") or data_file.get("description"),
        "content_type": data_file.get("contentType"),
        "size_bytes": data_file.get("filesize"),
        "categories": item.get("categories") or [],
        "restricted": item.get("restricted"),
        "persistent_id": data_file.get("persistentId"),
        "url": data_file.get("pidURL"),
        "download_url": f"{BASE_URL}/access/datafile/{file_id}" if file_id else None,
        "checksum_type": checksum.get("type"),
        "checksum": checksum.get("value"),
        "creation_date": data_file.get("creationDate"),
    }


def list_dataset_files(persistent_id: str, version: str = ":latest-published", max_items: int = 25) -> dict:
    """
    List the files of one dataset version, with sizes, checksums and download URLs.

    Like the collection listing, the upstream endpoint neither paginates nor
    honours a limit, so max_items clamps the answer here and total_found reports
    the untruncated count. This demo caps max_items at 25. download_url is the
    public bytes endpoint; nothing here fetches it.

    Args:
        persistent_id: The DOI in Dataverse form, e.g. "doi:10.57745/AJT1Z3".
        version: ":latest-published", or an explicit number such as "1.0". Drafts need a credential.
        max_items: Number of files to return, 1-25 on this demo endpoint.

    Returns:
        {"source": "recherche-data-gouv", "command": "list_dataset_files", "persistent_id": str, "version": str, "total_found": int, "returned": int, "truncated": bool, "total_size_bytes": int, "results": [{"source": str, "type": "file", "id": int, "filename": str, "content_type": str, "size_bytes": int, "restricted": bool, "download_url": str, "checksum": str | null}], "error": str | null}
    """
    out = _envelope(
        "list_dataset_files", persistent_id=persistent_id,
        version=version or ":latest-published", truncated=False, total_size_bytes=0,
    )
    data, error = _get(
        f"datasets/:persistentId/versions/{out['version']}/files",
        [("persistentId", (persistent_id or "").strip())],
    )
    if error:
        out["error"] = error
        return out

    items = [i for i in ((data.get("data") if isinstance(data, dict) else None) or []) if isinstance(i, dict)]
    capped = items[: max(1, min(int(max_items or 25), MAX_ITEMS))]
    out["total_found"] = len(items)
    out["returned"] = len(capped)
    out["truncated"] = len(items) > len(capped)
    out["total_size_bytes"] = sum((i.get("dataFile") or {}).get("filesize") or 0 for i in items)
    out["results"] = [_normalize_file(i) for i in capped]
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


def _render_blocks(payload: dict) -> str:
    data = payload.get("data")
    inner = data.get("data") if isinstance(data, dict) else None

    # The list endpoint answers with an array of blocks; one block answers with
    # an object carrying its fields.
    if isinstance(inner, list):
        lines = [
            f"**{len(inner)} blocs de métadonnées**",
            "",
            "| Nom | Intitulé | URI du vocabulaire |",
            "|---|---|---|",
        ]
        for b in inner:
            if not isinstance(b, dict):
                continue
            lines.append(
                "| `{n}` | {d} | {u} |".format(
                    n=b.get("name") or "—",
                    d=b.get("displayName") or "—",
                    u=b.get("blockURI") or "—",
                )
            )
        lines += ["", "_Reprenez un `nom` dans le champ ci-dessus pour voir son schéma._"]
        return "\n".join(lines)

    if isinstance(inner, dict):
        fields = inner.get("fields") or {}
        lines = [
            f"**{inner.get('displayName') or inner.get('name')}** — {len(fields)} champs",
            "",
            "| Champ | Intitulé | Type | Multiple |",
            "|---|---|---|---|",
        ]
        for name, f in list(fields.items())[:40]:
            if not isinstance(f, dict):
                continue
            lines.append(
                "| `{n}` | {d} | {t} | {m} |".format(
                    n=name,
                    d=(f.get("displayName") or "—").replace("|", "\\|"),
                    t=f.get("type") or "—",
                    m="oui" if f.get("multiple") else "non",
                )
            )
        if len(fields) > 40:
            lines.append(f"| … | _{len(fields) - 40} champs de plus dans la sortie brute_ | | |")
        return "\n".join(lines)

    return "_Rien à afficher — voir la sortie brute ci-dessous._"


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


def _run_blocks(block):
    payload = metadatablocks((block or "").strip() or None)
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render_blocks(payload), payload


def _render_collection(payload: dict) -> str:
    results = payload.get("results") or []
    if not results:
        return "_Collection introuvable._"
    r = results[0]
    name = r.get("name") or r.get("alias") or "—"
    url = r.get("url")
    lines = [f"## {f'[{name}]({url})' if url else name}", ""]
    if r.get("affiliation"):
        lines += [f"_{r['affiliation']}_", ""]
    rows = [
        ("Alias", f"`{r.get('alias')}`" if r.get("alias") else "—"),
        ("Identifiant interne", r.get("entity_id") or "—"),
        ("Collection parente", r.get("parent_name") or r.get("parent_alias") or "—"),
        ("Type", r.get("dataverse_type") or "—"),
        ("Jeux de données (arborescence)", r.get("dataset_count", "—")),
        ("Sous-collections (arborescence)", r.get("subcollection_count", "—")),
    ]
    lines += ["| | |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in rows]
    if r.get("description"):
        lines += ["", r["description"]]
    return "\n".join(lines)


def _render_contents(payload: dict) -> str:
    results = payload.get("results") or []
    if not results:
        return "_Cette collection n'a pas d'enfant direct de ce type._"
    lines = [
        f"**{payload.get('returned')} sur {payload.get('total_found')} enfants directs**"
        + (" — tronqué" if payload.get("truncated") else ""),
        "",
        "| Type | Identifiant à réutiliser | Libellé | Publié le |",
        "|---|---|---|---|",
    ]
    for r in results:
        ident = r.get("persistent_id") or r.get("entity_id") or "—"
        label = (r.get("title") or "—").replace("|", "\\|")
        url = r.get("url")
        lines.append(
            "| {t} | `{i}` | {l} | {p} |".format(
                t=r.get("type") or "—",
                i=ident,
                l=f"[{label}]({url})" if url and label != "—" else label,
                p=(r.get("publication_date") or "—")[:10],
            )
        )
    lines += ["", "_Un jeu de données n'a pas de titre ici : passez son DOI à `get_dataset`. "
              "Une sous-collection n'a pas d'alias : passez son identifiant à `get_collection`._"]
    return "\n".join(lines)


def _render_dataset(payload: dict) -> str:
    results = payload.get("results") or []
    if not results:
        return "_Jeu de données introuvable._"
    r = results[0]
    title = r.get("title") or "Sans titre"
    url = r.get("url")
    lines = [f"## {f'[{title}]({url})' if url else title}", ""]
    authors = [a.get("authorName") for a in (r.get("authors") or []) if a.get("authorName")]
    if authors:
        lines += [", ".join(authors[:8]) + (" et al." if len(authors) > 8 else ""), ""]
    rows = [
        ("DOI", f"`{r.get('persistent_id')}`" if r.get("persistent_id") else "—"),
        ("Version", f"{r.get('version')} ({r.get('version_state')})"),
        ("Publié le", (r.get("publication_date") or "—")[:10]),
        ("Éditeur", r.get("publisher") or "—"),
        ("Licence", r.get("license") or "voir les conditions d'utilisation"),
        ("Fichiers", r.get("file_count", "—")),
        ("Blocs de métadonnées", ", ".join(f"`{b}`" for b in r.get("metadata_blocks") or []) or "—"),
        ("Disciplines", ", ".join(r.get("subjects") or []) or "—"),
    ]
    lines += ["| | |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in rows]
    keywords = [k for k in (r.get("keywords") or []) if k]
    if keywords:
        lines += ["", "**Mots-clés** — " + ", ".join(keywords[:20])]
    if r.get("description"):
        lines += ["", "### Résumé", "", r["description"][:2000]]
    return "\n".join(lines)


def _human_size(n: Any) -> str:
    if not isinstance(n, (int, float)):
        return "—"
    for unit in ("o", "ko", "Mo", "Go", "To"):
        if n < 1024 or unit == "To":
            return f"{n:.0f} {unit}" if unit == "o" else f"{n:.1f} {unit}"
        n /= 1024
    return "—"


def _render_files(payload: dict) -> str:
    results = payload.get("results") or []
    if not results:
        return "_Cette version ne contient aucun fichier accessible._"
    lines = [
        "**{r} sur {t} fichiers — {s} au total**".format(
            r=payload.get("returned"), t=payload.get("total_found"),
            s=_human_size(payload.get("total_size_bytes")),
        ),
        "",
        "| Fichier | Type | Taille | Accès | Téléchargement |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        name = (r.get("filename") or r.get("label") or "—").replace("|", "\\|")
        dl = r.get("download_url")
        lines.append(
            "| {n} | `{c}` | {s} | {a} | {d} |".format(
                n=name,
                c=r.get("content_type") or "—",
                s=_human_size(r.get("size_bytes")),
                a="restreint" if r.get("restricted") else "ouvert",
                d=f"[octets]({dl})" if dl else "—",
            )
        )
    return "\n".join(lines)


def _run_collection(identifier, include_counts):
    payload = get_collection((identifier or "").strip(), bool(include_counts))
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render_collection(payload), payload


def _run_contents(identifier, item_type, max_items):
    payload = list_collection_contents((identifier or "").strip(), item_type or None, max_items)
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render_contents(payload), payload


def _run_dataset(persistent_id):
    payload = get_dataset((persistent_id or "").strip())
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render_dataset(payload), payload


def _run_files(persistent_id, version, max_items):
    payload = list_dataset_files((persistent_id or "").strip(), (version or "").strip() or ":latest-published", max_items)
    if payload.get("error"):
        raise gr.Error(payload["error"])
    return _render_files(payload), payload


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
                ['authorName:"Dupont"', "dataset", 5],
                ["subject:Agricultural Sciences", "dataset", 5],
                ["climat", "dataverse", 5],
                ["csv", "file", 5],
            ],
            inputs=[q, entity_type, per_page],
            label="Mots-clés, champ Solr, facette, puis les trois types d'entité",
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
            [""] + list(METRIC_BREAKDOWNS),
            value="",
            label="Ventilation (optionnelle) — chacune n'existe que sur certains compteurs",
        )
        metrics_btn = gr.Button("Relever", variant="primary")
        metrics_out = gr.Markdown()
        metrics_raw = gr.JSON(label="Sortie brute de l'outil")

        gr.Examples(
            examples=[
                ["downloads", ""],
                ["datasets", "bySubject"],
                ["datasets", "monthly"],
                ["dataverses", "byCategory"],
                ["files", "byType"],
            ],
            inputs=[category, breakdown],
            label="Un total, puis les quatre ventilations sur le compteur qui les porte",
        )
        metrics_btn.click(
            _run_metrics,
            inputs=[category, breakdown],
            outputs=[metrics_out, metrics_raw],
            api_name=False,
        )

    with gr.Tab("Blocs de métadonnées"):
        block = gr.Textbox(
            label="Bloc (vide = la liste complète)", value="", placeholder="geospatial"
        )
        blocks_btn = gr.Button("Afficher", variant="primary")
        blocks_out = gr.Markdown()
        blocks_raw = gr.JSON(label="Sortie brute de l'outil")

        gr.Examples(
            examples=[[""], ["citation"], ["geospatial"]],
            inputs=[block],
            label="La liste, le bloc obligatoire, puis un bloc disciplinaire",
        )
        blocks_btn.click(
            _run_blocks,
            inputs=[block],
            outputs=[blocks_out, blocks_raw],
            api_name=False,
        )

    with gr.Tab("Collection"):
        coll_id = gr.Textbox(
            label="Alias ou identifiant numérique", value="ecoledesponts", placeholder="inrae"
        )
        coll_counts = gr.Checkbox(
            value=True, label="Compter les jeux de données et sous-collections de l'arborescence"
        )
        coll_btn = gr.Button("Afficher la fiche", variant="primary")
        coll_out = gr.Markdown()
        coll_raw = gr.JSON(label="Sortie brute de l'outil")

        gr.Examples(
            examples=[
                ["ecoledesponts", True],
                ["inrae", True],
                ["root", True],
                ["artsetmetiers", False],
                ["158623", True],
            ],
            inputs=[coll_id, coll_counts],
            label="Un établissement, un grand institut, la racine, une fiche sans comptage, un identifiant numérique",
        )
        coll_btn.click(
            _run_collection, inputs=[coll_id, coll_counts],
            outputs=[coll_out, coll_raw], api_name=False,
        )

    with gr.Tab("Contenu d'une collection"):
        cont_id = gr.Textbox(label="Alias ou identifiant numérique", value="ecoledesponts")
        with gr.Row():
            cont_type = gr.Dropdown(
                ["", "dataverse", "dataset"], value="", label="Type d'enfant"
            )
            cont_max = gr.Slider(1, MAX_ITEMS, value=10, step=1, label="Enfants affichés")
        cont_btn = gr.Button("Lister", variant="primary")
        cont_out = gr.Markdown()
        cont_raw = gr.JSON(label="Sortie brute de l'outil")

        gr.Examples(
            examples=[
                ["ecoledesponts", "", 10],
                ["ecoledesponts", "dataset", 10],
                ["inrae", "dataverse", 25],
                ["root", "dataverse", 25],
                ["158623", "", 10],
            ],
            inputs=[cont_id, cont_type, cont_max],
            label="Les deux types, puis chaque type seul, la racine, et une sous-collection par identifiant",
        )
        cont_btn.click(
            _run_contents, inputs=[cont_id, cont_type, cont_max],
            outputs=[cont_out, cont_raw], api_name=False,
        )

    with gr.Tab("Jeu de données"):
        ds_id = gr.Textbox(
            label="DOI en forme Dataverse", value="doi:10.57745/FJFLYB",
            placeholder="doi:10.57745/XXXXXX",
        )
        ds_btn = gr.Button("Afficher", variant="primary")
        ds_out = gr.Markdown()
        ds_raw = gr.JSON(label="Sortie brute de l'outil")

        gr.Examples(
            examples=[["doi:10.57745/FJFLYB"], ["doi:10.57745/DC3HJE"], ["doi:10.57745/W7FB4W"]],
            inputs=[ds_id],
            label="Trois dépôts publics",
        )
        ds_btn.click(_run_dataset, inputs=[ds_id], outputs=[ds_out, ds_raw], api_name=False)

    with gr.Tab("Fichiers d'un jeu de données"):
        f_id = gr.Textbox(label="DOI en forme Dataverse", value="doi:10.57745/FJFLYB")
        with gr.Row():
            f_version = gr.Textbox(label="Version", value=":latest-published")
            f_max = gr.Slider(1, MAX_ITEMS, value=10, step=1, label="Fichiers affichés")
        f_btn = gr.Button("Lister les fichiers", variant="primary")
        f_out = gr.Markdown()
        f_raw = gr.JSON(label="Sortie brute de l'outil")

        gr.Examples(
            examples=[
                ["doi:10.57745/FJFLYB", ":latest-published", 10],
                ["doi:10.57745/FJFLYB", "1.0", 10],
                ["doi:10.57745/DC3HJE", ":latest-published", 25],
            ],
            inputs=[f_id, f_version, f_max],
            label="La dernière version publiée, une version explicite, un autre dépôt",
        )
        f_btn.click(
            _run_files, inputs=[f_id, f_version, f_max],
            outputs=[f_out, f_raw], api_name=False,
        )

    # The only declared MCP tools. Names match the canonical server's.
    gr.api(search, api_name="search")
    gr.api(metrics, api_name="metrics")
    gr.api(metadatablocks, api_name="metadatablocks")
    gr.api(get_collection, api_name="get_collection")
    gr.api(list_collection_contents, api_name="list_collection_contents")
    gr.api(get_dataset, api_name="get_dataset")
    gr.api(list_dataset_files, api_name="list_dataset_files")


if __name__ == "__main__":
    demo.launch(
        theme=gr.themes.Soft(),  # Gradio 6 moved theme from Blocks() to launch()
        server_name=os.getenv("GRADIO_SERVER_NAME", "0.0.0.0"),
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
        mcp_server=os.getenv("GRADIO_MCP_SERVER", "true").lower() == "true",
    )
