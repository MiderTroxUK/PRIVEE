"""Figures d'explication - " pourquoi A = 32 " rendu visuel (phase E8, Lot 8.3).

Quatre constructeurs purs (testables sans serveur) consommes par la page
``/node/<id>/explication`` :

- :func:`ur_waterfall_figure` : cascade des contributions des blocs KPI a
  Ur local (parts exactes en espace log-survie, reparties sur Ur_local
  pour l'affichage) ;
- :func:`propagation_bars_figure` : part locale vs parts des voisins
  (fournisseurs en montant, clients en descendant) ;
- :func:`ud_criteria_figure` : contributions additives exactes kappa_j des
  criteres AHP a Ud ;
- :func:`adequation_equation_block` : equation d'adequation instanciee
  chiffree (bloc HTML, pas une figure).

Les entrees sont consommees en duck-typing (attributs ``block``/``u``/
``omega``/``share``/``delta_without``, ``neighbor_name``/``coeff``/
``u_neighbor``/``share``, ``index``/``label``/``weight``/``score``/
``contribution``, ``e_under``/``e_over``/``penalty``/``adequation``/
``lambda_under``/``lambda_over``/``alpha``) : aucun import du moteur
d'explicabilite, les structures restent substituables.
"""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go
from dash import html

from supplyscore.web_ui.components.figures import _TEMPLATE, empty_figure
from supplyscore.web_ui.components.layout import COLORS, FONT_FAMILY

#: Libelles francais des blocs KPI (cf. supplyscore.core.ur_model.BLOCKS).
BLOCK_LABELS_FR: dict[str, str] = {
    "time": "Temps",
    "cap": "Capacité",
    "perf": "Performance (OEE)",
    "risk": "Risque",
    "cost": "Coût",
    "co2": "CO2",
}

#: Couleur de la part locale (distincte des voisins).
_LOCAL_COLOR = COLORS["primary"]
#: Couleur des parts des voisins (fournisseurs ou clients).
_NEIGHBOR_COLOR = "#8fa9bb"
#: Police monospace des equations instanciees.
_MONO_FONT = "Consolas, 'Courier New', monospace"

#: Tolerance d'egalite a 1 pour " part locale = 1 " (urgence entierement locale).
_EPS = 1e-9


def _subtitle_annotation(text: str) -> dict:
    """Annotation de sous-titre (coordonnees papier, sous le titre).

    Args:
        text: texte du sous-titre.

    Returns:
        Dictionnaire d'annotation Plotly pret pour ``layout.annotations``.
    """
    return {
        "text": text,
        "xref": "paper",
        "yref": "paper",
        "x": 0.0,
        "y": 1.10,
        "showarrow": False,
        "font": {"size": 11, "color": COLORS["muted"]},
        "align": "left",
    }


def ur_waterfall_figure(contributions: list, ur_local: float) -> go.Figure:
    """Cascade des contributions des blocs KPI a l'urgence reelle locale.

    Seuls les blocs ACTIFS (share > 0) sont traces, en mesures relatives
    valant ``share x ur_local`` : les parts sont EXACTES en espace
    log-survie, leur repartition sur Ur_local est une approximation
    d'affichage lisible (annotee comme telle en sous-titre). Comme les
    parts somment a 1 sur les blocs actifs, le total final vaut
    exactement ``ur_local``.

    Args:
        contributions: contributions par bloc (duck-typing : attributs
            ``block``, ``u``, ``omega``, ``share``, ``delta_without``).
        ur_local: urgence reelle locale Ur du noeud.

    Returns:
        ``go.Waterfall`` 0 -> blocs actifs -> total Ur local, ou figure
        vide avec message si aucune contribution active.
    """
    active = [c for c in contributions if c.share > 0.0]
    if not active:
        return empty_figure("Aucune contribution de bloc : Ur local n'est pas décomposable ici.")
    labels = [BLOCK_LABELS_FR.get(c.block, c.block) for c in active]
    values = [c.share * ur_local for c in active]
    fig = go.Figure(
        go.Waterfall(
            x=[*labels, "Ur local"],
            y=[*values, ur_local],
            measure=["relative"] * len(active) + ["total"],
            text=[f"{v:.3f}" for v in [*values, ur_local]],
            textposition="outside",
            increasing={"marker": {"color": COLORS["alert"]}},
            decreasing={"marker": {"color": COLORS["ok"]}},
            totals={"marker": {"color": _LOCAL_COLOR}},
            connector={"line": {"color": COLORS["border"], "width": 1}},
        )
    )
    fig.update_layout(
        template=_TEMPLATE,
        title={"text": f"D'où vient Ur local = {ur_local:.3f} ?", "font": {"size": 15}},
        annotations=[
            _subtitle_annotation(
                "Parts exactes en espace log-survie, réparties sur Ur local pour l'affichage."
            )
        ],
        yaxis={"title": "Ur local", "rangemode": "tozero"},
        showlegend=False,
        margin={"l": 50, "r": 20, "t": 75, "b": 40},
        height=360,
    )
    return fig


