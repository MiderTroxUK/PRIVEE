# MANIFEST des données ouvertes épinglées — projects/factory/opendata

Ingestion **data.gouv.fr épinglée** (U13, plan HÉLIOS v7). Contrairement à
`projects/simu_semiconducteurs/scripts/fetch_data.py` (API INSEE BDM directe,
campagne close), ce module cible l'écosystème générique du **catalogue public
data.gouv.fr** (`https://www.data.gouv.fr/api/1/`) pour des covariables
réutilisables par de futurs chantiers (HÉLIOS ou autres). Le serveur MCP
`data.gouv` (`https://mcp.data.gouv.fr/mcp`) est un outil de **découverte
interactive** ; il n'est pas appelé par ce pipeline automatisé — seules les
ressources ci-dessous, retrouvées et vérifiées via l'API REST publique le
2026-07-21, sont épinglées.

Règle de gel : chaque ligne fixe un **dataset ID**, une **resource URL** et un
**sha256** constatés à une date donnée. `fetch_opendata.py` refuse toute
divergence (voir §3) — même discipline que `HASHES.sha256` de la campagne
HÉLIOS : une source qui a bougé doit être ré-épinglée consciemment, jamais
silencieusement acceptée.

## 1. Séries épinglées (vérifiées via l'API data.gouv.fr le 2026-07-21)

| nom de série | dataset ID data.gouv épinglé | resource URL | licence | sha256 | usage prévu |
|---|---|---|---|---|---|
| `insee_ipch_ensemble` | `6983dff61f90da358ccf74d5` | https://api.insee.fr/melodi/file/DS_IPCH/DS_IPCH_CSV_FR | Licence Ouverte 2.0 (`lov2`) | `0370ee8c453baa8100171b227c7e81b704423a8a983ac339433e09e2861b9a2b` | covariable DGP |
| `sdes_prix_elec_industrie` | `689c42c3c3e194cb535c823a` | https://data.statistiques.developpement-durable.gouv.fr/dido/api/v1/datafiles/1d1b0e79-0979-4db9-98e6-ec7c0dea68d2/csv | Licence Ouverte (`fr-lo`) | `4b40e7110b386b6c30ab7f9c3f76e189fa7b3deeeae35555ce26db58ac26f6d5` | a priori sectoriel |
| `sdes_conso_elec_france` | `689c42c3c3e194cb535c823a` | https://data.statistiques.developpement-durable.gouv.fr/dido/api/v1/datafiles/d0186d31-af8e-4bc0-a579-c4c1e3f62b31/csv | Licence Ouverte (`fr-lo`) | `a6cb02f31331c244dbd20362b2ab5b960e778768b759ac12e21d6bbbbe21e0b8` | covariable DGP |

Tailles réelles téléchargées (traçabilité, cf. `--selftest`) :

| nom de série | fichier brut | octets |
|---|---|---|
| `insee_ipch_ensemble` | `raw/insee_ipch_ensemble.zip` | 1 355 008 |
| `sdes_prix_elec_industrie` | `raw/sdes_prix_elec_industrie.csv` | 22 401 |
| `sdes_conso_elec_france` | `raw/sdes_conso_elec_france.csv` | 58 784 |

**Total brut : 1 436 193 octets (≈ 1,37 Mo)** — sous le budget de 5 Mo. Les
trois licences sont des Licences Ouvertes Etalab : réutilisation et
redistribution libres avec mention de la source, ce qui autorise le commit
de `raw/` et `prepared/` pour que le pipeline fonctionne hors ligne.

### 1.1 Détail des séries et de leur extraction (`fetch_opendata.py`)

1. **`insee_ipch_ensemble`** — Indice des prix à la consommation harmonisé
   (IPCH), ensemble des ménages, France, tous postes (COICOP 2018 = `00`).
   Dataset data.gouv : *« Indice des prix à la consommation harmonisés
   (IPCH) »*, organisme INSEE. La ressource est une archive ZIP Melodi
   (`DS_IPCH_data.csv` + `DS_IPCH_metadata.csv`, séparateur `;`). Ligne
   retenue : `IDX_TYPE=HICP`, `IND_TYPE=IX`, `COICOP_2018=00`, `FREQ=M`.
   366 points mensuels vérifiés (1996-12 → 2026-06) au moment du gel.
   Usage : covariable DGP (pression inflationniste macro, contexte demande).
