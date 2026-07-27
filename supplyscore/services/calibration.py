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
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

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


def _rangs_moyens(valeurs: NDArray[np.float64]) -> NDArray[np.float64]:
    """Rangs moyens (1-indexés) de ``valeurs``, ex æquo partageant leur rang.

    Implémente le rang « fractional » standard (identique à
    ``scipy.stats.rankdata(method="average")``) sans dépendance
    supplémentaire : les valeurs égales reçoivent la moyenne des rangs
    bruts qu'elles occuperaient triées.

    Args:
        valeurs: tableau 1D de valeurs (peut contenir des ex æquo).

    Returns:
        Un tableau de même longueur, rang moyen par position d'origine.
    """
    ordre = np.argsort(valeurs, kind="mergesort")
    valeurs_triees = valeurs[ordre]
    n = len(valeurs)
    rangs_bruts = np.arange(1, n + 1, dtype=np.float64)
    frontieres = np.zeros(n, dtype=np.bool_)
    frontieres[1:] = valeurs_triees[1:] != valeurs_triees[:-1]
    groupes = np.cumsum(frontieres)
    sommes = np.bincount(groupes, weights=rangs_bruts)
    comptes = np.bincount(groupes)
    rangs_par_groupe = sommes / comptes
    rangs_tries = rangs_par_groupe[groupes]
    rangs: NDArray[np.float64] = np.empty(n, dtype=np.float64)
    rangs[ordre] = rangs_tries
    return rangs


def issues_defavorables(
    *,
    node: SupplyNode,
    debut_ts: float,
    fin_ts: float,
    milestones: list[Milestone],
    now_ts: float,
    evenements: Iterable[Mapping[str, Any]],
) -> list[str]:
    """Issues défavorables constatées dans la fenêtre ``[debut_ts, fin_ts[``.

    Définition FIGÉE du lot 11.1 (voir le docstring du module), extraite ici
    en fonction PURE et réutilisable — notamment par
    :class:`~supplyscore.services.interventions.InterventionJournal` pour le
    résultat opérationnel des interventions (docs/modele_mathematique.md,
    §13) — de sorte qu'il n'existe qu'UNE SEULE définition de la rupture
    dans tout le système. :meth:`CalibrationService._causes` délègue à cette
    fonction pour les fenêtres ISO-semaine qu'elle calcule elle-même.

    Args:
        node: nœud observé (son statut COURANT sert de proxy pour le critère
            « nœud abandonné », limite documentée ci-dessous).
        debut_ts: borne inférieure de la fenêtre, incluse (epoch s).
        fin_ts: borne supérieure de la fenêtre, EXCLUE (epoch s).
        milestones: jalons courants du nœud (ordre quelconque).
        now_ts: instant courant de l'horloge du projet — borne les jalons
            ACTIVE dont l'échéance est dans la fenêtre mais qui pourrait
            encore être livrée si ``now_ts`` ne l'a pas encore dépassée.
        evenements: lignes d'événements CANDIDATES (même forme que
            :meth:`~supplyscore.data.db.ClientDatabase.list_events` — dicts
            avec ``occurred_at``, ``reverted_at``, ``event_type``,
            ``params_json``) ; seules celles dont ``occurred_at`` tombe dans
            la fenêtre sont retenues, les autres sont ignorées (l'appelant
            peut donc fournir un sur-ensemble sans filtrage préalable).

    Returns:
        Les descriptions françaises des issues constatées (``[]`` sinon) :

        (a) un jalon dont l'échéance tombe dans la fenêtre est ABANDONED, ou
            ACTIVE avec l'échéance dépassée à la fin de la fenêtre (bornée
            par ``now_ts`` si la fenêtre déborde sur le futur) ;
        (b) le statut COURANT du nœud est ABANDONED (proxy — l'horodatage du
            passage n'est pas persisté, limite documentée) ;
        (c) un événement non annulé (``reverted_at`` NULL), dont
            ``occurred_at`` tombe dans la fenêtre, de gravité ``"critique"``
            ou ``"defaut"``.
    """
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

    # (b) nœud abandonné — l'horodatage du passage n'étant pas persisté, le
    # statut COURANT sert de proxy (limite documentée dans le module).
    if node.status is TaskStatus.ABANDONED:
        causes.append(
            "nœud au statut « abandonné » (statut courant utilisé comme proxy :"
            " horodatage du passage indisponible)"
        )

    # (c) événement non annulé de gravité critique/défaut dans la fenêtre.
    for row in evenements:
        if not debut_ts <= row["occurred_at"] < fin_ts:
            continue
        if row["reverted_at"] is not None:
            continue  # événement annulé : déclaré par erreur
        gravite = json.loads(row["params_json"]).get("gravite")
        if gravite in _GRAVITES_DEFAVORABLES:
            causes.append(
                f"événement {row['event_type']} de gravité « {gravite} »"
                f" (semaine {iso_week(row['occurred_at'])})"
            )
    return causes


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


