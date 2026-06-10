"""Tests de la page Onboarding (wizard 4 étapes) — aucun serveur lancé.

Les callbacks étant des fonctions nommées au niveau module (enregistrées via
``app.callback(...)(fn)`` dans ``register_callbacks``), ils sont appelés
directement ici, sans contexte de requête Dash : les States des formulaires
non montés sont simulés par None (ids simples) et listes vides
(pattern-matching), comme Dash le ferait.
"""

from __future__ import annotations

from typing import Any

import dash
import pytest
from dash import dcc, html, no_update
from dash.exceptions import PreventUpdate

from supplyscore.services import SupplyScoreService
from supplyscore.services.onboarding import OnboardingService
from supplyscore.web_ui import set_service
from supplyscore.web_ui.pages import onboarding
from supplyscore.web_ui.pages.questionnaire import PAIRS


@pytest.fixture
def service(tmp_path):
    """Service seedé avec une petite démo, partagé par les callbacks."""
    svc = SupplyScoreService(db_dir=tmp_path / "store")
    svc.seed_demo(n_ranks=2, seed=1)
    set_service(svc)
    yield svc
    set_service(None)


@pytest.fixture
def project_id(service):
    """Identifiant du projet de démo."""
    return service.registry.list_projects()[0].id


def _store(node_id=None, step=1):
    """Contenu du dcc.Store « store-onb » (position du wizard uniquement)."""
    return {"node_id": node_id, "step": step}


def _target_id(service, project_id, rank=0):
    """Id d'un nœud SEEDÉ (complete) du projet, au rang demandé."""
    for node in service.registry.list_nodes(project_id):
        if node.rank == rank and node.onboarding_state == "complete":
            return node.id
    raise AssertionError(f"aucun nœud seedé de rang {rank}")


# --- Construction des 28 States des 4 formulaires (ordre de _FORM_STATES) ----------

_DEFAULTS: dict[str, Any] = {
    "ident_name": None,
    "ident_label": None,
    "ident_location": None,
    "ident_tags": None,
    "ident_targets": None,
    "ident_gamma": None,
    "ident_beta": None,
    "ident_arckind": None,
    "cdc_budget": None,
    "cdc_unitcost": None,
    "cdc_currency": None,
    "cdc_standards": None,
    "cdc_certifications": None,
    "cdc_scrap": None,
    "dlv_names": [],
    "dlv_qtys": [],
    "dlv_units": [],
    "ms_names": [],
    "ms_kinds": [],
    "ms_starts": [],
    "ms_deadlines": [],
    "kpi_values": [],
    "kpi_ids": [],
    "pair_values": [],
    "pair_ids": [],
    "score_values": [],
    "score_ids": [],
    "ahp_notes": None,
}


def _form_args(**over):
    """Tuple des 28 valeurs de formulaire, formulaires non montés par défaut."""
    assert set(over) <= set(_DEFAULTS), f"clés inconnues : {set(over) - set(_DEFAULTS)}"
    data = {**_DEFAULTS, **over}
    return tuple(data[key] for key in _DEFAULTS)


def _identity_args(service, project_id, name="Atelier Test"):
    """States de l'étape 1 (identité valide, connectée à un nœud de rang 0)."""
    return _form_args(
        ident_name=name,
        ident_label="Workshop",
        ident_location="Lyon",
        ident_tags=["Usinage"],
        ident_targets=[_target_id(service, project_id, rank=0)],
        ident_gamma=0.6,
        ident_beta=0.4,
        ident_arckind="nominal",
    )


def _cdc_args():
    """States de l'étape 2 (un livrable + un jalon valide)."""
    return _form_args(
        cdc_budget=50_000,
        cdc_unitcost=12.5,
        cdc_currency="EUR",
        cdc_standards="ISO 9001",
        cdc_certifications="NADCAP",
        cdc_scrap=0.02,
        dlv_names=["Carter"],
        dlv_qtys=[100],
        dlv_units=["pièces"],
        ms_names=["Proto"],
        ms_kinds=["proto"],
        ms_starts=["2030-01-01"],
        ms_deadlines=["2030-03-01"],
    )


def _kpi_args():
    """States de l'étape 3 (un seul KPI renseigné)."""
    return _form_args(
        kpi_values=[24.0],
        kpi_ids=[{"type": "onb-kpi", "index": "time.lead_time_h"}],
    )


def _ahp_args():
    """States de l'étape 4 (toutes paires à 0 -> Saaty 1.0 -> CR = 0)."""
    return _form_args(
        pair_values=[0] * len(PAIRS),
        pair_ids=[{"type": "onb-ahp-pair", "index": f"{i}-{j}"} for i, j in PAIRS],
        score_values=[3, 3, 3, 3],
        score_ids=[{"type": "onb-ahp-score", "index": str(k)} for k in range(4)],
        ahp_notes="première évaluation",
    )


# --- Layout --------------------------------------------------------------------------


