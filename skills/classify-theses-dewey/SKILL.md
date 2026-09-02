---
name: classify-theses-dewey
description: >
  Assign a Dewey class to a French doctoral thesis — its title, its subject
  keywords, its abstract — through the humatheque-dewey-classifier-api service,
  which embeds the text with a multilingual model and ranks it against the
  reduced 98-class Dewey list French thesis cataloguing uses in the Sudoc. That
  list is what comes back, not the full Dewey schedules. Use this skill for
  prompts like "quel indice Dewey pour cette thèse", "classe ces sujets de
  thèse", "indice Dewey de ce titre de doctorat", "assign a Dewey class to this
  dissertation abstract", or whenever theses must be bucketed by discipline for a
  shelfmark, a facet, or a corpus breakdown. Handles one text or a batch, works
  in French and English, and returns ranked classes as dewey + label + score.
  Scores are similarity rankings, not probabilities. Material that is not a
  thesis still gets an answer, but from a vocabulary that was never meant for it.
  Prefer search-works-openalex classify-text when the wanted vocabulary is the
  OpenAlex topic hierarchy rather than Dewey. Returns strict JSON.
version: "0.1.0"
author: smartbiblia
maturity: experimental
preferred_output: json
metadata:
  {
    "openclaw": {
      "always": true,
      "requires": { "bins": ["uv"] },
      "primaryEnv": "DEWEY_API_KEY"
    }
  }

selection:
  use_when:
    - A doctoral thesis must be placed in the Dewey Decimal Classification.
    - Theses need a discipline bucket for a shelfmark, a facet, or a corpus breakdown.
    - A batch of thesis titles, subjects or abstracts must be classified in one pass.
    - The user mentions Dewey, CDD, indice Dewey, cote, or classification décimale for a thèse.
  avoid_when:
    - The wanted vocabulary is the OpenAlex topic hierarchy, not Dewey; use search-works-openalex classify-text.
    - The material is not a thesis — a monograph, an article, a dataset. The list is the thesis-cataloguing one; an answer still comes back, but treat it as a coarse discipline hint, not a shelfmark.
    - The task is to find records rather than to classify a text you already hold; use search-records-sudoc or search-works-openalex.
    - The record already carries an authoritative Dewey number from its cataloguer; keep theirs.
    - The task is Rameau or another subject-heading vocabulary; use search-authorities-idref.
  prefer_over:
    - generic-web-search
  combine_with:
    - search-theses-fr
    - search-records-sudoc
    - search-works-openalex
    - convert-records-unimarc

tags:
  - theses
  - dewey
  - classification
  - cataloguing
  - sudoc
  - abes
  - embeddings
  - french
---

# classify-theses-dewey

## Purpose

Deciding which Dewey class a thesis belongs to is a mapping from very specific
wording to a deliberately broad category: a thesis titled *"Buenos Aires, 1829"*
has to roll up to *Histoire générale de l'Amérique du Sud*, and no string match
gets there. That mapping lives in the `humatheque-dewey-classifier-api` service,
which embeds the text with a multilingual sentence-embedding model, ranks it
against a curated Dewey taxonomy where each class carries an enriched keyword
description, and returns the best classes with a similarity score.

**The taxonomy is the thesis one.** It is not the full Dewey schedules but the
reduced list French thesis cataloguing uses in the Sudoc — 98 classes, the ten
main divisions and their tens, plus the handful of finer entries that rule keeps
(`004`, `020`, `060`, `070`, `090`, `796`, `944`). That is the whole reason the
granularity stops where it does: what comes back is the indice a thesis record
carries, at the level a cataloguer assigns it, and there is no `005.13` to be
had. The service is built for that corpus and tuned on it — French doctoral
theses, classified from short metadata rather than from full text.

