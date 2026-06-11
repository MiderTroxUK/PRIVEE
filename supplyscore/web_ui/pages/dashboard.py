"""Page « Dashboard » : indicateurs globaux, DAG, tableau détaillé, historique.

Callbacks en fonctions nommées au niveau module, enregistrées dans
:func:`register_callbacks` — testables sans serveur.
"""

from __future__ import annotations

import numpy as np
from dash import Input, Output, dash_table, dcc, html

from supplyscore.core import BLOCKS
from supplyscore.domain.models import TaskStatus
from supplyscore.services.weekly import CycleHebdomadaire, EtatHebdo, StatutHebdo
from supplyscore.web_ui import get_service
from supplyscore.web_ui.components.badges import style_hebdo_conditionnel, texte_hebdo
from supplyscore.web_ui.components.explain_figures import BLOCK_LABELS_FR
from supplyscore.web_ui.components.figures import (
    correlation_heatmap_figure,
    dashboard_dag_figure,
    empty_figure,
    promethee_bars_figure,
    urgency_history_figure,
)
from supplyscore.web_ui.components.layout import (
    BUTTON_STYLE,
    CARD_STYLE,
    COLORS,
    FONT_FAMILY,
    PAGE_STYLE,
    STATUS_FR,
    card,
    labelled,
    node_options,
)

_VALUE_COLUMNS = ["Ud_loc", "Ur_loc", "Ud", "Ur", "A", "F", "H"]

#: Palettes du DAG (Lot 16.2) : libellés français, valeurs = colorscales Plotly.
#: « RdYlBu » remplace l'axe rouge-vert (indiscernable pour les daltoniens
#: deutéranopes/protanopes) par un axe rouge-bleu ; « Viridis » est
#: perceptuellement uniforme.
_PALETTE_OPTIONS: list[dict] = [
    {"label": "Rouge-Vert (défaut)", "value": "RdYlGn"},
    {"label": "Rouge-Bleu (daltonisme)", "value": "RdYlBu"},
    {"label": "Viridis", "value": "Viridis"},
]
_PALETTES: frozenset[str] = frozenset(o["value"] for o in _PALETTE_OPTIONS)
_PALETTE_DEFAUT: str = "RdYlGn"

#: Clé du réglage par projet (``project_settings``) portant la palette du DAG.
_CLE_PALETTE = "palette"

_TABLE_COLUMNS = (
    [
        {"name": "Nom", "id": "Nom"},
        {"name": "Rang", "id": "Rang", "type": "numeric"},
        {"name": "Statut", "id": "Statut"},
        {"name": "Hebdo", "id": "Hebdo"},
    ]
    + [{"name": c, "id": c, "type": "numeric"} for c in _VALUE_COLUMNS]
    + [{"name": "Pourquoi ?", "id": "Pourquoi", "presentation": "markdown"}]
)

#: Règles existantes (A < 40 fond rouge, H > 0.3 texte rouge) PUIS règles hebdo.
_TABLE_CONDITIONAL = [
    {"if": {"filter_query": "{A} < 40"}, "backgroundColor": "#fdecea"},
    {
        "if": {"filter_query": "{H} > 0.3", "column_id": "H"},
        "color": COLORS["alert"],
        "fontWeight": "700",
    },
    *style_hebdo_conditionnel("Hebdo"),
]

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

#: Seuil d'alerte |ρ| au-delà duquel deux blocs de poids fort sont signalés.
_SEUIL_CORRELATION = 0.8

#: Note de bas de carte PROMETHEE — limite documentée du classement (PLAN.md E12).
_NOTE_PERIMETRE = (
    "Le classement est RELATIF au périmètre du projet : ajouter ou retirer un "
    "nœud peut inverser des rangs (renversement de rang documenté)."
)

#: Bandeau d'avertissement orange (corrélation forte entre critères de poids fort).
_WARN_BANNER_STYLE = {
    "backgroundColor": "#fff4e5",
    "border": f"1px solid {COLORS['warn']}",
    "color": COLORS["warn"],
    "borderRadius": "6px",
    "padding": "10px 14px",
    "marginBottom": "10px",
    "fontSize": "13px",
}

