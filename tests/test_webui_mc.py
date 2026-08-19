"""Tests du Lot 13.4 : reglages du mode Monte Carlo dans l'UI - aucun serveur lance.

Couvre : la carte " Parametres du calcul d'urgence " de la page Projets
(controles refletant ``lead_time_mode(pid)``, application du mode MC avec
reevaluation et message vert, N hors bornes refuse en francais SANS ecriture,
ligne d'etat IC95 en mode MC / formule analytique sinon), les trois champs
triangulaires du volet 2 de la revue hebdo (affiches ET saisissables via le
mecanisme existant ``hebdo-kpi`` -> ``update_kpis``), et le round-trip JSON de
``TimeKPIs`` avec les champs triangulaires. Callbacks appeles directement
(fonctions module), service partage via ``set_service``, FixedClock.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest
from dash import no_update

from supplyscore.core.clock import FixedClock
from supplyscore.data.db import kpis_from_json, kpis_to_json
from supplyscore.domain.models import KPIBundle, Project, TimeKPIs
from supplyscore.mc.lead_time import N_TIRAGES_MAX, N_TIRAGES_MIN
from supplyscore.services import SupplyScoreService
from supplyscore.web_ui import set_service
from supplyscore.web_ui.pages import projects, weekly

#: Mercredi 2026-06-10 12:00 locale - semaine ISO " 2026-S24 ".
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()

#: N minimal accepte par le simulateur : suffisant et rapide pour les tests.
_N = 2_000

_OPERATOR = {"name": "testeuse"}

#: Les trois chemins triangulaires du mode Monte Carlo (E13).
_TRIANGULAIRES = ("time.lead_time_min_h", "time.lead_time_mode_h", "time.lead_time_max_h")


@pytest.fixture
def fixed_clock() -> FixedClock:
    return FixedClock(_NOW)


@pytest.fixture
def service(tmp_path: Path, fixed_clock: FixedClock):
    """Service a horloge figee (2026-S24), partage par les callbacks des pages."""
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=fixed_clock)
    set_service(svc)
    yield svc
    set_service(None)
    svc.close()


@pytest.fixture
def demo(service: SupplyScoreService) -> Project:
    """Projet de demonstration reproductible (KPIs, jalons et questionnaires)."""
    return service.seed_demo(n_ranks=2, seed=1)


@pytest.fixture
def store(demo: Project) -> dict:
    """Contenu de ``store-project`` apres selection du projet de demo."""
    return {"project_id": demo.id, "name": demo.name}


def _find_component(component, component_id):
    """Descente recursive dans l'arbre Dash jusqu'au composant d'id donne."""
    if getattr(component, "id", None) == component_id:
        return component
    children = getattr(component, "children", None)
    if children is None:
        return None
    if not isinstance(children, list | tuple):
        children = [children]
    for child in children:
        found = _find_component(child, component_id)
        if found is not None:
            return found
    return None


def _collect_kpi_input_ids(component, acc: list[dict]) -> list[dict]:
    """Ids pattern-matches ``{"type": "hebdo-kpi"}`` presents dans l'arbre Dash."""
    id_ = getattr(component, "id", None)
    if isinstance(id_, dict) and id_.get("type") == "hebdo-kpi":
        acc.append(id_)
    children = getattr(component, "children", None)
    if children is not None:
        if not isinstance(children, list | tuple):
            children = [children]
        for child in children:
            _collect_kpi_input_ids(child, acc)
    return acc


# Page Projets : carte " Parametres du calcul d'urgence "


