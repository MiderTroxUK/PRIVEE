"""Form-builders partages : wizard d'onboarding (E5) ET fiche noeud.

Chaque builder recoit un prefixe de contexte ``ctx`` (``"onb"`` pour le
wizard, ``"fiche"`` pour la fiche noeud) qui prefixe TOUS les ids - simples
(``f"{ctx}-ident-name"``) comme pattern-matching
(``{"type": f"{ctx}-kpi", "index": "bloc.champ"}``). Les deux pages peuvent
ainsi monter les memes formulaires sans ``DuplicateIdError``, et aucun id
n'entre en collision avec ceux du questionnaire hebdomadaire (``ahp-pair`` /
``ahp-score`` reserves).

Les parseurs inverses (:func:`parse_identity`, :func:`parse_cdc`,
:func:`parse_kpis`, :func:`parse_ahp`) sont des fonctions pures : ils
transforment les valeurs lues par les callbacks en payloads de section prets
pour ``OnboardingService.save_section``. Les parseurs qui recoivent des
listes pattern-matching trient TOUJOURS par ``id["index"]`` (l'ordre DOM
n'est pas garanti par Dash).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from dash import dcc, html

from supplyscore.core import CRITERIA, bipolar_to_saaty, score_6_to_9
from supplyscore.domain.constraints import KPI_CONSTRAINTS
from supplyscore.domain.milestones import Milestone
from supplyscore.domain.models import KPIBundle
from supplyscore.domain.specsheet import CahierDesCharges
from supplyscore.web_ui.components.layout import (
    BUTTON_SECONDARY_STYLE,
    COLORS,
    INPUT_STYLE,
    LABEL_STYLE,
    labelled,
)
from supplyscore.web_ui.pages.questionnaire import KPI_FIELDS, PAIRS

#: Labels metier proposes pour un noeud (aligne sur la page Projets).
NODE_LABELS: list[str] = [
    "Client",
    "Factory",
    "Warehouse",
    "Workshop",
    "Supplier",
    "Transport",
]

#: Natures d'arc proposees pour les connexions aval.
ARC_KIND_OPTIONS: list[dict] = [
    {"label": "Nominal (flux réel)", "value": "nominal"},
    {"label": "Backup (secours)", "value": "backup"},
]

#: Types de jalon proposes dans les lignes dynamiques du cahier des charges.
MILESTONE_KIND_OPTIONS: list[dict] = [
    {"label": "Proto", "value": "proto"},
    {"label": "Série", "value": "serie"},
    {"label": "Livraison", "value": "livraison"},
    {"label": "Autre", "value": "custom"},
]

_PAIR_MARKS = {-8: "-8", -4: "-4", 0: "0", 4: "+4", 8: "+8"}
_UNIT_MARKS = {0: "0", 0.5: "0.5", 1: "1"}

_H4_STYLE = {"margin": "10px 0 6px", "fontSize": "15px", "color": COLORS["primary"]}
_HINT_STYLE = {"fontSize": "13px", "color": COLORS["muted"], "marginBottom": "16px"}
_TITLE_STYLE = {"margin": "0 0 2px", "fontSize": "14px", "fontWeight": "600"}


# Petits helpers internes


def _short_uid() -> str:
    """Index court (8 hex) pour les lignes dynamiques pattern-matching."""
    return uuid.uuid4().hex[:8]


def _iso_to_epoch(value: Any) -> float:
    """Epoch (s, UTC) d'une date ISO " AAAA-MM-JJ " (heure conservee si presente)."""
    dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def _epoch_to_iso(ts: float) -> str | None:
    """Date ISO " AAAA-MM-JJ " (UTC) d'un epoch, ou None si non renseigne (<= 0)."""
    if ts <= 0:
        return None
    return datetime.fromtimestamp(ts, tz=UTC).date().isoformat()


def _float_or_none(value: Any) -> float | None:
    """Convertit en float, None pour les champs vides (None ou chaine vide)."""
    if value is None or value == "":
        return None
    return float(value)


def _float_or(value: Any, default: float) -> float:
    """Convertit en float avec valeur par defaut pour les champs vides."""
    result = _float_or_none(value)
    return default if result is None else result


