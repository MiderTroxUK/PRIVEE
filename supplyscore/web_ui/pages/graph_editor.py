"""Page « /graphe » : éditeur de structure du graphe — arcs, tags et statuts (Lot 10.4).

Cinq cartes : le tableau ÉDITABLE des arcs du projet actif (γ/β/δ, nature
nominal/backup, label), l'ajout d'arc, la suppression d'arc confirmée, la
taxonomie (catégories, tags, affectation) et les statuts de tâche. Toutes les
écritures métier passent par :class:`~supplyscore.services.mutations.MutationService`
(``source="edit"``, opérateur courant) ou par la façade
:class:`~supplyscore.services.orchestrator.SupplyScoreService` ; chaque action
réussie incrémente ``dcc.Store(id="graph-edit-refresh")``, qui re-rend le
tableau et toutes les listes déroulantes.

Pièges documentés :

- **Anti-cycle AVANT toute écriture** : ``MutationService.upsert_arc`` commite
  l'arc dans le REGISTRE puis seulement synchronise le graphe en mémoire
  (``_sync_repo_arc`` → ``repo.add_arc``). Si le ``ValueError`` de cycle du
  dépôt partait de là, l'arc resterait COMMITÉ en base sans rollback possible.
  Le contrôle anti-cycle (:func:`_creerait_un_cycle`, BFS sur
  ``repo.successors`` du client vers le fournisseur, arcs nominaux seulement)
  est donc fait ICI, avant tout appel à ``upsert_arc`` — à l'ajout d'arc comme
  au passage backup → nominal dans le tableau. La boucle sur soi-même est
  refusée pour toutes les natures.
- **UN SEUL ``dcc.ConfirmDialogProvider`` sur la page** (suppression d'arc) :
  plusieurs boîtes de confirmation natives sur une même page créent une race
  entre leurs ``submit_n_clicks`` (un dialogue peut rester armé et valider
  l'action d'une AUTRE carte au clic suivant). Règle : une boîte par page.
- **Diff du tableau par ligne** : chaque ligne porte une clé ``id`` stable
  ``"source_id->target_id"`` (jamais affichée — clé de diff fiable même après
  tri) ; le diff se fait contre ``data_previous`` (None au premier rendu →
  ``no_update`` intégral). Une valeur hors bornes ou une nature inconnue
  recharge le tableau depuis le registre : rien n'est écrit, aucune ligne
  d'audit n'est créée (la validation de ``upsert_arc`` précède toute écriture).
"""

from __future__ import annotations

import uuid
from typing import Any

from dash import Input, Output, State, dash_table, dcc, html, no_update
from dash.exceptions import PreventUpdate

from supplyscore.domain.models import ArcKind, SupplyArc, SupplyNode, TaskStatus
from supplyscore.domain.tags import Tag, TagCategory
from supplyscore.graph.repository import GraphRepository
from supplyscore.services.orchestrator import SupplyScoreService
from supplyscore.web_ui import get_service
from supplyscore.web_ui.components.layout import (
    BUTTON_STYLE,
    COLORS,
    FONT_FAMILY,
    INPUT_STYLE,
    MSG_ALERT_STYLE,
    MSG_OK_STYLE,
    PAGE_STYLE,
    STATUS_FR,
    card,
    labelled,
    node_options,
)
from supplyscore.web_ui.components.operator import current_operator

#: Bouton d'action destructive (suppression d'arc), aligné sur la page Simulation.
_BUTTON_DANGER_STYLE = {**BUTTON_STYLE, "backgroundColor": COLORS["alert"]}

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

#: Sous-titres internes de la carte « Tags & taxonomie ».
_H4_STYLE = {"margin": "14px 0 6px", "fontSize": "15px", "color": COLORS["primary"]}

#: Colonnes du tableau des arcs — Fournisseur/Client en lecture seule,
#: γ/β/δ numériques éditables, Nature en dropdown par colonne, Label libre.
_ARC_COLUMNS: list[dict[str, Any]] = [
    {"name": "Fournisseur", "id": "Fournisseur", "editable": False},
    {"name": "Client", "id": "Client", "editable": False},
    {"name": "γ", "id": "gamma", "type": "numeric", "editable": True},
    {"name": "β", "id": "beta", "type": "numeric", "editable": True},
    {"name": "δ", "id": "delta", "type": "numeric", "editable": True},
    {"name": "Nature", "id": "Nature", "presentation": "dropdown", "editable": True},
    {"name": "Label", "id": "Label", "editable": True},
]

#: Options du dropdown de colonne « Nature » (valeurs = membres d'ArcKind).
_NATURE_DROPDOWN: dict[str, dict[str, Any]] = {
    "Nature": {
        "options": [
            {"label": "nominal", "value": str(ArcKind.NOMINAL)},
            {"label": "backup", "value": str(ArcKind.BACKUP)},
        ]
    }
}

