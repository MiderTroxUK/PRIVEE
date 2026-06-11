"""Carte « Priorités PROMETHEE II » du dashboard (Lot 12.4b) — aucun serveur lancé.

Pattern de ``test_webui_dashboard_hebdo.py`` : service seedé sur ``tmp_path``
+ ``set_service``, callbacks appelés directement. Couvre :

- :func:`promethee_bars_figure` : tri φ décroissant, top N, couleurs
  rouge/gris, info-bulle « φ+ = … ; φ− = … », figure vide si < 2 nœuds ;
- :func:`correlation_heatmap_figure` : heatmap RdBu [−1, 1] annotée, figure
  vide si matrice vide ;
- ``promethee_callback`` sur un projet seedé : Σφ == 0 sur les barres
  rendues, heatmap des 6 blocs, diagonale à 1 ;
- le bandeau d'avertissement de corrélation — les blocs sont injectés via
  monkeypatch de ``dashboard._blocs_par_noeud`` (CHOIX DOCUMENTÉ : plus
  simple et plus lisible que de construire des KPIs réels parfaitement
  corrélés ; le reste de la chaîne — matrice, top 3 des poids, bandeau —
  est exécuté à l'identique) ;
- sans projet ou avec moins de 2 nœuds actifs : figures vides, aucune
  exception.
"""

import pytest

from supplyscore.domain.models import Project, SupplyNode, TaskStatus
from supplyscore.mcda.promethee import ResultatPromethee
from supplyscore.services import SupplyScoreService
from supplyscore.web_ui import set_service
from supplyscore.web_ui.components.figures import (
    correlation_heatmap_figure,
    promethee_bars_figure,
)
from supplyscore.web_ui.pages import dashboard


@pytest.fixture
def seeded(tmp_path):
    """Couple (service seedé, projet de démo), service partagé par les callbacks."""
    svc = SupplyScoreService(db_dir=tmp_path / "store")
    project = svc.seed_demo(n_ranks=2, seed=1)
    set_service(svc)
    yield svc, project
    set_service(None)


def _project_data(project):
    """Contenu du ``dcc.Store`` « store-project » tel que posé par la page Projets."""
    return {"project_id": project.id, "name": project.name}


def _resultat(phis):
    """ResultatPromethee construit depuis les flux nets (φ+ = max(φ, 0), φ− = max(−φ, 0))."""
    return ResultatPromethee(
        phi=dict(phis),
        phi_plus={alt: max(v, 0.0) for alt, v in phis.items()},
        phi_moins={alt: max(-v, 0.0) for alt, v in phis.items()},
        classement=sorted(phis, key=lambda alt: (-phis[alt], alt)),
    )


def _actifs(service, project_id):
    """Nœuds actifs du projet (mêmes règles que classement_promethee)."""
    return [
        n
        for n in service.repo.nodes_by_project(project_id)
        if n.status == TaskStatus.ACTIVE and n.onboarding_state != "draft"
    ]


# --- promethee_bars_figure ------------------------------------------------------------


def test_promethee_bars_tri_couleurs_et_hover():
    resultat = _resultat({"a": -0.3, "b": 0.4, "c": 0.0})
    fig = promethee_bars_figure(resultat, {"a": "Alpha", "b": "Bravo", "c": "Charlie"})
    barre = fig.data[0]
    assert barre.type == "bar" and barre.orientation == "h"
    # Tri par φ décroissant, labels = noms des nœuds, prioritaire en haut.
    assert list(barre.y) == ["Bravo", "Charlie", "Alpha"]
    assert list(barre.x) == [0.4, 0.0, -0.3]
    assert fig.layout.yaxis.autorange == "reversed"
    # Rouge pour φ > 0 (prioritaire), gris sinon.
    assert list(barre.marker.color) == ["#b3261e", "#9aa7b0", "#9aa7b0"]
    # Info-bulle « φ+ = … ; φ− = … ».
    assert "φ+ = 0.400 ; φ− = 0.000" in barre.hovertext[0]
    assert "φ+ = 0.000 ; φ− = 0.300" in barre.hovertext[2]
    assert "Priorités PROMETHEE II — nœuds à traiter en premier" in fig.layout.title.text


