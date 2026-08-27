---
name: synthesize-literature
description: >
  Contract pack for the post-retrieval stages of an academic literature review:
  screening, summarization, metadata extraction, quality appraisal, and synthesis
  (thematic, chronological, methodological, PRISMA). Use this skill whenever the
  task involves evaluating, summarizing, or synthesizing a set of already-retrieved
  academic papers. Each task is addressable independently — use a single task in
  isolation or chain them in a full review pipeline. Always use this skill before
  any synthesis or appraisal step. Each task returns one schema-validated JSON
  object; where it is persisted is the calling agent's decision. Do not use it
  for retrieval — retrieval must be handled separately before using this skill.
version: "1.4.0"
author: smartbiblia
maturity: stable
preferred_output: json
metadata:
  {
    "openclaw": {
      "always": true,
      "requires": { "bins": ["uv"], "env": [], "config": [] }
    }
  }

selection:
  use_when:
    - Papers have been retrieved and must be screened, summarized or appraised.
    - A thematic, chronological, methodological or PRISMA synthesis is requested.
    - A single post-retrieval task is needed in isolation (screen one abstract, summarize one paper).
    - A systematic review needs a documented, schema-validated methodology.
  avoid_when:
    - No papers have been retrieved yet; run a retrieval skill first.
    - The task is only to build a search strategy; use generate-search-queries.
    - The task is bibliographic format conversion.
  prefer_over:
    - freeform-summarization
  combine_with:
    - generate-search-queries
    - search-works-openalex
    - search-records-hal
    - search-records-sudoc

tags:
  - prisma
  - systematic-review
  - literature-review
  - contract-skill
  - synthesis
---

# synthesize-literature

## Purpose

A contract pack for the post-retrieval stages of a literature review. Each task
is backed by a methodological prompt and a strict JSON schema, which the agent
reads directly from `prompts/` and `schemas/`. The CLI does one thing:
`validate` the JSON the agent produced.

This skill is a **task library** for post-retrieval analysis. It answers: *how to execute this step correctly*.
Pipeline orchestration (what to do, in what order) is handled at the agent level.

---

## When to use / When not to use

**Use this skill when:**

- The task is to screen, summarize, appraise, or synthesize retrieved papers.
- Any post-retrieval step of a literature review pipeline is needed.
- A single atomic task (e.g. summarize one paper, screen one abstract) is needed independently.

**Do not use this skill when:**

- Papers have not yet been retrieved — retrieval must run first.
- The task is only to build a search strategy.

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

## Reading a task's contract

Every task `<t>` in the table above has exactly two files, both named after it:

- `prompts/<t>.md` — the methodological contract. **Read the file directly.**
- `schemas/<t>.schema.json` — the output schema. **Read the file directly.**

There is no subcommand for either; opening a file is not something a script
should do on your behalf.

## Artifact contract

Each task returns one schema-validated JSON object. The skill does not create,
discover, resume, or own a project, review, or run directory, and it never
infers a parent workspace from the research question.

**Destinations are supplied by the caller.** When the calling agent gives a
destination, write there. When it does not, return the JSON and persist nothing.

**The record key.** Name a record-level artifact `<source>-<id>`, lowercased,
every non-alphanumeric character collapsed to `-`: `openalex-w2741809807.json`,
`hal-hal-04312345.json`. When a record has no source id, fall back to its DOI on
the same rule (`doi-10-1145-3targ-2024-0117.json`). Reuse the identical key at
every stage the record passes through — that is what lets a caller join the
stages without an index.

**Recommended relative paths**, when the calling agent asks for the conventional
layout of a multi-stage review. They are relative to a workspace root the caller
owns; this skill does not create that root.

| Task | Relative destination |
|---|---|
| `screen_study_prisma` | `02-screening/<record-key>.json` |
| screening log | `02-screening/screening-log.json` |
| `summarize_paper` | `03-summaries/<record-key>.json` |
| `extract_metadata` | `04-metadata/<record-key>.json` |
| `appraise_study_quality` | `05-appraisal/<record-key>.json` |
| `synthesize_papers_<mode>` | `06-synthesis/<task-name>.json` |

Synthesis outputs are named after the task, since there is at most one of each:
`synthesize_papers_prisma.json`, `synthesize_papers_thematic.json`.

One record, one file, one stage. Never concatenate several records into one
file, and never put counts, dates, or a word such as `final` in a filename.

---

## CLI usage

The script does one thing: check the JSON you produced against a task's schema.

```bash
uv run ./skills/synthesize-literature/scripts/cli.py \
  --task screen_study_prisma \
  --json-file ./openalex-w2741809807.json
```

Returns `{"valid": true, "errors": []}` or `{"valid": false, "errors": [...]}`,
one line per problem as `<json-path>: <what is wrong>`. Exit code is `0` on
success, `1` on validation failure — the failing exit code is the point of the
script. `--task` accepts the eight task names listed above; `--help` prints
them.

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

## Output

The script returns a verdict object:

```jsonc
{ "valid": true,  "errors": [] }
{ "valid": false, "errors": ["$: 'decision' is a required property"] }
```

The *task* outputs themselves are produced by the agent, not by the CLI: each
one is a JSON object conforming to `schemas/<task>.schema.json`. Always
validate them before chaining to the next step.

---

## Composition hints

```
generate-search-queries          ← build the query set
      ↓
  search-works-openalex / search-records-hal / search-records-sudoc
      ↓
synthesize-literature            ← this skill
  screen_study_prisma            ← 1. include / exclude / uncertain
  summarize_paper                ← 2. critical reading note
  extract_metadata               ← 3. method and concept extraction
  appraise_study_quality         ← 4. risk of bias
  synthesize_papers_*            ← 5. thematic / chronological / methodological / PRISMA
```

That chain is data compatibility, not a sequence this skill drives: whether the
upstream steps ran, and where anything is stored, is the calling agent's
business.

The retrieval skills all emit the common record schema, so `title`, `abstract`
and `doi` feed the screening and summarization tasks directly. Merge and
deduplicate on `doi` across sources before screening; keep the screening log if
a PRISMA synthesis is the goal, since `synthesize_papers_prisma` requires it.

---

## Rules

- Execute one task at a time.
- Return JSON only — no markdown, no commentary outside the JSON object.
- Validate each output before moving to the next step.
- Retry at most 2 times on schema validation failure, then stop and report the error.
- When persisting, write one JSON file per record per stage, keyed on
  `<source>-<id>`; never concatenate several records into one file, and never
  overwrite a stage's output with the next stage's.
- If information is absent from the input, use `null` — never invent values.

---

## Failure modes

- **Validation failure**: re-prompt the LLM with the schema error message. Max 2 retries, then stop.
- **Abstract unavailable**: screen and summarize on title only — log `"abstract": null` in the record.
- **Schema not found**: check that the task name matches exactly (snake_case, no typos).
- **Record with no identifier**: key the file on a slug of its title, truncated
  to 60 characters, and report the collision risk to the caller.

See `./references/ARCHITECTURE.md` for the full contract design rationale.