"""Parcours navigateur de bout en bout (Lot 16.7) - 8 scenarios utilisateur.

Chaque test demarre l'application complete (``app_seedee`` : demo seedee,
bases SQLite jetables) dans un serveur de thread dash.testing, pilotee par
Chrome headless via la fixture ``dash_duo``. Toutes les attentes passent par
les ``wait_for_*`` de dash_duo (jamais de sleep brut) et les assertions
portent sur les TEXTES FRANCAIS reellement affiches.

Suite SKIPPEE par defaut : poser ``SUPPLYSCORE_UI=1`` (ou lancer
``scripts/ci.ps1 -Ui``) - cf. ``tests/ui/conftest.py``.
"""

from __future__ import annotations

import pytest
from dash.testing.wait import until

pytestmark = pytest.mark.ui

#: Delai max (s) des attentes : seed_demo + evaluate_all peuvent prendre quelques secondes.
TIMEOUT = 30


def _saisir(dash_duo, selector: str, texte: str) -> None:
    """Vide un input (Ctrl+A puis Suppr) et tape ``texte`` au clavier."""
    element = dash_duo.find_element(selector)
    dash_duo.clear_input(element)
    element.send_keys(texte)


# (1) Demarrage


def test_01_demarrage_navbar_et_titre(app_seedee, dash_duo):
    """Au demarrage : titre " SupplyScore ", navbar avec " Projets ", page Projets rendue."""
    dash_duo.start_server(app_seedee)
    dash_duo.wait_for_text_to_equal("a[href='/']", "Projets", timeout=TIMEOUT)
    until(lambda: "SupplyScore" in dash_duo.driver.title, timeout=TIMEOUT)
    assert "SupplyScore" in dash_duo.find_element("body").text
    dash_duo.wait_for_contains_text("#page-content h2", "Projets", timeout=TIMEOUT)


# (2) Generation d'une demo


def test_02_generation_demo_remplit_le_tableau(app_seedee, dash_duo):
    """" Generer la demo " (nouveau seed) : message " Demo ... generee " et tableau rempli."""
    dash_duo.start_server(app_seedee)
    dash_duo.wait_for_element("#demo-btn", timeout=TIMEOUT)
    # La fixture a deja seede (n_ranks=2, seed=1) : on genere avec un NOUVEAU seed.
    _saisir(dash_duo, "#demo-seed-input", "7")
    _saisir(dash_duo, "#demo-ranks-input", "2")
    dash_duo.find_element("#demo-btn").click()
    dash_duo.wait_for_contains_text("#demo-msg", "Démo", timeout=TIMEOUT)
    dash_duo.wait_for_contains_text("#demo-msg", "générée et sélectionnée", timeout=TIMEOUT)
    # Le projet demo devient actif : le tableau des noeuds se remplit.
    dash_duo.wait_for_element("#proj-table .dash-cell", timeout=TIMEOUT)
    dash_duo.wait_for_contains_text("#active-project-msg", "Projet actif", timeout=TIMEOUT)


# (3) Dashboard


def test_03_dashboard_tableau_et_dag(app_seedee, dash_duo):
    """Sur /dashboard : tableau detaille non vide et DAG de la chaine present."""
    dash_duo.start_server(app_seedee)
    dash_duo.wait_for_page(f"{dash_duo.server_url}/dashboard")
    dash_duo.wait_for_contains_text("#page-content h2", "Dashboard", timeout=TIMEOUT)
    # Sans projet actif, tout le graphe (la demo de la fixture) est liste.
    dash_duo.wait_for_element("#dash-table .dash-cell", timeout=TIMEOUT)
    dash_duo.wait_for_element("#dash-dag .js-plotly-plot", timeout=TIMEOUT)
    assert "Chaîne logistique" in dash_duo.find_element("#page-content").text


# (4) Questionnaire : enregistrement nominal


def test_04_questionnaire_enregistrement(app_seedee, dash_duo):
    """Noeud + operateur + sliders par defaut (CR = 0) : " Evaluation enregistree "."""
    dash_duo.start_server(app_seedee)
    dash_duo.wait_for_page(f"{dash_duo.server_url}/questionnaire")
    dash_duo.wait_for_element("#q-node-dd", timeout=TIMEOUT)
    dash_duo.select_dcc_dropdown("#q-node-dd", index=0)
    _saisir(dash_duo, "#q-operator", "jdupont")
    dash_duo.find_element("#q-save-btn").click()
    dash_duo.wait_for_contains_text("#q-save-msg", "Évaluation enregistrée", timeout=TIMEOUT)
    assert "semaine" in dash_duo.find_element("#q-save-msg").text


