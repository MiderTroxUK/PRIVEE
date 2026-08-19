"""Constructeurs de figures Plotly - fonctions pures, testables sans serveur."""

from __future__ import annotations

import functools
from datetime import datetime

import plotly.graph_objects as go

from supplyscore.core import CRITERIA
from supplyscore.domain.models import ArcKind, SupplyArc, SupplyNode, UrgencyState
from supplyscore.mcda.promethee import ResultatPromethee
from supplyscore.web_ui.components.layout import STATUS_FR

_TEMPLATE = "plotly_white"

#: Rouge des noeuds prioritaires (phi > 0) - aligne sur COLORS["alert"] du layout.
_PHI_POSITIF_COLOR = "#b3261e"
#: Gris des noeuds non prioritaires (phi <= 0) - aligne sur les voisins d'explication.
_PHI_NEGATIF_COLOR = "#9aa7b0"

#: Au-dela de ce nombre de noeuds, le DAG bascule en rendu WebGL allege (E14.3) : ``go.Scattergl`` pour les noeuds ET les aretes, etiquettes texte desactivees (hover seulement - Scattergl rend mal le texte), marqueurs de direction ronds (Scattergl ne supporte pas ``marker.angleref``).
SEUIL_WEBGL = 200

#: Position du marqueur de direction le long de l'arete : au 2/3 du chemin fournisseur -> client (proche de la cible, le sens se lit d'un coup d'oeil).
_FRACTION_FLECHE = 2.0 / 3.0

#: Couleur des marqueurs de direction - gris des anciennes fleches d'annotation.
_FLECHE_COLOR = "#9aa7b0"

#: Nom de la trace dediee aux marqueurs de direction (reperable dans les tests).
_NOM_TRACE_SENS = "sens-arcs"


def _fmt(value: float | None, digits: int = 2) -> str:
    """Formate une valeur optionnelle (" - " si None)."""
    return "—" if value is None else f"{value:.{digits}f}"


def empty_figure(message: str) -> go.Figure:
    """Figure vide avec un message central (etat initial d'un graphique)."""
    fig = go.Figure()
    fig.update_layout(
        template=_TEMPLATE,
        xaxis={"visible": False},
        yaxis={"visible": False},
        annotations=[
            {
                "text": message,
                "xref": "paper",
                "yref": "paper",
                "x": 0.5,
                "y": 0.5,
                "showarrow": False,
                "font": {"size": 14, "color": "#6b7a85"},
            }
        ],
        margin={"l": 20, "r": 20, "t": 30, "b": 20},
        height=320,
    )
    return fig


def ahp_weights_figure(weights: list[float]) -> go.Figure:
    """Bar chart horizontal des poids AHP des 4 criteres."""
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


@functools.lru_cache(maxsize=64)
def _positions_par_cle(cle: tuple[tuple[str, int], ...]) -> dict[str, tuple[float, float]]:
    """Positions pour une cle ``((id, rang), ...)`` triee par (rang, id) - memoisees."""
    par_rang: dict[int, list[str]] = {}
    for node_id, rank in cle:
        par_rang.setdefault(rank, []).append(node_id)
    positions: dict[str, tuple[float, float]] = {}
    for rank, group in par_rang.items():
        offset = (len(group) - 1) / 2.0
        for i, node_id in enumerate(group):
            positions[node_id] = (-float(rank), float(i) - offset)
    return positions


def node_positions(nodes: list[SupplyNode]) -> dict[str, tuple[float, float]]:
    """Positions du DAG : x = -rang, y reparti et centre au sein de chaque rang.

    Le calcul est memoise (E14.3) via :func:`_positions_par_cle` sur une cle
    hashable - le tuple des ``(id, rang)`` trie par (rang, id). L'invalidation
    est NATURELLE : tout ajout/retrait de noeud ou changement de rang produit
    une cle differente, donc une nouvelle entree de cache (LRU, 64 graphes).
    NE PAS muter le dictionnaire retourne : c'est le MEME objet qui est rendu
    a chaque hit de cache.
    """
    cle = tuple(sorted(((n.id, n.rank) for n in nodes), key=lambda t: (t[1], t[0])))
    return _positions_par_cle(cle)


