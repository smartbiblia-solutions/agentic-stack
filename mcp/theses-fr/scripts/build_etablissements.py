#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ['httpx']
# ///
"""Rebuild ../etablissements.json, the establishment referential of the server.

theses.fr has no endpoint mapping an establishment's name to its short code
(`codeEtab`) and its IdRef PPN, so the server ships this table. It is a compact
projection of the IdRef/ABES alignment kept in
gegedenice/humatheque-idref-qualinka-api: one entry per ABES code, with the
names theses.fr displays, the IdRef labels of the same PPN as aliases, and the
predecessor/successor codes. Codes rarely change; rerun this when they do.

  uv run mcp/theses-fr/scripts/build_etablissements.py
"""

from __future__ import annotations

import json
import pathlib

import httpx

SOURCE_URL = ("https://raw.githubusercontent.com/gegedenice/humatheque-idref-qualinka-api/"
              "refs/heads/main/idref_org_alignment/organisations_full.json")
TARGET = pathlib.Path(__file__).resolve().parent.parent / "etablissements.json"


def _codes(links: list[dict]) -> list[str]:
    return sorted({c for link in links or [] for c in link.get("codes") or []})


def main() -> None:
    data = httpx.get(SOURCE_URL, timeout=60, follow_redirects=True).raise_for_status().json()
    orgs = data.get("organisations") or {}
    entries = []
    for e in data["etablissements_abes"]:
        name = (e.get("nom_theses") or e.get("nom") or "").replace("‎", "").strip()
        org = orgs.get(e.get("ppn") or "") or {}
        aliases = {a.strip() for a in [e.get("nom"), org.get("label_officiel"), *(org.get("labels") or [])]
                   if a and a.strip() and a.strip() != name}
        entries.append({
            "code": e["code"],
            "nom": name,
            "ppn": e.get("ppn"),
            "debut": e.get("date_debut"),
            "fin": e.get("date_fin"),
            "avant": _codes(e.get("voir_avant")),
            "apres": _codes(e.get("voir_apres")),
            "alias": sorted(aliases),
        })
    entries.sort(key=lambda x: x["code"])
    # One entry per line: small diffs when a code changes, still plain JSON.
    lines = ",\n".join(json.dumps(x, ensure_ascii=False) for x in entries)
    TARGET.write_text(f'{{"source": {json.dumps(SOURCE_URL)},\n"etablissements": [\n{lines}\n]}}\n',
                      encoding="utf-8")
    print(f"{len(entries)} establishments -> {TARGET}")


if __name__ == "__main__":
    main()
