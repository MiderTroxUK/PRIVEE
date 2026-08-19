"""Tests du journal des interventions - contrat no9 (HELIOS v7 : InterventionJournal).

Couvre : la capture automatique de l'etat AVANT observable (contrat no9) et de
l'etat de risque d'interface (toujours capture, jamais surchargeable, jamais
lu pour le resultat), le cycle complet record -> executee -> proposer ->
clore, la definition figee du resultat operationnel (jalon rate -> 'echec',
fenetre propre + jalon livre -> 'resolu', fenetre propre sans jalon exploitable
-> 'partiel', fenetre pas close -> 'en_cours'), la derivation de ``succes`` a
la cloture, ``stats_par_action`` et le rejeu ``import_synthetic`` d'un fichier
JSONL synthetique.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from supplyscore.core.clock import WEEK_SECONDS, FixedClock
from supplyscore.data.db import ClientDatabase
from supplyscore.domain.milestones import Milestone, MilestoneStatus
from supplyscore.domain.models import Project, TaskStatus
from supplyscore.services import SupplyScoreService
from supplyscore.services.events import EventEngine
from supplyscore.services.interventions import Intervention, InterventionJournal

#: Mercredi 2026-06-10 12:00 locale - semaine ISO " 2026-S24 " (meme ancrage que test_decisions.py/test_calibration.py, pour rester coherent).
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()
_WEEK = WEEK_SECONDS


# Fixtures


@pytest.fixture
def fixed_clock() -> FixedClock:
    return FixedClock(_NOW)


@pytest.fixture
def service(tmp_path: Path, fixed_clock: FixedClock) -> Iterator[SupplyScoreService]:
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=fixed_clock)
    yield svc
    svc.close()


@pytest.fixture
def projet(service: SupplyScoreService) -> Project:
    """Projet de demonstration reproductible (seed_demo)."""
    return service.seed_demo(n_ranks=2, seed=1)


@pytest.fixture
def node_id(service: SupplyScoreService, projet: Project) -> str:
    """Premier noeud actif (ordre deterministe) du projet de demo."""
    nodes = sorted(service.repo.nodes(), key=lambda n: n.id)
    actifs = [
        n for n in nodes if n.status is TaskStatus.ACTIVE and n.onboarding_state == "complete"
    ]
    assert actifs, "le projet de démo doit contenir au moins un nœud actif"
    return actifs[0].id


@pytest.fixture
def journal(service: SupplyScoreService) -> InterventionJournal:
    return InterventionJournal(service)


def _repousser_jalons_existants(service: SupplyScoreService) -> None:
    """Repousse tous les jalons du seed_demo a +100 semaines (aucun parasite).

    Meme precaution que ``test_calibration.py::partie`` : le generateur de
    demonstration pose des jalons dont les echeances pourraient tomber dans
    les fenetres d'observation construites par les tests ci-dessous.
    """
    for node in service.repo.nodes():
        for milestone in service.registry.list_milestones(node.id):
            milestone.deadline_ts = _NOW + 100 * _WEEK
            service.registry.save_milestone(milestone)


# record : capture automatique de l'etat AVANT et de l'etat de risque


class TestRecord:
    def test_capture_automatique_observable_et_risque(
        self, service: SupplyScoreService, journal: InterventionJournal, node_id: str
    ) -> None:
        node = service.registry.get_node(node_id)
        assert node is not None
        urgence = node.urgency

        iv = journal.record(node_id, "action-relance", "op-7", "Réduire le lead time sous 48h")

        assert isinstance(iv, Intervention)
        assert iv.etat_avant == {
            "ur_local": urgence.ur_local,
            "ud_local": urgence.ud_local,
            "hidden_risk": urgence.hidden_risk,
            "false_urgency": urgence.false_urgency,
        }
        # Le projet de demo a des scores calcules : le snapshot n'est pas vide.
        assert iv.etat_avant["hidden_risk"] is not None
        assert iv.etat_risque_avant == {
            "ud_local": urgence.ud_local,
            "ur_local": urgence.ur_local,
            "ud": urgence.ud,
            "ur": urgence.ur,
            "adequation": urgence.adequation,
            "false_urgency": urgence.false_urgency,
            "hidden_risk": urgence.hidden_risk,
        }
        assert iv.node_id == node_id
        assert iv.action_id == "action-relance"
        assert iv.acteur == "op-7"
        assert iv.objectif_operationnel == "Réduire le lead time sous 48h"
        assert iv.date_ts == _NOW
        assert iv.decidee_ts == _NOW
        assert iv.executee is None
        assert iv.executee_ts is None
        assert iv.date_effet_ts is None
        assert iv.resultat == "en_cours"
        assert iv.etat_apres is None
        assert iv.etat_risque_apres is None
        assert iv.succes is None
        assert iv.effets_voisins == []
        assert iv.notes == ""

        # Persistee et relue a l'identique (round-trip JSON compris).
        assert journal.list_for_node(node_id) == [iv]

    def test_etat_avant_fourni_ecrase_l_auto_capture_mais_pas_le_risque(
        self, service: SupplyScoreService, journal: InterventionJournal, node_id: str
    ) -> None:
        node = service.registry.get_node(node_id)
        assert node is not None
        urgence = node.urgency

        iv = journal.record(
            node_id,
            "a1",
            "op",
            "Objectif",
            etat_avant={"p_issue": 0.42, "note": "forecast externe"},
        )

        assert iv.etat_avant == {"p_issue": 0.42, "note": "forecast externe"}
        # etat_risque_avant reste TOUJOURS auto-capture, jamais l'override.
        assert iv.etat_risque_avant["hidden_risk"] == urgence.hidden_risk
        assert iv.etat_risque_avant["ur"] == urgence.ur

    def test_acteur_vide_leve_value_error_et_n_ecrit_rien(
        self, journal: InterventionJournal, node_id: str
    ) -> None:
        with pytest.raises(ValueError, match="acteur"):
            journal.record(node_id, "a1", "", "Objectif")
        with pytest.raises(ValueError, match="acteur"):
            journal.record(node_id, "a1", "   ", "Objectif")
        assert journal.list_for_node(node_id) == []

    def test_objectif_vide_leve_value_error_et_n_ecrit_rien(
        self, journal: InterventionJournal, node_id: str
    ) -> None:
        with pytest.raises(ValueError, match="objectif"):
            journal.record(node_id, "a1", "op", "")
        with pytest.raises(ValueError, match="objectif"):
            journal.record(node_id, "a1", "op", "   ")
        assert journal.list_for_node(node_id) == []

    def test_noeud_inconnu_leve_value_error(
        self, journal: InterventionJournal, projet: Project
    ) -> None:
        with pytest.raises(ValueError, match="inconnu"):
            journal.record("fantome", "a1", "op", "Objectif")

    def test_ids_uniques(self, journal: InterventionJournal, node_id: str) -> None:
        i1 = journal.record(node_id, "a1", "op", "Obj A")
        i2 = journal.record(node_id, "a1", "op", "Obj B")
        assert i1.id != i2.id

    def test_horloge_reelle_si_noeud_sans_projet(
        self,
        service: SupplyScoreService,
        journal: InterventionJournal,
        fixed_clock: FixedClock,
    ) -> None:
        """Un noeud sans project_id retombe sur l'horloge reelle du service (pas clock_for)."""
        from supplyscore.domain.models import SupplyNode

        service.registry.save_node(SupplyNode(id="n-sans-projet", name="Orphelin", project_id=None))
        fixed_clock.set(_NOW + 999.0)

        iv = journal.record("n-sans-projet", "a1", "op", "Objectif")

        assert iv.date_ts == _NOW + 999.0


