"""Tests du polissage E16 (Lots 16.2 + 16.3) — dashboard, hebdo, pondération.

Couvre, sans serveur :

* la palette du DAG (Lot 16.2) : dropdown ``dash-palette-dd`` à 3 palettes,
  persistance PAR PROJET via ``project_settings('palette')`` (écriture quand
  le dropdown déclenche, relecture au rendu, défaut RdYlGn), colorscale
  réellement transmise à ``dashboard_dag_figure`` et légende cohérente ;
* les ``dcc.Loading`` autour des zones lentes (DAG, tableau, figures
  PROMETHEE/corrélation, corps des volets hebdo, aperçu des poids) — les ids
  internes restent posés sur les composants enveloppés ;
* les états vides explicites : bandeau d'invitation du dashboard sans
  projet, bandeau « Sélectionnez un nœud pour démarrer la revue. » du hebdo ;
* les indicateurs de progression (Lot 16.3) : compteur live « x/6 paires
  ajustées » du volet 1 (fonction de comptage PURE) et « x/9 jugements
  saisis » sous les dropdowns FBWM ;
* l'anti double-clic : ``running=`` désactive les boutons de sauvegarde
  pendant le traitement (specs ``_callback_list``) ;
* le format français des nombres dans les TEXTES (virgule décimale) ;
* AUCUNE régression d'id : les ids consommés par les parcours e2e
  (tests/ui/test_e2e_parcours.py) sont toujours présents dans les layouts.

Callbacks appelés directement (fonctions module), service seedé partagé via
``set_service`` et libéré en teardown, FixedClock.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import dash
import pytest
from dash import dcc

from supplyscore.core.clock import FixedClock
from supplyscore.domain.models import TaskStatus
from supplyscore.services import SupplyScoreService
from supplyscore.web_ui import set_service
from supplyscore.web_ui.components.figures import dashboard_dag_figure
from supplyscore.web_ui.pages import dashboard, ponderation, weekly
from supplyscore.web_ui.pages.questionnaire import PAIRS

#: Mercredi 2026-06-10 12:00 locale — semaine ISO « 2026-S24 ».
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()

_OPERATOR = {"name": "testeuse"}


@pytest.fixture
def seeded(tmp_path: Path):
    """Couple (service seedé à horloge figée, projet de démo) partagé par les callbacks."""
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(_NOW))
    project = svc.seed_demo(n_ranks=2, seed=1)
    set_service(svc)
    yield svc, project
    set_service(None)
    svc.close()


@pytest.fixture
def service_vide(tmp_path: Path):
    """Service SANS aucun nœud (état vide intégral), partagé par les callbacks."""
    svc = SupplyScoreService(db_dir=tmp_path / "vide", clock=FixedClock(_NOW))
    set_service(svc)
    yield svc
    set_service(None)
    svc.close()


def _project_data(project) -> dict:
    """Contenu du ``dcc.Store`` « store-project » tel que posé par la page Projets."""
    return {"project_id": project.id, "name": project.name}


def _premier_noeud(service) -> str:
    """Premier nœud ACTIF (ordre déterministe) du projet de démo seedé."""
    nodes = sorted(service.repo.nodes(), key=lambda n: n.id)
    return next(n.id for n in nodes if n.status is TaskStatus.ACTIVE)


# --- Helpers d'inspection d'arbres de composants Dash -------------------------------


def _walk(component):
    """Itère récursivement sur un arbre de composants Dash (children imbriqués)."""
    yield component
    children = getattr(component, "children", None)
    if children is None:
        return
    if isinstance(children, (list, tuple)):
        for child in children:
            yield from _walk(child)
    else:
        yield from _walk(children)


def _ids(component) -> set:
    """Ensemble des ids chaîne présents dans l'arbre de composants."""
    return {c.id for c in _walk(component) if isinstance(getattr(c, "id", None), str)}


def _texts(component) -> str:
    """Concatène tous les textes feuilles de l'arbre de composants."""
    return " ".join(c for c in _walk(component) if isinstance(c, str))


def _ids_sous_loading(layout) -> set:
    """Ids des composants enveloppés par un ``dcc.Loading`` du layout."""
    couverts: set = set()
    for c in _walk(layout):
        if isinstance(c, dcc.Loading):
            couverts |= _ids(c)
    return couverts


def _trace_noeuds(fig):
    """Trace des nœuds du DAG (la seule à porter une échelle de couleur)."""
    return next(t for t in fig.data if getattr(t, "marker", None) and t.marker.showscale)


def _specs_running(app) -> dict[str, dict]:
    """Specs ``running`` par sortie, depuis la liste de callbacks de l'app."""
    return {spec["output"]: spec["running"] for spec in app._callback_list if spec.get("running")}


