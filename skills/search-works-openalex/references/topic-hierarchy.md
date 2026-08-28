# Hiérarchie thématique OpenAlex — domaines, champs, sous-champs

Instantané des trois niveaux hauts de l'« aboutness » d'OpenAlex :
**4 domaines, 26 champs, 252 sous-champs**.
Ces trois niveaux sont stables et tiennent dans ce fichier — le lire coûte zéro
appel réseau et zéro budget, là où `browse-topics` en dépense un.

Le quatrième niveau, les **4 516 topics**, n'est pas ici : trop nombreux pour
être utiles en vrac, et c'est précisément ce que
`uv run scripts/cli.py browse-topics --level topics --query …` sert à trouver.

## Comment s'en servir

L'identifiant de la colonne de gauche se réinjecte tel quel dans `search` :

```bash
uv run scripts/cli.py search --query "..." --field 17          # Computer Science
uv run scripts/cli.py search --query "..." --subfield 1702     # Artificial Intelligence
uv run scripts/cli.py search --query "..." --domain 2          # Social Sciences
```

Clés de filtre correspondantes, si la requête est construite à la main :

| Niveau | Rappel (les 3 topics de la notice) | Précision (topic principal) |
|---|---|---|
| Domaine | `topics.domain.id` | `primary_topic.domain.id` |
| Champ | `topics.field.id` | `primary_topic.field.id` |
| Sous-champ | `topics.subfield.id` | `primary_topic.subfield.id` |
| Topic | `topics.id` | `primary_topic.id` |

`--topic-scope any` (défaut) utilise la colonne de gauche, `--topic-scope
primary` celle de droite. Une notice porte jusqu'à trois topics : filtrer sur
`topics.*` ratisse large, `primary_topic.*` ne retient que les notices dont
c'est le sujet principal.

---


## Domaine 1 — Life Sciences


### Champ 11 — Agricultural and Biological Sciences  (11 sous-champs)

| Sous-champ | Libellé |
|---|---|
| `1102` | Agronomy and Crop Science |
| `1103` | Animal Science and Zoology |
| `1104` | Aquatic Science |
| `1105` | Ecology, Evolution, Behavior and Systematics |
| `1106` | Food Science |
| `1107` | Forestry |
| `1100` | General Agricultural and Biological Sciences |
| `1108` | Horticulture |
| `1109` | Insect Science |
| `1110` | Plant Science |
| `1111` | Soil Science |


### Champ 13 — Biochemistry, Genetics and Molecular Biology  (14 sous-champs)

| Sous-champ | Libellé |
|---|---|
| `1302` | Aging |
| `1303` | Biochemistry |
| `1304` | Biophysics |
| `1305` | Biotechnology |
| `1306` | Cancer Research |
| `1307` | Cell Biology |
| `1308` | Clinical Biochemistry |
| `1309` | Developmental Biology |
| `1310` | Endocrinology |
| `1311` | Genetics |
| `1312` | Molecular Biology |
| `1313` | Molecular Medicine |
| `1314` | Physiology |
| `1315` | Structural Biology |


### Champ 24 — Immunology and Microbiology  (5 sous-champs)

| Sous-champ | Libellé |
|---|---|
| `2402` | Applied Microbiology and Biotechnology |
| `2403` | Immunology |
| `2404` | Microbiology |
| `2405` | Parasitology |
| `2406` | Virology |


### Champ 28 — Neuroscience  (8 sous-champs)

| Sous-champ | Libellé |
|---|---|
| `2802` | Behavioral Neuroscience |
| `2803` | Biological Psychiatry |
| `2804` | Cellular and Molecular Neuroscience |
| `2805` | Cognitive Neuroscience |
| `2806` | Developmental Neuroscience |
| `2807` | Endocrine and Autonomic Systems |
| `2808` | Neurology |
| `2809` | Sensory Systems |


