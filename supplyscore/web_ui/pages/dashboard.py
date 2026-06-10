"""Page « Dashboard » : indicateurs globaux, DAG, tableau détaillé, historique.

Callbacks en fonctions nommées au niveau module, enregistrées dans
:func:`register_callbacks` — testables sans serveur.
"""

from __future__ import annotations

from dash import Input, Output, dash_table, dcc, html

from supplyscore.web_ui import get_service
from supplyscore.web_ui.components.figures import (
    dashboard_dag_figure,
    empty_figure,
    urgency_history_figure,
)
from supplyscore.web_ui.components.layout import (
    BUTTON_STYLE,
    CARD_STYLE,
    COLORS,
    FONT_FAMILY,
    PAGE_STYLE,
    STATUS_FR,
    card,
    labelled,
    node_options,
)

_VALUE_COLUMNS = ["Ud_loc", "Ur_loc", "Ud", "Ur", "A", "F", "H"]

_TABLE_COLUMNS = (
    [{"name": "Nom", "id": "Nom"},
     {"name": "Rang", "id": "Rang", "type": "numeric"},
     {"name": "Statut", "id": "Statut"}]
    + [{"name": c, "id": c, "type": "numeric"} for c in _VALUE_COLUMNS]
)

_TABLE_CONDITIONAL = [
    {"if": {"filter_query": "{A} < 40"}, "backgroundColor": "#fdecea"},
    {"if": {"filter_query": "{H} > 0.3", "column_id": "H"},
     "color": COLORS["alert"], "fontWeight": "700"},
]

_TABLE_STYLE_CELL = {
    "fontFamily": FONT_FAMILY,
    "fontSize": "13px",
    "padding": "6px 10px",
    "textAlign": "left",
}

_TABLE_STYLE_HEADER = {
    "fontWeight": "700",
    "backgroundColor": "#eef2f5",
    "color": COLORS["text"],
}


def _r3(value: float | None) -> float | None:
    """Arrondit à 3 décimales en tolérant None."""
    return None if value is None else round(value, 3)


def _stat_card(value: str, label_text: str) -> html.Div:
    """Petite carte KPI (valeur en gros, libellé dessous)."""
    return html.Div(
        [
            html.Div(value, style={"fontSize": "20px", "fontWeight": "700",
                                   "color": COLORS["primary"]}),
            html.Div(label_text, style={"fontSize": "12px",
                                        "color": COLORS["muted"]}),
        ],
        style={**CARD_STYLE, "flex": "1 1 150px", "marginBottom": "0",
               "textAlign": "center"},
    )


def _kpi_summary(nodes) -> list[html.Div]:
    """Cartes KPI du haut de page : effectif, A moyen/pire, risques H et F."""
    a_known = [(n.urgency.adequation, n.name) for n in nodes
               if n.urgency.adequation is not None]
    if a_known:
        mean_a = f"{sum(v for v, _ in a_known) / len(a_known):.1f}"
        worst_val, worst_name = min(a_known, key=lambda pair: pair[0])
        worst = f"{worst_val:.1f} ({worst_name})"
    else:
        mean_a, worst = "—", "—"
    hidden = sum(1 for n in nodes if (n.urgency.hidden_risk or 0.0) > 0.1)
    false_u = sum(1 for n in nodes if (n.urgency.false_urgency or 0.0) > 0.1)
    return [
        _stat_card(str(len(nodes)), "Nœuds"),
        _stat_card(mean_a, "A moyen du projet"),
        _stat_card(worst, "Pire adéquation A"),
        _stat_card(str(hidden), "Risques cachés (H > 0.1)"),
        _stat_card(str(false_u), "Fausses urgences (F > 0.1)"),
    ]


def _scope_nodes(project_data):
    """Nœuds du projet actif, ou tout le graphe si aucun projet sélectionné."""
    service = get_service()
    pid = (project_data or {}).get("project_id")
    nodes = service.repo.nodes()
    if pid:
        nodes = [n for n in nodes if n.project_id == pid]
    return nodes


