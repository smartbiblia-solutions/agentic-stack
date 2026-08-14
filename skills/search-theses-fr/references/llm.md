# theses.fr API — LLM quick reference

Source: `https://theses.fr/api/v1/recherche/openapi.yaml` (title *API recherche
de theses.fr*, version 1.0), plus the ABES help portal
(`https://documentation.abes.fr/aidethesespro/`) and the data.gouv dataservice
`api-interroger-les-donnees-de-theses-fr`.

theses.fr is the French national register of doctoral theses, run by ABES. It
describes **defended theses** and **theses in preparation**, and the people
attached to them (authors, supervisors, rapporteurs, jury members). Everything
is public, anonymous, JSON, read-only. There is no key and no quota documented.

Every statement below marked *verified* was checked against the live API on
2026-08-11 and re-checked on 2026-08-12; the OpenAPI spec is not reliable on its
own (see §5). The searchable-field list comes from the help portal's *Principe
de l'API* page, which the OpenAPI file does not document at all.

---

## 0) The two things to know before writing a query

1. **`filtres` does not filter.** The spec documents it on `/recherche/`,
   `/facets/` and `/rechercheCSV`, with the example
   `[discipline="architecture"&langues="fr"]`. *Verified*: that syntax, and
   five other plausible ones, leave `totalHits` exactly at its unfiltered
   value. Put every constraint in `q`.
2. **Search hits have no résumé.** `/recherche/` returns a lightweight
   projection. The abstract exists only on `/these/{id}`, one request per
   record.

---

## 1) Endpoints

Base: `https://theses.fr/api/v1`

### Theses

| Path | Params | Returns |
|---|---|---|
| `/theses/recherche/` | `q` (required), `debut`, `nombre`, `tri`, `filtres` | `{totalHits, took, theses[]}` |
| `/theses/these/{id}` | `id` = NNT **or** `numSujet` | one full record, or `200` with an empty body |
| `/theses/facets/` | `q`, `filtres` | array of facets with counts |
| `/theses/completion/` | `q` | autocomplete over free keywords, Rameau subjects, disciplines |
| `/theses/checkNNT/{numSujet}` | `numSujet` | the NNT a subject number became |
| `/theses/organisme/{ppn}` | `ppn` | theses linked to an establishment, grouped by its role |
| `/theses/getorganismename/{ppn}` | `ppn` | establishment name |
| `/theses/statsTheses`, `/theses/statsSujets` | — | counts of defended / in-preparation theses |
| `/theses/rechercheCSV` | `q`, `tri`, `filtres` | the same search as CSV |
| `/theses/rss` | — | feed |

### Persons

| Path | Params | Returns |
|---|---|---|
| `/personnes/recherche/` | `q`, `debut`, `nombre`, `tri`, `filtres` | `{totalHits, took, personnes[]}` |
| `/personnes/personne/{id}` | `id` (IdRef PPN when `has_idref`) | one person |
| `/personnes/facets` | `q`, `filtres` | facets over the person index |
| `/personnes/completion` | `q` | autocomplete on names |
| `/personnes/stats` | — | counts |

The spec also lists a `/tests/personnes/…` family with an extra `index`
parameter. It is a staging surface; do not build on it.

---

## 2) `q` — Lucene over Elasticsearch

`q` is required. `q=*` matches everything (*verified*: 563 350 records).