#: Bandeau d'invitation bleu (état vide : aucun projet sélectionné, Lot 16.2).
_EMPTY_BANNER_STYLE = {
    "backgroundColor": "#eef4f8",
    "border": f"1px solid {COLORS['primary']}",
    "color": COLORS["primary"],
    "borderRadius": "6px",
    "padding": "10px 14px",
    "marginBottom": "14px",
    "fontSize": "14px",
    "fontWeight": "600",
}


def _r3(value: float | None) -> float | None:
    """Arrondit à 3 décimales en tolérant None.

    CHOIX DOCUMENTÉ (Lot 16.2) : les valeurs de la DataTable restent en
    NOTATION POINT — ses colonnes ``type="numeric"`` exigent des floats pour
    le tri et le filtre natifs ; seuls les TEXTES français (cartes KPI)
    passent en virgule décimale via :func:`_nombre_fr`.
    """
    return None if value is None else round(value, 3)


def _nombre_fr(valeur: float, decimales: int = 3) -> str:
    """Nombre en notation française (virgule décimale) pour les TEXTES affichés."""
    return f"{valeur:.{decimales}f}".replace(".", ",")


def _stat_card(value: str, label_text: str, color: str | None = None) -> html.Div:
    """Petite carte KPI (valeur en gros, libellé dessous)."""
    return html.Div(
        [
            html.Div(
                value,
                style={
                    "fontSize": "20px",
                    "fontWeight": "700",
                    "color": color or COLORS["primary"],
                },
            ),
            html.Div(label_text, style={"fontSize": "12px", "color": COLORS["muted"]}),
        ],
        style={**CARD_STYLE, "flex": "1 1 150px", "marginBottom": "0", "textAlign": "center"},
    )


def _coverage_card(coverage: tuple[int, int] | None) -> html.Div:
    """Carte « Questionnaires à jour : x/y » — vert si x == y, orange sinon.

    Sans projet sélectionné (``coverage`` à None), la carte affiche « — »
    en gris : aucune couverture calculable sans horloge de projet.
    """
    if coverage is None:
        return _stat_card("—", "Questionnaires à jour", color=COLORS["muted"])
    a_jour, total = coverage
    hue = COLORS["ok"] if a_jour == total else COLORS["warn"]
    return _stat_card(f"{a_jour}/{total}", "Questionnaires à jour", color=hue)


def _kpi_summary(nodes, coverage: tuple[int, int] | None = None) -> list[html.Div]:
    """Cartes KPI du haut de page : couverture hebdo, effectif, A, risques H et F."""
    a_known = [(n.urgency.adequation, n.name) for n in nodes if n.urgency.adequation is not None]
    if a_known:
        mean_a = _nombre_fr(sum(v for v, _ in a_known) / len(a_known), 1)
        worst_val, worst_name = min(a_known, key=lambda pair: pair[0])
        worst = f"{_nombre_fr(worst_val, 1)} ({worst_name})"
    else:
        mean_a, worst = "—", "—"
    hidden = sum(1 for n in nodes if (n.urgency.hidden_risk or 0.0) > 0.1)
    false_u = sum(1 for n in nodes if (n.urgency.false_urgency or 0.0) > 0.1)
    return [
        _coverage_card(coverage),
        _stat_card(str(len(nodes)), "Nœuds"),
        _stat_card(mean_a, "A moyen du projet"),
        _stat_card(worst, "Pire adéquation A"),
        _stat_card(str(hidden), "Risques cachés (H > 0.1)"),
        _stat_card(str(false_u), "Fausses urgences (F > 0.1)"),
    ]


def _scope_nodes(project_data):
    """Nœuds du projet actif, ou tout le graphe si aucun projet sélectionné."""
    service = get_service()
    pid = (project_data or {}).get("project_id")
    nodes = service.repo.nodes()
    if pid:
        nodes = [n for n in nodes if n.project_id == pid]
    return nodes


