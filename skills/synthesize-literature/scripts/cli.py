#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ['jsonschema', 'python-dotenv']
# ///


# ══════════════════════════════════════════════════════════════════════════════
# SECTION : core
# ══════════════════════════════════════════════════════════════════════════════

import json
from typing import Any, Dict
import pathlib

_SRC_DIR = pathlib.Path(__file__).resolve().parent
_ROOT_DIR = _SRC_DIR.parent
_SCHEMAS_DIR = _ROOT_DIR / "schemas"
_PROMPTS_DIR = _ROOT_DIR / "prompts"

try:
    import jsonschema
except ImportError as e:  # pragma: no cover
    raise RuntimeError("Install jsonschema to use validators: pip install jsonschema") from e

def load_prompt(task: str) -> str:
    """Load the prompt markdown contract for a given review task."""
    return (_PROMPTS_DIR / f"{task}.md").read_text(encoding="utf-8")

def load_schema(task: str) -> Dict[str, Any]:
    """Load the JSON schema contract for a given review task."""
    return json.loads((_SCHEMAS_DIR / f"{task}.schema.json").read_text(encoding="utf-8"))

def validate_output(task: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a task output payload against its task-specific JSON schema."""
    schema = load_schema(task)
    try:
        jsonschema.validate(instance=data, schema=schema)
        return {"valid": True, "errors": []}
    except jsonschema.ValidationError as e:
        return {"valid": False, "errors": [str(e)]}

# ══════════════════════════════════════════════════════════════════════════════
# SECTION : facade
# ══════════════════════════════════════════════════════════════════════════════

import argparse
import json
import pathlib
from typing import Any


TASKS = [
    "screen_study_prisma",
    "summarize_paper",
    "extract_metadata",
    "appraise_study_quality",
    "synthesize_papers_prisma",
    "synthesize_papers_thematic",
    "synthesize_papers_chronological",
    "synthesize_papers_methodological",
]


def _read_json(path: str) -> Any:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(prog="academic-review-engine")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List available tasks")

    p_prompt = sub.add_parser("prompt", help="Print the prompt for a task")
    p_prompt.add_argument("--task", required=True, choices=TASKS)

    p_schema = sub.add_parser("schema", help="Print the JSON schema for a task")
    p_schema.add_argument("--task", required=True, choices=TASKS)

    p_validate = sub.add_parser("validate", help="Validate JSON output file against a task schema")
    p_validate.add_argument("--task", required=True, choices=TASKS)
    p_validate.add_argument("--json-file", required=True)

    args = ap.parse_args()

    if args.cmd == "list":
        print(json.dumps({"tasks": TASKS}, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "prompt":
        print(load_prompt(args.task))
        return 0

    if args.cmd == "schema":
        print(json.dumps(load_schema(args.task), ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "validate":
        data = _read_json(args.json_file)
        if not isinstance(data, dict):
            print(json.dumps({"valid": False, "errors": ["Top-level JSON must be an object."]}, ensure_ascii=False, indent=2))
            return 1
        res = validate_output(args.task, data)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("valid") else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
