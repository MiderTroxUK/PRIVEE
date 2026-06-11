"""Propagation incrémentale (E14.4, Lot 14.4) — moteur, dépôt et orchestrateur.

Couverture :
- ``InMemoryGraphRepository`` : cache de l'ordre topologique (invalidé sur
  mutation de structure, pas sur ``update_node``), ``descendants``/``ancestors``
  (KeyError français), ``structure_version`` monotone ;
- ``PropagationEngine.propagate_incremental`` : recalcul restreint aux cônes
  des nœuds sales (espionné via les timestamps des ``UrgencyState``), valeurs
  identiques à ``propagate_all`` sur un jumeau, délégation au complet
  (``invalidate``, cache absent, mutation de structure hors orchestrateur),
  nœud « frontière » d'un diamant, repli générique pour un dépôt non-mémoire ;
- ``SupplyScoreService`` : marquage ``dirty_ud``/``dirty_ur`` par
  ``submit_assessment``/``refresh_ur_local``, équivalence
  ``evaluate_all()`` (incrémental) == ``evaluate_all(incremental=False)``.
"""

from __future__ import annotations

import pytest

from supplyscore.core.clock import FixedClock
from supplyscore.domain.models import (
    Project,
    SupplyArc,
    SupplyNode,
    TaskStatus,
    UrgencyState,
)
from supplyscore.graph import GraphRepository, InMemoryGraphRepository, PropagationEngine
from supplyscore.services import SupplyScoreService

# --- Aides -------------------------------------------------------------------------


def _node(node_id: str, ud_local: float, ur_local: float) -> SupplyNode:
    return SupplyNode(
        id=node_id,
        name=f"Node {node_id}",
        urgency=UrgencyState(ud_local=ud_local, ur_local=ur_local, timestamp=0.0),
    )


def _build(nodes: list[SupplyNode], arcs: list[SupplyArc]) -> InMemoryGraphRepository:
    repo = InMemoryGraphRepository()
    for node in nodes:
        repo.add_node(node)
    for arc in arcs:
        repo.add_arc(arc)
    repo.assign_ranks()
    return repo


def _chain_specs() -> tuple[list[SupplyNode], list[SupplyArc]]:
    """Chaîne C (rang 2) -> B (rang 1) -> A (rang 0), plus D isolé."""
    nodes = [
        _node("A", 0.2, 0.1),
        _node("B", 0.4, 0.3),
        _node("C", 0.6, 0.5),
        _node("D", 0.7, 0.8),
    ]
    arcs = [
        SupplyArc(source_id="C", target_id="B", gamma=0.5, beta=0.6),
        SupplyArc(source_id="B", target_id="A", gamma=0.7, beta=0.4),
    ]
    return nodes, arcs


def _diamond_specs() -> tuple[list[SupplyNode], list[SupplyArc]]:
    """Diamant D (rang 2) -> {B, C} (rang 1) -> A (rang 0, puits)."""
    nodes = [
        _node("A", 0.2, 0.1),
        _node("B", 0.4, 0.3),
        _node("C", 0.5, 0.6),
        _node("D", 0.7, 0.8),
    ]
    arcs = [
        SupplyArc(source_id="D", target_id="B", gamma=0.5, beta=0.6),
        SupplyArc(source_id="D", target_id="C", gamma=0.4, beta=0.3),
        SupplyArc(source_id="B", target_id="A", gamma=0.7, beta=0.4),
        SupplyArc(source_id="C", target_id="A", gamma=0.6, beta=0.8),
    ]
    return nodes, arcs


def _values(repo: GraphRepository) -> tuple[dict[str, float | None], dict[str, float | None]]:
    """Copies {id: ud} et {id: ur} (les UrgencyState sont mutées en place)."""
    ud = {node.id: node.urgency.ud for node in repo.nodes()}
    ur = {node.id: node.urgency.ur for node in repo.nodes()}
    return ud, ur


