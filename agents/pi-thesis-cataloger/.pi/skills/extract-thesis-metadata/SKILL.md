---
name: extract-thesis-metadata
description: >
  Extraire depuis l'image d'une page de titre de mémoire ou travail universitaire
  des métadonnées bibliographiques structurées en JSON strict. À utiliser lorsqu'une
  image de page de titre doit être analysée avant catalogage.
---

# Extraction des métadonnées d'un travail universitaire

Analyse l'image fournie en utilisant directement les capacités visuelles
du modèle multimodal actif.

Retourne uniquement un objet JSON conforme au contrat ci-dessous.

## Instructions d'extraction

You are extracting metadata from a French graduate dissertation title page.

General rules:

- Return ONLY valid JSON.
- Do not add markdown.
- Do not add explanations.
- Do not invent missing data.
- Multivalued fields are always JSON arrays; use [] when empty. Scalar fields use null when absent.
- If source text is written in all-caps, transform it into sentence case with French accents.
- For person names, apply sentence case (e.g. Jean-Daniel DUBOIS → Jean-Daniel Dubois, MARIE-FRANCE Dupont → Marie-France Dupont) and remove all civility and title prefixes (e.g. Monsieur, Madame, M., Mme, Professeur, Pr, Dr, etc.) before returning the name.

Role attribution rules:

- A role is explicit only when a textual role label is directly associated with the person.
- Assign a person to a specific role ONLY if that role is explicitly written on the title page.
- Do NOT infer roles from position, ordering, typography, academic conventions, or prior knowledge.
- Do not infer role equivalence from document structure or visual grouping.
- If people are listed without explicit role labels, place them ONLY in committee_members.
- If no jury or committee members are explicitly listed, use [].
- Do NOT guess who is advisor, reviewer, or jury president.

## Schéma de sortie

{
  "title": "Main title as it appears on the title page",
  "subtitle": "Subtitle or remainder of the title, usually following a colon.",
  "author": "Full name of the author (student) who wrote the graduate dissertation",
  "degree_type": "Academic degree sought by the author. Possible values are Habilitation à diriger des recherches | Mémoire de DEA | Mémoire de DES | Mémoire de DESS | Mémoire de DU | Mémoire de DIU | Mémoire de DUT | Mémoire de maîtrise | Mémoire de master professionnel 1re année | Mémoire de master professionnel 2e année | Mémoire de master recherche 1re année | Mémoire de master recherche 2e année",
  "discipline": "Academic field or discipline of the graduate dissertation as explicitly mentioned. If not explicitly mentioned, infer it from the title and any other visible contextual elements (this is the only field where inference is allowed). Always return the discipline label in French (e.g. Histoire, Droit public, Sciences de l'éducation).",
  "volume": "Volume number if the title page explicitly mentions a volume, returned as the Arabic numeral only (e.g. \"1\" when the page prints Tome 1, TOME PREMIER or vol. I). Null if not explicitly mentioned.",
  "granting_institution": "Institution where the graduate dissertation was submitted and the degree is granted",
  "co_tutelle_institutions": "List of institutions involved in a joint supervision or co-tutelle agreement.",
  "doctoral_school": "Doctoral school or graduate program, if explicitly mentioned",
  "defense_year": "Year the graduate dissertation was defended. Format yyyy",
  "advisor": "List of ONLY persons explicitly identified as graduate dissertation advisor/supervisor/director.",
  "jury_president": "ONLY the person explicitly identified as president/chair of the jury. Null if not explicitly stated.",
  "reviewers": "List of ONLY official reviewers/rapporteurs explicitly identified as such.",
  "committee_members": "List of persons explicitly listed as jury or committee members whose role is not explicitly identified as president/chair or reviewer/rapporteur. Include unlabeled persons here.",
  "language": "Language in ISO 639-3 codes. Example: fre, eng, ita...",
  "confidence": "Confidence score between 0.0 and 1.0 reflecting certainty based only on explicitly visible evidence on the page"
}

## Règle de sauvegarde

Lorsque cette skill est appelée dans le pack `thesis-cataloger`, le JSON final
doit être sauvegardé dans `output/metadata.json`.
