"""Fiche nœud 360° — vue d'ensemble par cartes et réédition section par section.

La page expose ``layout(node_id)`` et :func:`register_callbacks` ; le routage
``/node/<id>`` est branché par la tâche d'intégration E5.I dans ``app.py``.

Principes de conception :

- **Mêmes payloads, mêmes validations que le wizard** : chaque bouton
  « Enregistrer » passe par :meth:`OnboardingService.save_section` (étapes 1,
  2 et 3), donc par :class:`MutationService` (diff + validation + audit,
  ``source='onboarding'``). En cas d'erreur, RIEN n'est écrit : les messages
  français s'affichent au-dessus du formulaire, valeurs saisies conservées.
- **Un seul bloc en édition à la fois** : ``dcc.Store(id="store-fiche")``
  mémorise ``{"node_id", "editing"}`` ; cliquer « Modifier » sur une carte
  re-rend les trois cartes éditables (les deux autres repassent en lecture).
  Les boutons « Modifier » restent montés dans l'EN-TÊTE des cartes (inputs
  stables pour Dash) ; seul le CORPS de la carte bascule lecture/édition.
- **Resauver le cahier des charges remplace les jalons** (delete + recreate,
  sémantique du wizard) : la carte « Jalons » est donc re-rendue par
  :func:`save_cdc_callback`. Les clauses de pénalité et les notes de la
  version courante, non éditables dans le formulaire, sont reportées telles
  quelles dans la nouvelle version.
- **Historique d'audit fusionné** (choix documenté) : UNE seule table
  ``history_table`` mêle les entrées de la base client (``node_kpis``) et du
  registre (``node`` + arcs touchant le nœud), triées par timestamp
  décroissant et tronquées aux 50 dernières.
- Les scores du bandeau ne sont PAS recalculés après une sauvegarde (comme
  dans le wizard, seul ``complete()`` relance ``evaluate_all``) : ils
  reflètent la dernière évaluation persistée.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from datetime import datetime
from typing import Any

from dash import ALL, Input, Output, State, dash_table, dcc, html, no_update
from dash.exceptions import PreventUpdate

from supplyscore.data.audit import AuditEntry, AuditTrail
from supplyscore.data.db import kpis_from_json, kpis_to_json
from supplyscore.domain.constraints import KPI_CONSTRAINTS
from supplyscore.domain.milestones import Milestone, MilestoneStatus, theoretical_progress
from supplyscore.domain.models import KPIBundle
from supplyscore.domain.specsheet import cdc_from_json
from supplyscore.services.onboarding import OnboardingService
from supplyscore.services.weekly import CycleHebdomadaire
from supplyscore.web_ui import get_service
from supplyscore.web_ui.components.badges import badge_hebdo, draft_badge
from supplyscore.web_ui.components.figures import empty_figure
from supplyscore.web_ui.components.forms_node import (
    MILESTONE_KIND_OPTIONS,
    cdc_form,
    deliverable_row,
    identity_form,
    kpi_guided_form,
    milestone_row,
    parse_cdc,
    parse_identity,
    parse_kpis,
)
from supplyscore.web_ui.components.history import history_table, kpi_trajectory_figure
from supplyscore.web_ui.components.layout import (
    BUTTON_SECONDARY_STYLE,
    BUTTON_STYLE,
    CARD_STYLE,
    COLORS,
    FONT_FAMILY,
    MSG_ALERT_STYLE,
    MSG_OK_STYLE,
    PAGE_STYLE,
    STATUS_FR,
    card,
    node_options,
)
from supplyscore.web_ui.components.operator import current_operator
from supplyscore.web_ui.pages.questionnaire import KPI_FIELDS

#: Nombre maximal d'entrées affichées dans le journal d'audit de la fiche.
_AUDIT_LIMIT = 50

#: Bouton « Modifier » -> section du store ``store-fiche`` qu'il bascule.
_EDIT_BUTTONS: dict[str, str] = {
    "fiche-edit-identity-btn": "identity",
    "fiche-edit-cdc-btn": "cdc",
    "fiche-edit-kpis-btn": "kpis",
}

#: Libellés français des types de jalon (mêmes options que le formulaire).
_MS_KIND_FR: dict[str, str] = {opt["value"]: opt["label"] for opt in MILESTONE_KIND_OPTIONS}

#: Libellés français des statuts de jalon.
_MS_STATUS_FR: dict[MilestoneStatus, str] = {
    MilestoneStatus.ACTIVE: "Actif",
    MilestoneStatus.DONE: "Terminé",
    MilestoneStatus.ABANDONED: "Abandonné",
}

# Styles alignés sur les DataTable existantes (dashboard, historique).
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

_CHIP_STYLE = {
    "display": "inline-block",
    "padding": "3px 12px",
    "borderRadius": "10px",
    "backgroundColor": "#eef2f5",
    "color": COLORS["text"],
    "fontSize": "13px",
    "fontWeight": "600",
    "fontFamily": FONT_FAMILY,
    "marginRight": "8px",
    "whiteSpace": "nowrap",
}

_STATUS_PILL_STYLE = {
    "display": "inline-block",
    "padding": "2px 10px",
    "borderRadius": "10px",
    "backgroundColor": "#e4ebf1",
    "color": COLORS["primary"],
    "fontSize": "12px",
    "fontWeight": "600",
    "fontFamily": FONT_FAMILY,
    "whiteSpace": "nowrap",
}

_MUTED_STYLE = {"color": COLORS["muted"], "margin": "2px 0"}


# --- Aides de mise en forme -----------------------------------------------------------


def _fmt(value: float | None, digits: int = 2) -> str:
    """Formate un score optionnel (« — » si jamais évalué)."""
    return "—" if value is None else f"{value:.{digits}f}"


def _fmt_date(ts: float | None) -> str:
    """Date locale « JJ/MM/AAAA » d'un epoch (« — » si non renseignée)."""
    if ts is None or ts <= 0:
        return "—"
    return datetime.fromtimestamp(float(ts)).strftime("%d/%m/%Y")


