---
name: catalogage-these-unimarc
description: >
  Construire une proposition de notice UNIMARC pour un travail universitaire
  imprimé à partir de métadonnées extraites, d'autorités IdRef alignées et
  d'une classification Dewey. À utiliser uniquement après extraction et
  enrichissement documentaire.
---

# Catalogage UNIMARC des travaux universitaires

Cette skill construit une proposition de notice UNIMARC à partir des résultats
produits par le pipeline documentaire.

Elle ne doit jamais inventer une donnée absente des entrées.

## Entrées

Construis d'abord un objet de travail interne de la forme :

```json
{
  "profile": "these_originale_imprimee",
  "work_metadata": {
    "title": null,
    "subtitle": null,
    "volume": null,
    "defense_year": null,
    "language": "fre"
  },
  "thesis_metadata": {
    "degree_type": null,
    "discipline": null,
    "granting_institution": null,
    "doctoral_school": null
  },
  "persons": [],
  "dewey_classification": {
    "code": null,
    "label": null
  }
}
```

Chaque personne est représentée sous la forme :

```json
{
  "name": "Prénom Nom",
  "ppn": null,
  "roles": []
}
```

Les rôles possibles sont notamment :

- `author`
- `advisor`
- `jury_president`
- `reviewer`
- `committee_member`

Un PPN ne peut être ajouté que s'il provient explicitement du résultat
du service IdRef.

## Construction de la notice

Produis les zones dans cet ordre :

- 001
- 008
- 029
- 100
- 101
- 102
- 106
- 104 / 105 selon le profil
- 181
- 182
- 183
- 200
- 214
- 215
- 328
- 330 si disponible
- 608
- 686 si une classification Dewey est disponible
- 700 / 701 pour les personnes
- zones collectivités si applicables

### Zones fixes

```text
001  [à attribuer]
008  Aax3
029  ##$aFR
102  ##$aFR
106  ##$ar
181  ##$P01$ctxt
182  ##$P01$cn
183  ##$P01$anga
608  ##$3027253139$aThèses et écrits académiques$2rameau
```

Pour le profil `these_originale_imprimee` :

```text
104  ##$ak$by$cy$dba$e0$ffre
105  ##$bm$c0$d0$fy
```

## Zone 100

Construit une valeur codée cohérente avec l'année de soutenance et la langue,
selon la logique portée par le pipeline de référence.

## Zone 101

```text
101  0#$a[langue ISO 639-3]
```

## Zone 200

Construire :

```text
200  1#$a[Titre]$e[Sous-titre]$f[Auteur]$g[Directeur(s)]
```

Ne créer `$e`, `$f` ou `$g` que lorsque la donnée correspondante existe.

## Zone 214

```text
214  #1$d[année de soutenance]
```

## Zone 215

Si `volume` est null :

```text
215  ##$a1 volume
```

Si un numéro de volume est explicitement présent, la page de titre ne permet
pas de connaître le nombre total de volumes :

```text
215  ##$a? volumes
```

Ce point doit être signalé pour contrôle humain.

## Zone 328

Construire :

```text
328  #0$b[type de diplôme]$c[discipline]$e[établissement]$d[année]
```

La discipline issue des métadonnées reste la valeur de `$c`.

## Zone 686

Si une classe Dewey a été retenue :

```text
686  ##$a[code Dewey]$2TEF
```

## Personnes

L'auteur principal est porté en zone `700`.

Les autres personnes sont portées en zone `701`.

Ajouter `$3[PPN]` uniquement lorsqu'un PPN IdRef accepté est disponible.

Ne jamais fabriquer de PPN.

Les codes de fonction doivent être déterminés à partir du rôle explicite
de la personne et jamais depuis sa position dans la liste.

## Sortie

Retourne uniquement la notice UNIMARC textuelle.

Dans le pack `thesis-cataloger`, sauvegarde également la notice dans :

`output/notice.txt`
