"""Jalons (milestones) d'un nœud : proto, série, livraison.

Le cahier des charges d'un nœud définit N jalons datés, chacun avec son
statut et son avancement déclaré. L'urgence temporelle u_time se calcule
sur le PROCHAIN jalon actif ; le statut global du nœud DÉRIVE des jalons.
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
    """Jalon daté d'un nœud (proto, série, livraison…)."""

    id: str
    node_id: str
    name: str  # "Proto", "Série", "Livraison"...
    kind: str = "livraison"  # proto | serie | livraison | custom
    start_ts: float = 0.0  # epoch s (début planifié)
    deadline_ts: float = 0.0  # epoch s, > start_ts
    status: MilestoneStatus = MilestoneStatus.ACTIVE
    progress: float = 0.0  # avancement déclaré [0, 1]
    position: int = 0  # ordre dans le cahier des charges


def _clip01(x: float) -> float:
    """Borne une valeur sur [0, 1]."""
    return min(max(x, 0.0), 1.0)


def next_active_milestone(milestones: list[Milestone]) -> Milestone | None:
    """Prochain jalon actif : le jalon ACTIVE de ``deadline_ts`` minimale.

    Les jalons DONE et ABANDONED sont ignorés : seuls les jalons encore
    actifs portent une échéance à venir pour le nœud. C'est sur ce jalon
    M* que se calcule l'urgence temporelle u_time v2.

    Args:
        milestones: jalons du nœud (ordre quelconque).

    Returns:
        Le jalon ACTIVE dont la deadline est la plus proche, ou None si
        aucun jalon n'est actif (liste vide incluse).
    """
    actives = [m for m in milestones if m.status is MilestoneStatus.ACTIVE]
    if not actives:
        return None
    return min(actives, key=lambda m: m.deadline_ts)


def theoretical_progress(m: Milestone, now_ts: float) -> float:
    """Avancement théorique d'un jalon à ``now_ts`` (interpolation linéaire).

    p_th = clip01((now_ts − start_ts) / (deadline_ts − start_ts)) : 0 avant
    le début planifié, 1 après la deadline, linéaire entre les deux.
    Convention : si ``deadline_ts <= start_ts`` (fenêtre dégénérée ou
    inversée), p_th = 1.0 — le jalon aurait déjà dû être terminé.

    Args:
        m: jalon considéré.
        now_ts: date courante (epoch s).

    Returns:
        Avancement théorique dans [0, 1].
    """
    if m.deadline_ts <= m.start_ts:
        return 1.0
    return _clip01((now_ts - m.start_ts) / (m.deadline_ts - m.start_ts))


def derive_node_status(milestones: list[Milestone]) -> TaskStatus | None:
    """Statut du nœud dérivé de ses jalons (table de vérité, règle pessimiste).

    Table de vérité :
        - liste vide → None (statut manuel conservé, rétro-compatibilité) ;
        - au moins un jalon ACTIVE → :attr:`TaskStatus.ACTIVE` ;
        - aucun actif et au moins un ABANDONED → :attr:`TaskStatus.ABANDONED`
          (règle PESSIMISTE : un jalon abandonné teinte le nœud — le périmètre
          n'a pas été rempli, le risque pour l'aval est maximal ; c'est aussi
          ce qui rend l'action « abandonner le nœud » cohérente même quand un
          jalon antérieur avait déjà été livré) ;
        - tous DONE → :attr:`TaskStatus.DONE`.

    Args:
        milestones: jalons du nœud (ordre quelconque).

    Returns:
        Statut dérivé, ou None si le nœud n'a aucun jalon.
    """
    if not milestones:
        return None
    statuses = {m.status for m in milestones}
    if MilestoneStatus.ACTIVE in statuses:
        return TaskStatus.ACTIVE
    if MilestoneStatus.ABANDONED in statuses:
        return TaskStatus.ABANDONED
    return TaskStatus.DONE
