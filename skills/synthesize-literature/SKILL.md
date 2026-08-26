---
name: synthesize-literature
description: >
  Contract pack for the post-retrieval stages of an academic literature review:
  screening, summarization, metadata extraction, quality appraisal, and synthesis
  (thematic, chronological, methodological, PRISMA). Use this skill whenever the
  task involves evaluating, summarizing, or synthesizing a set of already-retrieved
  academic papers. Each task is addressable independently — use a single task in
  isolation or chain them in a full review pipeline. Always use this skill before
  any synthesis or appraisal step. All outputs are written into a single dated
  review folder with one numbered subfolder per pipeline stage — never loose in
  the working directory. Do not use it for retrieval — retrieval must be handled
  separately before using this skill.
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
    - The request is a full review from question to synthesis — use
      orchestrate-literature-review, which delegates these tasks back here.
    - The task is only to build a search strategy; use generate-search-queries.
    - The task is bibliographic format conversion.
  prefer_over:
    - freeform-summarization
  combine_with:
    - orchestrate-literature-review
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
is backed by a methodological prompt and a strict JSON schema. The CLI exposes
four commands: `list`, `prompt`, `schema` and `validate`.

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

## Where outputs go

Every file this skill produces belongs to **one review run**, and every run owns
**one folder**. Nothing is written loose in the working directory.

### The run folder

```text
reviews/<YYYY-MM-DD>-<topic-slug>/
```

- `reviews/` is the default root, created under the current working directory.
  If the user names a directory, use theirs instead — the internal layout below
  does not change.
- `<YYYY-MM-DD>` is the date the run starts, so successive runs on the same
  question sort chronologically instead of colliding.
- `<topic-slug>` is the research question compressed to 3–6 meaningful words,
  lowercase kebab-case, stopwords dropped. It must be readable a month later:
  `tool-augmented-llm-agents`, not `run-2` or `review-final`.

Ask the user for the folder label only if the research question has not been
stated. Otherwise derive it and say, in one line, where you are writing.

### Inside the run folder

```text
reviews/2026-08-26-tool-augmented-llm-agents/
├── README.md                     ← run manifest, written first, updated last
├── 00-strategy/                  ← generate-search-queries output (upstream)
│   └── search_queries.json
├── 01-corpus/                    ← retrieval output (upstream)
│   ├── openalex-tool-use.json        one file per source × query
│   ├── hal-agents-outillage.json
│   └── corpus.json                   merged + deduplicated on doi
├── 02-screening/
│   ├── openalex-w2741809807.json     one screen_study_prisma output per record
│   └── screening-log.json            the PRISMA log: every decision, in order
├── 03-summaries/
│   └── openalex-w2741809807.json     one summarize_paper output per record
├── 04-metadata/
│   └── openalex-w2741809807.json     one extract_metadata output per record
├── 05-appraisal/
│   └── openalex-w2741809807.json     one appraise_study_quality output per record
└── 06-synthesis/
    ├── synthesize_papers_thematic.json
    └── report.md                     the prose deliverable, if one is asked for
```

Rules for the tree:

- **Stage folders are numbered** in pipeline order, so the directory listing
  reads as the method. Create only the stages the run actually executes — a
  screening-only run has `01-corpus/` and `02-screening/` and nothing else.
- **One record, one file, same name at every stage.** The file name is the
  record key `<source>-<id>`, lowercased, every non-alphanumeric character
  collapsed to `-`: `openalex-w2741809807.json`, `hal-hal-04312345.json`. When
  a record has no source id, fall back to its DOI on the same rule
  (`doi-10-1145-3targ-2024-0117.json`). The identical name across
  `02-screening/`, `03-summaries/` and `05-appraisal/` is what lets an agent
  join the stages without an index.
- **Synthesis outputs are named after the task**, since there is at most one of
  each per run: `synthesize_papers_prisma.json`,
  `synthesize_papers_thematic.json`.
- **Never encode meaning in an ad-hoc prefix.** `exact_react.json` and
  `search_gorilla.json` in a flat directory say nothing about which stage, which
  run, or which record they belong to; the same content as
  `02-screening/openalex-w2741809807.json` says all three.

### When to add a subfolder

Add exactly one level under a stage folder, and only for a reason that is in the
data:

- the corpus is split across **several sub-questions or arms** —
  `03-summaries/<subquestion-slug>/`;
- the run keeps sources deliberately separate rather than merged —
  `02-screening/<source>/`;
