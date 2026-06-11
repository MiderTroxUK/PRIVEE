# SupplyScore

![phases](https://img.shields.io/badge/phases-E0%E2%80%93E17%20livr%C3%A9es-2c5f7c) ![jalons](https://img.shields.io/badge/jalons-1%20%C2%B7%202%20%C2%B7%203-1d7a3e) ![tests](https://img.shields.io/badge/tests-~1550-1d7a3e) ![couverture](https://img.shields.io/badge/couverture-94%25-1d7a3e)

Transforme des données supply chain en un **score d'alignement** entre le besoin déclaré et la réalité opérationnelle, sur une chaîne multi-rangs (client final rang 0 → fournisseurs profonds rang N).

- **Ud** — urgence déclarée : questionnaire humain hebdomadaire (AHP, Saaty 1977, CR < 0.10)
- **Ur** — urgence opérationnelle réelle : modélisée depuis les KPIs (temps, capacité, OEE, risque, coût, CO2), modulée par l'avancement des jalons ; poids des blocs pilotables par projet (FBWM)
- **A** — adéquation Ud/Ur : pénalité asymétrique Prospect Theory (Kahneman-Tversky), le **risque caché H** (sous-estimation) est pénalisé plus fort que la **fausse urgence F** (sur-estimation)
- **Propagation sur DAG** : le besoin déclaré descend (rang 0 → N), le risque réel remonte (rang N → 0) ; les statuts de tâche (terminée/abandonnée) propagent leur choc sur toute la chaîne

## Démarrage rapide

```powershell
# installer (une fois) — crée .venv et installe tout depuis uv.lock
$env:UV_LINK_MODE='copy'; uv sync

# lancer avec des données de démonstration (TEST uniquement, générées aléatoirement)
.venv\Scripts\python.exe run_app.py --demo

# -> http://127.0.0.1:8050
```

Options : `--db-dir` (dossier des bases SQLite ; défaut `%LOCALAPPDATA%\SupplyScore\data`, hors dossier synchronisé cloud — un `data_store/` historique est conservé avec avertissement, migrez-le avec `--migrate-data`), `--port`, `--debug`, `--log-level`, `--log-dir`.

## Serious game

SupplyScore est conçu pour animer un **serious game** sur un poste unique : un projet en mode « temps de jeu », un joueur par nœud de la chaîne (opérateurs identifiés), des tours d'une semaine simulée (« Avancer d'une semaine »). Chaque tour, chaque joueur déroule sa revue hebdomadaire en 4 volets (AHP, KPIs, jalons, événements & décision) ; l'animateur suit les scores au dashboard, puis clôture par l'export xlsx, le rapport de session (avec calibration prédiction/réalité) et une sauvegarde. Le parcours complet est documenté pas à pas dans le **[manuel utilisateur](docs/manuel_utilisateur.md)** (chapitre « Animer un serious game ») et prouvé par `tests/test_jalon1_session.py`.

## Pages de l'application