def _project_clock(service: Any, node: Any) -> Any:
    """Horloge effective du projet du nœud (horloge du service si sans projet)."""
    return service.clock_for(node.project_id) if node.project_id else service.clock


def _errors_block(errors: list[str] | None) -> list:
    """Liste rouge des erreurs de validation (vide si aucune erreur)."""
    if not errors:
        return []
    items = [html.Li(message, style=MSG_ALERT_STYLE) for message in errors]
    return [html.Ul(items, style={"paddingLeft": "18px", "margin": "0 0 10px"})]


def _message_block(message: str | None) -> list:
    """Message vert de succès (vide si aucun message)."""
    if not message:
        return []
    return [html.P(message, style=MSG_OK_STYLE)]


def _field_line(label: str, value: str) -> html.P:
    """Ligne « Libellé : valeur » d'une vue lecture."""
    return html.P([html.Strong(f"{label} : "), value], style={"margin": "2px 0"})


def _score_chip(label: str, value: float | None, digits: int = 2) -> html.Span:
    """Pastille de score du bandeau, ex. « Ud 0.42 » (« — » si jamais évalué)."""
    return html.Span(f"{label} {_fmt(value, digits)}", style=_CHIP_STYLE)


def _status_pill(node: Any) -> html.Span:
    """Badge du statut de tâche du nœud (libellés :data:`STATUS_FR`)."""
    return html.Span(STATUS_FR.get(node.status, str(node.status)), style=_STATUS_PILL_STYLE)


# --- Bandeau ---------------------------------------------------------------------------


def _header(service: Any, node: Any) -> html.Div:
    """Bandeau : nom, label/rang, badges (statut, hebdo, brouillon) et scores."""
    etat = CycleHebdomadaire(service).statut_noeud(node.id)
    badges: list = [_status_pill(node), badge_hebdo(etat.statut, etat.semaines_de_retard)]
    if node.onboarding_state == "draft":
        badges.append(draft_badge())
    urgency = node.urgency
    scores = [
        _score_chip("Ud", urgency.ud),
        _score_chip("Ur", urgency.ur),
        _score_chip("A", urgency.adequation, digits=1),
        _score_chip("F", urgency.false_urgency),
        _score_chip("H", urgency.hidden_risk),
    ]
    return html.Div(
        [
            html.H2(node.name, style={"margin": "6px 0 4px"}),
            html.Div(
                [
                    html.Span(
                        f"{node.label} — rang {node.rank}",
                        style={"color": COLORS["muted"], "marginRight": "12px"},
                    ),
                    *badges,
                ],
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "gap": "8px",
                    "flexWrap": "wrap",
                    "marginBottom": "8px",
                },
            ),
            html.Div(scores, style={"marginBottom": "6px"}),
            dcc.Link(
                "Pourquoi ces scores ? → explication détaillée",
                href=f"/node/{node.id}/explication",
                style={"fontSize": "13px", "color": COLORS["primary"]},
            ),
            html.Div(style={"marginBottom": "14px"}),
        ]
    )


# --- Corps des cartes éditables (vues lecture) ------------------------------------------


