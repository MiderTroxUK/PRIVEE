"""Page « Simulation » : du choc unitaire au scénario composite (Lot 15.4).

Quatre volets, du plus simple au plus riche :

- **choc unitaire** (historique, intact) : :meth:`SupplyScoreService.simulate_shock`
  sur un nœud, sans persistance ; la carte « Appliquer réellement » reste la
  SEULE action persistante de la page (confirmation explicite) ;
- **scénario composite** : liste DYNAMIQUE de chocs (Ur forcé, statut simulé,
  rupture d'arc — lignes pattern-matching ``{"type": ..., "index": uuid}``),
  évaluée par :class:`~supplyscore.graph.scenario.MoteurScenario` — calcul
  PUR, aucune écriture, ni dépôt ni ``UrgencyState`` ;
- **criticité systématique** : :class:`~supplyscore.services.criticite.ServiceCriticite`
  → tornado top 15 ;
- **scénarios enregistrés** : sérialisation JSON du scénario courant dans le
  registre (``save_scenario``), rechargement (reconstruction des lignes) et
  suppression. Les ``multiplicateurs_lead_time`` (réservés au mode Monte
  Carlo) ne sont PAS édités par l'UI : un scénario chargé n'en reconstruit pas.

Les chocs ne s'additionnent PAS (propagation multiplicative, cf. E15.1) :
seul le scénario composite donne la vraie valeur combinée — d'où ce volet.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any
from uuid import uuid4

from dash import ALL, MATCH, Input, Output, State, ctx, dash_table, dcc, html
from dash.exceptions import PreventUpdate

from supplyscore.domain.models import ArcKind, SupplyNode, TaskStatus
from supplyscore.graph.scenario import MoteurScenario, ResultatScenario, Scenario
from supplyscore.services.criticite import ServiceCriticite
from supplyscore.web_ui import get_service
from supplyscore.web_ui.components.event_forms import event_type_options
from supplyscore.web_ui.components.figures import (
    criticite_tornado_figure,
    empty_figure,
    shock_bar_figure,
    shock_dag_figure,
)
from supplyscore.web_ui.components.layout import (
    BUTTON_SECONDARY_STYLE,
    BUTTON_STYLE,
    COLORS,
    FONT_FAMILY,
    INPUT_STYLE,
    MSG_ALERT_STYLE,
    MSG_OK_STYLE,
    MSG_WARN_STYLE,
    PAGE_STYLE,
    STATUS_FR,
    card,
    labelled,
    node_options,
)

#: Style du bouton d'application réelle (action destructive).
BUTTON_DANGER_STYLE = {**BUTTON_STYLE, "backgroundColor": COLORS["alert"]}

#: Valeur du type de choc « Ur forcé » (les statuts utilisent ``str(TaskStatus)``).
CHOC_UR = "ur"

#: Options du dropdown « type de choc » d'une ligne de scénario.
CHOC_KIND_OPTIONS = [
    {"label": "Ur forcé", "value": CHOC_UR},
    {"label": "Statut abandonné", "value": str(TaskStatus.ABANDONED)},
    {"label": "Statut terminé", "value": str(TaskStatus.DONE)},
]

#: Mapping SIMPLE des 14 événements calibrés (E2) vers un choc pré-réglé.
#:
#: Heuristique documentée, volontairement grossière (le preset reste éditable) :
#: un défaut financier avéré équivaut à un ABANDON du nœud ; les autres
#: événements forcent le ``ur_local`` à un niveau forfaitaire reflétant leur
#: gravité type — 0.9 arrêt franc (panne, accident), 0.8 indisponibilité forte
#: (rupture matière, cyber), 0.7 capacité dégradée (grève, perte de capacité),
#: 0.6 flux retardé (retard fournisseur, transport), 0.5 qualité ou contexte
#: dégradé (non-conformité, instabilité politique), 0.4 tension de demande,
#: 0.3 choc purement tarifaire (tarif, énergie).
PRESET_CHOCS: dict[str, tuple[str, float]] = {
    "panne_machine": (CHOC_UR, 0.9),
    "accident": (CHOC_UR, 0.9),
    "rupture_matiere": (CHOC_UR, 0.8),
    "cyber_incident": (CHOC_UR, 0.8),
    "greve": (CHOC_UR, 0.7),
    "perte_capacite": (CHOC_UR, 0.7),
    "retard_fournisseur": (CHOC_UR, 0.6),
    "perturbation_transport": (CHOC_UR, 0.6),
    "non_conformite_qualite": (CHOC_UR, 0.5),
    "instabilite_politique": (CHOC_UR, 0.5),
    "pic_demande": (CHOC_UR, 0.4),
    "hausse_tarif": (CHOC_UR, 0.3),
    "hausse_energie": (CHOC_UR, 0.3),
    "alerte_financiere_fournisseur": (str(TaskStatus.ABANDONED), 1.0),
}

#: Seuil en deçà duquel un ΔUr est réputé nul (cohérent avec criticite.py).
_EPS_DELTA = 1e-12

#: Colonnes du tableau comparatif baseline/scénario.
_SCN_COLUMNS = [
    {"name": "Nœud", "id": "Nœud"},
    {"name": "Ur avant", "id": "Ur avant"},
    {"name": "Ur après", "id": "Ur après"},
    {"name": "ΔUr", "id": "ΔUr"},
    {"name": "ΔUd", "id": "ΔUd"},
]

_TABLE_STYLE_CELL = {
    "fontFamily": FONT_FAMILY,
    "fontSize": "13px",
    "padding": "6px 10px",
    "textAlign": "left",
}

_TABLE_STYLE_HEADER = {"backgroundColor": "#eef2f5", "fontWeight": "600"}

_ROW_STYLE = {"borderBottom": f"1px dashed {COLORS['border']}", "marginBottom": "4px"}

_NOTE_NON_ADDITIVITE = (
    "Les chocs ne s'additionnent pas : la propagation est multiplicative, "
    "seul le scénario composite donne la vraie valeur combinée."
)


def _triggered_id() -> Any:
    """Id du composant déclencheur (None hors contexte de requête Dash)."""
    try:  # ctx indisponible hors requête Dash (appel direct en test)
        return ctx.triggered_id
    except Exception:
        return None


def _fr(value: float, digits: int = 3, signe: bool = False) -> str:
    """Nombre formaté à la française (virgule décimale) pour les PHRASES.

    Réservé aux messages français visibles — jamais aux inputs ni aux
    colonnes numériques de DataTable (Dash exige le point).

    Args:
        value: valeur à formater.
        digits: nombre de décimales.
        signe: True pour forcer le signe (« +0,500 »).
    """
    texte = f"{value:+.{digits}f}" if signe else f"{value:.{digits}f}"
    return texte.replace(".", ",")


def layout() -> html.Div:
    """Construit la page Simulation (état du service relu à chaque navigation)."""
    service = get_service()
    return html.Div(
        [
            html.H2("Simulation de choc", style={"margin": "6px 0 12px"}),
            card(
                "Scénario catastrophe (what-if, sans persistance)",
                [
                    labelled(
                        "Nœud à choquer",
                        dcc.Dropdown(
                            id="sim-node-dd",
                            options=node_options(service.repo.nodes()),
                            placeholder="Choisir un nœud…",
                        ),
                        width="380px",
                    ),
                    labelled(
                        "Ur_local simulé",
                        dcc.Slider(
                            id="sim-ur-slider",
                            min=0,
                            max=1,
                            step=0.05,
                            value=1.0,
                            marks={0: "0", 0.5: "0.5", 1: "1"},
                            tooltip={"placement": "bottom"},
                        ),
                        width="320px",
                    ),
                    html.Div(
                        [
                            html.Button(
                                "Défaillance totale (1.0)",
                                id="sim-preset-fail",
                                style={**BUTTON_SECONDARY_STYLE, "marginRight": "10px"},
                            ),
                            html.Button(
                                "Retour à la normale (0.0)",
                                id="sim-preset-ok",
                                style=BUTTON_SECONDARY_STYLE,
                            ),
                        ],
                        style={"marginBottom": "12px"},
                    ),
                    html.Div(html.Button("Simuler", id="sim-run-btn", style=BUTTON_STYLE)),
                    html.Div(id="sim-summary"),
                ],
                subtitle="Aucune donnée n'est modifiée : la simulation est purement indicative.",
            ),
            card(
                "Propagation du choc",
                [
                    # E16.6 — dcc.Loading autour des zones lentes (figures et
                    # tableaux recalculés) : l'id reste sur le composant interne.
                    dcc.Loading(
                        type="circle",
                        children=dcc.Graph(
                            id="sim-dag-fig", figure=empty_figure("Lancez une simulation.")
                        ),
                    )
                ],
                subtitle="Le DAG du projet, coloré par ΔUr après le choc simulé.",
            ),
            card(
                "Impact par nœud",
                [
                    dcc.Loading(
                        type="circle",
                        children=dcc.Graph(
                            id="sim-bar-fig", figure=empty_figure("Lancez une simulation.")
                        ),
                    )
                ],
                subtitle="Les ΔUr du choc simulé, nœud par nœud.",
            ),
            card(
                "Scénario composite (multi-chocs, sans persistance)",
                [
                    html.Div(id="sim-chocs-rows", children=[]),
                    html.Div(
                        [
                            html.Button(
                                "+ choc",
                                id="sim-add-choc-btn",
                                style={**BUTTON_SECONDARY_STYLE, "marginRight": "10px"},
                            ),
                            html.Button(
                                "+ rupture d'arc",
                                id="sim-add-arc-btn",
                                style=BUTTON_SECONDARY_STYLE,
                            ),
                        ],
                        style={"margin": "10px 0 12px"},
                    ),
                    labelled(
                        "Choc prédéfini (événement calibré)",
                        dcc.Dropdown(
                            id="sim-preset-dd",
                            options=event_type_options(),
                            placeholder="Choisir un événement…",
                        ),
                        width="320px",
                    ),
                    html.Button(
                        "Ajouter comme choc",
                        id="sim-preset-add-btn",
                        style={**BUTTON_SECONDARY_STYLE, "verticalAlign": "bottom"},
                    ),
                    html.Div(
                        html.Button("Évaluer le scénario", id="sim-eval-btn", style=BUTTON_STYLE),
                        style={"margin": "12px 0"},
                    ),
                    html.Div(id="sim-eval-msg"),
                    dcc.Loading(
                        type="circle",
                        children=dash_table.DataTable(  # type: ignore[attr-defined]
                            id="sim-scn-table",
                            columns=_SCN_COLUMNS,
                            data=[],
                            sort_action="native",
                            style_cell=_TABLE_STYLE_CELL,
                            style_header=_TABLE_STYLE_HEADER,
                            style_as_list_view=True,
                        ),
                    ),
                    dcc.Loading(
                        type="circle",
                        children=dcc.Graph(
                            id="sim-scn-dag-fig",
                            figure=empty_figure("Évaluez un scénario composite."),
                        ),
                    ),
                ],
                subtitle=f"Évaluation pure (rien n'est modifié). {_NOTE_NON_ADDITIVITE}",
            ),
            card(
                "Criticité systématique",
                [
                    html.Div(
                        html.Button(
                            "Analyser la criticité (top 15)",
                            id="sim-crit-btn",
                            style=BUTTON_STYLE,
                        ),
                        style={"marginBottom": "12px"},
                    ),
                    dcc.Loading(
                        type="circle",
                        children=dcc.Graph(
                            id="sim-crit-fig",
                            figure=empty_figure("Lancez l'analyse de criticité."),
                        ),
                    ),
                ],
                subtitle=(
                    "Pour chaque nœud actif du projet : ΔUr du client final si son "
                    "ur_local passait à 1.0 — calcul pur, rien n'est modifié."
                ),
            ),
            card(
                "Scénarios enregistrés",
                [
                    labelled(
                        "Nom du scénario",
                        dcc.Input(
                            id="sim-scn-name",
                            type="text",
                            placeholder="ex. Hiver rude",
                            style=INPUT_STYLE,
                        ),
                        width="260px",
                    ),
                    html.Button(
                        "Sauvegarder",
                        id="sim-scn-save-btn",
                        style={**BUTTON_STYLE, "verticalAlign": "bottom"},
                    ),
                    html.Div(),
                    labelled(
                        "Scénario enregistré",
                        dcc.Dropdown(
                            id="sim-scn-dd",
                            options=[],
                            placeholder="Choisir un scénario…",
                        ),
                        width="300px",
                    ),
                    html.Button(
                        "Charger",
                        id="sim-scn-load-btn",
                        style={
                            **BUTTON_SECONDARY_STYLE,
                            "verticalAlign": "bottom",
                            "marginRight": "10px",
                        },
                    ),
                    html.Button(
                        "Supprimer",
                        id="sim-scn-del-btn",
                        style={**BUTTON_SECONDARY_STYLE, "verticalAlign": "bottom"},
                    ),
                    html.Div(id="sim-scn-msg"),
                ],
                subtitle=(
                    "Le scénario courant (lignes du scénario composite) est sérialisé "
                    "par projet ; « Charger » reconstruit ses lignes, rien n'est évalué."
                ),
            ),
            card(
                "Appliquer réellement",
                [
                    labelled(
                        "Statut à appliquer",
                        dcc.Dropdown(
                            id="sim-status-dd",
                            options=[
                                {
                                    "label": STATUS_FR[TaskStatus.DONE],
                                    "value": str(TaskStatus.DONE),
                                },
                                {
                                    "label": STATUS_FR[TaskStatus.ABANDONED],
                                    "value": str(TaskStatus.ABANDONED),
                                },
                            ],
                            placeholder="Choisir un statut…",
                        ),
                        width="220px",
                    ),
                    html.Div(
                        dcc.ConfirmDialogProvider(
                            children=html.Button(
                                "Appliquer le statut (persistant)",
                                style=BUTTON_DANGER_STYLE,
                            ),
                            id="sim-apply-confirm",
                            message=(
                                "Confirmer l'application RÉELLE du statut au nœud "
                                "sélectionné ? Le choc sera propagé et persisté."
                            ),
                        ),
                    ),
                    html.Div(id="sim-apply-msg"),
                ],
                subtitle=(
                    "Action persistante sur le nœud sélectionné ci-dessus — "
                    "contrairement à la simulation, le graphe est réellement modifié."
                ),
            ),
        ],
        style=PAGE_STYLE,
    )


# --- Aides : lignes dynamiques et construction du Scenario -----------------------


def _slider_style(visible: bool) -> dict:
    """Style du conteneur du slider « Ur forcé » : visible ou masqué."""
    return {"display": "inline-block"} if visible else {"display": "none"}


def _choc_row(
    uid: str,
    options: list[dict],
    kind: str = CHOC_UR,
    valeur: float = 1.0,
    node_id: str | None = None,
) -> html.Div:
    """Ligne « choc sur un nœud » : nœud, type de choc, slider Ur (si Ur forcé)."""
    return html.Div(
        [
            labelled(
                "Nœud choqué",
                dcc.Dropdown(
                    id={"type": "sim-choc-node", "index": uid},
                    options=options,
                    value=node_id,
                    placeholder="Choisir un nœud…",
                ),
                width="300px",
            ),
            labelled(
                "Type de choc",
                dcc.Dropdown(
                    id={"type": "sim-choc-kind", "index": uid},
                    options=CHOC_KIND_OPTIONS,
                    value=kind,
                    clearable=False,
                ),
                width="190px",
            ),
            html.Div(
                labelled(
                    "Ur forcé",
                    dcc.Slider(
                        id={"type": "sim-choc-val", "index": uid},
                        min=0,
                        max=1,
                        step=0.05,
                        value=valeur,
                        marks={0: "0", 0.5: "0.5", 1: "1"},
                        tooltip={"placement": "bottom"},
                    ),
                    width="260px",
                ),
                id={"type": "sim-choc-val-wrap", "index": uid},
                style=_slider_style(kind == CHOC_UR),
            ),
        ],
        style=_ROW_STYLE,
    )


def _arc_row(uid: str, options: list[dict], value: str | None = None) -> html.Div:
    """Ligne « rupture d'arc » : dropdown des arcs nominaux (fournisseur → client)."""
    return html.Div(
        [
            labelled(
                "Arc rompu (fournisseur → client)",
                dcc.Dropdown(
                    id={"type": "sim-arc-del", "index": uid},
                    options=options,
                    value=value,
                    placeholder="Choisir un arc…",
                ),
                width="420px",
            )
        ],
        style=_ROW_STYLE,
    )


