# HAL Search API — LLM quick reference (api.archives-ouvertes.fr)

Source: https://api.archives-ouvertes.fr/docs/search

This guide is meant for LLM-assisted query building.
HAL’s search API is backed by Apache Solr: you send a Solr query string via `q=` plus optional parameters (`fq`, `fl`, `rows`, `start`, `sort`, `facet.*`, `wt`, …).

---

## 0) MOST IMPORTANT: always scope to a portal or (more often) a collection

Default endpoint searches the **global HAL portal**:

- Base endpoint (global): `https://api.archives-ouvertes.fr/search/`

### Scope to a portal (instance)
Put the portal instance after `/search/`:

- Portal endpoint: `https://api.archives-ouvertes.fr/search/{portalInstance}/`
- Example (TEL portal): `https://api.archives-ouvertes.fr/search/tel/`

Portal instances are listed in the *instance* referential (see “Instances de portail” in the docs).

### Scope to a collection (typical usage)
Put the **collection code** after `/search/`:

- Collection endpoint: `https://api.archives-ouvertes.fr/search/{COLLECTION_CODE}/`
- Example: `https://api.archives-ouvertes.fr/search/FRANCE-GRILLES/`

### Case sensitivity matters
The casing of the path after `/search/` changes semantics:

- `/search/tel/` → portal (instance)
- `/search/FRANCE-GRILLES/` → collection

If you are targeting a specific institutional repository/portal, **prefer collection scoping** (faster + semantically correct).

---

## 1) Core request structure

Minimal requirement: **at least one parameter**, and it must include `q`.

Template:

```
GET https://api.archives-ouvertes.fr/search/{scope}/?q={solrQuery}&wt=json
```

Where:
- `{scope}` is either empty (global), a portal instance, or a collection code.
- `q` is a Solr query.
- `wt` controls the output format (default is json).

---

## 2) Query parameter `q` (Solr query)

### Basic search
- `q=test`

Example:
- `https://api.archives-ouvertes.fr/search/?q=test&wt=xml`

### Default field
If you omit the field name, HAL searches the default index **`text`** (aggregated field).

- `q=asie` is equivalent to `q=text:asie`

### Fielded search
Syntax: `field:value`

Example (search “japon” in title field `title_t`):
- `q=title_t:japon`

### Multiple terms in a field
Default boolean operator is **AND**.

- `q=title_t:(japon france)`

### OR
- `q=title_t:(japon OR france)`

### Phrase search
Use double quotes:
- `q=title_t:"Dictionnaire des idées reçues"`

### Wildcards / truncation
- Single char: `?` → `agricol?`
- Multiple chars: `*` → `agri*`

### Fuzzy match
- `aluminum~` (optionally with distance `~0..2`, default 2)
- Example: `title_t:aluminum~`

### Proximity
- `"aluminium fer"~3`

---

## 3) Escaping special characters (important)

Solr special characters must be escaped (and then URL-encoded as needed):

```
+ - && || ! ( ) { } [ ] ^ " ~ * ? : \
```

Escape with backslash, e.g.:
- `(1+1):2` becomes `\(1\+1\)\:2`

Also comply with URL encoding rules (see RFC3986 in the docs).

---

## 4) Boolean operators

Supported boolean operators and symbols:

- `AND` / `&&`  → both sides must match
- `OR`  / `||`  → at least one side must match
- `NOT` / `!`   → exclude
- `+term` required
- `-term` prohibited

Examples:
- `Paris -France +Texas`
- `Paris AND France AND history NOT (Texas AND history)`
- `Journal AND (Histoire OR History)`

---

## 5) Output format (`wt`)

Default is JSON.

- `wt=json` (default)
- `wt=xml`
- `wt=xml-tei`
- `wt=bibtex`
- `wt=endnote`
- `wt=rss`
- `wt=atom`
- `wt=csv`

Pretty printing:
- `indent=true`

