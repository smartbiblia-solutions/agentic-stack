---
name: search-works-openalex
description: >
  Search and retrieve academic papers from OpenAlex, the world's largest open
  bibliographic database. Use this skill whenever the user wants to find
  research papers, resolve DOIs, look up citation counts, find works that cite
  a paper, find papers by meaning rather than by keyword, resolve an author,
  institution, journal or funder name to an OpenAlex identifier, browse the
  topic hierarchy (domains, fields, subfields, topics), count works by any
  dimension without downloading them, or translate a question into OpenAlex
  query language. Trigger on keywords like "papers on", "find research",
  "look up DOI", "who cites", "academic literature", "scientific articles",
  "cited by", "papers similar to", "semantic search", "how many papers",
  "publications from <institution>", "what topic is this", or any request
  involving bibliographic data. Use it even if the user doesn't explicitly name
  OpenAlex — if they want to find or analyse academic papers, this skill
  applies. Returns JSON.
version: "0.4.0"
author: smartbiblia
maturity: stable
preferred_output: json
license: MIT
platforms: ["linux", "macos", "windows"]
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
    - The user names an author, institution, journal or funder and an OpenAlex
      identifier is needed before filtering on it.
    - The task is a count, a distribution or a trend rather than a list of papers.
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
  - topics
  - institutions
---

# search-works-openalex

## Purpose