def propagation_bars_figure(
    part_locale: float, edges: list, *, direction: str = "fournisseurs"
) -> go.Figure:
    """Barres horizontales : part locale vs parts des voisins (en %).

    En montant (``direction="fournisseurs"``), repond a " D'ou vient
    l'urgence reelle ? " avec les coefficients beta des arcs ; en descendant
    (clients), a " Qui tire le besoin declare ? " avec les coefficients gamma.

    Args:
        part_locale: part log-survie de la cause locale (0..1).
        edges: contributions des voisins (duck-typing : attributs
            ``neighbor_name``, ``coeff``, ``u_neighbor``, ``share``).
        direction: ``"fournisseurs"`` (Ur montant) ou ``"clients"``
            (Ud descendant).

    Returns:
        Figure a barres horizontales en % (" Local " en tete, couleur
        distincte), ou figure vide avec message si l'urgence est
        entierement locale (part_locale = 1 et aucun voisin).
    """
    upstream = direction == "fournisseurs"
    if not edges and part_locale >= 1.0 - _EPS:
        return empty_figure(
            "Urgence entièrement locale : aucun fournisseur ne contribue."
            if upstream
            else "Besoin déclaré entièrement local : aucun client ne le tire."
        )
    symbol = "β" if upstream else "γ"
    labels = ["Local"] + [f"{e.neighbor_name} ({symbol}={e.coeff:g})" for e in edges]
    percents = [part_locale * 100.0] + [e.share * 100.0 for e in edges]
    hovers = ["Part de la cause locale"] + [
        f"{e.neighbor_name} : {symbol} = {e.coeff:g}, u voisin = {e.u_neighbor:.3f}" for e in edges
    ]
    fig = go.Figure(
        go.Bar(
            x=percents,
            y=labels,
            orientation="h",
            marker_color=[_LOCAL_COLOR] + [_NEIGHBOR_COLOR] * len(edges),
            text=[f"{p:.1f} %" for p in percents],
            textposition="auto",
            hovertext=hovers,
            hoverinfo="text",
        )
    )
    title = "D'où vient l'urgence réelle ?" if upstream else "Qui tire le besoin déclaré ?"
    fig.update_layout(
        template=_TEMPLATE,
        title={"text": title, "font": {"size": 15}},
        xaxis={"range": [0, 100], "title": "Part (%)"},
        yaxis={"autorange": "reversed"},
        margin={"l": 10, "r": 30, "t": 50, "b": 40},
        height=max(220, 90 + 45 * (1 + len(edges))),
    )
    return fig