def _project_nodes(service, project_data) -> list[SupplyNode]:
    """Nœuds du projet actif (tout le graphe si aucun projet sélectionné)."""
    pid = (project_data or {}).get("project_id")
    nodes = service.repo.nodes()
    if pid:
        nodes = [n for n in nodes if n.project_id == pid]
    return nodes


def _arc_options(service, project_data) -> list[dict]:
    """Options du dropdown des arcs : arcs NOMINAUX internes au projet actif.

    Les arcs de secours (backup) sont exclus : inertes dans tous les calculs,
    leur rupture serait un choc à vide. Valeur = ``"source_id->target_id"``
    (le format de :attr:`SupplyArc.id`), libellé = « source → cible » en noms.
    """
    nodes = _project_nodes(service, project_data)
    ids = {n.id for n in nodes}
    names = {n.id: n.name for n in nodes}
    arcs = [
        a
        for a in service.repo.arcs()
        if a.kind_arc != ArcKind.BACKUP and a.source_id in ids and a.target_id in ids
    ]
    return [
        {
            "label": f"{names.get(a.source_id, a.source_id)} → "
            f"{names.get(a.target_id, a.target_id)}",
            "value": f"{a.source_id}->{a.target_id}",
        }
        for a in sorted(arcs, key=lambda a: (a.source_id, a.target_id))
    ]