def _identity_read(service: Any, node: Any, message: str | None = None) -> html.Div:
    """Vue lecture de la carte « Identité & tags » (tags et connexions aval)."""
    registry = service.registry
    tags = registry.tags_of_node(node.id)
    names = {n.id: n.name for n in registry.list_nodes(node.project_id)}
    arcs = [a for a in registry.list_arcs() if a.source_id == node.id]
    if arcs:
        connections: Any = html.Ul(
            [
                html.Li(
                    f"{names.get(a.target_id, a.target_id)} — "
                    f"γ {a.gamma:g}, β {a.beta:g} ({a.kind_arc})"
                )
                for a in arcs
            ],
            style={"margin": "2px 0", "paddingLeft": "18px"},
        )
    else:
        connections = html.P("Aucune connexion aval.", style=_MUTED_STYLE)
    children = [
        *_message_block(message),
        _field_line("Nom", node.name),
        _field_line("Label métier", node.label),
        _field_line("Localisation", node.location or "—"),
        _field_line("Tags", ", ".join(t.name for t in tags) or "—"),
        html.P(html.Strong("Connexions aval :"), style={"margin": "8px 0 2px"}),
        connections,
    ]
    return html.Div(children)


def _deliverable_label(deliverable: Any) -> str:
    """Libellé d'un livrable : « nom — quantité unité » (« — » si manquant)."""
    quantity = "—" if deliverable.quantity is None else f"{deliverable.quantity:g}"
    return f"{deliverable.name or '—'} — {quantity} {deliverable.unit}".rstrip()


def _cdc_read(service: Any, node: Any, message: str | None = None) -> html.Div:
    """Vue lecture du cahier des charges : budget, livrables, qualité, versions."""
    client = service.client_db(node.id)
    latest = client.latest_spec_sheet(node.id)
    if latest is None:
        empty = html.P("Aucun cahier des charges enregistré pour ce nœud.", style=_MUTED_STYLE)
        return html.Div([*_message_block(message), empty])
    version, payload_json = latest
    cdc = cdc_from_json(payload_json)
    versions = client.spec_sheet_versions(node.id)
    budget = f"{cdc.budget_total:g} {cdc.currency}" if cdc.budget_total is not None else "—"
    unit_cost = (
        f"{cdc.target_unit_cost:g} {cdc.currency}" if cdc.target_unit_cost is not None else "—"
    )
    if cdc.deliverables:
        deliverables: Any = html.Ul(
            [html.Li(_deliverable_label(d)) for d in cdc.deliverables],
            style={"margin": "2px 0", "paddingLeft": "18px"},
        )
    else:
        deliverables = html.P("Aucun livrable déclaré.", style=_MUTED_STYLE)
    quality = cdc.quality
    scrap = f"{quality.max_scrap_rate:g}" if quality.max_scrap_rate is not None else "—"
    penalties = (
        f"{len(cdc.penalties)} clause(s) de pénalité." if cdc.penalties else "Aucune clause."
    )
    children = [
        *_message_block(message),
        _field_line("Budget total", budget),
        _field_line("Coût unitaire cible", unit_cost),
        html.P(html.Strong("Livrables :"), style={"margin": "8px 0 2px"}),
        deliverables,
        _field_line("Normes", ", ".join(quality.standards) or "—"),
        _field_line("Certifications", ", ".join(quality.certifications) or "—"),
        _field_line("Taux de rebut max", scrap),
        _field_line("Pénalités", penalties),
        _field_line("Version courante", f"v{version} ({len(versions)} version(s))"),
    ]
    return html.Div(children)


def _kpis_read(node: Any, message: str | None = None) -> html.Div:
    """Vue lecture des KPIs courants : tableau compact « valeur + unité » par bloc."""
    rows = []
    for block_title, fields in KPI_FIELDS:
        for key, label_text in fields:
            block, field_name = key.split(".", 1)
            value = getattr(getattr(node.kpis, block), field_name)
            _lo, _hi, unit = KPI_CONSTRAINTS.get(key, (None, None, ""))
            rows.append(
                {
                    "Bloc": block_title,
                    "Indicateur": label_text,
                    "Valeur": "—" if value is None else f"{value:g} {unit}".rstrip(),
                }
            )
    table = dash_table.DataTable(  # type: ignore[attr-defined]
        id="fiche-kpi-table",
        columns=[{"name": c, "id": c} for c in ("Bloc", "Indicateur", "Valeur")],
        data=rows,
        editable=False,
        sort_action="none",
        style_cell=_TABLE_STYLE_CELL,
        style_header=_TABLE_STYLE_HEADER,
        style_as_list_view=True,
    )
    return html.Div([*_message_block(message), table])


# --- Corps des cartes éditables (vues édition) ------------------------------------------