#: Options du dropdown « Nature » de la carte d'ajout d'arc.
_NATURE_OPTIONS: list[dict[str, str]] = [
    {"label": "Nominal (flux réel)", "value": str(ArcKind.NOMINAL)},
    {"label": "Backup (secours, inerte)", "value": str(ArcKind.BACKUP)},
]


# --- Helpers purs ------------------------------------------------------------------


def _creerait_un_cycle(repo: GraphRepository, source_id: str, target_id: str) -> bool:
    """Vrai si l'arc NOMINAL ``source -> target`` fermerait un cycle.

    BFS sur ``repo.successors`` (arcs nominaux seulement) depuis le CLIENT
    (``target_id``) : si le FOURNISSEUR (``source_id``) est atteignable, alors
    ajouter l'arc fournisseur → client fermerait le cycle. La boucle sur
    soi-même est un cycle par définition.

    Args:
        repo: dépôt de graphe en mémoire.
        source_id: nœud fournisseur de l'arc envisagé.
        target_id: nœud client de l'arc envisagé.

    Returns:
        True si l'ajout (ou le passage en nominal) doit être refusé.
    """
    if source_id == target_id:
        return True
    a_visiter = [target_id]
    vus = {target_id}
    while a_visiter:
        courant = a_visiter.pop()
        for successeur in repo.successors(courant):
            if successeur.id == source_id:
                return True
            if successeur.id not in vus:
                vus.add(successeur.id)
                a_visiter.append(successeur.id)
    return False


def _project_nodes(service: SupplyScoreService, project_id: str | None) -> list[SupplyNode]:
    """Nœuds du projet actif (tout le graphe si aucun projet n'est sélectionné)."""
    nodes = service.repo.nodes()
    if project_id:
        nodes = [n for n in nodes if n.project_id == project_id]
    return nodes


def _project_arcs(service: SupplyScoreService, project_id: str | None) -> list[SupplyArc]:
    """Arcs du registre dont les DEUX extrémités appartiennent au projet actif."""
    ids = {n.id for n in _project_nodes(service, project_id)}
    return [a for a in service.registry.list_arcs() if a.source_id in ids and a.target_id in ids]


def _arc_rows(service: SupplyScoreService, project_id: str | None) -> list[dict[str, Any]]:
    """Lignes du tableau des arcs — clé ``id`` stable ``"source->target"``."""
    names = {n.id: n.name for n in service.repo.nodes()}
    return [
        {
            "id": arc.id,
            "Fournisseur": names.get(arc.source_id, arc.source_id),
            "Client": names.get(arc.target_id, arc.target_id),
            "gamma": arc.gamma,
            "beta": arc.beta,
            "delta": arc.delta,
            "Nature": str(arc.kind_arc),
            "Label": arc.label,
        }
        for arc in _project_arcs(service, project_id)
    ]


def _arc_options(service: SupplyScoreService, project_id: str | None) -> list[dict[str, str]]:
    """Options « Fournisseur → Client » du dropdown de suppression d'arc."""
    names = {n.id: n.name for n in service.repo.nodes()}
    return [
        {
            "label": (
                f"{names.get(a.source_id, a.source_id)} → {names.get(a.target_id, a.target_id)}"
            ),
            "value": a.id,
        }
        for a in _project_arcs(service, project_id)
    ]


def _tag_options(service: SupplyScoreService, project_id: str | None) -> list[dict[str, str]]:
    """Options du dropdown des tags du projet — « nom (catégorie) » si rattaché."""
    if not project_id:
        return []
    categories = {c.id: c.name for c in service.registry.list_tag_categories(project_id)}
    options = []
    for tag in service.registry.list_tags(project_id):
        cat = categories.get(tag.category_id or "")
        label = f"{tag.name} ({cat})" if cat else tag.name
        options.append({"label": label, "value": tag.id})
    return options


def _category_options(service: SupplyScoreService, project_id: str | None) -> list[dict[str, str]]:
    """Options du dropdown des catégories de tags du projet."""
    if not project_id:
        return []
    categories = service.registry.list_tag_categories(project_id)
    return [{"label": c.name, "value": c.id} for c in categories]