# marquer_executee


class TestMarquerExecutee:
    def test_pose_executee_executee_ts_et_date_effet(
        self,
        service: SupplyScoreService,
        journal: InterventionJournal,
        node_id: str,
        fixed_clock: FixedClock,
    ) -> None:
        iv = journal.record(node_id, "a1", "op", "Objectif")
        fixed_clock.set(_NOW + 3600.0)

        journal.marquer_executee(iv.id, node_id, True, date_effet_ts=_NOW + 7200.0)

        row = journal.list_for_node(node_id)[0]
        assert row.executee is True
        assert row.executee_ts == _NOW + 3600.0
        assert row.date_effet_ts == _NOW + 7200.0
        # Rien d'autre n'a bouge.
        assert row.resultat == "en_cours"

    def test_executee_false_sans_date_effet(
        self, journal: InterventionJournal, node_id: str
    ) -> None:
        iv = journal.record(node_id, "a1", "op", "Objectif")
        journal.marquer_executee(iv.id, node_id, False, date_effet_ts=None)

        row = journal.list_for_node(node_id)[0]
        assert row.executee is False
        assert row.date_effet_ts is None

    def test_intervention_inconnue_leve_value_error(
        self, journal: InterventionJournal, node_id: str
    ) -> None:
        with pytest.raises(ValueError, match="inconnue"):
            journal.marquer_executee("id-fantome", node_id, True, date_effet_ts=_NOW)

    def test_noeud_inconnu_leve_value_error(self, journal: InterventionJournal) -> None:
        with pytest.raises(ValueError, match="inconnu"):
            journal.marquer_executee("id-quelconque", "fantome", True, date_effet_ts=_NOW)