def test_promethee_bars_top_limite_le_nombre_de_barres():
    phis = {f"n{i:02d}": 0.5 - 0.05 * i for i in range(12)}
    fig = promethee_bars_figure(_resultat(phis), {})
    assert len(fig.data[0].x) == 10  # top 10 par défaut
    fig_top3 = promethee_bars_figure(_resultat(phis), {}, top=3)
    # Labels = id du nœud à défaut de nom, les 3 meilleurs φ seulement.
    assert list(fig_top3.data[0].y) == ["n00", "n01", "n02"]


def test_promethee_bars_moins_de_deux_noeuds():
    fig = promethee_bars_figure(_resultat({"seul": 0.0}), {"seul": "Seul"})
    assert not fig.data
    assert "au moins 2 nœuds actifs" in fig.layout.annotations[0].text


# --- correlation_heatmap_figure -------------------------------------------------------


def test_correlation_heatmap_annotee():
    matrice = [[1.0, 0.9], [0.9, 1.0]]
    fig = correlation_heatmap_figure(matrice, ["Temps", "Capacité"])
    heatmap = fig.data[0]
    assert heatmap.type == "heatmap"
    assert heatmap.zmin == -1.0 and heatmap.zmax == 1.0
    assert list(heatmap.x) == ["Temps", "Capacité"]
    assert heatmap.text[0][1] == "0.90"  # valeurs annotées dans les cases
    assert heatmap.texttemplate == "%{text}"


def test_correlation_heatmap_matrice_vide():
    fig = correlation_heatmap_figure([], [])
    assert not fig.data
    assert "aucun bloc" in fig.layout.annotations[0].text


# --- matrice de corrélation : paires complètes, blocs exclus ----------------------------


def test_matrice_correlation_paires_completes_et_blocs_exclus():
    blocs = {
        "n1": {"time": 0.1, "cap": 0.9, "perf": None, "risk": None, "cost": None, "co2": 0.5},
        "n2": {"time": 0.2, "cap": 0.8, "perf": 0.1, "risk": None, "cost": None, "co2": 0.5},
        "n3": {"time": 0.3, "cap": 0.7, "perf": 0.2, "risk": None, "cost": None, "co2": None},
        "n4": {"time": 0.4, "cap": None, "perf": 0.4, "risk": None, "cost": None, "co2": 0.5},
    }
    matrice, retenus = dashboard._matrice_correlation(blocs)
    # risk et cost entièrement None : exclus ; ordre = ordre de BLOCKS.
    assert retenus == ["time", "cap", "perf", "co2"]
    # time vs cap : paires complètes n1..n3 (n4 exclu) → anticorrélation parfaite.
    i_time, i_cap, i_co2 = 0, 1, 3
    assert matrice[i_time][i_cap] == pytest.approx(-1.0)
    assert matrice[i_cap][i_time] == pytest.approx(-1.0)  # symétrie
    assert all(matrice[k][k] == 1.0 for k in range(len(retenus)))  # diagonale
    # co2 constant sur ses paires : ρ indéfini ramené à 0 (choix documenté).
    assert matrice[i_time][i_co2] == 0.0


def test_matrice_correlation_aucun_bloc_calculable():
    blocs = {"n1": dict.fromkeys(["time", "cap", "perf", "risk", "cost", "co2"])}
    matrice, retenus = dashboard._matrice_correlation(blocs)
    assert matrice == [] and retenus == []


def test_avertissement_ignore_les_blocs_hors_top_3():
    # time et co2 fortement corrélés MAIS co2 n'est pas parmi les 3 poids forts.
    matrice = [[1.0, 0.95], [0.95, 1.0]]
    omega = {"time": 3.0, "cap": 2.0, "perf": 2.0, "risk": 1.0, "cost": 1.0, "co2": 0.1}
    assert dashboard._avertissements_correlation(matrice, ["time", "co2"], omega) == []


# --- callback dédié : projet seedé ------------------------------------------------------


