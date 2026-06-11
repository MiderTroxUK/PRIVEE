"""Tests du Lot 10.4 : page « /graphe » — éditeur de graphe, sans serveur.

Couvre : le tableau des arcs (lignes à id « src->dst », valeurs numériques),
l'édition de cellule (γ modifié → registre + audit + ``no_update`` table ;
γ hors bornes → rejet, table rechargée, AUCUN audit ; nature nominal→backup →
rangs recalés ; backup→nominal cyclique → refus AVANT écriture), l'ajout
d'arc (valide → base + repo ; cycle → message français, arc ABSENT de la base
ET du repo ; self-loop et doublon refusés), la suppression confirmée
(``service.remove_arc`` espionné), la taxonomie (catégorie + tag + affectation
→ ``tags_of_node``) et les statuts (``service.set_status``). Callbacks appelés
directement (fonctions module), service à FixedClock posé via ``set_service``
et libéré en teardown, graphe déterministe A ← B ← C (+ D isolé).
"""

from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path

import dash
import pytest
from dash import no_update
from dash.exceptions import PreventUpdate

from supplyscore.core.clock import FixedClock
from supplyscore.data.audit import AuditTrail
from supplyscore.domain.models import ArcKind, Project, SupplyArc, SupplyNode, TaskStatus
from supplyscore.services import SupplyScoreService
from supplyscore.web_ui import set_service
from supplyscore.web_ui.pages import graph_editor

#: Mercredi 2026-06-10 12:00 locale — semaine ISO « 2026-S24 ».
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()

_OPERATOR = {"name": "testeuse"}
_PROJECT = {"project_id": "p1", "name": "Chaîne"}


@pytest.fixture
def service(tmp_path: Path):
    """Service à horloge figée, partagé par les callbacks de la page."""
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(_NOW))
    set_service(svc)
    yield svc
    set_service(None)
    svc.close()


@pytest.fixture
def chain(service: SupplyScoreService) -> Project:
    """Chaîne déterministe C → B → A (+ D isolé), projet « p1 »."""
    project = Project(id="p1", name="Chaîne", owner_node_id="A", created_at=_NOW, t0_ts=_NOW)
    nodes = [
        SupplyNode(id="A", name="Client final", label="Client", rank=0, project_id="p1"),
        SupplyNode(id="B", name="Usine", label="Factory", rank=1, project_id="p1"),
        SupplyNode(id="C", name="Fournisseur", label="Supplier", rank=2, project_id="p1"),
        SupplyNode(id="D", name="Atelier", label="Workshop", rank=0, project_id="p1"),
    ]
    arcs = [
        SupplyArc(source_id="B", target_id="A", gamma=0.5, beta=0.5),
        SupplyArc(source_id="C", target_id="B", gamma=0.5, beta=0.5),
    ]
    service.create_project(project, nodes, arcs)
    return project


def _rows(service: SupplyScoreService) -> list[dict]:
    """Lignes fraîches du tableau des arcs du projet p1."""
    return graph_editor._arc_rows(service, "p1")


def _row(rows: list[dict], arc_id: str) -> dict:
    """La ligne du tableau portant l'id demandé."""
    matches = [r for r in rows if r["id"] == arc_id]
    assert len(matches) == 1, f"ligne {arc_id!r} introuvable dans {rows!r}"
    return matches[0]


def _audit_arc(service: SupplyScoreService, arc_id: str, field: str):
    """Historique d'audit du champ d'un arc dans le REGISTRE."""
    trail = AuditTrail(service.registry.conn, FixedClock(_NOW), lock=service.registry.lock)
    return trail.history("arc", arc_id, field=field, limit=20)


def _edit(service: SupplyScoreService, mutate, project=_PROJECT):
    """Joue une édition de cellule : copie data_previous, applique ``mutate``."""
    previous = _rows(service)
    data = copy.deepcopy(previous)
    mutate(data)
    return graph_editor.edit_arc_callback(123, data, previous, project, _OPERATOR, 0)


# --- Tableau des arcs --------------------------------------------------------------


