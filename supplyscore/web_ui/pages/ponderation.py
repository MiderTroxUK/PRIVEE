"""Page " Ponderation " : poids FBWM des 6 blocs KPI de l'urgence reelle Ur.

Questionnaire FBWM (Guo & Zhao 2017) en 2n-3 comparaisons : le decideur
designe le bloc le PLUS important (Meilleur) et le MOINS important (Pire),
puis juge " Meilleur contre chaque autre " et " chaque autre contre le
Pire " sur l'echelle linguistique de :data:`ECHELLE_LINGUISTIQUE`. Un apercu
en direct montre les poids resolus, xi* et le ratio de coherence CR ;
l'enregistrement (par projet, rattache a la semaine ISO de SON horloge)
exige des jugements coherents (CR < :data:`SEUIL_CR`) puis reevalue tous
les scores.

FRONTIERE METHODOLOGIQUE (PLAN.md, E12) : le FBWM pondere les blocs KPI
d'Ur ; l'AHP du questionnaire reste dedie aux 4 criteres du besoin declare
Ud - les deux ponderations ne se melangent jamais.

Convention de saisie alignee sur :func:`resoudre_fbwm` : le jugement a_BW
(Meilleur contre Pire) n'est saisi qu'UNE fois, cote Best->Autres - le
groupe Autres->Pire omet donc le Meilleur ET le Pire.
"""

from __future__ import annotations

import math

import plotly.graph_objects as go
from dash import ALL, Input, Output, State, dcc, html, no_update
from dash.exceptions import PreventUpdate

from supplyscore.core.clock import iso_week
from supplyscore.core.ur_model import BLOCKS
from supplyscore.mcda.fbwm import ECHELLE_LINGUISTIQUE, SEUIL_CR, ResultatFBWM, resoudre_fbwm
from supplyscore.web_ui import get_service
from supplyscore.web_ui.components.explain_figures import BLOCK_LABELS_FR
from supplyscore.web_ui.components.figures import _TEMPLATE, empty_figure
from supplyscore.web_ui.components.layout import (
    BUTTON_SECONDARY_STYLE,
    BUTTON_STYLE,
    COLORS,
    MSG_ALERT_STYLE,
    MSG_OK_STYLE,
    PAGE_STYLE,
    card,
    labelled,
)

#: Libelles francais lisibles des jugements linguistiques de l'echelle FBWM.
JUGEMENTS_FR: dict[str, str] = {
    "egalement_important": "Également important",
    "faiblement_plus_important": "Faiblement plus important",
    "assez_plus_important": "Assez plus important",
    "tres_plus_important": "Très plus important",
    "absolument_plus_important": "Absolument plus important",
}

#: Poids uniformes de repli : 1/6 par bloc (bouton " Revenir aux poids uniformes ").
POIDS_UNIFORMES: dict[str, float] = {bloc: 1.0 / len(BLOCKS) for bloc in BLOCKS}

#: Nombre total de jugements FBWM attendus : 2n-3 (9 pour les 6 blocs).
NB_JUGEMENTS: int = 2 * len(BLOCKS) - 3

#: Badge vert : jugements coherents (CR < SEUIL_CR).
_BADGE_OK_STYLE = {
    "backgroundColor": "#e4f3e9",
    "color": COLORS["ok"],
    "borderRadius": "10px",
    "padding": "4px 12px",
    "fontSize": "13px",
    "fontWeight": "600",
    "display": "inline-block",
    "marginRight": "10px",
}

#: Badge rouge : jugements incoherents ou solveur en echec.
_BADGE_ALERT_STYLE = {**_BADGE_OK_STYLE, "backgroundColor": "#f9e6e4", "color": COLORS["alert"]}

#: Texte secondaire (consignes, rappels de convention).
_MUTED_STYLE = {"fontSize": "13px", "color": COLORS["muted"], "margin": "4px 0 10px"}

#: Message initial de l'apercu, avant toute selection Meilleur/Pire complete.
_MSG_APERCU_VIDE = "Choisissez deux critères distincts (Meilleur et Pire) puis les 2n−3 jugements."


def _nombre_fr(valeur: float, decimales: int = 3) -> str:
    """Nombre en notation francaise (virgule decimale) pour les TEXTES affiches."""
    return f"{valeur:.{decimales}f}".replace(".", ",")


def compte_jugements_saisis(valeurs) -> int:
    """Nombre de jugements renseignes (valeurs non vides) - fonction PURE (Lot 16.3).

    Args:
        valeurs: valeurs des dropdowns de jugement (Best->Autres puis
            Autres->Pire, ordre indifferent).

    Returns:
        Le nombre de valeurs non vides (None et "" ne comptent pas).
    """
    return sum(1 for v in valeurs if v)