`scripts/cli.py` is a self-contained CLI (runs with `uv run`) that wraps the
[OpenAlex REST API](https://help.openalex.org/). It exposes nine subcommands and
emits **strict JSON on stdout**, making it easy to pipe into further processing.

```
uv run scripts/cli.py <subcommand> [flags]
```

> **Path note**: adjust the path to `cli.py` to wherever it lives in
> your project (e.g. `skills/search-works-openalex/scripts/cli.py`).

| Subcommand | Purpose | Cost per call |
|---|---|---|
| `search` | Keyword search, with author / institution / topic filters | $0.001 |
| `search-semantic` | Meaning-based search from a descriptive text | $0.001 |
| `batch-lookup-by-doi` | Resolve one or more DOIs to full metadata | **free** |
| `get-citing-works` | Find papers citing a specific work | $0.0001 |
| `classify-text` | Place a text in the topic hierarchy | $0.001 |
| `resolve-entity` | Name → OpenAlex id, for authors, institutions, journals… | **free** |
| `browse-topics` | Explore domains, fields, subfields, topics | $0.0001 |
| `group-by` | Count along a dimension without retrieving records | $0.0001 |
| `translate-query` | Translate between OQL, OQO and a REST URL | $0.0001 |

Two reference files sit beside this one and cost nothing to read:

- `references/topic-hierarchy.md` — the 4 domains, 26 fields and 252 subfields
  with their identifiers. Read it instead of calling `browse-topics` when the
  level wanted is one of those three.
- `references/openalex-api.md` — filters, query syntax, corpus, costs,
  deprecations, and the traps that make a well-formed request fail.

---

## When to use / When not to use

Use this skill for any task involving discovery or retrieval of scholarly works,
DOI resolution, citation graph exploration, entity resolution, or bibliometric
counting.

Do not use it when:
- The task concerns a library catalog or institutional holdings — use
  `search-records-sudoc` (French union catalogue) or `search-records-hal`.
- Papers have already been retrieved and the next step is appraisal or
  synthesis — use `synthesize-literature`.

---

## Subcommands

### 1. `search` — keyword search for works

```bash
uv run ./skills/search-works-openalex/scripts/cli.py search \
  --query "transformer language models" \
  --max-results 10 \
  --date-from 2022-01-01 \
  --oa \
  --sort-by "cited_by_count:desc" \
  --institution "Sorbonne Université" \
  --subfield 1702
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--query` | string | **required** | Free-text query — see `## Query syntax` |
| `--max-results` | int | `15` | Max **100** per call |
| `--date-from` / `--date-to` | `YYYY-MM-DD` | — | Inclusive bounds on publication date |
| `--oa` | flag | off | Open-access works only |
| `--sort-by` | string | `publication_date:desc` | e.g. `cited_by_count:desc`, `relevance_score:desc` |
| `--author` | string | — | Name **or** ORCID. Resolved automatically. |
| `--institution` | string | — | Name **or** ROR URL. Resolved automatically. |
| `--institution-scope` | `lineage` \| `exact` | `lineage` | See below |
| `--topic` / `--subfield` / `--field` / `--domain` | id | — | e.g. `T10601`, `1702`, `17`, `3` |
| `--topic-scope` | `any` \| `primary` | `any` | Recall vs. precision |
| `--corpus` | `core` \| `expansion` \| `all` | `core` | Adds ~190M dataset/repository records |
| `--exact` | flag | off | Disable stemming; **required** for `*` and `?` wildcards |
| `--cursor` | string | — | `*` to start deep paging, then `next_cursor` |

**`--institution-scope` defaults to `lineage`, and that is the interesting
part.** `lineage` matches the institution *and everything below it* — the joint
research units, hospitals and institutes attached to a university. It is what
OpenAlex's own query language compiles `institution is …` to, and it is almost
always what a user asking for "publications from Sorbonne Université" means.
`exact` matches only works whose affiliation string resolved to that one entity,
and will silently miss a CNRS-affiliated lab. Reach for it only when the
distinction is the point of the question.

**Topic filters.** A work carries up to three topics. `--topic-scope any`
(default) filters on all of them — good recall, some drift. `--topic-scope
primary` keeps only works whose *main* subject it is; the two counts routinely
differ by a factor of three. Identifiers come from
`references/topic-hierarchy.md` or from `browse-topics`.

**Author/institution resolution**: when a name is given rather than an
identifier, the CLI makes an extra (free) call to resolve it. Resolution
failures return zero results with an `error` — they never substitute a
different entity. If the name is ambiguous, run `resolve-entity` first and pass
the identifier.

---

### 2. `search-semantic` — search by meaning, not by keyword

Rank the corpus by semantic proximity to a piece of descriptive text. Use it
when the subject is easier to *describe* than to name. Feed it a sentence or an
abstract, not two keywords — the model was built for abstract-length input.

```bash
uv run ./skills/search-works-openalex/scripts/cli.py search-semantic \
  --text "Methods for automatically assigning subject headings to library
          catalogue records using neural language models" \
  --max-results 20 --year-from 2020 --oa
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--text` | string | **required** | Min 20 chars, **truncated at 2000** |
| `--file` | path | — | Text file; used if `--text` is absent |
| `--max-results` | int | `15` | **Max 50** — the endpoint refuses more |
| `--year-from` / `--year-to` | int | — | Inclusive bounds on publication **year** |
| `--oa` | flag | off | Open-access works only |
| `--institution` | string | — | Name or ROR; filtered on lineage |
| `--corpus` | `core` \| `expansion` \| `all` | `core` | — |

Each result carries `relevance_score` (cosine similarity). The response adds
`truncated` and `cost_usd`.

**Three constraints inherited from the endpoint**, and the reason this is a
separate subcommand rather than a flag on `search`:

- **`total_found` is always `null`.** OpenAlex reports `meta.count: 50` on every
  semantic response — that is the cap, not a corpus count.
- **Years, not dates.** The endpoint rejects `from_publication_date` /
  `to_publication_date`, hence `--year-from` / `--year-to`.
- **Two filters are refused**: `cited_by_count` and country code — pre-filtering
  hundreds of millions of vectors on them would time out. Everything else,
  including institution lineage, works.

Rate-limited to roughly **one request per second**.

---

### 3. `batch-lookup-by-doi` — resolve one or more DOIs

**Free**: single-entity lookups are not billed. When the identifier is known,
this is always cheaper than searching for it.

```bash
uv run ./skills/search-works-openalex/scripts/cli.py batch-lookup-by-doi \
  --doi 10.1038/s41586-021-03819-2 --doi 10.1145/3292500.3330701

uv run ./skills/search-works-openalex/scripts/cli.py batch-lookup-by-doi \
  --doi-file dois.txt
```

| Flag | Type | Notes |
|---|---|---|
| `--doi` | string (repeatable) | Short form (`10.xxx/…`) or full URL |
| `--doi-file` | path | One DOI per line |

Both can be combined; DOIs are normalised internally. Batches are chunked so the
request stays under the API's ~4 KB URL limit. The response adds `requested`,
so a caller can see how many DOIs went unmatched.

---

### 4. `get-citing-works` — find papers that cite a given work

```bash
uv run ./skills/search-works-openalex/scripts/cli.py get-citing-works \
  --openalex-id W2741809807 --max-results 50
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--openalex-id` | string | **required** | Short id or full URL |
| `--max-results` | int | `20` | Max **100** |
| `--cursor` | string | — | `*`, then `next_cursor`, to page past 10 000 |

Get the identifier from `batch-lookup-by-doi` (`openalex_id`).

---

### 5. `classify-text` — place a text in the topic hierarchy

```bash
uv run ./skills/search-works-openalex/scripts/cli.py classify-text \
  --text "We introduce a method for fine-tuning large language models with
          human feedback…"
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--text` | string | — | Min 20 chars, truncated at 2000 |
| `--file` | path | — | Used if `--text` is absent |
| `--max-works` | int | `25` | Neighbours the classification is aggregated from |

**How it works, and why it changed.** OpenAlex's `/text` classification endpoint
was retired. This subcommand rebuilds it: one semantic search finds the nearest
works, and their topics are aggregated weighted by relevance, then rolled up to
subfields, fields and domains. That costs $0.001 instead of the old endpoint's
$0.01, and it returns **real OpenAlex identifiers at all four levels** plus the
`filter_keys` needed to reuse them — where `/text` returned display names one
had to resolve again.

Own output contract (not the record envelope):

```jsonc
{
  "source": "openalex",
  "command": "classify-text",
  "query_used": "We introduce a method for fine-tuning…",
  "truncated": false,
  "based_on_works": 25,
  "topics":    [{ "id": "T10598", "display_name": "…", "score": 0.41, "works": 11 }],
  "subfields": [{ "id": "1702", "display_name": "Artificial Intelligence", "score": 0.63 }],
  "fields":    [{ "id": "17", "display_name": "Computer Science", "score": 0.81 }],
  "domains":   [{ "id": "3", "display_name": "Physical Sciences", "score": 0.88 }],
  "keywords":  ["reinforcement learning from human feedback", "…"],
  "filter_keys": { "topics": "topics.id", "subfields": "topics.subfield.id",
                   "fields": "topics.field.id", "domains": "topics.domain.id" },
  "cost_usd": 0.001,
  "error": null
}
```

The identifiers feed straight back into `search --topic/--subfield/--field`.

---

### 6. `resolve-entity` — a name to an OpenAlex identifier

**Free.** Backed by `/autocomplete`, which returns a `filter_key` alongside each
suggestion — the API telling you which filter that identifier belongs in.

```bash
uv run ./skills/search-works-openalex/scripts/cli.py resolve-entity \
  --query "université de stras" --type institutions
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--query` | string | **required** | Partial name |
| `--type` | enum | `institutions` | `works`, `authors`, `sources`, `institutions`, `topics`, `publishers`, `funders`, `keywords` |
| `--max-results` | int | `5` | — |

Records carry `id` (already in short form, `I68947357`), `url`,
`display_name`, `entity_type`, `hint` (country, journal — what disambiguates two
entities sharing a name), `external_id` (ROR, ORCID, ISSN), `works_count`,
`cited_by_count` and `filter_key`.

**Autocomplete is prefix-based and diacritic-sensitive**, and the two combine
badly: `strasbourg` alone finds nothing because it is not a prefix of the name,
and `universite de stras` finds nothing either because the name is spelled
`Université`. `université de stras` finds it on the first try. Type the
beginning of the name, accents included. When the prefix match is empty the CLI retries a widened
full-text search — and puts what it finds in a separate **`suggestions`** array,
leaving `results` empty and `error` set. That separation is deliberate: a
wrongly resolved institution becomes a filter that nobody will contest, so a
near-match is offered, never substituted.

---

### 7. `browse-topics` — explore the topic hierarchy

```bash
uv run ./skills/search-works-openalex/scripts/cli.py browse-topics \
  --level topics --query "digital humanities" --field 12
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--level` | `domains` \| `fields` \| `subfields` \| `topics` | `topics` | — |
| `--query` | string | — | Full-text search within the level |
| `--field` / `--domain` | id | — | Restrict to a branch |
| `--max-results` | int | `25` | Max 100 |

**For `domains`, `fields` and `subfields`, read `references/topic-hierarchy.md`
instead** — all 282 rows are there, for no call and no budget. Use this
subcommand for `topics`, where 4 516 rows make a lookup the only sensible
approach.

Each record carries the identifier, the display name, the parent levels and
`works_count`, plus the `filter_key` for the level.

---

### 8. `group-by` — count without retrieving

Answers "how many", "which are the top", "how has it evolved" in one call,
without downloading a single record.

```bash
# Publications per year for an institution
uv run ./skills/search-works-openalex/scripts/cli.py group-by \
  --dimension publication_year \
  --filters "authorships.institutions.lineage:I39804081"

# Which fields does a research question span?
uv run ./skills/search-works-openalex/scripts/cli.py group-by \
  --dimension topics.field.id --query "microplastics toxicity"
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--dimension` | string | **required** | Any filter key, e.g. `publication_year`, `type`, `open_access.oa_status`, `authorships.institutions.lineage` |
| `--query` | string | — | Restrict to a search |
| `--filters` | string | — | Raw OpenAlex filter string, comma-separated |
| `--entity` | string | `works` | Any entity endpoint |
| `--include-unknown` | flag | off | Count records with no value for the dimension |
| `--max-groups` | int | `100` | Max 100 |

Own output contract:

```jsonc
{
  "source": "openalex", "command": "group-by",
  "entity": "works", "dimension": "publication_year",
  "query_used": null, "filters_used": ["authorships.institutions.lineage:I39804081"],
  "total_found": 412903, "groups_count": 61,
  "groups": [{ "key": "2024", "key_display_name": "2024", "count": 21847 }],
  "oql": "works where institution is …", "cost_usd": 0.0001, "error": null
}
```

`groups_count` is the number of distinct groups, which can exceed the 100
returned. When it does, narrow the filters rather than paging.

---

### 9. `translate-query` — between OQL, OQO and a REST URL

Three forms of the same query:
**OQL** (readable text), **OQO** (a JSON object) and **oxurl** (the REST URL).
`--form` names what you are *giving* it. Translation never touches the index and
is billed at the cheapest rate, $0.0001 — a thousandth of what running the wrong
search would have cost.

```bash
# Natural-ish language → the URL and filters it actually means
uv run ./skills/search-works-openalex/scripts/cli.py translate-query \
  --query "works where institution is Sorbonne Université and is_oa is true"

# A REST URL → the OQL that describes it
uv run ./skills/search-works-openalex/scripts/cli.py translate-query \
  --form oxurl --query "/works?filter=topics.field.id:17,is_oa:true"
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--query` | string | **required** | The query, in the form named by `--form` |
| `--form` | `oql` \| `oqo` \| `oxurl` | `oql` | The form of the **input** |

Own output contract: `{source, command, form, query_used, valid, oql,
oql_oneline, oqo, oxurl, api_url, diagnostics, error}`. An invalid query returns
`valid: false` with the parser's own message in `error` and the full list in
`diagnostics` — it is the cheapest way to find out that a filter is not spelled
the way you think, and it is how one discovers that `institution is X` compiles
to `authorships.institutions.lineage`, not `.id`.

---

## Query syntax

Applies to `search --query` (and to the keyword half of `group-by`).

| Form | Example | Effect |
|---|---|---|
| Phrase | `"machine learning"` | The words, in that order |
| Proximity | `"climate policy"~5` | Within 5 words of each other |
| Fuzzy | `bioinformatics~2` | Tolerates 2 edits — useful on proper nouns |
| Boolean | `crispr AND (mouse OR murine)` | Operators must be uppercase |
| Wildcard | `neuro*`, `wom?n` | **Requires `--exact`**; silently ignored without it |

`--exact` also disables stemming: with it, `mice` no longer matches `mouse`.
That is what you want for a gene symbol, a standard reference or a wildcard, and
what you do not want for an ordinary subject search.

Only one search mode per request: `search`, `--exact`, or `search-semantic` —
never two.

---

## Output

Every **record** operation — `search`, `search-semantic`, `batch-lookup-by-doi`,
`get-citing-works`, `resolve-entity`, `browse-topics` — answers in the envelope
`{total_found, returned, results, error}`, with `results` always an array and
`error` always present. `classify-text`, `group-by` and `translate-query` have
their own contracts, documented above with their subcommands.

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
        { "name": "Ashish Vaswani", "orcid": "https://orcid.org/0000-0002-…",
          "openalex_id": "A123456789", "institutions": ["Google Brain"] }
      ],
      "abstract": "The dominant sequence transduction models…",
      "doi": "10.48550/arXiv.1706.03762",
      "pdf_url": "https://arxiv.org/pdf/1706.03762",
      "url": "https://openalex.org/W2741809807",
      "source_url": "https://openalex.org/W2741809807",
      "year": 2017,
      "date": "2017-06-12",
      "doc_type": "preprint",
      "language": "en",
      "journal": "arXiv",
      "cited_by_count": 98000,
      "referenced_works_count": 34,
      "is_open_access": true,
      "oa_status": "green",
      "is_retracted": false,
      "fwci": 41.2,
      "citation_percentile": 99.9,
      "is_in_top_1_percent": true,
      "is_in_top_10_percent": true,
      "funders": ["National Science Foundation"],
      "primary_topic": {
        "id": "T10598", "display_name": "Natural Language Processing", "score": 0.99,
        "subfield": { "id": "1702", "display_name": "Artificial Intelligence" },
        "field":    { "id": "17", "display_name": "Computer Science" },
        "domain":   { "id": "3", "display_name": "Physical Sciences" }
      },
      "topics": [ /* same shape, up to three */ ],
      "keywords": ["attention mechanism", "self-attention"],
      "cited_by_api_url": "https://api.openalex.org/works?filter=cites:W2741809807"
    }
  ],
  "query_used": "transformer language models",
  "filters_used": ["from_publication_date:2022-01-01"],
  "corpus": "core",
  "oql": "works where title_and_abstract.search is \"transformer language models\"",
  "next_cursor": null,
  "cost_usd": 0.001,
  "error": null
}
```

> **Breaking change in 0.4.0.** `topics` was a list of display-name strings; it
> is now a list of objects carrying the identifier at every level of the
> hierarchy, so a result can be turned back into a filter without a second
> resolution step. Code reading `record["topics"][0]` as a string must be
> updated. `primary_topic`, `language`, `is_retracted`, `fwci`,
> `citation_percentile`, `is_in_top_1_percent`, `is_in_top_10_percent` and
> `funders` are new, and `is_xpac` appears only on `--corpus expansion|all`.

The bibliographic core — `title`, `authors`, `abstract`, `doi`, `year`, `date`,
`doc_type`, `journal` — is shared with `search-records-hal`,
`search-records-sudoc` and `search-records-primo`, so results from all four
merge and deduplicate on `doi` without special handling.

### Error responses

```jsonc
{ "total_found": 0, "returned": 0, "results": [],
  "error": "Auteur introuvable dans OpenAlex : 'John Doe'" }
