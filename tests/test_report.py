"""Tests du Lot 11.2 : SessionReport (HTML autonome) + page " Rapport ".

Couvre : la partie simulee (FixedClock + seed_demo en mode jeu + 4 semaines +
un evenement applique + une decision enregistree -> rapport contenant le nom du
projet, les sections " Synthese ", " Chronologie ", " Calibration ", la
description de la decision, le libelle FR de l'evenement, au moins 2 blocs
plotly et l'avertissement d'echantillon reduit), le projet inconnu
(ValueError), la creation du repertoire de destination, le projet vide
(branches sans historique / sans point de calibration) et les callbacks de la
page (sans projet -> message d'erreur ; avec projet -> donnees de
telechargement non nulles).
"""

from __future__ import annotations

import html as html_lib
import re
from datetime import datetime
from pathlib import Path

import dash
import pytest
from dash import no_update
from dash.exceptions import PreventUpdate

from supplyscore.core.clock import FixedClock
from supplyscore.domain.models import Project, TaskStatus
from supplyscore.services import SupplyScoreService
from supplyscore.services import report as report_module
from supplyscore.services.calibration import CalibrationService
from supplyscore.services.decisions import DecisionService
from supplyscore.services.events import EventEngine
from supplyscore.services.report import SessionReport
from supplyscore.web_ui import set_service
from supplyscore.web_ui.pages import report as report_page

#: Mercredi 2026-06-10 12:00 locale - horodatage de fichier " 20260610_120000 ".
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()
_STAMP = "20260610_120000"

_DESCRIPTION_DECISION = "Doubler le stock de sécurité du fournisseur critique"

#: Horizon d'appariement prediction/realite de ``SessionReport.build`` (son defaut).
_HORIZON = 4


@pytest.fixture
def service(tmp_path: Path):
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(_NOW))
    yield svc
    svc.close()


@pytest.fixture
def partie(service: SupplyScoreService) -> Project:
    """Partie simulee : demo en mode jeu, 4 semaines, un evenement, une decision."""
    projet = service.seed_demo(n_ranks=2, seed=1)
    service.set_clock_mode(projet.id, "game")
    for _ in range(4):
        service.advance_week(projet.id)
    nodes = sorted(service.repo.nodes(), key=lambda n: n.id)
    node_id = next(
        n.id for n in nodes if n.status is TaskStatus.ACTIVE and n.onboarding_state == "complete"
    )
    EventEngine(service).apply(
        node_id,
        "panne_machine",
        {"duree_arret_h": 24.0, "gravite": "majeure"},
        operator_id="op-1",
        notes="four en panne",
    )
    DecisionService(service).record(node_id, _DESCRIPTION_DECISION, operator_id="op-2")
    return projet


@pytest.fixture
def rapport(service: SupplyScoreService, partie: Project, tmp_path: Path) -> str:
    """Texte HTML du rapport genere sur la partie simulee."""
    path = SessionReport(service).build(partie.id, dest_dir=tmp_path / "exports")
    return path.read_text(encoding="utf-8")


# build : partie simulee


class TestBuildPartieSimulee:
    def test_fichier_cree_avec_le_bon_nom(
        self, service: SupplyScoreService, partie: Project, tmp_path: Path
    ) -> None:
        path = SessionReport(service).build(partie.id, dest_dir=tmp_path / "exports")

        assert path.exists()
        assert re.fullmatch(rf"Rapport_[A-Za-z0-9-]+_{_STAMP}\.html", path.name)

    def test_en_tete_et_sections(self, rapport: str, partie: Project) -> None:
        assert partie.name in rapport
        assert "Synthèse" in rapport
        assert "Chronologie" in rapport
        assert "Calibration" in rapport
        assert "Graphe final" in rapport
        assert "temps de jeu" in rapport  # mode horloge du projet
        assert "10/06/2026" in rapport  # " genere le " : horloge du service

    def test_chronologie_evenement_fr_et_decision(self, rapport: str) -> None:
        texte = html_lib.unescape(rapport)  # l'autoescape encode les apostrophes
        assert "Panne machine" in texte  # libelle FR du type d'evenement
        assert "Durée d'arrêt" in texte  # parametre traduit
        assert "actif" in texte  # evenement non annule
        assert _DESCRIPTION_DECISION in texte
        assert "Scores au moment T" in texte
        assert "op-2" in texte

    def test_au_moins_deux_blocs_plotly_et_cdn_unique(self, rapport: str) -> None:
        # Evolutions par noeud + graphe final : au moins 2 figures embarquees.
        assert rapport.count("plotly-graph-div") >= 2
        # Le JS Plotly est charge UNE seule fois, via CDN, dans le <head>.
        assert rapport.count("cdn.plot.ly") == 1

    def test_avertissement_echantillon_reduit(
        self, service: SupplyScoreService, partie: Project, rapport: str
    ) -> None:
        # Une partie de demo = quelques dizaines de points au plus : avertissement. La precondition est VERIFIEE, pas supposee : l'effectif depend du nombre de noeuds du graphe seede x le nombre de semaines jouees, et un graphe plus large ferait disparaitre l'avertissement - ce qui doit se lire dans le message d'echec, pas comme une chaine introuvable.
        points = CalibrationService(service).outcomes(partie.id, horizon_weeks=_HORIZON)
        seuil = report_module._SEUIL_PETIT_ECHANTILLON
        assert len(points) < seuil, (
            f"la partie de démo n'est plus un petit échantillon "
            f"({len(points)} points >= {seuil}) : l'avertissement ne s'applique plus"
        )
        assert f"Échantillon réduit ({len(points)} point(s) nœud-semaine)" in rapport

    def test_evenement_annule_affiche_annule_le(
        self, service: SupplyScoreService, partie: Project, tmp_path: Path
    ) -> None:
        engine = EventEngine(service)
        node_id, event = next(
            (node.id, evenement)
            for node in service.registry.list_nodes(partie.id)
            for evenement in engine.open_events(node.id)
        )
        engine.revert(event.id, node_id, operator_id="op-1")

        path = SessionReport(service).build(partie.id, dest_dir=tmp_path / "exports")

        texte = html_lib.unescape(path.read_text(encoding="utf-8"))
        assert "annulé le" in texte


