#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ['jsonschema']
# ///

import argparse
import json
import pathlib
from typing import Any

try:
    import jsonschema
except ImportError as e:  # pragma: no cover
    raise RuntimeError("Install jsonschema: pip install jsonschema") from e

_SRC_DIR = pathlib.Path(__file__).resolve().parent
_ROOT_DIR = _SRC_DIR.parent
_PROMPT_PATH = _ROOT_DIR / "prompts" / "build_search_queries.md"
_SCHEMA_PATH = _ROOT_DIR / "schemas" / "build_search_queries.schema.json"


def load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def load_schema() -> dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_output(data: dict[str, Any]) -> dict[str, Any]:
    schema = load_schema()
    try:
        jsonschema.validate(instance=data, schema=schema)
        return {"valid": True, "errors": []}
    except jsonschema.ValidationError as e:
        return {"valid": False, "errors": [str(e)]}


def _read_json(path: str) -> Any:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(prog="build-search-queries")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("prompt", help="Print the task prompt")
    sub.add_parser("schema", help="Print the JSON schema")

    p_validate = sub.add_parser("validate", help="Validate JSON output file")
    p_validate.add_argument("--json-file", required=True)

    args = ap.parse_args()

    if args.cmd == "prompt":
        print(load_prompt())
        return 0

    if args.cmd == "schema":
        print(json.dumps(load_schema(), ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "validate":
        data = _read_json(args.json_file)
        if not isinstance(data, dict):
            print(
                json.dumps(
                    {"valid": False, "errors": ["Top-level JSON must be an object."]},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1
        res = validate_output(data)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("valid") else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
