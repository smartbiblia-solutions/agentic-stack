---
name: resolve-persons-idref
description: >
  Resolve a person named in any document to their IdRef PPN, the French national
  authority identifier, through the idref-resolver-api service (Qualinka
  find-ra-idref and attrra plus IdRef linked references). Use this skill for
  prompts like "trouve le PPN de X", "quel est le PPN de cet auteur", "find the
  IdRef identifier of this researcher", "align this author to IdRef", "authority
  control for this name", or whenever a person mentioned in a catalogue record,
  a bibliography or a web page must be tied to a national authority record. Give
  the name plus any disambiguating clue — works, field, affiliation, year — and
  the service returns the best-matching PPN with a status that may be a
  deliberate abstention. Prefer search-authorities-idref when the task is a
  direct authority search rather than deciding which candidate is the person.
  Returns strict JSON.
version: "1.0.0"
author: smartbiblia
maturity: beta
preferred_output: json
metadata:
  {
    "openclaw": {
      "always": true,
      "requires": { "bins": ["uv"], "env": ["IDREF_API_URL"] },
      "primaryEnv": "IDREF_API_KEY"
    }
  }

selection:
  use_when:
    - A person named in a document, a record or a page must be tied to an IdRef PPN.
    - The task is authority control or identity reconciliation on French person authorities.
    - The user mentions Qualinka, Paprika, find-ra-idref, attrra, PPN, or IdRef alignment.
    - Two homonyms must be separated using context such as an affiliation, a field or a year.
  avoid_when:
    - The task is to search or browse IdRef authorities directly by name or subject; use search-authorities-idref.
    - The task is to retrieve bibliographic records rather than authority records; use search-records-sudoc.
    - The PPN is already known and only its record is needed; fetch it from IdRef directly.
  prefer_over:
    - generic-web-search
  combine_with:
    - search-records-sudoc
    - search-authorities-idref

tags:
  - idref
  - qualinka
  - authorities
  - identity-resolution
  - france
---

# resolve-persons-idref

## Purpose

Deciding which IdRef authority *is* a given person is a judgement made from
evidence: the candidate's preferred forms, the sources and notes of their
authority record, and the citations of the documents linked to them. That
judgement lives in the `idref-resolver-api` service, which fans out to the
Qualinka `find-ra-idref` and `attrra` services and to the IdRef references
service, scores every candidate against the context you supply, and either
accepts one PPN or abstains.

This skill is the routing layer over that API. `scripts/cli.py` is a thin client:
it builds the request, forwards the key, and prints the API's answer unchanged.
No score is computed here, and the CLI calls no host but the API — which is why
a change in the alignment model never needs a change in this skill.

---

## When to use / When not to use

Use this skill when a person mentioned anywhere — a catalogue record, a thesis,
an article, a bibliography, a web page — has to be tied to the French national
authority file, and the answer must be defensible rather than plausible. Pass
every clue you have: a name alone rarely separates two homonyms, and the extra
context is exactly what the score is computed from.

Do not use it when:

- The task is to search or browse IdRef authorities directly — use
  `search-authorities-idref`.
- The task is bibliographic retrieval rather than authority control — use
  `search-records-sudoc`.
- The PPN is already known and only the record's content is wanted.

---

## CLI usage

```bash
# the common case: a name plus whatever context the document gives you
uv run ./skills/resolve-persons-idref/scripts/cli.py align-person \
  --name "Valérie Robert" \
  --affiliation "Nancy" \
  --year 2003

# an author of a known work
uv run ./skills/resolve-persons-idref/scripts/cli.py align-person \
  --name "Bruno Latour" \
  --work "Nous n'avons jamais été modernes" \
  --field "sociologie des sciences"

# is the service reachable at all?
uv run ./skills/resolve-persons-idref/scripts/cli.py health
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--name` | string | **required** | Full person name |
| `--first-name` / `--last-name` | string | — | Override the API's name parsing |
| `--work` | string | — | Title of a document the person is linked to. **Repeatable** |
| `--field` | string | — | Discipline or subject area |
| `--affiliation` | string | — | Institution, laboratory or place |
| `--role` | string | — | Role or document type; enriches the context, never scored |
| `--year` | string | — | A relevant year |
| `--context` | string | — | Any other free-text clue: a biographical note, an abstract |
| `--embedding-model` | enum | `lexical-idf` | `lexical`, `lexical-idf`, `albert-bge-m3`, `granite`, `qwen`, `minilm` |
| `--max-candidates` | int | `20` | Candidates the API enriches and scores |
| `--accept-threshold` | float | `0.65` | Minimum final score for `accepted` |
| `--margin-threshold` | float | `0.08` | Minimum lead over the runner-up |

