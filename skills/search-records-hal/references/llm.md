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

