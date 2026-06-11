"""Tests du ServiceCriticite (Lot 15.2) — criticité systématique des nœuds.

Couvre : valeurs analytiques sur la chaîne historique C→B→A (β=(0.5, 0.7),
ur_loc=(0.6, 0.3, 0.1)), classement (B avant C, client final en tête),
exclusions (autre projet, DONE/ABANDONED, onboarding draft), ``nb_impactes``,
``top``, erreurs françaises (projet inconnu, aucun actif), pureté (états
d'urgence du dépôt inchangés) et perf indicative non bloquante sur seed_demo.
"""

from __future__ import annotations

import copy
import time
import warnings
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from supplyscore.core.clock import FixedClock
from supplyscore.domain.models import Project, SupplyArc, SupplyNode, TaskStatus, UrgencyState
from supplyscore.services import SupplyScoreService
from supplyscore.services.criticite import PointCriticite, ServiceCriticite

#: Mercredi 2026-06-10 12:00 locale — instant figé des tests.
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()

#: Chaîne historique C (rang 2) -> B (rang 1) -> A (rang 0, client final).
UR_LOCAL = {"A": 0.1, "B": 0.3, "C": 0.6}
BETA = {("C", "B"): 0.5, ("B", "A"): 0.7}
GAMMA = {("C", "B"): 0.8, ("B", "A"): 0.6}

#: Valeurs analytiques (cf. test_graph_propagation.py / PLAN.md E15.1) :
#: baseline Ur_A = 0.4213 ; choc B→1 : ΔUr_A = +0.3087 ; choc C→1 : +0.0882 ;
#: choc A→1 : ΔUr_A = 1.0 − 0.4213 = +0.5787.
DELTA_A_CHOC_B = 0.3087
DELTA_A_CHOC_C = 0.0882
DELTA_A_CHOC_A = 0.5787

PROJECT_ID = "proj-chaine"


@pytest.fixture
def service(tmp_path: Path) -> Iterator[SupplyScoreService]:
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(_NOW))
    yield svc
    svc.close()


@pytest.fixture
def chaine(service: SupplyScoreService) -> SupplyScoreService:
    """Service portant la chaîne C→B→A avec les ur_local/β historiques."""
    ranks = {"A": 0, "B": 1, "C": 2}
    nodes = [
        SupplyNode(
            id=node_id,
            name=f"Node {node_id}",
            rank=ranks[node_id],
            project_id=PROJECT_ID,
            urgency=UrgencyState(ud_local=0.2, ur_local=UR_LOCAL[node_id]),
        )
        for node_id in ("A", "B", "C")
    ]
    arcs = [
        SupplyArc(source_id=s, target_id=t, gamma=GAMMA[(s, t)], beta=BETA[(s, t)])
        for s, t in (("C", "B"), ("B", "A"))
    ]
    project = Project(id=PROJECT_ID, name="Chaîne historique", owner_node_id="A", t0_ts=_NOW)
    service.create_project(project, nodes, arcs)
    return service


def _point(points: list[PointCriticite], node_id: str) -> PointCriticite:
    """Le point de criticité du nœud demandé (échoue si absent)."""
    matches = [p for p in points if p.node_id == node_id]
    assert len(matches) == 1, f"nœud {node_id!r} absent ou dupliqué dans {points}"
    return matches[0]


def _set_status(service: SupplyScoreService, node_id: str, status: TaskStatus) -> None:
    """Pose le statut DIRECTEMENT dans le dépôt (sans réévaluer les ur_local)."""
    node = service.repo.get_node(node_id)
    assert node is not None
    node.status = status
    service.repo.update_node(node)


# --- Valeurs analytiques sur la chaîne ------------------------------------------------


def test_criticite_de_b_egale_delta_ur_a_attendu(chaine: SupplyScoreService) -> None:
    points = ServiceCriticite(chaine).indice_criticite(PROJECT_ID)
    point_b = _point(points, "B")
    # Choc B→1 : Ur_B passe à 1.0, Ur_A = 1 − 0.9·(1 − 0.7) = 0.73 → ΔUr_A = +0.3087.
    assert point_b.delta_ur_final == pytest.approx(DELTA_A_CHOC_B, abs=1e-4)
    # ΔUr max du choc B : le nœud choqué lui-même (1.0 − 0.51 = 0.49).
    assert point_b.delta_ur_max == pytest.approx(1.0 - 0.51, abs=1e-4)


def test_b_classe_avant_c(chaine: SupplyScoreService) -> None:
    points = ServiceCriticite(chaine).indice_criticite(PROJECT_ID)
    point_c = _point(points, "C")
    assert point_c.delta_ur_final == pytest.approx(DELTA_A_CHOC_C, abs=1e-4)
    ordre = [p.node_id for p in points]
    assert ordre.index("B") < ordre.index("C")
    # Le tri est décroissant sur delta_ur_final et le champ rank suit (1-based).
    assert [p.rank for p in points] == list(range(1, len(points) + 1))
    deltas = [p.delta_ur_final for p in points]
    assert deltas == sorted(deltas, reverse=True)


def test_client_final_delta_final_egal_son_propre_delta(chaine: SupplyScoreService) -> None:
    # Choc sur A (rang 0) : delta_ur_final == le delta de A lui-même.
    deltas_choc_a = chaine.simulate_shock("A", 1.0)
    points = ServiceCriticite(chaine).indice_criticite(PROJECT_ID)
    point_a = _point(points, "A")
    assert point_a.delta_ur_final == pytest.approx(deltas_choc_a["A"], abs=1e-12)
    assert point_a.delta_ur_final == pytest.approx(DELTA_A_CHOC_A, abs=1e-4)
    # Le client final saturé d'office est ici le plus critique : rang 1.
    assert point_a.rank == 1


