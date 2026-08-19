"""Formulaires d'evenements generes depuis la calibration declarative (Lot 6.4).

Composant PUREMENT presentationnel pour le volet " Evenements " de la page
hebdomadaire : tout est genere depuis
:data:`supplyscore.domain.events.EVENT_CALIBRATION` (declaratif - champs,
bornes, unites, choix). Aucune IO et aucun import des services : les impacts
(:func:`impacts_preview_table`) et les evenements (:func:`events_list`) sont
recus en duck-typing (attributs lus via ``getattr`` avec defaut), le moteur
d'evenements etant developpe en parallele.

Les ids sont prefixes par un contexte ``ctx`` (``"ev"`` par defaut) :

- champs de parametres : ``{"type": f"{ctx}-param", "index": nom_du_champ}`` ;
- boutons d'annulation : ``{"type": f"{ctx}-revert", "index": id_evenement}``.

Le parseur pattern-matching (:func:`parse_event_params`) trie TOUJOURS par
``id["index"]`` (l'ordre DOM n'est pas garanti par Dash), comme ceux de
``forms_node``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from dash import dcc, html

from supplyscore.domain.events import (
    _STRICTLY_POSITIVE_FIELDS,
    EVENT_CALIBRATION,
    EventField,
    EventSpec,
)
from supplyscore.web_ui.components.layout import (
    BUTTON_SECONDARY_STYLE,
    COLORS,
    FONT_FAMILY,
    INPUT_STYLE,
    labelled,
)

#: Message gris par defaut quand aucun impact n'est calculable (liste vide).
NO_IMPACT_MSG_DEFAULT: str = "Aucun impact calculable pour cet événement."

#: Borne HTML ``min`` des champs strictement positifs : la borne domaine ``minimum=0`` est EXCLUSIVE (cf. ``_STRICTLY_POSITIVE_FIELDS``) alors que l'attribut HTML ``min`` est inclusif - un petit epsilon exclut le zero.
_STRICT_POSITIVE_MIN: float = 1e-6

#: En-tetes francais du tableau de previsualisation des impacts.
_IMPACT_HEADERS: tuple[str, ...] = ("KPI", "Avant", "Après", "Règle appliquée")

# Styles (alignes sur layout.py / history.py)

_DESCRIPTION_STYLE = {"fontSize": "13px", "color": COLORS["muted"], "margin": "0 0 12px"}

_EMPTY_STYLE = {"fontSize": "13px", "color": COLORS["muted"], "fontFamily": FONT_FAMILY}

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

_EVENT_ROW_STYLE = {
    "padding": "10px 12px",
    "border": f"1px solid {COLORS['border']}",
    "borderRadius": "6px",
    "marginBottom": "8px",
    "fontFamily": FONT_FAMILY,
}

_EVENT_TITLE_STYLE = {"fontWeight": "600", "fontSize": "14px", "marginRight": "10px"}

_EVENT_WEEK_STYLE = {"fontSize": "13px", "color": COLORS["muted"], "marginRight": "10px"}

_EVENT_PARAMS_STYLE = {"fontSize": "13px", "color": COLORS["text"], "margin": "4px 0 0"}

_EVENT_NOTES_STYLE = {
    "fontSize": "13px",
    "color": COLORS["muted"],
    "fontStyle": "italic",
    "margin": "4px 0 0",
}

#: Badge pilule gris " Annule " (meme gamme que les badges hebdo).
_REVERTED_BADGE_STYLE = {
    "display": "inline-block",
    "padding": "2px 10px",
    "borderRadius": "10px",
    "fontSize": "12px",
    "fontWeight": "600",
    "backgroundColor": "#ebeef1",
    "color": COLORS["muted"],
    "whiteSpace": "nowrap",
}

_REVERT_BUTTON_STYLE = {
    **BUTTON_SECONDARY_STYLE,
    "marginTop": "8px",
    "padding": "5px 12px",
    "fontSize": "13px",
}


# Selecteur de type


def event_type_options() -> list[dict]:
    """Options du dropdown des types d'evenement, triees par libelle francais.

    Returns:
        ``[{"label": label_fr, "value": event_type}, ...]`` - une entree par
        type de :data:`EVENT_CALIBRATION`, triee par ``label_fr``.
    """
    return [
        {"label": spec.label_fr, "value": spec.event_type}
        for spec in sorted(EVENT_CALIBRATION.values(), key=lambda spec: spec.label_fr)
    ]


# Champs de parametres


def _html_min(field: EventField) -> float | None:
    """Borne ``min`` HTML d'un champ numerique.

    La borne domaine ``minimum=0`` des champs strictement positifs est
    EXCLUSIVE alors que l'attribut HTML ``min`` est inclusif : un epsilon
    exclut le zero des la saisie (la validation domaine reste la reference).
    """
    if field.name in _STRICTLY_POSITIVE_FIELDS:
        return max(field.minimum if field.minimum is not None else 0.0, _STRICT_POSITIVE_MIN)
    return field.minimum


def _field_label(field: EventField) -> str:
    """Libelle affiche d'un champ : ``label_fr``, unite entre parentheses si presente."""
    return f"{field.label_fr} ({field.unit})" if field.unit else field.label_fr