def test_layout_contient_les_ids_du_wizard(service):
    tree = str(onboarding.layout())
    for component_id in (
        "store-onb",
        "onb-start-btn",
        "onb-start-name",
        "onb-start-label",
        "onb-drafts",
        "onb-step-content",
        "onb-prev-btn",
        "onb-next-btn",
        "onb-draft-btn",
        "onb-msg",
    ):
        assert component_id in tree


def test_register_callbacks_smoke(service):
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    app.layout = html.Div(
        [
            dcc.Store(id="store-project"),
            dcc.Store(id="store-operator"),
            onboarding.layout(),
        ]
    )
    onboarding.register_callbacks(app)
    assert app.callback_map


# --- start_onboarding_callback -------------------------------------------------------


def test_start_onboarding_cree_un_draft_et_pointe_le_store(service, project_id):
    store, msg = onboarding.start_onboarding_callback(
        1, {"project_id": project_id}, "Fournisseur T", "Supplier", _store()
    )
    assert store["step"] == 1
    node_id = store["node_id"]
    assert node_id
    node = service.registry.get_node(node_id)
    assert node is not None
    assert node.onboarding_state == "draft"
    assert node.name == "Fournisseur T"
    assert "créé" in str(msg)


def test_start_onboarding_exige_projet_et_nom(service, project_id):
    store, msg = onboarding.start_onboarding_callback(1, None, "X", "Supplier", _store())
    assert store is no_update
    assert "projet actif" in str(msg)

    store, msg = onboarding.start_onboarding_callback(
        1, {"project_id": project_id}, "   ", "Supplier", _store()
    )
    assert store is no_update
    assert "obligatoire" in str(msg)


# --- render_step_callback ------------------------------------------------------------


def test_render_step_sans_brouillon_affiche_un_message(service):
    children = onboarding.render_step_callback(_store(), 0)
    assert "Aucun onboarding en cours" in str(children)


def test_render_step_1_contient_le_formulaire_identite(service, project_id):
    wizard = OnboardingService(service)
    node_id = wizard.start_draft(project_id, "Atelier R")
    children = onboarding.render_step_callback(_store(node_id, 1), 0)
    tree = str(children)
    assert "onb-ident-name" in tree
    assert "onb-step" in tree  # bandeau des 4 étapes


def test_render_step_4_contient_le_formulaire_ahp(service, project_id):
    wizard = OnboardingService(service)
    node_id = wizard.start_draft(project_id, "Atelier R")
    children = onboarding.render_step_callback(_store(node_id, 4), 0)
    assert "onb-ahp-notes" in str(children)


def test_render_step_2_et_3_contiennent_cdc_et_kpis(service, project_id):
    wizard = OnboardingService(service)
    node_id = wizard.start_draft(project_id, "Atelier R")
    assert "onb-cdc-budget" in str(onboarding.render_step_callback(_store(node_id, 2), 0))
    assert "onb-kpi" in str(onboarding.render_step_callback(_store(node_id, 3), 0))


# --- save_section_callback -----------------------------------------------------------


def test_save_section_etape_1_valide_passe_a_l_etape_2(service, project_id):
    wizard = OnboardingService(service)
    node_id = wizard.start_draft(project_id, "Atelier S")

    store, msg = onboarding.save_section_callback(
        1, _store(node_id, 1), {"name": "op-test"}, *_identity_args(service, project_id)
    )

    assert store == {"node_id": node_id, "step": 2}
    assert "validée" in str(msg)
    state = wizard.load(node_id)
    assert state.sections_done["identity"] == 1
    assert state.current_step == 2


def test_save_section_etape_1_nom_vide_reste_sur_l_etape(service, project_id):
    wizard = OnboardingService(service)
    node_id = wizard.start_draft(project_id, "Atelier S")

    store, msg = onboarding.save_section_callback(
        1, _store(node_id, 1), None, *_form_args(ident_name="   ")
    )

    assert store is no_update
    assert "obligatoire" in str(msg)
    state = wizard.load(node_id)
    assert state.sections_done["identity"] == 0
    assert state.current_step == 1


def test_save_section_sans_brouillon_affiche_une_erreur(service):
    store, msg = onboarding.save_section_callback(1, _store(), None, *_form_args())
    assert store is no_update
    assert "Aucun onboarding en cours" in str(msg)


def test_parcours_complet_1_a_4_complete_le_noeud(service, project_id):
    wizard = OnboardingService(service)
    node_id = wizard.start_draft(project_id, "Atelier complet")

    store, msg = onboarding.save_section_callback(
        1, _store(node_id, 1), None, *_identity_args(service, project_id)
    )
    assert store["step"] == 2
    store, msg = onboarding.save_section_callback(1, store, None, *_cdc_args())
    assert store["step"] == 3
    store, msg = onboarding.save_section_callback(1, store, None, *_kpi_args())
    assert store["step"] == 4
    store, msg = onboarding.save_section_callback(1, store, None, *_ahp_args())

    # Après l'étape 4 : complete() + message de succès + store remis à zéro.
    assert store == {"node_id": None, "step": 1}
    assert "terminé" in str(msg)
    node = service.registry.get_node(node_id)
    assert node.onboarding_state == "complete"
    assert service.registry.get_onboarding(node_id) is None
    # Les écritures des sections sont bien là : jalon, KPI, évaluation AHP.
    assert [m.name for m in service.registry.list_milestones(node_id)] == ["Proto"]
    assert node.kpis.time.lead_time_h == pytest.approx(24.0)
    assessment = service.client_db(node_id).latest_assessment(node_id)
    assert assessment is not None
    assert assessment.consistency_ratio == pytest.approx(0.0)