def _reset_timestamps(repo: GraphRepository) -> None:
    """Pose timestamp=0.0 partout — tout timestamp > 0 signale un recalcul."""
    for node in repo.nodes():
        node.urgency.timestamp = 0.0
        repo.update_node(node)


def _recomputed_ids(repo: GraphRepository) -> set[str]:
    """Ids dont l'UrgencyState a été réécrite depuis ``_reset_timestamps``."""
    return {node.id for node in repo.nodes() if node.urgency.timestamp != 0.0}


def _set_ur_local(repo: GraphRepository, node_id: str, value: float) -> None:
    node = repo.get_node(node_id)
    assert node is not None
    node.urgency.ur_local = value
    repo.update_node(node)


def _set_ud_local(repo: GraphRepository, node_id: str, value: float) -> None:
    node = repo.get_node(node_id)
    assert node is not None
    node.urgency.ud_local = value
    repo.update_node(node)


# --- Dépôt : cache topologique, descendants/ancestors, version de structure ----------


class TestMemoryRepoIncremental:
    def test_descendants_et_ancestors_sur_le_diamant(self):
        repo = _build(*_diamond_specs())
        assert repo.descendants("D") == {"B", "C", "A"}
        assert repo.descendants("A") == set()
        assert repo.ancestors("A") == {"B", "C", "D"}
        assert repo.ancestors("D") == set()
        assert repo.descendants("B") == {"A"}
        assert repo.ancestors("B") == {"D"}

    def test_descendants_ancestors_noeud_inconnu_keyerror_francais(self):
        repo = _build(*_chain_specs())
        with pytest.raises(KeyError, match="Nœud inconnu"):
            repo.descendants("inconnu")
        with pytest.raises(KeyError, match="Nœud inconnu"):
            repo.ancestors("inconnu")
        # Même convention sur le voisinage direct (parcours des cônes).
        with pytest.raises(KeyError, match="Nœud inconnu"):
            repo.predecessors("inconnu")
        with pytest.raises(KeyError, match="Nœud inconnu"):
            repo.successors("inconnu")

    def test_ordre_topologique_cache_et_copie_defensive(self):
        repo = _build(*_chain_specs())
        order = repo.topological_order()
        order.append("intrus")  # la copie retournée ne corrompt pas le cache
        assert repo.topological_order() == order[:-1]

    def test_cache_invalide_sur_chaque_mutation_de_structure(self):
        repo = _build(*_chain_specs())
        version = repo.structure_version
        assert repo.topological_order().index("C") < repo.topological_order().index("A")

        repo.add_node(_node("E", 0.1, 0.1))
        assert repo.structure_version > version
        assert "E" in repo.topological_order()

        version = repo.structure_version
        repo.add_arc(SupplyArc(source_id="A", target_id="E", gamma=0.5, beta=0.5))
        assert repo.structure_version > version
        order = repo.topological_order()
        assert order.index("A") < order.index("E")

        version = repo.structure_version
        repo.remove_arc("A", "E")
        assert repo.structure_version > version

        version = repo.structure_version
        repo.remove_node("E")
        assert repo.structure_version > version
        assert "E" not in repo.topological_order()

        version = repo.structure_version
        repo.clear()
        assert repo.structure_version > version
        assert repo.topological_order() == []

    def test_update_node_ne_change_pas_la_structure(self):
        repo = _build(*_chain_specs())
        version = repo.structure_version
        node = repo.get_node("A")
        assert node is not None
        node.urgency.ur_local = 0.9
        repo.update_node(node)
        assert repo.structure_version == version  # pas d'invalidation


# --- Moteur : propagation incrémentale --------------------------------------------


