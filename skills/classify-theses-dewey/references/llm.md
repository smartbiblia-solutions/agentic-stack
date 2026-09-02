# humatheque-dewey-classifier-api — agent digest

A local documentation snapshot for the API this skill wraps, kept here because
the service publishes no `llm.txt`. It records the behaviours an agent gets
wrong from the OpenAPI schema alone. Authoritative sources, if this drifts:

- Code and README: <https://github.com/gegedenice/humatheque-dewey-classifier-api>
- Live deployment: <https://dewey-classifier.smartbiblia.fr>
- Interactive docs: `/docs` · machine schema: `/openapi.json`

Service title: **Humatheque Classification API**, version 0.2.0 at the time of
writing.

**What it classifies.** French doctoral theses, from the metadata a thesis record
carries. The vocabulary is not the full Dewey schedules: it is the reduced list
French thesis cataloguing uses in the Sudoc — 98 classes, snapshot below. The API
accepts any text and answers for any text, but the candidate set and the enriched
class descriptions were both built for that corpus, so an answer about a novel or
a software manual is the nearest class *in the thesis list*, not a Dewey number.

---

## Surface

Three endpoints, and only one does work.

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /` | none | `{"service", "version", "docs", "health"}` — a banner |
| `GET /health` | none | `{"ok": true}` — the container health check |
| `POST /classify` | `X-API-Key`, optional | The whole API |

There is **no endpoint that lists the taxonomy**, no lookup by code, and no way
to see a class's keyword description. See *Enumerating the taxonomy* below for
the workaround.

## Authentication

Optional and deployment-wide. The service reads `CLASSIFICATION_API_KEY` (or
`API_KEY`); when it is empty — as on the public deployment today — `/classify`
is open. When set, clients send `X-API-Key: <key>`. There is no per-request or
per-tool credential, and the key is never part of the request body.

## `POST /classify`

```jsonc
{
  "text": "…" | ["…", "…"],   // required
  "codes": ["980", "944"],     // optional, null = the whole taxonomy
  "threshold": 0.0,            // optional, -1.0 … 1.0
  "classification_type": "multi-label",  // or "single-label"
  "top_k": 5,                  // optional, ≥1, default from the deployment's env
  "method": "local"            // or "albert"
}
```

Response, identical in shape for both methods:

```jsonc
{
  "source": "embedding_classification",   // "albert_rerank_classification" for albert
  "method": "local",
  "model": "intfloat/multilingual-e5-large",
  "classification_type": "multi-label",
  "threshold": 0.0,
  "count": 1,                             // number of TEXTS, not of classes
  "results": [
    { "text": "…", "classes": [ {"dewey": "980", "label": "…", "score": 0.8194} ] }
  ]
}
```

### Non-obvious behaviours

- **`text` is a union.** A string classifies one text; a list classifies a batch
  and returns one `results` entry per element, **in the order sent**, each
  echoing its own `text`. That echo is the only join key — there is no index
  field — so preserve order or match on the string.
- **Batching is the throughput story.** The service embeds on CPU in a
  threadpool, and a single worker handles one request at a time. Ten texts in one
  call beat ten calls; a client-side loop just serializes.
- **`count` counts texts, not classes.** A batch of two with `top_k: 5` has
  `count: 2` and up to ten class entries in total.
- **`dewey` is nullable in the schema** (`label` and `score` are not). Handle a
  null code rather than assuming a string.
- **`classes` can legitimately be empty** when `threshold` filtered everything.
  That is a successful call, not a failure.
- **`single-label` returns exactly one class** and ignores `top_k`.
- **`top_k` has no server-side maximum.** Values above the taxonomy size simply
  return the whole ranking — which is what makes the enumeration trick below
  work.

### The scores are not what they look like

The README is explicit and it matters more than any other line here:

> these are cosine similarities, not calibrated probabilities. With e5-style
> models they cluster high (≈0.7–0.9) even for weak matches, so treat them as a
> *ranking*.

Practical consequences:

- `0.82` is not "82% confident". A wrong class routinely scores 0.79.
- The signal is the **gap** between rank 1 and rank 2, not the absolute value.
- `threshold` defaults to `0.0` deliberately. Do not invent a cutoff; rely on
  `top_k` plus human confirmation.
- **`local` and `albert` scores are on different scales and must never be
  compared.** `albert` returns the cross-encoder's `relevance_score` passed
  through unchanged — often two orders of magnitude smaller (`0.0022` where
  `local` says `0.88`) and much more sharply separated. A threshold tuned on one
  method is meaningless on the other.

### `method`

| Value | Pipeline | Requires |
|---|---|---|
| `local` | The deployment's own bi-encoder over the whole taxonomy, offline | nothing |
| `albert` | Albert API `BAAI/bge-m3` retrieval → `BAAI/bge-reranker-v2-m3` cross-encoder rerank | `ALBERT_API_KEY` on the service |

Both read the same `taxonomy.json` and the same k-NN examples. `albert` is
usually the sharper ranking; it is also a remote call, so it is slower and it
sends the text to <https://albert.api.etalab.gouv.fr>. Both are available on the
public deployment today.

### `codes`

Restricts the candidate classes. Unknown codes are dropped silently, **but a
list in which nothing is known is a hard error**, not an empty result:

```text
HTTP 400  {"detail":"No known Dewey codes provided."}
```

So `codes: ["980", "ZZZ"]` ranks against 980 alone, while `codes: ["ZZZ"]` is a
400. This is the one place where the README's "unknown codes are ignored"
under-describes the behaviour.

## Error policy

The service answers HTTP 200 with a full payload, or a `detail` string with a
4xx. It has no partial-success mode and no `error` field of its own — an
`error` in this skill's output always came from the client, not from the API.

| Status | `detail` | Cause |
|---|---|---|
| 400 | `Unknown method 'x'; expected one of ['local', 'albert'].` | bad `method` |
| 400 | `No known Dewey codes provided.` | every `codes` entry outside the taxonomy |
| 401 | — | `X-API-Key` missing or wrong, on a deployment that sets one |
| 422 | `[{"type":"missing","loc":["body","text"],…}]` | FastAPI validation; `loc` names the field |

Retry 429 and 5xx with backoff. Never retry a 400 or 422 — the body is wrong and
will stay wrong.

## Latency

- **Cold start is the outlier.** The first request after a restart downloads the
  embedding model from Hugging Face and builds the taxonomy index; budget tens of
  seconds. This skill's client waits up to 120 s for that reason.
- Warm `local` calls answer in well under a second; `albert` adds two remote
  round trips.
- The model and index are cached for the process lifetime. **The service must be
  restarted to pick up a `taxonomy.json` change** — which is also why the class
  list below is a snapshot, not a contract.

## How the classification actually works

Worth knowing, because it explains what the service is good at:

Each class is embedded once at startup as `"{label}. {description}"`, where
`description` is an **internal** enriched keyword string — place names, eras,
fields, synonyms — that never appears in a response. Incoming titles are terse
and specific and have to roll *up* to a broad category; a bare label cannot
connect "Buenos Aires, 1829" to "Amérique du Sud", and that keyword vocabulary
is what makes the mapping work.

The model is `intfloat/multilingual-e5-large` by default: multilingual, strong
on French, CPU-friendly. e5/bge models use asymmetric prefixes — the input text
is embedded as a `query: `, the class descriptions as `passage: `.

A deployment may also point `EXAMPLES_PATH` at confirmed `{text, code}`
assignments, blended in as
`final = max(description_similarity, weight × best_example_similarity)`. Where
that is configured, scores can only improve, never degrade.

**Accuracy is improved by editing `taxonomy.json`, not by tuning parameters.**
Nothing a client sends changes the quality of the mapping — only `codes`, which
narrows what it may choose from.

## Enumerating the taxonomy

There is no listing endpoint, but `top_k` is unbounded, so one call with a
throwaway text returns every class:

```bash
curl -s -X POST https://dewey-classifier.smartbiblia.fr/classify \
  -H 'Content-Type: application/json' \
  -d '{"text":"a","top_k":1000}' |