# --- save_draft_callback -------------------------------------------------------------


def test_save_draft_restitue_le_brouillon_via_load(service, project_id):
    wizard = OnboardingService(service)
    node_id = wizard.start_draft(project_id, "Brouillon B")

    msg = onboarding.save_draft_callback(
        1,
        _store(node_id, 1),
        *_form_args(ident_name="Brouillon B2", ident_tags=["incomplet"]),
    )

    assert "Brouillon enregistré — vous pouvez quitter." in str(msg)
    state = wizard.load(node_id)
    draft = state.draft["identity"]
    assert draft["name"] == "Brouillon B2"
    assert draft["tag_names"] == ["incomplet"]
    # save_draft ne valide RIEN : aucune section marquée faite.
    assert state.sections_done["identity"] == 0


def test_save_draft_sans_brouillon_affiche_une_erreur(service):
    msg = onboarding.save_draft_callback(1, _store(), *_form_args())
    assert "rien à enregistrer" in str(msg)


# --- resume_callback -----------------------------------------------------------------


def test_resume_restaure_node_id_et_etape(service, project_id):
    wizard = OnboardingService(service)
    node_id = wizard.start_draft(project_id, "À reprendre")
    payload = {
        "name": "À reprendre",
        "label": "Supplier",
        "location": "",
        "tag_names": [],
        "connections": [],
    }
    assert wizard.save_section(node_id, 1, payload, "op-1").ok  # current_step -> 2

    store = onboarding.resume_callback([1], [{"type": "onb-resume", "index": node_id}], _store())
    assert store == {"node_id": node_id, "step": 2}


def test_resume_sans_clic_ou_id_inconnu_ne_change_rien(service):
    with pytest.raises(PreventUpdate):
        onboarding.resume_callback([None], [{"type": "onb-resume", "index": "x"}], _store())
    with pytest.raises(PreventUpdate):
        onboarding.resume_callback([1], [{"type": "onb-resume", "index": "id-fantome"}], _store())


# --- navigation : précédent / bandeau d'étapes ----------------------------------------


def test_prev_step_recule_sans_passer_sous_1(service, project_id):
    assert onboarding.prev_step_callback(1, _store("nid", 3)) == _store("nid", 2)
    assert onboarding.prev_step_callback(1, _store("nid", 1)) == _store("nid", 1)


def test_goto_step_ne_revient_que_sur_une_section_validee(service, project_id):
    wizard = OnboardingService(service)
    node_id = wizard.start_draft(project_id, "Atelier G")
    payload = {
        "name": "Atelier G",
        "label": "Supplier",
        "location": "",
        "tag_names": [],
        "connections": [],
    }
    assert wizard.save_section(node_id, 1, payload, "op-1").ok

    ids = [{"type": "onb-step", "index": str(k)} for k in range(1, 5)]
    store = onboarding.goto_step_callback([1, None, None, None], ids, _store(node_id, 2))
    assert store == {"node_id": node_id, "step": 1}

    # Section 3 jamais validée : pas de saut en avant.
    with pytest.raises(PreventUpdate):
        onboarding.goto_step_callback([None, None, 1, None], ids, _store(node_id, 2))


# --- brouillons : liste et lignes dynamiques ------------------------------------------


def test_render_drafts_liste_les_brouillons_avec_badge(service, project_id):
    sans_projet = onboarding.render_drafts_callback(None, 0, _store())
    assert "projet actif" in str(sans_projet)

    vide = onboarding.render_drafts_callback({"project_id": project_id}, 0, _store())
    assert "Aucun brouillon" in str(vide)

    wizard = OnboardingService(service)
    node_id = wizard.start_draft(project_id, "Brouillon liste")
    rows = onboarding.render_drafts_callback({"project_id": project_id}, 0, _store())
    tree = str(rows)
    assert "Brouillon liste" in tree
    assert "0/4 sections" in tree
    assert "Reprendre" in tree
    assert node_id in tree


def test_add_deliverable_et_milestone_ajoutent_une_ligne(service):
    rows = onboarding.add_deliverable_callback(1, [])
    assert len(rows) == 1
    assert "onb-cdc-dlv-name" in str(rows[0])

    rows = onboarding.add_milestone_callback(1, [html.Div("ligne existante")])
    assert len(rows) == 2
    assert "onb-cdc-ms-name" in str(rows[-1])
