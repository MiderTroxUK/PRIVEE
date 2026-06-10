"""Page « Projets » : sélection/création de projets, démo, nœuds et statuts.

Tous les callbacks sont des fonctions nommées au niveau module, enregistrées
dans :func:`register_callbacks` — elles restent donc testables sans serveur.
"""

from __future__ import annotations

import uuid

from dash import Input, Output, State, dash_table, dcc, html, no_update
from dash.exceptions import PreventUpdate

from supplyscore.core.clock import iso_week
from supplyscore.domain.models import Project, SupplyNode, TaskStatus
from supplyscore.services.weekly import CycleHebdomadaire, EtatHebdo
from supplyscore.web_ui import get_service
from supplyscore.web_ui.components.badges import style_hebdo_conditionnel, texte_hebdo
from supplyscore.web_ui.components.layout import (
    BUTTON_STYLE,
    COLORS,
    FONT_FAMILY,
    INPUT_STYLE,
    MSG_ALERT_STYLE,
    MSG_OK_STYLE,
    PAGE_STYLE,
    STATUS_FR,
    card,
    labelled,
    node_options,
)

#: Labels métier proposés pour un nouveau nœud.
NODE_LABELS: list[str] = [
    "Client",
    "Factory",
    "Warehouse",
    "Workshop",
    "Supplier",
    "Transport",
]

