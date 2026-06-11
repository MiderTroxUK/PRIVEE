"""Page « Pourquoi ce score ? » — explication d'un nœud (phase E8, Lot 8.4).

La page expose ``layout(node_id)`` et :func:`register_callbacks` ; le routage
``/node/<id>/explication`` et les liens depuis la fiche nœud et le dashboard
sont branchés par la tâche d'intégration E8.I dans ``app.py``.

Principes de conception :

- **Lecture seule, aucun callback** : tout est construit côté serveur à partir
  d'UN appel à :meth:`ExplainService.explain_node` (pur en lecture) —
  :func:`register_callbacks` est volontairement vide ;
- **Bandeau** « Pourquoi A = 38.4 ? » avec la phrase de synthèse
  « A = … parce que le besoin déclaré Ud = … et l'urgence réelle Ur = … » et
  un lien retour vers la fiche ``/node/<id>`` ;
- **Six cartes** dans l'ordre du pipeline : besoin déclaré (critères AHP),
  urgence réelle locale (cascade des blocs KPI, encart rouge si retard
  avéré, ligne « dont glissement de planning » si la modulation u_time est
  non nulle), propagation montante (fournisseurs), propagation descendante
  (clients), équation d'adéquation instanciée, versions liées (audit des
  blocs dominants + événements ouverts) ;
- chaque décomposition absente est remplacée par un message français
  explicite (« Jamais évalué — remplissez le questionnaire. », etc.), la
  page ne lève jamais pour un nœud du graphe.
"""

from __future__ import annotations

from dash import dcc, html

from supplyscore.domain.events import EVENT_CALIBRATION
from supplyscore.services.explain import ExplainService, NodeExplanation
from supplyscore.web_ui import get_service
from supplyscore.web_ui.components.explain_figures import (
    adequation_equation_block,
    propagation_bars_figure,
    ud_criteria_figure,
    ur_waterfall_figure,
)
from supplyscore.web_ui.components.history import history_table
from supplyscore.web_ui.components.layout import COLORS, MSG_ALERT_STYLE, PAGE_STYLE, card

#: Style des messages secondaires (décomposition absente, listes vides).
_MUTED_STYLE = {"color": COLORS["muted"], "margin": "6px 0 2px", "fontSize": "13px"}

#: Encart rouge « Retard avéré » (cause locale unique, pas de décomposition).
_ALERT_BOX_STYLE = {
    "backgroundColor": "#fbeae9",
    "border": f"1px solid {COLORS['alert']}",
    "borderRadius": "6px",
    "padding": "12px 16px",
    "color": COLORS["alert"],
    "fontSize": "14px",
    "fontWeight": "600",
}


# --- Bandeau ----------------------------------------------------------------------------


def _header(node_id: str, exp: NodeExplanation) -> html.Div:
    """Bandeau : titre « Pourquoi A = … ? », phrase de synthèse, lien retour.

    Sans adéquation posée par le pipeline (nœud jamais propagé), le titre
    dégénère en « Pourquoi ce score ? » et la phrase de synthèse est
    remplacée par un message explicite.

    Args:
        node_id: identifiant du nœud (lien retour ``/node/<id>``).
        exp: explication assemblée du nœud.

    Returns:
        Le bandeau de la page.
    """
    if exp.adequation is not None:
        title = f"Pourquoi A = {exp.adequation:.1f} ?"
    else:
        title = "Pourquoi ce score ?"
    if exp.adequation is not None and exp.ud is not None and exp.ur is not None:
        synthese = (
            f"A = {exp.adequation:.1f} parce que le besoin déclaré Ud = {exp.ud:.2f} "
            f"et l'urgence réelle Ur = {exp.ur:.2f}."
        )
    else:
        synthese = (
            "Ce nœud n'a jamais été propagé par le pipeline : "
            "aucun score à expliquer pour l'instant."
        )
    return html.Div(
        [
            html.H2(title, style={"margin": "6px 0 4px"}),
            html.P(
                [html.Strong(exp.node_name), f" — {synthese}"],
                style={"margin": "0 0 8px", "fontSize": "15px"},
            ),
            dcc.Link(
                "← Retour à la fiche nœud",
                href=f"/node/{node_id}",
                style={"color": COLORS["primary"], "fontSize": "14px"},
            ),
        ],
        style={"marginBottom": "18px"},
    )