class TestTableau:
    def test_lignes_avec_id_stable_et_valeurs_numeriques(self, service, chain) -> None:
        outputs = graph_editor.refresh_view_callback(_PROJECT, 0)

        rows = outputs[0]
        assert {row["id"] for row in rows} == {"B->A", "C->B"}
        ligne = _row(rows, "C->B")
        assert ligne["Fournisseur"] == "Fournisseur"
        assert ligne["Client"] == "Usine"
        assert isinstance(ligne["gamma"], float) and ligne["gamma"] == 0.5
        assert isinstance(ligne["beta"], float) and ligne["beta"] == 0.5
        assert isinstance(ligne["delta"], float)
        assert ligne["Nature"] == "nominal"

    def test_options_de_suppression_au_format_fournisseur_vers_client(self, service, chain) -> None:
        outputs = graph_editor.refresh_view_callback(_PROJECT, 0)

        del_options = outputs[3]
        assert {o["value"] for o in del_options} == {"B->A", "C->B"}
        labels = {o["value"]: o["label"] for o in del_options}
        assert labels["C->B"] == "Fournisseur → Usine"

    def test_sans_projet_tout_le_graphe_et_tags_vides(self, service, chain) -> None:
        outputs = graph_editor.refresh_view_callback(None, 0)

        # outputs[9] = bandeau info (outputs[8] = options du dropdown de suppression de nœud)
        rows, cat_options, tag_options, info = outputs[0], outputs[4], outputs[6], outputs[9]
        assert {row["id"] for row in rows} == {"B->A", "C->B"}
        assert cat_options == [] and tag_options == []
        assert "Aucun projet sélectionné" in str(info)


# --- Édition de cellule ------------------------------------------------------------


class TestEditionArc:
    def test_edition_gamma_modifie_l_arc_audite_et_no_update_table(self, service, chain) -> None:
        table, message, refresh = _edit(service, lambda data: _row(data, "C->B").update(gamma=0.8))

        assert table is no_update
        assert "modifié" in str(message)
        assert refresh == 1
        arc = service.registry.get_arc("C", "B")
        assert arc is not None and arc.gamma == 0.8
        assert service.repo.get_arc("C", "B").gamma == 0.8
        entries = _audit_arc(service, "C->B", "gamma")
        assert len(entries) == 1
        assert entries[0].old_value == 0.5 and entries[0].new_value == 0.8
        assert entries[0].source == "edit" and entries[0].operator_id == "testeuse"

    def test_gamma_hors_bornes_rejet_table_rechargee_sans_audit(self, service, chain) -> None:
        table, message, refresh = _edit(service, lambda data: _row(data, "C->B").update(gamma=1.5))

        assert table is not no_update
        assert _row(table, "C->B")["gamma"] == 0.5  # rechargée depuis le registre
        assert "Modification refusée" in str(message)
        assert "gamma hors [0, 1]" in str(message)
        assert refresh is no_update
        assert service.registry.get_arc("C", "B").gamma == 0.5
        assert _audit_arc(service, "C->B", "gamma") == []

    def test_valeur_non_numerique_rejetee_en_francais(self, service, chain) -> None:
        table, message, _refresh = _edit(
            service, lambda data: _row(data, "C->B").update(gamma=None)
        )

        assert table is not no_update
        assert "doit être un nombre" in str(message)
        assert service.registry.get_arc("C", "B").gamma == 0.5

    def test_nature_inconnue_rejetee_en_francais(self, service, chain) -> None:
        table, message, _refresh = _edit(
            service, lambda data: _row(data, "C->B").update(Nature="exotique")
        )

        assert table is not no_update
        assert "nature d'arc inconnue" in str(message)
        assert service.registry.get_arc("C", "B").kind_arc is ArcKind.NOMINAL

    def test_data_previous_none_est_un_no_update_integral(self, service, chain) -> None:
        outputs = graph_editor.edit_arc_callback(123, _rows(service), None, _PROJECT, _OPERATOR, 0)
        assert all(out is no_update for out in outputs)

    def test_aucun_changement_est_un_no_update_integral(self, service, chain) -> None:
        outputs = _edit(service, lambda data: None)
        assert all(out is no_update for out in outputs)

    def test_nature_nominal_vers_backup_recale_les_rangs(self, service, chain) -> None:
        assert service.registry.get_node("C").rank == 2

        table, message, refresh = _edit(
            service, lambda data: _row(data, "C->B").update(Nature="backup")
        )

        assert table is no_update
        assert "rangs recalés" in str(message)
        assert refresh == 1
        arc = service.registry.get_arc("C", "B")
        assert arc is not None and arc.kind_arc is ArcKind.BACKUP
        assert service.repo.get_arc("C", "B").kind_arc is ArcKind.BACKUP
        # C, dont l'arc nominal sortant portait la profondeur, devient un puits.
        assert service.registry.get_node("C").rank == 0
        assert service.repo.get_node("C").rank == 0
        entries = _audit_arc(service, "C->B", "kind_arc")
        assert len(entries) == 1 and entries[0].source == "edit"

    def test_backup_vers_nominal_cyclique_refuse_avant_ecriture(self, service, chain) -> None:
        # Arc de secours A -> C : autorisé (inerte), mais il fermerait un
        # cycle A -> C -> B -> A s'il repassait en nominal.
        message, refresh = graph_editor.add_arc_callback(
            1, "A", "C", 0.4, 0.4, "backup", _OPERATOR, 0
        )
        assert "ajouté" in str(message) and refresh == 1

        table, message, refresh = _edit(
            service, lambda data: _row(data, "A->C").update(Nature="nominal")
        )

        assert table is not no_update
        assert "créerait un cycle" in str(message)
        assert refresh is no_update
        assert service.registry.get_arc("A", "C").kind_arc is ArcKind.BACKUP
        assert service.repo.get_arc("A", "C").kind_arc is ArcKind.BACKUP
        assert _audit_arc(service, "A->C", "kind_arc") == []


