"""Page « Édition des KPIs » : tableau éditable filtré par projet, bloc et tags.

Chaque ligne du tableau porte un champ ``id`` STABLE égal au ``node_id`` du
nœud : c'est la clé du diff entre ``data`` et ``data_previous`` — JAMAIS
l'index de ligne, qui change dès que l'ordre des lignes bouge.

PIÈGE DOCUMENTÉ : ``sort_action="none"`` est imposé en mode édition. Avec le
tri natif activé, l'utilisateur peut réordonner les lignes ENTRE deux éditions
et ``data_previous`` ne refléterait plus l'ordre courant — un diff par index
écrirait alors le KPI du MAUVAIS nœud. Le diff par row id reste correct même
réordonné, mais on fige l'ordre pour garder ``data``/``data_previous``
alignés visuellement et éviter toute ambiguïté.

Toute écriture passe par :meth:`MutationService.update_kpis` (diff +
validation + audit ``source='edit'``) puis ``evaluate_all(persist=True)`` :
les scores sont réévalués immédiatement. Sur REJET (``ValueError`` de
validation), la table est RECHARGÉE depuis la base — la cellule fautive est
ainsi restaurée. Sur succès, la table N'EST PAS réécrite (``no_update``,
anti-scintillement) : la valeur affichée est déjà celle persistée.

Les callbacks sont des fonctions nommées au niveau module (enregistrées dans
:func:`register_callbacks`) : testables sans serveur Dash.
"""

from __future__ import annotations

from dash import Input, Output, State, dash_table, dcc, html, no_update

from supplyscore.domain.constraints import kpi_unit
from supplyscore.web_ui import get_service
from supplyscore.web_ui.components.layout import (
    COLORS,
    FONT_FAMILY,
    MSG_ALERT_STYLE,
    MSG_OK_STYLE,
    PAGE_STYLE,
    card,
    labelled,
)
from supplyscore.web_ui.components.operator import current_operator
from supplyscore.web_ui.pages.questionnaire import KPI_FIELDS

#: Bloc affiché par défaut (premier bloc de ``KPI_FIELDS``) : « Temps ».
DEFAULT_BLOCK: str = KPI_FIELDS[0][0]

#: Colonnes non-KPI d'une ligne du tableau (jamais diffées).
_META_KEYS: frozenset[str] = frozenset({"id", "Nœud"})

_MSG_MUTED_STYLE = {"color": COLORS["muted"], "marginTop": "10px", "fontSize": "14px"}

_WARNING_BANNER_STYLE = {
    "backgroundColor": "#fdf3e7",
    "border": f"1px solid {COLORS['warn']}",
    "borderRadius": "6px",
    "color": COLORS["warn"],
    "padding": "10px 14px",
    "marginBottom": "16px",
    "fontSize": "14px",
}

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


# --- Aides de construction du tableau ------------------------------------------------


def _block_fields(block_name: str | None) -> list[tuple[str, str]]:
    """Champs ``(chemin, libellé)`` du bloc demandé (défaut : bloc « Temps »)."""
    for title, fields in KPI_FIELDS:
        if title == block_name:
            return fields
    return KPI_FIELDS[0][1]


def _column_name(path: str, label: str) -> str:
    """Nom de colonne « libellé + unité ».

    Les libellés de ``KPI_FIELDS`` embarquent déjà l'unité entre parenthèses
    pour la plupart des champs (« Lead time (h) ») : on ne suffixe
    :func:`kpi_unit` que si le libellé n'en contient aucune.
    """
    unit = kpi_unit(path)
    if not unit or "(" in label:
        return label
    return f"{label} ({unit})"


def _block_columns(block_name: str | None) -> list[dict]:
    """Colonnes DataTable du bloc : « Nœud » non éditable + un KPI par colonne."""
    columns: list[dict] = [{"name": "Nœud", "id": "Nœud", "editable": False}]
    for path, label in _block_fields(block_name):
        columns.append(
            {"name": _column_name(path, label), "id": path, "type": "numeric", "editable": True}
        )
    return columns


