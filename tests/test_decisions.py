"""Tests du Lot 6.3 : DecisionService - journal des decisions hebdomadaires.

Couvre : le snapshot automatique des scores ``{ud, ur, a, f, h}`` (egalite
champ a champ avec ``node.urgency``, None tolere), la description vide
(ValueError, rien d'ecrit), le filtre par semaine de ``list_for_node``,
l'agregation triee ``created_at`` DESC de ``list_for_project`` et l'horloge
de jeu (record apres ``advance_week(2)`` -> semaine simulee).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from supplyscore.core.clock import FixedClock, iso_week
from supplyscore.domain.models import Project, SupplyNode, TaskStatus
from supplyscore.services import SupplyScoreService
from supplyscore.services.decisions import Decision, DecisionService

#: Mercredi 2026-06-10 12:00 locale - semaine ISO " 2026-S24 ".
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()
_WEEK = 604_800.0


@pytest.fixture
def fixed_clock() -> FixedClock:
    return FixedClock(_NOW)


@pytest.fixture
def service(tmp_path: Path, fixed_clock: FixedClock):
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=fixed_clock)
    yield svc
    svc.close()


@pytest.fixture
def projet(service: SupplyScoreService) -> Project:
    """Projet de demonstration reproductible (seed_demo)."""
    return service.seed_demo(n_ranks=2, seed=1)


@pytest.fixture
def node_id(service: SupplyScoreService, projet: Project) -> str:
    """Premier noeud actif (ordre deterministe) du projet de demo."""
    nodes = sorted(service.repo.nodes(), key=lambda n: n.id)
    actifs = [
        n for n in nodes if n.status is TaskStatus.ACTIVE and n.onboarding_state == "complete"
    ]
    assert actifs, "le projet de démo doit contenir au moins un nœud actif"
    return actifs[0].id


@pytest.fixture
def decisions(service: SupplyScoreService) -> DecisionService:
    return DecisionService(service)


# record : snapshot automatique des scores


class TestRecord:
    def test_snapshot_egal_a_l_urgency_courante_champ_a_champ(
        self, service: SupplyScoreService, decisions: DecisionService, node_id: str
    ) -> None:
        node = service.registry.get_node(node_id)
        assert node is not None
        urgence = node.urgency

        decision = decisions.record(node_id, "Relancer le fournisseur", operator_id="op-7")

        assert isinstance(decision, Decision)
        assert decision.scores == {
            "ud": urgence.ud,
            "ur": urgence.ur,
            "a": urgence.adequation,
            "f": urgence.false_urgency,
            "h": urgence.hidden_risk,
        }
        # Le projet de demo a des scores calcules : le snapshot n'est pas vide.
        assert decision.scores["ud"] is not None
        assert decision.node_id == node_id
        assert decision.iso_week == iso_week(_NOW) == "2026-S24"
        assert decision.created_at == _NOW
        assert decision.operator_id == "op-7"
        assert decision.description == "Relancer le fournisseur"

        # Persistee et relue a l'identique (round-trip JSON des scores compris).
        assert decisions.list_for_node(node_id) == [decision]

    def test_scores_none_toleres(
        self, service: SupplyScoreService, decisions: DecisionService, projet: Project
    ) -> None:
        # Noeud vierge : urgency par defaut, tous les scores a None.
        service.registry.save_node(SupplyNode(id="n-vierge", name="Vierge", project_id=projet.id))

        decision = decisions.record("n-vierge", "Première décision")

        assert decision.scores == {"ud": None, "ur": None, "a": None, "f": None, "h": None}
        assert decisions.list_for_node("n-vierge") == [decision]

    def test_description_vide_leve_value_error_et_n_ecrit_rien(
        self, decisions: DecisionService, node_id: str
    ) -> None:
        with pytest.raises(ValueError, match="description"):
            decisions.record(node_id, "")
        with pytest.raises(ValueError, match="description"):
            decisions.record(node_id, "   ")
        assert decisions.list_for_node(node_id) == []

    def test_noeud_inconnu_leve_value_error(
        self, decisions: DecisionService, projet: Project
    ) -> None:
        with pytest.raises(ValueError, match="inconnu"):
            decisions.record("fantome", "Décision orpheline")

    def test_ids_uniques(self, decisions: DecisionService, node_id: str) -> None:
        d1 = decisions.record(node_id, "A")
        d2 = decisions.record(node_id, "B")
        assert d1.id != d2.id


# list_for_node : filtre par semaine


class TestListForNode:
    def test_filtre_par_semaine_iso(
        self,
        decisions: DecisionService,
        node_id: str,
        fixed_clock: FixedClock,
    ) -> None:
        d1 = decisions.record(node_id, "Décision S24")
        fixed_clock.set(_NOW + _WEEK)  # semaine suivante
        d2 = decisions.record(node_id, "Décision S25")

        # Sans filtre : tri created_at DESC (la plus recente d'abord).
        assert [d.id for d in decisions.list_for_node(node_id)] == [d2.id, d1.id]
        assert [d.id for d in decisions.list_for_node(node_id, "2026-S24")] == [d1.id]
        assert [d.id for d in decisions.list_for_node(node_id, "2026-S25")] == [d2.id]
        assert decisions.list_for_node(node_id, "2026-S01") == []


# list_for_project : agregation triee


class TestListForProject:
    def test_agrege_les_noeuds_et_trie_created_at_desc(
        self,
        service: SupplyScoreService,
        decisions: DecisionService,
        projet: Project,
        fixed_clock: FixedClock,
    ) -> None:
        noeuds = sorted(n.id for n in service.registry.list_nodes(projet.id))
        assert len(noeuds) >= 2
        n1, n2 = noeuds[0], noeuds[1]

        d1 = decisions.record(n1, "Décision A")
        fixed_clock.set(_NOW + 3600.0)
        d2 = decisions.record(n2, "Décision B")
        fixed_clock.set(_NOW + 7200.0)
        d3 = decisions.record(n1, "Décision C")

        assert [d.id for d in decisions.list_for_project(projet.id)] == [d3.id, d2.id, d1.id]

        # Filtre par semaine : la semaine suivante ne remonte que sa decision.
        fixed_clock.set(_NOW + _WEEK)
        d4 = decisions.record(n2, "Décision D")
        s24 = [d.id for d in decisions.list_for_project(projet.id, "2026-S24")]
        assert s24 == [d3.id, d2.id, d1.id]
        assert [d.id for d in decisions.list_for_project(projet.id, "2026-S25")] == [d4.id]

    def test_projet_sans_noeud_retourne_vide(
        self, decisions: DecisionService, projet: Project
    ) -> None:
        assert decisions.list_for_project("p-fantome") == []


# Horloge du PROJET : mode jeu


class TestHorlogeJeu:
    def test_record_apres_advance_week_porte_la_semaine_simulee(
        self,
        service: SupplyScoreService,
        decisions: DecisionService,
        projet: Project,
        node_id: str,
    ) -> None:
        service.set_clock_mode(projet.id, "game")
        service.advance_week(projet.id, 2)

        decision = decisions.record(node_id, "Décision simulée")

        assert decision.iso_week == iso_week(_NOW + 2 * _WEEK) == "2026-S26"
        assert decision.created_at == _NOW + 2 * _WEEK
        assert [d.id for d in decisions.list_for_node(node_id, "2026-S26")] == [decision.id]
