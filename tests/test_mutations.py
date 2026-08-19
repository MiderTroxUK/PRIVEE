"""Tests du Lot 3.3 : MutationService, point de passage obligatoire des ecritures.

Couvre : diff reel des KPIs (seuls les champs changes sont ecrits), no-op
complet sur valeurs identiques, refus bloquant d'une valeur invalide (rien
n'est ecrit), effacement par None, completude du journal (propriete
hypothesis), jalons (fenetre temporelle, progress), arcs (creation, diff,
suppression), tags (diff sur l'ensemble), cahier des charges versionne,
corrections d'evaluations (replaces_id), concurrence (aucune entree perdue)
et synchronisation du graphe en memoire.
"""

from __future__ import annotations

import dataclasses
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from supplyscore.core.clock import FixedClock, iso_week
from supplyscore.data.audit import AuditEntry, AuditTrail
from supplyscore.data.db import ClientDatabase, RegistryDatabase
from supplyscore.domain.milestones import Milestone, MilestoneStatus
from supplyscore.domain.models import AHPAssessment, ArcKind, SupplyArc, SupplyNode
from supplyscore.graph.memory_repo import InMemoryGraphRepository
from supplyscore.services.mutations import MutationService

_NOW = 1_750_000_000.0  # 2025-06-15 ~ : instant fige de reference


# Helpers


def _build_env(tmp_path: Path, repo: InMemoryGraphRepository | None = None) -> SimpleNamespace:
    """Construit registre + fabrique de bases client + MutationService (FixedClock)."""
    registry = RegistryDatabase(tmp_path)
    clients: dict[str, ClientDatabase] = {}
    factory_lock = threading.Lock()

    def factory(node_id: str) -> ClientDatabase:
        with factory_lock:
            if node_id not in clients:
                clients[node_id] = ClientDatabase(tmp_path, node_id)
            return clients[node_id]

    clock = FixedClock(_NOW)
    service = MutationService(registry, factory, clock, repo=repo)
    return SimpleNamespace(
        registry=registry,
        clients=clients,
        factory=factory,
        clock=clock,
        service=service,
        repo=repo,
    )


def _close_env(env: SimpleNamespace) -> None:
    for db in env.clients.values():
        db.close()
    env.registry.close()


@pytest.fixture
def env(tmp_path):
    e = _build_env(tmp_path)
    yield e
    _close_env(e)


@pytest.fixture
def env_repo(tmp_path):
    e = _build_env(tmp_path, repo=InMemoryGraphRepository())
    yield e
    _close_env(e)


def _seed_node(registry: RegistryDatabase, node_id: str = "n1", **kwargs) -> SupplyNode:
    """Cree et persiste un noeud avec trois KPIs discriminables."""
    node = SupplyNode(id=node_id, name="Atelier", project_id="p1", **kwargs)
    node.kpis.time.lead_time_h = 10.0
    node.kpis.network.demand = 100.0
    node.kpis.risk.severity = 0.2
    registry.save_node(node)
    return node


def _seed_milestone(registry: RegistryDatabase, milestone_id: str = "m1") -> Milestone:
    milestone = Milestone(
        id=milestone_id, node_id="n1", name="Proto", start_ts=1000.0, deadline_ts=2000.0
    )
    registry.save_milestone(milestone)
    return milestone


def _assessment(node_id: str = "n1", ts: float = 1000.0, ud: float = 0.4) -> AHPAssessment:
    return AHPAssessment(
        node_id=node_id,
        project_id="p1",
        operator_id="op-7",
        comparisons={(0, 1): 3.0},
        criteria_scores=[4.0, 6.5],
        weights=[0.6, 0.4],
        consistency_ratio=0.03,
        is_consistent=True,
        ud=ud,
        timestamp=ts,
    )


def _count(db, sql: str) -> int:
    return db.conn.execute(sql).fetchone()[0]


def _client_trail(env: SimpleNamespace, node_id: str) -> AuditTrail:
    db = env.factory(node_id)
    return AuditTrail(db.conn, env.clock, lock=db.lock)


# update_kpis