| Page | Rôle |
|---|---|
| **Projets** (`/`) | Créer/sélectionner un projet, ajouter des nœuds, statuts de tâche, horloge réel/jeu (« Avancer d'une semaine »), paramètres du calcul (u_time analytique ou Monte Carlo), export xlsx et sauvegarde |
| **Onboarding** (`/onboarding`) | Wizard 4 sections (identité, cahier des charges, KPIs, première évaluation AHP) — brouillon persisté en base et repris |
| **Hebdo** (`/hebdo`) | Revue hebdomadaire guidée d'un nœud en 4 volets : AHP pré-rempli, diff KPI, jalons, événements calibrés & décision tracée |
| **Questionnaire** (`/questionnaire`) | Mode expert : comparaisons AHP par paires, notes des 4 critères, saisie des KPIs — calcule Ud en direct avec contrôle de cohérence (CR) |
| **Dashboard** (`/dashboard`) | DAG coloré par adéquation A, badges hebdo, priorités PROMETHEE II, tableau détaillé Ud/Ur/A/F/H, évolution temporelle, lien « Expliquer » par nœud |
| **Simulation** (`/simulation`) | What-if sans persistance : choc unitaire, scénarios composites multi-chocs, criticité systématique (tornado), scénarios enregistrés |
| **Édition** (`/edition`) | Tableau éditable des KPIs courants (filtres projet/bloc/tags), validation + audit + recalcul à chaque cellule |
| **Pondération** (`/ponderation`) | Questionnaire FBWM (2n−3 comparaisons) : poids des blocs KPI d'Ur par projet et semaine, cohérence ξ*/CR en direct |
| **Graphe** (`/graphe`) | Éditeur de structure : arcs (γ/β/δ, nominal/backup), anti-cycle, taxonomie des tags, statuts |
| **Rapport** (`/rapport`) | Rapport de session HTML autonome : évolution des scores, chronologie événements/décisions, calibration prédiction/réalité |
| **Admin** (`/admin`) | Données brutes des tables SQLite — lecture seule par défaut, édition déverrouillable et auditée ; tables d'historique inéditables |
| **Fiche nœud** (`/node/<id>`) | Vue 360° rééditable par section : identité, cahier des charges versionné, jalons, KPIs, évaluations, événements, journal d'audit |
| **Explication** (`/node/<id>/explication`) | « Pourquoi ce score ? » — décomposition exacte de Ud, d'Ur (part locale vs propagée) et de l'équation d'adéquation |

## Architecture (POO)

```
supplyscore/
  domain/    modèles partagés : SupplyNode, SupplyArc, KPIBundle, Project, AHPAssessment,
             UrgencyState, Milestone, événements calibrés, cahier des charges, tags, validation
  core/      AHP -> Ud · UrModel (6 blocs KPI + OR probabiliste pondéré) -> Ur ·
             AdequationEngine -> A, F, H · horloge bimodale (réel/jeu) · explicabilité exacte
  graph/     GraphRepository (interface) · InMemoryGraphRepository (networkx) ·
             Neo4jGraphRepository (option) · PropagationEngine (complet + incrémental) · scénarios
  mcda/      FBWM (pondération floue des blocs Ur) · PROMETHEE II (classement des nœuds)
  mc/        Monte Carlo lead time (PERT stochastique propagé sur le DAG)
  data/      RegistryDatabase (graphe partagé) · ClientDatabase (une base SQLite PAR nœud) ·
             migrations versionnées (PRAGMA user_version) · audit append-only · sauvegarde/restauration
  services/  SupplyScoreService (façade) · MutationService (toute écriture auditée) · onboarding ·
             hebdo · événements · décisions · exports · calibration · rapport · criticité
  infra/     journalisation rotative · emplacements de données (platformdirs)
  tools/     restauration en ligne de commande (python -m supplyscore.tools.restore)
  web_ui/    application Dash (factory create_app, 13 pages, callbacks protégés, composants réutilisables)
run_app.py   point d'entrée
tests/       ~1550 tests (unitaires, intégration, ~120 propriétés hypothesis, benchmarks, navigateur)
```

### Modèle mathématique

1. **Ud local** : AHP 4 critères (impact opérationnel, fenêtre temporelle, dépendances aval, récupérabilité) ; Ud = (Σ wᵢ·sᵢ − 1)/8 ∈ [0,1] ; lissage EMA entre semaines (ρ = 0.3).
2. **Ur local** : u_time (probabilité de retard P(L > d−t) sur le prochain jalon actif, modulée par l'avancement déclaré vs théorique — ou Monte Carlo propagé sur le DAG, au choix du projet), u_cap, u_perf (1−OEE), u_risk (enrichi expositions env./politique), u_cost, u_co2 — agrégés par `Ur = 1 − Π(1−uₘ)^ωₘ` (ω pilotables par FBWM). Statut : terminée → 0, abandonnée → 1.
3. **Propagation** : `Ud_i = 1 − (1−Ud_loc)·Π(1−γ·Ud_client)` (descendante) ; `Ur_i = 1 − (1−Ur_loc)·Π(1−β·Ur_fournisseur)` (montante, ordre topologique).
4. **Adéquation** : A = 100·norm(exp(−λ₊·H^α − λ₋·F^α)) avec λ₊ = 2.25 > λ₋ = 1.0 (gouvernance : le danger invisible prime sur la panique).

La spécification complète (dérivations, bornes, cas de référence chiffrés, décisions de modélisation, références) : **[docs/modele_mathematique.md](docs/modele_mathematique.md)**.

## Documentation

- **[Manuel utilisateur](docs/manuel_utilisateur.md)** — démarrage, concepts, **animer un serious game** pas à pas, guide des 13 pages, FAQ.
- **[Guide d'exploitation](docs/exploitation.md)** — emplacement des données, sauvegarde/restauration, journaux, migrations de schéma, CI locale.
- **[Modèle mathématique](docs/modele_mathematique.md)** — spécification formelle des formules, vérifiée contre le code et les tests.

## Neo4j (optionnel)

Par défaut le graphe vit en mémoire (networkx) et est persisté dans SQLite. Pour brancher Neo4j :

```powershell
uv pip install -e ".[neo4j]" --python .venv\Scripts\python.exe
```

puis instancier `Neo4jGraphRepository(uri, user, password)` et le passer à `SupplyScoreService(repo=...)`.

## Tests et CI locale

```powershell
# suite rapide
.venv\Scripts\python.exe -m pytest tests -q

# pipeline complet : ruff -> mypy -> contrôle MutationService -> pytest + couverture (>= 90 % bloquant)
.\scripts\ci.ps1 [-SkipMypy] [-Benchmarks] [-Ui]
```

`-Benchmarks` exécute les bancs de performance (budgets tenus à 1 000 nœuds, rapports dans `docs/benchmarks/`) ; `-Ui` exécute les parcours navigateur réels (Chrome headless).

## Avertissement données

`RandomSupplyChainGenerator` et l'option `--demo` produisent des données **simulées, destinées aux tests et démos uniquement** — jamais à des décisions de production.
