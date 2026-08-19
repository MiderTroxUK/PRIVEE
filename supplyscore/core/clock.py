"""Horloge applicative bimodale - temps reel, temps fige et temps " jeu ".

Module pur (stdlib uniquement) decouplant le reste de l'application de la
source du temps. Trois implementations partagent le protocole :class:`Clock` :

- :class:`SystemClock` : mode " reel ", delegue a :func:`time.time` ;
- :class:`FixedClock` : horloge figee pilotable, destinee aux tests ;
- :class:`GameClock` : mode " jeu " (serious game), le temps avance par
  semaines entieres depuis un instant de depart.

Deux ponts vers les formules du coeur mathematique :

- :func:`iso_week` : libelle de semaine ISO (" AAAA-Sxx ") en heure locale ;
- :func:`project_hours` : conversion d'un epoch en " t " exprime en heures.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Protocol, runtime_checkable

#: Duree d'une semaine en secondes (7 x 24 x 3600).
WEEK_SECONDS: float = 604_800.0


@runtime_checkable
class Clock(Protocol):
    """Horloge abstraite : toute source de temps exposant l'epoch courant."""

    def now(self) -> float:
        """Renvoie l'instant courant en secondes depuis l'epoch Unix."""
        ...


class SystemClock:
    """Horloge " reelle " : l'instant courant du systeme d'exploitation."""

    def now(self) -> float:
        """Renvoie :func:`time.time` (epoch secondes)."""
        return time.time()


class FixedClock:
    """Horloge figee pour les tests : renvoie toujours le meme instant.

    L'instant peut etre repositionne explicitement via :meth:`set`, ce qui
    permet d'ecrire des scenarios temporels deterministes.
    """

    def __init__(self, ts: float) -> None:
        """Initialise l'horloge figee.

        Args:
            ts: instant fige, en secondes epoch.
        """
        self._ts = float(ts)

    def now(self) -> float:
        """Renvoie l'instant fige courant (epoch secondes)."""
        return self._ts

    def set(self, ts: float) -> None:
        """Repositionne l'instant fige.

        Args:
            ts: nouvel instant, en secondes epoch.
        """
        self._ts = float(ts)


class GameClock:
    """Horloge " jeu " : le temps avance par semaines entieres depuis un t0.

    L'instant courant vaut ``start_ts + weeks_elapsed x 604 800`` secondes.
    L'etat est entierement decrit par ``(start_ts, weeks_elapsed)`` et se
    serialise en JSON pour persister une partie en cours.
    """

    def __init__(self, start_ts: float, weeks_elapsed: int = 0) -> None:
        """Initialise l'horloge de jeu.

        Args:
            start_ts: instant de depart de la partie, en secondes epoch.
            weeks_elapsed: nombre de semaines deja ecoulees, >= 0.

        Raises:
            ValueError: si ``weeks_elapsed`` est strictement negatif.
        """
        if weeks_elapsed < 0:
            raise ValueError(f"weeks_elapsed doit être >= 0, reçu {weeks_elapsed}")
        self._start_ts = float(start_ts)
        self._weeks_elapsed = int(weeks_elapsed)

    @property
    def start_ts(self) -> float:
        """Instant de depart de la partie (epoch secondes)."""
        return self._start_ts

    @property
    def weeks_elapsed(self) -> int:
        """Nombre de semaines ecoulees depuis le depart."""
        return self._weeks_elapsed

    def now(self) -> float:
        """Renvoie ``start_ts + weeks_elapsed x 604 800`` (epoch secondes)."""
        return self._start_ts + self._weeks_elapsed * WEEK_SECONDS

    def advance_weeks(self, n: int = 1) -> None:
        """Avance l'horloge de ``n`` semaines entieres.

        Args:
            n: nombre de semaines a ajouter, >= 1.

        Raises:
            ValueError: si ``n`` est inferieur a 1.
        """
        if n < 1:
            raise ValueError(f"n doit être >= 1, reçu {n}")
        self._weeks_elapsed += n

    def to_json(self) -> str:
        """Serialise l'etat de l'horloge en JSON.

        Returns:
            Chaine JSON ``{"start_ts": ..., "weeks_elapsed": ...}``.
        """
        return json.dumps({"start_ts": self._start_ts, "weeks_elapsed": self._weeks_elapsed})

    @classmethod
    def from_json(cls, raw: str) -> GameClock:
        """Reconstruit une horloge de jeu depuis sa forme JSON.

        Args:
            raw: chaine JSON produite par :meth:`to_json`.

        Returns:
            Une :class:`GameClock` equivalente a l'horloge serialisee.

        Raises:
            ValueError: si la chaine est un JSON invalide ou de forme inattendue
                (cles manquantes ou types incorrects).
        """
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON invalide pour GameClock : {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"GameClock attend un objet JSON, reçu {type(data).__name__}")
        try:
            start_ts = data["start_ts"]
            weeks_elapsed = data["weeks_elapsed"]
        except KeyError as exc:
            raise ValueError(f"Clé manquante dans le JSON GameClock : {exc}") from exc
        if isinstance(start_ts, bool) or not isinstance(start_ts, int | float):
            raise ValueError(f"start_ts doit être un nombre, reçu {type(start_ts).__name__}")
        if isinstance(weeks_elapsed, bool) or not isinstance(weeks_elapsed, int):
            raise ValueError(
                f"weeks_elapsed doit être un entier, reçu {type(weeks_elapsed).__name__}"
            )
        return cls(start_ts=float(start_ts), weeks_elapsed=weeks_elapsed)


def iso_week(ts: float) -> str:
    """Libelle de la semaine ISO d'un instant, en heure locale du poste.

    L'annee affichee est l'annee ISO, qui peut differer de l'annee civile
    (ex. le 2021-01-01 appartient a la semaine " 2020-S53 ").

    Args:
        ts: instant en secondes epoch.

    Returns:
        Libelle " AAAA-Sxx " zero-padde, ex. " 2026-S05 ".
    """
    iso = datetime.fromtimestamp(ts).isocalendar()
    return f"{iso.year:04d}-S{iso.week:02d}"


def project_hours(ts: float, t0_ts: float) -> float:
    """Convertit un instant epoch en " t " projet exprime en heures.

    Pont entre l'horloge applicative et le temps " t " des formules du coeur
    mathematique (urgences, singularites), qui raisonnent en heures depuis t0.

    Args:
        ts: instant courant, en secondes epoch.
        t0_ts: origine du projet, en secondes epoch.

    Returns:
        ``(ts - t0_ts) / 3600``, en heures (negatif si ``ts`` precede ``t0_ts``).
    """
    return (ts - t0_ts) / 3600.0