Examples:
- Atom: `.../search/?q=*:*&wt=atom`
- BibTeX: `.../search/?q=*:*&wt=bibtex`

---

## 6) Fields to return (`fl`)

Use `fl` to control which fields are returned (reduce payload, speed up queries).

Typical pattern:
- `fl=title_s,authFullName_s,halId_s,doiId_s,publicationDateY_i,uri_s`

(Choose fields based on your downstream use: display, dedupe, export, analytics.)

---

## 7) Filters (`fq`) [Solr-style]

Use `fq` to apply filter queries (does not affect scoring; cache-friendly). Very useful for:
- year ranges
- document types
- affiliations
- language
- etc.

Pattern:
- `fq=field:value`
- multiple `fq` parameters can be repeated.

(See “Filtres” section in the docs; implement with standard Solr filter query semantics.)

---

## 8) Pagination (`rows`, `start`)

- `rows` = number of results to return
- `start` = offset

Pattern:
- `rows=50&start=0`

---

## 9) Sorting (`sort`)

Solr sort syntax:
- `sort=field asc|desc`

Example:
- `sort=publicationDateY_i desc`

---

## 10) Facets (for aggregations)

HAL uses Solr faceting.

Typical parameters (Solr):
- `facet=true`
- `facet.field=...`
- `facet.limit=...`
- `facet.mincount=...`

Use facets to get counts by year, type, affiliation, journal, etc.

---

## 11) Grouping (collapse / group)

Solr grouping is supported (see “Grouper des résultats”).

Typical parameters (Solr):
- `group=true`
- `group.field=...`
- `group.limit=...`

Use grouping to:
- collapse near-duplicates
- group by identifier

---

## 12) Practical patterns (recommended defaults)

### A) Collection-scoped search for publications with small payload

```
GET https://api.archives-ouvertes.fr/search/{COLLECTION}/?q=text:{term}&fq=docType_s:ART&rows=25&start=0&fl=halId_s,title_s,authFullName_s,doiId_s,publicationDateY_i,uri_s&wt=json
```

### B) Phrase title search

```
GET https://api.archives-ouvertes.fr/search/{COLLECTION}/?q=title_t:"{exact title}"&fl=halId_s,title_s,uri_s&wt=json
```

### C) Facet by year (trend)

```
GET https://api.archives-ouvertes.fr/search/{COLLECTION}/?q=text:{term}&rows=0&facet=true&facet.field=publicationDateY_i&facet.mincount=1&wt=json
```

---

## Notes for skill builders

1) Prefer putting portal/collection in the path rather than a filter.
2) Always set `wt=json` unless exporting BibTeX/TEI.
3) Always set `fl` explicitly for performance.
4) Escape Solr special characters and URL-encode.

---

# Appendix — field types, referentials, advanced faceting

Sources for this appendix:
- Field types and per-field capabilities: https://api.archives-ouvertes.fr/docs/search/?schema=field-types#fields
- Portal instances (JSON): https://api.archives-ouvertes.fr/ref/instance
- Worked request examples (CasuHAL API workshop):
  https://wiki.ccsd.cnrs.fr/wikis/hal/index.php/CasuHAL_AtelierAPI

---

## 13) The suffix decides what a field can do

Every HAL field carries a type suffix, and the suffix — not the field — decides
whether it can be **searched** (`q` / `fq`), **returned** (`fl`), **faceted**
(`facet.field`) or **sorted** (`sort`).

| Suffix | Type | Search | Return | Facet | Sort |
|---|---|:--:|:--:|:--:|:--:|
| `_s` | string, not analysed | — | ✅ | ✅ | ✅ |
| `_t` | text, analysed | ✅ | — | — | — |
| `_sci` | string + text, analysed | ✅ | ✅ | ✅ | ✅ |
| `_i` | integer | ✅ | ✅ | ✅ | ✅ |
| `_bool` | boolean | ✅ | ✅ | ✅ | ✅ |
| `_fs` | facet string (hierarchical) | — | ✅ | ✅ | — |
| `_id` | identifier | ✅ | — | — | — |
| `_tdate` | date | ✅ | ✅ | — | ✅ |
| `_sort` | sort-only | — | — | — | ✅ |

