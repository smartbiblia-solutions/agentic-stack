# Academic Review Engine — Architecture

This document describes a contract-based, host-LLM evidence synthesis pipeline aligned with PRISMA principles.

## Core idea

- Prompts define the **methodological contract**.
- JSON Schemas define the **machine-checkable contract**.
- The host LLM generates structured JSON at each step.
- Validation + retries enforce robustness and interoperability.

## Pipeline (end-to-end)

0. Orchestration (the calling agent — see `agents/literature-research-agent/AGENTS.md`)
1. Query strategy design (external skill: `generate-search-queries`)
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

## Run artifacts

This skill produces JSON objects, not a directory. Each task returns one
schema-validated object keyed on the record's `<source>-<id>`; the caller
decides whether it is persisted and where. `## Artifact contract` in `SKILL.md`
states the record key and the relative destinations a caller may ask for.

Workspace ownership sits one level up, in the agent instructions —
`agents/literature-research-agent/AGENTS.md` is the example: it creates the
research directory, holds it constant across stages, places artifacts, merges
and deduplicates the corpus, and maintains the human-readable manifest. No skill
here opens a workspace or looks for one on disk, so every stage stays usable on
its own with no agent instructions present.