def _compteur_jugements(saisis: int) -> html.Div:
    """Indicateur " x/N jugements saisis " affiche sous les dropdowns (Lot 16.3).

    CHOIX DOCUMENTE : le compteur est rendu par ``render_judgments_callback``
    (PAS de callback dedie - le contrat des tests existants fige la page a
    5 callbacks). C'est exact en continu : les dropdowns de jugement sont
    ``clearable=False`` et pre-remplis, leur valeur ne peut jamais redevenir
    vide une fois le groupe rendu.
    """
    return html.Div(
        f"{saisis}/{NB_JUGEMENTS} jugements saisis",
        id="pond-judgment-count",
        style={**_MUTED_STYLE, "fontWeight": "600", "marginTop": "8px"},
    )


def _bloc_options() -> list[dict]:
    """Options de dropdown des 6 blocs KPI (libelles francais, ordre canonique)."""
    return [{"label": BLOCK_LABELS_FR.get(bloc, bloc), "value": bloc} for bloc in BLOCKS]


def _jugement_options() -> list[dict]:
    """Options de dropdown de l'echelle linguistique FBWM (libelles francais)."""
    return [{"label": JUGEMENTS_FR.get(cle, cle), "value": cle} for cle in ECHELLE_LINGUISTIQUE]


def _collecter_jugements(values: list, ids: list) -> dict[str, str] | None:
    """Reconstruit ``{bloc: jugement}`` depuis les dropdowns a id composite.

    Args:
        values: valeurs des dropdowns (pattern-matching ``ALL``).
        ids: ids composites ``{"type": ..., "index": bloc}`` alignes.

    Returns:
        Le dictionnaire des jugements, ou None si une valeur manque.
    """
    jugements: dict[str, str] = {}
    for value, id_ in zip(values, ids, strict=False):
        if not value:
            return None
        jugements[str(id_["index"])] = str(value)
    return jugements


def _resultat_depuis_saisie(
    best: str | None,
    worst: str | None,
    bo_values: list,
    bo_ids: list,
    ow_values: list,
    ow_ids: list,
) -> ResultatFBWM | None:
    """Resout le FBWM depuis l'etat brut des dropdowns de la page.

    Args:
        best: bloc Meilleur selectionne (ou None).
        worst: bloc Pire selectionne (ou None).
        bo_values: valeurs des dropdowns Best->Autres.
        bo_ids: ids composites des dropdowns Best->Autres.
        ow_values: valeurs des dropdowns Autres->Pire.
        ow_ids: ids composites des dropdowns Autres->Pire.

    Returns:
        Le :class:`ResultatFBWM`, ou None si la saisie est incomplete
        (selection manquante, best == worst, jugement vide ou couverture
        partielle des 2n-3 comparaisons).
    """
    if not best or not worst or best == worst:
        return None
    bo = _collecter_jugements(bo_values, bo_ids)
    ow = _collecter_jugements(ow_values, ow_ids)
    if bo is None or ow is None:
        return None
    # Couverture attendue : a_BW saisi UNE fois cote Best->Autres (cf. resoudre_fbwm).
    if set(bo) != set(BLOCKS) - {best} or set(ow) != set(BLOCKS) - {best, worst}:
        return None
    try:
        return resoudre_fbwm(list(BLOCKS), best, worst, bo, ow)
    except ValueError:
        return None


def poids_bars_figure(poids: dict[str, float]) -> go.Figure:
    """Barres horizontales des poids FBWM des blocs (ordre canonique, libelles FR).

    Args:
        poids: poids par nom de bloc (somme = 1).

    Returns:
        Figure Plotly homogene avec les autres barres de poids de l'UI.
    """
    blocs = [bloc for bloc in BLOCKS if bloc in poids]
    values = [poids[bloc] for bloc in blocs]
    fig = go.Figure(
        go.Bar(
            x=values,
            y=[BLOCK_LABELS_FR.get(bloc, bloc) for bloc in blocs],
            orientation="h",
            marker_color=COLORS["primary"],
            text=[f"{v:.3f}" for v in values],
            textposition="outside",
        )
    )
    fig.update_layout(
        template=_TEMPLATE,
        title={"text": "Poids FBWM des blocs d'urgence (Ur)", "font": {"size": 15}},
        xaxis={"range": [0, 1], "title": "Poids (somme = 1)"},
        yaxis={"autorange": "reversed"},
        margin={"l": 10, "r": 30, "t": 45, "b": 35},
        height=300,
    )
    return fig


