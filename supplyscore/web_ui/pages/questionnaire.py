"""Page « Questionnaire » : évaluation AHP hebdomadaire + saisie des KPIs.

Les callbacks sont des fonctions nommées au niveau module (enregistrées dans
:func:`register_callbacks`) : la logique de sauvegarde est ainsi testable en
appelant directement :func:`save_assessment_callback`, sans serveur Dash.
"""

from __future__ import annotations

from dash import ALL, MATCH, Input, Output, State, dcc, html
from dash.exceptions import PreventUpdate

from supplyscore.core import (
    CONSISTENCY_THRESHOLD,
    CRITERIA,
    bipolar_to_saaty,
    compute_ud,
    run_ahp,
    score_6_to_9,
)
from supplyscore.services import SupplyScoreService
from supplyscore.web_ui import get_service
from supplyscore.web_ui.components.figures import ahp_weights_figure, empty_figure
from supplyscore.web_ui.components.layout import (
    BUTTON_STYLE,
    COLORS,
    INPUT_STYLE,
    MSG_ALERT_STYLE,
    MSG_OK_STYLE,
    PAGE_STYLE,
    card,
    labelled,
    node_options,
)

#: Les 6 paires (i, j) de comparaison des 4 critères AHP.
PAIRS: list[tuple[int, int]] = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]

#: Champs KPI optionnels saisissables, groupés par bloc d'affichage.
#: Chaque clé "bloc.champ" pointe un attribut de ``KPIBundle``.
KPI_FIELDS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Temps", [
        ("time.lead_time_h", "Lead time (h)"),
        ("time.lead_time_std_h", "Écart-type lead time (h)"),
        ("time.deadline_h", "Échéance / deadline (h)"),
    ]),
    ("Inventaire", [
        ("inventory.max_volume_m3", "Volume max (m³)"),
        ("inventory.current_volume_m3", "Volume actuel (m³)"),
        ("inventory.max_weight_kg", "Poids max (kg)"),
        ("inventory.current_weight_kg", "Poids actuel (kg)"),
        ("inventory.flow_rate", "Débit (unités/h)"),
        ("network.demand", "Demande (unités/h)"),
    ]),
    ("OEE", [
        ("oee.availability", "Disponibilité (0..1)"),
        ("oee.performance", "Performance (0..1)"),
        ("oee.quality", "Qualité (0..1)"),
    ]),
    ("Risque", [
        ("risk.failure_probability", "Probabilité de défaillance (0..1)"),
        ("risk.recovery_time_h", "Temps de récupération (h)"),
        ("risk.severity", "Sévérité (0..1)"),
        ("risk.env_exposure", "Exposition environnementale (0..1)"),
        ("risk.political_risk", "Risque politique (0..1)"),
    ]),
    ("Coût", [
        ("cost.nominal_op_cost", "Coût opérationnel nominal"),
        ("cost.op_cost", "Coût opérationnel courant"),
        ("cost.tariff", "Tarif (multiplicateur)"),
        ("cost.storage_cost", "Coût de stockage"),
    ]),
    ("CO2", [
        ("co2.op_emission_g_h", "Émissions opérationnelles (g/h)"),
        ("co2.energy_mix_g_h", "Mix énergétique (g/h)"),
        ("co2.co2_target_g_h", "Cible CO₂ (g/h)"),
        ("co2.co2_max_g_h", "Maximum CO₂ (g/h)"),
    ]),
]

_PAIR_MARKS = {-8: "-8", -4: "-4", 0: "0", 4: "+4", 8: "+8"}


def _pair_block(i: int, j: int) -> html.Div:
    """Slider bipolaire (-8..+8) d'une paire de critères + libellé dynamique."""
    key = f"{i}-{j}"
    return html.Div(
        [
            html.P(
                f"« {CRITERIA[i]} » vs « {CRITERIA[j]} »",
                style={"margin": "0 0 2px", "fontSize": "14px", "fontWeight": "600"},
            ),
            dcc.Slider(
                id={"type": "ahp-pair", "index": key},
                min=-8, max=8, step=1, value=0, marks=_PAIR_MARKS,
                tooltip={"placement": "bottom"},
            ),
            html.Div(
                "Importance égale",
                id={"type": "ahp-pair-label", "index": key},
                style={"fontSize": "13px", "color": COLORS["muted"],
                       "marginBottom": "16px"},
            ),
        ]
    )