The ABES help page (*Principe de l'API* → *champs interrogeables*) lists the
searchable fields. Every one below was re-queried live; the hit counts are the
answer on 2026-08-12 with `nombre=0`.

| Field | Example | Hits |
|---|---|---|
| *(bare term)* | `informatique` | 52 791 |
| `titrePrincipal` | `titrePrincipal:(informatique)` | 565 |
| `resumes.fr` | `resumes.fr:(microbiote)` | 1 403 |
| `resumes.en` | `resumes.en:(microbiome)` | 366 |
| `discipline` | `discipline:(informatique)` | 30 277 |
| `oaiSetNames` | `oaiSetNames:("Agronomie, agriculture et médecine vétérinaire")` | 3 248 |
| `codeEtab` | `codeEtab:(COAZ)` | 2 706 |
| `etabSoutenanceN` | `etabSoutenanceN:(Lorient)` | 928 |
| `etabSoutenancePpn` | `etabSoutenancePpn:(241035694)` | 2 706 |
| `nnt` | `nnt:*COAZ*` | 1 568 |
| `status` | `status:(soutenue)` | 485 326 |
| `accessible` | `accessible:(oui)` | 170 452 |
| `langues` | `langues:(en)` | 86 993 |
| `auteursNP` | `auteursNP:(Audelan)` | 1 |
| `directeursNP` | `directeursNP:(Frédéric Precioso)` | 14 |
| `rapporteursNP` | `rapporteursNP:(Menze)` | 6 |
| `membresJuryNP` | `membresJuryNP:(Bouveyron)` | 29 |
| `presidentJuryNP` | `presidentJuryNP:(Bouveyron)` | 11 |
| `auteursPpn` / `directeursPpn` / … | `directeursPpn:(060582952)` | 14 |
| `ecolesDoctoralesPpn` | `ecolesDoctoralesPpn:(059079800)` | 1 381 |
| `partenairesRecherchePpn` | `partenairesRecherchePpn:(059205717)` | 450 |
| `sujetsLibelle` | `sujetsLibelle:(microbiote)` | 782 |
| `sujetsRameauLibelle` | `sujetsRameauLibelle:("Apprentissage automatique")` | 2 815 |
| `sujetsRameauPpn` | `sujetsRameauPpn:(027940373)` | 2 814 |
| `dateSoutenance` | `dateSoutenance:([2024-01-01 TO 2025-12-31])` | 28 709 |
| `datePremiereInscriptionDoctorat` | `datePremiereInscriptionDoctorat:([2023-01-01 TO *])` | 44 979 |
| `dateInsertionDansES` | `dateInsertionDansES:([2026-08-01 TO *])` | 26 376 |
| `numSujet` / `numSujetSansS` | `numSujet:(s68236)` | 1 |

Boolean composition works: `codeEtab:(COAZ) AND status:(enCours)` → 1 139.

Rules learned the hard way:

- **`codeEtab` is the establishment filter, not `nnt`.** `codeEtab:(COAZ)` →
  2 706; `nnt:*COAZ*` → 1 568, exactly the defended subset, because an
  in-progress thesis has `nnt: null`. `codeEtab` is also **case-sensitive**:
  `codeEtab:(coaz)` → 0.
- **Quoting is per-field, and both directions are traps.** A controlled label
  must be quoted — `oaiSetNames:("Agronomie, agriculture et médecine
  vétérinaire")` → 3 248, unquoted → 0. A person name must **not** be:
  `directeursNP:(Frédéric Precioso)` → 14, `directeursNP:("Frédéric Precioso")`
  → 0, because the field holds name tokens in no fixed order.
- **Accents and apostrophes are fragile.** `etabSoutenanceN:"Université Côte d
  Azur"` → 0, while `etabSoutenanceN:Azur` → 3 565. Prefer a distinctive single
  token, or take the exact label from `/facets/`.
- **`oaiSetNames` is a real controlled vocabulary** — the 98 *Domaines
  thématiques* facet labels, not the OAI `ddc:NNN` setSpec form. Use it when a
  thematic slice must be reproducible; `discipline` is ~4 000 free-text values
  and is only a hint.
- **`accessible` is `oui`/`non` and implies a defended thesis.**
  `status:(enCours) AND accessible:(oui)` → 0.
- **Nested paths do not work.** `auteurs.nom:Dupont` → 0, and so does
  `ecolesDoctorale.nom:STIC`. The flat `*NP` (name) and `*Ppn` (identifier)
  fields are how a person is queried on the thesis index; the person index is
  for going the other way, from a name to a PPN.
- **Some returned keys are not indexed.** `titreEN:(…)` and `cas:(…)` answer 0
  for every value tried. Read them from the record; do not query them.
- **`resumes.*` is an HTTP 400** — one of the very few queries that fails loudly.
  Name the language.
- **Date bounds are ISO** (`YYYY-MM-DD`) even though results render
  `dateSoutenance` as `DD/MM/YYYY`. Wrapping the range in parentheses,
  `dateSoutenance:([… TO …])`, is what makes it safe to `AND` with other clauses.
- **`dateInsertionDansES` tracks the index, not the thesis.** It resets on a
  full reindex — 563 344 of 563 350 records carry a 2026 insertion date — so it
  is a sync cursor over short windows, never a proxy for recency.

### `tri`

*Verified* to work: `pertinence` (the default), `dateAsc`, `dateDesc`,
`auteursAsc`, `auteursDesc`, `disciplineAsc`, `disciplineDesc`. Anything else
is ignored silently rather than rejected — `personnesAsc`/`personnesDesc` from
the person index are no-ops here. `dateDesc` puts the in-progress records (null
`dateSoutenance`) first.

### Paging

`debut` (offset) and `nombre` (page size). No documented ceiling on `nombre`;
clamp client-side.

---

## 3) Response shapes

### `/theses/recherche/`

```jsonc
{ "totalHits": 60, "took": 12, "theses": [ /* hits */ ] }
```

Hit keys: `id`, `titrePrincipal`, `titreEN`, `etabSoutenanceN`,
`etabSoutenancePpn`, `dateSoutenance`, `datePremiereInscriptionDoctorat`,
`auteurs[]`, `directeurs[]`, `rapporteurs[]`, `examinateurs[]`, `president`,
`nnt`, `doi`, `discipline`, `status`, `ecolesDoctorale[]`,
`partenairesDeRecherche[]`, `sujets`, `sujetsRameau`.

Each person is `{ppn, nom, prenom}`. **No `resumes` key** — that is the whole
reason hydration exists.

### `/theses/these/{id}`

Adds `titres` and `resumes` (both language-keyed dicts, typically `fr` and
`en`), `numSujet`, `codeEtab`, `etabSoutenance` `{ppn, nom, type}`,
`etabCotutelle`, `partenairesRecherche`, `mapSujets`, `membresJury`, `langues[]`,
`cas`, `accessible` (`"oui"`/`"non"`), `ecolesDoctorales`, `presidentJury`,
`source`, `isSoutenue`.

Accepts **either** identifier: `2021COAZ4028` and `s68236` both answer `200`.

### `/theses/organisme/{ppn}`

Eight parallel lists — the four roles an organisation can play, each split into
defended and in-preparation — with a counter beside each:

```jsonc
{
  "totalHitsetabSoutenance": 1567,        "etabSoutenance": [ /* ≤100 hits */ ],
  "totalHitsetabSoutenanceEnCours": 1139, "etabSoutenanceEnCours": [ /* … */ ],
  "totalHitspartenaireRecherche": 303,    "partenaireRecherche": [ /* … */ ],
  "totalHitsetabCotutelle": 0,            "etabCotutelle": [],
  "totalHitsecoleDoctorale": 0,           "ecoleDoctorale": []
  // …EnCours twin for each
}
```

Records inside are the same lightweight hits as `/recherche/`. **Each list is
capped at 100** whatever the counter says, so this endpoint answers "in which
capacities, and how many" — not "give me everything". For an exhaustive listing
of what an establishment awarded, use `codeEtab` on `/recherche/` with paging.

`{ppn}` is the IdRef PPN of the organisation. Pass a person's PPN and the
endpoint still answers `200`, with all eight lists empty — indistinguishable
from an organisation with no theses. `/theses/getorganismename/{ppn}` is the
discriminator: it returns the name as **`text/plain`, not JSON** (do not call
`.json()` on it), and an empty body when the PPN is not an organisation.

### `/personnes/recherche/`

```jsonc
{ "totalHits": 4, "took": 8, "personnes": [
  { "id": "087273934", "nom": "Precioso", "prenom": "Frédéric",
    "has_idref": true,
    "roles": { "Directeur / Directrice": 23, "Examinateur / Examinatrice": 59 },
    "theses": ["2010CERG0497", "…"] } ] }
```

`roles` is a label → count map, and `theses` is a ready-made worklist for
`/these/{id}`. When `has_idref` is true, `id` is the IdRef PPN, which is what
makes `resolve-persons-idref` composable with this source.

### `/theses/facets/`

An **array**, not an object. Each entry is
`{name, searchBar, checkboxes: [{name, label, value, checkboxes?}]}` where
`value` is the count. Facets returned: *Statut* (`enCours`, `soutenue`, and a
nested *Accessibles en ligne*), *Établissements*, *Écoles doctorales*,
*Domaines thématiques*, *Disciplines*, *Langues*. Counts are relative to `q`.
This is the only way to learn the exact label a field query needs.

---

## 4) Data-quality traps

- **`titreEN` is not always an English title.** A record has been observed with
  `titreEN: "Informatique et Architectures numériques"` — a discipline. Never
  promote it to the title; keep it as a separate field.
- **`nnt` is null for a thesis in preparation.** Use `id` / `numSujet`
  (`s68236`) instead, and `checkNNT/{numSujet}` once it is defended.
- **`dateSoutenance` is null for in-progress records**, so any year derived
  from it is null too. `datePremiereInscriptionDoctorat` is the enrolment date,
  not a defense date — do not substitute one for the other.
- **`doi` exists for most defended theses** (`10.70675/…`) and never for
  in-progress ones. It is the merge key with OpenAlex and HAL.
- **Discipline is free text.** The facet list contains `?`, bracketed values and
  duplicate casings. Treat it as a search hint, never as a controlled vocabulary
  — `oaiSetNames` is the controlled one.
- **`accessible` describes online availability of the full text**, and only
  ~30 % of defended theses have it (170 452 of 485 326). It is not a licence
  statement: read `cas` and the record itself before asserting open access.
- **Defenses cluster seasonally** (autumn peak). Compare full years, not
  half-years, when monitoring output.

---

## 5) Where the spec and the API disagree

| Spec says | Reality |
|---|---|
| `filtres` filters | inert on every endpoint tested |
| `/recherche/` "search a thesis by title" | it searches the whole record, not just the title |
| `tri` example `"dateAsc, dateDesc, …"` | a single value, one of that list; other values are ignored, not rejected |
| an unknown `{id}` | `200` with an **empty body**, not `404` |
| `/api/v1/recherche/…` (the OpenAPI URL prefix) | the real search path is `/api/v1/theses/recherche/`; `/api/v1/recherche/theses` is `404` |

---

## 6) Errors

Documented statuses on `/recherche/` are `200`, `400` (bad request) and `503`
(service unavailable). In practice, malformed Lucene tends to come back as
`200` with zero hits rather than `400`, so a zero-hit answer never proves the
corpus is empty — re-check the syntax first. Retry `429` and `5xx` with
exponential backoff.