def _split_csv(raw: Any) -> list[str]:
    """Decoupe une chaine " a, b, c " en liste, entrees vides ignorees."""
    if not raw:
        return []
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def _labelled(
    label_text: str, component: Any, *, width: str = "230px", title: str | None = None
) -> html.Div:
    """Variante de :func:`labelled` avec info-bulle ``title`` optionnelle."""
    style = {
        "width": width,
        "marginRight": "16px",
        "marginBottom": "12px",
        "display": "inline-block",
        "verticalAlign": "top",
    }
    children = [html.Label(label_text, style=LABEL_STYLE), component]
    if title:
        return html.Div(children, title=title, style=style)
    return html.Div(children, style=style)


def _bounds_title(lo: float | None, hi: float | None, unit: str) -> str:
    """Info-bulle des bornes d'un KPI (" Entre lo et hi (unite) ")."""
    if lo is not None and hi is not None:
        text = f"Entre {lo:g} et {hi:g}"
    elif lo is not None:
        text = f"Minimum {lo:g}"
    elif hi is not None:
        text = f"Maximum {hi:g}"
    else:
        text = "Pas de borne"
    return f"{text} ({unit})" if unit else text


# Section 1 : identite


def identity_form(
    ctx: str,
    *,
    name: str = "",
    label: str = "Supplier",
    location: str = "",
    selected_tags: list[str] | None = None,
    tag_options: list[dict] | None = None,
    node_options: list[dict] | None = None,
    connections: list[dict] | None = None,
) -> html.Div:
    """Formulaire " Identite " : nom, label, localisation, tags et connexions aval.

    Args:
        ctx: prefixe de contexte des ids (``"onb"`` ou ``"fiche"``).
        name: nom du noeud pre-rempli.
        label: label metier pre-selectionne (cf. :data:`NODE_LABELS`).
        location: localisation pre-remplie.
        selected_tags: ids/valeurs de tags deja portes par le noeud.
        tag_options: options du dropdown tags ; les valeurs selectionnees
            absentes des options sont ajoutees (tags libres - l'appelant
            enrichit les options pour la creation de nouveaux tags).
        node_options: options du dropdown des clients aval (noeuds candidats).
        connections: arcs existants - dicts ``{"target_id", "gamma", "beta",
            "kind"}`` ; les curseurs gamma/beta et la nature sont pre-remplis depuis
            la premiere connexion (reglage commun aux cibles selectionnees).

    Returns:
        ``html.Div`` avec les ids simples ``f"{ctx}-ident-name"``, ``-label``,
        ``-location``, ``-tags``, ``-targets``, ``-gamma``, ``-beta`` et
        ``-arckind``.
    """
    tags = [str(t) for t in (selected_tags or [])]
    options = list(tag_options or [])
    known = {opt.get("value") for opt in options}
    options += [{"label": t, "value": t} for t in tags if t not in known]

    conns = list(connections or [])
    first: dict = conns[0] if conns else {}
    raw_targets = [c.get("target_id") or c.get("target") for c in conns]
    targets = [str(t) for t in raw_targets if t]

    return html.Div(
        [
            labelled(
                "Nom du nœud",
                dcc.Input(
                    id=f"{ctx}-ident-name",
                    type="text",
                    value=name,
                    placeholder="ex. Atelier usinage",
                    style=INPUT_STYLE,
                ),
                width="260px",
            ),
            labelled(
                "Label métier",
                dcc.Dropdown(
                    id=f"{ctx}-ident-label",
                    options=[{"label": lbl, "value": lbl} for lbl in NODE_LABELS],
                    value=label,
                    clearable=False,
                ),
                width="200px",
            ),
            labelled(
                "Localisation",
                dcc.Input(
                    id=f"{ctx}-ident-location",
                    type="text",
                    value=location,
                    placeholder="ville, pays",
                    style=INPUT_STYLE,
                ),
                width="260px",
            ),
            labelled(
                "Tags",
                dcc.Dropdown(
                    id=f"{ctx}-ident-tags",
                    options=options,
                    value=tags,
                    multi=True,
                    placeholder="choisir ou créer des tags…",
                ),
                width="320px",
            ),
            html.H4("Connexions aval", style=_H4_STYLE),
            labelled(
                "Clients aval (nœuds alimentés)",
                dcc.Dropdown(
                    id=f"{ctx}-ident-targets",
                    options=list(node_options or []),
                    value=targets,
                    multi=True,
                    placeholder="choisir les nœuds clients…",
                ),
                width="380px",
            ),
            labelled(
                "γ — intensité de dépendance Ud",
                dcc.Slider(
                    id=f"{ctx}-ident-gamma",
                    min=0,
                    max=1,
                    step=0.05,
                    value=_float_or(first.get("gamma"), 0.5),
                    marks=_UNIT_MARKS,
                    tooltip={"placement": "bottom"},
                ),
                width="300px",
            ),
            labelled(
                "β — coefficient de propagation Ur",
                dcc.Slider(
                    id=f"{ctx}-ident-beta",
                    min=0,
                    max=1,
                    step=0.05,
                    value=_float_or(first.get("beta"), 0.5),
                    marks=_UNIT_MARKS,
                    tooltip={"placement": "bottom"},
                ),
                width="300px",
            ),
            labelled(
                "Nature des arcs",
                dcc.Dropdown(
                    id=f"{ctx}-ident-arckind",
                    options=ARC_KIND_OPTIONS,
                    value=str(first.get("kind") or first.get("kind_arc") or "nominal"),
                    clearable=False,
                ),
                width="220px",
            ),
        ]
    )