```

The CLI **always exits 0**. Errors are data; check the `error` key.

---

## Artifact contract

The CLI writes one complete JSON response to stdout and nothing else. It does
not choose or create a project, review, or run directory, and it has no
`--output` flag: when persistence is wanted, the calling agent redirects stdout
or captures the payload itself — the whole response, not just `results`.

Stable filenames, when one is needed:

| What produced it | Filename |
|---|---|
| `search`, `search-semantic` | `openalex-<query-slug>.json` |
| `batch-lookup-by-doi`, `get-citing-works` | `openalex-<record-id>.json` |
| `classify-text` | `openalex-classify-text-<query-slug>.json` |
| `resolve-entity` | `openalex-resolve-<type>-<query-slug>.json` |
| `browse-topics` | `openalex-topics-<level>-<query-slug>.json` |
| `group-by` | `openalex-groupby-<dimension-slug>.json` |
| `translate-query` | `openalex-query-<query-slug>.json` |

Slugs are lowercase kebab-case, every non-alphanumeric character collapsed to
`-`. No counters, no result counts, no status words, and no date unless a date
is part of the query itself. The parent directory is the caller's business, and
no filename is needed at all when the result is only being returned to the user.

---

## Composition hints

```
generate-search-queries          ← build the query set first
  → resolve-entity               ← this skill: names → ids, before filtering
  → browse-topics                ← this skill: subject → topic ids
      ↓
  → search                       ← this skill, when a keyword names the subject
  → search-semantic              ← this skill, when only a description does
  → search-records-hal           ← run in parallel for French deposits
  → search-records-sudoc         ← run in parallel for library holdings
      ↓
    get-citing-works             ← expand the citation graph
      ↓
    synthesize-literature        ← screen, appraise, synthesize