def _identity_edit(
    service: Any,
    node: Any,
    errors: list[str] | None = None,
    values: dict | None = None,
) -> html.Div:
    """Vue édition de l'identité : formulaire partagé pré-rempli + Enregistrer.

    Args:
        service: façade applicative partagée.
        node: nœud édité (état registre).
        errors: erreurs de validation à afficher au-dessus du formulaire.
        values: payload soumis (re-soumission après erreur) ; ``None`` ->
            pré-remplissage depuis l'état courant du registre.
    """
    registry = service.registry
    tag_options = [
        {"label": t.name, "value": t.name} for t in registry.list_tags(node.project_id or "")
    ]
    candidates = [n for n in registry.list_nodes(node.project_id) if n.id != node.id]
    if values is None:
        values = {
            "name": node.name,
            "label": node.label,
            "location": node.location or "",
            "tags": [t.name for t in registry.tags_of_node(node.id)],
            "connections": [
                {
                    "target_id": a.target_id,
                    "gamma": a.gamma,
                    "beta": a.beta,
                    "kind": str(a.kind_arc),
                }
                for a in registry.list_arcs()
                if a.source_id == node.id
            ],
        }
    form = identity_form(
        "fiche",
        name=str(values.get("name") or ""),
        label=str(values.get("label") or node.label),
        location=str(values.get("location") or ""),
        selected_tags=[str(t) for t in (values.get("tags") or [])],
        tag_options=tag_options,
        node_options=node_options(candidates),
        connections=list(values.get("connections") or []),
    )
    save = html.Button("Enregistrer", id="fiche-save-identity-btn", style=BUTTON_STYLE)
    return html.Div([*_errors_block(errors), form, save])


def _cdc_edit(
    service: Any,
    node: Any,
    errors: list[str] | None = None,
    cdc: Any = None,
    milestones: list[Milestone] | None = None,
) -> html.Div:
    """Vue édition du cahier des charges : formulaire partagé + Enregistrer.

    Args:
        service: façade applicative partagée.
        node: nœud édité.
        errors: erreurs de validation à afficher au-dessus du formulaire.
        cdc: cahier des charges de pré-remplissage (``None`` -> version
            courante de la base client).
        milestones: jalons de pré-remplissage (``None`` -> jalons du registre).
    """
    if cdc is None:
        latest = service.client_db(node.id).latest_spec_sheet(node.id)
        cdc = cdc_from_json(latest[1]) if latest is not None else None
    if milestones is None:
        milestones = service.registry.list_milestones(node.id)
    form = cdc_form("fiche", cdc=cdc, milestones=milestones)
    save = html.Button("Enregistrer", id="fiche-save-cdc-btn", style=BUTTON_STYLE)
    return html.Div([*_errors_block(errors), form, save])


def _kpis_edit(
    node: Any, errors: list[str] | None = None, kpis: KPIBundle | None = None
) -> html.Div:
    """Vue édition des KPIs : saisie guidée pré-remplie + Enregistrer."""
    form = kpi_guided_form("fiche", kpis if kpis is not None else node.kpis)
    save = html.Button("Enregistrer", id="fiche-save-kpis-btn", style=BUTTON_STYLE)
    return html.Div([*_errors_block(errors), form, save])


def _section_body(service: Any, node: Any, section: str, editing: str | None) -> html.Div:
    """Corps d'une carte éditable : édition si ``editing == section``, lecture sinon."""
    if section == "identity":
        if editing == section:
            return _identity_edit(service, node)
        return _identity_read(service, node)
    if section == "cdc":
        if editing == section:
            return _cdc_edit(service, node)
        return _cdc_read(service, node)
    if editing == section:
        return _kpis_edit(node)
    return _kpis_read(node)


# --- Cartes lecture seule ----------------------------------------------------------------


def _milestones_body(service: Any, node: Any) -> Any:
    """Tableau des jalons : avancement déclaré vs THÉORIQUE (horloge du projet)."""
    milestones = service.registry.list_milestones(node.id)
    if not milestones:
        return html.P("Aucun jalon pour ce nœud.", style=_MUTED_STYLE)
    now_ts = _project_clock(service, node).now()
    rows = []
    for milestone in sorted(milestones, key=lambda m: (m.position, m.deadline_ts)):
        progress_th = theoretical_progress(milestone, now_ts)
        rows.append(
            {
                "Nom": milestone.name,
                "Type": _MS_KIND_FR.get(milestone.kind, milestone.kind),
                "Début": _fmt_date(milestone.start_ts),
                "Échéance": _fmt_date(milestone.deadline_ts),
                "Statut": _MS_STATUS_FR.get(milestone.status, str(milestone.status)),
                "Avancement": (
                    f"{milestone.progress * 100:.0f} % / théorique {progress_th * 100:.0f} %"
                ),
            }
        )
    columns = ("Nom", "Type", "Début", "Échéance", "Statut", "Avancement")
    return dash_table.DataTable(  # type: ignore[attr-defined]
        id="fiche-ms-table",
        columns=[{"name": c, "id": c} for c in columns],
        data=rows,
        editable=False,
        sort_action="none",
        style_cell=_TABLE_STYLE_CELL,
        style_header=_TABLE_STYLE_HEADER,
        style_as_list_view=True,
    )


