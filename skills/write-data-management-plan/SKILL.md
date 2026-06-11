---
name: wriite-data-management-plan
description: >
  Generates comprehensive, scholarly Data Management Plans (DMPs) adhering 
  to FAIR principles for academic research datasets. Use this skill whenever 
  the user wants to acts as a specialized documentation expert that guides 
  researchers through the entire lifecycle of their data—from creation to archival. 
  It is designed to produce a detailed, rigorous Data Management Plan that satisfies 
  funder requirements (e.g., NIH, NSF) and promotes data stewardship, 
  reproducibility, and ethical compliance.
metadata:
  {
    "version": "0.1.0",
    "author": "smartbiblia",
    "maturity": "experimental",
    "preferred_output": "markdown",
    "openclaw":
      {
        "requires": { },
      },
  }

selection:
  use_when:
    - The task targets ...
    - The user needs to ...
    - The task involves ...
    - The user wants to know ...
  avoid_when:
    - The task requires ...
    - The task targets ...

tags:
  - data-management
  - research
  - academia
  - DMP
  - FAIR
  - metadata
  - archiving
---

# Data Management Plan Writer Skill

## Core Function
Synthesize complex research project details into a formal, industry‑standard Data Management Plan (DMP) that meets funder and institutional requirements while following FAIR principles.

## Required Parameters (Inputs)
The agent must obtain the following information from the user (prompt if missing):
1. **project_title** – Official title of the research project.
2. **data_type** – Description of the data (e.g., survey results, patient records, geospatial imagery, interview transcripts).
3. **research_scope** – Duration and expected deliverables of the research.
4. **sharing_level** – Intended access level (Public/Open, Restricted/IRB‑only, Internal).
5. **data_sensitivity** – Ethical classification (PII, Sensitive Health Data, De‑identified, etc.).

## Execution Protocol
1. **Input Validation** – Verify that all required parameters are present; request any missing items before proceeding.
2. **FAIR Alignment** – Ensure each DMP section addresses the Findable, Accessible, Interoperable, and Reusable principles, either explicitly or implicitly.
3. **Mandatory Sections** – The DMP must contain the following core sections, even if the user provides minimal detail (extrapolate using best practices):
   - **1. Data Description** – Overview of the data, its scope, and lifecycle stage.
   - **2. Data Collection** – Methods, tools, and ethical/IRB approvals.
   - **3. Data Management & Curation** – Version control, quality checks, documentation, and metadata standards.
   - **4. Data Sharing & Access** – Repository links, permission models, licensing, and access procedures.
   - **5. Data Preservation & Archiving** – Long‑term storage strategy, retention period, migration and backup plans.
   - **6. Ethical Considerations** – Consent handling, anonymization techniques, and regulatory compliance.
4. **Optional Enhancements** – Prompt the user for any of the optional parameters below and incorporate the corresponding sections if provided:
   - `repository` – Preferred data repository (e.g., Dryad, Zenodo, institutional archive).
   - `metadata_standard` – Metadata schema (Dublin Core, DataCite, DDI, ISO 19115, etc.).
   - `file_formats` – Preferred open, non‑proprietary formats (CSV, NetCDF, JSON, TXT).
   - `licensing` – Desired reuse license (CC‑BY, CC0, custom).
   - `budget` – Estimated costs for storage, repository fees, and curation.
   - `responsibilities` – Team members responsible for each DMP component.
   - `timeline` – Key milestones for data creation, processing, sharing, and preservation.
   - `risk_assessment` – Potential risks (data loss, privacy breaches) and mitigation strategies.
5. **Expanded Mandatory Sections** – When optional parameters are supplied, enrich the DMP with these additional subsections:
   - **Data Security & Privacy** – Encryption methods, access controls, breach response procedures.
   - **Roles & Responsibilities** – Identify Data Steward, Principal Investigator, and supporting staff; define duties.
   - **Timeline & Milestones** – Align data‑related activities with the overall project schedule.
   - **Budget & Resources** – Detailed cost estimates and justification for external services.
   - **Funder & Institutional Compliance** – Map DMP elements to specific funder mandates and institutional policies.
   - **Review & Update Process** – Frequency of reviews, responsible parties, and versioning scheme.

## Expected Output Format
Produce a single, cohesive Markdown document titled **"Data Management Plan for [Project Title]"**. Use clear H2 (`##`) headings for each mandatory section and H3 (`###`) for any optional subsections. Present information in bulleted lists where appropriate for readability and actionability.
