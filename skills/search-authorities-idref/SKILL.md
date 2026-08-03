---
name: search-authorities-idref
description: >
  Search and retrieve authority records from IdRef, the French national authority
  file maintained by ABES, through its Solr index, and list the bibliographic
  references linked to an authority. Use this skill to find an IdRef authority for
  a person, an organization, a conference, a place, a title or a Rameau subject, to
  retrieve an authority by PPN, or to inspect the documents attached to one. Prefer
  it over generic web search whenever the target is IdRef or French authority
  control, and prefer resolve-persons-idref when the task is deciding which
  candidate is a given person rather than searching. Returns strict JSON.
version: "0.1.0"
author: smartbiblia
maturity: experimental
preferred_output: json
metadata:
  {
    "openclaw": { "always": true, "requires": { "bins": ["uv"] } }
  }

selection:
  use_when:
    - An IdRef authority must be found by name, title, subject or affiliation.
    - An IdRef PPN is known and its authority record or linked bibliography is needed.
    - The task concerns French academic authority data maintained by ABES.
    - A Solr expert query must be run against the IdRef index.
  avoid_when:
    - A person must be disambiguated among candidates rather than searched; use resolve-persons-idref.
    - Bibliographic records are wanted rather than authority records; use search-records-sudoc.
    - The task is scholarly article discovery; use search-works-openalex or search-records-hal.
  prefer_over:
    - generic-web-search
  combine_with:
    - resolve-persons-idref
    - search-records-sudoc

tags:
  - idref
  - authorities
  - abes
  - france
  - library
  - scholarly
---

# search-authorities-idref

## Purpose

IdRef is the authority file behind the French academic network: every person,
organization, conference, place, work title and Rameau subject used in Sudoc and
in institutional repositories has a record there, identified by a PPN. This skill
gives an agent direct, structured access to that file — searching it, fetching a
record by PPN, and following an authority to the documents attached to it.

`scripts/cli.py` is self-contained (`uv run`, no install step) and wraps two
public ABES endpoints:

- the **Solr authority index** at `https://www.idref.fr/Sru/Solr`
- the **`references` micro web service** at
  `https://www.idref.fr/services/references/<PPN>.json`

Both are anonymous, so the skill reads nothing from the environment. Output is
strict JSON on stdout, normalized to the common record schema.

## When to use / When not to use

Use this skill when the target is an IdRef authority: searching by name, title,
subject or affiliation; retrieving a record from a known PPN; or listing the
bibliography linked to an authority, grouped by role.

Do not use it when:

- The task is to decide *which* IdRef candidate corresponds to a person named in
  a document — that is identity resolution, and `resolve-persons-idref` makes
  that judgement from evidence this skill does not gather.
- The task is to retrieve bibliographic records rather than authority records —
  use `search-records-sudoc`.
- The task is general scholarly discovery — use `search-works-openalex` or
  `search-records-hal`.

## Subcommands

### `search` — authority search via Solr

Expert form, for a raw Solr query:

```bash
uv run skills/search-authorities-idref/scripts/cli.py search \
  --query 'persname_t:(Bourdieu AND Pierre)' \
  --max-results 5
```

Simple form, which builds the query for you:

```bash
uv run skills/search-authorities-idref/scripts/cli.py search \
  --index persname_t --text 'Victor Hugo' --max-results 5
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--query` | string | — | Raw Solr query. Takes precedence over `--index`/`--text`. |
| `--index` | string | `all` | Solr index, e.g. `persname_t`, `corpname_t`, `ppn_z`, `all`. |
| `--text` | string | — | Plain text searched in `--index`; several words are joined with `AND`. |
| `--max-results` | int | `10` | Solr `rows`. |
| `--start` | int | `0` | Offset for pagination. |
| `--sort` | string | `score desc` | Solr `sort`, e.g. `affcourt_z asc`. |
| `--fields` | comma list | `id,ppn_z,recordtype_z,affcourt_z` | Solr `fl`. |

