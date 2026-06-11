---
name: search-records-sudoc
description: >
  Search and retrieve bibliographic records from the Sudoc catalogue, the
  French academic union catalogue covering all higher education and research
  libraries in France. Use this skill whenever the user wants to find books,
  theses, serials, manuscripts, or any document held in a French university
  library; resolve a PPN or ISBN; look up French academic theses; search by
  author, title, subject, publisher, collection, or shelf mark; or count
  records matching a bibliographic query. Trigger on keywords like "sudoc",
  "catalogue universitaire français", "thèse française", "bibliothèque
  universitaire", "PPN", "UNIMARC", "fonds documentaire", "notices
  bibliographiques", or any request to search French academic holdings.
  Also use it when the user wants to know whether a document is held in
  French academic libraries, or needs UNIMARC metadata for a French
  publication.
metadata:
  {
    "version": "0.1.0",
    "author": "smartbiblia",
    "maturity": "stable",
    "preferred_output": "json",
    "openclaw":
      {
        "always": true, "requires": { "bins": ["uv"], "env": ["SUDOC_HTTP_TIMEOUT", "SUDOC_MAX_RETRIES", "SUDOC_TRACE"], "config": [] },
      },
	"nanobot":
      {
        "always": true, "requires": { "bins": ["uv"], "env": ["SUDOC_HTTP_TIMEOUT", "SUDOC_MAX_RETRIES", "SUDOC_TRACE"] },
      },
  }

tags:
  - sudoc
  - unimarc
  - academic-libraries
  - france
  - bibliographic-data
  - theses
---

# Sudoc SRU Skill

## Overview

