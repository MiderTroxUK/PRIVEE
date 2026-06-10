"""Couche d'orchestration — relie le core mathématique, le graphe et la persistance.

Pipeline complet pour un projet à la date t :
  1. Ud_local  : dernier questionnaire AHP de chaque nœud (lissé EMA si historique)
  2. Ur_local  : UrModel sur les KPIs du nœud
  3. Propagation descendante (Ud) et montante (Ur) sur le DAG
  4. Adéquation A, fausse urgence F, risque caché H par nœud
  5. Persistance de l'historique d'urgence dans la base du client
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path
from types import TracebackType

import numpy as np

from supplyscore.core import AdequationEngine, UrModel, compute_ud, run_ahp, ud_smoothed
from supplyscore.core.clock import Clock, GameClock, SystemClock, project_hours
from supplyscore.data import ClientDatabase, RandomSupplyChainGenerator, RegistryDatabase
from supplyscore.domain.milestones import MilestoneStatus, derive_node_status
from supplyscore.domain.models import (
    AHPAssessment,
    Project,
    SupplyArc,
    SupplyNode,
    TaskStatus,
    UrgencyState,
)
from supplyscore.graph import GraphRepository, InMemoryGraphRepository, PropagationEngine
from supplyscore.services.mutations import MutationService

#: nombre maximal de ClientDatabase gardées ouvertes simultanément (cache LRU).
_CLIENT_CACHE_SIZE = 64


class SupplyScoreService:
    """Façade unique consommée par l'UI et les scripts.

    Thread-safety : le serveur Dash sert chaque requête dans un thread
    distinct ; les méthodes publiques mutantes prennent donc ``self._lock``
    (RLock réentrant — les méthodes peuvent s'appeler entre elles).
    """

    def __init__(
        self,
        db_dir: Path | str = "data_store",
        repo: GraphRepository | None = None,
        ur_model: UrModel | None = None,
        adequation: AdequationEngine | None = None,
        rho_smoothing: float = 0.3,
        clock: Clock | None = None,
    ):
        """Initialise la façade et ses dépendances (bases, graphe, modèles).

        Args:
            db_dir: répertoire racine des bases SQLite.
            repo: dépôt de graphe (en mémoire par défaut).
            ur_model: modèle d'urgence réelle (défaut : ``UrModel()``).
            adequation: moteur d'adéquation (défaut : ``AdequationEngine()``).
            rho_smoothing: coefficient de lissage EMA du Ud_local.
            clock: horloge par défaut (mode « réel ») ; chaque projet peut
                la remplacer par une :class:`GameClock` via
                :meth:`set_clock_mode` (mode « jeu », serious game).
        """
        self.db_dir = Path(db_dir)
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.registry = RegistryDatabase(self.db_dir)
        self.repo = repo if repo is not None else InMemoryGraphRepository()
        self.ur_model = ur_model if ur_model is not None else UrModel()
        self.adequation = adequation if adequation is not None else AdequationEngine()
        self.propagation = PropagationEngine(self.repo)
        self.rho = rho_smoothing
        self.clock: Clock = clock if clock is not None else SystemClock()
        self._client_dbs: OrderedDict[str, ClientDatabase] = OrderedDict()
        self._lock = threading.RLock()
        self.mutations = MutationService(
            registry=self.registry,
            client_db_factory=self.client_db,
            clock=self.clock,
            repo=self.repo,
        )

    # --- cycle de vie -----------------------------------------------------------

    def close(self) -> None:
        """Ferme le registre et toutes les bases client encore ouvertes."""
        with self._lock:
            for db in self._client_dbs.values():
                db.close()
            self._client_dbs.clear()
            self.registry.close()

    def __enter__(self) -> SupplyScoreService:
        """Entre dans le context manager (retourne la façade elle-même)."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Sort du context manager en fermant toutes les bases."""
        self.close()

    # --- accès bases client --------------------------------------------------

    def client_db(self, node_id: str) -> ClientDatabase:
        """Retourne (en la créant au besoin) la base SQLite dédiée au nœud.

        Le cache est un LRU borné à ``_CLIENT_CACHE_SIZE`` entrées : la base la
        plus anciennement utilisée est fermée puis évincée au-delà de la borne.
        """
        with self._lock:
            db = self._client_dbs.get(node_id)
            if db is not None:
                self._client_dbs.move_to_end(node_id)
                return db
            db = ClientDatabase(self.db_dir, node_id)
            self._client_dbs[node_id] = db
            if len(self._client_dbs) > _CLIENT_CACHE_SIZE:
                _, evicted = self._client_dbs.popitem(last=False)
                evicted.close()
            return db

    # --- gestion projet / graphe ----------------------------------------------

    def create_project(
        self, project: Project, nodes: list[SupplyNode], arcs: list[SupplyArc]
    ) -> None:
        """Persiste le projet, ses nœuds et ses arcs, et alimente le graphe."""
        with self._lock:
            self.registry.save_project(project)
            for n in nodes:
                self.registry.save_node(n)
                self.repo.add_node(n)
            for a in arcs:
                self.registry.save_arc(a)
                self.repo.add_arc(a)

    def load_graph_from_registry(self) -> None:
        """Recharge le graphe en mémoire depuis la base registre (au démarrage)."""
        self.repo.clear()
        for n in self.registry.list_nodes():
            self.repo.add_node(n)
        for a in self.registry.list_arcs():
            self.repo.add_arc(a)

    def add_node(
        self,
        node: SupplyNode,
        supplies_to: list[str] | None = None,
        gamma: float = 0.5,
        beta: float = 0.5,
    ) -> None:
        """Ajoute un client/fournisseur de rang quelconque, relié à ses clients aval."""
        with self._lock:
            self.registry.save_node(node)
            self.repo.add_node(node)
            for target in supplies_to or []:
                arc = SupplyArc(source_id=node.id, target_id=target, gamma=gamma, beta=beta)
                self.registry.save_arc(arc)
                self.repo.add_arc(arc)

    def set_status(self, node_id: str, status: TaskStatus) -> dict[str, UrgencyState]:
        """Tâche finie/abandonnée : pose le statut puis réévalue UNE fois le réseau.

        Si le nœud a des jalons, le statut CASCADE sur eux (marquer un nœud
        terminé termine ses jalons actifs, l'abandonner les abandonne) — le
        statut global dérivant des jalons, c'est la seule façon cohérente de
        le changer. ``evaluate_all(persist=True)`` (appelé une seule fois) se
        charge ensuite des règles de statut et de la propagation.
        """
        with self._lock:
            status = TaskStatus(status)
            milestones = self.registry.list_milestones(node_id)
            if milestones and status in (TaskStatus.DONE, TaskStatus.ABANDONED):
                target = (
                    MilestoneStatus.DONE if status == TaskStatus.DONE else MilestoneStatus.ABANDONED
                )
                for milestone in milestones:
                    if milestone.status == MilestoneStatus.ACTIVE:
                        milestone.status = target
                        if target == MilestoneStatus.DONE:
                            milestone.progress = 1.0
                        self.registry.save_milestone(milestone)
            self.registry.set_node_status(node_id, status)
            node = self.repo.get_node(node_id)
            if node is not None:
                node.status = status
                self.repo.update_node(node)
            return self.evaluate_all(persist=True)

    # --- horloge bimodale par projet ---------------------------------------------

    def clock_for(self, project_id: str) -> Clock:
        """Horloge effective du projet : GameClock si mode « jeu », sinon l'horloge réelle."""
        raw = self.registry.get_setting(project_id, "clock")
        if isinstance(raw, dict) and raw.get("mode") == "game":
            return GameClock(
                start_ts=float(raw["start_ts"]),
                weeks_elapsed=int(raw.get("weeks_elapsed", 0)),
            )
        return self.clock

    def clock_mode(self, project_id: str) -> str:
        """Mode d'horloge du projet : ``"game"`` ou ``"real"`` (défaut)."""
        raw = self.registry.get_setting(project_id, "clock")
        if isinstance(raw, dict) and raw.get("mode") == "game":
            return "game"
        return "real"

    def set_clock_mode(self, project_id: str, mode: str) -> None:
        """Bascule l'horloge du projet entre temps réel et temps de jeu.

        En mode « jeu », l'origine est posée à l'instant de la bascule et les
        semaines écoulées repartent de zéro (sauf si le projet était déjà en
        mode jeu : son avancement est conservé).
        """
        with self._lock:
            if mode not in ("real", "game"):
                raise ValueError(f"mode d'horloge inconnu : {mode!r} (attendu 'real' ou 'game')")
            if mode == "real":
                self.registry.set_setting(project_id, "clock", {"mode": "real"})
                return
            raw = self.registry.get_setting(project_id, "clock")
            if isinstance(raw, dict) and raw.get("mode") == "game":
                return  # déjà en mode jeu : on conserve l'avancement
            self.registry.set_setting(
                project_id,
                "clock",
                {"mode": "game", "start_ts": self.clock.now(), "weeks_elapsed": 0},
            )

    def advance_week(self, project_id: str, n: int = 1) -> dict[str, UrgencyState]:
        """Avance le temps de jeu de ``n`` semaine(s) puis réévalue tout le réseau.

        Réservé aux projets en mode « jeu » (ValueError sinon).
        """
        with self._lock:
            raw = self.registry.get_setting(project_id, "clock")
            if not (isinstance(raw, dict) and raw.get("mode") == "game"):
                raise ValueError(
                    "Le projet n'est pas en mode « jeu » : "
                    "basculer l'horloge avec set_clock_mode(project_id, 'game') d'abord."
                )
            game = GameClock(
                start_ts=float(raw["start_ts"]),
                weeks_elapsed=int(raw.get("weeks_elapsed", 0)),
            )
            game.advance_weeks(n)
            self.registry.set_setting(
                project_id,
                "clock",
                {"mode": "game", "start_ts": game.start_ts, "weeks_elapsed": game.weeks_elapsed},
            )
            return self.evaluate_all(persist=True)

    # --- questionnaire AHP -----------------------------------------------------

    def submit_assessment(self, assessment: AHPAssessment) -> int:
        """Enregistre un questionnaire hebdo et met à jour le Ud_local lissé du nœud."""
        with self._lock:
            db = self.client_db(assessment.node_id)
            rowid = db.save_assessment(assessment)
            node = self.repo.get_node(assessment.node_id)
            if node is not None:
                prev = node.urgency.ud_local
                node.urgency.ud_local = ud_smoothed(prev, assessment.ud, self.rho)
                self.repo.update_node(node)
                self.registry.save_node(node)
            return rowid

    @staticmethod
    def build_assessment(
        node_id: str,
        project_id: str,
        operator_id: str,
        comparisons: dict[tuple[int, int], float],
        criteria_scores: list[float],
        notes: str = "",
    ) -> AHPAssessment:
        """Construit une évaluation complète depuis les réponses brutes du questionnaire."""
        res = run_ahp(comparisons, n=len(criteria_scores))
        ud = compute_ud(res.weights, np.asarray(criteria_scores, dtype=float))
        return AHPAssessment(
            node_id=node_id,
            project_id=project_id,
            operator_id=operator_id,
            comparisons=comparisons,
            criteria_scores=list(criteria_scores),
            weights=res.weights.tolist(),
            consistency_ratio=res.consistency_ratio,
            is_consistent=res.is_consistent,
            ud=ud,
            notes=notes,
        )

    # --- pipeline d'évaluation ---------------------------------------------------

    def _project_times(self) -> dict[str, tuple[float, float]]:
        """Temps courant par projet : ``project_id -> (t_heures, t0_ts epoch)``.

        ``t_heures`` est le temps écoulé depuis l'origine du projet selon SON
        horloge (réelle ou de jeu) — c'est le « t » des formules d'urgence.
        """
        times: dict[str, tuple[float, float]] = {}
        for project in self.registry.list_projects():
            origin = project.origin_ts
            now = self.clock_for(project.id).now()
            times[project.id] = (project_hours(now, origin), origin)
        return times

    def refresh_ur_local(self, t: float | None = None) -> None:
        """Recalcule Ur_local de chaque nœud depuis ses KPIs et jalons.

        Avec ``t=None`` (défaut), le temps de chaque nœud vient de l'horloge
        de SON projet et ses jalons pilotent u_time (mode v2). Avec un ``t``
        explicite, comportement v1 : pas de jalons, temps forcé identique
        partout (rétro-compatibilité tests/outillage).

        Le statut dérivé des jalons est appliqué AVANT le calcul (un nœud
        dont tous les jalons sont terminés passe DONE) ; les règles de statut
        (DONE → 0, ABANDONED → 1) restent dans ``core.status_rules``.
        """
        times = self._project_times() if t is None else None
        for node in self.repo.nodes():
            milestones = None
            t_h, t0 = (t if t is not None else 0.0), 0.0
            if times is not None:
                milestones = self.registry.list_milestones(node.id)
                derived = derive_node_status(milestones)
                if derived is not None and derived != node.status:
                    node.status = derived
                    self.registry.set_node_status(node.id, derived)
                if node.project_id and node.project_id in times:
                    t_h, t0 = times[node.project_id]
            node.urgency.ur_local = self.ur_model.ur_local(
                t_h, node.kpis, status=node.status, milestones=milestones, t0_ts=t0
            )
            self.repo.update_node(node)

    def evaluate_all(
        self, t: float | None = None, persist: bool = False
    ) -> dict[str, UrgencyState]:
        """Pipeline complet : Ur_local -> propagation -> adéquation (-> persistance).

        Avec ``persist=True``, chaque état est journalisé dans la base du
        client ET l'état courant est figé dans le registre (table
        ``node_urgency``) pour survivre à un redémarrage.
        """
        with self._lock:
            self.refresh_ur_local(t=t)
            states = self.propagation.propagate_all()
            for node_id, state in states.items():
                ud = state.ud if state.ud is not None else 0.0
                ur = state.ur if state.ur is not None else 0.0
                evaluated = self.adequation.evaluate(ud, ur)
                state.adequation = evaluated.adequation
                state.false_urgency = evaluated.false_urgency
                state.hidden_risk = evaluated.hidden_risk
                node = self.repo.get_node(node_id)
                if node is not None:
                    node.urgency = state
                    self.repo.update_node(node)
                if persist:
                    self.registry.save_urgency(node_id, state)
                    self.client_db(node_id).save_urgency_state(node_id, state)
            return states

    def simulate_shock(self, node_id: str, new_ur_local: float) -> dict[str, float]:
        """Scénario catastrophe what-if : retourne les ΔUr propagés sans rien persister."""
        return self.propagation.simulate_shock(node_id, new_ur_local)

    # --- données de démonstration ---------------------------------------------------

    def seed_demo(self, n_ranks: int = 3, seed: int = 42) -> Project:
        """Génère un projet de test aléatoire complet (questionnaires inclus).

        Enrichissements v2 : origine temporelle = maintenant (les jalons
        deviennent de vraies échéances), 2-4 jalons par nœud, tags et
        taxonomie, ~1 arc de secours sur 10. Données de TEST uniquement —
        jamais en production.
        """
        with self._lock:
            gen = RandomSupplyChainGenerator(seed=seed)
            project, nodes, arcs = gen.generate(n_ranks=n_ranks)
            project.t0_ts = self.clock.now()

            categories, tags = gen.generate_tags(project.id)
            tag_ids = [tag.id for tag in tags]
            for node in nodes:
                node.tags = gen.pick_node_tags(tag_ids)
            backups = gen.generate_backup_arcs(nodes, arcs)

            self.registry.save_project(project)
            for category in categories:
                self.registry.save_tag_category(category)
            for tag in tags:
                self.registry.save_tag(tag)
            self.create_project(project, nodes, arcs + backups)
            for node in nodes:
                for milestone in gen.generate_milestones(node.id, project.t0_ts):
                    self.registry.save_milestone(milestone)
                assessment = gen.generate_assessment(node.id, project.id)
                self.submit_assessment(assessment)
            self.evaluate_all(persist=True)
            return project