def _to_float(value: Any, field: str) -> float:
    """Coerce une valeur de cellule en flottant (message français sinon).

    Args:
        value: contenu brut de la cellule (nombre, chaîne, None…).
        field: nom affiché du champ (γ, β, δ) pour le message d'erreur.

    Returns:
        La valeur convertie en ``float``.

    Raises:
        ValueError: si la valeur n'est pas convertible en nombre.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} doit être un nombre (reçu : {value!r})") from None


def _to_kind(value: Any) -> ArcKind:
    """Coerce la valeur de la colonne « Nature » en :class:`ArcKind` (message français)."""
    try:
        return ArcKind(str(value))
    except ValueError:
        raise ValueError(
            f"nature d'arc inconnue : {value!r} (attendu « nominal » ou « backup »)"
        ) from None


def _arc_label(service: SupplyScoreService, source_id: str, target_id: str) -> str:
    """Libellé humain « Fournisseur → Client » d'un arc (noms des nœuds)."""
    names = {n.id: n.name for n in service.repo.nodes()}
    return f"{names.get(source_id, source_id)} → {names.get(target_id, target_id)}"


# --- Layout -----------------------------------------------------------------------


def layout() -> html.Div:
    """Construit la page Éditeur de graphe (état du service relu à chaque navigation)."""
    return html.Div(
        [
            dcc.Store(id="graph-edit-refresh", data=0),
            html.H2("Éditeur de graphe", style={"margin": "6px 0 6px"}),
            html.Div(id="graph-info", style={"marginBottom": "14px"}),
            card(
                "Arcs",
                [
                    dash_table.DataTable(  # type: ignore[attr-defined]
                        id="arc-edit-table",
                        columns=_ARC_COLUMNS,
                        data=[],
                        editable=True,
                        dropdown=_NATURE_DROPDOWN,
                        style_cell=_TABLE_STYLE_CELL,
                        style_header=_TABLE_STYLE_HEADER,
                    ),
                    html.Div(id="arc-table-msg"),
                ],
                subtitle=(
                    "γ et β dans [0, 1], δ dans [0, 2] — une valeur hors bornes est rejetée "
                    "et le tableau rechargé. La nature backup est inerte dans les calculs."
                ),
            ),
            card(
                "Ajouter un arc",
                [
                    labelled(
                        "Fournisseur (source)",
                        dcc.Dropdown(
                            id="arc-add-source-dd", options=[], placeholder="Choisir un nœud…"
                        ),
                        width="320px",
                    ),
                    labelled(
                        "Client (cible)",
                        dcc.Dropdown(
                            id="arc-add-target-dd", options=[], placeholder="Choisir un nœud…"
                        ),
                        width="320px",
                    ),
                    labelled(
                        "γ (dépendance Ud, descendante)",
                        dcc.Slider(
                            id="arc-add-gamma",
                            min=0,
                            max=1,
                            step=0.05,
                            value=0.5,
                            marks={0: "0", 0.5: "0.5", 1: "1"},
                            tooltip={"placement": "bottom"},
                        ),
                        width="280px",
                    ),
                    labelled(
                        "β (propagation Ur, montante)",
                        dcc.Slider(
                            id="arc-add-beta",
                            min=0,
                            max=1,
                            step=0.05,
                            value=0.5,
                            marks={0: "0", 0.5: "0.5", 1: "1"},
                            tooltip={"placement": "bottom"},
                        ),
                        width="280px",
                    ),
                    labelled(
                        "Nature",
                        dcc.Dropdown(
                            id="arc-add-nature-dd",
                            options=_NATURE_OPTIONS,
                            value=str(ArcKind.NOMINAL),
                            clearable=False,
                        ),
                        width="240px",
                    ),
                    html.Div(html.Button("Ajouter l'arc", id="arc-add-btn", style=BUTTON_STYLE)),
                    html.Div(id="arc-add-msg"),
                ],
                subtitle=(
                    "Un arc nominal qui fermerait un cycle est refusé AVANT toute écriture ; "
                    "les rangs sont recalés puis le réseau réévalué."
                ),
            ),
            card(
                "Supprimer un arc",
                [
                    labelled(
                        "Arc",
                        dcc.Dropdown(id="arc-del-dd", options=[], placeholder="Choisir un arc…"),
                        width="380px",
                    ),
                    html.Div(
                        # UN SEUL ConfirmDialogProvider sur toute la page : plusieurs
                        # boîtes natives créent une race entre submit_n_clicks.
                        dcc.ConfirmDialogProvider(
                            children=html.Button("Supprimer l'arc", style=_BUTTON_DANGER_STYLE),
                            id="arc-del-confirm",
                            message="Supprimer l'arc ? La propagation sera recalculée.",
                        )
                    ),
                    html.Div(id="arc-del-msg"),
                ],
                subtitle="Suppression définitive : rangs recalés et réseau réévalué.",
            ),
            card(
                "Supprimer un nœud",
                [
                    labelled(
                        "Nœud",
                        dcc.Dropdown(id="node-del-dd", options=[], placeholder="Choisir un nœud…"),
                        width="380px",
                    ),
                    dcc.Checklist(
                        id="node-del-ack",
                        options=[
                            {
                                "label": (
                                    " Je confirme : le nœud, ses arcs, jalons et tags seront "
                                    "retirés du graphe (sa base de données est archivée)."
                                ),
                                "value": "oui",
                            }
                        ],
                        value=[],
                        style={"fontSize": "13px", "margin": "6px 0"},
                    ),
                    html.Div(
                        html.Button(
                            "Supprimer le nœud", id="node-del-btn", style=_BUTTON_DANGER_STYLE
                        )
                    ),
                    html.Div(id="node-del-msg"),
                ],
                subtitle=(
                    "La base SQLite du client est CONSERVÉE en archive — seules la structure "
                    "et les références sont retirées (jamais de perte d'historique)."
                ),
            ),
            card(
                "Tags & taxonomie",
                [
                    html.H4("Nouvelle catégorie", style={**_H4_STYLE, "marginTop": "0"}),
                    labelled(
                        "Nom de la catégorie",
                        dcc.Input(id="tag-cat-name-input", type="text", style=INPUT_STYLE),
                    ),
                    labelled(
                        "Couleur (DAG)",
                        dcc.Input(
                            id="tag-cat-color-input",
                            # Le stub Dash ne liste pas "color", mais le navigateur
                            # rend bien le sélecteur natif <input type="color">.
                            type="color",  # type: ignore[arg-type]
                            value=COLORS["primary"],
                            style={**INPUT_STYLE, "height": "36px", "padding": "2px"},
                        ),
                        width="120px",
                    ),
                    html.Div(
                        html.Button(
                            "Créer la catégorie", id="tag-cat-create-btn", style=BUTTON_STYLE
                        )
                    ),
                    html.H4("Nouveau tag", style=_H4_STYLE),
                    labelled(
                        "Nom du tag",
                        dcc.Input(id="tag-name-input", type="text", style=INPUT_STYLE),
                    ),
                    labelled(
                        "Catégorie (optionnelle)",
                        dcc.Dropdown(id="tag-cat-dd", options=[], placeholder="Aucune"),
                        width="260px",
                    ),
                    html.Div(html.Button("Créer le tag", id="tag-create-btn", style=BUTTON_STYLE)),
                    html.H4("Affecter des tags à un nœud", style=_H4_STYLE),
                    labelled(
                        "Nœud",
                        dcc.Dropdown(id="tag-node-dd", options=[], placeholder="Choisir un nœud…"),
                        width="320px",
                    ),
                    labelled(
                        "Tags (les tags actuels sont pré-remplis)",
                        dcc.Dropdown(id="tag-assign-dd", options=[], multi=True),
                        width="380px",
                    ),
                    html.Div(html.Button("Affecter", id="tag-assign-btn", style=BUTTON_STYLE)),
                    html.Div(id="tag-msg"),
                ],
                subtitle=(
                    "Catégories et tags du PROJET actif — affectation auditée (source « edit »)."
                ),
            ),
            card(
                "Statuts",
                [
                    labelled(
                        "Nœud",
                        dcc.Dropdown(
                            id="graph-status-node-dd", options=[], placeholder="Choisir un nœud…"
                        ),
                        width="320px",
                    ),
                    labelled(
                        "Statut",
                        dcc.Dropdown(
                            id="graph-status-dd",
                            options=[{"label": fr, "value": str(s)} for s, fr in STATUS_FR.items()],
                            placeholder="Choisir un statut…",
                        ),
                        width="200px",
                    ),
                    html.Div(html.Button("Appliquer", id="graph-status-btn", style=BUTTON_STYLE)),
                    html.Div(id="graph-status-msg"),
                ],
                subtitle="Le statut cascade sur les jalons puis le choc est propagé sur le graphe.",
            ),
        ],
        style=PAGE_STYLE,
    )


