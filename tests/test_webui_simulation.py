"""Tests de la page Simulation refondue (Lot 15.4) - sans serveur, seede, FixedClock.

Couvre : ids historiques conserves, figure tornado (duck-typing), ajout de
lignes dynamiques (chocs, arcs, presets), evaluation d'un scenario composite
(tableau coherent avec MoteurScenario direct, DeltaUr nuls -> message, purete des
UrgencyState), criticite systematique, sauvegarde/chargement/suppression de
scenarios nommes (round-trip des lignes, doublon de nom en francais).
"""

from __future__ import annotations

import copy
from datetime import datetime
from types import SimpleNamespace

import pytest
from dash import html
from dash.exceptions import PreventUpdate

from supplyscore.core.clock import FixedClock
from supplyscore.domain.events import EVENT_CALIBRATION
from supplyscore.domain.models import ArcKind, TaskStatus
from supplyscore.graph.scenario import MoteurScenario, Scenario
from supplyscore.services import SupplyScoreService
from supplyscore.services.criticite import ServiceCriticite
from supplyscore.web_ui import set_service
from supplyscore.web_ui.components.figures import criticite_tornado_figure
from supplyscore.web_ui.pages import simulation

#: Mercredi 2026-06-10 12:00 locale - instant fige des tests.
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()


@pytest.fixture
def service(tmp_path):
    """Service seede (demo aleatoire deterministe) sur horloge figee."""
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(_NOW))
    svc.seed_demo(n_ranks=2, seed=1)
    set_service(svc)
    yield svc
    set_service(None)
    svc.close()


@pytest.fixture
def project_id(service):
    return service.registry.list_projects()[0].id


# Aides


def _find_components(component, type_name):
    """Tous les sous-composants dont l'id pattern-matching porte ce type."""
    found = []
    stack = [component]
    while stack:
        comp = stack.pop()
        cid = getattr(comp, "id", None)
        if isinstance(cid, dict) and cid.get("type") == type_name:
            found.append(comp)
        children = getattr(comp, "children", None)
        if isinstance(children, (list, tuple)):
            stack.extend(children)
        elif children is not None:
            stack.append(children)
    return found


def _states_from_rows(rows):
    """Reconstruit les 8 listes States (valeurs/ids) depuis des lignes rendues."""
    conteneur = html.Div(children=list(rows))

    def par_type(type_name):
        comps = _find_components(conteneur, type_name)
        return [getattr(c, "value", None) for c in comps], [c.id for c in comps]

    node_vals, node_ids = par_type("sim-choc-node")
    kind_vals, kind_ids = par_type("sim-choc-kind")
    val_vals, val_ids = par_type("sim-choc-val")
    arc_vals, arc_ids = par_type("sim-arc-del")
    return node_vals, node_ids, kind_vals, kind_ids, val_vals, val_ids, arc_vals, arc_ids


def _ids(type_name, indexes):
    return [{"type": type_name, "index": i} for i in indexes]


def _fournisseurs(service, project_id):
    """Les noeuds fournisseurs (rang > 0) du projet, tries par id (determinisme)."""
    nodes = [n for n in service.repo.nodes() if n.project_id == project_id and n.rank > 0]
    assert len(nodes) >= 2, "le seed doit fournir au moins 2 fournisseurs"
    return sorted(nodes, key=lambda n: n.id)


def _premier_arc_nominal(service, project_id):
    """Le premier arc nominal interne au projet (tri (source, cible))."""
    ids = {n.id for n in service.repo.nodes() if n.project_id == project_id}
    arcs = [
        a
        for a in service.repo.arcs()
        if a.kind_arc != ArcKind.BACKUP and a.source_id in ids and a.target_id in ids
    ]
    assert arcs, "le seed doit fournir au moins un arc nominal"
    return sorted(arcs, key=lambda a: (a.source_id, a.target_id))[0]