class TestCarteParametresCalcul:
    def test_layout_contient_les_controles(self, service, demo) -> None:
        layout = projects.layout()
        dd = _find_component(layout, "mc-mode-dd")
        assert dd is not None
        assert {"label": "Analytique (loi normale)", "value": "analytique"} in dd.options
        assert {
            "label": "Monte Carlo (propagation sur le DAG)",
            "value": "monte_carlo",
        } in dd.options
        n_input = _find_component(layout, "mc-n-input")
        assert n_input is not None
        assert n_input.min == N_TIRAGES_MIN
        assert n_input.max == N_TIRAGES_MAX
        assert n_input.value == 10_000
        seed_input = _find_component(layout, "mc-seed-input")
        assert seed_input is not None
        assert seed_input.placeholder == "stable par semaine si vide"
        for component_id in ("mc-apply-btn", "mc-msg", "mc-status"):
            assert _find_component(layout, component_id) is not None

    def test_init_reflete_le_mode_stocke(self, service, demo, store) -> None:
        # Defaut : analytique, N par defaut, pas de graine, statut analytique.
        mode, n, graine, statut = projects.mc_init_callback(store, 0)
        assert mode == "analytique"
        assert n == 10_000
        assert graine is None
        assert "u_time : formule analytique (loi normale)." in str(statut)

        # Mode MC stocke : les controles le REFLETENT a la selection du projet.
        service.set_lead_time_mode(demo.id, "monte_carlo", n_tirages=_N, graine=123)
        mode, n, graine, statut = projects.mc_init_callback(store, 0)
        assert mode == "monte_carlo"
        assert n == _N
        assert graine == 123
        assert "Monte Carlo" in str(statut)

    def test_init_sans_projet(self, service) -> None:
        mode, n, graine, statut = projects.mc_init_callback(None, 0)
        assert mode is None
        assert n == 10_000
        assert graine is None
        assert "Sélectionnez un projet" in str(statut)

    def test_appliquer_mc_persiste_et_message_vert(self, service, demo, store) -> None:
        msg, _statut, refresh = projects.mc_apply_callback(1, store, "monte_carlo", _N, 42, 0)

        config = service.lead_time_mode(demo.id)
        assert config["mode"] == "monte_carlo"
        assert config["n_tirages"] == _N
        assert config["graine"] == 42
        assert "Mode de calcul appliqué : Monte Carlo (propagation sur le DAG)" in str(msg)
        assert refresh == 1
        # evaluate_all(persist=True) a tourne : le resultat MC est memorise.
        resultat = service.last_mc_result(demo.id)
        assert resultat is not None
        assert resultat.n_tirages == _N
        assert resultat.graine == 42

    def test_n_hors_bornes_erreur_francaise_sans_ecriture(self, service, demo, store) -> None:
        msg, statut, refresh = projects.mc_apply_callback(1, store, "monte_carlo", 100, None, 0)

        assert "n_tirages doit être dans" in str(msg)
        assert statut is no_update
        assert refresh is no_update
        # RIEN n'est ecrit : le projet reste en mode analytique, sans resultat MC.
        assert service.lead_time_mode(demo.id) == {"mode": "analytique"}
        assert service.last_mc_result(demo.id) is None

    def test_statut_ic95_en_mode_mc_apres_evaluation(self, service, demo, store) -> None:
        _msg, statut, _refresh = projects.mc_apply_callback(1, store, "monte_carlo", _N, None, 0)

        texte = str(statut)
        assert re.search(r"u_time : Monte Carlo, N=2 000 — IC95 moyen ±0\.\d{3}\.", texte), texte
        # La moyenne affichee est bien celle des ic95 du dernier resultat MC.
        resultat = service.last_mc_result(demo.id)
        assert resultat is not None
        node_ids = {n.id for n in service.repo.nodes_by_project(demo.id)}
        ics = [ic for nid, ic in resultat.ic95.items() if nid in node_ids]
        moyen = sum(ics) / len(ics)
        assert f"±{moyen:.3f}" in texte

    def test_statut_analytique_apres_retour_arriere(self, service, demo, store) -> None:
        projects.mc_apply_callback(1, store, "monte_carlo", _N, None, 0)
        msg, statut, refresh = projects.mc_apply_callback(2, store, "analytique", _N, None, 1)

        assert "Analytique (loi normale)" in str(msg)
        assert "u_time : formule analytique (loi normale)." in str(statut)
        assert refresh == 2
        assert service.last_mc_result(demo.id) is None  # purge du resultat perime

    def test_appliquer_sans_projet_ou_sans_mode(self, service, demo, store) -> None:
        msg, statut, refresh = projects.mc_apply_callback(1, None, "monte_carlo", _N, None, 0)
        assert "Sélectionnez d'abord un projet." in str(msg)
        assert statut is no_update and refresh is no_update

        msg, statut, refresh = projects.mc_apply_callback(1, store, None, _N, None, 0)
        assert "Choisissez un mode de calcul." in str(msg)
        assert statut is no_update and refresh is no_update


