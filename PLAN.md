# PLAN.md — Feuille de route de production SupplyScore v2

> **But du système** : transformer des données supply chain en un score d'alignement entre le besoin déclaré (Ud, questionnaire humain) et la réalité opérationnelle (Ur, KPIs), propagé sur un DAG multi-rangs (client final rang 0 → fournisseurs rang N), pour détecter les fausses urgences (F), repérer les risques cachés (H) et visualiser l'impact sur le graphe des fournisseurs.
>
> **Banc d'essai final** : un serious game réel — plusieurs joueurs sur un même poste, chacun incarnant un nœud de la chaîne, jouant des semaines simulées ; le scoring et son impact sur les décisions seront mesurés sur ce jeu de données réel.
>
> **Priorité directrice** : le calculateur Ud/Ur/A, la gestion des clients de rang 0 à N et les questionnaires d'abord (Jalon 1) ; l'analyse et la défendabilité ensuite (Jalon 2) ; l'industrialisation enfin (Jalon 3).

**État de départ** : v1 fonctionnelle — 144 tests pytest verts, app Dash 4 vérifiée en HTTP (19 callbacks), package `supplyscore` (domain/core/graph/data/services/web_ui), Python 3.12, venv `.venv`, PAS de dépôt git.

---

## §1. Conventions transverses (s'appliquent à TOUTES les phases)

### Méthode d'exécution par agents IA
1. **Règle d'or des lots parallèles** : chaque fichier a UN SEUL lot propriétaire par phase. Les fichiers très partagés (`supplyscore/services/orchestrator.py`, `supplyscore/data/db.py`, `supplyscore/domain/models.py`) sont toujours affectés à un lot unique ; les autres lots codent contre une **API contractuelle figée dans ce PLAN** (signatures écrites avant le lancement des agents).
2. Chaque phase se termine par une **tâche d'intégration séquentielle** (un seul agent : câblage, exécution complète de la suite, lissage).
3. Chaque lot livre ses tests dans un fichier de test qui lui est propre (jamais d'édition concurrente d'un même `test_*.py`).
4. Protocole par phase : figer les API contractuelles → lancer les lots parallèles → tâche d'intégration → vérifier le DoD → `git commit` taggé `phase-EN`.

### Environnement (Windows 11, poste mono-utilisateur)
- Jamais `python` nu : `.venv\Scripts\python.exe -m pytest tests -q`.
- Installation : `uv` avec `$env:UV_LINK_MODE='copy'` (le dossier est synchronisé cloud, les hardlinks échouent — os error 396).
- Tout nouveau code : POO, docstrings et UI en **français**, urgences dans [0,1], adéquation dans [0,100].

### Definition of Done (DoD) global de chaque phase
- `ruff check` clean, `mypy` clean (strict sur domain/core/graph/data/services ; permissif sur web_ui),
- 100 % des tests verts (anciens + nouveaux),
- couverture ≥ seuil du jalon (Jalon 1 : mesurée et consignée ; Jalons 2-3 : ≥ 90 % bloquant),
- `git commit` taggé `phase-EN`.

### Paramètres de gouvernance du modèle (constants, toute modification = décision documentée)
- Adéquation asymétrique Prospect Theory : `lambda_under = 2.25 > lambda_over = 1.0`, `alpha = 0.88` (le danger invisible prime sur la panique).
- Cohérence AHP : `CR < 0.10` (4 critères : Impact opérationnel, Fenêtre temporelle, Dépendances aval, Récupérabilité).
- Lissage EMA du Ud : `rho = 0.3`.
- Modulation planning de u_time : `κ_retard = 0.5`, `κ_avance = 0.2` (surchargables par projet).
- Calibration bayésienne des événements : `N₀ = 26` pseudo-observations (≈ 6 mois hebdo).

### Références d'état de l'art (à citer dans docs/modele_mathematique.md)
- **Ripple effect / propagation multi-rangs** (fonde Ud descendant / Ur montant) : Ivanov et al. — tandfonline.com/doi/full/10.1080/00207543.2025.2470348 ; pmc.ncbi.nlm.nih.gov/articles/PMC7546950 ; approche Markov+DBN : tandfonline.com/doi/abs/10.1080/00207543.2019.1661538.
- **Réseaux bayésiens (DBN) pour la disruption** : sciencedirect.com/science/article/pii/S2405896322019048 ; revue : pmc.ncbi.nlm.nih.gov/articles/PMC7305519.
- **BWM/FBWM et hybrides BWM+PROMETHEE** (meilleure cohérence que l'AHP au-delà de quelques critères, 2n−3 comparaisons) : ejournal.umm.ac.id/index.php/industri/article/view/41355 ; link.springer.com/article/10.1007/s10668-023-04200-1.
- **Stress-test TTR/TTS (Simchi-Levi/MIT)** — écarté volontairement, documenté comme extension : sciencedirect.com/science/article/abs/pii/S0925527323001706 ; tandfonline.com/doi/full/10.1080/00207543.2025.2483113.
- **Pratique commerciale** (Everstream, Resilinc, Interos) : mapping multi-rangs jusqu'au tier 10, scoring continu, scénarios pré-événement. **Différenciateur SupplyScore : aucune plateforme ne mesure l'adéquation déclaré/réel (Ud vs Ur).**

---

## §2. Limites honnêtes — ce que le système ne fera PAS

1. **Pas de prédiction certaine** : le système produit des probabilités, des scores et des intervalles de confiance — pas des prophéties. Un modèle reste une simplification du réel.
2. **La fraîcheur des scores = la cadence de saisie** : sans connecteur ERP (choix : saisie manuelle), un score n'est jamais plus à jour que le dernier questionnaire rempli.
3. **L'AHP devient incohérent au-delà de ~7 critères** : il reste sur les 4 critères d'urgence (Ud) ; la pondération des nombreux blocs KPI (Ur) passe par FBWM (Jalon 2).
4. **La réversibilité d'un événement n'est garantie que si rien d'autre n'a réécrit le KPI entre-temps** : sinon le système lève un conflit explicite à résoudre manuellement. Toute annulation « magique » (rebase des écritures postérieures) serait mathématiquement malhonnête — assumé.
5. **Les calibrations d'impact des événements** (N₀=26, coefficients EMA, pseudo-comptes) sont défendables (révision bayésienne conjuguée standard) mais ne sont PAS des vérités mesurées : le serious game servira à les recaler.
6. **u_time ne regarde que le prochain jalon actif** : un jalon lointain qui dérive reste invisible jusqu'à devenir le prochain. Le modèle (fonction recevant la liste complète des jalons) permet une extension future (max pondéré), pas la formule v2.
7. **« Jamais de perte de données » exige des tables d'audit strictement inéditables** : `audit_log`, `urgency_history`, `kpi_snapshots`, `weekly_reviews`, `decisions` sont exclues de toute édition, y compris dans la vue admin. Si cette règle saute, la promesse d'audit s'effondre.
8. **DataTable éditable : ~2 000 lignes visibles maximum** : le périmètre par projet×bloc maintient < 600 lignes ; au-delà, plan B dash-ag-grid (arbitré en E14 sur mesures).
9. **Double comptage possible** : un événement saisi (volet 4 hebdo) ET une correction manuelle du même KPI la même semaine — un garde-fou avertit, mais n'interdit pas (l'opérateur reste souverain).
10. **Le branchement du temps réel fera bouger les scores** : aujourd'hui `t=0.0` partout ; dès que l'horloge vit (E1/E2), les deadlines saisies deviennent « vraies ». Mode par projet (réel/jeu) pour maîtriser la transition.

---

## §3. Registre des faiblesses v1 (détectées par audit du code réel)

| # | Gravité | Faiblesse | Phase |
|---|---------|-----------|-------|
| 1 | **CRITIQUE** | Perte d'état au redémarrage : `RegistryDatabase` ne persiste aucun champ d'urgence ; `_row_to_node` reconstruit un `UrgencyState()` vierge — le `ud_local` lissé (EMA) est perdu à chaque relance, l'adéquation est ensuite calculée contre `ud=0` | E1 |
| 2 | **CRITIQUE** | SQLite inter-threads latent : connexions créées au thread principal, callbacks Dash servis dans des threads Flask, `check_same_thread=True` par défaut → `ProgrammingError` au premier callback qui écrit | E1 |
| 3 | Majeure | Triple duplication des règles DONE/ABANDONED (`orchestrator.refresh_ur_local`, `UrModel.ur_local`, `PropagationEngine._effective_ur_local`) — divergence garantie | E1 |
| 4 | Majeure | Double propagation dans `set_status` (`apply_status` → `propagate_all`, puis `evaluate_all` → re-`propagate_all`) | E1 |
| 5 | Majeure | Connexions SQLite jamais fermées, cache `_client_dbs` non borné (1 fichier ouvert PAR nœud, à vie ; fichiers -wal/-shm orphelins constatés) | E1, E14 |
| 6 | Majeure | `t=0.0` partout — aucune notion de temps courant : `u_time` évalue toujours `P(L>d−0)` | E1, E2 |
| 7 | Mineure | Incohérence générateur/UI : `generate_assessment(n_criteria=5)` vs `CRITERIA` à 4 dans l'UI | E1 |
| 8 | Majeure | Aucune validation des KPIs ni des coefficients (`float(value)` brut, γ/β/δ non bornés, NaN/inf non rejetés) | E2 (léger), E10 (complet) |
| 9 | Majeure | CR vérifié uniquement côté UI : `submit_assessment` accepte une évaluation incohérente en appel direct | E10 |
| 10 | Mineure | `assign_ranks` jamais appelé par le service : les rangs peuvent diverger de la définition « plus longue distance vers un puits » | E10 |
| 11 | Majeure | Sémantique DONE ambiguë : un nœud DONE transmet toujours l'urgence amont et son `ud_local` se propage encore — non documenté | E9 |
| 12 | Mineure | `u_cost` : la dérive négative (économie) compense tarif/stockage avant le clip — non documenté | E9 |
| 13 | Majeure | Rendu DAG : une annotation Plotly PAR arc + Scatter SVG + étiquettes systématiques — inutilisable à 500+ nœuds | E14 |
| 14 | Majeure | `evaluate_all(persist=True)` : 1 transaction par nœud dans 1 base par nœud — O(N) commits | E14 |
| 15 | Mineure | Pas d'index sur `assessments`/`kpi_snapshots`/`urgency_history` (requêtes ORDER BY timestamp) | E3, E14 |
| 16 | Mineure | `PRAGMA foreign_keys=ON` sans aucune FK déclarée — garde-fou inopérant | E1 |
| 17 | Majeure | `kpis_from_json` fragile : `cls(**raw)` lèvera TypeError sur tout champ retiré/renommé — aucun mécanisme de migration | E1 |
| 18 | Majeure | Aucune gestion d'erreur dans les callbacks (toast Dash générique anglais), aucun logging applicatif | E1 (logs), E16 (callbacks) |
| 19 | Mineure | Épingles de dépendances incohérentes (`dash>=2.16` déclaré, 4.2.0 installé ; pas de lock) | E0 |
| 20 | Mineure | `neo4j_repo.py` (293 lignes) non testé, driver absent — à exclure de la couverture et geler | E0 |
| 21 | Majeure | Bases SQLite WAL dans un dossier synchronisé cloud — latences et risque de corruption (résidus -wal/-shm constatés) | E17 (bancs sur %TEMP% dès E14) |
| 22 | Majeure | Adéquation calculée contre `ud=0` pour les nœuds jamais évalués — H artificiellement alarmant | E4 |
| 23 | Mineure | `uuid.uuid4()` direct dans les callbacks vs UUID seedés du générateur — à centraliser si reproductibilité UI désirée | E16 (optionnel) |

---

## §4. JALON 1 — « Prêt pour le serious game »

> **Objectif du jalon** : le calculateur Ud/Ur/A, la gestion des clients de rang 0 à N et les deux questionnaires (onboarding + hebdomadaire) sont complets et fiables. À la sortie : une session de serious game est jouable de bout en bout.

---

### E0 — Socle qualité léger

**Objectif** : rendre toute régression détectable mécaniquement avant de toucher au code. **Prérequis** : aucun.

#### Lots
**Lot 0.1 — séquentiel, en premier** — `.gitignore`, `pyproject.toml`, `uv.lock` (nouveau), `README.md`
- `git init` + `.gitignore` : `.venv/`, `__pycache__/`, `*.egg-info/`, `.pytest_cache/`, `data_store/`, `data_demo/`, `*.sqlite*`, `.coverage*`, `htmlcov/`, `.hypothesis/`, `logs/`, `exports/`. Commit initial = état v1 exact (144 tests verts).
- `pyproject.toml` : resserrer les bornes (`dash>=4.2,<5`, `plotly>=6.8,<7`, `numpy>=2.4,<3`, `networkx>=3.6,<4`), groupe dev : `pytest`, `pytest-cov`, `hypothesis`, `ruff`, `mypy`, `pre-commit` (plus tard : `pytest-benchmark`, `dash[testing]`, `scipy`, `platformdirs`, `openpyxl`). Générer `uv.lock` (`uv lock`).
- `[tool.ruff]` : line-length 100, règles E,F,W,I,N,B,UP,SIM,RUF + D (docstrings, convention google). `[tool.mypy]` : strict sur `domain`, `core`, `graph`, `data`, `services` ; permissif sur `web_ui`. `[tool.coverage]` : mesure activée, `omit = ["supplyscore/graph/neo4j_repo.py"]` — le seuil bloquant ≥ 90 n'arrive qu'au Jalon 2 (E9).

**Lots 0.2a–0.2d — parallèles — conformité ruff+mypy par paquet** (périmètres disjoints) :
- 0.2a : `supplyscore/domain/`, `supplyscore/core/` ; 0.2b : `supplyscore/graph/`, `supplyscore/data/` ; 0.2c : `supplyscore/services/`, `run_app.py` ; 0.2d : `supplyscore/web_ui/`. Corrections mécaniques uniquement (imports, annotations, docstrings) — **interdiction de changer un comportement**. Ne pas reformater `web_ui` au point de casser les ids Dash (chaînes littérales).

**Lot 0.3 — parallèle à 0.2 — infrastructure de test** — `tests/conftest.py` (nouveau), `scripts/ci.ps1` (nouveau), `.pre-commit-config.yaml` (nouveau), `.github/workflows/ci.yml` (nouveau, dormant)
- `conftest.py` : fixtures partagées (`tmp_store`, `service_demo`), profils hypothesis (`dev` = 50 exemples, `ci` = 300, sélection via `HYPOTHESIS_PROFILE`).
- `scripts/ci.ps1` : `ruff check` → `ruff format --check` → `mypy` → `pytest --cov=supplyscore` ; code retour agrégé. C'est la « CI » mono-poste.

#### Tests exigés
Les 144 tests existants restent verts à l'identique ; couverture baseline mesurée et consignée dans le message de commit (~90 % attendu hors neo4j).