def _states_2_chocs_1_arc(service, project_id):
    """States " 2 chocs + 1 rupture d'arc " et le Scenario equivalent attendu."""
    n1, n2 = _fournisseurs(service, project_id)[:2]
    arc = _premier_arc_nominal(service, project_id)
    states = (
        [n1.id, n2.id],
        _ids("sim-choc-node", ["a1", "b2"]),
        [simulation.CHOC_UR, str(TaskStatus.ABANDONED)],
        _ids("sim-choc-kind", ["a1", "b2"]),
        [0.65, 1.0],
        _ids("sim-choc-val", ["a1", "b2"]),
        [f"{arc.source_id}->{arc.target_id}"],
        _ids("sim-arc-del", ["c3"]),
    )
    attendu = Scenario(
        surcharges_ur={n1.id: 0.65},
        statuts={n2.id: TaskStatus.ABANDONED},
        arcs_supprimes=[(arc.source_id, arc.target_id)],
    )
    return states, attendu


# Layout : ids historiques ET nouveaux


def test_layout_conserve_les_ids_historiques(service):
    tree = str(simulation.layout())
    for component_id in (
        "sim-node-dd",
        "sim-ur-slider",
        "sim-preset-fail",
        "sim-preset-ok",
        "sim-run-btn",
        "sim-dag-fig",
        "sim-bar-fig",
        "sim-status-dd",
        "sim-apply-confirm",
        "sim-apply-msg",
    ):
        assert component_id in tree, f"id historique manquant : {component_id}"


def test_layout_expose_les_nouvelles_cartes(service):
    tree = str(simulation.layout())
    for component_id in (
        "sim-chocs-rows",
        "sim-add-choc-btn",
        "sim-add-arc-btn",
        "sim-preset-dd",
        "sim-preset-add-btn",
        "sim-eval-btn",
        "sim-eval-msg",
        "sim-scn-table",
        "sim-scn-dag-fig",
        "sim-crit-btn",
        "sim-crit-fig",
        "sim-scn-name",
        "sim-scn-save-btn",
        "sim-scn-dd",
        "sim-scn-load-btn",
        "sim-scn-del-btn",
        "sim-scn-msg",
    ):
        assert component_id in tree, f"id manquant : {component_id}"


# Choc unitaire historique (conserve intact)


def test_triggered_id_retourne_none_hors_contexte_dash():
    assert simulation._triggered_id() is None


def test_node_options_callback_filtre_par_projet(service, project_id):
    options = simulation.node_options_callback({"project_id": project_id})
    assert options
    assert len(simulation.node_options_callback(None)) == len(service.repo.nodes())


def test_simulate_callback_historique_intact(service, project_id):
    node = _fournisseurs(service, project_id)[0]
    dag, bars, message = simulation.simulate_callback(1, node.id, 1.0, {"project_id": project_id})
    assert len(dag.data) >= 2
    assert bars.data
    assert "choc sur" in str(message)
    # Sans noeud selectionne : message d'aide, figures vides.
    _dag, _bars, message = simulation.simulate_callback(1, None, 1.0, {"project_id": project_id})
    assert "Sélectionnez" in str(message)


def test_apply_status_callback_persiste(service, project_id):
    node = _fournisseurs(service, project_id)[0]
    message = simulation.apply_status_callback(1, node.id, str(TaskStatus.DONE))
    assert "appliqué" in str(message)
    assert service.repo.get_node(node.id).status == TaskStatus.DONE
    # Sans statut choisi : message d'aide, rien n'est modifie.
    message = simulation.apply_status_callback(1, node.id, None)
    assert "ET un statut" in str(message)


# Figure tornado (duck-typing)


def _points_criticite():
    return [
        SimpleNamespace(node_name=f"N{i}", delta_ur_final=v, delta_ur_max=v + 0.1, nb_impactes=i)
        for i, v in enumerate([0.1, 0.4, 0.3, 0.2], start=1)
    ]


def test_tornado_vide_retourne_figure_message():
    fig = criticite_tornado_figure([])
    assert not fig.data
    assert "aucun nœud actif" in fig.layout.annotations[0].text.lower()