# --- Callbacks (fonctions nommées, testables sans serveur) -------------------------


def refresh_view_callback(project_data, _refresh):
    """Re-rend le tableau des arcs et toutes les listes déroulantes de la page.

    Déclenché par le changement de projet actif (``store-project``) et par
    chaque action réussie (``graph-edit-refresh``). Sans projet sélectionné,
    tout le graphe est affiché mais les tags (par projet) restent vides.

    Args:
        project_data: contenu de ``store-project`` (``{"project_id", "name"}``).
        _refresh: compteur ``graph-edit-refresh`` (seul le déclenchement compte).

    Returns:
        Lignes du tableau, options des sept dropdowns et bandeau d'information.
    """
    service = get_service()
    pid = (project_data or {}).get("project_id")
    nodes = _project_nodes(service, pid)
    opts = node_options(nodes)
    rows = _arc_rows(service, pid)
    if pid:
        name = (project_data or {}).get("name", pid)
        info = html.Span(
            f"Projet actif : « {name} » — {len(rows)} arc(s), {len(nodes)} nœud(s).",
            style={"color": COLORS["primary"], "fontWeight": "600"},
        )
    else:
        info = html.Span(
            "Aucun projet sélectionné — tout le graphe est affiché ; "
            "sélectionnez un projet (page Projets) pour gérer ses tags.",
            style={"color": COLORS["muted"]},
        )
    return (
        rows,
        opts,
        opts,
        _arc_options(service, pid),
        _category_options(service, pid),
        opts,
        _tag_options(service, pid),
        opts,
        opts,
        info,
    )


