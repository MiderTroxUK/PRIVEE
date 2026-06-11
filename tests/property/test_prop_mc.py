"""Propriétés Hypothesis du simulateur Monte Carlo (phase E13, Lot 13.1).

Profil LÉGER : max 20 exemples par propriété et ``deadline=None`` (chaque
exemple exécute une vraie simulation vectorisée — pas de chronomètre
Hypothesis). N = 2 000 (le minimum autorisé) suffit : les comparaisons
stochastiques sont toujours tolérées à 3 erreurs-types, jamais à seuil fixe.

Propriétés :
- u_time ∈ [0, 1] ou None (et ic95 cohérent, quantiles ordonnés) ;
- monotonie stochastique : deadline2 > deadline1 ⇒ p̂2 <= p̂1 + 3·SE ;
- ajouter un prédécesseur ne diminue pas p̂ (tolérance 3·SE) ;
- reproductibilité bit à bit à graine égale.
"""

from __future__ import annotations

import math

from hypothesis import given, settings
from hypothesis import strategies as st

from supplyscore.domain.models import KPIBundle, SupplyArc, SupplyNode, TimeKPIs
from supplyscore.graph import InMemoryGraphRepository
from supplyscore.mc import SimulateurLeadTime

#: N minimal autorisé — rapide, et les tolérances sont en multiples de SE.
_N = 2_000

_LEADS = st.floats(min_value=1.0, max_value=200.0, allow_nan=False, allow_infinity=False)
_STDS = st.none() | st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False)
_DEADLINES = st.floats(min_value=0.0, max_value=600.0, allow_nan=False, allow_infinity=False)
_GRAINES = st.integers(min_value=0, max_value=2**31 - 1)
_FAMILLES = st.sampled_from(["lognormale", "normale"])


def _noeud(
    node_id: str,
    lead: float | None = None,
    std: float | None = None,
    deadline: float | None = None,
) -> SupplyNode:
    return SupplyNode(
        id=node_id,
        name=node_id,
        kpis=KPIBundle(time=TimeKPIs(lead_time_h=lead, lead_time_std_h=std, deadline_h=deadline)),
    )


def _se(*p_hats: float) -> float:
    """Erreur-type combinée des estimateurs binomiaux fournis."""
    return math.sqrt(sum(p * (1.0 - p) / _N for p in p_hats))


