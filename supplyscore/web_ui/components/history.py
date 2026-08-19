"""Composants UI d'historique : journal d'audit et trajectoire de KPI.

Le tableau d'historique accepte ses entrees en duck-typing : les attributs
sont lus via ``getattr`` avec valeur par defaut. La dataclass ``AuditEntry``
(``supplyscore.data.audit``) est developpee en parallele et n'est
volontairement PAS importee ici - tout objet exposant ``timestamp``,
``iso_week``, ``field``, ``old_value``, ``new_value``, ``source`` et
``operator_id`` convient, et un attribut manquant ne fait pas planter le rendu.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

import plotly.graph_objects as go
from dash import dash_table

from supplyscore.web_ui.components.figures import empty_figure
from supplyscore.web_ui.components.layout import COLORS, FONT_FAMILY

_TEMPLATE = "plotly_white"

#: Colonnes francaises du journal d'audit (l'" id " sert de cle des lignes).
_HISTORY_COLUMNS = [
    {"name": "Date", "id": "Date"},
    {"name": "Semaine", "id": "Semaine"},
    {"name": "Champ", "id": "Champ"},
    {"name": "Ancienne valeur", "id": "Ancienne valeur"},
    {"name": "Nouvelle valeur", "id": "Nouvelle valeur"},
    {"name": "Source", "id": "Source"},
    {"name": "Opérateur", "id": "Opérateur"},
]

# Styles alignes sur les DataTable existantes (pages projets / dashboard).
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


def _fmt_date(timestamp: Any) -> str:
    """Formate un timestamp epoch en date locale " JJ/MM/AAAA HH:MM " (" - " si absent)."""
    if timestamp is None:
        return "—"
    return datetime.fromtimestamp(float(timestamp)).strftime("%d/%m/%Y %H:%M")


def _fmt_value(value: Any) -> str:
    """Formate une valeur d'audit : " - " si None, flottants sans zeros inutiles."""
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


# Lacune de typage Dash : dash_table est un module non type, son attribut DataTable n'existe pas pour mypy (ignore cible, comme dans les pages).
def history_table(entries: Iterable[Any]) -> dash_table.DataTable:  # type: ignore[name-defined]
    """Tableau LECTURE SEULE du journal d'audit, colonnes francaises.

    Le tri natif est desactive : l'ordre d'affichage est exactement celui
    fourni par l'appelant. Pagination par pages de 15 lignes.

    Args:
        entries: objets exposant ``timestamp`` (epoch, affiche en heure
            locale JJ/MM/AAAA HH:MM), ``iso_week``, ``field``, ``old_value``,
            ``new_value``, ``source`` et ``operator_id``. Lecture par
            ``getattr`` avec defaut (duck-typing volontaire, cf. docstring de
            module) : un attribut manquant s'affiche vide (ou " - " pour les
            dates et valeurs).
    """
    rows = [
        {
            "Date": _fmt_date(getattr(entry, "timestamp", None)),
            "Semaine": str(getattr(entry, "iso_week", "")),
            "Champ": str(getattr(entry, "field", "")),
            "Ancienne valeur": _fmt_value(getattr(entry, "old_value", None)),
            "Nouvelle valeur": _fmt_value(getattr(entry, "new_value", None)),
            "Source": str(getattr(entry, "source", "")),
            "Opérateur": str(getattr(entry, "operator_id", "")),
        }
        for entry in entries
    ]
    return dash_table.DataTable(  # type: ignore[attr-defined]
        id="history-table",
        columns=_HISTORY_COLUMNS,
        data=rows,
        editable=False,
        sort_action="none",
        page_size=15,
        style_cell=_TABLE_STYLE_CELL,
        style_header=_TABLE_STYLE_HEADER,
        style_as_list_view=True,
    )


def kpi_trajectory_figure(
    snapshots: list[tuple[float, float | None]], kpi_path: str, unit: str = ""
) -> go.Figure:
    """Courbe en escalier de la trajectoire d'UN KPI au fil des snapshots.

    Trace en escalier (``line_shape="hv"``) : un KPI garde sa valeur entre
    deux saisies. Le titre est " Trajectoire - {kpi_path} ({unit}) " (l'unite
    est omise si vide).

    Args:
        snapshots: couples ``(timestamp epoch, valeur)`` deja extraits par
            l'appelant pour UN KPI, ordonnes par timestamp croissant.
        kpi_path: chemin du KPI (ex. ``time.lead_time_h``), repris au titre.
        unit: unite d'affichage (axe y et titre), optionnelle.
    """
    label = f"{kpi_path} ({unit})" if unit else kpi_path
    if not snapshots:
        return empty_figure(f"Aucun snapshot KPI pour « {kpi_path} ».")
    fig = go.Figure(
        go.Scatter(
            x=[datetime.fromtimestamp(ts) for ts, _ in snapshots],
            y=[value for _, value in snapshots],
            mode="lines+markers",
            line={"shape": "hv", "color": COLORS["primary"]},
            name=kpi_path,
        )
    )
    fig.update_layout(
        template=_TEMPLATE,
        title={"text": f"Trajectoire — {label}", "font": {"size": 15}},
        xaxis={"title": "Date"},
        yaxis={"title": unit or "Valeur"},
        margin={"l": 50, "r": 20, "t": 50, "b": 40},
        height=320,
    )
    return fig