def _score_block(k: int) -> html.Div:
    """Slider de note 1..6 d'un critère + libellé live (équivalent Saaty)."""
    return html.Div(
        [
            html.P(CRITERIA[k],
                   style={"margin": "0 0 2px", "fontSize": "14px",
                          "fontWeight": "600"}),
            dcc.Slider(
                id={"type": "ahp-score", "index": str(k)},
                min=1, max=6, step=1, value=3,
                marks={v: str(v) for v in range(1, 7)},
            ),
            html.Div(
                id={"type": "ahp-score-label", "index": str(k)},
                style={"fontSize": "13px", "color": COLORS["muted"],
                       "marginBottom": "16px"},
            ),
        ]
    )


def _kpi_blocks() -> list:
    """Inputs numériques optionnels groupés par bloc KPI."""
    children: list = []
    for block_title, fields in KPI_FIELDS:
        children.append(
            html.H4(block_title, style={"margin": "10px 0 6px", "fontSize": "15px",
                                        "color": COLORS["primary"]})
        )
        children.append(
            html.Div(
                [
                    labelled(
                        label_text,
                        dcc.Input(
                            id={"type": "kpi-input", "index": key},
                            type="number",
                            placeholder="non renseigné",
                            style=INPUT_STYLE,
                        ),
                        width="230px",
                    )
                    for key, label_text in fields
                ]
            )
        )
    return children


def layout() -> html.Div:
    """Construit la page Questionnaire (état du service relu à chaque navigation)."""
    service = get_service()
    return html.Div(
        [
            html.H2("Questionnaire hebdomadaire", style={"margin": "6px 0 6px"}),
            html.Div(id="q-project-info", style={"marginBottom": "14px"}),
            card(
                "Évaluation",
                [
                    labelled(
                        "Nœud (n'importe quel rang)",
                        dcc.Dropdown(id="q-node-dd",
                                     options=node_options(service.repo.nodes()),
                                     placeholder="Choisir un nœud…"),
                        width="380px",
                    ),
                    labelled(
                        "Identifiant opérateur",
                        dcc.Input(id="q-operator", type="text",
                                  placeholder="ex. jdupont", style=INPUT_STYLE),
                    ),
                    labelled(
                        "Notes (optionnel)",
                        dcc.Input(id="q-notes", type="text",
                                  placeholder="commentaire libre",
                                  style=INPUT_STYLE),
                        width="320px",
                    ),
                ],
            ),
            card(
                "Comparaisons par paires (AHP)",
                [_pair_block(i, j) for i, j in PAIRS],
                subtitle=(
                    "Curseur à gauche : le second critère domine ; à droite : "
                    "le premier domine ; au centre : importance égale."
                ),
            ),
            card(
                "Notes des critères",
                [_score_block(k) for k in range(len(CRITERIA))],
                subtitle="Notez l'urgence de chaque critère de 1 (faible) à 6 (critique).",
            ),
            card(
                "Résultat",
                [
                    html.Div(id="q-ud-badge",
                             style={"fontSize": "26px", "fontWeight": "700",
                                    "color": COLORS["primary"],
                                    "marginBottom": "6px"}),
                    html.Div(id="q-cr-msg", style={"marginBottom": "10px"}),
                    dcc.Graph(id="q-weights-fig",
                              figure=empty_figure("Réglez les curseurs ci-dessus.")),
                ],
                subtitle="Aperçu en direct — rien n'est enregistré avant validation.",
            ),
            card(
                "KPIs opérationnels (optionnels)",
                _kpi_blocks(),
                subtitle=(
                    "Tous les champs sont optionnels ; ils sont pré-remplis avec "
                    "les valeurs actuelles du nœud sélectionné."
                ),
            ),
            html.Div(
                html.Button("Enregistrer l'évaluation hebdomadaire",
                            id="q-save-btn", style=BUTTON_STYLE),
            ),
            html.Div(id="q-save-msg"),
        ],
        style=PAGE_STYLE,
    )


# --- Helpers de conversion ------------------------------------------------------