# proposer_resultat : definition figee (jamais d'ecriture)


class TestProposerResultatEnCours:
    def test_sans_date_effet_propose_en_cours(
        self, journal: InterventionJournal, node_id: str
    ) -> None:
        iv = journal.record(node_id, "a1", "op", "Objectif")

        resultat, _causes = journal.proposer_resultat(iv.id, node_id)

        assert resultat == "en_cours"
        # Rien n'a ete ecrit par la proposition.
        assert journal.list_for_node(node_id)[0].resultat == "en_cours"

    def test_fenetre_pas_encore_ecoulee_propose_en_cours(
        self,
        service: SupplyScoreService,
        journal: InterventionJournal,
        node_id: str,
        fixed_clock: FixedClock,
    ) -> None:
        _repousser_jalons_existants(service)
        iv = journal.record(node_id, "a1", "op", "Objectif")
        journal.marquer_executee(iv.id, node_id, True, date_effet_ts=_NOW)
        fixed_clock.set(_NOW + 1 * _WEEK)  # dans la fenetre [date_effet, +4 sem[

        resultat, _causes = journal.proposer_resultat(iv.id, node_id)

        assert resultat == "en_cours"


class TestProposerResultatEchec:
    def test_non_executee_propose_echec_immediatement(
        self, journal: InterventionJournal, node_id: str
    ) -> None:
        iv = journal.record(node_id, "a1", "op", "Objectif")
        journal.marquer_executee(iv.id, node_id, False, date_effet_ts=None)

        resultat, causes = journal.proposer_resultat(iv.id, node_id)

        assert resultat == "echec"
        assert causes

    def test_jalon_rate_dans_la_fenetre_propose_echec(
        self,
        service: SupplyScoreService,
        journal: InterventionJournal,
        node_id: str,
        fixed_clock: FixedClock,
    ) -> None:
        _repousser_jalons_existants(service)
        iv = journal.record(node_id, "a1", "op", "Livrer le prototype")
        date_effet = _NOW
        journal.marquer_executee(iv.id, node_id, True, date_effet_ts=date_effet)

        # Jalon dont l'echeance tombe DANS la fenetre, toujours ACTIVE (jamais livre).
        service.registry.save_milestone(
            Milestone(
                id="m-rate",
                node_id=node_id,
                name="Prototype",
                start_ts=date_effet,
                deadline_ts=date_effet + 1.5 * _WEEK,
                status=MilestoneStatus.ACTIVE,
                progress=0.2,
                position=99,
            )
        )
        fixed_clock.set(date_effet + 5 * _WEEK)  # fenetre entierement ecoulee

        resultat, causes = journal.proposer_resultat(iv.id, node_id)

        assert resultat == "echec"
        assert any("Prototype" in cause for cause in causes)
        # proposer_resultat n'ecrit RIEN : le resultat en base reste 'en_cours'.
        assert journal.list_for_node(node_id)[0].resultat == "en_cours"

    def test_noeud_abandonne_propose_echec(
        self,
        service: SupplyScoreService,
        journal: InterventionJournal,
        node_id: str,
        fixed_clock: FixedClock,
    ) -> None:
        _repousser_jalons_existants(service)
        iv = journal.record(node_id, "a1", "op", "Objectif")
        journal.marquer_executee(iv.id, node_id, True, date_effet_ts=_NOW)
        service.set_status(node_id, TaskStatus.ABANDONED)
        fixed_clock.set(_NOW + 5 * _WEEK)

        resultat, causes = journal.proposer_resultat(iv.id, node_id)

        assert resultat == "echec"
        assert any("abandonné" in cause for cause in causes)


