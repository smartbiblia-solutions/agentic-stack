---
name: generate-search-queries
description: >
  Build a structured documentary search strategy from a natural-language research
  question. Decomposes concepts, expands terminology (synonyms, broader/narrower
  terms, related terms), and produces 8–15 validated bilingual (EN/FR) search
  queries as strict JSON. Use this skill at the very start of any literature
  review or retrieval task, before running any retrieval step. Trigger on
  phrases like "build a search strategy for", "find search terms for",
  "systematic review on", "what should I search for", "generate queries about",
  or any request that implies going from a research question to searchable
  expressions. Opens the review run folder the whole pipeline writes into, and
  saves the strategy there rather than loose in the working directory.
version: "0.3.0"
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
    - The task starts from a research question and needs searchable expressions.
    - A bilingual (EN/FR) or multi-database search strategy is required.
    - The user needs concept decomposition and terminology expansion.
    - A systematic review protocol must document its search strategy.
  avoid_when:
    - Queries already exist and the next step is retrieval.
    - The request is a full review from question to synthesis — use
      orchestrate-literature-review, which calls this skill as its first stage.
    - The user supplies keywords directly and only wants a search run.
    - Records have been retrieved and the next step is screening or synthesis.
  prefer_over:
    - ad-hoc-query-writing
  combine_with:
    - orchestrate-literature-review
    - search-works-openalex
    - search-records-hal
    - search-records-sudoc
    - synthesize-literature

tags:
  - systematic-review
  - search-strategy
  - bilingual
  - scholarly
---

# generate-search-queries

## Purpose

A contract pack for a single task: designing a documentary search strategy
from a natural-language research question.

The skill decomposes the question into core concepts, expands each concept
(synonyms, broader terms, narrower terms, related terms), and produces
8–15 bilingual (EN/FR) search queries directly usable in academic databases
(OpenAlex, HAL, PubMed, Web of Science, Scopus).

Output is strict JSON validated against a schema.

---

## When to use / When not to use

**Use this skill when:**

- The task starts from a research question and needs searchable query expressions.
- A bilingual (EN/FR) or multi-database search strategy is required.
- The user needs concept decomposition and terminology expansion.

**Do not use this skill when:**

- Search queries have already been produced and the next step is retrieval.
- The user provides keywords directly and only needs to run a search.

---

## Files

| File | What it is | How to use it |
|---|---|---|
| `prompts/generate_search_queries.md` | The methodological prompt | **Read it directly** |
| `schemas/generate_search_queries.schema.json` | The output schema | **Read it directly** |
| `scripts/cli.py` | The validator | Run it (below) |

Single task, so no `--task` flag anywhere.

## CLI usage

The script does one thing: check the JSON you produced against the schema.

```bash
uv run ./skills/generate-search-queries/scripts/cli.py --json-file ./queries.json
```

Returns `{"valid": true, "errors": []}` or `{"valid": false, "errors": [...]}`,
one line per problem as `<json-path>: <what is wrong>`. Exit code is `0` on
success, `1` on validation failure — the failing exit code is the point of the
script.

---

## Output

The validated JSON has this structure:

```jsonc
{
  "domain": "computer science",
  "core_concepts": ["retrieval-augmented generation", "knowledge graphs"],
  "concept_expansion": {
    "retrieval-augmented generation": {
      "synonyms": ["RAG", "retrieval-augmented LLM"],
      "broader_terms": ["augmented language models"],
      "narrower_terms": ["GraphRAG", "dense passage retrieval"],
      "related_terms": ["vector search", "document retrieval"]
    }
  },
  "queries": [
    {
      "query": "retrieval-augmented generation knowledge graph",
      "lang": "en",
      "type": "core",
      "rationale": "Direct combination of the two core concepts"
    },
    {
      "query": "graphe de connaissances génération augmentée par récupération",
      "lang": "fr",
      "type": "core",
      "rationale": "French equivalent for HAL and francophone databases"
    }
    // 6–13 more queries — 8 minimum, 15 maximum
  ],
  "boolean_logic_guidance": "Run core queries first. Combine with synonym queries using OR.",
  "suggested_filters": {
    "open_access_recommended": true,
    "date_range_recommendation": "2022–present for an emerging topic",
    "discipline_filters": ["computer science", "information retrieval"]
  }
}
```

The `queries[].query` strings are directly usable as search terms in any
academic database retrieval step.