def _node_hover(node: SupplyNode) -> str:
    """Texte de survol par defaut : nom, rang, Ud/Ur/A/F/H, statut."""
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
    """Visualisation generique du DAG logistique.

    Les noeuds sont positionnes par rang (x = -rang, clients finaux a droite)
    et colores selon ``color_values``. La direction fournisseur -> client de
    chaque arc nominal est indiquee par un MARQUEUR au 2/3 de l'arete (trace
    dediee ``sens-arcs``) - plus AUCUNE annotation Plotly par arc : O(E)
    annotations rendait le graphe inutilisable a 500+ noeuds (faiblesse #13).
    Les arcs de secours (kind_arc = backup) sont traces a part, en pointilles
    gris clair, SANS marqueur de direction : purement visuels, ils sont
    inertes dans tous les calculs.

    Au-dela de :data:`SEUIL_WEBGL` noeuds, rendu allege : ``go.Scattergl``
    pour toutes les traces, etiquettes texte desactivees (hover seulement)
    et mention " affichage allege " dans la legende.
    """
    if not nodes:
        return empty_figure("Aucun nœud : créez un projet ou générez la démo.")

    ordered = sorted(nodes, key=lambda n: (n.rank, n.id))
    positions = node_positions(ordered)
    nominal_arcs = [a for a in arcs if a.kind_arc != ArcKind.BACKUP]
    backup_arcs = [a for a in arcs if a.kind_arc == ArcKind.BACKUP]
    use_webgl = len(ordered) > SEUIL_WEBGL
    trace_cls: type[go.Scatter] | type[go.Scattergl] = go.Scattergl if use_webgl else go.Scatter

    if color_values is None:
        color_values = [
            n.urgency.adequation if n.urgency.adequation is not None else 50.0 for n in ordered
        ]
    if hover_texts is None:
        hover_texts = [_node_hover(n) for n in ordered]
    if sizes is None:
        sizes = []
        for n in ordered:
            ur = n.urgency.ur if n.urgency.ur is not None else 0.0
            sizes.append(14.0 + 22.0 * min(max(ur, 0.0), 1.5) / 1.5)

    # Arcs nominaux : UNE trace de segments + les points des marqueurs de direction. Chaque arc fournit une paire (point d'orientation invisible a la source, marqueur visible au 2/3 de l'arete) : le point de taille 0 sert de " previous " a marker.angleref pour orienter la fleche.
    taille_fleche = 5.0 if use_webgl else 9.0
    edge_x: list[float | None] = []
    edge_y: list[float | None] = []
    fleche_x: list[float] = []
    fleche_y: list[float] = []
    fleche_tailles: list[float] = []
    for arc in nominal_arcs:
        if arc.source_id not in positions or arc.target_id not in positions:
            continue
        x0, y0 = positions[arc.source_id]
        x1, y1 = positions[arc.target_id]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]
        fleche_x += [x0, x0 + _FRACTION_FLECHE * (x1 - x0)]
        fleche_y += [y0, y0 + _FRACTION_FLECHE * (y1 - y0)]
        fleche_tailles += [0.0, taille_fleche]

    # Arcs de secours : pointilles gris clair, sans fleche (inertes).
    backup_x: list[float | None] = []
    backup_y: list[float | None] = []
    for arc in backup_arcs:
        if arc.source_id not in positions or arc.target_id not in positions:
            continue
        x0, y0 = positions[arc.source_id]
        x1, y1 = positions[arc.target_id]
        backup_x += [x0, x1, None]
        backup_y += [y0, y1, None]

    fig = go.Figure()
    fig.add_trace(
        trace_cls(
            x=edge_x,
            y=edge_y,
            mode="lines",
            line={"width": 1, "color": "#c4ccd2"},
            hoverinfo="skip",
            showlegend=False,
        )
    )
    if backup_x:
        fig.add_trace(
            trace_cls(
                x=backup_x,
                y=backup_y,
                mode="lines",
                line={"width": 1, "color": "#d3dade", "dash": "dash"},
                hoverinfo="text",
                hovertext="Arc de secours (inactif)",
                name="Arc de secours (inactif)",
                showlegend=False,
            )
        )
    node_kwargs: dict = {
        "x": [positions[n.id][0] for n in ordered],
        "y": [positions[n.id][1] for n in ordered],
        "mode": "markers" if use_webgl else "markers+text",
        "hovertext": hover_texts,
        "hoverinfo": "text",
        "marker": {
            "size": sizes,
            "color": color_values,
            "colorscale": colorscale,
            "cmin": cmin,
            "cmax": cmax,
            "showscale": True,
            "colorbar": {"title": colorbar_title, "thickness": 14},
            "line": {"width": 1, "color": "#44525c"},
        },
        "showlegend": False,
    }
    if not use_webgl:  # etiquettes texte uniquement en SVG (Scattergl les rend mal)
        node_kwargs.update(
            text=[n.name for n in ordered],
            textposition="bottom center",
            textfont={"size": 11, "color": "#44525c"},
        )
    fig.add_trace(trace_cls(**node_kwargs))
    if fleche_x:
        if use_webgl:
            # CHOIX DOCUMENTE : Scattergl ne supporte pas marker.angleref - repli sur un marqueur ROND sans rotation, le sens est donne par le survol (" Sens : fournisseur -> client ").
            fig.add_trace(
                go.Scattergl(
                    x=fleche_x,
                    y=fleche_y,
                    mode="markers",
                    marker={"symbol": "circle", "size": fleche_tailles, "color": _FLECHE_COLOR},
                    hovertext="Sens : fournisseur → client",
                    hoverinfo="text",
                    name=_NOM_TRACE_SENS,
                    showlegend=False,
                )
            )
        else:
            # marker.angleref="previous" (Plotly >= 5.11, verifie sur 6.7) : la fleche est orientee selon le segment depuis le point precedent de la trace (le point invisible pose a la source de l'arc). hoverinfo="skip" : sinon les points d'orientation invisibles captureraient le survol au beau milieu des noeuds.
            fig.add_trace(
                go.Scatter(
                    x=fleche_x,
                    y=fleche_y,
                    mode="markers",
                    marker={
                        "symbol": "arrow",
                        "angleref": "previous",
                        "size": fleche_tailles,
                        "color": _FLECHE_COLOR,
                    },
                    hoverinfo="skip",
                    name=_NOM_TRACE_SENS,
                    showlegend=False,
                )
            )
    if use_webgl:
        mention = f"affichage allégé (>{SEUIL_WEBGL} nœuds)"
        caption = f"{caption} · {mention}" if caption else mention
    annotations = []
    if caption:
        annotations.append(
            {
                "text": caption,
                "xref": "paper",
                "yref": "paper",
                "x": 0.0,
                "y": 1.08,
                "showarrow": False,
                "font": {"size": 12, "color": "#6b7a85"},
                "align": "left",
            }
        )
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