# --- Cartes -----------------------------------------------------------------------------


def _ud_card(exp: NodeExplanation) -> html.Div:
    """Carte « Le besoin déclaré (Ud) » : critères AHP + dernière évaluation.

    Args:
        exp: explication assemblée du nœud.

    Returns:
        La carte avec la figure des contributions κ_j et la ligne « Dernière
        évaluation : opérateur, semaine, CR », ou le message « Jamais
        évalué — remplissez le questionnaire. » si aucun critère.
    """
    if not exp.criteres:
        return card(
            "Le besoin déclaré (Ud)",
            [html.P("Jamais évalué — remplissez le questionnaire.", style=_MUTED_STYLE)],
        )
    children: list = [dcc.Graph(id="explain-ud-graph", figure=ud_criteria_figure(exp.criteres))]
    evaluation = exp.derniere_evaluation
    if evaluation is not None:
        children.append(
            html.P(
                f"Dernière évaluation : opérateur « {evaluation['operateur']} » — "
                f"semaine {evaluation['semaine']} — CR = {float(evaluation['cr']):.3f}.",
                style=_MUTED_STYLE,
            )
        )
    return card(
        "Le besoin déclaré (Ud)",
        children,
        subtitle="Contributions additives exactes des critères AHP (Σ κ = Ud).",
    )


def _ur_local_card(exp: NodeExplanation, ur_local: float) -> html.Div:
    """Carte « L'urgence réelle locale (Ur_local) » : cascade des blocs KPI.

    En retard avéré (Ur_local effectif saturé à 1), la décomposition
    log-survie n'est pas définie : un encart rouge explique la cause unique
    à la place de la cascade. Sinon, la ligne « dont glissement de
    planning » est ajoutée si la modulation planning de u_time est non
    nulle.

    Args:
        exp: explication assemblée du nœud.
        ur_local: urgence réelle locale du nœud (0.0 si jamais évaluée).

    Returns:
        La carte (encart rouge, ou cascade + ligne de glissement éventuelle).
    """
    if exp.retard_avere:
        encart = html.Div(
            "Retard avéré : l'échéance est dépassée, u_time est forcé à 1 — cause unique.",
            style=_ALERT_BOX_STYLE,
        )
        return card("L'urgence réelle locale (Ur_local)", [encart])
    children: list = [
        dcc.Graph(id="explain-ur-graph", figure=ur_waterfall_figure(exp.blocs, ur_local))
    ]
    trace = exp.u_time_trace
    if (
        trace is not None
        and trace.planning_adjust != 0.0
        and trace.p_th is not None
        and trace.progress is not None
    ):
        children.append(
            html.P(
                f"dont glissement de planning : {trace.planning_adjust:+.2f} "
                f"(déclaré {trace.progress * 100:.0f} % vs théorique {trace.p_th * 100:.0f} %)",
                style=_MUTED_STYLE,
            )
        )
    return card(
        "L'urgence réelle locale (Ur_local)",
        children,
        subtitle="Parts log-survie exactes des blocs KPI, réparties sur Ur local.",
    )


def _fournisseurs_card(exp: NodeExplanation) -> html.Div:
    """Carte « D'où vient l'urgence réelle ? » : part locale vs fournisseurs.

    Args:
        exp: explication assemblée du nœud.

    Returns:
        La carte avec les barres de propagation montante (β des arcs).
    """
    figure = propagation_bars_figure(exp.part_locale_ur, exp.fournisseurs, direction="fournisseurs")
    return card(
        "D'où vient l'urgence réelle ?",
        [dcc.Graph(id="explain-prop-ur-graph", figure=figure)],
        subtitle="Part locale vs parts des fournisseurs directs dans Ur propagé (β des arcs).",
    )


def _clients_card(exp: NodeExplanation) -> html.Div:
    """Carte « Qui tire le besoin déclaré ? » : part locale vs clients.

    Args:
        exp: explication assemblée du nœud.

    Returns:
        La carte avec les barres de propagation descendante (γ des arcs).
    """
    figure = propagation_bars_figure(exp.part_locale_ud, exp.clients, direction="clients")
    return card(
        "Qui tire le besoin déclaré ?",
        [dcc.Graph(id="explain-prop-ud-graph", figure=figure)],
        subtitle="Part locale vs parts des clients directs dans Ud propagé (γ des arcs).",
    )


