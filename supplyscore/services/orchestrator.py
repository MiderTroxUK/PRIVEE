"""Couche d'orchestration — relie le core mathématique, le graphe et la persistance.

Pipeline complet pour un projet à la date t :
  1. Ud_local  : dernier questionnaire AHP de chaque nœud (lissé EMA si historique)
  2. Ur_local  : UrModel sur les KPIs du nœud
  3. Propagation descendante (Ud) et montante (Ur) sur le DAG
  4. Adéquation A, fausse urgence F, risque caché H par nœud
  5. Persistance de l'historique d'urgence dans la base du client
"""

from __future__ import annotations

from pathlib import Path

from supplyscore.core import AdequationEngine, UrModel, run_ahp, compute_ud, ud_smoothed
from supplyscore.data import ClientDatabase, RegistryDatabase, RandomSupplyChainGenerator
from supplyscore.domain.models import (
    AHPAssessment,
    Project,
    SupplyArc,
    SupplyNode,
    TaskStatus,
    UrgencyState,
)
from supplyscore.graph import GraphRepository, InMemoryGraphRepository, PropagationEngine


class SupplyScoreService:
    """Façade unique consommée par l'UI et les scripts."""

    def __init__(
        self,
        db_dir: Path | str = "data_store",
        repo: GraphRepository | None = None,
        ur_model: UrModel | None = None,
        adequation: AdequationEngine | None = None,
        rho_smoothing: float = 0.3,
    ):
        self.db_dir = Path(db_dir)
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.registry = RegistryDatabase(self.db_dir)
        self.repo = repo if repo is not None else InMemoryGraphRepository()
        self.ur_model = ur_model if ur_model is not None else UrModel()
        self.adequation = adequation if adequation is not None else AdequationEngine()
        self.propagation = PropagationEngine(self.repo)
        self.rho = rho_smoothing
        self._client_dbs: dict[str, ClientDatabase] = {}

    # --- accès bases client --------------------------------------------------

    def client_db(self, node_id: str) -> ClientDatabase:
        if node_id not in self._client_dbs:
            self._client_dbs[node_id] = ClientDatabase(self.db_dir, node_id)
        return self._client_dbs[node_id]

    # --- gestion projet / graphe ----------------------------------------------

    def create_project(self, project: Project, nodes: list[SupplyNode], arcs: list[SupplyArc]) -> None:
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

    def add_node(self, node: SupplyNode, supplies_to: list[str] | None = None,
                 gamma: float = 0.5, beta: float = 0.5) -> None:
        """Ajoute un client/fournisseur de rang quelconque, relié à ses clients aval."""
        self.registry.save_node(node)
        self.repo.add_node(node)
        for target in supplies_to or []:
            arc = SupplyArc(source_id=node.id, target_id=target, gamma=gamma, beta=beta)
            self.registry.save_arc(arc)
            self.repo.add_arc(arc)

    def set_status(self, node_id: str, status: TaskStatus) -> dict[str, UrgencyState]:
        """Tâche finie/abandonnée : persiste, repropage et retourne le nouvel état global."""
        self.registry.set_node_status(node_id, status)
        self.propagation.apply_status(node_id, status)
        return self.evaluate_all(persist=True)

    # --- questionnaire AHP -----------------------------------------------------

    def submit_assessment(self, assessment: AHPAssessment) -> int:
        """Enregistre un questionnaire hebdo et met à jour le Ud_local lissé du nœud."""
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
    def build_assessment(node_id: str, project_id: str, operator_id: str,
                         comparisons: dict[tuple[int, int], float],
                         criteria_scores: list[float], notes: str = "") -> AHPAssessment:
        """Construit une évaluation complète depuis les réponses brutes du questionnaire."""
        res = run_ahp(comparisons, n=len(criteria_scores))
        ud = compute_ud(res.weights, criteria_scores)
        return AHPAssessment(
            node_id=node_id, project_id=project_id, operator_id=operator_id,
            comparisons=comparisons, criteria_scores=list(criteria_scores),
            weights=res.weights.tolist(), consistency_ratio=res.consistency_ratio,
            is_consistent=res.is_consistent, ud=ud, notes=notes,
        )

    # --- pipeline d'évaluation ---------------------------------------------------

    def refresh_ur_local(self, t: float = 0.0) -> None:
        """Recalcule Ur_local de chaque nœud actif depuis ses KPIs."""
        for node in self.repo.nodes():
            if node.status == TaskStatus.DONE:
                node.urgency.ur_local = 0.0
            elif node.status == TaskStatus.ABANDONED:
                node.urgency.ur_local = 1.0
            else:
                node.urgency.ur_local = self.ur_model.ur_local(t, node.kpis)
            self.repo.update_node(node)

    def evaluate_all(self, t: float = 0.0, persist: bool = False) -> dict[str, UrgencyState]:
        """Pipeline complet : Ur_local -> propagation -> adéquation (-> persistance)."""
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
                self.client_db(node_id).save_urgency_state(node_id, state)
        return states

    def simulate_shock(self, node_id: str, new_ur_local: float) -> dict[str, float]:
        """Scénario catastrophe what-if : retourne les ΔUr propagés sans rien persister."""
        return self.propagation.simulate_shock(node_id, new_ur_local)

    # --- données de démonstration ---------------------------------------------------

    def seed_demo(self, n_ranks: int = 3, seed: int = 42) -> Project:
        """Génère un projet de test aléatoire complet (questionnaires inclus).

        Données de TEST uniquement — jamais en production.
        """
        gen = RandomSupplyChainGenerator(seed=seed)
        project, nodes, arcs = gen.generate(n_ranks=n_ranks)
        self.create_project(project, nodes, arcs)
        for node in nodes:
            assessment = gen.generate_assessment(node.id, project.id)
            self.submit_assessment(assessment)
        self.evaluate_all(persist=True)
        return project