def _rows_from_payload(payload: dict, options: list[dict], arc_options: list[dict]) -> list:
    """Reconstruit les lignes dynamiques depuis un payload de scénario chargé."""
    rows: list = []
    for node_id, valeur in (payload.get("surcharges_ur") or {}).items():
        rows.append(
            _choc_row(uuid4().hex[:8], options, kind=CHOC_UR, valeur=float(valeur), node_id=node_id)
        )
    for node_id, statut in (payload.get("statuts") or {}).items():
        rows.append(_choc_row(uuid4().hex[:8], options, kind=str(statut), node_id=node_id))
    for arc in payload.get("arcs_supprimes") or []:
        source_id, target_id = arc
        rows.append(_arc_row(uuid4().hex[:8], arc_options, value=f"{source_id}->{target_id}"))
    return rows


def _scenario_from_rows(
    nom,
    node_values,
    node_ids,
    kind_values,
    kind_ids,
    val_values,
    val_ids,
    arc_values,
    arc_ids,
) -> Scenario:
    """Construit le :class:`Scenario` depuis les lignes dynamiques du formulaire.

    Les lignes de choc sont parcourues par ``id["index"]`` CROISSANT (l'ordre
    DOM des composants pattern-matching n'est pas garanti par Dash, comme dans
    ``parse_event_params``) ; une ligne incomplète (nœud ou type manquant) est
    ignorée ; si un même nœud apparaît plusieurs fois, la dernière ligne (au
    sens du tri par index) l'emporte. Slider absent → Ur forcé à 1.0.
    """
    lignes: dict[str, dict[str, Any]] = {}
    for champ, ids, values in (
        ("node", node_ids, node_values),
        ("kind", kind_ids, kind_values),
        ("val", val_ids, val_values),
    ):
        for id_, value in zip(ids, values, strict=True):
            lignes.setdefault(str(id_["index"]), {})[champ] = value

    surcharges: dict[str, float] = {}
    statuts: dict[str, TaskStatus] = {}
    for index in sorted(lignes):
        ligne = lignes[index]
        node_id, kind = ligne.get("node"), ligne.get("kind")
        if not node_id or not kind:
            continue  # ligne incomplète : ignorée
        if kind == CHOC_UR:
            valeur = ligne.get("val")
            statuts.pop(node_id, None)
            surcharges[node_id] = float(valeur) if valeur is not None else 1.0
        else:
            surcharges.pop(node_id, None)
            statuts[node_id] = TaskStatus(kind)

    arcs: list[tuple[str, str]] = []
    arc_pairs = sorted(zip(arc_ids, arc_values, strict=True), key=lambda p: str(p[0]["index"]))
    for _id, value in arc_pairs:
        if not value:
            continue  # ligne incomplète : ignorée
        source_id, sep, target_id = str(value).partition("->")
        if sep and source_id and target_id and (source_id, target_id) not in arcs:
            arcs.append((source_id, target_id))
    return Scenario(
        nom=str(nom or "scénario"),
        surcharges_ur=surcharges,
        statuts=statuts,
        arcs_supprimes=arcs,
    )


