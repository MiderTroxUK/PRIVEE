"""Page « Simulation » : scénarios catastrophe what-if et application réelle.

La simulation (:meth:`SupplyScoreService.simulate_shock`) ne persiste RIEN ;
seule la carte « Appliquer réellement » modifie le statut d'un nœud, après
confirmation explicite (``dcc.ConfirmDialogProvider``).
"""

from __future__ import annotations

from dash import Input, Output, State, ctx, dcc, html
from dash.exceptions import PreventUpdate

from supplyscore.domain.models import TaskStatus
from supplyscore.web_ui import get_service
from supplyscore.web_ui.components.figures import (
    empty_figure,
    shock_bar_figure,
    shock_dag_figure,
)
from supplyscore.web_ui.components.layout import (
    BUTTON_SECONDARY_STYLE,
    BUTTON_STYLE,
    COLORS,
    MSG_ALERT_STYLE,
    MSG_OK_STYLE,
    MSG_WARN_STYLE,
    PAGE_STYLE,
    STATUS_FR,
    card,
    labelled,
    node_options,
)

#: Style du bouton d'application réelle (action destructive).
BUTTON_DANGER_STYLE = {**BUTTON_STYLE, "backgroundColor": COLORS["alert"]}


def layout() -> html.Div:
    """Construit la page Simulation (état du service relu à chaque navigation)."""
    service = get_service()
    return html.Div(
        [
            html.H2("Simulation de choc", style={"margin": "6px 0 12px"}),
            card(
                "Scénario catastrophe (what-if, sans persistance)",
                [
                    labelled(
                        "Nœud à choquer",
                        dcc.Dropdown(
                            id="sim-node-dd",
                            options=node_options(service.repo.nodes()),
                            placeholder="Choisir un nœud…",
                        ),
                        width="380px",
                    ),
                    labelled(
                        "Ur_local simulé",
                        dcc.Slider(
                            id="sim-ur-slider",
                            min=0,
                            max=1,
                            step=0.05,
                            value=1.0,
                            marks={0: "0", 0.5: "0.5", 1: "1"},
                            tooltip={"placement": "bottom"},
                        ),
                        width="320px",
                    ),
                    html.Div(
                        [
                            html.Button(
                                "Défaillance totale (1.0)",
                                id="sim-preset-fail",
                                style={**BUTTON_SECONDARY_STYLE, "marginRight": "10px"},
                            ),
                            html.Button(
                                "Retour à la normale (0.0)",
                                id="sim-preset-ok",
                                style=BUTTON_SECONDARY_STYLE,
                            ),
                        ],
                        style={"marginBottom": "12px"},
                    ),
                    html.Div(html.Button("Simuler", id="sim-run-btn", style=BUTTON_STYLE)),
                    html.Div(id="sim-summary"),
                ],
                subtitle="Aucune donnée n'est modifiée : la simulation est purement indicative.",
            ),
            card(
                "Propagation du choc",
                [dcc.Graph(id="sim-dag-fig", figure=empty_figure("Lancez une simulation."))],
            ),
            card(
                "Impact par nœud",
                [dcc.Graph(id="sim-bar-fig", figure=empty_figure("Lancez une simulation."))],
            ),
            card(
                "Appliquer réellement",
                [
                    labelled(
                        "Statut à appliquer",
                        dcc.Dropdown(
                            id="sim-status-dd",
                            options=[
                                {
                                    "label": STATUS_FR[TaskStatus.DONE],
                                    "value": str(TaskStatus.DONE),
                                },
                                {
                                    "label": STATUS_FR[TaskStatus.ABANDONED],
                                    "value": str(TaskStatus.ABANDONED),
                                },
                            ],
                            placeholder="Choisir un statut…",
                        ),
                        width="220px",
                    ),
                    html.Div(
                        dcc.ConfirmDialogProvider(
                            children=html.Button(
                                "Appliquer le statut (persistant)",
                                style=BUTTON_DANGER_STYLE,
                            ),
                            id="sim-apply-confirm",
                            message=(
                                "Confirmer l'application RÉELLE du statut au nœud "
                                "sélectionné ? Le choc sera propagé et persisté."
                            ),
                        ),
                    ),
                    html.Div(id="sim-apply-msg"),
                ],
                subtitle=(
                    "Action persistante sur le nœud sélectionné ci-dessus — "
                    "contrairement à la simulation, le graphe est réellement modifié."
                ),
            ),
        ],
        style=PAGE_STYLE,
    )


