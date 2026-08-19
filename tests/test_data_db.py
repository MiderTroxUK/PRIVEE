"""Tests de la couche de persistance SQLite (supplyscore.data.db)."""

from __future__ import annotations

import pytest

from supplyscore.data.db import (
    ClientDatabase,
    RegistryDatabase,
    kpis_from_json,
    kpis_to_json,
)
from supplyscore.domain.models import (
    AHPAssessment,
    KPIBundle,
    NodeKind,
    Project,
    SupplyArc,
    SupplyNode,
    TaskStatus,
    UrgencyState,
)


def _full_kpis() -> KPIBundle:
    kpis = KPIBundle()
    kpis.network.product = "Steel coil"
    kpis.network.distance_km = 320.0
    kpis.network.demand = 42.0
    kpis.inventory.max_volume_m3 = 1000.0
    kpis.inventory.current_volume_m3 = 250.0
    kpis.inventory.max_weight_kg = 8000.0
    kpis.inventory.current_weight_kg = 1200.0
    kpis.inventory.flow_rate = 40.0
    kpis.time.lead_time_h = 96.0
    kpis.time.lead_time_std_h = 8.0
    kpis.time.deadline_h = 168.0
    kpis.time.speed_kmh = 65.0
    kpis.cost.nominal_op_cost = 10000.0
    kpis.cost.op_cost = 11000.0
    kpis.cost.product_cost = 55.5
    kpis.co2.op_emission_g_h = 1500.0
    kpis.co2.energy_mix_g_h = 300.0
    kpis.co2.co2_target_g_h = 1200.0
    kpis.co2.co2_max_g_h = 2500.0
    kpis.oee.availability = 0.9
    kpis.oee.performance = 0.85
    kpis.oee.quality = 0.95
    kpis.risk.failure_probability = 0.02
    kpis.risk.severity = 0.4
    kpis.risk.env_exposure = 0.1
    kpis.risk.political_risk = 0.05
    return kpis


# Serialisation KPIBundle


class TestKPISerialization:
    def test_round_trip_full(self):
        kpis = _full_kpis()
        rebuilt = kpis_from_json(kpis_to_json(kpis))
        assert rebuilt == kpis
        # Les proprietes calculees se recalculent (non serialisees).
        assert rebuilt.oee.oee == pytest.approx(0.9 * 0.85 * 0.95)
        assert rebuilt.co2.total_g_h == pytest.approx(1800.0)
        assert rebuilt.inventory.remaining_volume_m3 == pytest.approx(750.0)

    def test_round_trip_empty(self):
        rebuilt = kpis_from_json(kpis_to_json(KPIBundle()))
        assert rebuilt == KPIBundle()
        assert rebuilt.oee.oee is None

    def test_properties_not_serialized(self):
        payload = kpis_to_json(_full_kpis())
        assert '"oee": {' in payload  # le bloc existe...
        assert '"total_g_h"' not in payload
        assert '"remaining_volume_m3"' not in payload

    def test_from_json_tolerates_none(self):
        assert kpis_from_json(None) == KPIBundle()
        assert kpis_from_json("") == KPIBundle()


# RegistryDatabase


class TestRegistryDatabase:
    def test_project_round_trip(self, tmp_path):
        with RegistryDatabase(tmp_path) as db:
            project = Project(
                id="p1", name="Proj", owner_node_id="n0", description="desc", created_at=123.5
            )
            db.save_project(project)
            assert db.get_project("p1") == project
            assert db.list_projects() == [project]
            assert db.get_project("missing") is None

    def test_node_round_trip_full_and_empty_kpis(self, tmp_path):
        with RegistryDatabase(tmp_path) as db:
            full = SupplyNode(
                id="n1",
                name="Usine",
                label="Factory",
                rank=2,
                project_id="p1",
                location="Lyon",
                latitude=45.7,
                longitude=4.8,
                status=TaskStatus.ACTIVE,
                kpis=_full_kpis(),
            )
            empty = SupplyNode(id="n2", name="Vide", kpis=KPIBundle())
            db.save_node(full)
            db.save_node(empty)

            got_full = db.get_node("n1")
            got_empty = db.get_node("n2")
            for attr in (
                "id",
                "name",
                "label",
                "rank",
                "project_id",
                "location",
                "latitude",
                "longitude",
                "status",
                "kpis",
            ):
                assert getattr(got_full, attr) == getattr(full, attr)
            assert got_full.kind is NodeKind.NODE
            assert got_empty.kpis == KPIBundle()
            assert db.get_node("missing") is None

    def test_list_nodes_filter_by_project(self, tmp_path):
        with RegistryDatabase(tmp_path) as db:
            db.save_node(SupplyNode(id="a", name="A", project_id="p1"))
            db.save_node(SupplyNode(id="b", name="B", project_id="p2"))
            assert {n.id for n in db.list_nodes()} == {"a", "b"}
            assert [n.id for n in db.list_nodes(project_id="p1")] == ["a"]

    def test_save_node_upsert(self, tmp_path):
        with RegistryDatabase(tmp_path) as db:
            db.save_node(SupplyNode(id="a", name="Avant"))
            db.save_node(SupplyNode(id="a", name="Apres", rank=3))
            node = db.get_node("a")
            assert node.name == "Apres"
            assert node.rank == 3
            assert len(db.list_nodes()) == 1

    def test_arc_round_trip(self, tmp_path):
        with RegistryDatabase(tmp_path) as db:
            arc = SupplyArc(
                source_id="s",
                target_id="t",
                label="Ship",
                gamma=0.4,
                beta=0.7,
                delta=1.2,
                kpis=_full_kpis(),
            )
            db.save_arc(arc)
            assert db.get_arc("s", "t") == arc
            assert db.list_arcs() == [arc]
            assert db.get_arc("t", "s") is None
            db.delete_arc("s", "t")
            assert db.get_arc("s", "t") is None

    def test_delete_node_cascades_arcs(self, tmp_path):
        with RegistryDatabase(tmp_path) as db:
            for nid in ("a", "b", "c"):
                db.save_node(SupplyNode(id=nid, name=nid))
            db.save_arc(SupplyArc(source_id="a", target_id="b"))
            db.save_arc(SupplyArc(source_id="b", target_id="c"))
            db.save_arc(SupplyArc(source_id="a", target_id="c"))

            db.delete_node("b")

            assert db.get_node("b") is None
            remaining = {(a.source_id, a.target_id) for a in db.list_arcs()}
            assert remaining == {("a", "c")}

    def test_set_node_status(self, tmp_path):
        with RegistryDatabase(tmp_path) as db:
            db.save_node(SupplyNode(id="a", name="A"))
            db.set_node_status("a", TaskStatus.DONE)
            assert db.get_node("a").status is TaskStatus.DONE
            db.set_node_status("a", "abandoned")
            assert db.get_node("a").status is TaskStatus.ABANDONED

    def test_persists_across_reopen(self, tmp_path):
        with RegistryDatabase(tmp_path) as db:
            db.save_node(SupplyNode(id="a", name="A"))
        with RegistryDatabase(tmp_path) as db:
            assert db.get_node("a").name == "A"