class TestProprietesMC:
    @settings(max_examples=20, deadline=None)
    @given(
        lead_a=_LEADS,
        std_a=_STDS,
        lead_b=_LEADS,
        std_b=_STDS,
        deadline=st.none() | _DEADLINES,
        famille=_FAMILLES,
        graine=_GRAINES,
    )
    def test_u_time_dans_01_ou_none(
        self,
        lead_a: float,
        std_a: float | None,
        lead_b: float,
        std_b: float | None,
        deadline: float | None,
        famille: str,
        graine: int,
    ):
        """Chaîne de 2 nœuds : u_time ∈ [0,1] ou None, ic95 et quantiles sains."""
        repo = InMemoryGraphRepository()
        repo.add_node(_noeud("a", lead=lead_a, std=std_a))  # jamais de deadline
        repo.add_node(_noeud("b", lead=lead_b, std=std_b, deadline=deadline))
        repo.add_arc(SupplyArc(source_id="a", target_id="b"))
        sim = SimulateurLeadTime(repo, n_tirages=_N, graine=graine, famille=famille)
        res = sim.executer(t=0.0)
        assert res.u_time["a"] is None  # pas d'échéance -> pas de u_time
        assert res.ic95["a"] == 0.0
        for node_id in ("a", "b"):
            u = res.u_time[node_id]
            if u is not None:
                assert math.isfinite(u)
                assert 0.0 <= u <= 1.0
            assert 0.0 <= res.ic95[node_id] <= 1.0
            q50 = res.completion_quantiles[node_id][0.5]
            q90 = res.completion_quantiles[node_id][0.9]
            assert math.isfinite(q50) and math.isfinite(q90)
            assert 0.0 <= q50 <= q90  # quantiles >= t = 0 et croissants en q

    @settings(max_examples=20, deadline=None)
    @given(
        lead=_LEADS,
        std=_STDS,
        d_pair=st.tuples(_DEADLINES, _DEADLINES),
        famille=_FAMILLES,
        graine=_GRAINES,
    )
    def test_monotonie_stochastique_en_deadline(
        self,
        lead: float,
        std: float | None,
        d_pair: tuple[float, float],
        famille: str,
        graine: int,
    ):
        """deadline2 > deadline1 ⇒ p̂2 <= p̂1 + 3·SE (même graine)."""
        d1, d2 = sorted(d_pair)
        p_hats: list[float] = []
        for d in (d1, d2):
            repo = InMemoryGraphRepository()
            repo.add_node(_noeud("n", lead=lead, std=std, deadline=d))
            sim = SimulateurLeadTime(repo, n_tirages=_N, graine=graine, famille=famille)
            p = sim.executer(t=0.0).u_time["n"]
            assert p is not None
            p_hats.append(p)
        p1, p2 = p_hats
        assert p2 <= p1 + 3.0 * _se(p1, p2) + 1e-12

    @settings(max_examples=20, deadline=None)
    @given(
        lead=_LEADS,
        std=_STDS,
        lead_pred=_LEADS,
        std_pred=_STDS,
        deadline=_DEADLINES,
        famille=_FAMILLES,
        graine=_GRAINES,
    )
    def test_ajouter_un_predecesseur_ne_diminue_pas_p(
        self,
        lead: float,
        std: float | None,
        lead_pred: float,
        std_pred: float | None,
        deadline: float,
        famille: str,
        graine: int,
    ):
        """p̂(avec prédécesseur) >= p̂(isolé) − 3·SE (+ correction 3/N).

        Le prédécesseur retarde le démarrage (S = C_pred >= t) : la date
        d'achèvement croît stochastiquement. Les tirages du nœud diffèrent
        entre les deux graphes (flux RNG décalé), d'où la tolérance.
        """
        repo_isole = InMemoryGraphRepository()
        repo_isole.add_node(_noeud("n", lead=lead, std=std, deadline=deadline))
        sim1 = SimulateurLeadTime(repo_isole, n_tirages=_N, graine=graine, famille=famille)
        p_isole = sim1.executer(t=0.0).u_time["n"]

        repo_pred = InMemoryGraphRepository()
        repo_pred.add_node(_noeud("pred", lead=lead_pred, std=std_pred))
        repo_pred.add_node(_noeud("n", lead=lead, std=std, deadline=deadline))
        repo_pred.add_arc(SupplyArc(source_id="pred", target_id="n"))
        sim2 = SimulateurLeadTime(repo_pred, n_tirages=_N, graine=graine, famille=famille)
        p_avec = sim2.executer(t=0.0).u_time["n"]

        assert p_isole is not None and p_avec is not None
        assert p_avec >= p_isole - 3.0 * _se(p_isole, p_avec) - 3.0 / _N

    @settings(max_examples=20, deadline=None)
    @given(
        lead=_LEADS,
        std=_STDS,
        deadline=st.none() | _DEADLINES,
        famille=_FAMILLES,
        graine=_GRAINES,
    )
    def test_reproductibilite_par_graine(
        self,
        lead: float,
        std: float | None,
        deadline: float | None,
        famille: str,
        graine: int,
    ):
        """Même graine ⇒ u_time, ic95 et quantiles identiques bit à bit."""
        repo = InMemoryGraphRepository()
        repo.add_node(_noeud("amont", lead=lead, std=std))
        repo.add_node(_noeud("n", lead=lead, std=std, deadline=deadline))
        repo.add_arc(SupplyArc(source_id="amont", target_id="n"))
        res1 = SimulateurLeadTime(repo, n_tirages=_N, graine=graine, famille=famille).executer()
        res2 = SimulateurLeadTime(repo, n_tirages=_N, graine=graine, famille=famille).executer()
        assert res1.u_time == res2.u_time
        assert res1.ic95 == res2.ic95
        assert res1.completion_quantiles == res2.completion_quantiles