---

## Where the output goes

This skill is normally the **first** step of a review, so unless an orchestrator
is driving it is the one that **creates the run folder** every later skill writes
into. Getting this right here is what keeps the strategy, the retrieved records,
the screening decisions and the synthesis in one directory instead of scattered
across the workspace.

### When the orchestrator is driving

`orchestrate-literature-review` creates the run folder and **hands you the
path**. Use it verbatim: write into it, skip the discovery below, and do not
re-derive the slug — a question paraphrased twice slugifies twice, and the review
ends up in two folders.

Called on its own, this skill does the discovery itself, exactly as follows.

### The run folder

```text
reviews/<YYYY-MM-DD>-<topic-slug>/
├── README.md            ← run manifest; its first line is the join key
└── 00-strategy/
    └── search_queries.json      ← this skill's validated output
```

- `reviews/` is the default root under the current working directory; a folder
  the user names wins over it.
- `<YYYY-MM-DD>` is today. `<topic-slug>` is the research question compressed to
  3–6 meaningful words, lowercase kebab-case, stopwords dropped —
  `tool-augmented-llm-agents`, not `queries-final`.
- Later stages add `01-corpus/`, `02-screening/`, `03-summaries/`,
  `04-metadata/`, `05-appraisal/`, `06-synthesis/`. Do not create them here;
  create only what you write.

**This layout is duplicated, not referenced.** `orchestrate-literature-review`
states it canonically; it is repeated here because the skills install
separately and this one must work with the orchestrator absent. Change one,
change the other.

### Before creating: look for an existing run

The downstream skills are installed separately and share no state with this one,
so when no orchestrator supplies the path, the folder is found on disk — never
carried in memory:

```bash
ls -d reviews/*/ 2>/dev/null && head -1 reviews/*/README.md
```

1. **The user named a folder** — use it.
2. **A `README.md` first line matches this research question** — that run already
   exists; write `00-strategy/search_queries.json` into it.
3. **Otherwise** — create the folder, write `README.md`, then the strategy.

Never open a second folder for a question that already has one.

### README.md

Write it as the folder is created. Its **first line is the research question
verbatim**, because that line is how every downstream skill recognises this run:

```markdown
# <research question, verbatim>

- Started: 2026-08-26
- Strategy: 12 queries (8 en, 4 fr) — `00-strategy/search_queries.json`
- Stages run: 00-strategy
```

Each later stage appends its own line. Announce the path once, in your reply, so
the retrieval step that follows has it.

---

## Composition hints

```
generate-search-queries          ← this skill: always first
      ↓
  → search-works-openalex        ← run the `en` queries here
  → search-records-hal           ← run the `fr` queries here
  → search-records-sudoc         ← run the `fr` queries against library holdings
      ↓
    synthesize-literature        ← screen, appraise, synthesize
```

Every skill in that chain writes into the same run folder this one opens —
retrieval into `01-corpus/`, `synthesize-literature` into `02-screening/` and
beyond. Name the path in your reply so the next step inherits it.

Feed `queries[].query` straight into the retrieval skills' `--query` / `--q`
flags, routing on `queries[].lang`. `suggested_filters` maps onto the retrieval
flags: `open_access_recommended` → `--oa`, `date_range_recommendation` →
`--date-from` / `--year-from`.

---

## Rules

- Locate or create the run folder first (see **Where the output goes**), and
  save the validated JSON as `00-strategy/search_queries.json` inside it. A
  strategy file written to the working-directory root is a bug.
- Read `prompts/generate_search_queries.md`, produce JSON, validate. Fix and
  re-validate on failure.
- Max 2 retries on schema validation failure, then stop and report the error.
- Return JSON only — no prose, no markdown outside the JSON object.

---

## Failure modes

- **Validation failure**: re-prompt the LLM with the schema error message.
  Max 2 retries, then stop.
- **Fewer than 8 queries generated**: schema validation will catch this —
  the `queries` array requires `minItems: 8`.
- **Prompt file not found**: it lives at
  `./skills/generate-search-queries/prompts/generate_search_queries.md`.
- **Two candidate run folders for the same question**: pick the one whose
  `README.md` first line matches exactly, and tell the user the other exists.
  Do not merge them silently.
- **Question refined after the folder exists**: that is a new review. Say so
  and open a new folder rather than editing the join key.