def _ident_key(key: str) -> str:
    """Suffixe nu d'un id identite (" onb-ident-name " -> " name ")."""
    return key.rsplit("ident-", 1)[-1]


def parse_identity(values: dict) -> dict:
    """Payload " identite " (section 1) depuis un dict ``{id_simple: valeur}``.

    Les cles sont acceptees en id complet (``"onb-ident-name"``) comme en
    suffixe nu (``"name"``) : tout ce qui precede ``"ident-"`` est ignore,
    le parseur est donc independant du contexte.

    Args:
        values: valeurs lues par le callback, indexees par id simple.

    Returns:
        Payload ``{"name", "label", "location", "tags", "connections"}`` -
        une connexion ``{"target_id", "gamma", "beta", "kind"}`` par cible
        selectionnee (gamma/beta/nature communs, lus sur les curseurs).
    """
    data = {_ident_key(str(k)): v for k, v in values.items()}
    gamma = _float_or(data.get("gamma"), 0.5)
    beta = _float_or(data.get("beta"), 0.5)
    kind = str(data.get("arckind") or "nominal")
    targets = [str(t) for t in (data.get("targets") or []) if t]
    return {
        "name": str(data.get("name") or "").strip(),
        "label": str(data.get("label") or "Supplier"),
        "location": str(data.get("location") or "").strip(),
        "tags": [str(t) for t in (data.get("tags") or [])],
        "connections": [
            {"target_id": target, "gamma": gamma, "beta": beta, "kind": kind} for target in targets
        ],
    }


# Section 2 : cahier des charges


def deliverable_row(
    ctx: str,
    index: str,
    name: str = "",
    quantity: float | None = None,
    unit: str = "",
) -> html.Div:
    """Ligne dynamique " livrable " : nom, quantite et unite.

    Appelee par :func:`cdc_form` pour le pre-remplissage ET par les callbacks
    " + livrable " des pages (avec un index frais, ex. ``uuid4().hex[:8]``).
    """
    return html.Div(
        [
            labelled(
                "Livrable",
                dcc.Input(
                    id={"type": f"{ctx}-cdc-dlv-name", "index": index},
                    type="text",
                    value=name,
                    placeholder="ex. Carter avant",
                    style=INPUT_STYLE,
                ),
                width="240px",
            ),
            labelled(
                "Quantité",
                dcc.Input(
                    id={"type": f"{ctx}-cdc-dlv-qty", "index": index},
                    type="number",
                    value=quantity,
                    min=0,
                    placeholder="0",
                    style=INPUT_STYLE,
                ),
                width="120px",
            ),
            labelled(
                "Unité",
                dcc.Input(
                    id={"type": f"{ctx}-cdc-dlv-unit", "index": index},
                    type="text",
                    value=unit,
                    placeholder="pièces, kg, lots…",
                    style=INPUT_STYLE,
                ),
                width="150px",
            ),
        ]
    )


