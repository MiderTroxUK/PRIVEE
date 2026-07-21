# Référence des données et des exports

> Vérifié contre SupplyScore v2.0.0. Source de vérité : supplyscore/services/exports.py, services/report.py, data/.

Ce document décrit où vivent les données de SupplyScore, sous quelle forme elles
sortent de l'application (export tabulaire, rapport HTML, archive de sauvegarde)
et comment elles sont structurées en base (schéma SQLite, migrations, journal
d'audit). Le public visé : la personne qui dépouille une session de jeu, écrit un
script d'analyse ou doit comprendre un fichier produit par l'application. Les
procédures d'exploitation (sauvegarde planifiée, restauration pas à pas,
journaux) sont dans le [guide d'exploitation](exploitation.md).

## 1. Architecture des données

L'interface web (Dash) ne touche jamais SQLite directement : toutes les pages
passent par la façade `SupplyScoreService` (services/orchestrator.py), qui tient
deux familles de bases et alimente trois types de sorties.

```
                 ┌──────────────────────────┐
                 │   Interface web (Dash)   │
                 │  pages /projets /rapport │
                 └────────────┬─────────────┘
                              │
                 ┌────────────▼─────────────┐
                 │    SupplyScoreService    │
                 │   (façade applicative)   │
                 └────┬────────────────┬────┘
                      │                │
        ┌─────────────▼──┐      ┌──────▼──────────────────┐
        │ registry.sqlite│      │  <node_id>.sqlite       │
        │ registre global│      │  UNE base PAR nœud      │
        │ (graphe, tags, │      │  (AHP, KPI, urgences,   │
        │  jalons...)    │      │  événements, décisions) │
        └────────────────┘      └─────────────────────────┘
                      │                │
        ┌─────────────▼────────────────▼─────────────────┐
        │                 Trois sorties                  │
        │  export projet      rapport de session  zip de │
        │  (.xlsx / .zip CSV) (.html autonome)  sauvegarde│
        └────────────────────────────────────────────────┘
```

Le découpage suit le principe métier : le graphe logistique (projets, nœuds,
arcs, jalons, tags) est partagé et vit dans `registry.sqlite`, tandis que chaque
nœud possède son propre fichier `<node_id>.sqlite` avec ses séries temporelles
(évaluations AHP hebdomadaires, snapshots KPI, historique d'urgence, événements,
décisions, revues). Les deux familles portent en plus leur journal d'audit
(section 6).

Toutes les bases vivent dans un répertoire unique, par défaut
`%LOCALAPPDATA%\SupplyScore\data` (hors dossier synchronisé cloud), modifiable
par `--db-dir`. Le choix de cet emplacement, la migration depuis l'ancien
`data_store/` et le risque de corruption des bases WAL sous OneDrive sont
détaillés dans [exploitation.md](exploitation.md) §1. Sur un poste en activité,
le répertoire ressemble à ceci :

```
%LOCALAPPDATA%\SupplyScore\data\
├── registry.sqlite              registre global
├── registry.sqlite-wal          journal WAL (transitoire, purgé à la fermeture)
├── registry.sqlite-shm          mémoire partagée WAL (transitoire)
├── 3f2a...e91c.sqlite           base du nœud 3f2a...e91c
├── 7bd4...02af.sqlite           base d'un autre nœud (autant que de nœuds)
└── backups\
    ├── SupplyScore_20260610_083015.zip
    └── SupplyScore_20260611_090212.zip
```

Les fichiers `-wal` et `-shm` n'existent que pendant l'exécution : la fermeture
propre checkpointe et les purge (section 5). Les exports et rapports, eux, ne
vont pas dans ce répertoire : ils sont écrits dans un dossier `exports` relatif
au dossier de lancement de l'application, puis téléchargés par le navigateur.

Les trois sorties sont en lecture seule : ni l'export, ni le rapport, ni la
sauvegarde n'écrivent dans les bases.

## 2. Export projet (xlsx ou zip CSV)

`ExportService` (supplyscore/services/exports.py) agrège tout le matériau d'un
projet pour l'analyse post-jeu. Le fichier produit s'appelle
`SupplyScore_<slug>_AAAAMMJJ_HHMMSS.xlsx` ou `.zip` : le slug est le nom du
projet translittéré en ASCII (décomposition NFKD, les accents tombent), tout
caractère non alphanumérique devenant un tiret ; l'horodatage vient de l'horloge
du service, en heure locale. Un projet nommé « Démo AÉRIS / phase 2 » exporté le
12 juin 2026 à 14 h 30 donne ainsi
`SupplyScore_Demo-AERIS-phase-2_20260612_143000.xlsx`. Le fichier est déposé
dans le répertoire `exports` (relatif au dossier de lancement), créé au besoin.
Toutes les dates epoch sont rendues « JJ/MM/AAAA HH:MM » en heure locale, et
chaque feuille porte ses en-têtes en ligne 1.

Le déclenchement se fait depuis la page Projets, carte « Exporter &
sauvegarder », bouton « Exporter le projet (xlsx) » : le callback appelle
`export_project(pid, fmt="xlsx")` et déclenche le téléchargement. La variante
CSV n'a pas de bouton : elle s'obtient par l'API,
`ExportService(service).export_project(project_id, fmt="csv")`.

### Les douze feuilles, dans l'ordre du classeur

`_build_sheets` assemble douze feuilles : quatre feuilles registre (`projet`,
`noeuds`, `arcs`, `jalons`), sept feuilles agrégées des bases client (chacune
avec une colonne « nœud » en tête), et la feuille `audit_registre` qui clôt le
classeur. Les feuilles client agrègent tous les nœuds du projet en un seul
passage.

Feuille `projet` (une ligne, la fiche d'identité) :

| Colonne | Signification |
|---|---|
| id | identifiant du projet |
| nom | nom libre du projet |
| description | description libre |
| t0 | origine temporelle effective (t0_ts, sinon la date de création) |
| créé le | date de création |
| mode horloge | `game` (temps de jeu) ou `real` (temps réel) |

Feuille `noeuds` (identité, tags et état d'urgence courant, ordre registre :
rang puis id) :

| Colonne | Signification |
|---|---|
| id | identifiant du nœud |
| nom | nom du nœud |
| label | étiquette (Factory, Warehouse, Client...) |
| rang | rang dans le DAG (0 = client final) |
| statut | statut de tâche du nœud |
| complétude onboarding | `draft` tant que le wizard n'est pas fini, `complete` sinon |
| tags | noms des tags du nœud, joints par des virgules |
| localisation | ville |
| ud_local, ur_local | urgences locales (questionnaire, KPIs) |
| ud, ur | urgences propagées sur le graphe |
| adequation | score d'adéquation A, dans [0, 100] |
| false_urgency | F = [Ud moins Ur]+ |
| hidden_risk | H = [Ur moins Ud]+ |

Feuille `arcs` (seuls les arcs dont les deux extrémités sont dans le projet) :

| Colonne | Signification |
|---|---|
| source, cible | noms des nœuds (pas les ids) |
| nature | `nominal` ou `backup` |
| gamma, beta, delta | coefficients de propagation de l'arc |

Feuille `jalons` (tous les jalons des nœuds du projet) :

| Colonne | Signification |
|---|---|
| nœud | nom du nœud porteur |
| nom | nom du jalon |
| type | proto, serie, livraison, custom |
| début, échéance | fenêtre temporelle, dates formatées |
| statut | statut du jalon (active, done...) |
| avancement | progression dans [0, 1] |

Feuille `historique_urgences` (table `urgency_history` de chaque base client,
chronologique) :

| Colonne | Signification |
|---|---|
| nœud | nom du nœud |
| semaine | semaine ISO calculée du timestamp (« AAAA-Sxx ») |
| date | date formatée |
| ud_local, ur_local, ud, ur | les quatre urgences à cet instant |
| adequation, false_urgency, hidden_risk | A, F, H à cet instant |

Feuille `evaluations` (table `assessments`, chronologique) :

| Colonne | Signification |
|---|---|
| nœud | nom du nœud |
| opérateur | opérateur ayant répondu au questionnaire |
| semaine | semaine ISO de l'évaluation |
| ud | urgence déclarée résultante |
| CR | ratio de cohérence AHP |
| cohérente | « oui » si CR < 0.10, « non » sinon |
| notes | notes libres |
| remplacée par | id de l'évaluation correctrice, vide si l'évaluation est effective |

Feuille `snapshots_kpi` (table `kpi_snapshots`, chronologique) : trois colonnes
fixes suivies des 42 colonnes KPI aplaties décrites plus bas.

| Colonne | Signification |
|---|---|
| nœud | nom du nœud |
| date | date du snapshot, formatée |
| semaine | semaine ISO calculée du timestamp |
| network.product ... risk.political_risk | les 42 valeurs du bundle, une colonne par champ déclaré |

Feuille `evenements` (table `events`, par date d'occurrence) :

| Colonne | Signification |
|---|---|
| nœud | nom du nœud |
| type | type d'événement (clé du catalogue) |
| semaine, date | semaine ISO et date d'occurrence |
| paramètres | paramètres saisis, en JSON trié |
| impacts | résumé lisible « bloc.champ: avant → après », joints par « ; » |
| annulé le | date d'annulation, vide si l'événement est actif |
| opérateur, notes | opérateur déclarant et notes libres |

Feuille `decisions` (table `decisions`, en ordre chronologique) :

| Colonne | Signification |
|---|---|
| nœud | nom du nœud |
| semaine | semaine ISO de la décision |
| opérateur | opérateur ayant consigné la décision |
| description | texte de la décision |
| ud, ur, a, f, h | snapshot des cinq scores au moment de la décision |

Feuille `revues_hebdo` (table `weekly_reviews`, par semaine ISO croissante) :

| Colonne | Signification |
|---|---|
| nœud | nom du nœud |
| semaine | semaine ISO de la revue |
| volets | avancement des volets, JSON brut (ex. `{"ahp": 1, "kpis": 0}`) |
| début, fin | horodatages de démarrage et de complétion |
| durée (minutes) | (fin moins début) / 60, arrondie à une décimale, vide si la revue n'est pas bornée |

Feuille `audit` (table `audit_log` de chaque base client, chronologique) :

| Colonne | Signification |
|---|---|
| nœud | nom du nœud dont la base est lue |
| type entité | type d'entité auditée (`node_kpis`, `spec_sheet`...) |
| id entité | identifiant de l'entité (l'id du nœud pour les KPIs) |
| champ | champ qualifié modifié, ex. `risk.failure_probability` |
| avant, après | valeurs JSON avant et après la mutation |
| source | origine de la mutation (voir section 6) |
| opérateur | opérateur à l'origine, vide si non applicable |
| semaine | semaine ISO de l'écriture |
| date | date formatée |

Feuille `audit_registre` : le journal d'audit global de `registry.sqlite`, mêmes
colonnes sans « nœud ». Ce journal n'est pas filtré par projet : le registre est
partagé entre projets, et les entités qu'il audite (nœuds, arcs, jalons) n'y
portent pas toutes leur projet.

Quelques conventions transverses sur les lignes : chaque feuille de série est
triée chronologiquement (timestamp puis id), sauf `revues_hebdo` qui suit la
semaine ISO croissante. Dans `evaluations`, une ligne dont « remplacée par » est
renseignée a été corrigée par l'évaluation portant cet id : seule la correction
compte dans les calculs, mais l'historique complet est exporté.

### Les colonnes KPI aplaties

La fonction `_kpi_columns()` dérive les colonnes de la dataclass `KPIBundle`
(domain/models.py) : pour chaque bloc déclaré, chaque champ déclaré devient une
colonne `bloc.champ`, dans l'ordre des dataclasses. Les propriétés calculées
(`oee`, `total_g_h`, `remaining_volume_m3`...) ne sont pas des champs déclarés
et n'apparaissent donc pas. Le décompte par bloc :

| Bloc | Champs | Colonnes |
|---|---|---|
| network | product, distance_km, demand | 3 |
| inventory | max_volume_m3, max_weight_kg, current_volume_m3, current_weight_kg, flow_rate | 5 |
| time | speed_kmh, distance_range_km, time_range_h, refuel_time_h, lead_time_h, lead_time_std_h, lead_time_min_h, lead_time_mode_h, lead_time_max_h, delay_h, deadline_h | 11 |
| cost | product_cost, tariff, nominal_op_cost, op_cost, fuel_cost, risk_cost, storage_cost | 7 |
| co2 | fuel_emission_g_km, op_emission_g_h, energy_mix_g_h, co2_target_g_h, co2_max_g_h | 5 |
| oee | production_time_h, operating_time_h, availability, performance, quality | 5 |
| risk | failure_probability, recovery_time_h, severity, cost_volatility, env_exposure, political_risk | 6 |

Soit 42 colonnes au total. Un KPI non renseigné donne une cellule vide. Comme la
liste est dérivée du code à chaque export, un champ ajouté à un bloc apparaîtra
automatiquement dans les exports suivants.

### Variante zip CSV

Avec `fmt="csv"`, l'export produit un zip contenant un fichier `<feuille>.csv`
par feuille, mêmes noms, mêmes en-têtes, mêmes lignes. L'encodage est
`utf-8-sig` (BOM en tête, ce qu'Excel attend pour détecter l'UTF-8), le
séparateur est le point-virgule et les fins de ligne sont CRLF : les conventions
d'Excel en français. Les valeurs `None` deviennent des cellules vides. Le
contenu est strictement identique entre les deux formats : seul le contenant
change, un double-clic sur un CSV du zip ouvre la feuille correspondante dans
Excel sans assistant d'import.

## 3. Rapport de session HTML

`SessionReport` (supplyscore/services/report.py) produit le livrable d'une
partie : un fichier `Rapport_<slug>_AAAAMMJJ_HHMMSS.html` (mêmes règles de slug
et d'horodatage que l'export), déposé lui aussi dans `exports`. Le fichier est
autonome : le CSS est inline et chaque figure n'embarque que son fragment HTML
(`fig.to_html(full_html=False, include_plotlyjs=False)`). Seul le JavaScript
Plotly est chargé via CDN, une seule fois dans le `<head>`, à la version exacte
embarquée par plotly.py : l'ouverture du rapport nécessite donc une connexion
internet. Une règle `@media print` rend le document imprimable tel quel.

Le gabarit Jinja2 (inline dans le module) comporte un en-tête puis cinq sections
numérotées :

1. un tableau de métadonnées en tête : période couverte (première et dernière
   semaine ISO de l'historique d'urgence), mode horloge (« temps de jeu » ou
   « temps réel »), nombre de nœuds, date de génération ;
2. « 1. Synthèse des scores » : un tableau par nœud avec rang, statut et les
   scores courants Ud, Ur, A, F, H ;
3. « 2. Évolution temporelle » : une figure Plotly Ud/Ur/A par nœud possédant un
   historique d'urgence (les nœuds sans historique sont omis) ;
4. « 3. Chronologie des événements et décisions » : les deux journaux fusionnés
   et regroupés par semaine ISO, en ordre chronologique, avec pour chaque entrée
   le type, le nœud, l'intitulé, le détail, l'opérateur et le statut (un
   événement annulé porte sa date d'annulation) ;
5. « 4. Calibration prédiction / réalité » : synthèse, matrice de confusion au
   seuil H = 0.5 (VP, FP, FN, VN), précision et rappel, puis la courbe de
   calibration en cinq segments. Les effectifs sont toujours affichés à côté des
   taux, et un avertissement « échantillon réduit » apparaît sous 30 points
   nœud-semaine ;
6. « 5. Graphe final » : le DAG du projet (figure `dashboard_dag_figure`,
   arcs internes au projet uniquement).

Un pied de page « SupplyScore, rapport de session généré automatiquement »
ferme le document. Dans la chronologie, une décision affiche en détail le
snapshot des cinq scores au moment où elle a été prise (Ud, Ur, A, F, H), et un
événement affiche ses paramètres avec leurs libellés français et leurs unités
tels que calibrés dans le catalogue d'événements.

L'horizon de calibration (l'appariement entre une prédiction H et l'issue
observée N semaines plus tard) vaut 4 semaines par défaut et se règle entre 1 et
12. La génération se fait depuis la page Rapport (`/rapport`), qui exige un
projet actif : le champ « Horizon de calibration (semaines) » est borné côté
client, puis revalidé côté serveur (coercition entière et bornage 1..12, la
saisie clavier pouvant contourner les attributs `min`/`max` du champ). Le
fichier produit est téléchargé via le navigateur.

Comme l'export, le rapport est en lecture seule et tire toutes ses dates de
l'horloge du service : pour un projet en mode « temps de jeu », la date
« Généré le » et l'horodatage du nom de fichier reflètent le temps de la
partie, pas celui du poste. Les données proviennent du registre (nœuds, arcs,
scores courants) et des bases client (historiques, événements, décisions),
exactement les mêmes sources que l'export tabulaire de la section 2.

## 4. Format de sauvegarde

`ServiceSauvegarde` (supplyscore/data/backup.py) archive toutes les bases
`*.sqlite` du répertoire de données dans un zip
`SupplyScore_AAAAMMJJ_HHMMSS.zip`, déposé par défaut dans `<db_dir>/backups`.

La méthode `backup_all` suit quatre étapes pour chaque base :

1. `PRAGMA integrity_check` : si une base est corrompue, une `IntegriteError`
   est levée et rien n'est archivé, aucune archive partielle n'existe ;
2. copie vers un fichier temporaire par l'API native
   `sqlite3.Connection.backup`, qui produit une copie cohérente même si
   l'application tient la base ouverte ;
3. les copies sont zippées (les fichiers annexes `-wal` et `-shm` ne sont pas
   archivés : l'API native a absorbé leur contenu dans la copie) ;
4. le répertoire temporaire est nettoyé.

La sauvegarde automatique du démarrage passe par `backup_auto()` : si l'archive
la plus récente a strictement plus de 24 heures (`max_age_h=24.0`), ou s'il n'en
existe aucune, une nouvelle archive est créée ; la rétention supprime ensuite
les archives les plus anciennes au-delà de 20 (`RETENTION_DEFAUT = 20`). L'âge
se lit dans le nom de l'archive, jamais dans les dates du système de fichiers,
et tout fichier au nom non conforme au motif `SupplyScore_AAAAMMJJ_HHMMSS.zip`
est ignoré par la mécanique automatique : ni compté, ni supprimé. Au démarrage,
une base corrompue détectée par cette étape arrête tout avec le code de sortie
2 : l'application ne se lance pas sur des bases corrompues. L'option
`--no-backup` saute l'étape (tests et développement).

La même mécanique est accessible à la demande : page Projets, carte « Exporter &
sauvegarder », bouton « Sauvegarder les bases maintenant » (archive immédiate
puis rétention), avec la liste des trois archives les plus récentes affichée
sous le bouton. Le tri des archives s'appuie sur le nom : l'ordre
lexicographique des horodatages `AAAAMMJJ_HHMMSS` coïncide avec l'ordre
chronologique. Une troisième source d'archives existe : la migration depuis un
`data_store/` hérité (`--migrate-data`) crée d'abord un zip de sécurité dans
`backups_migration`, frère du répertoire cible, avant de déplacer quoi que ce
soit.

La restauration (`restore_backup`, en ligne de commande
`python -m supplyscore.tools.restore`) ne détruit jamais les bases en place :
sans `--force` elle est refusée si le répertoire cible contient déjà des bases ;
avec `--force`, **les bases existantes sont d'abord déplacées, avec leurs
résidus `-wal`/`-shm`/`-journal`, dans un sous-dossier
`avant_restauration_AAAAMMJJ_HHMMSS/`**, jamais supprimées. Chaque base
restaurée est revérifiée par `PRAGMA integrity_check`. Les options de l'outil
sont décrites dans [reference_cli.md §4](reference_cli.md).

## 5. Schéma SQLite

Les deux familles de bases (data/db.py) partagent la même mécanique : connexion
en mode WAL avec `synchronous=NORMAL` (le fsync n'a lieu qu'au checkpoint, gain
massif en écriture ; en cas de coupure brutale, les dernières transactions
depuis le dernier checkpoint peuvent être perdues mais l'intégrité du fichier
est garantie par le WAL), un `threading.RLock` par base sous lequel passe chaque
méthode publique (la connexion est ouverte avec `check_same_thread=False`, le
serveur web servant chaque requête dans un thread distinct), et un
`wal_checkpoint(TRUNCATE)` suivi d'un commit à la fermeture, qui purge les
fichiers `-wal`/`-shm`. Les contraintes de clés étrangères existent dans le DDL
mais leur application est désactivée sur la connexion (`PRAGMA
foreign_keys=OFF`), les appelants historiques insérant parfois l'enfant avant
le parent ; les cascades de suppression sont donc exécutées explicitement. La
suppression d'un nœud, par exemple, efface dans la même transaction ses arcs,
son état d'urgence, ses liens de tags, ses jalons et sa progression
d'onboarding. Les contraintes restent vérifiables à la demande par
`PRAGMA foreign_key_check`.

La version de schéma est portée par `PRAGMA user_version` et gérée par
data/migrations.py : à l'ouverture, `apply_migrations` rejoue dans l'ordre
toutes les migrations dont la version dépasse celle de la base, chacune se
terminant par `PRAGMA user_version = N` dans sa propre transaction.

### Tables de registry.sqlite (12 tables, schéma final v5)

| Table | Colonnes clés | Rôle |
|---|---|---|
| projects | id (PK), name, owner_node_id, t0_ts | fiche projet et origine temporelle |
| nodes | id (PK), project_id, rank, status, kpis_json, onboarding_state | nœuds du graphe, KPIs courants en JSON |
| arcs | (source_id, target_id) PK, gamma, beta, delta, arc_kind | arcs orientés, nominal ou backup |
| node_urgency | node_id (PK), ud, ur, adequation, false_urgency, hidden_risk | état d'urgence courant par nœud (cache de redémarrage) |
| project_settings | (project_id, key) PK, value_json | réglages par projet (mode horloge...) |
| milestones | id (PK), node_id, start_ts, deadline_ts, status, progress | jalons datés des nœuds |
| tag_categories | id (PK), project_id, name, color | catégories de la taxonomie, uniques par projet |
| tags | id (PK), project_id, category_id, name | tags libres, uniques par projet |
| node_tags | (node_id, tag_id) PK | liaisons nœud-tag |
| onboarding_progress | node_id (PK), draft_json, current_step | brouillon du wizard d'onboarding |
| audit_log | id (PK), entity_type, entity_id, field, old_value, new_value, source | journal d'audit du registre (section 6) |
| scenarios | id (PK), project_id, nom, payload_json | scénarios de simulation nommés, nom unique par projet |

### Tables d'une base client (9 tables, schéma final v7)

Chaque nœud possède son fichier `<node_id>.sqlite` :

| Table | Colonnes clés | Rôle |
|---|---|---|
| assessments | id (PK), node_id, comparisons_json, consistency_ratio, ud, replaces_id, iso_week | évaluations AHP hebdomadaires, corrections chaînées par replaces_id |
| kpi_snapshots | id (PK), node_id, kpis_json, timestamp | photos datées du bundle KPI |
| urgency_history | id (PK), node_id, ud, ur, adequation, timestamp, iso_week | série temporelle des états d'urgence |
| spec_sheet | id (PK), node_id, version, payload_json | cahier des charges versionné (version auto-incrémentée par nœud) |
| events | id (PK), node_id, event_type, iso_week, params_json, impacts_json, reverted_at | journal des événements de jeu, annulables |
| audit_log | id (PK), entity_type, entity_id, field, source | journal d'audit de la base client (section 6) |
| weekly_reviews | (node_id, iso_week) PK, volets_json, started_at, completed_at | avancement des volets de la revue hebdomadaire |
| decisions | id (PK), node_id, iso_week, description, scores_snapshot_json | décisions consignées en revue, scores au moment T |
| interventions | id (PK), node_id, date_ts, etat_avant_json, action_id, resultat, etat_apres_json, etat_risque_avant_json, etat_risque_apres_json, succes | journal des interventions correctives, contrat n°9 (voir modele_mathematique.md §13) |

Les bundles KPI sont stockés en JSON (colonnes `kpis_json`). La sérialisation
n'embarque que les champs déclarés des dataclasses : les propriétés calculées
(`oee`, `total_g_h`, `remaining_volume_m3`...) se recalculent à la relecture.
La désérialisation tolère l'évolution de schéma : les clés inconnues d'un bloc
(champs ajoutés par une version plus récente, ou retirés depuis) sont ignorées,
si bien qu'une base ancienne reste lisible par un code plus récent et
inversement. La table `scenarios` suit le même principe d'opacité : son
`payload_json` est validé syntaxiquement avant écriture mais jamais interprété
par la couche data, et le nom d'un scénario est unique par projet.

### Index des bases client et requêtes servies

| Index | Table (colonnes) | Requêtes servies |
|---|---|---|
| idx_events_node_week | events (node_id, iso_week) | liste des événements d'un nœud, filtrée par semaine |
| idx_kpi_snap_node_ts | kpi_snapshots (node_id, timestamp) | lecture temporelle `kpis_at` (dernier snapshot avant t) |
| idx_assessments_week | assessments (node_id, iso_week) | semaines distinctes ayant une évaluation (cycle hebdomadaire) |
| idx_urgency_week | urgency_history (node_id, iso_week) | lectures hebdomadaires de l'historique d'urgence |
| idx_decisions_node_week | decisions (node_id, iso_week) | journal des décisions d'un nœud, filtré par semaine |
| idx_urgency_node_ts | urgency_history (node_id, timestamp) | série temporelle `urgency_series` |
| idx_assessments_node_ts | assessments (node_id, timestamp) | dernière évaluation effective, liste chronologique |
| idx_interventions_node_date | interventions (node_id, date_ts) | journal des interventions d'un nœud, ordre chronologique |

Côté registre, `idx_nodes_project` sert le filtrage des nœuds par projet,
`idx_milestones_node` le listage des jalons par position, `idx_node_tags_tag`
les recherches par tag et `idx_scenarios_project` les listages de scénarios ;
les index d'audit sont décrits en section 6.

### Récapitulatif des migrations

| Base | Version | Apports |
|---|---|---|
| registre | v1 | schéma historique : projects, nodes, arcs (idempotent, passe par-dessus une base existante) |
| registre | v2 | node_urgency, project_settings, vraies FK par reconstruction de nodes et arcs, purge des références pendantes, index idx_nodes_project |
| registre | v3 | colonne projects.t0_ts (backfillée sur created_at), nodes.onboarding_state, arcs.arc_kind, tables milestones, tag_categories, tags, node_tags, onboarding_progress |
| registre | v4 | table audit_log et ses index |
| registre | v5 | table scenarios et l'index idx_scenarios_project |
| client | v1 | schéma historique : assessments, kpi_snapshots, urgency_history |
| client | v2 | spec_sheet, events et l'index idx_events_node_week |
| client | v3 | audit_log, index idx_kpi_snap_node_ts, colonne assessments.replaces_id |
| client | v4 | colonne iso_week sur assessments et urgency_history, backfillée ligne à ligne depuis le timestamp, index idx_assessments_week et idx_urgency_week |
| client | v5 | weekly_reviews, decisions et l'index idx_decisions_node_week |
| client | v6 | index temporels idx_urgency_node_ts et idx_assessments_node_ts |
| client | v7 | table interventions (journal des interventions correctives, contrat n°9) et l'index idx_interventions_node_date |

Chaque migration est atomique : une interruption laisse la base à la version
précédente, rejouable proprement au prochain démarrage.

## 6. Journal d'audit

`AuditTrail` (supplyscore/data/audit.py) journalise chaque mutation d'une entité
dans la table `audit_log` de la base hôte (registre ou client). La classe est
append-only par construction : elle n'expose aucune méthode UPDATE ni DELETE,
une ligne écrite ne peut plus être modifiée ni supprimée par cette API. Les
valeurs avant et après sont sérialisées en JSON typé (`json.dumps`, jamais
`str()`) : un float reste un float, un dict reste un dict après relecture, et
`None` est stocké comme la chaîne JSON `null` plutôt qu'un NULL SQL.

Une entrée porte les colonnes suivantes :

| Colonne | Contenu |
|---|---|
| id | auto-incrémenté par SQLite |
| entity_type | type d'entité : `node`, `arc`, `milestone`, `node_kpis`, `spec_sheet`, `raw:<table>`... |
| entity_id | id de l'entité (pour les KPIs, l'id du nœud porteur) |
| field | champ qualifié, ex. `risk.failure_probability` ; vide si l'entité entière est concernée |
| old_value | valeur avant mutation, JSON (null à la création) |
| new_value | valeur après mutation, JSON |
| source | origine de la mutation (voir ci-dessous) |
| operator_id | opérateur à l'origine de la mutation, vide si non applicable |
| iso_week | semaine ISO de l'écriture, ex. `2026-S24` |
| timestamp | secondes epoch, fournies par l'horloge injectée du projet |

La colonne `source` prend les valeurs du contrat de l'API : `onboarding`
(complétion du wizard), `weekly` (revue hebdomadaire et confirmations de KPI),
`edit` (éditeurs de fiche, de graphe et la page Admin), `event:<id>` (impacts
d'un événement de jeu, id de l'événement inclus), `revert:<id>` (annulation d'un
événement), plus `system` et `migration` réservées par le contrat. Deux index
servent les lectures : `idx_audit_entity` sur (entity_type, entity_id, field,
timestamp) pour l'historique d'une entité, `idx_audit_week` sur iso_week pour
les vues hebdomadaires.

Les écritures respectent la transaction de l'hôte : si la connexion est déjà en
transaction, l'entrée d'audit s'y intègre sans commit et l'atomicité « mutation
métier plus trace » est garantie ; sinon elle est commitée immédiatement. Les
lots (`record_many`) passent sous un SAVEPOINT : une entrée invalide annule tout
le lot sans toucher au travail antérieur de la transaction englobante.

Deux lectures sont exposées en plus de l'écriture : `history` rejoue
l'historique d'une entité du plus récent au plus ancien (filtrable par champ,
borné à 200 entrées par défaut), et `value_at` reconstitue la valeur d'un champ
à un instant donné en retournant le `new_value` de la dernière écriture
antérieure ou égale à cet instant.

Le journal se consulte à quatre endroits. La page Admin (`/admin`) expose la
table `audit_log` de chaque base parmi les données brutes, en lecture seule (les
tables d'historique sont inéditables par construction). La fiche nœud affiche
les 50 dernières entrées qui le concernent, fusionnées entre sa base client
(entrées `node_kpis`) et le registre (entrées `node` et `arc` des arcs qui le
touchent), triées par date décroissante. La page Explication montre, dans la
carte « Versions liées », les dernières modifications des blocs KPI dominants.
Enfin l'export projet emporte le tout : feuille `audit` (bases client, une
colonne « nœud ») et feuille `audit_registre` (journal global du registre).

## 7. Générateur de données de démonstration

`RandomSupplyChainGenerator` (supplyscore/data/generator.py) construit des
chaînes d'approvisionnement plausibles pour les tests et les démonstrations.
Tout l'aléa passe par une instance `random.Random(seed)` interne, y compris les
UUID (dérivés du PRNG, pas de `uuid4` global) : à graine égale, la sortie est
identique octet pour octet, ce qui rend les scénarios de démonstration et les
bancs de performance rejouables.

La méthode `generate(n_ranks=3, breadth=(1, 3))` produit un DAG par rangs : un
client final unique au rang 0 (label « Client », porteur du projet), puis à
chaque rang de 1 à `n_ranks`, chaque nœud du rang inférieur reçoit entre un et
trois fournisseurs dédiés ; environ 20 % des fournisseurs servent en plus un
second client du rang inférieur (arcs croisés). Tous les arcs étant orientés du
rang r vers le rang r moins 1, aucun cycle n'est possible. Chaque nœud reçoit un
bundle KPI complet aux valeurs plausibles et cohérentes entre elles : l'échéance
dépasse toujours le lead time, la cible CO2 reste sous le total qui reste sous
le maximum, le débit de stock suit la demande à 15 % près. Une variante
`generate_stress(n_nodes=1000, largeur_rang=40, p_arc_croise=0.25)` fabrique les
grands DAG des bancs de performance : par défaut elle s'en tient au strict
nécessaire pour mesurer (ni jalons ni tags, qui ne pèsent pas sur la
propagation) ; avec `enrich=True` les tags sont posés sur les nœuds et des arcs
de secours ajoutés, les jalons restant à générer par l'appelant.

Les enrichissements complètent le tableau : 2 à 4 jalons successifs par nœud,
aux échéances relatives à l'origine du projet (le premier est parfois déjà
terminé, 30 % de chance) ; une taxonomie de 2 catégories (« Procédé »,
« Région ») et 4 à 6 tags, chaque nœud en recevant 1 à 3 ; environ un arc
nominal sur dix doublé d'un arc de secours (inerte dans les calculs) ; et des
questionnaires AHP simulés garantis cohérents (les comparaisons par paires sont
dérivées de poids cibles arrondis à l'échelle de Saaty, puis le CR est recalculé
et la matrice retirée tant qu'il atteint 0.10, ce qui n'arrive presque jamais).

L'API publique du générateur, telle qu'utilisée par `seed_demo` et les bancs :

| Méthode | Produit |
|---|---|
| generate(n_ranks, breadth) | un projet, ses nœuds et ses arcs (DAG par rangs) |
| generate_stress(n_nodes, largeur_rang, p_arc_croise, enrich) | un DAG large et profond pour les bancs de performance |
| generate_milestones(node_id, t0_ts) | 2 à 4 jalons successifs, échéances relatives à t0 |
| generate_tags(project_id) | 2 catégories et 4 à 6 tags rattachés |
| pick_node_tags(tag_ids) | 1 à 3 tags sans doublon pour un nœud |
| generate_backup_arcs(nodes, arcs) | environ un arc de secours pour dix arcs nominaux |
| generate_assessment(node_id, project_id, ...) | un questionnaire AHP cohérent (CR < 0.10), biaisable par `urgency_bias` |

`seed_demo` (façade `SupplyScoreService`) orchestre le tout : génération du
graphe, origine temporelle posée à maintenant, persistance du projet, des tags,
des jalons, soumission d'une évaluation AHP par nœud puis réévaluation complète
du réseau. La commande `supplyscore --demo` l'appelle avec `n_ranks=3` et
`seed=42`, uniquement si le registre ne contient encore aucun nœud : une base
peuplée n'est jamais écrasée.

**Ces données sont simulées et réservées aux tests et démonstrations : elles ne
doivent jamais alimenter de vraies décisions logistiques.** Les projets générés
portent d'ailleurs la mention « simulation » dans leur description.
