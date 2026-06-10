"""Constructeurs de figures Plotly — fonctions pures, testables sans serveur."""

from __future__ import annotations

from datetime import datetime

import plotly.graph_objects as go

from supplyscore.core import CRITERIA
from supplyscore.domain.models import SupplyArc, SupplyNode, UrgencyState
from supplyscore.web_ui.components.layout import STATUS_FR

_TEMPLATE = "plotly_white"


def _fmt(value: float | None, digits: int = 2) -> str:
    """Formate une valeur optionnelle (« — » si None)."""
    return "—" if value is None else f"{value:.{digits}f}"


def empty_figure(message: str) -> go.Figure:
    """Figure vide avec un message central (état initial d'un graphique)."""
    fig = go.Figure()
    fig.update_layout(
        template=_TEMPLATE,
        xaxis={"visible": False},
        yaxis={"visible": False},
        annotations=[{
            "text": message, "xref": "paper", "yref": "paper",
            "x": 0.5, "y": 0.5, "showarrow": False,
            "font": {"size": 14, "color": "#6b7a85"},
        }],
        margin={"l": 20, "r": 20, "t": 30, "b": 20},
        height=320,
    )
    return fig


def ahp_weights_figure(weights: list[float]) -> go.Figure:
    """Bar chart horizontal des poids AHP des 4 critères."""
    fig = go.Figure(
        go.Bar(
            x=list(weights),
            y=list(CRITERIA),
            orientation="h",
            marker_color="#2c5f7c",
            text=[f"{w:.3f}" for w in weights],
            textposition="outside",
        )
    )
    fig.update_layout(
        template=_TEMPLATE,
        title={"text": "Poids AHP des critères", "font": {"size": 15}},
        xaxis={"range": [0, 1], "title": "Poids (somme = 1)"},
        yaxis={"autorange": "reversed"},
        margin={"l": 10, "r": 30, "t": 45, "b": 35},
        height=260,
    )
    return fig


def node_positions(nodes: list[SupplyNode]) -> dict[str, tuple[float, float]]:
    """Positions du DAG : x = -rang, y réparti et centré au sein de chaque rang."""
    by_rank: dict[int, list[SupplyNode]] = {}
    for node in sorted(nodes, key=lambda n: (n.rank, n.id)):
        by_rank.setdefault(node.rank, []).append(node)
    positions: dict[str, tuple[float, float]] = {}
    for rank, group in by_rank.items():
        offset = (len(group) - 1) / 2.0
        for i, node in enumerate(group):
            positions[node.id] = (-float(rank), float(i) - offset)
    return positions


def _node_hover(node: SupplyNode) -> str:
    """Texte de survol par défaut : nom, rang, Ud/Ur/A/F/H, statut."""
    u = node.urgency
    return (
        f"<b>{node.name}</b><br>"
        f"Rang : {node.rank} — {node.label}<br>"
        f"Statut : {STATUS_FR.get(node.status, str(node.status))}<br>"
        f"Ud : {_fmt(u.ud)} | Ur : {_fmt(u.ur)}<br>"
        f"A : {_fmt(u.adequation, 1)} | F : {_fmt(u.false_urgency)} | "
        f"H : {_fmt(u.hidden_risk)}"
    )


def dag_figure(
    nodes: list[SupplyNode],
    arcs: list[SupplyArc],
    *,
    color_values: list[float] | None = None,
    hover_texts: list[str] | None = None,
    sizes: list[float] | None = None,
    colorscale: str = "RdYlGn",
    cmin: float = 0.0,
    cmax: float = 100.0,
    colorbar_title: str = "A",
    title: str = "Chaîne logistique",
    caption: str = "",
) -> go.Figure:
    """Visualisation générique du DAG logistique.

    Les nœuds sont positionnés par rang (x = -rang, clients finaux à droite),
    colorés selon ``color_values`` et reliés par des flèches fournisseur -> client.
    """
    if not nodes:
        return empty_figure("Aucun nœud : créez un projet ou générez la démo.")

    ordered = sorted(nodes, key=lambda n: (n.rank, n.id))
    positions = node_positions(ordered)

    if color_values is None:
        color_values = [
            n.urgency.adequation if n.urgency.adequation is not None else 50.0
            for n in ordered
        ]
    if hover_texts is None:
        hover_texts = [_node_hover(n) for n in ordered]
    if sizes is None:
        sizes = []
        for n in ordered:
            ur = n.urgency.ur if n.urgency.ur is not None else 0.0
            sizes.append(14.0 + 22.0 * min(max(ur, 0.0), 1.5) / 1.5)

    # Arcs : segments + flèches (annotations en coordonnées data).
    edge_x: list[float | None] = []
    edge_y: list[float | None] = []
    annotations = []
    for arc in arcs:
        if arc.source_id not in positions or arc.target_id not in positions:
            continue
        x0, y0 = positions[arc.source_id]
        x1, y1 = positions[arc.target_id]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]
        annotations.append({
            "x": x1, "y": y1, "ax": x0, "ay": y0,
            "xref": "x", "yref": "y", "axref": "x", "ayref": "y",
            "showarrow": True, "arrowhead": 2, "arrowsize": 1.1,
            "arrowwidth": 1.2, "arrowcolor": "#9aa7b0",
            "standoff": 16, "startstandoff": 12, "opacity": 0.85, "text": "",
        })

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=edge_x, y=edge_y, mode="lines",
            line={"width": 1, "color": "#c4ccd2"},
            hoverinfo="skip", showlegend=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[positions[n.id][0] for n in ordered],
            y=[positions[n.id][1] for n in ordered],
            mode="markers+text",
            text=[n.name for n in ordered],
            textposition="bottom center",
            textfont={"size": 11, "color": "#44525c"},
            hovertext=hover_texts,
            hoverinfo="text",
            marker={
                "size": sizes,
                "color": color_values,
                "colorscale": colorscale,
                "cmin": cmin,
                "cmax": cmax,
                "showscale": True,
                "colorbar": {"title": colorbar_title, "thickness": 14},
                "line": {"width": 1, "color": "#44525c"},
            },
            showlegend=False,
        )
    )
    if caption:
        annotations.append({
            "text": caption, "xref": "paper", "yref": "paper",
            "x": 0.0, "y": 1.08, "showarrow": False,
            "font": {"size": 12, "color": "#6b7a85"}, "align": "left",
        })
    max_rank = max(n.rank for n in ordered)
    fig.update_layout(
        template=_TEMPLATE,
        title={"text": title, "font": {"size": 16}},
        annotations=annotations,
        xaxis={
            "title": "← Fournisseurs profonds … Client final →",
            "tickmode": "array",
            "tickvals": [-r for r in range(max_rank + 1)],
            "ticktext": [f"Rang {r}" for r in range(max_rank + 1)],
            "zeroline": False,
        },
        yaxis={"visible": False},
        margin={"l": 30, "r": 30, "t": 70, "b": 50},
        height=480,
        hovermode="closest",
    )
    return fig