```

`resolve-entity` and `browse-topics` are the cheap first step of any question
naming an institution, an author or a subject area: both are free or nearly so,
and both remove the guesswork from the filters that follow. `classify-text`
does the same from a text rather than a name.

`group-by` is a side branch answering a different kind of question — a count, a
distribution, a trend — and its output is not a record set, so it does not feed
`synthesize-literature`.

`search` and `search-semantic` are complementary, not alternatives: run both on
the same question and merge on `doi`. The keyword pass finds what the vocabulary
names; the semantic pass finds what it misses.

---

## Environment variables

Copy `scripts/.env.example` to `scripts/.env`, or export in the shell.

| Variable | Required | Purpose |
|---|---|---|
| `OPENALEX_API_KEY` | no | Raises the daily budget from $0.10 to $1.00 |
| `OPENALEX_API_URL` | no | Override the API base, for a mirror or a proxy |

**The polite pool is gone.** Since February 2026 OpenAlex meters usage as a
daily budget and ignores the `mailto` parameter. Anonymous access gets **$0.10 a
day** — roughly 100 searches; a free API key gets **$1.00 a day**, ten times
that. Single-entity lookups and autocomplete are free at either level, which is why
`batch-lookup-by-doi` and `resolve-entity` cost nothing to lean on.

Every response reports `cost_usd` — `null` for the free operations. When the
budget runs out, the `error` field carries OpenAlex's own message, naming the
cost of the refused request and the midnight-UTC reset; retrying will not
change it before then.

Retried status codes: **429, 403, 500, 502, 503, 504**; timeouts too. The
timeout, the retry count and the backoff are constants in `cli.py`, not
environment variables.

---

## Common workflows

**Resolve an institution, then count its output by year:**
```bash
uv run ./skills/search-works-openalex/scripts/cli.py resolve-entity \
  --query "université de stras" --type institutions
