---
name: search-records-hal
description: >
  Search and retrieve records from HAL (Hyper Articles en Ligne), the French
  open repository, powered by Apache Solr. Use this skill whenever the user
  asks to search HAL, query a specific HAL collection or portal, retrieve
  bibliographic metadata, export BibTeX/TEI, or compute facets and trends from
  HAL. Also resolves HAL's own reference data (AuréHAL): portal codes,
  laboratories and institutions (structures), authors, journals, ANR and
  European projects. Prefer this skill when the task targets French
  institutional or lab deposits or francophone open-access preprints. Trigger
  on keywords like "HAL", "archives-ouvertes", "collection HAL", "portail HAL",
  "dépôt HAL", "AuréHAL", "structure HAL", or any request to search French
  open-access deposits. Most HAL usage is collection-scoped — always ask for
  the collection code when it is not provided. Returns JSON.
version: "0.3.0"
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
    - The task targets a specific HAL collection or institutional portal.
    - The user asks for French open-access deposits or francophone preprints.
    - The search strategy produced queries with lang "fr" and HAL is a target source.
    - BibTeX or TEI export from HAL is needed.
    - Facets or publication trends over a HAL collection are required.
    - A HAL portal code, structure/laboratory id, journal id or project
      reference has to be resolved before it can be used as a filter.
  avoid_when:
    - The task requires broad international scholarly coverage; use search-works-openalex.
    - The task targets library holdings rather than deposits; use search-records-sudoc.
    - DOI resolution is the primary goal.
  prefer_over:
    - generic-web-search
  combine_with:
    - generate-search-queries
    - search-works-openalex
    - synthesize-literature

tags:
  - hal
  - scholarly
  - open-access
  - france
  - solr
---

# search-records-hal

## Purpose

