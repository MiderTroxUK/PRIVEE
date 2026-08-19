"""Cablage hebdo du dashboard (lot 4.3a) - aucun serveur lance.

Le callback du tableau detaille est appele directement (pattern de
``test_webui.py`` : service seede sur ``tmp_path`` + ``set_service``).
Couvre : colonne " Hebdo " (libelles A jour / Manquant), masquage A/F/H en
" - " pour un noeud MANQUANT, carte KPI " Questionnaires a jour : x/y " et
``style_data_conditional`` (regles hebdo EN PLUS des regles existantes).
"""

import pytest

from supplyscore.domain.models import TaskStatus
from supplyscore.services import SupplyScoreService
from supplyscore.web_ui import set_service
from supplyscore.web_ui.components.badges import style_hebdo_conditionnel
from supplyscore.web_ui.pages import dashboard


@pytest.fixture
def seeded(tmp_path):
    """Couple (service seede, projet de demo), service partage par les callbacks."""
    svc = SupplyScoreService(db_dir=tmp_path / "store")
    project = svc.seed_demo(n_ranks=2, seed=1)
    set_service(svc)
    yield svc, project
    set_service(None)


def _project_data(project):
    """Contenu du ``dcc.Store`` " store-project " tel que pose par la page Projets."""
    return {"project_id": project.id, "name": project.name}


def _delete_assessments(service, node_id):
    """Supprime en base client toutes les evaluations AHP du noeud."""
    db = service.client_db(node_id)
    with db.lock:
        db.conn.execute("DELETE FROM assessments WHERE node_id = ?", (node_id,))
        db.conn.commit()


def _row_of(rows, name):
    """Ligne du tableau detaille portant le nom donne (doit etre unique)."""
    matches = [r for r in rows if r["Nom"] == name]
    assert len(matches) == 1, f"ligne introuvable ou ambiguë pour {name!r}"
    return matches[0]


# Colonne Hebdo : libelles et masquage A/F/H


def test_colonne_hebdo_a_jour_et_manquant(seeded):
    service, project = seeded
    nodes = service.repo.nodes()
    assert nodes

    # seed_demo evalue chaque noeud a l'instant du seed : tous " A jour ".
    _, _, rows, _ = dashboard.update_dashboard_callback(_project_data(project), None)
    assert len(rows) == len(nodes)
    assert all(r["Hebdo"] == "À jour" for r in rows)

    # Sans evaluation en base, le noeud passe " Manquant "...
    manquant = nodes[0]
    _delete_assessments(service, manquant.id)
    _, _, rows, _ = dashboard.update_dashboard_callback(_project_data(project), None)
    row = _row_of(rows, manquant.name)
    assert row["Hebdo"] == "Manquant"
    # ... et son A (comme F et H) est masque : l'adequation calculee contre un Ud inexistant est trompeuse (H artificiellement alarmant).
    assert row["A"] == "—"
    assert row["F"] == "—"
    assert row["H"] == "—"

    # Les autres noeuds restent " A jour ", valeurs numeriques intactes.
    autres = [r for r in rows if r["Nom"] != manquant.name]
    assert autres and all(r["Hebdo"] == "À jour" for r in autres)
    assert all(isinstance(r["A"], float) for r in autres)


# Carte KPI " Questionnaires a jour : x/y "


def test_carte_couverture_coherente(seeded):
    service, project = seeded
    actifs = [n for n in service.repo.nodes() if n.status is TaskStatus.ACTIVE]
    total = len(actifs)
    assert total > 0

    # Tous evalues au seed : x == y, badge vert.
    cards, _, _, _ = dashboard.update_dashboard_callback(_project_data(project), None)
    carte = str(cards[0])
    assert "Questionnaires à jour" in carte
    assert f"{total}/{total}" in carte
    assert "#1d7a3e" in carte  # COLORS["ok"]

    # Un noeud actif sans evaluation : x == y - 1, badge orange.
    _delete_assessments(service, actifs[0].id)
    cards, _, _, _ = dashboard.update_dashboard_callback(_project_data(project), None)
    carte = str(cards[0])
    assert f"{total - 1}/{total}" in carte
    assert "#b06000" in carte  # COLORS["warn"]


# style_data_conditional : regles hebdo EN PLUS des regles existantes


def test_style_conditionnel_hebdo_et_regles_existantes(seeded):
    cond = dashboard._TABLE_CONDITIONAL

    # Regles existantes conservees : A < 40 fond rouge, H > 0.3 texte rouge.
    assert {"if": {"filter_query": "{A} < 40"}, "backgroundColor": "#fdecea"} in cond
    assert any(
        r.get("if") == {"filter_query": "{H} > 0.3", "column_id": "H"}
        and r.get("color") == "#b3261e"
        for r in cond
    )

    # Les trois regles hebdo (A jour / En retard / Manquant) sont presentes.
    for regle in style_hebdo_conditionnel("Hebdo"):
        assert regle in cond

    # La colonne Hebdo est bien declaree, et le layout cable ces regles.
    assert {"name": "Hebdo", "id": "Hebdo"} in dashboard._TABLE_COLUMNS
    tree = str(dashboard.layout())
    assert "Hebdo" in tree
    assert "Manquant" in tree  # filter_query hebdo embarquee dans la DataTable


# Aucun projet selectionne : comportements actuels conserves


def test_sans_projet_pas_de_plantage_valeurs_vides(seeded):
    service, _ = seeded
    cards, _, rows, _ = dashboard.update_dashboard_callback(None, None)

    # Tout le graphe est liste, la colonne Hebdo reste neutre (" - ").
    assert len(rows) == len(service.repo.nodes())
    assert all(r["Hebdo"] == "—" for r in rows)
    # A/F/H gardent leurs valeurs numeriques (comportement actuel conserve).
    assert all(isinstance(r["A"], float) for r in rows)

    # La carte couverture affiche " - " sans plantage.
    carte = str(cards[0])
    assert "Questionnaires à jour" in carte
    assert "—" in carte