#: Legendes du DAG du dashboard, coherentes avec la palette choisie (Lot 16.2) : la description des couleurs extremes suit la colorscale reellement rendue.
_DAG_CAPTIONS: dict[str, str] = {
    "RdYlGn": "Couleur : adéquation A (0 = rouge, 100 = vert) · Taille : urgence réelle Ur",
    "RdYlBu": "Couleur : adéquation A (0 = rouge, 100 = bleu) · Taille : urgence réelle Ur",
    "Viridis": "Couleur : adéquation A (0 = violet, 100 = jaune) · Taille : urgence réelle Ur",
}


def dashboard_dag_figure(
    nodes: list[SupplyNode], arcs: list[SupplyArc], colorscale: str = "RdYlGn"
) -> go.Figure:
    """DAG du dashboard : couleur = adequation A, taille = Ur.

    Args:
        nodes: noeuds a tracer.
        arcs: arcs du graphe (nominaux et secours).
        colorscale: palette Plotly de l'adequation - " RdYlGn " (defaut),
            " RdYlBu " (lisible pour les daltoniens) ou " Viridis " ; la
            legende suit la palette (:data:`_DAG_CAPTIONS`, repli neutre
            pour une palette inconnue).
    """
    caption = _DAG_CAPTIONS.get(
        colorscale,
        "Couleur : adéquation A (0 = faible, 100 = bonne) · Taille : urgence réelle Ur",
    )
    return dag_figure(
        nodes,
        arcs,
        colorscale=colorscale,
        cmin=0.0,
        cmax=100.0,
        colorbar_title="A",
        title="Chaîne logistique — adéquation par nœud",
        caption=caption,
    )


def shock_dag_figure(
    nodes: list[SupplyNode], arcs: list[SupplyArc], deltas: dict[str, float]
) -> go.Figure:
    """DAG de simulation : couleur = DeltaUr propage (blanc -> rouge)."""
    ordered = sorted(nodes, key=lambda n: (n.rank, n.id))
    values = [deltas.get(n.id, 0.0) for n in ordered]
    bound = max((abs(v) for v in values), default=0.0) or 0.01
    hovers = [
        f"<b>{n.name}</b><br>Rang : {n.rank}<br>ΔUr : {deltas.get(n.id, 0.0):+.3f}" for n in ordered
    ]
    return dag_figure(
        ordered,
        arcs,
        color_values=values,
        hover_texts=hovers,
        sizes=[18.0] * len(ordered),
        colorscale="RdBu_r",
        cmin=-bound,
        cmax=bound,
        colorbar_title="ΔUr",
        title="Propagation du choc sur la chaîne",
        caption="Couleur : variation d'urgence réelle ΔUr (rouge = aggravation)",
    )