def _score_youden(matrice: ConfusionMatrix) -> float | None:
    """Indice de Youden (sensibilité + spécificité − 1) d'une matrice de confusion.

    Args:
        matrice: matrice de confusion à un seuil donné.

    Returns:
        L'indice, ou None si le rappel (sensibilité) ou la spécificité n'est
        pas défini (classe unique parmi les points considérés).
    """
    if matrice.rappel is None:
        return None
    denominateur_specificite = matrice.vn + matrice.fp
    if denominateur_specificite == 0:
        return None
    specificite = matrice.vn / denominateur_specificite
    return matrice.rappel + specificite - 1.0


def _score_f1(matrice: ConfusionMatrix) -> float | None:
    """Score F1 (moyenne harmonique précision/rappel) d'une matrice de confusion.

    Args:
        matrice: matrice de confusion à un seuil donné.

    Returns:
        Le score F1, ou None si la précision ou le rappel n'est pas défini.
    """
    if matrice.precision is None or matrice.rappel is None:
        return None
    denominateur = matrice.precision + matrice.rappel
    if denominateur == 0:
        return None
    return 2.0 * matrice.precision * matrice.rappel / denominateur


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

        Calcule la fenêtre ISO-semaine puis délègue à la définition FIGÉE et
        partagée :func:`issues_defavorables` (jalon raté, nœud abandonné,
        événement critique/défaut) — voir son docstring pour le détail des
        trois critères. Les événements sont rassemblés semaine par semaine
        (sert l'index ``idx_events_node_week``) puis filtrés par la fonction
        partagée sur leur ``occurred_at`` réel.

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
        client = self._service.client_db(node.id)
        evenements: list[Mapping[str, Any]] = []
        for offset in range(1, horizon_weeks + 1):
            semaine_fenetre = _semaine_decalee(semaine, offset)
            evenements.extend(client.list_events(node.id, semaine_fenetre))
        return issues_defavorables(
            node=node,
            debut_ts=debut_ts,
            fin_ts=fin_ts,
            milestones=milestones,
            now_ts=now_ts,
            evenements=evenements,
        )

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

    # -- discrimination et calibration probabiliste --

    def auc(self, points: list[OutcomePoint]) -> float | None:
        """Aire sous la courbe ROC, via la statistique de rang de Mann-Whitney.

        Équivaut à la probabilité qu'un point avec issue défavorable ait un H
        strictement plus élevé qu'un point sans issue, tirés au hasard parmi
        les points exploitables (les ex æquo comptant pour moitié) — calculée
        à partir de la somme des rangs moyens de H chez les points positifs,
        sans balayer de seuils.

        Args:
            points: points d'observation (typiquement :meth:`outcomes`). Les
                points sans H (None) sont ignorés.

        Returns:
            L'AUC dans [0, 1], ou None si une seule classe (positive ou
            négative) est présente parmi les points exploitables.
        """
        utilisables = [point for point in points if point.hidden_risk is not None]
        if not utilisables:
            return None
        h: NDArray[np.float64] = np.array(
            [point.hidden_risk for point in utilisables], dtype=np.float64
        )
        positifs: NDArray[np.bool_] = np.array(
            [point.issue_defavorable for point in utilisables], dtype=np.bool_
        )
        n_pos = int(positifs.sum())
        n_neg = len(utilisables) - n_pos
        if n_pos == 0 or n_neg == 0:
            return None
        rangs = _rangs_moyens(h)
        somme_rangs_positifs = float(rangs[positifs].sum())
        return (somme_rangs_positifs - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)

    def auc_ci(
        self, points: list[OutcomePoint], n_boot: int = 1000, seed: int = 0
    ) -> tuple[float, float] | None:
        """Intervalle de confiance à 95 % de l'AUC, par bootstrap en grappes de nœuds.

        Chaque tirage rééchantillonne AVEC REMISE les identifiants de nœuds
        distincts (même effectif de nœuds que l'original), préservant ainsi
        la corrélation entre les points d'un même nœud, puis concatène les
        points des nœuds tirés et recalcule l'AUC (:meth:`auc`) ; les tirages
        où une seule classe subsiste sont ignorés. Déterministe à ``seed``
        fixé (générateur numpy dédié).

        Args:
            points: points d'observation (typiquement :meth:`outcomes`). Les
                points sans H (None) sont ignorés.
            n_boot: nombre de tirages bootstrap (défaut 1000).
            seed: graine du générateur, pour la reproductibilité.

        Returns:
            Le couple (percentile 2.5, percentile 97.5) des AUC bootstrap, ou
            None si moins de deux tirages exploitables.
        """
        utilisables = [point for point in points if point.hidden_risk is not None]
        if not utilisables:
            return None
        points_par_noeud: dict[str, list[OutcomePoint]] = defaultdict(list)
        for point in utilisables:
            points_par_noeud[point.node_id].append(point)
        noeuds = np.array(sorted(points_par_noeud), dtype=object)
        rng = np.random.default_rng(seed)
        aucs: list[float] = []
        for _ in range(n_boot):
            tirage = rng.choice(noeuds, size=len(noeuds), replace=True)
            echantillon = [point for noeud_id in tirage for point in points_par_noeud[noeud_id]]
            auc_tirage = self.auc(echantillon)
            if auc_tirage is not None:
                aucs.append(auc_tirage)
        if len(aucs) < 2:
            return None
        bas, haut = np.percentile(np.array(aucs, dtype=np.float64), [2.5, 97.5])
        return float(bas), float(haut)

    def pr_auc(self, points: list[OutcomePoint]) -> float | None:
        """Précision moyenne (average precision), aire sous la courbe précision-rappel.

        Intégration en escalier de la courbe précision-rappel obtenue en
        balayant les valeurs de H par ordre décroissant, les ex æquo étant
        regroupés au même palier avant de calculer précision et rappel
        (définition « sklearn-style » de l'average precision, insensible à
        l'ordre de tri arbitraire des ex æquo).

        Args:
            points: points d'observation (typiquement :meth:`outcomes`). Les
                points sans H (None) sont ignorés.

        Returns:
            L'average precision dans [0, 1], ou None si aucune issue
            défavorable n'est présente parmi les points exploitables.
        """
        utilisables = [point for point in points if point.hidden_risk is not None]
        if not utilisables:
            return None
        h: NDArray[np.float64] = np.array(
            [point.hidden_risk for point in utilisables], dtype=np.float64
        )
        y: NDArray[np.float64] = np.array(
            [float(point.issue_defavorable) for point in utilisables], dtype=np.float64
        )
        n_pos = float(y.sum())
        if n_pos == 0:
            return None
        ordre = np.argsort(-h, kind="mergesort")
        h_trie = h[ordre]
        y_trie = y[ordre]
        tp_cumule = np.cumsum(y_trie)
        fp_cumule = np.cumsum(1.0 - y_trie)
        n = len(h_trie)
        palier: NDArray[np.bool_] = np.empty(n, dtype=np.bool_)
        palier[:-1] = h_trie[:-1] != h_trie[1:]
        palier[-1] = True
        tp_palier = tp_cumule[palier]
        fp_palier = fp_cumule[palier]
        precision = tp_palier / (tp_palier + fp_palier)
        rappel = tp_palier / n_pos
        rappel_precedent = np.concatenate(([0.0], rappel[:-1]))
        return float(np.sum((rappel - rappel_precedent) * precision))

    def brier(self, points: list[OutcomePoint]) -> tuple[float, float] | None:
        """Score de Brier de H contre l'issue constatée, et sa skill score de climatologie.

        Le score de Brier est l'erreur quadratique moyenne de H comme
        prévision probabiliste de l'issue défavorable (0 = parfait). La
        climatologie prédit pour CHAQUE point le taux de base observé
        (moyenne des issues, prévision constante) ; la skill score
        ``1 − brier / brier_climatologie`` mesure le gain de H par rapport à
        cette référence triviale (positif = H fait mieux que la
        climatologie, négatif = moins bien).

        Args:
            points: points d'observation (typiquement :meth:`outcomes`). Les
                points sans H (None) sont ignorés.

        Returns:
            Le couple (score de Brier, skill score), ou None si aucun point
            n'est exploitable. Convention : skill score à 0.0 si la
            climatologie est déjà parfaite (brier climatologique nul, taux
            de base à 0 ou 1).
        """
        utilisables = [point for point in points if point.hidden_risk is not None]
        if not utilisables:
            return None
        h: NDArray[np.float64] = np.array(
            [point.hidden_risk for point in utilisables], dtype=np.float64
        )
        y: NDArray[np.float64] = np.array(
            [float(point.issue_defavorable) for point in utilisables], dtype=np.float64
        )
        brier_score = float(np.mean((h - y) ** 2))
        taux_base = float(y.mean())
        brier_climatologie = float(np.mean((taux_base - y) ** 2))
        skill = 1.0 - brier_score / brier_climatologie if brier_climatologie > 0 else 0.0
        return brier_score, skill

    def sweep(
        self, points: list[OutcomePoint], seuils: list[float] | None = None
    ) -> list[ConfusionMatrix]:
        """Matrices de confusion balayées sur une liste de seuils.

        Args:
            points: points d'observation (typiquement :meth:`outcomes`).
            seuils: seuils à évaluer (:meth:`confusion` pour chacun) ; par
                défaut les valeurs de H distinctes observées parmi les
                points (triées croissant), soit le balayage exhaustif des
                seuils qui changent effectivement la matrice de confusion.

        Returns:
            Une :class:`ConfusionMatrix` par seuil, dans l'ordre de
            ``seuils`` (ou de H croissant si par défaut).
        """
        valeurs = (
            seuils
            if seuils is not None
            else sorted({point.hidden_risk for point in points if point.hidden_risk is not None})
        )
        return [self.confusion(points, seuil=valeur) for valeur in valeurs]

    def seuil_optimal(
        self, points: list[OutcomePoint], critere: str = "youden"
    ) -> tuple[float, ConfusionMatrix] | None:
        """Seuil de décision maximisant un critère, parmi les seuils observés.

        Balaie les valeurs de H distinctes (:meth:`sweep`, seuils par
        défaut) et retient celle qui maximise le critère choisi :
        ``"youden"`` (sensibilité + spécificité − 1) ou ``"f1"`` (moyenne
        harmonique précision/rappel). En cas d'égalité, le premier seuil
        rencontré est conservé (le plus petit, l'ordre de :meth:`sweep` par
        défaut étant croissant).

        Args:
            points: points d'observation (typiquement :meth:`outcomes`).
            critere: ``"youden"`` ou ``"f1"``.

        Returns:
            Le couple (seuil optimal, sa :class:`ConfusionMatrix`), ou None
            si le critère n'est défini pour aucun seuil (classe unique parmi
            les points exploitables).

        Raises:
            ValueError: si ``critere`` n'est ni ``"youden"`` ni ``"f1"``.
        """
        if critere not in ("youden", "f1"):
            raise ValueError(f"critère inconnu : {critere!r} (attendu « youden » ou « f1 »)")
        calcul_score: Callable[[ConfusionMatrix], float | None] = (
            _score_youden if critere == "youden" else _score_f1
        )
        meilleur_score: float | None = None
        meilleure_matrice: ConfusionMatrix | None = None
        for matrice in self.sweep(points):
            score = calcul_score(matrice)
            if score is None:
                continue
            if meilleur_score is None or score > meilleur_score:
                meilleur_score = score
                meilleure_matrice = matrice
        if meilleure_matrice is None:
            return None
        return meilleure_matrice.seuil, meilleure_matrice

    def summary(self, project_id: str, horizon_weeks: int = 4, seuil: float = 0.5) -> str:
        """Résumé français de la calibration du projet, prudence statistique incluse.

        Construit les points (:meth:`outcomes`), la matrice (:meth:`confusion`)
        puis restitue : nombre de points, matrice, précision et rappel avec
        leurs effectifs, AUC avec son IC95 bootstrap (:meth:`auc`,
        :meth:`auc_ci`), score de Brier et skill score (:meth:`brier`), seuil
        optimal au sens de Youden avec sa précision/son rappel
        (:meth:`seuil_optimal`), et un avertissement explicite (« échantillon
        trop petit pour conclure ») sous :data:`_MIN_POINTS_CONCLUSION` points.

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
        auc_valeur = self.auc(points)
        if auc_valeur is None:
            ligne_auc = (
                "AUC (aire sous la courbe ROC) : non définie"
                " (classe unique ou aucun point exploitable)."
            )
        else:
            ic = self.auc_ci(points)
            ic_txt = f"[{ic[0]:.2f}, {ic[1]:.2f}]" if ic is not None else "non calculable"
            ligne_auc = f"AUC : {auc_valeur:.2f} (IC95 bootstrap {ic_txt})."
        brier_resultat = self.brier(points)
        if brier_resultat is None:
            ligne_brier = "Score de Brier : non défini (aucun point exploitable)."
        else:
            brier_score, skill = brier_resultat
            ligne_brier = (
                f"Score de Brier : {brier_score:.3f} (skill score vs climatologie : {skill:.2f})."
            )
        seuil_opt = self.seuil_optimal(points, critere="youden")
        if seuil_opt is None:
            ligne_seuil_opt = (
                "Seuil optimal (Youden) : non défini (classe unique ou aucun point exploitable)."
            )
        else:
            valeur_seuil, matrice_opt = seuil_opt
            precision_opt_txt = (
                f"{matrice_opt.precision:.2f}"
                if matrice_opt.precision is not None
                else "non définie"
            )
            rappel_opt_txt = (
                f"{matrice_opt.rappel:.2f}" if matrice_opt.rappel is not None else "non défini"
            )
            ligne_seuil_opt = (
                f"Seuil optimal (Youden) : H > {valeur_seuil:g}"
                f" (précision {precision_opt_txt}, rappel {rappel_opt_txt})."
            )
        lignes = [
            f"Calibration prédiction/réalité — projet {project_id},"
            f" horizon {horizon_weeks} semaine(s), seuil H > {seuil:g}.",
            f"Points d'observation : {n}.",
            f"Matrice de confusion : VP={matrice.vp}, FP={matrice.fp},"
            f" FN={matrice.fn}, VN={matrice.vn}.",
            ligne_precision,
            ligne_rappel,
            ligne_auc,
            ligne_brier,
            ligne_seuil_opt,
        ]
        if n < _MIN_POINTS_CONCLUSION:
            lignes.append(
                "Avertissement : échantillon trop petit pour conclure"
                f" ({n} point(s) < {_MIN_POINTS_CONCLUSION})."
            )
        return "\n".join(lignes)
