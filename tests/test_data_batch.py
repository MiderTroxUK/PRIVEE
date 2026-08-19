"""Tests des ecritures par lots SQLite (Lot 14.2 - faiblesses #14/#15).

Couvre : ``RegistryDatabase.save_urgencies`` et
``ClientDatabase.save_urgency_states`` (equivalence champ a champ avec les
chemins unitaires, transaction unique), la persistance groupee de
``evaluate_all(persist=True)`` (lignes identiques a l'ancien chemin), le
``PRAGMA synchronous=NORMAL``, les index de la migration client v6 et une
mesure de performance indicative NON bloquante.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from supplyscore.core.clock import FixedClock, iso_week
from supplyscore.data.db import ClientDatabase, RegistryDatabase
from supplyscore.domain.models import Project, SupplyArc, SupplyNode, UrgencyState
from supplyscore.services import SupplyScoreService

_URGENCY_FIELDS = (
    "ud_local",
    "ur_local",
    "ud",
    "ur",
    "adequation",
    "false_urgency",
    "hidden_risk",
    "timestamp",
)

#: instant fige de reference (mi-2023) - semaine ISO stable pour les tests.
_T0 = 1_700_000_000.0


def _make_states(n: int, base_ts: float = _T0) -> dict[str, UrgencyState]:
    """Construit ``n`` etats d'urgence distincts, a timestamps tous differents.

    Les timestamps sont espaces de 25 h : le lot traverse plusieurs semaines
    ISO, ce qui rend le calcul d'``iso_week`` reellement discriminant.
    """
    return {
        f"n{i:04d}": UrgencyState(
            ud_local=i / max(n, 1),
            ur_local=(n - i) / max(n, 1),
            ud=0.5 * i / max(n, 1),
            ur=0.25,
            adequation=float(i % 100),
            false_urgency=0.01 * (i % 7),
            hidden_risk=0.02 * (i % 5),
            timestamp=base_ts + i * 25 * 3600.0,
        )
        for i in range(n)
    }


def _node_urgency_rows(db_path: Path) -> list[tuple]:
    """Lignes de node_urgency, ordonnees par node_id (colonnes explicites)."""
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            """
            SELECT node_id, ud_local, ur_local, ud, ur, adequation,
                   false_urgency, hidden_risk, timestamp
            FROM node_urgency ORDER BY node_id
            """
        ).fetchall()
    finally:
        conn.close()


def _urgency_history_rows(db_path: Path) -> list[tuple]:
    """Lignes d'urgency_history, dans l'ordre d'insertion (colonnes explicites)."""
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            """
            SELECT node_id, ud_local, ur_local, ud, ur, adequation,
                   false_urgency, hidden_risk, timestamp, iso_week
            FROM urgency_history ORDER BY id
            """
        ).fetchall()
    finally:
        conn.close()


class _TransactionSpy:
    """Compte les BEGIN/COMMIT vus par le trace callback d'une connexion."""

    def __init__(self) -> None:
        self.begins = 0
        self.commits = 0

    def __call__(self, statement: str) -> None:
        head = statement.lstrip().upper()
        if head.startswith("BEGIN"):
            self.begins += 1
        elif head.startswith("COMMIT"):
            self.commits += 1


# RegistryDatabase.save_urgencies


class TestSaveUrgencies:
    def test_lot_equivaut_au_chemin_unitaire(self, tmp_path):
        states = _make_states(200)

        with RegistryDatabase(tmp_path / "unitaire") as db_unit:
            for node_id, state in states.items():
                db_unit.save_urgency(node_id, state)
        with RegistryDatabase(tmp_path / "lot") as db_batch:
            db_batch.save_urgencies(states)

        rows_unit = _node_urgency_rows(tmp_path / "unitaire" / "registry.sqlite")
        rows_batch = _node_urgency_rows(tmp_path / "lot" / "registry.sqlite")
        assert len(rows_batch) == 200
        assert rows_batch == rows_unit  # champ a champ, memes lignes

    def test_lot_en_une_seule_transaction(self, tmp_path):
        states = _make_states(200)
        with RegistryDatabase(tmp_path) as db:
            spy = _TransactionSpy()
            db.conn.set_trace_callback(spy)
            db.save_urgencies(states)
            db.conn.set_trace_callback(None)

        assert spy.begins == 1
        assert spy.commits == 1

    def test_lot_est_un_upsert(self, tmp_path):
        states = _make_states(10)
        with RegistryDatabase(tmp_path) as db:
            db.save_urgencies(states)
            updated = {
                node_id: UrgencyState(ud=0.9, ur=0.1, timestamp=_T0 + 1.0) for node_id in states
            }
            db.save_urgencies(updated)  # second lot : mise a jour, pas doublon
            assert db.get_node("n0001") is None  # garde-fou : pas de noeud cree

        rows = _node_urgency_rows(tmp_path / "registry.sqlite")
        assert len(rows) == 10
        assert all(row[3] == 0.9 and row[4] == 0.1 for row in rows)

    def test_lot_vide_est_un_noop(self, tmp_path):
        with RegistryDatabase(tmp_path) as db:
            db.save_urgencies({})
        assert _node_urgency_rows(tmp_path / "registry.sqlite") == []