class TestProposerResultatResoluEtPartiel:
    def test_fenetre_propre_avec_jalon_livre_propose_resolu(
        self,
        service: SupplyScoreService,
        journal: InterventionJournal,
        node_id: str,
        fixed_clock: FixedClock,
    ) -> None:
        _repousser_jalons_existants(service)
        iv = journal.record(node_id, "a1", "op", "Livrer le prototype")
        date_effet = _NOW
        journal.marquer_executee(iv.id, node_id, True, date_effet_ts=date_effet)

        service.registry.save_milestone(
            Milestone(
                id="m-livre",
                node_id=node_id,
                name="Prototype",
                start_ts=date_effet,
                deadline_ts=date_effet + 1.5 * _WEEK,
                status=MilestoneStatus.DONE,
                progress=1.0,
                position=99,
            )
        )
        fixed_clock.set(date_effet + 5 * _WEEK)

        resultat, causes = journal.proposer_resultat(iv.id, node_id)

        assert resultat == "resolu"
        assert any("Prototype" in cause for cause in causes)

    def test_evenement_hors_fenetre_est_ignore(
        self,
        service: SupplyScoreService,
        journal: InterventionJournal,
        node_id: str,
        fixed_clock: FixedClock,
    ) -> None:
        """Un evenement critique survenu AVANT date_effet ne compte pas comme issue."""
        _repousser_jalons_existants(service)
        # Evenement critique declare AVANT l'ouverture de la fenetre d'observation.
        EventEngine(service).apply(
            node_id, "panne_machine", {"duree_arret_h": 24.0, "gravite": "critique"}
        )

        fixed_clock.set(_NOW + 1 * _WEEK)
        date_effet = fixed_clock.now()
        iv = journal.record(node_id, "a1", "op", "Livrer le prototype")
        journal.marquer_executee(iv.id, node_id, True, date_effet_ts=date_effet)
        service.registry.save_milestone(
            Milestone(
                id="m-livre",
                node_id=node_id,
                name="Prototype",
                start_ts=date_effet,
                deadline_ts=date_effet + 1.5 * _WEEK,
                status=MilestoneStatus.DONE,
                progress=1.0,
                position=99,
            )
        )
        fixed_clock.set(date_effet + 5 * _WEEK)

        resultat, _causes = journal.proposer_resultat(iv.id, node_id)

        # L'evenement critique, anterieur a date_effet, n'a AUCUNE incidence.
        assert resultat == "resolu"

    def test_fenetre_propre_sans_jalon_exploitable_propose_partiel(
        self,
        service: SupplyScoreService,
        journal: InterventionJournal,
        node_id: str,
        fixed_clock: FixedClock,
    ) -> None:
        _repousser_jalons_existants(service)
        iv = journal.record(node_id, "a1", "op", "Objectif")
        date_effet = _NOW
        journal.marquer_executee(iv.id, node_id, True, date_effet_ts=date_effet)
        fixed_clock.set(date_effet + 5 * _WEEK)

        resultat, causes = journal.proposer_resultat(iv.id, node_id)

        assert resultat == "partiel"
        assert causes  # motif explicite (confirmation operateur requise)