def edit_arc_callback(_timestamp, data, data_previous, project_data, operator_data, refresh):
    """Applique les éditions de cellules du tableau des arcs (diff par ligne ``id``).

    Au premier rendu, ``data_previous`` vaut None : ``no_update`` intégral.
    Chaque ligne modifiée reconstruit un :class:`SupplyArc` complet (KPIs de
    l'arc existant conservés) passé à ``mutations.upsert_arc(source="edit")``.
    Le passage backup → nominal est contrôlé anti-cycle AVANT l'écriture
    (cf. docstring du module : ``upsert_arc`` ne garantit pas le rollback).
    Si la nature a changé, les rangs sont recalés ; le réseau est ensuite
    réévalué avec persistance. Toute erreur recharge le tableau depuis le
    registre (aucune écriture, aucun audit) avec un message français.

    Args:
        _timestamp: ``data_timestamp`` du tableau (déclencheur seulement).
        data: contenu courant du tableau.
        data_previous: contenu précédent (None au premier rendu).
        project_data: contenu de ``store-project``.
        operator_data: contenu de ``store-operator``.
        refresh: compteur courant de ``graph-edit-refresh``.

    Returns:
        ``(données du tableau, message, refresh)`` — table ``no_update`` en cas
        de succès (anti-scintillement), rechargée en cas d'erreur.
    """
    if data_previous is None:
        return no_update, no_update, no_update
    service = get_service()
    pid = (project_data or {}).get("project_id")
    operator_id = current_operator(operator_data)
    previous_by_id = {row.get("id"): row for row in data_previous}
    changements = 0
    nature_changee = False
    try:
        for row in data or []:
            avant = previous_by_id.get(row.get("id"))
            if avant is None or row == avant:
                continue
            arc_id = str(row["id"])
            source_id, target_id = arc_id.split("->", 1)
            existant = service.registry.get_arc(source_id, target_id)
            if existant is None:
                raise ValueError(f"arc inconnu du registre : {arc_id!r}")
            nouveau = SupplyArc(
                source_id=source_id,
                target_id=target_id,
                label=str(row.get("Label") or existant.label),
                gamma=_to_float(row.get("gamma"), "γ"),
                beta=_to_float(row.get("beta"), "β"),
                delta=_to_float(row.get("delta"), "δ"),
                kind_arc=_to_kind(row.get("Nature")),
                kpis=existant.kpis,
            )
            if nouveau.kind_arc is not existant.kind_arc:
                if nouveau.kind_arc is ArcKind.NOMINAL and _creerait_un_cycle(
                    service.repo, source_id, target_id
                ):
                    raise ValueError(
                        f"l'arc « {_arc_label(service, source_id, target_id)} » repassé "
                        "en nominal créerait un cycle dans le graphe"
                    )
                nature_changee = True
            changements += len(
                service.mutations.upsert_arc(nouveau, source="edit", operator_id=operator_id)
            )
    except ValueError as exc:
        return (
            _arc_rows(service, pid),
            html.Span(f"Modification refusée : {exc}", style=MSG_ALERT_STYLE),
            no_update,
        )
    if changements == 0:
        return no_update, no_update, no_update
    if nature_changee:
        service.reassign_ranks()
    service.evaluate_all(persist=True)
    message = html.Span(
        f"{changements} champ(s) d'arc modifié(s) — réseau réévalué"
        + (" et rangs recalés." if nature_changee else "."),
        style=MSG_OK_STYLE,
    )
    return no_update, message, (refresh or 0) + 1