`total_found` reports what IdRef holds for the query, `returned` what came back —
compare the two before concluding a search is exhaustive, and page with `--start`
or raise `--max-results` when they differ. When a precise name yields nothing, retry
on a broader index (`all`) or on fewer name parts; IdRef preferred forms often carry
initials, dates or accents the user did not type.

### `get` — one authority by PPN

```bash
uv run skills/search-authorities-idref/scripts/cli.py get --ppn 027715078
```

Runs a `ppn_z:<PPN>` Solr lookup and returns the single matching authority, or
`result: null` when the PPN is unknown.

### `references` — bibliography linked to an authority

```bash
uv run skills/search-authorities-idref/scripts/cli.py references --ppn 02686018X
```

Returns the documents attached to the authority, grouped by role (author,
editor, thesis supervisor…) with their MARC21 and UNIMARC role codes.

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--ppn` | string | **required** | IdRef PPN. |
| `--max-roles` | int | all | Limit the number of role groups. |
| `--max-docs-per-role` | int | `10` | Limit the documents listed in each group. |

## Output

### `search` and `get`

Records follow the common record schema, plus `ppn`, `recordtype`, `solr_id` and
`raw`. An authority is a name rather than a publication, so the bibliographic
fields are structurally `null` — they are kept so results merge with those of the
other `search-*` skills without transformation.

```jsonc
{
  "source": "idref",
  "query": "persname_t:(Bourdieu AND Pierre)",
  "total_found": 1,
  "returned": 1,
  "start": 0,
  "results": [
    {
      "source": "idref",
      "id": "027715078",
      "ppn": "027715078",
      "title": "Bourdieu, Pierre (1930-2002)",
      "authors": null,
      "abstract": null,
      "doi": null,
      "pdf_url": null,
      "url": "https://www.idref.fr/027715078",
      "year": null,
      "date": null,
      "doc_type": "a",
      "journal": null,
      "recordtype": "a",
      "solr_id": "91588",
      "raw": { }
    }
  ],
  "error": null
}
```

`get` returns the same record under a single `result` key instead of `results`.

### `references`

```jsonc
{
  "source": "idref",
  "ppn": "02686018X",
  "roles": [
    {
      "role_name": "Auteur",
      "marc21_code": "aut",
      "unimarc_code": "070",
      "count": 146,
      "docs": [
        {
          "citation": "Commanditaire, auteur, artiste dans les inscriptions médiévales / Robert Favreau",
          "referentiel": "sudoc",
          "id": "189894652",
          "ppn": "189894652",
          "url": "https://www.sudoc.fr/189894652",
          "uri": "https://www.sudoc.fr/189894652/id",
          "raw": { }
        }
      ]
    }
  ],
  "error": null
}
```

`count` is the total IdRef holds for that role; `docs` is capped by
`--max-docs-per-role`.

## Failure modes

- **Exit code is always 0.** Upstream failures come back in the `error` field
  next to empty results, so an agent reads the failure instead of a stack trace.
- **No authority found** is not an error: `search` returns `results: []` and
  `get` returns `result: null`, both with `error: null`.
- **Malformed Solr query**: IdRef answers HTTP 200 with an empty body rather than
  a 4xx, so there is nothing to parse. The CLI reports that explicitly in `error`
  and does not retry — check the parentheses and the field suffixes in `--query`.
- **Unknown PPN on `references`**: the micro service answers normally with no
  roles, so the result is `roles: []` and `error: null`, not a failure.
- **Sparse fields**: IdRef Solr documents vary; request more with `--fields` when
  a normalized field you need is `null`, and read `raw` for anything unmapped.
- Transient failures (429, 500, 502, 503, 504) are retried twice with exponential
  backoff and jitter before being reported.

## Composition hints

```text
resolve-persons-idref            ← when the person must first be disambiguated
  → search-authorities-idref     ← this skill: search / get / references
      → search-records-sudoc     ← expand an authority's bibliography to catalogue records
      → convert-records-unimarc  ← when those records need reformatting
```

Typical pattern: `search` to identify an authority, `references` to see what it is
attached to, then `search-records-sudoc` for the full catalogue records.

## Files

- `scripts/cli.py` — self-contained CLI wrapper
- `references/llm.md` — condensed IdRef API reference, for maintenance
