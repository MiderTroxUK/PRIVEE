"""Page « /hebdo » : le rituel hebdomadaire guidé en quatre volets (Lot 6.5).

Parcours nominal (budget 15-20 minutes PAR NŒUD, ≤ 12 clics) : choisir un
nœud, puis dérouler les quatre volets de la revue
(:data:`supplyscore.services.weekly.VOLETS`) :

1. **AHP** — sliders PRÉ-REMPLIS depuis la dernière évaluation
   (:func:`saaty_to_bipolar` / :func:`saaty_to_score6`, inverses exactes des
   conversions du questionnaire) ; « Confirmer à l'identique » re-soumet la
   dernière évaluation en un clic ;
2. **KPIs** — tableau de diff semaine passée / valeur courante
   (:meth:`WeeklyReview.kpi_diff`), avec garde-fou anti double comptage : un
   KPI déjà touché par un événement de la semaine porte un avertissement ;
3. **Jalons** — confirmation des jalons actifs, avancement déclaré vs
   THÉORIQUE (:func:`~supplyscore.domain.milestones.theoretical_progress`) ;
4. **Événements & décision** — déclaration calibrée (preview → apply),
   relance des événements ouverts des semaines passées, journal de décision.

Quand les quatre volets sont ✓, « Clôturer la revue » pose ``completed_at``
et affiche la durée. Les callbacks sont des fonctions nommées au niveau
module (testables sans serveur) ; toutes les écritures sont estampillées par
l'opérateur courant (:func:`~supplyscore.web_ui.components.operator.current_operator`)
et datées par l'horloge du PROJET du nœud.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from dash import ALL, Input, Output, State, dcc, html, no_update
from dash.exceptions import PreventUpdate

from supplyscore.core import CONSISTENCY_THRESHOLD, CRITERIA, bipolar_to_saaty, score_6_to_9
from supplyscore.core.clock import iso_week
from supplyscore.domain.constraints import kpi_unit
from supplyscore.domain.events import EVENT_CALIBRATION
from supplyscore.domain.milestones import Milestone, MilestoneStatus, theoretical_progress
from supplyscore.domain.models import AHPAssessment
from supplyscore.services import SupplyScoreService
from supplyscore.services.decisions import Decision, DecisionService
from supplyscore.services.events import ConflictError, EventEngine
from supplyscore.services.weekly import VOLETS, CycleHebdomadaire, KpiRow, WeeklyReview, _lundi
from supplyscore.web_ui import get_service
from supplyscore.web_ui.components.badges import texte_hebdo
from supplyscore.web_ui.components.event_forms import (
    event_param_fields,
    event_type_options,
    events_list,
    impacts_preview_table,
    parse_event_params,
)
from supplyscore.web_ui.components.layout import (
    BUTTON_SECONDARY_STYLE,
    BUTTON_STYLE,
    CARD_STYLE,
    COLORS,
    FONT_FAMILY,
    INPUT_STYLE,
    MSG_ALERT_STYLE,
    MSG_OK_STYLE,
    PAGE_STYLE,
    card,
    labelled,
    node_options,
)
from supplyscore.web_ui.components.operator import current_operator
from supplyscore.web_ui.pages.questionnaire import KPI_FIELDS, PAIRS

#: Titres français des quatre volets, dans l'ordre du déroulé.
VOLET_TITLES: dict[str, str] = {
    "ahp": "Volet 1 — Évaluation AHP",
    "kpis": "Volet 2 — KPIs de la semaine",
    "jalons": "Volet 3 — Jalons",
    "evenements": "Volet 4 — Événements & décision",
}

#: Blocs KPI confirmés par « Rien n'a changé » (préfixes uniques de KPI_FIELDS).
KPI_BLOCKS: list[str] = list(
    dict.fromkeys(path.split(".", 1)[0] for _bloc, fields in KPI_FIELDS for path, _ in fields)
)

#: Champs triangulaires du lead time (mode Monte Carlo E13) affichés au volet 2.
#: POINT D'EXTENSION DOCUMENTÉ : ``KPI_FIELDS`` appartient au questionnaire
#: PARTAGÉ (il pilote aussi l'éditeur, la fiche nœud 360 et le wizard) — ces
#: champs, propres au mode Monte Carlo, sont donc ajoutés LOCALEMENT aux lignes
#: du volet 2, en AVAL de :meth:`WeeklyReview.kpi_diff` (cf. :func:`_mc_kpi_rows`).
#: La saisie réutilise le mécanisme existant tel quel : mêmes ids pattern-matchés
#: ``{"type": "hebdo-kpi"}``, même :func:`kpi_save_callback`, validation par les
#: bornes de ``KPI_CONSTRAINTS`` (domain.constraints).
MC_TRIANGULAR_FIELDS: list[tuple[str, str]] = [
    ("time.lead_time_min_h", "Lead time min — triangulaire MC (h)"),
    ("time.lead_time_mode_h", "Lead time mode — triangulaire MC (h)"),
    ("time.lead_time_max_h", "Lead time max — triangulaire MC (h)"),
]

#: Écart toléré (en points de progression) avant l'alerte rouge « en retard ».
LATE_PROGRESS_MARGIN: float = 0.10

#: Options françaises du dropdown de statut d'un jalon.
_MS_STATUS_OPTIONS: list[dict] = [
    {"label": "Actif", "value": str(MilestoneStatus.ACTIVE)},
    {"label": "Terminé", "value": str(MilestoneStatus.DONE)},
    {"label": "Abandonné", "value": str(MilestoneStatus.ABANDONED)},
]

_PAIR_MARKS = {-8: "-8", -4: "-4", 0: "0", 4: "+4", 8: "+8"}
_PROGRESS_MARKS = {0: "0 %", 25: "25", 50: "50", 75: "75", 100: "100 %"}

# --- Styles locaux (alignés sur layout.py / badges.py) --------------------------------

_MUTED_STYLE = {"fontSize": "13px", "color": COLORS["muted"], "fontFamily": FONT_FAMILY}

_TITLE_STYLE = {"margin": "0 0 2px", "fontSize": "14px", "fontWeight": "600"}

_H4_STYLE = {"margin": "14px 0 6px", "fontSize": "15px", "color": COLORS["primary"]}

_SUMMARY_STYLE = {
    "cursor": "pointer",
    "fontSize": "16px",
    "fontWeight": "600",
    "fontFamily": FONT_FAMILY,
    "color": COLORS["text"],
    "listStylePosition": "inside",
}

_PILL_BASE = {
    "display": "inline-block",
    "padding": "2px 10px",
    "borderRadius": "10px",
    "fontSize": "12px",
    "fontWeight": "600",
    "fontFamily": FONT_FAMILY,
    "whiteSpace": "nowrap",
}

_PILL_OK = {**_PILL_BASE, "backgroundColor": "#e2f2e7", "color": COLORS["ok"]}
_PILL_WARN = {**_PILL_BASE, "backgroundColor": "#f8ecdb", "color": COLORS["warn"]}
_PILL_MUTED = {**_PILL_BASE, "backgroundColor": "#ebeef1", "color": COLORS["muted"]}

_TABLE_STYLE = {"borderCollapse": "collapse", "width": "100%", "fontFamily": FONT_FAMILY}

_TH_STYLE = {
    "textAlign": "left",
    "padding": "6px 10px",
    "fontSize": "13px",
    "backgroundColor": "#eef2f5",
    "color": COLORS["text"],
    "borderBottom": f"2px solid {COLORS['border']}",
}

_TD_STYLE = {
    "textAlign": "left",
    "padding": "6px 10px",
    "fontSize": "13px",
    "borderBottom": f"1px solid {COLORS['border']}",
    "verticalAlign": "top",
}

_KPI_WARN_STYLE = {"fontSize": "12px", "color": COLORS["warn"], "marginTop": "3px"}

_BUTTON_ROW_STYLE = {"marginTop": "14px", "display": "flex", "gap": "10px", "flexWrap": "wrap"}

#: Bandeau d'invitation bleu (état vide : aucun nœud sélectionné, Lot 16.2).
_EMPTY_BANNER_STYLE = {
    "backgroundColor": "#eef4f8",
    "border": f"1px solid {COLORS['primary']}",
    "color": COLORS["primary"],
    "borderRadius": "6px",
    "padding": "10px 14px",
    "margin": "0 0 14px",
    "fontSize": "14px",
    "fontWeight": "600",
    "fontFamily": FONT_FAMILY,
}

#: Compteur de progression du volet 1 (« x/6 paires ajustées », Lot 16.3).
_PAIR_COUNT_STYLE = {
    "fontSize": "13px",
    "fontWeight": "600",
    "color": COLORS["primary"],
    "margin": "0 0 10px",
}


# --- Conversions inverses (Saaty -> UI) ------------------------------------------------


def saaty_to_bipolar(a: float) -> int:
    """Position bipolaire UI [-8, +8] d'un jugement de Saaty (inverse exacte).

    Inverse de :func:`~supplyscore.core.bipolar_to_saaty` :
    ``v = round(a) − 1`` si ``a >= 1``, sinon ``v = −(round(1/a) − 1)``.
    Bijection exacte sur les 17 valeurs de l'échelle bipolaire ; le résultat
    est borné sur [-8, +8] (garde-fou pour un jugement hors échelle).

    Args:
        a: jugement de Saaty dans [1/9, 9].

    Returns:
        La position du curseur bipolaire, entier dans [-8, +8].
    """
    v = round(a) - 1 if a >= 1.0 else -(round(1.0 / a) - 1)
    return max(-8, min(8, v))


def saaty_to_score6(s: float) -> int:
    """Note UI 1..6 (arrondie) d'une note Saaty [1, 9] (inverse de score_6_to_9).

    ``score_6_to_9`` est linéaire (1 → 1, 6 → 9) : l'inverse vaut
    ``v = 1 + (s − 1) · 5/8``, arrondi à l'entier et borné sur [1, 6].

    Args:
        s: note sur l'échelle de Saaty [1, 9].

    Returns:
        La note UI entière dans [1, 6].
    """
    return max(1, min(6, round(1.0 + (s - 1.0) * 5.0 / 8.0)))


def ahp_prefill(service: SupplyScoreService, node_id: str) -> tuple[dict[str, int], dict[str, int]]:
    """Valeurs initiales des sliders AHP depuis la DERNIÈRE évaluation du nœud.

    Sans évaluation précédente, les défauts du questionnaire s'appliquent
    (paires à 0 — importance égale —, notes à 3).

    Args:
        service: façade applicative.
        node_id: identifiant du nœud.

    Returns:
        ``({"i-j": bipolaire}, {"k": note 1..6})`` pour les 6 paires et les
        4 critères.
    """
    pairs = {f"{i}-{j}": 0 for i, j in PAIRS}
    scores = {str(k): 3 for k in range(len(CRITERIA))}
    latest = service.client_db(node_id).latest_assessment(node_id)
    if latest is None:
        return pairs, scores
    for (i, j), saaty in latest.comparisons.items():
        key = f"{i}-{j}"
        if key in pairs:
            pairs[key] = saaty_to_bipolar(saaty)
    for k, s in enumerate(latest.criteria_scores):
        key = str(k)
        if key in scores:
            scores[key] = saaty_to_score6(s)
    return pairs, scores


# --- Petits helpers d'affichage --------------------------------------------------------


def _nombre_fr(valeur: float, decimales: int = 3) -> str:
    """Nombre en notation française (virgule décimale) pour les TEXTES affichés."""
    return f"{valeur:.{decimales}f}".replace(".", ",")


def _fmt_value(value: float | None) -> str:
    """Formate une valeur de KPI : « non renseigné » si None, 4 décimales utiles.

    CHOIX DOCUMENTÉ (Lot 16.2) : notation POINT conservée — la valeur sert
    de ``placeholder`` aux ``dcc.Input`` numériques du volet 2 (la saisie se
    fait en point) et de colonne de comparaison alignée sur ces inputs ; la
    virgule française est réservée aux PHRASES (:func:`_nombre_fr`).
    """
    if value is None:
        return "non renseigné"
    return f"{value:.4g}"


def _fmt_date(ts: float) -> str:
    """Date locale « JJ/MM/AAAA » d'un epoch (« — » si non renseignée)."""
    if ts <= 0:
        return "—"
    return datetime.fromtimestamp(float(ts)).strftime("%d/%m/%Y")