def _payload_json(scenario: Scenario) -> str:
    """Sérialise un :class:`Scenario` en JSON (statuts en str, arcs en listes)."""
    payload = dataclasses.asdict(scenario)
    payload["statuts"] = {nid: str(statut) for nid, statut in scenario.statuts.items()}
    payload["arcs_supprimes"] = [list(arc) for arc in scenario.arcs_supprimes]
    return json.dumps(payload, sort_keys=True)


def _table_comparative(resultat: ResultatScenario, nodes: list[SupplyNode]) -> list[dict]:
    """Tableau baseline/scénario : top 20 des nœuds du périmètre par ``|ΔUr|``."""
    retenus = sorted(nodes, key=lambda n: (-abs(resultat.delta_ur.get(n.id, 0.0)), n.name, n.id))[
        :20
    ]
    return [
        {
            "Nœud": n.name,
            "Ur avant": round(resultat.baseline_ur.get(n.id, 0.0), 3),
            "Ur après": round(resultat.scenario_ur.get(n.id, 0.0), 3),
            "ΔUr": round(resultat.delta_ur.get(n.id, 0.0), 3),
            "ΔUd": round(resultat.delta_ud.get(n.id, 0.0), 3),
        }
        for n in retenus
    ]


def _scenario_options(service, pid) -> list[dict]:
    """Options du dropdown des scénarios enregistrés du projet (vide sans projet)."""
    if not pid:
        return []
    return [{"label": s["nom"], "value": s["id"]} for s in service.registry.list_scenarios(pid)]