def test_noeud_deja_sature_donne_delta_nul(chaine: SupplyScoreService) -> None:
    # CHOIX DOCUMENTÉ : ur_local déjà >= 1.0 → choc à vide, deltas nuls partout.
    node_b = chaine.repo.get_node("B")
    assert node_b is not None
    node_b.urgency.ur_local = 1.0
    chaine.repo.update_node(node_b)
    points = ServiceCriticite(chaine).indice_criticite(PROJECT_ID)
    point_b = _point(points, "B")
    assert point_b.delta_ur_final == pytest.approx(0.0, abs=1e-12)
    assert point_b.delta_ur_max == pytest.approx(0.0, abs=1e-12)
    assert point_b.nb_impactes == 0
    assert point_b.rank == len(points)  # queue de classement


# --- Périmètre : projet, statuts, onboarding -------------------------------------------


def test_noeud_isole_d_un_autre_projet_exclu(chaine: SupplyScoreService) -> None:
    autre = Project(id="proj-autre", name="Autre projet", owner_node_id="X", t0_ts=_NOW)
    noeud_x = SupplyNode(
        id="X",
        name="Node X",
        rank=0,
        project_id="proj-autre",
        urgency=UrgencyState(ud_local=0.5, ur_local=0.9),
    )
    chaine.create_project(autre, [noeud_x], [])
    points = ServiceCriticite(chaine).indice_criticite(PROJECT_ID)
    assert {p.node_id for p in points} == {"A", "B", "C"}


def test_done_et_abandoned_exclus_de_la_liste(chaine: SupplyScoreService) -> None:
    _set_status(chaine, "B", TaskStatus.DONE)
    _set_status(chaine, "C", TaskStatus.ABANDONED)
    points = ServiceCriticite(chaine).indice_criticite(PROJECT_ID)
    assert {p.node_id for p in points} == {"A"}


def test_onboarding_draft_exclu(chaine: SupplyScoreService) -> None:
    node_c = chaine.repo.get_node("C")
    assert node_c is not None
    node_c.onboarding_state = "draft"
    chaine.repo.update_node(node_c)
    points = ServiceCriticite(chaine).indice_criticite(PROJECT_ID)
    assert {p.node_id for p in points} == {"A", "B"}


# --- nb_impactes ----------------------------------------------------------------------


def test_nb_impactes_coherent_sur_la_chaine(chaine: SupplyScoreService) -> None:
    points = ServiceCriticite(chaine).indice_criticite(PROJECT_ID)
    # Choc sur C : C, B et A bougent → 3 ; sur B : B et A → 2 ; sur A : A seul → 1.
    assert _point(points, "C").nb_impactes == 3
    assert _point(points, "B").nb_impactes == 2
    assert _point(points, "A").nb_impactes == 1


# --- top ------------------------------------------------------------------------------


def test_top_n1_retourne_le_plus_critique(chaine: SupplyScoreService) -> None:
    crit = ServiceCriticite(chaine)
    top1 = crit.top(PROJECT_ID, n=1)
    assert [p.node_id for p in top1] == ["A"]
    assert top1 == crit.indice_criticite(PROJECT_ID)[:1]


def test_top_defaut_et_bornes(chaine: SupplyScoreService) -> None:
    crit = ServiceCriticite(chaine)
    assert len(crit.top(PROJECT_ID)) == 3  # n=15 > 3 nœuds actifs : tout
    assert crit.top(PROJECT_ID, n=0) == []


# --- Erreurs --------------------------------------------------------------------------


def test_projet_inconnu_leve_valueerror(chaine: SupplyScoreService) -> None:
    with pytest.raises(ValueError, match="inconnu"):
        ServiceCriticite(chaine).indice_criticite("fantome")


def test_projet_sans_noeud_actif_leve_valueerror(chaine: SupplyScoreService) -> None:
    for node_id in ("A", "B", "C"):
        _set_status(chaine, node_id, TaskStatus.DONE)
    with pytest.raises(ValueError, match="actif"):
        ServiceCriticite(chaine).indice_criticite(PROJECT_ID)


# --- Pureté ---------------------------------------------------------------------------


def test_indice_criticite_ne_modifie_pas_les_urgences(chaine: SupplyScoreService) -> None:
    # Référence riche : pipeline complet d'abord (ud/ur/adequation posés partout).
    chaine.evaluate_all()
    avant = {node.id: copy.deepcopy(node.urgency) for node in chaine.repo.nodes()}
    statuts = {node.id: node.status for node in chaine.repo.nodes()}

    ServiceCriticite(chaine).indice_criticite(PROJECT_ID)

    for node in chaine.repo.nodes():
        assert node.urgency == avant[node.id], f"UrgencyState modifié sur {node.id!r}"
        assert node.status is statuts[node.id]


# --- Perf indicative (non bloquante) ----------------------------------------------------


def test_perf_indicative_seed_demo(service: SupplyScoreService) -> None:
    project = service.seed_demo(n_ranks=3, seed=42)
    crit = ServiceCriticite(service)

    debut = time.perf_counter()
    points = crit.indice_criticite(project.id)
    duree = time.perf_counter() - debut

    assert points, "seed_demo doit produire au moins un nœud actif"
    deltas = [p.delta_ur_final for p in points]
    assert deltas == sorted(deltas, reverse=True)
    if duree >= 2.0:  # indicatif, non bloquant : on signale sans faire échouer
        warnings.warn(
            f"indice_criticite a pris {duree:.2f} s sur seed_demo(n_ranks=3) (budget 2 s)",
            stacklevel=1,
        )