# → id = I68947357

uv run ./skills/search-works-openalex/scripts/cli.py group-by \
  --dimension publication_year \
  --filters "authorships.institutions.lineage:I68947357"
```

**Find recent open-access papers in a subfield:**
```bash
uv run ./skills/search-works-openalex/scripts/cli.py search \
  --query "large language model alignment" \
  --subfield 1702 --date-from 2023-01-01 --oa --max-results 20
```

**Find papers on a subject no keyword names cleanly:**
```bash
uv run ./skills/search-works-openalex/scripts/cli.py search-semantic \
  --text "Using citation context to decide whether a retracted paper is being
          cited approvingly or as an example of misconduct" \
  --max-results 25 --year-from 2018
```

**Place an abstract in the hierarchy, then search where it landed:**
```bash
uv run ./skills/search-works-openalex/scripts/cli.py classify-text \
  --file abstract.txt
# → fields[0].id = "17"
uv run ./skills/search-works-openalex/scripts/cli.py search \
  --query "…" --field 17 --topic-scope primary
```

**Check what a filter really means before spending anything on it:**
```bash
uv run ./skills/search-works-openalex/scripts/cli.py translate-query \
  --query "works where institution is Sorbonne Université and is_oa is true"
```

**Resolve a DOI and then find what cites it:**
```bash
uv run ./skills/search-works-openalex/scripts/cli.py batch-lookup-by-doi \
  --doi 10.1038/s41586-021-03819-2 \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['results'][0]['openalex_id'])"

