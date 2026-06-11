"""Règles de statut unifiées — urgences locales effectives selon le cycle de vie.

Source de vérité UNIQUE de la règle « DONE → Ur_local effectif 0.0,
ABANDONED → 1.0 », auparavant dupliquée dans l'orchestrateur, dans
:meth:`UrModel.ur_local` et dans ``PropagationEngine._effective_ur_local``.
Tout consommateur (core, graph, services) doit déléguer à ce module au lieu
de réimplémenter la règle.

Les fonctions sont pures : elles ne modifient jamais le ``ur_local`` /
``ud_local`` stocké sur le nœud, elles calculent la valeur EFFECTIVE à
utiliser dans les agrégations et propagations.
"""

from __future__ import annotations

from supplyscore.domain.models import TaskStatus


def effective_ur_local(status: TaskStatus, ur_local: float | None) -> float:
    """Urgence réelle locale effective d'un nœud selon son statut.

    Règles :
        - ``DONE`` → 0.0 : une tâche finie n'est plus urgente, sa
          contribution montante est nulle ;
        - ``ABANDONED`` → 1.0 : une tâche abandonnée est une urgence
          maximale pour tout l'aval ;
        - sinon → ``ur_local`` si non-None, 0.0 sinon (absence de mesure
          = pas d'urgence connue).

    Args:
        status: statut de la tâche portée par le nœud.
        ur_local: urgence réelle locale mesurée (KPIs), ou None si inconnue.

    Returns:
        Urgence réelle locale effective (>= 0 ; peut dépasser 1 si le
        ``ur_local`` fourni dépasse 1, p. ex. tâche en retard — le clip
        éventuel reste la responsabilité de l'appelant).
    """
    if status is TaskStatus.DONE:
        return 0.0
    if status is TaskStatus.ABANDONED:
        return 1.0
    return ur_local if ur_local is not None else 0.0


def effective_ud_local(status: TaskStatus, ud_local: float | None) -> float:
    """Urgence déclarée locale effective d'un nœud selon son statut.

    DÉCISION DE MODÉLISATION n°1 (tranchée en E9, cf.
    ``docs/modele_mathematique.md`` § Décisions) : le statut n'écrase PAS le
    besoin déclaré — un nœud DONE continue de propager son ``ud_local`` (le
    flux physique et les dépendances aval existent encore). Pour isoler un
    nœud, le supprimer ou couper ses arcs, pas le marquer DONE.

    Args:
        status: statut de la tâche portée par le nœud (sans effet, par décision).
        ud_local: urgence déclarée locale (questionnaire), ou None si absente.

    Returns:
        Urgence déclarée locale effective (``ud_local`` ou 0.0).
    """
    del status  # Sans effet par décision n°1 — point d'application centralisé.
    return ud_local if ud_local is not None else 0.0