def test_tornado_barres_decroissantes_et_hover():
    fig = criticite_tornado_figure(_points_criticite())
    barre = fig.data[0]
    assert barre.orientation == "h"
    assert list(barre.x) == [0.4, 0.3, 0.2, 0.1]  # delta_ur_final decroissant
    assert list(barre.y) == ["N2", "N3", "N4", "N1"]
    assert "impacte 2 nœud(s)" in barre.hovertext[0]
    assert "ΔUr max = +0.500" in barre.hovertext[0]
    # Rouge degrade : la couleur des barres encode la valeur, bornee sur [0, max].
    assert barre.marker.colorscale is not None
    assert barre.marker.cmin == 0.0
    assert barre.marker.cmax == pytest.approx(0.4)


def test_tornado_tronque_au_top():
    fig = criticite_tornado_figure(_points_criticite(), top=2)
    assert list(fig.data[0].x) == [0.4, 0.3]


# Presets : mapping des 14 evenements calibres


def test_preset_chocs_couvre_les_14_evenements():
    assert set(simulation.PRESET_CHOCS) == set(EVENT_CALIBRATION)
    assert simulation.PRESET_CHOCS["panne_machine"] == (simulation.CHOC_UR, 0.9)
    kind, _ = simulation.PRESET_CHOCS["alerte_financiere_fournisseur"]
    assert kind == str(TaskStatus.ABANDONED)
    for kind, valeur in simulation.PRESET_CHOCS.values():
        assert kind in {simulation.CHOC_UR, str(TaskStatus.ABANDONED), str(TaskStatus.DONE)}
        assert 0.0 <= valeur <= 1.0


# Lignes dynamiques


def test_add_choc_ajoute_une_ligne_pattern(service, project_id, monkeypatch):
    monkeypatch.setattr(simulation, "_triggered_id", lambda: "sim-add-choc-btn")
    rows = simulation.rows_callback(1, None, None, None, [], None, None, {"project_id": project_id})
    assert len(rows) == 1
    for type_name in ("sim-choc-node", "sim-choc-kind", "sim-choc-val"):
        assert len(_find_components(rows[0], type_name)) == 1
    # Type par defaut : Ur force, slider visible.
    assert _find_components(rows[0], "sim-choc-kind")[0].value == simulation.CHOC_UR
    wrap = _find_components(rows[0], "sim-choc-val-wrap")[0]
    assert wrap.style == {"display": "inline-block"}


def test_add_arc_ajoute_une_ligne_rupture(service, project_id, monkeypatch):
    monkeypatch.setattr(simulation, "_triggered_id", lambda: "sim-add-choc-btn")
    rows = simulation.rows_callback(1, None, None, None, [], None, None, {"project_id": project_id})
    monkeypatch.setattr(simulation, "_triggered_id", lambda: "sim-add-arc-btn")
    rows = simulation.rows_callback(1, 1, None, None, rows, None, None, {"project_id": project_id})
    assert len(rows) == 2  # la ligne de choc existante est conservee
    arc_dd = _find_components(rows[1], "sim-arc-del")[0]
    options = list(arc_dd.options)
    assert options, "le dropdown des arcs doit proposer les arcs du projet"
    assert all("->" in str(o["value"]) for o in options)
    assert all("→" in str(o["label"]) for o in options)


def test_preset_panne_machine_preregle_ur_force(service, project_id, monkeypatch):
    monkeypatch.setattr(simulation, "_triggered_id", lambda: "sim-preset-add-btn")
    rows = simulation.rows_callback(
        None, None, 1, None, [], "panne_machine", None, {"project_id": project_id}
    )
    assert len(rows) == 1
    assert _find_components(rows[0], "sim-choc-kind")[0].value == simulation.CHOC_UR
    assert _find_components(rows[0], "sim-choc-val")[0].value == 0.9
    assert _find_components(rows[0], "sim-choc-val-wrap")[0].style == {"display": "inline-block"}


def test_preset_alerte_defaut_preregle_abandon(service, project_id, monkeypatch):
    monkeypatch.setattr(simulation, "_triggered_id", lambda: "sim-preset-add-btn")
    rows = simulation.rows_callback(
        None,
        None,
        1,
        None,
        [],
        "alerte_financiere_fournisseur",
        None,
        {"project_id": project_id},
    )
    assert _find_components(rows[0], "sim-choc-kind")[0].value == str(TaskStatus.ABANDONED)
    # Slider masque : le statut simule n'a pas de valeur d'Ur a regler.
    assert _find_components(rows[0], "sim-choc-val-wrap")[0].style == {"display": "none"}