python3 -c 'import sys,json
for c in sorted(json.load(sys.stdin)["results"][0]["classes"], key=lambda x: x["dewey"] or ""):
    print(c["dewey"], c["label"])'
```

Do this against the deployment you are actually calling before relying on any
code — the operator owns the taxonomy and can change it.

### Snapshot: 98 classes, public deployment, September 2026

This is the list French thesis cataloguing uses in the Sudoc, not the full Dewey
schedules: the ten main classes and their tens divisions, plus the seven finer
entries that rule keeps — `004`, `020`, `060`, `070`, `090`, `796`, `944`. Codes
are always three characters, zero-padded. A code that is valid in Dewey but
absent from thesis practice is absent here too, and `codes` will drop it.

| | |
|---|---|
| `000` Informatique, information, généralités · `004` Informatique · `020` Bibliothéconomie et sciences de l'information · `060` Organisations générales et muséologie · `070` Médias d'information, journalisme, édition · `090` Manuscrits et livres rares | |
| `100` Philosophie, psychologie · `110` Métaphysique · `120` Epistémologie, causalité, genre humain · `130` Phénomènes paranormaux, pseudosciences · `140` Les divers systèmes et écoles philosophiques · `150` Psychologie · `160` Logique · `170` Morale (éthique) · `180` Philosophie de l'Antiquité, du Moyen Âge, de l'Orient · `190` Philosophie occidentale moderne et philosophies non orientales | |
| `200` Religion · `210` Philosophie et théorie de la religion · `220` Bible · `230` Théologie chrétienne · `240` Théologie morale et pratiques chrétiennes · `250` Eglises locales, ordres religieux chrétiens · `260` Théologie chrétienne et société, ecclésiologie · `270` Histoire et géographie du christianisme et de l'Eglise chrétienne · `280` Confessions et sectes de l'Eglise chrétienne · `290` Autres religions | |
| `300` Sciences sociales, sociologie, anthropologie · `310` Statistiques générales · `320` Science politique · `330` Economie · `340` Droit · `350` Administration publique. Arts et science militaires · `360` Problèmes et services sociaux · `370` Education et enseignement · `380` Commerce, communications, transports · `390` Ethnologie | |
| `400` Langues et linguistique · `410` Linguistique générale · `420` Langue anglaise. Anglo-saxon · `430` Langues germaniques. Allemand · `440` Langues romanes. Français · `450` Langues italienne, roumaine, rhéto-romane · `460` Langues espagnole et portugaise · `470` Langues italiques. Latin · `480` Langues helléniques. Grec classique · `490` Autres langues | |
| `500` Sciences de la nature et mathématiques · `510` Mathématiques · `520` Astronomie, cartographie, géodésie · `530` Physique · `540` Chimie, minéralogie, cristallographie · `550` Sciences de la terre · `560` Paléontologie. Paléozoologie · `570` Sciences de la vie, biologie, biochimie · `580` Plantes. Botanique · `590` Animaux. Zoologie | |
| `600` Technologie (Sciences appliquées) · `610` Médecine et santé · `620` Sciences de l'ingénieur · `630` Agronomie, agriculture et médecine vétérinaire · `640` Economie domestique. Vie familiale · `650` Gestion et organisation de l'entreprise · `660` Génie chimique, technologies alimentaires · `670` Fabrication industrielle · `680` Fabrication de produits à usages spécifiques · `690` Bâtiments | |
| `700` Arts. Beaux-arts et arts décoratifs · `710` Urbanisme · `720` Architecture · `730` Arts plastiques. Sculpture · `740` Dessin. Arts décoratifs · `750` Peinture · `760` Arts graphiques · `770` Photographie et les photographies, art numérique · `780` Musique · `790` Arts du spectacle, loisirs · `796` Sport | |
| `800` Histoire et critique littéraires, rhétorique · `810` Littérature américaine en anglais · `820` Littératures anglaise et anglo-saxonne · `830` Littérature allemande · `840` Littérature de langues romanes. Littérature française · `850` Littérature italienne · `860` Littératures espagnole et portugaise · `870` Littérature latine · `880` Littérature grecque · `890` Littératures des autres langues | |
| `900` Géographie et histoire · `910` Géographie et voyages · `920` Biographies générales, généalogie, emblèmes · `930` Histoire ancienne et préhistoire · `940` Histoire moderne et contemporaine de l'Europe · `944` Histoire générale de la France · `950` Histoire générale de l'Asie, Orient, Extrême-Orient · `960` Histoire générale de l'Afrique · `970` Histoire générale de l'Amérique du Nord · `980` Histoire générale de l'Amérique du Sud · `990` Histoire générale des autres parties du monde, des mondes extraterrestres. Iles du Pacifique | |

Two consequences for a caller:

- **Labels are French**, whatever the language of the input. The classifier is
  multilingual on the input side only.
- **The granularity is coarse by design.** There is no `005.13` here, because
  there is none in the thesis rule either: the record carries a division-level
  indice and the cataloguer refines from there. Asking the service for a precise
  shelfmark is asking for something the list does not contain.
- **The odd-looking entries are the rule's, not an accident.** `796` beside a
  bare `790`, `944` beside `940`, `004` beside `000` — those are the splits
  thesis cataloguing makes, and they are why the list has 98 entries rather than
  100.

## Deployment-side settings, for context

None of these are client-visible, but they explain why two deployments answer
differently: `EMBEDDING_MODEL`, `EMBEDDING_DEVICE`, `TAXONOMY_PATH`,
`EXAMPLES_PATH`, `EMBEDDING_EXAMPLE_WEIGHT`, `CLASSIFICATION_TOP_K`,
`CLASSIFICATION_THRESHOLD`, `CLASSIFICATION_TYPE`, `CLASSIFICATION_METHOD`,
`ALBERT_API_KEY`, `RERANK_CANDIDATES`. The last defaults — `top_k` 5, threshold
0.0, `multi-label`, `local` — are what an omitted request field falls back to,
so **always send the ones you care about** rather than relying on a default that
belongs to someone else's deployment.
