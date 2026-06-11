"""Calibration prédiction/réalité — le score H a-t-il prédit les vraies ruptures ? (E11, Lot 11.1).

:class:`CalibrationService` confronte les risques cachés H persistés semaine
après semaine (table ``urgency_history`` des bases CLIENT) aux issues
défavorables réellement constatées ensuite. C'est l'instrument de mesure du
serious game : matrice de confusion, précision/rappel et courbe de calibration.

Définitions FIGÉES du lot 11.1 :

- **Point d'observation** : un couple (nœud, semaine ISO S) où le nœud a un
  état d'urgence persisté dans son historique (``urgency_history``) — on prend
  le DERNIER état de la semaine S (``hidden_risk`` H et ``ur``). Les points
  sans H (None) sont ignorés ; la semaine COURANTE du projet (et toute semaine
  postérieure) est exclue, sa fenêtre d'observation n'ayant pas commencé.
- **Issue défavorable dans [S+1, S+horizon]** (horizon en semaines, défaut 4),
  au moins un des trois constats :

  (a) **jalon RATÉ** : un jalon du nœud dont la deadline tombe dans la fenêtre
      (timestamps : ``lundi(S+1) <= deadline_ts < lundi(S+horizon+1)``, heure
      locale) ET dont le statut est ABANDONED, ou ACTIVE avec la deadline
      dépassée à la fin de la fenêtre (bornée par « maintenant » si la fenêtre
      déborde sur le futur) — on utilise les timestamps, jamais les statuts
      hebdo ;
  (b) **nœud ABANDONNÉ** : le registre ne conservant PAS l'horodatage du
      passage au statut ABANDONED, le statut COURANT du nœud sert de proxy —
      un nœud aujourd'hui abandonné marque TOUS ses points d'observation
      (limite documentée : le passage peut être postérieur à la fenêtre) ;
  (c) **événement de gravité critique/défaut** : un événement non annulé
      (``reverted_at`` NULL) journalisé dans une semaine de la fenêtre dont le
      paramètre ``gravite`` vaut ``"critique"`` ou ``"defaut"``.

Limite assumée (censure à droite) : pour les semaines récentes, la fenêtre
[S+1, S+horizon] déborde sur le futur — une issue peut encore survenir après
« maintenant » ; le taux observé de ces points est donc une borne inférieure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from supplyscore.core.clock import iso_week
from supplyscore.domain.milestones import MilestoneStatus
from supplyscore.domain.models import TaskStatus

# ``_lundi`` est le parseur canonique des libellés « AAAA-Sxx » (même module
# que ``semaines_ecart``) : on le réutilise plutôt que de dupliquer le calcul.
from supplyscore.services.weekly import _lundi, semaines_ecart

if TYPE_CHECKING:
    from supplyscore.domain.milestones import Milestone
    from supplyscore.domain.models import SupplyNode, UrgencyState
    from supplyscore.services.orchestrator import SupplyScoreService

#: Gravités d'événement comptées comme issue défavorable (critère (c)).
_GRAVITES_DEFAVORABLES: frozenset[str] = frozenset({"critique", "defaut"})

#: En dessous de ce nombre de points, :meth:`CalibrationService.summary`
#: avertit explicitement que l'échantillon est trop petit pour conclure.
_MIN_POINTS_CONCLUSION: int = 30


def _semaine_decalee(week: str, n: int) -> str:
    """Libellé de la semaine ISO située ``n`` semaines après ``week``.

    Args:
        week: semaine de départ, ex. « 2026-S24 ».
        n: décalage en semaines (peut être négatif).

    Returns:
        Le libellé « AAAA-Sxx » de la semaine décalée, bords d'année ISO exacts.

    Raises:
        ValueError: si ``week`` n'est pas de la forme « AAAA-Sxx ».
    """
    iso = (_lundi(week) + timedelta(weeks=n)).isocalendar()
    return f"{iso.year:04d}-S{iso.week:02d}"


@dataclass(frozen=True)
class OutcomePoint:
    """Point d'observation calibré : prédiction H d'une semaine vs issue constatée.

    Attributes:
        node_id: identifiant du nœud observé.
        node_name: nom du nœud (pour l'affichage des rapports).
        iso_week: semaine ISO « AAAA-Sxx » de l'observation (semaine S).
        hidden_risk: risque caché H persisté en fin de semaine S (None si
            jamais calculé — ces points sont ignorés par ``outcomes``).
        ur: urgence réelle propagée Ur persistée en fin de semaine S.
        issue_defavorable: True si au moins une issue défavorable a été
            constatée dans la fenêtre [S+1, S+horizon].
        causes: descriptions françaises des issues constatées (``[]`` sinon).
    """

    node_id: str
    node_name: str
    iso_week: str
    hidden_risk: float | None
    ur: float | None
    issue_defavorable: bool
    causes: list[str]


@dataclass(frozen=True)
class ConfusionMatrix:
    """Matrice de confusion de la prédiction « H > seuil » contre les issues.

    Attributes:
        seuil: seuil de décision sur H (prédiction positive si H > seuil).
        vp: vrais positifs — H > seuil ET issue défavorable constatée.
        fp: faux positifs — H > seuil, aucune issue constatée (fausse alerte).
        fn: faux négatifs — H <= seuil mais issue constatée (rupture ratée).
        vn: vrais négatifs — H <= seuil et aucune issue.
    """

    seuil: float
    vp: int
    fp: int
    fn: int
    vn: int

    @property
    def precision(self) -> float | None:
        """Précision ``vp / (vp + fp)``, None si aucune prédiction positive."""
        denominateur = self.vp + self.fp
        return self.vp / denominateur if denominateur else None

    @property
    def rappel(self) -> float | None:
        """Rappel ``vp / (vp + fn)``, None si aucune issue défavorable."""
        denominateur = self.vp + self.fn
        return self.vp / denominateur if denominateur else None


class CalibrationService:
    """Calibration du score H contre les issues réellement constatées.

    S'appuie sur la façade :class:`SupplyScoreService` : le registre fournit
    les nœuds, leurs jalons et leur statut courant, ``clock_for`` l'horloge
    effective du projet (réelle ou de jeu), et les bases CLIENT l'historique
    d'urgence (``urgency_series``) et le journal d'événements (``list_events``).
    Service en LECTURE SEULE : rien n'est jamais écrit.
    """

    def __init__(self, service: SupplyScoreService) -> None:
        """Initialise le service de calibration au-dessus de la façade.

        Args:
            service: façade applicative (registre, bases client, horloges).
        """
        self._service = service

    # -- construction des points d'observation --

    def outcomes(self, project_id: str, horizon_weeks: int = 4) -> list[OutcomePoint]:
        """Points d'observation du projet, confrontés aux issues de leur fenêtre.

        Pour chaque nœud du projet et chaque semaine ISO S de son historique
        d'urgence, le DERNIER état persisté de la semaine fournit (H, Ur), et
        la fenêtre [S+1, S+horizon] est balayée pour constater les issues
        défavorables (jalon raté, nœud abandonné, événement critique/défaut —
        voir le module). Les points sans H (None) sont ignorés ; la semaine
        courante du projet et les semaines postérieures sont exclues (fenêtre
        non commencée).

        Args:
            project_id: identifiant du projet.
            horizon_weeks: longueur de la fenêtre d'observation, en semaines
                (défaut 4).

        Returns:
            Les :class:`OutcomePoint`, triés par (semaine, nom de nœud).

        Raises:
            ValueError: si ``horizon_weeks < 1``.
        """
        if horizon_weeks < 1:
            raise ValueError(f"horizon_weeks doit être >= 1, reçu {horizon_weeks}")
        now_ts = self._service.clock_for(project_id).now()
        semaine_courante = iso_week(now_ts)
        points: list[OutcomePoint] = []
        for node in self._service.registry.list_nodes(project_id):
            derniers: dict[str, UrgencyState] = {}
            for state in self._service.client_db(node.id).urgency_series(node.id):
                # Série croissante par timestamp : le dernier état de chaque
                # semaine écrase les précédents.
                derniers[iso_week(state.timestamp)] = state
            if not derniers:
                continue
            milestones = self._service.registry.list_milestones(node.id)
            for semaine, state in derniers.items():
                if state.hidden_risk is None:
                    continue  # point sans H : inutilisable pour la calibration
                if semaines_ecart(semaine, semaine_courante) < 1:
                    continue  # fenêtre [S+1, S+horizon] pas encore commencée
                causes = self._causes(node, semaine, horizon_weeks, milestones, now_ts)
                points.append(
                    OutcomePoint(
                        node_id=node.id,
                        node_name=node.name,
                        iso_week=semaine,
                        hidden_risk=state.hidden_risk,
                        ur=state.ur,
                        issue_defavorable=bool(causes),
                        causes=causes,
                    )
                )
        points.sort(key=lambda point: (point.iso_week, point.node_name))
        return points

    def _causes(
        self,
        node: SupplyNode,
        semaine: str,
        horizon_weeks: int,
        milestones: list[Milestone],
        now_ts: float,
    ) -> list[str]:
        """Issues défavorables constatées dans la fenêtre [S+1, S+horizon] du nœud.

        Applique les trois critères figés du module : (a) jalon raté (sur les
        timestamps de deadline), (b) nœud abandonné (statut courant en proxy),
        (c) événement non annulé de gravité critique/défaut.

        Args:
            node: nœud observé (lecture fraîche du registre).
            semaine: semaine ISO S du point d'observation.
            horizon_weeks: longueur de la fenêtre, en semaines.
            milestones: jalons courants du nœud.
            now_ts: instant courant de l'horloge du projet (epoch s).

        Returns:
            Les descriptions françaises des issues constatées (``[]`` sinon).
        """
        lundi_s = _lundi(semaine)
        debut_ts = (lundi_s + timedelta(weeks=1)).timestamp()
        fin_ts = (lundi_s + timedelta(weeks=horizon_weeks + 1)).timestamp()
        causes: list[str] = []

        # (a) jalon raté : deadline dans la fenêtre, jamais livré.
        for milestone in milestones:
            if not debut_ts <= milestone.deadline_ts < fin_ts:
                continue
            echeance = iso_week(milestone.deadline_ts)
            if milestone.status is MilestoneStatus.ABANDONED:
                causes.append(f"jalon « {milestone.name} » abandonné (échéance {echeance})")
            elif milestone.status is MilestoneStatus.ACTIVE and milestone.deadline_ts < min(
                fin_ts, now_ts
            ):
                causes.append(f"jalon « {milestone.name} » non livré à son échéance ({echeance})")

        # (b) nœud abandonné — l'horodatage du passage n'étant pas persisté,
        # le statut COURANT sert de proxy (limite documentée dans le module).
        if node.status is TaskStatus.ABANDONED:
            causes.append(
                "nœud au statut « abandonné » (statut courant utilisé comme proxy :"
                " horodatage du passage indisponible)"
            )

        # (c) événement non annulé de gravité critique/défaut dans la fenêtre.
        client = self._service.client_db(node.id)
        for offset in range(1, horizon_weeks + 1):
            semaine_fenetre = _semaine_decalee(semaine, offset)
            for row in client.list_events(node.id, semaine_fenetre):
                if row["reverted_at"] is not None:
                    continue  # événement annulé : déclaré par erreur
                gravite = json.loads(row["params_json"]).get("gravite")
                if gravite in _GRAVITES_DEFAVORABLES:
                    causes.append(
                        f"événement {row['event_type']} de gravité « {gravite} »"
                        f" (semaine {semaine_fenetre})"
                    )
        return causes

    # -- agrégats --

    def confusion(self, points: list[OutcomePoint], seuil: float = 0.5) -> ConfusionMatrix:
        """Matrice de confusion des points : prédiction positive si ``H > seuil``.

        Les points sans H (None) sont ignorés — :meth:`outcomes` n'en produit
        jamais, le garde-fou couvre les listes construites à la main.

        Args:
            points: points d'observation (typiquement :meth:`outcomes`).
            seuil: seuil de décision sur H (strict : H > seuil).

        Returns:
            La :class:`ConfusionMatrix` (vp, fp, fn, vn) au seuil donné.
        """
        vp = fp = fn = vn = 0
        for point in points:
            if point.hidden_risk is None:
                continue
            predit = point.hidden_risk > seuil
            if predit and point.issue_defavorable:
                vp += 1
            elif predit:
                fp += 1
            elif point.issue_defavorable:
                fn += 1
            else:
                vn += 1
        return ConfusionMatrix(seuil=seuil, vp=vp, fp=fp, fn=fn, vn=vn)

    def calibration_curve(
        self, points: list[OutcomePoint], n_bins: int = 5
    ) -> list[tuple[float, float, int]]:
        """Courbe de calibration : taux d'issues observées par tranche de H.

        Les valeurs de H sont réparties dans ``n_bins`` tranches régulières de
        [0, 1] (la borne H = 1 rejoint la dernière tranche). Chaque tranche
        non vide produit ``(H moyen, taux d'issues observées, effectif)`` —
        l'effectif est TOUJOURS retourné : sur de petits échantillons, un taux
        sans son n ne veut rien dire. Les tranches vides sont omises ; les
        points sans H (None) sont ignorés.

        Args:
            points: points d'observation (typiquement :meth:`outcomes`).
            n_bins: nombre de tranches régulières sur [0, 1] (défaut 5).

        Returns:
            Une liste ``[(H moyen, taux d'issues, effectif), ...]`` ordonnée
            par tranche croissante, tranches vides omises.

        Raises:
            ValueError: si ``n_bins < 1``.
        """
        if n_bins < 1:
            raise ValueError(f"n_bins doit être >= 1, reçu {n_bins}")
        sommes_h = [0.0] * n_bins
        issues = [0] * n_bins
        effectifs = [0] * n_bins
        for point in points:
            if point.hidden_risk is None:
                continue
            indice = min(max(int(point.hidden_risk * n_bins), 0), n_bins - 1)
            sommes_h[indice] += point.hidden_risk
            issues[indice] += int(point.issue_defavorable)
            effectifs[indice] += 1
        return [
            (sommes_h[i] / effectifs[i], issues[i] / effectifs[i], effectifs[i])
            for i in range(n_bins)
            if effectifs[i]
        ]

    def summary(self, project_id: str, horizon_weeks: int = 4, seuil: float = 0.5) -> str:
        """Résumé français de la calibration du projet, prudence statistique incluse.

        Construit les points (:meth:`outcomes`), la matrice (:meth:`confusion`)
        puis restitue : nombre de points, matrice, précision et rappel avec
        leurs effectifs, et un avertissement explicite (« échantillon trop
        petit pour conclure ») sous :data:`_MIN_POINTS_CONCLUSION` points.

        Args:
            project_id: identifiant du projet.
            horizon_weeks: longueur de la fenêtre d'observation, en semaines.
            seuil: seuil de décision sur H (prédiction positive si H > seuil).

        Returns:
            Le résumé multi-lignes en français.

        Raises:
            ValueError: si ``horizon_weeks < 1``.
        """
        points = self.outcomes(project_id, horizon_weeks=horizon_weeks)
        matrice = self.confusion(points, seuil=seuil)
        n = len(points)
        positifs = matrice.vp + matrice.fp
        constats = matrice.vp + matrice.fn
        if matrice.precision is None:
            ligne_precision = "Précision : non définie (aucune prédiction positive)."
        else:
            ligne_precision = (
                f"Précision : {matrice.precision:.2f}"
                f" ({matrice.vp}/{positifs} prédictions positives confirmées)."
            )
        if matrice.rappel is None:
            ligne_rappel = "Rappel : non défini (aucune issue défavorable observée)."
        else:
            ligne_rappel = (
                f"Rappel : {matrice.rappel:.2f}"
                f" ({matrice.vp}/{constats} issues défavorables détectées)."
            )
        lignes = [
            f"Calibration prédiction/réalité — projet {project_id},"
            f" horizon {horizon_weeks} semaine(s), seuil H > {seuil:g}.",
            f"Points d'observation : {n}.",
            f"Matrice de confusion : VP={matrice.vp}, FP={matrice.fp},"
            f" FN={matrice.fn}, VN={matrice.vn}.",
            ligne_precision,
            ligne_rappel,
        ]
        if n < _MIN_POINTS_CONCLUSION:
            lignes.append(
                "Avertissement : échantillon trop petit pour conclure"
                f" ({n} point(s) < {_MIN_POINTS_CONCLUSION})."
            )
        return "\n".join(lignes)