def _equation_card(exp: NodeExplanation) -> html.Div:
    """Carte « L'équation d'adéquation » : équation instanciée chiffrée.

    Args:
        exp: explication assemblée du nœud.

    Returns:
        La carte avec le bloc d'équation, ou un message si le pipeline n'a
        jamais propagé le nœud (pas d'équation à instancier).
    """
    subtitle = "Le score A tel que le moteur le calcule, avec les valeurs du nœud."
    if exp.adequation_trace is None:
        message = html.P(
            "Jamais propagé par le pipeline — pas d'équation d'adéquation à instancier.",
            style=_MUTED_STYLE,
        )
        return card("L'équation d'adéquation", [message], subtitle=subtitle)
    return card(
        "L'équation d'adéquation",
        [adequation_equation_block(exp.adequation_trace)],
        subtitle=subtitle,
    )


def _event_label(event_type: str) -> str:
    """Libellé français d'un type d'événement (le type brut si inconnu).

    Args:
        event_type: clé de :data:`~supplyscore.domain.events.EVENT_CALIBRATION`.

    Returns:
        Le ``label_fr`` calibré, ou ``event_type`` tel quel à défaut.
    """
    spec = EVENT_CALIBRATION.get(event_type)
    return spec.label_fr if spec is not None else event_type


def _versions_card(exp: NodeExplanation) -> html.Div:
    """Carte « Versions liées » : audit des blocs dominants + événements ouverts.

    Args:
        exp: explication assemblée du nœud.

    Returns:
        La carte avec le journal d'audit (ou un message si vide) et la liste
        des événements ouverts « type — semaine » (ou un message si vide).
    """
    children: list = []
    if exp.audits_recents:
        children.append(history_table(exp.audits_recents))
    else:
        children.append(
            html.P("Aucune modification récente des blocs dominants.", style=_MUTED_STYLE)
        )
    children.append(html.P(html.Strong("Événements ouverts :"), style={"margin": "12px 0 2px"}))
    if exp.evenements_ouverts:
        children.append(
            html.Ul(
                [
                    html.Li(f"{_event_label(e.event_type)} — semaine {e.iso_week}")
                    for e in exp.evenements_ouverts
                ],
                style={"margin": "2px 0", "paddingLeft": "18px"},
            )
        )
    else:
        children.append(html.P("Aucun événement ouvert.", style=_MUTED_STYLE))
    return card(
        "Versions liées",
        children,
        subtitle="Les dernières modifications des blocs dominants et les événements ouverts.",
    )


# --- Layout -----------------------------------------------------------------------------


def layout(node_id: str) -> html.Div:
    """Construit la page d'explication (« Nœud introuvable » si id inconnu).

    Args:
        node_id: identifiant du nœud (segment de l'URL
            ``/node/<id>/explication``).

    Returns:
        L'arbre de la page (bandeau + six cartes), ou un message d'erreur
        sans exception si le nœud est inconnu du graphe.
    """
    service = get_service()
    node = service.repo.get_node(node_id)
    if node is None:
        return html.Div(
            [
                html.H2("Pourquoi ce score ?", style={"margin": "6px 0 6px"}),
                html.P(f"Nœud introuvable : « {node_id} ».", style=MSG_ALERT_STYLE),
            ],
            style=PAGE_STYLE,
        )
    exp = ExplainService(service).explain_node(node_id)
    ur_local = node.urgency.ur_local if node.urgency.ur_local is not None else 0.0
    return html.Div(
        [
            _header(node_id, exp),
            _ud_card(exp),
            _ur_local_card(exp, ur_local),
            _fournisseurs_card(exp),
            _clients_card(exp),
            _equation_card(exp),
            _versions_card(exp),
        ],
        style=PAGE_STYLE,
    )


def register_callbacks(app) -> None:
    """Aucun callback à enregistrer : la page est en LECTURE SEULE.

    Fonction exposée pour homogénéité avec les autres pages — l'intégrateur
    E8.I appelle ``register_callbacks(app)`` sur chaque page au montage des
    routes. Tout est construit côté serveur dans :func:`layout` à partir
    d'un appel pur en lecture à :meth:`ExplainService.explain_node` :
    cette fonction est volontairement vide.

    Args:
        app: application Dash cible (ignorée — aucun callback).
    """