def add_arc_callback(n_clicks, source_id, target_id, gamma, beta, nature, operator_data, refresh):
    """Ajoute un arc fournisseur → client (anti-cycle AVANT toute écriture).

    Refus en français : sélection incomplète, boucle sur soi-même, arc déjà
    présent (à modifier dans le tableau), cycle nominal. En cas de succès :
    ``mutations.upsert_arc(source="edit")``, rangs recalés, réseau réévalué.

    Args:
        n_clicks: clics sur « Ajouter l'arc ».
        source_id: nœud fournisseur choisi.
        target_id: nœud client choisi.
        gamma: valeur du slider γ.
        beta: valeur du slider β.
        nature: nature choisie (nominal/backup).
        operator_data: contenu de ``store-operator``.
        refresh: compteur courant de ``graph-edit-refresh``.

    Returns:
        ``(message, refresh)`` — refresh inchangé (``no_update``) en cas d'échec.
    """
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    if not source_id or not target_id:
        return (
            html.Span("Choisissez un fournisseur ET un client.", style=MSG_ALERT_STYLE),
            no_update,
        )
    if source_id == target_id:
        return (
            html.Span(
                "Un nœud ne peut pas s'alimenter lui-même (boucle refusée).",
                style=MSG_ALERT_STYLE,
            ),
            no_update,
        )
    if service.registry.get_arc(source_id, target_id) is not None:
        return (
            html.Span(
                "Cet arc existe déjà — modifiez-le dans le tableau des arcs.",
                style=MSG_ALERT_STYLE,
            ),
            no_update,
        )
    kind = _to_kind(nature or str(ArcKind.NOMINAL))
    # Contrôle anti-cycle AVANT upsert_arc : le service commite le registre
    # avant de synchroniser le repo — il n'y aurait pas de rollback après coup.
    if kind is ArcKind.NOMINAL and _creerait_un_cycle(service.repo, source_id, target_id):
        return (
            html.Span(
                f"Ajout refusé : l'arc « {_arc_label(service, source_id, target_id)} » "
                "créerait un cycle dans le graphe.",
                style=MSG_ALERT_STYLE,
            ),
            no_update,
        )
    arc = SupplyArc(
        source_id=source_id,
        target_id=target_id,
        gamma=float(gamma) if gamma is not None else 0.5,
        beta=float(beta) if beta is not None else 0.5,
        kind_arc=kind,
    )
    try:
        service.mutations.upsert_arc(
            arc, source="edit", operator_id=current_operator(operator_data)
        )
    except ValueError as exc:  # bornes γ/β/δ — message français du service
        return html.Span(f"Ajout refusé : {exc}", style=MSG_ALERT_STYLE), no_update
    service.reassign_ranks()
    service.evaluate_all(persist=True)
    message = html.Span(
        f"Arc « {_arc_label(service, source_id, target_id)} » ajouté — "
        "rangs recalés et réseau réévalué.",
        style=MSG_OK_STYLE,
    )
    return message, (refresh or 0) + 1


def delete_arc_callback(submit_n_clicks, arc_value, refresh):
    """Supprime l'arc choisi après confirmation (``service.remove_arc``).

    Args:
        submit_n_clicks: confirmations du ``dcc.ConfirmDialogProvider``.
        arc_value: id de l'arc choisi (``"source->target"``).
        refresh: compteur courant de ``graph-edit-refresh``.

    Returns:
        ``(message, refresh)`` — refresh inchangé en cas d'échec.
    """
    if not submit_n_clicks:
        raise PreventUpdate
    service = get_service()
    if not arc_value:
        return (
            html.Span("Choisissez d'abord un arc à supprimer.", style=MSG_ALERT_STYLE),
            no_update,
        )
    source_id, target_id = str(arc_value).split("->", 1)
    libelle = _arc_label(service, source_id, target_id)
    try:
        service.remove_arc(source_id, target_id)
    except KeyError as exc:  # message français du dépôt
        return html.Span(str(exc.args[0]), style=MSG_ALERT_STYLE), no_update
    message = html.Span(
        f"Arc « {libelle} » supprimé — rangs recalés et propagation recalculée.",
        style=MSG_OK_STYLE,
    )
    return message, (refresh or 0) + 1


def create_category_callback(n_clicks, name, color, project_data, refresh):
    """Crée une catégorie de tags pour le projet actif (nom + couleur du DAG).

    Args:
        n_clicks: clics sur « Créer la catégorie ».
        name: nom saisi.
        color: couleur hex de l'input ``type="color"``.
        project_data: contenu de ``store-project``.
        refresh: compteur courant de ``graph-edit-refresh``.

    Returns:
        ``(message, refresh)`` — refresh inchangé en cas d'échec.
    """
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    pid = (project_data or {}).get("project_id")
    if not pid:
        return html.Span("Sélectionnez d'abord un projet actif.", style=MSG_ALERT_STYLE), no_update
    if not name or not str(name).strip():
        return html.Span("Le nom de la catégorie est requis.", style=MSG_ALERT_STYLE), no_update
    category = TagCategory(
        id=str(uuid.uuid4()), project_id=pid, name=str(name).strip(), color=color or None
    )
    service.registry.save_tag_category(category)
    message = html.Span(f"Catégorie « {category.name} » créée.", style=MSG_OK_STYLE)
    return message, (refresh or 0) + 1


