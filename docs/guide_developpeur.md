# Guide développeur

> Vérifié contre SupplyScore v2.0.0. Source de vérité : le code de supplyscore/ et tests/.

Ce guide s'adresse à qui modifie le code de SupplyScore : mise en place du poste, carte des
packages, API de la façade, chemin d'écriture, propagation, interface Dash, tests et points
d'extension. Le modèle mathématique est documenté à part dans
[modele_mathematique.md](modele_mathematique.md), le fonctionnement côté utilisateur dans
[manuel_utilisateur.md](manuel_utilisateur.md).

## 1. Mise en place de l'environnement

Le projet exige Python 3.12 (`requires-python = ">=3.12"` dans pyproject.toml) et s'installe avec
uv depuis le lockfile :

```powershell
$env:UV_LINK_MODE = 'copy'
uv sync
```

`uv sync` crée `.venv` et installe les dépendances de production plus le groupe `dev` (pytest,
ruff, mypy, hypothesis, pre-commit) épinglées par `uv.lock`. Le mode `copy` est obligatoire sur ce
poste : le dossier du projet est synchronisé cloud et les liens physiques d'uv y échouent (os
error 396, convention consignée dans PLAN.md §1).

Aucun `python` n'est exposé dans le PATH. Toute commande Python passe soit par le lanceur Windows
(`py -3.12`), soit, de préférence, par l'exécutable du venv : `.venv\Scripts\python.exe`. La même
règle vaut pour les outils : `.venv\Scripts\ruff.exe`, `.venv\Scripts\mypy.exe`,
`.venv\Scripts\pre-commit.exe`.

Après le premier `uv sync`, installer les hooks git :

```powershell
.venv\Scripts\pre-commit.exe install
```

Les hooks sont entièrement locaux (`.pre-commit-config.yaml`, `repo: local`, `language: system`) :
`ruff check --fix` puis `ruff format`, exécutés depuis le venv, sans accès réseau.

Lancement en développement :

```powershell
.venv\Scripts\supplyscore.exe --no-backup --debug
```

`supplyscore.exe` est l'entry point déclaré dans `[project.scripts]` (équivalent :
`.venv\Scripts\python.exe -m supplyscore.cli`). `--no-backup` saute la sauvegarde automatique du
démarrage (inutile sur des bases de travail jetables, et plus rapide), `--debug` active le
rechargement à chaud de Dash. Le serveur écoute sur `http://127.0.0.1:8050` (option `--port`).
`--demo` peuple une base vide avec un projet aléatoire : données de test, jamais en production.

La CI locale (lint, format, typage, contrôle des écritures directes, tests avec couverture) se
lance avec `scripts/ci.ps1` ; ses options `-SkipMypy`, `-Benchmarks` et `-Ui` sont détaillées dans
[reference_cli.md](reference_cli.md) §7.

## 2. Carte des packages

