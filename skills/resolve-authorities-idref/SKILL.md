---
name: resolve-authorities-idref
description: >
  Resolve and enrich French IdRef person authorities using the Qualinka/Paprika
  authority-resolution services, IdRef attrra records, and linked bibliographic
  references. Use this skill to find the IdRef PPN of a person from any source —
  for prompts like "trouve le PPN de X, auteur de cette monographie", "quel est
  le PPN de X, chercheur à l'Université Paris 1", "find IdRef person", "align
  person to PPN", "authority resolution", "find-ra-idref", or "attrra". It takes
  a name plus any disambiguation clues (works authored, field, affiliation, role,
  year) and returns the best-matching PPN with a confidence status. Prefer this
  skill over search-authorities-idref when the task is person-name authority
  resolution rather than direct Solr authority search. Returns strict JSON.
metadata:
  {
    "version": "0.1.0",
    "author": "smartbiblia",
    "maturity": "experimental",
    "preferred_output": "json",
    "nanobot":  { "always": true, "requires": { "bins": ["uv"], "env": [] } },
    "openclaw": { "always": true, "requires": { "bins": ["uv"], "env": [], "config": [] } }
  }

tags:
  - idref
  - qualinka
  - authorities
  - identity-resolution
  - france
---

# IdRef authority resolution

## When to use / When not to use

**Use this skill when:**

- The task is to resolve a person name to an IdRef PPN.
- The user asks for Qualinka, Paprika, find-ra-idref, attrra, or authority-resolution machinery.
- A person mentioned in any source (a book author, an article author, a researcher with a known affiliation, etc.) must be aligned to a French national authority record.
- Status assignment rules:
  - 'low_confidence': Assign when there are candidate PPNs but with insufficient information to confidently match.
  - 'ambiguous': Assign when multiple candidates exist with similar confidence scores.
  - 'not_found': Assign when no suitable candidates are found after evaluation.
- Assign 'accepted' when the best candidate exceeds score and margin thresholds.

**Do not use this skill when:**

- The task is to retrieve bibliographic catalog records rather than authority records — use search-records-sudoc instead.

---

## Purpose

`scripts/cli.py` is a self-contained CLI (runs with `uv run`) that wraps the
Qualinka/Paprika authority-resolution services and the IdRef references micro
web service. It is designed for person authority control: find candidate PPNs
from a name, enrich one PPN with authority-record evidence, fetch linked
bibliographic references, or align a person mentioned in any source to the most
plausible IdRef PPN.

This skill exposes four logical operations through CLI subcommands:

| Logical operation | CLI subcommand | Purpose |
|---|---|---|
| person authority resolution | `find-person` | Search candidate IdRef person PPNs with Qualinka `find-ra-idref` |
| authority enrichment | `attrra` | Fetch enriched authority-record evidence for one PPN |
| linked bibliographic references | `references` | Fetch IdRef linked references grouped by role |
| person alignment | `align-person` | Combine candidates, attrra, references, and scoring to choose or abstain |

The disambiguation clues fed to `align-person` are source-agnostic: pass
whatever you know about the person — titles of works they produced, their field,
their affiliation, their role, a relevant year, or any free-text context.

## Subcommands

### `find-person` — candidate PPNs from a person name

```bash
uv run ./skills/resolve-authorities-idref/scripts/cli.py find-person \
  --name "Valérie Robert" \
  --max-results 20
```

You can bypass name parsing when the extracted name is ambiguous:

```bash
uv run ./skills/resolve-authorities-idref/scripts/cli.py find-person \
  --first-name "Valérie" \
  --last-name "Robert"
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--name` | string | — | Full name to parse as first/last name |
| `--first-name` | string | — | Explicit first name; overrides parsed first name |
| `--last-name` | string | — | Explicit last name; overrides parsed last name |
| `--max-results` | int | `20` | Maximum candidate PPNs returned |
| `--trace` | flag | off | Include requested URL in stderr |

### `attrra` — enriched authority record by PPN

```bash
uv run ./skills/resolve-authorities-idref/scripts/cli.py attrra \
  --ppn 076642860
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--ppn` | string | **required** | IdRef authority PPN |
| `--trace` | flag | off | Include requested URL in stderr |

### `references` — linked references by PPN

```bash
uv run ./skills/resolve-authorities-idref/scripts/cli.py references \
  --ppn 076642860 \
  --max-docs-per-role 10
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--ppn` | string | **required** | IdRef authority PPN |
| `--max-roles` | int | unlimited | Limit role groups |
| `--max-docs-per-role` | int | `10` | Limit docs per role group |
| `--trace` | flag | off | Include requested URL in stderr |

### `align-person` — score and select a candidate PPN

Pass whatever clues you have. For "find the PPN of an author of a monograph":

```bash
uv run ./skills/resolve-authorities-idref/scripts/cli.py align-person \
  --name "Bruno Latour" \
  --work "Nous n'avons jamais été modernes" \
  --field "sociologie des sciences" \
  --year 1991
```

For "find the PPN of a researcher at a given institution":

```bash
uv run ./skills/resolve-authorities-idref/scripts/cli.py align-person \
  --name "Valérie Robert" \
  --affiliation "Université Paris 1" \
  --field "histoire de l'art" \
  --role "chercheuse"
```