class TestUpdateKpis:
    def test_diff_reel_seuls_les_champs_changes_sont_ecrits(self, env):
        _seed_node(env.registry)
        entries = env.service.update_kpis(
            "n1",
            {
                "time.lead_time_h": 10.0,  # identique -> ignore
                "network.demand": 150.0,
                "risk.severity": 0.5,
            },
            source="edit",
            operator_id="op-1",
        )

        # 2 entrees (sur 3 demandees), dans l'ordre des changes.
        assert [e.field for e in entries] == ["network.demand", "risk.severity"]
        assert all(isinstance(e, AuditEntry) for e in entries)
        assert all(e.entity_type == "node_kpis" and e.entity_id == "n1" for e in entries)
        assert entries[0].old_value == 100.0 and entries[0].new_value == 150.0
        assert entries[1].old_value == 0.2 and entries[1].new_value == 0.5
        assert entries[0].source == "edit" and entries[0].operator_id == "op-1"
        assert entries[0].iso_week == iso_week(_NOW)
        assert entries[0].timestamp == _NOW

        # Noeud persiste dans le registre, champ identique inchange.
        node = env.registry.get_node("n1")
        assert node.kpis.network.demand == 150.0
        assert node.kpis.risk.severity == 0.5
        assert node.kpis.time.lead_time_h == 10.0

        # UN snapshot (etat APRES mutation) et 2 lignes d'audit dans la base CLIENT.
        client = env.clients["n1"]
        assert _count(client, "SELECT COUNT(*) FROM kpi_snapshots") == 1
        snap = client.kpis_at("n1", _NOW)
        assert snap is not None and snap.network.demand == 150.0
        assert _count(client, "SELECT COUNT(*) FROM audit_log") == 2
        # ... et RIEN dans le journal du registre.
        assert _count(env.registry, "SELECT COUNT(*) FROM audit_log") == 0

    def test_valeurs_identiques_partout_no_op_complet(self, env):
        _seed_node(env.registry)
        client = env.factory("n1")
        entries = env.service.update_kpis(
            "n1", {"time.lead_time_h": 10.0, "network.demand": 100.0}, source="edit"
        )
        assert entries == []
        assert _count(client, "SELECT COUNT(*) FROM kpi_snapshots") == 0
        assert _count(client, "SELECT COUNT(*) FROM audit_log") == 0

    def test_valeur_invalide_rien_nest_ecrit(self, env):
        _seed_node(env.registry)
        client = env.factory("n1")
        with pytest.raises(ValueError, match=r"risk\.failure_probability"):
            env.service.update_kpis(
                "n1",
                {"risk.failure_probability": 1.7, "network.demand": 150.0},
                source="edit",
            )
        # RIEN n'est ecrit : ni noeud, ni snapshot, ni audit.
        node = env.registry.get_node("n1")
        assert node.kpis.network.demand == 100.0
        assert node.kpis.risk.failure_probability is None
        assert _count(client, "SELECT COUNT(*) FROM kpi_snapshots") == 0
        assert _count(client, "SELECT COUNT(*) FROM audit_log") == 0

    def test_toutes_les_erreurs_sont_listees(self, env):
        _seed_node(env.registry)
        with pytest.raises(ValueError) as exc:
            env.service.update_kpis(
                "n1",
                {"risk.failure_probability": 1.7, "oee.availability": -0.5},
                source="edit",
            )
        message = str(exc.value)
        assert "risk.failure_probability" in message
        assert "oee.availability" in message

    def test_kpi_inconnu_refuse(self, env):
        _seed_node(env.registry)
        with pytest.raises(ValueError, match="KPI inconnu"):
            env.service.update_kpis("n1", {"foo.bar": 1.0}, source="edit")

    def test_none_efface_un_champ(self, env):
        _seed_node(env.registry)
        entries = env.service.update_kpis("n1", {"network.demand": None}, source="edit")
        assert len(entries) == 1
        assert entries[0].old_value == 100.0 and entries[0].new_value is None
        assert env.registry.get_node("n1").kpis.network.demand is None
        assert _count(env.clients["n1"], "SELECT COUNT(*) FROM kpi_snapshots") == 1

    def test_noeud_inconnu(self, env):
        with pytest.raises(KeyError):
            env.service.update_kpis("fantome", {"network.demand": 1.0}, source="edit")


# Propriete hypothesis : completude du journal

_KPI_PATHS = ("time.lead_time_h", "network.demand", "risk.severity", "oee.availability")


class TestJournalComplet:
    @settings(deadline=None, max_examples=25)
    @given(
        seq=st.lists(
            st.tuples(
                st.sampled_from(_KPI_PATHS),
                st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
            ),
            min_size=1,
            max_size=12,
        )
    )
    def test_dernier_new_value_du_journal_egale_valeur_courante(self, seq):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            registry = RegistryDatabase(tmp_path)
            client = ClientDatabase(tmp_path, "n1")
            try:
                clock = FixedClock(_NOW)
                service = MutationService(registry, lambda _nid: client, clock)
                registry.save_node(SupplyNode(id="n1", name="N", project_id="p1"))

                for path, value in seq:
                    service.update_kpis("n1", {path: value}, source="edit")

                node = registry.get_node("n1")
                trail = AuditTrail(client.conn, clock, lock=client.lock)
                for path in _KPI_PATHS:
                    block, field = path.split(".", 1)
                    current = getattr(getattr(node.kpis, block), field)
                    journal = trail.history("node_kpis", "n1", field=path, limit=1000)
                    if journal:
                        # journal trie du plus recent au plus ancien.
                        assert journal[0].new_value == current
                    else:
                        assert current is None  # jamais ecrit : valeur initiale
            finally:
                client.close()
                registry.close()