def _check_badge(done: bool) -> html.Span:
    """Pilule d'état d'un volet : « ✓ » vert si traité, « à traiter » gris sinon."""
    if done:
        return html.Span("✓", style=_PILL_OK)
    return html.Span("à traiter", style=_PILL_MUTED)


def _progress_badge(status: dict[str, Any]) -> html.Span:
    """Badge « x/4 volets » : vert quand la revue est complète, orange sinon."""
    done, total = status["done"], status["total"]
    return html.Span(f"{done}/{total} volets", style=_PILL_OK if done >= total else _PILL_WARN)


def _volet_badges(status: dict[str, Any]) -> tuple[html.Span, ...]:
    """Les quatre pilules d'état des volets, dans l'ordre de :data:`VOLETS`."""
    return tuple(_check_badge(bool(status["volets"][volet])) for volet in VOLETS)


def _triggered_id() -> Any:
    """Id du composant déclencheur (None hors contexte de requête Dash)."""
    try:  # ctx indisponible hors requête Dash (appel direct en test)
        from dash import ctx

        return ctx.triggered_id
    except Exception:
        return None


def _store_node_id(hebdo_data: Any) -> str:
    """Nœud mémorisé dans ``store-hebdo`` (chaîne vide si aucun)."""
    if isinstance(hebdo_data, dict):
        return str(hebdo_data.get("node_id") or "")
    return ""


def _no_node_msg() -> html.Span:
    """Message d'erreur standard quand aucun nœud n'est sélectionné."""
    return html.Span("Sélectionnez d'abord un nœud à passer en revue.", style=MSG_ALERT_STYLE)


def _bandeau_selection() -> html.Div:
    """Bandeau d'état vide : invite à choisir un nœud pour démarrer la revue."""
    return html.Div("Sélectionnez un nœud pour démarrer la revue.", style=_EMPTY_BANNER_STYLE)


def compte_paires_ajustees(valeurs) -> int:
    """Nombre de paires AJUSTÉES : curseurs à une valeur non nulle (Lot 16.3).

    Fonction PURE (testable sans serveur) : une paire compte dès que son
    curseur bipolaire vaut autre chose que 0 (« importance égale ») ; les
    valeurs manquantes (None) ne comptent pas.

    Args:
        valeurs: valeurs courantes des sliders de paires (ordre quelconque).

    Returns:
        Le nombre de valeurs renseignées et non nulles.
    """
    return sum(1 for v in valeurs if v is not None and v != 0)


