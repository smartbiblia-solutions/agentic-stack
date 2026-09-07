# Pack thesis-cataloger

Ce workspace implémente un pipeline minimal de catalogage assisté de travaux
universitaires à partir d'une image de page de titre.

## Dossiers

- `input/` : images à traiter.
- `output/` : résultats intermédiaires et notice finale.

## Workflow

Lorsqu'un utilisateur demande de cataloguer un document, exécute les étapes
ci-dessous dans l'ordre.

### 1. Sélection de l'image

Liste les images présentes dans `input/`.

- Si une seule image est présente, utilise-la.
- Si plusieurs images sont présentes et qu'aucune n'a été désignée, demande
  laquelle traiter.
- Si aucune image n'est présente, indique-le à l'utilisateur et arrête le workflow.

### 2. Extraction des métadonnées

Utilise la skill `extract-thesis-metadata`.

Analyse l'image sélectionnée et produis les métadonnées structurées selon
le contrat défini par la skill.

Enregistre exactement le JSON obtenu dans :

`output/metadata.json`

Ne corrige pas et ne complète pas silencieusement le résultat de la skill.

### 3. Vérification Sudoc

Utilise les outils du serveur MCP `sudoc-sru` pour rechercher une notice
correspondant au document extrait.

Effectue la recherche à partir des métadonnées disponibles, notamment :

- titre ;
- auteur ;
- année ;
- établissement ;
- type de diplôme ;
- discipline.

Enregistre le résultat utile dans :

`output/sudoc.json`

Si une notice imprimée correspondant clairement au document existe déjà :

- signale son PPN ;
- arrête la génération d'une nouvelle notice.

Si le résultat est ambigu, signale-le mais ne transforme jamais une
correspondance incertaine en correspondance certaine.

### 4. Alignement IdRef

Utilise les outils du serveur MCP `idref-resolver`.

Effectue l'alignement pour :

- l'auteur ;
- chaque directeur ou directrice ;
- le président ou la présidente du jury ;
- les rapporteurs ;
- les autres membres du jury lorsque cela est utile.

Utilise comme contexte de désambiguïsation les métadonnées du document
disponibles (titre, sous-titre, discipline...).

N'accepte un PPN que lorsque le service le considère comme suffisamment fiable.

Enregistre les résultats dans :

`output/idref.json`

Ne jamais inventer ou compléter un PPN.

### 5. Classification Dewey

Utilise les outils du serveur MCP `dewey-classifier`.

Construis le texte de classification à partir, au minimum, du titre et de la
discipline, et ajoute le sous-titre s'il est disponible.

Demande plusieurs propositions lorsque l'outil le permet.

Enregistre le résultat dans :

`output/dewey.json`

La classe Dewey retenue reste une proposition documentaire et doit être
signalée comme telle si le résultat est incertain.

### 6. Construction de la notice UNIMARC

Utilise la skill `catalogage-these-unimarc`.

Fournis-lui :

- les métadonnées extraites ;
- les identifiants IdRef acceptés ;
- la classification Dewey retenue ;
- les informations utiles issues de la vérification Sudoc.

Ne génère pas directement la notice sans utiliser cette skill.

Enregistre la notice obtenue dans :

`output/notice.txt`

### 7. Restitution

Présente un résumé court du traitement comprenant :

- l'image traitée ;
- le résultat Sudoc ;
- les alignements IdRef acceptés et non résolus ;
- la classe Dewey proposée ;
- le chemin de la notice générée ;
- les points nécessitant une validation humaine.