@pytest.mark.parametrize(
    ("triggered", "preset", "scn"),
    [
        (None, None, None),  # hors contexte Dash : rien a faire
        ("sim-preset-add-btn", None, None),  # preset non choisi
        ("sim-scn-load-btn", None, None),  # aucun scenario selectionne
        ("sim-scn-load-btn", None, "fantome"),  # scenario inconnu
    ],
)
def test_rows_callback_prevent_update(service, project_id, monkeypatch, triggered, preset, scn):
    monkeypatch.setattr(simulation, "_triggered_id", lambda: triggered)
    with pytest.raises(PreventUpdate):
        simulation.rows_callback(1, 1, 1, 1, [], preset, scn, {"project_id": project_id})


def test_toggle_slider_visible_uniquement_pour_ur_force():
    assert simulation.toggle_choc_val_callback(simulation.CHOC_UR) == {"display": "inline-block"}
    assert simulation.toggle_choc_val_callback(str(TaskStatus.DONE)) == {"display": "none"}
    assert simulation.toggle_choc_val_callback(str(TaskStatus.ABANDONED)) == {"display": "none"}


# Evaluation du scenario composite


def test_evaluation_sans_clic_prevent_update(service, project_id):
    with pytest.raises(PreventUpdate):
        simulation.evaluate_scenario_callback(
            None, [], [], [], [], [], [], [], [], {"project_id": project_id}
        )


def test_evaluation_sans_ligne_complete_message(service, project_id):
    # Une ligne de choc SANS noeud choisi : incomplete, donc ignoree.
    data, _fig, message = simulation.evaluate_scenario_callback(
        1,
        [None],
        _ids("sim-choc-node", ["a1"]),
        [simulation.CHOC_UR],
        _ids("sim-choc-kind", ["a1"]),
        [1.0],
        _ids("sim-choc-val", ["a1"]),
        [],
        [],
        {"project_id": project_id},
    )
    assert data == []
    assert "Aucun choc complet" in str(message)


def test_evaluation_2_chocs_coherente_avec_moteur_direct(service, project_id):
    states, scenario = _states_2_chocs_1_arc(service, project_id)
    data, fig, message = simulation.evaluate_scenario_callback(
        1, *states, {"project_id": project_id}
    )
    assert data, "le tableau comparatif doit être non vide"
    assert len(data) <= 20

    resultat = MoteurScenario(service.repo, service.propagation).evaluer(scenario)
    nodes = [n for n in service.repo.nodes() if n.project_id == project_id]
    retenus = sorted(nodes, key=lambda n: (-abs(resultat.delta_ur[n.id]), n.name, n.id))[:20]
    attendu = [
        {
            "Nœud": n.name,
            "Ur avant": round(resultat.baseline_ur[n.id], 3),
            "Ur après": round(resultat.scenario_ur[n.id], 3),
            "ΔUr": round(resultat.delta_ur[n.id], 3),
            "ΔUd": round(resultat.delta_ud[n.id], 3),
        }
        for n in retenus
    ]
    assert data == attendu
    # Le noeud abandonne simule doit aggraver son propre Ur (ur_local -> 1.0)...
    assert any(ligne["ΔUr"] > 0 for ligne in data)
    # ... et la figure DAG est bien construite (aretes + noeuds au minimum).
    assert len(fig.data) >= 2
    assert "impacté" in str(message)


