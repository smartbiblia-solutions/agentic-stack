---
name: search-works-openalex
description: >
  Search and retrieve academic papers from OpenAlex, the world's largest open
  bibliographic database. Use this skill whenever the user wants to find
  research papers, resolve DOIs, look up citation counts, find works that cite
  a paper, classify text by academic topic, or find papers by meaning rather
  than by keyword. Trigger on keywords like "papers on", "find research",
  "look up DOI", "who cites", "academic literature", "scientific articles",
  "cited by", "classify this abstract", "papers similar to", "semantic search",
  "find work like this abstract", or any request involving bibliographic data.
  Use it even if the user doesn't explicitly name OpenAlex — if they want to
  find or analyse academic papers, this skill applies.
version: "0.3.0"
author: smartbiblia
maturity: stable
preferred_output: json
metadata:
  {
    "openclaw": {
      "always": true,
      "requires": { "bins": ["uv"], "env": [], "config": [] },
      "primaryEnv": "OPENALEX_API_KEY"
    }
  }

selection:
  use_when:
    - The task is to discover or retrieve scholarly works, articles, or preprints.
    - The user wants to resolve a DOI or find full bibliographic metadata.
    - The task requires finding papers that cite a specific work.
    - The task is to classify a title or abstract by academic topic.
    - The user describes a subject in prose, or has an abstract in hand, and no
      single keyword captures it — search by meaning instead.
  avoid_when:
    - The task concerns a library catalog or institutional holdings.
    - Papers have already been retrieved and the next step is appraisal or synthesis.
  prefer_over:
    - generic-web-search
  combine_with:
    - generate-search-queries
    - search-records-hal
    - synthesize-literature

tags:
  - openalex
  - scholarly
  - literature
  - bibliometrics
---

# search-works-openalex

## Purpose