def layout() -> html.Div:
    """Construit la page Dashboard (état du service relu à chaque navigation)."""
    return html.Div(
        [
            html.H2("Dashboard", style={"margin": "6px 0 12px"}),
            html.Div(
                html.Button("Recalculer maintenant", id="dash-recalc-btn",
                            style=BUTTON_STYLE),
                style={"marginBottom": "14px"},
            ),
            html.Div(id="dash-kpi-cards",
                     style={"display": "flex", "gap": "14px", "flexWrap": "wrap",
                            "marginBottom": "18px"}),
            card(
                "Chaîne logistique",
                [dcc.Graph(id="dash-dag", figure=empty_figure("Chargement…"))],
            ),
            card(
                "Détail des nœuds",
                [
                    dash_table.DataTable(
                        id="dash-table",
                        columns=_TABLE_COLUMNS,
                        data=[],
                        sort_action="native",
                        style_cell=_TABLE_STYLE_CELL,
                        style_header=_TABLE_STYLE_HEADER,
                        style_data_conditional=_TABLE_CONDITIONAL,
                        style_as_list_view=True,
                    )
                ],
                subtitle="Fond rouge clair : A < 40 · H en rouge : H > 0.3.",
            ),
            card(
                "Évolution temporelle",
                [
                    labelled(
                        "Nœud",
                        dcc.Dropdown(id="dash-history-dd", options=[],
                                     placeholder="Choisir un nœud…"),
                        width="380px",
                    ),
                    dcc.Graph(
                        id="dash-history-fig",
                        figure=empty_figure("Sélectionnez un nœud pour afficher "
                                            "son historique."),
                    ),
                ],
            ),
        ],
        style=PAGE_STYLE,
    )


# --- Callbacks (fonctions nommées, testables sans serveur) -----------------------

def update_dashboard_callback(project_data, n_clicks):
    """Met à jour cartes KPI, DAG, tableau et options d'historique.

    Si le déclencheur est le bouton « Recalculer maintenant », le pipeline
    complet est relancé et persisté avant le rafraîchissement.
    """
    service = get_service()
    try:  # ctx indisponible hors requête Dash (appel direct en test)
        from dash import ctx
        triggered = ctx.triggered_id
    except Exception:
        triggered = None
    if triggered == "dash-recalc-btn":
        service.evaluate_all(persist=True)

    nodes = _scope_nodes(project_data)
    ids = {n.id for n in nodes}
    arcs = [a for a in service.repo.arcs()
            if a.source_id in ids and a.target_id in ids]

    rows = [
        {
            "Nom": n.name,
            "Rang": n.rank,
            "Statut": STATUS_FR.get(n.status, str(n.status)),
            "Ud_loc": _r3(n.urgency.ud_local),
            "Ur_loc": _r3(n.urgency.ur_local),
            "Ud": _r3(n.urgency.ud),
            "Ur": _r3(n.urgency.ur),
            "A": _r3(n.urgency.adequation),
            "F": _r3(n.urgency.false_urgency),
            "H": _r3(n.urgency.hidden_risk),
        }
        for n in sorted(nodes, key=lambda n: (n.rank, n.name))
    ]
    return (
        _kpi_summary(nodes),
        dashboard_dag_figure(nodes, arcs),
        rows,
        node_options(nodes),
    )


def history_figure_callback(node_id):
    """Figure d'évolution temporelle Ud/Ur/A du nœud sélectionné."""
    if not node_id:
        return empty_figure("Sélectionnez un nœud pour afficher son historique.")
    service = get_service()
    node = service.repo.get_node(node_id)
    name = node.name if node is not None else node_id
    series = service.client_db(node_id).urgency_series(node_id)
    return urgency_history_figure(series, name)


def register_callbacks(app) -> None:
    """Enregistre les callbacks de la page Dashboard sur l'application Dash."""
    app.callback(
        Output("dash-kpi-cards", "children"),
        Output("dash-dag", "figure"),
        Output("dash-table", "data"),
        Output("dash-history-dd", "options"),
        Input("store-project", "data"),
        Input("dash-recalc-btn", "n_clicks"),
    )(update_dashboard_callback)

    app.callback(
        Output("dash-history-fig", "figure"),
        Input("dash-history-dd", "value"),
    )(history_figure_callback)
