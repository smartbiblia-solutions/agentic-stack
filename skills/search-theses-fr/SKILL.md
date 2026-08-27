---
name: search-theses-fr
description: >
  Search and retrieve French doctoral theses from theses.fr, the national portal
  run by ABES, both defended theses and theses in progress. Use this skill when
  the task is to search theses.fr, find a French PhD thesis, retrieve one by its
  NNT identifier, obtain a thesis résumé, look up a doctoral supervisor or jury
  member, or monitor doctoral output for a French establishment or discipline.
  Filters on establishment code, thematic domain, author or supervisor name,
  language, online availability, defense date and status. Trigger on
  "theses.fr", "thèse", "NNT", "doctorat", "soutenance", "résumé de thèse",
  "directeur de thèse", "French PhD thesis". Search hits carry no abstract: pass
  --hydrate, or fetch the record by identifier. Prefer this skill over
  search-records-sudoc for the thesis itself, and over OpenAlex or HAL for any
  French doctoral coverage question. Returns JSON.
version: "0.3.0"
author: smartbiblia
maturity: beta
preferred_output: json
license: MIT
platforms: ["linux", "macos", "windows"]
metadata:
  {
    "openclaw": { "always": true, "requires": { "bins": ["uv"] } }
  }

selection:
  use_when:
    - The task targets French doctoral theses, defended or in progress.
    - A thesis NNT or subject number is known and the full record, with its résumés, is needed.
    - Doctoral output must be counted or monitored for a French establishment, discipline or period.
    - A doctoral supervisor, rapporteur or jury member must be looked up by name.
    - An organisation's full doctoral footprint is wanted, including the theses it only co-supervised or hosted.
  avoid_when:
    - Coverage must be international or non-doctoral; use search-works-openalex.
    - The target is a deposited full text or a French open-access article; use search-records-hal.
    - The target is the library catalogue record of a thesis rather than the defense; use search-records-sudoc.
    - A person must be aligned onto an IdRef PPN; use resolve-persons-idref.
  prefer_over:
    - generic-web-search
    - search-records-sudoc
  combine_with:
    - generate-search-queries
    - resolve-persons-idref
    - synthesize-literature

tags:
  - theses
  - doctoral
  - french
  - abes
  - open-access
---

# search-theses-fr

## Purpose