# --- Ajout d'arc -------------------------------------------------------------------


class TestAjoutArc:
    def test_ajout_valide_present_en_base_et_dans_le_repo(self, service, chain) -> None:
        message, refresh = graph_editor.add_arc_callback(
            1, "D", "A", 0.7, 0.6, "nominal", _OPERATOR, 0
        )

        assert "Atelier → Client final" in str(message)
        assert refresh == 1
        arc = service.registry.get_arc("D", "A")
        assert arc is not None and arc.gamma == 0.7 and arc.beta == 0.6
        assert service.repo.get_arc("D", "A") is not None
        # D alimente désormais A : son rang canonique passe à 1.
        assert service.registry.get_node("D").rank == 1
        entries = _audit_arc(service, "D->A", "")
        assert len(entries) == 1 and entries[0].new_value == "created"
        assert entries[0].source == "edit" and entries[0].operator_id == "testeuse"

    def test_ajout_cyclique_refuse_arc_absent_de_la_base_et_du_repo(self, service, chain) -> None:
        message, refresh = graph_editor.add_arc_callback(
            1, "A", "C", 0.5, 0.5, "nominal", _OPERATOR, 0
        )

        assert "créerait un cycle" in str(message)
        assert refresh is no_update
        assert service.registry.get_arc("A", "C") is None
        assert service.repo.get_arc("A", "C") is None
        assert _audit_arc(service, "A->C", "") == []

    def test_self_loop_refuse(self, service, chain) -> None:
        message, refresh = graph_editor.add_arc_callback(
            1, "B", "B", 0.5, 0.5, "nominal", _OPERATOR, 0
        )

        assert "boucle refusée" in str(message)
        assert refresh is no_update
        assert service.registry.get_arc("B", "B") is None

    def test_arc_deja_present_refuse(self, service, chain) -> None:
        message, refresh = graph_editor.add_arc_callback(
            1, "B", "A", 0.9, 0.9, "nominal", _OPERATOR, 0
        )

        assert "existe déjà" in str(message)
        assert refresh is no_update
        assert service.registry.get_arc("B", "A").gamma == 0.5  # inchangé

    def test_selection_incomplete_refusee(self, service, chain) -> None:
        message, refresh = graph_editor.add_arc_callback(
            1, None, "A", 0.5, 0.5, "nominal", _OPERATOR, 0
        )

        assert "Choisissez un fournisseur ET un client." in str(message)
        assert refresh is no_update

    def test_valeurs_par_defaut_des_sliders(self, service, chain) -> None:
        message, refresh = graph_editor.add_arc_callback(
            1, "D", "B", None, None, None, _OPERATOR, 3
        )

        assert refresh == 4
        arc = service.registry.get_arc("D", "B")
        assert arc is not None and arc.gamma == 0.5 and arc.beta == 0.5
        assert arc.kind_arc is ArcKind.NOMINAL
        assert "ajouté" in str(message)


# --- Suppression d'arc -------------------------------------------------------------