# (5) Questionnaire : refus sans operateur


def test_05_questionnaire_refus_sans_operateur(app_seedee, dash_duo):
    """Sans identifiant operateur, l'enregistrement est refuse (message d'erreur)."""
    dash_duo.start_server(app_seedee)
    dash_duo.wait_for_page(f"{dash_duo.server_url}/questionnaire")
    dash_duo.wait_for_element("#q-node-dd", timeout=TIMEOUT)
    dash_duo.select_dcc_dropdown("#q-node-dd", index=0)
    dash_duo.find_element("#q-save-btn").click()
    dash_duo.wait_for_contains_text(
        "#q-save-msg", "L'identifiant opérateur est requis.", timeout=TIMEOUT
    )


# (6) Revue hebdomadaire : les quatre volets


def test_06_hebdo_quatre_volets(app_seedee, dash_duo):
    """Sur /hebdo, apres choix d'un noeud : les quatre volets du rituel sont montes."""
    dash_duo.start_server(app_seedee)
    dash_duo.wait_for_page(f"{dash_duo.server_url}/hebdo")
    dash_duo.wait_for_contains_text("#page-content h2", "Revue hebdomadaire", timeout=TIMEOUT)
    dash_duo.select_dcc_dropdown("#hebdo-node-dd", index=0)
    dash_duo.wait_for_contains_text("#hebdo-week", "Semaine", timeout=TIMEOUT)
    # Titres des quatre volets (layout) :
    page = dash_duo.find_element("#page-content").text
    for titre in (
        "Volet 1 — Évaluation AHP",
        "Volet 2 — KPIs de la semaine",
        "Volet 3 — Jalons",
        "Volet 4 — Événements & décision",
    ):
        assert titre in page, f"volet absent de la page : {titre}"
    # Corps des quatre volets montes pour le noeud choisi (textes stables) :
    dash_duo.wait_for_contains_text("#hebdo-ahp-body", "Enregistrer l'évaluation", timeout=TIMEOUT)
    dash_duo.wait_for_contains_text("#hebdo-kpi-body", "Rien n'a changé", timeout=TIMEOUT)
    dash_duo.wait_for_contains_text("#hebdo-ms-body", "Confirmer les jalons", timeout=TIMEOUT)
    dash_duo.wait_for_contains_text("#hebdo-ev-body", "Déclarer un événement", timeout=TIMEOUT)


# (7) Simulation : choc unitaire


def test_07_simulation_choc_unitaire(app_seedee, dash_duo):
    """Choc unitaire : recapitulatif " Le choc sur ... " et DAG avec des donnees."""
    dash_duo.start_server(app_seedee)
    dash_duo.wait_for_page(f"{dash_duo.server_url}/simulation")
    dash_duo.wait_for_contains_text("#page-content h2", "Simulation de choc", timeout=TIMEOUT)
    dash_duo.select_dcc_dropdown("#sim-node-dd", index=0)
    dash_duo.find_element("#sim-run-btn").click()
    dash_duo.wait_for_contains_text("#sim-summary", "Le choc sur", timeout=TIMEOUT)
    # La figure vide initiale n'a aucune trace : leur apparition prouve la mise a jour.
    dash_duo.wait_for_element("#sim-dag-fig .js-plotly-plot .scatterlayer .trace", timeout=TIMEOUT)
    assert "Simulation" in dash_duo.find_element("#page-content").text


# (8) Route inconnue


def test_08_route_inconnue_affiche_404(app_seedee, dash_duo):
    """Une URL inconnue (/xyz) affiche la page 404 francaise."""
    dash_duo.start_server(app_seedee)
    dash_duo.wait_for_page(f"{dash_duo.server_url}/xyz")
    dash_duo.wait_for_contains_text("#page-content", "404", timeout=TIMEOUT)
    assert "Page inconnue" in dash_duo.find_element("#page-content").text