# update_node_fields


class TestUpdateNodeFields:
    def test_diff_et_audit_dans_le_registre(self, env):
        _seed_node(env.registry)
        entries = env.service.update_node_fields(
            "n1", {"name": "Atelier", "location": "Lyon"}, source="edit", operator_id="op-2"
        )
        # name identique -> seul location est ecrit.
        assert [e.field for e in entries] == ["location"]
        assert entries[0].entity_type == "node" and entries[0].entity_id == "n1"
        assert entries[0].old_value is None and entries[0].new_value == "Lyon"
        assert env.registry.get_node("n1").location == "Lyon"
        assert _count(env.registry, "SELECT COUNT(*) FROM audit_log") == 1

    def test_aucun_changement(self, env):
        _seed_node(env.registry)
        assert env.service.update_node_fields("n1", {"name": "Atelier"}, source="edit") == []
        assert _count(env.registry, "SELECT COUNT(*) FROM audit_log") == 0

    def test_champ_hors_liste_blanche(self, env):
        _seed_node(env.registry)
        with pytest.raises(ValueError, match="liste blanche"):
            env.service.update_node_fields("n1", {"rank": 3}, source="edit")

    def test_noeud_inconnu(self, env):
        with pytest.raises(KeyError):
            env.service.update_node_fields("fantome", {"name": "X"}, source="edit")


# upsert_arc / delete_arc


class TestUpsertArc:
    def test_creation_auditee(self, env):
        _seed_node(env.registry, "n1")
        _seed_node(env.registry, "n2")
        arc = SupplyArc(source_id="n2", target_id="n1", gamma=0.5, beta=0.5)
        entries = env.service.upsert_arc(arc, source="edit", operator_id="op-3")
        assert len(entries) == 1
        assert entries[0].entity_type == "arc" and entries[0].entity_id == "n2->n1"
        assert entries[0].field == ""
        assert entries[0].old_value is None and entries[0].new_value == "created"
        assert env.registry.get_arc("n2", "n1") is not None

    def test_modification_gamma_diff_par_champ(self, env):
        _seed_node(env.registry, "n1")
        _seed_node(env.registry, "n2")
        arc = SupplyArc(source_id="n2", target_id="n1", gamma=0.5, beta=0.5)
        env.service.upsert_arc(arc, source="edit")

        entries = env.service.upsert_arc(
            dataclasses.replace(arc, gamma=0.8), source="edit", operator_id="op-3"
        )
        assert [e.field for e in entries] == ["gamma"]
        assert entries[0].old_value == 0.5 and entries[0].new_value == 0.8
        stored = env.registry.get_arc("n2", "n1")
        assert stored is not None and stored.gamma == 0.8

    def test_aucun_changement(self, env):
        _seed_node(env.registry, "n1")
        _seed_node(env.registry, "n2")
        arc = SupplyArc(source_id="n2", target_id="n1")
        env.service.upsert_arc(arc, source="edit")
        before = _count(env.registry, "SELECT COUNT(*) FROM audit_log")
        assert env.service.upsert_arc(dataclasses.replace(arc), source="edit") == []
        assert _count(env.registry, "SELECT COUNT(*) FROM audit_log") == before

    def test_changement_de_nature_audite(self, env):
        _seed_node(env.registry, "n1")
        _seed_node(env.registry, "n2")
        arc = SupplyArc(source_id="n2", target_id="n1")
        env.service.upsert_arc(arc, source="edit")
        entries = env.service.upsert_arc(
            dataclasses.replace(arc, kind_arc=ArcKind.BACKUP), source="edit"
        )
        assert [e.field for e in entries] == ["kind_arc"]
        assert entries[0].old_value == "nominal" and entries[0].new_value == "backup"

    @pytest.mark.parametrize(
        ("kwargs", "borne"),
        [
            ({"gamma": 1.5}, "gamma hors"),
            ({"beta": -0.1}, "beta hors"),
            ({"delta": 2.5}, "delta hors"),
        ],
    )
    def test_bornes_refusees(self, env, kwargs, borne):
        _seed_node(env.registry, "n1")
        _seed_node(env.registry, "n2")
        arc = SupplyArc(source_id="n2", target_id="n1", **kwargs)
        with pytest.raises(ValueError, match=borne):
            env.service.upsert_arc(arc, source="edit")
        assert env.registry.get_arc("n2", "n1") is None
        assert _count(env.registry, "SELECT COUNT(*) FROM audit_log") == 0


