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
from supplyscore.web_ui.components.layout import COLORS, FONT_FAMILY, PAGE_STYLE, navbar
from supplyscore.web_ui.pages import dashboard, projects, questionnaire, simulation


def route_callback(pathname: str | None):
    """Routage : retourne le layout de la page correspondant à l'URL.

    Args:
        pathname: chemin courant de ``dcc.Location`` (ex. "/dashboard").

    Returns:
        L'arbre de composants de la page demandée, ou un message 404.
    """
    routes = {
        "/": projects.layout,
        "/questionnaire": questionnaire.layout,
        "/dashboard": dashboard.layout,
        "/simulation": simulation.layout,
    }
    builder = routes.get(pathname or "/")
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
            navbar(),
            dcc.Location(id="url"),
            dcc.Store(id="store-project", storage_type="session"),
            html.Div(id="page-content"),
        ],
        style={
            "backgroundColor": COLORS["background"],
            "minHeight": "100vh",
            "fontFamily": FONT_FAMILY,
        },
    )

    app.callback(Output("page-content", "children"), Input("url", "pathname"))(route_callback)
    for page in (projects, questionnaire, dashboard, simulation):
        page.register_callbacks(app)
    return app
