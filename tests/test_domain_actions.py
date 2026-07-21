"""Tests du catalogue d'actions correctives (U15, contrat gelé n° 8).

Couvre : intégrité du catalogue (ids, incompatibles, bornes de coût et de
délai), préconditions (cas vrai/faux par action), pureté de
``apply_to_rollout`` (le state en entrée n'est jamais modifié), effet
numérique de chaque ``apply_to_rollout``, écritures réelles de chaque
``apply_to_project`` (via ``MutationService`` uniquement) et équivalence
sim/réel (même variation relative pour ``expedition_express``, même arc
promu en nominal des deux côtés pour ``promouvoir_arc_secours``).
"""

from __future__ import annotations

import copy
import dataclasses
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from supplyscore.domain.actions import (
    CATALOGUE_V1,
    OBJECTIFS_OPERATIONNELS,
    ContexteAction,
    RolloutState,
    _validate_catalogue,
    contexte_pour,
)
from supplyscore.domain.milestones import Milestone, MilestoneStatus
from supplyscore.domain.models import ArcKind, Project, SupplyArc, SupplyNode, UrgencyState
from supplyscore.services import SupplyScoreService

_DEUX_SEMAINES_H = 2.0 * 7.0 * 24.0
_DEUX_SEMAINES_S = _DEUX_SEMAINES_H * 3600.0


# --- Fixtures et aides ---------------------------------------------------------------


@pytest.fixture
def service(tmp_path: Path) -> Iterator[SupplyScoreService]:
    svc = SupplyScoreService(db_dir=tmp_path / "store")
    try:
        yield svc
    finally:
        svc.close()


def _ctx(
    node: SupplyNode | None = None,
    arcs_entrants: list[SupplyArc] | None = None,
    arcs_backup: list[SupplyArc] | None = None,
    urgency: UrgencyState | None = None,
    milestones: list[Milestone] | None = None,
) -> ContexteAction:
    return ContexteAction(
        node=node if node is not None else SupplyNode(id="n1", name="Atelier"),
        arcs_entrants=arcs_entrants or [],
        arcs_backup=arcs_backup or [],
        urgency=urgency if urgency is not None else UrgencyState(),
        milestones=milestones or [],
    )


def _sample_state() -> RolloutState:
    return {
        "ur_local": np.array([0.2, 0.3, 0.5]),
        "hazard": np.array([0.1, 0.15, 0.2]),
        "deadlines_h": {"m1": 100.0, "m2": 200.0},
        "arc_beta": {
            "fournisseur_nominal->client": 0.5,
            "fournisseur_secours->client:backup": 0.4,
        },
    }


def _toy_project(service: SupplyScoreService) -> tuple[SupplyNode, SupplyArc]:
    """Client + fournisseur nominal + fournisseur de secours (arc backup, beta=0.4).

    Returns:
        Le nœud client et l'arc de secours entrant (encore BACKUP).
    """
    project = Project(id="p1", name="Projet test", owner_node_id="client")
    client = SupplyNode(id="client", name="Client", project_id="p1", rank=0)
    nominal_supplier = SupplyNode(
        id="fournisseur_nominal", name="Fournisseur nominal", project_id="p1", rank=1
    )
    backup_supplier = SupplyNode(
        id="fournisseur_secours", name="Fournisseur de secours", project_id="p1", rank=1
    )
    nominal_arc = SupplyArc(source_id="fournisseur_nominal", target_id="client", beta=0.6)
    backup_arc = SupplyArc(
        source_id="fournisseur_secours", target_id="client", beta=0.4, kind_arc=ArcKind.BACKUP
    )
    service.create_project(
        project, [client, nominal_supplier, backup_supplier], [nominal_arc, backup_arc]
    )
    return client, backup_arc


# --- Intégrité du catalogue -----------------------------------------------------------