# build : erreurs, destination, projet vide


class TestBuildErreursEtBranches:
    def test_projet_inconnu_value_error(self, service: SupplyScoreService, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="inconnu"):
            SessionReport(service).build("fantome", dest_dir=tmp_path / "exports")

    def test_dest_dir_cree_au_besoin(
        self, service: SupplyScoreService, partie: Project, tmp_path: Path
    ) -> None:
        dest = tmp_path / "exports" / "sous" / "dossier"
        assert not dest.exists()

        path = SessionReport(service).build(partie.id, dest_dir=dest)

        assert dest.is_dir()
        assert path.parent == dest

    def test_projet_vide_sans_historique_ni_calibration(
        self, service: SupplyScoreService, tmp_path: Path
    ) -> None:
        service.registry.save_project(
            Project(id="p-vide", name="Été à São Paulo / vide", owner_node_id="n0")
        )

        path = SessionReport(service).build("p-vide", dest_dir=tmp_path / "exports")

        assert path.name == f"Rapport_Ete-a-Sao-Paulo-vide_{_STAMP}.html"
        texte = path.read_text(encoding="utf-8")
        assert "aucun historique" in texte
        assert "temps réel" in texte
        assert "aucun nœud" in texte
        assert "Aucun nœud ne possède encore d'historique" in texte
        assert "Aucun événement ni décision" in texte
        assert "Aucun point de calibration" in texte
        assert "Échantillon réduit (0 point(s)" in texte
        # Le graphe final est rendu meme vide (figure " Aucun noeud ").
        assert texte.count("plotly-graph-div") == 1


# helpers recopies de services.exports


def test_fmt_date_none_chaine_vide() -> None:
    assert report_module._fmt_date(None) == ""


# page : layout


class TestLayout:
    def test_layout_contient_les_composants_attendus(self) -> None:
        texte = str(report_page.layout())

        assert "Générer le rapport de session" in texte
        assert "report-horizon" in texte
        assert "report-btn" in texte
        assert "report-download" in texte
        assert "report-msg" in texte


# page : callback


@pytest.fixture
def ui(service: SupplyScoreService):
    """Service partage avec la page (set_service/teardown)."""
    set_service(service)
    yield service
    set_service(None)


class TestGenerateReportCallback:
    def test_premier_rendu_prevent_update(self) -> None:
        with pytest.raises(PreventUpdate):
            report_page.generate_report_callback(None, {"project_id": "x"}, 4)

    def test_sans_projet_actif_message_erreur(self) -> None:
        msg, download = report_page.generate_report_callback(1, None, 4)

        assert "Sélectionnez d'abord un projet" in str(msg)
        assert download is no_update

    def test_projet_inconnu_message_erreur(self, ui: SupplyScoreService) -> None:
        msg, download = report_page.generate_report_callback(1, {"project_id": "fantome"}, 4)

        assert "inconnu" in str(msg)
        assert download is no_update

    def test_avec_projet_telechargement_non_none(
        self, ui: SupplyScoreService, partie: Project, tmp_path: Path, monkeypatch
    ) -> None:
        fake = tmp_path / "Rapport_factice.html"
        fake.write_text("<html></html>", encoding="utf-8")
        appels: list[tuple[str, int]] = []

        def fake_build(self, project_id, horizon_weeks=4, dest_dir="exports"):
            appels.append((project_id, horizon_weeks))
            return fake

        monkeypatch.setattr(SessionReport, "build", fake_build)

        msg, download = report_page.generate_report_callback(1, {"project_id": partie.id}, 4)

        assert download is not None and download is not no_update
        assert download["filename"] == "Rapport_factice.html"
        assert "Rapport_factice.html" in str(msg)
        assert appels == [(partie.id, 4)]

    @pytest.mark.parametrize(
        ("horizon_saisi", "horizon_attendu"),
        [("abc", 4), (None, 4), (99, 12), (0, 1), ("6", 6)],
    )
    def test_horizon_valide_cote_serveur(
        self,
        ui: SupplyScoreService,
        partie: Project,
        tmp_path: Path,
        monkeypatch,
        horizon_saisi,
        horizon_attendu,
    ) -> None:
        fake = tmp_path / "Rapport_factice.html"
        fake.write_text("<html></html>", encoding="utf-8")
        horizons: list[int] = []

        def fake_build(self, project_id, horizon_weeks=4, dest_dir="exports"):
            horizons.append(horizon_weeks)
            return fake

        monkeypatch.setattr(SessionReport, "build", fake_build)

        report_page.generate_report_callback(1, {"project_id": partie.id}, horizon_saisi)

        assert horizons == [horizon_attendu]


# page : register_callbacks


def test_register_callbacks_branche_le_callback() -> None:
    app = dash.Dash(__name__)
    report_page.register_callbacks(app)

    assert any("report-msg" in key for key in app.callback_map)
