"""Page « /rapport » : génération du rapport de session HTML (E11, Lot 11.2).

Une carte unique « Générer le rapport de session » : paramètre d'horizon de
calibration (1 à 12 semaines, 4 par défaut), bouton de génération, message de
résultat et ``dcc.Download`` qui déclenche le téléchargement du fichier HTML
produit par :class:`~supplyscore.services.report.SessionReport`. La page
nécessite un projet actif (``store-project``) — sans projet, un message
d'erreur en français est affiché.

Le routage « /rapport » et le lien de navigation sont branchés par la tâche
d'intégration E11.I dans ``app.py`` (la page expose ``layout()`` et
:func:`register_callbacks`).
"""

from __future__ import annotations

from dash import Input, Output, State, dcc, html, no_update
from dash.exceptions import PreventUpdate

from supplyscore.services.report import SessionReport
from supplyscore.web_ui import get_service
from supplyscore.web_ui.components.layout import (
    BUTTON_STYLE,
    INPUT_STYLE,
    MSG_ALERT_STYLE,
    MSG_OK_STYLE,
    PAGE_STYLE,
    card,
    labelled,
)

#: Bornes et défaut de l'horizon de calibration, en semaines.
HORIZON_MIN = 1
HORIZON_MAX = 12
HORIZON_DEFAUT = 4


# --- Layout -----------------------------------------------------------------------------


def layout() -> html.Div:
    """Construit la page Rapport (carte unique de génération)."""
    return html.Div(
        [
            html.H2("Rapport de session", style={"margin": "6px 0 10px"}),
            card(
                "Générer le rapport de session",
                [
                    labelled(
                        "Horizon de calibration (semaines)",
                        dcc.Input(
                            id="report-horizon",
                            type="number",
                            min=HORIZON_MIN,
                            max=HORIZON_MAX,
                            step=1,
                            value=HORIZON_DEFAUT,
                            style=INPUT_STYLE,
                        ),
                    ),
                    html.Div(
                        html.Button("Générer le rapport", id="report-btn", style=BUTTON_STYLE)
                    ),
                    dcc.Download(id="report-download"),
                    html.Div(id="report-msg"),
                ],
                subtitle=(
                    "Rapport HTML autonome et imprimable : synthèse des scores, évolutions "
                    "Ud/Ur/A, chronologie des événements et décisions, calibration "
                    "prédiction/réalité et graphe final. Nécessite un projet actif "
                    "(page Projets) ; les figures se chargent via internet à l'ouverture."
                ),
            ),
        ],
        style=PAGE_STYLE,
    )


# --- Callbacks (fonctions nommées, testables sans serveur) -------------------------------


def generate_report_callback(n_clicks, project_data, horizon):
    """Génère le rapport du projet actif puis déclenche son téléchargement.

    Sans projet actif : message d'erreur en français, pas de téléchargement.
    L'horizon est validé côté serveur (coercition entière puis bornage 1..12 —
    la saisie clavier peut contourner ``min``/``max`` du ``dcc.Input``).
    """
    if not n_clicks:
        raise PreventUpdate
    pid = (project_data or {}).get("project_id")
    if not pid:
        return (
            html.Span("Sélectionnez d'abord un projet (page Projets).", style=MSG_ALERT_STYLE),
            no_update,
        )
    try:
        horizon_weeks = int(horizon)
    except (TypeError, ValueError):
        horizon_weeks = HORIZON_DEFAUT
    horizon_weeks = min(max(horizon_weeks, HORIZON_MIN), HORIZON_MAX)
    service = get_service()
    try:
        path = SessionReport(service).build(pid, horizon_weeks=horizon_weeks)
    except ValueError as exc:
        return html.Span(str(exc), style=MSG_ALERT_STYLE), no_update
    msg = html.Span(f"Rapport généré : {path.name}", style=MSG_OK_STYLE)
    return msg, dcc.send_file(str(path))


def register_callbacks(app) -> None:
    """Enregistre les callbacks de la page Rapport sur l'application Dash."""
    app.callback(
        Output("report-msg", "children"),
        Output("report-download", "data"),
        Input("report-btn", "n_clicks"),
        State("store-project", "data"),
        State("report-horizon", "value"),
        prevent_initial_call=True,
    )(generate_report_callback)
