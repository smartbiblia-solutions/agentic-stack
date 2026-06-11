# Sudoc SRU API Guide for LLM Agents and AI Applications

Sudoc (Système Universitaire de Documentation) is the French academic union catalog, maintained by ABES (Agence bibliographique de l'enseignement supérieur). It contains bibliographic records and holdings data for French higher education and research libraries.

```
Base URL:        https://www.sudoc.abes.fr/cbs/sru/
Protocol:        SRU (Search/Retrieve via URL) version 1.1
Data format:     UNIMARC encapsulated in XML (UTF-8)
Authentication:  None required
Coverage:        Bibliographic records + holdings (no authority records)
```

> **Note for AI agents:** Sudoc uses the SRU protocol (not a REST API). Queries are URL-based with specific encoding rules. Read the encoding section carefully before building queries.

---

## CRITICAL GOTCHAS — Read These First!

### ❌ DON'T: Use `=` directly in query search clauses

WRONG: `query=mti=arbres`  
The `=` sign is reserved for SRU URL parameters.

### ✅ DO: Always encode `=` as `%3D` in search clauses

CORRECT: `query=mti%3Darbres`

This applies to every index-value pair. It is the single most common source of errors.

---

### ❌ DON'T: Omit `recordSchema=unimarc`

WRONG: `?operation=searchRetrieve&version=1.1&query=mti%3Darbres`  
The server may not return usable records.

### ✅ DO: Always include `recordSchema=unimarc`

CORRECT: `?operation=searchRetrieve&version=1.1&recordSchema=unimarc&query=mti%3Darbres`

---

### ❌ DON'T: Search for authors by free-text name in a general index

WRONG: `query=tou%3Dzola emile`  
This searches all fields and produces noisy results.

### ✅ DO: Use the appropriate author index

CORRECT for author words: `query=aut%3Dzola`  
CORRECT for full person name (phrase index): `query=per%3Dzola%2CEmile`  
CORRECT for corporate author (phrase index): `query=org%3Dinsee`

---

### ❌ DON'T: Use `>=` or `<=` literally in date queries

WRONG: `apu%3D>=2010`

### ✅ DO: Use encoded comparison operators for dates

- Greater than or equal: `apu%3D%3E%3D2010` or `apu%3D>%3D2010`
- Less than or equal: `apu%3D%3C%3D2010` or `apu%3D<%3D2010`
- Greater than (strict): `apu%3D%3E2010` or `apu%3D>2010`
- Less than (strict): `apu%3D%3C2010` or `apu%3D<2010`

---

### ❌ DON'T: Forget to quote multi-word terms in phrase indexes

WRONG: `query=org%3Dinsee rhone alpes` (ambiguous — are "rhone alpes" in the same clause?)  
WRONG: `query=per%3Deco umberto` (will not match the phrase index correctly)

### ✅ DO: Use quotes (or `%22`) for multi-word terms in phrase indexes

CORRECT: `query=org%3D"insee rhone alpes"`  
CORRECT: `query=per%3Deco%2Cumberto` (comma = `%2C` in PER index)

Phrase indexes require the full, exact form. Use truncation `*` (encoded `%2A`) when you don't know the exact form.

---

### ❌ DON'T: Use a search term that matches an index key without quoting it

WRONG: `query=mti%3Dcol` — this will be interpreted as the `COL` index, not the word "col"  
WRONG: `query=lai%3Dper` — `per` is both the Persian language code AND the PER index key

### ✅ DO: Quote any search term that coincides with an index key

CORRECT: `query=mti%3D"col" and galibier`  
CORRECT: `query=lai%3D"per"`

---

### ❌ DON'T: Expect accent-sensitive searches to return all results

Accented terms only match their accented form → fewer results.

### ✅ DO: Search without accents for maximum recall

`query=mti%3Dmemoires` matches both "mémoires" and "memoires"  
`query=mti%3Dmémoires` matches only "mémoires"

---

## Quick Reference

### The Three SRU Operations

| Operation | Purpose | URL |
|---|---|---|
| `explain` | Discover server capabilities | `?operation=explain&version=1.1` |
| `scan` | Browse an index (useful for debugging) | `?operation=scan&version=1.1&scanClause=` |
| `searchRetrieve` | Search and retrieve records | `?operation=searchRetrieve&version=1.1&recordSchema=unimarc&query=` |

### Base URL for searchRetrieve (use this as your template)

```
https://www.sudoc.abes.fr/cbs/sru/?operation=searchRetrieve&version=1.1&recordSchema=unimarc&query=
```

### Essential Parameters for searchRetrieve

| Parameter | Required | Default | Max | Description |
|---|---|---|---|---|
| `operation` | ✅ | — | — | Always `searchRetrieve` |
| `version` | ✅ | — | — | Always `1.1` |
| `recordSchema` | ✅* | — | — | Always `unimarc` (*technically optional but required in practice) |
| `query` | ✅ | — | — | Search criteria (see Query Syntax section) |
| `startRecord` | ❌ | `1` | — | First result position (must be > 0) |
| `maximumRecords` | ❌ | `10` | `1000` | Number of records per page |
| `recordPacking` | ❌ | `xml` | — | Always `xml` |

### Special Characters Encoding Table

| Character | Encoded | Use case |
|---|---|---|
| `=` | `%3D` | **Mandatory** after every index key in query |
| `>` | `%3E` | Date comparison (strictly greater than) |
| `>=` | `%3E%3D` | Date comparison (greater than or equal) |
| `<` | `%3C` | Date comparison (strictly less than) |
| `<=` | `%3C%3D` | Date comparison (less than or equal) |
| `\|` | `%7C` | Boolean OR operator |
| `"` | `%22` | Exact phrase / quoting |
| `,` | `%2C` | Used in PER index (lastname,firstname) |
| `-` | `%2D` | Hyphens in identifiers or titles |
| `*` | `%2A` | Truncation wildcard |
| `/` | `%2F` | Shelf marks (COT index) |

---

## Query Syntax

### Structure of a Search Clause

```
query=[index]%3D[term]
```

Example: `query=mti%3Darbres` → search for "arbres" in title words index

### Boolean Operators

All three operators (AND, OR, NOT) have **equal priority**. The query executes left to right. Use parentheses to control precedence.

| Operator | Syntax alternatives | Notes |
|---|---|---|
| AND | `and`, `+`, or just a space | Default operator — can be omitted |
| OR | `or`, `\|`, `%7C` | |
| NOT | `not` | Exclusion |

```
# All three are equivalent:
query=mti%3Djardins and japonais
query=mti%3Djardins+japonais
query=mti%3Djardins japonais

# OR example:
query=mti%3Dapocope or apherese
query=mti%3Dapocope|apherese

# NOT example:
query=col%3Ddunod not entreprises

# Parentheses for precedence:
query=pcp%3Dpcdroit not (fgr%3Dactes congres)
```

### Searching the Same Index vs. Different Indexes

When chaining terms in the same index, you do **not** need to repeat the index key:

```
# These are equivalent:
query=nth%3Dpolynesie not memoire
query=nth%3Dpolynesie not nth%3Dmemoire
```

When combining **different** indexes, each needs its own key:

```
query=aut%3Dzola and mti%3Dventre paris
query=aut%3Dzola+mti%3Dventre+paris
```

### Truncation

Use `*` (or `%2A`) at the end of a term:

```
query=nnt%3D2018perp*          # theses starting with "2018perp"
query=mti%3Dorthod*            # titles with words starting with "orthod"
query=per%3Deco*               # person names starting with "eco"
```

### Exact Phrase Search

Wrap the phrase in double quotes `"` (or `%22`):

```
query=tou%3D"ocre jaune"
query=res%3D"vers blancs"
query=rpc%3D"armes de Dominique Barnabé Turgot de Saint-Clair"

# Truncation inside phrases works:
query=rpc%3D"armes de Dominique*"
```

---

## Index Reference

### Index Types

- **mot** (word index): Search for individual words. Terms do not need to be complete.
- **phrase** (phrase index): Requires the full, exact form of the term. Use truncation `*` if uncertain.
- **numérique** (numeric index): For identifiers (ISBN, ISSN, record numbers, etc.).

### Full Index List

#### Identifier Indexes (numérique)

| Key | Description | Example query |
|---|---|---|
| `PPN` | Sudoc record number | `query=ppn%3D070685045` |
| `NUM` | All identifiers | `query=num%3DDLV-20160831-5586` |
| `ISB` | ISBN (with or without hyphens) | `query=isb%3D9782081603752` |
| `ISN` | ISSN (with or without hyphens) | `query=isn%3D2558-4278` |
| `NNT` | National thesis number | `query=nnt%3D2018perp*` |
| `SOU` | Source number | `query=sou%3Dstar*` |
| `OCN` | WorldCat record number | `query=ocn%3D690860108` |
| `BQT` | Electronic resource bundle code | `query=bqt%3D2014-110` |

#### Title Indexes

| Key | Type | Description | Example query |
|---|---|---|---|
| `MTI` | mot | Title words | `query=mti%3Djardins japonais` |
| `TCO` | phrase | Full title | `query=tco%3Doui-oui*` |
| `TAB` | phrase | Abbreviated title (serials) | `query=tab%3Dnat*` |
| `COL` | mot | Collection/series | `query=col%3Ddunod` |

#### Author Indexes

| Key | Type | Description | Example query |
|---|---|---|---|
| `AUT` | mot | Author words | `query=aut%3Dlagerlof` |
| `PER` | phrase | Person name (Lastname,Firstname) | `query=per%3Deco%2Cumberto` |
| `ORG` | phrase | Corporate/organizational author | `query=org%3Dinsee` |

#### Subject Indexes

| Key | Type | Description | Example query |
|---|---|---|---|
| `MSU` | mot | Subject words (French) | `query=msu%3Dhominides` |
| `VMA` | phrase | Subject access point (French) | `query=vma%3Dabricot*` |
| `FGR` | mot | Form/Genre | `query=fgr%3Dactes congres` |
| `MSA` | mot | Subject words (English) | `query=msa%3Dapricot*` |
| `MEE` | mot | MeSH subject (English) | `query=mee%3Dantivir*` |

#### Notes Indexes

| Key | Type | Description | Example query |
|---|---|---|---|
| `NTH` | mot | Thesis note | `query=nth%3Dbiophysique lyon` |
| `RES` | mot | Abstract/summary | `query=res%3D"vers blancs"` |
| `LVA` | mot | Old/rare books note | `query=lva%3Dmemoires` |
| `FIR` | mot | Funding source | `query=fir%3Dlabx` |
| `REC` | mot | Award note | `query=rec%3Daward*` |

#### Holdings Indexes

| Key | Type | Description | Example query |
|---|---|---|---|
| `RBC` | numérique | Library RCR number | `query=rbc%3D840079901` |
| `PCP` | mot | Shared conservation plan | `query=pcp%3Dpcdroit` |
| `RPC` | mot | Binding/provenance/conservation note | `query=rpc%3D"armes de*"` |
| `COT` | phrase | Shelf mark | `query=cot%3D"839.73 EKM"` |

#### General Indexes

| Key | Type | Description | Example query |
|---|---|---|---|
| `TOU` | mot | All words (all fields) | `query=tou%3D"ocre jaune"` |
| `EDI` | mot | Publisher | `query=edi%3Ddomino` |

---

## Limitations (Filters)

Limitations restrict results by document type, language, or country. They **must always be combined with at least one index**.

### Document Type: `TDO`

| Code | Document type |
|---|---|
| `a` | Articles |
| `b` | Printed monographs |
| `f` | Manuscripts |
| `g` | Musical sound recordings |
| `i` | Still images |
| `k` | Printed and manuscript maps |
| `m` | Printed and manuscript scores |
| `n` | Non-musical sound recordings |
| `o` | Electronic monographs |
| `t` | Serials and collections (all formats) |
| `v` | Audiovisual documents |
| `x` | Objects, multimedia documents |
| `y` | Theses (print and electronic) |

```
# Theses about primates with hominid subject:
query=mti%3Dprimates and msu%3Dhominides and tdo%3Dy

# Photographs of lighthouses:
query=tou%3D(phare* not fana*) and tdo%3Di
```

### Language: `LAN` (10 major languages) / `LAI` (all others)

Use **`LAN`** for these 10 languages:

| Code | Language |
|---|---|
| `ger` | German |
| `eng` | English |
| `spa` | Spanish |
| `fre` | French |
| `ita` | Italian |
| `lat` | Latin |
| `dut` | Dutch |
| `pol` | Polish |
| `por` | Portuguese |
| `rus` | Russian |

For all other languages, use **`LAI`** with [ISO 639-2 / ISO 639-3](https://www.loc.gov/standards/iso639-2/) codes.  
For Danish: `lai%3Ddan` | For Arabic: `lai%3Dara` | For Japanese: `lai%3Djpn`

```
# Books by Blixen in Danish about Africa:
query=aut%3Dblixen and mti%3Dafri* and lai%3Ddan

# Books by Umberto Eco in Italian after 2015:
query=per%3Deco%2Cumberto and lan%3Dita and apu%3D>2015
```

### Country: `PAY` (11 major countries) / `PAI` (all others)

Use **`PAY`** for these 11 countries:

| Code | Country |
|---|---|
| `de` | Germany |
| `be` | Belgium |
| `ca` | Canada |
| `es` | Spain |
| `us` | United States |
| `fr` | France |
| `it` | Italy |
| `nl` | Netherlands |
| `gb` | United Kingdom |
| `ru` | Russia |
| `ch` | Switzerland |

For all other countries, use **`PAI`** with [ISO 3166](https://www.iso.org/iso-3166-country-codes.html) codes.  
For Sweden: `pai%3Dse` | For Japan: `pai%3Djp`

```
# PUF books published in Belgium in 1991:
query=edi%3Dpuf and apu%3D1991 and pay%3Dbe
```

---

## Date Queries: `APU`

The `APU` limitation filters by publication date. It must be combined with at least one index.

### Simple Dates

```
# Equal to 2014:
query=edi%3Ddomino and apu%3D2014

# Strictly after 2010:
query=edi%3Ddomino and apu%3D>2010
query=edi%3Ddomino+apu%3D%3E2010

# 2010 or later (>= encoded):
query=edi%3Ddomino and apu%3D>%3D2010
query=edi%3Ddomino and apu%3D%3E%3D2010

# Strictly before 2010:
query=edi%3Ddomino and apu%3D<2010

# Up to and including 2010 (<= encoded):
query=edi%3Ddomino and apu%3D<%3D2010
```

### Date Ranges

```
# Between 1995 and 2000 (inclusive, shorthand):
query=rec%3Daward* and apu%3D1995-2000

# After 2015 (exclusive) and up to 2022 (inclusive):
query=fir%3Dlabx and apu%3D>2015 and apu%3D<%3D2022

# Between 1981 and 1989 (both exclusive):
query=edi%3Ddomino and apu%3D>1980 and apu%3D<1990
```

> Quotes around dates are optional: `apu%3D2014` and `apu%3D"2014"` are equivalent.

---

## Common Query Patterns

### Pattern 1 — Single index, single term

```
https://www.sudoc.abes.fr/cbs/sru/?operation=searchRetrieve&version=1.1&recordSchema=unimarc&query=ppn%3D070685045
```

### Pattern 2 — Single index, multiple terms (AND)

```
https://www.sudoc.abes.fr/cbs/sru/?operation=searchRetrieve&version=1.1&recordSchema=unimarc&query=mti%3Dvents+sud
```

### Pattern 3 — Single index, multiple terms (OR)

```
https://www.sudoc.abes.fr/cbs/sru/?operation=searchRetrieve&version=1.1&recordSchema=unimarc&query=mti%3Dapocope|apherese
```

### Pattern 4 — Two indexes (AND)

```
https://www.sudoc.abes.fr/cbs/sru/?operation=searchRetrieve&version=1.1&recordSchema=unimarc&query=aut%3Dlagerlof+mti%3Dtroll
```

### Pattern 5 — Two indexes (OR), cross-language subject search

```
https://www.sudoc.abes.fr/cbs/sru/?operation=searchRetrieve&version=1.1&recordSchema=unimarc&query=vma%3Dabricot*|msa%3Dapricot*
```

### Pattern 6 — Exclusion (NOT)

```
https://www.sudoc.abes.fr/cbs/sru/?operation=searchRetrieve&version=1.1&recordSchema=unimarc&query=col%3Ddunod not entreprises
```

### Pattern 7 — Document type filter

```
# Theses about Polynesia:
https://www.sudoc.abes.fr/cbs/sru/?operation=searchRetrieve&version=1.1&recordSchema=unimarc&query=nth%3Dpolynesie+tdo%3Dy
```

### Pattern 8 — Language filter

```
# Blixen works in Danish about Africa:
https://www.sudoc.abes.fr/cbs/sru/?operation=searchRetrieve&version=1.1&recordSchema=unimarc&query=aut%3Dblixen+mti%3Dafri*+lai%3Ddan
```

### Pattern 9 — Date range with subject

```
# Award-winning works 1995–2000:
https://www.sudoc.abes.fr/cbs/sru/?operation=searchRetrieve&version=1.1&recordSchema=unimarc&query=rec%3Daward*+apu%3D1995-2000
```

### Pattern 10 — Pagination (retrieve records 51–100)

```
https://www.sudoc.abes.fr/cbs/sru/?operation=searchRetrieve&version=1.1&recordSchema=unimarc&maximumRecords=50&startRecord=51&query=org%3Dinsee not "insee rhone*"
```

### Pattern 11 — Holdings: all records held by a specific library

```
# All records held by library with RCR 840079901:
https://www.sudoc.abes.fr/cbs/sru/?operation=searchRetrieve&version=1.1&recordSchema=unimarc&query=rbc%3D840079901
```

### Pattern 12 — Holdings + corpus: records from CAIRN held by ABES

```
https://www.sudoc.abes.fr/cbs/sru/?operation=searchRetrieve&version=1.1&recordSchema=unimarc&query=rbc%3D341729901+sou%3Dfrcairn*
```

---

## Pagination

Use `startRecord` and `maximumRecords` together to page through results.

```
# Total records returned in response: srw:numberOfRecords
# Default page size: 10
# Maximum page size: 1000

# Page 1 (records 1–50):
&maximumRecords=50&startRecord=1

# Page 2 (records 51–100):
&maximumRecords=50&startRecord=51

# Page 3 (records 101–150):
&maximumRecords=50&startRecord=101
```

> The total count of results is in `<srw:numberOfRecords>` in the XML response.

---

## Response Structure

The `searchRetrieve` operation returns XML. Key elements:

```xml
<srw:searchRetrieveResponse>
  <srw:numberOfRecords>65</srw:numberOfRecords>   <!-- Total matching records -->
  <srw:resultSetId>SIDa12fcb83-86fS2</srw:resultSetId>

  <srw:records>
    <srw:record>
      <srw:recordSchema>unimarc</srw:recordSchema>
      <srw:recordPacking>xml</srw:recordPacking>
      <srw:recordData>
        <record>
          <!-- UNIMARC bibliographic record -->
        </record>
      </srw:recordData>
      <srw:recordPosition>1</srw:recordPosition>  <!-- Position in result list -->
    </srw:record>
    <!-- ... more records ... -->
  </srw:records>

  <srw:echoedSearchRetrieveRequest>
    <srw:query>...</srw:query>      <!-- Query as executed -->
    <srw:xQuery>...</srw:xQuery>    <!-- CQL decomposition in XML -->
    <maximumRecords>10</maximumRecords>
  </srw:echoedSearchRetrieveRequest>
</srw:searchRetrieveResponse>
```

---

## Using the `scan` Operation

`scan` browses an index alphabetically. Useful for discovering valid terms or debugging zero-result queries.

```
https://www.sudoc.abes.fr/cbs/sru/?operation=scan&version=1.1&scanClause=mti%3Dpar&responsePosition=1&maximumTerms=25
```

| Parameter | Description | Default |
|---|---|---|
| `scanClause` | Index key + term to scan from | required |
| `responsePosition` | Position of the scanned term in the list | `1` |
| `maximumTerms` | Number of terms to return | `10` |

---

## Data Coverage and Restrictions

- **Scope:** Bibliographic records and holdings data only (no authority records)
- **ISSN Register restriction:** Records derived from the ISSN Register are restricted, **except** for the ROAD corpus and ISSN France corpus
- **Encoding:** UTF-8
- **Format:** UNIMARC in XML
- **Protocol version:** SRU 1.1 — see [Library of Congress SRU specification](http://www.loc.gov/standards/sru)

---

## Advanced Tips

### Shelf Marks (COT index)

The COT index is a phrase index with special handling for punctuation:

- **Multi-element shelf marks**: wrap in quotes — `"650.6 GIL"`
- **Simple shelf marks**: no quotes needed — `CEAN-4578`
- **Special characters**: omit `()` and `""` from the shelf mark; encode `=` as `%3D` and `/` as `%2F`; keep `-` and `…`; `°`, `+`, `:` are optional

```
# Examples:
query=cot%3D"HM F 8875"
query=cot%3DCEAN-4578
query=cot%3D"944.083%2F305 LEG"
query=cot%3D839.7*    # truncation works
```

### Complex Exclusion with Parentheses

```
# Serials in shared conservation plan "pcmed", 
# excluding those with orthodontics or dentistry in the title:
query=pcp%3Dpcmed not (mti%3Dorthod* or dent*)
query=pcp%3Dpcmed not mti%3D(orthod* or dent*)
```

### Cross-language Subject Search

To maximize recall on a subject topic, combine French and English subject indexes with OR:

```
query=vma%3Dantivir*|mee%3Dantivir*
```

### Saving Results from a Browser

When querying from a browser, save the XML response with `Ctrl+S` and save as `.xml`.

---

## Common Mistakes to Avoid

1. ❌ Using `=` unencoded in query clauses → ✅ Always use `%3D`
2. ❌ Omitting `recordSchema=unimarc` → ✅ Always include it
3. ❌ Using `>=` or `<=` literally in date queries → ✅ Encode as `%3E%3D` / `%3C%3D`
4. ❌ Forgetting quotes for multi-word terms in phrase indexes → ✅ Use `"term1 term2"` or `%22term1 term2%22`
5. ❌ Using an accented search term expecting full recall → ✅ Search without accents for broader results
6. ❌ Using a term that matches an index key (e.g., `col`, `per`) without quoting → ✅ Wrap in `""` 
7. ❌ Combining limitations without any index → ✅ Limitations (`TDO`, `LAN`, `APU`, etc.) must always accompany at least one index
8. ❌ Using `LAI` for one of the 10 major languages → ✅ Use `LAN` for those 10 (ger, eng, spa, fre, ita, lat, dut, pol, por, rus)
9. ❌ Using `PAI` for one of the 11 major countries → ✅ Use `PAY` for those 11 (de, be, ca, es, us, fr, it, nl, gb, ru, ch)
10. ❌ Hyphenated terms in phrase indexes without encoding → ✅ Keep `-` as-is or encode as `%2D`; use truncation if uncertain

---

## Quick Diagnostic: Use `explain` to Inspect the Server

```
https://www.sudoc.abes.fr/cbs/sru/?operation=explain&version=1.1
```

This returns the server's capabilities, available indexes, and configuration. The `indexSet` name is `pica`, but you do **not** need to qualify index keys with it:

- `query=pica.mti%3Dpagnol` is equivalent to `query=mti%3Dpagnol`

---

## Further Resources

- **Sudoc public catalog:** https://www.sudoc.abes.fr
- **ABES website:** https://www.abes.fr
- **SRU standard (Library of Congress):** http://www.loc.gov/standards/sru
- **ISO 639-2/639-3 language codes:** https://www.loc.gov/standards/iso639-2/
- **ISO 3166 country codes:** https://www.iso.org/iso-3166-country-codes.html
- **SRU Diagnostics List:** http://www.loc.gov/standards/sru/diagnostics/

---

*This guide was produced for LLM agents, AI applications, and automated tools querying the Sudoc SRU service. Source documentation: ABES, "Guide d'utilisation du service SRU du catalogue Sudoc", November 2023.*