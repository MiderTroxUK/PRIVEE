"""Tests de la fiche nœud 360° (page « /node/<id> ») — aucun serveur Dash.

Les callbacks sont des fonctions nommées au niveau module : ils sont appelés
directement, sans contexte de requête. La sauvegarde passe par
``OnboardingService.save_section`` (mêmes validations que le wizard) et
l'audit est vérifié via ``AuditTrail`` sur les bases SQLite temporaires.
"""

from __future__ import annotations

import pytest

from supplyscore.data.audit import AuditTrail
from supplyscore.services import SupplyScoreService
from supplyscore.services.onboarding import OnboardingService
from supplyscore.web_ui import set_service
from supplyscore.web_ui.pages import node_detail


@pytest.fixture
def service(tmp_path):
    """Service seedé avec une petite démo, partagé par les callbacks."""
    svc = SupplyScoreService(db_dir=tmp_path / "store")
    svc.seed_demo(n_ranks=2, seed=1)
    set_service(svc)
    yield svc
    set_service(None)


def _first_node(service):
    """Premier nœud de la démo (rang minimal, ordre stable par nom)."""
    return sorted(service.repo.nodes(), key=lambda n: (n.rank, n.name))[0]


# --- layout ---------------------------------------------------------------------------


def test_layout_contains_cards_and_scores(service):
    node = _first_node(service)
    tree = str(node_detail.layout(node.id))

    assert node.name in tree
    for expected in (
        "Identité & tags",
        "Cahier des charges",
        "Jalons",
        "KPIs courants",
        "Évaluations AHP",
        "Historique",
    ):
        assert expected in tree

    urgency = node.urgency
    assert f"Ud {urgency.ud:.2f}" in tree
    assert f"Ur {urgency.ur:.2f}" in tree
    assert f"A {urgency.adequation:.1f}" in tree
    assert "store-fiche" in tree


def test_layout_unknown_node_shows_message_without_exception(service):
    tree = str(node_detail.layout("inconnu"))
    assert "introuvable" in tree


def test_milestones_card_shows_theoretical_progress(service):
    node = _first_node(service)
    assert service.registry.list_milestones(node.id), "la démo doit générer des jalons"
    tree = str(node_detail.layout(node.id))
    assert "théorique" in tree


def test_draft_node_shows_incomplete_badge(service):
    project = service.registry.list_projects()[0]
    draft_id = OnboardingService(service).start_draft(project.id, "Brouillon X")

    tree = str(node_detail.layout(draft_id))

    assert "Brouillon X" in tree
    assert "Incomplet" in tree
    assert "A —" in tree  # jamais évalué : l'adéquation s'affiche « — »


# --- save_kpis_callback -----------------------------------------------------------------


def test_save_kpis_callback_updates_kpi_and_audits(service):
    node = _first_node(service)
    assert service.registry.get_node(node.id).kpis.time.lead_time_h != 200.0
    ids = [{"type": "fiche-kpi", "index": "time.lead_time_h"}]

    body, store = node_detail.save_kpis_callback(
        1, [200], ids, {"name": "op-kpi"}, {"node_id": node.id, "editing": "kpis"}
    )

    # KPI mis à jour dans le registre (et la carte repasse en lecture).
    assert service.registry.get_node(node.id).kpis.time.lead_time_h == pytest.approx(200.0)
    assert store["editing"] is None
    assert "enregistrés" in str(body)

    # Audit dans la base CLIENT du nœud, source onboarding/edit, opérateur du store.
    client = service.client_db(node.id)
    trail = AuditTrail(client.conn, service.clock, client.lock)
    entries = trail.history("node_kpis", node.id, field="time.lead_time_h", limit=5)
    assert entries, "la mutation KPI doit être auditée dans la base client"
    assert entries[0].source in ("onboarding", "edit")
    assert entries[0].new_value == pytest.approx(200.0)
    assert entries[0].operator_id == "op-kpi"


# --- save_identity_callback ----------------------------------------------------------------


def test_save_identity_callback_empty_name_writes_nothing(service):
    node = _first_node(service)
    before = service.registry.get_node(node.id)

    body, store = node_detail.save_identity_callback(
        1,
        "   ",  # nom vide après strip -> erreur de validation
        node.label,
        "",
        [],
        [],
        0.5,
        0.5,
        "nominal",
        {"name": "op-err"},
        {"node_id": node.id, "editing": "identity"},
    )

    assert "obligatoire" in str(body)
    assert store["editing"] == "identity"  # la carte reste en édition
    after = service.registry.get_node(node.id)
    assert after.name == before.name
    assert after.tags == before.tags


def test_save_identity_callback_success_renames_and_audits(service):
    node = _first_node(service)
    tag_names = [t.name for t in service.registry.tags_of_node(node.id)]

    body, store = node_detail.save_identity_callback(
        1,
        "Nouveau nom",
        node.label,
        node.location or "",
        tag_names,
        [],
        0.5,
        0.5,
        "nominal",
        {"name": "op-id"},
        {"node_id": node.id, "editing": "identity"},
    )

    assert service.registry.get_node(node.id).name == "Nouveau nom"
    assert store["editing"] is None
    assert "enregistrée" in str(body)

    registry = service.registry
    trail = AuditTrail(registry.conn, service.clock, registry.lock)
    entries = trail.history("node", node.id, field="name", limit=5)
    assert entries and entries[0].source == "onboarding"
    assert entries[0].operator_id == "op-id"
    assert entries[0].new_value == "Nouveau nom"
