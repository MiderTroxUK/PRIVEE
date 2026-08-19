"""Tests des garde-fous d'erreur de l'UI web (Lot 16.1).

Aucun serveur n'est lance : ``proteger_app`` remplace ``app.callback`` par
une version qui enveloppe chaque fonction au point d'enregistrement, et le
decorateur retourne la fonction ENVELOPPEE - appelable directement ici.
Elle est aussi retrouvable via ``app.callback_map`` : Dash y range
``add_context`` construit avec ``functools.wraps(fn)``, donc
``entry["callback"].__wrapped__`` est la fonction enregistree (protegee).
"""

import logging

import dash
import pytest
from dash import Input, Output
from dash.exceptions import PreventUpdate

from supplyscore.services import SupplyScoreService
from supplyscore.web_ui import set_service
from supplyscore.web_ui.app import create_app
from supplyscore.web_ui.errors import (
    est_protege,
    nombre_callbacks_proteges,
    protege_callback,
    proteger_app,
)

LOGGER_NAME = "supplyscore.web_ui"


@pytest.fixture
def app_protegee():
    """Application Dash factice dont les enregistrements sont proteges."""
    app = dash.Dash("test_webui_errors", suppress_callback_exceptions=True)
    proteger_app(app)
    return app


@pytest.fixture
def service(tmp_path):
    """Service seede avec une petite demo, partage par les callbacks."""
    svc = SupplyScoreService(db_dir=tmp_path / "store")
    svc.seed_demo(n_ranks=2, seed=1)
    set_service(svc)
    yield svc
    set_service(None)


# Callback 1 Output children : message francais + log


def test_un_output_children_retourne_message_francais(app_protegee, caplog):
    @app_protegee.callback(Output("zone", "children"), Input("btn", "n_clicks"))
    def boum(n_clicks):
        raise RuntimeError("explosion volontaire")

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        resultat = boum(1)

    # Composant SEUL (pas un tuple de 1) pour un Output unique non-liste.
    assert not isinstance(resultat, tuple)
    texte = str(resultat)
    assert "erreur" in texte
    assert "supplyscore.log" in texte
    assert "RuntimeError" in texte
    assert "explosion volontaire" not in texte  # jamais le message brut a l'ecran

    erreurs = [r for r in caplog.records if r.name == LOGGER_NAME]
    assert len(erreurs) == 1
    assert erreurs[0].exc_info is not None  # trace complete journalisee
    assert "boum" in erreurs[0].getMessage()


def test_fonction_enregistree_retrouvable_via_callback_map(app_protegee):
    @app_protegee.callback(Output("zone", "children"), Input("btn", "n_clicks"))
    def boum(n_clicks):
        raise RuntimeError("kaboom")

    entree = app_protegee.callback_map["zone.children"]["callback"]
    assert entree.__wrapped__ is boum
    assert est_protege(entree.__wrapped__)
    assert "supplyscore.log" in str(entree.__wrapped__(1))


# Callback 3 Outputs : (message, no_update, no_update)


def test_trois_outputs_message_sur_le_premier_children(app_protegee, caplog):
    @app_protegee.callback(
        Output("msg", "children"),
        Output("fig", "figure"),
        Output("store", "data"),
        Input("btn", "n_clicks"),
    )
    def boum3(n_clicks):
        raise ValueError("trois sorties")

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        resultat = boum3(1)

    assert isinstance(resultat, tuple)
    assert len(resultat) == 3
    assert "supplyscore.log" in str(resultat[0])
    # Heuristique : une figure/un store qui recevrait un html.Div casserait le rendu cote client - ils recoivent no_update.
    assert resultat[1] is dash.no_update
    assert resultat[2] is dash.no_update
    assert any(r.name == LOGGER_NAME for r in caplog.records)


def test_children_en_seconde_position_recoit_le_message(app_protegee):
    @app_protegee.callback(
        Output("fig", "figure"),
        Output("msg", "children"),
        Output("autre-msg", "children"),
        Input("btn", "n_clicks"),
    )
    def boum_milieu(n_clicks):
        raise KeyError("children au milieu")

    resultat = boum_milieu(1)
    assert resultat[0] is dash.no_update
    assert "supplyscore.log" in str(resultat[1])
    assert resultat[2] is dash.no_update  # SEUL le premier children est servi


# PreventUpdate : flux normal de Dash, traverse sans etre attrape