This skill is the routing layer over that API. `scripts/cli.py` is a thin client:
it builds the request, forwards the key, and prints the API's answer unchanged.
No text is embedded here, no class is ranked here, and the CLI calls no host but
the API — which is why improving accuracy (editing the service's `taxonomy.json`)
never needs a change in this skill.

---

## When to use / When not to use

Use this skill when you hold a thesis and want its discipline in Dewey terms:
cataloguing a batch of new deposits, building a subject facet over a theses.fr
or Sudoc result set, sanity-checking an indice before it goes into a record, or
breaking a doctoral corpus down by field. It is at its best on the metadata a
thesis record actually carries — the title, the subject keywords, occasionally
the abstract.

Do not use it when:

- **The material is not a thesis.** A monograph, an article, a dataset or a web
  page still gets an answer, but from a list built for theses and by a service
  tuned on thesis metadata. Read it as a coarse discipline hint, never as a
  shelfmark.
- The vocabulary wanted is the OpenAlex topic hierarchy — use
  `search-works-openalex classify-text`, which returns real OpenAlex topic,
  subfield, field and domain identifiers and is not restricted to theses.
- A precise Dewey number is needed. This list stops at the division level; the
  cataloguer refines from there.
- The task is to *find* theses — use `search-theses-fr` or
  `search-records-sudoc` first, then classify what comes back.
- A cataloguer has already assigned a Dewey number to the record. This service
  proposes; it does not overrule.
- The target is Rameau, LCSH or another subject-heading vocabulary.

---

## CLI usage

```bash
# the common case: one thesis title, the top few classes
uv run ./skills/classify-theses-dewey/scripts/cli.py classify \
  --text "Histoire politique de Buenos Aires au XIXe siècle"

# a batch — one API call for many texts, much cheaper than one call each
uv run ./skills/classify-theses-dewey/scripts/cli.py classify \
  --text "Apprentissage automatique appliqué au diagnostic médical" \
  --text "Le contrôle de constitutionnalité en droit comparé" \
  --top-k 3

# a file of thesis titles, one per line
uv run ./skills/classify-theses-dewey/scripts/cli.py classify \
  --file sujets-theses.txt --top-k 3

# force a single answer, restricted to a shortlist of candidate classes
uv run ./skills/classify-theses-dewey/scripts/cli.py classify \
  --text "Étude des sols agricoles du Massif central" \
  --classification-type single-label --code 630 --code 550 --code 910

# the sharper, remote ranking
uv run ./skills/classify-theses-dewey/scripts/cli.py classify \
  --text "Alignement des grands modèles de langue pour les langues peu dotées" \
  --method albert --top-k 3

# is the service reachable at all?
uv run ./skills/classify-theses-dewey/scripts/cli.py health
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--text` | string | — | A thesis title, subject or abstract. **Repeatable** — repeat it for a batch |
| `--file` | path | — | File holding one thesis text per line; appended to any `--text` |
| `--code` | string | — | Restrict candidates to this Dewey code, e.g. `980`. **Repeatable** |
| `--threshold` | float | `0.0` | Drop classes below this score |
| `--classification-type` | enum | `multi-label` | `multi-label` (up to `--top-k`) or `single-label` (best one) |
| `--top-k` | int | `5` | Classes per text; clamped to 98, the size of the thesis list |
| `--method` | enum | `local` | `local` or `albert` |

At least one of `--text` or `--file` is required. The client sends at most 50
texts per call; split a longer list.

### `--method`, and why the two are not comparable

| Method | Ranking | Score means | Availability |
|---|---|---|---|
| `local` | The deployment's own bi-encoder (`intfloat/multilingual-e5-large`) over the whole taxonomy | Cosine similarity, clustering high (~0.7–0.9) even for weak matches | Always |
| `albert` | Albert API `bge-m3` retrieval, then a `bge-reranker-v2-m3` cross-encoder | Reranker relevance, typically small and sharply separated | Only where the deployment holds an Albert key |

The orders are usually similar and `albert` is often sharper, but **the numbers
are on different scales**. Never compare a `local` score to an `albert` one, and
never carry a threshold tuned on one over to the other. A deployment without an
Albert key answers `HTTP 400` naming what is missing; fall back to `local`
rather than retrying.

### `--code`: narrowing the candidate set

`--code` restricts the ranking to the codes you pass, which is how to force a
choice within a known area — a collection that only ever spans three classes, or
a second pass that resolves a tie. Unknown codes are ignored silently; a list in
which *nothing* is known is `HTTP 400: No known Dewey codes provided.`

The taxonomy is the deployment's own `taxonomy.json`: the reduced Dewey list
French thesis cataloguing uses in the Sudoc, 98 classes — the ten main divisions
plus their tens, with the finer entries that rule keeps (`004`, `020`, `060`,
`070`, `090`, `796`, `944`). A code outside it, however valid in Dewey proper,
is simply not there. The snapshot served at the time of writing is in
[`references/llm.md`](references/llm.md), along with the one-call way to
re-derive it — the operator can edit the taxonomy, so treat the list as a
snapshot rather than a contract.

---

## Output

Strict JSON on stdout. Classification returns no records, so it does not use the
record envelope; it has its own contract, and this is it — the API's response,
plus the `command` and the `api_url` it came from.

```jsonc
{
  "source": "embedding_classification",   // or "albert_rerank_classification"
  "command": "classify",
  "api_url": "https://dewey-classifier.smartbiblia.fr",
  "method": "local",
  "model": "intfloat/multilingual-e5-large",
  "classification_type": "multi-label",
  "threshold": 0.0,
  "count": 1,                             // texts classified, not classes returned
  "results": [
    {
      "text": "Histoire politique de Buenos Aires au XIXe siècle",
      "classes": [
        { "dewey": "980", "label": "Histoire générale de l'Amérique du Sud", "score": 0.8194 },
        { "dewey": "944", "label": "Histoire générale de la France",         "score": 0.7925 },
        { "dewey": "330", "label": "Economie",                               "score": 0.7891 }
      ]
    }
  ],
  "error": null
}
```

`results` is always an array with one entry per input text, in the order sent,
each echoing its `text` so a batch can be re-joined to its source rows.
`classes` is ranked best-first and may be empty when `--threshold` filtered
everything out. `dewey` is the authoritative code and `label` its authoritative
French label — both come from the thesis list unchanged and are what you write
into a record; `score` is a ranking aid and belongs in a report, not in a
catalogue field.

`health` has its own small shape:

```jsonc
{ "command": "health", "api_url": "https://…", "ok": true, "error": null }
```

### Reading the scores

**They are similarities, not probabilities, and not calibrated.** With
e5-style models they sit around 0.7–0.9 even when the match is poor, so a high
number is not evidence on its own — only the *gap* between the first and second
class is. Two habits follow:

- Treat the answer as a shortlist. Ask for `--top-k 3` and look at whether the
  leader stands clear, rather than trusting a single `single-label` answer.
- Leave `--threshold` at `0.0` unless you have measured a cutoff on your own
  corpus, and confirm assignments with a human before they reach a catalogue.
- On anything that is not a thesis, treat even a clear leader as a hint: the
  ranking is against the thesis list, so the nearest class may simply be the
  least wrong one available.

---

## Artifact contract

The CLI writes one complete JSON response to stdout and nothing else. It does
not choose or create a project, review, or run directory, and it has no
`--output` flag: when persistence is wanted, the calling agent redirects stdout
or captures the payload itself — the whole response, not just `results`.

Stable filenames, when one is needed:

| What produced it | Filename |
|---|---|
| `classify`, one text | `dewey-classify-<text-slug>.json` |
| `classify`, a batch | `dewey-classify-batch.json` |
| `health` | `dewey-health.json` |

`<text-slug>` is the first `--text` value, lowercase kebab-case, every
non-alphanumeric character collapsed to `-` and truncated to 60 characters. No
counters, no class codes, no scores, no dates. The parent directory is the
caller's business, and no filename is needed at all when the result is only
being returned to the user.

---

## Composition hints

```text
a thesis you already hold — its title, its subject keywords, its abstract
  → classify-theses-dewey classify   ← this skill
      ↓
   a ranked shortlist of Dewey classes, best-first
      ↓
   a clear leader → propose the class, for a human to confirm
   a tight cluster → report the top few, or re-run with --code over them
```

Upstream and downstream:

```text
search-theses-fr / search-records-sudoc   ← where the theses come from
  → classify-theses-dewey                 ← this skill
      → convert-records-unimarc           ← where a confirmed class is written back
```

`search-theses-fr` is the natural upstream: its records are exactly the material
the service was built for. Pass each `title` — optionally joined with its
`abstract` or its subject keywords — as one `--text`, batched, and re-join the
answers on the echoed `text`. Records from another bibliographic retrieval skill
fit the same way, with the caveat above about material that is not a thesis.

The same classification is reachable over MCP from
`mcp/dewey-classifier-api/mcp_server.py` in this repository. Use that server when
the agent has a live MCP connection; use this skill's CLI in a shell pipeline.
They call the same endpoint and return the same fields.

---

## Environment variables

| Variable | Default | Required | Purpose |
|---|---|---|---|
| `DEWEY_API_URL` | `https://dewey-classifier.smartbiblia.fr` | no | Base URL of the humatheque-dewey-classifier-api service |
| `DEWEY_API_KEY` | empty | only if the API sets one | Sent as `X-API-Key` |

The default is the public SmartBibl.IA deployment, so the skill works with no
configuration; **point `DEWEY_API_URL` at your own deployment when the texts
should not leave your infrastructure.** Set them in `scripts/.env` (see
`scripts/.env.example`) or export them. Nothing else is configurable by
environment: the timeout, the retry count and the backoff are constants in
`cli.py`, and every classification parameter is a flag.

---

## Failure modes

- Exit code is always `0`. Every failure is an `error` string in the JSON —
  check it before reading `results`.
- **API unreachable** — `error` names the URL. Check `DEWEY_API_URL`, then run
  `health`. Nothing about the classification can be inferred from this.
- **`HTTP 401`** — `DEWEY_API_KEY` is missing or wrong for that deployment.
- **`HTTP 422`** — the request body was rejected; the `detail` names the field.
- **`HTTP 400: Unknown method`** — that deployment cannot serve `--method albert`
  (no Albert key). Fall back to `local`; do not retry the same method.
- **`HTTP 400: No known Dewey codes provided.`** — every `--code` you passed is
  outside the thesis list. Drop the restriction, or take codes from
  `references/llm.md`.
- **`results` present but `classes` empty** — a successful call: `--threshold`
  filtered everything. Lower it, or drop it.
- **The first call is slow (tens of seconds)** — a cold deployment loads the
  embedding model and builds the taxonomy index on first use. The client waits up
  to 120s. Later calls answer in well under a second.
- **A batch is one call** — repeating `--text` is far cheaper than looping the
  CLI, and the API is single-worker, so a loop also serializes anyway.

---

## Files

- `scripts/cli.py` — thin uv client over the API
- `scripts/.env.example` — endpoint and credential template
- `references/llm.md` — API digest: the 98-class thesis list, the score semantics,
  and the request/response quirks the OpenAPI schema does not state
