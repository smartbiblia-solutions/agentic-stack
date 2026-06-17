---
name: search_records_hal
description: >
  Search and retrieve records from HAL (Hyper Articles en Ligne), the French
  open repository, powered by Apache Solr. Use this skill whenever the user
  asks to search HAL, query a specific HAL collection or portal, retrieve
  bibliographic metadata, export BibTeX/TEI, or compute facets and trends from
  HAL. Prefer this skill when the task targets French institutional or lab
  deposits or francophone open-access preprints. Trigger on keywords like
  "HAL", "archives-ouvertes", "collection HAL", "portail HAL", "dépôt HAL",
  or any request to search French open-access deposits. Most HAL usage is
  collection-scoped — always ask for the collection code when it is not provided.
metadata:
  {
    "version": "0.1.0",
    "author": "smartbiblia",
    "maturity": "stable",
    "preferred_output": "json",
    "openclaw":
      {	    
        "always": true, "requires": { "bins": ["uv"], "env": ["HAL_HTTP_TIMEOUT", "HAL_MAX_RETRIES", "HAL_TRACE"], "config": [] },
      },
	"nanobot":
      {	    
        "always": true, "requires": { "bins": ["uv"], "env": ["HAL_HTTP_TIMEOUT", "HAL_MAX_RETRIES", "HAL_TRACE"] },
      }
  }

tags:
  - hal
  - scholarly
  - open-access
  - france
  - solr
---

# search-records-hal

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
| `--facet-field` | string (repeatable) | — | Enable facets on a field. |
| `--facet-mincount` | int | `1` | Facet mincount. |
| `--facet-limit` | int | `20` | Facet limit. |
| `--group-field` | string | — | Enable grouping by field. |
| `--group-limit` | int | `1` | Group size. |
| `--wt` | enum | `json` | Response format: `json`, `xml`, `xml-tei`, `bibtex`, `endnote`, `rss`, `atom`, `csv`. |
| `--indent` | flag | off | Add `indent=true` to the Solr request. |
| `--trace` | flag | off | Append HTTP trace info to output JSON. |

> **Note on `--wt`**: only `json` produces structured output through this CLI.
> Other formats (`bibtex`, `xml-tei`, etc.) return an error payload with the
> raw Solr URL, so you can fetch the export format directly if needed.
> This is intentional — non-JSON responses cannot be piped into downstream skills.

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
  "facets": {},
  "error": null
}
```

Errors are returned inline — exit code is always 0:

```jsonc
{ "error": "...", "total_found": 0, "returned": 0, "results": [] }
```

Always check the `error` field in the output.

---

## Environment variables

Set in `./skills/search-records-hal/.env` or export in the shell.

| Variable | Default | Purpose |
|---|---|---|
| `HAL_HTTP_TIMEOUT` | `20.0` | Request timeout (seconds) |
| `HAL_MAX_RETRIES` | `2` | Retry attempts |
| `HAL_BACKOFF_BASE` | `1.0` | Backoff base seconds |
| `HAL_BACKOFF_FACTOR` | `2.0` | Backoff multiplier |
| `HAL_JITTER_MAX` | `0.25` | Max jitter seconds |
| `HAL_TRACE` | `0` | Set to `1` for global trace logging |

Retried status codes: 429, 500, 502, 503, 504. Timeouts are also retried.

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