def test_prevent_update_traverse_sans_log(app_protegee, caplog):
    @app_protegee.callback(Output("zone", "children"), Input("btn", "n_clicks"))
    def silencieux(n_clicks):
        raise PreventUpdate

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME), pytest.raises(PreventUpdate):
        silencieux(1)

    assert not [r for r in caplog.records if r.name == LOGGER_NAME]


# Callbacks sans Output children : tous no_update, le log est la seule trace


def test_sans_children_tous_no_update_et_log(app_protegee, caplog):
    @app_protegee.callback(
        Output("fig", "figure"),
        Output("store", "data"),
        Input("btn", "n_clicks"),
    )
    def boum_muet(n_clicks):
        raise RuntimeError("aucune zone de message")

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        resultat = boum_muet(1)

    assert resultat == (dash.no_update, dash.no_update)
    erreurs = [r for r in caplog.records if r.name == LOGGER_NAME]
    assert len(erreurs) == 1
    assert erreurs[0].exc_info is not None


def test_output_unique_non_children_no_update_scalaire(app_protegee, caplog):
    @app_protegee.callback(Output("fig", "figure"), Input("btn", "n_clicks"))
    def boum_figure(n_clicks):
        raise RuntimeError("figure seule")

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        resultat = boum_figure(1)

    assert resultat is dash.no_update  # scalaire : Output unique non-liste
    assert any(r.name == LOGGER_NAME for r in caplog.records)


def test_output_unique_en_liste_retourne_tuple_de_un(app_protegee):
    # Un Output unique passe DANS une liste : Dash attend une sequence de 1.
    @app_protegee.callback([Output("zone", "children")], Input("btn", "n_clicks"))
    def boum_liste(n_clicks):
        raise RuntimeError("liste d'un seul Output")

    resultat = boum_liste(1)
    assert isinstance(resultat, tuple)
    assert len(resultat) == 1
    assert "supplyscore.log" in str(resultat[0])


# Decorateur seul (sans point d'enregistrement) et flux nominal


def test_protege_callback_seul_suppose_children_unique(caplog):
    def boum_direct():
        raise RuntimeError("sans enregistrement")

    protegee = protege_callback(boum_direct)
    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        resultat = protegee()

    assert "supplyscore.log" in str(resultat)
    assert est_protege(protegee)
    assert not est_protege(boum_direct)


def test_flux_nominal_intact(app_protegee):
    @app_protegee.callback(Output("zone", "children"), Input("btn", "n_clicks"))
    def nominal(n_clicks):
        return f"ok-{n_clicks}"

    assert nominal(3) == "ok-3"


def test_proteger_app_idempotente_et_compteur(app_protegee):
    assert proteger_app(app_protegee) == 0  # second appel : aucun double emballage

    @app_protegee.callback(Output("zone", "children"), Input("btn", "n_clicks"))
    def unique(n_clicks):
        return "ok"

    assert nombre_callbacks_proteges(app_protegee) == 1
    assert unique("ok") == "ok"  # pas d'enveloppe en double


# Application reelle : create_app protege TOUS les callbacks


def test_create_app_protege_tous_les_callbacks(service):
    app = create_app(service=service)
    # Egalite stricte : chaque appel app.callback(...) cree UNE entree de callback_map (les sorties allow_duplicate recoivent des cles uniques) et proteger_app est appelee avant le tout premier enregistrement.
    assert nombre_callbacks_proteges(app) == len(app.callback_map)
    assert nombre_callbacks_proteges(app) > 0
    for entree in app.callback_map.values():
        assert est_protege(entree["callback"].__wrapped__)


def test_callback_reel_avec_service_casse_retourne_message(service, caplog):
    app = create_app(service=service)
    enveloppes = {
        e["callback"].__wrapped__.__name__: e["callback"].__wrapped__
        for e in app.callback_map.values()
    }
    update_dashboard = enveloppes["update_dashboard_callback"]

    set_service(None)  # service CASSE : get_service() leve RuntimeError
    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        resultat = update_dashboard(None, None, None)

    # 4 Outputs (children, figure, data, options) : message sur le premier.
    assert isinstance(resultat, tuple)
    assert len(resultat) == 4
    texte = str(resultat[0])
    assert "erreur" in texte
    assert "supplyscore.log" in texte
    assert all(v is dash.no_update for v in resultat[1:])
    assert any(r.name == LOGGER_NAME for r in caplog.records)