class TestDeleteArc:
    def test_suppression_auditee(self, env):
        _seed_node(env.registry, "n1")
        _seed_node(env.registry, "n2")
        env.service.upsert_arc(SupplyArc(source_id="n2", target_id="n1"), source="edit")

        entries = env.service.delete_arc("n2", "n1", source="edit", operator_id="op-4")
        assert len(entries) == 1
        assert entries[0].entity_type == "arc" and entries[0].entity_id == "n2->n1"
        assert entries[0].field == ""
        assert entries[0].old_value == "exists" and entries[0].new_value == "deleted"
        assert env.registry.get_arc("n2", "n1") is None

    def test_arc_inconnu(self, env):
        with pytest.raises(KeyError):
            env.service.delete_arc("n2", "n1", source="edit")


# set_node_tags


class TestSetNodeTags:
    def test_meme_ensemble_aucune_ecriture(self, env):
        _seed_node(env.registry, tags=["t1", "t2"])
        assert env.service.set_node_tags("n1", ["t2", "t1"], source="edit") == []
        assert _count(env.registry, "SELECT COUNT(*) FROM audit_log") == 0

    def test_diff_exact_audite(self, env):
        _seed_node(env.registry, tags=["t1", "t2"])
        entries = env.service.set_node_tags("n1", ["t2", "t3"], source="edit", operator_id="op-5")
        assert len(entries) == 1
        assert entries[0].entity_type == "node" and entries[0].field == "tags"
        assert entries[0].old_value == ["t1", "t2"]
        assert entries[0].new_value == ["t2", "t3"]
        assert env.registry.get_node("n1").tags == ["t2", "t3"]

    def test_noeud_inconnu(self, env):
        with pytest.raises(KeyError):
            env.service.set_node_tags("fantome", ["t1"], source="edit")


# update_milestone


class TestUpdateMilestone:
    def test_deadline_avant_start_refusee(self, env):
        _seed_milestone(env.registry)
        with pytest.raises(ValueError, match="deadline_ts"):
            env.service.update_milestone("m1", {"deadline_ts": 500.0}, source="edit")
        # Rien n'est ecrit.
        milestone = env.registry.get_milestone("m1")
        assert milestone is not None and milestone.deadline_ts == 2000.0
        assert _count(env.registry, "SELECT COUNT(*) FROM audit_log") == 0

    def test_progress_audite(self, env):
        _seed_milestone(env.registry)
        entries = env.service.update_milestone(
            "m1", {"progress": 0.5}, source="edit", operator_id="op-6"
        )
        assert [e.field for e in entries] == ["progress"]
        assert entries[0].entity_type == "milestone" and entries[0].entity_id == "m1"
        assert entries[0].old_value == 0.0 and entries[0].new_value == 0.5
        milestone = env.registry.get_milestone("m1")
        assert milestone is not None and milestone.progress == 0.5

    def test_progress_hors_bornes(self, env):
        _seed_milestone(env.registry)
        with pytest.raises(ValueError, match="progress hors"):
            env.service.update_milestone("m1", {"progress": 1.5}, source="edit")

    def test_statut_normalise_et_audite(self, env):
        _seed_milestone(env.registry)
        entries = env.service.update_milestone("m1", {"status": "done"}, source="edit")
        assert [e.field for e in entries] == ["status"]
        assert entries[0].old_value == "active" and entries[0].new_value == "done"
        milestone = env.registry.get_milestone("m1")
        assert milestone is not None and milestone.status is MilestoneStatus.DONE

    def test_champ_hors_liste_blanche(self, env):
        _seed_milestone(env.registry)
        with pytest.raises(ValueError, match="liste blanche"):
            env.service.update_milestone("m1", {"node_id": "n9"}, source="edit")

    def test_jalon_inconnu(self, env):
        with pytest.raises(KeyError):
            env.service.update_milestone("fantome", {"progress": 0.5}, source="edit")


# save_spec_sheet