`scripts/cli.py` wraps the [theses.fr API](https://www.data.gouv.fr/dataservices/api-interroger-les-donnees-de-theses-fr),
the French national register of doctoral theses maintained by ABES. It covers
theses already defended and theses in progress, their supervisors and juries.
The service is public and anonymous — no key, no environment variable.

```bash
uv run ./skills/search-theses-fr/scripts/cli.py <subcommand> [flags]
```

Records carry the shared bibliographic fields (`title`, `authors`, `abstract`,
`doi`, `year`, `date`, `doc_type`, `journal`, `raw`) so results merge with those
of `search-works-openalex` and `search-records-hal`, plus the fields theses.fr
adds: `nnt`, `directors`, `institution`, `institution_ppn`, `discipline`,
`doctoral_schools`, `research_partners`, `keywords`, `rapporteurs`, `jury`,
`president`, `status`.

---

## When to use / When not to use

**Use this skill when:**

- The task targets French doctoral theses — defended or still in progress.
- An NNT (`2021COAZ4028`) or a subject number (`s68236`) is known.
- Doctoral output must be counted for an establishment, a discipline or a period.
- A supervisor, rapporteur or jury member must be found by name.

**Do not use this skill when:**

- The scope is international or non-doctoral — use `search-works-openalex`.
- What is wanted is the deposited full text — use `search-records-hal`.
- What is wanted is the catalogue record — use `search-records-sudoc`.

---

## Two API facts that decide how you query

**1. Only `q` filters.** The API documents a `filtres` parameter; it is inert.
Every syntax in the OpenAPI examples leaves the hit count unchanged. All
filtering therefore goes through the Lucene `q`, which the CLI assembles for
you from `--etab`, `--discipline`, `--domain`, `--author`, `--director`,
`--language`, `--accessible`, `--date-from/--date-to` and `--status`, ANDed
with any raw `--q`.

**2. Search hits carry no résumé.** `/recherche/` returns lightweight hits with
`abstract: null`. The résumés live on the record endpoint only:

- `search --hydrate` fetches the record of every hit and fills `abstract`
  (English preferred, French fallback), `abstracts`, `titles`, `languages`,
  `code_etab`, `accessible`, `cotutelle` and `is_defended` — **one extra HTTP
  request per hit**. Everything else (keywords, jury, schools, partners) already
  rides along on the hit.
- `get --id <NNT>` fetches one record directly.

Screen on titles first, then hydrate the shortlist. A hit whose hydration fails
keeps its `hydrate_error` and the rest of the response is unaffected.

---

## Query syntax

`q` is Lucene over an Elasticsearch index. Fields verified against the live
service — the ones with a flag are listed under `search`, the rest are reachable
through `--q`:

| Field | Example | Notes |
|---|---|---|
| `titrePrincipal` | `titrePrincipal:(informatique)` | Title of record. `titreEN` is returned but **not** searchable |
| `resumes.fr` / `resumes.en` | `resumes.fr:(microbiote)` | Full-text résumé search. `resumes.*` is a **400** |
| `discipline` | `discipline:(informatique)` | Free text, ~4000 distinct values |
| `oaiSetNames` | `oaiSetNames:("Informatique")` | Controlled: the 98 *Domaines thématiques* labels. Must be quoted |
| `codeEtab` | `codeEtab:(COAZ)` | Establishment short code, **case-sensitive** |
| `etabSoutenanceN` | `etabSoutenanceN:(Lorient)` | Establishment label |
| `etabSoutenancePpn` | `etabSoutenancePpn:(241035694)` | Establishment IdRef PPN |
| `nnt` | `nnt:*COAZ*` | Defended theses **only** — an in-progress thesis has no NNT |
| `status` | `status:(soutenue)` | `soutenue` or `enCours` |
| `accessible` | `accessible:(oui)` | `oui`/`non`; online full text. Defended theses only — `enCours AND accessible:oui` is always 0 |
| `auteursNP` / `directeursNP` | `directeursNP:(Frédéric Precioso)` | Name tokens, **never quoted** — the phrase returns 0 |
| `rapporteursNP`, `membresJuryNP`, `presidentJuryNP` | `membresJuryNP:(Bouveyron)` | Same rule |
| `auteursPpn`, `directeursPpn`, … | `directeursPpn:(060582952)` | Exact person, no homonym noise |
| `ecolesDoctoralesPpn`, `partenairesRecherchePpn` | `ecolesDoctoralesPpn:(059079800)` | Structures by PPN |
| `sujetsLibelle` / `sujetsRameauLibelle` | `sujetsRameauLibelle:("Apprentissage automatique")` | Free keywords / RAMEAU headings |
| `langues` | `langues:(en)` | ISO code of the writing language |
| `dateSoutenance` | `dateSoutenance:([2024-01-01 TO 2025-12-31])` | ISO bounds, even though results display `DD/MM/YYYY` |
| `datePremiereInscriptionDoctorat` | `datePremiereInscriptionDoctorat:([2023-01-01 TO *])` | The only date an in-progress thesis has |
| `dateInsertionDansES` | `dateInsertionDansES:([2025-01-01 TO *])` | Indexing date — for incremental sync |
| `numSujet` | `numSujet:(s68236)` | Subject number of a thesis in preparation |

Combine with `AND` / `OR`. Quoting is per-field and not optional: quote
controlled labels (`oaiSetNames`, RAMEAU headings) or a multi-word value is
tokenized and matches far more than the phrase; never quote a person-name field,
whose tokens are stored in no fixed order. Nested paths do **not** work
(`auteurs.nom:Dupont` returns zero) — the flat `*NP` fields are the way to query
a name. Run `facets` to discover the exact establishment, domain, school and
discipline labels a query accepts.

---

## Subcommands

### `search` — search theses

```bash
uv run ./skills/search-theses-fr/scripts/cli.py search \
  --etab COAZ --discipline informatique \
  --date-from 2024-01-01 --date-to 2025-12-31 --rows 25
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--q` | string | `""` | Raw Lucene query, ANDed with the shortcuts below |
| `--etab` | string | — | Establishment short code → `codeEtab:(<CODE>)`, upper-cased |
| `--discipline` | string | — | → `discipline:(<value>)` |
| `--domain` | string | — | → `oaiSetNames:("<label>")` — a *Domaines thématiques* facet label |
| `--author` | string | — | → `auteursNP:(<name>)` |
| `--director` | string | — | → `directeursNP:(<name>)` |
| `--language` | string | — | → `langues:(<code>)`, e.g. `fr`, `en` |
| `--accessible` | choice | — | `oui` \| `non` → `accessible:(<value>)`; defended theses only |
| `--date-from` / `--date-to` | string | — | `dateSoutenance` bounds, `YYYY-MM-DD` |
| `--status` | string | — | → `status:(<value>)` (`soutenue`, `enCours`) |
| `--rows` | int | `15` | Page size (`nombre`), clamped to 500 |
| `--start` | int | `0` | Offset (`debut`) |
| `--sort` | choice | — | `pertinence`, `dateAsc`, `dateDesc`, `auteursAsc`, `auteursDesc`, `disciplineAsc`, `disciplineDesc` |
| `--hydrate` | flag | off | Fetch the résumé of every hit — one request each |

`--etab COAZ` compiles to `codeEtab:(COAZ)`, not to the older `nnt:*COAZ*`
idiom: an in-progress thesis has no NNT, so the wildcard silently dropped every
one of them — 1 567 hits instead of 2 706 for Université Côte d'Azur.

### `get` — one thesis by identifier

```bash
uv run ./skills/search-theses-fr/scripts/cli.py get --id 2021COAZ4028
uv run ./skills/search-theses-fr/scripts/cli.py get --id s68236     # in progress
```

Returns one record under `results`, with `abstracts` and `titles` as
language-keyed dicts, plus `code_etab`, `languages`, `accessible`, `status`.

### `persons` — the person index

```bash
uv run ./skills/search-theses-fr/scripts/cli.py persons --q Precioso --rows 5
```

Each result carries `roles` (role label → number of theses) and `theses` (the
identifiers, ready for `get`).

### `facets` — the values a query accepts

```bash
uv run ./skills/search-theses-fr/scripts/cli.py facets --q informatique --limit 10
```

Returns one entry per facet — Statut, Établissements, Écoles doctorales,
Domaines thématiques, Disciplines, Langues — each with `buckets` of
`{value, count}`. Counts are relative to `--q`. The *Domaines thématiques*
buckets are exactly the values `--domain` accepts.

### `organisme` — an establishment's theses, by the role it played

```bash
uv run ./skills/search-theses-fr/scripts/cli.py organisme --ppn 241035694
uv run ./skills/search-theses-fr/scripts/cli.py organisme --ppn 241035694 --role partenaireRecherche
```

The one view `q` cannot assemble: `codeEtab` only ever finds the *awarding*
establishment, while this endpoint also returns the theses where the
organisation was a cotutelle partner, a research partner or the doctoral
school. `--ppn` is the organisation's IdRef PPN — the `institution_ppn` of any
of its records, or a `*Ppn` value under `raw`.

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--ppn` | string | required | IdRef PPN of the organisation |
| `--role` | choice | all four | `etabSoutenance`, `etabCotutelle`, `partenaireRecherche`, `ecoleDoctorale` |

Each result is a normal thesis record plus `role` and `in_progress`. `totals`
gives the eight upstream counters (each role × defended/in-progress); upstream
caps every bucket at 100 records, so `total_found` is routinely far larger than
`returned` — use `search` with `--rows` for an exhaustive listing of the
awarding establishment. A PPN that belongs to a person comes back with
`error` set and empty `results`.

---

## Output

Strict JSON on stdout, in the universal envelope. Exit code is always `0`.

```jsonc
{
  "total_found": 60,
  "returned": 2,
  "results": [
    {
      "source": "theses-fr",
      "id": "2024COAZ4013",
      "nnt": "2024COAZ4013",
      "record_id": "2024COAZ4013",
      "title": "Localisation sur le territoire…",
      "title_en": null,           // unreliable upstream — see Failure modes
      "authors": ["First Last"],
      "directors": ["First Last"],
      "abstract": null,           // null unless --hydrate
      "doi": "10.70675/…",
      "year": 2024,
      "date": "24/01/2024",
      "doc_type": "thesis",
      "journal": null,
      "institution": "Université Côte d'Azur",
      "institution_ppn": "241035694",
      "discipline": "Informatique",
      "date_first_registration": null,   // set only while in progress
      "doctoral_schools": ["École doctorale …"],
      "research_partners": ["Laboratoire …"],
      "keywords": ["…"],                 // sujets + sujetsRameau, deduplicated
      "rapporteurs": ["First Last"],
      "jury": ["First Last"],
      "president": "First Last",
      "status": "soutenue",
      "url": "https://theses.fr/2024COAZ4013",
      "raw": { }
    }
  ],
  "query_used": "codeEtab:(COAZ) AND discipline:(informatique)",
  "params": { "rows": 15, "start": 0, "sort": null },
  "hydrated": false,
  "error": null
}
```

On failure the same envelope comes back with `results: []` and a populated
`error`. Always read `error` — the CLI never exits non-zero.

---

## Common workflows

### Doctoral output for an establishment over a window

```bash
uv run ./skills/search-theses-fr/scripts/cli.py search \
  --etab COAZ --status soutenue \
  --date-from 2024-01-01 --date-to 2024-12-31 --rows 100
```

### Cheap scan, then hydrate the shortlist

```bash
uv run ./skills/search-theses-fr/scripts/cli.py search --etab COAZ --rows 100
uv run ./skills/search-theses-fr/scripts/cli.py get --id 2024COAZ4013
```

### Find a supervisor, then their theses

```bash
uv run ./skills/search-theses-fr/scripts/cli.py persons --q Precioso --rows 3
uv run ./skills/search-theses-fr/scripts/cli.py search --director Precioso --rows 20
# no homonyms: the PPN from `persons` is exact
uv run ./skills/search-theses-fr/scripts/cli.py search --q 'directeursPpn:(060582952)'
```

### Only theses whose full text is online, in one thematic domain

```bash
uv run ./skills/search-theses-fr/scripts/cli.py search \
  --domain "Informatique" --accessible oui --language en \
  --date-from 2023-01-01 --sort dateDesc --rows 50
```

### An establishment's whole footprint, not just what it awarded

```bash
uv run ./skills/search-theses-fr/scripts/cli.py organisme --ppn 241035694
```

### Discover the domain and establishment labels to filter on

```bash
uv run ./skills/search-theses-fr/scripts/cli.py facets --q informatique --limit 0
```

### Incremental sync — what the index gained since a date

```bash
uv run ./skills/search-theses-fr/scripts/cli.py search \
  --q 'dateInsertionDansES:([2025-01-01 TO *])' --rows 100
```

---

## Failure modes

- **Exit code is always 0.** Upstream failures are in `error`, next to empty
  `results`.
- **`abstract` is null** on every search hit. Expected — pass `--hydrate` or use
  `get`. Many records genuinely have no résumé at all; `abstract` then stays
  null after hydration.
- **`hydrate_error` on a record** means that one detail fetch failed; the other
  hits are unaffected.
- **Unknown identifier**: theses.fr answers `200` with an empty body rather than
  `404`. The CLI reports `No record found (empty response)`.
- **`filtres` is inert.** Do not expect any server-side filter outside `q`.
- **`titreEN` is not always an English title** — records exist where it holds
  the discipline. It is exposed as `title_en` and never promoted to `title`.
- **`nnt` is null while a thesis is in progress**; `id` then carries the subject
  number (`s68236`), which the record endpoint accepts just the same. Filter on
  `codeEtab`, never on `nnt:*CODE*`, or every in-progress thesis disappears.
- **A quoted person name returns zero.** `directeursNP:("Frédéric Precioso")`
  is 0 hits, `directeursNP:(Frédéric Precioso)` is 14. Conversely an unquoted
  `oaiSetNames` label returns zero. `--author`/`--director`/`--domain` handle
  this; raw `--q` does not.
- **`codeEtab` is case-sensitive** — `codeEtab:(coaz)` is empty. `--etab`
  upper-cases for you.
- **`accessible:oui` implies a defended thesis**; combined with
  `status:(enCours)` it always returns zero.
- **`resumes.*:` is an HTTP 400.** Name the language: `resumes.fr` or
  `resumes.en`.
- **`organisme` buckets are capped at 100 upstream**, so `returned` is far below
  `total_found` on a large establishment. `totals` still reports the true
  counts.
- **Rate limiting** (429) and 5xx are retried three times with exponential
  backoff and jitter.

---

## Artifact contract

The CLI writes one complete JSON response envelope to stdout and nothing else.
It does not choose or create a project, review, or run directory, and it has no
`--output` flag: when persistence is wanted, the calling agent redirects stdout
or captures the payload itself — the whole envelope, not just `results`.

Stable filenames, when one is needed:

| What produced it | Filename |
|---|---|
| `search`, `organisme` | `theses-fr-<query-slug>.json` |
| `get` | `theses-fr-<record-id>.json` |
| `facets`, `persons` | `theses-fr-<operation>-<query-slug>.json` |

Slugs are lowercase kebab-case, every non-alphanumeric character collapsed to
`-`. No counters, no result counts, no status words, and no date unless a date
is part of the query itself — a `--date-from` sync window is, a run date is not.
The parent directory is the caller's business, and no filename is needed at all
when the result is only being returned to the user.

---

## Composition hints

```
generate-search-queries        ← build the query set
      ↓
search-theses-fr               ← this skill (French doctoral coverage)
  search --hydrate             ← records with résumés
      ↓
synthesize-literature          ← screen, summarize, synthesize
```

Sits beside `search-works-openalex` and `search-records-hal`: the three share
the bibliographic record fields, so merge and deduplicate on `doi` — theses.fr
mints a DOI for most defended theses. Use `search-records-sudoc` for the
catalogue record of a printed thesis and `resolve-persons-idref` to align a
supervisor onto a PPN; `persons` results already carry `has_idref`.

The API digest is in `references/llm.md`.