def urgency_history_figure(series: list[UrgencyState], node_name: str) -> go.Figure:
    """Evolution temporelle Ud / Ur (axe gauche) et A (axe droit, 0..100)."""
    if not series:
        return empty_figure(f"Aucun historique d'urgence pour « {node_name} ».")
    x = [datetime.fromtimestamp(s.timestamp) for s in series]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=x,
            y=[s.ud for s in series],
            name="Ud (déclarée)",
            mode="lines+markers",
            line={"color": "#2c5f7c"},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=[s.ur for s in series],
            name="Ur (réelle)",
            mode="lines+markers",
            line={"color": "#b3261e"},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=[s.adequation for s in series],
            name="A (adéquation)",
            mode="lines+markers",
            yaxis="y2",
            line={"color": "#1d7a3e", "dash": "dot"},
        )
    )
    fig.update_layout(
        template=_TEMPLATE,
        title={"text": f"Évolution temporelle — {node_name}", "font": {"size": 15}},
        xaxis={"title": "Date"},
        yaxis={"title": "Urgence (Ud, Ur)", "range": [0, 1.05]},
        yaxis2={"title": "Adéquation A", "overlaying": "y", "side": "right", "range": [0, 105]},
        legend={"orientation": "h", "y": -0.25},
        margin={"l": 50, "r": 50, "t": 50, "b": 40},
        height=380,
    )
    return fig


def promethee_bars_figure(
    resultat: ResultatPromethee, names: dict[str, str], top: int = 10
) -> go.Figure:
    """Barres horizontales des flux nets phi PROMETHEE II, triees par phi decroissant.

    Seuls les ``top`` premiers noeuds du classement sont traces (le classement
    de :class:`ResultatPromethee` est deja trie par phi decroissant), le plus
    prioritaire en HAUT (axe y inverse). Couleur : rouge si phi > 0 (le noeud
    domine en moyenne, a traiter en premier), gris sinon. Le survol detaille
    les flux sortant et entrant (" phi+ = ... ; phi- = ... ").

    Args:
        resultat: classement PROMETHEE II complet (phi, phi^+, phi^-, classement).
        names: noms d'affichage par identifiant de noeud (repli : l'id).
        top: nombre maximal de barres tracees.

    Returns:
        Figure a barres horizontales, ou figure vide avec message si le
        classement compte moins de 2 noeuds.
    """
    if len(resultat.classement) < 2:
        return empty_figure(
            "Classement PROMETHEE II indisponible : au moins 2 nœuds actifs requis."
        )
    retenus = resultat.classement[:top]
    labels = [names.get(node_id, node_id) for node_id in retenus]
    phis = [resultat.phi[node_id] for node_id in retenus]
    hovers = [
        f"<b>{label}</b><br>φ = {resultat.phi[node_id]:+.3f}<br>"
        f"φ+ = {resultat.phi_plus[node_id]:.3f} ; φ− = {resultat.phi_moins[node_id]:.3f}"
        for node_id, label in zip(retenus, labels, strict=True)
    ]
    fig = go.Figure(
        go.Bar(
            x=phis,
            y=labels,
            orientation="h",
            marker_color=[_PHI_POSITIF_COLOR if phi > 0.0 else _PHI_NEGATIF_COLOR for phi in phis],
            text=[f"{phi:+.3f}" for phi in phis],
            textposition="outside",
            hovertext=hovers,
            hoverinfo="text",
        )
    )
    fig.update_layout(
        template=_TEMPLATE,
        title={
            "text": "Priorités PROMETHEE II — nœuds à traiter en premier",
            "font": {"size": 15},
        },
        xaxis={"title": "Flux net φ (rouge : φ > 0, prioritaire)"},
        yaxis={"autorange": "reversed"},
        margin={"l": 10, "r": 50, "t": 50, "b": 40},
        height=max(260, 90 + 38 * len(retenus)),
    )
    return fig