class TestProposerResultatIgnoreEtatDeRisque:
    """L'etat de risque (Ud/Ur/H) ne doit JAMAIS influencer le label causal."""

    def test_hidden_risk_extreme_ne_change_pas_le_resultat_resolu(
        self,
        service: SupplyScoreService,
        journal: InterventionJournal,
        node_id: str,
        fixed_clock: FixedClock,
    ) -> None:
        _repousser_jalons_existants(service)
        # Risque cache catastrophique juste avant l'ouverture : si le resultat en tenait compte, on n'obtiendrait jamais 'resolu' ci-dessous.
        from supplyscore.domain.models import UrgencyState

        service.client_db(node_id).save_urgency_state(
            node_id, UrgencyState(hidden_risk=0.99, ur=0.99, ud=0.0, timestamp=_NOW - 10.0)
        )
        service.registry.save_urgency(
            node_id, UrgencyState(hidden_risk=0.99, ur=0.99, ud=0.0, timestamp=_NOW - 10.0)
        )

        iv = journal.record(node_id, "a1", "op", "Livrer le prototype")
        assert iv.etat_avant["hidden_risk"] == pytest.approx(0.99)  # bien capture...

        date_effet = _NOW
        journal.marquer_executee(iv.id, node_id, True, date_effet_ts=date_effet)
        service.registry.save_milestone(
            Milestone(
                id="m-livre",
                node_id=node_id,
                name="Prototype",
                start_ts=date_effet,
                deadline_ts=date_effet + 1.5 * _WEEK,
                status=MilestoneStatus.DONE,
                progress=1.0,
                position=99,
            )
        )
        fixed_clock.set(date_effet + 5 * _WEEK)

        resultat, _causes = journal.proposer_resultat(iv.id, node_id)

        # ... mais le resultat reste 'resolu' : le risque n'est jamais lu.
        assert resultat == "resolu"

    def test_hidden_risk_nul_ne_change_pas_le_resultat_echec(
        self,
        service: SupplyScoreService,
        journal: InterventionJournal,
        node_id: str,
        fixed_clock: FixedClock,
    ) -> None:
        _repousser_jalons_existants(service)
        from supplyscore.domain.models import UrgencyState

        service.registry.save_urgency(
            node_id, UrgencyState(hidden_risk=0.0, ur=0.0, ud=0.0, timestamp=_NOW - 10.0)
        )

        iv = journal.record(node_id, "a1", "op", "Livrer le prototype")
        date_effet = _NOW
        journal.marquer_executee(iv.id, node_id, True, date_effet_ts=date_effet)
        service.registry.save_milestone(
            Milestone(
                id="m-rate",
                node_id=node_id,
                name="Prototype",
                start_ts=date_effet,
                deadline_ts=date_effet + 1.5 * _WEEK,
                status=MilestoneStatus.ACTIVE,
                progress=0.1,
                position=99,
            )
        )
        fixed_clock.set(date_effet + 5 * _WEEK)

        resultat, _causes = journal.proposer_resultat(iv.id, node_id)

        # Risque cache nul (tout va "bien" cote urgence) mais jalon rate : le resultat reste 'echec' - seuls les faits comptent.
        assert resultat == "echec"


class TestProposerResultatErreurs:
    def test_intervention_inconnue_leve_value_error(
        self, journal: InterventionJournal, node_id: str
    ) -> None:
        with pytest.raises(ValueError, match="inconnue"):
            journal.proposer_resultat("id-fantome", node_id)


# clore : ecriture humaine, succes derive


class TestClore:
    def test_clore_resolu_derive_succes_true_et_capture_etat_apres(
        self, service: SupplyScoreService, journal: InterventionJournal, node_id: str
    ) -> None:
        node = service.registry.get_node(node_id)
        assert node is not None
        urgence = node.urgency
        iv = journal.record(node_id, "a1", "op", "Objectif")

        journal.clore(
            iv.id, node_id, "resolu", effets_voisins=["nœud voisin : Ur -0.1"], notes="clôturé"
        )

        row = journal.list_for_node(node_id)[0]
        assert row.resultat == "resolu"
        assert row.succes is True
        assert row.effets_voisins == ["nœud voisin : Ur -0.1"]
        assert row.notes == "clôturé"
        assert row.etat_apres == {
            "ur_local": urgence.ur_local,
            "ud_local": urgence.ud_local,
            "hidden_risk": urgence.hidden_risk,
            "false_urgency": urgence.false_urgency,
        }
        assert row.etat_risque_apres is not None
        assert row.etat_risque_apres["hidden_risk"] == urgence.hidden_risk

    def test_clore_echec_derive_succes_false(
        self, journal: InterventionJournal, node_id: str
    ) -> None:
        iv = journal.record(node_id, "a1", "op", "Objectif")
        journal.clore(iv.id, node_id, "echec")
        assert journal.list_for_node(node_id)[0].succes is False

    @pytest.mark.parametrize("resultat", ["partiel", "en_cours"])
    def test_clore_partiel_et_en_cours_derivent_succes_none(
        self, journal: InterventionJournal, node_id: str, resultat: str
    ) -> None:
        iv = journal.record(node_id, "a1", "op", "Objectif")
        journal.clore(iv.id, node_id, resultat)
        assert journal.list_for_node(node_id)[0].succes is None

    def test_etat_apres_fourni_ecrase_l_auto_capture(
        self, journal: InterventionJournal, node_id: str
    ) -> None:
        iv = journal.record(node_id, "a1", "op", "Objectif")
        journal.clore(iv.id, node_id, "resolu", etat_apres={"p_issue": 0.05})
        assert journal.list_for_node(node_id)[0].etat_apres == {"p_issue": 0.05}

    def test_resultat_invalide_leve_value_error_et_n_ecrit_rien(
        self, journal: InterventionJournal, node_id: str
    ) -> None:
        iv = journal.record(node_id, "a1", "op", "Objectif")
        with pytest.raises(ValueError, match="resultat"):
            journal.clore(iv.id, node_id, "invalide")
        assert journal.list_for_node(node_id)[0].resultat == "en_cours"

    def test_intervention_inconnue_leve_value_error(
        self, journal: InterventionJournal, node_id: str
    ) -> None:
        with pytest.raises(ValueError, match="inconnue"):
            journal.clore("id-fantome", node_id, "resolu")