Two consequences that cause most silent failures:

- **`q=title_s:japon` returns zero results with no error.** `_s` is not
  searchable; the searchable twin is `title_t`. Symmetrically `fl=title_t` comes
  back empty — search on `_t`, display on `_s`.
- **`facet.field=producedDate_tdate` is refused**; facet on the derived integer
  `publicationDateY_i` instead.

Rule of thumb: **search `_t`, filter and facet `_s` / `_i`, sort `_i` /
`_tdate` / `_sort`.**

---

## 14) Field catalogue (the ones worth knowing)

**Identifiers**

| Field | Meaning |
|---|---|
| `docid` | Internal HAL document id (integer, stable) |
| `halId_s` | HAL identifier, e.g. `hal-01234567`, `tel-00987654` |
| `halIdSameAs_s` | Other HAL ids of the same deposit (versions) |
| `uri_s` | Public HAL URL of the record |
| `version_i` | Version number of the deposit |
| `doiId_s` | DOI |
| `arxivId_s`, `pubmedId_s`, `pubmedcentralId_s`, `nntId_s` | External ids |
| `issn_s`, `eissn_s`, `isbn_s` | Serial / book identifiers |

**Title, authors, content**

| Field | Notes |
|---|---|
| `title_t` / `title_s` | Search on `_t`, display on `_s` |
| `subTitle_t` / `subTitle_s`, `en_title_t`, `fr_title_t` | Language-typed titles |
| `abstract_t` / `abstract_s` | Same split |
| `keyword_t` / `keyword_s` | Author keywords |
| `authFullName_s` | Author display names, facetable |
| `authLastName_s`, `authFirstName_s`, `authFullNameIdHal_fs` | Split / IdHAL-joined |
| `authIdHal_s`, `authIdHal_i` | IdHAL of the author |
| `authIdForm_i` | Internal author-form id (AuréHAL `author` docid) |
| `text` | Default aggregated index (metadata) |
| `text_fulltext` | Aggregated index **including the deposited full text** |

**Dates** — five families, do not mix them up:

| Field | Meaning |
|---|---|
| `producedDate_tdate` / `producedDateY_i` | Date written by the author |
| `publicationDate_tdate` / `publicationDateY_i` | Publication date (the usual one) |
| `submittedDate_tdate` / `submittedDateY_i` | Date the deposit was submitted |
| `releasedDate_tdate` / `releasedDateY_i` | Date the deposit went online |
| `modifiedDate_tdate` / `modifiedDateY_i` | Last modification |
| `defenseDate_tdate` / `defenseDateY_i` | Thesis / HDR defence |

Each family also comes as `_s` and split `Y_i` / `M_i` / `D_i` parts. Year
ranges use the `Y_i` twin: `fq=publicationDateY_i:[2020 TO 2024]`.

**Typology and status**

| Field | Notes |
|---|---|
| `docType_s` | Document type code — see §15 |
| `docSubType_s` | Sub-type refining `docType_s`: `PREPRINT`, `WORKINGPAPER`, `RESREPORT`, `TECHREPORT`, `FUNDREPORT`, `EXPERTREPORT`, `DMP`, `DATAPAPER`, `BOOKREVIEW`, `ARTREV`, `PHOTOGRAPHY`, `MANUAL`, … |
| `domain_s` / `domainAllCode_s` | HAL scientific domains (`shs.hist`, `info.info-ir`, …) |
| `language_s` | ISO language code |
| `popularLevel_s`, `peerReviewing_s`, `audience_s`, `invitedCommunication_s`, `proceedings_s` | Editorial qualifiers |
| `submitType_s` | `file`, `notice`, `annex` — whether a full text is attached |
| `openAccess_bool` | Open access flag |