uv run ./skills/search-works-openalex/scripts/cli.py get-citing-works \
  --openalex-id W3177828909 --max-results 50
```

---

## Failure modes

- **Exit code always 0.** The CLI never raises on an API error — inspect the
  `error` field.
- **Entity not found.** `search` returns zero results with an `error` rather
  than guessing. `resolve-entity` puts near-matches in `suggestions`, never in
  `results`.
- **Autocomplete misses.** It is prefix-based and diacritic-sensitive:
  `strasbourg` finds nothing on its own. Start from the beginning of the name.
- **`search-semantic` caps at 50 records and reports no total.** `total_found`
  is `null` by design; there is no paging past the cap. Narrow with year bounds
  or `--oa` rather than asking for more.
- **`search-semantic` is rate-limited to about one call per second.** Pace a
  loop of semantic queries; do not parallelise them.
- **URL length, about 4 KB.** A very long DOI list or filter string returns
  HTTP 400. `batch-lookup-by-doi` chunks its requests; a hand-built `--filters`
  with hundreds of ids must be split and the responses merged.
- **Basic paging stops at 10 000.** `page × per_page ≤ 10 000`. Past that, use
  `--cursor '*'` and follow `next_cursor`, which is also the only way to page
  grouped results.
- **`--corpus expansion` is noisy.** It adds ~190M dataset and repository
  records, many without abstracts and some duplicating core works. Use it for
  datasets and grey literature, not for a literature review.
- **Budget exhausted.** $0.10/day anonymous, $1.00/day with a key. The `error`
  field then reads *"Insufficient budget. This request costs $… but you only
  have $0 remaining. Resets at midnight UTC."* Retrying does not help — set
  `OPENALEX_API_KEY`, or fall back on the free operations
  (`batch-lookup-by-doi`, `resolve-entity`).
- **Abstract unavailable.** `abstract` is `null` for some works; OpenAlex does
  not guarantee coverage.