def _ahp_children(service: Any, node: Any) -> list:
    """Dernière évaluation AHP + figure d'historique du Ud (``urgency_series``)."""
    client = service.client_db(node.id)
    latest = client.latest_assessment(node.id)
    if latest is None:
        info = html.P("Aucune évaluation AHP pour ce nœud.", style=_MUTED_STYLE)
    else:
        info = html.P(
            f"Dernière évaluation : Ud = {latest.ud:.3f} — "
            f"CR = {latest.consistency_ratio:.3f} — "
            f"opérateur « {latest.operator_id} » — semaine {latest.iso_week}."
        )
    points = [(s.timestamp, s.ud) for s in client.urgency_series(node.id) if s.ud is not None]
    if points:
        # Réutilisation documentée : la trajectoire en escalier du composant
        # d'historique convient au Ud (une valeur tient entre deux saisies).
        figure = kpi_trajectory_figure(points, "Ud")
    else:
        figure = empty_figure("Aucun historique de Ud — première évaluation attendue.")
    return [info, dcc.Graph(id="fiche-ud-history", figure=figure)]


def _audit_entries(service: Any, node: Any) -> list[AuditEntry]:
    """50 dernières entrées d'audit du nœud : base client + registre fusionnés.

    Choix documenté : UNE seule table fusionnée plutôt que deux — les entrées
    ``node_kpis`` (base client du nœud) et ``node``/``arc`` (registre, arcs
    touchant le nœud) sont triées ensemble par timestamp décroissant puis
    tronquées à :data:`_AUDIT_LIMIT`.
    """
    clock = _project_clock(service, node)
    client = service.client_db(node.id)
    entries = AuditTrail(client.conn, clock, client.lock).history(
        "node_kpis", node.id, limit=_AUDIT_LIMIT
    )
    registry = service.registry
    registry_trail = AuditTrail(registry.conn, clock, registry.lock)
    entries += registry_trail.history("node", node.id, limit=_AUDIT_LIMIT)
    for arc in registry.list_arcs():
        if node.id in (arc.source_id, arc.target_id):
            entries += registry_trail.history("arc", arc.id, limit=_AUDIT_LIMIT)
    entries.sort(key=lambda entry: (entry.timestamp, entry.id), reverse=True)
    return entries[:_AUDIT_LIMIT]


def _editable_card(title: str, section: str, body: Any, subtitle: str | None = None) -> html.Div:
    """Carte avec bouton « Modifier » dans l'en-tête et corps re-rendable.

    Le bouton (id ``fiche-edit-<section>-btn``) reste TOUJOURS monté — c'est
    le corps (id ``fiche-<section>-body``) qui bascule lecture/édition.
    """
    header = html.Div(
        [
            html.H3(title, style={"margin": "0", "fontSize": "17px"}),
            html.Button(
                "Modifier",
                id=f"fiche-edit-{section}-btn",
                style={**BUTTON_SECONDARY_STYLE, "marginLeft": "auto", "padding": "5px 14px"},
            ),
        ],
        style={"display": "flex", "alignItems": "center", "marginBottom": "6px"},
    )
    children: list = [header]
    if subtitle:
        children.append(
            html.P(
                subtitle,
                style={"margin": "0 0 12px", "fontSize": "13px", "color": COLORS["muted"]},
            )
        )
    children.append(html.Div(body, id=f"fiche-{section}-body"))
    return html.Div(children, style=CARD_STYLE)


# --- Layout ------------------------------------------------------------------------------