def layout() -> html.Div:
    """Construit la page Dashboard (état du service relu à chaque navigation)."""
    return html.Div(
        [
            html.H2("Dashboard", style={"margin": "6px 0 12px"}),
            html.Div(id="dash-empty-banner"),
            html.Div(
                [
                    html.Button("Recalculer maintenant", id="dash-recalc-btn", style=BUTTON_STYLE),
                    html.Div(
                        dcc.Dropdown(
                            id="dash-tags-dd",
                            options=[],
                            multi=True,
                            placeholder="Filtrer par tags…",
                        ),
                        style={"width": "320px", "marginLeft": "14px"},
                    ),
                ],
                style={"display": "flex", "alignItems": "center", "marginBottom": "14px"},
            ),
            html.Div(
                id="dash-kpi-cards",
                style={
                    "display": "flex",
                    "gap": "14px",
                    "flexWrap": "wrap",
                    "marginBottom": "18px",
                },
            ),
            card(
                "Chaîne logistique",
                [
                    labelled(
                        "Palette de couleurs",
                        dcc.Dropdown(
                            id="dash-palette-dd",
                            options=_PALETTE_OPTIONS,
                            value=_PALETTE_DEFAUT,
                            clearable=False,
                        ),
                        width="260px",
                    ),
                    # dcc.Loading ENVELOPPE le graphe : l'id "dash-dag" reste
                    # posé sur le composant interne (contrat des tests e2e).
                    dcc.Loading(
                        dcc.Graph(id="dash-dag", figure=empty_figure("Chargement…")),
                        type="circle",
                        color=COLORS["primary"],
                    ),
                ],
            ),
            card(
                "Priorités PROMETHEE II",
                [
                    html.Div(id="dash-promethee-warning"),
                    dcc.Loading(
                        [
                            dcc.Graph(
                                id="dash-promethee-fig",
                                figure=empty_figure(
                                    "Sélectionnez un projet pour afficher le classement "
                                    "PROMETHEE II."
                                ),
                            ),
                            dcc.Graph(
                                id="dash-correlation-fig",
                                figure=empty_figure(
                                    "Sélectionnez un projet pour afficher la corrélation "
                                    "des critères."
                                ),
                            ),
                        ],
                        type="circle",
                        color=COLORS["primary"],
                    ),
                    html.P(
                        _NOTE_PERIMETRE,
                        style={
                            "margin": "8px 0 0",
                            "fontSize": "12px",
                            "color": COLORS["muted"],
                            "fontStyle": "italic",
                        },
                    ),
                ],
                subtitle=(
                    "Classement multicritère des nœuds actifs (flux nets φ) et "
                    "diagnostic de corrélation des 6 blocs d'urgence."
                ),
            ),
            card(
                "Détail des nœuds",
                [
                    # E14.3 — pagination native SEULE (page_size=25), SANS
                    # virtualization : les deux mécanismes sont redondants
                    # (25 lignes rendues par page suffisent à 1 000+ nœuds) et
                    # virtualization=True exige des hauteurs de lignes fixes et
                    # casse le rendu des colonnes presentation="markdown"
                    # (« Pourquoi ? ») dans plusieurs versions de dash-table.
                    dcc.Loading(
                        dash_table.DataTable(  # type: ignore[attr-defined]
                            id="dash-table",
                            columns=_TABLE_COLUMNS,
                            data=[],
                            sort_action="native",
                            filter_action="native",
                            page_action="native",
                            page_size=25,
                            virtualization=False,
                            style_cell=_TABLE_STYLE_CELL,
                            style_header=_TABLE_STYLE_HEADER,
                            style_data_conditional=_TABLE_CONDITIONAL,
                            style_as_list_view=True,
                        ),
                        type="circle",
                        color=COLORS["primary"],
                    )
                ],
                subtitle=(
                    "Fond rouge clair : A < 40 · H en rouge : H > 0.3 · "
                    "Hebdo coloré selon le statut (A/F/H « — » si questionnaire manquant)."
                ),
            ),
            card(
                "Évolution temporelle",
                [
                    labelled(
                        "Nœud",
                        dcc.Dropdown(
                            id="dash-history-dd", options=[], placeholder="Choisir un nœud…"
                        ),
                        width="380px",
                    ),
                    dcc.Graph(
                        id="dash-history-fig",
                        figure=empty_figure("Sélectionnez un nœud pour afficher son historique."),
                    ),
                ],
            ),
        ],
        style=PAGE_STYLE,
    )