def _comparisons_from_inputs(values, ids) -> dict[tuple[int, int], float]:
    """Convertit les curseurs bipolaires en jugements de Saaty {(i, j): v}."""
    comparisons: dict[tuple[int, int], float] = {}
    for value, id_ in zip(values, ids):
        i_str, j_str = id_["index"].split("-", 1)
        comparisons[(int(i_str), int(j_str))] = bipolar_to_saaty(int(value or 0))
    return comparisons


def _scores_from_inputs(values, ids) -> list[float]:
    """Convertit les notes UI [1, 6] en notes Saaty [1, 9], ordonnées par critère."""
    ordered = sorted(zip(ids, values), key=lambda pair: int(pair[0]["index"]))
    return [score_6_to_9(float(v if v is not None else 3)) for _, v in ordered]


# --- Callbacks (fonctions nommées, testables sans serveur) ------------------------

def project_info_callback(project_data):
    """Affiche le projet actif et restreint le dropdown nœud à ses nœuds."""
    service = get_service()
    pid = (project_data or {}).get("project_id")
    if pid:
        nodes = [n for n in service.repo.nodes() if n.project_id == pid]
        name = (project_data or {}).get("name", pid)
        info = html.Span(f"Projet actif : « {name} ».",
                         style={"color": COLORS["primary"], "fontWeight": "600"})
    else:
        nodes = service.repo.nodes()
        info = html.Span(
            "Aucun projet sélectionné — tous les nœuds du graphe sont listés.",
            style={"color": COLORS["muted"]},
        )
    return info, node_options(nodes)


def pair_label_callback(value, id_):
    """Libellé dynamique sous un slider de comparaison par paire."""
    i, j = (int(x) for x in id_["index"].split("-", 1))
    v = int(value or 0)
    if v == 0:
        return "Importance égale"
    if v > 0:
        return f"« {CRITERIA[i]} » {v}× plus important"
    return f"« {CRITERIA[j]} » {abs(v)}× plus important"


def score_label_callback(value):
    """Libellé live d'une note critère : « Note v/6 (≈ Saaty s) »."""
    v = float(value if value is not None else 3)
    return f"Note {int(v)}/6 (≈ Saaty {score_6_to_9(v):.1f})"


def preview_callback(pair_values, score_values, pair_ids, score_ids):
    """Aperçu live : Ud, ratio de cohérence CR et figure des poids AHP."""
    comparisons = _comparisons_from_inputs(pair_values, pair_ids)
    scores = _scores_from_inputs(score_values, score_ids)
    result = run_ahp(comparisons, n=len(CRITERIA))
    ud = compute_ud(result.weights, scores)
    badge = f"Ud = {ud:.3f}"
    cr = result.consistency_ratio
    if cr >= CONSISTENCY_THRESHOLD:
        cr_msg = html.Span(
            f"CR = {cr:.3f} ≥ {CONSISTENCY_THRESHOLD:.2f} : jugements incohérents, "
            "révisez vos comparaisons.",
            style={"color": COLORS["alert"], "fontWeight": "600"},
        )
    else:
        cr_msg = html.Span(
            f"CR = {cr:.3f} < {CONSISTENCY_THRESHOLD:.2f} : jugements cohérents.",
            style={"color": COLORS["ok"]},
        )
    return badge, cr_msg, ahp_weights_figure(list(result.weights))


def prefill_kpis_callback(node_id, kpi_ids):
    """Pré-remplit les inputs KPI avec les valeurs actuelles du nœud sélectionné."""
    service = get_service()
    if not node_id:
        raise PreventUpdate
    node = service.repo.get_node(node_id)
    if node is None:
        raise PreventUpdate
    values = []
    for id_ in kpi_ids:
        block, field = id_["index"].split(".", 1)
        values.append(getattr(getattr(node.kpis, block), field))
    return values


