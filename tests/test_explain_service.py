"""Tests du Lot 8.2 : ExplainService - assemblage de l'explication d'un noeud.

Couvre : coherence des scores avec ``node.urgency``, somme des contributions
criteres == ud du dernier assessment (le ``ud_local`` du noeud est lisse EMA),
somme des parts de blocs == 1, part locale + parts fournisseurs == 1, noeud de
rang max (part locale 1.0), noeud jamais evalue, audit des blocs dominants,
evenements ouverts, retard avere (noeud abandonne), KeyError noeud inconnu et
purete (deux appels identiques, aucune ecriture).
"""

from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path

import pytest

from supplyscore.core.clock import FixedClock
from supplyscore.domain.models import SupplyNode, TaskStatus
from supplyscore.services import SupplyScoreService
from supplyscore.services.events import EventEngine
from supplyscore.services.explain import _BLOCK_KPI_PREFIXES, ExplainService, NodeExplanation

#: Mercredi 2026-06-10 12:00 locale - semaine ISO " 2026-S24 ".
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()

TOL = 1e-9


# Fixtures


@pytest.fixture
def fixed_clock() -> FixedClock:
    return FixedClock(_NOW)


@pytest.fixture
def service(tmp_path: Path, fixed_clock: FixedClock):
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=fixed_clock)
    svc.seed_demo(n_ranks=2, seed=1)
    yield svc
    svc.close()


@pytest.fixture
def explainer(service: SupplyScoreService) -> ExplainService:
    return ExplainService(service)


# Helpers


def _actifs(service: SupplyScoreService) -> list[SupplyNode]:
    """Noeuds actifs et complets du projet de demo, en ordre deterministe."""
    return sorted(
        (
            n
            for n in service.repo.nodes()
            if n.status is TaskStatus.ACTIVE and n.onboarding_state == "complete"
        ),
        key=lambda n: n.id,
    )


def _avec_fournisseurs(service: SupplyScoreService) -> str:
    """Premier noeud actif ayant au moins un fournisseur direct (arc nominal)."""
    for node in _actifs(service):
        if service.repo.predecessors(node.id):
            return node.id
    pytest.fail("le projet de démo doit contenir un nœud avec fournisseurs")


def _rang_max(service: SupplyScoreService) -> str:
    """Premier noeud actif SANS fournisseur et d'urgence locale non nulle."""
    candidats = [
        n
        for n in _actifs(service)
        if not service.repo.predecessors(n.id) and (n.urgency.ur_local or 0.0) > 0.0
    ]
    assert candidats, "le projet de démo doit contenir un nœud de rang max actif"
    return candidats[0].id


# Coherence avec le pipeline


class TestCoherencePipeline:
    def test_scores_egaux_a_node_urgency(self, service, explainer):
        nid = _avec_fournisseurs(service)
        node = service.repo.get_node(nid)
        exp = explainer.explain_node(nid)

        assert isinstance(exp, NodeExplanation)
        assert exp.node_id == nid
        assert exp.node_name == node.name
        assert exp.ud == pytest.approx(node.urgency.ud, abs=TOL)
        assert exp.ur == pytest.approx(node.urgency.ur, abs=TOL)
        assert exp.adequation == pytest.approx(node.urgency.adequation, abs=TOL)
        assert exp.retard_avere is False
        # L'equation d'adequation instanciee rend le MEME score que le pipeline.
        assert exp.adequation_trace is not None
        assert exp.adequation_trace.adequation == pytest.approx(node.urgency.adequation, abs=TOL)

    def test_somme_criteres_egale_ud_assessment(self, service, explainer):
        # ATTENTION : node.urgency.ud_local est LISSE EMA - la reference est le ud du dernier questionnaire effectif, pas le ud_local du noeud.
        nid = _avec_fournisseurs(service)
        assessment = service.client_db(nid).latest_assessment(nid)
        assert assessment is not None
        exp = explainer.explain_node(nid)

        assert exp.criteres, "le nœud de démo a un questionnaire : critères attendus"
        assert sum(c.contribution for c in exp.criteres) == pytest.approx(assessment.ud, abs=TOL)
        assert exp.derniere_evaluation == {
            "operateur": assessment.operator_id,
            "semaine": assessment.iso_week,
            "ud": assessment.ud,
            "cr": assessment.consistency_ratio,
            "notes": assessment.notes,
        }

    def test_somme_shares_blocs_egale_1(self, service, explainer):
        nid = _avec_fournisseurs(service)
        exp = explainer.explain_node(nid)
        assert sum(b.share for b in exp.blocs) == pytest.approx(1.0, abs=TOL)

    def test_u_time_trace_coherente_avec_bloc_time(self, service, explainer):
        nid = _avec_fournisseurs(service)
        exp = explainer.explain_node(nid)
        par_bloc = {b.block: b for b in exp.blocs}
        assert exp.u_time_trace is not None
        assert exp.u_time_trace.final == par_bloc["time"].u

    def test_part_locale_plus_fournisseurs_egale_1(self, service, explainer):
        nid = _avec_fournisseurs(service)
        exp = explainer.explain_node(nid)

        assert exp.fournisseurs, "le nœud choisi a des fournisseurs"
        total = exp.part_locale_ur + sum(f.share for f in exp.fournisseurs)
        assert total == pytest.approx(1.0, abs=TOL)
        # Les coefficients exposes sont ceux des arcs du graphe.
        for contrib in exp.fournisseurs:
            arc = service.repo.get_arc(contrib.neighbor_id, nid)
            assert arc is not None
            assert contrib.coeff == pytest.approx(arc.beta, abs=TOL)

    def test_rang_max_part_locale_1(self, service, explainer):
        nid = _rang_max(service)
        exp = explainer.explain_node(nid)

        assert exp.fournisseurs == []
        assert exp.part_locale_ur == pytest.approx(1.0, abs=TOL)
        # Cote descendant, le noeud a des clients : part locale + parts = 1.
        assert exp.clients, "un nœud de rang max alimente au moins un client"
        total = exp.part_locale_ud + sum(c.share for c in exp.clients)
        assert total == pytest.approx(1.0, abs=TOL)

    def test_retard_avere_apres_abandon(self, service, explainer):
        nid = _avec_fournisseurs(service)
        service.set_status(nid, TaskStatus.ABANDONED)
        exp = explainer.explain_node(nid)

        # Ur_loc effectif = 1.0 : decomposition log non definie, cause locale unique.
        assert exp.retard_avere is True
        assert exp.part_locale_ur == 1.0
        assert all(f.share == 0.0 for f in exp.fournisseurs)