# --- Palette du DAG (Lot 16.2) ---------------------------------------------------------


class TestPalette:
    def test_dropdown_trois_palettes_defaut_rdylgn(self, seeded):
        page = dashboard.layout()
        dd = next(c for c in _walk(page) if getattr(c, "id", None) == "dash-palette-dd")
        assert {o["value"] for o in dd.options} == {"RdYlGn", "RdYlBu", "Viridis"}
        assert dd.value == "RdYlGn"
        assert dd.clearable is False
        labels = {o["label"] for o in dd.options}
        assert "Rouge-Vert (défaut)" in labels
        assert "Rouge-Bleu (daltonisme)" in labels

    def test_choix_au_dropdown_persiste_par_projet(self, seeded, monkeypatch):
        service, project = seeded
        monkeypatch.setattr(dashboard, "_triggered_id", lambda: "dash-palette-dd")

        _, fig, _, _ = dashboard.update_dashboard_callback(
            _project_data(project), None, None, "RdYlBu"
        )

        assert service.registry.get_setting(project.id, "palette") == "RdYlBu"
        # Le dropdown se resynchronise sur la valeur persistée du projet…
        assert dashboard.palette_value_callback(_project_data(project)) == "RdYlBu"
        # … et la figure rendue utilise bien la palette choisie.
        nodes, arcs = service.repo.nodes(), service.repo.arcs()
        reference = dashboard_dag_figure(nodes, arcs, colorscale="RdYlBu")
        assert _trace_noeuds(fig).marker.colorscale == _trace_noeuds(reference).marker.colorscale

    def test_palette_persistee_relue_au_rendu(self, seeded):
        service, project = seeded
        service.registry.set_setting(project.id, "palette", "Viridis")

        # Rendu SANS déclencheur dropdown (navigation) : la valeur stockée fait foi.
        _, fig, _, _ = dashboard.update_dashboard_callback(_project_data(project), None)

        nodes, arcs = service.repo.nodes(), service.repo.arcs()
        attendue = _trace_noeuds(dashboard_dag_figure(nodes, arcs, colorscale="Viridis"))
        defaut = _trace_noeuds(dashboard_dag_figure(nodes, arcs))
        assert _trace_noeuds(fig).marker.colorscale == attendue.marker.colorscale
        assert _trace_noeuds(fig).marker.colorscale != defaut.marker.colorscale

    def test_defaut_rdylgn_sans_reglage_ni_projet(self, seeded):
        _service, project = seeded
        assert dashboard.palette_value_callback(_project_data(project)) == "RdYlGn"
        assert dashboard.palette_value_callback(None) == "RdYlGn"

    def test_palette_inconnue_retombe_au_defaut_sans_persistance(self, seeded):
        service, project = seeded
        effective = dashboard._palette_effective(service, project.id, "Zorglub", persister=True)
        assert effective == "RdYlGn"
        assert service.registry.get_setting(project.id, "palette") is None

    def test_sans_projet_la_palette_choisie_sert_sans_persistance(self, seeded):
        service, _project = seeded
        assert dashboard._palette_effective(service, None, "RdYlBu", persister=True) == "RdYlBu"

    def test_legende_coherente_avec_la_palette(self, seeded):
        service, _project = seeded
        nodes, arcs = service.repo.nodes(), service.repo.arcs()
        attendus = {"RdYlGn": "vert", "RdYlBu": "bleu", "Viridis": "jaune"}
        for palette, couleur in attendus.items():
            fig = dashboard_dag_figure(nodes, arcs, colorscale=palette)
            legende = fig.layout.annotations[0].text
            assert couleur in legende, f"légende incohérente pour {palette} : {legende}"
            assert "adéquation A" in legende


# --- dcc.Loading autour des zones lentes ------------------------------------------------


class TestLoading:
    def test_dashboard_dag_tableau_et_figures_sous_loading(self, seeded):
        couverts = _ids_sous_loading(dashboard.layout())
        for attendu in ("dash-dag", "dash-table", "dash-promethee-fig", "dash-correlation-fig"):
            assert attendu in couverts, f"{attendu} n'est pas enveloppé par dcc.Loading"
        assert "Loading" in str(dashboard.layout())

    def test_hebdo_corps_des_volets_sous_loading(self, seeded):
        couverts = _ids_sous_loading(weekly.layout())
        for attendu in ("hebdo-ahp-body", "hebdo-kpi-body", "hebdo-ms-body", "hebdo-ev-body"):
            assert attendu in couverts, f"{attendu} n'est pas enveloppé par dcc.Loading"

    def test_ponderation_apercu_sous_loading(self, seeded):
        couverts = _ids_sous_loading(ponderation.layout())
        assert "pond-weights-fig" in couverts
        assert "pond-preview-badges" in couverts