`scripts/cli.py` is a self-contained CLI (runs with `uv run`) that wraps the
[OpenAlex REST API](https://docs.openalex.org). It exposes five subcommands and
emits **strict JSON on stdout**, making it easy to pipe into further processing.

```
uv run scripts/cli.py <subcommand> [flags]
```

> **Path note**: adjust the path to `cli.py` to wherever it lives in
> your project (e.g. `skills/search-works-openalex/scripts/cli.py`).

This skill exposes five logical operations, each addressable independently:

| Logical skill | Subcommand | Purpose |
|---|---|---|
| `search-works-openalex` | `search` | Keyword search across the OpenAlex corpus |
| `search-works-openalex` | `search-semantic` | Meaning-based search from a descriptive text |
| `lookup-dois-openalex` | `batch-lookup-by-doi` | Resolve one or more DOIs to full metadata |
| `get-citing-works-openalex` | `get-citing-works` | Find papers citing a specific work |
| `classify-text-openalex` | `classify-text` | Classify a title or abstract by academic topic |

---

## When to use / When not to use

Use this skill for any task involving discovery or retrieval of scholarly works,
DOI resolution, citation graph exploration, or topic classification of academic text.

Do not use it when:
- The task concerns a library catalog or institutional holdings — use
  `search-records-sudoc` (French union catalogue) or `search-records-hal`.
- Papers have already been retrieved and the next step is appraisal or
  synthesis — use `synthesize-literature`.

---

## Subcommands

### 1. `search` — keyword search for works

Find papers by free-text query, with optional filters.

```bash
uv run ./skills/search-works-openalex/scripts/cli.py search \
  --query "transformer language models" \
  --max-results 10 \
  --date-from 2022-01-01 \
  --date-to 2024-12-31 \
  --oa \
  --sort-by "cited_by_count:desc" \
  --author "Yann LeCun" \
  --institution "MIT"
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--query` | string | **required** | Free-text search query |
| `--max-results` | int | `15` | Max 200 per call |
| `--date-from` | `YYYY-MM-DD` | — | Inclusive lower bound on publication date |
| `--date-to` | `YYYY-MM-DD` | — | Inclusive upper bound |
| `--oa` | flag | off | Return only open-access works |
| `--sort-by` | string | `publication_date:desc` | Any OpenAlex sort field, e.g. `cited_by_count:desc` |
| `--author` | string | — | Author name **or** ORCID (e.g. `0000-0002-1825-0097`). Resolved automatically. |
| `--institution` | string | — | Institution name **or** ROR URL. Resolved automatically. |

**Author/institution resolution**: when a name is given (not an ID), the CLI
makes an extra API call to resolve it to an OpenAlex ID before searching. If
resolution fails, the result will contain `"error": "Auteur introuvable…"` and
zero results — check spelling or try the ORCID/ROR identifier directly.

---

### 2. `search-semantic` — search by meaning, not by keyword

Rank the corpus by semantic proximity to a piece of descriptive text. Use it
when the subject is easier to *describe* than to name: the query is embedded and
compared to work embeddings, so a paper matches even when it shares none of the
words used to ask for it. Feed it a sentence or an abstract, not two keywords —
the model was built for abstract-length input.

```bash
uv run ./skills/search-works-openalex/scripts/cli.py search-semantic \
  --text "Methods for automatically assigning subject headings to library
          catalogue records using neural language models" \
  --max-results 20 \
  --year-from 2020 \
  --oa
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--text` | string | **required** | Descriptive text, min 20 chars, **truncated at 2000** |
| `--file` | path | — | Text file to read from; used if `--text` is absent |
| `--max-results` | int | `15` | **Max 50** — the endpoint refuses more |
| `--year-from` | int | — | Inclusive lower bound on publication **year** |
| `--year-to` | int | — | Inclusive upper bound on publication **year** |
| `--oa` | flag | off | Return only open-access works |

Each result carries an extra `relevance_score` (cosine similarity, higher is
closer). The response adds `truncated` (whether the text exceeded 2000
characters) and `cost_usd`, the price OpenAlex reports for the call.

**Three constraints inherited from the endpoint**, and the reason this
subcommand is not just a flag on `search`:

- **`total_found` is always `null`.** OpenAlex reports `meta.count: 50` on every
  semantic response — that is the result cap, not a corpus count. Reporting it
  as a total would overstate what was searched.
- **Years, not dates.** The endpoint rejects `from_publication_date` /
  `to_publication_date`, which is what `search`'s `--date-from` / `--date-to`
  send. Hence `--year-from` / `--year-to`, which map to `publication_year`.
- **Only a closed set of filters is accepted** — `is_oa`, `publication_year`,
  `type`, `language`, `has_abstract`, `has_fulltext`, `is_retracted`, author,
  institution, funder, source and licence ids. Anything else (`cited_by_count`,
  country code, a date range) returns HTTP 400. `--oa` and the year bounds are
  the ones exposed here.

Semantic search is also rate-limited to roughly **one request per second** and
is slower than keyword search. Use `search` when a keyword genuinely names the
subject; reach for `search-semantic` when it does not.

---

### 3. `batch-lookup-by-doi` — resolve one or more DOIs

Fetch full metadata for known papers by DOI. Handles batches of up to 200 DOIs
(internally chunked at 50 per request).

```bash
# Single DOI
uv run ./skills/search-works-openalex/scripts/cli.py batch-lookup-by-doi \
  --doi 10.1038/s41586-021-03819-2

# Multiple DOIs (repeat the flag)
uv run ./skills/search-works-openalex/scripts/cli.py batch-lookup-by-doi \
  --doi 10.1038/s41586-021-03819-2 \
  --doi 10.1145/3292500.3330701

# From a file (one DOI per line)
uv run ./skills/search-works-openalex/scripts/cli.py batch-lookup-by-doi \
  --doi-file dois.txt
```

| Flag | Type | Notes |
|---|---|---|
| `--doi` | string (repeatable) | Short form (`10.xxx/…`) or full URL — both accepted |
| `--doi-file` | path | Text file, one DOI per line |

Both `--doi` and `--doi-file` can be combined. DOIs are auto-normalised to
`https://doi.org/…` format internally; you don't need to include the prefix.

---

### 4. `get-citing-works` — find papers that cite a given work

Retrieve works that cite a specific OpenAlex work, sorted by citation count
(most-cited first).

```bash
uv run ./skills/search-works-openalex/scripts/cli.py get-citing-works \
  --openalex-id W2741809807 \
  --max-results 50
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--openalex-id` | string | **required** | Short ID (`W2741809807`) or full URL — both accepted |
| `--max-results` | int | `20` | Max 200 |

To get the OpenAlex ID for a paper, run `batch-lookup-by-doi` first and read
the `openalex_id` field from its result.

---

### 5. `classify-text` — classify a piece of text by academic topic

Submit a title or abstract and get back topics and keywords as classified by
OpenAlex's `/text` endpoint.

```bash
# Inline text
uv run ./skills/search-works-openalex/scripts/cli.py classify-text \
  --text "Attention is all you need. We propose a new simple network architecture..."

# From a file
uv run ./skills/search-works-openalex/scripts/cli.py classify-text \
  --file abstract.txt
```

| Flag | Type | Notes |
|---|---|---|
| `--text` | string | The text to classify (min 20 chars, truncated at 2000) |
| `--file` | path | Text file to read from; used if `--text` is absent |

Both `--text` and `--file` can be provided; `--text` takes precedence. If the
input is shorter than 20 characters the response will contain
`"error": "Texte trop court…"`.

---

## Output

All subcommands return a JSON object. The `results` array (where present) uses
this common schema:

```jsonc
{
  "total_found": 1523,
  "returned": 15,
  "results": [
    {
      "source": "openalex",
      "id": "W2741809807",
      "openalex_id": "W2741809807",
      "title": "Attention Is All You Need",
      "authors": ["Ashish Vaswani", "Noam Shazeer"],
      "author_details": [
        {
          "name": "Ashish Vaswani",
          "orcid": "https://orcid.org/0000-0002-...",
          "openalex_id": "A123456789",
          "institutions": ["Google Brain"]
        }
      ],
      "abstract": "The dominant sequence transduction models…",
      "doi": "10.48550/arXiv.1706.03762",
      "pdf_url": "https://arxiv.org/pdf/1706.03762",
      "url": "https://openalex.org/W2741809807",
      "source_url": "https://openalex.org/W2741809807",
      "year": 2017,
      "date": "2017-06-12",
      "doc_type": "preprint",
      "journal": "arXiv",
      "cited_by_count": 98000,
      "referenced_works_count": 34,
      "is_open_access": true,
      "oa_status": "green",
      "topics": ["Transformer Models", "Natural Language Processing"],
      "keywords": ["attention mechanism", "self-attention"],
      "cited_by_api_url": "https://api.openalex.org/works?filter=cites:W2741809807"
    }
  ],
  "query_used": "transformer language models",
  "filters_used": ["from_publication_date:2022-01-01"],
  "cited_work_id": "W2741809807"
}
```

`search-semantic` returns the same records with three additions — a per-record
`relevance_score`, and `truncated` / `cost_usd` at the top level — and
`total_found` pinned to `null`:

```jsonc
{
  "total_found": null,          // the endpoint reports a cap, never a count
  "returned": 3,
  "results": [
    { "source": "openalex", "id": "W4387313225", "…": "…", "relevance_score": 0.9746 }
  ],
  "query_used": "Methods for automatically assigning subject headings…",
  "filters_used": ["publication_year:>2019", "is_oa:true"],
  "truncated": false,
  "cost_usd": 0.001,
  "error": null
}
```

`classify-text` returns a different shape:

```jsonc
{
  "topics": [
    {
      "name": "Natural Language Processing",
      "score": 0.97,
      "field": "Computer Science",
      "domain": "Physical Sciences"
    }
  ],
  "keywords": ["attention mechanism", "encoder-decoder", "BLEU score"]
}
```

### Error responses

When author or institution resolution fails, `search` returns:

```jsonc
{ "total_found": 0, "returned": 0, "results": [], "error": "Auteur introuvable dans OpenAlex : 'John Doe'" }
```

The CLI **does not raise a non-zero exit code** in this case — always check for
the `error` key in the output.

---

## Composition hints

```
generate-search-queries          ← build the query set first
  → search                       ← this skill, when a keyword names the subject
  → search-semantic              ← this skill, when only a description does
  → search-records-hal           ← run in parallel for French deposits
  → search-records-sudoc         ← run in parallel for library holdings
      ↓
    get-citing-works             ← expand the citation graph
      ↓
    synthesize-literature        ← screen, appraise, synthesize
```

`classify-text` is a side branch: use it to place a research question in the
OpenAlex topic hierarchy before searching, and feed the returned topic names
back into `--query`.

`search` and `search-semantic` are complementary, not alternatives: run both on
the same question and merge on `doi`. The keyword pass finds what the vocabulary
names; the semantic pass finds what it misses. Their records share the same
schema, so deduplication needs no special handling.

---

## Environment variables

Copy `scripts/.env.example` to `scripts/.env`, or export in the shell.

| Variable | Required | Purpose |
|---|---|---|
| `OPENALEX_API_KEY` | no | « Polite pool » — higher rate limits. Anonymous access works without it. |

Retried status codes: **429, 403, 500, 502, 503, 504**; timeouts are retried
too. The timeout, the retry count and the backoff are constants in `cli.py`,
not environment variables.

---

## Common workflows

**Find recent open-access papers on a topic:**
```bash
uv run ./skills/search-works-openalex/scripts/cli.py search \
  --query "large language model alignment" \
  --date-from 2023-01-01 --oa --max-results 20
```

**Find papers on a subject no keyword names cleanly:**
```bash
uv run ./skills/search-works-openalex/scripts/cli.py search-semantic \
  --text "Using citation context to decide whether a retracted paper is being
          cited approvingly or as an example of misconduct" \
  --max-results 25 --year-from 2018
```

**Find work close to a paper you already have** — feed its abstract back in:
```bash
uv run ./skills/search-works-openalex/scripts/cli.py batch-lookup-by-doi \
  --doi 10.1038/s41586-021-03819-2 \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['results'][0]['abstract'])" \
  > abstract.txt

uv run ./skills/search-works-openalex/scripts/cli.py search-semantic \
  --file abstract.txt --max-results 20
```

**Resolve a DOI and then find what cites it:**
```bash
# Step 1 — get the OpenAlex ID
uv run ./skills/search-works-openalex/scripts/cli.py batch-lookup-by-doi \
  --doi 10.1038/s41586-021-03819-2 \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['results'][0]['openalex_id'])"

# Step 2 — fetch citing works
uv run ./skills/search-works-openalex/scripts/cli.py get-citing-works \
  --openalex-id W2741809807 --max-results 50
```

**Classify an abstract to find its research field:**
```bash
uv run ./skills/search-works-openalex/scripts/cli.py classify-text \
  --text "We introduce a method for fine-tuning large language models with human feedback…"
```

**Look up papers by a specific author at a specific institution:**
```bash
uv run ./skills/search-works-openalex/scripts/cli.py search \
  --query "protein folding" \
  --author "David Baker" \
  --institution "University of Washington"
```

---

## Failure modes

- **Author/institution not found**: resolution returns zero results with an `error` key — check spelling or use ORCID/ROR directly.
- **Exit code always 0**: the CLI does not raise non-zero on API errors — always inspect the `error` field in the JSON output.
- **Rate limiting**: handled automatically via retry with exponential backoff. If persistent, set `OPENALEX_API_KEY`.
- **Abstract unavailable**: the `abstract` field is `null` for some works — OpenAlex does not guarantee abstract coverage.
- **`search-semantic` returns at most 50 records and no total**: `total_found` is `null` by design. There is no paging past the cap — narrow with `--year-from` / `--year-to` / `--oa`, or rephrase the text, instead of asking for more.
- **`search-semantic` is rate-limited to roughly one call per second**: back-to-back calls return 429. Retries handle it, but a loop of semantic queries should be paced rather than parallelised.