def texte_paires_ajustees(valeurs) -> str:
    """Texte du compteur « x/6 paires ajustées » du volet 1.

    Le dénominateur suit les sliders réellement montés (repli sur
    :data:`PAIRS` tant qu'aucun volet n'est rendu).
    """
    valeurs = list(valeurs)
    total = len(valeurs) or len(PAIRS)
    return f"{compte_paires_ajustees(valeurs)}/{total} paires ajustées"


# --- Corps des volets -------------------------------------------------------------------


def _pair_block(i: int, j: int, value: int) -> html.Div:
    """Slider bipolaire (-8..+8) pré-rempli d'une paire de critères."""
    key = f"{i}-{j}"
    return html.Div(
        [
            html.P(f"« {CRITERIA[i]} » vs « {CRITERIA[j]} »", style=_TITLE_STYLE),
            dcc.Slider(
                id={"type": "hebdo-ahp-pair", "index": key},
                min=-8,
                max=8,
                step=1,
                value=value,
                marks=_PAIR_MARKS,
                tooltip={"placement": "bottom"},
            ),
        ],
        style={"marginBottom": "14px"},
    )


def _score_block(k: int, value: int) -> html.Div:
    """Slider de note 1..6 pré-rempli d'un critère."""
    return html.Div(
        [
            html.P(CRITERIA[k], style=_TITLE_STYLE),
            dcc.Slider(
                id={"type": "hebdo-ahp-score", "index": str(k)},
                min=1,
                max=6,
                step=1,
                value=value,
                marks={v: str(v) for v in range(1, 7)},
            ),
        ],
        style={"marginBottom": "14px"},
    )


def _ahp_body(service: SupplyScoreService, node_id: str) -> html.Div:
    """Volet 1 : sliders pré-remplis depuis la dernière évaluation + 2 boutons."""
    pairs, scores = ahp_prefill(service, node_id)
    latest = service.client_db(node_id).latest_assessment(node_id)
    if latest is None:
        intro = html.P(
            "Aucune évaluation précédente : réglez les curseurs puis enregistrez.",
            style=_MUTED_STYLE,
        )
    else:
        intro = html.P(
            f"Pré-rempli depuis la dernière évaluation (semaine {latest.iso_week}, "
            f"Ud = {_nombre_fr(latest.ud)}, opérateur « {latest.operator_id} »).",
            style=_MUTED_STYLE,
        )
    children: list = [
        intro,
        html.H4("Comparaisons par paires", style=_H4_STYLE),
        # Compteur de progression (Lot 16.3), mis à jour LIVE par
        # ahp_pair_count_callback à chaque mouvement de slider.
        html.Div(
            texte_paires_ajustees(pairs[f"{i}-{j}"] for i, j in PAIRS),
            id="hebdo-ahp-pair-count",
            style=_PAIR_COUNT_STYLE,
        ),
    ]
    children += [_pair_block(i, j, pairs[f"{i}-{j}"]) for i, j in PAIRS]
    children.append(html.H4("Notes des critères (1 à 6)", style=_H4_STYLE))
    children += [_score_block(k, scores[str(k)]) for k in range(len(CRITERIA))]
    children.append(
        html.Div(
            [
                html.Button(
                    "Confirmer à l'identique",
                    id="hebdo-ahp-confirm-btn",
                    style=BUTTON_SECONDARY_STYLE,
                    disabled=latest is None,
                ),
                html.Button(
                    "Enregistrer l'évaluation", id="hebdo-ahp-save-btn", style=BUTTON_STYLE
                ),
            ],
            style=_BUTTON_ROW_STYLE,
        )
    )
    return html.Div(children)


def _kpis_touched_this_week(service: SupplyScoreService, node_id: str) -> dict[str, str]:
    """KPIs déjà modifiés par un événement ACTIF de la semaine : chemin -> libellé.

    Garde-fou anti double comptage : seuls les événements non annulés de la
    semaine courante comptent (un événement reverté ne modifie plus rien).
    """
    review = WeeklyReview(service)
    engine = EventEngine(service)
    touched: dict[str, str] = {}
    for event in engine.list_week(node_id, review.week_of(node_id)):
        if event.reverted_at is not None:
            continue
        spec = EVENT_CALIBRATION.get(event.event_type)
        label = spec.label_fr if spec is not None else event.event_type
        for impact in event.impacts:
            touched.setdefault(impact.kpi_path, label)
    return touched


def _mc_kpi_rows(service: SupplyScoreService, node_id: str) -> list[KpiRow]:
    """Lignes du volet 2 pour les champs triangulaires (mode Monte Carlo E13).

    Extension LOCALE de :meth:`WeeklyReview.kpi_diff` (cf. le choix documenté
    sur :data:`MC_TRIANGULAR_FIELDS`), avec les MÊMES règles : valeur
    précédente = dernier snapshot KPI antérieur au lundi 00:00 de la semaine
    courante du projet (``kpis_at``), valeur courante = lecture fraîche du
    registre, unité depuis ``KPI_CONSTRAINTS``.
    """
    node = service.registry.get_node(node_id)
    if node is None:
        return []
    semaine = WeeklyReview(service).week_of(node_id)
    previous_bundle = service.client_db(node_id).kpis_at(node_id, _lundi(semaine).timestamp())
    rows: list[KpiRow] = []
    for path, label in MC_TRIANGULAR_FIELDS:
        bloc, champ = path.split(".", 1)
        current = getattr(getattr(node.kpis, bloc), champ)
        previous = (
            getattr(getattr(previous_bundle, bloc), champ) if previous_bundle is not None else None
        )
        rows.append(
            KpiRow(
                path=path,
                label_fr=label,
                unit=kpi_unit(path),
                previous=previous,
                current=current,
            )
        )
    return rows


def _kpi_body(service: SupplyScoreService, node_id: str) -> html.Div:
    """Volet 2 : tableau de diff KPI + saisie des nouvelles valeurs + 2 boutons.

    Aux champs du questionnaire (:meth:`WeeklyReview.kpi_diff`) s'ajoutent les
    trois champs triangulaires du mode Monte Carlo (:func:`_mc_kpi_rows`).
    """
    review = WeeklyReview(service)
    touched = _kpis_touched_this_week(service, node_id)
    header = html.Thead(
        html.Tr(
            [
                html.Th(title, style=_TH_STYLE)
                for title in (
                    "KPI",
                    "Valeur semaine passée",
                    "Nouvelle valeur (vide = inchangé)",
                    "Unité",
                )
            ]
        )
    )
    body_rows = []
    for row in [*review.kpi_diff(node_id), *_mc_kpi_rows(service, node_id)]:
        input_cell: list = [
            dcc.Input(
                id={"type": "hebdo-kpi", "index": row.path},
                type="number",
                step="any",
                placeholder=_fmt_value(row.current),
                style=INPUT_STYLE,
            )
        ]
        if row.path in touched:
            input_cell.append(
                html.Div(
                    f"Déjà modifié par l'événement {touched[row.path]} cette semaine",
                    style=_KPI_WARN_STYLE,
                )
            )
        body_rows.append(
            html.Tr(
                [
                    html.Td(row.label_fr, style=_TD_STYLE),
                    html.Td(_fmt_value(row.previous), style=_TD_STYLE),
                    html.Td(input_cell, style={**_TD_STYLE, "minWidth": "180px"}),
                    html.Td(row.unit, style=_TD_STYLE),
                ]
            )
        )
    return html.Div(
        [
            html.Table([header, html.Tbody(body_rows)], style=_TABLE_STYLE),
            html.Div(
                [
                    html.Button(
                        "Enregistrer les changements", id="hebdo-kpi-save-btn", style=BUTTON_STYLE
                    ),
                    html.Button(
                        "Rien n'a changé", id="hebdo-kpi-none-btn", style=BUTTON_SECONDARY_STYLE
                    ),
                ],
                style=_BUTTON_ROW_STYLE,
            ),
        ]
    )