# Cycle complet : record -> executee -> proposer -> clore (happy path)


class TestCycleComplet:
    def test_record_executee_proposer_clore(
        self,
        service: SupplyScoreService,
        journal: InterventionJournal,
        node_id: str,
        fixed_clock: FixedClock,
    ) -> None:
        _repousser_jalons_existants(service)

        # 1. Ouverture.
        iv = journal.record(
            node_id, "action-relance-fournisseur", "op-7", "Réduire le lead time sous 48h"
        )
        assert journal.list_for_node(node_id, only_open=True) == [iv]

        # 2. Execution.
        fixed_clock.set(_NOW + 1000.0)
        date_effet = fixed_clock.now()
        journal.marquer_executee(iv.id, node_id, True, date_effet_ts=date_effet)

        # 3. Le jalon vise par l'intervention est livre dans la fenetre.
        service.registry.save_milestone(
            Milestone(
                id="m-ok",
                node_id=node_id,
                name="Livraison anticipée",
                start_ts=date_effet,
                deadline_ts=date_effet + 2 * _WEEK,
                status=MilestoneStatus.DONE,
                progress=1.0,
                position=1,
            )
        )
        fixed_clock.set(date_effet + 5 * _WEEK)  # fenetre entierement ecoulee

        # 4. Proposition (lecture seule).
        resultat_propose, causes = journal.proposer_resultat(iv.id, node_id)
        assert resultat_propose == "resolu"
        assert causes
        assert journal.list_for_node(node_id)[0].resultat == "en_cours"  # rien ecrit

        # 5. Cloture humaine : l'operateur retient la proposition.
        journal.clore(
            iv.id,
            node_id,
            resultat_propose,
            effets_voisins=["nœud voisin stabilisé"],
            notes="clôturé après revue",
        )

        final = journal.list_for_node(node_id)[0]
        assert final.resultat == "resolu"
        assert final.succes is True
        assert final.effets_voisins == ["nœud voisin stabilisé"]
        assert journal.list_for_node(node_id, only_open=True) == []

        project_id = service.registry.get_node(node_id).project_id
        assert project_id is not None
        stats = journal.stats_par_action(project_id)
        assert stats["action-relance-fournisseur"] == {
            "n": 1,
            "n_executees": 1,
            "n_succes": 1,
            "n_echecs": 0,
        }


# stats_par_action