def _param_input(field: EventField, ctx: str) -> Any:
    """Composant de saisie d'un champ : Dropdown pour " choice ", Input number sinon.

    ``step="any"`` evite le pas implicite de 1 des inputs HTML number (une
    duree de 1.5 h ou un ratio de 0.35 doivent rester valides).
    """
    field_id = {"type": f"{ctx}-param", "index": field.name}
    if field.kind == "choice":
        return dcc.Dropdown(
            id=field_id,
            options=[{"label": choice, "value": choice} for choice in field.choices],
            placeholder="choisir…",
        )
    return dcc.Input(
        id=field_id,
        type="number",
        min=_html_min(field),
        max=field.maximum,
        step="any",
        placeholder="à renseigner",
        style=INPUT_STYLE,
    )


def event_param_fields(event_type: str, ctx: str = "ev") -> html.Div:
    """Champs de saisie des parametres d'un evenement, generes depuis sa calibration.

    Chaque :class:`~supplyscore.domain.events.EventField` de
    ``EVENT_CALIBRATION[event_type].fields`` devient un champ :
    ``dcc.Input(type="number", min=, max=)`` pour les kinds " number " et
    " ratio " (unite reprise dans le libelle), ``dcc.Dropdown`` pour
    " choice ". La description francaise de l'evenement est affichee en
    sous-titre.

    Args:
        event_type: cle de :data:`EVENT_CALIBRATION`.
        ctx: prefixe de contexte des ids pattern-matching
            (``{"type": f"{ctx}-param", "index": nom_du_champ}``).

    Returns:
        ``html.Div`` pret a monter dans le volet evenements de la page hebdo.

    Raises:
        ValueError: type d'evenement inconnu.
    """
    spec = EVENT_CALIBRATION.get(event_type)
    if spec is None:
        raise ValueError(
            f"Type d'événement inconnu : {event_type!r} — types admis : {sorted(EVENT_CALIBRATION)}"
        )
    children: list = [html.P(spec.description_fr, style=_DESCRIPTION_STYLE)]
    children += [labelled(_field_label(field), _param_input(field, ctx)) for field in spec.fields]
    return html.Div(children)


def parse_event_params(values: list, ids: list[dict]) -> dict:
    """Parametres saisis ``{nom_du_champ: valeur}`` depuis un callback ``ALL``.

    Les champs vides (None ou ``""``) sont ignores, les valeurs numeriques
    converties en float (les choix restent des chaines). Trie par
    ``id["index"]`` - l'ordre DOM des composants pattern-matching n'est pas
    garanti par Dash.

    Args:
        values: valeurs des champs de parametres (callback ``ALL``).
        ids: ids pattern-matching alignes sur ``values``.

    Returns:
        Dict ordonne par nom de champ, pret pour
        :func:`supplyscore.domain.events.compute_impacts`.
    """
    out: dict[str, float | str] = {}
    pairs = sorted(zip(ids, values, strict=True), key=lambda pair: str(pair[0]["index"]))
    for id_, value in pairs:
        if value is None or value == "":
            continue
        name = str(id_["index"])
        out[name] = float(value) if isinstance(value, int | float) else str(value)
    return out


# Previsualisation des impacts


def _fmt_kpi_value(value: Any) -> str:
    """Formate une valeur de KPI : " non renseigne " si None, 4 decimales utiles sinon."""
    if value is None:
        return "non renseigné"
    if isinstance(value, int | float):
        return f"{value:.4g}"
    return str(value)