def _ms_row(milestone: Milestone, now_ts: float) -> html.Tr:
    """Ligne d'un jalon actif : nom, échéance, statut, progression, théorique."""
    progress_th = theoretical_progress(milestone, now_ts)
    late = milestone.progress < progress_th - LATE_PROGRESS_MARGIN
    th_style = {
        "fontSize": "13px",
        "fontWeight": "600",
        "color": COLORS["alert"] if late else COLORS["muted"],
        "whiteSpace": "nowrap",
    }
    return html.Tr(
        [
            html.Td(milestone.name, style=_TD_STYLE),
            html.Td(_fmt_date(milestone.deadline_ts), style=_TD_STYLE),
            html.Td(
                dcc.Dropdown(
                    id={"type": "hebdo-ms-status", "index": milestone.id},
                    options=_MS_STATUS_OPTIONS,
                    value=str(milestone.status),
                    clearable=False,
                ),
                style={**_TD_STYLE, "minWidth": "150px"},
            ),
            html.Td(
                dcc.Slider(
                    id={"type": "hebdo-ms-progress", "index": milestone.id},
                    min=0,
                    max=100,
                    step=1,
                    value=round(milestone.progress * 100),
                    marks=_PROGRESS_MARKS,
                    tooltip={"placement": "bottom"},
                ),
                style={**_TD_STYLE, "minWidth": "260px"},
            ),
            html.Td(
                html.Span(f"théorique {progress_th * 100:.0f} %", style=th_style), style=_TD_STYLE
            ),
        ]
    )


def _ms_body(service: SupplyScoreService, node_id: str) -> html.Div:
    """Volet 3 : une ligne par jalon ACTIF + bouton « Confirmer les jalons »."""
    node = service.registry.get_node(node_id)
    clock = (
        service.clock_for(node.project_id)
        if node is not None and node.project_id
        else service.clock
    )
    now_ts = clock.now()
    actifs = sorted(
        (
            m
            for m in service.registry.list_milestones(node_id)
            if m.status is MilestoneStatus.ACTIVE
        ),
        key=lambda m: (m.position, m.deadline_ts),
    )
    if actifs:
        header = html.Thead(
            html.Tr(
                [
                    html.Th(title, style=_TH_STYLE)
                    for title in ("Jalon", "Échéance", "Statut", "Avancement déclaré", "Théorique")
                ]
            )
        )
        content: Any = html.Table(
            [header, html.Tbody([_ms_row(m, now_ts) for m in actifs])], style=_TABLE_STYLE
        )
    else:
        content = html.P(
            "Aucun jalon actif pour ce nœud — confirmez pour valider le volet.",
            style=_MUTED_STYLE,
        )
    return html.Div(
        [
            content,
            html.Div(
                html.Button("Confirmer les jalons", id="hebdo-ms-save-btn", style=BUTTON_STYLE),
                style=_BUTTON_ROW_STYLE,
            ),
        ]
    )


def _week_events_children(engine: EventEngine, node_id: str, week: str) -> html.Div:
    """Liste des événements déclarés pendant la semaine courante (annulés inclus)."""
    return events_list(engine.list_week(node_id, week), ctx="ev")


def _open_events_children(engine: EventEngine, node_id: str, week: str) -> Any:
    """Relance des événements OUVERTS des semaines passées (« toujours en cours ? »)."""
    past = [event for event in engine.open_events(node_id) if event.iso_week != week]
    if not past:
        return html.P("Aucun événement ouvert des semaines passées.", style=_MUTED_STYLE)
    return events_list(past, ctx="ev")


def _decisions_children(decisions: list[Decision]) -> Any:
    """Liste des décisions de la semaine, avec leur snapshot de scores."""
    if not decisions:
        return html.P("Aucune décision consignée cette semaine.", style=_MUTED_STYLE)
    items = []
    for decision in decisions:
        snapshot = " · ".join(
            f"{label} {_nombre_fr(value, 2)}"
            for label, value in (
                ("Ud", decision.scores.get("ud")),
                ("Ur", decision.scores.get("ur")),
            )
            if value is not None
        )
        suffix = f" — {snapshot}" if snapshot else ""
        items.append(
            html.Li(
                f"« {decision.description} » — opérateur {decision.operator_id}{suffix}",
                style={"fontSize": "13px", "marginBottom": "4px"},
            )
        )
    return html.Ul(items, style={"paddingLeft": "18px", "margin": "6px 0"})


def _ev_body(service: SupplyScoreService, node_id: str) -> html.Div:
    """Volet 4 : déclaration d'événement, relances, décision de la semaine."""
    review = WeeklyReview(service)
    engine = EventEngine(service)
    week = review.week_of(node_id)
    decisions = DecisionService(service).list_for_node(node_id, week)
    return html.Div(
        [
            html.H4("Déclarer un événement", style=_H4_STYLE),
            labelled(
                "Type d'événement",
                dcc.Dropdown(
                    id="hebdo-ev-type",
                    options=event_type_options(),
                    placeholder="choisir…",
                ),
                width="340px",
            ),
            html.Div(id="hebdo-ev-params"),
            html.Div(
                [
                    html.Button(
                        "Prévisualiser", id="hebdo-ev-preview-btn", style=BUTTON_SECONDARY_STYLE
                    ),
                    html.Button(
                        "Confirmer l'événement", id="hebdo-ev-apply-btn", style=BUTTON_STYLE
                    ),
                ],
                style=_BUTTON_ROW_STYLE,
            ),
            html.Div(id="hebdo-ev-preview", style={"marginTop": "10px"}),
            html.H4("Événements de la semaine", style=_H4_STYLE),
            html.Div(_week_events_children(engine, node_id, week), id="hebdo-ev-week-list"),
            html.H4(
                "Événements ouverts des semaines passées — toujours en cours ?",
                style=_H4_STYLE,
            ),
            html.Div(_open_events_children(engine, node_id, week), id="hebdo-ev-open-list"),
            html.H4("Décision prise cette semaine", style=_H4_STYLE),
            dcc.Textarea(
                id="hebdo-decision-text",
                placeholder=(
                    "ex. doubler le stock de sécurité, qualifier un fournisseur de secours…"
                ),
                style={**INPUT_STYLE, "height": "70px", "maxWidth": "560px"},
            ),
            html.Div(
                [
                    html.Button(
                        "Enregistrer la décision", id="hebdo-decision-btn", style=BUTTON_STYLE
                    ),
                    html.Button(
                        "Aucun événement ni décision",
                        id="hebdo-ev-none-btn",
                        style=BUTTON_SECONDARY_STYLE,
                    ),
                ],
                style=_BUTTON_ROW_STYLE,
            ),
            html.Div(_decisions_children(decisions), id="hebdo-decision-list"),
        ]
    )


# --- Layout -----------------------------------------------------------------------------