def test_callback_projet_seede_phi_somme_nulle_et_heatmap(seeded):
    service, project = seeded
    bandeaux, fig_phi, fig_rho = dashboard.promethee_callback(_project_data(project), None)
    assert isinstance(bandeaux, list)

    barre = fig_phi.data[0]
    actifs = _actifs(service, project.id)
    assert 2 <= len(actifs) <= 10  # tous rendus par le top 10 par défaut
    assert len(barre.x) == len(actifs)
    assert sum(barre.x) == pytest.approx(0.0, abs=1e-9)  # Σφ == 0 (PROMETHEE II)
    noms = {n.name for n in actifs}
    assert set(barre.y) == noms  # labels = noms des nœuds

    heatmap = fig_rho.data[0]
    assert heatmap.type == "heatmap"
    assert len(heatmap.x) == 6  # les 6 blocs sont calculables dans la démo
    assert "Temps" in heatmap.x and "Capacité" in heatmap.x
    assert all(heatmap.z[i][i] == pytest.approx(1.0) for i in range(6))


def test_callback_avertissement_correlation_forte(seeded, monkeypatch):
    service, project = seeded
    # Poids effectifs : top 3 = time (3.0), cap (2.5), perf (2.0).
    service.set_poids_criteres(
        project.id,
        {"time": 3.0, "cap": 2.5, "perf": 2.0, "risk": 0.5, "cost": 0.5, "co2": 0.5},
    )

    def blocs_correles(service_, project_id, actifs):
        # time == cap (ρ = 1, tous deux dans le top 3) ; perf constant
        # (ρ indéfini → 0) ; cost entièrement None (bloc exclu) ; risk présent
        # sur un seul nœud (< 2 paires complètes → ρ = 0).
        return {
            n.id: {
                "time": 0.1 * i,
                "cap": 0.1 * i,
                "perf": 0.3,
                "risk": 0.5 if i == 0 else None,
                "cost": None,
                "co2": 0.9 - 0.07 * i if i % 2 else 0.2,
            }
            for i, n in enumerate(actifs)
        }

    monkeypatch.setattr(dashboard, "_blocs_par_noeud", blocs_correles)
    bandeaux, _, fig_rho = dashboard.promethee_callback(_project_data(project), None)

    assert len(bandeaux) == 1  # une seule paire incriminée : time / cap
    texte = str(bandeaux[0])
    assert "fortement corrélés" in texte
    assert "ρ=1.00" in texte
    assert "Temps" in texte and "Capacité" in texte
    assert "réduire un des deux poids" in texte
    assert "#b06000" in texte  # bandeau orange (COLORS["warn"])
    # cost entièrement None : exclu de la heatmap (5 blocs restants).
    assert len(fig_rho.data[0].x) == 5


# --- callback dédié : cas dégradés ------------------------------------------------------


def test_callback_sans_projet_figures_vides_sans_exception(seeded):
    bandeaux, fig_phi, fig_rho = dashboard.promethee_callback(None, None)
    assert bandeaux == []
    assert not fig_phi.data and not fig_rho.data
    assert "Sélectionnez un projet" in fig_phi.layout.annotations[0].text
    assert "Sélectionnez un projet" in fig_rho.layout.annotations[0].text


def test_callback_moins_de_deux_actifs_figures_vides(seeded):
    service, _ = seeded
    solo = Project(id="p-solo", name="Solo", owner_node_id="n-1", created_at=0.0, t0_ts=0.0)
    service.create_project(solo, [SupplyNode(id="n-1", name="N1", project_id="p-solo")], [])
    bandeaux, fig_phi, fig_rho = dashboard.promethee_callback(_project_data(solo), None)
    assert bandeaux == []
    assert not fig_phi.data and not fig_rho.data
    assert "2 nœuds actifs" in fig_phi.layout.annotations[0].text


# --- layout : la carte et sa note de bas de carte ---------------------------------------


def test_layout_contient_la_carte_promethee(seeded):
    tree = str(dashboard.layout())
    assert "dash-promethee-warning" in tree
    assert "dash-promethee-fig" in tree
    assert "dash-correlation-fig" in tree
    assert "Priorités PROMETHEE II" in tree
    assert "RELATIF au périmètre du projet" in tree  # note de renversement de rang