def test_evaluation_deltas_nuls_message(service, project_id):
    # Surcharge Ur == ur_local mesure d'un noeud ACTIF : scenario sans effet.
    candidats = [
        n
        for n in service.repo.nodes()
        if n.project_id == project_id
        and n.status == TaskStatus.ACTIVE
        and n.urgency.ur_local is not None
        and 0.0 <= n.urgency.ur_local <= 1.0
    ]
    assert candidats, "le seed doit fournir un nœud actif avec ur_local mesurable"
    node = candidats[0]
    data, _fig, message = simulation.evaluate_scenario_callback(
        1,
        [node.id],
        _ids("sim-choc-node", ["a1"]),
        [simulation.CHOC_UR],
        _ids("sim-choc-kind", ["a1"]),
        [node.urgency.ur_local],
        _ids("sim-choc-val", ["a1"]),
        [],
        [],
        {"project_id": project_id},
    )
    assert "ΔUr du scénario sont nuls" in str(message)
    assert all(ligne["ΔUr"] == 0.0 for ligne in data)


def test_evaluation_noeud_inconnu_message_invalide(service, project_id):
    data, _fig, message = simulation.evaluate_scenario_callback(
        1,
        ["fantome"],
        _ids("sim-choc-node", ["a1"]),
        [simulation.CHOC_UR],
        _ids("sim-choc-kind", ["a1"]),
        [1.0],
        _ids("sim-choc-val", ["a1"]),
        [],
        [],
        {"project_id": project_id},
    )
    assert data == []
    assert "Scénario invalide" in str(message)


def test_evaluation_est_pure_urgences_inchangees(service, project_id):
    """PURETE : aucun UrgencyState ni statut ne bouge apres evaluation via callback."""
    states, _scenario = _states_2_chocs_1_arc(service, project_id)
    avant = {n.id: (copy.deepcopy(n.urgency), n.status) for n in service.repo.nodes()}
    nb_arcs = len(service.repo.arcs())

    simulation.evaluate_scenario_callback(1, *states, {"project_id": project_id})

    apres = {n.id: (n.urgency, n.status) for n in service.repo.nodes()}
    assert apres == avant
    assert len(service.repo.arcs()) == nb_arcs  # l'arc " rompu " n'a pas ete supprime


def test_scenario_from_rows_derniere_ligne_par_noeud_l_emporte(service, project_id):
    n1, _ = _fournisseurs(service, project_id)[:2]
    scenario = simulation._scenario_from_rows(
        "x",
        [n1.id, n1.id],
        _ids("sim-choc-node", ["a1", "b2"]),
        [simulation.CHOC_UR, str(TaskStatus.DONE)],
        _ids("sim-choc-kind", ["a1", "b2"]),
        [0.5, 1.0],
        _ids("sim-choc-val", ["a1", "b2"]),
        [],
        [],
    )
    # La ligne d'index " b2 " (statut termine) ecrase la surcharge " a1 ".
    assert scenario.surcharges_ur == {}
    assert scenario.statuts == {n1.id: TaskStatus.DONE}


# Criticite systematique


def test_criticite_sans_clic_prevent_update(service, project_id):
    with pytest.raises(PreventUpdate):
        simulation.criticite_callback(None, {"project_id": project_id})


def test_criticite_figure_avec_barres(service, project_id):
    fig = simulation.criticite_callback(1, {"project_id": project_id})
    points = ServiceCriticite(service).top(project_id, 15)
    barre = fig.data[0]
    assert list(barre.x) == [p.delta_ur_final for p in points]
    assert list(barre.y) == [p.node_name for p in points]
    assert len(barre.x) <= 15


def test_criticite_sans_projet_figure_message(service):
    fig = simulation.criticite_callback(1, None)
    assert not fig.data
    assert "projet" in fig.layout.annotations[0].text.lower()


def test_criticite_projet_inconnu_figure_message(service):
    fig = simulation.criticite_callback(1, {"project_id": "fantome"})
    assert not fig.data
    assert "inconnu" in fig.layout.annotations[0].text.lower()


# Scenarios enregistres