class TestSuppressionArc:
    def test_suppression_confirmee_retire_l_arc_via_le_service(
        self, service, chain, monkeypatch
    ) -> None:
        appels: list[tuple[str, str]] = []
        original = service.remove_arc
        monkeypatch.setattr(
            service,
            "remove_arc",
            lambda s, t: (appels.append((s, t)), original(s, t))[1],
        )

        message, refresh = graph_editor.delete_arc_callback(1, "C->B", 0)

        assert appels == [("C", "B")]
        assert "supprimé" in str(message)
        assert refresh == 1
        assert service.registry.get_arc("C", "B") is None
        assert service.repo.get_arc("C", "B") is None
        # Fournisseur devenu isolé : rang recalé à 0 par remove_arc.
        assert service.registry.get_node("C").rank == 0

    def test_suppression_sans_choix_refusee(self, service, chain) -> None:
        message, refresh = graph_editor.delete_arc_callback(1, None, 0)

        assert "Choisissez d'abord un arc" in str(message)
        assert refresh is no_update

    def test_suppression_arc_inconnu_message_francais(self, service, chain) -> None:
        message, refresh = graph_editor.delete_arc_callback(1, "X->Y", 0)

        assert "Arc inconnu" in str(message)
        assert refresh is no_update


# --- Tags & taxonomie --------------------------------------------------------------


class TestTags:
    def test_categorie_tag_et_affectation_via_tags_of_node(self, service, chain) -> None:
        message, refresh = graph_editor.create_category_callback(
            1, "  Procédé ", "#ff0000", _PROJECT, 0
        )
        assert "Procédé" in str(message) and refresh == 1
        categories = service.registry.list_tag_categories("p1")
        assert len(categories) == 1
        assert categories[0].name == "Procédé" and categories[0].color == "#ff0000"

        message, refresh = graph_editor.create_tag_callback(
            1, "Usinage", categories[0].id, _PROJECT, 0
        )
        assert "Usinage" in str(message) and refresh == 1
        tags = service.registry.list_tags("p1")
        assert len(tags) == 1 and tags[0].category_id == categories[0].id

        message, refresh = graph_editor.assign_tags_callback(1, "B", [tags[0].id], _OPERATOR, 0)
        assert "mis à jour" in str(message) and refresh == 1
        assert [t.name for t in service.registry.tags_of_node("B")] == ["Usinage"]
        # Affectation auditée au registre (entity node, champ tags, source edit).
        trail = AuditTrail(service.registry.conn, FixedClock(_NOW), lock=service.registry.lock)
        entries = trail.history("node", "B", field="tags", limit=5)
        assert len(entries) == 1
        assert entries[0].source == "edit" and entries[0].operator_id == "testeuse"

    def test_prefill_retourne_les_tags_courants_du_noeud(self, service, chain) -> None:
        graph_editor.create_tag_callback(1, "Sud", None, _PROJECT, 0)
        tag = service.registry.list_tags("p1")[0]
        graph_editor.assign_tags_callback(1, "C", [tag.id], _OPERATOR, 0)

        assert graph_editor.node_tags_callback("C") == [tag.id]
        assert graph_editor.node_tags_callback("B") == []
        assert graph_editor.node_tags_callback(None) == []

    def test_affectation_identique_est_un_noop(self, service, chain) -> None:
        graph_editor.create_tag_callback(1, "Nord", None, _PROJECT, 0)
        tag = service.registry.list_tags("p1")[0]
        graph_editor.assign_tags_callback(1, "B", [tag.id], _OPERATOR, 0)

        message, refresh = graph_editor.assign_tags_callback(1, "B", [tag.id], _OPERATOR, 5)

        assert "inchangés" in str(message)
        assert refresh is no_update

    def test_affectation_noeud_inconnu_message_francais(self, service, chain) -> None:
        message, refresh = graph_editor.assign_tags_callback(1, "Z", [], _OPERATOR, 0)

        assert "Nœud inconnu" in str(message)
        assert refresh is no_update

    def test_refus_sans_projet_ou_sans_nom(self, service, chain) -> None:
        message, refresh = graph_editor.create_category_callback(1, "Région", "#fff", None, 0)
        assert "projet actif" in str(message) and refresh is no_update

        message, refresh = graph_editor.create_category_callback(1, "  ", "#fff", _PROJECT, 0)
        assert "nom de la catégorie est requis" in str(message) and refresh is no_update

        message, refresh = graph_editor.create_tag_callback(1, None, None, _PROJECT, 0)
        assert "nom du tag est requis" in str(message) and refresh is no_update

        message, refresh = graph_editor.create_tag_callback(1, "Tag", None, None, 0)
        assert "projet actif" in str(message) and refresh is no_update

        message, refresh = graph_editor.assign_tags_callback(1, None, [], _OPERATOR, 0)
        assert "Choisissez d'abord un nœud." in str(message) and refresh is no_update

    def test_options_tags_portent_la_categorie(self, service, chain) -> None:
        graph_editor.create_category_callback(1, "Procédé", "#00ff00", _PROJECT, 0)
        cat = service.registry.list_tag_categories("p1")[0]
        graph_editor.create_tag_callback(1, "Fonderie", cat.id, _PROJECT, 0)
        graph_editor.create_tag_callback(1, "Libre", None, _PROJECT, 0)

        options = graph_editor._tag_options(service, "p1")

        labels = sorted(o["label"] for o in options)
        assert labels == ["Fonderie (Procédé)", "Libre"]


