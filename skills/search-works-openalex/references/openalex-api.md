# OpenAlex — digest hors ligne de l'API

Ce qu'il faut savoir sur `https://api.openalex.org` pour utiliser cette skill
sans aller lire la documentation. Il ne remplace pas l'amont, il évite d'y
retourner pour les cinq choses qu'on y cherche à chaque fois : ce que coûte un
appel, comment filtrer, ce qui a été supprimé, et les deux ou trois pièges qui
font échouer une requête pourtant correcte.

Documentation en ligne : <https://help.openalex.org/>, digest agent
<https://help.openalex.org/api/llm-quick-reference/>. OpenAlex publie désormais
son propre `llms.txt` : quand le réseau est disponible, il fait autorité sur ce
fichier.

Instantané pris le 2026-08-28.

---

## Budget : la seule contrainte qui compte

Depuis février 2026, le *polite pool* et le paramètre `mailto` n'existent plus.
L'accès est mesuré en **budget quotidien** :

| Accès | Budget/jour | Ordre de grandeur |
|---|---|---|
| Anonyme (sans clé) | **$0.10** | ~100 recherches |
| Clé gratuite (`OPENALEX_API_KEY`) | **$1.00** | ~1 000 recherches |
| Formules payantes | plus | — |

Tarifs, pour 1 000 appels :

| Opération | Coût / 1 000 | Ce que la skill l'utilise |
|---|---|---|
| Entité unique par ID ou DOI | **gratuit** | `batch-lookup-by-doi` |
| Liste + filtre | **$0.10** | `search` sans `--query`, `get-citing-works`, `group-by`, `browse-topics` |
| Recherche plein texte | **$1** | `search` avec `--query` |
| Recherche sémantique | **$1** | `search-semantic`, `classify-text` |
| Traduction OQL (`/query/...`) | **$0.10** | `translate-query` — ne touche pas l'index, facturé au tarif liste |
| Autocomplete (`/autocomplete/...`) | **gratuit** | `resolve-entity` |
| Téléchargement de contenu | **$10** | non utilisé |

Deux conséquences pratiques :

- **Un lookup par DOI est gratuit, une recherche ne l'est pas.** Quand
  l'identifiant est connu, `batch-lookup-by-doi` ne consomme rien.
- **`per_page=100` divise la facture par quatre** face au défaut de 25 : le
  coût est par appel, pas par notice. La skill le fait par défaut.

Chaque réponse expose son coût dans `meta.cost` ; les commandes de la skill le
recopient dans `cost_usd`.

---

## Filtres utiles

Syntaxe : `?filter=cle:valeur,autre:valeur` — la virgule est un **ET**, le tube
`|` un **OU** à l'intérieur d'une clé, le `!` une négation
(`type:!dataset`). Les comparaisons numériques et de dates s'écrivent
`publication_year:>2020`, `cited_by_count:<10`.

| Clé | Note |
|---|---|
| `authorships.institutions.lineage` | **Le bon filtre institution** : couvre l'établissement et ses composantes (UMR, hôpital, IUT). C'est ce vers quoi OQL compile `institution is …`. |
| `authorships.institutions.id` | Affiliation exacte, sans descendance — plus étroit, rate les labos rattachés. |
| `authorships.author.id` | Un auteur. |
| `topics.id` / `topics.subfield.id` / `topics.field.id` / `topics.domain.id` | Rappel : une notice porte jusqu'à 3 topics. |
| `primary_topic.id` (et `.subfield/.field/.domain`) | Précision : le sujet principal seul. |
| `publication_year`, `from_publication_date`, `to_publication_date` | Bornes temporelles. |
| `is_oa`, `open_access.oa_status` | `gold`, `green`, `hybrid`, `bronze`, `closed`, `diamond`. |
| `type` | `article`, `book-chapter`, `preprint`, `dataset`, `review`… |
| `language` | Code ISO 639-1 (`fr`, `en`). |
| `has_abstract`, `has_fulltext`, `has_doi` | Booléens de complétude. |
| `is_retracted` | À exclure explicitement dans une revue de littérature. |
| `cited_by_count`, `fwci` | Impact brut / normalisé par champ et par année. |
| `doi`, `ids.pmid`, `ids.openalex` | Identifiants. |
| `primary_location.source.id` | Une revue ou un dépôt. |
| `authorships.countries` / `authorships.institutions.country_code` | Code pays ISO. |