class TestPropagateIncremental:
    def test_ur_sale_recalcule_seulement_le_cone_aval(self):
        """Chaîne C -> B -> A : ur_local(C) change => C/B/A recalculés, D intact."""
        repo = _build(*_chain_specs())
        engine = PropagationEngine(repo)
        engine.propagate_all()

        twin = _build(*_chain_specs())
        _set_ur_local(twin, "C", 0.95)
        PropagationEngine(twin).propagate_all()

        _set_ur_local(repo, "C", 0.95)
        engine.mark_dirty_ur("C")
        _reset_timestamps(repo)
        states = engine.propagate_incremental()

        assert _recomputed_ids(repo) == {"A", "B", "C"}  # D (isolé) jamais réécrit
        assert set(states) == {"A", "B", "C", "D"}
        # Identité stricte (==) : mêmes opérations, mêmes entrées que le complet.
        assert _values(repo) == _values(twin)

    def test_ud_sale_sur_le_puits_recalcule_les_ancetres(self):
        """ud_local(A) change => Affectés_Ud = {A} + ancestors(A) = {A, B, C}."""
        repo = _build(*_chain_specs())
        engine = PropagationEngine(repo)
        engine.propagate_all()

        twin = _build(*_chain_specs())
        _set_ud_local(twin, "A", 0.9)
        PropagationEngine(twin).propagate_all()

        _set_ud_local(repo, "A", 0.9)
        engine.mark_dirty_ud("A")
        _reset_timestamps(repo)
        engine.propagate_incremental()

        assert _recomputed_ids(repo) == {"A", "B", "C"}
        assert _values(repo) == _values(twin)

    def test_ud_sale_sur_fournisseur_profond_ne_recalcule_que_lui(self):
        """ud_local(C) change => ancestors(C) = ∅, seul C est recalculé."""
        repo = _build(*_chain_specs())
        engine = PropagationEngine(repo)
        engine.propagate_all()

        twin = _build(*_chain_specs())
        _set_ud_local(twin, "C", 0.05)
        PropagationEngine(twin).propagate_all()

        _set_ud_local(repo, "C", 0.05)
        engine.mark_dirty_ud("C")
        _reset_timestamps(repo)
        engine.propagate_incremental()

        assert _recomputed_ids(repo) == {"C"}
        assert _values(repo) == _values(twin)

    def test_noeud_isole_sale_un_seul_recalcul(self):
        repo = _build(*_chain_specs())
        engine = PropagationEngine(repo)
        engine.propagate_all()

        _set_ur_local(repo, "D", 0.05)
        engine.mark_dirty_ur("D")
        _reset_timestamps(repo)
        engine.propagate_incremental()

        assert _recomputed_ids(repo) == {"D"}
        node_d = repo.get_node("D")
        assert node_d is not None
        assert node_d.urgency.ur == pytest.approx(0.05, abs=1e-12)

    def test_invalidate_delegue_au_complet(self):
        repo = _build(*_chain_specs())
        engine = PropagationEngine(repo)
        engine.propagate_all()

        engine.invalidate()
        _reset_timestamps(repo)
        states = engine.propagate_incremental()

        assert _recomputed_ids(repo) == {"A", "B", "C", "D"}  # tout est repassé
        assert set(states) == {"A", "B", "C", "D"}

    def test_dirty_vide_aucun_recalcul_etats_caches_retournes(self):
        repo = _build(*_chain_specs())
        engine = PropagationEngine(repo)
        before = engine.propagate_all()
        snapshot = _values(repo)

        _reset_timestamps(repo)
        states = engine.propagate_incremental()

        assert _recomputed_ids(repo) == set()  # aucun recalcul
        assert set(states) == set(before)
        assert _values(repo) == snapshot  # états cachés inchangés, bit à bit

    def test_frontiere_diamant_relit_le_predecesseur_non_affecte_du_cache(self):
        """UN seul prédécesseur du puits affecté : l'autre est relu du cache."""
        repo = _build(*_diamond_specs())
        engine = PropagationEngine(repo)
        engine.propagate_all()

        twin = _build(*_diamond_specs())
        _set_ur_local(twin, "B", 0.9)
        PropagationEngine(twin).propagate_all()

        _set_ur_local(repo, "B", 0.9)
        engine.mark_dirty_ur("B")
        _reset_timestamps(repo)
        engine.propagate_incremental()

        assert _recomputed_ids(repo) == {"A", "B"}  # C et D relus du cache
        assert _values(repo) == _values(twin)  # identité stricte avec le complet

    def test_cache_absent_hors_zone_affectee_delegue_au_complet(self):
        """Un nœud jamais propagé hors zone => délégation au complet (choix documenté)."""
        repo = _build(*_chain_specs())
        engine = PropagationEngine(repo)
        engine.propagate_all()

        node_a = repo.get_node("A")
        assert node_a is not None
        node_a.urgency.ud = None  # simule un nœud jamais propagé
        repo.update_node(node_a)

        _set_ur_local(repo, "D", 0.05)
        engine.mark_dirty_ur("D")  # A n'est PAS dans la zone affectée
        _reset_timestamps(repo)
        engine.propagate_incremental()

        assert _recomputed_ids(repo) == {"A", "B", "C", "D"}  # complet
        assert node_a.urgency.ud is not None  # le cache absent a été reconstruit

    def test_mutation_de_structure_hors_orchestrateur_detectee(self):
        """Remplacement d'arc façon MutationService._sync_repo_arc (β modifié) :

        ni invalidate() ni mark_dirty_* — la version de structure du dépôt
        suffit à déclencher la délégation au complet.
        """
        repo = _build(*_chain_specs())
        engine = PropagationEngine(repo)
        engine.propagate_all()

        twin = _build(*_chain_specs())
        twin.remove_arc("C", "B")
        twin.add_arc(SupplyArc(source_id="C", target_id="B", gamma=0.5, beta=0.95))
        PropagationEngine(twin).propagate_all()

        repo.remove_arc("C", "B")
        repo.add_arc(SupplyArc(source_id="C", target_id="B", gamma=0.5, beta=0.95))
        _reset_timestamps(repo)
        engine.propagate_incremental()

        assert _recomputed_ids(repo) == {"A", "B", "C", "D"}  # délégation au complet
        assert _values(repo) == _values(twin)