# --- États vides explicites --------------------------------------------------------------


class TestEtatsVides:
    def test_dashboard_sans_projet_bandeau_d_invitation(self, seeded):
        bandeau = dashboard.empty_state_callback(None)
        texte = _texts(bandeau)
        assert "Aucun projet sélectionné" in texte
        assert "Projets" in texte

    def test_dashboard_avec_projet_aucun_bandeau(self, seeded):
        _service, project = seeded
        assert dashboard.empty_state_callback(_project_data(project)) is None

    def test_dashboard_repo_vide_invite_a_creer(self, service_vide):
        texte = _texts(dashboard.empty_state_callback(None))
        assert "créez un projet" in texte
        assert "démo" in texte

    def test_hebdo_sans_noeud_bandeau_de_selection(self, seeded):
        bandeau = weekly.empty_banner_callback(None)
        assert _texts(bandeau) == "Sélectionnez un nœud pour démarrer la revue."
        assert weekly.empty_banner_callback("") is not None

    def test_hebdo_noeud_choisi_bandeau_efface(self, seeded):
        assert weekly.empty_banner_callback("n-quelconque") is None

    def test_layouts_portent_les_zones_d_etat_vide(self, seeded):
        assert "dash-empty-banner" in str(dashboard.layout())
        rendu = str(weekly.layout())
        assert "hebdo-empty-banner" in rendu
        assert "Sélectionnez un nœud pour démarrer la revue." in rendu


# --- Indicateurs de progression (Lot 16.3) ------------------------------------------------


class TestCompteurPaires:
    def test_fonction_pure_de_comptage(self):
        assert weekly.compte_paires_ajustees([]) == 0
        assert weekly.compte_paires_ajustees([0, 0, None]) == 0
        assert weekly.compte_paires_ajustees([1, -4, 0, None, 2, 8]) == 4
        assert weekly.compte_paires_ajustees([-8] * 6) == 6

    def test_texte_du_compteur(self):
        assert weekly.texte_paires_ajustees([]) == f"0/{len(PAIRS)} paires ajustées"
        assert weekly.texte_paires_ajustees([0] * 6) == "0/6 paires ajustées"
        assert weekly.texte_paires_ajustees([1, 0, 0, 0, 0, -2]) == "2/6 paires ajustées"

    def test_callback_live(self):
        assert weekly.ahp_pair_count_callback([0, 3, 0, 0, 0, 0]) == "1/6 paires ajustées"
        assert weekly.ahp_pair_count_callback(None) == "0/6 paires ajustées"

    def test_volet_1_porte_le_compteur_initialise(self, seeded):
        service, _project = seeded
        node_id = _premier_noeud(service)
        corps = weekly._ahp_body(service, node_id)
        assert "hebdo-ahp-pair-count" in _ids(corps)
        assert re.search(r"\d/6 paires ajustées", _texts(corps))


class TestCompteurJugements:
    def test_fonction_pure_de_comptage(self):
        assert ponderation.NB_JUGEMENTS == 9
        assert ponderation.compte_jugements_saisis([]) == 0
        assert ponderation.compte_jugements_saisis(["a", "", None, "b"]) == 2

    def test_jugements_rendus_compteur_complet(self):
        rendu = ponderation.render_judgments_callback("time", "co2")
        assert "pond-judgment-count" in _ids(rendu)
        assert "9/9 jugements saisis" in _texts(rendu)

    def test_selection_incomplete_compteur_a_zero(self):
        for best, worst in ((None, None), ("time", None), ("time", "time")):
            rendu = ponderation.render_judgments_callback(best, worst)
            assert "0/9 jugements saisis" in _texts(rendu)


# --- Anti double-clic (running=) -----------------------------------------------------------


class TestAntiDoubleClic:
    def test_ponderation_save_desactive_pendant_le_traitement(self):
        app = dash.Dash(__name__, suppress_callback_exceptions=True)
        app.layout = ponderation.layout()
        ponderation.register_callbacks(app)
        # Contrat existant intact : la page reste à 5 callbacks.
        assert len(app.callback_map) == 5
        runnings = _specs_running(app)
        assert any(
            spec.get("running") == {"pond-save-btn.disabled": True} for spec in runnings.values()
        )

    def test_hebdo_boutons_de_sauvegarde_desactives_pendant_le_traitement(self):
        app = dash.Dash(__name__, suppress_callback_exceptions=True)
        weekly.register_callbacks(app)
        actifs = set()
        for spec in _specs_running(app).values():
            actifs |= set(spec.get("running", {}))
        for bouton in (
            "hebdo-ahp-confirm-btn",
            "hebdo-ahp-save-btn",
            "hebdo-kpi-save-btn",
            "hebdo-kpi-none-btn",
            "hebdo-ms-save-btn",
            "hebdo-ev-apply-btn",
            "hebdo-decision-btn",
            "hebdo-ev-none-btn",
            "hebdo-complete-btn",
        ):
            assert f"{bouton}.disabled" in actifs, f"{bouton} sans anti double-clic"