class TestCatalogueIntegrity:
    def test_six_actions(self):
        assert set(CATALOGUE_V1) == {
            "promouvoir_arc_secours",
            "replanifier_jalon",
            "expedition_express",
            "boost_capacite",
            "revue_declaration",
            "ne_rien_faire",
        }

    def test_ids_match_keys(self):
        for key, spec in CATALOGUE_V1.items():
            assert spec.id == key

    def test_incompatibles_reference_existing_ids(self):
        for spec in CATALOGUE_V1.values():
            for incompatible_id in spec.incompatibles:
                assert incompatible_id in CATALOGUE_V1

    def test_p_echec_in_bounds(self):
        for spec in CATALOGUE_V1.values():
            assert 0.0 <= spec.cout["p_echec_execution_defaut"] <= 1.0

    def test_delai_effet_weeks_ordered(self):
        for spec in CATALOGUE_V1.values():
            lo, mode, hi = spec.delai_effet_weeks
            assert lo <= mode <= hi

    def test_objectifs_operationnels_dans_liste_fermee(self):
        for spec in CATALOGUE_V1.values():
            for objectif in spec.objectifs_operationnels:
                assert objectif in OBJECTIFS_OPERATIONNELS

    def test_validate_catalogue_accepte_le_vrai_catalogue(self):
        _validate_catalogue(CATALOGUE_V1)  # ne lève pas

    def test_validate_catalogue_rejette_id_incoherent(self):
        broken = dict(CATALOGUE_V1)
        broken["ne_rien_faire"] = dataclasses.replace(broken["ne_rien_faire"], id="autre_id")
        with pytest.raises(ValueError, match="id incohérent"):
            _validate_catalogue(broken)

    def test_validate_catalogue_rejette_incompatible_inconnu(self):
        broken = dict(CATALOGUE_V1)
        broken["ne_rien_faire"] = dataclasses.replace(
            broken["ne_rien_faire"], incompatibles=["action_fantome"]
        )
        with pytest.raises(ValueError, match="incompatibles inconnus"):
            _validate_catalogue(broken)

    def test_validate_catalogue_rejette_p_echec_hors_bornes(self):
        base = CATALOGUE_V1["ne_rien_faire"]
        broken = dict(CATALOGUE_V1)
        broken["ne_rien_faire"] = dataclasses.replace(
            base, cout={**base.cout, "p_echec_execution_defaut": 1.5}
        )
        with pytest.raises(ValueError, match="p_echec_execution_defaut hors"):
            _validate_catalogue(broken)

    def test_validate_catalogue_rejette_delai_non_croissant(self):
        broken = dict(CATALOGUE_V1)
        broken["ne_rien_faire"] = dataclasses.replace(
            broken["ne_rien_faire"], delai_effet_weeks=(2.0, 1.0, 0.0)
        )
        with pytest.raises(ValueError, match="delai_effet_weeks non croissant"):
            _validate_catalogue(broken)

    def test_validate_catalogue_rejette_incompatibilite_asymetrique(self):
        # boost_capacite ne référence personne dans le vrai catalogue : le
        # rendre incompatible avec expedition_express sans réciprocité doit
        # être rejeté (cf. finding de revue : incompatibles doit être une
        # relation symétrique pour rester utilisable sans ambiguïté).
        broken = dict(CATALOGUE_V1)
        broken["boost_capacite"] = dataclasses.replace(
            broken["boost_capacite"], incompatibles=["expedition_express"]
        )
        with pytest.raises(ValueError, match="non symétrique"):
            _validate_catalogue(broken)

    def test_incompatibles_est_symetrique_dans_le_vrai_catalogue(self):
        for key, spec in CATALOGUE_V1.items():
            for other_id in spec.incompatibles:
                assert key in CATALOGUE_V1[other_id].incompatibles


# --- Préconditions ---------------------------------------------------------------------