`scripts/cli.py` is a self-contained CLI (runs with `uv run`) that wraps the
[HAL Search API](https://api.archives-ouvertes.fr/docs/search), powered by
Apache Solr. It emits **strict JSON on stdout**, normalized to an
OpenAlex-compatible record shape for consistent downstream processing.

```
uv run ./skills/search-records-hal/scripts/cli.py <subcommand> [flags]
```

The output schema is intentionally aligned with the common hub record schema
so that records from different sources can be processed by downstream steps
without transformation.

### Query-building defaults

- Always set an explicit Solr field list (params.fl); never leave it null.
- Minimum required: halId_s, uri_s
- Recommended: halId_s, uri_s, title_s, doiId_s, publicationDateY_i, docType_s
- For facets/trends (or when rows=0), always compute the year facet:
- facet=true, facet.field=publicationDateY_i, facet.mincount=1, facet.limit=-1
- If only facets are requested, set rows=0 to return buckets without documents

### Facets and trends output contract

- When facets or trends are requested (e.g., by year), issue a facet-enabled query and always include a year histogram in the output.
- Always request: facet=true, facet.field=publicationDateY_i, facet.limit=-1, facet.sort=index, facet.mincount=1. For trend-only, set rows=0 so no documents are returned while facets are computed.
- In all JSON responses, include a facets object with publicationDateY_i as an array of { value: <year>, count: <int> } buckets. Do not omit facets when returned=0 or results=[]. If no buckets are returned, set publicationDateY_i: [] rather than leaving facets empty.

---

## When to use / When not to use

**Use this skill when:**

- The task targets a specific HAL collection or institutional portal.
- The user asks for French open-access deposits or francophone preprints.
- The search strategy produced queries with lang "fr" and HAL is a target source.
- BibTeX or TEI export from HAL is needed.

**Do not use this skill when:**

- The task requires broad international scholarly coverage.
- DOI resolution is the primary goal.

---

## Collection-first design

Most HAL usage targets a specific collection (institution or lab portal).
This skill is designed **collection-first**:

- Always provide `--collection {CODE}` when the user specifies a collection.
- If no collection is mentioned, ask the user before falling back to global HAL search.
- Case sensitivity matters in HAL's path routing:
  - `/search/tel/` → portal (instance, lowercase)
  - `/search/FRANCE-GRILLES/` → collection (typically uppercase)

`--collection` and `--portal` are mutually exclusive; `--collection` wins.

---

## Subcommands

### `search` — search HAL records

```bash
uv run ./skills/search-records-hal/scripts/cli.py search \
  --collection "FRANCE-GRILLES" \
  --q 'title_t:(japon OR france)' \
  --rows 20 \
  --fl 'halId_s,title_s,authFullName_s,doiId_s,publicationDateY_i,uri_s' \
  --wt json
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--collection` | string | *(none)* | Recommended. Routes to `/search/{COLLECTION}/`. |
| `--portal` | string | *(none)* | Alternative to collection; routes to `/search/{portal}/`. |
| `--q` | string | `*:*` | Solr query string. |
| `--fq` | string (repeatable) | — | Solr filter query. |
| `--fl` | string | `halId_s,title_s,uri_s` | Fields to return. Always use a tight `--fl` for performance. |
| `--rows` | int | `15` | Page size. |
| `--start` | int | `0` | Offset for pagination. |
| `--sort` | string | — | Solr sort expression, e.g. `publicationDateY_i desc`. |
| `--facet-field` | string (repeatable) | — | Enable facets on a field. Must be a facetable suffix (`_s`, `_i`, `_fs`, `_bool`, `_sci`). |
| `--facet-mincount` | int | `1` | Facet mincount. |
| `--facet-limit` | int | `20` | Facet limit. `-1` for every bucket (use for year histograms). |
| `--facet-sort` | enum | *(Solr default)* | `count` (most frequent first) or `index` (alphabetical/chronological — what a trend needs). |
| `--facet-prefix` | string | — | Keep only facet values starting with this prefix, e.g. `81173_` on `structHasAuthIdHal_fs` to list the authors of one structure. |
| `--facet-pivot` | string (repeatable) | — | Comma-separated field chain for a hierarchical facet, e.g. `title_s,docType_s,halId_s` (duplicate detection) or `docType_s,publicationDateY_i`. |
| `--group-field` | string | — | Enable grouping by field. |
| `--group-limit` | int | `1` | Group size. |
| `--wt` | enum | `json` | Response format: `json`, `xml`, `xml-tei`, `bibtex`, `endnote`, `rss`, `atom`, `csv`. |
| `--indent` | flag | off | Add `indent=true` to the Solr request. |

> **Note on `--wt`**: only `json` produces structured output through this CLI.
> Other formats (`bibtex`, `xml-tei`, etc.) return an error payload with the
> raw Solr URL, so you can fetch the export format directly if needed.
> This is intentional — non-JSON responses cannot be piped into downstream skills.

### `list-portals` — list HAL portals (instances)

```bash
uv run ./skills/search-records-hal/scripts/cli.py list-portals --contains univ
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--contains` | string | *(none)* | Case-insensitive substring match on the portal code or name. Literal — accents are not folded, so `thèses` matches and `these` does not. |
| `--include-deprecated` | flag | off | Also return portals flagged deprecated. |
| `--rows` | int | `0` | Truncate the list; `0` returns every match. |

Reads `/ref/instance/`, which answers with the ~216 HAL portals as `code`
(the lowercase path segment `--portal` takes), `name` and public `url`.
That endpoint ignores `q` and `rows` and always returns the whole list, so the
filtering happens client-side — hence `--contains` rather than a Solr query.

### `lookup-ref` — resolve an AuréHAL reference entry

```bash
uv run ./skills/search-records-hal/scripts/cli.py lookup-ref \
  --ref structure --q 'text:CRIStAL' --rows 5 \
  --fl 'docid,label_s,acronym_s,type_s,valid_s'
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--ref` | enum | *(required)* | `structure`, `author`, `journal`, `anrproject`, `europeanproject`, `domain`. |
| `--q` | string | `*:*` | Solr query over that reference. |
| `--fq` | string (repeatable) | — | Solr filter query. |
| `--fl` | string | `*` | Fields to return; `*` keeps the whole entry. |
| `--rows` / `--start` / `--sort` | | `15` / `0` / — | As in `search`. |

The references carry the identifiers that make a `search` filter precise:

| Need | Reference | Field to reuse in `search` |
|---|---|---|
| Lab / institution | `structure` | `docid` → `structId_i:<docid>` |
| Author (idHAL, form id) | `author` | `docid` → `authIdFormPerson_s`, or `authIdHal_s` |
| Journal | `journal` | `docid` → `journalId_i:<docid>` |
| ANR project | `anrproject` | `reference_s` → `anrProjectReference_s` |
| European project | `europeanproject` | `reference_s` → `europeanProjectReference_s` |
| Subject domain | `domain` | `code_s` → `domain_s:<code>` |

Reference entries have no common schema, so only `id`, `label`, `code`,
`acronym` and `url` are normalized; the whole source entry stays under `raw`.

**Collections have no reference endpoint.** Discover a collection code by
faceting the search index instead:

```bash
uv run ./skills/search-records-hal/scripts/cli.py search \
  --q 'collName_t:grilles' --rows 0 --facet-field collCodeName_fs
```

---

## Field reference

HAL is a Solr index and the **field suffix declares what the field can do**.
Using a field outside its capability is the single most common cause of an
empty result set with no error.

| Suffix | Type | Display (`fl`) | Facet | Search (`q`/`fq`) | Sort |
|---|---|---|---|---|---|
| `_s` | string | yes | yes | **no** | yes |
| `_t` | text (case/accent-insensitive) | **no** | no | yes | no |
| `_sci` | string, case/accent-insensitive | yes | yes | yes | yes |
| `_i` | int / long / double | yes | yes | yes | yes |
| `_bool` | boolean | yes | yes | yes | yes |
| `_fs` | facetString | yes | yes | no | no |
| `_id` | identifier (ignores `-` `_` `/`) | no | no | yes | no |
| `_tdate` | ISO 8601 date | yes | **no** | yes | yes |
| `_sort` | alphaOnlySort | no | no | no | yes |

Read it as a rule of thumb: **search on `_t`, return and facet on `_s`,
sort on `_i`/`_s`, match identifiers on `_id`.**

### Default index

`q=asie` is `q=text:asie`. `text` aggregates title, authors, abstract,
keywords, journal, conference, ISBN/ISSN, project names and identifiers.
`text_fulltext` is the same plus the indexed full text of deposited PDFs —
use it when the term is expected in the body rather than in the metadata.

### Fields worth knowing

| Purpose | Search on | Return / facet on |
|---|---|---|
| Free text | `text`, `text_fulltext`, `fulltext_t` | — |
| Title | `title_t` | `title_s` |
| Abstract | `abstract_t` | `abstract_s` |
| Keywords | `keyword_t` | `keyword_s` |
| Author name | `authFullName_t`, `authLastName_t` | `authFullName_s`, `authIdHal_s` |
| Affiliation | `structure_t`, `structName_t`, `structAcronym_t` | `structId_i`, `structIdName_fs` |
| Collection | `collection_t`, `collName_t` | `collCode_s`, `collCodeName_fs` |
| Portal | — | `instance_s` |
| Journal | `journal_t`, `journalTitle_t` | `journalTitle_s`, `journalIssn_s`, `journalId_i` |
| Conference | `conference_t`, `conferenceTitle_t` | `conferenceTitle_s`, `conferenceStartDateY_i` |
| Doc type | — | `docType_s` |
| Language | — | `language_s` (ISO 639-1) |
| Domain | `domain_t` | `domain_s`, `domainAllCode_s` |
| Identifiers | `halId_id`, `doiId_id`, `arxivId_id`, `pubmedId_id`, `nntId_id`, `isbn_id` | `halId_s`, `doiId_s`, `uri_s` |
| Full text online | — | `openAccess_bool`, `fileMain_s`, `files_s`, `fileType_s`, `licence_s` |
| Projects | `anrProject_t`, `europeanProject_t` | `anrProjectReference_s`, `europeanProjectReference_s` |

Five different dates exist and they answer different questions —
`publicationDate*` (published), `producedDate*` (written), `submittedDate*`
(deposited in HAL), `releasedDate*` (made visible), `defenseDate*` (thesis
defence). Each comes as `_s`, `_tdate` and split `Y_i` / `M_i` / `D_i` parts;
year filters and histograms use the `Y_i` form, e.g.
`fq=publicationDateY_i:[2020 TO 2024]`.

### Document types (`docType_s`)

`ART` article · `COMM` conference paper · `POSTER` · `PROCEEDINGS` · `ISSUE`
special issue · `OUV` book · `COUV` book chapter · `BLOG` · `NOTICE`
encyclopaedia entry · `TRAD` translation · `PATENT` · `REPORT` (with
`RESREPORT`, `TECHREPORT`, `FUNDREPORT`, `EXPERTREPORT`, `DMP`) · `THESE`
thesis · `ETABTHESE` · `HDR` · `MEM` student dissertation · `LECTURE` course ·
`UNDEFINED` preprint/working paper (with `PREPRINT`, `WORKINGPAPER`) ·
`IMG` · `VIDEO` · `SON` · `MAP` · `SOFTWARE` · `OTHER`.

The codes in parentheses are **`docSubType_s`** values, a second field, not
`docType_s` ones: a preprint is `docType_s:UNDEFINED` *and*
`docSubType_s:PREPRINT`, a research report `docType_s:REPORT` *and*
`docSubType_s:RESREPORT`. Filter on both when the distinction matters.

`references/llm.md` carries the full query syntax, escaping rules, the field
catalogue with its capability matrix, the AuréHAL referentials and the worked
request patterns.

---

## Output

All subcommands return strict JSON. Records are normalized to an
OpenAlex-compatible shape:

```jsonc
{
  "total_found": 1234,
  "returned": 20,
  "results": [
    {
      "source": "hal",
      "id": "hal-01234567",
      "hal_id": "hal-01234567",
      "title": "...",
      "authors": ["First Last"],
      "abstract": null,
      "doi": "10....",
      "pdf_url": "https://hal.science/hal-01234567v1/file/paper.pdf",
      "url": "https://hal.science/hal-01234567",
      "source_url": "https://hal.science/hal-01234567",
      "year": 2024,
      "date": "2024-03-15",
      "doc_type": "ART",
      "journal": null,
      "raw": { }
    }
  ],
  "query_used": "title_t:(japon OR france)",
  "filters_used": [],
  "scope": {"type": "collection", "value": "FRANCE-GRILLES"},
  "params": {"rows": 20, "start": 0, "sort": null, "wt": "json", "fl": "..."},
  "facets": {
    "publicationDateY_i": [{"value": "2023", "count": 41}]
  },
  "error": null
}
```

`facets` is keyed by the fields passed to `--facet-field`, each one an array of
`{value, count}` buckets — Solr's flat `[value, count, value, count]` array is
unpacked for you. A requested field with no matching value comes back as `[]`,
never missing. The untouched Solr block is kept under `facets_raw`, and pivot
results under `facet_pivot`.

`list-portals` and `lookup-ref` use the same envelope with a flatter record,
since reference entries share no schema:

```jsonc
{
  "total_found": 26,
  "returned": 2,
  "results": [
    {
      "source": "hal",
      "ref": "structure",
      "id": "410272",
      "label": "Centre de Recherche en Informatique, Signal et Automatique de Lille - UMR 9189 [CRIStAL]",
      "code": null,
      "acronym": "CRIStAL",
      "url": null,
      "raw": { }
    }
  ],
  "ref": "structure",
  "error": null
}
```

Errors are returned inline — exit code is always 0:

```jsonc
{ "error": "...", "total_found": 0, "returned": 0, "results": [] }
```

Always check the `error` field in the output.

---

## Composition hints

```
generate-search-queries          ← build the query set first
  → search-records-hal           ← this skill (French open-access deposits)
  → search-works-openalex        ← run in parallel for international literature
  → search-records-sudoc         ← run in parallel for library holdings
      ↓
    synthesize-literature        ← screen, appraise, synthesize
```

Records are normalized to the common hub schema, so results from HAL, OpenAlex
and Sudoc can be merged and deduplicated on `doi` before synthesis. Ask for the
collection code before the first call — a global HAL query is rarely what the
user means.

---

## Environment variables

None. The HAL Search API is public and anonymous, so this skill ships no `.env`
and no `.env.example`. The timeout, the retry count and the backoff are
constants in `cli.py`.

Retried status codes: **429, 500, 502, 503, 504**; timeouts are retried too.

---

## Common workflows

### Collection-scoped search, compact payload

```bash
uv run ./skills/search-records-hal/scripts/cli.py search \
  --collection "FRANCE-GRILLES" \
  --q 'text:intelligence artificielle' \
  --rows 25 \
  --fl 'halId_s,title_s,authFullName_s,publicationDateY_i,uri_s' \
  --wt json
```

### Publication trend by year (facets, no records)

```bash
uv run ./skills/search-records-hal/scripts/cli.py search \
  --collection "FRANCE-GRILLES" \
  --q 'text:machine learning' \
  --rows 0 \
  --facet-field publicationDateY_i \
  --wt json
```

### Find the portal code, then search it

```bash
uv run ./skills/search-records-hal/scripts/cli.py list-portals --contains thèses
# → tel (TEL - Thèses en ligne), pastel
uv run ./skills/search-records-hal/scripts/cli.py search \
  --portal tel --q 'title_t:"apprentissage profond"' --rows 10 \
  --fl 'halId_s,title_s,authFullName_s,defenseDateY_i,uri_s'
```

### Resolve a laboratory, then filter deposits by its identifier

```bash
uv run ./skills/search-records-hal/scripts/cli.py lookup-ref \
  --ref structure --q 'acronym_t:CRIStAL' --fq 'valid_s:VALID' --rows 5 \
  --fl 'docid,label_s,acronym_s,type_s'
# → take docid, e.g. 410272 for CRIStAL (UMR 9189, Lille)
uv run ./skills/search-records-hal/scripts/cli.py search \
  --q 'structId_i:410272' --fq 'publicationDateY_i:[2020 TO 2024]' \
  --fq 'docType_s:ART' --rows 25 \
  --fl 'halId_s,title_s,authFullName_s,doiId_s,publicationDateY_i,uri_s'
```

### Spot potential duplicates in a collection (pivot facet)

```bash
uv run ./skills/search-records-hal/scripts/cli.py search \
  --q 'collCode_s:INRIA AND producedDateY_i:2015' --rows 0 \
  --facet-pivot 'title_s,docType_s,halId_s' \
  --facet-mincount 2 --facet-limit 10
```

### Export BibTeX for a known HAL ID

```bash
uv run ./skills/search-records-hal/scripts/cli.py search \
  --collection "FRANCE-GRILLES" \
  --q 'halId_s:hal-01234567' \
  --rows 1 \
  --wt bibtex
# → returns error payload with source_url; fetch that URL directly for BibTeX
```

## Failure modes

- **Exit code always 0**: check the `error` field in the output — the CLI does not raise non-zero on API errors.
- **`wt != json`**: returns an error payload with `source_url` pointing to the raw Solr URL. Fetch it directly for BibTeX or TEI export.
- **Collection not found**: HAL returns 0 results without an error — verify the collection code and its case sensitivity.
- **Rate limiting**: handled automatically via retry with exponential backoff.
- **Abstract unavailable**: `abstract` is `null` for many HAL records — screen on title only in that case.
- **Zero results with a valid-looking query**: check the field suffix against
  the capability table above. `title_s:japon` matches nothing (a `_s` field is
  not searchable); `title_t:japon` does. Symmetrically, faceting or sorting on
  a `_t` field silently yields nothing.
- **`--facet-field` on an unfacetable field**: the bucket list comes back empty
  rather than as an error — `facets` still carries the key.
- **`lookup-ref --ref instance`**: not accepted. `/ref/instance/` ignores `q`
  and `rows`, so portals are served by `list-portals` and filtered client-side.
- **No collection reference endpoint**: collection codes are discovered by
  faceting `collCodeName_fs` in `search`, not through `lookup-ref`.