# --- Callbacks (fonctions nommées, testables sans serveur) -----------------------


def node_options_callback(project_data):
    """Restreint le dropdown aux nœuds du projet actif (tout le graphe sinon)."""
    service = get_service()
    return node_options(_project_nodes(service, project_data))


def preset_callback(n_fail, n_ok):
    """Présets du slider : défaillance totale (1.0) ou retour à la normale (0.0)."""
    triggered = ctx.triggered_id
    if triggered == "sim-preset-fail":
        return 1.0
    if triggered == "sim-preset-ok":
        return 0.0
    raise PreventUpdate


def simulate_callback(n_clicks, node_id, ur_value, project_data):
    """Lance le what-if : figures DAG + barres et texte récapitulatif."""
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    if not node_id:
        message = html.Span("Sélectionnez d'abord un nœud à choquer.", style=MSG_ALERT_STYLE)
        return (
            empty_figure("Sélectionnez un nœud."),
            empty_figure("Sélectionnez un nœud."),
            message,
        )

    value = float(ur_value if ur_value is not None else 1.0)
    deltas = service.simulate_shock(node_id, value)

    nodes = _project_nodes(service, project_data)
    ids = {n.id for n in nodes}
    arcs = [a for a in service.repo.arcs() if a.source_id in ids and a.target_id in ids]
    names = {n.id: n.name for n in service.repo.nodes()}

    shocked = service.repo.get_node(node_id)
    shocked_name = shocked.name if shocked is not None else node_id
    impacted = {nid: d for nid, d in deltas.items() if nid != node_id and abs(d) > 1e-9}
    if impacted:
        worst = max(impacted, key=lambda nid: abs(impacted[nid]))
        text = (
            f"Le choc sur « {shocked_name} » (Ur_local = {_fr(value, 2)}) impacte "
            f"{len(impacted)} nœud(s) aval, ΔUr max = {_fr(impacted[worst], signe=True)} "
            f"sur « {names.get(worst, worst)} ». Simulation sans persistance."
        )
    else:
        text = (
            f"Le choc sur « {shocked_name} » (Ur_local = {_fr(value, 2)}) "
            "n'impacte aucun nœud aval."
        )
    return (
        shock_dag_figure(nodes, arcs, deltas),
        shock_bar_figure(deltas, names),
        html.Span(text, style=MSG_WARN_STYLE),
    )


