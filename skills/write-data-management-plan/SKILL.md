---
name: write-data-management-plan
description: >
  Write a comprehensive, funder-ready Data Management Plan (DMP) for a research
  project, aligned with the FAIR principles. Use this skill whenever the user
  asks to draft, review, or complete a data management plan, a "plan de gestion
  de données" (PGD), or the data-management section of a grant application
  (ANR, Horizon Europe, NIH, NSF). Trigger on phrases like "write a DMP",
  "data management plan", "plan de gestion de données", "how will I archive my
  data", "which repository should I deposit in", "FAIR data plan", or any
  request about the lifecycle of research data from collection to archival.
  Produces a structured Markdown document covering description, collection,
  curation, sharing, preservation and ethics.
version: "0.2.0"
author: smartbiblia
maturity: experimental
preferred_output: markdown
metadata:
  {
    "openclaw": {
      "always": true,
      "requires": { "bins": [], "env": [], "config": [] }
    }
  }

selection:
  use_when:
    - The user needs a Data Management Plan for a grant application or an institutional review.
    - A research project must document how its data will be collected, curated, shared and archived.
    - An existing DMP has to be reviewed or completed against the FAIR principles.
    - The user asks which repository, metadata standard or licence fits their data.
  avoid_when:
    - The task is to find or retrieve datasets rather than to plan their management.
    - The task is a literature review or a bibliographic search.
    - The user needs the software management plan (code, not data) — the deliverable differs.
  prefer_over:
    - freeform-document-drafting
  combine_with:
    - synthesize-literature

tags:
  - data-management
  - research
  - academia
  - DMP
  - FAIR
  - metadata
  - archiving
---

# write-data-management-plan

## Purpose

A methodological contract for producing a formal Data Management Plan. It turns
a handful of project facts into an industry-standard DMP that satisfies funder
and institutional requirements while addressing the FAIR principles (Findable,
Accessible, Interoperable, Reusable) in every section.

This skill has no CLI: it is a prompt contract executed by the agent. The
deliverable is a single Markdown document.

---

## When to use / When not to use

**Use this skill when:**

- The user needs a DMP for a grant application or an institutional review.
- A project must document the lifecycle of its data, from collection to archival.
- An existing DMP must be reviewed or completed against the FAIR principles.
- The user asks which repository, metadata standard or licence fits their data.

**Do not use this skill when:**

- The task is to *find* datasets rather than to plan their management.
- The task is a literature review or a bibliographic search — use
  `generate-search-queries` and `synthesize-literature`.
- The deliverable is a software management plan; code stewardship is a
  different contract.

---

## Input

Five parameters are required. Ask for any that are missing before drafting —
do not invent them:

1. **project_title** — official title of the research project.
2. **data_type** — nature of the data (survey results, patient records,
   geospatial imagery, interview transcripts…).
3. **research_scope** — duration and expected deliverables.
4. **sharing_level** — intended access level (public/open, restricted/IRB-only,
   internal).
5. **data_sensitivity** — ethical classification (PII, sensitive health data,
   de-identified…).

Optional parameters enrich the plan when supplied; prompt for them once, then
proceed with whatever the user provides:

| Parameter | Purpose |
|---|---|
| `repository` | Target repository (Zenodo, Dryad, Recherche Data Gouv, institutional archive) |
| `metadata_standard` | Metadata schema (Dublin Core, DataCite, DDI, ISO 19115) |
| `file_formats` | Preferred open, non-proprietary formats (CSV, NetCDF, JSON, TXT) |
| `licensing` | Reuse licence (CC-BY, CC0, custom) |
| `budget` | Storage, repository fees, curation costs |
| `responsibilities` | Who owns each component of the plan |
| `timeline` | Milestones for creation, processing, sharing, preservation |
| `risk_assessment` | Risks (data loss, privacy breach) and mitigations |

---

## Execution protocol

1. **Validate the input** — confirm the five required parameters; request any
   missing item before proceeding.
2. **Align on FAIR** — every section must address Findable, Accessible,
   Interoperable and Reusable, explicitly or implicitly.
3. **Write the mandatory sections** — all six, even when the user gives minimal
   detail; extrapolate from disciplinary best practice and say so.
4. **Add the optional subsections** for whichever optional parameters were
   supplied.
5. **State the assumptions** — anything extrapolated rather than given must be
   flagged so the researcher can correct it.

---

## Output

A single cohesive Markdown document titled
**"Data Management Plan for \<Project Title\>"**, using `##` for each mandatory
section and `###` for optional subsections, with bulleted lists where they aid
readability.

Mandatory sections:

1. **Data Description** — overview of the data, scope and lifecycle stage.
2. **Data Collection** — methods, tools, ethical/IRB approvals.
3. **Data Management & Curation** — version control, quality checks,
   documentation, metadata standards.
4. **Data Sharing & Access** — repository, permission model, licensing,
   access procedure.
5. **Data Preservation & Archiving** — long-term storage, retention period,
   migration and backup.
6. **Ethical Considerations** — consent, anonymization, regulatory compliance.

Optional subsections, added when the corresponding parameters are supplied:
Data Security & Privacy, Roles & Responsibilities, Timeline & Milestones,
Budget & Resources, Funder & Institutional Compliance, Review & Update Process.

---

## Composition hints

```
[project facts from the researcher]
  → write-data-management-plan     ← this skill
      ↓
    DMP Markdown document
      ↓
    funder submission / institutional review
```

The plan is a standalone deliverable, not a pipeline stage: it consumes project
facts, not retrieved records. When a DMP must cite disciplinary norms or an
existing corpus, run the retrieval skills and `synthesize-literature` first and
feed the conclusions in as context.

---

## Rules

- Never invent a required parameter — ask for it.
- Mark every extrapolated recommendation as such; the researcher must be able
  to tell their facts from your defaults.
- Prefer open, non-proprietary formats and a certified repository unless the
  user's constraints rule them out; justify the exception in the plan.
- Sensitive data (PII, health) requires an explicit anonymization and access
  procedure — never write "data will be shared openly" over sensitive data.