**Files**

`fileMain_s` (main file URL), `files_s`, `fileType_s`, `fileAnnexes_s`,
`licence_s`, `linkExtUrl_s`, `linkExtId_s`.

**Journal, publisher, conference**

`journalTitle_s`, `journalPublisher_s`, `journalIssn_s`, `journalEissn_s`,
`volume_s`, `issue_s`, `page_s`, `publisher_s`, `bookTitle_s`,
`conferenceTitle_s`, `conferenceStartDate_tdate`, `city_s`, `country_s`.

**Structures and affiliations** — the joined fields are what make institutional
queries possible:

| Field | Notes |
|---|---|
| `structId_i` | AuréHAL structure docid of any affiliation, **including parents** |
| `structAcronym_s`, `structName_s`, `structType_s`, `structCountry_s` | Structure attributes |
| `labStructId_i`, `labStructAcronym_s`, `labStructName_s` | Affiliations of type *laboratory* only |
| `instStructId_i`, `instStructAcronym_s`, `instStructName_s` | Affiliations of type *institution* only |
| `rteamStructId_i`, `deptStructId_i` | Research team / department |
| `structHasAuthId_fs`, `structHasAuthIdHal_fs`, `structHasAuthIdHalFullName_fs` | Structure↔author joined facets — see §20 B for the bucket format |
| `collCode_s`, `collName_s`, `collId_i` | Collections the record belongs to |
| `anrProjectId_i`, `anrProjectTitle_s`, `europeanProjectId_i`, `europeanProjectTitle_s` | Funding |

---

## 15) `docType_s` codes

Live facet counts on global HAL, most frequent first:

`ART` article · `COMM` conference communication · `COUV` book chapter ·
`THESE` doctoral thesis · `OUV` book · `MEM` student dissertation ·
`UNDEFINED` · `POSTER` · `OTHER` · `REPORT` report · `IMG` still image ·
`ISSUE` journal issue · `BLOG` blog post · `NOTICE` reference notice ·
`PROCEEDINGS` · `HDR` habilitation · `PATENT` · `VIDEO` · `REPORT_LABO` ·
`LECTURE` teaching material · `TRAD` translation ·
`REPORT_MAST` / `REPORT_LPRO` / `REPORT_LICE` / `REPORT_DOCT` / `REPORT_ETAB` /
`REPORT_FORM` / `REPORT_GMAST` / `REPORT_GLICE` / `REPORT_FPROJ` /
`REPORT_COOR` / `REPORT_RFOINT` / `REPORT_RETABINT` (report sub-types) ·
`SOFTWARE` · `PRESCONF` conference preface · `CREPORT` critical report ·
`SON` audio · `MAP` · `NOTE` · `SYNTHESE` · `ETABTHESE` · `REPACT` · `MEMLIC`.

A preprint is **not** a `docType_s`: it is `docType_s:UNDEFINED` plus
`docSubType_s:PREPRINT`. Same for report flavours (`REPORT` +
`RESREPORT` / `TECHREPORT` / `FUNDREPORT` / `EXPERTREPORT` / `DMP`).

Refresh either list at any time with:

```
GET https://api.archives-ouvertes.fr/search/?q=*:*&rows=0&facet=true&facet.field=docType_s&facet.limit=60&wt=json
GET https://api.archives-ouvertes.fr/search/?q=*:*&rows=0&facet=true&facet.field=docSubType_s&facet.limit=40&wt=json
```

---

## 16) Defaults and limits

- **`rows` defaults to 30**, not 10. Always set it explicitly.
- `rows=0` returns counts and facets only — the cheapest way to get an
  aggregation.
- Deep paging with `start` degrades; past a few thousand rows prefer
  `cursorMark=*` with a deterministic `sort` (e.g. `sort=docid asc`).