def milestone_row(
    ctx: str,
    index: str,
    name: str = "",
    kind: str = "livraison",
    start_date: str | None = None,
    deadline_date: str | None = None,
) -> html.Div:
    """Ligne dynamique " jalon " : nom, type, debut planifie et echeance.

    Appelee par :func:`cdc_form` pour le pre-remplissage ET par les callbacks
    " + jalon " des pages. Les dates sont des chaines ISO " AAAA-MM-JJ "
    (format natif de ``dcc.DatePickerSingle``).
    """
    return html.Div(
        [
            labelled(
                "Jalon",
                dcc.Input(
                    id={"type": f"{ctx}-cdc-ms-name", "index": index},
                    type="text",
                    value=name,
                    placeholder="ex. Proto",
                    style=INPUT_STYLE,
                ),
                width="200px",
            ),
            labelled(
                "Type",
                dcc.Dropdown(
                    id={"type": f"{ctx}-cdc-ms-kind", "index": index},
                    options=MILESTONE_KIND_OPTIONS,
                    value=kind,
                    clearable=False,
                ),
                width="160px",
            ),
            labelled(
                "Début planifié",
                dcc.DatePickerSingle(
                    id={"type": f"{ctx}-cdc-ms-start", "index": index},
                    date=start_date,
                    display_format="YYYY-MM-DD",
                    placeholder="AAAA-MM-JJ",
                ),
                width="170px",
            ),
            labelled(
                "Échéance",
                dcc.DatePickerSingle(
                    id={"type": f"{ctx}-cdc-ms-deadline", "index": index},
                    date=deadline_date,
                    display_format="YYYY-MM-DD",
                    placeholder="AAAA-MM-JJ",
                ),
                width="170px",
            ),
        ]
    )


def cdc_form(
    ctx: str,
    *,
    cdc: CahierDesCharges | None = None,
    milestones: list[Milestone] | None = None,
) -> html.Div:
    """Formulaire " Cahier des charges " : budget, qualite, livrables et jalons.

    Les livrables et jalons sont des LIGNES DYNAMIQUES pattern-matching :
    les conteneurs ``f"{ctx}-cdc-deliverables"`` / ``f"{ctx}-cdc-milestones"``
    sont pre-remplis (une ligne par element existant, une ligne vierge sinon)
    et les boutons ``f"{ctx}-cdc-add-dlv"`` / ``f"{ctx}-cdc-add-ms"``
    permettent aux pages d'ajouter des lignes via
    :func:`deliverable_row` / :func:`milestone_row`.

    Args:
        ctx: prefixe de contexte des ids (``"onb"`` ou ``"fiche"``).
        cdc: cahier des charges existant pour le pre-remplissage.
        milestones: jalons existants du noeud (tries par position/echeance).

    Returns:
        ``html.Div`` avec les ids simples ``f"{ctx}-cdc-budget"``,
        ``-unitcost``, ``-currency``, ``-standards``, ``-certifications``
        et ``-scrap``, plus les conteneurs et boutons de lignes dynamiques.
    """
    spec = cdc or CahierDesCharges()
    dlv_rows = [
        deliverable_row(ctx, _short_uid(), name=d.name, quantity=d.quantity, unit=d.unit)
        for d in spec.deliverables
    ] or [deliverable_row(ctx, _short_uid())]
    ordered_ms = sorted(milestones or [], key=lambda m: (m.position, m.deadline_ts))
    ms_rows = [
        milestone_row(
            ctx,
            _short_uid(),
            name=m.name,
            kind=m.kind,
            start_date=_epoch_to_iso(m.start_ts),
            deadline_date=_epoch_to_iso(m.deadline_ts),
        )
        for m in ordered_ms
    ] or [milestone_row(ctx, _short_uid())]

    return html.Div(
        [
            html.H4("Budget et coûts", style=_H4_STYLE),
            labelled(
                "Budget total",
                dcc.Input(
                    id=f"{ctx}-cdc-budget",
                    type="number",
                    value=spec.budget_total,
                    min=0,
                    placeholder="non renseigné",
                    style=INPUT_STYLE,
                ),
                width="180px",
            ),
            labelled(
                "Coût unitaire cible",
                dcc.Input(
                    id=f"{ctx}-cdc-unitcost",
                    type="number",
                    value=spec.target_unit_cost,
                    min=0,
                    placeholder="non renseigné",
                    style=INPUT_STYLE,
                ),
                width="180px",
            ),
            labelled(
                "Devise",
                dcc.Input(
                    id=f"{ctx}-cdc-currency",
                    type="text",
                    value=spec.currency,
                    style=INPUT_STYLE,
                ),
                width="120px",
            ),
            html.H4("Exigences qualité", style=_H4_STYLE),
            labelled(
                "Normes (séparées par des virgules)",
                dcc.Input(
                    id=f"{ctx}-cdc-standards",
                    type="text",
                    value=", ".join(spec.quality.standards),
                    placeholder="ISO 9001, EN 9100…",
                    style=INPUT_STYLE,
                ),
                width="320px",
            ),
            labelled(
                "Certifications (séparées par des virgules)",
                dcc.Input(
                    id=f"{ctx}-cdc-certifications",
                    type="text",
                    value=", ".join(spec.quality.certifications),
                    placeholder="ex. NADCAP",
                    style=INPUT_STYLE,
                ),
                width="320px",
            ),
            labelled(
                "Taux de rebut max (0..1)",
                dcc.Input(
                    id=f"{ctx}-cdc-scrap",
                    type="number",
                    value=spec.quality.max_scrap_rate,
                    min=0,
                    max=1,
                    step=0.01,
                    placeholder="non renseigné",
                    style=INPUT_STYLE,
                ),
                width="180px",
            ),
            html.H4("Livrables", style=_H4_STYLE),
            html.Div(dlv_rows, id=f"{ctx}-cdc-deliverables"),
            html.Button("+ livrable", id=f"{ctx}-cdc-add-dlv", style=BUTTON_SECONDARY_STYLE),
            html.H4("Jalons", style=_H4_STYLE),
            html.Div(ms_rows, id=f"{ctx}-cdc-milestones"),
            html.Button("+ jalon", id=f"{ctx}-cdc-add-ms", style=BUTTON_SECONDARY_STYLE),
        ]
    )