# --- Callbacks (fonctions nommées, testables sans serveur) -----------------------


def _triggered_id():
    """Id du composant déclencheur (None hors contexte de requête Dash)."""
    try:  # ctx indisponible hors requête Dash (appel direct en test)
        from dash import ctx

        return ctx.triggered_id
    except Exception:
        return None


def _palette_effective(service, project_id, palette, persister: bool) -> str:
    """Palette du DAG : persistée par projet, relue au rendu (Lot 16.2).

    Si ``persister`` (le dropdown a déclenché le rafraîchissement) et qu'un
    projet est actif, la valeur est écrite dans ``project_settings``
    (clé :data:`_CLE_PALETTE`). Sinon la valeur STOCKÉE du projet fait foi :
    au premier rendu le dropdown n'est pas encore synchronisé. Toute valeur
    inconnue retombe sur :data:`_PALETTE_DEFAUT`.

    Args:
        service: façade applicative.
        project_id: projet actif (ou None/vide).
        palette: valeur courante du dropdown (ou None).
        persister: True si le dropdown est le déclencheur du callback.

    Returns:
        La colorscale Plotly à passer à ``dashboard_dag_figure``.
    """
    if palette not in _PALETTES:
        palette = None
    if persister and project_id and palette:
        service.registry.set_setting(project_id, _CLE_PALETTE, palette)
        return palette
    if project_id:
        stockee = service.registry.get_setting(project_id, _CLE_PALETTE)
        if stockee in _PALETTES:
            return stockee
    return palette or _PALETTE_DEFAUT


def palette_value_callback(project_data):
    """Synchronise le dropdown palette sur le réglage du projet actif."""
    service = get_service()
    pid = (project_data or {}).get("project_id")
    stockee = service.registry.get_setting(pid, _CLE_PALETTE) if pid else None
    return stockee if stockee in _PALETTES else _PALETTE_DEFAUT


def empty_state_callback(project_data):
    """Bandeau d'invitation quand aucun projet n'est sélectionné (état vide).

    Avec un projet actif, la zone reste vide. Sans projet, le bandeau invite
    à en choisir un sur la page Projets — et précise, repo vide, qu'il faut
    d'abord créer un projet ou générer la démo (rien d'affichable sinon).
    """
    pid = (project_data or {}).get("project_id")
    if pid:
        return None
    service = get_service()
    if not service.repo.nodes():
        texte = "Aucun nœud à afficher : créez un projet ou générez la démo depuis la page Projets."
    else:
        texte = (
            "Aucun projet sélectionné — choisissez un projet sur la page "
            "Projets ; en attendant, tout le graphe est affiché."
        )
    return html.Div(texte, style=_EMPTY_BANNER_STYLE)


def _table_row(n, etat: EtatHebdo | None) -> dict:
    """Ligne du tableau détaillé pour un nœud, statut hebdo inclus.

    Sans état hebdo (aucun projet sélectionné), la colonne Hebdo affiche « — ».
    Pour un nœud MANQUANT, A/F/H affichent « — » : l'adéquation calculée
    contre un Ud inexistant est trompeuse (H artificiellement alarmant).
    """
    manquant = etat is not None and etat.statut is StatutHebdo.MANQUANT
    return {
        "Nom": n.name,
        "Rang": n.rank,
        "Statut": STATUS_FR.get(n.status, str(n.status)),
        "Hebdo": texte_hebdo(etat.statut, etat.semaines_de_retard) if etat is not None else "—",
        "Ud_loc": _r3(n.urgency.ud_local),
        "Ur_loc": _r3(n.urgency.ur_local),
        "Ud": _r3(n.urgency.ud),
        "Ur": _r3(n.urgency.ur),
        "A": "—" if manquant else _r3(n.urgency.adequation),
        "F": "—" if manquant else _r3(n.urgency.false_urgency),
        "H": "—" if manquant else _r3(n.urgency.hidden_risk),
        "Pourquoi": f"[Expliquer](/node/{n.id}/explication)",
    }


