"""Page " Onboarding " : wizard 4 etapes pour integrer un nouveau noeud (E5).

La page s'appuie sur :class:`~supplyscore.services.onboarding.OnboardingService`
(brouillon persiste EN BASE, table ``onboarding_progress``) et sur les
form-builders partages de :mod:`supplyscore.web_ui.components.forms_node`
montes en contexte ``ctx="onb"``. Le ``dcc.Store(id="store-onb")`` ne porte
QUE la position du wizard (``{"node_id", "step"}``) - JAMAIS le brouillon,
qui vit en base.

Tous les callbacks sont des fonctions nommees au niveau module, enregistrees
dans :func:`register_callbacks` - elles restent donc testables sans serveur.
Piege Dash gere partout : les ``State`` pattern-matching des formulaires NON
montes renvoient des listes vides (et les ids simples absents valent None) ;
seuls les etats de l'etape courante sont parses.
"""

from __future__ import annotations

import uuid

from dash import ALL, MATCH, Input, Output, State, dcc, html, no_update
from dash.exceptions import PreventUpdate

from supplyscore.domain.specsheet import cdc_from_json
from supplyscore.services.onboarding import SECTION_KEYS, OnboardingService
from supplyscore.web_ui import get_service
from supplyscore.web_ui.components.badges import completeness_badge, draft_badge
from supplyscore.web_ui.components.forms_node import (
    ahp_form,
    cdc_form,
    deliverable_row,
    identity_form,
    kpi_guided_form,
    milestone_row,
    parse_ahp,
    parse_cdc,
    parse_identity,
    parse_kpis,
)
from supplyscore.web_ui.components.layout import (
    BUTTON_SECONDARY_STYLE,
    BUTTON_STYLE,
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
from supplyscore.web_ui.pages.projects import label_metier_options
from supplyscore.web_ui.pages.questionnaire import pair_label_callback, score_label_callback

#: Titres francais des 4 etapes, alignes sur :data:`SECTION_KEYS`.
STEP_TITLES: tuple[str, str, str, str] = (
    "Identité",
    "Cahier des charges",
    "KPIs",
    "Première évaluation",
)

_MUTED_STYLE = {"color": COLORS["muted"], "fontSize": "14px"}

_STEP_BTN_BASE = {
    "border": f"1px solid {COLORS['border']}",
    "borderRadius": "6px",
    "padding": "8px 14px",
    "fontFamily": FONT_FAMILY,
    "fontSize": "13px",
    "fontWeight": "600",
    "backgroundColor": "#fff",
    "color": COLORS["muted"],
    "cursor": "default",
}

_DRAFT_ROW_STYLE = {
    "display": "flex",
    "alignItems": "center",
    "gap": "12px",
    "padding": "8px 0",
    "borderBottom": f"1px solid {COLORS['border']}",
}


# Aides internes


def _wizard() -> OnboardingService:
    """Instancie le service d'onboarding au-dessus du service partage."""
    return OnboardingService(get_service())


def _clamp_step(value) -> int:
    """Etape bornee dans [1, 4] (valeur absente ou invalide -> 1)."""
    try:
        step = int(value)
    except (TypeError, ValueError):
        step = 1
    return min(max(step, 1), len(SECTION_KEYS))


def _ok(text: str) -> html.Span:
    """Message de succes (vert)."""
    return html.Span(text, style=MSG_OK_STYLE)


def _alert(text: str) -> html.Span:
    """Message d'erreur (rouge)."""
    return html.Span(text, style=MSG_ALERT_STYLE)


def _errors(errors: list[str]) -> html.Ul:
    """Liste a puces des erreurs francaises retournees par le service."""
    return html.Ul(
        [html.Li(e) for e in errors],
        style={**MSG_ALERT_STYLE, "paddingLeft": "20px"},
    )


def _triggered_index() -> str | None:
    """Index pattern-matching du declencheur, ou None hors requete Dash."""
    try:  # ctx indisponible hors requete Dash (appel direct en test)
        from dash import ctx

        triggered = ctx.triggered_id
    except Exception:
        return None
    if isinstance(triggered, dict) and triggered.get("index") is not None:
        return str(triggered["index"])
    return None


def _clicked_index(n_clicks_list, ids) -> str | None:
    """Index du bouton pattern-matching clique.

    Utilise ``ctx.triggered_id`` quand le contexte de requete existe ; en
    appel direct (tests), retombe sur le dernier bouton dont ``n_clicks``
    est truthy.
    """
    index = _triggered_index()
    if index is not None:
        return index
    clicked = [
        str(id_.get("index"))
        for id_, n in zip(ids or [], n_clicks_list or [], strict=False)
        if n and isinstance(id_, dict)
    ]
    return clicked[-1] if clicked else None


def _stepper(step: int, sections_done: dict[str, int]) -> html.Div:
    """Bandeau des 4 etapes : [ok] sur les sections validees, etape courante en avant.

    Les etapes DEJA validees sont cliquables (retour en arriere via
    ``goto_step_callback``) ; les autres restent desactivees.
    """
    items: list = []
    for pos, (key, title) in enumerate(zip(SECTION_KEYS, STEP_TITLES, strict=True), start=1):
        done = bool(sections_done.get(key))
        label = f"✓ {pos}. {title}" if done else f"{pos}. {title}"
        style = dict(_STEP_BTN_BASE)
        if pos == step:
            style.update(
                {
                    "backgroundColor": COLORS["primary"],
                    "borderColor": COLORS["primary"],
                    "color": "#fff",
                }
            )
        elif done:
            style.update({"color": COLORS["ok"], "cursor": "pointer"})
        items.append(
            html.Button(
                label,
                id={"type": "onb-step", "index": str(pos)},
                disabled=not done,
                title=(
                    "Revenir à cette section validée"
                    if done and pos != step
                    else "Section à valider via « Enregistrer et continuer »"
                ),
                style=style,
            )
        )
    return html.Div(
        items,
        style={"display": "flex", "gap": "8px", "flexWrap": "wrap", "marginBottom": "14px"},
    )


def _step_form(service, node, state, step: int) -> html.Div:
    """Formulaire ``ctx="onb"`` de l'etape, pre-rempli depuis brouillon/base.

    Etape 1 : draft " identity " s'il existe, SINON l'etat reel du noeud
    (tags portes, arcs sortants). Etape 2 : derniere version du cahier des
    charges (``latest_spec_sheet`` deserialise) + jalons du registre.
    Etape 3 : KPIs courants du noeud. Etape 4 : questionnaire AHP vierge.
    """
    registry = service.registry
    project_id = node.project_id or ""
    if step == 1:
        draft = state.draft.get("identity") or {}
        if draft:
            name = str(draft.get("name") or "")
            label = str(draft.get("label") or node.label)
            location = str(draft.get("location") or "")
            selected = [str(t) for t in (draft.get("tag_names") or draft.get("tags") or [])]
            connections = [c for c in (draft.get("connections") or []) if isinstance(c, dict)]
        else:
            name = node.name
            label = node.label
            location = node.location or ""
            selected = [t.name for t in registry.tags_of_node(node.id)]
            connections = [
                {"target_id": a.target_id, "gamma": a.gamma, "beta": a.beta, "kind": a.kind_arc}
                for a in registry.list_arcs()
                if a.source_id == node.id
            ]
        candidates = [n for n in registry.list_nodes(project_id) if n.id != node.id]
        tag_options = [{"label": t.name, "value": t.name} for t in registry.list_tags(project_id)]
        return identity_form(
            "onb",
            name=name,
            label=label,
            location=location,
            selected_tags=selected,
            tag_options=tag_options,
            node_options=node_options(candidates),
            connections=connections,
        )
    if step == 2:
        spec = service.client_db(node.id).latest_spec_sheet(node.id)
        cdc = None
        if spec is not None:
            try:
                cdc = cdc_from_json(spec[1])
            except ValueError:  # version illisible : formulaire vierge
                cdc = None
        return cdc_form("onb", cdc=cdc, milestones=registry.list_milestones(node.id))
    if step == 3:
        return kpi_guided_form("onb", node.kpis)
    return ahp_form("onb")


def _section_payload(
    step,
    ident_name,
    ident_label,
    ident_location,
    ident_tags,
    ident_targets,
    ident_gamma,
    ident_beta,
    ident_arckind,
    cdc_budget,
    cdc_unitcost,
    cdc_currency,
    cdc_standards,
    cdc_certifications,
    cdc_scrap,
    dlv_names,
    dlv_qtys,
    dlv_units,
    ms_names,
    ms_kinds,
    ms_starts,
    ms_deadlines,
    kpi_values,
    kpi_ids,
    pair_values,
    pair_ids,
    score_values,
    score_ids,
    ahp_notes,
) -> dict:
    """Payload de section depuis les States des 4 formulaires (ordre _FORM_STATES).

    Seuls les etats de l'etape ``step`` sont parses : les formulaires non
    montes renvoient des listes vides (pattern-matching) ou None (ids
    simples) et sont ignores. Les payloads suivent les contrats de
    ``OnboardingService.save_section`` - notamment ``tag_names`` (section 1)
    et l'enveloppe ``{"cdc": ..., "milestones": ...}`` (section 2).
    """
    if step == 1:
        payload = parse_identity(
            {
                "name": ident_name,
                "label": ident_label,
                "location": ident_location,
                "tags": ident_tags,
                "targets": ident_targets,
                "gamma": ident_gamma,
                "beta": ident_beta,
                "arckind": ident_arckind,
            }
        )
        payload["tag_names"] = payload.pop("tags")  # contrat du service (tags crees par nom)
        return payload
    if step == 2:
        parsed = parse_cdc(
            dlv_names or [],
            dlv_qtys or [],
            dlv_units or [],
            ms_names or [],
            ms_kinds or [],
            ms_starts or [],
            ms_deadlines or [],
            {
                "budget": cdc_budget,
                "unitcost": cdc_unitcost,
                "currency": cdc_currency,
                "standards": cdc_standards,
                "certifications": cdc_certifications,
                "scrap": cdc_scrap,
            },
        )
        return {
            "cdc": {
                "deliverables": parsed["deliverables"],
                "budget_total": parsed["budget_total"],
                "target_unit_cost": parsed["target_unit_cost"],
                "currency": parsed["currency"],
                "quality": parsed["quality"],
            },
            "milestones": parsed["milestones"],
        }
    if step == 3:
        return parse_kpis(kpi_values or [], kpi_ids or [])
    return parse_ahp(
        pair_values or [], pair_ids or [], score_values or [], score_ids or [], ahp_notes
    )


# Layout


def layout() -> html.Div:
    """Construit la page Onboarding (wizard 4 etapes, brouillons en base)."""
    return html.Div(
        [
            dcc.Store(id="store-refresh", data=0),
            dcc.Store(id="store-onb", data={"node_id": None, "step": 1}),
            html.H2("Onboarding", style={"margin": "6px 0 14px"}),
            card(
                "Démarrer un onboarding",
                [
                    labelled(
                        "Nom du nœud",
                        dcc.Input(
                            id="onb-start-name",
                            type="text",
                            placeholder="ex. Atelier usinage",
                            style=INPUT_STYLE,
                        ),
                        width="280px",
                    ),
                    labelled(
                        "Label métier",
                        dcc.Dropdown(
                            id="onb-start-label",
                            options=label_metier_options(),
                            value="Supplier",
                            clearable=False,
                        ),
                        width="200px",
                    ),
                    html.Div(
                        html.Button("Créer le brouillon", id="onb-start-btn", style=BUTTON_STYLE)
                    ),
                ],
                subtitle=(
                    "Le nœud est créé immédiatement en brouillon (rang 0, sans connexion) "
                    "— exige un projet actif (page Projets)."
                ),
            ),
            card(
                "Brouillons en cours",
                [html.Div(id="onb-drafts")],
                subtitle=(
                    "Reprenez un onboarding là où il s'était arrêté : "
                    "le brouillon est persisté en base."
                ),
            ),
            card(
                "Assistant en 4 étapes",
                [
                    # E16.4 - dcc.Loading autour du contenu d'etape (re-rendu serveur a chaque navigation du wizard) : l'id reste sur le html.Div interne.
                    dcc.Loading(type="circle", children=html.Div(id="onb-step-content")),
                    html.Div(
                        [
                            html.Button(
                                "Étape précédente",
                                id="onb-prev-btn",
                                style=BUTTON_SECONDARY_STYLE,
                            ),
                            html.Button(
                                "Enregistrer et continuer",
                                id="onb-next-btn",
                                style={**BUTTON_STYLE, "marginLeft": "10px"},
                            ),
                            html.Button(
                                "Enregistrer le brouillon et quitter",
                                id="onb-draft-btn",
                                style={**BUTTON_SECONDARY_STYLE, "marginLeft": "10px"},
                            ),
                        ],
                        style={"marginTop": "16px"},
                    ),
                    html.Div(id="onb-msg"),
                ],
                subtitle=(
                    "Identité, cahier des charges, KPIs puis première évaluation AHP : "
                    "chaque section validée est écrite immédiatement."
                ),
            ),
        ],
        style=PAGE_STYLE,
    )


# Callbacks (fonctions nommees, testables sans serveur)


def start_onboarding_callback(n_clicks, project_data, name, label, store):
    """Cree IMMEDIATEMENT le noeud en brouillon et pointe le wizard dessus."""
    if not n_clicks:
        raise PreventUpdate
    project_id = (project_data or {}).get("project_id")
    if not project_id:
        return no_update, _alert("Sélectionnez d'abord un projet actif (page Projets).")
    clean = str(name or "").strip()
    if not clean:
        return no_update, _alert("Le nom du nœud est obligatoire.")
    node_id = _wizard().start_draft(str(project_id), clean, str(label or "Supplier"))
    msg = _ok(f"Brouillon « {clean} » créé — déroulez les 4 étapes ci-dessous.")
    return {"node_id": node_id, "step": 1}, msg


def resume_callback(n_clicks_list, ids, store):
    """Recharge un brouillon depuis la base et restaure son etape courante."""
    if not any(n for n in (n_clicks_list or [])):
        raise PreventUpdate
    index = _clicked_index(n_clicks_list, ids)
    if index is None:
        raise PreventUpdate
    try:
        state = _wizard().load(index)
    except KeyError as exc:
        raise PreventUpdate from exc
    return {"node_id": state.node_id, "step": _clamp_step(state.current_step)}


def goto_step_callback(n_clicks_list, ids, store):
    """Retourne a une section DEJA validee via le bandeau d'etapes."""
    if not any(n for n in (n_clicks_list or [])):
        raise PreventUpdate
    data = dict(store or {})
    node_id = data.get("node_id")
    index = _clicked_index(n_clicks_list, ids)
    if not node_id or index is None:
        raise PreventUpdate
    step = _clamp_step(index)
    try:
        state = _wizard().load(str(node_id))
    except KeyError as exc:
        raise PreventUpdate from exc
    if not state.sections_done.get(SECTION_KEYS[step - 1]):
        raise PreventUpdate  # on ne revient que sur une section deja validee
    return {**data, "step": step}


def render_drafts_callback(project_data, refresh, store):
    """Liste les brouillons du projet actif avec badge x/4 et bouton " Reprendre "."""
    pid = (project_data or {}).get("project_id")
    if not pid:
        return html.P("Sélectionnez d'abord un projet actif (page Projets).", style=_MUTED_STYLE)
    wizard = _wizard()
    drafts = wizard.list_drafts(pid)
    if not drafts:
        return html.P("Aucun brouillon en cours pour ce projet.", style=_MUTED_STYLE)
    rows: list = []
    for node in drafts:
        done, total = wizard.completeness(node.id)
        rows.append(
            html.Div(
                [
                    html.Span(
                        f"{node.name} ({node.label})",
                        style={"fontWeight": "600", "minWidth": "220px"},
                    ),
                    draft_badge(),
                    completeness_badge(done, total),
                    html.Button(
                        "Reprendre",
                        id={"type": "onb-resume", "index": node.id},
                        style={**BUTTON_SECONDARY_STYLE, "marginLeft": "auto"},
                    ),
                ],
                style=_DRAFT_ROW_STYLE,
            )
        )
    return rows


def render_step_callback(store, refresh):
    """Rend le bandeau d'etapes + le formulaire de l'etape courante (cote serveur)."""
    data = store or {}
    node_id = data.get("node_id")
    if not node_id:
        return [
            html.P(
                "Aucun onboarding en cours : créez un brouillon ou reprenez-en un ci-dessus.",
                style=_MUTED_STYLE,
            )
        ]
    service = get_service()
    try:
        state = _wizard().load(str(node_id))
    except KeyError:
        return [html.P("Brouillon introuvable — relancez l'onboarding.", style=MSG_ALERT_STYLE)]
    node = service.registry.get_node(str(node_id))
    if node is None:
        return [html.P("Nœud introuvable dans le registre.", style=MSG_ALERT_STYLE)]
    step = _clamp_step(data.get("step") or state.current_step)
    return [
        _stepper(step, state.sections_done),
        html.P(
            f"Nœud en cours : « {node.name} » ({node.label}).",
            style={"color": COLORS["primary"], "fontWeight": "600", "margin": "0 0 4px"},
        ),
        html.H4(
            f"Étape {step}/{len(SECTION_KEYS)} — {STEP_TITLES[step - 1]}",
            style={"margin": "0 0 12px"},
        ),
        _step_form(service, node, state, step),
    ]


def save_section_callback(n_clicks, store, operator_data, *form_values):
    """Valide et ecrit la section courante, puis avance (ou termine apres l'etape 4).

    Erreurs de validation : liste francaise dans ``onb-msg``, on RESTE sur
    l'etape (store inchange). Apres l'etape 4 : ``complete()`` bascule le
    noeud en ``complete`` et le store est remis a zero.
    """
    if not n_clicks:
        raise PreventUpdate
    data = dict(store or {})
    node_id = data.get("node_id")
    if not node_id:
        return no_update, _alert("Aucun onboarding en cours : créez ou reprenez un brouillon.")
    step = _clamp_step(data.get("step"))
    try:
        payload = _section_payload(step, *form_values)
    except (TypeError, ValueError) as exc:
        return no_update, _alert(f"Saisie invalide : {exc}")
    wizard = _wizard()
    operator_id = current_operator(operator_data)
    try:
        result = wizard.save_section(str(node_id), step, payload, operator_id)
    except KeyError:
        return no_update, _alert("Brouillon introuvable — relancez l'onboarding.")
    if not result.ok:
        return no_update, _errors(result.errors)
    if step < len(SECTION_KEYS):
        msg = _ok(
            f"Section « {STEP_TITLES[step - 1]} » validée — étape {step + 1}/{len(SECTION_KEYS)}."
        )
        return {**data, "step": step + 1}, msg
    completion = wizard.complete(str(node_id), operator_id)
    if not completion.ok:
        return no_update, _errors(completion.errors)
    node = get_service().registry.get_node(str(node_id))
    name = node.name if node is not None else str(node_id)
    msg = _ok(
        f"Onboarding terminé : « {name} » est intégré au réseau et les scores sont recalculés."
    )
    return {"node_id": None, "step": 1}, msg


def save_draft_callback(n_clicks, store, *form_values):
    """Serialise l'etape courante en brouillon SANS valider (" quitter ")."""
    if not n_clicks:
        raise PreventUpdate
    data = store or {}
    node_id = data.get("node_id")
    if not node_id:
        return _alert("Aucun onboarding en cours : rien à enregistrer.")
    step = _clamp_step(data.get("step"))
    try:
        payload = _section_payload(step, *form_values)
    except (TypeError, ValueError) as exc:
        return _alert(f"Saisie invalide : {exc}")
    try:
        _wizard().save_draft(str(node_id), step, payload)
    except KeyError:
        return _alert("Brouillon introuvable — il a peut-être déjà été complété.")
    return _ok("Brouillon enregistré — vous pouvez quitter.")


def prev_step_callback(n_clicks, store):
    """Recule d'une etape (minimum 1), sans aucune sauvegarde."""
    if not n_clicks:
        raise PreventUpdate
    data = dict(store or {})
    data["step"] = max(_clamp_step(data.get("step")) - 1, 1)
    return data


def add_deliverable_callback(n_clicks, children):
    """Ajoute une ligne " livrable " vierge au cahier des charges."""
    if not n_clicks:
        raise PreventUpdate
    rows = list(children or [])
    rows.append(deliverable_row("onb", uuid.uuid4().hex[:8]))
    return rows


def add_milestone_callback(n_clicks, children):
    """Ajoute une ligne " jalon " vierge au cahier des charges."""
    if not n_clicks:
        raise PreventUpdate
    rows = list(children or [])
    rows.append(milestone_row("onb", uuid.uuid4().hex[:8]))
    return rows


#: States partages par " Enregistrer et continuer " et " Enregistrer le brouillon " : TOUS les champs des 4 formulaires ctx="onb" (les non montes valent None / []).
_FORM_STATES: tuple = (
    State("onb-ident-name", "value"),
    State("onb-ident-label", "value"),
    State("onb-ident-location", "value"),
    State("onb-ident-tags", "value"),
    State("onb-ident-targets", "value"),
    State("onb-ident-gamma", "value"),
    State("onb-ident-beta", "value"),
    State("onb-ident-arckind", "value"),
    State("onb-cdc-budget", "value"),
    State("onb-cdc-unitcost", "value"),
    State("onb-cdc-currency", "value"),
    State("onb-cdc-standards", "value"),
    State("onb-cdc-certifications", "value"),
    State("onb-cdc-scrap", "value"),
    State({"type": "onb-cdc-dlv-name", "index": ALL}, "value"),
    State({"type": "onb-cdc-dlv-qty", "index": ALL}, "value"),
    State({"type": "onb-cdc-dlv-unit", "index": ALL}, "value"),
    State({"type": "onb-cdc-ms-name", "index": ALL}, "value"),
    State({"type": "onb-cdc-ms-kind", "index": ALL}, "value"),
    State({"type": "onb-cdc-ms-start", "index": ALL}, "date"),
    State({"type": "onb-cdc-ms-deadline", "index": ALL}, "date"),
    State({"type": "onb-kpi", "index": ALL}, "value"),
    State({"type": "onb-kpi", "index": ALL}, "id"),
    State({"type": "onb-ahp-pair", "index": ALL}, "value"),
    State({"type": "onb-ahp-pair", "index": ALL}, "id"),
    State({"type": "onb-ahp-score", "index": ALL}, "value"),
    State({"type": "onb-ahp-score", "index": ALL}, "id"),
    State("onb-ahp-notes", "value"),
)


def register_callbacks(app) -> None:
    """Enregistre les callbacks de la page Onboarding sur l'application Dash."""
    app.callback(
        Output("store-onb", "data", allow_duplicate=True),
        Output("onb-msg", "children", allow_duplicate=True),
        Input("onb-start-btn", "n_clicks"),
        State("store-project", "data"),
        State("onb-start-name", "value"),
        State("onb-start-label", "value"),
        State("store-onb", "data"),
        prevent_initial_call=True,
    )(start_onboarding_callback)

    app.callback(
        Output("store-onb", "data", allow_duplicate=True),
        Input({"type": "onb-resume", "index": ALL}, "n_clicks"),
        State({"type": "onb-resume", "index": ALL}, "id"),
        State("store-onb", "data"),
        prevent_initial_call=True,
    )(resume_callback)

    app.callback(
        Output("store-onb", "data", allow_duplicate=True),
        Input({"type": "onb-step", "index": ALL}, "n_clicks"),
        State({"type": "onb-step", "index": ALL}, "id"),
        State("store-onb", "data"),
        prevent_initial_call=True,
    )(goto_step_callback)

    app.callback(
        Output("onb-drafts", "children"),
        Input("store-project", "data"),
        Input("store-refresh", "data"),
        Input("store-onb", "data"),
    )(render_drafts_callback)

    app.callback(
        Output("onb-step-content", "children"),
        Input("store-onb", "data"),
        Input("store-refresh", "data"),
    )(render_step_callback)

    app.callback(
        Output("store-onb", "data", allow_duplicate=True),
        Output("onb-msg", "children", allow_duplicate=True),
        Input("onb-next-btn", "n_clicks"),
        State("store-onb", "data"),
        State("store-operator", "data"),
        *_FORM_STATES,
        prevent_initial_call=True,
    )(save_section_callback)

    app.callback(
        Output("onb-msg", "children", allow_duplicate=True),
        Input("onb-draft-btn", "n_clicks"),
        State("store-onb", "data"),
        *_FORM_STATES,
        prevent_initial_call=True,
    )(save_draft_callback)

    app.callback(
        Output("store-onb", "data", allow_duplicate=True),
        Input("onb-prev-btn", "n_clicks"),
        State("store-onb", "data"),
        prevent_initial_call=True,
    )(prev_step_callback)

    app.callback(
        Output("onb-cdc-deliverables", "children"),
        Input("onb-cdc-add-dlv", "n_clicks"),
        State("onb-cdc-deliverables", "children"),
        prevent_initial_call=True,
    )(add_deliverable_callback)

    app.callback(
        Output("onb-cdc-milestones", "children"),
        Input("onb-cdc-add-ms", "n_clicks"),
        State("onb-cdc-milestones", "children"),
        prevent_initial_call=True,
    )(add_milestone_callback)

    # Libelles live du questionnaire AHP, reutilises en contexte " onb ".
    app.callback(
        Output({"type": "onb-ahp-pair-label", "index": MATCH}, "children"),
        Input({"type": "onb-ahp-pair", "index": MATCH}, "value"),
        State({"type": "onb-ahp-pair", "index": MATCH}, "id"),
    )(pair_label_callback)

    app.callback(
        Output({"type": "onb-ahp-score-label", "index": MATCH}, "children"),
        Input({"type": "onb-ahp-score", "index": MATCH}, "value"),
    )(score_label_callback)
