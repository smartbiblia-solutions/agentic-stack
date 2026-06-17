---
name: synthesize_literature
description: >
  Contract pack for the post-retrieval stages of an academic literature review:
  screening, summarization, metadata extraction, quality appraisal, and synthesis
  (thematic, chronological, methodological, PRISMA). Use this skill whenever the
  task involves evaluating, summarizing, or synthesizing a set of already-retrieved
  academic papers. Each task is addressable independently — use a single task in
  isolation or chain them in a full review pipeline. Always use this skill before
  any synthesis or appraisal step. Do not use it for retrieval — retrieval must
  be handled separately before using this skill.
metadata:
  {
    "version": "1.2.0",
    "author": "smartbiblia",
    "maturity": "stable",
    "preferred_output": "json",
	"nanobot":  { "always": true, "requires": { } },
    "openclaw": { "always": true, "requires": { } }
  }

tags:
  - prisma
  - systematic-review
  - literature-review
  - contract-skill
  - synthesis
---

# synthesize-literature

## When to use / When not to use

**Use this skill when:**

- The task is to screen, summarize, appraise, or synthesize retrieved papers.
- Any post-retrieval step of a literature review pipeline is needed.
- A single atomic task (e.g. summarize one paper, screen one abstract) is needed independently.

**Do not use this skill when:**

- Papers have not yet been retrieved — retrieval must run first.
- The task is only to build a search strategy.

---

## Purpose

A contract pack for the post-retrieval stages of a literature review. Each task
is backed by a methodological prompt and a strict JSON schema. The CLI exposes
three commands: `list`, `prompt`, `schema`, and `validate`.

This skill is a **task library** for post-retrieval analysis. It answers: *how to execute this step correctly*.
Pipeline orchestration (what to do, in what order) is handled at the agent level.

---

## Logical skills exposed by this package

These task identifiers can be addressed independently in the hub registry.
All are backed by the same CLI and contract pack.

| Logical skill | Task name | Purpose |
|---|---|---|
| `screen-studies-prisma` | `screen_study_prisma` | Title/abstract screening — include / exclude / uncertain |
| `summarize-paper` | `summarize_paper` | Structured critical reading note from title + abstract |
| `extract-metadata-paper` | `extract_metadata` | Methodology and concept extraction |
| `appraise-study-quality` | `appraise_study_quality` | Quality appraisal and risk of bias |
| `synthesize-papers-thematic` | `synthesize_papers_thematic` | Cross-cutting theme identification |
| `synthesize-papers-chronological` | `synthesize_papers_chronological` | Evolution of a field over time |
| `synthesize-papers-methodological` | `synthesize_papers_methodological` | Comparison of methodological approaches |
| `synthesize-papers-prisma` | `synthesize_papers_prisma` | Formal PRISMA 2020 systematic synthesis |

---

## Directory structure

```text
./skills/synthesize-literature/
├── scripts/
│   └── cli.py
├── prompts/
│   ├── screen_study_prisma.md
│   ├── summarize_paper.md
│   ├── extract_metadata.md
│   ├── appraise_study_quality.md
│   ├── synthesize_papers_prisma.md
│   ├── synthesize_papers_thematic.md
│   ├── synthesize_papers_chronological.md
│   └── synthesize_papers_methodological.md
├── schemas/
│   ├── screen_study_prisma.schema.json
│   ├── summarize_paper.schema.json
│   ├── extract_metadata.schema.json
│   ├── appraise_study_quality.schema.json
│   ├── synthesize_papers_prisma.schema.json
│   ├── synthesize_papers_thematic.schema.json
│   ├── synthesize_papers_chronological.schema.json
│   └── synthesize_papers_methodological.schema.json
└── references/
    └── ARCHITECTURE.md
```

--- 

## CLI usage

```bash
uv run ./skills/synthesize-literature/scripts/cli.py <command> [flags]
```

### `list` — list available tasks

```bash
uv run ./skills/synthesize-literature/scripts/cli.py list
```

### `prompt` — read the methodological contract for a task

```bash
uv run ./skills/synthesize-literature/scripts/cli.py prompt --task screen_study_prisma
```

### `schema` — read the JSON output schema for a task

```bash
uv run ./skills/synthesize-literature/scripts/cli.py schema --task summarize_paper
```

### `validate` — validate a task output against its schema

```bash
uv run ./skills/synthesize-literature/scripts/cli.py validate \
  --task screen_study_prisma \
  --json-file ./screening_W123.json
```

Returns `{"valid": true, "errors": []}` or `{"valid": false, "errors": [...]}`.
Exit code is `0` on success, `1` on validation failure.

---

## Task reference

| Step | Task | Schema | Input required |
|---|---|---|---|
| 1 | `screen_study_prisma` | `screen_study_prisma.schema.json` | research_question, title, abstract |
| 2 | `summarize_paper` | `summarize_paper.schema.json` | research_question, title, abstract |
| 3 | `extract_metadata` | `extract_metadata.schema.json` | title, abstract |
| 4 | `appraise_study_quality` | `appraise_study_quality.schema.json` | summary from step 2 |
| 5a | `synthesize_papers_thematic` | `synthesize_papers_thematic.schema.json` | research_question, summaries[] |
| 5b | `synthesize_papers_chronological` | `synthesize_papers_chronological.schema.json` | research_question, summaries[] |
| 5c | `synthesize_papers_methodological` | `synthesize_papers_methodological.schema.json` | research_question, summaries[] |
| 5d | `synthesize_papers_prisma` | `synthesize_papers_prisma.schema.json` | research_question, summaries[], screening_log[] |

---

## Rules

- Execute one task at a time.
- Return JSON only — no markdown, no commentary outside the JSON object.
- Validate each output before moving to the next step.
- Retry at most 2 times on schema validation failure, then stop and report the error.
- If information is absent from the input, use `null` — never invent values.

---

## Failure modes

- **Validation failure**: re-prompt the LLM with the schema error message. Max 2 retries, then stop.
- **Abstract unavailable**: screen and summarize on title only — log `"abstract": null` in the record.
- **Schema not found**: check that the task name matches exactly (snake_case, no typos).

See `./references/ARCHITECTURE.md` for the full contract design rationale.