# ClientDatabase


def _assessment(node_id="n1", ts=1000.0, ud=0.4) -> AHPAssessment:
    return AHPAssessment(
        node_id=node_id,
        project_id="p1",
        operator_id="op-7",
        comparisons={(0, 1): 3.0, (0, 2): 5.0, (1, 2): 2.0},
        criteria_scores=[4.0, 6.5, 2.0],
        weights=[0.6, 0.25, 0.15],
        consistency_ratio=0.03,
        is_consistent=True,
        ud=ud,
        notes="hebdo",
        timestamp=ts,
    )


class TestClientDatabase:
    def test_assessment_round_trip_tuple_keys(self, tmp_path):
        with ClientDatabase(tmp_path, "client-1") as db:
            original = _assessment()
            row_id = db.save_assessment(original)
            assert isinstance(row_id, int) and row_id >= 1

            got = db.latest_assessment("n1")
            assert got == original
            assert got.comparisons == {(0, 1): 3.0, (0, 2): 5.0, (1, 2): 2.0}
            assert all(isinstance(k, tuple) for k in got.comparisons)
            assert got.is_consistent is True

    def test_latest_and_list_assessments(self, tmp_path):
        with ClientDatabase(tmp_path, "client-1") as db:
            db.save_assessment(_assessment(ts=200.0, ud=0.2))
            db.save_assessment(_assessment(ts=100.0, ud=0.1))
            db.save_assessment(_assessment(ts=300.0, ud=0.3))

            assert db.latest_assessment("n1").ud == pytest.approx(0.3)
            history = db.list_assessments("n1")
            assert [a.timestamp for a in history] == [100.0, 200.0, 300.0]
            assert db.latest_assessment("autre") is None
            assert db.list_assessments("autre") == []

    def test_kpi_snapshot(self, tmp_path):
        with ClientDatabase(tmp_path, "client-1") as db:
            sid = db.save_kpi_snapshot("n1", _full_kpis(), timestamp=42.0)
            assert isinstance(sid, int) and sid >= 1

    def test_urgency_series_ordered_by_timestamp(self, tmp_path):
        with ClientDatabase(tmp_path, "client-1") as db:
            states = [
                UrgencyState(
                    ud_local=0.2,
                    ur_local=0.5,
                    ud=0.3,
                    ur=0.6,
                    adequation=70.0,
                    false_urgency=0.0,
                    hidden_risk=0.3,
                    timestamp=300.0,
                ),
                UrgencyState(
                    ud_local=0.8,
                    ur_local=0.1,
                    ud=0.7,
                    ur=0.2,
                    adequation=50.0,
                    false_urgency=0.5,
                    hidden_risk=0.0,
                    timestamp=100.0,
                ),
                UrgencyState(timestamp=200.0),  # tous champs None
            ]
            for s in states:
                db.save_urgency_state("n1", s)

            series = db.urgency_series("n1")
            assert [s.timestamp for s in series] == [100.0, 200.0, 300.0]
            assert series[0] == states[1]
            assert series[1] == states[2]
            assert series[2] == states[0]
            assert series[1].ud_local is None
            assert db.urgency_series("autre") == []

    def test_two_clients_two_distinct_sqlite_files(self, tmp_path):
        with (
            ClientDatabase(tmp_path, "client-A") as db_a,
            ClientDatabase(tmp_path, "client-B") as db_b,
        ):
            db_a.save_assessment(_assessment(node_id="nA"))
            assert db_a.db_path != db_b.db_path
            # L'evaluation du client A n'existe pas chez B (isolation).
            assert db_b.latest_assessment("nA") is None

        assert (tmp_path / "client-A.sqlite").exists()
        assert (tmp_path / "client-B.sqlite").exists()
        # Le registre est un troisieme fichier, distinct des bases clients.
        with RegistryDatabase(tmp_path):
            pass
        assert (tmp_path / "registry.sqlite").exists()