`lexical-idf` needs no model and always works. The other modes must be deployed
on the API side — `albert-bge-m3` needs an Albert key there, and the local
sentence-transformers models need their directory mounted. A mode the deployment
cannot serve comes back as an `error` naming what is missing; that is a
deployment fact, not a retry-worthy failure.

---

## Output

Strict JSON on stdout. The payload is the API's response, plus the `api_url` it
came from — deliberately not trimmed, so there is one schema and not two.

```jsonc
{
  "source": "idref_qualinka_alignment",
  "api_url": "http://localhost:8000",
  "status": "accepted",
  "best_ppn": "076642860",
  "best_candidate": {
    "ppn": "076642860",
    "url": "https://www.idref.fr/076642860",
    "score": {
      "final": 0.6783,
      "name": 1.0,
      "attrra_source": 0.7432,
      "attrra_note": 0.3667,
      "references": 0.0,
      "clue_match": 0.75
    },
    "evidence": {
      "preferred_forms": ["Robert, Valérie"],
      "best_attrra_source": "Satisfaction et vécu périopératoire…",
      "best_attrra_note": "Titulaire d'un doctorat d'université…",
      "best_references": []
    },
    "errors": []
  },
  "candidates": [],
  "similarity": { "embedding_model": "lexical-idf", "backend": "lexical" },
  "query": { "name": "Valérie Robert", "context_text": "Valérie Robert Nancy 2003" },
  "score_weights": { "name": 0.4, "attrra_source": 0.25 },
  "error": null
}
```

`status` is the answer, and three of its four values are abstentions:

| Status | Meaning | What to report |
|---|---|---|
| `accepted` | Best candidate clears both thresholds | The PPN |
| `ambiguous` | Best candidate is too close to the runner-up | Two or more plausible people; ask for a clue |
| `low_confidence` | Candidates exist but none scores high enough | No usable match on this evidence |
| `not_found` | Candidate search returned no usable PPN | The name is absent, or misspelled |

**`best_ppn` is populated only when `status == "accepted"`.** `best_candidate` is
always the top of the ranking so an abstention can be inspected; never report it
as the resolved identifier. Do not lower the thresholds to force an answer — an
abstention with a reason is worth more than a wrong PPN in an authority file.

---

## Composition hints

```text
a person named in a record, a document or a page
  → resolve-persons-idref align-person   ← this skill
      ↓
   accepted → the PPN, usable as a stable identifier
   abstained → report the status, or come back with one more clue
```

Upstream and downstream:

```text
search-records-sudoc          ← where the person's name and works often come from
  → resolve-persons-idref     ← this skill
      → search-authorities-idref   ← inspect or expand the accepted authority
```

The same alignment is reachable over MCP from
`mcp/idref-resolver-api/mcp_server.py` in this repository. Use that server
when the agent has a live MCP
connection; use this skill's CLI in a shell pipeline. They call the same
endpoint and return the same fields.

---

## Environment variables

| Variable | Default | Required | Purpose |
|---|---|---|---|
| `IDREF_API_URL` | `http://localhost:8000` | yes in practice | Base URL of the idref-resolver-api service |
| `IDREF_API_KEY` | empty | only if the API sets one | Sent as `X-API-Key` |

Set them in `scripts/.env` (see `scripts/.env.example`) or export them. Nothing
else is configurable by environment: the timeout, the retry count and the
backoff are constants in `cli.py`, and every alignment parameter is a flag.

---

## Failure modes

- Exit code is always `0`. Every failure is an `error` string in the JSON —
  inspect it before reading `status`.
- **API unreachable** — `error` names the URL. Check `IDREF_API_URL`, then run
  `health`. Nothing about the alignment can be inferred from this.
- **`HTTP 401`** — `IDREF_API_KEY` is missing or wrong for that deployment.
- **`HTTP 422`** — the request body was rejected; the `detail` names the field.
- **`HTTP 400`** — the deployment cannot serve the requested `--embedding-model`.
  Fall back to `lexical-idf`; do not retry the same mode.
- **`status` is an abstention** — this is a successful call. Report the status.
- **`error` set with a `status` present** — an upstream ABES service degraded and
  the alignment ran on partial evidence. Treat the result as weaker than usual;
  per-candidate failures are listed in each candidate's `errors[]`.
- An alignment can take tens of seconds: the API fans out to as many as 41
  upstream requests. The client waits up to 180s.

---

## Files

- `scripts/cli.py` — thin uv client over the API
- `scripts/.env.example` — endpoint and credential template