- The API is **public and anonymous**: no key, no quota published, but be
  reasonable — one pooled connection, no parallel storms.
- `q` is mandatory; use `q=*:*` when you only want filters and facets.

---

## 17) Referentials (AuréHAL) — `https://api.archives-ouvertes.fr/ref/`

Same Solr grammar as `/search/` (`q`, `fq`, `fl`, `rows`, `sort`, `wt=json`),
different corpora. Use them to turn a name into an id, then filter `/search/` on
that id.

| Endpoint | Contains | Key fields | Join back into `/search/` with |
|---|---|---|---|
| `/ref/structure/` | Laboratories, institutions, teams | `docid`, `label_s`, `name_s`, `acronym_s`, `type_s`, `valid_s`, `country_s`, `address_s`, `parentDocid_i` / `parentName_s` / `parentType_s`, and the external ids `ror_s`, `idref_s`, `rnsr_s`, `wikidata_s` (each with a `…Url_s` twin) | `structId_i:<docid>` (or `labStructId_i`, `instStructId_i`) |
| `/ref/author/` | Author forms | `docid` (`"<form_i>-<person_i>"`), `form_i`, `person_i`, `fullName_s`, `fullName_sci`, `lastName_s`, `firstName_s`, `valid_s`, `orcidId_s` | `authIdForm_i:<form_i>` / `authIdHal_i:<person_i>` / `authIdHal_s:<idHal>` |
| `/ref/journal/` | Journals | `docid`, `title_s`, `issn_s`, `eissn_s`, `publisher_s`, `valid_s` | `journalId_i:<docid>` |
| `/ref/anrproject/` | ANR projects | `docid`, `title_s`, `acronym_s`, `reference_s`, `year_i` | `anrProjectId_i:<docid>` |
| `/ref/europeanproject/` | European projects | `docid`, `title_s`, `acronym_s`, `reference_s`, `programme_s` | `europeanProjectId_i:<docid>` |
| `/ref/domain/` | HAL scientific domains | `docid`, `code_s`, `label_s`, `fr_domain_s`, `en_domain_s`, `level_i`, `parent_i` | `domainAllCode_s:<code>` |
| `/ref/instance/` | Portals — see §18 | `code`, `name`, `url`, `deprecated` | path scoping `/search/<code>/` |
| `/ref/doctype/` | Document types | — | not Solr-shaped; use the `docType_s` facet instead (§15) |

`valid_s` matters on `structure` and `journal`: `VALID`, `OLD`, `INCOMING`,
`DELETED`. Filter `fq=valid_s:VALID` unless you deliberately want the
deduplication history.

Structures are hierarchical: `parentDocid_i` on a child, so the sub-structures of
a laboratory are `q=parentDocid_i:<docid>`. `structId_i` in `/search/` already
matches through the hierarchy — a query on a university's docid also returns its
laboratories' deposits.

---

## 18) Portal instances (`/ref/instance`)

```
GET https://api.archives-ouvertes.fr/ref/instance?wt=json
```

Returns all 216 portals in one shot under `response.docs` — **it ignores `q` and
`rows`**, so filter client-side. Entries are *not* Solr documents: each carries
`id`, `code` (the path segment: `tel`, `pastel`, `inria`, `lara`, …), `name`
(French label), `url`, and `deprecated` as the **string** `"true"` / `"false"`,
not a boolean.

```jsonc
{"id": "9", "code": "tel", "name": "TEL - Thèses en ligne",
 "url": "https://theses.hal.science", "deprecated": "false"}
```

Two portals sit apart from institutional ones: `tel` (TEL — Thèses en ligne) and
`memsic` (dissertations). Note the accents in `name` are literal — a substring
search for `these` does not match "Thèses".

---

## 19) Advanced faceting

Beyond `facet.field` / `facet.limit` / `facet.mincount`:

