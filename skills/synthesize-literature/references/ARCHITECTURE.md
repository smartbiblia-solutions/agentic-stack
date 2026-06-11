# Academic Review Engine — Architecture

This document describes a contract-based, host-LLM evidence synthesis pipeline aligned with PRISMA principles.

## Core idea

- Prompts define the **methodological contract**.
- JSON Schemas define the **machine-checkable contract**.
- The host LLM generates structured JSON at each step.
- Validation + retries enforce robustness and interoperability.

## Pipeline (end-to-end)

1. Query strategy design (external skill: `build-search-queries`)
2. Retrieval (external connectors; OpenAlex/HAL/PubMed/WoS)
3. Deduplication (optional)
4. Screening (`screen_study_prisma`)
5. Extraction:
   - `summarize_paper`
   - `extract_metadata`
6. Quality appraisal (`appraise_study_quality`)
7. Synthesis (choose one):
   - PRISMA systematic synthesis (`synthesize_papers_prisma`)
   - Thematic synthesis (`synthesize_papers_thematic`)
   - Chronological synthesis (`synthesize_papers_chronological`)
   - Methodological synthesis (`synthesize_papers_methodological`)

## Extensibility
- Add new tasks by adding `prompts/<task>.md` + `schemas/<task>.schema.json`.
- Keep strict `additionalProperties: false` for auditability.