#### DoD
`scripts/ci.ps1` retourne 0 ; dépôt git avec ≥ 2 commits (v1 brute, v1 conformée) ; `uv.lock` présent. Tag `phase-E0`.

#### Risques
- Dossier synchronisé cloud : exclure `.git` de la synchro si possible.
- mypy strict sur `core` révélera des `float | None` non gardés — corriger par des gardes, jamais par `# type: ignore`.

---

### E1 — Assainissement critique + horloge bimodale + opérateurs

**Objectif** : corriger les défauts structurels (faiblesses #1-7, #16-18) AVANT le serious game — on ne peut pas perdre une partie. Introduire le temps (réel/jeu) et l'identification des joueurs. **Prérequis** : E0.

#### Lots
**Lot 1.1 — SÉQUENTIEL EN PREMIER (fichiers très partagés)** — `supplyscore/data/db.py`, `supplyscore/data/migrations.py` (nouveau), `supplyscore/services/orchestrator.py`, `tests/test_data_migrations.py` (nouveau)
1. **Migrations versionnées** : `migrations.py` expose `apply_migrations(conn, kind: Literal["registry","client"])` pilotées par `PRAGMA user_version` (liste ordonnée `(version, sql|callable)`). Le `_create_schema` actuel devient la migration v1.
2. **Migration registry v2** : table `node_urgency(node_id TEXT PRIMARY KEY, ud_local REAL, ur_local REAL, ud REAL, ur REAL, adequation REAL, false_urgency REAL, hidden_risk REAL, timestamp REAL)` + table `project_settings(project_id TEXT, key TEXT, value_json TEXT, PRIMARY KEY(project_id, key))` (servira à E2/E4/E12/E13 sans nouveau conflit de fichier) + vraies contraintes `FOREIGN KEY` sur `nodes.project_id` et `arcs.source_id/target_id` + index `idx_nodes_project`.
3. **Réhydratation** : `RegistryDatabase.save_node` écrit aussi `node_urgency` (upsert) ; `load_graph_from_registry` restaure l'`UrgencyState` complet. **Test pivot** : créer service → soumettre questionnaires → `evaluate_all(persist=True)` → fermer → rouvrir un service neuf sur le même répertoire → états strictement identiques champ à champ.
4. **Threading SQLite** : `sqlite3.connect(..., check_same_thread=False)` + `threading.RLock` par instance, pris dans chaque méthode publique (reproduire l'erreur en test AVANT de corriger : callback simulé depuis un thread secondaire → `ProgrammingError`).
5. **Cycle de vie** : `SupplyScoreService.close()` (ferme registre + toutes les `ClientDatabase`, `PRAGMA wal_checkpoint(TRUNCATE)`), `__enter__/__exit__` ; cache `_client_dbs` borné LRU (taille 64, fermeture à l'éviction, sous le verrou de l'instance évincée).
6. **Suppression de la double propagation** : `apply_status` ne fait plus que poser le statut ; `evaluate_all` reste l'UNIQUE point de propagation. Test d'équivalence avant/après (mêmes états finaux, `propagate_all` exécuté une seule fois — compteur espion).
7. **`kpis_from_json` robuste** : filtrage des clés inconnues à la reconstruction (`{k: v for k, v in raw.items() if k in fields}`) — tolère l'évolution de schéma.

**Lot 1.2 — parallèle — horloge bimodale** — `supplyscore/core/clock.py` (nouveau), `tests/test_core_clock.py` (nouveau)
```python
class Clock(Protocol):
    def now(self) -> float: ...          # epoch secondes

class SystemClock:                        # mode « réel »
    def now(self) -> float: return time.time()

class FixedClock:                         # tests
    def __init__(self, ts: float): ...

class GameClock:                          # mode « jeu » (serious game)
    def __init__(self, start_ts: float, weeks_elapsed: int = 0): ...
    def now(self) -> float: ...           # start_ts + weeks_elapsed*604800
    def advance_weeks(self, n: int = 1) -> None
    def to_json(self) -> str / from_json(cls, raw) -> GameClock   # persisté dans project_settings('clock')

def iso_week(ts: float) -> str            # "2026-S24", zéro-paddé
def project_hours(ts: float, t0_ts: float) -> float   # (ts - t0)/3600 : pont vers le t des formules
```
- **Mode par projet** : `project_settings('clock') = {"mode": "real"|"game", "start_ts": ..., "weeks_elapsed": n}`. Le service résout l'horloge du projet à chaque évaluation.
- Cas analytiques exigés : `2026-06-10 → "2026-S24"`, `2026-12-28 → "2026-S53"`, `2021-01-01 → "2020-S53"`, `2026-01-01 → "2026-S01"` ; `GameClock(t0).advance_weeks(3)` ⇒ `now() = t0 + 3·604800` et `iso_week` avance de 3 semaines.

**Lot 1.3 — parallèle — règles de statut unifiées** — `supplyscore/core/status_rules.py` (nouveau), `supplyscore/core/ur_model.py`, `supplyscore/graph/propagation.py`, `tests/test_core_status_rules.py` (nouveau)
- `def effective_ur_local(status: TaskStatus, ur_local: float | None) -> float` — unique source de vérité (DONE→0.0, ABANDONED→1.0, sinon `ur_local or 0.0`). `UrModel` et `PropagationEngine` délèguent. (`orchestrator.refresh_ur_local` aligné par la tâche d'intégration — le fichier appartient au lot 1.1.)

**Lot 1.4 — parallèle — journalisation** — `supplyscore/infra/__init__.py`, `supplyscore/infra/logging.py` (nouveaux), `run_app.py`, `tests/test_infra_logging.py` (nouveau)
- `configure_logging(level, log_dir)` : handler fichier rotatif (`logs/supplyscore.log`, 5×2 Mo) + console, format horodaté FR. `run_app.py` ajoute `--log-level` et un arrêt propre (`atexit` → `service.close()`).

**Lot 1.5 — parallèle — cohérence du générateur** — `supplyscore/data/generator.py`, `tests/test_data_generator.py`
- `generate_assessment(n_criteria=5)` → défaut **4**, aligné sur `CRITERIA` de l'UI.

**Lot 1.6 — parallèle — sélecteur d'opérateur** — `supplyscore/web_ui/components/operator.py` (nouveau), `supplyscore/web_ui/app.py`, `tests/test_webui_operator.py` (nouveau)
- Dropdown « Qui joue ? » dans la navbar + champ de création ; `dcc.Store(id="store-operator", storage_type="session")` ; helper `current_operator(store_data) -> str` (défaut `"anonyme"`). Tous les callbacks d'écriture futurs lisent ce store. Les opérateurs connus sont mémorisés dans `project_settings('operators')`.

**Tâche d'intégration E1.I (séquentielle)** : aligner `orchestrator.refresh_ur_local` sur `status_rules` ; injecter `Clock` dans `SupplyScoreService.__init__(clock: Clock | None = None)` avec résolution par projet (`_clock_for(project_id)`) ; bouton « Avancer d'une semaine » (visible si mode jeu) sur la page Projets → `advance_weeks(1)` + `evaluate_all(persist=True)` ; suite complète verte.

#### Tests exigés
- Test de redémarrage (pivot ci-dessus) ; test multi-threads : 8 threads × 50 `submit_assessment`/`evaluate_all` concurrents sans exception ni corruption (`PRAGMA integrity_check` = ok) ; plus de fichiers `-wal`/`-shm` orphelins après `close()` ; équivalence `set_status` (une seule propagation) ; GameClock : avancer 3 semaines ⇒ `iso_week` et `u_time` bougent conformément ; migration d'une base v1 réelle sans perte (test sur copie).

#### DoD
Redémarrage sans perte d'état ; aucun accès SQLite inter-thread non protégé ; une seule implémentation des règles de statut ; horloge bimodale opérationnelle par projet ; opérateur courant propagé ; logs en place ; suite verte. Tag `phase-E1`.

#### Risques
- `check_same_thread=False` sans verrou = corruption silencieuse : le verrou est obligatoire.
- L'arrivée du temps réel change le comportement de TOUS les Ur existants (les deadlines v1 deviennent « vraies ») : les projets de démo doivent être re-seedés avec des deadlines relatives à `now()`.
- L'éviction LRU doit prendre le verrou de l'instance évincée.

---

### E2 — Domaine v2 : jalons, événements calibrés, cahier des charges, tags, arcs backup

**Objectif** : introduire toutes les entités métier du serious game et la formule u_time v2. **Prérequis** : E1 (migrations, clock, status_rules).

#### Lots
**Lot 2.1 — jalons + u_time v2** — `supplyscore/domain/milestones.py` (nouveau), `supplyscore/core/ur_model.py`, `tests/test_milestones.py`, `tests/test_u_time_v2.py` (nouveaux)
```python
class MilestoneStatus(StrEnum): ACTIVE = "active"; DONE = "done"; ABANDONED = "abandoned"

@dataclass
class Milestone:
    id: str; node_id: str; name: str          # "Proto", "Série", "Livraison"...
    kind: str = "livraison"                    # proto | serie | livraison | custom
    start_ts: float = 0.0                      # epoch s (début planifié)
    deadline_ts: float = 0.0                   # epoch s, > start_ts
    status: MilestoneStatus = ACTIVE
    progress: float = 0.0                      # avancement déclaré [0, 1]
    position: int = 0

def next_active_milestone(milestones) -> Milestone | None    # ACTIVE de deadline minimale
def theoretical_progress(m, now_ts) -> float                 # clip01((t-s*)/(d*-s*)), 1.0 si d*==s*
def derive_node_status(milestones) -> TaskStatus | None
```
**Règle de statut dérivé** (table de vérité) : liste vide → `None` (statut manuel v1 conservé — rétro-compat) ; ≥ 1 ACTIVE → ACTIVE ; 0 actif et ≥ 1 DONE → DONE ; tous ABANDONED → ABANDONED.

**Formule u_time v2** (signature étendue `u_time(t, kpis, milestones=None)`, fallback v1 exact si `milestones` None/vide). Soit `M*` le jalon ACTIVE de deadline minimale, `d* = (deadline_ts − t0_ts)/3600`, `s* = (start_ts − t0_ts)/3600` :
```
si t > d* :  u_time = 1.0                                  (retard avéré)
sinon :
  u_base = P(L > d* − t)      L ~ Normale(lead_time_h, std)  (réutilise _normal_sf v1)
  p_th   = theoretical_progress(M*, t)
  r      = p_th − M*.progress           ∈ [−1, 1]  (r > 0 = en retard sur le planning)
  u_time = clip01( u_base + κ_r·max(r, 0) − κ_a·max(−r, 0) )
```
Défauts `κ_r = 0.5`, `κ_a = 0.2` (l'avance déclarée est moins fiable qu'un retard constaté), surchargables via `project_settings('ur.kappa_retard'|'ur.kappa_avance')`. La forme ADDITIVE est choisie exprès : la contribution du glissement de planning `κ_r·r₊` sera directement lisible dans l'explicabilité (E8).

Cas chiffrés exigés : jalon `d*=100 h`, `s*=0`, lead 50, std 10, `t=40` → slack 60, `u_base = 1−Φ(1) = 0.1587` ; `progress=0.4` (= p_th) → **0.1587** ; `progress=0.1` → r=0.3 → **0.3087** ; `progress=0.9` → r=−0.5 → **0.0587** ; `t=120` → **1.0** ; jalon 1 DONE + jalon 2 d=200 → M* = jalon 2. Hypothesis : `u_time ∈ [0,1]` avant deadline ; décroissante en `progress` à t fixé.

**Lot 2.2 — événements + calibration** — `supplyscore/domain/events.py` (nouveau), `tests/test_events_calibration.py` (nouveau)
Trois opérateurs, défendables et documentés :
- **Révision bayésienne Beta-Bernoulli** (pour `failure_probability`) : prior `Beta(α,β)`, `α = p·N₀`, `β = (1−p)·N₀`, `N₀ = 26` (mémoire ≈ 6 mois hebdo). Un événement = `n` pseudo-observations dont `k` défaillances : `BAYES(p, k, n) = (p·N₀ + k) / (N₀ + n)`, borné `[1e-4, 0.99]`. Sémantique auditable : « cet événement équivaut à observer k défaillances sur n essais ».
- **Lissage exponentiel** : `EMA(old, obs, λ) = (1−λ)·old + λ·obs`.
- **Mise à jour DIRECTE** pour les faits (un tarif signé n'est pas une croyance).

**Typologie des 14 événements** (constante `EVENT_CALIBRATION: dict[str, EventSpec]`, surchargable via `project_settings('events.calibration')`) :

| Type | Paramètres de saisie | Impacts calibrés |
|---|---|---|
| `panne_machine` | `duree_arret_h>0`, `gravite∈{mineure,majeure,critique}` | `risk.failure_probability ← BAYES(p,k,n)` avec (k,n) = (0.5,1)/(1,1)/(2,2) ; `risk.recovery_time_h ← EMA(·, duree, 0.4)` ; `oee.availability ← EMA(·, max(0, 1−duree/168), 0.3)` |
| `retard_fournisseur` | `retard_h>0` | `time.lead_time_h ← EMA(·, old+retard, 0.4)` ; `time.lead_time_std_h ← EMA(·, retard, 0.3)` |
| `greve` | `duree_prevue_h`, `part_effectif∈[0,1]` | `oee.availability ← old·(1 − part·min(duree/168, 1))` ; `risk.severity ← max(old, part)` |
| `hausse_tarif` | `pct∈[−100,+500]` | `cost.tariff ← old·(1+pct/100)` (DIRECT) ; `risk.cost_volatility ← EMA(·, min(|pct|/100,1), 0.3)` |
| `rupture_matiere` | `duree_prevue_h`, `criticite∈[0,1]` | `inventory.flow_rate ← old·(1−criticite)` ; `risk.failure_probability ← BAYES(p, criticite, 1)` ; `risk.severity ← max(old, criticite)` |
| `accident` | `duree_arret_h`, `gravite` | `failure_probability ← BAYES` (mêmes (k,n) que panne) ; `recovery_time_h ← EMA(·,·,0.5)` ; `severity ← max(old, 0.4/0.7/1.0)` |
| `non_conformite_qualite` | `taux_rebut_obs∈[0,1]` | `oee.quality ← EMA(·, 1−taux, 0.4)` ; si taux > `max_scrap_rate` du cahier des charges → alerte (pas d'impact suppl.) |
| `perturbation_transport` | `retard_h`, `surcout≥0` | `time.lead_time_h ← EMA(·, old+retard, 0.4)` ; `cost.op_cost ← old + surcout` (DIRECT) |
| `instabilite_politique` | `niveau∈[0,1]` | `risk.political_risk ← max(old, niveau)` (cliquet ; redescente par décroissance hebdo ou édition) |
| `cyber_incident` | `duree_arret_h` | `failure_probability ← BAYES(p,1,1)` ; `availability ← EMA(·, max(0,1−duree/168), 0.3)` |
| `hausse_energie` | `pct` | `cost.op_cost ← old·(1+pct/100)` (DIRECT) ; `cost_volatility ← EMA(·, min(|pct|/100,1), 0.3)` |
| `alerte_financiere_fournisseur` | `gravite∈{surveillee,procedure,defaut}` | `failure_probability ← BAYES` avec (k,n) = (0.5,1)/(1,1)/(3,3) ; `severity ← max(old, 0.3/0.6/0.9)` |
| `perte_capacite` | `pct_volume_perdu∈[0,1]` | `inventory.max_volume_m3 ← old·(1−pct)` (DIRECT, fait physique) ; `risk.env_exposure ← max(old, pct)` |
| `pic_demande` | `nouvelle_demande>0` | `network.demand ← nouvelle_demande` (DIRECT) |

Plus la **décroissance optionnelle** au volet hebdo « rien à signaler » : `failure_probability ← BAYES(p, 0, 1)` — la semaine sans incident est elle-même une observation, c'est ce qui rend le modèle symétrique. Tous les résultats sont bornés par `KPI_CONSTRAINTS`. Les fonctions sont **PURES** : elles calculent `list[KpiImpact(kpi_path, old, new, rule)]` sans IO — l'application transactionnelle arrive en E6.

Cas chiffrés exigés : p=0.02, N₀=26 : panne majeure → **0.0563** ; critique → **0.09** ; mineure → **0.0378** ; décroissance → **0.01926** ; `hausse_tarif` pct=12 sur tariff=1.05 → **1.176**. Hypothesis : `BAYES ∈ (0,1)`, croissante en k, point fixe si k/n = p.

**Lot 2.3 — cahier des charges + tags** — `supplyscore/domain/specsheet.py`, `supplyscore/domain/tags.py` (nouveaux), `tests/test_specsheet.py` (nouveau)
```python
@dataclass class Deliverable: name: str; quantity: float; unit: str; milestone_id: str | None = None
@dataclass class QualityRequirements: standards: list[str]; certifications: list[str]; max_scrap_rate: float | None; notes: str = ""
@dataclass class PenaltyClause: kind: str  # late_delivery|quality|other
                                trigger: str; amount_per_day: float | None; cap_amount: float | None
@dataclass class CahierDesCharges: deliverables: list[Deliverable]; budget_total: float | None
    target_unit_cost: float | None; currency: str = "EUR"
    quality: QualityRequirements; penalties: list[PenaltyClause]; notes: str = ""
# + cdc_to_json / cdc_from_json (même pattern tolérant que kpis_from_json)
@dataclass class TagCategory: id: str; project_id: str; name: str; color: str | None
@dataclass class Tag: id: str; project_id: str; name: str; category_id: str | None
```

**Lot 2.4 — modèles + migrations + CRUD** — `supplyscore/domain/models.py`, `supplyscore/data/db.py`, `supplyscore/data/migrations.py`, `tests/test_db_v2.py` (nouveau)
- `models.py` : `class ArcKind(StrEnum): NOMINAL="nominal"; BACKUP="backup"` ; `SupplyArc.kind_arc: ArcKind = NOMINAL` ; `SupplyNode.tags: list[str]` (ids) ; `SupplyNode.onboarding_state: str = "complete"` (`draft`|`complete`).
- Migrations **registre** :
```sql
ALTER TABLE projects ADD COLUMN t0_ts REAL;                 -- backfill = created_at
ALTER TABLE nodes ADD COLUMN onboarding_state TEXT NOT NULL DEFAULT 'complete';
ALTER TABLE arcs ADD COLUMN arc_kind TEXT NOT NULL DEFAULT 'nominal';
CREATE TABLE milestones (
  id TEXT PRIMARY KEY, node_id TEXT NOT NULL,
  name TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'livraison',
  start_ts REAL NOT NULL, deadline_ts REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  progress REAL NOT NULL DEFAULT 0.0 CHECK (progress BETWEEN 0 AND 1),
  position INTEGER NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
  FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE CASCADE,
  CHECK (deadline_ts > start_ts));
CREATE INDEX idx_milestones_node ON milestones(node_id, position);
CREATE TABLE tag_categories (id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
  name TEXT NOT NULL, color TEXT, UNIQUE(project_id, name));
CREATE TABLE tags (id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
  category_id TEXT REFERENCES tag_categories(id) ON DELETE SET NULL,
  name TEXT NOT NULL, UNIQUE(project_id, name));
CREATE TABLE node_tags (node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  tag_id TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  PRIMARY KEY (node_id, tag_id));
CREATE INDEX idx_node_tags_tag ON node_tags(tag_id);
CREATE TABLE onboarding_progress (
  node_id TEXT PRIMARY KEY REFERENCES nodes(id) ON DELETE CASCADE,
  sections_done_json TEXT NOT NULL,       -- {"identity":1,"cdc":0,"kpis":0,"ahp":0}
  draft_json TEXT NOT NULL DEFAULT '{}',
  current_step INTEGER NOT NULL DEFAULT 1,
  updated_at REAL NOT NULL);
```
- Migrations **base client** :
```sql
CREATE TABLE spec_sheet (id INTEGER PRIMARY KEY AUTOINCREMENT, node_id TEXT NOT NULL,
  version INTEGER NOT NULL, payload_json TEXT NOT NULL,
  source TEXT NOT NULL, created_at REAL NOT NULL, UNIQUE(node_id, version));
CREATE TABLE events (id TEXT PRIMARY KEY, node_id TEXT NOT NULL,
  event_type TEXT NOT NULL, iso_week TEXT NOT NULL, occurred_at REAL NOT NULL,
  params_json TEXT NOT NULL, impacts_json TEXT NOT NULL,
  reverted_at REAL, operator_id TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '');
CREATE INDEX idx_events_node_week ON events(node_id, iso_week);
```
- CRUD : `RegistryDatabase.save_milestone/list_milestones(node_id)/delete_milestone`, `save_tag/list_tags(project_id)/save_tag_category/list_tag_categories/set_node_tags/tags_of_node`, `save_onboarding/get_onboarding/delete_onboarding` ; `ClientDatabase.save_spec_sheet/latest_spec_sheet/spec_sheet_versions`, `save_event/list_events(node_id, iso_week=None)/mark_reverted`.
- **Validation LÉGÈRE intégrée** (la validation exhaustive attend E10) : table `KPI_CONSTRAINTS: dict[str, tuple[float|None, float|None, str]]` (min, max, unité) dans `supplyscore/domain/constraints.py` (nouveau, ce lot) — ratios [0,1], durées/coûts ≥ 0, `tariff > 0`, rejet `NaN/±inf` (`math.isfinite`) ; appliquée par les setters de KPIs et les formulaires.

**Lot 2.5 — arcs backup inertes** — `supplyscore/graph/repository.py`, `supplyscore/graph/memory_repo.py`, `supplyscore/graph/propagation.py`, `supplyscore/web_ui/components/figures.py`, `tests/test_backup_arcs.py` (nouveau)
- `GraphRepository.predecessors(node_id, *, kinds=("nominal",))`, idem `successors`, `arcs(kinds=None)`. `PropagationEngine` ne traverse QUE les arcs `nominal`. `dashboard_dag_figure` trace les backup en pointillés gris.
- Test : graphe A→B nominal + C→B backup, `Ur_loc_C=1.0` → `Ur_B` identique avec ou sans C (égalité STRICTE, bit à bit).

**Tâche d'intégration E2.I (séquentielle)** — `supplyscore/services/orchestrator.py`, `supplyscore/data/generator.py` : `project_time_h(project) = (clock.now() − t0_ts)/3600` ; `evaluate_all()` charge les jalons, passe `milestones` à `u_time`, applique `derive_node_status` AVANT `refresh_ur_local` ; `seed_demo` enrichi (2-4 jalons par nœud avec deadlines relatives à now(), tags, 1 arc backup sur ~10, déterministe à seed égal).

#### DoD
Migrations idempotentes et rejouables sur une base v1 réelle ; 100 % des tests v1 verts (rétro-compat `milestones=None`) ; backup sans aucun effet calcul ; u_time v2 vérifiée sur les 5 cas chiffrés ; statut dérivé conforme à la table de vérité. Tag `phase-E2`.

#### Risques
- `ALTER TABLE` SQLite ne supporte pas `ADD COLUMN ... CHECK` : les CHECK vont sur les CREATE TABLE, les bornes des colonnes ajoutées passent par `constraints.py`.
- Ne PAS dériver le statut d'un nœud sans jalons (écraserait les statuts manuels v1).
- `theoretical_progress` avec `d* == s*` → convention `p_th = 1.0` (pas de division par zéro).

---

### E3 — Versionnage & audit universels

**Objectif** : aucune écriture ne perd jamais une valeur — journal d'audit append-only (quoi, quand, ancienne→nouvelle, source, opérateur), API « valeur à la date t ». Posé AVANT les questionnaires : toutes les saisies du serious game doivent être tracées pour l'analyse post-jeu. **Prérequis** : E1 (RLock, migrations, clock), E2 (entités à auditer).

**Architecture** : UNE table générique `audit_log` PAR base (le journal suit l'entité : structure → registre, données du nœud → base client), en diff-journal ; les « valeurs à la date t » des KPIs restent matérialisées par `kpi_snapshots` (lecture O(log n), pas de replay). Pas de triggers SQL : **triggers applicatifs** concentrés dans un service de mutations unique.

#### Lots
**Lot 3.1 — couche d'audit** — `supplyscore/data/audit.py` (nouveau), `tests/test_audit.py` (nouveau)
```python
@dataclass(frozen=True)
class AuditEntry:
    id: int; entity_type: str; entity_id: str; field: str
    old_value: Any; new_value: Any                 # JSON typés (json.dumps, jamais str())
    source: str    # 'onboarding'|'weekly'|'edit'|'event:<id>'|'revert:<id>'|'system'|'migration'
    operator_id: str; iso_week: str; timestamp: float

class AuditTrail:
    def __init__(self, conn, clock: Clock): ...
    def record(self, entity_type, entity_id, field, old, new, source, operator_id="") -> int
    def record_many(self, entries) -> None              # une seule transaction
    def history(self, entity_type, entity_id, field=None, limit=200, before=None) -> list[AuditEntry]
    def value_at(self, entity_type, entity_id, field, t: float) -> Any   # dernier new_value <= t
```

**Lot 3.2 — migrations + lectures** — `supplyscore/data/db.py`, `supplyscore/data/migrations.py`, `tests/test_db_audit.py` (nouveau)
```sql
-- dans registry.sqlite ET chaque <client>.sqlite :
CREATE TABLE audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, field TEXT NOT NULL,
  old_value TEXT, new_value TEXT,
  source TEXT NOT NULL, operator_id TEXT NOT NULL DEFAULT '',
  iso_week TEXT NOT NULL, timestamp REAL NOT NULL);
CREATE INDEX idx_audit_entity ON audit_log(entity_type, entity_id, field, timestamp);
CREATE INDEX idx_audit_week ON audit_log(iso_week);
CREATE INDEX idx_kpi_snap_node_ts ON kpi_snapshots(node_id, timestamp);
ALTER TABLE assessments ADD COLUMN replaces_id INTEGER;     -- NULL = originale
```
- `ClientDatabase.kpis_at(node_id, t) -> KPIBundle | None` (dernier snapshot ≤ t) ; `latest_assessment` exclut les évaluations remplacées.

**Lot 3.3 — MutationService** — `supplyscore/services/mutations.py` (nouveau), `tests/test_mutations.py` (nouveau)
```python
class MutationService:
    """Point de passage OBLIGATOIRE de toute écriture métier (diff + audit + transaction)."""
    def update_kpis(self, node_id, changes: dict[str, float | None], source, operator_id) -> list[AuditEntry]
    def update_node_fields(self, node_id, changes, source, operator_id) -> list[AuditEntry]
    def upsert_arc(self, arc, source, operator_id) / delete_arc(self, source_id, target_id, source, operator_id)
    def set_node_tags(self, node_id, tag_ids, source, operator_id)
    def update_milestone(self, milestone_id, changes, source, operator_id)
    def save_spec_sheet(self, node_id, cdc, source, operator_id) -> int       # version++
    def replace_assessment(self, old_id, new: AHPAssessment, operator_id) -> int  # replaces_id
```
- `update_kpis` : diff champ à champ (`risk.failure_probability` comme identifiant qualifié), n'écrit QUE les champs changés, valide via `KPI_CONSTRAINTS`, persiste nœud + snapshot + lignes d'audit dans UNE transaction.
- **Règle CI** (script dans `scripts/ci.ps1`) : motifs `save_node(`/`save_arc(` interdits hors `supplyscore/data/` et `supplyscore/services/` — le piège classique est l'écriture « rapide » ajoutée plus tard qui contourne le service.

**Lot 3.4 — composants UI d'historique** — `supplyscore/web_ui/components/history.py` (nouveau), `tests/test_history_component.py` (nouveau)
- `history_table(entries)` (DataTable lecture seule : date, semaine ISO, champ, ancienne → nouvelle, source, opérateur) ; `kpi_trajectory_figure(snapshots, kpi_path)` (vraie trajectoire d'un KPI).

**Tâche d'intégration E3.I (séquentielle)** — `orchestrator.py`, `web_ui/pages/questionnaire.py` : toutes les écritures existantes basculent sur `MutationService` ; test de garde « aucune écriture sans audit » (monkey-patch de `RegistryDatabase.save_node` : plus jamais appelé directement depuis les pages).

#### Dimensionnement (justifié, >500 nœuds)
Par nœud et par semaine : ~30 lignes d'audit + 1 snapshot (~1,5 Ko) + 1 ligne urgency_history, dans SA base client → sur 5 ans : ~8 000 lignes d'audit et ~400 Ko de snapshots par base. Registre : audit structurel rare (< 10³ lignes/an). `value_at()` en O(log n) par l'index.

#### Tests exigés
- `value_at` : écritures à t=100/200/300 → t=250 rend la valeur de t=200 ; t=50 rend None.
- `update_kpis` avec valeur identique → 0 ligne d'audit, 0 snapshot.
- Hypothesis : pour toute séquence d'updates aléatoires, replay des `new_value` du journal == valeur courante (complétude du journal).
- `replace_assessment` : l'originale reste lisible, `latest_assessment` rend la correction.
- Concurrence : 2 threads × 50 `update_kpis` sous verrou → 100 lignes, aucune perdue.

#### DoD
Toute mutation passe par MutationService (règle CI active) ; `value_at` < 5 ms sur 10 000 lignes ; courbes du dashboard alimentées par les vraies trajectoires. Tag `phase-E3`.

---

### E4 — Cycle hebdomadaire ISO

**Objectif** : rattacher chaque évaluation à une semaine ISO, état « à jour / en retard / manquant » par nœud, badges — pilotable par GameClock (avancer d'une semaine ⇒ statuts basculent). **Prérequis** : E1 (clock, project_settings), E3 (audit des écritures).

**Définitions à figer** : `semaine(e) = iso_week(e.timestamp)`, format `"AAAA-Sxx"`. **À jour** : ≥ 1 évaluation AHP de la semaine courante (du projet, selon SON horloge). **En retard** : dernière évaluation de semaine strictement antérieure (+ `semaines_de_retard`). **Manquant** : aucune évaluation. Pas de dégradation auto du Ud, pas d'email — affichage seulement. **Nœud « manquant » ⇒ l'adéquation A est affichée « — »** (et non calculée contre `ud=0`, qui produit des H artificiellement alarmants — faiblesse #22).

#### Lots
**Lot 4.1 — backend** — `supplyscore/services/weekly.py` (nouveau), `supplyscore/data/db.py` + `migrations.py` (colonne `iso_week TEXT` + index sur `assessments` et `urgency_history`, backfill depuis `timestamp` en une transaction), `supplyscore/services/orchestrator.py` (`submit_assessment` renseigne `iso_week`), `tests/test_services_weekly.py` (nouveau)
- API : `class CycleHebdomadaire(service, clock)` ; `statut_noeud(node_id) -> StatutHebdo` (StrEnum A_JOUR/EN_RETARD/MANQUANT + `semaines_de_retard: int`) ; `synthese(project_id) -> dict[node_id, StatutHebdo]` ; `couverture(project_id) -> tuple[int, int]`. Nœuds DONE/ABANDONED exclus du décompte.

**Lot 4.2 — composant badges** — `supplyscore/web_ui/components/badges.py` (nouveau), `tests/test_webui_badges.py` (nouveau)
- `badge_hebdo(statut)` (vert « À jour », orange « En retard (n sem.) », rouge « Manquant ») ; `completeness_badge(done, total)` et `draft_badge()` (pour E5). **Piège DataTable** : une cellule n'accepte pas de composant → texte + `style_data_conditional` sur la valeur ; le badge riche est réservé aux cartes/listes.

**Lots 4.3a/4.3b/4.3c — parallèles après 4.2 — câblage UI**
- 4.3a `dashboard.py` : colonne « Hebdo », carte KPI « Questionnaires à jour : x/y », A affiché « — » si manquant.
- 4.3b `projects.py` : colonne « Hebdo » + bandeau semaine courante (selon l'horloge du projet) + bouton « Avancer d'une semaine » si mode jeu.
- 4.3c `questionnaire.py` : bandeau « Semaine 2026-S24 », statut hebdo dans le dropdown nœud, confirmation mentionnant la semaine enregistrée.

#### Tests exigés
- `FixedClock` : trois nœuds (évalué cette semaine / il y a 2 semaines / jamais) ⇒ statuts exacts, `semaines_de_retard=2`.
- Bascule de semaine : évaluation dimanche 23:59 vs lundi 00:00 (heure locale) ⇒ semaines différentes.
- GameClock : `advance_weeks(1)` ⇒ tous les nœuds « à jour » passent « en retard ».
- Edge ISO : 2026-12-28 (S53) et 2021-01-01 (2020-S53) ; migration backfill correcte.

#### DoD
Badges sur les 3 pages ; statuts corrects sous horloge contrôlée ; aucune adéquation calculée contre un Ud inexistant. Tag `phase-E4`.

#### Risques
- Fuseaux : `isocalendar` sur heure locale Windows — convention « heure locale du poste » figée dans la doc.

---

### E5 — Wizard d'onboarding + fiche nœud 360°

**Objectif** : créer un nœud complet en 4 sections (budget humain 1-2 h), brouillon persisté EN BASE et repris, nœud visible « incomplet » dès l'étape 1, fiche nœud 360° rééditable par section. **Prérequis** : E2 (onboarding_progress, jalons, cdc, tags), E3 (mutations auditées `source='onboarding'`), E4 (badges).

**Machine à états du wizard** : état = `(node_id, current_step ∈ {1..4}, sections_done)` — **source de vérité : table `onboarding_progress`** ; le `dcc.Store` ne porte que `{node_id, step}`. Transitions :
- `start` → création immédiate du nœud (`onboarding_state='draft'`, contribution neutre au pipeline : ud_local/ur_local = 0, badgé « incomplet » partout) ;
- `save_section(k)` → validation (`constraints.py`) → écriture des entités réelles + `sections_done[k]=1` ; échec = messages par champ, RIEN n'est écrit (transaction) ;
- `save_draft(k)` → écrit `draft_json` SANS valider (« Enregistrer le brouillon et quitter ») ;
- étape 4 validée → `onboarding_state='complete'`, suppression de `onboarding_progress`, `evaluate_all(persist=True)` ;
- reprise : liste des nœuds `draft` avec badge x/4 → « Reprendre » recharge `draft_json` + sections validées.

Sections : **1** identité + type + tags + connexions (γ/β par arc, type nominal/backup) ; **2** cahier des charges (livrables/quantités, jalons datés, budget/coûts cibles, qualité/normes/rebut max/certifications, pénalités) ; **3** KPIs initiaux des 7 blocs (saisie guidée : unité, info-bulle, bornes affichées) ; **4** première évaluation AHP (réutilise `build_assessment`).

#### Lots
**Lot 5.1 — service** — `supplyscore/services/onboarding.py` (nouveau), `tests/test_onboarding_service.py` (nouveau)
```python
class OnboardingService:
    def start_draft(self, project_id, name, label) -> str          # node_id
    def load(self, node_id) -> OnboardingState                     # sections_done, draft, step
    def save_section(self, node_id, step: int, payload: dict, operator_id) -> SectionResult
    def save_draft(self, node_id, step: int, payload: dict) -> None
    def completeness(self, node_id) -> tuple[int, int]             # (faites, 4)
    def complete(self, node_id, operator_id) -> None
```

**Lot 5.2 — form-builders partagés** — `supplyscore/web_ui/components/forms_node.py` (nouveau), `tests/test_forms_node.py` (nouveau)
- `identity_form(node, tags_options)`, `cdc_form(cdc, milestones)` (lignes dynamiques de livrables/jalons en pattern-matching `{"type":"<ctx>-deliverable-name","index":i}` + boutons « + ligne »), `kpi_guided_form(kpis)` (réutilise `KPI_FIELDS` enrichi de `KPI_CONSTRAINTS`), + parseurs inverses `parse_identity(values, ids) -> dict`. Réutilisés par le wizard ET la fiche — **ids préfixés par contexte (`onb-` vs `fiche-`)** contre `DuplicateIdError`.

**Lot 5.3 — page wizard** — `supplyscore/web_ui/pages/onboarding.py` (nouveau), `tests/ui/test_onboarding_wizard.py` (nouveau)
- Stepper 4 étapes (en-têtes cliquables pour revenir à une section validée), contenu d'étape rendu serveur dans un conteneur unique `onb-step-content`, boutons « Étape précédente / Enregistrer et continuer / Brouillon et quitter ».

**Lot 5.4 — fiche nœud** — `supplyscore/web_ui/pages/node_detail.py` (nouveau), `tests/ui/test_node_detail.py` (nouveau)
- Route `/node/<id>` : cartes identité+tags, cahier des charges (+versions `spec_sheet`), jalons (timeline + barre avancement déclaré vs théorique), KPIs courants, évaluations AHP (dernière + historique Ud), événements, journal d'audit (composant E3.4). Chaque carte a « Modifier » → form-builder 5.2, sauvegarde via `OnboardingService.save_section` (mêmes validations, `source='edit'`).

**Tâche d'intégration E5.I (séquentielle)** — `web_ui/app.py` (routage paramétré : `if pathname.startswith("/node/")`, route `/onboarding`), `projects.py` (colonne « Complétude » + lien fiche), navbar ; test dash[testing] bout en bout : créer un nœud en 4 étapes, FERMER le navigateur à l'étape 2, reprendre, finir.

#### Tests exigés
- `start_draft` → nœud en base `onboarding_state='draft'` ; `save_section(2)` avec jalon `deadline_ts <= start_ts` → rejet, rien écrit ; reprise après `save_draft` → payload identique ; `complete()` impossible si une section manque.
- Le nœud draft apparaît au dashboard badgé « incomplet », A affiché « — ».
- Nœud complété → `evaluate_all` produit un Ur_local cohérent (cas chiffré : KPIs du test E2 → u_time 0.1587).

#### DoD
Onboarding complet < 30 min de manipulation (chronométré en test manuel scripté) ; fermeture navigateur à n'importe quelle étape sans perte ; chaque section rééditable depuis la fiche avec audit. Tag `phase-E5`.

#### Risques / pièges Dash
- **Ne JAMAIS porter le brouillon dans `dcc.Store`** (session perdue = brouillon perdu) : le Store ne contient que node_id/step ; sauvegarde de brouillon EXPLICITE (pas de `beforeunload` fiable en Dash).
- Callbacks `ALL` : les composants arrivent dans l'ordre du DOM — TOUJOURS trier par `id["index"]` ; index = uuid courts, jamais des entiers réutilisés (bug classique après suppression d'une ligne du milieu).
- `suppress_callback_exceptions=True` déjà posé (les composants d'étape n'existent pas tous au chargement) ; contrepartie : tests dash[testing] obligatoires pour attraper les fautes d'ids.

---

### E6 — Hebdo riche + moteur d'événements + journal des décisions

**Objectif** : rituel hebdomadaire 15-20 min PAR NŒUD en 4 volets, avec impacts d'événements calibrés/prévisualisés/réversibles, et journal des décisions pour l'analyse post-jeu. **Prérequis** : E2 (events, jalons), E3 (audit/réversibilité), E4 (iso_week, badges), E5 (fiche nœud, souple).

#### Lots
**Lot 6.1 — moteur d'événements** — `supplyscore/services/events.py` (nouveau), `tests/test_event_engine.py` (nouveau)
```python
class EventEngine:
    def __init__(self, registry, client_db_factory, mutations: MutationService, calibration, clock): ...
    def preview(self, node_id, event_type, params: dict) -> list[KpiImpact]    # PUR, rien écrit
    def apply(self, node_id, event_type, params, operator_id, notes="") -> SupplyEvent
        # 1 transaction : ligne events + update_kpis(source=f'event:{id}') + evaluate_all
    def revert(self, event_id, node_id, operator_id) -> list[KpiImpact]
        # chaque impact : si valeur courante == new → restaure old (source=f'revert:{event_id}')
        # sinon ConflictError(champs divergents) — AUCUNE restauration partielle silencieuse
    def open_events(self, node_id) -> list[SupplyEvent]    # non revertis, pour relance hebdo
```

**Lot 6.2 — revue hebdomadaire** — `supplyscore/services/weekly.py` (extension), `supplyscore/data/migrations.py` (table ci-dessous), `tests/test_weekly_review.py` (nouveau)
```python
class WeeklyReview:
    def kpi_diff(self, node_id, week) -> list[KpiRow]      # (path, libellé, unité, valeur S-1, valeur courante)
    def confirm_block(self, node_id, week, block, operator_id)      # « rien n'a changé »
    def confirm_milestone(self, milestone_id, status, progress, operator_id)
    def review_status(self, node_id, week) -> dict          # {volet: fait/à faire} → badge 4/4
    def start(self, node_id, week) / complete(self, node_id, week)  # mesure de la durée réelle
```
```sql
CREATE TABLE weekly_reviews (node_id TEXT NOT NULL, iso_week TEXT NOT NULL,
  volets_json TEXT NOT NULL, started_at REAL, completed_at REAL,
  PRIMARY KEY (node_id, iso_week));
```
- « Rien n'a changé » n'écrit AUCUN KPI mais une ligne d'audit `field='__confirmed__'` + la décroissance bayésienne optionnelle (`project_settings('events.decay')`).

**Lot 6.3 — journal des décisions** — `supplyscore/services/decisions.py` (nouveau), `supplyscore/data/migrations.py` (rattaché au lot 6.2 pour le fichier — la table ci-dessous est livrée avec celle de 6.2), `tests/test_decisions.py` (nouveau)
```sql
CREATE TABLE decisions (id TEXT PRIMARY KEY, node_id TEXT NOT NULL,
  iso_week TEXT NOT NULL, operator_id TEXT NOT NULL,
  description TEXT NOT NULL, scores_snapshot_json TEXT NOT NULL,  -- {ud, ur, a, f, h} au moment T
  created_at REAL NOT NULL);
CREATE INDEX idx_decisions_node_week ON decisions(node_id, iso_week);
```
- `DecisionService.record(node_id, description, operator_id) -> Decision` (snapshot automatique des scores courants du nœud), `list_decisions(node_id | project_id, iso_week=None)`. C'est l'instrument qui reliera décisions et scores a posteriori (calibration E11).

**Lot 6.4 — formulaires d'événements** — `supplyscore/web_ui/components/event_forms.py` (nouveau), `tests/test_event_forms.py` (nouveau)
- Dropdown type → formulaire de paramètres généré depuis `EVENT_CALIBRATION` (déclaratif : chaque EventSpec décrit champs, bornes, unités) ; « Prévisualiser » → tableau `KPI | avant | après | règle appliquée` ; « Confirmer » → apply. Liste des événements de la semaine avec « Annuler » (revert + message de conflit le cas échéant).

**Lot 6.5 — page hebdo** — `supplyscore/web_ui/pages/weekly.py` (nouveau), `tests/ui/test_weekly_page.py` (nouveau)
- Route `/hebdo` : sélection nœud → 4 volets en accordéon avec badge ✓ par volet :
  - **Volet 1 AHP** : sliders pré-remplis avec la semaine S−1 (conversion Saaty→bipolaire : `v = a−1` si `a≥1`, sinon `−(1/a − 1)`, arrondi entier — **test de bijection sur les 17 valeurs possibles**) + bouton « Confirmer à l'identique » (1 clic).
  - **Volet 2 diff KPI** : par bloc, tableau « valeur S−1 | nouvelle valeur (vide = inchangé) | unité » + « Rien n'a changé » par bloc et global.
  - **Volet 3 jalons** : ligne par jalon actif : statut, slider %, avancement théorique en regard (« théorique 62 % / déclaré 40 % → retard »).
  - **Volet 4 événements** : composant 6.4 + relance des `open_events` (« Grève déclarée en S−2 — toujours en cours ? Résoudre / Maintenir ») + carte « Décision prise cette semaine » (description libre → DecisionService).

**Tâche d'intégration E6.I (séquentielle)** — `app.py` (route, navbar), `questionnaire.py` conservé en « mode expert » (lien discret), badge global « hebdo 4/4 » branché sur E4 ; garde-fou double comptage : si un événement de la semaine a touché un KPI, le volet 2 affiche un avertissement sur ce champ ; parcours chronométré.

#### Tests exigés (cas chiffrés)
- EventEngine : `failure_probability=0.02`, panne majeure → preview `[0.02 → 0.0563]` ; apply puis revert immédiat → 0.02 restauré, 2 lignes d'audit (`event:` puis `revert:`) ; apply puis édition manuelle à 0.10 puis revert → `ConflictError` listant `risk.failure_probability`.
- `hausse_tarif` pct=12, tariff=1.05 → **1.176** ; `u_cost` recalculé (chaîne complète jusqu'au score).
- `kpi_diff` : modifier 2 KPIs en S−1 → le diff S affiche les bonnes valeurs précédentes ; champ vide → aucune écriture.
- Hypothesis : `apply` puis `revert` (sans écriture intermédiaire) = identité sur le KPIBundle, pour tout type et paramètres valides.
- Décisions : `record` capture exactement les scores affichés au moment T (égalité champ à champ avec l'UrgencyState courant).
- UI : parcours 4 volets complet ; « rien n'a changé » global → `weekly_reviews.completed_at` posé.

#### DoD
Parcours hebdo nominal (AHP confirmé, 0 KPI changé, jalons confirmés, 0 événement) ≤ **12 clics** ; durée médiane mesurée (started_at/completed_at) ≤ 20 min sur tests pilotes ; tout impact d'événement dans l'audit avec `source='event:<id>'` ; réversibilité garantie ou conflit explicite. Tag `phase-E6`.

#### Risques
- Double comptage événement + édition manuelle : garde-fou affiché, pas d'interdiction (l'opérateur reste souverain).
- Formulaire du volet 4 régénéré à chaque changement de type → conteneur dédié + `prevent_initial_call`, sinon cascade de callbacks au montage.

---

### E7 — Exports + sauvegarde minimale

**Objectif** : protéger et libérer les données du serious game — export complet pour analyse externe, sauvegarde manuelle sûre. **Prérequis** : E3 (toutes les tables finales du Jalon 1 existent). Dépendance : `openpyxl`.

#### Lots
**Lot 7.1 — exports** — `supplyscore/services/exports.py` (nouveau), `supplyscore/web_ui/pages/projects.py` (carte « Exporter »), `tests/test_exports.py` (nouveau)
- `ExportService.export_project(project_id, fmt: Literal["csv","xlsx"], dest_dir) -> Path` : un classeur xlsx multi-feuilles (ou un zip de CSV) — feuilles : `nodes`, `arcs`, `milestones`, `tags`, `urgency_history`, `assessments`, `kpi_snapshots`, `events`, `decisions`, `audit_log`, `weekly_reviews`. Encodage UTF-8 BOM pour Excel FR ; horodatage dans le nom (`SupplyScore_<projet>_AAAAMMJJ_HHMMSS.xlsx`).
- Bouton de téléchargement Dash (`dcc.Download`).

**Lot 7.2 — sauvegarde/restauration manuelles** — `supplyscore/data/backup.py` (nouveau), `supplyscore/tools/restore.py` (nouveau), `supplyscore/web_ui/pages/projects.py` est DÉJÀ pris par 7.1 → le bouton « Sauvegarder maintenant » est posé par la tâche d'intégration, `tests/test_data_backup.py` (nouveau)
- `ServiceSauvegarde.backup_all(db_dir) -> Path` : API SQLite native `conn.backup()` (cohérente même base ouverte) pour registre + toutes bases client → `SupplyScore_AAAAMMJJ_HHMMSS.zip` ; `PRAGMA integrity_check` avant archivage ; restauration : `python -m supplyscore.tools.restore <zip> [--db-dir]`. (La sauvegarde AUTOMATIQUE et la rétention arrivent en E17.)

**Tâche d'intégration E7.I (séquentielle)** : boutons câblés, test cycle créer → sauvegarder → corrompre → restaurer → états identiques ; test export : un projet de démo exporté → toutes les feuilles non vides, valeurs sondées identiques à la base.

#### DoD
Export xlsx complet en un clic ; cycle sauvegarde→restauration prouvé par test. Tag `phase-E7`.

---

### ✅ Critère de sortie du JALON 1

**Une session de serious game complète est jouable** : créer un projet (mode horloge « jeu ») → onboarder N nœuds au wizard (rang 0 à N, tags, jalons, KPIs, première AHP) → jouer des semaines (« Avancer d'une semaine ») → remplir les hebdos multi-joueurs (opérateurs identifiés) → déclarer événements et décisions → suivre Ud/Ur/A/F/H et leurs évolutions → exporter tout pour l'analyse. Suite de tests complète verte ; redémarrage du poste sans aucune perte.

---

## §5. JALON 2 — « Analyse & défendabilité »

> **Objectif du jalon** : chaque score est justifiable devant un décideur (explicabilité, preuves mathématiques), les données du jeu sont analysables (calibration prédiction/réalité, rapport de session), l'édition est libre mais sûre, et les méthodes avancées (FBWM/PROMETHEE, Monte Carlo) sont disponibles.

---

### E8 — Explicabilité : « pourquoi A = 32 »

**Objectif** : page par nœud décomposant exactement Ud (critères AHP), Ur_local (blocs KPI), la part propagation (quels fournisseurs poussent Ur, quels clients tirent Ud), l'équation d'adéquation instanciée, avec liens vers les versions d'audit. **Prérequis** : E2 (u_time v2 explicable), E3 (versions liées). **Parallélisable avec E9** (périmètres disjoints).

#### Décompositions mathématiques exactes (à reprendre telles quelles)
- **Ud (additive exacte)** : `Ud = Σ_j w_j·(s_j − 1)/8` ⇒ contribution du critère j : `κ_j = w_j·(s_j − 1)/8`, avec `Σκ_j = Ud` exactement.
- **Ur_local (additive exacte en log-survie)** : `Ur = 1 − S`, `S = Π_m (1−u_m)^ω_m`. Poser `ℓ_m = −ω_m·ln(1−u_m) ≥ 0` ⇒ `Ur = 1 − exp(−Σℓ_m)` et **part exacte du bloc m : `part_m = ℓ_m / Σ_k ℓ_k`** (somme 1 — additive dans l'espace log, où l'agrégation EST additive). Cas limite : `u_m ≥ 1−ε` (ε=1e-9) → les blocs saturés se partagent part=1 à parts égales. Afficher EN PLUS la contribution marginale intuitive `Δ_m = Ur − Ur_sans_m = S·((1−u_m)^{−ω_m} − 1)` (« sans ce bloc, Ur vaudrait… ») — non additive, étiquetée comme telle.
- **Propagation (même structure)** : `Ur_i = 1 − (1−Ur_loc_i)·Π_j(1−β_ji·Ur_j)` ⇒ `ℓ_loc = −ln(1−Ur_loc_i)`, `ℓ_j = −ln(1−β_ji·Ur_j)` ; `part_locale = ℓ_loc/Σ`, `part_fournisseur_j = ℓ_j/Σ`, part propagée totale = `Σ_j ℓ_j / (ℓ_loc + Σ_j ℓ_j)`. Symétrique pour Ud descendant avec `γ_ik·Ud_k` (quels CLIENTS tirent Ud). Dans u_time v2, la part du glissement de planning est directement `κ_r·r₊` (forme additive choisie exprès en E2).
- **Adéquation** : pas de décomposition additive — équation instanciée chiffrée : `e_under = [Ur−Ud]₊ = 0.31`, `e_over = 0`, `penalty = 2.25·0.31^0.88 = 0.804`, `A = 100·(e^{−0.804} − e^{−2.25})/(1 − e^{−2.25}) = 38.4` + phrase de gouvernance (sous-estimation pénalisée ×2.25).

#### Lots
**Lot 8.1 — moteur** — `supplyscore/core/explain.py` (nouveau), `tests/test_explain_math.py` (nouveau)
```python
@dataclass(frozen=True) class BlockContribution: block: str; u: float | None; omega: float; share: float; delta_without: float
@dataclass(frozen=True) class CriterionContribution: index: int; label: str; weight: float; score: float; contribution: float
@dataclass(frozen=True) class EdgeContribution: neighbor_id: str; neighbor_name: str; coeff: float; u_neighbor: float; share: float
@dataclass(frozen=True) class AdequationTrace: e_under: float; e_over: float; penalty: float; adequation: float; lambdas: tuple

def explain_ur_local(t, kpis, milestones, model: UrModel) -> list[BlockContribution]
def explain_ud(weights, scores) -> list[CriterionContribution]
def explain_propagation_up(node, predecessors, arcs) -> tuple[float, list[EdgeContribution]]
def explain_propagation_down(node, successors, arcs) -> tuple[float, list[EdgeContribution]]
def explain_adequation(ud, ur, engine: AdequationEngine) -> AdequationTrace
```
Invariants : `Σ share = 1` ; `|reconstruction − valeur pipeline| < 1e-12` (mêmes fonctions internes, mêmes constantes).

**Lot 8.2 — service** — `supplyscore/services/explain.py` (nouveau), `tests/test_explain_service.py` (nouveau)
- `ExplainService.explain_node(node_id) -> NodeExplanation` : assemble les 5 décompositions + versions liées (dernière évaluation AHP et sa correction éventuelle, dernières lignes d'audit des 2 blocs dominants, derniers changements de β/γ des arcs dominants, événements actifs). Pur en lecture.

**Lot 8.3 — figures** — `supplyscore/web_ui/components/explain_figures.py` (nouveau), `tests/test_explain_figures.py` (nouveau)
- `ur_waterfall_figure(contributions)` (Plotly Waterfall : 0 → blocs → Ur_local), `propagation_bars_figure(part_locale, edges)` (« local 30 % / Fournisseur X (β=0.8) 49 % / Fournisseur Y 21 % »), `ud_criteria_figure(criteria)`.

**Lot 8.4 — page** — `supplyscore/web_ui/pages/explain.py` (nouveau), `tests/ui/test_explain_page.py` (nouveau)
- Route `/node/<id>/explication` + onglet fiche : bandeau « A = 38.4 parce que Ud = 0.21 et Ur = 0.52 » ; 4 sections + équation d'adéquation ; chaque ligne de contribution cliquable → historique d'audit du KPI/critère concerné.

**Tâche d'intégration E8.I** — `node_detail.py` (onglet), `app.py` (route), `dashboard.py` (lien « pourquoi ? » par ligne).

#### Tests exigés (cas chiffrés)
- Ud : `w=(0.4,0.3,0.2,0.1)`, `s=(9,5,1,3)` → `Ud = 0.575` ; κ = (0.400, 0.150, 0.000, 0.025), Σ = 0.575 exactement.
- Ur_local : `u={time:0.5, risk:0.5}`, ω=1 → Ur=0.75, parts (0.5, 0.5), Δ chacun 0.25 ; `u={0.9, 0.1}` → ℓ=(2.3026, 0.1054), parts (0.9562, 0.0438), Ur=0.91.
- Propagation : `Ur_loc=0.2`, un fournisseur `Ur_j=0.5`, β=0.8 → `Ur_i=0.52` ; part propagée = `ln(0.6)/(ln(0.8)+ln(0.6))` = **0.696**.
- Saturation : un bloc à u=1 → part 1, Ur=1, pas de NaN (hypothesis : aucune entrée valide ne produit NaN/Inf).
- Hypothesis : reconstruction `1−exp(−Σℓ)` == `ur_local()` à 1e-12 sur KPIBundles aléatoires — **test de cohérence OBLIGATOIRE en CI** (toute divergence entre explain.py et ur_model.py détruit la défendabilité).

#### DoD
Page reconstruite < 200 ms pour tout nœud de la démo ; les valeurs re-additionnent exactement Ud/Ur du pipeline ; chaque contribution liée à ≥ 1 version d'audit consultable. Si Ur > 1 (retard avéré, ur_singularity) : affichage « retard avéré : u_time forcé à 1 » comme cause unique, pas de calcul de parts. Tag `phase-E8`.

---

### E9 — Durcissement mathématique complet

**Objectif** : prouver CHAQUE formule par (a) un cas de référence calculé à la main, (b) des invariants hypothesis, (c) une spécification formelle versionnée. **Prérequis** : E2 (u_time v2 et événements à couvrir). **Parallélisable avec E8.**

#### Lots (tous parallèles — tests/docs disjoints ; le code source n'est PAS modifié sauf lot 9.6 séquentiel en dernier)
**Lot 9.1 — spécification formelle** — `docs/modele_mathematique.md` (nouveau)
- Chaque formule (v1 + v2 : AHP, Ud, EMA, 6 blocs u_*, u_time v2, OR probabiliste, propagation, adéquation, BAYES/EMA des événements, statut dérivé) avec dérivation, domaine, bornes, références d'état de l'art (§1), et la **table des cas de référence chiffrés** (les mêmes valeurs que dans les tests — traçabilité croisée).
- **Trancher et documenter 2 ambiguïtés sémantiques** (faiblesses #11, #12) : (a) un nœud DONE a `Ur_loc=0` mais TRANSMET toujours l'urgence de ses fournisseurs vers l'aval, et son `ud_local` continue de se propager — voulu (le flux physique existe encore) ou à couper ? Décision + test dédié dans les deux cas. (b) `u_cost` : la dérive `(op_cost − nominal)/nominal` peut être négative (économie) et compense tarif/stockage avant le clip — « compensation autorisée » (documenter) ou `max(drift, 0)` ?

**Lot 9.2 — propriétés UrModel** — `tests/property/test_prop_ur_model.py` (nouveau)
- Cas analytiques : `u_time(μ=100, σ=20, slack=100) = 0.5` exactement ; `slack = μ+1.96σ = 139.2 ⇒ 0.0250 ± 5e-4` ; `σ=0, μ>slack ⇒ 1.0` ; `u_perf(OEE=0.9³=0.729) = 0.271` ; `u_risk(fp=0.1, rt=24, sev=1, T_ref=24) = 1−e^{−0.1} = 0.0951626`, avec `env=0.2` ⇒ `1−0.9048374×0.8 = 0.2761301` ; `u_co2(total=900, cible=600, max=1000) = 0.75` ; agrégation OU : deux blocs à 0.5, ω=1 ⇒ `1−0.25 = 0.75` ; un bloc 0.5 avec ω=2 ⇒ `0.75`.
- Invariants hypothesis (sur bundles valides) : tous les `u_* ∈ [0,1] ∪ {None}` ; `ur_local ∈ [0,1]` ; monotonies — `u_time` décroissante en slack, croissante en μ et en t ; `ur_local` croissante en chaque bloc ; `ω_m=0` ⇔ bloc ignoré ; `ur_local ≥ max_m(1−(1−u_m)^{ω_m})` (l'OU domine chaque contribution) ; statuts DONE/ABANDONED écrasent tout.

**Lot 9.3 — propriétés propagation** — `tests/property/test_prop_propagation.py` (nouveau)
- **Bornes** [0,1] partout ; **idempotence** (deux `propagate_all` successifs sans changement ⇒ valeurs bit-à-bit identiques) ; **monotonie** (augmenter un `ur_local` ne diminue aucun Ur ; idem Ud/γ) ; **localité** (modifier `ur_local(i)` ne change `Ur(k)` que si k atteignable depuis i — sinon delta exactement 0) ; **stabilité de l'ordre topologique** (même graphe, ordres d'insertion mélangés ⇒ résultats identiques à 1e-15) ; `simulate_shock(i, valeur_courante) ⇒ deltas = 0` ; γ=0 partout ⇒ `Ud = Ud_local` ; β=1 et fournisseur à 1 ⇒ client à 1.
- Stratégie : générateur de DAG aléatoires par rangs (réutiliser `RandomSupplyChainGenerator` seedé) + ud_local/ur_local/γ/β tirés dans [0,1].

**Lot 9.4 — propriétés AHP** — `tests/property/test_prop_ahp.py` (nouveau)
- Cas exacts : poids vrais `w=(0.4,0.3,0.2,0.1)`, matrice `a_ij=w_i/w_j` parfaitement cohérente ⇒ `priority_vector` retourne w exactement, `λmax=4`, `CR=0` ; matrice 2×2 `[[1,3],[1/3,1]]` ⇒ `w=(0.75,0.25)`.
- Propriétés : `Σw=1`, `w>0` ; invariance par permutation des critères ; `bipolar_to_saaty ∈ [1/9,9]` et `bipolar_to_saaty(−v)=1/bipolar_to_saaty(v)` ; `compute_ud ∈ [0,1]`, =0 ssi toutes notes =1, =1 ssi toutes =9 ; `ud_smoothed ∈ [min(prev,cur), max(prev,cur)]` ; documenter (9.1) que `priority_vector` est l'approximation « moyenne des colonnes normalisées », pas le vecteur propre exact, avec borne d'écart acceptée.

**Lot 9.5 — propriétés adéquation + événements + jalons** — `tests/property/test_prop_adequation.py`, `tests/property/test_prop_events.py`, `tests/property/test_prop_milestones.py` (nouveaux)
- Adéquation : `A(x,x)=100` ∀x ; `A(ud=1, ur=0) = 100·(e^{−1}−e^{−2.25})/(1−e^{−2.25}) = 29.34 ± 0.01` ; `A(0,1) = 0` exactement ; asymétrie `A(0.2,0.8) < A(0.8,0.2)` ; `F·H = 0` et `F−H = ud−ur` ∀(ud,ur) ; monotonie en |ud−ur| à direction fixée.
- Événements : `BAYES ∈ (0,1)`, croissante en k, point fixe k/n=p ; tous les impacts respectent `KPI_CONSTRAINTS` pour tout paramètre valide.
- Jalons : `u_time` v2 continue au passage des κ ; `derive_node_status` conforme à la table de vérité sur listes aléatoires.

**Lot 9.6 — séquentiel après 9.2-9.5 — corrections** — `supplyscore/core/*.py`, `supplyscore/graph/propagation.py` selon découvertes
- Tout écart découvert est corrigé ici (un seul agent, périmètre = fonctions fautives + tests), reporté dans `docs/modele_mathematique.md`. **Ne jamais affaiblir un invariant pour le faire passer** : tout échec = bug ou spec à clarifier, jamais une tolérance élargie en silence.

#### DoD
Chaque fonction publique de `core/` et `propagation.py` a ≥ 1 cas analytique chiffré + ≥ 1 propriété hypothesis ; doc exhaustive concordante avec les tests ; 2 décisions sémantiques tranchées/documentées/testées ; **couverture ≥ 90 % activée en bloquant** (`fail_under = 90`). Optionnel ambitieux : mutation testing (`mutmut`) sur `supplyscore/core`, mutants tués ≥ 90 %. Tag `phase-E9`.

#### Risques
- hypothesis + flottants : `allow_nan=False`, bornes explicites, tolérances `abs=1e-12` pour identités algébriques, `1e-9` pour compositions.

---

### E10 — Validation complète + édition à la volée + vue admin

**Objectif** : aucune valeur aberrante ne peut entrer (UI, service, ou appel direct) ; l'utilisateur édite tout, partout, en sécurité. **Prérequis** : E3 (MutationService — rien ne s'édite sans audit), E9 (invariants posés).

**Choix technique** : `dash_table.DataTable` éditable (zéro dépendance nouvelle, suffisant ≤ ~2 000 lignes avec pagination native ; périmètre réaliste 500 nœuds × 1 bloc ≤ 500 lignes). dash-ag-grid reste le plan B documenté si E14 mesure > 200 ms de re-render.

#### Lots
**Lot 10.1 — validation exhaustive** — `supplyscore/domain/validation.py` (nouveau, absorbe et étend `constraints.py`), `tests/test_domain_validation.py` (nouveau)
- `@dataclass ValidationIssue(champ, message_fr, severite: Literal["erreur","avertissement"])`.
- `validate_kpis(b) -> list[ValidationIssue]` : bornes par champ (ratios ∈ [0,1] ; durées/coûts ≥ 0 ; `tariff > 0` ; `max_volume/max_weight > 0` si renseignés ; NaN/±inf rejetés partout) + **avertissements croisés non bloquants** : `current_volume > max_volume`, `co2_target ≥ co2_max`, `deadline < lead_time` (retard quasi certain), `flow_rate` sans `demand`. Ne PAS transformer les avertissements en erreurs bloquantes (l'opérateur doit pouvoir enregistrer des situations anormales réelles).
- `validate_arc(a)` : `gamma, beta ∈ [0,1]`, `delta ∈ [0,2]` ; `validate_node` ; `validate_milestone` ; `validate_cdc`.

**Lot 10.2 — application côté service** — `supplyscore/services/orchestrator.py`, `tests/test_services_validation.py` (nouveau)
- `submit_assessment` **refuse côté serveur** `CR ≥ 0.10` (ValueError) — faiblesse #9.
- `add_node`/`create_project` valident nœud + arcs ; **`remove_node(node_id)`** (registre + repo, bases client conservées en archive) et **`remove_arc`**, avec **recalcul des rangs** (`repo.assign_ranks()` — faiblesse #10) puis réévaluation.

**Lot 10.3 — éditeur KPIs** — `supplyscore/web_ui/pages/editor.py` (nouveau), `tests/ui/test_kpi_editor.py` (nouveau)
- Tableau « KPIs courants » : filtres projet + bloc + tags ; lignes = nœuds, **chaque ligne porte un champ `id` stable = node_id** (clé de diff fiable). Callback sur `data_timestamp` + `State("data")` + `State("data_previous")` : diff cellule → validation → si invalide : cellule REMISE à l'ancienne valeur + toast d'erreur ; si valide : `MutationService.update_kpis(source='edit')` + `evaluate_all`. Renvoyer `no_update` quand la valeur est acceptée telle quelle (anti-scintillement).

**Lot 10.4 — éditeur de graphe** — `supplyscore/web_ui/pages/graph_editor.py` (nouveau), `tests/ui/test_graph_editor.py` (nouveau)
- Tableau des arcs (γ/β/δ éditables, type nominal/backup en dropdown), ajout/suppression d'arc avec `dcc.ConfirmDialog` + contrôle anti-cycle (le repo lève déjà ValueError) ; gestion des tags (création catégorie/tag, couleur, auto-complétion « créer "xyz" ») ; statuts. Tout via MutationService.

**Lot 10.5 — vue admin données brutes** — `supplyscore/services/raw_admin.py`, `supplyscore/web_ui/pages/admin_data.py` (nouveaux), `tests/test_raw_admin.py`, `tests/ui/test_admin_view.py` (nouveaux)
```python
class RawTableService:
    EDITABLE_TABLES = {"registry": {"nodes","arcs","milestones","tags","tag_categories","projects"},
                       "client":   {"assessments","spec_sheet","events"}}
    FORBIDDEN = {"audit_log","urgency_history","kpi_snapshots","weekly_reviews","decisions"}  # append-only
    def list_databases(self) / list_tables(self, db) / fetch(self, db, table, limit, offset)
    def update_cell(self, db, table, pk, column, new_value, operator_id) -> CellResult
        # validation type+bornes, audit source='edit', refus sinon (ForbiddenTableError sur FORBIDDEN)
```
- Page /admin : dropdown base → table → DataTable **lecture seule par défaut** ; interrupteur « Déverrouiller l'édition » + ConfirmDialog ; après chaque commit : re-validation de l'entité + `evaluate_all` avec rapport (« 1 cellule modifiée, revalidation OK, ΔUr max = 0.04 sur 3 nœuds »). Correction d'évaluations passées : « Corriger » une ligne assessments ouvre le formulaire AHP pré-rempli → `replace_assessment` (l'originale reste, `replaces_id` posé).

**Tâche d'intégration E10.I (séquentielle)** — `app.py` (routes /edition, /graph-editor, /admin), navbar ; **filtres par tags branchés sur dashboard/graphe/simulation** (+ paramètre `tag_filter` et coloration/groupement du DAG par catégorie dans `figures.py` — couleur de `tag_categories.color`) ; suppression nœud/arc exposée sur la page projets avec confirmation.

#### Tests exigés
- hypothesis : tout KPIBundle avec ≥ 1 champ hors borne ⇒ ≥ 1 erreur ; tout bundle valide ⇒ 0 erreur et `ur_local` ne lève jamais. Cas : `availability=1.2` rejeté ; `tariff=0` rejeté ; `deadline=100 < lead_time=200` ⇒ avertissement (pas erreur) ; `submit_assessment` CR=0.25 ⇒ ValueError, rien persisté.
- Diff de cellule : `data_previous` None (premier rendu) → no-op ; `failure_probability = 1.7` → rejet, cellule restaurée, 0 audit ; `= 0.05` → 1 audit + snapshot.
- `update_cell` sur `audit_log` → `ForbiddenTableError` ; suppression d'arc sans confirmation → rien ne change ; arc créant un cycle → message propre.
- Perf : tableau 500 lignes × 8 colonnes — édition d'une cellule < 500 ms aller-retour.

#### DoD
Impossible de persister une valeur hors contrat par l'UI ou le service ; toute édition auditée `source='edit'` avec opérateur ; tables append-only inéditables par construction ; filtres tags sur 4 pages ; rangs recalculés après mutation. Tag `phase-E10`.

#### Risques / pièges Dash
- `dcc.Input(type="number", min=, max=)` n'empêche PAS la saisie clavier hors borne dans tous les navigateurs — la validation serveur reste l'autorité.
- DataTable renvoie des chaînes même sur colonnes numeric — coercition `try/float` systématique côté serveur.
- `data_previous` n'est fiable que si l'ordre des lignes est stable : désactiver `sort_action` en mode édition OU differ par `id` de ligne, jamais par index.
- Un seul ConfirmDialog par page logique (les enchaîner crée des races) — action en attente portée dans un dcc.Store.

---

### E11 — Calibration prédiction/réalité + rapport de session

**Objectif** : l'instrument de mesure du serious game — « le score a-t-il aidé à décider ? le score H a-t-il prédit les vraies ruptures ? ». **Prérequis** : E6 (décisions, événements), E4 (semaines).

#### Lots
**Lot 11.1 — calibration** — `supplyscore/services/calibration.py` (nouveau), `tests/test_calibration.py` (nouveau)
- Définition d'une « issue défavorable » pour un nœud en semaine S+k : jalon raté (deadline dépassée sans DONE), statut ABANDONED, ou événement de gravité critique.
- `CalibrationService.outcomes(project_id, horizon_weeks=4) -> list[OutcomePoint]` : pour chaque (nœud, semaine S), apparie `hidden_risk(S)` (et Ur(S)) avec la survenue d'une issue défavorable dans [S+1, S+horizon].
- `confusion(threshold_h: float) -> ConfusionMatrix` (VP/FP/VN/FN, précision, rappel) ; `calibration_curve(n_bins=5) -> list[(h_moyen, taux_observé)]` (le score est-il calibré ?) ; `summary()` en français.
- Cas de test synthétique chiffré : 10 nœuds-semaines construits à la main (4 H>0.5 dont 3 avec rupture ; 6 H<0.5 dont 1 avec rupture) ⇒ à seuil 0.5 : VP=3, FP=1, FN=1, VN=5, précision=0.75, rappel=0.75.

**Lot 11.2 — rapport de session** — `supplyscore/services/report.py` (nouveau), `supplyscore/web_ui/pages/report.py` (nouveau), `tests/test_report.py` (nouveau)
- `SessionReport.build(project_id) -> str` (HTML autonome imprimable, gabarit Jinja2 — déjà dépendance de Flask) : en-tête projet + période ; évolution Ud/Ur/A par nœud (figures Plotly en `to_html(include_plotlyjs="cdn")` ou images statiques) ; chronologie des événements et décisions (avec scores au moment T) ; tableau de calibration (11.1) ; graphe final. Route `/rapport` + bouton « Générer le rapport » → `dcc.Download` du HTML.

**Tâche d'intégration E11.I** : liens navbar/dashboard, test bout-en-bout sur une partie simulée (seed_demo + GameClock avancé de 6 semaines + événements injectés ⇒ rapport non vide, matrice de confusion calculée).

#### DoD
Rapport HTML complet généré en un clic sur une partie de démo ; matrice de confusion et courbe de calibration exactes sur le cas synthétique. Tag `phase-E11`.

#### Risques
- Échantillons petits (un serious game = quelques dizaines de nœuds-semaines) : afficher les effectifs à côté de chaque taux, jamais de pourcentage seul.

---

### E12 — MCDA : FBWM (pondération) + PROMETHEE II (classement)

**Objectif** : (a) FBWM pour pondérer les 6 blocs KPI d'Ur avec 2n−3 comparaisons (là où l'AHP exigerait n(n−1)/2) — les poids alimentent `UrModel.omega` par projet ; (b) PROMETHEE II pour un classement multicritère des nœuds « à traiter en priorité ». **Prérequis** : E9 (gabarit de preuve), E4 (rattachement hebdo des pondérations). Dépendance : `scipy>=1.13,<2`. **Parallélisable avec E13.**

**Frontière à respecter (noir sur blanc)** : l'AHP reste sur le questionnaire Ud (4 critères, il y est pertinent) ; FBWM pondère les blocs KPI d'Ur. On ne remplace PAS l'un par l'autre.

#### Lots
**Lot 12.1 — PROMETHEE II** — `supplyscore/mcda/__init__.py`, `supplyscore/mcda/promethee.py` (nouveaux), `tests/test_mcda_promethee.py`, `tests/property/test_prop_promethee.py` (nouveaux)
- `class FonctionPreference(ABC)` avec les 6 types de Brans–Vincke : Usuelle `P(d)=1 si d>0` ; U-shape (seuil q) ; V-shape `P=min(d/p,1)` ; Palier ; **Linéaire avec indifférence (type V, DÉFAUT)** `P=0 si d≤q ; (d−q)/(p−q) si q<d≤p ; 1 si d>p` avec `q=0.05, p=0.30` (critères dans [0,1]) ; Gaussienne `P=1−exp(−d²/2s²)`.
- `class PrometheeII(criteres: list[Critere], poids)` ; `Critere(nom, sens: "max"|"min", fonction)` ; `classer(valeurs: dict[alt_id, dict[critere, float|None]]) -> ResultatPromethee` avec `π(a,b)=Σ_j w_j·P_j(d_j(a,b))`, `φ⁺(a)=1/(n−1)·Σ_{b≠a} π(a,b)`, `φ⁻(a)=1/(n−1)·Σ π(b,a)`, `φ=φ⁺−φ⁻`.
- **Valeurs manquantes** (règle mot pour mot) : pour chaque paire (a,b) et critère j où l'une des deux valeurs manque, `P_j=0` dans les deux sens et renormalisation des poids sur les critères présents pour CETTE paire.
- Cas analytique calculé à la main : 3 alternatives, 2 critères max, fonction usuelle, `g1=(0.8, 0.5, 0.2)` poids 0.6, `g2=(0.1, 0.4, 0.7)` poids 0.4 ⇒ `φ(A)=+0.2, φ(B)=0.0, φ(C)=−0.2`.
- Propriétés : `Σ_a φ(a)=0` toujours ; `φ ∈ [−1,1]` ; améliorer une alternative sur un critère « max » ne diminue jamais son φ ; invariance par translation ; **renversement de rang documenté** (ajouter une alternative PEUT inverser deux rangs : test descriptif, pas un invariant).

**Lot 12.2 — FBWM** — `supplyscore/mcda/fbwm.py` (nouveau), `tests/test_mcda_fbwm.py`, `tests/property/test_prop_fbwm.py` (nouveaux)
- Nombres flous triangulaires (l,m,u) ; échelle linguistique (Guo & Zhao 2017) : Également important (1,1,1) ; Faiblement (2/3,1,3/2) ; Assez (3/2,2,5/2) ; Très (5/2,3,7/2) ; Absolument (7/2,4,9/2).
- Entrées : critère Meilleur B, critère Pire W, vecteurs `ã_Bj` (Best-to-Others) et `ã_jW` (Others-to-Worst).
- Optimisation : variables `(l_j, m_j, u_j)` ∀j + `ξ` ; `min ξ` sous `|w̃_B ⊘ w̃_j − ã_Bj| ≤ (ξ,ξ,ξ)`, `|w̃_j ⊘ w̃_W − ã_jW| ≤ (ξ,ξ,ξ)` (division NFT approchée `(l₁/u₂, m₁/m₂, u₁/l₂)`), `Σ_j R(w̃_j) = 1` avec défuzzification GMIR `R(w̃)=(l+4m+u)/6`, `0 ≤ l_j ≤ m_j ≤ u_j`. Résolution `scipy.optimize.minimize(method="SLSQP")`, **multi-départs (5 points initiaux seedés)**.
- Cohérence : `CR = ξ*/CI(ã_BW)` avec table CI : (1,1,1)→3.00 ; (2/3,1,3/2)→3.80 ; (3/2,2,5/2)→5.29 ; (5/2,3,7/2)→6.69 ; (7/2,4,9/2)→8.04 ; acceptation `CR < 0.10`.
- Cas analytique : cas crisp dégénéré (l=m=u), 3 critères, `a_B=(1,2,4)`, `a_W=(4,2,1)` cohérent (`a_13=a_12·a_23`) ⇒ `w=(4/7, 2/7, 1/7)` et `ξ*=0`.
- Propriétés : `Σ R(w̃_j)=1` ; `R(w̃_j)>0` ; invariance par permutation des « Others » ; cohérent ⇒ `ξ* < 1e-6` ; échec de convergence → message FR + repli sur poids uniformes (JAMAIS de crash).

**Lot 12.3 — séquentiel après 12.1+12.2 — intégration service** — `supplyscore/services/orchestrator.py`, `supplyscore/data/db.py` (lecture/écriture project_settings), `tests/test_services_mcda.py` (nouveau)
- `set_poids_criteres(project_id, poids, methode, xi_star, iso_week)` → `project_settings['omega_ur']` ; `evaluate_all` construit `UrModel(omega=poids_du_projet)` (le ω de l'OU probabiliste devient pilotable par FBWM, sans toucher aux formules).
- `classement_promethee(project_id) -> ResultatPromethee` : alternatives = nœuds actifs, critères = les 6 urgences de bloc `UrModel.blocks(t, kpis)` (sens « max »), poids = mêmes ω normalisés.

**Lots 12.4a/12.4b — parallèles après 12.3 — UI**
- 12.4a : `supplyscore/web_ui/pages/ponderation.py` (nouvelle page), `app.py` (+route), `components/layout.py` (navbar) — questionnaire FBWM : choix Meilleur/Pire parmi les 6 blocs, 2n−3 dropdowns linguistiques, aperçu live des poids + ξ*/CR, enregistrement par projet et semaine.
- 12.4b : `dashboard.py` + `components/figures.py` — carte « Priorités PROMETHEE II » : barres φ triées top-10, info-bulle φ⁺/φ⁻ ; **carte diagnostique « corrélation des critères »** avec avertissement si |ρ| > 0.8 entre deux critères de poids fort (PROMETHEE double-compte l'information corrélée — coût↔risque↔temps souvent corrélés en supply chain).

#### DoD
Poids FBWM persistés par projet et injectés dans Ur (test bout-en-bout : changer les poids change `ur_local` conformément à la formule OU) ; classement PROMETHEE au dashboard ; tous les cas analytiques verts ; reproductibilité seedée du solveur. Tag `phase-E12`.

---

### E13 — Monte Carlo / DBN pour le lead time

**Objectif** : remplacer (en option, PAR PROJET) `u_time` analytique par une **simulation Monte Carlo des dates d'achèvement propagées sur le DAG** (PERT stochastique : la distribution d'achèvement de chaque nœud est conditionnée par celles de ses fournisseurs). **Prérequis** : E2 (jalons = vraies deadlines), E9 (référence analytique). **Parallélisable avec E12.**

#### Modèle (à figer dans docs/modele_mathematique.md)
- Lead time du nœud i : `L_i` de famille configurable — **lognormale (DÉFAUT)** paramétrée par moments : pour moyenne `m=lead_time_h` et écart-type `s=lead_time_std_h` : `σ²_ln = ln(1+s²/m²)`, `μ_ln = ln m − σ²_ln/2` ; **normale tronquée à 0** ; **triangulaire** (3 nouveaux champs optionnels `time.lead_time_min_h / lead_time_mode_h / lead_time_max_h`) ; **déterministe** (s=0).
- Récurrence sur le DAG (ordre topologique) : `S_i = max_{j∈Pred(i)} C_j` (0 si aucun fournisseur), `C_i = S_i + L_i`. Estimateur : `u_time_MC(i) = P(C_i > d_i) ≈ (1/N)·Σ_k 1[C_i^{(k)} > d_i]` avec `d_i` = deadline du prochain jalon actif.
- Tirages : `numpy.random.Generator(PCG64(seed))`, **N=10 000 par défaut** (erreur-type ≤ `0.5/√N = 0.005`), configurable 2 000–50 000 ; **graine stable par (project_id, semaine ISO)** — le dashboard ne « clignote » pas d'un rafraîchissement à l'autre ; IC95 affiché : `p̂ ± 1.96·√(p̂(1−p̂)/N)`.
- Vectorisation : un tableau `(N,)` par nœud, `C = np.maximum.reduce([C_j…]) + tirages` ; mémoire ~80 Mo pour 1 000 nœuds × 10 000 tirages float64 — **garde-fou `n_tirages × n_nœuds ≤ 5·10⁷`**, sinon traitement par rangs.

#### Lots
**Lot 13.1 — moteur MC** — `supplyscore/mc/__init__.py`, `supplyscore/mc/lead_time.py` (nouveaux), `tests/test_mc_lead_time.py`, `tests/property/test_prop_mc.py` (nouveaux)
- `class SimulateurLeadTime(repo, n_tirages=10_000, graine=None)` ; `executer(t) -> ResultatMC` avec `.u_time: dict[node_id, float]`, `.ic95`, `.dates_achevement_quantiles(q)`.
- Tests analytiques : nœud isolé, normale (μ=100, σ=20), slack=100 ⇒ `p̂ = 0.5 ± 0.015` (3 erreurs-types à N=10⁴) ; **convergence vers la formule erf de `UrModel.u_time` à N=100 000 dans ±0.005 — LA validation croisée MC↔analytique, test le plus important de la phase** ; chaîne déterministe 10+20+30 h, deadline 55 ⇒ p=1.0 exactement, deadline 65 ⇒ p=0.0 ; diamant (chemins parallèles déterministes 40 et 50) ⇒ `C_final = 50 + L_final`.
- Propriétés : `u_time ∈ [0,1]` ; reproductibilité bit-à-bit à graine égale ; monotonie stochastique (augmenter la deadline ⇒ p̂ non croissant ; ajouter un prédécesseur ⇒ p̂ non décroissant, tolérance 3·erreur-type) ; lognormale : moments empiriques retrouvent (m, s) à 2 % près à N=10⁵.
- **Interdit** : tout raccourci analytique dans la propagation MC (le max de lognormales n'est PAS lognormale).

**Lot 13.2 — parallèle (contrat figé) — point d'extension UrModel** — `supplyscore/core/ur_model.py`, `tests/test_core_ur.py`
- `UrModel.blocks(t, kpis, milestones=None, u_time_override: float | None = None)` et `ur_local(..., u_time_override=None)` : si fourni, le bloc time prend cette valeur (clipée [0,1]). Aucune autre modification.

**Lot 13.3 — séquentiel après 13.1+13.2 — orchestration** — `supplyscore/services/orchestrator.py`, `tests/test_services_mc.py` (nouveau)
- `project_settings['lead_time'] = {"mode": "analytique"|"monte_carlo", "n_tirages": 10000, "graine": null}` ; `evaluate_all` : si mode MC, exécute le simulateur UNE fois pour tout le graphe puis passe `u_time_override` nœud par nœud. `simulate_shock` reste analytique (rapidité) — documenté.

**Lot 13.4 — UI** — `projects.py` (carte « Paramètres du calcul » : mode, N, graine), `dashboard.py` (mention « u_time : Monte Carlo, N=10 000, IC95 ±0.010 » + IC dans le hover), `weekly.py` (3 champs triangulaires optionnels au volet 2), `tests/test_webui_mc.py` (nouveau)

#### DoD
Mode MC activable par projet SANS régression du mode analytique (tests d'intégration paramétrés sur les deux modes) ; validation croisée MC↔erf verte ; temps d'exécution MC consigné (contraint en E14). Tag `phase-E13`.

#### Risques
- Ne jamais comparer MC à l'analytique à tolérance fixe : toujours en multiples de l'erreur-type, sinon tests flaky.

---

## §6. JALON 3 — « Industrialisation »

> **Objectif du jalon** : tenir 1 000+ nœuds sans broncher, simuler des scénarios composites, blinder l'UI, et livrer un poste exploitable des mois sans intervention.

---

### E14 — Performance : > 500 nœuds sans broncher

**Objectif** : tenir 1 000+ nœuds sur toutes les opérations (chargement, propagation, évaluation persistée, MC, rendu, tables, audit). Positionné APRÈS E12/E13 : on optimise les chemins de calcul définitifs, pas un profil intermédiaire. **Prérequis** : E1 (LRU/lifecycle), E12, E13. Dépendance dev : `pytest-benchmark`.

#### Budgets de performance (critères de sortie tels quels ; marges ×3 en CI)
| Opération @ 1 000 nœuds / ~2 500 arcs | Budget |
|---|---|
| `load_graph_from_registry` | < 1.5 s |
| `propagate_all` (complet) | < 80 ms |
| propagation incrémentale (1 nœud changé, ~50 descendants) | < 5 ms |
| `evaluate_all(persist=True)` | < 2.5 s |
| Monte Carlo N=10 000 | < 2 s |
| Construction figure DAG dashboard | < 300 ms |
| `simulate_shock` | < 30 ms |
| Édition d'une cellule DataTable (aller-retour) | < 500 ms |

#### Lots
**Lot 14.1 — bancs + générateur de stress** — `tests/benchmarks/test_bench_propagation.py`, `test_bench_db.py`, `test_bench_figures.py`, `test_bench_mc.py` (nouveaux), `supplyscore/data/generator.py` (+`generate_stress(n_nodes=1000, largeur_rang=40, p_arc_croise=0.25, seed)` — DAG large et profond, KPIs complets, jalons, tags)
- Marqueur `@pytest.mark.benchmark`, exclus du run rapide, exécutés par `scripts/ci.ps1 -Benchmarks`. **Les bancs DB tournent sur `%TEMP%`** (jamais dans le dossier synchronisé cloud — faiblesse #21).

**Lot 14.2 — écriture par lots SQLite** — `supplyscore/data/db.py`, `tests/test_data_batch.py` (nouveau)
- `ClientDatabase.save_urgency_states(states)` en UNE transaction `executemany` ; `RegistryDatabase.save_nodes(nodes)` / `save_urgencies(...)` par lots (faiblesse #14 : O(N) commits) ; index `idx_assessments_node_ts`, `idx_urgency_node_ts`, `idx_snapshots_node_ts` (migration — faiblesse #15) ; `PRAGMA synchronous=NORMAL` (avec WAL).

**Lot 14.3 — rendu graphe + tables** — `supplyscore/web_ui/components/figures.py`, `pages/dashboard.py`, `pages/projects.py`, `tests/test_webui_perf.py` (nouveau)
- **Supprimer les annotations Plotly par arc** (O(E) annotations = le tueur de perf principal, faiblesse #13) → une seule trace de segments ; direction indiquée par un marqueur au ⅔ de l'arête, pas par `annotations`.
- `go.Scattergl` pour nœuds ET arêtes au-delà du seuil constant `SEUIL_WEBGL = 200` ; étiquettes texte désactivées au-delà (hover uniquement — Scattergl rend mal le texte) ; positions mises en cache par (ids, rangs). Max 2 graphes WebGL par page (limite ~8 contextes par onglet).
- DataTables : `page_size=25`, `page_action="native"`, `filter_action="native"`, `virtualization=True` au-delà de 200 lignes.
- Mesurer aussi le re-render de l'éditeur E10 → si > 200 ms : arbitrer le plan B dash-ag-grid ICI.

**Lot 14.4 — séquentiel après 14.1/14.2 — propagation incrémentale** — `supplyscore/graph/propagation.py`, `supplyscore/graph/memory_repo.py`, `supplyscore/services/orchestrator.py`, `tests/test_graph_incremental.py`, `tests/property/test_prop_incremental.py` (nouveaux)
- `memory_repo` : cache de l'ordre topologique (invalidé sur mutation de structure), `descendants(node_id)`, `ancestors(node_id)` (via `nx.descendants/ancestors`).
- `PropagationEngine` : ensembles sales `_dirty_ur: set[str]`, `_dirty_ud: set[str]` alimentés par l'orchestrateur (`submit_assessment` → dirty_ud(i) ; changement KPI/statut → dirty_ur(i)) ; `propagate_incremental()` : `Affectés_Ur = ⋃_{s∈dirty} ({s} ∪ descendants(s))`, recalcul en ordre topologique restreint, les Ur des prédécesseurs non affectés lus du cache ; symétriquement `Affectés_Ud = ⋃ ({s} ∪ ancestors(s))`. Mutation de structure ⇒ invalidation totale.
- **L'invariant central de la phase (hypothesis)** : pour toute séquence aléatoire de modifications (ud_local, ur_local, statuts) sur un DAG aléatoire, `propagate_incremental` == `propagate_all` à 1e-12 sur tous les nœuds. Le piège classique est le nœud « frontière » dont un seul prédécesseur est affecté — le test d'équivalence le couvre, ne pas s'en passer.

#### DoD
Tous les budgets tenus sur le DAG de stress 1 000 nœuds (rapport pytest-benchmark archivé dans `docs/benchmarks/`) ; équivalence incrémental/complet prouvée ; l'app reste fluide (< 2 s par interaction) sur une démo 1 000 nœuds. Tag `phase-E14`.

---

### E15 — Simulation avancée : multi-chocs, scénarios, criticité

**Objectif** : passer du choc unitaire au scénario composite (plusieurs nœuds, statuts, ruptures d'arcs), avec analyse systématique de criticité. **Prérequis** : E14 (la criticité = N propagations partielles, infaisable confortablement sans l'incrémental) ; E13 souple (chocs sur lead time si mode MC).

#### Lots
**Lot 15.1 — moteur de scénarios** — `supplyscore/graph/scenario.py` (nouveau), `tests/test_graph_scenario.py`, `tests/property/test_prop_scenario.py` (nouveaux)
- `@dataclass Scenario(nom, surcharges_ur: dict[str, float], statuts: dict[str, TaskStatus], arcs_supprimes: list[tuple[str, str]], multiplicateurs_lead_time: dict[str, float])` ; `class MoteurScenario(repo, propagation): evaluer(s) -> ResultatScenario` (deltas Ud/Ur/A par nœud, JAMAIS de persistance — calcul sur surcharges sans copier le graphe).
- **Cas analytique chiffré** (chaîne C→B→A des tests existants, β=(0.5, 0.7), ur_loc=(0.6, 0.3, 0.1)) : baseline `Ur_A=0.4213` ; choc C→1 seul : `ΔUr_A=+0.0882` ; choc B→1 seul : `ΔUr_A=+0.3087` ; **double choc {B→1, C→1} : `ΔUr_A=+0.3087` ≠ somme 0.3969** — la non-additivité est un cas de test exact ET un encart pédagogique dans l'UI.
- Propriétés : scénario vide ⇒ deltas nuls ; monotonie (un choc aggravant de plus ne diminue aucun ΔUr) ; suppression d'arc (s→t) ⇒ ΔUr nul sur tout nœud non descendant de t ; état du graphe bit-à-bit inchangé après évaluation (pureté, test espion sur les écritures).
- Les 14 types d'événements (E2) sont proposés comme **chocs prédéfinis** (presets de scénario).

**Lot 15.2 — criticité** — `supplyscore/services/criticite.py` (nouveau), `tests/test_services_criticite.py` (nouveau)
- `indice_criticite(project_id) -> list[tuple[node_id, float]]` : pour chaque nœud actif i, choc `ur_local(i)→1.0`, mesure du `ΔUr` du client final (rang 0) — via propagation incrémentale (descendants de i seulement). Tri décroissant. Complexité O(Σ|desc(i)|).

**Lot 15.3 — parallèle — persistance des scénarios** — `supplyscore/data/db.py` + migration (table `scenarios(id, project_id, nom, payload_json, created_at)`), `tests/test_data_scenarios.py` (nouveau)

**Lot 15.4 — séquentiel après 15.1–15.3 — UI** — `supplyscore/web_ui/pages/simulation.py`, `components/figures.py`, `tests/test_webui_simulation.py` (nouveau)
- Constructeur de scénario : liste dynamique de chocs (pattern-matching `{"type": "choc-ur", "index": i}` — les lignes dynamiques sortent d'un Output children unique), tableau comparatif baseline/scénario, **graphique tornado de criticité (top-15)**, sauvegarde/rechargement de scénarios nommés, export PNG natif Plotly. Séparation visuelle stricte « simuler » vs « appliquer réellement » (bouton rouge + ConfirmDialog) conservée.

#### DoD
Scénario 3 chocs + 1 arc rompu sur graphe 1 000 nœuds évalué < 100 ms ; criticité complète 1 000 nœuds < 2 s ; non-additivité testée et affichée ; aucune écriture en base pendant un what-if (test espion). Tag `phase-E15`.

---

### E16 — UX, robustesse UI et tests navigateur

**Objectif** : aucune exception n'atteint l'utilisateur sans message français ; les parcours critiques sont couverts par des tests navigateur réels. **Prérequis** : toutes les pages finales (E5, E6, E10, E11, E12, E15). Dépendance dev : `dash[testing]` + Chrome/chromedriver (`webdriver-manager` ou version figée).

#### Lots
**Lot 16.1 — séquentiel en premier — garde-fous d'erreur** — `supplyscore/web_ui/errors.py` (nouveau), `supplyscore/web_ui/app.py`, `tests/test_webui_errors.py` (nouveau)
- Décorateur `protege_callback(fn)` : try/except, log complet (`infra.logging`), retour d'un composant d'erreur FR (« Une erreur est survenue : … Consultez logs/supplyscore.log ») **dimensionné au nombre d'Outputs du callback (introspection de la signature — sinon Dash lève une seconde erreur qui masque la première)** ; appliqué via le `register_callbacks` de chaque page.

**Lots 16.2–16.6 — parallèles — polissage par page** (un agent par page, fichiers disjoints)
- 16.2 `dashboard.py` : `dcc.Loading` sur DAG/tableau, états vides explicites, **palette daltonisme** (RdYlGn est hostile aux deutéranopes : option `RdYlBu`/viridis persistée dans `project_settings`).
- 16.3 `weekly.py` + `ponderation.py` : indicateurs de progression (x/6 paires), désactivation du bouton pendant l'enregistrement, focus des erreurs.
- 16.4 `projects.py` + `onboarding.py` : confirmations de suppression, libellés d'aide, formatage FR des nombres à l'AFFICHAGE (virgule décimale — PAS dans les inputs, Dash exige le point).
- 16.5 `node_detail.py` + `explain.py` : loading, cohérence visuelle.
- 16.6 `editor.py` + `graph_editor.py` + `admin_data.py` + `simulation.py` : loading + cohérence (le gros est déjà fait en E10/E15).

**Lot 16.7 — tests navigateur** — `tests/ui/test_e2e_parcours.py`, `tests/ui/conftest.py` (nouveaux)
- `dash.testing` (fixture `dash_duo`, Chrome headless), 8 parcours : (1) générer démo → dashboard non vide ; (2) wizard onboarding complet 4 étapes ; (3) wizard interrompu à l'étape 2 → repris → fini ; (4) hebdo 4 volets avec événement prévisualisé/appliqué → badge « À jour » ; (5) enregistrement refusé si opérateur vide ; (6) édition de cellule rejetée (hors borne) → cellule restaurée ; (7) simulation multi-chocs → figures non vides ; (8) page d'explication → contributions sommant au score affiché. Marqueur `@pytest.mark.ui`, exécutés par `scripts/ci.ps1 -Ui` (suite séparée, ne bloque pas la CI rapide).

#### DoD
100 % des callbacks décorés (test par introspection de l'app) ; 8 parcours navigateur verts en headless ; aucun texte anglais visible (test grep sur les layouts). Tag `phase-E16`.

---

### E17 — Packaging local, sauvegardes automatiques, manuel

**Objectif** : installation et exploitation mono-poste propres : données hors dossier synchronisé, sauvegardes automatiques restaurables, lanceur en un clic, manuel français. **Prérequis** : tout le reste (on fige).

#### Lots
**Lot 17.1 — emplacement des données** — `run_app.py`, `supplyscore/services/orchestrator.py`, `supplyscore/infra/paths.py` (nouveau), `tests/test_infra_paths.py` (nouveau)
- `platformdirs` : défaut `%LOCALAPPDATA%\SupplyScore\data` (les bases SQLite WAL dans un dossier cloud-sync sont un risque réel de corruption — faiblesse #21, résidus -wal/-shm déjà constatés) ; `--db-dir` reste prioritaire ; **assistant de migration au premier lancement** (déplace `data_store/` existant après sauvegarde).

**Lot 17.2 — sauvegardes automatiques** — `supplyscore/data/backup.py` (extension d'E7), `supplyscore/web_ui/pages/projects.py` (carte « Sauvegarde »), `tests/test_data_backup_auto.py` (nouveau)
- Déclenchement au démarrage (si > 24 h depuis la dernière) + bouton UI ; **rétention 20** ; `PRAGMA integrity_check` avant archivage ; restauration testée : créer → sauvegarder → corrompre → restaurer → états identiques.

**Lot 17.3 — packaging** — `pyproject.toml` (entry point `supplyscore = "supplyscore.cli:main"`, version unique dans `supplyscore/__init__.py`), `supplyscore/cli.py` (nouveau, absorbe run_app), `scripts/Installer.ps1`, `scripts/SupplyScore.ps1` + `.bat` (lanceur : démarre le serveur, attend le port, ouvre le navigateur via `webbrowser`), `CHANGELOG.md`
- Option PyInstaller (one-folder) documentée non bloquante — pièges consignés : `--collect-data dash --collect-data plotly`, hiddenimports des pages.

**Lot 17.4 — manuel** — `docs/manuel_utilisateur.md` (FR, captures, **chapitre dédié « animer un serious game »** : créer le projet en mode jeu, onboarder les joueurs, avancer les semaines, déclarer événements/décisions, générer le rapport), `docs/exploitation.md` (sauvegarde/restauration, logs, migration), `README.md` (mise à jour finale).

#### DoD
Installation depuis zéro sur un poste vierge en suivant uniquement le manuel : < 10 minutes, app fonctionnelle ; cycle sauvegarde→restauration prouvé ; `git tag v2.0.0`. Tag `phase-E17`.

---

## §7. Matrice de dépendances et protocole d'exécution

### Matrice (● = dépendance dure, ○ = souple)

| Phase | Dépend de (dur) | Souple | Parallélisable avec |
|---|---|---|---|
| E0 socle | — | — | — |
| E1 assainissement+horloge | E0 | — | — |
| E2 domaine v2 | E1 | — | — |
| E3 audit | E1, E2 | — | — |
| E4 hebdo ISO | E1, E3 | — | E5 (fichiers disjoints) |
| E5 wizard+fiche | E2, E3 | E4 (badges) | E4 |
| E6 hebdo riche+décisions | E2, E3, E4 | E5 (fiche) | — |
| E7 exports+backup min | E3, E6 (tables finales) | — | — |
| E8 explicabilité | E2, E3 | E9 | **E9** |
| E9 durcissement math | E2 | — | **E8** |
| E10 validation+édition | E3, E9 | E8 | — |
| E11 calibration+rapport | E4, E6 | — | E12, E13 |
| E12 FBWM+PROMETHEE | E9, E4 | — | **E13**, E11 |
| E13 Monte Carlo | E2, E9 | E4 (graine hebdo) | **E12**, E11 |
| E14 performance | E12, E13, E1 | E10 (éditeur à mesurer) | — |
| E15 multi-chocs | E14 | E13 (chocs lead time) | E16 partiellement (pages ≠ simulation) |
| E16 UX+navigateur | E5, E6, E10, E11, E12, E15 | — | — |
| E17 packaging | E16 | toutes | — |

**Chemin critique** : E0 → E1 → E2 → E3 → {E4 ∥ E5} → E6 → E7 **[fin Jalon 1]** → {E8 ∥ E9} → E10 → {E11 ∥ E12 ∥ E13} **[fin Jalon 2]** → E14 → E15 → E16 → E17 **[fin Jalon 3]**.

Volumétrie indicative : ~55 lots, dont ~35 parallélisables au sein de leurs phases. Les fichiers les plus contendus (`orchestrator.py`, `db.py`, `migrations.py`) sont touchés dans la majorité des phases — c'est pourquoi chaque phase leur affecte UN propriétaire unique et une tâche d'intégration finale.

### Protocole d'exécution d'une phase (à suivre mécaniquement)

1. **Préparation** (séquentiel, orchestrateur) : relire la section de la phase ; figer dans le prompt de chaque agent les API contractuelles (signatures de ce PLAN) ; vérifier que les prérequis (tags git) sont présents.
2. **Lots parallèles** : un agent par lot, périmètre de fichiers STRICT (rappelé dans le prompt : « tu ne crées/modifies QUE ces fichiers »), chaque agent lance SES tests et itère jusqu'à vert.
3. **Tâche d'intégration** (séquentiel, 1 agent) : câblage des points de contact, exécution de `scripts/ci.ps1`, lissage.
4. **DoD** : vérifier chaque critère de sortie de la phase ; couverture consignée.
5. **Commit + tag** `phase-EN` ; mise à jour du CHANGELOG si présent.
6. En cas d'échec d'un invariant mathématique : NE PAS élargir la tolérance — corriger le code ou documenter la décision dans `docs/modele_mathematique.md`.

### Extensions futures écartées du périmètre (décisions explicites)

- **TTR/TTS (Simchi-Levi)** : Time-to-Recover/Time-to-Survive par scénario — le modèle a déjà les données (recovery_time, stocks, flux) ; à reconsidérer après le serious game.
- **Centre d'alertes** : badges et tri suffisent (décision utilisateur).
- **Activation calculatoire des arcs backup** (bascule simulée avec délai/capacité) : le modèle (`ArcKind.BACKUP`) est prêt, la formule attendra.
- **Neo4j bout-en-bout** : l'adaptateur `neo4j_repo.py` existe, gelé hors couverture.
- **Import fichier / connecteurs ERP** : saisie manuelle assumée.
- **Multi-postes LAN / authentification** : mono-poste multi-joueurs assumé ; le multi-accès concurrent réseau réintroduirait une complexité écartée.
- **u_time multi-jalons pondéré** (au-delà du prochain jalon) : la fonction reçoit déjà la liste complète, la formule attendra.

---

*Fin du PLAN.md — pour exécuter : « exécute la phase E0 » (puis E1, E2, … dans l'ordre du chemin critique).*
