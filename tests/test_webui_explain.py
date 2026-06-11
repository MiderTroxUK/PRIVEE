"""Tests de la page « Pourquoi ce score ? » (« /node/<id>/explication ») — sans serveur.

La page est en lecture seule : ``layout(node_id)`` est appelé directement sur
un service seedé (FixedClock, set_service/teardown), aucun serveur Dash. Les
branches conditionnelles sont couvertes : nœud évalué (bandeau chiffré, ≥ 3
figures), nœud introuvable, nœud nu jamais évalué, nœud ABANDONED (encart
« Retard avéré »), glissement de planning, audit des blocs dominants et
événements ouverts.
"""

from __future__ import annotations

from datetime import datetime

import dash
import pytest
from dash import dcc

from supplyscore.core.clock import FixedClock
from supplyscore.core.explain import BlockContribution, UTimeTrace
from supplyscore.domain.models import SupplyNode, TaskStatus
from supplyscore.services import SupplyScoreService
from supplyscore.services.events import EventEngine
from supplyscore.services.explain import NodeExplanation
from supplyscore.web_ui import set_service
from supplyscore.web_ui.pages import explain

#: Mercredi 2026-06-10 12:00 locale — semaine ISO « 2026-S24 ».
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()


@pytest.fixture
def service(tmp_path):
    """Service seedé avec une petite démo évaluée, partagé par la page."""
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(_NOW))
    svc.seed_demo(n_ranks=2, seed=1)
    set_service(svc)
    yield svc
    set_service(None)
    svc.close()


def _demo_node(service):
    """Premier nœud de la démo évalué (questionnaire AHP + scores propagés)."""
    for node in sorted(service.repo.nodes(), key=lambda n: (n.rank, n.name)):
        if (
            node.urgency.adequation is not None
            and service.client_db(node.id).latest_assessment(node.id) is not None
        ):
            return node
    pytest.fail("la démo doit contenir un nœud évalué")


def _count_graphs(component) -> int:
    """Nombre de dcc.Graph dans l'arbre de composants (récursif)."""
    count = int(isinstance(component, dcc.Graph))
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        return count + sum(_count_graphs(child) for child in children)
    if children is not None:
        return count + _count_graphs(children)
    return count


# --- layout : nœud évalué -----------------------------------------------------------------


def test_layout_demo_node_contains_sections_and_graphs(service):
    node = _demo_node(service)
    tree = explain.layout(node.id)
    text = str(tree)

    assert "Pourquoi" in text
    assert node.name in text
    assert "besoin déclaré" in text
    assert "urgence réelle" in text
    assert "équation" in text
    assert _count_graphs(tree) >= 3


def test_bandeau_values_match_node_urgency(service):
    node = _demo_node(service)
    text = str(explain.layout(node.id))
    urgency = node.urgency

    assert f"Pourquoi A = {urgency.adequation:.1f} ?" in text
    assert f"Ud = {urgency.ud:.2f}" in text
    assert f"Ur = {urgency.ur:.2f}" in text
    # Lien retour vers la fiche nœud.
    assert f"/node/{node.id}" in text


def test_layout_demo_node_shows_last_assessment_and_empty_messages(service):
    node = _demo_node(service)
    text = str(explain.layout(node.id))

    assert "Dernière évaluation" in text
    # seed_demo n'écrit ni audit MutationService ni événement : messages vides.
    assert "Aucune modification récente des blocs dominants" in text
    assert "Aucun événement ouvert" in text


# --- layout : nœud introuvable --------------------------------------------------------------


def test_layout_unknown_node_shows_message_without_exception(service):
    text = str(explain.layout("inconnu"))
    assert "introuvable" in text


# --- layout : nœud nu jamais évalué ---------------------------------------------------------


def test_layout_naked_node_never_evaluated(service):
    service.add_node(SupplyNode(id="nu-1", name="Nœud nu"))
    text = str(explain.layout("nu-1"))

    assert "Jamais évalué" in text
    assert "Pourquoi ce score ?" in text  # adéquation None : titre dégénéré
    assert "jamais été propagé" in text  # phrase de synthèse remplacée
    assert "pas d'équation d'adéquation à instancier" in text


# --- layout : nœud ABANDONED (retard avéré) -------------------------------------------------


def test_layout_abandoned_node_shows_retard_avere(service):
    node = _demo_node(service)
    service.set_status(node.id, TaskStatus.ABANDONED)
    text = str(explain.layout(node.id))

    assert "Retard avéré" in text
    assert "u_time est forcé à 1" in text


# --- carte Ur_local : ligne « glissement de planning » --------------------------------------


def _explanation_with_planning_adjust() -> NodeExplanation:
    """Explication minimale avec une modulation planning non nulle (v2 nominal)."""
    blocs = [BlockContribution(block="time", u=0.3, omega=1.0, share=1.0, delta_without=0.3)]
    trace = UTimeTrace(u_base=0.2, p_th=0.5, progress=0.3, planning_adjust=0.1, final=0.3)
    return NodeExplanation(
        node_id="x-1",
        node_name="Nœud X",
        ud=0.2,
        ur=0.3,
        adequation=80.0,
        criteres=[],
        blocs=blocs,
        u_time_trace=trace,
        part_locale_ur=1.0,
        fournisseurs=[],
        part_locale_ud=1.0,
        clients=[],
        adequation_trace=None,
        derniere_evaluation=None,
        audits_recents=[],
        evenements_ouverts=[],
        retard_avere=False,
    )


def test_ur_local_card_shows_planning_adjust_line():
    text = str(explain._ur_local_card(_explanation_with_planning_adjust(), 0.3))

    assert "dont glissement de planning : +0.10" in text
    assert "déclaré 30 % vs théorique 50 %" in text


# --- versions liées : audit des blocs dominants et événements ouverts -----------------------


def test_layout_shows_audit_entries_after_dominant_block_mutation(service):
    node = _demo_node(service)
    service.mutations.update_kpis(
        node.id,
        {
            "risk.failure_probability": 0.95,
            "risk.recovery_time_h": 240.0,
            "risk.severity": 1.0,
        },
        source="edit",
        operator_id="op-1",
    )
    service.evaluate_all(persist=True)

    text = str(explain.layout(node.id))

    assert "risk.failure_probability" in text
    assert "Aucune modification récente des blocs dominants" not in text


def test_layout_lists_open_events_with_french_label_and_week(service):
    node = _demo_node(service)
    event = EventEngine(service).apply(
        node.id, "panne_machine", {"duree_arret_h": 24.0, "gravite": "majeure"}, "op-1"
    )

    text = str(explain.layout(node.id))

    assert f"Panne machine — semaine {event.iso_week}" in text
    assert "Aucun événement ouvert" not in text


# --- register_callbacks ----------------------------------------------------------------------


def test_register_callbacks_does_not_raise():
    app = dash.Dash(__name__)
    explain.register_callbacks(app)  # aucun callback : ne doit pas lever