def _cdc_key(key: str) -> str:
    """Suffixe nu d'un id cahier des charges (" onb-cdc-budget " -> " budget ")."""
    return key.rsplit("cdc-", 1)[-1]


def parse_cdc(
    names: list,
    quantities: list,
    units: list,
    ms_names: list,
    ms_kinds: list,
    ms_starts: list,
    ms_deadlines: list,
    extras: dict,
) -> dict:
    """Payload " cahier des charges " (section 2) depuis les lignes dynamiques.

    Les listes livrables (``names``/``quantities``/``units``) et jalons sont
    alignees position a position : Dash renvoie les composants d'un meme type
    pattern-matching dans le meme ordre DOM, et chaque ligne contient
    exactement un composant de chaque type. Les lignes ENTIEREMENT vides sont
    ignorees ; les dates ISO (" 2026-06-10 ") sont converties en epoch (UTC)
    via :mod:`datetime`.

    Args:
        names: noms des livrables (une entree par ligne).
        quantities: quantites des livrables.
        units: unites des livrables.
        ms_names: noms des jalons.
        ms_kinds: types des jalons (proto/serie/livraison/custom).
        ms_starts: dates ISO de debut planifie des jalons.
        ms_deadlines: dates ISO d'echeance des jalons.
        extras: champs simples ``{id: valeur}`` (budget, unitcost, currency,
            standards, certifications, scrap) - ids complets ou suffixes nus.

    Returns:
        Payload ``{"deliverables", "milestones", "budget_total",
        "target_unit_cost", "currency", "quality"}`` avec ``start_ts`` /
        ``deadline_ts`` en epoch (0.0 si date absente).

    Raises:
        ValueError: si les listes d'une meme famille ne sont pas alignees.
    """
    deliverables: list[dict] = []
    for name, qty, unit in zip(names or [], quantities or [], units or [], strict=True):
        clean_name = str(name or "").strip()
        clean_unit = str(unit or "").strip()
        quantity = _float_or_none(qty)
        if not clean_name and quantity is None and not clean_unit:
            continue  # ligne entierement vide
        deliverables.append({"name": clean_name, "quantity": quantity, "unit": clean_unit})

    milestones: list[dict] = []
    rows = zip(ms_names or [], ms_kinds or [], ms_starts or [], ms_deadlines or [], strict=True)
    for name, kind, start, deadline in rows:
        clean_name = str(name or "").strip()
        if not clean_name and not start and not deadline:
            continue  # ligne entierement vide (le type a toujours une valeur)
        milestones.append(
            {
                "name": clean_name,
                "kind": str(kind or "livraison"),
                "start_ts": _iso_to_epoch(start) if start else 0.0,
                "deadline_ts": _iso_to_epoch(deadline) if deadline else 0.0,
            }
        )

    data = {_cdc_key(str(k)): v for k, v in extras.items()}
    return {
        "deliverables": deliverables,
        "milestones": milestones,
        "budget_total": _float_or_none(data.get("budget")),
        "target_unit_cost": _float_or_none(data.get("unitcost")),
        "currency": str(data.get("currency") or "").strip() or "EUR",
        "quality": {
            "standards": _split_csv(data.get("standards")),
            "certifications": _split_csv(data.get("certifications")),
            "max_scrap_rate": _float_or_none(data.get("scrap")),
        },
    }


