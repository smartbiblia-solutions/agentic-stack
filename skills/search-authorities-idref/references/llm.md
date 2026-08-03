# IdRef — LLM reference

> Condensed API reference for skill creation and maintenance.
> Generated: 2026-04-17
> Source docs: https://documentation.abes.fr/aideidrefdeveloppeur/

---

## API overview

- **Base URL (search)**: `https://www.idref.fr/Sru/Solr`
- **Base URL (references)**: `https://www.idref.fr/services/references/<PPN>`
- **Protocol**: Solr HTTP API + REST-like micro web service
- **Authentication**: none required
- **Rate limits**: none published in the docs sampled
- **Response format**:
  - Solr search: XML by default, JSON with `wt=json`
  - references micro service: JSON at `.json`
- **Encoding notes**:
  - Solr query syntax follows Solr/Lucene rules.
  - Spaces and reserved query characters must be URL-encoded.
  - Docs show `version=2.2`, `indent=on`, `start`, `rows`, `sort`, `fl`.

---

## Endpoints

### Solr authority search

**URL pattern**:

`GET https://www.idref.fr/Sru/Solr?q=<solr-query>&wt=json&start=<n>&rows=<n>&sort=<field> <dir>&fl=<fields>`

**Key parameters**:

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `q` | string | **required** | Solr query string |
| `wt` | string | XML default | Set `json` for agent use |
| `start` | int | `0` | Offset |
| `rows` | int | implementation-defined | Number of docs |
| `sort` | string | `score desc` | e.g. `affcourt_z asc` |
| `fl` | string | all fields | Comma-separated list of fields |
| `indent` | string | optional | `on` in docs/examples |
| `version` | string | optional | docs examples use `2.2` |

**Non-obvious behavior**:
- Docs explicitly say the default response is XML; JSON requires `wt=json`.
- The service follows Solr specifications; expert queries can use boolean operators and fielded syntax.
- Documented display field: `affcourt_z` = preferred authorized access point in Latin script.
- Documented extra sortable field: `affcourt_z`; `score` is relevance.
- Common examples use exact field names like `persname_t`, `corpname_t`, `ppn_z`, `recordtype_z`, `affiliation_s`, `rattachement_s`, `equivalent_s`, `classification_t`.

**Observed response structure**:

```json
{
  "responseHeader": {
    "status": 0,
    "QTime": 1,
    "params": {
      "q": "persname_t:(Bourdieu AND Pierre)",
      "wt": "json",
      "start": "0",
      "rows": "2",
      "sort": "score desc",
      "fl": "id,ppn_z,recordtype_z,affcourt_z"
    }
  },
  "response": {
    "numFound": 1,
    "start": 0,
    "docs": [
      {
        "id": "91588",
        "ppn_z": "027715078",
        "recordtype_z": "a",
        "affcourt_z": "Bourdieu, Pierre (1930-2002)"
      }
    ]
  }
}
```

### references micro web service

**URL pattern**:

- Generic: `GET https://www.idref.fr/services/references/<PPN>`
- JSON: `GET https://www.idref.fr/services/references/<PPN>.json`
- XML: `GET https://www.idref.fr/services/references/<PPN>.xml`

**Key parameters**:

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `<PPN>` | string | **required** | IdRef authority identifier |

**Non-obvious behavior**:
- The docs say JSON can be requested either by content negotiation or directly with the `.json` suffix.
- Response is grouped by role.
- `referentiel` indicates the source of linked bibliographic data, e.g. Sudoc, Calames, Theses.fr, Persée, Okina, OATAO, HAL, Istex, Orcid, BnF.
- The `doc` field is inconsistent: it may be a single object or an array depending on count.

**Observed response structure**:

```json
{
  "sudoc": {
    "result": {
      "role": [
        {
          "marc21Code": "aut",
          "roleName": "Auteur",
          "count": "146",
          "doc": [
            {
              "citation": "...",
              "referentiel": "sudoc",
              "id": "189894652",
              "URI": "https://www.sudoc.fr/189894652/id",
              "URL": "https://www.sudoc.fr/189894652",
              "ppn": "189894652"
            }
          ],
          "unimarcCode": "070"
        }
      ]
    }
  }
}
```

---

## Field mapping to common record schema

| Common field | Source field | Notes |
|---|---|---|
| `id` | `ppn_z` | Prefer PPN as stable authority identifier |
| `title` | `affcourt_z` | Preferred authorized access point |
| `authors` | — | Not applicable for authority records |
| `abstract` | — | Not available |
| `doi` | — | Not available |
| `pdf_url` | — | Not available |
| `url` | `https://www.idref.fr/<ppn_z>` | Constructed public record URL |
| `year` | — | Not available |
| `date` | — | Not available |
| `doc_type` | `recordtype_z` | IdRef authority type code |
| `journal` | — | Not applicable |

Source-specific fields to preserve:
- `ppn`: `ppn_z`
- `recordtype`: `recordtype_z`
- `solr_id`: `id`

---

## Error handling

- **HTTP errors**: retry on 429, 500, 502, 503, 504.
- **Solr errors**: malformed query may return an HTML or text error body; wrap as `error`.
- **Not found**:
  - Solr search returns `numFound: 0`.
  - references endpoint may not return the expected JSON envelope for an invalid PPN.
- **Application behavior**: prefer resilient parsing and normalize singular `doc` objects to arrays.

---

## Known quirks and gotchas

- Solr docs and examples use many field names ending in `_t`, `_s`, `_z`, `_dt`; preserve them exactly.
- `recordtype_z` is important for narrowing classes of authorities.
- `references` is bibliographic linkage, not the authority description itself.
- Public record URLs and some older endpoint patterns can redirect in odd ways; use the documented service endpoints directly.

---

## Useful query examples

```bash
# Person search
curl 'https://www.idref.fr/Sru/Solr?q=persname_t:(Bourdieu%20AND%20Pierre)&wt=json&sort=score%20desc&start=0&rows=5&fl=id,ppn_z,recordtype_z,affcourt_z'

# Exact PPN lookup
curl 'https://www.idref.fr/Sru/Solr?q=ppn_z:027715078&wt=json&rows=1&fl=id,ppn_z,recordtype_z,affcourt_z'

# Linked references for an authority
curl 'https://www.idref.fr/services/references/02686018X.json'
```