def layout(node_id: str) -> html.Div:
    """Construit la fiche 360° du nœud (« Nœud introuvable » si id inconnu).

    Args:
        node_id: identifiant du nœud (segment de l'URL ``/node/<id>``).
    """
    service = get_service()
    node = service.repo.get_node(node_id) or service.registry.get_node(node_id)
    if node is None:
        return html.Div(
            [
                html.H2("Fiche nœud", style={"margin": "6px 0 6px"}),
                html.P(f"Nœud introuvable : « {node_id} ».", style=MSG_ALERT_STYLE),
            ],
            style=PAGE_STYLE,
        )
    return html.Div(
        [
            dcc.Store(id="store-fiche", data={"node_id": node_id, "editing": None}),
            _header(service, node),
            _editable_card(
                "Identité & tags",
                "identity",
                _identity_read(service, node),
                subtitle="Nom, label, localisation, tags et connexions aval (section 1).",
            ),
            _editable_card(
                "Cahier des charges",
                "cdc",
                _cdc_read(service, node),
                subtitle=(
                    "Budget, qualité, livrables et jalons (section 2) — "
                    "resauver remplace les jalons."
                ),
            ),
            card(
                "Jalons",
                [html.Div(_milestones_body(service, node), id="fiche-milestones-body")],
                subtitle="Avancement déclaré vs théorique, selon l'horloge du projet.",
            ),
            _editable_card(
                "KPIs courants",
                "kpis",
                _kpis_read(node),
                subtitle="Tableau compact par bloc (section 3) — champs vides ignorés.",
            ),
            card("Évaluations AHP", _ahp_children(service, node)),
            card(
                "Historique d'audit",
                [history_table(_audit_entries(service, node))],
                subtitle=(
                    "50 dernières entrées — base client (KPIs) et registre (nœud, arcs) "
                    "fusionnées par date décroissante."
                ),
            ),
        ],
        style=PAGE_STYLE,
    )


# --- Aides des callbacks -------------------------------------------------------------------


def _triggered_id() -> Any:
    """Id du composant déclencheur (None hors contexte de requête Dash)."""
    try:  # ctx indisponible hors requête Dash (appel direct en test)
        from dash import ctx

        return ctx.triggered_id
    except Exception:
        return None


def _milestones_from_payload(node_id: str, raw: list[dict]) -> list[Milestone]:
    """Jalons d'affichage reconstruits depuis le payload soumis (pré-remplissage)."""
    return [
        Milestone(
            id="",
            node_id=node_id,
            name=str(item.get("name") or ""),
            kind=str(item.get("kind") or "livraison"),
            start_ts=float(item.get("start_ts") or 0.0),
            deadline_ts=float(item.get("deadline_ts") or 0.0),
            position=position,
        )
        for position, item in enumerate(raw)
    ]


def _kpis_with_overrides(kpis: KPIBundle, changes: dict) -> KPIBundle:
    """Copie du bundle avec les valeurs soumises appliquées (pré-remplissage)."""
    bundle = kpis_from_json(kpis_to_json(kpis))
    for path, value in changes.items():
        block, _, field_name = str(path).partition(".")
        block_obj = getattr(bundle, block, None)
        if block_obj is not None and hasattr(block_obj, field_name):
            setattr(block_obj, field_name, value)
    return bundle


# --- Callbacks (fonctions nommées, testables sans serveur) ----------------------------------


def toggle_edit_callback(_n_identity, _n_cdc, _n_kpis, fiche_data):
    """Bascule UNE carte en édition, les deux autres repassant en lecture.

    Re-cliquer « Modifier » sur la carte déjà en édition la repasse en
    lecture. ``store-fiche`` mémorise la section en cours (une seule à la
    fois) ; les trois corps de carte sont re-rendus à chaque bascule.
    """
    section = _EDIT_BUTTONS.get(str(_triggered_id() or ""))
    if section is None:
        raise PreventUpdate
    service = get_service()
    data = dict(fiche_data or {})
    node = service.registry.get_node(str(data.get("node_id") or ""))
    if node is None:
        raise PreventUpdate
    editing = None if data.get("editing") == section else section
    data["editing"] = editing
    return (
        data,
        _section_body(service, node, "identity", editing),
        _section_body(service, node, "cdc", editing),
        _section_body(service, node, "kpis", editing),
    )


def save_identity_callback(
    n_clicks, name, label, location, tags, targets, gamma, beta, arckind, operator_data, fiche_data
):
    """Enregistre la section identité (mêmes payload/validations que le wizard).

    Parse les champs via :func:`parse_identity` (la clé ``tags`` est dupliquée
    en ``tag_names``, clé attendue par ``save_section``), puis écrit via
    :meth:`OnboardingService.save_section` (étape 1) avec l'opérateur du store
    global. En cas d'erreur, rien n'est écrit et le formulaire est re-rendu
    avec les valeurs soumises et les messages.

    Returns:
        Le corps de la carte identité (lecture si succès, formulaire + erreurs
        sinon) et le contenu de ``store-fiche``.
    """
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    data = dict(fiche_data or {})
    node_id = str(data.get("node_id") or "")
    node = service.registry.get_node(node_id)
    if node is None:
        return html.P("Nœud introuvable.", style=MSG_ALERT_STYLE), data
    payload = parse_identity(
        {
            "name": name,
            "label": label,
            "location": location,
            "tags": tags,
            "targets": targets,
            "gamma": gamma,
            "beta": beta,
            "arckind": arckind,
        }
    )
    payload["tag_names"] = list(payload["tags"])  # clé attendue par save_section
    result = OnboardingService(service).save_section(
        node_id, 1, payload, operator_id=current_operator(operator_data)
    )
    if not result.ok:
        return _identity_edit(service, node, errors=result.errors, values=payload), data
    data["editing"] = None
    fresh = service.registry.get_node(node_id) or node
    return _identity_read(service, fresh, message="Identité enregistrée."), data