# Section 3 : KPIs guides


def kpi_guided_form(ctx: str, kpis: KPIBundle | None = None) -> html.Div:
    """Saisie guidee des KPIs : bornes, unites affichees et valeurs pre-remplies.

    Reutilise la structure de ``KPI_FIELDS`` du questionnaire (memes blocs,
    memes champs) avec des ids ``{"type": f"{ctx}-kpi", "index":
    "bloc.champ"}``. Chaque champ expose ``min``/``max`` depuis
    :data:`~supplyscore.domain.constraints.KPI_CONSTRAINTS`, affiche l'unite
    dans le libelle et porte une info-bulle ``title`` avec les bornes.

    Args:
        ctx: prefixe de contexte des ids (``"onb"`` ou ``"fiche"``).
        kpis: bundle existant pour le pre-remplissage (getattr en deux temps).

    Returns:
        ``html.Div`` des blocs KPI (Temps, Inventaire, OEE, Risque, Cout, CO2).
    """
    children: list = []
    for block_title, fields in KPI_FIELDS:
        children.append(html.H4(block_title, style=_H4_STYLE))
        row: list = []
        for key, label_text in fields:
            lo, hi, unit = KPI_CONSTRAINTS.get(key, (None, None, ""))
            value = None
            if kpis is not None:
                block, field_name = key.split(".", 1)
                value = getattr(getattr(kpis, block), field_name)
            shown = f"{label_text} — {unit}" if unit and unit not in label_text else label_text
            row.append(
                _labelled(
                    shown,
                    dcc.Input(
                        id={"type": f"{ctx}-kpi", "index": key},
                        type="number",
                        value=value,
                        min=lo,
                        max=hi,
                        placeholder="non renseigné",
                        style=INPUT_STYLE,
                    ),
                    width="230px",
                    title=_bounds_title(lo, hi, unit),
                )
            )
        children.append(html.Div(row))
    return html.Div(children)


def parse_kpis(values: list, ids: list[dict]) -> dict:
    """Payload " KPIs " (section 3) : ``{"bloc.champ": float}``, vides ignores.

    Trie par ``id["index"]`` - l'ordre DOM des composants pattern-matching
    n'est pas garanti par Dash.

    Args:
        values: valeurs des inputs KPI (callback ``ALL``).
        ids: ids pattern-matching alignes sur ``values``.

    Returns:
        Dict ordonne par chemin de KPI, champs vides (None ou "") exclus.
    """
    out: dict[str, float] = {}
    pairs = sorted(zip(ids, values, strict=True), key=lambda pair: str(pair[0]["index"]))
    for id_, value in pairs:
        if value is None or value == "":
            continue
        out[str(id_["index"])] = float(value)
    return out


# Section 4 : premiere evaluation AHP


def _pair_block(ctx: str, i: int, j: int) -> html.Div:
    """Slider bipolaire (-8..+8) d'une paire de criteres + libelle dynamique."""
    key = f"{i}-{j}"
    return html.Div(
        [
            html.P(f"« {CRITERIA[i]} » vs « {CRITERIA[j]} »", style=_TITLE_STYLE),
            dcc.Slider(
                id={"type": f"{ctx}-ahp-pair", "index": key},
                min=-8,
                max=8,
                step=1,
                value=0,
                marks=_PAIR_MARKS,
                tooltip={"placement": "bottom"},
            ),
            html.Div(
                "Importance égale",
                id={"type": f"{ctx}-ahp-pair-label", "index": key},
                style=_HINT_STYLE,
            ),
        ]
    )