def dashboard_dag_figure(nodes: list[SupplyNode], arcs: list[SupplyArc]) -> go.Figure:
    """DAG du dashboard : couleur = adéquation A (rouge -> vert), taille = Ur."""
    return dag_figure(
        nodes, arcs,
        colorscale="RdYlGn", cmin=0.0, cmax=100.0, colorbar_title="A",
        title="Chaîne logistique — adéquation par nœud",
        caption="Couleur : adéquation A (0 = rouge, 100 = vert) · Taille : urgence réelle Ur",
    )


def shock_dag_figure(
    nodes: list[SupplyNode], arcs: list[SupplyArc], deltas: dict[str, float]
) -> go.Figure:
    """DAG de simulation : couleur = ΔUr propagé (blanc -> rouge)."""
    ordered = sorted(nodes, key=lambda n: (n.rank, n.id))
    values = [deltas.get(n.id, 0.0) for n in ordered]
    bound = max((abs(v) for v in values), default=0.0) or 0.01
    hovers = [
        f"<b>{n.name}</b><br>Rang : {n.rank}<br>ΔUr : {deltas.get(n.id, 0.0):+.3f}"
        for n in ordered
    ]
    return dag_figure(
        ordered, arcs,
        color_values=values, hover_texts=hovers,
        sizes=[18.0] * len(ordered),
        colorscale="RdBu_r", cmin=-bound, cmax=bound, colorbar_title="ΔUr",
        title="Propagation du choc sur la chaîne",
        caption="Couleur : variation d'urgence réelle ΔUr (rouge = aggravation)",
    )


def urgency_history_figure(series: list[UrgencyState], node_name: str) -> go.Figure:
    """Évolution temporelle Ud / Ur (axe gauche) et A (axe droit, 0..100)."""
    if not series:
        return empty_figure(f"Aucun historique d'urgence pour « {node_name} ».")
    x = [datetime.fromtimestamp(s.timestamp) for s in series]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=[s.ud for s in series], name="Ud (déclarée)",
                             mode="lines+markers", line={"color": "#2c5f7c"}))
    fig.add_trace(go.Scatter(x=x, y=[s.ur for s in series], name="Ur (réelle)",
                             mode="lines+markers", line={"color": "#b3261e"}))
    fig.add_trace(go.Scatter(x=x, y=[s.adequation for s in series], name="A (adéquation)",
                             mode="lines+markers", yaxis="y2",
                             line={"color": "#1d7a3e", "dash": "dot"}))
    fig.update_layout(
        template=_TEMPLATE,
        title={"text": f"Évolution temporelle — {node_name}", "font": {"size": 15}},
        xaxis={"title": "Date"},
        yaxis={"title": "Urgence (Ud, Ur)", "range": [0, 1.05]},
        yaxis2={"title": "Adéquation A", "overlaying": "y", "side": "right",
                "range": [0, 105]},
        legend={"orientation": "h", "y": -0.25},
        margin={"l": 50, "r": 50, "t": 50, "b": 40},
        height=380,
    )
    return fig


def shock_bar_figure(deltas: dict[str, float], names: dict[str, str]) -> go.Figure:
    """Bar chart des ΔUr par nœud, ordonné par delta décroissant."""
    if not deltas:
        return empty_figure("Aucun impact propagé.")
    items = sorted(deltas.items(), key=lambda kv: kv[1], reverse=True)
    labels = [names.get(node_id, node_id) for node_id, _ in items]
    values = [v for _, v in items]
    bound = max((abs(v) for v in values), default=0.0) or 0.01
    fig = go.Figure(
        go.Bar(
            x=labels, y=values,
            marker={"color": values, "colorscale": "RdBu_r",
                    "cmin": -bound, "cmax": bound},
            text=[f"{v:+.3f}" for v in values],
            textposition="outside",
        )
    )
    fig.update_layout(
        template=_TEMPLATE,
        title={"text": "ΔUr propagé par nœud (décroissant)", "font": {"size": 15}},
        yaxis={"title": "ΔUr"},
        margin={"l": 40, "r": 20, "t": 50, "b": 80},
        height=380,
    )
    return fig