def save_cdc_callback(
    n_clicks,
    dlv_names,
    dlv_qtys,
    dlv_units,
    ms_names,
    ms_kinds,
    ms_starts,
    ms_deadlines,
    budget,
    unitcost,
    currency,
    standards,
    certifications,
    scrap,
    operator_data,
    fiche_data,
):
    """Enregistre le cahier des charges + jalons (nouvelle version ``spec_sheet``).

    Le payload de :func:`parse_cdc` est remballé au format attendu par
    ``save_section`` (étape 2) : ``{"cdc": {...}, "milestones": [...]}``. Les
    pénalités et notes de la version courante, non éditables ici, sont
    reportées telles quelles. La carte « Jalons » est re-rendue : la
    sauvegarde REMPLACE les jalons (sémantique du wizard).

    Returns:
        Le corps de la carte cahier des charges, celui de la carte jalons
        (``no_update`` en cas d'erreur) et le contenu de ``store-fiche``.
    """
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    data = dict(fiche_data or {})
    node_id = str(data.get("node_id") or "")
    node = service.registry.get_node(node_id)
    if node is None:
        return html.P("Nœud introuvable.", style=MSG_ALERT_STYLE), no_update, data
    extras = {
        "budget": budget,
        "unitcost": unitcost,
        "currency": currency,
        "standards": standards,
        "certifications": certifications,
        "scrap": scrap,
    }
    parsed = parse_cdc(
        dlv_names or [],
        dlv_qtys or [],
        dlv_units or [],
        ms_names or [],
        ms_kinds or [],
        ms_starts or [],
        ms_deadlines or [],
        extras,
    )
    cdc_dict: dict[str, Any] = {
        "deliverables": parsed["deliverables"],
        "budget_total": parsed["budget_total"],
        "target_unit_cost": parsed["target_unit_cost"],
        "currency": parsed["currency"],
        "quality": parsed["quality"],
    }
    latest = service.client_db(node_id).latest_spec_sheet(node_id)
    if latest is not None:  # pénalités/notes de la version courante conservées
        current = cdc_from_json(latest[1])
        cdc_dict["penalties"] = [dataclasses.asdict(p) for p in current.penalties]
        cdc_dict["notes"] = current.notes
    payload = {"cdc": cdc_dict, "milestones": parsed["milestones"]}
    result = OnboardingService(service).save_section(
        node_id, 2, payload, operator_id=current_operator(operator_data)
    )
    if not result.ok:
        body = _cdc_edit(
            service,
            node,
            errors=result.errors,
            cdc=cdc_from_json(json.dumps(cdc_dict)),
            milestones=_milestones_from_payload(node_id, parsed["milestones"]),
        )
        return body, no_update, data
    data["editing"] = None
    return (
        _cdc_read(service, node, message="Cahier des charges enregistré."),
        _milestones_body(service, node),
        data,
    )


def save_kpis_callback(n_clicks, values, ids, operator_data, fiche_data):
    """Enregistre les KPIs saisis (diff + validation + audit via MutationService).

    Parse les inputs pattern-matching via :func:`parse_kpis` (champs vides
    ignorés) puis écrit via ``save_section`` (étape 3). En cas d'erreur de
    bornes, rien n'est écrit et le formulaire est re-rendu avec les valeurs
    soumises.

    Returns:
        Le corps de la carte KPIs (lecture si succès, formulaire + erreurs
        sinon) et le contenu de ``store-fiche``.
    """
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    data = dict(fiche_data or {})
    node_id = str(data.get("node_id") or "")
    node = service.registry.get_node(node_id)
    if node is None:
        return html.P("Nœud introuvable.", style=MSG_ALERT_STYLE), data
    payload = parse_kpis(values or [], ids or [])
    result = OnboardingService(service).save_section(
        node_id, 3, payload, operator_id=current_operator(operator_data)
    )
    if not result.ok:
        bundle = _kpis_with_overrides(node.kpis, payload)
        return _kpis_edit(node, errors=result.errors, kpis=bundle), data
    data["editing"] = None
    fresh = service.registry.get_node(node_id) or node
    return _kpis_read(fresh, message="KPIs enregistrés."), data


