---
name: generate_search_queries
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
metadata:
  {
    "version": "0.1.0",
    "author": "smartbiblia",
    "maturity": "stable",
    "preferred_output": "json",
	"nanobot":  { "always": true, "requires": { } },
    "openclaw": { "always": true, "requires": { } }
  }

tags:
  - systematic-review
  - search-strategy
  - bilingual
  - scholarly
---

# generate-search-queries

## When to use / When not to use

**Use this skill when:**

- The task starts from a research question and needs searchable query expressions.
- A bilingual (EN/FR) or multi-database search strategy is required.
- The user needs concept decomposition and terminology expansion.

**Do not use this skill when:**

- Search queries have already been produced and the next step is retrieval.
- The user provides keywords directly and only needs to run a search.

---

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

Use this skill at the **start** of any literature review or retrieval task,
before running any database search.

Do not use it if the user already has search terms and only needs to run a
retrieval.

---

## CLI usage

This skill exposes a single task. There is no `--task` flag.

```bash
# Read the methodological prompt
uv run ./skills/generate-search-queries/scripts/cli.py prompt

# Read the output schema
uv run ./skills/generate-search-queries/scripts/cli.py schema

# Validate the produced JSON
uv run ./skills/generate-search-queries/scripts/cli.py validate \
  --json-file ./queries.json
```

Returns `{"valid": true, "errors": []}` or `{"valid": false, "errors": [...]}`.
Exit code is `0` on success, `1` on validation failure.

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

## Rules

- Read the prompt, produce JSON, validate. Fix and re-validate on failure.
- Max 2 retries on schema validation failure, then stop and report the error.
- Return JSON only — no prose, no markdown outside the JSON object.

---

## Failure modes

- **Validation failure**: re-prompt the LLM with the schema error message.
  Max 2 retries, then stop.
- **Fewer than 8 queries generated**: schema validation will catch this —
  the `queries` array requires `minItems: 8`.
- **Prompt file not found**: check that the file is at
  `./skills/generate-search-queries/prompts/generate_search_queries.md`
  (note: the CLI internally maps to this path).