def save_assessment_callback(n_clicks, project_data, node_id, operator_id, notes,
                             pair_values, pair_ids, score_values, score_ids,
                             kpi_values, kpi_ids):
    """Valide et persiste l'évaluation hebdomadaire (AHP + KPIs renseignés).

    Refuse l'enregistrement si le nœud ou l'opérateur manquent, ou si le
    ratio de cohérence CR dépasse le seuil de Saaty (0.10).
    """
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    if not node_id:
        return html.Span("Sélectionnez un nœud avant d'enregistrer.",
                         style=MSG_ALERT_STYLE)
    if not operator_id or not str(operator_id).strip():
        return html.Span("L'identifiant opérateur est requis.",
                         style=MSG_ALERT_STYLE)
    node = service.repo.get_node(node_id)
    if node is None:
        return html.Span("Nœud introuvable dans le graphe.", style=MSG_ALERT_STYLE)

    comparisons = _comparisons_from_inputs(pair_values, pair_ids)
    scores = _scores_from_inputs(score_values, score_ids)
    project_id = (project_data or {}).get("project_id") or node.project_id or ""
    assessment = SupplyScoreService.build_assessment(
        node_id=node_id,
        project_id=project_id,
        operator_id=str(operator_id).strip(),
        comparisons=comparisons,
        criteria_scores=scores,
        notes=str(notes).strip() if notes else "",
    )
    if assessment.consistency_ratio >= CONSISTENCY_THRESHOLD:
        return html.Span(
            f"Enregistrement refusé : CR = {assessment.consistency_ratio:.3f} "
            f"≥ {CONSISTENCY_THRESHOLD:.2f}. Révisez vos comparaisons par paires.",
            style=MSG_ALERT_STYLE,
        )

    service.submit_assessment(assessment)

    # KPIs : seuls les champs renseignés écrasent les valeurs du nœud.
    node = service.repo.get_node(node_id)
    updated = 0
    for value, id_ in zip(kpi_values, kpi_ids):
        if value is None or value == "":
            continue
        block, field = id_["index"].split(".", 1)
        setattr(getattr(node.kpis, block), field, float(value))
        updated += 1
    service.registry.save_node(node)
    service.repo.update_node(node)
    service.client_db(node_id).save_kpi_snapshot(node_id, node.kpis)
    service.evaluate_all(persist=True)

    return html.Span(
        f"Évaluation enregistrée pour « {node.name} » "
        f"(Ud = {assessment.ud:.3f}, {updated} KPI mis à jour). "
        "Pensez à re-remplir le questionnaire chaque semaine.",
        style=MSG_OK_STYLE,
    )


def register_callbacks(app) -> None:
    """Enregistre les callbacks de la page Questionnaire sur l'application Dash."""
    app.callback(
        Output("q-project-info", "children"),
        Output("q-node-dd", "options"),
        Input("store-project", "data"),
    )(project_info_callback)

    app.callback(
        Output({"type": "ahp-pair-label", "index": MATCH}, "children"),
        Input({"type": "ahp-pair", "index": MATCH}, "value"),
        State({"type": "ahp-pair", "index": MATCH}, "id"),
    )(pair_label_callback)

    app.callback(
        Output({"type": "ahp-score-label", "index": MATCH}, "children"),
        Input({"type": "ahp-score", "index": MATCH}, "value"),
    )(score_label_callback)

    app.callback(
        Output("q-ud-badge", "children"),
        Output("q-cr-msg", "children"),
        Output("q-weights-fig", "figure"),
        Input({"type": "ahp-pair", "index": ALL}, "value"),
        Input({"type": "ahp-score", "index": ALL}, "value"),
        State({"type": "ahp-pair", "index": ALL}, "id"),
        State({"type": "ahp-score", "index": ALL}, "id"),
    )(preview_callback)

    app.callback(
        Output({"type": "kpi-input", "index": ALL}, "value"),
        Input("q-node-dd", "value"),
        State({"type": "kpi-input", "index": ALL}, "id"),
        prevent_initial_call=True,
    )(prefill_kpis_callback)

    app.callback(
        Output("q-save-msg", "children"),
        Input("q-save-btn", "n_clicks"),
        State("store-project", "data"),
        State("q-node-dd", "value"),
        State("q-operator", "value"),
        State("q-notes", "value"),
        State({"type": "ahp-pair", "index": ALL}, "value"),
        State({"type": "ahp-pair", "index": ALL}, "id"),
        State({"type": "ahp-score", "index": ALL}, "value"),
        State({"type": "ahp-score", "index": ALL}, "id"),
        State({"type": "kpi-input", "index": ALL}, "value"),
        State({"type": "kpi-input", "index": ALL}, "id"),
        prevent_initial_call=True,
    )(save_assessment_callback)