2. **`sdes_prix_elec_industrie`** — Prix de l'électricité pour l'industrie,
   toutes tranches de consommation confondues (colonne
   `PX_ELE_I_TTES_TRANCHES`), €/MWh. Dataset data.gouv : *« Conjoncture
   mensuelle de l'énergie »* (SDES, ressource « 2.2. Prix industriels
   Électricité »). CSV direct (API DiDo), séparateur `;`, colonne `PERIODE`
   (AAAA-MM). Cadence réellement semestrielle republiée en mensuel par la
   source (valeurs répétées sur 6 mois) — traité comme une série mensuelle
   ordinaire par le pipeline. Usage : a priori sectoriel (coût énergie
   industrie, driver direct de `cost.op_cost` — même rôle que l'IPP
   industrie dans la campagne HÉLIOS).
3. **`sdes_conso_elec_france`** — Consommation électrique française
   (synthèse, colonne `CONSO_ELE_SYNT`, GWh). Même dataset SDES, ressource
   « 4.2 Synthèse Électricité ». Usage : covariable DGP (niveau d'activité
   économique/industrielle — proxy d'activité au même titre que les
   facturations WSTS dans la campagne HÉLIOS).

Pour les trois séries, les mois les plus récents (non encore publiés par la
source) apparaissent avec une valeur vide dans le CSV brut : le normaliseur
les ignore complètement (jamais d'invention de valeur) — ces semaines sont
simplement absentes de `prepared/<serie>.csv`, sans report en avant de la
dernière valeur connue au-delà de son propre mois.

## 2. À qualifier en session MCP (découverte interactive — John)

Les trois candidats initialement visés par le plan — **indice de la
production industrielle**, **climat des affaires dans l'industrie**,
**défaillances d'entreprises** — ont été recherchés via l'API publique
data.gouv.fr (`/api/2/datasets/search/`) le 2026-07-21 et **écartés pour ce
gel** : les datasets INSEE correspondants existent bien sur data.gouv.fr
(`Activité productrice des entreprises` id `53698e6aa3a729239d203466`,
`Enquêtes de conjoncture` id `53699437a3a729239d2043bb`, `Démographie des
entreprises` id `53699260a3a729239d203ee9`) mais **chacun n'expose qu'une
unique ressource de format `html`**, pointant vers une page de recherche
`insee.fr` — pas de resource URL de téléchargement direct, donc rien à
épingler avec un sha256 stable. Ce constat est documenté ici plutôt
qu'inventé ou contourné par un lien deviné.

Pistes pour la session MCP data.gouv (`https://mcp.data.gouv.fr/mcp`), qui
permet une recherche sémantique plus riche que l'API REST brute :

- **Indicateur du climat des affaires dans l'industrie** (série INSEE
  historique la plus directement liée au chantier « Ud empirique INSEE » —
  cf. mémoire `project_ud_calibration_insee.md` : remplacer à terme le
  questionnaire AHP hebdomadaire par un signal réel de confiance/urgence
  perçue des entreprises). Non trouvé avec ressource directe à ce jour ;
  probablement disponible via une API Melodi dédiée (même famille que
  `DS_IPCH` ci-dessus) mais pas encore repérée comme resource data.gouv.
- **Indice de production industrielle** (NAF 26.1 ou ensemble industrie) —
  déjà couvert pour la campagne HÉLIOS via l'API BDM directe
  (`fetch_data.py`, hors périmètre data.gouv) ; à réévaluer si une ressource
  data.gouv directe apparaît (dataset actuellement en `html` seul).
- **Défaillances d'entreprises** — idem ; la Banque de France publie des
  séries proches via Webstat, non encore repérées sur data.gouv.fr avec une
  ressource directe lors de cette session.
- **Baromètre Nogogo — Risque des entreprises françaises** (id
  `6a29297bf504bebf00ded2e6`) : source non institutionnelle repérée en
  passant, jamais qualifiée (licence et méthodologie à vérifier par John
  avant tout usage).

## 3. Discipline de vérification

`fetch_opendata.py --serie NAME` (ou `--all`) télécharge la ressource
épinglée, calcule son sha256 et le compare à ce MANIFEST. Toute divergence
est un **échec dur** : le script s'arrête avec un message explicite (la
source a changé depuis le gel, donc son contenu n'est plus celui vérifié —
même principe que le gel de `data/prepared/HASHES.sha256` dans la campagne
HÉLIOS, qui interdit toute retouche silencieuse d'un pack déjà vérifié).
`--selftest` revérifie les fichiers déjà présents sous `raw/` sans retélécharger
(utilisable hors ligne / en CI).