Voir `topic-hierarchy.md` pour les identifiants de domaines, champs et
sous-champs — 282 lignes, zéro appel réseau.

## Paramètres transverses

| Paramètre | Valeurs | Note |
|---|---|---|
| `per_page` | 1–**100** | 200 encore toléré mais **déprécié** ; 201 renvoie 400. La skill plafonne à 100. |
| `page` | — | `page × per_page ≤ 10 000`. Au-delà : curseur. |
| `cursor` | `*` puis `meta.next_cursor` | Seule pagination profonde, et la seule possible avec `group_by`. |
| `select` | liste de champs | Réduit la charge utile, pas le coût. |
| `sort` | `relevance_score:desc`, `cited_by_count:desc`, `publication_date:desc` | `relevance_score` n'a de sens qu'avec une recherche. |
| `group_by` | une clé de filtre | Agrégation ; 200 groupes par page, `meta.groups_count` donne le total. Suffixe `:include_unknown` pour compter les valeurs manquantes. |
| `corpus` | `core` (défaut), `expansion`, `all` | **Works uniquement.** |
| `api_key` | — | Sinon budget anonyme. |

### Corpus

Le **core** (~320 M notices, Crossref/MAG/PubMed/DataCite) est ce que renvoie
toute requête par défaut. L'**expansion** (~190 M, ex-« XPAC ») ajoute surtout
des jeux de données et des notices de dépôt non appariées ; `all` réunit les
deux (~510 M). Chaque notice porte `is_xpac`. Les anciens contrôles
`include_xpac=true` et `filter=is_xpac:true` sont dépréciés, et **les mélanger
avec `corpus=` renvoie une erreur**.

Un décompte qui double sans raison, c'est presque toujours le corpus.

---

## Recherche

Un seul paramètre de recherche par requête : `search`, `search.exact` **ou**
`search.semantic` — jamais deux.

### Plein texte (`search`)

Analyse stemmée, mots vides retirés. La syntaxe utilisable :

| Forme | Exemple | Effet |
|---|---|---|
| Phrase | `"machine learning"` | Les mots dans cet ordre. |
| Proximité | `"climate policy"~5` | À moins de 5 mots l'un de l'autre. |
| Flou | `bioinformatics~2` | Tolère 2 éditions — utile sur les noms propres. |
| Booléens | `crispr AND (mouse OR murine)` | Majuscules obligatoires. |
| Joker | `neuro*`, `wom?n` | **Exige `search.exact`** — ignoré par `search`. |

`search.exact` désactive le stemming : `mice` ne trouve plus `mouse`. C'est ce
qu'il faut pour un nom de gène, une référence de norme, ou un joker.

### Sémantique (`search.semantic`)

Plongement du titre et du résumé (GTE Large EN, 1 024 dimensions), similarité
cosinus. Trouve « computational toxicology » à partir de « predicting drug
toxicity from molecular structure ».

| Contrainte | Valeur |
|---|---|
| Entrée | **2 000 caractères**, tronqué au-delà |
| Résultats | **50 maximum**, sans pagination |
| Débit | 1 requête/seconde |

Les filtres et `select` s'appliquent normalement, **sauf deux** que le
pré-filtrage de centaines de millions de vecteurs ferait expirer :
`last_known_institutions.country_code` (et le raccourci `country_code`) et
`cited_by_count`. `authorships.institutions.lineage` fonctionne, lui — c'est ce
qui rend `search-semantic --institution` possible.

Plus l'entrée est longue et descriptive, meilleur est le résultat : un résumé
ou un objectif de projet collé tel quel bat trois mots-clés.

---

## OQL — le langage de requête