_TABLE_COLUMNS = [
    {"name": "Nom", "id": "Nom"},
    {"name": "Rang", "id": "Rang", "type": "numeric"},
    {"name": "Label", "id": "Label"},
    {"name": "Statut", "id": "Statut"},
    {"name": "Hebdo", "id": "Hebdo"},
    {"name": "Ud", "id": "Ud", "type": "numeric"},
    {"name": "Ur", "id": "Ur", "type": "numeric"},
    {"name": "A", "id": "A", "type": "numeric"},
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


def _hebdo_texte(etat: EtatHebdo | None) -> str:
    """Texte de la cellule « Hebdo » d'un nœud (« — » si état inconnu)."""
    return "—" if etat is None else texte_hebdo(etat.statut, etat.semaines_de_retard)


def layout() -> html.Div:
    """Construit la page Projets (relit l'état du service à chaque navigation)."""
    service = get_service()
    project_opts = [{"label": p.name, "value": p.id} for p in service.registry.list_projects()]
    return html.Div(
        [
            dcc.Store(id="store-refresh", data=0),
            html.H2("Projets", style={"margin": "6px 0 6px"}),
            html.Div(id="active-project-msg", style={"marginBottom": "14px"}),
            card(
                "Projets existants",
                [
                    labelled(
                        "Projet",
                        dcc.Dropdown(
                            id="proj-dd", options=project_opts, placeholder="Choisir un projet…"
                        ),
                        width="340px",
                    ),
                    html.Div(html.Button("Sélectionner", id="proj-select-btn", style=BUTTON_STYLE)),
                    html.Div(id="proj-select-msg"),
                ],
                subtitle="Le projet sélectionné devient le projet actif de toutes les pages.",
            ),
            card(
                "Nouveau projet",
                [
                    labelled(
                        "Nom du projet",
                        dcc.Input(id="proj-name-input", type="text", style=INPUT_STYLE),
                    ),
                    labelled(
                        "Description",
                        dcc.Input(id="proj-desc-input", type="text", style=INPUT_STYLE),
                        width="300px",
                    ),
                    labelled(
                        "Client final (rang 0)",
                        dcc.Input(id="proj-client-input", type="text", style=INPUT_STYLE),
                    ),
                    labelled(
                        "Localisation",
                        dcc.Input(id="proj-location-input", type="text", style=INPUT_STYLE),
                    ),
                    html.Div(html.Button("Créer", id="proj-create-btn", style=BUTTON_STYLE)),
                    html.Div(id="proj-create-msg"),
                ],
                subtitle="Crée le projet et son nœud client final (rang 0).",
            ),
            card(
                "Générer une démo (données de TEST aléatoires)",
                [
                    labelled(
                        "Nombre de rangs (2..5)",
                        dcc.Input(
                            id="demo-ranks-input",
                            type="number",
                            min=2,
                            max=5,
                            step=1,
                            value=3,
                            style=INPUT_STYLE,
                        ),
                        width="180px",
                    ),
                    labelled(
                        "Graine aléatoire (seed)",
                        dcc.Input(
                            id="demo-seed-input", type="number", step=1, value=42, style=INPUT_STYLE
                        ),
                        width="180px",
                    ),
                    html.Div(html.Button("Générer la démo", id="demo-btn", style=BUTTON_STYLE)),
                    html.Div(id="demo-msg"),
                ],
                subtitle=(
                    "Données SIMULÉES, destinées uniquement aux tests et démos — "
                    "à ne JAMAIS utiliser en production."
                ),
            ),
            card(
                "Ajouter un client/fournisseur (rang quelconque)",
                [
                    labelled("Nom", dcc.Input(id="add-node-name", type="text", style=INPUT_STYLE)),
                    labelled(
                        "Label",
                        dcc.Dropdown(
                            id="add-node-label",
                            options=[{"label": lbl, "value": lbl} for lbl in NODE_LABELS],
                            value="Supplier",
                        ),
                        width="180px",
                    ),
                    labelled(
                        "Alimente quels nœuds (clients aval)",
                        dcc.Dropdown(
                            id="add-node-targets",
                            options=[],
                            multi=True,
                            placeholder="Aucun (rang 0)",
                        ),
                        width="380px",
                    ),
                    labelled(
                        "γ (dépendance Ud, descendante)",
                        dcc.Slider(
                            id="add-node-gamma",
                            min=0,
                            max=1,
                            step=0.05,
                            value=0.5,
                            marks={0: "0", 0.5: "0.5", 1: "1"},
                            tooltip={"placement": "bottom"},
                        ),
                        width="280px",
                    ),
                    labelled(
                        "β (propagation Ur, montante)",
                        dcc.Slider(
                            id="add-node-beta",
                            min=0,
                            max=1,
                            step=0.05,
                            value=0.5,
                            marks={0: "0", 0.5: "0.5", 1: "1"},
                            tooltip={"placement": "bottom"},
                        ),
                        width="280px",
                    ),
                    html.Div(html.Button("Ajouter le nœud", id="add-node-btn", style=BUTTON_STYLE)),
                    html.Div(id="add-node-msg"),
                ],
                subtitle="Le rang est déduit des clients aval : 1 + max(rang des cibles).",
            ),
            card(
                "Statut des tâches",
                [
                    labelled(
                        "Nœud",
                        dcc.Dropdown(
                            id="status-node-dd", options=[], placeholder="Choisir un nœud…"
                        ),
                        width="340px",
                    ),
                    labelled(
                        "Statut",
                        dcc.Dropdown(
                            id="status-dd",
                            options=[{"label": fr, "value": str(s)} for s, fr in STATUS_FR.items()],
                            placeholder="Choisir un statut…",
                        ),
                        width="200px",
                    ),
                    html.Div(html.Button("Appliquer", id="status-apply-btn", style=BUTTON_STYLE)),
                    html.Div(id="status-msg"),
                ],
                subtitle=(
                    "Marquer une tâche terminée ou abandonnée propage le choc sur tout le graphe."
                ),
            ),
            card(
                "Horloge du projet",
                [
                    labelled(
                        "Mode",
                        dcc.Dropdown(
                            id="clock-mode-dd",
                            options=[
                                {"label": "Temps réel", "value": "real"},
                                {"label": "Temps de jeu (serious game)", "value": "game"},
                            ],
                            placeholder="Choisir un mode…",
                        ),
                        width="260px",
                    ),
                    html.Div(
                        [
                            html.Button(
                                "Appliquer le mode", id="clock-mode-btn", style=BUTTON_STYLE
                            ),
                            html.Button(
                                "Avancer d'une semaine",
                                id="clock-advance-btn",
                                style={**BUTTON_STYLE, "marginLeft": "10px"},
                            ),
                        ]
                    ),
                    html.Div(id="clock-msg"),
                ],
                subtitle=(
                    "En mode jeu, « Avancer d'une semaine » fait progresser le temps simulé "
                    "du projet (l'animateur pilote les tours du serious game)."
                ),
            ),
            card(
                "Nœuds du projet actif",
                [
                    dash_table.DataTable(  # type: ignore[attr-defined]
                        id="proj-table",
                        columns=_TABLE_COLUMNS,
                        data=[],
                        sort_action="native",
                        style_cell=_TABLE_STYLE_CELL,
                        style_header=_TABLE_STYLE_HEADER,
                        style_data_conditional=style_hebdo_conditionnel("Hebdo"),
                        style_as_list_view=True,
                    )
                ],
            ),
        ],
        style=PAGE_STYLE,
    )


# --- Callbacks (fonctions nommées, testables sans serveur) --------------------


def select_project_callback(n_clicks, project_id):
    """Sélectionne un projet existant et l'écrit dans le store de session."""
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    if not project_id:
        return no_update, html.Span(
            "Choisissez d'abord un projet dans la liste.", style=MSG_ALERT_STYLE
        )
    project = service.registry.get_project(project_id)
    if project is None:
        return no_update, html.Span("Projet introuvable dans le registre.", style=MSG_ALERT_STYLE)
    data = {"project_id": project.id, "name": project.name}
    return data, html.Span(f"Projet actif : « {project.name} ».", style=MSG_OK_STYLE)


def create_project_callback(n_clicks, name, description, client_name, location, refresh):
    """Crée un projet et son nœud client final (rang 0), puis le sélectionne."""
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    if not name or not str(name).strip():
        return (
            no_update,
            html.Span("Le nom du projet est requis.", style=MSG_ALERT_STYLE),
            no_update,
        )
    if not client_name or not str(client_name).strip():
        return (
            no_update,
            html.Span("Le nom du client final (rang 0) est requis.", style=MSG_ALERT_STYLE),
            no_update,
        )
    project_id = str(uuid.uuid4())
    node = SupplyNode(
        id=str(uuid.uuid4()),
        name=str(client_name).strip(),
        label="Client",
        rank=0,
        project_id=project_id,
        location=str(location).strip() if location and str(location).strip() else None,
    )
    project = Project(
        id=project_id,
        name=str(name).strip(),
        owner_node_id=node.id,
        description=str(description).strip() if description else "",
    )
    service.create_project(project, [node], [])
    data = {"project_id": project.id, "name": project.name}
    msg = html.Span(f"Projet « {project.name} » créé et sélectionné.", style=MSG_OK_STYLE)
    return data, msg, (refresh or 0) + 1


def seed_demo_callback(n_clicks, n_ranks, seed, refresh):
    """Génère un projet de démonstration aléatoire (données de TEST) et le sélectionne."""
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    ranks = min(max(int(n_ranks) if n_ranks is not None else 3, 2), 5)
    seed_value = int(seed) if seed is not None else 42
    project = service.seed_demo(n_ranks=ranks, seed=seed_value)
    data = {"project_id": project.id, "name": project.name}
    msg = html.Span(
        f"Démo « {project.name} » générée et sélectionnée — données SIMULÉES, "
        "jamais pour la production.",
        style=MSG_OK_STYLE,
    )
    return data, msg, (refresh or 0) + 1


def add_node_callback(n_clicks, name, label, targets, gamma, beta, project_data, refresh):
    """Ajoute un client/fournisseur relié à ses clients aval puis réévalue tout."""
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    project_id = (project_data or {}).get("project_id")
    if not project_id:
        return html.Span("Sélectionnez d'abord un projet actif.", style=MSG_ALERT_STYLE), no_update
    if not name or not str(name).strip():
        return html.Span("Le nom du nœud est requis.", style=MSG_ALERT_STYLE), no_update
    target_ids: list[str] = []
    ranks: list[int] = []
    for target_id in targets or []:
        target_node = service.repo.get_node(target_id)
        if target_node is not None:
            target_ids.append(target_id)
            ranks.append(target_node.rank)
    rank = 1 + max(ranks) if ranks else 0
    node = SupplyNode(
        id=str(uuid.uuid4()),
        name=str(name).strip(),
        label=label or "Workshop",
        rank=rank,
        project_id=project_id,
    )
    service.add_node(
        node,
        supplies_to=target_ids,
        gamma=float(gamma) if gamma is not None else 0.5,
        beta=float(beta) if beta is not None else 0.5,
    )
    service.evaluate_all(persist=True)
    msg = html.Span(
        f"Nœud « {node.name} » ajouté au rang {rank} "
        f"({len(target_ids)} client(s) aval) — urgences recalculées.",
        style=MSG_OK_STYLE,
    )
    return msg, (refresh or 0) + 1


def set_status_callback(n_clicks, node_id, status_value, refresh):
    """Applique un statut (active/terminée/abandonnée) et repropage le choc."""
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    if not node_id or not status_value:
        return html.Span("Choisissez un nœud ET un statut.", style=MSG_ALERT_STYLE), no_update
    status = TaskStatus(status_value)
    service.set_status(node_id, status)
    node = service.repo.get_node(node_id)
    name = node.name if node is not None else node_id
    msg = html.Span(
        f"Statut « {STATUS_FR[status]} » appliqué à « {name} » : "
        "le choc est propagé sur tout le graphe.",
        style=MSG_OK_STYLE,
    )
    return msg, (refresh or 0) + 1


def set_clock_mode_callback(n_clicks, project_data, mode, refresh):
    """Bascule l'horloge du projet actif entre temps réel et temps de jeu."""
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    pid = (project_data or {}).get("project_id")
    if not pid:
        return html.Span("Sélectionnez d'abord un projet.", style=MSG_ALERT_STYLE), no_update
    if mode not in ("real", "game"):
        return html.Span("Choisissez un mode d'horloge.", style=MSG_ALERT_STYLE), no_update
    service.set_clock_mode(pid, mode)
    label = "temps réel" if mode == "real" else "temps de jeu"
    week = iso_week(service.clock_for(pid).now())
    msg = html.Span(f"Horloge du projet : {label} — semaine courante {week}.", style=MSG_OK_STYLE)
    return msg, (refresh or 0) + 1


def advance_week_callback(n_clicks, project_data, refresh):
    """Avance le temps de jeu d'une semaine puis réévalue tout le réseau."""
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    pid = (project_data or {}).get("project_id")
    if not pid:
        return html.Span("Sélectionnez d'abord un projet.", style=MSG_ALERT_STYLE), no_update
    try:
        service.advance_week(pid)
    except ValueError as exc:
        return html.Span(str(exc), style=MSG_ALERT_STYLE), no_update
    week = iso_week(service.clock_for(pid).now())
    msg = html.Span(
        f"Semaine avancée : le projet est maintenant en {week} "
        "(scores réévalués sur tout le graphe).",
        style=MSG_OK_STYLE,
    )
    return msg, (refresh or 0) + 1


def update_view_callback(project_data, refresh):
    """Rafraîchit dropdowns, tableau (statuts hebdo inclus) et bandeau du projet actif."""
    service = get_service()
    project_opts = [{"label": p.name, "value": p.id} for p in service.registry.list_projects()]
    pid = (project_data or {}).get("project_id")
    etats: dict[str, EtatHebdo] = {}
    if pid:
        nodes = [n for n in service.repo.nodes() if n.project_id == pid]
        etats = CycleHebdomadaire(service).synthese(pid)
        name = (project_data or {}).get("name", pid)
        week = iso_week(service.clock_for(pid).now())
        mode = "temps de jeu" if service.clock_mode(pid) == "game" else "temps réel"
        active = html.Span(
            f"Projet actif : « {name} » ({len(nodes)} nœud(s)) — semaine {week} [{mode}].",
            style={"color": COLORS["primary"], "fontWeight": "600"},
        )
    else:
        nodes = []
        active = html.Span(
            "Aucun projet sélectionné : choisissez ou créez un projet ci-dessous.",
            style={"color": COLORS["muted"]},
        )
    opts = node_options(nodes)
    rows = [
        {
            "Nom": n.name,
            "Rang": n.rank,
            "Label": n.label,
            "Statut": STATUS_FR.get(n.status, str(n.status)),
            "Hebdo": _hebdo_texte(etats.get(n.id)),
            "Ud": _r3(n.urgency.ud),
            "Ur": _r3(n.urgency.ur),
            "A": _r3(n.urgency.adequation),
        }
        for n in sorted(nodes, key=lambda n: (n.rank, n.name))
    ]
    return project_opts, opts, opts, rows, active


def register_callbacks(app) -> None:
    """Enregistre les callbacks de la page Projets sur l'application Dash."""
    app.callback(
        Output("store-project", "data", allow_duplicate=True),
        Output("proj-select-msg", "children"),
        Input("proj-select-btn", "n_clicks"),
        State("proj-dd", "value"),
        prevent_initial_call=True,
    )(select_project_callback)

    app.callback(
        Output("store-project", "data", allow_duplicate=True),
        Output("proj-create-msg", "children"),
        Output("store-refresh", "data", allow_duplicate=True),
        Input("proj-create-btn", "n_clicks"),
        State("proj-name-input", "value"),
        State("proj-desc-input", "value"),
        State("proj-client-input", "value"),
        State("proj-location-input", "value"),
        State("store-refresh", "data"),
        prevent_initial_call=True,
    )(create_project_callback)

    app.callback(
        Output("store-project", "data", allow_duplicate=True),
        Output("demo-msg", "children"),
        Output("store-refresh", "data", allow_duplicate=True),
        Input("demo-btn", "n_clicks"),
        State("demo-ranks-input", "value"),
        State("demo-seed-input", "value"),
        State("store-refresh", "data"),
        prevent_initial_call=True,
    )(seed_demo_callback)

    app.callback(
        Output("add-node-msg", "children"),
        Output("store-refresh", "data", allow_duplicate=True),
        Input("add-node-btn", "n_clicks"),
        State("add-node-name", "value"),
        State("add-node-label", "value"),
        State("add-node-targets", "value"),
        State("add-node-gamma", "value"),
        State("add-node-beta", "value"),
        State("store-project", "data"),
        State("store-refresh", "data"),
        prevent_initial_call=True,
    )(add_node_callback)

    app.callback(
        Output("status-msg", "children"),
        Output("store-refresh", "data", allow_duplicate=True),
        Input("status-apply-btn", "n_clicks"),
        State("status-node-dd", "value"),
        State("status-dd", "value"),
        State("store-refresh", "data"),
        prevent_initial_call=True,
    )(set_status_callback)

    app.callback(
        Output("clock-msg", "children"),
        Output("store-refresh", "data", allow_duplicate=True),
        Input("clock-mode-btn", "n_clicks"),
        State("store-project", "data"),
        State("clock-mode-dd", "value"),
        State("store-refresh", "data"),
        prevent_initial_call=True,
    )(set_clock_mode_callback)

    app.callback(
        Output("clock-msg", "children", allow_duplicate=True),
        Output("store-refresh", "data", allow_duplicate=True),
        Input("clock-advance-btn", "n_clicks"),
        State("store-project", "data"),
        State("store-refresh", "data"),
        prevent_initial_call=True,
    )(advance_week_callback)

    app.callback(
        Output("proj-dd", "options"),
        Output("add-node-targets", "options"),
        Output("status-node-dd", "options"),
        Output("proj-table", "data"),
        Output("active-project-msg", "children"),
        Input("store-project", "data"),
        Input("store-refresh", "data"),
    )(update_view_callback)