| Parameter | Effect |
|---|---|
| `facet.sort=count\|index` | Order buckets by frequency (default) or alphabetically — `index` is what you want for a year axis |
| `facet.prefix=<str>` | Keep only buckets starting with `<str>`. Essential on the joined `_fs` fields |
| `facet.pivot=f1,f2[,f3]` | Nested cross-tabulation: counts of `f2` inside each bucket of `f1` |
| `facet.mincount=2` | With a pivot, a cheap duplicate detector |

`facet.limit=-1` removes the cap; do it only on a scoped query.

---

## 20) Worked patterns (CasuHAL workshop)

### A) Name → author ids → publications

`/ref/author/` is indexed by name, **not** by structure: there is no
`structureId_i` there, and asking for one returns `{"error": …}`. Resolve the
person first, then join.

```
GET https://api.archives-ouvertes.fr/ref/author/?q=fullName_t:"Franck Montmessin"&fl=docid,form_i,person_i,fullName_s,valid_s,orcidId_s&wt=json
→ form_i 1195, person_i 174267 (valid_s PREFERRED)
GET https://api.archives-ouvertes.fr/search/?q=authIdHal_i:174267&rows=100&wt=json
```

`authIdForm_i:<form_i>` matches one *spelling* of the name;
`authIdHal_i:<person_i>` (or `authIdHal_s:<idHal>`) matches the *person* across
spellings — prefer the latter. To go the other way, from a structure to its
authors, use the facet in B.

### B) Which authors of a laboratory deposited, and how much

`structHasAuthIdHal_fs` values are prefixed by the structure id, so a
`facet.prefix` restricts the facet to one laboratory:

```
GET https://api.archives-ouvertes.fr/search/?q=*:*&fq=structId_i:81173&rows=0
    &facet=true&facet.field=structHasAuthIdHal_fs&facet.prefix=81173_
    &facet.limit=-1&facet.mincount=1&wt=json
```

Each bucket reads
`<structId>_FacetSep_<structure label>_JoinSep_<idHal>_FacetSep_<Full Name>`,
e.g. `81173_FacetSep_Université de Versailles Saint-Quentin-en-Yvelines_JoinSep_franck-montmessin_FacetSep_Montmessin Franck`.
Split on `_JoinSep_` first, then on `_FacetSep_`. The idHal segment is **empty**
for authors who have none — the name is still there, which is the point of the
facet.

### C) Candidate duplicates inside a perimeter

Same title appearing under more than one HAL id:

```
GET https://api.archives-ouvertes.fr/search/?q=*:*&fq=collCode_s:<COLL>&rows=0
    &facet=true&facet.pivot=title_s,docType_s,halId_s&facet.mincount=2
    &facet.limit=-1&wt=json
```

### D) Sub-structures of a laboratory

```
GET https://api.archives-ouvertes.fr/ref/structure/?q=parentDocid_i:300297&fq=valid_s:VALID&fl=docid,label_s,type_s&wt=json
```

### E) Name → structure id → publications

```
GET https://api.archives-ouvertes.fr/ref/structure/?q=acronym_t:CRIStAL&fq=valid_s:VALID&fl=docid,label_s,type_s&wt=json
→ docid 410272
GET https://api.archives-ouvertes.fr/search/?q=structId_i:410272&fq=publicationDateY_i:[2020 TO 2024]
    &fl=halId_s,title_s,authFullName_s,doiId_s,publicationDateY_i,uri_s&rows=100&wt=json
```

### F) Full-text search rather than metadata search

```
GET https://api.archives-ouvertes.fr/search/?q=text_fulltext:"transition énergétique"&fq=submitType_s:file&rows=20&wt=json
```

### G) Annual production of an institution, as a time series

```
GET https://api.archives-ouvertes.fr/search/?q=*:*&fq=instStructId_i:<docid>&rows=0
    &facet=true&facet.field=publicationDateY_i&facet.sort=index&facet.limit=-1&wt=json
```