### Champ 30 — Pharmacology, Toxicology and Pharmaceutics  (4 sous-champs)

| Sous-champ | Libellé |
|---|---|
| `3002` | Drug Discovery |
| `3003` | Pharmaceutical Science |
| `3004` | Pharmacology |
| `3005` | Toxicology |


## Domaine 2 — Social Sciences


### Champ 12 — Arts and Humanities  (13 sous-champs)

| Sous-champ | Libellé |
|---|---|
| `1204` | Archeology |
| `1205` | Classics |
| `1206` | Conservation |
| `1200` | General Arts and Humanities |
| `1202` | History |
| `1207` | History and Philosophy of Science |
| `1203` | Language and Linguistics |
| `1208` | Literature and Literary Theory |
| `1209` | Museology |
| `1210` | Music |
| `1211` | Philosophy |
| `1212` | Religious studies |
| `1213` | Visual Arts and Performing Arts |


### Champ 14 — Business, Management and Accounting  (9 sous-champs)

| Sous-champ | Libellé |
|---|---|
| `1402` | Accounting |
| `1403` | Business and International Management |
| `1410` | Industrial relations |
| `1404` | Management Information Systems |
| `1405` | Management of Technology and Innovation |
| `1406` | Marketing |
| `1407` | Organizational Behavior and Human Resource Management |
| `1408` | Strategy and Management |
| `1409` | Tourism, Leisure and Hospitality Management |


### Champ 18 — Decision Sciences  (4 sous-champs)

| Sous-champ | Libellé |
|---|---|
| `1800` | General Decision Sciences |
| `1802` | Information Systems and Management |
| `1803` | Management Science and Operations Research |
| `1804` | Statistics, Probability and Uncertainty |


### Champ 20 — Economics, Econometrics and Finance  (3 sous-champs)

| Sous-champ | Libellé |
|---|---|
| `2002` | Economics and Econometrics |
| `2003` | Finance |
| `2000` | General Economics, Econometrics and Finance |


### Champ 32 — Psychology  (7 sous-champs)

| Sous-champ | Libellé |
|---|---|
| `3202` | Applied Psychology |
| `3203` | Clinical Psychology |
| `3204` | Developmental and Educational Psychology |
| `3205` | Experimental and Cognitive Psychology |
| `3200` | General Psychology |
| `3206` | Neuropsychology and Physiological Psychology |
| `3207` | Social Psychology |


### Champ 33 — Social Sciences  (22 sous-champs)

| Sous-champ | Libellé |
|---|---|
| `3314` | Anthropology |
| `3302` | Archeology |
| `3315` | Communication |
| `3316` | Cultural Studies |
| `3317` | Demography |
| `3303` | Development |
| `3304` | Education |
| `3318` | Gender Studies |
| `3300` | General Social Sciences |
| `3305` | Geography, Planning and Development |
| `3306` | Health |
| `3307` | Human Factors and Ergonomics |
| `3308` | Law |
| `3309` | Library and Information Sciences |
| `3319` | Life-span and Life-course Studies |
| `3310` | Linguistics and Language |
| `3320` | Political Science and International Relations |
| `3321` | Public Administration |
| `3311` | Safety Research |
| `3312` | Sociology and Political Science |
| `3313` | Transportation |
| `3322` | Urban Studies |


## Domaine 3 — Physical Sciences


### Champ 15 — Chemical Engineering  (6 sous-champs)

| Sous-champ | Libellé |
|---|---|
| `1502` | Bioengineering |
| `1503` | Catalysis |
| `1504` | Chemical Health and Safety |
| `1506` | Filtration and Separation |
| `1507` | Fluid Flow and Transfer Processes |
| `1508` | Process Chemistry and Technology |


### Champ 16 — Chemistry  (6 sous-champs)

| Sous-champ | Libellé |
|---|---|
| `1602` | Analytical Chemistry |
| `1603` | Electrochemistry |
| `1604` | Inorganic Chemistry |
| `1605` | Organic Chemistry |
| `1606` | Physical and Theoretical Chemistry |
| `1607` | Spectroscopy |