def _badges_resultat(resultat: ResultatFBWM) -> html.Div:
    """Badges xi*/CR de l'apercu : vert si coherent, rouge sinon.

    Args:
        resultat: sortie du solveur FBWM.

    Returns:
        ``html.Div`` portant le badge de coherence et, si le solveur a
        echoue (``converge=False``), l'avertissement de repli uniforme.
    """
    if not resultat.converge:
        return html.Div(
            html.Span(
                "Solveur en échec — poids uniformes de repli.",
                style=_BADGE_ALERT_STYLE,
            ),
            style={"marginBottom": "8px"},
        )
    mesure = f"ξ* = {_nombre_fr(resultat.xi_star)} — CR = {_nombre_fr(resultat.cr)}"
    if resultat.coherent:
        badge = html.Span(
            f"{mesure} : jugements cohérents (CR < {_nombre_fr(SEUIL_CR, 2)}).",
            style=_BADGE_OK_STYLE,
        )
    else:
        badge = html.Span(
            f"{mesure} : jugements incohérents — révisez.",
            style=_BADGE_ALERT_STYLE,
        )
    return html.Div(badge, style={"marginBottom": "8px"})


def _affichage_poids_actuels(service, project_id) -> html.Div:
    """Ligne " poids actuels du projet " du bandeau pedagogique.

    Args:
        service: service SupplyScore partage.
        project_id: projet actif, ou None/vide.

    Returns:
        ``html.Div`` : poids stockes formates, " uniformes " si aucun poids
        n'est enregistre, ou invite a choisir un projet.
    """
    if not project_id:
        return html.Div(
            "Aucun projet actif : sélectionnez un projet sur la page Projets.",
            style=_MUTED_STYLE,
        )
    poids = service.poids_criteres(project_id)
    if poids is None:
        texte = "Poids actuels du projet : uniformes (aucune pondération enregistrée)."
    else:
        # CHOIX DOCUMENTE (Lot 16.2) : les poids restent en notation POINT, alignes sur les etiquettes des figures de poids (poids_bars_figure) et sur le format contractuel des tests existants de la page.
        detail = " · ".join(
            f"{BLOCK_LABELS_FR.get(bloc, bloc)} {poids[bloc]:.3f}"
            for bloc in BLOCKS
            if bloc in poids
        )
        texte = f"Poids actuels du projet : {detail}."
    return html.Div(texte, style={**_MUTED_STYLE, "fontWeight": "600"})


def layout() -> html.Div:
    """Construit la page " Ponderation des criteres d'urgence (FBWM) "."""
    return html.Div(
        [
            html.H2("Pondération des critères d'urgence (FBWM)", style={"margin": "6px 0 12px"}),
            card(
                "À quoi servent ces poids ?",
                [
                    html.P(
                        html.Strong(
                            "FBWM pondère les 6 BLOCS KPI de l'urgence réelle Ur — "
                            "l'AHP du questionnaire reste dédié aux 4 critères du "
                            "besoin déclaré Ud."
                        ),
                        style={"margin": "0 0 8px", "fontSize": "14px"},
                    ),
                    html.P(
                        "Seulement 2n−3 comparaisons (9 pour 6 blocs) suffisent, là où "
                        "une matrice complète en exigerait 15.",
                        style=_MUTED_STYLE,
                    ),
                    html.Div(id="pond-current-weights"),
                ],
            ),
            card(
                "1. Meilleur et Pire critère",
                [
                    labelled(
                        "Critère le PLUS important",
                        dcc.Dropdown(
                            id="pond-best-dd",
                            options=_bloc_options(),
                            placeholder="Choisir un bloc…",
                        ),
                        width="300px",
                    ),
                    labelled(
                        "Critère le MOINS important",
                        dcc.Dropdown(
                            id="pond-worst-dd",
                            options=_bloc_options(),
                            placeholder="Choisir un bloc…",
                        ),
                        width="300px",
                    ),
                ],
                subtitle="Le FBWM ancre toutes les comparaisons sur ces deux extrêmes.",
            ),
            card(
                "2. Jugements linguistiques (2n−3)",
                [html.Div(id="pond-judgments")],
            ),
            card(
                "3. Aperçu des poids résolus",
                [
                    # dcc.Loading ENVELOPPE l'apercu : les ids internes (badges + figure) restent poses sur les composants.
                    dcc.Loading(
                        [
                            html.Div(id="pond-preview-badges"),
                            dcc.Graph(id="pond-weights-fig", figure=empty_figure(_MSG_APERCU_VIDE)),
                        ],
                        type="circle",
                        color=COLORS["primary"],
                    ),
                ],
                subtitle="L'aperçu se recalcule à chaque jugement modifié — rien n'est persisté.",
            ),
            card(
                "4. Enregistrement (projet actif)",
                [
                    html.Div(
                        [
                            html.Button(
                                "Enregistrer les poids pour ce projet",
                                id="pond-save-btn",
                                style={**BUTTON_STYLE, "marginRight": "10px"},
                            ),
                            html.Button(
                                "Revenir aux poids uniformes",
                                id="pond-reset-btn",
                                style=BUTTON_SECONDARY_STYLE,
                            ),
                        ]
                    ),
                    html.Div(id="pond-save-msg"),
                    html.Div(id="pond-reset-msg"),
                ],
                subtitle=(
                    "L'enregistrement exige des jugements cohérents (CR < 0.10), "
                    "rattache les poids à la semaine ISO du projet et réévalue tous les scores."
                ),
            ),
        ],
        style=PAGE_STYLE,
    )