`scripts/cli.py` is a self-contained CLI (runs with `uv run`) that wraps the
[Sudoc SRU service](https://www.sudoc.abes.fr/cbs/sru/) maintained by
[ABES](https://abes.fr). It exposes five subcommands and emits **strict JSON
on stdout**, making it easy to pipe into further processing.

```
uv run scripts/cli.py <subcommand> [flags]
```

> **Path note**: adjust the path to `cli.py` to wherever it lives in your
> project (e.g. `skills/search-records-sudoc/scripts/cli.py`).

The Sudoc catalogue covers **bibliographic records and their holdings** across
French higher education and research libraries. It contains books, serials,
theses, manuscripts, maps, scores, audiovisual documents, and electronic
resources. Data is in UNIMARC format (UTF-8).

---

## When to use / When not to use

**Use this skill when:**

- The task targets French academic library holdings, union catalogue records, or institutional collections.
- The user needs to find books, serials, theses, manuscripts, or documents held in French universities.
- PPN or ISBN resolution is needed for French library records.
- The task involves French academic theses (including electronic theses from the STAR corpus).
- UNIMARC metadata or RAMEAU subject headings are required.
- The user wants to know whether a document is held in French academic libraries.

**Do not use this skill when:**

- The task requires broad international scholarly literature.
- The task targets French open-access preprints or institutional deposits.
- DOI-based scholarly retrieval is the primary goal.

---

## Critical: SRU Query Encoding

The Sudoc SRU service uses a **non-standard encoding rule** that differs from
typical REST APIs: the `=` sign must be encoded as `%3D` inside every
index–term pair in a query.

The CLI handles this automatically. When you pass `--query "mti=jardins and japonais"`,
the CLI encodes it correctly before sending the request. **You write natural
syntax; the CLI handles encoding.**

Key encoding rules applied internally:

| Character | Encoded | When |
|---|---|---|
| `=`  | `%3D` | Always, in every index=term pair |
| `\|` | `%7C` | Boolean OR operator |
| `"` | `%22` | Exact phrase |
| `,` | `%2C` | PER index (lastname,firstname) |
| `/` | `%2F` | COT index (shelf marks) |
| ` ` (space) | `+`  | Between tokens |

---

## Subcommands

### 1. `search` — keyword search across Sudoc indexes

Search the catalogue using any combination of Sudoc index keys. Supports
boolean operators, truncation, and all document-type / language / country /
date filters.

```bash
uv run ./skills/search-records-sudoc/scripts/cli.py search \
  --query "mti=jardins and japonais" \
  --max-results 20 \
  --doc-type b \
  --lang-major fre \
  --country-major fr \
  --year-from 2000 \
  --year-to 2023
```

```bash
# Theses in biophysics defended at Lyon:
uv run ./skills/search-records-sudoc/scripts/cli.py search \
  --query "nth=biophysique and lyon" \
  --doc-type y

# Works by Lagerlöf with "troll" in the title:
uv run ./skills/search-records-sudoc/scripts/cli.py search \
  --query "aut=lagerlof and mti=troll"

# Serials in the shared conservation plan "pcdroit", excluding congress proceedings:
uv run ./skills/search-records-sudoc/scripts/cli.py search \
  --query "pcp=pcdroit not fgr=actes congres" \
  --doc-type t

# Records about antivirals (French and English subject indexes combined with OR):
uv run ./skills/search-records-sudoc/scripts/cli.py search \
  --query "vma=antivir* or mee=antivir*"

# Electronic theses from STAR corpus held by Avignon SCD (RCR 840079901):
uv run ./skills/search-records-sudoc/scripts/cli.py search \
  --query "rbc=840079901 and sou=star*"
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--query` | string | **required** | SRU query. Use `index=term` syntax. See Index Reference below. |
| `--max-results` | int | `15` | Max records to return (server cap: 1000) |
| `--doc-type` | string | — | TDO code. See Document Types table below. |
| `--language` | string | — | ISO 639-2/3 code for LAI (most languages, e.g. `dan`, `ara`, `jpn`) |
| `--lang-major` | string | — | LAN code for 10 major languages: `ger` `eng` `spa` `fre` `ita` `lat` `dut` `pol` `por` `rus` |
| `--country` | string | — | ISO 3166 code for PAI (most countries, e.g. `se`, `jp`) |
| `--country-major` | string | — | PAY code for 11 major countries: `de` `be` `ca` `es` `us` `fr` `it` `nl` `gb` `ru` `ch` |
| `--year-from` | int | — | Inclusive lower bound on publication year |
| `--year-to` | int | — | Inclusive upper bound on publication year |
| `--year-exact` | int | — | Exact publication year (overrides year-from/year-to) |
| `--trace` | flag | off | Append HTTP trace log to JSON output |

> **Language note:** Use `--lang-major` for the 10 major languages (French,
> English, German, etc.) and `--language` for all others. Do not mix them —
> the CLI applies the correct Sudoc limitation automatically.

> **Country note:** Same rule as language: use `--country-major` for the 11
> major countries, `--country` for all others.

---

### 2. `lookup-by-ppn` — fetch a single record by PPN

The PPN (Pica Production Number) is Sudoc's unique record identifier.

```bash
uv run ./skills/search-records-sudoc/scripts/cli.py lookup-by-ppn --ppn 070685045
```

| Flag | Type | Notes |
|---|---|---|
| `--ppn` | string | **required** — Sudoc PPN |
| `--trace` | flag | Append HTTP trace log |

---

### 3. `lookup-by-isbn` — fetch record(s) by ISBN

Accepts ISBN-10 or ISBN-13, with or without hyphens. One ISBN may match
multiple records (e.g. different editions or manifestations).

```bash
uv run ./skills/search-records-sudoc/scripts/cli.py lookup-by-isbn --isbn 978-2-07-036024-5
uv run ./skills/search-records-sudoc/scripts/cli.py lookup-by-isbn --isbn 2070360245
```

| Flag | Type | Notes |
|---|---|---|
| `--isbn` | string | **required** — ISBN-10 or ISBN-13, hyphens optional |
| `--trace` | flag | Append HTTP trace log |

---

### 4. `count` — count matching records without fetching them

Returns only the total number of matching records. Use this before a large
`search` to estimate corpus size or validate a query.

```bash
uv run ./skills/search-records-sudoc/scripts/cli.py count --query "aut=zola"
uv run ./skills/search-records-sudoc/scripts/cli.py count --query "pcp=pcmed and tdo=t"
```

| Flag | Type | Notes |
|---|---|---|
| `--query` | string | **required** — same syntax as `search` |
| `--trace` | flag | Append HTTP trace log |

---

### 5. `scan` — browse an index alphabetically

Browse a Sudoc index to discover valid terms, check spelling, or debug
zero-result queries. Equivalent to the SRU `scan` operation.

```bash
# Browse title-word index starting from "paralogue":
uv run ./skills/search-records-sudoc/scripts/cli.py scan --index mti --term paralogue --max-terms 25

# Browse author index starting from "lagerlof":
uv run ./skills/search-records-sudoc/scripts/cli.py scan --index aut --term lagerlof --max-terms 10

# Browse subject access point index:
uv run ./skills/search-records-sudoc/scripts/cli.py scan --index vma --term abricot --max-terms 15
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--index` | string | **required** | Sudoc index key (see Index Reference) |
| `--term`  | string | **required** | Starting term to scan from |
| `--max-terms` | int | `25` | Number of index terms to return |
| `--response-position` | int | `1` | Position of `--term` in the returned list |
| `--trace` | flag | — | Append HTTP trace log |

---

## Index Reference

Use these keys in `--query` with the `key=value` syntax.

### Identifier Indexes (numeric / exact match)

| Key | Description | Example |
|---|---|---|
| `ppn` | Sudoc record number | `ppn=070685045` |
| `isb` | ISBN (10 or 13) | `isb=9782070360246` |
| `isn` | ISSN | `isn=2558-4278` |
| `num` | All identifiers (ISBN, ISSN, deposit numbers…) | `num=DLV-20160831-5586` |
| `nnt` | National thesis number | `nnt=2018perp*` |
| `ocn` | WorldCat record number | `ocn=690860108` |
| `sou` | Source number (electronic corpus ID) | `sou=star*` |
| `bqt` | Electronic resource bundle code | `bqt=2014-110` |

### Title Indexes

| Key | Type | Description | Example |
|---|---|---|---|
| `mti` | word | Title words | `mti=jardins japonais` |
| `tco` | phrase | Full title (exact / truncation) | `tco=oui-oui*` |
| `tab` | phrase | Abbreviated serial title | `tab=nat*` |
| `col` | word | Collection / series | `col=dunod` |

### Author Indexes

| Key | Type | Description | Example |
|---|---|---|---|
| `aut` | word | Author words (any part of name) | `aut=lagerlof` |
| `per` | phrase | Person name — requires `Lastname,Firstname` or truncation | `per=eco,umberto` or `per=eco*` |
| `org` | phrase | Corporate / organizational author | `org=insee` |

> **Phrase indexes (per, org, tco, tab):** require the full, exact form or
> truncation with `*`. For `per`, the comma between lastname and firstname
> is handled automatically by the CLI.

### Subject Indexes

| Key | Type | Description | Example |
|---|---|---|---|
| `msu` | word | Subject words (French) | `msu=hominides` |
| `vma` | phrase | Subject access point (French, RAMEAU) | `vma=abricot*` |
| `fgr` | word | Form / genre | `fgr=actes congres` |
| `msa` | word | Subject words (English) | `msa=apricot*` |
| `mee` | word | MeSH subject headings (English) | `mee=antivir*` |

### Notes Indexes

| Key | Type | Description | Example |
|---|---|---|---|
| `nth` | word | Thesis note (institution, discipline) | `nth=biophysique lyon` |
| `res` | word | Abstract / summary | `res="vers blancs"` |
| `lva` | word | Old / rare books note | `lva=memoires` |
| `fir` | word | Funding source | `fir=labx` |
| `rec` | word | Award / prize note | `rec=award*` |

### Holdings Indexes

| Key | Type | Description | Example |
|---|---|---|---|
| `rbc` | numeric | Library RCR number | `rbc=840079901` |
| `pcp` | word | Shared conservation plan (PCP) | `pcp=pcdroit` |
| `rpc` | word | Binding / provenance / conservation | `rpc="armes de Dominique*"` |
| `cot` | phrase | Shelf mark | `cot="839.73 EKM"` |

### General Indexes

| Key | Type | Description | Example |
|---|---|---|---|
| `tou` | word | All words (all fields) | `tou="ocre jaune"` |
| `edi` | word | Publisher | `edi=domino` |

---

## Document Types (--doc-type / TDO)

| Code | Document type |
|---|---|
| `a` | Articles |
| `b` | Printed monographs |
| `f` | Manuscripts |
| `g` | Musical sound recordings |
| `i` | Still images / photographs |
| `k` | Printed and manuscript maps |
| `m` | Scores (printed and manuscript) |
| `n` | Non-musical sound recordings |
| `o` | Electronic monographs |
| `t` | Serials and collections (all formats) |
| `v` | Audiovisual documents |
| `x` | Objects, multimedia |
| `y` | Theses (print and electronic) |

---

## Output Schema

All subcommands return a JSON object. The `results` array uses this schema:

```json
{
  "total_found": 42,       // total matching records in Sudoc
  "returned": 15,          // records in this response
  "query_used": "mti=jardins japonais and lan=fre",
  "results": [
    {
      "source": "sudoc",
      "ppn": "070685045",                          // Sudoc record number
      "title": "Les jardins japonais",             // main title (+ subtitle joined with " : ")
      "authors": ["Tanaka, Hiroshi"],              // personal authors (Lastname, Firstname)
      "personal_authors": ["Tanaka, Hiroshi"],
      "corporate_authors": [],
      "year": 1998,                                // publication year (null if unknown)
      "publisher": "Actes Sud",
      "pub_place": "Arles",
      "language": "fre",                           // ISO 639-2 language code
      "isbn": "2742712345",                        // null if not applicable
      "issn": null,
      "thesis": null,                              // or see thesis object below
      "subjects": [                                // RAMEAU / subject headings
        "Jardins japonais -- Histoire",
        "Architecture des jardins -- Japon"
      ],
      "series": "Le génie du lieu",               // series/collection title (null if none)
      "physical_desc": "245 p.",
      "notes": ["Bibliogr. p. 230-240"],          // null if none
      "urls": null,                                // list of URLs for e-resources (null if none)
      "sudoc_url": "https://www.sudoc.fr/070685045"
    }
  ]
}
```

For thesis records, the `thesis` field is populated:

```json
"thesis": {
  "type": "Thèse de doctorat",
  "discipline": "Biophysique",
  "institution": "Université de Lyon 1",
  "year": "2018"
}
```

### `count` response

```json
{
  "query": "aut=zola",
  "total_found": 1247,
  "url_used": "https://www.sudoc.abes.fr/cbs/sru/?..."
}
```

### `scan` response

```json
{
  "index": "mti",
  "start_term": "paralogue",
  "terms": [
    { "term": "paralogue",     "count": 3  },
    { "term": "paralogues",    "count": 12 },
    { "term": "paralogisme",   "count": 7  },
    ...
  ]
}
```

### Error responses

```json
{ "total_found": 0, "returned": 0, "results": [],
  "error": "PPN not found in Sudoc: '000000000'" }
```

The CLI **always exits with code 0** — always check for the `error` key.

---

## Environment Variables

Set in a `.env` file next to the script or export in the shell.

| Variable | Default | Purpose |
|---|---|---|
| `SUDOC_HTTP_TIMEOUT` | `30.0` | Seconds before a request times out |
| `SUDOC_MAX_RETRIES` | `3` | Total attempts per request (min 1) |
| `SUDOC_BACKOFF_BASE` | `1.0` | Base seconds for exponential backoff |
| `SUDOC_BACKOFF_FACTOR` | `2.0` | Backoff multiplier per retry |
| `SUDOC_JITTER_MAX` | `0.25` | Max random jitter added per retry |
| `SUDOC_TRACE` | `0` | Set to `1` to enable trace globally |

Retried HTTP status codes: **429, 500, 502, 503, 504**. Timeouts are also
retried up to `SUDOC_MAX_RETRIES`.

---

## Common Workflows

**Find recent French theses on primates:**
```bash
uv run ./skills/search-records-sudoc/scripts/cli.py search \
  --query "mti=primates and msu=hominides" \
  --doc-type y \
  --year-from 2010
```

**Look up a book by ISBN and get its Sudoc PPN:**
```bash
uv run ./skills/search-records-sudoc/scripts/cli.py lookup-by-isbn --isbn 978-2-07-036024-5 \
  | python3 -c "import sys,json; [print(r['ppn']) for r in json.load(sys.stdin)['results']]"
```

**Count how many records Sudoc has for a publisher:**
```bash
uv run ./skills/search-records-sudoc/scripts/cli.py count --query "edi=gallimard"
```

**Cross-language subject search (French + English MeSH):**
```bash
uv run ./skills/search-records-sudoc/scripts/cli.py search \
  --query "vma=antivir* or mee=antivir*" \
  --max-results 50
```

**Find all records held by a specific library (by RCR number):**
```bash
uv run ./skills/search-records-sudoc/scripts/cli.py search \
  --query "rbc=130012101" \
  --max-results 100
```

**Scan the subject index to discover RAMEAU terms starting with "abricot":**
```bash
uv run ./skills/search-records-sudoc/scripts/cli.py scan --index vma --term abricot --max-terms 20
```

**Find Umberto Eco's Italian-language works published after 2015:**
```bash
uv run ./skills/search-records-sudoc/scripts/cli.py search \
  --query "per=eco,umberto" \
  --lang-major ita \
  --year-from 2016
```

**Serials in shared conservation plan "pcmed", excluding orthodontics/dentistry:**
```bash
uv run ./skills/search-records-sudoc/scripts/cli.py search \
  --query "pcp=pcmed not mti=orthod* and pcp=pcmed not mti=dent*" \
  --doc-type t
```

**Find electronic theses about machine learning from Toulouse universities:**
```bash
uv run ./skills/search-records-sudoc/scripts/cli.py search \
  --query "nth=toulouse and mti=machine learning" \
  --doc-type y
```

---

## Query Syntax Reference

### Boolean Operators

| Operator | Syntax | Example |
|---|---|---|
| AND (default) | `and`, `+`, or space | `mti=jardins japonais` |
| OR | `or` or `\|` | `mti=apocope\|apherese` |
| NOT | `not` | `col=dunod not entreprises` |

All three operators have **equal priority**. Use parentheses to control precedence:
`pcp=pcdroit not (fgr=actes congres)`

### Truncation

Use `*` at the end of a term: `mti=orthod*`, `nnt=2018perp*`, `per=eco*`

### Exact Phrase

Wrap in quotes: `tou="ocre jaune"`, `rpc="armes de Dominique*"`

### Combining Multiple Limitations

Limitations (doc-type, language, country, date) are always `AND`-combined with
the main query. You cannot have a query with limitations only — there must
always be at least one regular index term.

---

## Data Coverage and Restrictions

- **Scope:** Bibliographic records and holdings only (no authority records).
- **ISSN Register:** Records from the ISSN Register are restricted, except
  for the **ROAD corpus** and **ISSN France corpus**.
- **Format:** UNIMARC encapsulated in XML, UTF-8.
- **Protocol:** SRU version 1.1.
- **No authentication required.**

---

## Notes

- Output is strict JSON on stdout.
- The Sudoc SRU service has no published rate limit, but courtesy pauses of
  200 ms between paginated requests are applied automatically.
- For the `per` (person name) index: if you don't know the exact normalized
  form, use truncation: `per=eco*` instead of `per=eco,umberto`.
- Accents: searching without accents returns more results (matches both
  accented and unaccented forms). The CLI does not strip accents — pass
  unaccented terms for maximum recall.