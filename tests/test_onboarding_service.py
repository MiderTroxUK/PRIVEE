"""Tests du Lot 5.1 : OnboardingService, wizard 4 sections avec brouillon en base.

Couvre : création immédiate du nœud brouillon (start_draft), aller-retour
save_draft/load, refus bloquants par section (jalon à fenêtre inversée, KPI
hors bornes, AHP incohérent — RIEN n'est écrit), écriture réelle de la
section identité (rang dérivé, arcs audités source='onboarding', tags créés
et liés), idempotence du remplacement des jalons, cycle complete() (refus
tant que les 4 sections manquent, puis bascule 'complete' + évaluation), et
reprise après fermeture/réouverture du service.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from supplyscore.core.ahp import CONSISTENCY_THRESHOLD
from supplyscore.core.clock import FixedClock, iso_week
from supplyscore.data.audit import AuditTrail
from supplyscore.domain.models import SupplyNode
from supplyscore.services import SupplyScoreService
from supplyscore.services.onboarding import SECTION_KEYS, OnboardingService

_NOW = 1_750_000_000.0  # 2025-06-15 ~ : instant figé de référence
_DAY = 86_400.0


# --- Fixtures / helpers -----------------------------------------------------------


@pytest.fixture
def env(tmp_path: Path):
    """Service seedé (projet + cibles de rangs 0 et 1) + OnboardingService."""
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(_NOW))
    project = svc.seed_demo(n_ranks=2, seed=1)
    e = SimpleNamespace(service=svc, wizard=OnboardingService(svc), project=project)
    yield e
    e.service.close()


def _target_by_rank(env: SimpleNamespace, rank: int) -> SupplyNode:
    """Premier nœud SEEDÉ (complete) du projet ayant le rang demandé."""
    for node in env.service.registry.list_nodes(env.project.id):
        if node.rank == rank and node.onboarding_state == "complete":
            return node
    raise AssertionError(f"aucun nœud seedé de rang {rank}")


def _identity_payload(env: SimpleNamespace) -> dict:
    """Payload de section 1 : connexions vers un nœud de rang 0 et un de rang 1."""
    return {
        "name": "Atelier Nord",
        "label": "Workshop",
        "location": "Lyon",
        "tag_names": ["Usinage", "Europe"],
        "connections": [
            {
                "target_id": _target_by_rank(env, 0).id,
                "gamma": 0.6,
                "beta": 0.4,
                "kind": "nominal",
            },
            {
                "target_id": _target_by_rank(env, 1).id,
                "gamma": 0.5,
                "beta": 0.5,
                "kind": "nominal",
            },
        ],
    }


def _cdc_payload(*, valid: bool = True) -> dict:
    """Payload de section 2 ; ``valid=False`` -> jalon à fenêtre inversée."""
    start = _NOW + _DAY
    deadline = start + 13 * _DAY if valid else start - _DAY
    return {
        "cdc": {
            "deliverables": [{"name": "Carter usiné", "quantity": 100.0, "unit": "pièces"}],
            "budget_total": 50_000.0,
            "currency": "EUR",
            "quality": {"standards": ["ISO 9001"], "max_scrap_rate": 0.02},
            "penalties": [],
            "notes": "",
        },
        "milestones": [
            {"name": "Proto", "kind": "proto", "start_ts": start, "deadline_ts": deadline},
            {
                "name": "Livraison",
                "kind": "livraison",
                "start_ts": start,
                "deadline_ts": start + 30 * _DAY,
            },
        ],
    }


_KPIS_OK = {"time.lead_time_h": 24.0, "risk.failure_probability": 0.1, "oee.availability": 0.9}

_AHP_OK = {
    "comparisons": {"0-1": 1.0, "0-2": 1.0, "0-3": 1.0, "1-2": 1.0, "1-3": 1.0, "2-3": 1.0},
    "scores": [5.0, 6.0, 4.0, 5.0],
    "notes": "première évaluation",
}

#: 0 ≫ 1 et 1 ≫ 2 mais 0 ≪ 2 : violation flagrante de transitivité (CR >= 0.10).
_AHP_INCOHERENT = {
    "comparisons": {"0-1": 9.0, "1-2": 9.0, "0-2": 1.0 / 9.0},
    "scores": [5.0, 6.0, 4.0, 5.0],
    "notes": "",
}


def _full_onboarding(env: SimpleNamespace, node_id: str) -> None:
    """Valide les 4 sections du wizard (payloads tous valides)."""
    assert env.wizard.save_section(node_id, 1, _identity_payload(env), "op-1").ok
    assert env.wizard.save_section(node_id, 2, _cdc_payload(), "op-1").ok
    assert env.wizard.save_section(node_id, 3, dict(_KPIS_OK), "op-1").ok
    assert env.wizard.save_section(node_id, 4, dict(_AHP_OK), "op-1").ok


# --- start_draft / list_drafts -----------------------------------------------------


def test_start_draft_cree_noeud_brouillon_et_progression(env):
    node_id = env.wizard.start_draft(env.project.id, "Fournisseur X")

    node = env.service.registry.get_node(node_id)
    assert node is not None
    assert node.onboarding_state == "draft"
    assert node.rank == 0
    assert node.project_id == env.project.id
    assert node.name == "Fournisseur X"
    # Aucun arc : le nœud naît isolé.
    assert all(node_id not in (a.source_id, a.target_id) for a in env.service.registry.list_arcs())
    # Présent dans le graphe en mémoire dès la création.
    assert env.service.repo.get_node(node_id) is not None

    state = env.wizard.load(node_id)
    assert state.node_id == node_id
    assert state.sections_done == dict.fromkeys(SECTION_KEYS, 0)
    assert state.draft == {}
    assert state.current_step == 1
    assert env.wizard.completeness(node_id) == (0, 4)

    assert node_id in [n.id for n in env.wizard.list_drafts(env.project.id)]
    assert node_id in [n.id for n in env.wizard.list_drafts()]
    # Les nœuds seedés (complete) n'apparaissent pas dans les brouillons.
    assert all(n.onboarding_state == "draft" for n in env.wizard.list_drafts())


def test_load_inconnu_leve_keyerror(env):
    with pytest.raises(KeyError):
        env.wizard.load("id-fantome")


# --- save_draft / load --------------------------------------------------------------


def test_save_draft_puis_load_restitue_payload_et_etape(env):
    node_id = env.wizard.start_draft(env.project.id, "Brouillon")
    payload_1 = {"name": "Brouillon", "tag_names": ["incomplet"], "connections": []}
    payload_3 = {"time.lead_time_h": 5.0}

    env.wizard.save_draft(node_id, 1, payload_1)
    state = env.wizard.load(node_id)
    assert state.draft["identity"] == payload_1
    assert state.current_step == 1

    env.wizard.save_draft(node_id, 3, payload_3)
    state = env.wizard.load(node_id)
    # Les deux brouillons coexistent, restitués à l'identique.
    assert state.draft["identity"] == payload_1
    assert state.draft["kpis"] == payload_3
    assert state.current_step == 3
    # save_draft ne valide RIEN et ne marque AUCUNE section faite.
    assert state.sections_done == dict.fromkeys(SECTION_KEYS, 0)


def test_save_draft_etape_invalide_ou_noeud_inconnu(env):
    node_id = env.wizard.start_draft(env.project.id, "X")
    with pytest.raises(ValueError):
        env.wizard.save_draft(node_id, 5, {})
    with pytest.raises(KeyError):
        env.wizard.save_draft("id-fantome", 1, {})


# --- section 1 : identité ------------------------------------------------------------


def test_save_section_identite_rang_arcs_audites_et_tags(env):
    node_id = env.wizard.start_draft(env.project.id, "Atelier")
    cible_r0 = _target_by_rank(env, 0)
    cible_r1 = _target_by_rank(env, 1)

    result = env.wizard.save_section(node_id, 1, _identity_payload(env), "op-42")
    assert result.ok
    assert result.errors == []

    # Rang = 1 + max(rang des cibles nominales) = 1 + max(0, 1) = 2.
    node = env.service.registry.get_node(node_id)
    assert node.rank == 2
    assert env.service.repo.get_node(node_id).rank == 2
    assert node.name == "Atelier Nord"
    assert node.location == "Lyon"

    # Arcs créés du nœud vers chaque cible, audités source='onboarding'.
    trail = AuditTrail(env.service.registry.conn, FixedClock(_NOW), lock=env.service.registry.lock)
    for cible in (cible_r0, cible_r1):
        arc = env.service.registry.get_arc(node_id, cible.id)
        assert arc is not None
        entries = trail.history("arc", arc.id)
        assert entries and all(e.source == "onboarding" for e in entries)
        assert entries[0].operator_id == "op-42"

    # Tags créés par nom dans le projet, puis liés au nœud.
    tag_names = {t.name for t in env.service.registry.tags_of_node(node_id)}
    assert tag_names == {"Usinage", "Europe"}
    project_tags = {t.name for t in env.service.registry.list_tags(env.project.id)}
    assert {"Usinage", "Europe"} <= project_tags

    state = env.wizard.load(node_id)
    assert state.sections_done["identity"] == 1
    assert state.current_step == 2
    assert env.wizard.completeness(node_id) == (1, 4)


def test_save_section_identite_refus_bornes_cible_et_autoconnexion(env):
    node_id = env.wizard.start_draft(env.project.id, "Atelier")
    payload = {
        "name": "",
        "label": "Workshop",
        "location": None,
        "tag_names": [],
        "connections": [
            {"target_id": node_id, "gamma": 0.5, "beta": 0.5, "kind": "nominal"},
            {"target_id": "id-fantome", "gamma": 1.7, "beta": -0.2, "kind": "nominal"},
        ],
    }
    result = env.wizard.save_section(node_id, 1, payload, "op-1")
    assert not result.ok
    assert any("nom du nœud" in e for e in result.errors)
    assert any("auto-connexion" in e for e in result.errors)
    assert any("cible inconnu" in e for e in result.errors)
    assert any("gamma" in e and "[0, 1]" in e for e in result.errors)
    assert any("beta" in e and "[0, 1]" in e for e in result.errors)
    # RIEN n'est écrit : aucun arc, section toujours à 0.
    assert all(node_id not in (a.source_id, a.target_id) for a in env.service.registry.list_arcs())
    assert env.wizard.load(node_id).sections_done["identity"] == 0


# --- section 2 : cahier des charges + jalons -----------------------------------------


def test_save_section_cdc_jalon_invalide_rien_ecrit(env):
    node_id = env.wizard.start_draft(env.project.id, "Atelier")

    result = env.wizard.save_section(node_id, 2, _cdc_payload(valid=False), "op-1")
    assert not result.ok
    assert result.errors
    assert any("échéance" in e and "postérieure" in e for e in result.errors)
    # AUCUN jalon ni cahier des charges écrit, section toujours à 0.
    assert env.service.registry.list_milestones(node_id) == []
    assert env.service.client_db(node_id).latest_spec_sheet(node_id) is None
    assert env.wizard.load(node_id).sections_done["cdc"] == 0


def test_save_section_cdc_valide_puis_resauvegarde_idempotente(env):
    node_id = env.wizard.start_draft(env.project.id, "Atelier")
    payload = _cdc_payload()

    assert env.wizard.save_section(node_id, 2, payload, "op-1").ok
    jalons = env.service.registry.list_milestones(node_id)
    assert [m.name for m in jalons] == ["Proto", "Livraison"]
    assert [m.position for m in jalons] == [0, 1]
    spec = env.service.client_db(node_id).latest_spec_sheet(node_id)
    assert spec is not None and spec[0] == 1
    assert env.wizard.load(node_id).sections_done["cdc"] == 1

    # Resauvegarde : les jalons sont REMPLACÉS (pas dupliqués), le cdc versionné.
    assert env.wizard.save_section(node_id, 2, payload, "op-1").ok
    jalons = env.service.registry.list_milestones(node_id)
    assert [m.name for m in jalons] == ["Proto", "Livraison"]
    assert env.service.client_db(node_id).latest_spec_sheet(node_id)[0] == 2


def test_save_section_cdc_exige_au_moins_un_jalon(env):
    node_id = env.wizard.start_draft(env.project.id, "Atelier")
    payload = _cdc_payload()
    payload["milestones"] = []
    result = env.wizard.save_section(node_id, 2, payload, "op-1")
    assert not result.ok
    assert any("Au moins un jalon" in e for e in result.errors)


# --- section 3 : KPIs ----------------------------------------------------------------


def test_save_section_kpis_hors_bornes_rien_ecrit(env):
    node_id = env.wizard.start_draft(env.project.id, "Atelier")

    result = env.wizard.save_section(node_id, 3, {"risk.failure_probability": 1.7}, "op-1")
    assert not result.ok
    assert any("risk.failure_probability" in e for e in result.errors)
    # RIEN n'est écrit : le KPI reste non renseigné, la section à 0.
    assert env.service.registry.get_node(node_id).kpis.risk.failure_probability is None
    assert env.wizard.load(node_id).sections_done["kpis"] == 0

    # La même section passe avec des valeurs valides.
    assert env.wizard.save_section(node_id, 3, dict(_KPIS_OK), "op-1").ok
    node = env.service.registry.get_node(node_id)
    assert node.kpis.risk.failure_probability == 0.1
    assert node.kpis.time.lead_time_h == 24.0
    assert env.wizard.load(node_id).sections_done["kpis"] == 1


# --- section 4 : première évaluation AHP ---------------------------------------------


def test_save_section_ahp_incoherente_refusee_en_francais(env):
    node_id = env.wizard.start_draft(env.project.id, "Atelier")

    result = env.wizard.save_section(node_id, 4, dict(_AHP_INCOHERENT), "op-1")
    assert not result.ok
    assert any("incohérents" in e for e in result.errors)
    assert env.service.client_db(node_id).latest_assessment(node_id) is None
    assert env.wizard.load(node_id).sections_done["ahp"] == 0


def test_save_section_ahp_coherente_persistee_avec_iso_week(env):
    node_id = env.wizard.start_draft(env.project.id, "Atelier")

    assert env.wizard.save_section(node_id, 4, dict(_AHP_OK), "op-7").ok
    assessment = env.service.client_db(node_id).latest_assessment(node_id)
    assert assessment is not None
    assert assessment.consistency_ratio < CONSISTENCY_THRESHOLD
    assert assessment.iso_week == iso_week(_NOW)
    assert assessment.operator_id == "op-7"
    assert assessment.notes == "première évaluation"
    # submit_assessment a posé le Ud_local du nœud.
    assert env.service.repo.get_node(node_id).urgency.ud_local is not None
    assert env.wizard.load(node_id).sections_done["ahp"] == 1


# --- complete() ----------------------------------------------------------------------


def test_complete_refuse_tant_que_sections_manquent(env):
    node_id = env.wizard.start_draft(env.project.id, "Atelier")

    result = env.wizard.complete(node_id, "op-1")
    assert not result.ok
    assert any("sections restantes" in e for e in result.errors)
    # Toujours en brouillon, progression intacte.
    assert env.service.registry.get_node(node_id).onboarding_state == "draft"
    assert env.service.registry.get_onboarding(node_id) is not None

    # Une seule section validée ne suffit pas non plus.
    assert env.wizard.save_section(node_id, 1, _identity_payload(env), "op-1").ok
    assert not env.wizard.complete(node_id, "op-1").ok


def test_complete_apres_4_sections_bascule_et_evalue(env):
    node_id = env.wizard.start_draft(env.project.id, "Atelier")
    _full_onboarding(env, node_id)
    assert env.wizard.completeness(node_id) == (4, 4)

    result = env.wizard.complete(node_id, "op-1")
    assert result.ok
    assert result.errors == []

    node = env.service.registry.get_node(node_id)
    assert node.onboarding_state == "complete"
    assert env.service.registry.get_onboarding(node_id) is None
    assert env.wizard.completeness(node_id) == (4, 4)
    assert node_id not in [n.id for n in env.wizard.list_drafts(env.project.id)]

    # evaluate_all(persist=True) a évalué le nœud (urgence non None, persistée).
    assert node.urgency.ur is not None
    assert node.urgency.ud is not None
    assert node.urgency.adequation is not None
    assert env.service.client_db(node_id).urgency_series(node_id)

    # Idempotent : un nœud déjà complet (sans progression) répond ok.
    assert env.wizard.complete(node_id, "op-1").ok


# --- reprise après fermeture/réouverture ----------------------------------------------


def test_reprise_apres_fermeture_du_service(env, tmp_path):
    node_id = env.wizard.start_draft(env.project.id, "Atelier")
    identity = _identity_payload(env)
    brouillon_cdc = {"cdc": {"notes": "à finir"}, "milestones": []}
    assert env.wizard.save_section(node_id, 1, identity, "op-1").ok
    env.wizard.save_draft(node_id, 2, brouillon_cdc)
    env.service.close()

    svc2 = SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(_NOW))
    try:
        svc2.load_graph_from_registry()
        wizard2 = OnboardingService(svc2)

        state = wizard2.load(node_id)
        assert state.sections_done == {"identity": 1, "cdc": 0, "kpis": 0, "ahp": 0}
        assert state.draft["identity"] == identity
        assert state.draft["cdc"] == brouillon_cdc
        assert state.current_step == 2
        assert wizard2.completeness(node_id) == (1, 4)
        assert node_id in [n.id for n in wizard2.list_drafts(env.project.id)]
        # Le rang dérivé et les arcs ont survécu à la réouverture.
        reloaded = svc2.registry.get_node(node_id)
        in_memory = svc2.repo.get_node(node_id)
        assert reloaded is not None and reloaded.rank == 2
        assert in_memory is not None and in_memory.rank == 2
    finally:
        svc2.close()
