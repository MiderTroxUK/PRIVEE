"""Page " /admin " : vue " Donnees brutes " type administrateur (Lot 10.5).

Zone avancee VERROUILLEE par defaut : la :class:`dash_table.DataTable` est en
lecture seule tant que l'operateur n'a pas deverrouille l'edition via le
bouton " Deverrouiller l'edition " (confirme par un
``dcc.ConfirmDialogProvider``). Meme deverrouillee, la table ne devient
editable QUE si elle figure dans la liste blanche du service
(:class:`~supplyscore.services.raw_admin.RawTableService`) - les tables
d'historique restent ineditables par construction.

Parcours : dropdown base (" Registre " + bases client par nom de noeud) ->
dropdown table (" nom (n lignes) ", our les non editables) -> DataTable
paginee (pagination custom servie par :meth:`RawTableService.fetch`). Une
edition de cellule est diffee par LIGNE sur le ``rowid`` SQLite (cle de ligne
universelle incluse par ``fetch``), validee et auditee par
:meth:`RawTableService.update_cell`, puis le reseau est revalide
(``evaluate_all(persist=True)``) et le DeltaUr maximal est annonce. Un refus
recharge la table et affiche la cause en rouge.

Le routage " /admin " et le lien de navigation sont branches par la tache
d'integration E10.I dans ``app.py`` (la page expose ``layout()`` et
:func:`register_callbacks`).
"""

from __future__ import annotations

import math

from dash import Input, Output, State, dash_table, dcc, html
from dash.exceptions import PreventUpdate

from supplyscore.services.raw_admin import ForbiddenTableError, RawTableService
from supplyscore.web_ui import get_service
from supplyscore.web_ui.components.layout import (
    BUTTON_SECONDARY_STYLE,
    COLORS,
    FONT_FAMILY,
    MSG_ALERT_STYLE,
    MSG_OK_STYLE,
    PAGE_STYLE,
    card,
    labelled,
)
from supplyscore.web_ui.components.operator import current_operator

#: Taille de page de la DataTable (= ``limit`` des lectures du service).
PAGE_SIZE = 50

#: Seuil au-dela duquel une variation d'Ur compte comme " noeud impacte ".
_UR_EPSILON = 1e-9

#: Bandeau ROUGE d'avertissement en tete de page.
_BANNER_TEXT = (
    "Zone avancée : édition cellule par cellule, sous audit. "
    "Les tables d'historique sont inéditables par construction."
)

_BANNER_STYLE = {
    "backgroundColor": COLORS["alert"],
    "color": "#fff",
    "padding": "12px 16px",
    "borderRadius": "6px",
    "fontWeight": "600",
    "fontSize": "14px",
    "marginBottom": "16px",
    "fontFamily": FONT_FAMILY,
}

_TABLE_STYLE_CELL = {
    "fontFamily": FONT_FAMILY,
    "fontSize": "13px",
    "padding": "6px 10px",
    "textAlign": "left",
    "maxWidth": "320px",
    "overflow": "hidden",
    "textOverflow": "ellipsis",
}

_TABLE_STYLE_HEADER = {
    "fontWeight": "700",
    "backgroundColor": "#eef2f5",
    "color": COLORS["text"],
}


def _fr(value: float, digits: int = 3) -> str:
    """Nombre formate a la francaise (virgule decimale) pour les PHRASES.

    Reserve aux messages francais visibles - jamais aux inputs ni aux
    colonnes numeriques de DataTable (Dash exige le point).
    """
    return f"{value:.{digits}f}".replace(".", ",")


# Layout


def _db_options() -> list[dict]:
    """Options du dropdown de base : " Registre " puis les noeuds par NOM."""
    service = get_service()
    options: list[dict] = [{"label": "Registre", "value": "registry"}]
    for node in sorted(service.registry.list_nodes(), key=lambda n: (n.rank, n.name)):
        options.append({"label": node.name, "value": node.id})
    return options


