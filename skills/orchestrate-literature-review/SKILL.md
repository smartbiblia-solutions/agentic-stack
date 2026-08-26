---
name: orchestrate-literature-review
description: >
  Run a complete literature review end to end: open one dated run folder, design
  the search strategy, retrieve from the bibliographic sources, deduplicate,
  screen, summarize, appraise and synthesize — each step delegated to its own
  skill, every artefact written into that one folder. Use this skill when the
  request is a whole review ("do a literature review on X", "systematic review
  of Y", "find and synthesize the literature about Z") rather than a single
  step, or when a review already started must be resumed. Do not use it when the
  user asks for exactly one stage — call that stage's skill directly.
version: "0.1.0"
author: smartbiblia
maturity: experimental
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
    - The request is a full literature review, from a question to a synthesis.
    - Several stages must run in order and share their outputs.
    - An interrupted review must be resumed without redoing completed stages.
    - Results from several sources must be merged and deduplicated before screening.
  avoid_when:
    - Only a search strategy is needed — use generate-search-queries.
    - Only screening, summarizing or synthesis is needed — use synthesize-literature.
    - Only records are needed — use search-works-openalex, search-records-hal,
      search-records-sudoc or search-theses-fr directly.
  prefer_over:
    - ad-hoc-pipeline-improvisation
  combine_with:
    - generate-search-queries
    - search-works-openalex
    - search-records-hal
    - search-records-sudoc
    - search-theses-fr
    - synthesize-literature

tags:
  - literature-review
  - orchestration
  - prisma
  - pipeline
---

# orchestrate-literature-review

## Purpose

The skills of a literature review are deliberately separate: a query designer, a
handful of source connectors, a post-retrieval contract pack. Each is usable
alone, and each knows nothing about the others' state. This skill is the only
one that holds the review as a *whole*: it decides which stages run, in what
order, and — the part that actually breaks without it — it owns **the run
folder** every other skill writes into.

It performs no retrieval and no analysis of its own. Every stage is delegated to
the skill that owns it. What this skill contributes is the sequence, the shared
directory, and the ability to resume.

---

## When to use / When not to use

**Use this skill when:**

- The request is a whole review: question in, synthesis out.
- Several stages must run in order and hand results to each other.
- A review interrupted halfway must continue without redoing finished stages.

**Do not use this skill when:**

- The user asked for one stage. Call that skill directly — every one of them
  works standalone, and wrapping a single step in a pipeline only adds a folder.
- The corpus is already screened and only a synthesis is wanted:
  `synthesize-literature` handles that alone.

---

## The run folder

One review is one folder. This skill creates it, names it, and passes the path
to every stage.

```text
reviews/<YYYY-MM-DD>-<topic-slug>/
├── README.md                     ← run manifest; first line = the join key
├── 00-strategy/search_queries.json
├── 01-corpus/                    ← one file per source × query, plus corpus.json
├── 02-screening/                 ← one JSON per record, plus screening-log.json
├── 03-summaries/                 ← one JSON per record
├── 04-metadata/                  ← one JSON per record
├── 05-appraisal/                 ← one JSON per record
└── 06-synthesis/                 ← synthesize_papers_<mode>.json, report.md
```

- `<topic-slug>`: the research question in 3–6 meaningful words, lowercase
  kebab-case, stopwords dropped. Readable a month later.
- Per-record files are named on the record key `<source>-<id>`, lowercased with
  non-alphanumerics collapsed to a dash — `openalex-w2741809807.json` — and the
  **same name is reused at every stage**, which is what lets the stages be
  joined without an index.
- Create only the stages the run executes.

**This layout is duplicated, not referenced.** `generate-search-queries` and
`synthesize-literature` each state it in their own `SKILL.md`, because they are
installed separately and must work with this skill absent. This file is the
canonical statement; change it here, change it there in the same commit.

### Finding an existing run

```bash
uv run ./skills/orchestrate-literature-review/scripts/cli.py --root reviews
```

Lists every run folder with its question and the stages it already has. Reuse a
run whose `question` matches the one you were given; otherwise create a new
folder. Never open a second folder for a question that already has one, and
never suffix `-2` — two folders for one review splits the evidence, which is
worse than the flat directory this convention replaces.

---

## Pipeline

Run the stages in order. Announce the run folder once, before stage 0, and use
that exact path in every delegated step — a stage never re-derives the slug.

| # | Stage | Skill that owns it | Writes |
|---|---|---|---|
| 0 | Search strategy | `generate-search-queries` | `00-strategy/search_queries.json` |
| 1 | Retrieval | `search-works-openalex`, `search-records-hal`, `search-records-sudoc`, `search-theses-fr` | `01-corpus/<source>-<query-slug>.json` |
| 2 | Merge + deduplicate | this skill | `01-corpus/corpus.json` |
| 3 | Screening | `synthesize-literature` · `screen_study_prisma` | `02-screening/<key>.json`, `screening-log.json` |
| 4 | Summarization | `synthesize-literature` · `summarize_paper` | `03-summaries/<key>.json` |
| 5 | Metadata extraction *(optional)* | `synthesize-literature` · `extract_metadata` | `04-metadata/<key>.json` |
| 6 | Quality appraisal *(optional)* | `synthesize-literature` · `appraise_study_quality` | `05-appraisal/<key>.json` |
| 7 | Synthesis | `synthesize-literature` · `synthesize_papers_*` | `06-synthesis/…` |

Stage rules:

- **Stage 0** — ask the user for the question if it is not already explicit.
  Route `queries[].lang` to the sources: `en` to OpenAlex, `fr` to HAL, Sudoc and
  theses.fr.
- **Stage 1** — the connectors print JSON to stdout; **you** save it, one file
  per source × query, into `01-corpus/`. They know nothing about the run folder.
- **Stage 2** — merge on `doi`, falling back to a normalized title when the DOI
  is absent. Keep every record's `source` and `id`; the key `<source>-<id>` of
  the *retained* record names its files downstream. Record how many were dropped
  — the PRISMA count comes from here.
- **Stages 3–6** — one task, one record, one file. Validate each output with
  `synthesize-literature`'s validator before writing the next stage. A record
  screened out stops at stage 3; `uncertain` continues to full-text review.
- **Stage 7** — pick the mode from the request: PRISMA when the user asked for a
  systematic review, thematic by default otherwise. `synthesize_papers_prisma`
  additionally requires `02-screening/screening-log.json`.
- **Optional stages are optional.** Skip 5 and 6 unless the request needs
  methodology comparison or risk-of-bias, and say in `README.md` that they were
  skipped.

### Between every stage

```bash
uv run ./skills/orchestrate-literature-review/scripts/cli.py --run-dir reviews/<run>
```

`next_action` is what to do next; `results` lists exactly which records are
missing from which stage. Resume from that, not from memory: after an
interruption it is the only account of the run that is still true.

---

## CLI usage

The script does bookkeeping over the run folder, and nothing else — the pipeline
logic is this file.

```bash
# Which runs exist, and what is in them
uv run ./skills/orchestrate-literature-review/scripts/cli.py

# What is still missing from one run
uv run ./skills/orchestrate-literature-review/scripts/cli.py \
  --run-dir reviews/2026-08-26-tool-augmented-llm-agents
```

`--root` defaults to `reviews`. Exit code is always `0`; failures come back in
`error`.

---

## Output

Listing runs:

```jsonc
{
  "root": "reviews",
  "total_found": 2,
  "returned": 2,
  "results": [
    {
      "run_dir": "reviews/2026-08-26-tool-augmented-llm-agents",
      "question": "How do tool-augmented LLM agents handle failure recovery?",
      "stages": ["00-strategy", "01-corpus", "02-screening", "03-summaries"]
    }
  ],
  "error": null
}
```

One run's state — `results` holds only the records with a gap, so an empty
`results` with a non-zero `complete` means the stage set is finished:

```jsonc
{
  "run_dir": "reviews/2026-08-26-tool-augmented-llm-agents",
  "question": "How do tool-augmented LLM agents handle failure recovery?",
  "stages": {
    "00-strategy": {"present": true, "files": 1},
    "01-corpus":   {"present": true, "files": 5},
    "02-screening":{"present": true, "files": 338},
    "03-summaries":{"present": true, "files": 29},
    "04-metadata": {"present": false, "files": 0},
    "05-appraisal":{"present": false, "files": 0},
    "06-synthesis":{"present": false, "files": 0}
  },
  "total_found": 337,          // records in 01-corpus/corpus.json
  "returned": 12,              // records with at least one gap
  "results": [
    {"record": "openalex-w2741809807", "decision": "include", "missing": ["03-summaries"]}
  ],
  "complete": 325,
  "next_action": "03-summaries: 12 record(s) missing",
  "error": null
}
```

`total_found` is `null` when no corpus and no stage folder exist yet.

---

## Composition hints

```
orchestrate-literature-review        ← this skill: owns the run folder and the order
      ├─ generate-search-queries     ← 0. question → 8–15 bilingual queries
      ├─ search-works-openalex       ← 1. en queries
      ├─ search-records-hal          ← 1. fr queries
      ├─ search-records-sudoc        ← 1. fr queries, library holdings
      ├─ search-theses-fr            ← 1. French doctoral theses
      ├─ (merge + deduplicate)       ← 2. this skill
      └─ synthesize-literature       ← 3–7. screen, summarize, appraise, synthesize
```

Every one of those skills also runs standalone. Called alone, each finds or
creates the run folder itself, using the same rules as above. Called from here,
it is **handed** the path and must not re-derive it — that is the only
difference, and it exists because a question paraphrased twice slugifies twice.

---

## Rules

- Locate or create the run folder before stage 0, print its path, and pass that
  exact path to every stage.
- One stage at a time. Check the run state before moving on, and never start a
  stage whose input the previous one has not written.
- Delegate. This skill does not screen, summarize or appraise — if you are
  writing a synthesis prompt here, you skipped `synthesize-literature`.
- Update `README.md` at the end of each stage: counts, decisions, what was
  skipped. It is the only human-readable account of the run.
- Stop and ask the user before stage 3 if the corpus is empty or implausibly
  large (say, past a few thousand records) — screening is the expensive stage,
  and a bad query set is cheaper to fix than to screen.

---

## Failure modes

- **A stage's skill is not installed**: say which one and stop at that stage.
  What is already written stays valid — the run resumes once it is available.
- **Retrieval returns nothing**: the connectors report upstream failure in
  `error` and still exit 0. Read it, record it in `README.md`, and revisit the
  query set before screening rather than screening an empty corpus.
- **Interrupted run**: re-run with `--run-dir`; `next_action` and `results` say
  exactly where to restart. Never restart a finished stage.
- **`corpus.json` missing**: the state report falls back to the widest per-record
  stage present, so `total_found` may undercount. Write `corpus.json` at stage 2.
- **Question refined mid-run**: that is a different review. Say so and open a new
  run folder rather than editing the join key in `README.md`.