class TestStatsParAction:
    def test_agrege_plusieurs_noeuds_et_actions(
        self, service: SupplyScoreService, journal: InterventionJournal, projet: Project
    ) -> None:
        nodes = sorted(n.id for n in service.registry.list_nodes(projet.id))
        assert len(nodes) >= 2
        n1, n2 = nodes[0], nodes[1]

        i1 = journal.record(n1, "a1", "op", "Obj 1")
        journal.marquer_executee(i1.id, n1, True, date_effet_ts=_NOW)
        journal.clore(i1.id, n1, "resolu")

        i2 = journal.record(n2, "a1", "op", "Obj 2")
        journal.marquer_executee(i2.id, n2, True, date_effet_ts=_NOW)
        journal.clore(i2.id, n2, "echec")

        journal.record(n1, "a2", "op", "Obj 3")  # jamais executee

        stats = journal.stats_par_action(projet.id)

        assert stats["a1"] == {"n": 2, "n_executees": 2, "n_succes": 1, "n_echecs": 1}
        assert stats["a2"] == {"n": 1, "n_executees": 0, "n_succes": 0, "n_echecs": 0}

    def test_projet_sans_intervention_retourne_vide(
        self, journal: InterventionJournal, projet: Project
    ) -> None:
        assert journal.stats_par_action(projet.id) == {}

    def test_projet_inconnu_retourne_vide(self, journal: InterventionJournal) -> None:
        assert journal.stats_par_action("p-fantome") == {}


# import_synthetic : rejeu d'un fichier JSONL synthetique


class TestImportSynthetic:
    def test_rejoue_fichier_jsonl(self, tmp_path: Path, journal: InterventionJournal) -> None:
        lignes = [
            {
                "tour": 1,
                "node": "nA",
                "action_id": "a1",
                "etat_avant": {"hidden_risk": 0.6},
                "decidee": True,
                "executee": True,
                "date_effet": 2,
                "resultat_operationnel": "resolu",
                "effets_voisins": ["nB : Ur -0.05"],
            },
            {
                "tour": 3,
                "node": "nB",
                "action_id": "a2",
                "decidee": True,
                "executee": False,
                "date_effet": None,
                "resultat_operationnel": "echec",
            },
            # candidate rejetee par le generateur synthetique : pas importee.
            {"tour": 4, "node": "nA", "action_id": "a3", "decidee": False},
            # cle inconnue toleree, resultat absent -> 'en_cours' par defaut.
            {
                "tour": 5,
                "node": "nA",
                "action_id": "a1",
                "decidee": True,
                "executee": True,
                "date_effet": 5,
                "cle_inconnue": "peu importe",
            },
        ]
        chemin = tmp_path / "interventions_truth.jsonl"
        chemin.write_text("\n".join(json.dumps(ligne) for ligne in lignes) + "\n", encoding="utf-8")

        compte = journal.import_synthetic(chemin)

        assert compte == 3  # la candidate 'decidee: false' n'est pas comptee

        na = journal.list_for_node("nA")
        assert len(na) == 2
        assert na[0].action_id == "a1"
        assert na[0].resultat == "resolu"
        assert na[0].succes is True
        assert na[0].etat_avant == {"hidden_risk": 0.6}
        assert na[0].effets_voisins == ["nB : Ur -0.05"]
        assert na[0].date_ts == pytest.approx(1 * WEEK_SECONDS)
        assert na[0].date_effet_ts == pytest.approx(2 * WEEK_SECONDS)
        assert na[1].resultat == "en_cours"
        assert na[1].succes is None

        nb = journal.list_for_node("nB")
        assert len(nb) == 1
        assert nb[0].executee is False
        assert nb[0].resultat == "echec"
        assert nb[0].succes is False
        assert nb[0].date_effet_ts is None

    def test_resultat_operationnel_invalide_retombe_sur_en_cours(
        self, tmp_path: Path, journal: InterventionJournal
    ) -> None:
        chemin = tmp_path / "truth.jsonl"
        chemin.write_text(
            json.dumps(
                {
                    "tour": 1,
                    "node": "nA",
                    "action_id": "a1",
                    "resultat_operationnel": "n'importe quoi",
                }
            )
            + "\n",
            encoding="utf-8",
        )

        assert journal.import_synthetic(chemin) == 1

        row = journal.list_for_node("nA")[0]
        assert row.resultat == "en_cours"
        assert row.succes is None

    def test_node_mapping_reecrit_les_ids(
        self, tmp_path: Path, journal: InterventionJournal
    ) -> None:
        chemin = tmp_path / "truth.jsonl"
        chemin.write_text(
            json.dumps({"tour": 1, "node": "synthetic-A", "action_id": "a1"}) + "\n",
            encoding="utf-8",
        )

        compte = journal.import_synthetic(chemin, node_mapping={"synthetic-A": "real-node-1"})

        assert compte == 1
        assert journal.list_for_node("real-node-1")
        assert journal.list_for_node("synthetic-A") == []

    def test_ligne_json_invalide_leve_value_error(
        self, tmp_path: Path, journal: InterventionJournal
    ) -> None:
        chemin = tmp_path / "bad.jsonl"
        chemin.write_text("{ceci n'est pas du JSON}\n", encoding="utf-8")
        with pytest.raises(ValueError, match="JSON invalide"):
            journal.import_synthetic(chemin)

    def test_cle_requise_manquante_leve_value_error(
        self, tmp_path: Path, journal: InterventionJournal
    ) -> None:
        chemin = tmp_path / "missing.jsonl"
        chemin.write_text(json.dumps({"tour": 1, "node": "nA"}) + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match="action_id"):
            journal.import_synthetic(chemin)

    def test_lignes_vides_ignorees(self, tmp_path: Path, journal: InterventionJournal) -> None:
        chemin = tmp_path / "with_blanks.jsonl"
        chemin.write_text(
            "\n" + json.dumps({"tour": 1, "node": "nA", "action_id": "a1"}) + "\n\n",
            encoding="utf-8",
        )
        assert journal.import_synthetic(chemin) == 1