def _volet_card(volet: str) -> html.Details:
    """Carte pliante (accordéon) d'un volet : titre + badge ✓ + corps dynamique."""
    body_ids = {
        "ahp": "hebdo-ahp-body",
        "kpis": "hebdo-kpi-body",
        "jalons": "hebdo-ms-body",
        "evenements": "hebdo-ev-body",
    }
    return html.Details(
        [
            html.Summary(
                [
                    html.Span(VOLET_TITLES[volet], style={"marginRight": "10px"}),
                    html.Span(_check_badge(False), id=f"hebdo-volet-check-{volet}"),
                ],
                style=_SUMMARY_STYLE,
            ),
            # dcc.Loading ENVELOPPE le corps : l'id du volet reste posé sur
            # le Div interne (contrat des tests e2e et des callbacks).
            dcc.Loading(
                html.Div(
                    html.P("Sélectionnez un nœud pour démarrer la revue.", style=_MUTED_STYLE),
                    id=body_ids[volet],
                    style={"marginTop": "10px"},
                ),
                type="circle",
                color=COLORS["primary"],
            ),
        ],
        open=True,
        style=CARD_STYLE,
    )


def layout() -> html.Div:
    """Construit la page Revue hebdomadaire (état du service relu à chaque navigation)."""
    service = get_service()
    return html.Div(
        [
            html.H2("Revue hebdomadaire", style={"margin": "6px 0 6px"}),
            html.Div(id="hebdo-project-info", style={"marginBottom": "14px"}),
            card(
                "Nœud en revue",
                [
                    labelled(
                        "Nœud (statut hebdo)",
                        dcc.Dropdown(
                            id="hebdo-node-dd",
                            options=node_options(service.repo.nodes()),
                            placeholder="Choisir un nœud…",
                        ),
                        width="420px",
                    ),
                    html.Div(
                        [
                            html.Span(
                                id="hebdo-week",
                                style={"marginRight": "12px", "fontWeight": "600"},
                            ),
                            html.Span(id="hebdo-progress"),
                        ]
                    ),
                ],
                subtitle=(
                    "Budget : 15 à 20 minutes par nœud — déroulez les quatre volets dans l'ordre."
                ),
            ),
            html.Div(_bandeau_selection(), id="hebdo-empty-banner"),
            *[_volet_card(volet) for volet in VOLETS],
            card(
                "Clôture",
                [
                    html.Button("Clôturer la revue", id="hebdo-complete-btn", style=BUTTON_STYLE),
                ],
                subtitle="Disponible quand les quatre volets sont traités.",
            ),
            html.Div(id="hebdo-msg"),
            dcc.Store(id="store-hebdo", data={"node_id": None}),
        ],
        style=PAGE_STYLE,
    )


# --- Callbacks (fonctions nommées, testables sans serveur) -------------------------------


def project_info_callback(project_data):
    """Bandeau du projet actif (semaine ISO) + statuts hebdo dans le dropdown nœud.

    Même contrat que la page Questionnaire : avec un projet sélectionné, le
    bandeau mentionne la semaine courante de SON horloge et chaque option du
    dropdown porte le statut hebdo du nœud (un seul appel à
    :meth:`CycleHebdomadaire.synthese`).
    """
    service = get_service()
    pid = (project_data or {}).get("project_id")
    if pid:
        nodes = [n for n in service.repo.nodes() if n.project_id == pid]
        name = (project_data or {}).get("name", pid)
        semaine = iso_week(service.clock_for(pid).now())
        info = html.Span(
            f"Projet actif : « {name} » — Semaine {semaine}.",
            style={"color": COLORS["primary"], "fontWeight": "600"},
        )
        etats = CycleHebdomadaire(service).synthese(pid)
        options = []
        for option in node_options(nodes):
            etat = etats.get(option["value"])
            if etat is not None:
                option["label"] += f" — {texte_hebdo(etat.statut, etat.semaines_de_retard)}"
            options.append(option)
        return info, options
    nodes = service.repo.nodes()
    info = html.Span(
        "Aucun projet sélectionné — tous les nœuds du graphe sont listés.",
        style={"color": COLORS["muted"]},
    )
    return info, node_options(nodes)


def empty_banner_callback(node_id):
    """Bandeau d'état vide : visible tant qu'aucun nœud n'est sélectionné."""
    if node_id:
        return None
    return _bandeau_selection()


def ahp_pair_count_callback(pair_values):
    """Compteur LIVE « x/6 paires ajustées » du volet 1 (valeurs ≠ 0)."""
    return texte_paires_ajustees(pair_values or [])


def select_node_callback(node_id):
    """Démarre la revue du nœud choisi et monte les quatre volets.

    Pose ``started_at`` (idempotent, :meth:`WeeklyReview.start`), mémorise le
    nœud dans ``store-hebdo``, rafraîchit le bandeau semaine, le badge x/4 et
    les corps des quatre volets (sliders AHP pré-remplis, diff KPI, jalons
    actifs, événements et décisions de la semaine).
    """
    if not node_id:
        raise PreventUpdate
    service = get_service()
    node = service.registry.get_node(str(node_id))
    if node is None:
        raise PreventUpdate
    review = WeeklyReview(service)
    review.start(node.id)
    status = review.review_status(node.id)
    week = review.week_of(node.id)
    banner = f"Semaine {week} — revue de « {node.name} »."
    return (
        {"node_id": node.id},
        banner,
        _progress_badge(status),
        *_volet_badges(status),
        _ahp_body(service, node.id),
        _kpi_body(service, node.id),
        _ms_body(service, node.id),
        _ev_body(service, node.id),
        "",
    )


def _submit_weekly_assessment(
    service: SupplyScoreService,
    node_id: str,
    assessment: AHPAssessment,
    operator_id: str,
    action: str,
):
    """Soumet l'évaluation, marque le volet AHP et construit la réponse commune.

    Refuse (message rouge, rien n'est écrit) si le ratio de cohérence dépasse
    le seuil de Saaty.
    """
    node = service.registry.get_node(node_id)
    if node is None:
        return _no_node_msg(), no_update, no_update
    if assessment.consistency_ratio >= CONSISTENCY_THRESHOLD:
        return (
            html.Span(
                f"Enregistrement refusé : CR = {_nombre_fr(assessment.consistency_ratio)} "
                f"≥ {_nombre_fr(CONSISTENCY_THRESHOLD, 2)}. "
                "Révisez vos comparaisons par paires.",
                style=MSG_ALERT_STYLE,
            ),
            no_update,
            no_update,
        )
    service.submit_assessment(assessment)
    status = WeeklyReview(service).mark_volet(node_id, "ahp", operator_id)
    message = html.Span(
        f"{action} pour « {node.name} » (Ud = {_nombre_fr(assessment.ud)}) — "
        f"semaine {assessment.iso_week}. Volet AHP traité.",
        style=MSG_OK_STYLE,
    )
    return message, _progress_badge(status), _check_badge(True)


def ahp_confirm_callback(n_clicks, hebdo_data, operator_data):
    """« Confirmer à l'identique » : re-soumet la dernière évaluation telle quelle.

    UN clic : les comparaisons, notes, poids et Ud de la dernière évaluation
    sont re-soumis pour la semaine courante (horloge du projet), estampillés
    par l'opérateur courant, puis le volet AHP est marqué traité.
    """
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    node_id = _store_node_id(hebdo_data)
    if not node_id:
        return _no_node_msg(), no_update, no_update
    latest = service.client_db(node_id).latest_assessment(node_id)
    if latest is None:
        return (
            html.Span(
                "Aucune évaluation précédente à confirmer — utilisez « Enregistrer l'évaluation ».",
                style=MSG_ALERT_STYLE,
            ),
            no_update,
            no_update,
        )
    node = service.registry.get_node(node_id)
    if node is None:
        return _no_node_msg(), no_update, no_update
    # timestamp par défaut (temps réel, comme au questionnaire) : c'est lui qui
    # ordonne latest_assessment ; la SEMAINE, elle, vient de l'horloge du projet
    # (iso_week vide -> posée par submit_assessment).
    assessment = AHPAssessment(
        node_id=node_id,
        project_id=latest.project_id or node.project_id or "",
        operator_id=current_operator(operator_data),
        comparisons=dict(latest.comparisons),
        criteria_scores=list(latest.criteria_scores),
        weights=list(latest.weights),
        consistency_ratio=latest.consistency_ratio,
        is_consistent=latest.is_consistent,
        ud=latest.ud,
        notes="Confirmée à l'identique (revue hebdomadaire).",
        iso_week="",
    )
    return _submit_weekly_assessment(
        service, node_id, assessment, assessment.operator_id, "Évaluation confirmée à l'identique"
    )