# Callbacks (fonctions nommees, testables sans serveur)


def current_weights_callback(project_data):
    """Affiche les poids actuellement stockes pour le projet actif."""
    service = get_service()
    pid = (project_data or {}).get("project_id")
    return _affichage_poids_actuels(service, pid)


def render_judgments_callback(best, worst):
    """Rend les 2n-3 dropdowns de jugement une fois Meilleur et Pire choisis.

    Convention alignee sur :func:`resoudre_fbwm` : le groupe Best->Autres
    couvre tous les blocs sauf le Meilleur (le jugement a_BW y est saisi) ;
    le groupe Autres->Pire omet le Meilleur ET le Pire.
    """
    if not best or not worst:
        return html.Div(
            [
                html.P(
                    "Choisissez d'abord le critère le PLUS important et le MOINS important.",
                    style=_MUTED_STYLE,
                ),
                _compteur_jugements(0),
            ]
        )
    if best == worst:
        return html.Div(
            [
                html.P(
                    "Le Meilleur et le Pire doivent être deux critères distincts.",
                    style=MSG_ALERT_STYLE,
                ),
                _compteur_jugements(0),
            ]
        )
    label_best = BLOCK_LABELS_FR.get(best, best)
    label_worst = BLOCK_LABELS_FR.get(worst, worst)
    bo_rows = [
        labelled(
            f"« {label_best} » contre « {BLOCK_LABELS_FR.get(bloc, bloc)} »",
            dcc.Dropdown(
                id={"type": "pond-bo", "index": bloc},
                options=_jugement_options(),
                value="egalement_important",
                clearable=False,
            ),
            width="300px",
        )
        for bloc in BLOCKS
        if bloc != best
    ]
    ow_rows = [
        labelled(
            f"« {BLOCK_LABELS_FR.get(bloc, bloc)} » contre « {label_worst} »",
            dcc.Dropdown(
                id={"type": "pond-ow", "index": bloc},
                options=_jugement_options(),
                value="egalement_important",
                clearable=False,
            ),
            width="300px",
        )
        for bloc in BLOCKS
        if bloc not in (best, worst)
    ]
    return html.Div(
        [
            html.H4(
                f"Le Meilleur ({label_best}) contre les autres",
                style={"margin": "0 0 4px", "fontSize": "15px"},
            ),
            html.Div(bo_rows),
            html.H4(
                f"Les autres contre le Pire ({label_worst})",
                style={"margin": "8px 0 4px", "fontSize": "15px"},
            ),
            html.P(
                "Le jugement « Meilleur contre Pire » n'est saisi qu'une fois, "
                "dans le groupe ci-dessus.",
                style=_MUTED_STYLE,
            ),
            html.Div(ow_rows),
            # Dropdowns non effacables pre-remplis : tous les jugements sont saisis des le rendu du groupe (cf. _compteur_jugements).
            _compteur_jugements(
                compte_jugements_saisis(["egalement_important"] * (len(bo_rows) + len(ow_rows)))
            ),
        ]
    )


def preview_callback(best, worst, bo_values, ow_values, bo_ids, ow_ids):
    """Apercu live : barres des poids resolus + badge xi*/CR."""
    resultat = _resultat_depuis_saisie(best, worst, bo_values, bo_ids, ow_values, ow_ids)
    if resultat is None:
        return empty_figure(_MSG_APERCU_VIDE), html.Div()
    return poids_bars_figure(resultat.poids), _badges_resultat(resultat)