class TestPreconditions:
    def test_promouvoir_arc_secours(self):
        spec = CATALOGUE_V1["promouvoir_arc_secours"]
        backup_arc = SupplyArc(source_id="s", target_id="n1", kind_arc=ArcKind.BACKUP)
        assert spec.preconditions(_ctx(arcs_backup=[backup_arc])) is True
        assert spec.preconditions(_ctx(arcs_backup=[])) is False

    def test_replanifier_jalon(self):
        spec = CATALOGUE_V1["replanifier_jalon"]
        active = Milestone(id="m1", node_id="n1", name="Proto", start_ts=0.0, deadline_ts=100.0)
        done = Milestone(
            id="m2",
            node_id="n1",
            name="Livraison",
            start_ts=0.0,
            deadline_ts=200.0,
            status=MilestoneStatus.DONE,
        )
        assert spec.preconditions(_ctx(milestones=[active])) is True
        assert spec.preconditions(_ctx(milestones=[done])) is False
        assert spec.preconditions(_ctx(milestones=[])) is False

    def test_expedition_express_toujours_applicable(self):
        spec = CATALOGUE_V1["expedition_express"]
        assert spec.preconditions(_ctx()) is True

    def test_boost_capacite(self):
        spec = CATALOGUE_V1["boost_capacite"]
        node_avec_debit = SupplyNode(id="n1", name="Atelier")
        node_avec_debit.kpis.inventory.flow_rate = 50.0
        node_sans_capacite = SupplyNode(id="n2", name="Atelier")
        assert spec.preconditions(_ctx(node=node_avec_debit)) is True
        assert spec.preconditions(_ctx(node=node_sans_capacite)) is False

    def test_revue_declaration(self):
        spec = CATALOGUE_V1["revue_declaration"]
        assert spec.preconditions(_ctx(urgency=UrgencyState(ud_local=0.4))) is True
        assert spec.preconditions(_ctx(urgency=UrgencyState(ud_local=None))) is False

    def test_ne_rien_faire_toujours_applicable(self):
        # Bras de référence : toujours applicable par contrat — pas de cas
        # « faux » à tester pour cette action (cf. docstring du catalogue).
        spec = CATALOGUE_V1["ne_rien_faire"]
        assert spec.preconditions(_ctx()) is True


# --- Pureté de apply_to_rollout ---------------------------------------------------------


class TestRolloutPurity:
    @pytest.mark.parametrize("action_id", list(CATALOGUE_V1))
    def test_input_state_untouched(self, action_id):
        spec = CATALOGUE_V1[action_id]
        state = _sample_state()
        snapshot = copy.deepcopy(state)

        result = spec.apply_to_rollout(state)

        assert result is not None
        assert set(state) == set(snapshot)
        assert np.array_equal(state["ur_local"], snapshot["ur_local"])
        assert np.array_equal(state["hazard"], snapshot["hazard"])
        assert state["deadlines_h"] == snapshot["deadlines_h"]
        assert state["arc_beta"] == snapshot["arc_beta"]


# --- Effet numérique de apply_to_rollout, par action -------------------------------------


class TestApplyToRolloutEffects:
    def test_promouvoir_arc_secours_active_le_backup_en_attente(self):
        state = _sample_state()

        result = CATALOGUE_V1["promouvoir_arc_secours"].apply_to_rollout(state)

        assert "fournisseur_secours->client:backup" not in result["arc_beta"]
        assert result["arc_beta"]["fournisseur_secours->client"] == pytest.approx(0.4)
        assert result["arc_beta"]["fournisseur_nominal->client"] == pytest.approx(0.5)

    def test_promouvoir_arc_secours_sans_backup_est_un_no_op(self):
        state = _sample_state()
        state["arc_beta"] = {"fournisseur_nominal->client": 0.5}

        result = CATALOGUE_V1["promouvoir_arc_secours"].apply_to_rollout(state)

        assert result["arc_beta"] == {"fournisseur_nominal->client": 0.5}

    def test_promouvoir_arc_secours_departage_par_petite_source_id(self):
        # Régression : avec plusieurs backups en attente, le rollout doit
        # choisir EXACTEMENT le même (plus petite source_id) que le côté réel
        # (_apply_project_promouvoir_arc_secours utilise min(..., key=source_id)),
        # sinon les deux applications promeuvent des arcs différents.
        state = _sample_state()
        state["arc_beta"] = {
            "z_fournisseur->client:backup": 0.9,
            "a_fournisseur->client:backup": 0.4,
        }

        result = CATALOGUE_V1["promouvoir_arc_secours"].apply_to_rollout(state)

        assert result["arc_beta"] == {
            "a_fournisseur->client": 0.4,
            "z_fournisseur->client:backup": 0.9,
        }

    def test_replanifier_jalon_decale_336h_uniquement_lechance_la_plus_proche(self):
        # Régression : seule l'échéance MINIMALE bouge, les autres restent en
        # place — même règle que côté réel (next_active_milestone), sinon
        # les deux applications ne portent plus sur le même jalon dès que le
        # nœud a plus d'un jalon actif (cf. RandomSupplyChainGenerator).
        state = _sample_state()

        result = CATALOGUE_V1["replanifier_jalon"].apply_to_rollout(state)

        assert result["deadlines_h"] == {
            "m1": 100.0 + _DEUX_SEMAINES_H,  # la plus proche (100 < 200) : décalée
            "m2": 200.0,  # inchangée
        }

    def test_replanifier_jalon_no_op_si_deadlines_h_vide(self):
        state = _sample_state()
        state["deadlines_h"] = {}

        result = CATALOGUE_V1["replanifier_jalon"].apply_to_rollout(state)

        assert result["deadlines_h"] == {}

    def test_expedition_express_reduit_ur_local_de_30_pourcent(self):
        state = _sample_state()
        original = np.array(state["ur_local"])

        result = CATALOGUE_V1["expedition_express"].apply_to_rollout(state)

        assert np.allclose(result["ur_local"], original * 0.7)

    def test_boost_capacite_reduit_hazard_de_25_pourcent(self):
        state = _sample_state()
        original = np.array(state["hazard"])

        result = CATALOGUE_V1["boost_capacite"].apply_to_rollout(state)

        assert np.allclose(result["hazard"], original * 0.75)

    def test_revue_declaration_et_ne_rien_faire_sont_des_identites(self):
        state = _sample_state()
        for action_id in ("revue_declaration", "ne_rien_faire"):
            result = CATALOGUE_V1[action_id].apply_to_rollout(state)
            assert result is not state
            assert result["deadlines_h"] == state["deadlines_h"]
            assert np.array_equal(result["ur_local"], state["ur_local"])