| Package | Responsabilité | Fichiers et classes clés |
|---|---|---|
| `domain/` | Modèles métier purs, contraintes, calibration d'événements | `models.py` (SupplyNode, SupplyArc, Project, KPIBundle, UrgencyState, AHPAssessment), `constraints.py`, `events.py` (EVENT_CALIBRATION, compute_impacts), `milestones.py`, `specsheet.py`, `tags.py`, `validation.py` |
| `core/` | Calculs locaux : AHP, modèle Ur, adéquation, horloge, explicabilité | `ahp.py` (run_ahp, compute_ud), `ur_model.py` (UrModel, BLOCKS), `adequation.py` (AdequationEngine), `clock.py` (SystemClock, GameClock, FixedClock), `status_rules.py`, `explain.py` |
| `graph/` | Dépôt de graphe et propagation sur le DAG | `repository.py` (GraphRepository, 14 méthodes abstraites), `memory_repo.py` (InMemoryGraphRepository), `neo4j_repo.py`, `propagation.py` (PropagationEngine), `scenario.py` (MoteurScenario) |
| `mcda/` | Méthodes multicritères | `fbwm.py` (resoudre_fbwm, ResultatFBWM), `promethee.py` (PrometheeII, Critere, fonctions de préférence) |
| `mc/` | Monte Carlo du lead time | `lead_time.py` (SimulateurLeadTime, ResultatMC, LoiLeadTime, bornes N_TIRAGES_MIN=2000 et N_TIRAGES_MAX=50000) |
| `data/` | Persistance SQLite, audit, sauvegardes, générateur | `db.py` (RegistryDatabase, ClientDatabase), `audit.py` (AuditTrail, AuditEntry), `backup.py` (ServiceSauvegarde, restore_backup), `generator.py`, `migrations.py` |
| `services/` | Orchestration et services applicatifs | `orchestrator.py` (SupplyScoreService), `mutations.py` (MutationService), `events.py` (EventEngine), `exports.py` (ExportService), `onboarding.py`, `weekly.py`, `decisions.py`, `criticite.py`, `explain.py`, `calibration.py`, `report.py`, `raw_admin.py` |
| `infra/` | Emplacements disque et journalisation | `paths.py` (default_data_dir, legacy_data_dir, migrate_legacy_data), `logging.py` (configure_logging) |
| `tools/` | Outillage hors serveur | `restore.py` (restauration d'archive : `python -m supplyscore.tools.restore`) |
| `web_ui/` | Interface Dash | `app.py` (create_app), `errors.py` (proteger_app), `components/` (8 modules), `pages/` (13 pages) |

Le sens des dépendances va du bas vers le haut de cette table. `domain` n'importe rien du projet :
c'est le vocabulaire commun. `core` importe `domain` ; `graph` importe `domain` et
`core.status_rules` (règles de statut appliquées avant la propagation montante) ; `mc` importe
`domain` et `graph` ; `mcda` n'importe que numpy et la bibliothèque standard, ce qui rend FBWM et
PROMETHEE testables sans le reste. `data` importe `domain` et `core.clock` (semaine ISO des
horodatages). `services` assemble tout ce qui précède ; `web_ui` ne parle qu'à `services` (et à
`domain.constraints` pour les unités d'affichage). `infra/paths.py` importe `data.backup` pour
zipper avant migration. Enfin `cli.py`, à la racine du package, câble `infra`, `data.backup` et
`web_ui.app` : c'est le point d'entrée du serveur.

Un import qui remonterait ce sens (par exemple `core` important `services`) est une erreur
d'architecture : le cœur de calcul doit rester utilisable sans base de données ni interface.

## 3. La façade SupplyScoreService

`services/orchestrator.py` définit `SupplyScoreService`, la façade unique consommée par
l'interface et les scripts. Le serveur Dash sert chaque requête dans un thread distinct : les
méthodes mutantes prennent `self._lock`, un `threading.RLock` réentrant. Les bases client ouvertes
vivent dans un cache LRU borné (64 entrées par défaut, paramètre `client_cache_size`).

Construction et cycle de vie :

```python
def __init__(self, db_dir: Path | str = "data_store", repo: GraphRepository | None = None,
             ur_model: UrModel | None = None, adequation: AdequationEngine | None = None,
             rho_smoothing: float = 0.3, clock: Clock | None = None,
             client_cache_size: int = 64)
def close(self) -> None
```

Le constructeur ouvre le registre, crée le dépôt mémoire et instancie `self.mutations` (le
MutationService de la section 4). `close()` ferme le registre et toutes les bases client ; la
classe est aussi un context manager (`__enter__`/`__exit__`), utilisé dans l'exemple plus bas.

Projet et graphe :

```python
def create_project(self, project: Project, nodes: list[SupplyNode], arcs: list[SupplyArc]) -> None
def load_graph_from_registry(self) -> None
def add_node(self, node: SupplyNode, supplies_to: list[str] | None = None,
             gamma: float = 0.5, beta: float = 0.5) -> None
def remove_arc(self, source_id: str, target_id: str) -> None
def remove_node(self, node_id: str) -> None
def reassign_ranks(self) -> None
def set_status(self, node_id: str, status: TaskStatus) -> dict[str, UrgencyState]
```

`create_project` persiste tout dans le registre et alimente le dépôt mémoire ;
`load_graph_from_registry` fait l'inverse au démarrage. `add_node` relie le nouveau nœud à ses
clients aval puis recale les rangs canoniques (plus longue distance vers un puits). `remove_node`
archive la base SQLite du nœud sans la supprimer (historique conservé pour audit). `set_status`
cascade le statut sur les jalons actifs puis réévalue une seule fois le réseau.

Horloge bimodale par projet :

```python
def clock_for(self, project_id: str) -> Clock
def clock_mode(self, project_id: str) -> str
def set_clock_mode(self, project_id: str, mode: str) -> None
def advance_week(self, project_id: str, n: int = 1) -> dict[str, UrgencyState]
```

Chaque projet est en temps réel (`"real"`, défaut) ou en temps de jeu (`"game"`, serious game) ;
`advance_week` n'est valide qu'en mode jeu et réévalue tout le réseau après avoir avancé la
`GameClock`.

Évaluations et pipeline :

```python
@staticmethod
def build_assessment(node_id: str, project_id: str, operator_id: str,
                     comparisons: dict[tuple[int, int], float],
                     criteria_scores: list[float], notes: str = "") -> AHPAssessment
def submit_assessment(self, assessment: AHPAssessment) -> int
def refresh_ur_local(self, t: float | None = None) -> None
def evaluate_all(self, t: float | None = None, persist: bool = False,
                 incremental: bool = True) -> dict[str, UrgencyState]
```

`build_assessment` exécute l'AHP (`run_ahp`, `compute_ud`) sur les réponses brutes du
questionnaire ; `submit_assessment` refuse toute évaluation dont le ratio de cohérence atteint le
seuil de Saaty (0.10), enregistre dans la base client et lisse le `ud_local` du nœud (EMA,
coefficient `rho_smoothing`). `evaluate_all` est le pipeline complet : Ur locaux, propagation
(incrémentale par défaut quand `t` est None), adéquation, et persistance des états si
`persist=True`. `refresh_ur_local` est son premier étage, exposé séparément.

FBWM et PROMETHEE :

```python
def set_poids_criteres(self, project_id: str, poids: dict[str, float], methode: str = "fbwm",
                       xi_star: float | None = None, iso_week_val: str | None = None) -> None
def poids_criteres(self, project_id: str) -> dict[str, float] | None
def classement_promethee(self, project_id: str) -> ResultatPromethee
```

Les poids des blocs d'Ur (sortie FBWM ou saisie directe) sont stockés par projet et fusionnés dans
l'`omega` du UrModel effectif ; `classement_promethee` classe les nœuds actifs du projet sur les
six blocs (au moins 2 nœuds actifs requis, ValueError sinon).

Monte Carlo du lead time :

```python
def set_lead_time_mode(self, project_id: str, mode: str, n_tirages: int = 10_000,
                       graine: int | None = None) -> None
def lead_time_mode(self, project_id: str) -> dict[str, Any]
def last_mc_result(self, project_id: str) -> ResultatMC | None
```

`mode` vaut `"analytique"` ou `"monte_carlo"` ; `n_tirages` est validé à l'écriture contre les
bornes du simulateur. Sans graine explicite, une graine stable est dérivée de (project_id, semaine
ISO) : deux rafraîchissements de la même semaine donnent des résultats identiques bit à bit.

Simulation :

```python
def simulate_shock(self, node_id: str, new_ur_local: float) -> dict[str, float]
```

Le what-if délègue au moteur de propagation et reste analytique même pour un projet en mode Monte
Carlo (réponse instantanée dans l'UI). Rien n'est persisté.

Accès bases client :

```python
def client_db(self, node_id: str) -> ClientDatabase
```

Retourne (en l'ouvrant au besoin) la base SQLite privée du nœud, sous cache LRU.

Démo :

```python
def seed_demo(self, n_ranks: int = 3, seed: int = 42) -> Project
```

Génère un projet aléatoire complet (nœuds, arcs nominaux et de secours, jalons, tags,
questionnaires). **Données de test uniquement, jamais en production.**

Le script suivant est exécutable tel quel (`.venv\Scripts\python.exe exemple.py` depuis un dossier
de travail) ; il reprend les signatures éprouvées par `tests/test_jalon1_session.py` :

```python
"""Session SupplyScore minimale, sans interface : projet, KPIs, AHP, scores, export."""

from pathlib import Path

from supplyscore.domain.models import Project, SupplyArc, SupplyNode
from supplyscore.services import SupplyScoreService
from supplyscore.services.exports import ExportService

with SupplyScoreService(db_dir=Path("demo_store")) as service:
    # 1. Un client final (rang 0) alimenté par un atelier (rang 1).
    project = Project(id="p1", name="Ligne pilote", owner_node_id="client")
    client = SupplyNode(id="client", name="Client final", rank=0, project_id="p1")
    atelier = SupplyNode(id="fab", name="Atelier usinage", rank=1, project_id="p1")
    arc = SupplyArc(source_id="fab", target_id="client", gamma=0.6, beta=0.7)
    service.create_project(project, [client, atelier], [arc])

    # 2. KPIs : toute écriture métier passe par MutationService.
    entries = service.mutations.update_kpis(
        "fab",
        {"time.lead_time_h": 120.0, "time.lead_time_std_h": 24.0, "oee.availability": 0.92},
        source="edit",
        operator_id="dev",
    )
    print(f"{len(entries)} entrées d'audit créées")

    # 3. Questionnaire AHP : 4 critères, 6 comparaisons de Saaty parfaitement
    #    transitives (CR = 0, sinon submit_assessment refuse au-delà de 0.10).
    assessment = SupplyScoreService.build_assessment(
        node_id="fab",
        project_id="p1",
        operator_id="dev",
        comparisons={(0, 1): 2.0, (0, 2): 4.0, (0, 3): 8.0,
                     (1, 2): 2.0, (1, 3): 4.0, (2, 3): 2.0},
        criteria_scores=[8.0, 6.0, 4.0, 3.0],
    )
    service.submit_assessment(assessment)

    # 4. Pipeline complet, avec persistance registre + bases client.
    states = service.evaluate_all(persist=True)
    for node_id, state in sorted(states.items()):
        print(f"{node_id}: Ud={state.ud:.3f} Ur={state.ur:.3f} A={state.adequation:.1f}")

    # 5. Export xlsx multi-feuilles.
    chemin = ExportService(service).export_project("p1", fmt="xlsx", dest_dir="exports")
    print(f"Export : {chemin}")
```

Sortie observée : 3 entrées d'audit, `fab: Ud=0.700 Ur=0.000 A=42.1` (urgence déclarée sans
réalité opérationnelle, donc fausse urgence et adéquation dégradée) et un fichier
`exports\SupplyScore_Ligne-pilote_<horodatage>.xlsx` dont les feuilles incluent `projet`,
`noeuds`, `arcs`, `jalons`, `evaluations` et `audit_registre`.

## 4. Le chemin d'écriture : MutationService

`services/mutations.py` définit l'invariant central du projet : toute écriture métier passe par
`MutationService`. L'orchestrateur construit l'instance dans son constructeur et l'expose en
`service.mutations`. L'invariant est contrôlé mécaniquement par `scripts/ci.ps1`, étape « contrôle
des écritures directes (MutationService) » (entre mypy et pytest) : les motifs `.save_node(` et
`.save_arc(` sont interdits dans `supplyscore\web_ui\` et `run_app.py`, et une occurrence fait
échouer la CI. Le périmètre est volontairement limité : `orchestrator.py` garde le droit d'écrire
directement pour ses besoins internes (rangs, urgences).

Chaque mutation suit le même chemin. La validation est bloquante : si une seule valeur est
invalide, rien n'est écrit et le `ValueError` levé liste toutes les erreurs en français (le
message commence par « Mise à jour des KPIs refusée » et précise qu'aucune écriture n'a été
effectuée). Le diff est calculé champ à champ : une valeur identique à l'existante n'est ni écrite
ni journalisée, et un appel sans changement effectif est un no-op complet qui retourne `[]`. Les
lignes d'audit sont insérées dans la même transaction que l'écriture métier, avant elle, via le
context manager interne `_transaction` : le commit final emporte le tout, il ne peut pas exister
d'écriture commitée sans sa trace. Exception documentée dans le code : `replace_assessment`, où
l'id audité n'existe qu'après l'INSERT. Pour les KPIs, deux bases sont touchées : audit plus
snapshot atomiques dans la base client du nœud, puis upsert du nœud dans le registre (deux
fichiers SQLite ne partagent pas de transaction). Si un dépôt de graphe est fourni, le nœud ou
l'arc en mémoire est synchronisé après chaque écriture réussie.

Les huit méthodes publiques :

```python
def update_kpis(self, node_id: str, changes: dict[str, float | None], source: str,
                operator_id: str = "") -> list[AuditEntry]
def update_node_fields(self, node_id: str, changes: dict[str, Any], source: str,
                       operator_id: str = "") -> list[AuditEntry]
def upsert_arc(self, arc: SupplyArc, source: str, operator_id: str = "") -> list[AuditEntry]
def delete_arc(self, source_id: str, target_id: str, source: str,
               operator_id: str = "") -> list[AuditEntry]
def set_node_tags(self, node_id: str, tag_ids: list[str], source: str,
                  operator_id: str = "") -> list[AuditEntry]
def update_milestone(self, milestone_id: str, changes: dict[str, Any], source: str,
                     operator_id: str = "") -> list[AuditEntry]
def save_spec_sheet(self, node_id: str, payload_json: str, source: str,
                    operator_id: str = "") -> int
def replace_assessment(self, node_id: str, old_id: int, new: AHPAssessment,
                       operator_id: str = "") -> int
```

`update_kpis` valide chaque chemin `"bloc.champ"` avec `domain.constraints.validate_kpi_value` ;
`update_node_fields` et `update_milestone` n'acceptent que les champs des listes blanches
`_NODE_FIELDS` (6 champs) et `_MILESTONE_FIELDS` (7 champs) déclarées en tête de module ;
`upsert_arc` borne `gamma` et `beta` sur [0, 1] et `delta` sur [0, 2] ; `save_spec_sheet`
versionne le cahier des charges (version auto-incrémentée par nœud) ; `replace_assessment` insère
une évaluation corrective sans effacer l'originale de l'historique.

Pour ajouter une mutation : écrire une méthode publique sur `MutationService` qui prend
`self._lock`, valide en listant toutes les erreurs dans un seul message français, calcule le diff
avant toute écriture, journalise via `self._record(...)` à l'intérieur d'un bloc `with
self._transaction(base):`, synchronise le dépôt mémoire si pertinent, et retourne les `AuditEntry`
créées (liste vide si no-op). Ajouter les cas dans `tests/test_mutations.py` : changement
effectif, no-op, validation refusée sans écriture, contenu des lignes d'audit.

## 5. Propagation sur le DAG

`graph/propagation.py` définit `PropagationEngine`, construit sur un `GraphRepository`. Le moteur
lit les urgences locales (`ud_local`, `ur_local`) posées par l'orchestrateur et calcule les
urgences propagées (`ud`, `ur`). Les formules exactes (produit d'atténuation par `gamma` côté Ud,
par `beta` côté Ur, règles de statut, clipage [0, 1]) sont dérivées dans
[modele_mathematique.md](modele_mathematique.md) §4 et ne sont pas répétées ici.

`propagate_all() -> dict[str, UrgencyState]` enchaîne `propagate_descending()` puis
`propagate_ascending()`. Le Ud se calcule en ordre topologique inverse (clients d'abord, du rang 0
vers le rang N) ; le Ur en ordre topologique direct (fournisseurs profonds d'abord, du rang N vers
le rang 0). Les valeurs sont persistées dans le dépôt et l'état incrémental est réinitialisé.

La propagation incrémentale (phase E14.4) tient deux ensembles sales alimentés par l'orchestrateur
: `mark_dirty_ud(node_id)` quand un questionnaire change le `ud_local` (appelé par
`submit_assessment`), `mark_dirty_ur(node_id)` quand le `ur_local` recalculé diffère de la valeur
précédente (comparaison faite dans `refresh_ur_local`), et `invalidate()` sur toute mutation de
structure (tout redevient sale). `propagate_incremental()` ne recalcule que les cônes affectés :
ancêtres des nœuds sales côté Ud, descendants côté Ur ; les nœuds frontières lisent les valeurs en
cache de leurs voisins non affectés. Trois situations délèguent au calcul complet : tout est sale,
un nœud hors zone n'a jamais été propagé (cache absent), ou la version de structure du dépôt a
changé depuis la dernière propagation complète.

Ce dernier filet s'appuie sur `graph/memory_repo.py` : `InMemoryGraphRepository` expose un
compteur monotone `structure_version`, incrémenté à chaque mutation de nœud ou d'arc, qui détecte
les mutations de structure passées hors orchestrateur (par exemple
`MutationService._sync_repo_arc`, qui remplace un arc pour changer son `beta`). Le dépôt mémoire
est adossé à un `networkx.DiGraph` qui ne porte que les arcs nominaux : les arcs de secours
(`ArcKind.BACKUP`), purement documentaires, sont stockés à part et n'influencent ni le tri
topologique, ni les voisinages, ni les rangs. L'ordre topologique est mis en cache et invalidé par
toute mutation de structure ; `assign_ranks()` recalcule le rang canonique (plus longue distance
vers un puits).

`simulate_shock(node_id, new_ur_local) -> dict[str, float]` calcule deux passes pures de Ur, l'une
de référence, l'autre avec le `ur_local` choqué injecté en override, et retourne les deltas par
nœud. Aucune écriture : ni le choc, ni les Ur recalculés ne touchent le dépôt. Les services de
simulation avancée (scénarios composites de `graph/scenario.py`, criticité systématique de
`services/criticite.py`) sont bâtis sur cette primitive et sur des vues du dépôt, en lecture seule
également.

## 6. L'interface Dash

`web_ui/app.py` expose `create_app(db_dir: str = "data_store", service: SupplyScoreService | None
= None) -> dash.Dash`. Aucune instance ne se construit à l'import : la factory instancie (ou
réutilise) le service, recharge le graphe depuis le registre, le partage via `set_service` (module
`web_ui/__init__.py`, récupéré partout par `get_service()`), pose le layout global (navbar,
`dcc.Location`, deux `dcc.Store` de session pour le projet et l'opérateur courants) puis
enregistre les callbacks. Le routage est un callback unique, `route_callback(pathname)` : un
dictionnaire de 11 routes statiques (`/`, `/questionnaire`, `/dashboard`, `/simulation`,
`/onboarding`, `/hebdo`, `/edition`, `/graphe`, `/admin`, `/rapport`, `/ponderation`) plus deux
routes paramétrées, `/node/<id>` (fiche nœud) et `/node/<id>/explication`. Un chemin inconnu rend
un message 404 en français.

Chaque page de `web_ui/pages/` suit le même contrat, documenté dans `pages/__init__.py` : une
fonction `layout()` qui construit l'arbre de composants en relisant l'état du service à chaque
navigation (jamais une constante de module), et une fonction `register_callbacks(app)` appelée une
fois par `create_app`. Les callbacks sont des fonctions nommées au niveau module, donc testables
par appel direct sans serveur Dash.

`web_ui/errors.py` fournit le garde-fou d'erreurs : `proteger_app(app)`, appelé dans `create_app`
avant tout enregistrement (routeur compris), remplace `app.callback` par une version qui compte
les `Output` au point d'enregistrement et enveloppe chaque fonction avec `protege_callback`. Toute
exception d'un callback (sauf `PreventUpdate`, flux normal) est journalisée avec sa trace dans
`logs/supplyscore.log` et remplacée par un bandeau d'erreur en français ; seul le type de
l'exception est montré, jamais le message brut. Les valeurs de repli sont dimensionnées au nombre
d'Outputs : le premier Output de propriété `children` reçoit le bandeau, tous les autres reçoivent
`dash.no_update` (une figure qui recevrait un `html.Div` casserait le rendu).

`web_ui/components/` regroupe les briques partagées : `layout.py` (palette `COLORS`, `navbar`,
`card`, `labelled`, styles de page), `operator.py` (sélecteur d'opérateur global et son store),
`badges.py` (badges de statut hebdo), `figures.py` (figures Plotly du dashboard), `event_forms.py`
(formulaires générés depuis `EVENT_CALIBRATION`), `forms_node.py`, `history.py` et
`explain_figures.py`.

Ajouter une quatorzième page (exemple : une page « Capacité » sur `/capacite`) touche exactement
ces fichiers :

1. Créer `supplyscore/web_ui/pages/capacite.py` avec `layout() -> html.Div` (qui relit le service
   via `get_service()`) et `register_callbacks(app)` enregistrant des callbacks nommés au niveau
   module. S'inspirer de `editor.py`, la plus petite page complète.
2. Dans `supplyscore/web_ui/app.py` : ajouter `capacite` à l'import groupé `from
   supplyscore.web_ui.pages import (...)`, ajouter `"/capacite": capacite.layout` au dictionnaire
   `routes` de `route_callback`, et ajouter `capacite` au tuple parcouru par la boucle `for page
   in (...)` de `create_app`.
3. Dans `supplyscore/web_ui/components/layout.py` : ajouter `dcc.Link("Capacité",
   href="/capacite", style=link_style)` à la liste `children` de `navbar`.
4. Créer `tests/test_webui_capacite.py` sur le modèle de `tests/test_webui_editor.py` : appeler
   `layout()` et les callbacks directement sur un service seedé partagé via `set_service` (libéré
   en teardown), et vérifier le routage avec `route_callback("/capacite")`.

`pages/__init__.py` n'a pas besoin d'être modifié : `app.py` importe les modules de pages
directement, le `__all__` historique ne liste que les quatre pages d'origine. La protection
d'erreurs est automatique (aucun décorateur à poser), puisque `proteger_app` est appliqué avant
l'enregistrement. Pour le futur paquet PyInstaller, la nouvelle page devra être déclarée en
`hiddenimports` (voir section 11).

## 7. Flux d'une action de bout en bout

Trace complète d'une édition de KPI dans la page Édition (`/edition`), du clic à l'écran rafraîchi :

1. L'utilisateur modifie une cellule du `DataTable`. Dash déclenche `edit_cell_callback`
   (`web_ui/pages/editor.py`), enregistré sur `Input("kpi-edit-table", "data_timestamp")` avec
   `data` et `data_previous` en `State`. Le callback repère la cellule changée en comparant chaque
   ligne à la ligne de même `id` dans `data_previous` : le diff se fait par row id stable (le
   `node_id`), jamais par index de ligne, et le tri natif de la table est désactivé
   (`sort_action="none"`) pour garder les deux instantanés alignés.
2. Le callback appelle `service.mutations.update_kpis(node_id, {path: value}, source="edit",
   operator_id=...)` (`services/mutations.py`). La valeur est validée par `validate_kpi_value`
   (`domain/constraints.py`, message en français si hors bornes) ; le diff écarte les valeurs
   identiques ; puis, dans une même transaction sur la base client du nœud, une ligne d'audit par
   champ changé (`data/audit.py`) et un snapshot KPI (`ClientDatabase.save_kpi_snapshot`,
   `data/db.py`) sont écrits, suivis de l'upsert du nœud dans le registre et de la synchronisation
   du nœud en mémoire dans le dépôt de graphe.
3. Sur succès avec changement effectif, le callback appelle `service.evaluate_all(persist=True)`
   (`services/orchestrator.py`). `refresh_ur_local` recalcule le `ur_local` du nœud depuis ses
   KPIs frais et, la valeur ayant changé, appelle `propagation.mark_dirty_ur(node_id)`.
4. `evaluate_all` passe par `PropagationEngine.propagate_incremental()` (`graph/propagation.py`) :
   seuls le nœud édité et son cône aval (côté Ur) sont recalculés, les autres valeurs sont relues
   du cache. L'`AdequationEngine` (`core/adequation.py`) recalcule ensuite A, F et H pour chaque
   état retourné.
5. Avec `persist=True`, les états sont persistés par lots : un `executemany` UPSERT dans le
   registre (`RegistryDatabase.save_urgencies`) et une journalisation dans la base client de
   chaque nœud (`ClientDatabase.save_urgency_states`).
6. Retour à l'interface : sur succès la table n'est pas réécrite (`no_update`, anti-scintillement)
   et le message vert indique le nombre d'entrées d'audit ; sur rejet (`ValueError` de validation,
   nœud inconnu, valeur non numérique) la table est rechargée depuis la base, ce qui restaure la
   cellule fautive, avec un message d'erreur. Un no-op (valeur identique à la base) affiche un
   message neutre sans écriture ni recalcul.

Le même squelette (callback, mutation auditée, `evaluate_all`, retour) se retrouve dans toutes les
pages d'écriture : hebdo, graphe, fiche nœud, onboarding.

## 8. Les tests

La suite collecte 1 614 tests (`pytest --collect-only -q`). Elle s'organise en
quatre étages :

| Emplacement | Contenu | Activation |
|---|---|---|
| `tests/*.py` (80 fichiers) | Unitaires et intégration, dont les critères de sortie de jalon (`test_jalon1_session.py`, `test_milestones.py`) | Toujours |
| `tests/property/` (11 fichiers) | Tests de propriétés Hypothesis (propagation, AHP, FBWM, PROMETHEE, Monte Carlo...) | Toujours ; profil `dev` 50 exemples par défaut, `ci` 300 exemples via `HYPOTHESIS_PROFILE=ci` (profils déclarés dans `tests/conftest.py`) |
| `tests/benchmarks/` (4 fichiers) | Bancs pytest-benchmark avec budgets de performance exprimés à 1 000 nœuds | Sautés sauf si `SUPPLYSCORE_BENCH=1` (posé par `ci.ps1 -Benchmarks`, rapports archivés dans `docs/benchmarks`) |
| `tests/ui/` | Parcours navigateur Selenium (Chrome headless via `dash[testing]`) | Sautés sauf si `SUPPLYSCORE_UI=1` (posé par `ci.ps1 -Ui`) ; skip gracieux si Chrome ou chromedriver manquent |

Commandes usuelles :

```powershell
# suite rapide complète (couverture incluse via ci.ps1, ou directement :)
.venv\Scripts\python.exe -m pytest tests -q

# un fichier, ou un filtre par nom
.venv\Scripts\python.exe -m pytest tests/test_mutations.py -q
.venv\Scripts\python.exe -m pytest tests -q -k "update_kpis"

# propriétés en profil exhaustif
$env:HYPOTHESIS_PROFILE = 'ci'; .venv\Scripts\python.exe -m pytest tests/property -q

# bancs de performance
$env:SUPPLYSCORE_BENCH = '1'
.venv\Scripts\python.exe -m pytest tests/benchmarks -q --benchmark-only

# tests navigateur
$env:SUPPLYSCORE_UI = '1'; .venv\Scripts\python.exe -m pytest tests/ui -q -m ui

# compter ce qui serait exécuté
.venv\Scripts\python.exe -m pytest --collect-only -q
```

`tests/conftest.py` fournit deux fixtures partagées : `tmp_store` (un répertoire de stockage
temporaire créé sous `tmp_path`) et `service_demo` (un `SupplyScoreService` seedé avec
`seed_demo(n_ranks=2, seed=1)`, reproductible). Les fixtures locales des modules existants gardent
la priorité sur ces noms. Les conftest des sous-dossiers enregistrent leurs marqueurs localement
(`benchmark_suite`, `ui`) : aucun réglage pytest global n'est nécessaire, la suite rapide saute
ces fichiers à la collecte. Les bases des bancs vivent sous `%TEMP%` (`tmp_path_factory`), jamais
dans le dossier du projet.

## 9. Conventions de code

Tout est piloté par `pyproject.toml`. Le typage mypy est strict sur le cœur et permissif sur
l'interface : l'override `[[tool.mypy.overrides]]` sur `supplyscore.domain.*`,
`supplyscore.core.*`, `supplyscore.graph.*`, `supplyscore.data.*` et `supplyscore.services.*`
impose `disallow_untyped_defs = true` et `disallow_incomplete_defs = true`, tandis que l'override
`supplyscore.web_ui.*` pose `disallow_untyped_defs = false` (les erreurs y restent vérifiées :
`ignore_errors = false`). Un troisième override déclare `ignore_missing_imports` pour `dash.*`,
`plotly.*`, `networkx.*` et `neo4j.*`, dépourvus de stubs.

Ruff applique `line-length = 100`, cible py312, et la sélection `E, F, W, I, N, B, UP, SIM, RUF,
D`. Les docstrings suivent la convention Google (`[tool.ruff.lint.pydocstyle] convention =
"google"`) et sont rédigées en français, comme l'UI et les messages d'erreur ; les caractères
typographiques français et mathématiques (« × », « → », lettres grecques...) sont déclarés dans
`allowed-confusables` pour ne pas déclencher les règles RUF de confusables. Les tests sont
exemptés des règles de docstrings (`per-file-ignores` sur `tests/**`). La couverture est bloquante
sous 90 % (`[tool.coverage.report] fail_under = 90`), `neo4j_repo.py` étant exclu de la mesure
(dépendance optionnelle).

Les hooks pre-commit sont 100 % locaux (voir section 1) : `ruff check --fix` puis `ruff format`
sur les fichiers indexés. La CI complète reste `scripts/ci.ps1`, qui ajoute mypy, le contrôle des
écritures directes et pytest avec couverture.

Deux fichiers de pilotage vivent à la racine. `CHANGELOG.md` suit le format Keep a Changelog et le
versionnage sémantique, la version du paquet étant alignée sur les jalons (v2.0.0 marque la fin du
Jalon 3) : toute évolution notable y est consignée. `PLAN.md` est la feuille de route d'origine :
conventions transverses (un fichier appartient à un seul lot par phase, API contractuelles figées
avant les lots parallèles), Definition of Done de chaque phase et découpage E0 à E17 ; il
documente le pourquoi des choix que ce guide décrit.

## 10. Points d'extension

Implémenter un GraphRepository : l'interface est `graph/repository.py` (classe abstraite
`GraphRepository`, 14 méthodes : nœuds, arcs, voisinages avec filtre `kinds`, `nodes_by_project`,
`topological_order`, `clear`). L'exemple complet est `graph/neo4j_repo.py`
(`Neo4jGraphRepository`), avec import paresseux du driver (extra `supplyscore[neo4j]`) et
sérialisation JSON des KPIs. Fichiers à modifier : le nouveau module sous `supplyscore/graph/`,
l'export dans `graph/__init__.py`, et rien d'autre ; `PropagationEngine` et l'orchestrateur
fonctionnent sur le contrat abstrait (ils n'utilisent les chemins rapides
`descendants`/`ancestors`/`structure_version` que si le dépôt est un `InMemoryGraphRepository`,
avec replis génériques sinon ; sans `structure_version`, les invalidations reposent sur les appels
explicites de l'orchestrateur). Tests à ajouter : un fichier sur le modèle de
`tests/test_graph_repo.py` exerçant le contrat complet (anticycle, arcs de secours inertes, ordre
topologique), plus un passage de `tests/test_graph_propagation.py` sur le nouveau dépôt.

Ajouter un bloc KPI d'Ur : déclarer le dataclass de KPIs et son champ dans `KPIBundle`
(`domain/models.py`), poser les bornes des nouveaux chemins dans `KPI_CONSTRAINTS`
(`domain/constraints.py`), puis dans `core/ur_model.py` ajouter le nom au tuple `BLOCKS`, écrire
la méthode `u_<bloc>(kpis) -> float | None` et brancher le résultat dans le dictionnaire retourné
par `UrModel.blocks` ; le poids par défaut dans `omega` suit automatiquement (`{name: 1.0 for name
in BLOCKS}`). Le bloc devient alors visible du FBWM, de PROMETHEE et de l'OU probabiliste sans
autre code. Côté UI, ajouter les champs à `KPI_FIELDS` (`web_ui/pages/questionnaire.py`), consommé
aussi par la page Édition. Tests : `tests/test_core_ur.py` (cas None, bornes, monotonie) et
`tests/property/test_prop_ur_model.py`.

Ajouter un événement calibré : dans `domain/events.py`, déclarer l'`EventSpec` (champs
`EventField` avec bornes et unités) dans `EVENT_CALIBRATION`, écrire le handler
`_mon_evenement(params, kpis) -> list[KpiImpact]` à partir des opérateurs existants
(`bayes_update`, `ema_update`, cliquet) et l'enregistrer dans le dictionnaire `_HANDLERS` consommé
par `compute_impacts`. Aucun code d'interface : le formulaire du volet Événements est généré
déclarativement depuis `EVENT_CALIBRATION` par `web_ui/components/event_forms.py`, et
`EventEngine` (`services/events.py`) applique les impacts via `mutations.update_kpis`. Tests :
`tests/test_events_calibration.py` (impacts attendus, bornes des paramètres),
`tests/test_event_forms.py` (rendu du formulaire) et `tests/property/test_prop_events.py` (les
valeurs produites restent dans les bornes de `clamp_kpi_value`).

Ajouter une feuille d'export : dans `services/exports.py`, une feuille est un `_Sheet = tuple[str,
list[str], list[list[Any]]]` (nom, en-têtes, lignes). Écrire une méthode `_sheet_<nom>` ou
`_rows_<nom>` (selon que la feuille est globale ou par base client) et l'insérer dans
`_build_sheets`, qui fixe l'ordre du classeur ; les écritures xlsx et csv-zip (`_write_xlsx`,
`_write_csv_zip`) sont communes à toutes les feuilles. Tests : `tests/test_exports.py` (présence
de la feuille, en-têtes, contenu sur un projet seedé, dans les deux formats).

## 11. Pièges connus

Notes PyInstaller : la docstring de `supplyscore/cli.py` documente les pièges du futur paquet
one-folder, rien n'est codé. Dash et Plotly embarquent des ressources non-Python invisibles à
l'analyse statique : construire avec `--collect-data dash --collect-data plotly`, sous peine de
page blanche au premier rendu. Les pages Dash étant importées dynamiquement par le routeur, chaque
module de `supplyscore/web_ui/pages/` doit être déclaré en `--hidden-import`. Le point d'entrée du
binaire reste `supplyscore.cli:main`.

`UV_LINK_MODE=copy` sur dossiers synchronisés : sans cette variable, uv installe par liens
physiques, qui échouent sur un dossier OneDrive/Dropbox (os error 396). Le symptôme est un `uv
sync` qui casse à mi-installation. `scripts/Installer.ps1` pose la variable lui-même ; en ligne de
commande, la poser avant chaque `uv sync`.

Données hors dossier cloud : des bases SQLite en mode WAL dans un dossier synchronisé risquent la
corruption, le client de synchronisation pouvant copier les fichiers `.sqlite`, `-wal` et `-shm` à
des instants incohérents (`infra/paths.py`). L'emplacement par défaut est donc
`%LOCALAPPDATA%\SupplyScore\data` ; un `data_store/` hérité dans le dossier du projet est conservé
avec un avertissement loggé, et `--migrate-data` le déplace après sauvegarde zip. **Ne jamais
pointer `--db-dir` vers un dossier synchronisé pour des données réelles : c'est un risque de perte
de données.** Les tests et bancs suivent la même règle en stockant sous `%TEMP%`.

SQLite entre threads : les connexions sont ouvertes avec `check_same_thread=False` (`data/db.py`),
car le serveur Dash sert chaque requête dans un thread distinct. La sécurité repose sur des
verrous explicites : chaque base expose son `threading.RLock` réentrant via la propriété `lock`,
`AuditTrail` partage le verrou de sa base hôte, `MutationService._transaction` prend `db.lock`
autour du couple BEGIN/commit, et les méthodes mutantes de `SupplyScoreService` et
`MutationService` prennent leur RLock d'instance. Tout nouveau code qui touche une connexion doit
tenir le verrou de la base correspondante pendant toute la séquence lecture-écriture ; un accès
non verrouillé fonctionne en apparence puis produit des `sqlite3.ProgrammingError` ou des pertes
de mise à jour sous charge.
