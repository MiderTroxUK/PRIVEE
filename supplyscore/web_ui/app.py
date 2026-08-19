"""Factory de l'application web Dash de SupplyScore.

Aucun serveur n'est lance a l'import : :func:`create_app` construit
l'application (pattern factory), enregistre les callbacks des 4 pages et
retourne l'instance ``dash.Dash``. Le lancement (``app.run``) est du ressort
de l'appelant (cf. ``run_app.py`` a la racine du depot).
"""

from __future__ import annotations

import dash
from dash import Input, Output, dcc, html

from supplyscore.services import SupplyScoreService
from supplyscore.web_ui import set_service
from supplyscore.web_ui.components import operator
from supplyscore.web_ui.components.layout import COLORS, FONT_FAMILY, PAGE_STYLE, navbar
from supplyscore.web_ui.errors import proteger_app
from supplyscore.web_ui.pages import (
    admin_data,
    dashboard,
    editor,
    explain,
    graph_editor,
    node_detail,
    onboarding,
    ponderation,
    projects,
    questionnaire,
    report,
    simulation,
    weekly,
)


def route_callback(pathname: str | None):
    """Routage : retourne le layout de la page correspondant a l'URL.

    Routes statiques + route parametree ``/node/<id>`` (fiche noeud 360o).

    Args:
        pathname: chemin courant de ``dcc.Location`` (ex. "/dashboard").

    Returns:
        L'arbre de composants de la page demandee, ou un message 404.
    """
    path = pathname or "/"
    if path.startswith("/node/"):
        rest = path[len("/node/") :].strip("/")
        if rest.endswith("/explication"):
            return explain.layout(rest[: -len("/explication")].strip("/"))
        return node_detail.layout(rest)
    routes = {
        "/": projects.layout,
        "/questionnaire": questionnaire.layout,
        "/dashboard": dashboard.layout,
        "/simulation": simulation.layout,
        "/onboarding": onboarding.layout,
        "/hebdo": weekly.layout,
        "/edition": editor.layout,
        "/graphe": graph_editor.layout,
        "/admin": admin_data.layout,
        "/rapport": report.layout,
        "/ponderation": ponderation.layout,
    }
    builder = routes.get(path)
    if builder is None:
        return html.Div(
            html.P("Page inconnue (404) — utilisez la barre de navigation."),
            style=PAGE_STYLE,
        )
    return builder()


def create_app(
    db_dir: str = "data_store",
    service: SupplyScoreService | None = None,
) -> dash.Dash:
    """Construit l'application Dash complete (sans la lancer).

    Args:
        db_dir: repertoire des bases SQLite (utilise si ``service`` est None).
        service: instance de :class:`SupplyScoreService` a reutiliser
            (tests, scripts) ; instanciee depuis ``db_dir`` sinon.

    Returns:
        L'application ``dash.Dash`` prete a etre lancee via ``app.run``.
    """
    if service is None:
        service = SupplyScoreService(db_dir)
    service.load_graph_from_registry()
    set_service(service)

    app = dash.Dash(
        __name__,
        suppress_callback_exceptions=True,
        title="SupplyScore",
    )
    # Garde-fou E16.1 : AVANT tout enregistrement (routeur compris), chaque callback est automatiquement protege - aucune exception n'atteint l'utilisateur sans message francais (cf. supplyscore.web_ui.errors).
    proteger_app(app)
    app.layout = html.Div(
        [
            navbar(right=operator.operator_selector()),
            dcc.Location(id="url"),
            dcc.Store(id="store-project", storage_type="session"),
            dcc.Store(id="store-operator", storage_type="session"),
            html.Div(id="page-content"),
        ],
        style={
            "backgroundColor": COLORS["background"],
            "minHeight": "100vh",
            "fontFamily": FONT_FAMILY,
        },
    )

    app.callback(Output("page-content", "children"), Input("url", "pathname"))(route_callback)
    operator.register_callbacks(app)
    for page in (
        projects,
        questionnaire,
        dashboard,
        simulation,
        onboarding,
        node_detail,
        weekly,
        explain,
        editor,
        graph_editor,
        admin_data,
        report,
        ponderation,
    ):
        page.register_callbacks(app)
    return app