def _table_rows(project_id: str | None, block_name: str | None, tag_ids: list | None) -> list[dict]:
    """Lignes du tableau relues depuis la BASE (registre) — une par nœud du projet.

    Chaque ligne porte ``"id": node_id`` (row id stable, clé du diff). Les
    nœuds sont filtrés par tags (intersection non vide avec ``node.tags`` si
    des tags sont sélectionnés) puis triés par rang/nom.
    """
    if not project_id:
        return []
    service = get_service()
    nodes = service.registry.list_nodes(project_id)
    if tag_ids:
        wanted = set(tag_ids)
        nodes = [n for n in nodes if wanted & set(n.tags)]
    rows: list[dict] = []
    for node in sorted(nodes, key=lambda n: (n.rank, n.name)):
        row: dict = {"id": node.id, "Nœud": node.name}
        for path, _label in _block_fields(block_name):
            block, field = path.split(".", 1)
            row[path] = getattr(getattr(node.kpis, block), field)
        rows.append(row)
    return rows


# --- Layout ---------------------------------------------------------------------------


def layout() -> html.Div:
    """Construit la page Édition des KPIs (état du service relu à chaque navigation)."""
    service = get_service()
    project_options = [{"label": p.name, "value": p.id} for p in service.registry.list_projects()]
    block_options = [{"label": title, "value": title} for title, _fields in KPI_FIELDS]
    return html.Div(
        [
            html.H2("Édition des KPIs", style={"margin": "6px 0 12px"}),
            html.Div(
                "Les modifications sont auditées et réévaluent les scores immédiatement.",
                style=_WARNING_BANNER_STYLE,
            ),
            card(
                "Filtres",
                [
                    labelled(
                        "Projet",
                        dcc.Dropdown(
                            id="edit-project-dd",
                            options=project_options,
                            placeholder="Choisir un projet…",
                        ),
                        width="300px",
                    ),
                    labelled(
                        "Bloc de KPIs",
                        dcc.Dropdown(
                            id="edit-block-dd",
                            options=block_options,
                            value=DEFAULT_BLOCK,
                            clearable=False,
                        ),
                        width="220px",
                    ),
                    labelled(
                        "Tags (intersection non vide)",
                        dcc.Dropdown(
                            id="edit-tags-dd",
                            options=[],
                            value=[],
                            multi=True,
                            placeholder="Tous les nœuds",
                        ),
                        width="320px",
                    ),
                ],
            ),
            card(
                "KPIs courants",
                [
                    dash_table.DataTable(  # type: ignore[attr-defined]
                        id="kpi-edit-table",
                        columns=_block_columns(DEFAULT_BLOCK),
                        data=[],
                        editable=True,
                        # Tri DÉSACTIVÉ en mode édition : l'ordre des lignes doit
                        # rester stable pour que data_previous reste comparable
                        # (voir la docstring du module).
                        sort_action="none",
                        style_cell=_TABLE_STYLE_CELL,
                        style_header=_TABLE_STYLE_HEADER,
                        style_as_list_view=True,
                    ),
                    html.Div(id="edit-msg"),
                ],
                subtitle=(
                    "Cellule vide = KPI non renseigné (None). Une valeur hors bornes "
                    "est refusée et la cellule restaurée."
                ),
            ),
        ],
        style=PAGE_STYLE,
    )


# --- Callbacks (fonctions nommées, testables sans serveur) -----------------------------


def tags_options_callback(project_id):
    """Options du dropdown tags = tags du projet sélectionné (valeur réinitialisée).

    Sans projet, la liste est vide et la sélection est effacée : des ids de
    tags d'un autre projet ne doivent jamais filtrer le tableau courant.
    """
    if not project_id:
        return [], []
    service = get_service()
    options = [{"label": t.name, "value": t.id} for t in service.registry.list_tags(project_id)]
    return options, []


def refresh_table_callback(project_id, block_name, tag_ids):
    """Reconstruit colonnes et lignes du tableau selon les trois filtres.

    Colonnes : « Nœud » (non éditable) + une colonne numérique éditable par
    champ du bloc choisi (id = chemin « bloc.champ », nom = libellé + unité).
    Lignes : nœuds du projet (filtrés par tags, triés par rang/nom), chaque
    ligne portant ``"id": node_id`` — la clé STABLE du diff d'édition.
    """
    return _block_columns(block_name), _table_rows(project_id, block_name, tag_ids)


