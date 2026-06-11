"""Tests du cycle hebdomadaire ISO (services.weekly) et de la migration client v4.

Couvre : statuts à jour / en retard / manquant (FixedClock), passage en retard
en mode jeu (GameClock + advance_week), bascule de semaine dimanche/lundi,
``semaines_ecart`` (bords d'année inclus), couverture excluant DONE/ABANDONED
et backfill ``iso_week`` de la migration client v3 -> v4.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from supplyscore.core.clock import FixedClock, iso_week
from supplyscore.data.db import ClientDatabase
from supplyscore.data.migrations import _client_v1, _client_v2, _client_v3, apply_migrations
from supplyscore.domain.models import AHPAssessment, Project, SupplyNode, TaskStatus, UrgencyState
from supplyscore.services import SupplyScoreService
from supplyscore.services.weekly import CycleHebdomadaire, EtatHebdo, StatutHebdo, semaines_ecart

#: Mercredi 2026-06-10 12:00 locale — semaine ISO « 2026-S24 ».
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()
_WEEK = 604_800.0


def _assessment(node_id: str, project_id: str = "p1", ts: float | None = None) -> AHPAssessment:
    """Évaluation AHP minimale valide (iso_week laissée vide volontairement)."""
    return AHPAssessment(
        node_id=node_id,
        project_id=project_id,
        operator_id="op",
        comparisons={(0, 1): 1.0},
        criteria_scores=[5.0, 5.0],
        weights=[0.5, 0.5],
        consistency_ratio=0.0,
        is_consistent=True,
        ud=0.5,
        timestamp=_NOW if ts is None else ts,
    )


def _setup_projet(service: SupplyScoreService, node_ids: tuple[str, ...]) -> Project:
    """Crée un projet « p1 » et ses nœuds actifs (aucun arc, aucun jalon)."""
    project = Project(
        id="p1",
        name="Projet",
        owner_node_id=node_ids[0],
        created_at=_NOW - 5 * _WEEK,
        t0_ts=_NOW - 5 * _WEEK,
    )
    nodes = [
        SupplyNode(id=node_id, name=node_id, project_id="p1", rank=i)
        for i, node_id in enumerate(node_ids)
    ]
    service.create_project(project, nodes, [])
    return project


@pytest.fixture
def fixed_clock() -> FixedClock:
    return FixedClock(_NOW)


@pytest.fixture
def service(tmp_path: Path, fixed_clock: FixedClock):
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=fixed_clock)
    yield svc
    svc.close()


# --- Statuts : à jour / en retard / manquant (FixedClock) ---------------------------


def test_trois_noeuds_a_jour_en_retard_manquant(
    service: SupplyScoreService, fixed_clock: FixedClock
) -> None:
    _setup_projet(service, ("n-a", "n-b", "n-c"))
    cycle = CycleHebdomadaire(service)

    # n-a : évalué cette semaine.
    service.submit_assessment(_assessment("n-a"))

    # n-b : évalué il y a 2 semaines (horloge reculée puis ré-avancée).
    fixed_clock.set(_NOW - 2 * _WEEK)
    service.submit_assessment(_assessment("n-b", ts=_NOW - 2 * _WEEK))
    fixed_clock.set(_NOW)

    semaine = iso_week(_NOW)
    assert semaine == "2026-S24"
    assert cycle.statut_noeud("n-a") == EtatHebdo(StatutHebdo.A_JOUR, semaine, semaine, 0)

    etat_b = cycle.statut_noeud("n-b")
    assert etat_b.statut is StatutHebdo.EN_RETARD
    assert etat_b.semaines_de_retard == 2
    assert etat_b.derniere_semaine == "2026-S22"
    assert etat_b.semaine_courante == semaine

    # n-c : jamais évalué.
    assert cycle.statut_noeud("n-c") == EtatHebdo(StatutHebdo.MANQUANT, semaine, None, 0)

    synthese = cycle.synthese("p1")
    assert {nid: etat.statut for nid, etat in synthese.items()} == {
        "n-a": StatutHebdo.A_JOUR,
        "n-b": StatutHebdo.EN_RETARD,
        "n-c": StatutHebdo.MANQUANT,
    }


def test_statut_noeud_inconnu_leve_value_error(service: SupplyScoreService) -> None:
    cycle = CycleHebdomadaire(service)
    with pytest.raises(ValueError, match="inconnu"):
        cycle.statut_noeud("fantome")


# --- Mode jeu : advance_week fait passer en retard -----------------------------------


def test_game_clock_advance_week_passe_en_retard(service: SupplyScoreService) -> None:
    _setup_projet(service, ("n-a",))
    service.set_clock_mode("p1", "game")  # origine = _NOW (horloge réelle figée)
    cycle = CycleHebdomadaire(service)

    service.submit_assessment(_assessment("n-a"))
    etat = cycle.statut_noeud("n-a")
    assert etat.statut is StatutHebdo.A_JOUR
    assert etat.semaine_courante == iso_week(_NOW)

    service.advance_week("p1", 1)
    etat = cycle.statut_noeud("n-a")
    assert etat.statut is StatutHebdo.EN_RETARD
    assert etat.semaines_de_retard == 1
    assert etat.semaine_courante == iso_week(_NOW + _WEEK)
    assert etat.derniere_semaine == iso_week(_NOW)


# --- Bascule de semaine : dimanche 23:59 vs lundi 00:00 (heure locale) ----------------


def test_bascule_dimanche_lundi(tmp_path: Path) -> None:
    dimanche = datetime.fromisocalendar(2026, 24, 7).replace(hour=23, minute=59)
    lundi = datetime.fromisocalendar(2026, 25, 1)  # minuit local

    assert iso_week(dimanche.timestamp()) == "2026-S24"
    assert iso_week(lundi.timestamp()) == "2026-S25"

    with ClientDatabase(tmp_path, "client-1") as db:
        # iso_week vide : le garde-fou de save_assessment la dérive du timestamp.
        db.save_assessment(_assessment("n1", ts=dimanche.timestamp()))
        db.save_assessment(_assessment("n1", ts=lundi.timestamp()))

        assert db.assessment_weeks("n1") == ["2026-S25", "2026-S24"]
        assert db.last_assessment_week("n1") == "2026-S25"
        assert db.last_assessment_week("autre") is None
        assert db.assessment_weeks("autre") == []


# --- semaines_ecart -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("week_a", "week_b", "attendu"),
    [
        ("2026-S24", "2026-S24", 0),
        ("2026-S24", "2026-S26", 2),
        ("2020-S53", "2021-S01", 1),  # bord d'année ISO (2020 compte 53 semaines)
        ("2026-S26", "2026-S24", -2),  # b avant a : écart négatif
    ],
)
def test_semaines_ecart(week_a: str, week_b: str, attendu: int) -> None:
    assert semaines_ecart(week_a, week_b) == attendu


def test_semaines_ecart_libelle_invalide() -> None:
    with pytest.raises(ValueError):
        semaines_ecart("2026-24", "2026-S25")


# --- Persistance de iso_week (écriture et relecture) -----------------------------------


def test_submit_assessment_pose_iso_week_et_round_trip(service: SupplyScoreService) -> None:
    _setup_projet(service, ("n-a",))
    service.submit_assessment(_assessment("n-a"))

    got = service.client_db("n-a").latest_assessment("n-a")
    assert got is not None
    assert got.iso_week == iso_week(_NOW)

    # Une iso_week explicitement posée n'est PAS écrasée.
    explicite = _assessment("n-a", ts=_NOW + 60.0)
    explicite.iso_week = "2025-S01"
    service.submit_assessment(explicite)
    got = service.client_db("n-a").latest_assessment("n-a")
    assert got is not None and got.iso_week == "2025-S01"


def test_save_urgency_state_persiste_iso_week(tmp_path: Path) -> None:
    with ClientDatabase(tmp_path, "client-1") as db:
        db.save_urgency_state("n1", UrgencyState(ud=0.3, timestamp=_NOW))
        with db.lock:
            row = db.conn.execute("SELECT iso_week, timestamp FROM urgency_history").fetchone()
        assert row["iso_week"] == iso_week(_NOW)
        assert row["timestamp"] == _NOW


# --- Couverture : DONE/ABANDONED exclus --------------------------------------------------


def test_couverture_exclut_done_et_abandoned(service: SupplyScoreService) -> None:
    _setup_projet(service, ("n-a", "n-b", "n-c", "n-d", "n-e"))
    service.submit_assessment(_assessment("n-a"))
    service.submit_assessment(_assessment("n-d"))  # sera DONE : exclu malgré l'évaluation
    service.registry.set_node_status("n-d", TaskStatus.DONE)
    service.registry.set_node_status("n-e", TaskStatus.ABANDONED)

    cycle = CycleHebdomadaire(service)
    # 3 actifs (n-a, n-b, n-c) dont un seul à jour (n-a).
    assert cycle.couverture("p1") == (1, 3)

    # statut_noeud répond quand même pour les nœuds exclus du décompte.
    assert cycle.statut_noeud("n-d").statut is StatutHebdo.A_JOUR
    assert cycle.statut_noeud("n-e").statut is StatutHebdo.MANQUANT

    # La synthèse, elle, couvre TOUS les nœuds du projet.
    assert set(cycle.synthese("p1")) == {"n-a", "n-b", "n-c", "n-d", "n-e"}


# --- Migration client v3 -> v4 : backfill iso_week ----------------------------------------


def _build_v3_client_with_data(db_file: Path, timestamps: list[float]) -> None:
    """Construit une vraie base client v3 et y insère des évaluations datées."""
    conn = sqlite3.connect(str(db_file))
    _client_v1(conn)
    _client_v2(conn)
    _client_v3(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    for ts in timestamps:
        conn.execute(
            """
            INSERT INTO assessments (node_id, project_id, operator_id, comparisons_json,
                                     criteria_scores_json, weights_json, consistency_ratio,
                                     is_consistent, ud, notes, timestamp)
            VALUES ('n1', 'p1', 'op', '{}', '[]', '[]', 0.0, 1, 0.5, '', ?)
            """,
            (ts,),
        )
        conn.execute(
            "INSERT INTO urgency_history (node_id, ud, timestamp) VALUES ('n1', 0.4, ?)",
            (ts,),
        )
    conn.commit()
    conn.close()


def test_migration_v4_backfill_iso_week(tmp_path: Path) -> None:
    ts_s53 = datetime(2026, 12, 28, 12, 0).timestamp()  # lundi -> « 2026-S53 »
    _build_v3_client_with_data(tmp_path / "client.sqlite", [_NOW, ts_s53])

    conn = sqlite3.connect(str(tmp_path / "client.sqlite"))
    assert apply_migrations(conn, "client") == 6
    assert apply_migrations(conn, "client") == 6  # idempotent
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 6

    weeks = [
        row[0]
        for row in conn.execute("SELECT iso_week FROM assessments ORDER BY timestamp").fetchall()
    ]
    assert weeks == ["2026-S24", "2026-S53"]
    weeks_urgency = [
        row[0]
        for row in conn.execute(
            "SELECT iso_week FROM urgency_history ORDER BY timestamp"
        ).fetchall()
    ]
    assert weeks_urgency == ["2026-S24", "2026-S53"]

    index_names = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
    }
    assert {"idx_assessments_week", "idx_urgency_week"} <= index_names
    conn.close()


def test_client_database_ouvre_base_v3_et_lit_les_semaines(tmp_path: Path) -> None:
    """Une base v3 existante est migrée à l'ouverture et lisible par les nouvelles méthodes."""
    ts_s53 = datetime(2026, 12, 28, 12, 0).timestamp()
    _build_v3_client_with_data(tmp_path / "client.sqlite", [_NOW, ts_s53])

    with ClientDatabase(tmp_path, "client") as db:
        assert db.schema_version == 6
        assert db.assessment_weeks("n1") == ["2026-S53", "2026-S24"]
        assert db.last_assessment_week("n1") == "2026-S53"
        latest = db.latest_assessment("n1")
        assert latest is not None and latest.iso_week == "2026-S53"