def tag_filter_options_callback(project_data):
    """Options du filtre par tags (tags du projet actif, valeur réinitialisée)."""
    service = get_service()
    pid = (project_data or {}).get("project_id")
    if not pid:
        return [], []
    options = [{"label": t.name, "value": t.id} for t in service.registry.list_tags(pid)]
    return sorted(options, key=lambda o: o["label"]), []


def update_dashboard_callback(project_data, n_clicks, tag_ids=None, palette=None):
    """Met à jour cartes KPI, DAG, tableau et options d'historique.

    Si le déclencheur est le bouton « Recalculer maintenant », le pipeline
    complet est relancé et persisté avant le rafraîchissement. Les états
    hebdo du projet sont construits en UNE passe (``synthese``), jamais
    nœud par nœud (N requêtes sinon). ``tag_ids`` filtre les nœuds affichés
    (intersection non vide avec ``node.tags``). ``palette`` (dropdown
    ``dash-palette-dd``) choisit la colorscale du DAG : persistée par projet
    quand le dropdown déclenche, relue des réglages sinon
    (:func:`_palette_effective`).
    """
    service = get_service()
    triggered = _triggered_id()
    if triggered == "dash-recalc-btn":
        service.evaluate_all(persist=True)

    nodes = _scope_nodes(project_data)
    if tag_ids:
        wanted = set(tag_ids)
        nodes = [n for n in nodes if wanted & set(n.tags)]
    ids = {n.id for n in nodes}
    arcs = [a for a in service.repo.arcs() if a.source_id in ids and a.target_id in ids]

    pid = (project_data or {}).get("project_id")
    palette_dag = _palette_effective(service, pid, palette, triggered == "dash-palette-dd")
    if pid:
        cycle = CycleHebdomadaire(service)
        etats = cycle.synthese(pid)
        coverage: tuple[int, int] | None = cycle.couverture(pid)
    else:  # aucun projet sélectionné : pas d'horloge de projet, pas d'états hebdo
        etats = {}
        coverage = None

    rows = [_table_row(n, etats.get(n.id)) for n in sorted(nodes, key=lambda n: (n.rank, n.name))]
    return (
        _kpi_summary(nodes, coverage),
        dashboard_dag_figure(nodes, arcs, colorscale=palette_dag),
        rows,
        node_options(nodes),
    )


# --- Carte « Priorités PROMETHEE II » (Lot 12.4b) -----------------------------------


def _noeuds_actifs(service, project_id):
    """Nœuds ACTIFS du projet, onboarding terminé — mêmes règles que le service.

    Le filtre reproduit celui de ``SupplyScoreService.classement_promethee``
    pour que la carte et le classement portent sur le MÊME périmètre.
    """
    return [
        n
        for n in service.repo.nodes_by_project(project_id)
        if n.status == TaskStatus.ACTIVE and n.onboarding_state != "draft"
    ]


def _blocs_par_noeud(service, project_id, actifs):
    """Blocs d'urgence analytiques par nœud actif du projet.

    Temps, jalons et modèle Ur viennent des MÊMES sources que
    ``classement_promethee`` (``_project_times`` / ``_ur_model_for``) : la
    matrice de corrélation diagnostique exactement les valeurs que PROMETHEE
    consomme.

    Returns:
        ``{node_id: {bloc: urgence ou None}}`` (cf. :data:`BLOCKS`).
    """
    t_h, t0 = service._project_times().get(project_id, (0.0, 0.0))
    model = service._ur_model_for(project_id)
    return {
        n.id: model.blocks(t_h, n.kpis, milestones=service.registry.list_milestones(n.id), t0_ts=t0)
        for n in actifs
    }