def create_tag_callback(n_clicks, name, category_id, project_data, refresh):
    """Crée un tag du projet actif, rattaché ou non à une catégorie.

    Args:
        n_clicks: clics sur « Créer le tag ».
        name: nom saisi.
        category_id: catégorie choisie (None = tag libre).
        project_data: contenu de ``store-project``.
        refresh: compteur courant de ``graph-edit-refresh``.

    Returns:
        ``(message, refresh)`` — refresh inchangé en cas d'échec.
    """
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    pid = (project_data or {}).get("project_id")
    if not pid:
        return html.Span("Sélectionnez d'abord un projet actif.", style=MSG_ALERT_STYLE), no_update
    if not name or not str(name).strip():
        return html.Span("Le nom du tag est requis.", style=MSG_ALERT_STYLE), no_update
    tag = Tag(
        id=str(uuid.uuid4()),
        project_id=pid,
        name=str(name).strip(),
        category_id=category_id or None,
    )
    service.registry.save_tag(tag)
    message = html.Span(f"Tag « {tag.name} » créé.", style=MSG_OK_STYLE)
    return message, (refresh or 0) + 1


def node_tags_callback(node_id):
    """Pré-remplit le dropdown multi des tags avec les tags ACTUELS du nœud choisi.

    Args:
        node_id: nœud choisi dans « Affecter des tags à un nœud ».

    Returns:
        La liste des ids de tags actuellement liés au nœud ([] sans nœud).
    """
    if not node_id:
        return []
    service = get_service()
    return [tag.id for tag in service.registry.tags_of_node(str(node_id))]


def assign_tags_callback(n_clicks, node_id, tag_ids, operator_data, refresh):
    """Remplace les tags du nœud choisi (``mutations.set_node_tags(source="edit")``).

    Args:
        n_clicks: clics sur « Affecter ».
        node_id: nœud choisi.
        tag_ids: ids de tags choisis (liste, None = vide).
        operator_data: contenu de ``store-operator``.
        refresh: compteur courant de ``graph-edit-refresh``.

    Returns:
        ``(message, refresh)`` — refresh inchangé en cas d'échec.
    """
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    if not node_id:
        return html.Span("Choisissez d'abord un nœud.", style=MSG_ALERT_STYLE), no_update
    try:
        entries = service.mutations.set_node_tags(
            str(node_id),
            [str(t) for t in (tag_ids or [])],
            source="edit",
            operator_id=current_operator(operator_data),
        )
    except KeyError as exc:  # message français du service
        return html.Span(str(exc.args[0]), style=MSG_ALERT_STYLE), no_update
    node = service.registry.get_node(str(node_id))
    name = node.name if node is not None else str(node_id)
    if not entries:
        message = html.Span(
            f"Tags de « {name} » inchangés (aucune différence).", style=MSG_OK_STYLE
        )
        return message, no_update
    message = html.Span(
        f"Tags de « {name} » mis à jour ({len(tag_ids or [])} tag(s)).", style=MSG_OK_STYLE
    )
    return message, (refresh or 0) + 1


def apply_status_callback(n_clicks, node_id, status_value, refresh):
    """Applique un statut de tâche au nœud choisi (``service.set_status``).

    Args:
        n_clicks: clics sur « Appliquer ».
        node_id: nœud choisi.
        status_value: statut choisi (valeur de :class:`TaskStatus`).
        refresh: compteur courant de ``graph-edit-refresh``.

    Returns:
        ``(message, refresh)`` — refresh inchangé en cas d'échec.
    """
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    if not node_id or not status_value:
        return html.Span("Choisissez un nœud ET un statut.", style=MSG_ALERT_STYLE), no_update
    status = TaskStatus(status_value)
    service.set_status(str(node_id), status)
    node = service.repo.get_node(str(node_id))
    name = node.name if node is not None else str(node_id)
    message = html.Span(
        f"Statut « {STATUS_FR[status]} » appliqué à « {name} » — choc propagé sur le graphe.",
        style=MSG_OK_STYLE,
    )
    return message, (refresh or 0) + 1


def delete_node_callback(n_clicks, node_id, ack, refresh):
    """Supprime un nœud du graphe (base client archivée) après confirmation cochée."""
    if not n_clicks:
        raise PreventUpdate
    service = get_service()
    if not node_id:
        return html.Span("Choisissez un nœud.", style=MSG_ALERT_STYLE), no_update
    if "oui" not in (ack or []):
        return (
            html.Span("Cochez la case de confirmation avant de supprimer.", style=MSG_ALERT_STYLE),
            no_update,
        )
    node = service.repo.get_node(node_id)
    name = node.name if node is not None else node_id
    try:
        service.remove_node(node_id)
    except KeyError as exc:
        return html.Span(str(exc), style=MSG_ALERT_STYLE), no_update
    msg = html.Span(
        f"Nœud « {name} » supprimé — rangs recalés, réseau réévalué, base client archivée.",
        style=MSG_OK_STYLE,
    )
    return msg, (refresh or 0) + 1


