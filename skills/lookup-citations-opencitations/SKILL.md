---
name: lookup-citations-opencitations
description: >
  Look up citation data in OpenCitations — how many times a work is cited, which
  works cite it, which works it cites, and the bibliographic record behind an
  identifier. Use this skill when a DOI, PMID, OMID or ORCID is already known and
  the task is to count citations, list citing or cited works, measure citation
  impact, detect journal or author self-citations, follow a citation trail, or
  resolve a DOI to open bibliographic metadata. Covers OpenCitations Meta v1 and
  OpenCitations Index v2, both CC0. Trigger on "OpenCitations", "citation count",
  "cited by", "reference list of a DOI", "citing works", "self-citation", "OCI",
  "OMID". OpenCitations has NO search: discover works with search-works-openalex
  or search-records-hal first, then bring their DOIs here. Returns JSON.
version: "0.1.0"
author: smartbiblia
maturity: experimental
preferred_output: json
license: MIT
platforms: ["linux", "macos", "windows"]
metadata:
  {
    "openclaw": { "always": true, "requires": { "bins": ["uv"] } }
  }

selection:
  use_when:
    - A work's citation count or reference count is needed, from a DOI, PMID or OMID.
    - The list of works citing a given work, or cited by it, must be retrieved.
    - Journal or author self-citations must be identified or excluded.
    - A DOI, PMID, ISBN, OpenAlex id or OMID must be resolved to open bibliographic metadata.
    - The publication list of an ORCID is wanted, as author or as editor.
  avoid_when:
    - The task is to discover works by topic, keyword or year — OpenCitations has no search; use search-works-openalex.
    - An abstract, a full text or an open-access link is required; OpenCitations Meta carries none.
    - Coverage of French doctoral theses or repository deposits is the point; use search-theses-fr or search-records-hal.
  prefer_over:
    - generic-web-search
  combine_with:
    - search-works-openalex
    - search-records-hal
    - synthesize-literature

tags:
  - citations
  - open-access
  - opencitations
  - doi
  - bibliometrics
---

# lookup-citations-opencitations

## Purpose