def test_sauvegarde_chargement_round_trip(service, project_id, monkeypatch):
    states, attendu = _states_2_chocs_1_arc(service, project_id)

    monkeypatch.setattr(simulation, "_triggered_id", lambda: "sim-scn-save-btn")
    options, message = simulation.scenario_registry_callback(
        1, None, {"project_id": project_id}, "  Hiver rude  ", None, *states
    )
    assert "sauvegardé" in str(message)
    assert [o["label"] for o in options] == ["Hiver rude"]
    scn_id = options[0]["value"]

    # Persistance : payload JSON avec statuts en str, horodate par FixedClock.
    enregistre = service.registry.get_scenario(scn_id)
    assert enregistre is not None
    assert enregistre["created_at"] == _NOW
    assert enregistre["payload"]["nom"] == "Hiver rude"
    assert enregistre["payload"]["statuts"] == {nid: str(st) for nid, st in attendu.statuts.items()}
    assert enregistre["payload"]["surcharges_ur"] == attendu.surcharges_ur

    # Chargement : les lignes reconstruites redonnent le MEME scenario.
    monkeypatch.setattr(simulation, "_triggered_id", lambda: "sim-scn-load-btn")
    rows = simulation.rows_callback(
        None, None, None, 1, [], None, scn_id, {"project_id": project_id}
    )
    recharge = simulation._scenario_from_rows("Hiver rude", *_states_from_rows(rows))
    assert recharge.surcharges_ur == attendu.surcharges_ur
    assert recharge.statuts == attendu.statuts
    assert recharge.arcs_supprimes == attendu.arcs_supprimes


def test_sauvegarde_doublon_message_francais(service, project_id, monkeypatch):
    states, _ = _states_2_chocs_1_arc(service, project_id)
    monkeypatch.setattr(simulation, "_triggered_id", lambda: "sim-scn-save-btn")
    options, message = simulation.scenario_registry_callback(
        1, None, {"project_id": project_id}, "Hiver", None, *states
    )
    assert "sauvegardé" in str(message)
    options, message = simulation.scenario_registry_callback(
        2, None, {"project_id": project_id}, "Hiver", None, *states
    )
    assert "existe déjà" in str(message)
    assert len(options) == 1  # pas de doublon enregistre


def test_sauvegarde_sans_projet_ou_sans_nom(service, project_id, monkeypatch):
    monkeypatch.setattr(simulation, "_triggered_id", lambda: "sim-scn-save-btn")
    options, message = simulation.scenario_registry_callback(
        1, None, None, "Hiver", None, [], [], [], [], [], [], [], []
    )
    assert options == []
    assert "projet" in str(message)
    options, message = simulation.scenario_registry_callback(
        1, None, {"project_id": project_id}, "   ", None, [], [], [], [], [], [], [], []
    )
    assert "nom" in str(message)
    assert service.registry.list_scenarios(project_id) == []


def test_suppression_de_scenario(service, project_id, monkeypatch):
    states, _ = _states_2_chocs_1_arc(service, project_id)
    monkeypatch.setattr(simulation, "_triggered_id", lambda: "sim-scn-save-btn")
    options, _ = simulation.scenario_registry_callback(
        1, None, {"project_id": project_id}, "Éphémère", None, *states
    )
    scn_id = options[0]["value"]

    monkeypatch.setattr(simulation, "_triggered_id", lambda: "sim-scn-del-btn")
    options, message = simulation.scenario_registry_callback(
        None, 1, {"project_id": project_id}, "", scn_id, [], [], [], [], [], [], [], []
    )
    assert options == []
    assert "supprimé" in str(message)
    assert service.registry.get_scenario(scn_id) is None

    # Suppression sans selection : message d'aide, rien ne casse.
    _options, message = simulation.scenario_registry_callback(
        None, 1, {"project_id": project_id}, "", None, [], [], [], [], [], [], [], []
    )
    assert "Choisissez" in str(message)


def test_dropdown_scenarios_peuple_au_changement_de_projet(service, project_id, monkeypatch):
    # Declencheur store-project (navigation) : options listees, message vide.
    states, _ = _states_2_chocs_1_arc(service, project_id)
    monkeypatch.setattr(simulation, "_triggered_id", lambda: "sim-scn-save-btn")
    simulation.scenario_registry_callback(
        1, None, {"project_id": project_id}, "Référence", None, *states
    )
    monkeypatch.setattr(simulation, "_triggered_id", lambda: None)
    options, message = simulation.scenario_registry_callback(
        None, None, {"project_id": project_id}, None, None, [], [], [], [], [], [], [], []
    )
    assert [o["label"] for o in options] == ["Référence"]
    assert message == ""
