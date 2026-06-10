"""Éléments de mise en page partagés : barre de navigation, cartes, styles."""

from __future__ import annotations

from dash import dcc, html

from supplyscore.domain.models import SupplyNode, TaskStatus

#: Libellés français des statuts de tâche.
STATUS_FR: dict[TaskStatus, str] = {
    TaskStatus.ACTIVE: "Active",
    TaskStatus.DONE: "Terminée",
    TaskStatus.ABANDONED: "Abandonnée",
}

FONT_FAMILY = "'Segoe UI', 'Helvetica Neue', Arial, sans-serif"

COLORS = {
    "primary": "#2c5f7c",
    "primary_dark": "#1e4258",
    "background": "#f4f6f8",
    "card": "#ffffff",
    "text": "#22313a",
    "muted": "#6b7a85",
    "ok": "#1d7a3e",
    "warn": "#b06000",
    "alert": "#b3261e",
    "border": "#d8dee3",
}

PAGE_STYLE = {
    "maxWidth": "1100px",
    "margin": "0 auto",
    "padding": "18px 24px 60px",
    "fontFamily": FONT_FAMILY,
    "color": COLORS["text"],
}

CARD_STYLE = {
    "backgroundColor": COLORS["card"],
    "border": f"1px solid {COLORS['border']}",
    "borderRadius": "8px",
    "padding": "16px 20px",
    "marginBottom": "18px",
    "boxShadow": "0 1px 3px rgba(0,0,0,0.06)",
}

BUTTON_STYLE = {
    "backgroundColor": COLORS["primary"],
    "color": "#fff",
    "border": "none",
    "borderRadius": "6px",
    "padding": "8px 16px",
    "cursor": "pointer",
    "fontFamily": FONT_FAMILY,
    "fontSize": "14px",
}

BUTTON_SECONDARY_STYLE = {
    **BUTTON_STYLE,
    "backgroundColor": "#fff",
    "color": COLORS["primary"],
    "border": f"1px solid {COLORS['primary']}",
}

INPUT_STYLE = {
    "padding": "7px 10px",
    "border": f"1px solid {COLORS['border']}",
    "borderRadius": "6px",
    "fontFamily": FONT_FAMILY,
    "fontSize": "14px",
    "width": "100%",
    "boxSizing": "border-box",
}

LABEL_STYLE = {
    "fontSize": "13px",
    "fontWeight": "600",
    "color": COLORS["muted"],
    "marginBottom": "4px",
    "display": "block",
}

MSG_OK_STYLE = {"color": COLORS["ok"], "marginTop": "10px", "fontSize": "14px"}
MSG_WARN_STYLE = {"color": COLORS["warn"], "marginTop": "10px", "fontSize": "14px"}
MSG_ALERT_STYLE = {"color": COLORS["alert"], "marginTop": "10px", "fontSize": "14px"}


def navbar() -> html.Div:
    """Barre de navigation principale (les 4 pages de l'application)."""
    link_style = {
        "color": "#dfe9f0",
        "textDecoration": "none",
        "padding": "6px 14px",
        "borderRadius": "5px",
        "fontSize": "15px",
    }
    return html.Div(
        [
            html.Div(
                [
                    html.Span(
                        "SupplyScore",
                        style={
                            "fontWeight": "700",
                            "fontSize": "18px",
                            "color": "#fff",
                            "marginRight": "28px",
                        },
                    ),
                    dcc.Link("Projets", href="/", style=link_style),
                    dcc.Link("Questionnaire", href="/questionnaire", style=link_style),
                    dcc.Link("Dashboard", href="/dashboard", style=link_style),
                    dcc.Link("Simulation", href="/simulation", style=link_style),
                ],
                style={
                    "maxWidth": "1100px",
                    "margin": "0 auto",
                    "padding": "12px 24px",
                    "display": "flex",
                    "alignItems": "center",
                },
            )
        ],
        style={"backgroundColor": COLORS["primary_dark"], "fontFamily": FONT_FAMILY},
    )


def card(title: str, children: list, subtitle: str | None = None) -> html.Div:
    """Carte standard avec titre (sections homogènes sur toutes les pages)."""
    header: list = [html.H3(title, style={"margin": "0 0 4px", "fontSize": "17px"})]
    if subtitle:
        header.append(
            html.P(subtitle, style={"margin": "0 0 12px", "fontSize": "13px",
                                    "color": COLORS["muted"]})
        )
    else:
        header.append(html.Div(style={"marginBottom": "10px"}))
    return html.Div(header + children, style=CARD_STYLE)


def labelled(label: str, component, width: str = "220px") -> html.Div:
    """Champ de formulaire : libellé au-dessus du composant."""
    return html.Div(
        [html.Label(label, style=LABEL_STYLE), component],
        style={"width": width, "marginRight": "16px", "marginBottom": "12px",
               "display": "inline-block", "verticalAlign": "top"},
    )


def node_option(node: SupplyNode) -> dict:
    """Option de dropdown pour un nœud : « Nom (rang r — label) »."""
    return {"label": f"{node.name} (rang {node.rank} — {node.label})", "value": node.id}


def node_options(nodes: list[SupplyNode]) -> list[dict]:
    """Options de dropdown pour une liste de nœuds, triées par rang puis nom."""
    return [node_option(n) for n in sorted(nodes, key=lambda n: (n.rank, n.name))]