`--work` can be repeated to pass several titles the person produced.

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--name` | string | **required** | Person name |
| `--first-name` / `--last-name` | string | — | Optional parser overrides |
| `--work` | string | — | Title of a work the person produced (book, article, report, …). **Repeatable.** |
| `--field` | string | — | Field, domain, or discipline the person works in |
| `--affiliation` | string | — | Institution or organization the person is affiliated with |
| `--role` | string | — | Role or capacity (author, editor, researcher, …); low ranking weight |
| `--year` | string | — | A year associated with the person or work |
| `--context` | string | — | Any extra free-text clues to disambiguate the person |
| `--max-candidates` | int | `20` | Candidate PPNs to enrich and score |
| `--max-docs-per-role` | int | `20` | Reference docs fetched per role |
| `--reference-top-k` | int | `3` | Top reference similarities averaged |
| `--embedding-model` | string | — | Optional sentence-transformers model; omit for lexical scoring |
| `--accept-threshold` | float | `0.65` | Minimum final score for `accepted` |
| `--margin-threshold` | float | `0.08` | Minimum lead over second candidate |
| `--trace` | flag | off | Include requested URLs in stderr |

> Legacy aliases `--title`/`--subtitle` (→ `--work`), `--discipline` (→ `--field`),
> `--institution`/`--doctoral-school` (→ `--affiliation`), and `--degree-type`
> (→ `--role`) are still accepted for backward compatibility.

## Output

Every subcommand emits strict JSON on stdout. Handled failures still exit `0`
and set an `error` field; callers must inspect it.

### `find-person`

```jsonc
{
  "source": "qualinka_find_ra_idref",
  "query": {
    "name": "Valérie Robert",
    "first_name": "Valérie",
    "last_name": "Robert"
  },
  "found": 14,
  "returned": 14,
  "results": [
    {
      "source": "idref",
      "id": "150899696",
      "ppn": "150899696",
      "title": "Robert, Valérie",
      "authors": null,
      "abstract": null,
      "doi": null,
      "pdf_url": null,
      "url": "https://www.idref.fr/150899696",
      "year": null,
      "date": null,
      "doc_type": "authority-person",
      "journal": null,
      "first_name": "Valérie",
      "last_name": "Robert"
    }
  ],
  "error": null
}
```

### `attrra`

```jsonc
{
  "source": "qualinka_attrra",
  "ppn": "076642860",
  "url": "https://www.idref.fr/076642860",
  "record": {
    "id": "076642860",
    "preferedform": [{"script": "ba", "value": "Robert, Valérie"}],
    "noteGen": ["Titulaire d'un doctorat d'université en médecine spécialisée (Nancy 1,2003)"],
    "source": ["Satisfaction et vécu périopératoire des patients opérés sous anesthésie péribulbaire..."]
  },
  "error": null
}
```

### `align-person`

```jsonc
{
  "source": "idref_qualinka_alignment",
  "status": "accepted",
  "best_ppn": "076642860",
  "best_candidate": {
    "ppn": "076642860",
    "url": "https://www.idref.fr/076642860",
    "score": {
      "final": 0.6783,
      "name": 1.0,
      "attrra_source": 0.7432,
      "attrra_note": 0.3667,
      "references": 0.0,
      "context_match": 0.75
    },
    "evidence": {
      "preferred_forms": ["Robert, Valérie", "Valérie Robert"],
      "best_attrra_source": "Satisfaction et vécu périopératoire...",
      "best_attrra_note": "Titulaire d'un doctorat...",
      "best_references": []
    },
    "errors": []
  },
  "candidates": []
}
```

`status` is one of:

| Status | Meaning |
|---|---|
| `accepted` | Best candidate exceeds score and margin thresholds |
| `ambiguous` | Best candidate is close to the second candidate |
| `low_confidence` | Candidates exist but score is too weak |
| `not_found` | Candidate generation returned no usable PPN |

## Scoring model

`align-person` keeps role out of the score to avoid bias. It scores:

```text
final_score =
  0.40 * name_score
+ 0.25 * attrra_source_similarity
+ 0.15 * attrra_note_similarity
+ 0.15 * references_top_k_similarity
+ 0.05 * context_match
```

`context_match` is an exact-substring boost: it rewards a candidate whose
authority evidence contains the caller's `--affiliation`, `--field`, or `--year`
verbatim.

Use `--embedding-model` when sentence-transformer semantic similarity is
needed. Without it, the CLI uses dependency-free lexical cosine similarity,
which is faster and safer for smoke tests.

## Composition hints

```text
person name + clues (from a catalog record, a document, a web page, …)
  → resolve-authorities-idref align-person
  → optional search-authorities-idref get/references for deeper inspection
  → authority-linked PPN for downstream use
```

Useful pairing:

```text
resolve-authorities-idref find-person
  → resolve-authorities-idref attrra
  → resolve-authorities-idref references
  → resolve-authorities-idref align-person
```

## Environment variables

Set these in `skills/resolve-authorities-idref/scripts/.env` or export them.

| Variable | Default | Purpose |
|---|---|---|
| `IDREF_HTTP_TIMEOUT` | `20.0` | Seconds before timeout |
| `IDREF_MAX_RETRIES` | `2` | Total retry attempts |
| `IDREF_BACKOFF_BASE` | `1.0` | Base seconds for exponential backoff |
| `IDREF_BACKOFF_FACTOR` | `2.0` | Backoff multiplier |
| `IDREF_TRACE` | `0` | Set to `1` for HTTP trace logging |

Retried status codes: `429`, `500`, `502`, `503`, `504`.

## Failure modes

- Exit code remains `0` for handled API failures; inspect `error`.
- `find-ra-idref` can return broad name variants, including compound surnames
  and initials; use the scoring and margin thresholds before accepting a PPN.
- `attrra` fields are sparse and may omit `noteGen` or `source`.
- `references` may return no roles or sparse citations for young authors.
- `align-person` should abstain when evidence is weak or candidates are close.
- Network, DNS, timeout, and malformed JSON errors are surfaced in `error`.

## Files

- `scripts/cli.py` — self-contained uv CLI wrapper
- `scripts/.env.example` — environment variable template
- `references/llm.md` — condensed Qualinka/IdRef API reference for maintenance