def _pearson(xs, ys):
    """Coefficient de Pearson des deux séries, 0.0 si indéfini.

    CHOIX DOCUMENTÉ : ρ indéfini (moins de 2 paires complètes ou variance
    nulle) est ramené à 0.0 — neutre : la heatmap reste lisible et aucun
    avertissement n'est déclenché sans information.
    """
    if len(xs) < 2:
        return 0.0
    ax = np.asarray(xs, dtype=float)
    ay = np.asarray(ys, dtype=float)
    if float(np.std(ax)) == 0.0 or float(np.std(ay)) == 0.0:
        return 0.0
    return float(np.corrcoef(ax, ay)[0, 1])


def _matrice_correlation(blocs_par_noeud):
    """Matrice de corrélation de Pearson des blocs d'urgence sur les nœuds actifs.

    Règles (Lot 12.4b) : corrélation par PAIRES COMPLÈTES seulement — un nœud
    dont l'un des deux blocs vaut None est exclu de la paire ; les blocs
    entièrement None sont exclus de la matrice.

    Args:
        blocs_par_noeud: ``{node_id: {bloc: urgence ou None}}``.

    Returns:
        ``(matrice, blocs_retenus)`` — matrice carrée symétrique (diagonale
        à 1.0), blocs dans l'ordre de :data:`BLOCKS` ; ``([], [])`` si aucun
        bloc n'est calculable.
    """
    colonnes = {
        bloc: [valeurs.get(bloc) for valeurs in blocs_par_noeud.values()] for bloc in BLOCKS
    }
    retenus = [bloc for bloc in BLOCKS if any(v is not None for v in colonnes[bloc])]
    matrice = [[1.0] * len(retenus) for _ in range(len(retenus))]
    for i, bloc_i in enumerate(retenus):
        for j in range(i + 1, len(retenus)):
            paires = [
                (vx, vy)
                for vx, vy in zip(colonnes[bloc_i], colonnes[retenus[j]], strict=True)
                if vx is not None and vy is not None
            ]
            rho = _pearson([vx for vx, _ in paires], [vy for _, vy in paires])
            matrice[i][j] = matrice[j][i] = rho
    return matrice, retenus


def _avertissements_correlation(matrice, blocs, omega):
    """Messages d'avertissement : |ρ| > 0.8 entre deux blocs de poids fort.

    « Poids fort » : les 3 poids effectifs les plus élevés parmi les SIX
    blocs (égalités départagées par l'ordre de :data:`BLOCKS`) — une forte
    corrélation entre blocs marginaux ne fausse guère le classement, elle
    n'est pas signalée.

    Args:
        matrice: matrice de corrélation (ordre de ``blocs``).
        blocs: noms des blocs retenus dans la matrice.
        omega: poids effectifs par bloc (omega du UrModel du projet).

    Returns:
        Liste de messages français, une entrée par paire incriminée
        (« ρ=x.xx » reste en notation POINT : format technique contractuel,
        cf. tests PROMETHEE existants).
    """
    if not matrice:
        return []
    tri = sorted(BLOCKS, key=lambda b: (-omega.get(b, 1.0), BLOCKS.index(b)))
    top3 = set(tri[:3])
    messages = []
    for i, bloc_i in enumerate(blocs):
        for j in range(i + 1, len(blocs)):
            bloc_j = blocs[j]
            rho = matrice[i][j]
            if abs(rho) > _SEUIL_CORRELATION and bloc_i in top3 and bloc_j in top3:
                messages.append(
                    f"Attention : les critères {BLOCK_LABELS_FR.get(bloc_i, bloc_i)} et "
                    f"{BLOCK_LABELS_FR.get(bloc_j, bloc_j)} sont fortement corrélés "
                    f"(ρ={rho:.2f}) — PROMETHEE double-compte l'information corrélée ; "
                    "envisagez de réduire un des deux poids."
                )
    return messages