def ahp_save_callback(
    n_clicks, hebdo_data, operator_data, pair_values, pair_ids, score_values, score_ids
):
    """« Enregistrer l'évaluation » : soumet les valeurs courantes des sliders.

    Conversions identiques au questionnaire (bipolaire → Saaty, note 1..6 →
    Saaty 1..9), tri par ``id["index"]`` (ordre DOM non garanti), CR ≥ 0.10
    refusé, succès → volet AHP traité.
    """
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    node_id = _store_node_id(hebdo_data)
    if not node_id:
        return _no_node_msg(), no_update, no_update
    node = service.registry.get_node(node_id)
    if node is None:
        return _no_node_msg(), no_update, no_update
    comparisons: dict[tuple[int, int], float] = {}
    for id_, value in zip(pair_ids, pair_values, strict=True):
        i_str, j_str = str(id_["index"]).split("-", 1)
        comparisons[(int(i_str), int(j_str))] = bipolar_to_saaty(int(value or 0))
    ordered = sorted(
        zip(score_ids, score_values, strict=True), key=lambda pair: int(pair[0]["index"])
    )
    scores = [score_6_to_9(float(v if v is not None else 3)) for _, v in ordered]
    operator_id = current_operator(operator_data)
    assessment = SupplyScoreService.build_assessment(
        node_id=node_id,
        project_id=node.project_id or "",
        operator_id=operator_id,
        comparisons=comparisons,
        criteria_scores=scores,
        notes="Revue hebdomadaire.",
    )
    return _submit_weekly_assessment(
        service, node_id, assessment, operator_id, "Évaluation enregistrée"
    )


def kpi_save_callback(n_clicks, hebdo_data, operator_data, kpi_values, kpi_ids):
    """« Enregistrer les changements » : applique les KPIs saisis (vide = inchangé).

    Mutations via ``service.mutations.update_kpis`` (``source="weekly"``),
    réévaluation persistée du réseau, puis volet KPIs marqué traité. Une
    valeur invalide refuse TOUT le lot (message rouge, rien n'est écrit).
    """
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    node_id = _store_node_id(hebdo_data)
    if not node_id:
        return _no_node_msg(), no_update, no_update
    operator_id = current_operator(operator_data)
    changes: dict[str, float | None] = {}
    pairs = sorted(zip(kpi_ids, kpi_values, strict=True), key=lambda pair: str(pair[0]["index"]))
    for id_, value in pairs:
        if value is None or value == "":
            continue
        changes[str(id_["index"])] = float(value)
    try:
        entries = service.mutations.update_kpis(
            node_id, changes, source="weekly", operator_id=operator_id
        )
    except (KeyError, ValueError) as exc:
        return html.Span(f"KPIs refusés : {exc}", style=MSG_ALERT_STYLE), no_update, no_update
    service.evaluate_all(persist=True)
    status = WeeklyReview(service).mark_volet(node_id, "kpis", operator_id)
    message = html.Span(f"{len(entries)} KPI mis à jour — volet KPIs traité.", style=MSG_OK_STYLE)
    return message, _progress_badge(status), _check_badge(True)


def kpi_none_callback(n_clicks, hebdo_data, operator_data):
    """« Rien n'a changé » : confirme chaque bloc KPI et applique la décroissance.

    Une ligne d'audit ``__confirmed__`` par bloc (:meth:`WeeklyReview.confirm_block`),
    puis décroissance bayésienne « semaine sans incident »
    (:meth:`EventEngine.apply_weekly_decay`), réévaluation persistée et volet
    KPIs marqué traité.
    """
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    node_id = _store_node_id(hebdo_data)
    if not node_id:
        return _no_node_msg(), no_update, no_update
    operator_id = current_operator(operator_data)
    review = WeeklyReview(service)
    try:
        for block in KPI_BLOCKS:
            review.confirm_block(node_id, block, operator_id)
        impacts = EventEngine(service).apply_weekly_decay(node_id, operator_id)
    except (KeyError, ValueError) as exc:
        return (
            html.Span(f"Confirmation refusée : {exc}", style=MSG_ALERT_STYLE),
            no_update,
            no_update,
        )
    service.evaluate_all(persist=True)
    status = review.mark_volet(node_id, "kpis", operator_id)
    message = html.Span(
        f"Blocs KPI confirmés sans changement — décroissance hebdomadaire appliquée "
        f"({len(impacts)} KPI). Volet KPIs traité.",
        style=MSG_OK_STYLE,
    )
    return message, _progress_badge(status), _check_badge(True)


def ms_save_callback(
    n_clicks, hebdo_data, operator_data, status_values, status_ids, progress_values, progress_ids
):
    """« Confirmer les jalons » : audite chaque jalon MODIFIÉ puis marque le volet.

    Les lignes sont triées par ``id["index"]`` ; seuls les jalons dont le
    statut ou l'avancement déclaré (slider 0..100 → [0, 1]) diffère de l'état
    du registre passent par :meth:`WeeklyReview.confirm_milestone`
    (``source="weekly"``). Le corps du volet est re-rendu (théorique à jour).
    """
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    node_id = _store_node_id(hebdo_data)
    if not node_id:
        return _no_node_msg(), no_update, no_update, no_update
    operator_id = current_operator(operator_data)
    statuses = {
        str(id_["index"]): value for id_, value in zip(status_ids, status_values, strict=True)
    }
    progresses = {
        str(id_["index"]): value for id_, value in zip(progress_ids, progress_values, strict=True)
    }
    review = WeeklyReview(service)
    modified = 0
    for ms_id in sorted(set(statuses) | set(progresses)):
        milestone = service.registry.get_milestone(ms_id)
        if milestone is None:
            continue
        declared_status = str(statuses.get(ms_id) or milestone.status)
        raw_progress = progresses.get(ms_id)
        declared_progress = (
            milestone.progress if raw_progress is None else float(raw_progress) / 100.0
        )
        if (
            declared_status == str(milestone.status)
            and abs(declared_progress - milestone.progress) < 1e-9
        ):
            continue
        try:
            review.confirm_milestone(ms_id, declared_status, declared_progress, operator_id)
        except (KeyError, ValueError) as exc:
            return (
                html.Span(f"Jalon refusé : {exc}", style=MSG_ALERT_STYLE),
                no_update,
                no_update,
                no_update,
            )
        modified += 1
    service.evaluate_all(persist=True)
    status = review.mark_volet(node_id, "jalons", operator_id)
    message = html.Span(
        f"Jalons confirmés ({modified} modifié(s)) — volet Jalons traité.", style=MSG_OK_STYLE
    )
    return message, _progress_badge(status), _check_badge(True), _ms_body(service, node_id)


def ev_type_callback(event_type):
    """Régénère les champs de paramètres au changement de type d'événement."""
    if not event_type:
        return html.Div()
    return event_param_fields(str(event_type), ctx="ev")


