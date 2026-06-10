"""Tests de l'horloge applicative bimodale (supplyscore.core.clock)."""

import json
import time
from datetime import datetime

import pytest

from supplyscore.core.clock import (
    WEEK_SECONDS,
    Clock,
    FixedClock,
    GameClock,
    SystemClock,
    iso_week,
    project_hours,
)


def ts_local(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> float:
    """Timestamp epoch d'une date construite en heure locale du poste."""
    return datetime(year, month, day, hour, minute).timestamp()


class TestIsoWeek:
    """Cas analytiques de la semaine ISO en heure locale."""

    def test_semaine_courante_2026(self):
        assert iso_week(ts_local(2026, 6, 10)) == "2026-S24"

    def test_annee_a_53_semaines(self):
        assert iso_week(ts_local(2026, 12, 28)) == "2026-S53"

    def test_rattachement_annee_iso_precedente(self):
        # Le 1er janvier 2021 (vendredi) appartient à la semaine 53 de 2020.
        assert iso_week(ts_local(2021, 1, 1)) == "2020-S53"

    def test_premiere_semaine_zero_paddee(self):
        assert iso_week(ts_local(2026, 1, 1)) == "2026-S01"


class TestSystemClock:
    """Mode « réel » : délégation à time.time()."""

    def test_now_proche_de_time_time(self):
        clock = SystemClock()
        assert abs(clock.now() - time.time()) < 2.0


class TestFixedClock:
    """Horloge figée pilotable pour les tests."""

    def test_now_renvoie_l_instant_fige(self):
        clock = FixedClock(1_000.0)
        assert clock.now() == 1_000.0
        assert clock.now() == 1_000.0  # stable entre deux appels

    def test_set_repositionne_l_instant(self):
        clock = FixedClock(1_000.0)
        clock.set(2_500.5)
        assert clock.now() == 2_500.5


class TestGameClock:
    """Mode « jeu » : avancement par semaines entières."""

    @pytest.fixture
    def t0(self) -> float:
        return ts_local(2026, 6, 10, 9, 30)

    def test_now_initial_egal_t0(self, t0):
        assert GameClock(t0).now() == t0

    def test_advance_weeks_3_exact(self, t0):
        clock = GameClock(t0)
        clock.advance_weeks(3)
        assert clock.now() == t0 + 3 * 604_800.0
        assert clock.weeks_elapsed == 3

    def test_iso_week_avance_de_3_semaines(self, t0):
        clock = GameClock(t0)
        assert iso_week(clock.now()) == "2026-S24"
        clock.advance_weeks(3)
        assert iso_week(clock.now()) == "2026-S27"

    def test_advance_weeks_cumulatif_par_defaut(self, t0):
        clock = GameClock(t0)
        clock.advance_weeks()
        clock.advance_weeks(2)
        assert clock.weeks_elapsed == 3
        assert clock.now() == t0 + 3 * WEEK_SECONDS

    @pytest.mark.parametrize("n", [0, -1])
    def test_advance_weeks_invalide(self, t0, n):
        clock = GameClock(t0)
        with pytest.raises(ValueError, match=">= 1"):
            clock.advance_weeks(n)

    def test_weeks_elapsed_negatif_refuse(self, t0):
        with pytest.raises(ValueError, match=">= 0"):
            GameClock(t0, weeks_elapsed=-1)

    def test_proprietes_lecture(self, t0):
        clock = GameClock(t0, weeks_elapsed=5)
        assert clock.start_ts == t0
        assert clock.weeks_elapsed == 5


class TestGameClockJson:
    """Sérialisation JSON et round-trip strict."""

    def test_to_json_forme_exacte(self):
        t0 = ts_local(2026, 6, 10)
        clock = GameClock(t0, weeks_elapsed=3)
        assert json.loads(clock.to_json()) == {"start_ts": t0, "weeks_elapsed": 3}

    def test_round_trip_strict(self):
        t0 = ts_local(2026, 6, 10, 9, 30)
        clock = GameClock(t0, weeks_elapsed=7)
        restored = GameClock.from_json(clock.to_json())
        assert restored.start_ts == clock.start_ts
        assert restored.weeks_elapsed == clock.weeks_elapsed
        assert restored.now() == clock.now()
        assert restored.to_json() == clock.to_json()

    @pytest.mark.parametrize(
        "raw",
        [
            "pas du json",
            "[1, 2]",
            '{"start_ts": 0.0}',
            '{"weeks_elapsed": 2}',
            '{"start_ts": "demain", "weeks_elapsed": 2}',
            '{"start_ts": 0.0, "weeks_elapsed": 1.5}',
            '{"start_ts": 0.0, "weeks_elapsed": -1}',
        ],
    )
    def test_from_json_invalide(self, raw):
        with pytest.raises(ValueError):
            GameClock.from_json(raw)


class TestProtocol:
    """Les trois horloges satisfont le protocole Clock."""

    @pytest.mark.parametrize(
        "clock",
        [SystemClock(), FixedClock(0.0), GameClock(0.0)],
        ids=["system", "fixed", "game"],
    )
    def test_isinstance_clock(self, clock):
        assert isinstance(clock, Clock)
        assert isinstance(clock.now(), float)


class TestProjectHours:
    """Pont epoch → heures projet."""

    def test_deux_heures(self):
        t0 = ts_local(2026, 6, 10)
        assert project_hours(t0 + 7_200.0, t0) == 2.0

    def test_origine_et_negatif(self):
        t0 = ts_local(2026, 6, 10)
        assert project_hours(t0, t0) == 0.0
        assert project_hours(t0 - 1_800.0, t0) == -0.5
