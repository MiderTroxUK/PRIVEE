"""Jalons (milestones) d'un noeud : proto, serie, livraison.

Le cahier des charges d'un noeud definit N jalons dates, chacun avec son
statut et son avancement declare. L'urgence temporelle u_time se calcule
sur le PROCHAIN jalon actif ; le statut global du noeud DERIVE des jalons.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from supplyscore.domain.models import TaskStatus


class MilestoneStatus(StrEnum):
    """Statut d'un jalon (cycle de vie individuel)."""

    ACTIVE = "active"
    DONE = "done"
    ABANDONED = "abandoned"


@dataclass
class Milestone:
    """Jalon date d'un noeud (proto, serie, livraison...)."""

    id: str
    node_id: str
    name: str  # "Proto", "Serie", "Livraison"...
    kind: str = "livraison"  # proto | serie | livraison | custom
    start_ts: float = 0.0  # epoch s (debut planifie)
    deadline_ts: float = 0.0  # epoch s, > start_ts
    status: MilestoneStatus = MilestoneStatus.ACTIVE
    progress: float = 0.0  # avancement declare [0, 1]
    position: int = 0  # ordre dans le cahier des charges


def _clip01(x: float) -> float:
    """Borne une valeur sur [0, 1]."""
    return min(max(x, 0.0), 1.0)


def next_active_milestone(milestones: list[Milestone]) -> Milestone | None:
    """Prochain jalon actif : le jalon ACTIVE de ``deadline_ts`` minimale.

    Les jalons DONE et ABANDONED sont ignores : seuls les jalons encore
    actifs portent une echeance a venir pour le noeud. C'est sur ce jalon
    M* que se calcule l'urgence temporelle u_time v2.

    Args:
        milestones: jalons du noeud (ordre quelconque).

    Returns:
        Le jalon ACTIVE dont la deadline est la plus proche, ou None si
        aucun jalon n'est actif (liste vide incluse).
    """
    actives = [m for m in milestones if m.status is MilestoneStatus.ACTIVE]
    if not actives:
        return None
    return min(actives, key=lambda m: m.deadline_ts)


def theoretical_progress(m: Milestone, now_ts: float) -> float:
    """Avancement theorique d'un jalon a ``now_ts`` (interpolation lineaire).

    p_th = clip01((now_ts - start_ts) / (deadline_ts - start_ts)) : 0 avant
    le debut planifie, 1 apres la deadline, lineaire entre les deux.
    Convention : si ``deadline_ts <= start_ts`` (fenetre degeneree ou
    inversee), p_th = 1.0 - le jalon aurait deja du etre termine.

    Args:
        m: jalon considere.
        now_ts: date courante (epoch s).

    Returns:
        Avancement theorique dans [0, 1].
    """
    if m.deadline_ts <= m.start_ts:
        return 1.0
    return _clip01((now_ts - m.start_ts) / (m.deadline_ts - m.start_ts))


def derive_node_status(milestones: list[Milestone]) -> TaskStatus | None:
    """Statut du noeud derive de ses jalons (table de verite, regle pessimiste).

    Table de verite :
        - liste vide -> None (statut manuel conserve, retro-compatibilite) ;
        - au moins un jalon ACTIVE -> :attr:`TaskStatus.ACTIVE` ;
        - aucun actif et au moins un ABANDONED -> :attr:`TaskStatus.ABANDONED`
          (regle PESSIMISTE : un jalon abandonne teinte le noeud - le perimetre
          n'a pas ete rempli, le risque pour l'aval est maximal ; c'est aussi
          ce qui rend l'action " abandonner le noeud " coherente meme quand un
          jalon anterieur avait deja ete livre) ;
        - tous DONE -> :attr:`TaskStatus.DONE`.

    Args:
        milestones: jalons du noeud (ordre quelconque).

    Returns:
        Statut derive, ou None si le noeud n'a aucun jalon.
    """
    if not milestones:
        return None
    statuses = {m.status for m in milestones}
    if MilestoneStatus.ACTIVE in statuses:
        return TaskStatus.ACTIVE
    if MilestoneStatus.ABANDONED in statuses:
        return TaskStatus.ABANDONED
    return TaskStatus.DONE