### Champ 17 — Computer Science  (11 sous-champs)

| Sous-champ | Libellé |
|---|---|
| `1702` | Artificial Intelligence |
| `1703` | Computational Theory and Mathematics |
| `1704` | Computer Graphics and Computer-Aided Design |
| `1705` | Computer Networks and Communications |
| `1706` | Computer Science Applications |
| `1707` | Computer Vision and Pattern Recognition |
| `1708` | Hardware and Architecture |
| `1709` | Human-Computer Interaction |
| `1710` | Information Systems |
| `1711` | Signal Processing |
| `1712` | Software |


### Champ 19 — Earth and Planetary Sciences  (8 sous-champs)

| Sous-champ | Libellé |
|---|---|
| `1902` | Atmospheric Science |
| `1904` | Earth-Surface Processes |
| `1906` | Geochemistry and Petrology |
| `1907` | Geology |
| `1908` | Geophysics |
| `1910` | Oceanography |
| `1911` | Paleontology |
| `1912` | Space and Planetary Science |


### Champ 21 — Energy  (5 sous-champs)

| Sous-champ | Libellé |
|---|---|
| `2102` | Energy Engineering and Power Technology |
| `2103` | Fuel Technology |
| `2100` | General Energy |
| `2104` | Nuclear Energy and Engineering |
| `2105` | Renewable Energy, Sustainability and the Environment |


### Champ 22 — Engineering  (16 sous-champs)

| Sous-champ | Libellé |
|---|---|
| `2202` | Aerospace Engineering |
| `2216` | Architecture |
| `2203` | Automotive Engineering |
| `2204` | Biomedical Engineering |
| `2215` | Building and Construction |
| `2205` | Civil and Structural Engineering |
| `2206` | Computational Mechanics |
| `2207` | Control and Systems Engineering |
| `2208` | Electrical and Electronic Engineering |
| `2200` | General Engineering |
| `2209` | Industrial and Manufacturing Engineering |
| `2210` | Mechanical Engineering |
| `2211` | Mechanics of Materials |
| `2214` | Media Technology |
| `2212` | Ocean Engineering |
| `2213` | Safety, Risk, Reliability and Quality |


### Champ 23 — Environmental Science  (11 sous-champs)

| Sous-champ | Libellé |
|---|---|
| `2302` | Ecological Modeling |
| `2303` | Ecology |
| `2304` | Environmental Chemistry |
| `2305` | Environmental Engineering |
| `2306` | Global and Planetary Change |
| `2307` | Health, Toxicology and Mutagenesis |
| `2308` | Management, Monitoring, Policy and Law |
| `2309` | Nature and Landscape Conservation |
| `2310` | Pollution |
| `2311` | Waste Management and Disposal |
| `2312` | Water Science and Technology |


### Champ 25 — Materials Science  (8 sous-champs)

| Sous-champ | Libellé |
|---|---|
| `2502` | Biomaterials |
| `2503` | Ceramics and Composites |
| `2504` | Electronic, Optical and Magnetic Materials |
| `2500` | General Materials Science |
| `2505` | Materials Chemistry |
| `2506` | Metals and Alloys |
| `2507` | Polymers and Plastics |
| `2508` | Surfaces, Coatings and Films |


### Champ 26 — Mathematics  (10 sous-champs)

| Sous-champ | Libellé |
|---|---|
| `2602` | Algebra and Number Theory |
| `2604` | Applied Mathematics |
| `2605` | Computational Mathematics |
| `2607` | Discrete Mathematics and Combinatorics |
| `2608` | Geometry and Topology |
| `2610` | Mathematical Physics |
| `2611` | Modeling and Simulation |
| `2612` | Numerical Analysis |
| `2613` | Statistics and Probability |
| `2614` | Theoretical Computer Science |


