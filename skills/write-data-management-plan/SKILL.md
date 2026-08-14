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
version: "0.4.0"
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

This skill is **prose only**. There is no script, no JSON schema and nothing to
install: the deliverable is a Markdown document written by the agent, and every
rule it must respect is on this page. Read it, gather the inputs, check the
table in *Coherence checks* before drafting, write the plan.

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
never invent one:

| Parameter | What it is |
|---|---|
| `project_title` | Official title of the research project |
| `data_type` | Nature of the data (survey results, patient records, geospatial imagery, interview transcripts…) |
| `research_scope` | Duration and expected deliverables |
| `sharing_level` | `public` \| `restricted` \| `internal` \| `embargoed` |
| `data_sensitivity` | `none` \| `de-identified` \| `pii` \| `sensitive-health` \| `other-regulated` |

Two more become required depending on the last two:

| Parameter | Required when |
|---|---|
| `anonymization_procedure` | `data_sensitivity` is `pii`, `sensitive-health` or `other-regulated` — how identifiers are removed or replaced |
| `access_procedure` | `sharing_level` is `restricted` or `embargoed` — how a third party requests and obtains access |

Optional parameters enrich the plan when supplied. Ask for them once, then
proceed with whatever the user gives:

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

## Coherence checks

Run these three checks **before** writing a word of the plan. They are where a
DMP actually goes wrong, and each one is a conversation with the user, not
something to resolve on your own:

| Check | Stop when | What to do |
|---|---|---|
| Completeness | Any of the five required parameters is still unknown | Ask for it. Do not draft around it. |
| Sensitivity vs sharing | `data_sensitivity` is `pii` / `sensitive-health` / `other-regulated` **and** `sharing_level` is `public` | Say so plainly: identifiable data cannot be shared openly. Resolve with the user before drafting. |
| Gated access | `sharing_level` is `restricted` or `embargoed` **and** no `access_procedure` | Ask how a third party requests access. A gated dataset with no documented route fails review. |

Also required when the data is sensitive: an `anonymization_procedure`. Never
write that sensitive data will be shared openly.

---

## Execution protocol

1. **Collect the five required parameters**, plus the conditional ones the
   answers make necessary. Ask once for the optional parameters.
2. **Run the coherence checks** above. If one stops you, ask the user; do not
   paper over the conflict in prose.
3. **Write the six mandatory sections** as Markdown, even when the user gives
   minimal detail — extrapolate from disciplinary best practice.
4. **Add the optional subsections** for whichever optional parameters were
   supplied.
5. **Close with `## Assumptions`** — one entry per default you applied, with
   its basis, so the researcher can tell their facts from your defaults.

---

## Output

A single cohesive Markdown document titled **"Data Management Plan for
\<Project Title\>"**, `##` per mandatory section, `###` for optional
subsections, bulleted lists where they aid readability.

Mandatory sections, in this order:

1. **Data Description** — the data, its scope, lifecycle stage, expected volume.
2. **Data Collection** — methods, instruments, ethical/IRB approvals.
3. **Data Management & Curation** — version control, quality checks,
   documentation, metadata standard.
4. **Data Sharing & Access** — repository, permission model, licence, access
   procedure.
5. **Data Preservation & Archiving** — long-term storage, retention period,
   migration, backup.
6. **Ethical Considerations** — consent, anonymization, regulatory compliance
   (GDPR, IRB).

Optional subsections, added when the corresponding parameters were supplied:
Data Security & Privacy, Roles & Responsibilities, Timeline & Milestones,
Budget & Resources, Funder & Institutional Compliance, Review & Update Process.

The document closes with `## Assumptions`, each entry giving the statement and
the basis it rests on:

```markdown
## Assumptions

- **10-year retention after project end.** Default for ANR-funded
  social-science projects; not supplied by the researcher.
```

Each section addresses the FAIR principles it bears on in prose — no
compliance table; a funder reads paragraphs.

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
- Mark every extrapolated recommendation as an assumption; the researcher must
  be able to tell their facts from your defaults.
- Prefer open, non-proprietary formats and a certified repository unless the
  user's constraints rule them out; justify the exception in the section that
  needs it.
- Sensitive data (PII, health) requires an explicit anonymization and access
  procedure — never write "data will be shared openly" over sensitive data.
- Write in the user's language, at the register of a grant application:
  specific, sober, ready to paste into a funder form.
- The deliverable is Markdown. Do not emit a JSON intermediate; there is
  nothing downstream that consumes one.