def save_callback(n_clicks, best, worst, bo_values, ow_values, bo_ids, ow_ids, project_data):
    """Persiste les poids FBWM du projet actif (exige coherence CR < 0.10)."""
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    pid = (project_data or {}).get("project_id")
    if not pid:
        return (
            html.Span(
                "Aucun projet actif : sélectionnez d'abord un projet sur la page Projets.",
                style=MSG_ALERT_STYLE,
            ),
            no_update,
        )
    resultat = _resultat_depuis_saisie(best, worst, bo_values, bo_ids, ow_values, ow_ids)
    if resultat is None:
        return (
            html.Span(
                "Saisie incomplète : choisissez deux critères distincts (Meilleur et "
                "Pire) puis renseignez les 2n−3 jugements.",
                style=MSG_ALERT_STYLE,
            ),
            no_update,
        )
    if not resultat.coherent:
        cr_txt = _nombre_fr(resultat.cr) if math.isfinite(resultat.cr) else "∞"
        return (
            html.Span(
                f"Jugements incohérents (CR = {cr_txt} ≥ {_nombre_fr(SEUIL_CR, 2)}) — "
                "révisez vos comparaisons avant d'enregistrer.",
                style=MSG_ALERT_STYLE,
            ),
            no_update,
        )
    service.set_poids_criteres(
        pid, resultat.poids, methode="fbwm", xi_star=resultat.xi_star, iso_week_val=None
    )
    service.evaluate_all(persist=True)
    semaine = iso_week(service.clock_for(pid).now())
    return (
        html.Span(
            f"Poids FBWM enregistrés pour le projet (semaine {semaine}) — scores réévalués.",
            style=MSG_OK_STYLE,
        ),
        _affichage_poids_actuels(service, pid),
    )


def reset_callback(n_clicks, project_data):
    """Retablit les poids uniformes (1/6 par bloc) pour le projet actif."""
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    pid = (project_data or {}).get("project_id")
    if not pid:
        return (
            html.Span(
                "Aucun projet actif : sélectionnez d'abord un projet sur la page Projets.",
                style=MSG_ALERT_STYLE,
            ),
            no_update,
        )
    service.set_poids_criteres(
        pid, dict(POIDS_UNIFORMES), methode="uniforme", xi_star=None, iso_week_val=None
    )
    service.evaluate_all(persist=True)
    semaine = iso_week(service.clock_for(pid).now())
    return (
        html.Span(
            f"Poids uniformes (1/6 par bloc) rétablis (semaine {semaine}) — scores réévalués.",
            style=MSG_OK_STYLE,
        ),
        _affichage_poids_actuels(service, pid),
    )


def register_callbacks(app) -> None:
    """Enregistre les callbacks de la page Ponderation sur l'application Dash."""
    app.callback(
        Output("pond-current-weights", "children"),
        Input("store-project", "data"),
    )(current_weights_callback)

    app.callback(
        Output("pond-judgments", "children"),
        Input("pond-best-dd", "value"),
        Input("pond-worst-dd", "value"),
    )(render_judgments_callback)

    app.callback(
        Output("pond-weights-fig", "figure"),
        Output("pond-preview-badges", "children"),
        Input("pond-best-dd", "value"),
        Input("pond-worst-dd", "value"),
        Input({"type": "pond-bo", "index": ALL}, "value"),
        Input({"type": "pond-ow", "index": ALL}, "value"),
        State({"type": "pond-bo", "index": ALL}, "id"),
        State({"type": "pond-ow", "index": ALL}, "id"),
    )(preview_callback)

    app.callback(
        Output("pond-save-msg", "children"),
        Output("pond-current-weights", "children", allow_duplicate=True),
        Input("pond-save-btn", "n_clicks"),
        State("pond-best-dd", "value"),
        State("pond-worst-dd", "value"),
        State({"type": "pond-bo", "index": ALL}, "value"),
        State({"type": "pond-ow", "index": ALL}, "value"),
        State({"type": "pond-bo", "index": ALL}, "id"),
        State({"type": "pond-ow", "index": ALL}, "id"),
        State("store-project", "data"),
        prevent_initial_call=True,
        # Anti double-clic (Lot 16.3) : running= est supporte par Dash 4.2, y compris en enregistrement differe app.callback(...)(fn) - le bouton est desactive pendant le traitement, et le resultat (succes/refus) s'affiche toujours dans pond-save-msg.
        running=[(Output("pond-save-btn", "disabled"), True, False)],
    )(save_callback)

    app.callback(
        Output("pond-reset-msg", "children"),
        Output("pond-current-weights", "children", allow_duplicate=True),
        Input("pond-reset-btn", "n_clicks"),
        State("store-project", "data"),
        prevent_initial_call=True,
    )(reset_callback)
