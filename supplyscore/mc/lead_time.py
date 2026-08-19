"""Simulation Monte Carlo des dates d'achèvement propagées sur le DAG (E13, Lot 13.1).

PERT stochastique : la distribution de la date d'achèvement de chaque nœud est
conditionnée par celles de ses fournisseurs. AUCUN raccourci analytique n'est
admis dans la propagation (le max de lognormales n'est PAS lognormale).

Modèle (PLAN.md, phase E13) :

- **Lead time du nœud i** : ``L_i`` de famille configurable par nœud —

  - **lognormale (DÉFAUT)** paramétrée PAR MOMENTS : pour moyenne
    ``m = lead_time_h`` et écart-type ``s = lead_time_std_h`` (défaut
    ``0.25·m`` si None) : ``σ²_ln = ln(1 + s²/m²)``,
    ``μ_ln = ln(m) − σ²_ln/2`` ;
  - **normale tronquée à 0** — troncature PAR CLIP (``np.maximum(·, 0)``),
    choix documenté : le rejet itératif est exact mais de coût non borné ;
    le clip déplace la masse ``P(X < 0)`` sur ``{0}``, biais négligeable
    tant que ``m ≫ s`` et jamais optimiste (aucun lead time négatif) ;
  - **triangulaire** si les champs OPTIONNELS ``lead_time_min_h`` /
    ``lead_time_mode_h`` / ``lead_time_max_h`` sont tous présents — ces
    champs n'existent pas encore dans ``TimeKPIs`` (domain.models), ils
    sont lus via :func:`getattr` (None s'ils manquent) ;
  - **déterministe** si ``s == 0`` (après application du défaut ``0.25·m``).

- **Récurrence en ORDRE TOPOLOGIQUE** (arcs nominaux, fournisseurs profonds
  d'abord) : ``S_i = max_{j∈Pred(i)} C_j`` (``t`` si aucun fournisseur) ;
  ``C_i = S_i + L_i·(1 − p_i)`` où ``p_i`` est l'avancement du prochain jalon
  ACTIF du nœud (0 si aucun). ``L_i`` tire un cycle COMPLET : seule la part
  ``1 − p_i`` reste à parcourir (cf. :meth:`SimulateurLeadTime._reste`).

- **Estimateur** : ``u_time_MC(i) = P(C_i > d_i) ≈ (1/N)·Σ_k 1[C_i^(k) > d_i]``
  où ``d_i`` est la deadline en HEURES-PROJET du prochain jalon ACTIF du nœud
  (``(deadline_ts − t0_ts)/3600``), sinon ``kpis.time.deadline_h``, sinon
  None (pas de u_time pour ce nœud). IC95 : ``p̂ ± 1.96·√(p̂(1−p̂)/N)``.

- **Tirages** : ``numpy.random.Generator(PCG64(graine))``, vectorisés — un
  tableau ``(N,)`` par nœud, ``C = np.maximum.reduce([...]) + tirages``.
  ``N = 10 000`` par défaut (configurable 2 000..50 000, ValueError hors
  bornes) ; garde-fou mémoire ``N × n_nœuds <= 5·10⁷`` sinon ValueError
  (le streaming par rangs viendra en E14 si besoin).

CHOIX DOCUMENTÉ pour l'instant courant ``t`` (heures-projet) : la simulation
repart de ``t`` — les nœuds RACINES (fournisseurs profonds, sans
prédécesseur) démarrent à ``S = t`` (« les travaux restants commencent
maintenant »), et la récurrence ``S_i = max C_pred`` garantit ``C_i >= t``
partout. Conséquence vérifiable, fondement de la validation croisée
MC ↔ erf : pour un nœud ISOLÉ dont le jalon actif est à l'avancement ``p``,
``P(t + L·(1 − p) > d) == survie analytique de L·(1 − p) au seuil (d − t)`` —
soit, à ``p = 0``, la survie de ``L`` elle-même. Un nœud DÉJÀ en retard
(``d_i <= t``) reçoit ``u_time = 1.0`` exactement, sans passer par
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

#: Garde-fou mémoire : produit n_tirages × n_nœuds maximal (~400 Mo de float64).
BUDGET_MEMOIRE_MAX: float = 5e7

#: Familles utilisables comme DÉFAUT global. Les familles « triangulaire » et
#: « deterministe » ne s'imposent pas : elles sont DÉTECTÉES d'après les
#: données du nœud (champs triangulaires présents, resp. s == 0).
FAMILLES_DEFAUT: tuple[str, ...] = ("lognormale", "normale")


@dataclass(frozen=True)
class LoiLeadTime:
    """Paramètres résolus de la loi du lead time d'un nœud.

    Attributes:
        famille: "lognormale", "normale", "triangulaire" ou "deterministe".
        m: moyenne du lead time (heures) — lois lognormale, normale et
            déterministe (valeur exacte pour cette dernière).
        s: écart-type du lead time (heures) — lois lognormale et normale.
        minimum: borne basse (heures) — loi triangulaire.
        mode: mode (heures) — loi triangulaire.
        maximum: borne haute (heures) — loi triangulaire.
    """

    famille: str
    m: float = 0.0
    s: float = 0.0
    minimum: float = 0.0
    mode: float = 0.0
    maximum: float = 0.0


def resoudre_loi(node: SupplyNode, famille_defaut: str = "lognormale") -> LoiLeadTime:
    """Détecte la famille de loi du lead time d'un nœud et résout ses paramètres.

    Ordre de détection :

    1. **triangulaire** si ``lead_time_min_h``, ``lead_time_mode_h`` et
       ``lead_time_max_h`` sont tous présents (champs OPTIONNELS lus via
       :func:`getattr` — ils n'existent pas encore dans ``TimeKPIs``) ;
       exige ``min <= mode <= max`` (ValueError sinon) ; dégénère en
       déterministe au mode si ``min == max`` ;
    2. **déterministe** si ``s == 0`` — où ``s = lead_time_std_h`` si fourni,
       sinon ``0.25·m`` par défaut (donc ``m`` absent ou nul sans écart-type
       explicite ⇒ déterministe). Un ``lead_time_h`` absent vaut 0.0 : le
       nœud n'ajoute aucun délai, son achèvement égale son démarrage ;
    3. sinon **famille_defaut** ("lognormale" par défaut, "normale" pour
       forcer la normale tronquée à 0). La lognormale exige ``m > 0`` :
       ``m <= 0`` avec ``s > 0`` dégénère en déterministe à ``max(m, 0)``.

    Args:
        node: nœud dont on lit ``kpis.time``.
        famille_defaut: famille appliquée au cas 3 (cf. :data:`FAMILLES_DEFAUT`).

    Returns:
        La loi résolue, prête pour :func:`tirer_lead_times`.

    Raises:
        ValueError: famille_defaut inconnue, ou bornes triangulaires
            incohérentes (``min <= mode <= max`` violé).
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
    """Tire ``n`` réalisations vectorisées du lead time selon la loi résolue.

    - **lognormale** par moments : ``σ²_ln = ln(1 + s²/m²)``,
      ``μ_ln = ln(m) − σ²_ln/2`` — la moyenne et l'écart-type des tirages
      retrouvent (m, s) ;
    - **normale** tronquée à 0 par CLIP (cf. docstring du module) ;
    - **triangulaire** sur (minimum, mode, maximum) ;
    - **deterministe** : tableau constant à ``m`` (aucun aléa consommé sur
      le générateur).

    Args:
        loi: loi résolue (cf. :func:`resoudre_loi`).
        rng: générateur ``numpy.random.Generator`` partagé de la simulation.
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
    """Résultat immuable d'une simulation Monte Carlo des dates d'achèvement.

    Attributes:
        n_tirages: nombre de tirages N utilisés.
        graine: graine du générateur PCG64 (None = entropie système).
        u_time: par nœud, ``P(C_i > d_i)`` estimée — None si le nœud n'a
            aucune deadline (ni jalon actif, ni ``deadline_h``).
        ic95: par nœud, demi-largeur de l'IC95 ``1.96·√(p̂(1−p̂)/N)`` ;
            0.0 pour les u_time à None ou forcés (nœud déjà en retard).
        completion_quantiles: par nœud, quantiles des dates d'achèvement
            simulées ``{q: heures-projet}``, ex. ``{0.5: ..., 0.9: ...}``.
    """

    n_tirages: int
    graine: int | None
    u_time: dict[str, float | None]
    ic95: dict[str, float]
    completion_quantiles: dict[str, dict[float, float]]


class SimulateurLeadTime:
    """Simulateur Monte Carlo des dates d'achèvement propagées sur le DAG.

    Chaque appel à :meth:`executer` repart d'un générateur frais
    ``Generator(PCG64(graine))`` : à graine égale, les résultats sont
    reproductibles bit à bit.
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
            repo: dépôt de graphe (ordre topologique et prédécesseurs NOMINAUX).
            n_tirages: nombre de tirages N, dans [2 000, 50 000].
            graine: graine PCG64 (None = entropie système, non reproductible).
            famille: famille de loi par DÉFAUT pour les nœuds sans champs
                triangulaires et d'écart-type non nul — "lognormale" (défaut)
                ou "normale" (override global, utile aux tests de validation
                croisée). Cf. :func:`resoudre_loi`.

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

    # --- Échéances ----------------------------------------------------------

    @staticmethod
    def _deadline_h(
        node: SupplyNode, milestones: list[Milestone] | None, t0_ts: float
    ) -> float | None:
        """Deadline d_i du nœud en heures-projet, ou None si aucune échéance.

        Priorité au prochain jalon ACTIF : ``(deadline_ts − t0_ts)/3600`` ;
        sinon ``kpis.time.deadline_h`` ; sinon None (pas de u_time).

        Args:
            node: nœud évalué.
            milestones: jalons du nœud (None ou vide = aucun).
            t0_ts: origine temporelle du projet (epoch s).

        Returns:
            Échéance en heures depuis t0, ou None.
        """
        m_star = next_active_milestone(milestones) if milestones else None
        if m_star is not None:
            return (m_star.deadline_ts - t0_ts) / 3600.0
        return node.kpis.time.deadline_h

    @staticmethod
    def _reste(milestones: list[Milestone] | None) -> float:
        """Part du cycle qu'il reste à parcourir sur le jalon actif, dans [0, 1].

        Le lead time tiré est la durée d'un cycle COMPLET. Un jalon avancé à
        ``p`` n'a plus que ``1 − p`` de ce cycle devant lui : sans ce facteur,
        tout nœud dont le lead time nominal dépasse sa marge est déclaré perdu
        d'avance quel que soit son avancement. Même correction que
        :meth:`~supplyscore.core.ur_model.UrModel.u_base_jalon` et que
        ``ForecastService`` — les trois estimateurs de P(jalon raté) doivent
        rester d'accord.

        Args:
            milestones: jalons du nœud (None ou vide = aucun).

        Returns:
            ``1 − progress`` du prochain jalon ACTIF, ou 1.0 s'il n'y en a pas.
        """
        m_star = next_active_milestone(milestones) if milestones else None
        if m_star is None:
            return 1.0
        return min(max(1.0 - m_star.progress, 0.0), 1.0)

    # --- Simulation -----------------------------------------------------------

    def executer(
        self,
        t: float = 0.0,
        milestones_par_noeud: dict[str, list[Milestone]] | None = None,
        t0_ts: float = 0.0,
        quantiles: tuple[float, ...] = (0.5, 0.9),
    ) -> ResultatMC:
        """Simule les dates d'achèvement de tout le graphe et estime u_time.

        Récurrence vectorisée en ordre topologique (fournisseurs profonds
        d'abord, arcs nominaux seuls) : ``S_i = max_{j∈Pred(i)} C_j`` —
        ``t`` pour les racines, cf. le CHOIX DOCUMENTÉ du module — puis
        ``C_i = S_i + L_i`` avec un tableau ``(N,)`` par nœud.

        Args:
            t: instant courant en heures-projet ; les racines démarrent à t,
                et tout nœud dont la deadline est déjà passée (``d_i <= t``)
                reçoit u_time = 1.0 exactement.
            milestones_par_noeud: jalons par id de nœud — fournit la deadline
                v2 (prochain jalon ACTIF) ; None ou id absent = repli sur
                ``kpis.time.deadline_h``.
            t0_ts: origine temporelle du projet (epoch s) pour convertir les
                ``deadline_ts`` des jalons en heures-projet.
            quantiles: ordres des quantiles d'achèvement à restituer,
                chacun dans [0, 1].

        Returns:
            Le :class:`ResultatMC` (u_time, IC95, quantiles d'achèvement).

        Raises:
            ValueError: budget mémoire ``N × n_nœuds > 5·10⁷`` dépassé, ordre
                de quantile hors [0, 1], ou loi de nœud invalide
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
            if node is None:  # pragma: no cover — l'id provient du tri topologique
                raise KeyError(f"Nœud inconnu : {node_id!r}")
            preds = self._repo.predecessors(node_id)
            if preds:
                depart = np.maximum.reduce([achevements[p.id] for p in preds])
            else:
                depart = depart_racine
            loi = resoudre_loi(node, self.famille)
            jalons = milestones_par_noeud.get(node_id)
            # Seul le TRAVAIL RESTANT du jalon actif est devant nous (cf. _reste).
            c = depart + tirer_lead_times(loi, rng, self.n_tirages) * self._reste(jalons)
            achevements[node_id] = c
            completion_quantiles[node_id] = {float(q): float(np.quantile(c, q)) for q in quantiles}
            d = self._deadline_h(node, jalons, t0_ts)
            if d is None:
                u_time[node_id] = None  # pas d'échéance : pas de u_time
                ic95[node_id] = 0.0
            elif d <= t:
                u_time[node_id] = 1.0  # retard avéré : forcé, hors estimateur
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