def apply_status_callback(submit_n_clicks, node_id, status_value):
    """Applique RÉELLEMENT le statut choisi (persistant) après confirmation."""
    if not submit_n_clicks:
        raise PreventUpdate
    service = get_service()
    if not node_id or not status_value:
        return html.Span("Choisissez un nœud (carte du haut) ET un statut.", style=MSG_ALERT_STYLE)
    status = TaskStatus(status_value)
    service.set_status(node_id, status)
    node = service.repo.get_node(node_id)
    name = node.name if node is not None else node_id
    return html.Span(
        f"Statut « {STATUS_FR[status]} » appliqué à « {name} » : "
        "propagation recalculée et persistée.",
        style=MSG_OK_STYLE,
    )


def rows_callback(n_choc, n_arc, n_preset, n_load, rows, preset_type, scn_id, project_data):
    """Liste dynamique des chocs : ajout, preset, rupture d'arc et chargement.

    UN SEUL callback alimente ``sim-chocs-rows.children`` (contrainte Dash) :
    le déclencheur est dispatché via :func:`_triggered_id`. « Charger »
    REMPLACE les lignes par celles du scénario enregistré ; les autres
    déclencheurs APPENDENT une ligne (index = ``uuid4().hex[:8]``).
    """
    service = get_service()
    triggered = _triggered_id()
    rows = list(rows or [])
    options = node_options(_project_nodes(service, project_data))
    uid = uuid4().hex[:8]
    if triggered == "sim-add-choc-btn":
        return [*rows, _choc_row(uid, options)]
    if triggered == "sim-add-arc-btn":
        return [*rows, _arc_row(uid, _arc_options(service, project_data))]
    if triggered == "sim-preset-add-btn":
        if not preset_type:
            raise PreventUpdate
        kind, valeur = PRESET_CHOCS[preset_type]
        return [*rows, _choc_row(uid, options, kind=kind, valeur=valeur)]
    if triggered == "sim-scn-load-btn":
        if not scn_id:
            raise PreventUpdate
        scenario = service.registry.get_scenario(scn_id)
        if scenario is None:
            raise PreventUpdate
        return _rows_from_payload(scenario["payload"], options, _arc_options(service, project_data))
    raise PreventUpdate


