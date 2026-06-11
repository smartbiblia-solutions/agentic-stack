# Qualinka/Paprika IdRef — LLM reference

> Condensed API reference for skill creation and maintenance.
> Generated: 2026-04-28
> Source docs: https://github.com/abes-esr/qualinka-microservices and observed public endpoints.

---

## API overview

- **Base URLs**:
  - `https://qualinka.idref.fr/data/find-ra-idref/api/v2/debug/req`
  - `https://qualinka.idref.fr/data/attrra/api/v2/req`
  - `https://www.idref.fr/services/references/<PPN>.json`
- **Protocol**: REST over HTTPS
- **Authentication**: none required
- **Response format**: JSON
- **Primary use**: person authority candidate generation, authority enrichment, and linked-reference retrieval.
- **Encoding notes**: query parameters must be URL-encoded UTF-8.

---

## Endpoints

### `find-ra-idref`

**URL pattern**:

```text
GET https://qualinka.idref.fr/data/find-ra-idref/api/v2/debug/req?lastName=<last>&firstName=<first>
```

**Key parameters**:

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `lastName` | string | required | Family name or parsed last-name segment |
| `firstName` | string | optional | Given name; omit only when unavailable |

**Behavior**:

- Returns compacted results from multiple underlying IdRef/Solr authority queries.
- The debug endpoint can include query metadata such as `solrRequest`.
- Results may include name variants, compound surnames, initials, and homonyms.
- Do not accept the first result without disambiguation when several PPNs are returned.

**Response structure**:

```json
[
  {
    "found": 14,
    "results": [
      {
        "ppn": "150899696",
        "firstName": "Valérie",
        "lastName": "Robert"
      }
    ]
  }
]
```

### `attrra`

**URL pattern**:

```text
GET https://qualinka.idref.fr/data/attrra/api/v2/req?ra_id=<PPN>
```

**Key parameters**:

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `ra_id` | string | required | IdRef authority PPN |

**Behavior**:

- Returns authority-record evidence useful for disambiguation.
- `source` often contains a bibliographic source used to create or justify the authority record.
- `noteGen` can contain biographical or academic statements, such as degree, institution, or year.
- Fields are sparse; absence does not imply a negative signal.

**Response structure**:

```json
{
  "id": "076642860",
  "dateCreationNotice": "20040302",
  "noteGen": [
    "Titulaire d'un doctorat d'université en médecine spécialisée (Nancy 1,2003)"
  ],
  "preferedform": [
    {
      "script": "ba",
      "value": "Robert, Valérie"
    }
  ],
  "gender": "aa",
  "country": "FR",
  "source": [
    "Satisfaction et vécu périopératoire des patients opérés sous anesthésie péribulbaire dans le service d'ophtalmologie A au CHU de Nancy /  Valérie Robert 24 septembre 2003"
  ]
}
```

### IdRef `references`

**URL pattern**:

```text
GET https://www.idref.fr/services/references/<PPN>.json
```

**Key parameters**:

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `<PPN>` | path string | required | IdRef authority PPN |

**Behavior**:

- Returns linked bibliographic references grouped by role.
- Role groups are useful for explainability, but role should not be used as a strong ranking criterion for person-authority alignment.
- Some authority records have few or no linked references.

**Response structure**:

```json
{
  "roles": [
    {
      "role_name": "Auteur",
      "marc21_code": "aut",
      "unimarc_code": "070",
      "count": 146,
      "docs": [
        {
          "citation": "Commanditaire, auteur, artiste dans les inscriptions médiévales / Robert Favreau",
          "referentiel": "sudoc",
          "id": "189894652",
          "ppn": "189894652",
          "url": "https://www.sudoc.fr/189894652",
          "uri": "https://www.sudoc.fr/189894652/id"
        }
      ]
    }
  ]
}
```

---

## Field mapping to common record schema

`find-person` candidates map to the common record schema as authority records:

| Common field | Source field | Notes |
|---|---|---|
| `source` | constant | `idref` |
| `id` | `ppn` | Same as PPN |
| `title` | `firstName + lastName` | Human-readable label if no attrra preferred form is fetched |
| `authors` | null | Not meaningful for authority records |
| `abstract` | null | Not meaningful |
| `doi` | null | Not meaningful |
| `pdf_url` | null | Not meaningful |
| `url` | `https://www.idref.fr/<PPN>` | Public authority page |
| `year` | null | Not reliably available from candidate search |
| `date` | null | Not reliably available from candidate search |
| `doc_type` | constant | `authority-person` |
| `journal` | null | Not meaningful |

Source-specific fields to preserve:

- `ppn`
- `first_name`
- `last_name`
- `preferedform`
- `noteGen`
- `source`
- `roles`

---

## Alignment guidance

Use `find-ra-idref` for candidate generation and `attrra` for primary
disambiguation. Use `references` as secondary bibliographic neighborhood
evidence.

Recommended scoring signals:

```text
name_score
attrra.source similarity
attrra.noteGen similarity
linked reference citation similarity
affiliation/field/year consistency
```

Avoid using the caller-supplied role as a strong ranking feature. A person's
role in the source (author, editor, contributor, …) often differs from how they
appear in IdRef references, and some people have sparse references.

Return `ambiguous` or `low_confidence` rather than forcing a PPN when the best
candidate has weak evidence or a small margin over the second candidate.

---

## Error handling

- HTTP `429`, `500`, `502`, `503`, `504` should be retried with exponential backoff.
- DNS, timeout, JSON decoding, and unexpected response-shape failures should be surfaced in an `error` field.
- Public services may return sparse but valid JSON; treat missing fields as neutral, not negative.
- Handled CLI failures should exit `0` and emit strict JSON.

---

## Useful query examples

```bash
curl "https://qualinka.idref.fr/data/find-ra-idref/api/v2/debug/req?lastName=robert&firstName=val%C3%A9rie"
curl "https://qualinka.idref.fr/data/attrra/api/v2/req?ra_id=076642860"
curl "https://www.idref.fr/services/references/076642860.json"
```
