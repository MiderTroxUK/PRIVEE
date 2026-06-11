"""Tests de performance du rendu web (E14.3, faiblesse #13).

Couvre : suppression des annotations Plotly par arc (direction portée par une
trace de marqueurs dédiée), bascule WebGL au-delà de SEUIL_WEBGL (Scattergl,
étiquettes désactivées), mémoïsation des positions, pagination des DataTables
et budget de construction de la figure du dashboard à 1 000 nœuds.
"""

from __future__ import annotations

import time
from dataclasses import replace

import pytest

from supplyscore.domain.models import SupplyArc, SupplyNode, UrgencyState
from supplyscore.services import SupplyScoreService
from supplyscore.web_ui import set_service
from supplyscore.web_ui.components import figures
from supplyscore.web_ui.components.figures import (
    SEUIL_WEBGL,
    dag_figure,
    dashboard_dag_figure,
    node_positions,
)
from supplyscore.web_ui.pages import dashboard, projects


def make_graph(n_nodes: int, largeur: int = 25) -> tuple[list[SupplyNode], list[SupplyArc]]:
    """DAG synthétique en couches : ``largeur`` nœuds par rang.

    Chaque nœud (hors rang 0) alimente un client du rang précédent — un graphe
    connexe de ``n_nodes - largeur`` arcs nominaux, sans passer par le service.
    """
    nodes = [
        SupplyNode(
            id=f"n{i:04d}",
            name=f"Nœud {i}",
            rank=i // largeur,
            urgency=UrgencyState(ud_local=0.4, ur_local=0.5),
        )
        for i in range(n_nodes)
    ]
    arcs = [
        SupplyArc(source_id=nodes[i].id, target_id=nodes[i - largeur].id, gamma=0.5, beta=0.5)
        for i in range(largeur, n_nodes)
    ]
    return nodes, arcs


def _find_component(component, component_id):
    """Recherche récursive d'un composant Dash par id dans un layout."""
    if getattr(component, "id", None) == component_id:
        return component
    children = getattr(component, "children", None)
    if children is None:
        return None
    if not isinstance(children, (list, tuple)):
        children = [children]
    for child in children:
        found = _find_component(child, component_id)
        if found is not None:
            return found
    return None


@pytest.fixture
def service(tmp_path):
    """Service vide (aucun seed : seuls les layouts sont inspectés ici)."""
    svc = SupplyScoreService(db_dir=tmp_path / "store")
    set_service(svc)
    yield svc
    set_service(None)


# --- 1. Plus aucune annotation de flèche par arc -----------------------------------


def test_dag_50_noeuds_annotations_independantes_du_nombre_d_arcs():
    nodes, arcs = make_graph(50)
    fig_plein = dashboard_dag_figure(nodes, arcs)
    fig_sans_arcs = dashboard_dag_figure(nodes, [])

    # Seule l'annotation de légende (caption) subsiste — aucune flèche O(E).
    assert len(fig_plein.layout.annotations) == len(fig_sans_arcs.layout.annotations) == 1
    assert all(not a.showarrow for a in fig_plein.layout.annotations)


# --- 2. Marqueurs de direction (trace dédiée) ---------------------------------------


def test_marqueurs_de_direction_trace_dediee_orientee():
    nodes, arcs = make_graph(50)
    fig = dag_figure(nodes, arcs)

    sens = [t for t in fig.data if t.name == "sens-arcs"]
    assert len(sens) == 1
    # Une paire (point d'orientation invisible, flèche au ⅔) par arc nominal.
    assert len(sens[0].x) == 2 * len(arcs)
    assert sens[0].marker.symbol == "arrow"
    assert sens[0].marker.angleref == "previous"
    assert list(sens[0].marker.size)[::2] == [0.0] * len(arcs)  # points d'orientation


# --- 3. Seuil WebGL ------------------------------------------------------------------


def test_dag_50_noeuds_scatter_svg_avec_etiquettes():
    nodes, arcs = make_graph(50)
    fig = dag_figure(nodes, arcs)

    assert all(t.type == "scatter" for t in fig.data)
    noeuds = [t for t in fig.data if "text" in (t.mode or "")]
    assert len(noeuds) == 1  # la trace des nœuds porte les étiquettes
    assert len(noeuds[0].x) == 50
    assert noeuds[0].text[0] == "Nœud 0"


def test_dag_250_noeuds_bascule_scattergl_sans_etiquettes():
    nodes, arcs = make_graph(250)
    assert len(nodes) > SEUIL_WEBGL
    fig = dag_figure(nodes, arcs)

    assert all(t.type == "scattergl" for t in fig.data)
    assert all("text" not in (t.mode or "") for t in fig.data)
    # Repli documenté : Scattergl sans angleref — marqueur rond + survol du sens.
    sens = next(t for t in fig.data if t.name == "sens-arcs")
    assert sens.marker.symbol == "circle"
    assert sens.hovertext == "Sens : fournisseur → client"
    # La légende mentionne le mode allégé.
    mention = f"affichage allégé (>{SEUIL_WEBGL} nœuds)"
    assert any(mention in (a.text or "") for a in fig.layout.annotations)


# --- 4. Positions mémoïsées ----------------------------------------------------------


def test_node_positions_memoisees_meme_objet_et_hit_du_cache():
    nodes, _ = make_graph(50)
    figures._positions_par_cle.cache_clear()

    p1 = node_positions(nodes)
    apres_premier = figures._positions_par_cle.cache_info()
    p2 = node_positions(list(reversed(nodes)))  # même graphe, ordre d'appel différent

    assert p2 is p1  # même objet : hit du cache
    assert figures._positions_par_cle.cache_info().hits == apres_premier.hits + 1
    # Clé différente (rang changé) ⇒ invalidation naturelle : nouvel objet.
    autres = [replace(n, rank=n.rank + 1) for n in nodes]
    assert node_positions(autres) is not p1


# --- 5. DataTables paginées ----------------------------------------------------------


def test_dash_table_paginee_et_filtrable(service):
    table = _find_component(dashboard.layout(), "dash-table")
    assert table is not None
    assert table.page_size == 25
    assert table.page_action == "native"
    assert table.filter_action == "native"
    assert getattr(table, "virtualization", None) is False


def test_proj_table_paginee_tri_seul(service):
    table = _find_component(projects.layout(), "proj-table")
    assert table is not None
    assert table.page_size == 25
    assert table.page_action == "native"
    assert table.sort_action == "native"
    # La page Projets garde le tri natif SANS filtre (choix E14.3).
    assert getattr(table, "filter_action", None) in (None, "none")
    assert getattr(table, "virtualization", None) is False


# --- 6. Budget : figure dashboard à 1 000 nœuds --------------------------------------


def test_dashboard_dag_1000_noeuds_construit_sous_1s5():
    nodes, arcs = make_graph(1000, largeur=40)

    # Étalonnage : une petite figure sert de chronomètre témoin — au-delà de
    # 0.5 s pour 50 nœuds, la machine est jugée trop lente pour un budget fiable.
    debut = time.perf_counter()
    dag_figure(nodes[:50], [])
    if time.perf_counter() - debut > 0.5:
        pytest.skip("machine très lente : étalonnage 50 nœuds > 0.5 s")

    debut = time.perf_counter()
    fig = dashboard_dag_figure(nodes, arcs)
    duree = time.perf_counter() - debut

    assert len(fig.data) >= 2  # arêtes + nœuds (+ marqueurs de direction)
    assert duree < 1.5, f"construction trop lente : {duree:.2f} s (budget 1.5 s)"
