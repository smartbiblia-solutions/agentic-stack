# Academic Review Engine — Architecture

This document describes a contract-based, host-LLM evidence synthesis pipeline aligned with PRISMA principles.

## Core idea

- Prompts define the **methodological contract**.
- JSON Schemas define the **machine-checkable contract**.
- The host LLM generates structured JSON at each step.
- Validation + retries enforce robustness and interoperability.

## Pipeline (end-to-end)

0. Orchestration (external skill: `orchestrate-literature-review`, optional)
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

A pipeline execution is a directory, not a pile of files: one dated run folder
per research question, one numbered subfolder per stage above, one JSON per
record named on its `<source>-<id>` key at every stage it passes through. The
normative layout is `## Where outputs go` in `SKILL.md`.

The stages are owned by different skills, installed separately and sharing no
state, so the convention is **duplicated** into each of them rather than
referenced from one place. `skills/orchestrate-literature-review/SKILL.md` is the
canonical statement — it also owns the end-to-end sequence and hands the run
folder to each stage — and `skills/generate-search-queries/SKILL.md` repeats it
under `## Where the output goes`. A skill joins a run by
reading the disk: `reviews/<run>/README.md`, whose first line is the research
question verbatim, is the join key. Change the rule in one skill, change it in
the others in the same commit.