def add_deliverable_callback(n_clicks, children):
    """Ajoute une ligne « livrable » vierge au formulaire cahier des charges."""
    if not n_clicks:
        raise PreventUpdate
    rows = list(children or [])
    rows.append(deliverable_row("fiche", uuid.uuid4().hex[:8]))
    return rows


def add_milestone_callback(n_clicks, children):
    """Ajoute une ligne « jalon » vierge au formulaire cahier des charges."""
    if not n_clicks:
        raise PreventUpdate
    rows = list(children or [])
    rows.append(milestone_row("fiche", uuid.uuid4().hex[:8]))
    return rows


def register_callbacks(app) -> None:
    """Enregistre les callbacks de la fiche nœud sur l'application Dash.

    Les corps de carte et ``store-fiche`` sont aussi écrits par les callbacks
    de sauvegarde : ces sorties partagées portent ``allow_duplicate=True``
    (toutes avec ``prevent_initial_call=True``, exigé par Dash).
    """
    app.callback(
        Output("store-fiche", "data"),
        Output("fiche-identity-body", "children"),
        Output("fiche-cdc-body", "children"),
        Output("fiche-kpis-body", "children"),
        Input("fiche-edit-identity-btn", "n_clicks"),
        Input("fiche-edit-cdc-btn", "n_clicks"),
        Input("fiche-edit-kpis-btn", "n_clicks"),
        State("store-fiche", "data"),
        prevent_initial_call=True,
    )(toggle_edit_callback)

    app.callback(
        Output("fiche-identity-body", "children", allow_duplicate=True),
        Output("store-fiche", "data", allow_duplicate=True),
        Input("fiche-save-identity-btn", "n_clicks"),
        State("fiche-ident-name", "value"),
        State("fiche-ident-label", "value"),
        State("fiche-ident-location", "value"),
        State("fiche-ident-tags", "value"),
        State("fiche-ident-targets", "value"),
        State("fiche-ident-gamma", "value"),
        State("fiche-ident-beta", "value"),
        State("fiche-ident-arckind", "value"),
        State("store-operator", "data"),
        State("store-fiche", "data"),
        prevent_initial_call=True,
    )(save_identity_callback)

    app.callback(
        Output("fiche-cdc-body", "children", allow_duplicate=True),
        Output("fiche-milestones-body", "children"),
        Output("store-fiche", "data", allow_duplicate=True),
        Input("fiche-save-cdc-btn", "n_clicks"),
        State({"type": "fiche-cdc-dlv-name", "index": ALL}, "value"),
        State({"type": "fiche-cdc-dlv-qty", "index": ALL}, "value"),
        State({"type": "fiche-cdc-dlv-unit", "index": ALL}, "value"),
        State({"type": "fiche-cdc-ms-name", "index": ALL}, "value"),
        State({"type": "fiche-cdc-ms-kind", "index": ALL}, "value"),
        State({"type": "fiche-cdc-ms-start", "index": ALL}, "date"),
        State({"type": "fiche-cdc-ms-deadline", "index": ALL}, "date"),
        State("fiche-cdc-budget", "value"),
        State("fiche-cdc-unitcost", "value"),
        State("fiche-cdc-currency", "value"),
        State("fiche-cdc-standards", "value"),
        State("fiche-cdc-certifications", "value"),
        State("fiche-cdc-scrap", "value"),
        State("store-operator", "data"),
        State("store-fiche", "data"),
        prevent_initial_call=True,
    )(save_cdc_callback)

    app.callback(
        Output("fiche-kpis-body", "children", allow_duplicate=True),
        Output("store-fiche", "data", allow_duplicate=True),
        Input("fiche-save-kpis-btn", "n_clicks"),
        State({"type": "fiche-kpi", "index": ALL}, "value"),
        State({"type": "fiche-kpi", "index": ALL}, "id"),
        State("store-operator", "data"),
        State("store-fiche", "data"),
        prevent_initial_call=True,
    )(save_kpis_callback)

    app.callback(
        Output("fiche-cdc-deliverables", "children"),
        Input("fiche-cdc-add-dlv", "n_clicks"),
        State("fiche-cdc-deliverables", "children"),
        prevent_initial_call=True,
    )(add_deliverable_callback)

    app.callback(
        Output("fiche-cdc-milestones", "children"),
        Input("fiche-cdc-add-ms", "n_clicks"),
        State("fiche-cdc-milestones", "children"),
        prevent_initial_call=True,
    )(add_milestone_callback)