# Noeud jamais evalue


class TestJamaisEvalue:
    def test_noeud_nu_via_add_node(self, service, explainer):
        service.add_node(SupplyNode(id="nu-1", name="Nœud nu"))
        exp = explainer.explain_node("nu-1")

        assert exp.criteres == []
        assert exp.derniere_evaluation is None
        # Choix documente : sans passage du pipeline (Ud/Ur propages absents), il n'y a pas d'equation d'adequation a instancier.
        assert exp.adequation_trace is None
        assert exp.ud is None
        assert exp.ur is None
        assert exp.adequation is None
        # Aucun KPI, aucun voisin : blocs inertes, parts nulles.
        assert all(b.u is None for b in exp.blocs)
        assert sum(b.share for b in exp.blocs) == 0.0
        assert exp.u_time_trace is not None
        assert exp.u_time_trace.final is None
        assert exp.fournisseurs == []
        assert exp.clients == []
        assert exp.part_locale_ur == 0.0
        assert exp.part_locale_ud == 0.0
        assert exp.audits_recents == []
        assert exp.evenements_ouverts == []
        assert exp.retard_avere is False

    def test_noeud_au_projet_inconnu_referentiel_degenere(self, service, explainer):
        # Projet absent du registre : le referentiel temporel degenere en (0, 0) sans erreur (meme tolerance que evaluate_all).
        service.add_node(SupplyNode(id="nu-2", name="Nœud orphelin", project_id="projet-fantome"))
        exp = explainer.explain_node("nu-2")
        assert exp.criteres == []
        assert exp.adequation_trace is None
        assert sum(b.share for b in exp.blocs) == 0.0


# Versions liees : audit et evenements


class TestVersionsLiees:
    def test_audits_recents_apres_mutation_bloc_dominant(self, service, explainer):
        nid = _avec_fournisseurs(service)
        # seed_demo n'ecrit aucun KPI via MutationService : audit vide au depart.
        assert explainer.explain_node(nid).audits_recents == []

        # Risque quasi sature : le bloc " risk " devient dominant.
        service.mutations.update_kpis(
            nid,
            {
                "risk.failure_probability": 0.95,
                "risk.recovery_time_h": 240.0,
                "risk.severity": 1.0,
            },
            source="edit",
            operator_id="op-1",
        )
        service.evaluate_all(persist=True)
        exp = explainer.explain_node(nid)

        dominants = sorted(exp.blocs, key=lambda b: b.share, reverse=True)[:2]
        assert "risk" in {b.block for b in dominants}
        assert exp.audits_recents, "la mutation du bloc dominant doit apparaître"
        assert len(exp.audits_recents) <= 10
        prefixes = tuple(f"{kpi}." for bloc in dominants for kpi in _BLOCK_KPI_PREFIXES[bloc.block])
        assert all(e.field.startswith(prefixes) for e in exp.audits_recents)
        assert any(e.field == "risk.failure_probability" for e in exp.audits_recents)
        for entry in exp.audits_recents:
            assert entry.entity_type == "node_kpis"
            assert entry.entity_id == nid

    def test_evenement_ouvert_puis_reverte(self, service, explainer):
        nid = _avec_fournisseurs(service)
        engine = EventEngine(service)
        event = engine.apply(
            nid, "panne_machine", {"duree_arret_h": 24.0, "gravite": "majeure"}, "op-1"
        )

        exp = explainer.explain_node(nid)
        assert [e.id for e in exp.evenements_ouverts] == [event.id]
        assert exp.evenements_ouverts[0].reverted_at is None

        # explain_node est pur : les KPIs n'ont pas bouge, le revert passe.
        engine.revert(event.id, nid, "op-1")
        assert explainer.explain_node(nid).evenements_ouverts == []


# Robustesse et purete


class TestRobustesse:
    def test_keyerror_noeud_inconnu(self, explainer):
        with pytest.raises(KeyError, match="fantome"):
            explainer.explain_node("fantome")

    def test_purete_deux_appels_identiques_sans_ecriture(self, service, explainer):
        nid = _avec_fournisseurs(service)
        avant = {n.id: copy.deepcopy(n.urgency) for n in service.repo.nodes()}

        premier = explainer.explain_node(nid)
        second = explainer.explain_node(nid)
        assert premier == second

        apres = {n.id: copy.deepcopy(n.urgency) for n in service.repo.nodes()}
        assert apres == avant
        # Le registre non plus n'a pas bouge.
        node_registre = service.registry.get_node(nid)
        assert node_registre is not None
        assert node_registre.urgency == avant[nid]