def _score_block(ctx: str, k: int) -> html.Div:
    """Slider de note 1..6 d'un critere + libelle live (equivalent Saaty)."""
    return html.Div(
        [
            html.P(CRITERIA[k], style=_TITLE_STYLE),
            dcc.Slider(
                id={"type": f"{ctx}-ahp-score", "index": str(k)},
                min=1,
                max=6,
                step=1,
                value=3,
                marks={v: str(v) for v in range(1, 7)},
            ),
            html.Div(id={"type": f"{ctx}-ahp-score-label", "index": str(k)}, style=_HINT_STYLE),
        ]
    )


def ahp_form(ctx: str) -> html.Div:
    """Premiere evaluation AHP : 6 comparaisons par paires + 4 notes + notes libres.

    Memes echelles que le questionnaire hebdomadaire (curseurs bipolaires
    -8..+8, notes 1..6, criteres :data:`~supplyscore.core.CRITERIA`) mais
    avec des ids prefixes par ``ctx`` - aucune collision avec les ids
    ``ahp-pair`` / ``ahp-score`` reserves a la page Questionnaire.

    Args:
        ctx: prefixe de contexte des ids (``"onb"`` ou ``"fiche"``).

    Returns:
        ``html.Div`` avec les sliders pattern-matching et la zone de notes
        ``f"{ctx}-ahp-notes"``.
    """
    children: list = [
        html.H4("Comparaisons par paires", style=_H4_STYLE),
        html.P(
            "Curseur à gauche : le second critère domine ; à droite : le premier "
            "domine ; au centre : importance égale.",
            style=_HINT_STYLE,
        ),
    ]
    children += [_pair_block(ctx, i, j) for i, j in PAIRS]
    children.append(html.H4("Notes des critères (1 à 6)", style=_H4_STYLE))
    children += [_score_block(ctx, k) for k in range(len(CRITERIA))]
    children.append(
        labelled(
            "Notes (optionnel)",
            dcc.Textarea(
                id=f"{ctx}-ahp-notes",
                placeholder="commentaire libre",
                style={**INPUT_STYLE, "height": "70px"},
            ),
            width="420px",
        )
    )
    return html.Div(children)


def _pair_sort_key(index: str) -> tuple[int, int]:
    """Cle de tri numerique d'un index de paire " i-j "."""
    i_str, j_str = str(index).split("-", 1)
    return int(i_str), int(j_str)


def parse_ahp(
    pair_values: list,
    pair_ids: list[dict],
    score_values: list,
    score_ids: list[dict],
    notes: Any,
) -> dict:
    """Payload " premiere evaluation " (section 4) en echelles de Saaty.

    Les comparaisons bipolaires sont converties via
    :func:`~supplyscore.core.bipolar_to_saaty` (cles " i-j "), les notes UI
    1..6 via :func:`~supplyscore.core.score_6_to_9`. Les deux familles sont
    triees par ``id["index"]`` (ordre DOM non garanti) ; les curseurs non
    touches valent leurs defauts (paire 0 -> 1.0, note 3).

    Args:
        pair_values: valeurs des curseurs bipolaires (callback ``ALL``).
        pair_ids: ids pattern-matching des paires, alignes sur ``pair_values``.
        score_values: valeurs des curseurs de notes 1..6.
        score_ids: ids pattern-matching des notes.
        notes: texte libre de la zone ``f"{ctx}-ahp-notes"``.

    Returns:
        Payload ``{"comparisons": {"i-j": saaty}, "criteria_scores": [1..9],
        "notes": str}`` ordonne par paire puis par critere.
    """
    pairs = sorted(
        zip(pair_ids, pair_values, strict=True),
        key=lambda pair: _pair_sort_key(pair[0]["index"]),
    )
    comparisons = {str(id_["index"]): bipolar_to_saaty(int(value or 0)) for id_, value in pairs}
    ordered = sorted(
        zip(score_ids, score_values, strict=True), key=lambda pair: int(pair[0]["index"])
    )
    scores = [score_6_to_9(float(v if v is not None else 3)) for _, v in ordered]
    return {
        "comparisons": comparisons,
        "criteria_scores": scores,
        "notes": str(notes).strip() if notes else "",
    }