# Volet 2 hebdo : champs triangulaires


class TestVolet2ChampsTriangulaires:
    def _premier_noeud_actif(self, service) -> str:
        from supplyscore.domain.models import TaskStatus

        nodes = sorted(service.repo.nodes(), key=lambda n: n.id)
        actifs = [n for n in nodes if n.status is TaskStatus.ACTIVE]
        assert actifs, "le projet de démo doit contenir au moins un nœud actif"
        return actifs[0].id

    def test_champs_triangulaires_affiches_au_volet_2(self, service, demo) -> None:
        node_id = self._premier_noeud_actif(service)
        body = weekly._kpi_body(service, node_id)
        ids = _collect_kpi_input_ids(body, [])
        paths = [id_["index"] for id_ in ids]

        for path in _TRIANGULAIRES:
            assert path in paths
        # Ajoutes EN AVAL des champs du questionnaire (extension locale documentee).
        assert paths[-3:] == list(_TRIANGULAIRES)
        # Les libelles francais du volet mentionnent la loi triangulaire.
        texte = str(body)
        assert "Lead time min — triangulaire MC (h)" in texte
        assert "Lead time mode — triangulaire MC (h)" in texte
        assert "Lead time max — triangulaire MC (h)" in texte

    def test_saisie_lead_time_min_via_le_volet_ecrit_le_kpi(self, service, demo) -> None:
        node_id = self._premier_noeud_actif(service)
        # Les ids viennent du RENDU reel du volet : le test passe par le mecanisme existant (inputs pattern-matches + kpi_save_callback).
        ids = _collect_kpi_input_ids(weekly._kpi_body(service, node_id), [])
        values = [30.0 if id_["index"] == "time.lead_time_min_h" else None for id_ in ids]

        msg, _badge, _check = weekly.kpi_save_callback(
            1, {"node_id": node_id}, _OPERATOR, values, ids
        )

        assert "1 KPI mis à jour" in str(msg)
        node = service.registry.get_node(node_id)
        assert node is not None
        assert node.kpis.time.lead_time_min_h == 30.0

    def test_valeur_triangulaire_negative_refusee_sans_ecriture(self, service, demo) -> None:
        node_id = self._premier_noeud_actif(service)
        ids = _collect_kpi_input_ids(weekly._kpi_body(service, node_id), [])
        values = [-5.0 if id_["index"] == "time.lead_time_max_h" else None for id_ in ids]

        msg, badge, check = weekly.kpi_save_callback(
            1, {"node_id": node_id}, _OPERATOR, values, ids
        )

        assert "KPIs refusés" in str(msg)
        assert "time.lead_time_max_h" in str(msg)
        assert badge is no_update and check is no_update
        node = service.registry.get_node(node_id)
        assert node is not None
        assert node.kpis.time.lead_time_max_h is None  # rien n'est ecrit


# TimeKPIs : round-trip JSON avec les champs triangulaires


def test_time_kpis_round_trip_json_champs_triangulaires() -> None:
    bundle = KPIBundle(
        time=TimeKPIs(
            lead_time_h=40.0,
            lead_time_min_h=30.0,
            lead_time_mode_h=40.0,
            lead_time_max_h=60.0,
        )
    )
    rebuilt = kpis_from_json(kpis_to_json(bundle))
    assert rebuilt == bundle
    assert rebuilt.time.lead_time_min_h == 30.0
    assert rebuilt.time.lead_time_mode_h == 40.0
    assert rebuilt.time.lead_time_max_h == 60.0
    # Champs OPTIONNELS : absents du JSON d'une version anterieure -> None.
    ancien = kpis_from_json('{"time": {"lead_time_h": 40.0}}')
    assert ancien.time.lead_time_min_h is None
    assert ancien.time.lead_time_mode_h is None
    assert ancien.time.lead_time_max_h is None