`scripts/cli.py` wraps the two [OpenCitations](https://opencitations.net/) REST
APIs: **Meta v1** (bibliographic metadata of the documents involved in
citations) and **Index v2** (the citation entities themselves). Both are CC0 and
need no credential. The skill turns an identifier you already have into citation
counts, citation edges, or a normalized bibliographic record.

It is the *downstream* step of a literature search, never the entry point.

## When to use / When not to use

Use it once a DOI, PMID, OMID or ORCID is in hand and the question is about
**citations**: how often, by whom, towards whom, and how long after publication.
`counts` answers the impact question for a few cents of latency; the two list
subcommands answer the trail question.

Do not use it to *find* works. **OpenCitations exposes no search operation of
any kind** — no query string, no topic, no year range, no author name in free
text. `search-works-openalex` finds the works; this skill explains their
citations. Do not use it for abstracts or full texts either: Meta records carry
neither, and `abstract` is always `null` in the output (it is present only so
results merge with OpenAlex, HAL, Sudoc and Primo hits on `doi`).

## Subcommands

```bash
# The cheap call. Always start here — it also tells you whether a list is viable.
uv run scripts/cli.py counts doi:10.1108/jd-12-2013-0166
uv run scripts/cli.py counts doi:10.1108/jd-12-2013-0166 pmid:2942070

# Incoming edges: who cites this work.
uv run scripts/cli.py citations doi:10.1108/jd-12-2013-0166 --max-results 20 --sort creation-desc
uv run scripts/cli.py citations doi:10.1108/jd-12-2013-0166 --exclude-self-citations

# Outgoing edges: what this work cites, with the cited works' metadata attached.
uv run scripts/cli.py references doi:10.1108/jd-12-2013-0166 --hydrate

# Bibliographic records. Several identifiers in one call.
uv run scripts/cli.py metadata doi:10.1108/jd-12-2013-0166 pmid:2942070

# What an ORCID published, as author or as editor.
uv run scripts/cli.py works-by-person orcid:0000-0003-0530-4305 --role author
```

Identifiers always carry their scheme prefix: `doi:`, `pmid:`, `pmcid:`,
`isbn:`, `issn:`, `openalex:`, `omid:`, `orcid:`. `counts`, `citations` and
`references` accept `doi:`, `pmid:` and `omid:` only — the three give identical
results for the same work, verified.

Flags on `citations` and `references`:

| Flag | Effect |
|---|---|
| `--max-results N` | clamp, applied **client-side after the full download** (default 20) |
| `--sort creation-asc\|creation-desc\|timespan_days-asc\|timespan_days-desc` | client-side ordering; the API's own `sort` is unusable at scale |
| `--exclude-self-citations` | drops edges where `journal_sc` or `author_sc` is `yes`, and reports how many in `excluded_self_citations` |
| `--hydrate` | attaches `citing_work` / `cited_work`, the Meta record of the work at the other end, one extra request per 10 works |

## Output

Strict JSON on stdout, in the universal envelope. Two record families.

A **citation edge** (`citations`, `references`) — its own family, not a
bibliographic record:

```jsonc
{
  "total_found": 57,          // the true count from the count endpoint, before any clamp
  "returned": 2,
  "results": [
    {
      "source": "opencitations",
      "id": "06012708740-06180334099",           // the OCI
      "url": "https://opencitations.net/index/ci/06012708740-06180334099",
      "citing": {"omid": "br/06012708740", "doi": "10.53730/ijhs.v9n2.15534"},
      "cited":  {"omid": "br/06180334099", "doi": "10.1108/jd-12-2013-0166"},
      "creation": "2025-06-24",                  // date of the citing work
      "timespan": "P10Y3M15D",                   // publication gap, ISO 8601
      "timespan_days": 3755,                     // parsed, 365-day years
      "journal_sc": "no",                        // journal self-citation
      "author_sc": "no",                         // author self-citation
      "raw": { }
    }
  ],
  "source": "opencitations",
  "command": "citations",
  "id": "doi:10.1108/jd-12-2013-0166",
  "error": null
}
```

A **Meta record** (`metadata`, `works-by-person`, and the hydrated ends of an
edge) joins the bibliographic family and merges with OpenAlex/HAL/Sudoc/Primo
results on `doi`:

```jsonc
{
  "source": "opencitations",
  "id": "br/0616067039",                  // OMID, or the DOI when there is none
  "url": "https://doi.org/10.1002/…",
  "title": "Problems Of Citation Analysis: A Critical Review",
  "authors": [{"name": "MacRoberts, Michael H.", "orcid": null, "omid": "ra/06160114401"}],
  "abstract": null,                       // always null — Meta carries no abstracts
  "doi": "10.1002/…",
  "year": "1989",
  "date": "1989-09",                      // as precise as the source is: YYYY, YYYY-MM or YYYY-MM-DD
  "doc_type": "journal article",
  "journal": "Journal Of The American Society For Information Science",
  "venue": {"title": "…", "issn": "0002-8231", "omid": "br/06201057"},
  "publisher": [{"name": "Wiley", "orcid": null, "omid": "ra/0610116001"}],
  "editors": [],
  "volume": "40", "issue": "5", "page": "342-349",
  "identifiers": {"doi": "…", "omid": "br/0616067039", "openalex": "W…"},
  "raw": { }
}
```

`counts` returns one flat record per identifier with `citation_count` and
`reference_count`.

## Environment variables

| Variable | Required | Default | Effect |
|---|---|---|---|
| `OPENCITATIONS_API_URL` | no | `https://api.opencitations.net` | API root; `/meta/v1` and `/index/v2` are appended |
| `OPENCITATIONS_API_KEY` | no | *(unset)* | access token, sent raw in an `authorization` header only when non-empty. The API is fully usable anonymously; a token only raises the quota |

Nothing else is read from the environment. Timeout (60 s), retries (3), backoff
and the volume threshold are constants in `scripts/cli.py`.

## Failure modes

**The CLI always exits 0.** Every failure is data, in `error`, next to empty
`results`.

- **No search.** There is no subcommand that takes a query string, because the
  API has no such operation. `/meta/v1/search` is a 404.
- **No pagination, no server-side limit.** A list endpoint returns everything:
  9.9 MB and 24 354 edges was measured on a single work. `--max-results` clamps
  *after* the download, so it saves tokens, not bandwidth.
- **Large works are refused, deliberately.** Above 5 000 edges the CLI returns
  `total_found`, empty `results`, and an `error` saying so, instead of waiting
  on an endpoint that answers HTTP 500 after four minutes.
- **Truncated JSON with HTTP 200.** The server occasionally cuts a large payload
  mid-stream. The request is retried once, then reported as an error.
- **An unknown identifier is not an error.** It answers HTTP 200 with `count: 0`
  or an empty list, so `total_found: 0, error: null` means "not in
  OpenCitations", which is not the same as "not cited".
- **An ISSN in `metadata` returns the journal itself**, repeated once per record
  the index holds — never its articles. There is no way to list a journal's
  works.
- **A rejected token answers HTTP 403 with a plain-text body**, surfaced in
  `error`. Unset `OPENCITATIONS_API_KEY` rather than guessing at one.
- Rate limit: 180 requests per minute per IP. `--hydrate` on 20 edges costs two
  extra requests, not twenty.

More verified quirks, with the measurements behind them, in
`references/llm.md`.

## Composition hints

Upstream: `generate-search-queries` → `search-works-openalex` (or
`search-records-hal`, `search-theses-fr`) produce the DOIs. This skill takes
them from there.

- `search-works-openalex` → `lookup-citations-opencitations counts` to rank a
  result set by citation impact against an independent, CC0 source.
- `lookup-citations-opencitations references --hydrate` → `synthesize-literature`
  to build a citation-backed corpus around a seed paper.
- `citations --exclude-self-citations` before any impact claim: the raw count
  includes journal and author self-citations, and the flag quantifies them.
- The same coverage question is worth asking twice: OpenAlex and OpenCitations
  disagree on counts, and the gap is itself informative.