# --- Format français des nombres dans les textes -------------------------------------------


class TestFormatFrancais:
    def test_helpers_virgule_decimale(self):
        assert dashboard._nombre_fr(0.01, 3) == "0,010"
        assert weekly._nombre_fr(72.345, 1) == "72,3"
        assert ponderation._nombre_fr(0.1, 2) == "0,10"

    def test_cartes_kpi_dashboard_en_virgule(self, seeded):
        _service, project = seeded
        cards, _, rows, _ = dashboard.update_dashboard_callback(_project_data(project), None)
        texte = " ".join(_texts(card) for card in cards)
        assert re.search(r"\d+,\d", texte), texte  # « A moyen du projet » en virgule
        # CHOIX DOCUMENTÉ : la DataTable reste en NOTATION POINT (colonnes
        # numériques — tri/filtre natifs sur des floats).
        assert all(isinstance(r["Ud"], float) for r in rows)

    def test_message_hebdo_ud_en_virgule(self, seeded):
        service, _project = seeded
        node_id = _premier_noeud(service)
        message, _badge, _check = weekly.ahp_confirm_callback(1, {"node_id": node_id}, _OPERATOR)
        assert re.search(r"Ud = \d,\d{3}", str(message))

    def test_badges_fbwm_en_virgule(self):
        bo_ids = [{"type": "pond-bo", "index": b} for b in ponderation.BLOCKS if b != "time"]
        ow_ids = [
            {"type": "pond-ow", "index": b} for b in ponderation.BLOCKS if b not in ("time", "co2")
        ]
        bo_vals = ["egalement_important"] * len(bo_ids)
        ow_vals = ["egalement_important"] * len(ow_ids)
        _fig, badges = ponderation.preview_callback("time", "co2", bo_vals, ow_vals, bo_ids, ow_ids)
        texte = _texts(badges)
        assert re.search(r"ξ\* = \d,\d{3}", texte), texte
        assert "CR < 0,10" in texte


# --- Aucune régression d'id (parcours e2e) --------------------------------------------------


class TestIdsParcours:
    def test_dashboard_ids_intacts(self, seeded):
        rendu = str(dashboard.layout())
        for attendu in (
            "dash-recalc-btn",
            "dash-tags-dd",
            "dash-kpi-cards",
            "dash-dag",
            "dash-promethee-warning",
            "dash-promethee-fig",
            "dash-correlation-fig",
            "dash-table",
            "dash-history-dd",
            "dash-history-fig",
            "dash-palette-dd",
            "dash-empty-banner",
        ):
            assert attendu in rendu, f"id manquant au layout dashboard : {attendu}"

    def test_hebdo_ids_intacts(self, seeded):
        rendu = str(weekly.layout())
        for attendu in (
            "hebdo-node-dd",
            "hebdo-week",
            "hebdo-progress",
            "hebdo-ahp-body",
            "hebdo-kpi-body",
            "hebdo-ms-body",
            "hebdo-ev-body",
            "hebdo-volet-check-ahp",
            "hebdo-volet-check-kpis",
            "hebdo-volet-check-jalons",
            "hebdo-volet-check-evenements",
            "hebdo-complete-btn",
            "hebdo-msg",
            "store-hebdo",
        ):
            assert attendu in rendu, f"id manquant au layout hebdo : {attendu}"

    def test_ponderation_ids_intacts(self, seeded):
        rendu = str(ponderation.layout())
        for attendu in (
            "pond-best-dd",
            "pond-worst-dd",
            "pond-judgments",
            "pond-preview-badges",
            "pond-weights-fig",
            "pond-save-btn",
            "pond-reset-btn",
            "pond-save-msg",
            "pond-reset-msg",
            "pond-current-weights",
        ):
            assert attendu in rendu, f"id manquant au layout pondération : {attendu}"

    def test_enregistrement_des_callbacks_sans_erreur(self, seeded):
        for page in (dashboard, weekly):
            app = dash.Dash(__name__, suppress_callback_exceptions=True)
            page.register_callbacks(app)  # aucun DuplicateCallback / output invalide
            assert len(app.callback_map) > 0