def impacts_preview_table(impacts: list, no_impact_msg: str = NO_IMPACT_MSG_DEFAULT) -> html.Div:
    """Tableau de previsualisation " KPI | avant | apres | regle appliquee ".

    Duck-typing volontaire : tout objet exposant ``kpi_path``, ``old``,
    ``new`` et ``rule`` convient (la dataclass ``KpiImpact`` du domaine comme
    un substitut de test) ; un attribut manquant s'affiche vide. ``old`` a
    None s'affiche " non renseigne " ; les valeurs numeriques sont formatees
    a 4 decimales utiles (``:.4g``).

    Args:
        impacts: impacts calcules (``compute_impacts`` ou equivalent).
        no_impact_msg: message gris affiche si la liste est vide.

    Returns:
        ``html.Div`` contenant le tableau, ou le message si aucun impact.
    """
    if not impacts:
        return html.Div(no_impact_msg, style=_EMPTY_STYLE)
    header = html.Thead(html.Tr([html.Th(title, style=_TH_STYLE) for title in _IMPACT_HEADERS]))
    body = html.Tbody(
        [
            html.Tr(
                [
                    html.Td(str(getattr(impact, "kpi_path", "")), style=_TD_STYLE),
                    html.Td(_fmt_kpi_value(getattr(impact, "old", None)), style=_TD_STYLE),
                    html.Td(_fmt_kpi_value(getattr(impact, "new", None)), style=_TD_STYLE),
                    html.Td(str(getattr(impact, "rule", "")), style=_TD_STYLE),
                ]
            )
            for impact in impacts
        ]
    )
    return html.Div(html.Table([header, body], style=_TABLE_STYLE))


# Liste des evenements


def _params_summary(spec: EventSpec | None, params: Any) -> str:
    """Resume francais des parametres : " Libelle : valeur unite ", separes par " - ".

    Les parametres connus de la spec sont libelles en francais (unite
    incluse) et affiches dans l'ordre de declaration des champs ; les
    parametres inconnus suivent, sous leur nom brut.
    """
    if not isinstance(params, Mapping) or not params:
        return ""
    fields: dict[str, EventField] = (
        {field.name: field for field in spec.fields} if spec is not None else {}
    )
    order = {name: position for position, name in enumerate(fields)}
    items = sorted(params.items(), key=lambda kv: (order.get(str(kv[0]), len(order)), str(kv[0])))
    parts: list[str] = []
    for name, value in items:
        field = fields.get(str(name))
        shown = f"{value:g}" if isinstance(value, int | float) else str(value)
        if field is not None and field.unit:
            shown = f"{shown} {field.unit}"
        parts.append(f"{field.label_fr if field is not None else name} : {shown}")
    return " · ".join(parts)


def _event_row(event: Any, ctx: str) -> html.Div:
    """Ligne d'un evenement : libelle FR, semaine, params resumes, badge/bouton."""
    event_type = str(getattr(event, "event_type", ""))
    spec = EVENT_CALIBRATION.get(event_type)
    label = spec.label_fr if spec is not None else event_type
    reverted_at = getattr(event, "reverted_at", None)

    header: list = [
        html.Span(label, style=_EVENT_TITLE_STYLE),
        html.Span(f"semaine {getattr(event, 'iso_week', '')}", style=_EVENT_WEEK_STYLE),
    ]
    if reverted_at is not None:
        header.append(html.Span("Annulé", style=_REVERTED_BADGE_STYLE))

    children: list = [html.Div(header)]
    summary = _params_summary(spec, getattr(event, "params", None))
    if summary:
        children.append(html.Div(summary, style=_EVENT_PARAMS_STYLE))
    notes = getattr(event, "notes", "")
    if notes:
        children.append(html.Div(str(notes), style=_EVENT_NOTES_STYLE))
    if reverted_at is None:
        children.append(
            html.Button(
                "Annuler",
                id={"type": f"{ctx}-revert", "index": str(getattr(event, "id", ""))},
                style=_REVERT_BUTTON_STYLE,
            )
        )
    return html.Div(children, style=_EVENT_ROW_STYLE)


def events_list(events: list, ctx: str = "ev") -> html.Div:
    """Liste des evenements de la semaine, avec annulation des evenements actifs.

    Duck-typing volontaire : tout objet exposant ``id``, ``event_type``,
    ``iso_week``, ``params``, ``notes`` et ``reverted_at`` convient (la
    dataclass du service est developpee en parallele et n'est PAS importee).
    Chaque ligne affiche le libelle francais du type (via
    :data:`EVENT_CALIBRATION`, type inconnu affiche brut), la semaine, les
    parametres resumes et les notes ; un evenement reverte porte le badge
    " Annule ", un evenement actif porte le bouton " Annuler "
    (``{"type": f"{ctx}-revert", "index": event.id}``).

    Args:
        events: evenements a afficher, dans l'ordre fourni par l'appelant.
        ctx: prefixe de contexte des ids des boutons d'annulation.

    Returns:
        ``html.Div`` des lignes, ou message gris si la liste est vide.
    """
    if not events:
        return html.Div("Aucun événement déclaré cette semaine.", style=_EMPTY_STYLE)
    return html.Div([_event_row(event, ctx) for event in events])
