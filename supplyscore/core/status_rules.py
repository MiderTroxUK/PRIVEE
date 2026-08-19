"""Regles de statut unifiees - urgences locales effectives selon le cycle de vie.

Source de verite UNIQUE de la regle " DONE -> Ur_local effectif 0.0,
ABANDONED -> 1.0 ", auparavant dupliquee dans l'orchestrateur, dans
:meth:`UrModel.ur_local` et dans ``PropagationEngine._effective_ur_local``.
Tout consommateur (core, graph, services) doit deleguer a ce module au lieu
de reimplementer la regle.

Les fonctions sont pures : elles ne modifient jamais le ``ur_local`` /
``ud_local`` stocke sur le noeud, elles calculent la valeur EFFECTIVE a
utiliser dans les agregations et propagations.
"""

from __future__ import annotations

from supplyscore.domain.models import TaskStatus


def effective_ur_local(status: TaskStatus, ur_local: float | None) -> float:
    """Urgence reelle locale effective d'un noeud selon son statut.

    Regles :
        - ``DONE`` -> 0.0 : une tache finie n'est plus urgente, sa
          contribution montante est nulle ;
        - ``ABANDONED`` -> 1.0 : une tache abandonnee est une urgence
          maximale pour tout l'aval ;
        - sinon -> ``ur_local`` si non-None, 0.0 sinon (absence de mesure
          = pas d'urgence connue).

    Args:
        status: statut de la tache portee par le noeud.
        ur_local: urgence reelle locale mesuree (KPIs), ou None si inconnue.

    Returns:
        Urgence reelle locale effective (>= 0 ; peut depasser 1 si le
        ``ur_local`` fourni depasse 1, p. ex. tache en retard - le clip
        eventuel reste la responsabilite de l'appelant).
    """
    if status is TaskStatus.DONE:
        return 0.0
    if status is TaskStatus.ABANDONED:
        return 1.0
    return ur_local if ur_local is not None else 0.0


def effective_ud_local(status: TaskStatus, ud_local: float | None) -> float:
    """Urgence declaree locale effective d'un noeud selon son statut.

    DECISION DE MODELISATION no1 (tranchee en E9, cf.
    ``docs/modele_mathematique.md`` section  Decisions) : le statut n'ecrase PAS le
    besoin declare - un noeud DONE continue de propager son ``ud_local`` (le
    flux physique et les dependances aval existent encore). Pour isoler un
    noeud, le supprimer ou couper ses arcs, pas le marquer DONE.

    Args:
        status: statut de la tache portee par le noeud (sans effet, par decision).
        ud_local: urgence declaree locale (questionnaire), ou None si absente.

    Returns:
        Urgence declaree locale effective (``ud_local`` ou 0.0).
    """
    del status  # Sans effet par decision no1 - point d'application centralise.
    return ud_local if ud_local is not None else 0.0