# --- Repli générique pour un dépôt non-mémoire --------------------------------------


class _DelegatingRepo(GraphRepository):
    """Doublure NON-mémoire : force les replis génériques du moteur.

    Délègue tout à un :class:`InMemoryGraphRepository` interne, mais n'expose
    ni ``descendants``/``ancestors`` ni ``structure_version`` — le moteur doit
    alors parcourir les voisins via le contrat abstrait.
    """

    def __init__(self, inner: InMemoryGraphRepository) -> None:
        self._inner = inner

    def add_node(self, node):
        self._inner.add_node(node)

    def get_node(self, node_id):
        return self._inner.get_node(node_id)

    def update_node(self, node):
        self._inner.update_node(node)

    def remove_node(self, node_id):
        self._inner.remove_node(node_id)

    def add_arc(self, arc):
        self._inner.add_arc(arc)

    def get_arc(self, source_id, target_id):
        return self._inner.get_arc(source_id, target_id)

    def remove_arc(self, source_id, target_id):
        self._inner.remove_arc(source_id, target_id)

    def nodes(self):
        return self._inner.nodes()

    def arcs(self, kinds=None):
        return self._inner.arcs(kinds)

    def predecessors(self, node_id, *, kinds=("nominal",)):
        return self._inner.predecessors(node_id, kinds=kinds)

    def successors(self, node_id, *, kinds=("nominal",)):
        return self._inner.successors(node_id, kinds=kinds)

    def nodes_by_project(self, project_id):
        return self._inner.nodes_by_project(project_id)

    def topological_order(self):
        return self._inner.topological_order()

    def clear(self):
        self._inner.clear()


class TestRepliGeneriqueDepotNonMemoire:
    def test_incremental_equivalent_au_complet_sans_chemins_rapides(self):
        repo = _DelegatingRepo(_build(*_diamond_specs()))
        engine = PropagationEngine(repo)
        engine.propagate_all()

        twin = _build(*_diamond_specs())
        _set_ur_local(twin, "D", 0.95)
        _set_ud_local(twin, "A", 0.9)
        PropagationEngine(twin).propagate_all()

        _set_ur_local(repo, "D", 0.95)
        _set_ud_local(repo, "A", 0.9)
        engine.mark_dirty_ur("D")  # repli _descendants : parcours via successors
        engine.mark_dirty_ud("A")  # repli _ancestors : parcours via predecessors
        _reset_timestamps(repo)
        engine.propagate_incremental()

        assert _recomputed_ids(repo) == {"A", "B", "C", "D"}
        assert _values(repo) == _values(twin)


