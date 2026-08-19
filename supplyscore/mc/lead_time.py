"""Simulation Monte Carlo des dates d'achevement propagees sur le DAG (E13, Lot 13.1).

PERT stochastique : la distribution de la date d'achevement de chaque noeud est
conditionnee par celles de ses fournisseurs. AUCUN raccourci analytique n'est
admis dans la propagation (le max de lognormales n'est PAS lognormale).

Modele (PLAN.md, phase E13) :

- **Lead time du noeud i** : ``L_i`` de famille configurable par noeud -

  - **lognormale (DEFAUT)** parametree PAR MOMENTS : pour moyenne
    ``m = lead_time_h`` et ecart-type ``s = lead_time_std_h`` (defaut
    ``0.25-m`` si None) : ``sigma^2_ln = ln(1 + s^2/m^2)``,
    ``mu_ln = ln(m) - sigma^2_ln/2`` ;
  - **normale tronquee a 0** - troncature PAR CLIP (``np.maximum(-, 0)``),
    choix documente : le rejet iteratif est exact mais de cout non borne ;
    le clip deplace la masse ``P(X < 0)`` sur ``{0}``, biais negligeable
    tant que ``m >> s`` et jamais optimiste (aucun lead time negatif) ;
  - **triangulaire** si les champs OPTIONNELS ``lead_time_min_h`` /
    ``lead_time_mode_h`` / ``lead_time_max_h`` sont tous presents - ces
    champs n'existent pas encore dans ``TimeKPIs`` (domain.models), ils
    sont lus via :func:`getattr` (None s'ils manquent) ;
  - **deterministe** si ``s == 0`` (apres application du defaut ``0.25-m``).

- **Recurrence en ORDRE TOPOLOGIQUE** (arcs nominaux, fournisseurs profonds
  d'abord) : ``S_i = max_{j dans Pred(i)} C_j`` (``t`` si aucun fournisseur) ;
  ``C_i = S_i + L_i-(1 - p_i) + R_i`` ou ``p_i`` est l'avancement du prochain
  jalon ACTIF du noeud (0 si aucun) et ``R_i = time.delay_h`` le temps
  de production perdu. ``L_i`` tire un cycle COMPLET : seule la part
  ``1 - p_i`` reste a parcourir (:meth:`SimulateurLeadTime._reste`), tandis
  que ``R_i`` s'AJOUTE sans mise a l'echelle (:meth:`SimulateurLeadTime._retard_h`).

- **Estimateur** : ``u_time_MC(i) = P(C_i > d_i) ~= (1/N)-Sigma_k 1[C_i^(k) > d_i]``
  ou ``d_i`` est la deadline en HEURES-PROJET du prochain jalon ACTIF du noeud
  (``(deadline_ts - t0_ts)/3600``), sinon ``kpis.time.deadline_h``, sinon
  None (pas de u_time pour ce noeud). IC95 : ``p +/- 1.96-sqrt(p(1-p)/N)``.

- **Tirages** : ``numpy.random.Generator(PCG64(graine))``, vectorises - un
  tableau ``(N,)`` par noeud, ``C = np.maximum.reduce([...]) + tirages``.
  ``N = 10 000`` par defaut (configurable 2 000..50 000, ValueError hors
  bornes) ; garde-fou memoire ``N x n_noeuds <= 5-10?`` sinon ValueError
  (le streaming par rangs viendra en E14 si besoin).

CHOIX DOCUMENTE pour l'instant courant ``t`` (heures-projet) : la simulation
repart de ``t`` - les noeuds RACINES (fournisseurs profonds, sans
predecesseur) demarrent a ``S = t`` (" les travaux restants commencent
maintenant "), et la recurrence ``S_i = max C_pred`` garantit ``C_i >= t``
partout. Consequence verifiable, fondement de la validation croisee
MC <-> erf : pour un noeud ISOLE dont le jalon actif est a l'avancement ``p``,
``P(t + L-(1 - p) > d) == survie analytique de L-(1 - p) au seuil (d - t)`` -
soit, a ``p = 0``, la survie de ``L`` elle-meme. Un noeud DEJA en retard
(``d_i <= t``) recoit ``u_time = 1.0`` exactement, sans passer par
l'estimateur.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from supplyscore.domain.milestones import Milestone, next_active_milestone
from supplyscore.domain.models import SupplyNode
from supplyscore.graph.repository import GraphRepository

#: Bornes inclusives du nombre de tirages N.
N_TIRAGES_MIN: int = 2_000
N_TIRAGES_MAX: int = 50_000

#: Garde-fou memoire : produit n_tirages x n_noeuds maximal (~400 Mo de float64).
BUDGET_MEMOIRE_MAX: float = 5e7

#: Familles utilisables comme DEFAUT global. Les familles " triangulaire " et " deterministe " ne s'imposent pas : elles sont DETECTEES d'apres les donnees du noeud (champs triangulaires presents, resp. s == 0).
FAMILLES_DEFAUT: tuple[str, ...] = ("lognormale", "normale")


@dataclass(frozen=True)
class LoiLeadTime:
    """Parametres resolus de la loi du lead time d'un noeud.

    Attributes:
        famille: "lognormale", "normale", "triangulaire" ou "deterministe".
        m: moyenne du lead time (heures) - lois lognormale, normale et
            deterministe (valeur exacte pour cette derniere).
        s: ecart-type du lead time (heures) - lois lognormale et normale.
        minimum: borne basse (heures) - loi triangulaire.
        mode: mode (heures) - loi triangulaire.
        maximum: borne haute (heures) - loi triangulaire.
    """

    famille: str
    m: float = 0.0
    s: float = 0.0
    minimum: float = 0.0
    mode: float = 0.0
    maximum: float = 0.0


def resoudre_loi(node: SupplyNode, famille_defaut: str = "lognormale") -> LoiLeadTime:
    """Detecte la famille de loi du lead time d'un noeud et resout ses parametres.

    Ordre de detection :

    1. **triangulaire** si ``lead_time_min_h``, ``lead_time_mode_h`` et
       ``lead_time_max_h`` sont tous presents (champs OPTIONNELS lus via
       :func:`getattr` - ils n'existent pas encore dans ``TimeKPIs``) ;
       exige ``min <= mode <= max`` (ValueError sinon) ; degenere en
       deterministe au mode si ``min == max`` ;
    2. **deterministe** si ``s == 0`` - ou ``s = lead_time_std_h`` si fourni,
       sinon ``0.25-m`` par defaut (donc ``m`` absent ou nul sans ecart-type
       explicite => deterministe). Un ``lead_time_h`` absent vaut 0.0 : le
       noeud n'ajoute aucun delai, son achevement egale son demarrage ;
    3. sinon **famille_defaut** ("lognormale" par defaut, "normale" pour
       forcer la normale tronquee a 0). La lognormale exige ``m > 0`` :
       ``m <= 0`` avec ``s > 0`` degenere en deterministe a ``max(m, 0)``.

    Args:
        node: noeud dont on lit ``kpis.time``.
        famille_defaut: famille appliquee au cas 3 (cf. :data:`FAMILLES_DEFAUT`).

    Returns:
        La loi resolue, prete pour :func:`tirer_lead_times`.

    Raises:
        ValueError: famille_defaut inconnue, ou bornes triangulaires
            incoherentes (``min <= mode <= max`` viole).
    """
    if famille_defaut not in FAMILLES_DEFAUT:
        raise ValueError(
            f"Famille de loi inconnue : {famille_defaut!r} (attendu : {FAMILLES_DEFAUT})"
        )
    tk = node.kpis.time
    lt_min = getattr(tk, "lead_time_min_h", None)
    lt_mode = getattr(tk, "lead_time_mode_h", None)
    lt_max = getattr(tk, "lead_time_max_h", None)
    if lt_min is not None and lt_mode is not None and lt_max is not None:
        if not lt_min <= lt_mode <= lt_max:
            raise ValueError(
                f"Bornes triangulaires incohérentes pour le nœud {node.id!r} : "
                f"min={lt_min}, mode={lt_mode}, max={lt_max} (attendu min <= mode <= max)"
            )
        if lt_min == lt_max:
            return LoiLeadTime("deterministe", m=lt_mode)
        return LoiLeadTime("triangulaire", minimum=lt_min, mode=lt_mode, maximum=lt_max)
    m = tk.lead_time_h if tk.lead_time_h is not None else 0.0
    s = tk.lead_time_std_h if tk.lead_time_std_h is not None else 0.25 * m
    if s <= 0.0:
        return LoiLeadTime("deterministe", m=max(m, 0.0))
    if famille_defaut == "lognormale":
        if m <= 0.0:
            return LoiLeadTime("deterministe", m=max(m, 0.0))
        return LoiLeadTime("lognormale", m=m, s=s)
    return LoiLeadTime("normale", m=m, s=s)


def tirer_lead_times(loi: LoiLeadTime, rng: np.random.Generator, n: int) -> NDArray[np.float64]:
    """Tire ``n`` realisations vectorisees du lead time selon la loi resolue.

    - **lognormale** par moments : ``sigma^2_ln = ln(1 + s^2/m^2)``,
      ``mu_ln = ln(m) - sigma^2_ln/2`` - la moyenne et l'ecart-type des tirages
      retrouvent (m, s) ;
    - **normale** tronquee a 0 par CLIP (cf. docstring du module) ;
    - **triangulaire** sur (minimum, mode, maximum) ;
    - **deterministe** : tableau constant a ``m`` (aucun alea consomme sur
      le generateur).

    Args:
        loi: loi resolue (cf. :func:`resoudre_loi`).
        rng: generateur ``numpy.random.Generator`` partage de la simulation.
        n: nombre de tirages.

    Returns:
        Tableau ``(n,)`` de lead times en heures, tous >= 0.

    Raises:
        ValueError: famille de loi inconnue dans ``loi``.
    """
    if loi.famille == "lognormale":
        var_ln = math.log(1.0 + (loi.s / loi.m) ** 2)
        mu_ln = math.log(loi.m) - var_ln / 2.0
        return rng.lognormal(mean=mu_ln, sigma=math.sqrt(var_ln), size=n)
    if loi.famille == "normale":
        return np.maximum(rng.normal(loc=loi.m, scale=loi.s, size=n), 0.0)
    if loi.famille == "triangulaire":
        return rng.triangular(left=loi.minimum, mode=loi.mode, right=loi.maximum, size=n)
    if loi.famille == "deterministe":
        return np.full(n, loi.m, dtype=np.float64)
    raise ValueError(f"Famille de loi inconnue : {loi.famille!r}")


@dataclass(frozen=True)
class ResultatMC:
    """Resultat immuable d'une simulation Monte Carlo des dates d'achevement.

    Attributes:
        n_tirages: nombre de tirages N utilises.
        graine: graine du generateur PCG64 (None = entropie systeme).
        u_time: par noeud, ``P(C_i > d_i)`` estimee - None si le noeud n'a
            aucune deadline (ni jalon actif, ni ``deadline_h``).
        ic95: par noeud, demi-largeur de l'IC95 ``1.96-sqrt(p(1-p)/N)`` ;
            0.0 pour les u_time a None ou forces (noeud deja en retard).
        completion_quantiles: par noeud, quantiles des dates d'achevement
            simulees ``{q: heures-projet}``, ex. ``{0.5: ..., 0.9: ...}``.
    """

    n_tirages: int
    graine: int | None
    u_time: dict[str, float | None]
    ic95: dict[str, float]
    completion_quantiles: dict[str, dict[float, float]]


class SimulateurLeadTime:
    """Simulateur Monte Carlo des dates d'achevement propagees sur le DAG.

    Chaque appel a :meth:`executer` repart d'un generateur frais
    ``Generator(PCG64(graine))`` : a graine egale, les resultats sont
    reproductibles bit a bit.
    """

    def __init__(
        self,
        repo: GraphRepository,
        n_tirages: int = 10_000,
        graine: int | None = None,
        famille: str = "lognormale",
    ) -> None:
        """Configure le simulateur.

        Args:
            repo: depot de graphe (ordre topologique et predecesseurs NOMINAUX).
            n_tirages: nombre de tirages N, dans [2 000, 50 000].
            graine: graine PCG64 (None = entropie systeme, non reproductible).
            famille: famille de loi par DEFAUT pour les noeuds sans champs
                triangulaires et d'ecart-type non nul - "lognormale" (defaut)
                ou "normale" (override global, utile aux tests de validation
                croisee). Cf. :func:`resoudre_loi`.

        Raises:
            ValueError: ``n_tirages`` hors bornes ou ``famille`` inconnue.
        """
        if not N_TIRAGES_MIN <= n_tirages <= N_TIRAGES_MAX:
            raise ValueError(
                f"n_tirages doit être dans [{N_TIRAGES_MIN}, {N_TIRAGES_MAX}], reçu {n_tirages}"
            )
        if famille not in FAMILLES_DEFAUT:
            raise ValueError(f"Famille de loi inconnue : {famille!r} (attendu : {FAMILLES_DEFAUT})")
        self._repo = repo
        self.n_tirages = n_tirages
        self.graine = graine
        self.famille = famille

    # Echeances

    @staticmethod
    def _deadline_h(
        node: SupplyNode, milestones: list[Milestone] | None, t0_ts: float
    ) -> float | None:
        """Deadline d_i du noeud en heures-projet, ou None si aucune echeance.

        Priorite au prochain jalon ACTIF : ``(deadline_ts - t0_ts)/3600`` ;
        sinon ``kpis.time.deadline_h`` ; sinon None (pas de u_time).

        Args:
            node: noeud evalue.
            milestones: jalons du noeud (None ou vide = aucun).
            t0_ts: origine temporelle du projet (epoch s).

        Returns:
            Echeance en heures depuis t0, ou None.
        """
        m_star = next_active_milestone(milestones) if milestones else None
        if m_star is not None:
            return (m_star.deadline_ts - t0_ts) / 3600.0
        return node.kpis.time.deadline_h

    @staticmethod
    def _retard_h(node: SupplyNode) -> float:
        """Temps de production perdu et non rattrape (``time.delay_h``).

        ADDITIF a l'achevement, jamais mis a l'echelle de l'avancement : un
        arret de quatre semaines coute quatre semaines qu'on soit a 10 % ou a
        90 % du jalon. C'est le canal par lequel les chocs de CAPACITE (panne,
        accident, greve, rupture, cyber) atteignent P(jalon rate) - cf.
        :func:`supplyscore.domain.events._arret_impact`.

        Args:
            node: noeud evalue.

        Returns:
            Le retard residuel en heures, >= 0 (0.0 si le KPI est absent).
        """
        return max(node.kpis.time.delay_h or 0.0, 0.0)

    @staticmethod
    def _reste(milestones: list[Milestone] | None) -> float:
        """Part du cycle qu'il reste a parcourir sur le jalon actif, dans [0, 1].

        Le lead time tire est la duree d'un cycle COMPLET. Un jalon avance a
        ``p`` n'a plus que ``1 - p`` de ce cycle devant lui : sans ce facteur,
        tout noeud dont le lead time nominal depasse sa marge est declare perdu
        d'avance quel que soit son avancement. Meme correction que
        :meth:`~supplyscore.core.ur_model.UrModel.u_base_jalon` et que
        ``ForecastService`` - les trois estimateurs de P(jalon rate) doivent
        rester d'accord.

        Args:
            milestones: jalons du noeud (None ou vide = aucun).

        Returns:
            ``1 - progress`` du prochain jalon ACTIF, ou 1.0 s'il n'y en a pas.
        """
        m_star = next_active_milestone(milestones) if milestones else None
        if m_star is None:
            return 1.0
        return min(max(1.0 - m_star.progress, 0.0), 1.0)

    # Simulation

    def executer(
        self,
        t: float = 0.0,
        milestones_par_noeud: dict[str, list[Milestone]] | None = None,
        t0_ts: float = 0.0,
        quantiles: tuple[float, ...] = (0.5, 0.9),
    ) -> ResultatMC:
        """Simule les dates d'achevement de tout le graphe et estime u_time.

        Recurrence vectorisee en ordre topologique (fournisseurs profonds
        d'abord, arcs nominaux seuls) : ``S_i = max_{j dans Pred(i)} C_j`` -
        ``t`` pour les racines, cf. le CHOIX DOCUMENTE du module - puis
        ``C_i = S_i + L_i`` avec un tableau ``(N,)`` par noeud.

        Args:
            t: instant courant en heures-projet ; les racines demarrent a t,
                et tout noeud dont la deadline est deja passee (``d_i <= t``)
                recoit u_time = 1.0 exactement.
            milestones_par_noeud: jalons par id de noeud - fournit la deadline
                v2 (prochain jalon ACTIF) ; None ou id absent = repli sur
                ``kpis.time.deadline_h``.
            t0_ts: origine temporelle du projet (epoch s) pour convertir les
                ``deadline_ts`` des jalons en heures-projet.
            quantiles: ordres des quantiles d'achevement a restituer,
                chacun dans [0, 1].

        Returns:
            Le :class:`ResultatMC` (u_time, IC95, quantiles d'achevement).

        Raises:
            ValueError: budget memoire ``N x n_noeuds > 5-10?`` depasse, ordre
                de quantile hors [0, 1], ou loi de noeud invalide
                (cf. :func:`resoudre_loi`).
        """
        ordre = self._repo.topological_order()
        if self.n_tirages * len(ordre) > BUDGET_MEMOIRE_MAX:
            raise ValueError(
                f"Budget mémoire dépassé : n_tirages × n_nœuds = "
                f"{self.n_tirages} × {len(ordre)} = {self.n_tirages * len(ordre):.3g} "
                f"> {BUDGET_MEMOIRE_MAX:.0e} — réduisez n_tirages ou découpez le "
                f"graphe (le streaming par rangs arrivera en E14)."
            )
        for q in quantiles:
            if not 0.0 <= q <= 1.0:
                raise ValueError(f"Ordre de quantile hors [0, 1] : {q}")
        milestones_par_noeud = milestones_par_noeud or {}
        rng = np.random.Generator(np.random.PCG64(self.graine))
        depart_racine: NDArray[np.float64] = np.full(self.n_tirages, float(t))
        achevements: dict[str, NDArray[np.float64]] = {}
        u_time: dict[str, float | None] = {}
        ic95: dict[str, float] = {}
        completion_quantiles: dict[str, dict[float, float]] = {}
        for node_id in ordre:
            node = self._repo.get_node(node_id)
            if node is None:  # pragma: no cover - l'id provient du tri topologique
                raise KeyError(f"Nœud inconnu : {node_id!r}")
            preds = self._repo.predecessors(node_id)
            if preds:
                depart = np.maximum.reduce([achevements[p.id] for p in preds])
            else:
                depart = depart_racine
            loi = resoudre_loi(node, self.famille)
            jalons = milestones_par_noeud.get(node_id)
            # Seul le TRAVAIL RESTANT du jalon actif est devant nous (cf. _reste).
            c = (
                depart
                + tirer_lead_times(loi, rng, self.n_tirages) * self._reste(jalons)
                + self._retard_h(node)
            )
            achevements[node_id] = c
            completion_quantiles[node_id] = {float(q): float(np.quantile(c, q)) for q in quantiles}
            d = self._deadline_h(node, jalons, t0_ts)
            if d is None:
                u_time[node_id] = None  # pas d'echeance : pas de u_time
                ic95[node_id] = 0.0
            elif d <= t:
                u_time[node_id] = 1.0  # retard avere : force, hors estimateur
                ic95[node_id] = 0.0
            else:
                p = float(np.mean(c > d))
                u_time[node_id] = p
                ic95[node_id] = 1.96 * math.sqrt(p * (1.0 - p) / self.n_tirages)
        return ResultatMC(
            n_tirages=self.n_tirages,
            graine=self.graine,
            u_time=u_time,
            ic95=ic95,
            completion_quantiles=completion_quantiles,
        )