# Couche data : ClientDatabase.*_intervention (edition directe)

_ROW_BASE: dict[str, object] = {
    "id": "iv-1",
    "node_id": "n1",
    "date_ts": 1000.0,
    "etat_avant_json": "{}",
    "action_id": "a1",
    "acteur": "op",
    "objectif_operationnel": "tester",
    "decidee_ts": 1000.0,
    "executee": None,
    "executee_ts": None,
    "date_effet_ts": None,
    "resultat": "en_cours",
    "etat_apres_json": None,
    "etat_risque_avant_json": "{}",
    "etat_risque_apres_json": None,
    "succes": None,
    "effets_voisins_json": "[]",
    "notes": "",
}


class TestClientDatabaseInterventions:
    def test_insert_et_list_round_trip(self, tmp_path: Path) -> None:
        with ClientDatabase(tmp_path, "n1") as db:
            row_id = db.insert_intervention(dict(_ROW_BASE))
            assert row_id == "iv-1"
            rows = db.list_interventions("n1")
            assert len(rows) == 1
            assert rows[0]["action_id"] == "a1"

    def test_list_interventions_only_open_filtre_sur_resultat(self, tmp_path: Path) -> None:
        with ClientDatabase(tmp_path, "n1") as db:
            db.insert_intervention({**_ROW_BASE, "id": "iv-1", "resultat": "en_cours"})
            db.insert_intervention({**_ROW_BASE, "id": "iv-2", "resultat": "resolu"})
            assert {row["id"] for row in db.list_interventions("n1")} == {"iv-1", "iv-2"}
            assert [row["id"] for row in db.list_interventions("n1", only_open=True)] == ["iv-1"]

    def test_update_intervention_modifie_seulement_les_colonnes_fournies(
        self, tmp_path: Path
    ) -> None:
        with ClientDatabase(tmp_path, "n1") as db:
            db.insert_intervention(dict(_ROW_BASE))
            db.update_intervention("iv-1", {"resultat": "resolu", "succes": 1})
            row = db.list_interventions("n1")[0]
            assert row["resultat"] == "resolu"
            assert row["succes"] == 1
            assert row["action_id"] == "a1"  # non touche

    def test_update_intervention_changes_vide_leve_value_error(self, tmp_path: Path) -> None:
        with ClientDatabase(tmp_path, "n1") as db:
            db.insert_intervention(dict(_ROW_BASE))
            with pytest.raises(ValueError, match="vide"):
                db.update_intervention("iv-1", {})

    def test_update_intervention_colonne_inconnue_leve_value_error(self, tmp_path: Path) -> None:
        with ClientDatabase(tmp_path, "n1") as db:
            db.insert_intervention(dict(_ROW_BASE))
            with pytest.raises(ValueError, match="inconnues"):
                db.update_intervention("iv-1", {"colonne_inexistante": 1})

    def test_update_intervention_id_non_modifiable(self, tmp_path: Path) -> None:
        with ClientDatabase(tmp_path, "n1") as db:
            db.insert_intervention(dict(_ROW_BASE))
            with pytest.raises(ValueError, match="inconnues"):
                db.update_intervention("iv-1", {"id": "autre-id"})