class TestSaveSpecSheet:
    def test_versions_successives_auditees(self, env):
        _seed_node(env.registry)
        assert env.service.save_spec_sheet("n1", '{"a": 1}', source="onboarding") == 1
        assert env.service.save_spec_sheet("n1", '{"a": 2}', source="edit", operator_id="op") == 2

        client = env.clients["n1"]
        assert client.latest_spec_sheet("n1") == (2, '{"a": 2}')

        journal = _client_trail(env, "n1").history("spec_sheet", "n1", field="version")
        assert len(journal) == 2  # du plus recent au plus ancien
        assert journal[0].old_value == 1 and journal[0].new_value == 2
        assert journal[1].old_value is None and journal[1].new_value == 1


# replace_assessment


class TestReplaceAssessment:
    def test_correction_auditee_originale_conservee(self, env):
        _seed_node(env.registry)
        client = env.factory("n1")
        old_id = client.save_assessment(_assessment(ts=100.0, ud=0.1))

        new_id = env.service.replace_assessment(
            "n1", old_id, _assessment(ts=150.0, ud=0.2), operator_id="op-8"
        )
        assert new_id != old_id

        # latest_assessment retourne la correction ; l'originale reste listee.
        latest = client.latest_assessment("n1")
        assert latest is not None and latest.ud == pytest.approx(0.2)
        full = client.list_assessments("n1")
        assert [a.ud for a in full] == [pytest.approx(0.1), pytest.approx(0.2)]

        journal = _client_trail(env, "n1").history("assessment", "n1", field="replaces")
        assert len(journal) == 1
        assert journal[0].old_value == old_id and journal[0].new_value == new_id
        assert journal[0].source == "edit" and journal[0].operator_id == "op-8"


# Concurrence


class TestConcurrence:
    def test_2_threads_x_50_updates_aucune_entree_perdue(self, env):
        for node_id in ("n1", "n2"):
            _seed_node(env.registry, node_id)
            env.factory(node_id)  # pre-cree la base client (hors course)

        failures: list[BaseException] = []

        def worker(node_id: str) -> None:
            try:
                for i in range(1, 51):  # 50 valeurs toutes differentes -> 50 diffs
                    env.service.update_kpis(node_id, {"time.lead_time_h": float(i)}, source="edit")
            except BaseException as exc:  # remontee au thread principal
                failures.append(exc)

        threads = [threading.Thread(target=worker, args=(nid,)) for nid in ("n1", "n2")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert failures == []
        total = 0
        for node_id in ("n1", "n2"):
            count = _count(
                env.clients[node_id],
                "SELECT COUNT(*) FROM audit_log WHERE entity_type = 'node_kpis'",
            )
            assert count == 50
            total += count
        assert total == 100
        # Valeur finale coherente avec le journal.
        for node_id in ("n1", "n2"):
            node = env.registry.get_node(node_id)
            assert node.kpis.time.lead_time_h == 50.0


# Synchronisation du graphe en memoire


class TestRepoSync:
    def test_noeud_mis_a_jour_en_memoire(self, env_repo):
        _seed_node(env_repo.registry)
        env_repo.repo.add_node(env_repo.registry.get_node("n1"))

        env_repo.service.update_kpis("n1", {"network.demand": 150.0}, source="edit")
        assert env_repo.repo.get_node("n1").kpis.network.demand == 150.0

        env_repo.service.update_node_fields("n1", {"name": "Nouveau"}, source="edit")
        assert env_repo.repo.get_node("n1").name == "Nouveau"

        env_repo.service.set_node_tags("n1", ["t9"], source="edit")
        assert env_repo.repo.get_node("n1").tags == ["t9"]

    def test_arc_synchronise_en_memoire(self, env_repo):
        _seed_node(env_repo.registry, "n1")
        _seed_node(env_repo.registry, "n2")
        env_repo.repo.add_node(env_repo.registry.get_node("n1"))
        env_repo.repo.add_node(env_repo.registry.get_node("n2"))

        arc = SupplyArc(source_id="n2", target_id="n1", gamma=0.5)
        env_repo.service.upsert_arc(arc, source="edit")
        assert env_repo.repo.get_arc("n2", "n1") is not None

        env_repo.service.upsert_arc(dataclasses.replace(arc, gamma=0.8), source="edit")
        assert env_repo.repo.get_arc("n2", "n1").gamma == 0.8

        env_repo.service.delete_arc("n2", "n1", source="edit")
        assert env_repo.repo.get_arc("n2", "n1") is None

    def test_noeud_absent_du_repo_ignore(self, env_repo):
        _seed_node(env_repo.registry)  # jamais ajoute au repo
        entries = env_repo.service.update_kpis("n1", {"network.demand": 150.0}, source="edit")
        assert len(entries) == 1  # l'ecriture en base a bien eu lieu
        assert env_repo.repo.get_node("n1") is None