def ud_criteria_figure(criteres: list) -> go.Figure:
    """Barres horizontales des contributions kappa_j des criteres AHP a Ud.

    La decomposition est additive exacte : kappa_j = w_j-(s_j - 1)/8 et
    Sigma kappa_j = Ud - la somme est rappelee en annotation " Sigma kappa = Ud ".

    Args:
        criteres: contributions par critere (duck-typing : attributs
            ``index``, ``label``, ``weight``, ``score``, ``contribution``).

    Returns:
        Figure a barres horizontales (une par critere, dans l'ordre des
        indices), ou figure vide avec message si ``criteres`` est vide.
    """
    if not criteres:
        return empty_figure("Aucun critère : Ud n'est pas décomposable.")
    ordered = sorted(criteres, key=lambda c: c.index)
    contribs = [c.contribution for c in ordered]
    total = sum(contribs)
    fig = go.Figure(
        go.Bar(
            x=contribs,
            y=[c.label for c in ordered],
            orientation="h",
            marker_color=_LOCAL_COLOR,
            text=[f"{v:.3f}" for v in contribs],
            textposition="outside",
            hovertext=[
                f"{c.label} : w = {c.weight:.3f}, s = {c.score:g}, κ = {c.contribution:.3f}"
                for c in ordered
            ],
            hoverinfo="text",
        )
    )
    fig.update_layout(
        template=_TEMPLATE,
        title={"text": "Contributions des critères à Ud", "font": {"size": 15}},
        annotations=[
            {
                "text": f"Σ κ = Ud = {total:.3f}",
                "xref": "paper",
                "yref": "paper",
                "x": 0.98,
                "y": 0.02,
                "showarrow": False,
                "font": {"size": 13, "color": COLORS["text"]},
                "align": "right",
            }
        ],
        xaxis={"title": "Contribution κ_j (additive : Σ κ = Ud)", "rangemode": "tozero"},
        yaxis={"autorange": "reversed"},
        margin={"l": 10, "r": 40, "t": 50, "b": 40},
        height=280,
    )
    return fig


def adequation_equation_block(trace: Any) -> html.Div:
    """Bloc HTML francais : equation d'adequation instanciee chiffree.

    Pas une figure - l'adequation n'admet pas de decomposition additive,
    on montre l'equation avec les valeurs du noeud, par exemple :
    " e_sous = [Ur - Ud]+ = 0.31 ; e_sur = 0.00 ; penalite =
    2.25x0.31^0.88 = 0.80 ; A = 100-(e^-0.80 - e^-2.25)/(1 - e^-2.25)
    = 38.4 ", suivie de la phrase de gouvernance (asymetrie
    Kahneman-Tversky).

    Args:
        trace: trace d'adequation (duck-typing : attributs ``e_under``,
            ``e_over``, ``penalty``, ``adequation``, ``lambda_under``,
            ``lambda_over``, ``alpha``).

    Returns:
        ``html.Div`` a trois lignes d'equation monospace et une phrase
        de gouvernance.
    """
    e_under = float(trace.e_under)
    e_over = float(trace.e_over)
    penalty = float(trace.penalty)
    adequation = float(trace.adequation)
    lam_under = float(trace.lambda_under)
    lam_over = float(trace.lambda_over)
    alpha = float(trace.alpha)
    max_penalty = max(lam_under, lam_over)

    terms = []
    if e_under > 0.0:
        terms.append(f"{lam_under:g}×{e_under:.2f}^{alpha:g}")
    if e_over > 0.0:
        terms.append(f"{lam_over:g}×{e_over:.2f}^{alpha:g}")
    penalty_expr = " + ".join(terms) if terms else "0"

    line_errors = f"e_sous = [Ur − Ud]+ = {e_under:.2f} ; e_sur = [Ud − Ur]+ = {e_over:.2f}"
    line_penalty = f"pénalité = {penalty_expr} = {penalty:.2f}"
    line_score = (
        f"A = 100·(e^−{penalty:.2f} − e^−{max_penalty:g})"
        f"/(1 − e^−{max_penalty:g}) = {adequation:.1f}"
    )
    governance = (
        f"La sous-estimation est pénalisée {lam_under / lam_over:g}× plus fort que la "
        "panique : le danger invisible est pire que la fausse urgence "
        "(asymétrie Kahneman-Tversky)."
    )

    eq_style = {
        "fontFamily": _MONO_FONT,
        "fontSize": "14px",
        "color": COLORS["text"],
        "margin": "2px 0",
    }
    return html.Div(
        [
            html.P(line_errors, style=eq_style),
            html.P(line_penalty, style=eq_style),
            html.P(line_score, style=eq_style),
            html.P(
                governance,
                style={
                    "fontFamily": FONT_FAMILY,
                    "fontSize": "13px",
                    "color": COLORS["muted"],
                    "fontStyle": "italic",
                    "margin": "10px 0 0",
                },
            ),
        ],
        style={
            "backgroundColor": COLORS["background"],
            "border": f"1px solid {COLORS['border']}",
            "borderRadius": "6px",
            "padding": "12px 16px",
        },
    )