def layout() -> html.Div:
    """Construit la page Donnees brutes (etat du service relu a chaque navigation)."""
    return html.Div(
        [
            html.H2("Données brutes", style={"margin": "6px 0 10px"}),
            html.Div(_BANNER_TEXT, id="admin-banner", style=_BANNER_STYLE),
            card(
                "Sélection",
                [
                    labelled(
                        "Base",
                        dcc.Dropdown(
                            id="admin-db-dd",
                            options=_db_options(),
                            placeholder="Choisir une base…",
                        ),
                        width="320px",
                    ),
                    labelled(
                        "Table",
                        dcc.Dropdown(
                            id="admin-table-dd",
                            options=[],
                            placeholder="Choisir une table…",
                        ),
                        width="420px",
                    ),
                    html.Div(
                        dcc.ConfirmDialogProvider(
                            html.Button(
                                "Déverrouiller l'édition",
                                id="admin-unlock",
                                style=BUTTON_SECONDARY_STYLE,
                            ),
                            id="admin-unlock-confirm",
                            message="Vous éditez les données brutes sous audit. Continuer ?",
                        ),
                        style={"marginBottom": "8px"},
                    ),
                ],
                subtitle=(
                    "La table reste en LECTURE SEULE tant que l'édition n'est pas "
                    "déverrouillée — et seules les tables de la liste blanche s'éditent."
                ),
            ),
            card(
                "Contenu",
                [
                    # E16.6 - dcc.Loading autour de la table paginee (lecture SQLite page par page) : l'id reste sur la DataTable.
                    dcc.Loading(
                        type="circle",
                        children=dash_table.DataTable(  # type: ignore[attr-defined]
                            id="admin-table",
                            columns=[],
                            data=[],
                            editable=False,
                            page_action="custom",
                            page_current=0,
                            page_size=PAGE_SIZE,
                            page_count=1,
                            style_table={"overflowX": "auto"},
                            style_cell=_TABLE_STYLE_CELL,
                            style_header=_TABLE_STYLE_HEADER,
                        ),
                    )
                ],
                subtitle=(
                    "Choisissez d'abord une base puis une table ci-dessus : son contenu "
                    "s'affiche ici page par page (la colonne rowid est la clé technique "
                    "des lignes)."
                ),
            ),
            html.Div(id="admin-msg"),
        ],
        style=PAGE_STYLE,
    )


# Callbacks (fonctions nommees, testables sans serveur)


def tables_callback(db):
    """Options du dropdown table au choix d'une base : " nom (n lignes) " + [verrou].

    Le cadenas marque les tables NON editables (hors liste blanche ou
    historique append-only). La valeur courante est reinitialisee.
    """
    if not db:
        return [], None
    raw = RawTableService(get_service())
    options = []
    for info in raw.list_tables(str(db)):
        suffix = "" if info.editable else " 🔒"
        options.append(
            {"label": f"{info.name} ({info.row_count} lignes){suffix}", "value": info.name}
        )
    return options, None


def reset_page_callback(_table):
    """Repart a la premiere page quand la table choisie change."""
    return 0


