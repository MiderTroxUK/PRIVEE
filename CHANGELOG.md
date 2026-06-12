# Changelog

Toutes les évolutions notables de SupplyScore sont consignées dans ce fichier.

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le
projet adhère au [versionnage sémantique](https://semver.org/lang/fr/) — la
version du paquet suit les jalons du PLAN (v2.0.0 = fin du Jalon 3).

## [Non publié]

### Documentation

- Réécriture du README : badges figés sur la v2.0.0, démarrage rapide via
  `scripts/Installer.ps1`, table des 13 pages avec leurs routes, table
  d'orientation des documents par public.
- Création de `docs/reference_cli.md` (points d'entrée exécutables),
  `docs/reference_donnees.md` (exports, schéma SQLite, audit),
  `docs/guide_developpeur.md` (architecture et points d'extension) et
  `docs/README.md` (index de la documentation).
- Manuel utilisateur illustré page par page et guide d'exploitation retouchés.
- Nouveau test de cohérence documentation/code (`tests/test_docs_coherence.py`) :
  options CLI, feuilles d'export, versions de schéma, nombre de pages, liens
  relatifs, version du paquet.

## [2.0.0] — 2026-06-11

Refonte complète en trois jalons (phases E0 à E17 du PLAN).

### Ajouté

#### Jalon 1 — « Prêt pour le serious game » (E0-E7)

- Wizard d'onboarding en 4 sections (identité/connexions, cahier des charges,
  KPIs guidés, première évaluation AHP) avec brouillons persistés en base et
  fiche nœud 360° rééditable par section.
- Cycle hebdomadaire ISO en 4 volets (AHP, KPIs, jalons, événements) avec
  statuts dérivés, badges et suivi de semaine par projet.
- Moteur d'événements calibrés : impacts prévisualisés, appliqués de façon
  réversible et tracés dans l'audit ; journal des décisions pour l'analyse
  post-jeu.
- Horloge bimodale par projet (temps réel / mode « jeu » avec avancement
  semaine par semaine).
- Versionnage et audit universels de toute écriture métier (MutationService).
- Exports complets (Excel/CSV) et sauvegarde manuelle sûre des bases SQLite
  (copies cohérentes via l'API native, zip horodaté, restauration outillée).

#### Jalon 2 — « Analyse & défendabilité » (E8-E13)

- Explicabilité de bout en bout : décomposition de chaque score Ud/Ur/A
  (contributions, chemins de propagation, figures dédiées).
- Preuves par propriétés (Hypothesis) sur l'adéquation, les événements et les
  jalons ; seuil de couverture bloquant >= 90 %.
- Édition libre mais sûre des données (graphe, nœuds, arcs) et administration
  des données brutes avec garde-fous.
- Calibration prédiction/réalité et rapport de session imprimable.
- Méthodes avancées : pondération FBWM des blocs KPI, surclassement
  PROMETHEE, simulation Monte Carlo des dates d'achèvement propagées sur le
  DAG (PERT stochastique, en option par projet).

#### Jalon 3 — « Industrialisation » (E14-E17)

- Tenue à l'échelle 1 000+ nœuds avec budgets de performance mesurés
  (bancs pytest-benchmark archivés).
- Scénarios composites : multi-chocs et analyse de criticité.
- Garde-fous UI systématiques (aucune exception brute à l'écran) et 8
  parcours navigateur automatisés (Chrome headless).
- Packaging local : commande `supplyscore` (entry point `supplyscore.cli`),
  lanceur 1-clic `scripts/SupplyScore.bat` (+ `.ps1`) qui ouvre le
  navigateur, installateur idempotent `scripts/Installer.ps1` (uv).
- Données et journaux hors dossier synchronisé cloud
  (`%LOCALAPPDATA%\SupplyScore`) avec assistant de migration
  (`--migrate-data`).
- Sauvegarde automatique au démarrage avec rétention (24 h / 20 archives) ;
  une base corrompue bloque le lancement (code de sortie 2).

### Modifié

- `run_app.py` devient un mince wrapper rétro-compatible de
  `supplyscore.cli` (mêmes options, réexport de `resolve_db_dir`).

## [1.0.0] — 2026-06-10

- Version 1 historique (état initial du dépôt, 144 tests verts) :
  calculateur d'adéquation Ud/Ur, graphe multi-rangs, UI web Dash
  (projets, questionnaire, dashboard, simulation), stockage SQLite.
