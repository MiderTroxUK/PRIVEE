"""Propriete Hypothesis de la de-saturation Deltal (HELIOS v7, U3).

Invariant : sur un DAG NON sature (``ur_local``  dans  [0, 0.9], beta  dans  [0.1, 0.9],
un seul client final), le classement des noeuds induit par ``delta_ell_final``
(Deltal log-survie au client final, jumeau epsilon-regularise de
``simulate_shock_detailed``) est IDENTIQUE au classement induit par
``delta_ur_final`` (DeltaUr standard au client final) pour le pire choc local
``ur_local -> 1.0``.

Justification : au client final f, la reference Ur_f est commune a tous les
chocs candidats et l(p) = -ln(1-p) est strictement croissante - Deltal_f et
DeltaUr_f sont deux transformees monotones de la meme urgence choquee Ur'_f.
Encodage robuste au bruit flottant : implication par paires - si
DeltaUr_final(X) > DeltaUr_final(Y) + tol alors Deltal_final(X) >= Deltal_final(Y) - tol
(les quasi-egalites, departagees par le nom dans les deux tris, sont
ignorees).
"""

from __future__ import annotations

from hypothesis import assume, given
from hypothesis import strategies as st

from supplyscore.data.generator import RandomSupplyChainGenerator
from supplyscore.domain.models import SupplyArc, SupplyNode, UrgencyState
from supplyscore.graph import InMemoryGraphRepository, PropagationEngine

#: Urgences locales non saturees : marge franche sous 1.0 (pas de clip actif).
_UR_LOCAL = st.floats(min_value=0.0, max_value=0.9, allow_nan=False, allow_infinity=False)

#: Coefficients beta ni nuls ni saturants (propagation effective, jamais degeneree).
_BETA = st.floats(min_value=0.1, max_value=0.9, allow_nan=False, allow_infinity=False)

#: Tolerance de quasi-egalite des DeltaUr (les paires plus proches sont des ex aequo : departagees par le nom, identiquement dans les deux tris).
_TOL = 1e-9


@st.composite
def dag_cases(draw: st.DrawFn) -> tuple[list[SupplyNode], list[SupplyArc]]:
    """DAG par rangs (generateur seede), ur_local  dans  [0, 0.9] et beta  dans  [0.1, 0.9]."""
    seed = draw(st.integers(min_value=0, max_value=2**32 - 1))
    n_ranks = draw(st.integers(min_value=1, max_value=3))
    _project, nodes, arcs = RandomSupplyChainGenerator(seed=seed).generate(
        n_ranks=n_ranks, breadth=(1, 2)
    )
    for node in nodes:
        node.urgency = UrgencyState(ud_local=0.0, ur_local=draw(_UR_LOCAL), timestamp=0.0)
    for arc in arcs:
        arc.beta = draw(_BETA)
    return nodes, arcs


@given(case=dag_cases())
def test_ranking_delta_ell_final_equals_ranking_delta_ur_final(
    case: tuple[list[SupplyNode], list[SupplyArc]],
) -> None:
    """Hors saturation, Deltal_final et DeltaUr_final induisent le meme classement."""
    nodes, arcs = case
    repo = InMemoryGraphRepository()
    for node in nodes:
        repo.add_node(node)
    for arc in arcs:
        repo.add_arc(arc)
    repo.assign_ranks()

    finals = [node.id for node in repo.nodes() if node.rank == 0]
    assume(len(finals) == 1)  # un seul client final : delta_final sans max ambigu
    final_id = finals[0]

    engine = PropagationEngine(repo)
    delta_ur_final: dict[str, float] = {}
    delta_ell_final: dict[str, float] = {}
    for node in repo.nodes():
        detail = engine.simulate_shock_detailed(node.id, 1.0)
        delta_ur_final[node.id] = detail.delta_ur[final_id]
        delta_ell_final[node.id] = detail.delta_ell[final_id]

    node_ids = sorted(delta_ur_final)
    for i, x in enumerate(node_ids):
        for y in node_ids[i + 1 :]:
            if delta_ur_final[x] > delta_ur_final[y] + _TOL:
                assert delta_ell_final[x] >= delta_ell_final[y] - _TOL, (
                    f"classements divergents : ΔUr({x})={delta_ur_final[x]} > "
                    f"ΔUr({y})={delta_ur_final[y]} mais Δl({x})={delta_ell_final[x]} < "
                    f"Δl({y})={delta_ell_final[y]}"
                )
            elif delta_ur_final[y] > delta_ur_final[x] + _TOL:
                assert delta_ell_final[y] >= delta_ell_final[x] - _TOL, (
                    f"classements divergents : ΔUr({y})={delta_ur_final[y]} > "
                    f"ΔUr({x})={delta_ur_final[x]} mais Δl({y})={delta_ell_final[y]} < "
                    f"Δl({x})={delta_ell_final[x]}"
                )