def correlation_heatmap_figure(matrix: list[list[float]], labels: list[str]) -> go.Figure:
    """Heatmap de correlation de Pearson des blocs d'urgence (diagnostic PROMETHEE).

    Echelle divergente RdBu bornee sur [-1, 1], valeurs rho annotees dans les
    cases. La diagonale vaut 1 par construction ; une forte correlation hors
    diagonale signale une information double-comptee par PROMETHEE.

    Args:
        matrix: matrice carree symetrique des correlations rho  dans  [-1, 1].
        labels: libelles des blocs, dans l'ordre des lignes/colonnes.

    Returns:
        Figure heatmap annotee, ou figure vide avec message si la matrice
        est vide.
    """
    if not matrix:
        return empty_figure("Corrélation indisponible : aucun bloc d'urgence calculable.")
    fig = go.Figure(
        go.Heatmap(
            z=matrix,
            x=labels,
            y=labels,
            colorscale="RdBu",
            zmin=-1.0,
            zmax=1.0,
            text=[[f"{value:.2f}" for value in row] for row in matrix],
            texttemplate="%{text}",
            colorbar={"title": "ρ", "thickness": 14},
            hovertemplate="ρ(%{y}, %{x}) = %{z:.2f}<extra></extra>",
        )
    )
    fig.update_layout(
        template=_TEMPLATE,
        title={"text": "Corrélation des critères (blocs d'Ur)", "font": {"size": 15}},
        yaxis={"autorange": "reversed"},
        margin={"l": 10, "r": 30, "t": 50, "b": 40},
        height=380,
    )
    return fig


def criticite_tornado_figure(points: list, top: int = 15) -> go.Figure:
    """Tornado de criticite : barres horizontales de DeltaUr_final decroissant (Lot 15.4).

    Duck-typing volontaire : tout objet exposant ``node_name``,
    ``delta_ur_final``, ``delta_ur_max`` et ``nb_impactes`` convient (la
    dataclass :class:`~supplyscore.services.criticite.PointCriticite` comme un
    substitut de test) ; un attribut manquant ou None vaut 0 (nom vide).
    Les barres sont triees par ``delta_ur_final`` decroissant (tri stable :
    l'ordre d'entree departage les egalites), le noeud le plus critique en
    HAUT ; le survol detaille la portee du choc (" impacte n noeud(s) ;
    DeltaUr max = ... ") ; rouge degrade - plus le DeltaUr du client final est grand,
    plus la barre est sombre.

    Args:
        points: points de criticite (``ServiceCriticite.top`` ou equivalent).
        top: nombre maximal de barres tracees.

    Returns:
        Figure a barres horizontales, ou figure vide avec message si la
        liste est vide.
    """
    if not points:
        return empty_figure("Criticité indisponible : aucun nœud actif analysé.")

    def _val(point: object, attr: str) -> float:
        valeur = getattr(point, attr, 0.0)
        return float(valeur) if valeur is not None else 0.0

    retenus = sorted(points, key=lambda p: -_val(p, "delta_ur_final"))[: max(0, top)]
    labels = [str(getattr(p, "node_name", "") or "") for p in retenus]
    valeurs = [_val(p, "delta_ur_final") for p in retenus]
    hovers = [
        f"<b>{label}</b><br>impacte {int(_val(p, 'nb_impactes'))} nœud(s) ; "
        f"ΔUr max = {_val(p, 'delta_ur_max'):+.3f}"
        for p, label in zip(retenus, labels, strict=True)
    ]
    borne = max(valeurs, default=0.0) or 0.01
    fig = go.Figure(
        go.Bar(
            x=valeurs,
            y=labels,
            orientation="h",
            marker={"color": valeurs, "colorscale": "Reds", "cmin": 0.0, "cmax": borne},
            text=[f"{v:+.3f}" for v in valeurs],
            textposition="outside",
            hovertext=hovers,
            hoverinfo="text",
        )
    )
    fig.update_layout(
        template=_TEMPLATE,
        title={
            "text": "Criticité systématique — pire choc local par nœud",
            "font": {"size": 15},
        },
        xaxis={"title": "ΔUr du client final si le nœud tombait (ur_local → 1.0)"},
        yaxis={"autorange": "reversed"},
        margin={"l": 10, "r": 50, "t": 50, "b": 40},
        height=max(260, 90 + 38 * len(retenus)),
    )
    return fig


def shock_bar_figure(deltas: dict[str, float], names: dict[str, str]) -> go.Figure:
    """Bar chart des DeltaUr par noeud, ordonne par delta decroissant."""
    if not deltas:
        return empty_figure("Aucun impact propagé.")
    items = sorted(deltas.items(), key=lambda kv: kv[1], reverse=True)
    labels = [names.get(node_id, node_id) for node_id, _ in items]
    values = [v for _, v in items]
    bound = max((abs(v) for v in values), default=0.0) or 0.01
    fig = go.Figure(
        go.Bar(
            x=labels,
            y=values,
            marker={"color": values, "colorscale": "RdBu_r", "cmin": -bound, "cmax": bound},
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