# --- Orchestrateur : marquage des sales et équivalence de bout en bout ----------------

#: Instant figé des tests service (epoch s) — refresh_ur_local reproductible.
_T0 = 1_790_000_000.0


@pytest.fixture
def service(tmp_path):
    """Service à horloge figée, chargé avec la chaîne C -> B -> A (+ D isolé)."""
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(_T0))
    project = Project(
        id="p1", name="Incremental", owner_node_id="A", created_at=_T0 - 7 * 24 * 3600.0
    )
    nodes, arcs = _chain_specs()
    for node, proba in zip(nodes, (0.2, 0.5, 0.8, 0.4), strict=True):
        node.project_id = "p1"
        # u_risk = 1 − exp(−p·t_réc·sév/T_ref) : p pilote le bloc, donc ur_local
        # est non trivial dès la première passe et sensible aux éditions de KPI.
        node.kpis.risk.failure_probability = proba
    svc.create_project(project, nodes, arcs)
    yield svc
    svc.close()


class TestOrchestrateurIncremental:
    def test_submit_assessment_marque_dirty_ud(self, service):
        service.evaluate_all()  # première passe : complète, vide les sales
        assert service.propagation._dirty_ud == set()

        assessment = service.build_assessment(
            node_id="B",
            project_id="p1",
            operator_id="op",
            comparisons={(0, 1): 1.0},
            criteria_scores=[5.0, 5.0],
        )
        service.submit_assessment(assessment)
        assert "B" in service.propagation._dirty_ud

    def test_refresh_ur_local_marque_dirty_ur_sur_changement_seulement(self, service):
        service.evaluate_all()
        assert service.propagation._dirty_ur == set()

        # Horloge figée, KPIs inchangés : un refresh ne marque RIEN.
        service.refresh_ur_local()
        assert service.propagation._dirty_ur == set()

        # Un KPI change (via MutationService) : le ur_local recalculé diffère.
        service.mutations.update_kpis("C", {"risk.failure_probability": 0.95}, source="edit")
        service.refresh_ur_local()
        assert "C" in service.propagation._dirty_ur

    def test_set_status_via_evaluate_all_equivaut_au_complet(self, service):
        service.evaluate_all()
        states_inc = service.set_status("B", TaskStatus.DONE)  # chemin incrémental
        states_full = service.evaluate_all(incremental=False)
        for nid in states_full:
            assert states_inc[nid].ud == pytest.approx(states_full[nid].ud, abs=1e-12)
            assert states_inc[nid].ur == pytest.approx(states_full[nid].ur, abs=1e-12)

    def test_upsert_arc_via_mutations_equivaut_au_complet(self, service):
        """β modifié par MutationService (hors orchestrateur) : non périmé."""
        service.evaluate_all()
        arc = service.registry.get_arc("C", "B")
        assert arc is not None
        arc.beta = 0.95
        service.mutations.upsert_arc(arc, source="edit")

        states_inc = service.evaluate_all()  # incrémental par défaut
        states_full = service.evaluate_all(incremental=False)
        for nid in states_full:
            assert states_inc[nid].ud == pytest.approx(states_full[nid].ud, abs=1e-12)
            assert states_inc[nid].ur == pytest.approx(states_full[nid].ur, abs=1e-12)

    def test_remove_arc_invalide_la_propagation(self, service):
        service.evaluate_all()
        service.remove_arc("C", "B")  # invalide puis réévalue (persist=True)
        states_inc = service.evaluate_all()
        states_full = service.evaluate_all(incremental=False)
        for nid in states_full:
            assert states_inc[nid].ur == pytest.approx(states_full[nid].ur, abs=1e-12)