def toggle_choc_val_callback(kind):
    """Affiche le slider « Ur forcé » de la ligne si (et seulement si) ce type."""
    return _slider_style(kind == CHOC_UR)


def evaluate_scenario_callback(
    n_clicks,
    node_values,
    node_ids,
    kind_values,
    kind_ids,
    val_values,
    val_ids,
    arc_values,
    arc_ids,
    project_data,
):
    """Évalue le scénario composite : tableau comparatif, DAG des ΔUr, messages.

    PURETÉ : tout passe par :meth:`MoteurScenario.evaluer` — aucune écriture,
    ni dans le dépôt ni dans les ``UrgencyState`` (rien à « appliquer » ici,
    l'application réelle reste la carte statut dédiée).
    """
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    scenario = _scenario_from_rows(
        "scénario",
        node_values,
        node_ids,
        kind_values,
        kind_ids,
        val_values,
        val_ids,
        arc_values,
        arc_ids,
    )
    if not (scenario.surcharges_ur or scenario.statuts or scenario.arcs_supprimes):
        message = html.Span(
            "Aucun choc complet : ajoutez au moins une ligne (nœud + type de choc).",
            style=MSG_ALERT_STYLE,
        )
        return [], empty_figure("Ajoutez au moins un choc."), message

    moteur = MoteurScenario(service.repo, service.propagation)
    try:
        resultat = moteur.evaluer(scenario)
    except ValueError as exc:
        message = html.Span(f"Scénario invalide : {exc}", style=MSG_ALERT_STYLE)
        return [], empty_figure("Scénario invalide."), message

    nodes = _project_nodes(service, project_data)
    ids = {n.id for n in nodes}
    arcs = [a for a in service.repo.arcs() if a.source_id in ids and a.target_id in ids]
    data = _table_comparative(resultat, nodes)
    fig = shock_dag_figure(nodes, arcs, resultat.delta_ur)

    impactes = {n.id: resultat.delta_ur.get(n.id, 0.0) for n in nodes}
    impactes = {nid: d for nid, d in impactes.items() if abs(d) > _EPS_DELTA}
    if impactes:
        names = {n.id: n.name for n in nodes}
        worst = max(impactes, key=lambda nid: abs(impactes[nid]))
        texte = (
            f"Scénario évalué : {len(impactes)} nœud(s) impacté(s), "
            f"ΔUr max = {_fr(impactes[worst], signe=True)} sur « {names.get(worst, worst)} ». "
            "Évaluation pure, rien n'est persisté."
        )
        spans: list = [html.Span(texte, style=MSG_WARN_STYLE)]
    else:
        spans = [
            html.Span(
                "Aucun nœud impacté : tous les ΔUr du scénario sont nuls.",
                style=MSG_WARN_STYLE,
            )
        ]
    spans += [html.Div(avert, style=MSG_WARN_STYLE) for avert in resultat.avertissements]
    return data, fig, html.Div(spans)


def criticite_callback(n_clicks, project_data):
    """Analyse de criticité systématique du projet actif → tornado top 15."""
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    pid = (project_data or {}).get("project_id")
    if not pid:
        return empty_figure("Sélectionnez d'abord un projet (page Projets).")
    try:
        points = ServiceCriticite(service).top(pid, 15)
    except ValueError as exc:
        return empty_figure(str(exc))
    return criticite_tornado_figure(points, top=15)


def scenario_registry_callback(
    save_clicks,
    delete_clicks,
    project_data,
    name,
    scn_id,
    node_values,
    node_ids,
    kind_values,
    kind_ids,
    val_values,
    val_ids,
    arc_values,
    arc_ids,
):
    """Sauvegarde/suppression des scénarios nommés + options du dropdown.

    La sauvegarde sérialise le scénario COURANT (les lignes du formulaire) en
    JSON via :func:`_payload_json` — id ``uuid4``, horodatage = horloge du
    service ; un doublon de nom (ValueError du registre) est affiché tel quel.
    Déclenché aussi par ``store-project`` pour peupler le dropdown à l'arrivée
    sur la page (message vide dans ce cas).
    """
    service = get_service()
    pid = (project_data or {}).get("project_id")
    triggered = _triggered_id()
    message: Any = ""
    if triggered == "sim-scn-save-btn" and save_clicks:
        nom = str(name or "").strip()
        if not pid:
            message = html.Span(
                "Sélectionnez d'abord un projet (page Projets).", style=MSG_ALERT_STYLE
            )
        elif not nom:
            message = html.Span(
                "Donnez un nom au scénario avant de sauvegarder.", style=MSG_ALERT_STYLE
            )
        else:
            scenario = _scenario_from_rows(
                nom,
                node_values,
                node_ids,
                kind_values,
                kind_ids,
                val_values,
                val_ids,
                arc_values,
                arc_ids,
            )
            try:
                service.registry.save_scenario(
                    uuid4().hex, pid, nom, _payload_json(scenario), now=service.clock.now()
                )
                message = html.Span(f"Scénario « {nom} » sauvegardé.", style=MSG_OK_STYLE)
            except ValueError as exc:
                message = html.Span(f"Sauvegarde refusée : {exc}", style=MSG_ALERT_STYLE)
    elif triggered == "sim-scn-del-btn" and delete_clicks:
        if scn_id:
            service.registry.delete_scenario(scn_id)
            message = html.Span("Scénario supprimé.", style=MSG_OK_STYLE)
        else:
            message = html.Span(
                "Choisissez d'abord un scénario à supprimer.", style=MSG_ALERT_STYLE
            )
    return _scenario_options(service, pid), message