def edit_cell_callback(timestamp, data, previous, operator_store, project_id, block_name, tag_ids):
    """Persiste la cellule éditée via MutationService (diff par ROW ID, jamais par index).

    Cheminement :

    - ``data_previous`` absent (premier rendu) ou aucun écart → ``no_update`` ;
    - la cellule changée est repérée en comparant chaque ligne de ``data`` à
      la ligne de MÊME ``id`` dans ``data_previous`` (robuste au
      réordonnancement) ;
    - coercition ``float()`` défensive (la DataTable renvoie parfois des
      chaînes même sur colonne numeric) ; vide/None = effacement du KPI ;
    - succès → ``evaluate_all(persist=True)`` + message vert et ``no_update``
      sur la table (anti-scintillement : on ne réécrit ``data`` que sur REJET) ;
    - rejet (``ValueError`` de validation, nœud inconnu, valeur non
      numérique) → la table est RECHARGÉE depuis la base (cellule restaurée)
      + message d'erreur. Si ce rechargement redéclenchait le callback, le
      diff retomberait sur la valeur de la base : ``update_kpis`` ne verrait
      aucun changement effectif (no-op) — pas de boucle possible.

    Returns:
        ``(data, message)`` — ``data`` vaut ``no_update`` sauf sur rejet.
    """
    if previous is None or data is None:
        return no_update, no_update

    previous_by_id = {row.get("id"): row for row in previous}
    change: tuple[str, str, object] | None = None
    for row in data:
        before = previous_by_id.get(row.get("id"))
        if before is None:
            continue
        for path, cell in row.items():
            if path in _META_KEYS:
                continue
            if cell != before.get(path):
                change = (row["id"], path, cell)
                break
        if change is not None:
            break
    if change is None:
        return no_update, no_update

    node_id, path, raw = change
    if raw is None or raw == "":
        value: float | None = None  # effacement : KPI non renseigné
    else:
        try:
            value = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return (
                _table_rows(project_id, block_name, tag_ids),
                html.Span(
                    f"Valeur non numérique pour « {path} » : {raw!r} — cellule restaurée.",
                    style=MSG_ALERT_STYLE,
                ),
            )

    service = get_service()
    try:
        entries = service.mutations.update_kpis(
            node_id, {path: value}, source="edit", operator_id=current_operator(operator_store)
        )
    except (KeyError, ValueError) as exc:
        return (
            _table_rows(project_id, block_name, tag_ids),
            html.Span(f"Modification refusée : {exc}", style=MSG_ALERT_STYLE),
        )

    if not entries:  # valeur identique à la base : aucun audit, aucun recalcul
        return no_update, html.Span(
            "Valeur identique à celle en base — aucune écriture.", style=_MSG_MUTED_STYLE
        )

    service.evaluate_all(persist=True)
    return no_update, html.Span(
        f"KPI mis à jour — {len(entries)} entrée(s) d'audit.", style=MSG_OK_STYLE
    )


def register_callbacks(app) -> None:
    """Enregistre les callbacks de la page Édition des KPIs sur l'application Dash."""
    app.callback(
        Output("edit-tags-dd", "options"),
        Output("edit-tags-dd", "value"),
        Input("edit-project-dd", "value"),
    )(tags_options_callback)

    app.callback(
        Output("kpi-edit-table", "columns"),
        Output("kpi-edit-table", "data"),
        Input("edit-project-dd", "value"),
        Input("edit-block-dd", "value"),
        Input("edit-tags-dd", "value"),
    )(refresh_table_callback)

    app.callback(
        Output("kpi-edit-table", "data", allow_duplicate=True),
        Output("edit-msg", "children"),
        Input("kpi-edit-table", "data_timestamp"),
        State("kpi-edit-table", "data"),
        State("kpi-edit-table", "data_previous"),
        State("store-operator", "data"),
        State("edit-project-dd", "value"),
        State("edit-block-dd", "value"),
        State("edit-tags-dd", "value"),
        prevent_initial_call=True,
    )(edit_cell_callback)
