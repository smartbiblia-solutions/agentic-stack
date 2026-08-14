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
  expressions.
version: "0.2.0"
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
    - The user supplies keywords directly and only wants a search run.
    - Records have been retrieved and the next step is screening or synthesis.
  prefer_over:
    - ad-hoc-query-writing
  combine_with:
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

Feed `queries[].query` straight into the retrieval skills' `--query` / `--q`
flags, routing on `queries[].lang`. `suggested_filters` maps onto the retrieval
flags: `open_access_recommended` → `--oa`, `date_range_recommendation` →
`--date-from` / `--year-from`.

---

## Rules

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