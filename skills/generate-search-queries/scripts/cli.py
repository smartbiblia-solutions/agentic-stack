#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ['jsonschema']
# ///
"""Validate a generated query set against the pack's JSON schema.

Validation is the only thing here that needs code. The prompt and the schema
are files: read them with the file tool, not through a subcommand that shells
out to `cat`.
"""

import argparse
import json
import pathlib
from typing import Any

import jsonschema

_SCHEMA_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "schemas"
    / "generate_search_queries.schema.json"
)


def _short(message: str, limit: int = 200) -> str:
    """jsonschema inlines the offending instance; keep the diagnosis, drop the dump."""
    return message if len(message) <= limit else message[:limit] + "…"


def validate_output(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"valid": False, "errors": ["Top-level JSON must be an object."]}
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = [
        f"{e.json_path}: {_short(e.message)}"
        for e in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    ]
    return {"valid": not errors, "errors": errors}


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="generate-search-queries",
        description="Validate a query set against schemas/generate_search_queries.schema.json",
    )
    ap.add_argument("--json-file", required=True, help="Path to the JSON to validate")
    args = ap.parse_args()

    data = json.loads(pathlib.Path(args.json_file).read_text(encoding="utf-8"))
    result = validate_output(data)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