# --- Statuts -----------------------------------------------------------------------


class TestStatuts:
    def test_set_status_applique_le_statut(self, service, chain) -> None:
        message, refresh = graph_editor.apply_status_callback(1, "B", "done", 0)

        assert "Terminée" in str(message) and "Usine" in str(message)
        assert refresh == 1
        assert service.registry.get_node("B").status is TaskStatus.DONE
        assert service.repo.get_node("B").status is TaskStatus.DONE

    def test_selection_incomplete_refusee(self, service, chain) -> None:
        message, refresh = graph_editor.apply_status_callback(1, None, "done", 0)

        assert "Choisissez un nœud ET un statut." in str(message)
        assert refresh is no_update


# --- Layout, câblage et garde-fous -------------------------------------------------


class TestPage:
    def test_layout_contient_les_ids_et_le_dialogue_unique(self, service, chain) -> None:
        rendu = str(graph_editor.layout())

        for el_id in (
            "arc-edit-table",
            "arc-add-source-dd",
            "arc-add-target-dd",
            "arc-add-gamma",
            "arc-add-beta",
            "arc-add-nature-dd",
            "arc-add-btn",
            "arc-del-dd",
            "arc-del-confirm",
            "tag-cat-name-input",
            "tag-cat-color-input",
            "tag-cat-create-btn",
            "tag-name-input",
            "tag-cat-dd",
            "tag-create-btn",
            "tag-node-dd",
            "tag-assign-dd",
            "tag-assign-btn",
            "graph-status-node-dd",
            "graph-status-dd",
            "graph-status-btn",
            "graph-edit-refresh",
        ):
            assert el_id in rendu, f"id manquant dans le layout : {el_id}"
        # UN SEUL ConfirmDialogProvider sur la page (piège des races documenté).
        assert rendu.count("ConfirmDialogProvider") == 1
        assert "Supprimer l'arc ? La propagation sera recalculée." in rendu

    def test_register_callbacks_sans_doublon(self, service) -> None:
        app = dash.Dash(__name__, suppress_callback_exceptions=True)
        graph_editor.register_callbacks(app)  # aucun DuplicateCallback / output invalide

    @pytest.mark.parametrize(
        "appel",
        [
            lambda: graph_editor.add_arc_callback(0, "B", "A", 0.5, 0.5, "nominal", {}, 0),
            lambda: graph_editor.delete_arc_callback(None, "B->A", 0),
            lambda: graph_editor.create_category_callback(0, "x", "#fff", _PROJECT, 0),
            lambda: graph_editor.create_tag_callback(0, "x", None, _PROJECT, 0),
            lambda: graph_editor.assign_tags_callback(0, "B", [], {}, 0),
            lambda: graph_editor.apply_status_callback(0, "B", "done", 0),
        ],
    )
    def test_sans_clic_prevent_update(self, service, chain, appel) -> None:
        with pytest.raises(PreventUpdate):
            appel()

    def test_creerait_un_cycle_bfs(self, service, chain) -> None:
        assert graph_editor._creerait_un_cycle(service.repo, "A", "C") is True  # A→C ferme C⇝A
        assert graph_editor._creerait_un_cycle(service.repo, "B", "B") is True  # boucle
        assert graph_editor._creerait_un_cycle(service.repo, "D", "A") is False
        assert graph_editor._creerait_un_cycle(service.repo, "C", "A") is False  # diamant licite