# --- apply_to_project : écritures réelles ------------------------------------------------


class TestApplyToProject:
    def test_promouvoir_arc_secours_keyerror_si_noeud_inconnu(self, service):
        with pytest.raises(KeyError):
            CATALOGUE_V1["promouvoir_arc_secours"].apply_to_project(service, "fantome")

    def test_promouvoir_arc_secours_no_op_sans_backup(self, service):
        project = Project(id="p1", name="Projet", owner_node_id="client")
        client = SupplyNode(id="client", name="Client", project_id="p1")
        service.create_project(project, [client], [])

        CATALOGUE_V1["promouvoir_arc_secours"].apply_to_project(service, "client")  # ne lève pas

    def test_promouvoir_arc_secours_departage_deterministe(self, service):
        project = Project(id="p1", name="Projet", owner_node_id="client")
        client = SupplyNode(id="client", name="Client", project_id="p1")
        supplier_a = SupplyNode(id="a_fournisseur", name="A", project_id="p1")
        supplier_z = SupplyNode(id="z_fournisseur", name="Z", project_id="p1")
        arc_a = SupplyArc(source_id="a_fournisseur", target_id="client", kind_arc=ArcKind.BACKUP)
        arc_z = SupplyArc(source_id="z_fournisseur", target_id="client", kind_arc=ArcKind.BACKUP)
        service.create_project(project, [client, supplier_a, supplier_z], [arc_a, arc_z])

        CATALOGUE_V1["promouvoir_arc_secours"].apply_to_project(service, "client")

        promu = service.repo.get_arc("a_fournisseur", "client")
        toujours_backup = service.repo.get_arc("z_fournisseur", "client")
        assert promu is not None and promu.kind_arc == ArcKind.NOMINAL
        assert toujours_backup is not None and toujours_backup.kind_arc == ArcKind.BACKUP

    def test_replanifier_jalon_decale_la_deadline(self, service):
        project = Project(id="p1", name="Projet", owner_node_id="n1")
        node = SupplyNode(id="n1", name="Atelier", project_id="p1")
        service.create_project(project, [node], [])
        service.registry.save_milestone(
            Milestone(id="m1", node_id="n1", name="Proto", start_ts=0.0, deadline_ts=1000.0)
        )

        CATALOGUE_V1["replanifier_jalon"].apply_to_project(service, "n1")

        updated = service.registry.get_milestone("m1")
        assert updated is not None
        assert updated.deadline_ts == pytest.approx(1000.0 + _DEUX_SEMAINES_S)
        assert updated.start_ts == 0.0

    def test_replanifier_jalon_ne_touche_que_le_jalon_le_plus_proche(self, service):
        # Régression : avec 2 jalons ACTIVE, seul celui de deadline minimale
        # (next_active_milestone) doit bouger — le second reste intact.
        project = Project(id="p1", name="Projet", owner_node_id="n1")
        node = SupplyNode(id="n1", name="Atelier", project_id="p1")
        service.create_project(project, [node], [])
        service.registry.save_milestone(
            Milestone(id="proche", node_id="n1", name="Proto", start_ts=0.0, deadline_ts=1000.0)
        )
        service.registry.save_milestone(
            Milestone(id="lointain", node_id="n1", name="Série", start_ts=0.0, deadline_ts=5000.0)
        )

        CATALOGUE_V1["replanifier_jalon"].apply_to_project(service, "n1")

        proche = service.registry.get_milestone("proche")
        lointain = service.registry.get_milestone("lointain")
        assert proche is not None and proche.deadline_ts == pytest.approx(1000.0 + _DEUX_SEMAINES_S)
        assert lointain is not None and lointain.deadline_ts == 5000.0

    def test_replanifier_jalon_no_op_sans_jalon_actif(self, service):
        project = Project(id="p1", name="Projet", owner_node_id="n1")
        node = SupplyNode(id="n1", name="Atelier", project_id="p1")
        service.create_project(project, [node], [])

        CATALOGUE_V1["replanifier_jalon"].apply_to_project(service, "n1")  # ne lève pas

    def test_replanifier_jalon_keyerror_si_noeud_inconnu(self, service):
        with pytest.raises(KeyError):
            CATALOGUE_V1["replanifier_jalon"].apply_to_project(service, "fantome")

    def test_expedition_express_reduit_le_lead_time(self, service):
        project = Project(id="p1", name="Projet", owner_node_id="n1")
        node = SupplyNode(id="n1", name="Atelier", project_id="p1")
        node.kpis.time.lead_time_h = 100.0
        service.create_project(project, [node], [])

        CATALOGUE_V1["expedition_express"].apply_to_project(service, "n1")

        updated = service.repo.get_node("n1")
        assert updated is not None
        assert updated.kpis.time.lead_time_h == pytest.approx(70.0)

    def test_expedition_express_no_op_sans_lead_time(self, service):
        project = Project(id="p1", name="Projet", owner_node_id="n1")
        node = SupplyNode(id="n1", name="Atelier", project_id="p1")
        service.create_project(project, [node], [])

        CATALOGUE_V1["expedition_express"].apply_to_project(service, "n1")

        updated = service.repo.get_node("n1")
        assert updated is not None
        assert updated.kpis.time.lead_time_h is None

    def test_expedition_express_keyerror_si_noeud_inconnu(self, service):
        with pytest.raises(KeyError):
            CATALOGUE_V1["expedition_express"].apply_to_project(service, "fantome")

    def test_boost_capacite_augmente_debit_et_volume(self, service):
        project = Project(id="p1", name="Projet", owner_node_id="n1")
        node = SupplyNode(id="n1", name="Atelier", project_id="p1")
        node.kpis.inventory.flow_rate = 50.0
        node.kpis.inventory.max_volume_m3 = 1000.0
        service.create_project(project, [node], [])

        CATALOGUE_V1["boost_capacite"].apply_to_project(service, "n1")

        updated = service.repo.get_node("n1")
        assert updated is not None
        assert updated.kpis.inventory.flow_rate == pytest.approx(65.0)
        assert updated.kpis.inventory.max_volume_m3 == pytest.approx(1200.0)

    def test_boost_capacite_ne_touche_que_le_kpi_renseigne(self, service):
        project = Project(id="p1", name="Projet", owner_node_id="n1")
        node = SupplyNode(id="n1", name="Atelier", project_id="p1")
        node.kpis.inventory.flow_rate = 50.0  # max_volume_m3 non renseigné
        service.create_project(project, [node], [])

        CATALOGUE_V1["boost_capacite"].apply_to_project(service, "n1")

        updated = service.repo.get_node("n1")
        assert updated is not None
        assert updated.kpis.inventory.flow_rate == pytest.approx(65.0)
        assert updated.kpis.inventory.max_volume_m3 is None

    def test_boost_capacite_no_op_sans_kpi_capacite(self, service):
        project = Project(id="p1", name="Projet", owner_node_id="n1")
        node = SupplyNode(id="n1", name="Atelier", project_id="p1")
        service.create_project(project, [node], [])

        CATALOGUE_V1["boost_capacite"].apply_to_project(service, "n1")  # ne lève pas

    def test_boost_capacite_keyerror_si_noeud_inconnu(self, service):
        with pytest.raises(KeyError):
            CATALOGUE_V1["boost_capacite"].apply_to_project(service, "fantome")

    def test_revue_declaration_est_un_no_op_meme_sur_noeud_inconnu(self, service):
        assert CATALOGUE_V1["revue_declaration"].apply_to_project(service, "fantome") is None

    def test_ne_rien_faire_est_un_no_op_meme_sur_noeud_inconnu(self, service):
        assert CATALOGUE_V1["ne_rien_faire"].apply_to_project(service, "fantome") is None


