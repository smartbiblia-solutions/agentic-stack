#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Report the state of a review run folder, so the pipeline can resume.

Two things need code here, and nothing else does:

  - finding the run that belongs to a research question, across a `reviews/`
    root, by reading each run's join key (the first line of its README);
  - joining a stage's files against the corpus to say which records are still
    missing from which stage.

Both are cross-file bookkeeping over folders that can hold hundreds of records —
the kind of counting an agent gets wrong by one and then trusts. Everything else
about the pipeline (what a stage means, which prompt to read, when to stop) is
in SKILL.md, because it is instruction, not computation.
"""

import argparse
import json
import pathlib
import re
import sys
from typing import Any

# Per-record stages, in pipeline order. 00-strategy, 01-corpus and 06-synthesis
# are run-level: one artefact each, not one per record.
RECORD_STAGES = ["02-screening", "03-summaries", "04-metadata", "05-appraisal"]
RUN_STAGES = ["00-strategy", "01-corpus", "06-synthesis"]
ALL_STAGES = ["00-strategy", "01-corpus", *RECORD_STAGES, "06-synthesis"]

# A record screened out is not expected downstream; `uncertain` goes to
# full-text review, so it is.
CARRIED_FORWARD = {"include", "uncertain"}

# Files that live in a stage folder without being a record.
NON_RECORD_FILES = {"corpus.json", "screening-log.json", "search_queries.json", "report.md"}


def record_key(source: str | None, identifier: str | None) -> str:
    """`<source>-<id>`, lowercased, non-alphanumerics collapsed to a single dash."""
    raw = "-".join(p for p in (source, identifier) if p)
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", raw.lower())).strip("-")


def _question(run_dir: pathlib.Path) -> str | None:
    """The join key: the first line of README.md, minus its heading marker."""
    readme = run_dir / "README.md"
    if not readme.is_file():
        return None
    for line in readme.read_text(encoding="utf-8").splitlines():
        if line.strip():
            return line.lstrip("#").strip()
    return None


def _stage_records(stage_dir: pathlib.Path) -> set[str]:
    if not stage_dir.is_dir():
        return set()
    return {
        p.stem
        for p in stage_dir.rglob("*.json")  # rglob: a stage may be split one level deep
        if p.name not in NON_RECORD_FILES
    }


def _corpus_records(run_dir: pathlib.Path) -> tuple[set[str], str | None]:
    """Record keys from the deduplicated corpus, else from the widest stage present."""
    corpus = run_dir / "01-corpus" / "corpus.json"
    if corpus.is_file():
        try:
            data = json.loads(corpus.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return set(), f"01-corpus/corpus.json is not valid JSON: {exc}"
        results = data.get("results") if isinstance(data, dict) else data
        if isinstance(results, list):
            keys = {record_key(r.get("source"), r.get("id")) for r in results if isinstance(r, dict)}
            return {k for k in keys if k}, None
    widest: set[str] = set()
    for stage in RECORD_STAGES:
        widest |= _stage_records(run_dir / stage)
    return widest, None


def _decisions(run_dir: pathlib.Path) -> dict[str, str]:
    out: dict[str, str] = {}
    stage = run_dir / "02-screening"
    if not stage.is_dir():
        return out
    for path in stage.rglob("*.json"):
        if path.name in NON_RECORD_FILES:
            continue
        try:
            decision = json.loads(path.read_text(encoding="utf-8")).get("decision")
        except (json.JSONDecodeError, AttributeError):
            decision = None
        if isinstance(decision, str):
            out[path.stem] = decision
    return out


def list_runs(root: pathlib.Path) -> dict[str, Any]:
    if not root.is_dir():
        return {"root": str(root), "total_found": 0, "returned": 0, "results": [], "error": None}
    runs = []
    for run_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        runs.append(
            {
                "run_dir": str(run_dir),
                "question": _question(run_dir),
                "stages": [s for s in ALL_STAGES if (run_dir / s).is_dir()],
            }
        )
    return {"root": str(root), "total_found": len(runs), "returned": len(runs), "results": runs, "error": None}


def run_state(run_dir: pathlib.Path) -> dict[str, Any]:
    if not run_dir.is_dir():
        return {
            "run_dir": str(run_dir), "question": None, "stages": {}, "total_found": None,
            "returned": 0, "results": [], "complete": 0, "next_action": None,
            "error": f"No such run folder: {run_dir}",
        }

    corpus, error = _corpus_records(run_dir)
    decisions = _decisions(run_dir)
    present = {stage: _stage_records(run_dir / stage) for stage in RECORD_STAGES}
    active = [s for s in RECORD_STAGES if (run_dir / s).is_dir()]

    gaps, complete = [], 0
    for key in sorted(corpus):
        expected = []
        for stage in active:
            # Downstream stages only apply to records screening carried forward.
            if stage != "02-screening" and decisions.get(key, "include") not in CARRIED_FORWARD:
                continue
            expected.append(stage)
        missing = [s for s in expected if key not in present[s]]
        if missing:
            gaps.append({"record": key, "decision": decisions.get(key), "missing": missing})
        else:
            complete += 1

    stages = {}
    for stage in ALL_STAGES:
        path = run_dir / stage
        stages[stage] = {
            "present": path.is_dir(),
            "files": sum(1 for p in path.rglob("*") if p.is_file()) if path.is_dir() else 0,
        }

    next_action = None
    for stage in active:
        blocked = sum(1 for g in gaps if stage in g["missing"])
        if blocked:
            next_action = f"{stage}: {blocked} record(s) missing"
            break
    if next_action is None and not (run_dir / "06-synthesis").is_dir():
        next_action = "06-synthesis: no synthesis written yet"

    return {
        "run_dir": str(run_dir),
        "question": _question(run_dir),
        "stages": stages,
        "total_found": len(corpus) or None,
        "returned": len(gaps),
        "results": gaps,
        "complete": complete,
        "next_action": next_action,
        "error": error,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="orchestrate-literature-review",
        description="List review runs, or report which records are missing from which stage.",
    )
    ap.add_argument("--root", default="reviews", help="Where run folders live (default: reviews)")
    ap.add_argument("--run-dir", help="Report this run's state instead of listing runs")
    args = ap.parse_args()

    state = run_state(pathlib.Path(args.run_dir)) if args.run_dir else list_runs(pathlib.Path(args.root))
    json.dump(state, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