def promethee_callback(project_data, n_clicks=None):
    """Carte « Priorités PROMETHEE II » : bandeau, barres φ et heatmap ρ.

    CHOIX DOCUMENTÉ : callback DÉDIÉ plutôt qu'une extension de
    :func:`update_dashboard_callback` — les quatre sorties existantes restent
    inchangées (compatibilité des tests et consommateurs actuels) et le coût
    O(n²) du classement n'est payé que pour cette carte. Le bouton
    « Recalculer maintenant » reste un déclencheur pour rafraîchir la carte
    en même temps que le reste du dashboard.

    Sans projet actif ou avec moins de 2 nœuds actifs : figures vides avec
    message, aucun bandeau, aucune exception.
    """
    service = get_service()
    pid = (project_data or {}).get("project_id")
    if not pid:
        return (
            [],
            empty_figure("Sélectionnez un projet pour afficher le classement PROMETHEE II."),
            empty_figure("Sélectionnez un projet pour afficher la corrélation des critères."),
        )
    actifs = _noeuds_actifs(service, pid)
    if len(actifs) < 2:
        return (
            [],
            empty_figure("Au moins 2 nœuds actifs sont requis pour le classement PROMETHEE II."),
            empty_figure("Au moins 2 nœuds actifs sont requis pour la corrélation des critères."),
        )
    resultat = service.classement_promethee(pid)
    figure_phi = promethee_bars_figure(resultat, {n.id: n.name for n in actifs})
    matrice, retenus = _matrice_correlation(_blocs_par_noeud(service, pid, actifs))
    figure_rho = correlation_heatmap_figure(matrice, [BLOCK_LABELS_FR.get(b, b) for b in retenus])
    omega = service._ur_model_for(pid).omega
    bandeaux = [
        html.Div(message, style=_WARN_BANNER_STYLE)
        for message in _avertissements_correlation(matrice, retenus, omega)
    ]
    return bandeaux, figure_phi, figure_rho


def history_figure_callback(node_id):
    """Figure d'évolution temporelle Ud/Ur/A du nœud sélectionné."""
    if not node_id:
        return empty_figure("Sélectionnez un nœud pour afficher son historique.")
    service = get_service()
    node = service.repo.get_node(node_id)
    name = node.name if node is not None else node_id
    series = service.client_db(node_id).urgency_series(node_id)
    return urgency_history_figure(series, name)


def register_callbacks(app) -> None:
    """Enregistre les callbacks de la page Dashboard sur l'application Dash."""
    app.callback(
        Output("dash-tags-dd", "options"),
        Output("dash-tags-dd", "value"),
        Input("store-project", "data"),
    )(tag_filter_options_callback)

    app.callback(
        Output("dash-palette-dd", "value"),
        Input("store-project", "data"),
    )(palette_value_callback)

    app.callback(
        Output("dash-empty-banner", "children"),
        Input("store-project", "data"),
    )(empty_state_callback)

    app.callback(
        Output("dash-kpi-cards", "children"),
        Output("dash-dag", "figure"),
        Output("dash-table", "data"),
        Output("dash-history-dd", "options"),
        Input("store-project", "data"),
        Input("dash-recalc-btn", "n_clicks"),
        Input("dash-tags-dd", "value"),
        Input("dash-palette-dd", "value"),
    )(update_dashboard_callback)

    app.callback(
        Output("dash-promethee-warning", "children"),
        Output("dash-promethee-fig", "figure"),
        Output("dash-correlation-fig", "figure"),
        Input("store-project", "data"),
        Input("dash-recalc-btn", "n_clicks"),
    )(promethee_callback)

    app.callback(
        Output("dash-history-fig", "figure"),
        Input("dash-history-dd", "value"),
    )(history_figure_callback)