def ev_preview_callback(n_clicks, hebdo_data, event_type, param_values, param_ids):
    """« Prévisualiser » : impacts calibrés AVANT application (rien n'est écrit)."""
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    node_id = _store_node_id(hebdo_data)
    if not node_id:
        return html.Div("Sélectionnez d'abord un nœud à passer en revue.", style=MSG_ALERT_STYLE)
    if not event_type:
        return html.Div("Choisissez un type d'événement.", style=MSG_ALERT_STYLE)
    params = parse_event_params(param_values, param_ids)
    try:
        impacts = EventEngine(service).preview(node_id, str(event_type), params)
    except (KeyError, ValueError) as exc:
        return html.Div(f"Prévisualisation impossible : {exc}", style=MSG_ALERT_STYLE)
    return impacts_preview_table(impacts)


def ev_apply_callback(n_clicks, hebdo_data, operator_data, event_type, param_values, param_ids):
    """« Confirmer l'événement » : journalise, applique les impacts, marque le volet.

    Passe par :meth:`EventEngine.apply` (journal + mutations
    ``source="event:<id>"`` + réévaluation), rafraîchit les listes
    d'événements et le tableau KPI (garde-fou double comptage à jour).
    """
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    node_id = _store_node_id(hebdo_data)
    if not node_id:
        return _no_node_msg(), no_update, no_update, no_update, no_update, no_update
    if not event_type:
        return (
            html.Span("Choisissez un type d'événement.", style=MSG_ALERT_STYLE),
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
        )
    operator_id = current_operator(operator_data)
    params = parse_event_params(param_values, param_ids)
    engine = EventEngine(service)
    try:
        event = engine.apply(node_id, str(event_type), params, operator_id=operator_id)
    except (KeyError, ValueError) as exc:
        return (
            html.Span(f"Événement refusé : {exc}", style=MSG_ALERT_STYLE),
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
        )
    review = WeeklyReview(service)
    status = review.mark_volet(node_id, "evenements", operator_id)
    spec = EVENT_CALIBRATION.get(event.event_type)
    label = spec.label_fr if spec is not None else event.event_type
    message = html.Span(
        f"Événement « {label} » enregistré ({len(event.impacts)} impact(s)) — "
        f"semaine {event.iso_week}. Volet Événements traité.",
        style=MSG_OK_STYLE,
    )
    week = review.week_of(node_id)
    return (
        message,
        _progress_badge(status),
        _check_badge(True),
        _week_events_children(engine, node_id, week),
        _open_events_children(engine, node_id, week),
        _kpi_body(service, node_id),
    )


def ev_revert_callback(n_clicks_list, hebdo_data):
    """Annule l'événement du bouton cliqué (tout-ou-rien, conflits en français).

    Le :class:`~supplyscore.services.events.ConflictError` du moteur est déjà
    libellé en français (champs réécrits depuis l'événement) : il est affiché
    tel quel, rien n'est restauré.
    """
    triggered = _triggered_id()
    if not isinstance(triggered, dict) or triggered.get("type") != "ev-revert":
        raise PreventUpdate
    if not any(n for n in n_clicks_list if n):
        raise PreventUpdate
    service = get_service()
    node_id = _store_node_id(hebdo_data)
    if not node_id:
        return _no_node_msg(), no_update, no_update, no_update
    engine = EventEngine(service)
    event_id = str(triggered.get("index") or "")
    try:
        engine.revert(event_id, node_id)
    except (KeyError, ValueError, ConflictError) as exc:  # messages français du moteur
        return html.Span(str(exc), style=MSG_ALERT_STYLE), no_update, no_update, no_update
    week = WeeklyReview(service).week_of(node_id)
    message = html.Span("Événement annulé — KPIs restaurés.", style=MSG_OK_STYLE)
    return (
        message,
        _week_events_children(engine, node_id, week),
        _open_events_children(engine, node_id, week),
        _kpi_body(service, node_id),
    )


def decision_callback(n_clicks, hebdo_data, operator_data, text):
    """Consigne la décision de la semaine (snapshot automatique des scores)."""
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    node_id = _store_node_id(hebdo_data)
    if not node_id:
        return _no_node_msg(), no_update, no_update, no_update, no_update
    operator_id = current_operator(operator_data)
    try:
        DecisionService(service).record(node_id, str(text or ""), operator_id)
    except ValueError as exc:
        return (
            html.Span(f"Décision refusée : {exc}", style=MSG_ALERT_STYLE),
            no_update,
            no_update,
            no_update,
            no_update,
        )
    review = WeeklyReview(service)
    status = review.mark_volet(node_id, "evenements", operator_id)
    week = review.week_of(node_id)
    decisions = DecisionService(service).list_for_node(node_id, week)
    message = html.Span(
        "Décision consignée (scores du moment joints) — volet Événements traité.",
        style=MSG_OK_STYLE,
    )
    return message, _progress_badge(status), _check_badge(True), _decisions_children(decisions), ""


def ev_none_callback(n_clicks, hebdo_data, operator_data):
    """« Aucun événement ni décision » : marque le volet Événements traité."""
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    node_id = _store_node_id(hebdo_data)
    if not node_id:
        return _no_node_msg(), no_update, no_update
    operator_id = current_operator(operator_data)
    status = WeeklyReview(service).mark_volet(node_id, "evenements", operator_id)
    message = html.Span(
        "Rien à signaler cette semaine — volet Événements traité.", style=MSG_OK_STYLE
    )
    return message, _progress_badge(status), _check_badge(True)


def complete_callback(n_clicks, hebdo_data):
    """« Clôturer la revue » : exige les quatre volets, affiche la durée.

    L'erreur du service (« Revue hebdomadaire incomplète — volets
    restants : … ») est affichée telle quelle si un volet manque.
    """
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    node_id = _store_node_id(hebdo_data)
    if not node_id:
        return _no_node_msg(), no_update
    review = WeeklyReview(service)
    try:
        status = review.complete(node_id)
    except ValueError as exc:
        return html.Span(str(exc), style=MSG_ALERT_STYLE), no_update
    started = status.get("started_at")
    completed = status.get("completed_at")
    minutes = 0
    if started is not None and completed is not None:
        minutes = max(0, round((completed - started) / 60.0))
    message = html.Span(
        f"Revue clôturée en {minutes} minute(s) — semaine {review.week_of(node_id)}.",
        style=MSG_OK_STYLE,
    )
    return message, _progress_badge(status)


def _anti_double_clic(button_id: str) -> list:
    """Triplet ``running=`` désactivant le bouton pendant le traitement.

    Anti double-clic (Lot 16.3) : ``running=`` est supporté par Dash 4.2 y
    compris en enregistrement différé ``app.callback(...)(fn)`` — le bouton
    déclencheur est ``disabled`` du départ de la requête à sa réponse, et
    chaque action affiche de toute façon son message dans ``hebdo-msg``.
    """
    return [(Output(button_id, "disabled"), True, False)]