- a stage holds more than roughly 80 files and one of the two splits above
  applies.

Do not nest deeper, and do not shard alphabetically or by batch: a second level
buys nothing an agent cannot get from the file name.

**This layout is duplicated, not referenced.** `orchestrate-literature-review`
states it canonically; it is repeated here because the skills install
separately and this one must work with the orchestrator absent. Change one,
change the other.

### Joining a run another skill started

When `orchestrate-literature-review` is driving, it **hands you the run folder**
— use that path verbatim and skip the rest of this section.

On your own, you have to find it. The upstream skills — `generate-search-queries`,
the `search-*` connectors — are installed separately and share no state with this
one, so the run folder is discovered on disk, never carried in memory. This skill
is rarely the first to write, so look before creating anything:

```bash
ls -d reviews/*/ 2>/dev/null && head -1 reviews/*/README.md
```

Then, in order:

1. **An orchestrator or the user named a folder** — use it, full stop. An
   explicit path always wins.
2. **A run folder exists whose `README.md` first line is this research question**
   — that is the run. Reuse it, whatever its date.
3. **A run folder was created earlier in this session** — reuse it. The path you
   printed when you created it is the handle; do not re-derive the slug, since a
   question paraphrased twice slugifies twice.
4. **Nothing matches** — create the folder and its `README.md`, and print the
   path in your next message. That line is what the next skill, and the user,
   will refer back to.

Never create a second folder for a question that already has one, and never
suffix `-2`. Two folders for one review is the failure this convention exists to
prevent — worse than the flat directory, because the evidence is now split.

The `README.md` first line is the join key, so it is written **verbatim from the
user's question** and never edited afterwards. Refine the question mid-run and
you have started a different review; say so and open a new folder deliberately.

### README.md — the run manifest

Write it when the folder is created, update it when the run ends. It is the only
prose file the pipeline always produces, and it is what makes the folder
readable without opening a single JSON:

```markdown
# <research question, verbatim>

- Started: 2026-08-26 · Completed: 2026-08-26
- Sources: openalex, hal
- Retrieved 412 → deduplicated 337 → screened 337 → included 41
- Synthesis: thematic (`06-synthesis/synthesize_papers_thematic.json`)
- Stages run: 00-strategy, 01-corpus, 02-screening, 03-summaries, 06-synthesis

## Notes
Exclusions concentrated on non-empirical position papers; see the screening log.
```

Counts go in the README, never in a file name.

---

## CLI usage

The script does one thing: check the JSON you produced against a task's schema.

```bash
uv run ./skills/synthesize-literature/scripts/cli.py \
  --task screen_study_prisma \
  --json-file reviews/2026-08-26-tool-augmented-llm-agents/02-screening/openalex-w2741809807.json
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

Retrieval writes into `01-corpus/` of the same run folder, so the whole review —
queries, records, decisions, synthesis — is one directory an agent or a human
can read end to end.

The retrieval skills all emit the common record schema, so `title`, `abstract`
and `doi` feed the screening and summarization tasks directly. Merge and
deduplicate on `doi` across sources before screening; keep the screening log if
a PRISMA synthesis is the goal, since `synthesize_papers_prisma` requires it.

---

## Rules

- Locate or create the run folder before the first task — see **Joining a run
  another skill started** — and write every file inside it, at the stage path
  defined in **Where outputs go**. A file written to the
  working directory root is a bug, whatever it contains.
- Execute one task at a time.
- Return JSON only — no markdown, no commentary outside the JSON object.
- Validate each output before moving to the next step.
- Retry at most 2 times on schema validation failure, then stop and report the error.
- Write one JSON file per record per stage, keyed on `<source>-<id>`; never
  concatenate several records into one file, and never overwrite a stage's
  output with the next stage's.
- If information is absent from the input, use `null` — never invent values.

---

## Failure modes

- **Validation failure**: re-prompt the LLM with the schema error message. Max 2 retries, then stop.
- **Abstract unavailable**: screen and summarize on title only — log `"abstract": null` in the record.
- **Schema not found**: check that the task name matches exactly (snake_case, no typos).
- **Run folder already exists**: a re-run on the same day and question resumes
  it — re-validate what is there, write only what is missing. Never start
  `…-tool-augmented-llm-agents-2/`.
- **Record with no identifier**: key the file on a slug of its title, truncated
  to 60 characters, and record the collision risk in `README.md`.

See `./references/ARCHITECTURE.md` for the full contract design rationale.