# --- Callbacks (fonctions nommées, testables sans serveur) -----------------------


def node_options_callback(project_data):
    """Restreint le dropdown aux nœuds du projet actif (tout le graphe sinon)."""
    service = get_service()
    pid = (project_data or {}).get("project_id")
    nodes = service.repo.nodes()
    if pid:
        nodes = [n for n in nodes if n.project_id == pid]
    return node_options(nodes)


def preset_callback(n_fail, n_ok):
    """Présets du slider : défaillance totale (1.0) ou retour à la normale (0.0)."""
    triggered = ctx.triggered_id
    if triggered == "sim-preset-fail":
        return 1.0
    if triggered == "sim-preset-ok":
        return 0.0
    raise PreventUpdate


def simulate_callback(n_clicks, node_id, ur_value, project_data):
    """Lance le what-if : figures DAG + barres et texte récapitulatif."""
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    if not node_id:
        message = html.Span("Sélectionnez d'abord un nœud à choquer.", style=MSG_ALERT_STYLE)
        return (
            empty_figure("Sélectionnez un nœud."),
            empty_figure("Sélectionnez un nœud."),
            message,
        )

    value = float(ur_value if ur_value is not None else 1.0)
    deltas = service.simulate_shock(node_id, value)

    pid = (project_data or {}).get("project_id")
    nodes = service.repo.nodes()
    if pid:
        nodes = [n for n in nodes if n.project_id == pid]
    ids = {n.id for n in nodes}
    arcs = [a for a in service.repo.arcs() if a.source_id in ids and a.target_id in ids]
    names = {n.id: n.name for n in service.repo.nodes()}

    shocked = service.repo.get_node(node_id)
    shocked_name = shocked.name if shocked is not None else node_id
    impacted = {nid: d for nid, d in deltas.items() if nid != node_id and abs(d) > 1e-9}
    if impacted:
        worst = max(impacted, key=lambda nid: abs(impacted[nid]))
        text = (
            f"Le choc sur « {shocked_name} » (Ur_local = {value:.2f}) impacte "
            f"{len(impacted)} nœud(s) aval, ΔUr max = {impacted[worst]:+.3f} "
            f"sur « {names.get(worst, worst)} ». Simulation sans persistance."
        )
    else:
        text = f"Le choc sur « {shocked_name} » (Ur_local = {value:.2f}) n'impacte aucun nœud aval."
    return (
        shock_dag_figure(nodes, arcs, deltas),
        shock_bar_figure(deltas, names),
        html.Span(text, style=MSG_WARN_STYLE),
    )


def apply_status_callback(submit_n_clicks, node_id, status_value):
    """Applique RÉELLEMENT le statut choisi (persistant) après confirmation."""
    if not submit_n_clicks:
        raise PreventUpdate
    service = get_service()
    if not node_id or not status_value:
        return html.Span("Choisissez un nœud (carte du haut) ET un statut.", style=MSG_ALERT_STYLE)
    status = TaskStatus(status_value)
    service.set_status(node_id, status)
    node = service.repo.get_node(node_id)
    name = node.name if node is not None else node_id
    return html.Span(
        f"Statut « {STATUS_FR[status]} » appliqué à « {name} » : "
        "propagation recalculée et persistée.",
        style=MSG_OK_STYLE,
    )


def register_callbacks(app) -> None:
    """Enregistre les callbacks de la page Simulation sur l'application Dash."""
    app.callback(
        Output("sim-node-dd", "options"),
        Input("store-project", "data"),
    )(node_options_callback)

    app.callback(
        Output("sim-ur-slider", "value"),
        Input("sim-preset-fail", "n_clicks"),
        Input("sim-preset-ok", "n_clicks"),
        prevent_initial_call=True,
    )(preset_callback)

    app.callback(
        Output("sim-dag-fig", "figure"),
        Output("sim-bar-fig", "figure"),
        Output("sim-summary", "children"),
        Input("sim-run-btn", "n_clicks"),
        State("sim-node-dd", "value"),
        State("sim-ur-slider", "value"),
        State("store-project", "data"),
        prevent_initial_call=True,
    )(simulate_callback)

    app.callback(
        Output("sim-apply-msg", "children"),
        Input("sim-apply-confirm", "submit_n_clicks"),
        State("sim-node-dd", "value"),
        State("sim-status-dd", "value"),
        prevent_initial_call=True,
    )(apply_status_callback)