def register_callbacks(app) -> None:
    """Enregistre les callbacks de la page Revue hebdomadaire sur l'app Dash."""
    app.callback(
        Output("hebdo-project-info", "children"),
        Output("hebdo-node-dd", "options"),
        Input("store-project", "data"),
    )(project_info_callback)

    app.callback(
        Output("hebdo-empty-banner", "children"),
        Input("hebdo-node-dd", "value"),
    )(empty_banner_callback)

    app.callback(
        Output("hebdo-ahp-pair-count", "children"),
        Input({"type": "hebdo-ahp-pair", "index": ALL}, "value"),
        prevent_initial_call=True,
    )(ahp_pair_count_callback)

    app.callback(
        Output("store-hebdo", "data"),
        Output("hebdo-week", "children"),
        Output("hebdo-progress", "children"),
        Output("hebdo-volet-check-ahp", "children"),
        Output("hebdo-volet-check-kpis", "children"),
        Output("hebdo-volet-check-jalons", "children"),
        Output("hebdo-volet-check-evenements", "children"),
        Output("hebdo-ahp-body", "children"),
        Output("hebdo-kpi-body", "children"),
        Output("hebdo-ms-body", "children"),
        Output("hebdo-ev-body", "children"),
        Output("hebdo-msg", "children"),
        Input("hebdo-node-dd", "value"),
        prevent_initial_call=True,
    )(select_node_callback)

    app.callback(
        Output("hebdo-msg", "children", allow_duplicate=True),
        Output("hebdo-progress", "children", allow_duplicate=True),
        Output("hebdo-volet-check-ahp", "children", allow_duplicate=True),
        Input("hebdo-ahp-confirm-btn", "n_clicks"),
        State("store-hebdo", "data"),
        State("store-operator", "data"),
        prevent_initial_call=True,
        running=_anti_double_clic("hebdo-ahp-confirm-btn"),
    )(ahp_confirm_callback)

    app.callback(
        Output("hebdo-msg", "children", allow_duplicate=True),
        Output("hebdo-progress", "children", allow_duplicate=True),
        Output("hebdo-volet-check-ahp", "children", allow_duplicate=True),
        Input("hebdo-ahp-save-btn", "n_clicks"),
        State("store-hebdo", "data"),
        State("store-operator", "data"),
        State({"type": "hebdo-ahp-pair", "index": ALL}, "value"),
        State({"type": "hebdo-ahp-pair", "index": ALL}, "id"),
        State({"type": "hebdo-ahp-score", "index": ALL}, "value"),
        State({"type": "hebdo-ahp-score", "index": ALL}, "id"),
        prevent_initial_call=True,
        running=_anti_double_clic("hebdo-ahp-save-btn"),
    )(ahp_save_callback)

    app.callback(
        Output("hebdo-msg", "children", allow_duplicate=True),
        Output("hebdo-progress", "children", allow_duplicate=True),
        Output("hebdo-volet-check-kpis", "children", allow_duplicate=True),
        Input("hebdo-kpi-save-btn", "n_clicks"),
        State("store-hebdo", "data"),
        State("store-operator", "data"),
        State({"type": "hebdo-kpi", "index": ALL}, "value"),
        State({"type": "hebdo-kpi", "index": ALL}, "id"),
        prevent_initial_call=True,
        running=_anti_double_clic("hebdo-kpi-save-btn"),
    )(kpi_save_callback)

    app.callback(
        Output("hebdo-msg", "children", allow_duplicate=True),
        Output("hebdo-progress", "children", allow_duplicate=True),
        Output("hebdo-volet-check-kpis", "children", allow_duplicate=True),
        Input("hebdo-kpi-none-btn", "n_clicks"),
        State("store-hebdo", "data"),
        State("store-operator", "data"),
        prevent_initial_call=True,
        running=_anti_double_clic("hebdo-kpi-none-btn"),
    )(kpi_none_callback)

    app.callback(
        Output("hebdo-msg", "children", allow_duplicate=True),
        Output("hebdo-progress", "children", allow_duplicate=True),
        Output("hebdo-volet-check-jalons", "children", allow_duplicate=True),
        Output("hebdo-ms-body", "children", allow_duplicate=True),
        Input("hebdo-ms-save-btn", "n_clicks"),
        State("store-hebdo", "data"),
        State("store-operator", "data"),
        State({"type": "hebdo-ms-status", "index": ALL}, "value"),
        State({"type": "hebdo-ms-status", "index": ALL}, "id"),
        State({"type": "hebdo-ms-progress", "index": ALL}, "value"),
        State({"type": "hebdo-ms-progress", "index": ALL}, "id"),
        prevent_initial_call=True,
        running=_anti_double_clic("hebdo-ms-save-btn"),
    )(ms_save_callback)

    app.callback(
        Output("hebdo-ev-params", "children"),
        Input("hebdo-ev-type", "value"),
        prevent_initial_call=True,
    )(ev_type_callback)

    app.callback(
        Output("hebdo-ev-preview", "children"),
        Input("hebdo-ev-preview-btn", "n_clicks"),
        State("store-hebdo", "data"),
        State("hebdo-ev-type", "value"),
        State({"type": "ev-param", "index": ALL}, "value"),
        State({"type": "ev-param", "index": ALL}, "id"),
        prevent_initial_call=True,
    )(ev_preview_callback)

    app.callback(
        Output("hebdo-msg", "children", allow_duplicate=True),
        Output("hebdo-progress", "children", allow_duplicate=True),
        Output("hebdo-volet-check-evenements", "children", allow_duplicate=True),
        Output("hebdo-ev-week-list", "children", allow_duplicate=True),
        Output("hebdo-ev-open-list", "children", allow_duplicate=True),
        Output("hebdo-kpi-body", "children", allow_duplicate=True),
        Input("hebdo-ev-apply-btn", "n_clicks"),
        State("store-hebdo", "data"),
        State("store-operator", "data"),
        State("hebdo-ev-type", "value"),
        State({"type": "ev-param", "index": ALL}, "value"),
        State({"type": "ev-param", "index": ALL}, "id"),
        prevent_initial_call=True,
        running=_anti_double_clic("hebdo-ev-apply-btn"),
    )(ev_apply_callback)

    app.callback(
        Output("hebdo-msg", "children", allow_duplicate=True),
        Output("hebdo-ev-week-list", "children", allow_duplicate=True),
        Output("hebdo-ev-open-list", "children", allow_duplicate=True),
        Output("hebdo-kpi-body", "children", allow_duplicate=True),
        Input({"type": "ev-revert", "index": ALL}, "n_clicks"),
        State("store-hebdo", "data"),
        prevent_initial_call=True,
    )(ev_revert_callback)

    app.callback(
        Output("hebdo-msg", "children", allow_duplicate=True),
        Output("hebdo-progress", "children", allow_duplicate=True),
        Output("hebdo-volet-check-evenements", "children", allow_duplicate=True),
        Output("hebdo-decision-list", "children"),
        Output("hebdo-decision-text", "value"),
        Input("hebdo-decision-btn", "n_clicks"),
        State("store-hebdo", "data"),
        State("store-operator", "data"),
        State("hebdo-decision-text", "value"),
        prevent_initial_call=True,
        running=_anti_double_clic("hebdo-decision-btn"),
    )(decision_callback)

    app.callback(
        Output("hebdo-msg", "children", allow_duplicate=True),
        Output("hebdo-progress", "children", allow_duplicate=True),
        Output("hebdo-volet-check-evenements", "children", allow_duplicate=True),
        Input("hebdo-ev-none-btn", "n_clicks"),
        State("store-hebdo", "data"),
        State("store-operator", "data"),
        prevent_initial_call=True,
        running=_anti_double_clic("hebdo-ev-none-btn"),
    )(ev_none_callback)

    app.callback(
        Output("hebdo-msg", "children", allow_duplicate=True),
        Output("hebdo-progress", "children", allow_duplicate=True),
        Input("hebdo-complete-btn", "n_clicks"),
        State("store-hebdo", "data"),
        prevent_initial_call=True,
        running=_anti_double_clic("hebdo-complete-btn"),
    )(complete_callback)