#: États partagés des lignes dynamiques (chocs + ruptures d'arc), dans l'ordre
#: des paramètres ``node_values, node_ids, ..., arc_values, arc_ids``.
_ROWS_STATES = (
    State({"type": "sim-choc-node", "index": ALL}, "value"),
    State({"type": "sim-choc-node", "index": ALL}, "id"),
    State({"type": "sim-choc-kind", "index": ALL}, "value"),
    State({"type": "sim-choc-kind", "index": ALL}, "id"),
    State({"type": "sim-choc-val", "index": ALL}, "value"),
    State({"type": "sim-choc-val", "index": ALL}, "id"),
    State({"type": "sim-arc-del", "index": ALL}, "value"),
    State({"type": "sim-arc-del", "index": ALL}, "id"),
)


def register_callbacks(app) -> None:
    """Enregistre les callbacks de la page Simulation sur l'application Dash."""
    app.callback(
        Output("sim-node-dd", "options"),
        Input("store-project", "data"),
    )(node_options_callback)

    app.callback(
        Output("sim-ur-slider", "value"),
        Input("sim-preset-fail", "n_clicks"),
        Input("sim-preset-ok", "n_clicks"),
        prevent_initial_call=True,
    )(preset_callback)

    app.callback(
        Output("sim-dag-fig", "figure"),
        Output("sim-bar-fig", "figure"),
        Output("sim-summary", "children"),
        Input("sim-run-btn", "n_clicks"),
        State("sim-node-dd", "value"),
        State("sim-ur-slider", "value"),
        State("store-project", "data"),
        prevent_initial_call=True,
    )(simulate_callback)

    app.callback(
        Output("sim-apply-msg", "children"),
        Input("sim-apply-confirm", "submit_n_clicks"),
        State("sim-node-dd", "value"),
        State("sim-status-dd", "value"),
        prevent_initial_call=True,
    )(apply_status_callback)

    app.callback(
        Output("sim-chocs-rows", "children"),
        Input("sim-add-choc-btn", "n_clicks"),
        Input("sim-add-arc-btn", "n_clicks"),
        Input("sim-preset-add-btn", "n_clicks"),
        Input("sim-scn-load-btn", "n_clicks"),
        State("sim-chocs-rows", "children"),
        State("sim-preset-dd", "value"),
        State("sim-scn-dd", "value"),
        State("store-project", "data"),
        prevent_initial_call=True,
    )(rows_callback)

    app.callback(
        Output({"type": "sim-choc-val-wrap", "index": MATCH}, "style"),
        Input({"type": "sim-choc-kind", "index": MATCH}, "value"),
        prevent_initial_call=True,
    )(toggle_choc_val_callback)

    app.callback(
        Output("sim-scn-table", "data"),
        Output("sim-scn-dag-fig", "figure"),
        Output("sim-eval-msg", "children"),
        Input("sim-eval-btn", "n_clicks"),
        *_ROWS_STATES,
        State("store-project", "data"),
        prevent_initial_call=True,
    )(evaluate_scenario_callback)

    app.callback(
        Output("sim-crit-fig", "figure"),
        Input("sim-crit-btn", "n_clicks"),
        State("store-project", "data"),
        prevent_initial_call=True,
    )(criticite_callback)

    app.callback(
        Output("sim-scn-dd", "options"),
        Output("sim-scn-msg", "children"),
        Input("sim-scn-save-btn", "n_clicks"),
        Input("sim-scn-del-btn", "n_clicks"),
        Input("store-project", "data"),
        State("sim-scn-name", "value"),
        State("sim-scn-dd", "value"),
        *_ROWS_STATES,
    )(scenario_registry_callback)