Trois formes de la même requête : **OQL** (texte lisible), **OQO** (objet JSON)
et **oxurl** (l'URL REST). La traduction se fait à
`GET /query/{oql|oqo|oxurl}/{requête-encodée}` — **segment de chemin, pas
paramètre**. `?q=` sur cette route renvoie
`{"message": "OpenAlex ID format not recognized"}`, ce qui n'aide pas à
comprendre l'erreur.

```
GET /query/oxurl/works%20where%20institution%20is%20Sorbonne%20Universit%C3%A9
GET /query/oql/%2Fworks%3Ffilter%3Dis_oa%3Atrue
```

Deux routes voisines prennent, elles, un paramètre : `/query/validate?q=` et
`/query/parse-context?q=`.

La traduction ne touche pas l'index et est facturée au tarif le plus bas
(0,0001 $ l'appel). C'est le moyen le moins cher de vérifier qu'un filtre s'écrit comme on le croit — et de découvrir
que `institution is X` compile vers `authorships.institutions.lineage`, pas
vers `.id`.

Toute réponse normale renvoie aussi `meta.x_query.oql` : la requête que l'on
vient de faire, réécrite en OQL. Utile pour montrer à l'utilisateur ce qui a
réellement été interrogé.

Le corpus s'y exprime en parenthèse finale : `works (expansion corpus)`.

---

## Autocomplete

`GET /autocomplete/{works|authors|sources|institutions|topics|publishers|funders|keywords}?q=…`

Gratuit, ~200 ms. Chaque suggestion porte `id`, `short_id`, `display_name`,
`hint` (désambiguïsation : pays d'une institution, revue d'un auteur),
`external_id` (ROR, ORCID, ISSN), `works_count`, `cited_by_count`,
`entity_type` et **`filter_key`** — la clé de filtre à utiliser avec cet
identifiant, donnée par l'API elle-même.

Deux propriétés à connaître, parce qu'elles produisent des silences :

- **préfixe** : `strasbourg` ne trouve pas « Université de Strasbourg », mais
  `universite de stras` oui ;
- **sensible aux diacritiques** : `universite` et `université` ne donnent pas
  la même chose.

D'où le repli de `resolve-entity` sur `/institutions?search=` quand
l'autocomplete ne rend rien.

---

## Hiérarchie thématique

4 domaines → 26 champs → 252 sous-champs → 4 516 topics. Les trois premiers
niveaux sont dans `topic-hierarchy.md`. Endpoints : `/domains`, `/fields`,
`/subfields`, `/topics`, plus `/keywords` et `/sdgs` (17 objectifs de
développement durable) qui ne font pas partie de la hiérarchie.

Les identifiants sont courts et stables : domaine `2`, champ `17`, sous-champ
`1702`, topic `T10234`.

---

## Supprimé et déprécié

Supprimé — provoque une erreur :

| Ancien | Remplacement |
|---|---|
| `host_venue`, `alternate_host_venues` | `primary_location`, `locations` |
| `grants` | `awards` (et `funders` sur la notice) |
| `has_ngrams` | `has_fulltext` |
| `mailto` / polite pool | `api_key` |
| `/text` (classification « aboutness ») | plus d'endpoint — reconstruire par `search.semantic` puis agrégation des topics, ce que fait `classify-text` |

Déprécié, encore fonctionnel :

| Déprécié | Remplacement |
|---|---|
| Entité **Concepts** (~65 000, 6 niveaux, ex-MAG) | **Topics** (~4 500, 4 niveaux) — `concepts.id` → `topics.id` |
| `x_concepts` sur auteurs/sources/institutions | `group_by=topics.id` sur leurs works |
| `last_known_institution` (singulier) | `last_known_institutions` (pluriel) |
| `per_page=200` | `per_page=100` |
| `include_xpac`, `filter=is_xpac:` | `corpus=` |

---

## Pièges

- **URL d'environ 4 Ko.** Une liste de 200 DOI dans un `filter=doi:a|b|c…`
  dépasse la limite et renvoie 400. Découper et réunir les réponses ;
  `batch-lookup-by-doi` le fait.
- **Pagination classique bloquée à 10 000.** `page × per_page ≤ 10 000` ;
  au-delà, `cursor=*` puis `meta.next_cursor`. Le curseur est aussi la seule
  pagination possible sur `group_by`.
- **`relevance_score` n'existe que sur une recherche.** Trier dessus une requête
  purement filtrée ne renvoie rien d'utile.
- **`corpus=expansion` est bruyant.** Notices de dépôt sans résumé, doublons
  non appariés. À réserver aux jeux de données et à la littérature grise.
- **Une institution est une lignée.** Filtrer sur `.id` rate les publications
  signées par une UMR ou un CHU rattaché : préférer `.lineage`.
- **Trois topics par notice.** `topics.id` ratisse, `primary_topic.id` tranche —
  et l'écart entre les deux décomptes est souvent d'un facteur trois.