def register_callbacks(app) -> None:
    """Enregistre les callbacks de la page Éditeur de graphe sur l'application Dash."""
    app.callback(
        Output("arc-edit-table", "data"),
        Output("arc-add-source-dd", "options"),
        Output("arc-add-target-dd", "options"),
        Output("arc-del-dd", "options"),
        Output("tag-cat-dd", "options"),
        Output("tag-node-dd", "options"),
        Output("tag-assign-dd", "options"),
        Output("graph-status-node-dd", "options"),
        Output("node-del-dd", "options"),
        Output("graph-info", "children"),
        Input("store-project", "data"),
        Input("graph-edit-refresh", "data"),
    )(refresh_view_callback)

    app.callback(
        Output("node-del-msg", "children"),
        Output("graph-edit-refresh", "data", allow_duplicate=True),
        Input("node-del-btn", "n_clicks"),
        State("node-del-dd", "value"),
        State("node-del-ack", "value"),
        State("graph-edit-refresh", "data"),
        prevent_initial_call=True,
    )(delete_node_callback)

    app.callback(
        Output("arc-edit-table", "data", allow_duplicate=True),
        Output("arc-table-msg", "children"),
        Output("graph-edit-refresh", "data", allow_duplicate=True),
        Input("arc-edit-table", "data_timestamp"),
        State("arc-edit-table", "data"),
        State("arc-edit-table", "data_previous"),
        State("store-project", "data"),
        State("store-operator", "data"),
        State("graph-edit-refresh", "data"),
        prevent_initial_call=True,
    )(edit_arc_callback)

    app.callback(
        Output("arc-add-msg", "children"),
        Output("graph-edit-refresh", "data", allow_duplicate=True),
        Input("arc-add-btn", "n_clicks"),
        State("arc-add-source-dd", "value"),
        State("arc-add-target-dd", "value"),
        State("arc-add-gamma", "value"),
        State("arc-add-beta", "value"),
        State("arc-add-nature-dd", "value"),
        State("store-operator", "data"),
        State("graph-edit-refresh", "data"),
        prevent_initial_call=True,
    )(add_arc_callback)

    app.callback(
        Output("arc-del-msg", "children"),
        Output("graph-edit-refresh", "data", allow_duplicate=True),
        Input("arc-del-confirm", "submit_n_clicks"),
        State("arc-del-dd", "value"),
        State("graph-edit-refresh", "data"),
        prevent_initial_call=True,
    )(delete_arc_callback)

    app.callback(
        Output("tag-msg", "children"),
        Output("graph-edit-refresh", "data", allow_duplicate=True),
        Input("tag-cat-create-btn", "n_clicks"),
        State("tag-cat-name-input", "value"),
        State("tag-cat-color-input", "value"),
        State("store-project", "data"),
        State("graph-edit-refresh", "data"),
        prevent_initial_call=True,
    )(create_category_callback)

    app.callback(
        Output("tag-msg", "children", allow_duplicate=True),
        Output("graph-edit-refresh", "data", allow_duplicate=True),
        Input("tag-create-btn", "n_clicks"),
        State("tag-name-input", "value"),
        State("tag-cat-dd", "value"),
        State("store-project", "data"),
        State("graph-edit-refresh", "data"),
        prevent_initial_call=True,
    )(create_tag_callback)

    app.callback(
        Output("tag-assign-dd", "value"),
        Input("tag-node-dd", "value"),
        prevent_initial_call=True,
    )(node_tags_callback)

    app.callback(
        Output("tag-msg", "children", allow_duplicate=True),
        Output("graph-edit-refresh", "data", allow_duplicate=True),
        Input("tag-assign-btn", "n_clicks"),
        State("tag-node-dd", "value"),
        State("tag-assign-dd", "value"),
        State("store-operator", "data"),
        State("graph-edit-refresh", "data"),
        prevent_initial_call=True,
    )(assign_tags_callback)

    app.callback(
        Output("graph-status-msg", "children"),
        Output("graph-edit-refresh", "data", allow_duplicate=True),
        Input("graph-status-btn", "n_clicks"),
        State("graph-status-node-dd", "value"),
        State("graph-status-dd", "value"),
        State("graph-edit-refresh", "data"),
        prevent_initial_call=True,
    )(apply_status_callback)