# --- contexte_pour ---------------------------------------------------------------------


class TestContextePour:
    def test_construit_le_contexte_depuis_le_service(self, service):
        _client, _backup_arc = _toy_project(service)
        service.registry.save_milestone(
            Milestone(id="m1", node_id="client", name="Proto", start_ts=0.0, deadline_ts=500.0)
        )

        ctx = contexte_pour(service, "client")

        assert ctx.node.id == "client"
        assert {a.source_id for a in ctx.arcs_entrants} == {"fournisseur_nominal"}
        assert {a.source_id for a in ctx.arcs_backup} == {"fournisseur_secours"}
        assert ctx.urgency is ctx.node.urgency
        assert [m.id for m in ctx.milestones] == ["m1"]

    def test_keyerror_si_noeud_inconnu(self, service):
        with pytest.raises(KeyError):
            contexte_pour(service, "fantome")


# --- Équivalence sim/réel ----------------------------------------------------------------


class TestEquivalenceSimReel:
    def test_expedition_express_meme_variation_relative(self, service):
        """expedition_express : même facteur -30 % côté KPI réel et côté rollout simulé."""
        service.seed_demo(n_ranks=2, seed=7)
        node = next(n for n in service.repo.nodes() if n.kpis.time.lead_time_h is not None)
        old_lead = node.kpis.time.lead_time_h
        assert old_lead is not None

        CATALOGUE_V1["expedition_express"].apply_to_project(service, node.id)
        updated = service.repo.get_node(node.id)
        assert updated is not None
        new_lead = updated.kpis.time.lead_time_h
        assert new_lead is not None
        real_relative_change = (new_lead - old_lead) / old_lead

        state: RolloutState = {
            "ur_local": np.array([old_lead]),
            "hazard": np.array([0.0]),
            "deadlines_h": {},
            "arc_beta": {},
        }
        result = CATALOGUE_V1["expedition_express"].apply_to_rollout(state)
        sim_relative_change = (result["ur_local"][0] - state["ur_local"][0]) / state["ur_local"][0]

        assert real_relative_change == pytest.approx(sim_relative_change)
        assert real_relative_change == pytest.approx(-0.3)

    def test_promouvoir_arc_secours_meme_arc_active_des_deux_cotes(self, service):
        """« Même esprit » : arc nominal côté réel, arc actif (même beta) côté simulé."""
        client, backup_arc = _toy_project(service)

        CATALOGUE_V1["promouvoir_arc_secours"].apply_to_project(service, client.id)

        promoted = service.repo.get_arc(backup_arc.source_id, backup_arc.target_id)
        assert promoted is not None
        assert promoted.kind_arc == ArcKind.NOMINAL
        registre_arc = service.registry.get_arc(backup_arc.source_id, backup_arc.target_id)
        assert registre_arc is not None
        assert registre_arc.kind_arc == ArcKind.NOMINAL

        state: RolloutState = {
            "ur_local": np.array([0.0]),
            "hazard": np.array([0.0]),
            "deadlines_h": {},
            "arc_beta": {f"{backup_arc.id}:backup": backup_arc.beta},
        }
        result = CATALOGUE_V1["promouvoir_arc_secours"].apply_to_rollout(state)

        assert result["arc_beta"] == {backup_arc.id: backup_arc.beta}
