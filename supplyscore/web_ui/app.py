"""Factory de l'application web Dash de SupplyScore.

Aucun serveur n'est lancé à l'import : :func:`create_app` construit
l'application (pattern factory), enregistre les callbacks des 4 pages et
retourne l'instance ``dash.Dash``. Le lancement (``app.run``) est du ressort
de l'appelant (cf. ``run_app.py`` à la racine du dépôt).
"""

from __future__ import annotations

import dash
from dash import Input, Output, dcc, html

from supplyscore.services import SupplyScoreService
from supplyscore.web_ui import set_service
from supplyscore.web_ui.components import operator
from supplyscore.web_ui.components.layout import COLORS, FONT_FAMILY, PAGE_STYLE, navbar
from supplyscore.web_ui.pages import (
    dashboard,
    node_detail,
    onboarding,
    projects,
    questionnaire,
    simulation,
    weekly,
)


def route_callback(pathname: str | None):
    """Routage : retourne le layout de la page correspondant à l'URL.

    Routes statiques + route paramétrée ``/node/<id>`` (fiche nœud 360°).

    Args:
        pathname: chemin courant de ``dcc.Location`` (ex. "/dashboard").

    Returns:
        L'arbre de composants de la page demandée, ou un message 404.
    """
    path = pathname or "/"
    if path.startswith("/node/"):
        node_id = path[len("/node/") :].strip("/")
        return node_detail.layout(node_id)
    routes = {
        "/": projects.layout,
        "/questionnaire": questionnaire.layout,
        "/dashboard": dashboard.layout,
        "/simulation": simulation.layout,
        "/onboarding": onboarding.layout,
        "/hebdo": weekly.layout,
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
    """Construit l'application Dash complète (sans la lancer).

    Args:
        db_dir: répertoire des bases SQLite (utilisé si ``service`` est None).
        service: instance de :class:`SupplyScoreService` à réutiliser
            (tests, scripts) ; instanciée depuis ``db_dir`` sinon.

    Returns:
        L'application ``dash.Dash`` prête à être lancée via ``app.run``.
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
    ):
        page.register_callbacks(app)
    return app