# ClientDatabase.save_urgency_states


class TestSaveUrgencyStates:
    def test_lot_equivaut_au_chemin_unitaire_iso_week_comprise(self, tmp_path):
        states = _make_states(200)
        rows_in = list(states.items())

        with ClientDatabase(tmp_path, "unitaire") as db_unit:
            for node_id, state in rows_in:
                db_unit.save_urgency_state(node_id, state)
        with ClientDatabase(tmp_path, "lot") as db_batch:
            db_batch.save_urgency_states(rows_in)

        rows_unit = _urgency_history_rows(tmp_path / "unitaire.sqlite")
        rows_batch = _urgency_history_rows(tmp_path / "lot.sqlite")
        assert len(rows_batch) == 200
        assert rows_batch == rows_unit  # champ a champ, ordre d'insertion compris
        # iso_week calculee comme dans save_urgency_state : depuis CHAQUE timestamp.
        for row in rows_batch:
            assert row[9] == iso_week(row[8])
        assert len({row[9] for row in rows_batch}) > 1  # le lot traverse des semaines

    def test_lot_en_une_seule_transaction(self, tmp_path):
        with ClientDatabase(tmp_path, "client") as db:
            spy = _TransactionSpy()
            db.conn.set_trace_callback(spy)
            db.save_urgency_states(list(_make_states(50).items()))
            db.conn.set_trace_callback(None)

        assert spy.begins == 1
        assert spy.commits == 1

    def test_serie_relue_identique(self, tmp_path):
        states = _make_states(5)
        with ClientDatabase(tmp_path, "client") as db:
            db.save_urgency_states([("n1", state) for state in states.values()])
            serie = db.urgency_series("n1")

        assert len(serie) == 5
        for relu, attendu in zip(serie, states.values(), strict=True):
            for champ in _URGENCY_FIELDS:
                assert getattr(relu, champ) == getattr(attendu, champ)


# evaluate_all(persist=True) : memes lignes que l'ancien chemin