### Champ 31 — Physics and Astronomy  (8 sous-champs)

| Sous-champ | Libellé |
|---|---|
| `3102` | Acoustics and Ultrasonics |
| `3103` | Astronomy and Astrophysics |
| `3107` | Atomic and Molecular Physics, and Optics |
| `3104` | Condensed Matter Physics |
| `3105` | Instrumentation |
| `3106` | Nuclear and High Energy Physics |
| `3108` | Radiation |
| `3109` | Statistical and Nonlinear Physics |


## Domaine 4 — Health Sciences


### Champ 35 — Dentistry  (4 sous-champs)

| Sous-champ | Libellé |
|---|---|
| `3500` | General Dentistry |
| `3504` | Oral Surgery |
| `3505` | Orthodontics |
| `3506` | Periodontics |


### Champ 36 — Health Professions  (11 sous-champs)

| Sous-champ | Libellé |
|---|---|
| `3603` | Complementary and Manual Therapy |
| `3604` | Emergency Medical Services |
| `3600` | General Health Professions |
| `3605` | Health Information Management |
| `3607` | Medical Laboratory Technology |
| `3608` | Medical Terminology |
| `3609` | Occupational Therapy |
| `3611` | Pharmacy |
| `3612` | Physical Therapy, Sports Therapy and Rehabilitation |
| `3614` | Radiological and Ultrasound Technology |
| `3616` | Speech and Hearing |


### Champ 27 — Medicine  (42 sous-champs)

| Sous-champ | Libellé |
|---|---|
| `2702` | Anatomy |
| `2703` | Anesthesiology and Pain Medicine |
| `2704` | Biochemistry |
| `2705` | Cardiology and Cardiovascular Medicine |
| `2707` | Complementary and alternative medicine |
| `2706` | Critical Care and Intensive Care Medicine |
| `2708` | Dermatology |
| `2711` | Emergency Medicine |
| `2712` | Endocrinology, Diabetes and Metabolism |
| `2713` | Epidemiology |
| `2714` | Family Practice |
| `2715` | Gastroenterology |
| `2716` | Genetics |
| `2717` | Geriatrics and Gerontology |
| `2718` | Health Informatics |
| `2720` | Hematology |
| `2721` | Hepatology |
| `2723` | Immunology and Allergy |
| `2725` | Infectious Diseases |
| `2724` | Internal Medicine |
| `2726` | Microbiology |
| `2727` | Nephrology |
| `2728` | Neurology |
| `2729` | Obstetrics and Gynecology |
| `2730` | Oncology |
| `2731` | Ophthalmology |
| `2732` | Orthopedics and Sports Medicine |
| `2733` | Otorhinolaryngology |
| `2734` | Pathology and Forensic Medicine |
| `2735` | Pediatrics, Perinatology and Child Health |
| `2736` | Pharmacology |
| `2737` | Physiology |
| `2738` | Psychiatry and Mental health |
| `2739` | Public Health, Environmental and Occupational Health |
| `2740` | Pulmonary and Respiratory Medicine |
| `2741` | Radiology, Nuclear Medicine and Imaging |
| `2742` | Rehabilitation |
| `2743` | Reproductive Medicine |
| `2745` | Rheumatology |
| `2746` | Surgery |
| `2747` | Transplantation |
| `2748` | Urology |


### Champ 29 — Nursing  (4 sous-champs)

| Sous-champ | Libellé |
|---|---|
| `2910` | Issues, ethics and legal aspects |
| `2911` | Leadership and Management |
| `2916` | Nutrition and Dietetics |
| `2922` | Research and Theory |


### Champ 34 — Veterinary  (2 sous-champs)

| Sous-champ | Libellé |
|---|---|
| `3402` | Equine |
| `3404` | Small Animals |


---

Instantané pris le 2026-08-28 sur `https://api.openalex.org/{domains,fields,subfields}`.