def table_data_callback(table, page_current, db):
    """Charge la page courante de la table (lecture seule, ``rowid`` inclus).

    La colonne ``rowid`` reste ineditable au niveau colonne ; les autres
    colonnes suivent l'editabilite GLOBALE de la table (geree par
    :func:`unlock_callback`) - aucun ``editable=True`` par colonne, qui
    contournerait le verrou global.
    """
    if not db or not table:
        return [], [], 1
    raw = RawTableService(get_service())
    page = int(page_current or 0)
    rows, columns = raw.fetch(str(db), str(table), limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    cols = []
    for name in columns:
        col: dict = {"name": name, "id": name}
        if name == "rowid":
            col["editable"] = False
        cols.append(col)
    total = next((info.row_count for info in raw.list_tables(str(db)) if info.name == table), 0)
    return rows, cols, max(1, math.ceil(total / PAGE_SIZE))


def unlock_callback(submit_n_clicks, table, db):
    """Editabilite de la DataTable : deverrouillage confirme ET table whitelistee.

    La confirmation du ``ConfirmDialogProvider`` deverrouille l'edition pour
    la session de page, mais une table FORBIDDEN ou hors liste blanche reste
    ineditable quoi qu'il arrive (``editable=False``).
    """
    if not submit_n_clicks or not db or not table:
        return False
    raw = RawTableService(get_service())
    return any(info.editable for info in raw.list_tables(str(db)) if info.name == table)


def _diff_cell(data, data_previous):
    """Premiere cellule modifiee entre deux etats de la table, par LIGNE (rowid).

    Returns:
        ``(rowid, colonne, nouvelle valeur)`` ou None si rien n'a change.
    """
    previous_by_rowid = {row.get("rowid"): row for row in data_previous}
    for row in data:
        before = previous_by_rowid.get(row.get("rowid"))
        if before is None:
            continue
        for column, value in row.items():
            if column != "rowid" and before.get(column) != value:
                return row.get("rowid"), column, value
    return None


def _reload(raw: RawTableService, db: str, table: str, page: int):
    """Recharge la page courante de la table (apres refus ou ecriture)."""
    rows, _columns = raw.fetch(db, table, limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    return rows


def edit_callback(_timestamp, data, data_previous, db, table, page_current, operator_data):
    """Edition d'une cellule : diff par rowid -> ``update_cell`` -> revalidation.

    Succes : la modification est auditee, le graphe est recharge depuis le
    registre si l'edition l'a touche, le reseau est reevalue
    (``evaluate_all(persist=True)``) et le message annonce
    " 1 cellule modifiee, revalidation OK, DeltaUr max = x.xxx sur n noeud(s) "
    (Ur compares avant/apres). Refus (contrainte violee, table interdite,
    cle invalide) : la table est RECHARGEE depuis la base et la cause est
    affichee en rouge - rien n'a ete ecrit.
    """
    if not data_previous or not db or not table:
        raise PreventUpdate
    change = _diff_cell(data or [], data_previous)
    if change is None:
        raise PreventUpdate
    rowid, column, value = change
    service = get_service()
    raw = RawTableService(service)
    db, table, page = str(db), str(table), int(page_current or 0)
    try:
        result = raw.update_cell(
            db,
            table,
            {"rowid": rowid},
            str(column),
            value,
            operator_id=current_operator(operator_data),
        )
    except (ForbiddenTableError, ValueError) as exc:
        message = html.Span(f"Édition refusée : {exc}", style=MSG_ALERT_STYLE)
        return message, _reload(raw, db, table, page)
    if not result.ok:
        return html.Span(result.message_fr, style=MSG_ALERT_STYLE), _reload(raw, db, table, page)

    ur_before = {node.id: node.urgency.ur or 0.0 for node in service.repo.nodes()}
    if db == "registry":
        # L'edition brute a contourne le depot en memoire : on le resynchronise.
        service.load_graph_from_registry()
    states = service.evaluate_all(persist=True)
    deltas = [abs((state.ur or 0.0) - ur_before.get(nid, 0.0)) for nid, state in states.items()]
    impacted = sum(1 for delta in deltas if delta > _UR_EPSILON)
    message = html.Span(
        f"1 cellule modifiée, revalidation OK, ΔUr max = {_fr(max(deltas, default=0.0))} "
        f"sur {impacted} nœud(s) — {result.message_fr}",
        style=MSG_OK_STYLE,
    )
    return message, _reload(raw, db, table, page)


def register_callbacks(app) -> None:
    """Enregistre les callbacks de la page Donnees brutes sur l'app Dash."""
    app.callback(
        Output("admin-table-dd", "options"),
        Output("admin-table-dd", "value"),
        Input("admin-db-dd", "value"),
    )(tables_callback)

    app.callback(
        Output("admin-table", "page_current"),
        Input("admin-table-dd", "value"),
        prevent_initial_call=True,
    )(reset_page_callback)

    app.callback(
        Output("admin-table", "data"),
        Output("admin-table", "columns"),
        Output("admin-table", "page_count"),
        Input("admin-table-dd", "value"),
        Input("admin-table", "page_current"),
        State("admin-db-dd", "value"),
    )(table_data_callback)

    app.callback(
        Output("admin-table", "editable"),
        Input("admin-unlock-confirm", "submit_n_clicks"),
        Input("admin-table-dd", "value"),
        State("admin-db-dd", "value"),
    )(unlock_callback)

    app.callback(
        Output("admin-msg", "children"),
        Output("admin-table", "data", allow_duplicate=True),
        Input("admin-table", "data_timestamp"),
        State("admin-table", "data"),
        State("admin-table", "data_previous"),
        State("admin-db-dd", "value"),
        State("admin-table-dd", "value"),
        State("admin-table", "page_current"),
        State("store-operator", "data"),
        prevent_initial_call=True,
    )(edit_callback)