def test_evaluate_all_persist_produit_les_memes_lignes(tmp_path):
    """Reference construite a la main sur un petit graphe, horloge figee.

    L'ancien chemin ecrivait, noeud par noeud, ``save_urgency(node_id, state)``
    dans le registre et ``save_urgency_state(node_id, state)`` dans la base du
    client. Les lignes attendues sont donc derivables directement des etats
    retournes : ce test les reconstruit champ a champ et les compare aux
    lignes reellement persistees par le chemin par lots.
    """
    store = tmp_path / "store"
    clock = FixedClock(_T0)
    with SupplyScoreService(db_dir=store, clock=clock) as service:
        project = Project(
            id="p1", name="Test", owner_node_id="n0", created_at=_T0 - 7 * 24 * 3600.0
        )
        nodes = [
            SupplyNode(id="n0", name="Client", rank=0, project_id="p1"),
            SupplyNode(id="n1", name="Usine", rank=1, project_id="p1"),
            SupplyNode(id="n2", name="Atelier", rank=1, project_id="p1"),
        ]
        arcs = [
            SupplyArc(source_id="n1", target_id="n0", gamma=0.6, beta=0.7),
            SupplyArc(source_id="n2", target_id="n0", gamma=0.4, beta=0.5),
        ]
        service.create_project(project, nodes, arcs)
        for node, ud_local in zip(nodes, (0.8, 0.3, 0.6), strict=True):
            node.urgency.ud_local = ud_local
            service.repo.update_node(node)

        states = service.evaluate_all(persist=True)

        # Reference "ancien chemin" : une ligne node_urgency et une ligne urgency_history par noeud, champs copies de l'etat, iso_week derivee.
        expected_registry = sorted(
            (
                node_id,
                s.ud_local,
                s.ur_local,
                s.ud,
                s.ur,
                s.adequation,
                s.false_urgency,
                s.hidden_risk,
                s.timestamp,
            )
            for node_id, s in states.items()
        )
        assert {nid for nid, *_ in expected_registry} == {"n0", "n1", "n2"}
        assert all(row[-1] == _T0 for row in expected_registry)  # horloge figee

    rows_registry = [tuple(r) for r in _node_urgency_rows(store / "registry.sqlite")]
    assert rows_registry == [tuple(row) for row in expected_registry]

    for node_id, s in states.items():
        rows = _urgency_history_rows(store / f"{node_id}.sqlite")
        assert rows == [
            (
                node_id,
                s.ud_local,
                s.ur_local,
                s.ud,
                s.ur,
                s.adequation,
                s.false_urgency,
                s.hidden_risk,
                s.timestamp,
                iso_week(s.timestamp),
            )
        ]


# PRAGMA synchronous=NORMAL


def test_synchronous_normal_sur_chaque_base(tmp_path):
    with RegistryDatabase(tmp_path) as registry:
        assert registry.conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL
        assert registry.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    with ClientDatabase(tmp_path, "client") as client:
        assert client.conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL
        assert client.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


# Index de la migration client v6


def _index_names(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
        return {row[0] for row in rows}
    finally:
        conn.close()


def test_client_v6_pose_les_index_temporels_manquants(tmp_path):
    with ClientDatabase(tmp_path, "client") as db:
        assert db.schema_version == 7  # v7 (U16) est la version courante

    index = _index_names(tmp_path / "client.sqlite")
    assert "idx_urgency_node_ts" in index  # nouveau (v6)
    assert "idx_assessments_node_ts" in index  # nouveau (v6)
    assert "idx_kpi_snap_node_ts" in index  # existait deja (v3) - pas de doublon
    assert "idx_snapshots_node_ts" not in index


def test_registre_reste_en_v4_index_audit_deja_presents(tmp_path):
    with RegistryDatabase(tmp_path) as db:
        assert db.schema_version == 5  # aucun index registre ne manquait (v5 = scenarios)

    index = _index_names(tmp_path / "registry.sqlite")
    assert {"idx_audit_entity", "idx_audit_week"} <= index


# Performance indicative (NON bloquante)


def test_perf_indicative_lot_plus_rapide_que_unitaire(tmp_path):
    """500 etats : le lot vise au moins 3x plus vite que 500 appels unitaires.

    Mesure indicative NON bloquante : sur une machine lente ou chargee le
    ratio peut se degrader - le test est alors SKIPPE plutot qu'echoue.
    L'assertion souple ne reclame que ratio < 0.8 (le gain 3x est l'objectif
    nominal, observe en conditions normales).
    """
    states = _make_states(500)

    with RegistryDatabase(tmp_path / "unitaire") as db_unit:
        debut = time.perf_counter()
        for node_id, state in states.items():
            db_unit.save_urgency(node_id, state)
        duree_unitaire = time.perf_counter() - debut

    with RegistryDatabase(tmp_path / "lot") as db_batch:
        debut = time.perf_counter()
        db_batch.save_urgencies(states)
        duree_lot = time.perf_counter() - debut

    assert _node_urgency_rows(tmp_path / "lot" / "registry.sqlite") == _node_urgency_rows(
        tmp_path / "unitaire" / "registry.sqlite"
    )
    ratio = duree_lot / duree_unitaire if duree_unitaire > 0 else 0.0
    if ratio >= 0.8:
        pytest.skip(
            f"Machine lente/chargée : lot/unitaire = {ratio:.2f} "
            f"({duree_lot * 1000:.1f} ms vs {duree_unitaire * 1000:.1f} ms) — "
            "mesure indicative non bloquante."
        )
    assert ratio < 0.8
