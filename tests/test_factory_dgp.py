"""Tests ciblés du DGP de l'usine de campagnes (U6, ``projects/factory/dgp.py``).

Se concentre sur les propriétés de CORRECTION critiques du plan (D18/D21/D29) :
paire CRN à bruit identique, absence de fuite du stress latent dans les
structures observables, bornes du plan QMC, cohérence AHP du déclarant
synthétique et acceptation des paramètres d'évènement tirés par
``compute_impacts``. Les modules ``dgp``/``run_random_campaign`` vivent hors
``supplyscore`` (``projects/factory/``, hors couverture par convention) --
importés ici via un ajout ciblé de ``sys.path``.
"""

from __future__ import annotations

import copy
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

_FACTORY_DIR = Path(__file__).resolve().parent.parent / "projects" / "factory"
if str(_FACTORY_DIR) not in sys.path:
    sys.path.append(str(_FACTORY_DIR))

import dgp  # noqa: E402 -- après l'ajout de sys.path, par nécessité

# --- Plan QMC -------------------------------------------------------------------------


def test_sample_regimes_bounds_and_determinism():
    regimes_a = dgp.sample_regimes(seed=42, n_chains=17)
    regimes_b = dgp.sample_regimes(seed=42, n_chains=17)
    assert regimes_a == regimes_b  # même seed -> même plan (dataclasses frozen comparables)
    assert len(regimes_a) == 17
    for regime in regimes_a:
        assert regime.n_ranks in dgp.N_RANKS_CHOICES
        assert dgp.A_BOUNDS[0] <= regime.a <= dgp.A_BOUNDS[1]
        assert dgp.B_BOUNDS[0] <= regime.b <= dgp.B_BOUNDS[1]
        assert dgp.P_CHOC_BOUNDS[0] <= regime.p_choc <= dgp.P_CHOC_BOUNDS[1]
        assert dgp.SIGMA_BOUNDS[0] <= regime.sigma <= dgp.SIGMA_BOUNDS[1]


def test_sample_regimes_rejects_zero_chains():
    with pytest.raises(ValueError):
        dgp.sample_regimes(seed=1, n_chains=0)


def test_derive_seed_deterministic_and_distinct():
    assert dgp.derive_seed("a", 1) == dgp.derive_seed("a", 1)
    assert dgp.derive_seed("a", 1) != dgp.derive_seed("a", 2)
    assert isinstance(dgp.derive_seed("x", "y", 3), int)


def test_dgp_manifest_schema():
    regime = dgp.Regime(n_ranks=5, a=-3.0, b=5.0, p_choc=0.04, sigma=0.08)
    manifest = dgp.dgp_manifest(regime, seed=42)
    for key in ("a", "b", "p_choc", "sigma", "dgp_params_id", "macro_series_id"):
        assert key in manifest
    assert manifest["macro_series_id"] is None
    assert manifest["a"] == regime.a
    assert manifest["dgp_params_id"] == regime.params_id


# --- Paire CRN (D18) -- LA propriété de correction la plus critique -------------------


def test_dynamics_week_step_consumes_identical_rng_regardless_of_mitigation():
    """Le flux BRUT consommé ne dépend PAS de ``mitigation_active`` -- condition de la paire CRN."""
    regime = dgp.Regime(n_ranks=4, a=-3.0, b=5.0, p_choc=0.05, sigma=0.08)
    base_state = np.random.default_rng(12345).bit_generator.state

    rng_a = np.random.default_rng()
    rng_a.bit_generator.state = copy.deepcopy(base_state)
    result_a = dgp.dynamics_week_step(rng_a, 0.5, 0.5, regime, mitigation_active=0.0)

    rng_b = np.random.default_rng()
    rng_b.bit_generator.state = copy.deepcopy(base_state)
    result_b = dgp.dynamics_week_step(rng_b, 0.5, 0.5, regime, mitigation_active=0.9)

    # Tirages BRUTS identiques (les innovations ne dépendent pas de mitigation_active).
    assert result_a.innovations == result_b.innovations
    # Flux consommé de façon identique (même nombre, même ordre de tirages) : l'état du
    # générateur après l'appel est BIT-IDENTIQUE malgré une mitigation différente.
    assert rng_a.bit_generator.state == rng_b.bit_generator.state
    # Seule la transformation déterministe diffère : la mitigation doit réduire s.
    assert result_a.s > result_b.s


def test_dynamics_week_step_fixed_shape_across_many_draws():
    """Sur de nombreux tirages, l'état du générateur après N pas ne dépend jamais de l'issue."""
    regime = dgp.Regime(n_ranks=3, a=-3.5, b=6.0, p_choc=0.05, sigma=0.1)
    base_state = np.random.default_rng(7).bit_generator.state

    rng_no_mitig = np.random.default_rng()
    rng_no_mitig.bit_generator.state = copy.deepcopy(base_state)
    rng_mitig = np.random.default_rng()
    rng_mitig.bit_generator.state = copy.deepcopy(base_state)

    sk_a, hd_a, sk_b, hd_b = 0.0, 0.0, 0.0, 0.0
    for _ in range(12):
        ra = dgp.dynamics_week_step(rng_no_mitig, sk_a, hd_a, regime, mitigation_active=0.0)
        rb = dgp.dynamics_week_step(rng_mitig, sk_b, hd_b, regime, mitigation_active=0.6)
        sk_a, hd_a = ra.stress_kpi, ra.hidden
        sk_b, hd_b = rb.stress_kpi, rb.hidden

    assert rng_no_mitig.bit_generator.state == rng_mitig.bit_generator.state


def test_replay_without_action_matches_manual_loop():
    """``replay_without_action`` == rejouer ``dynamics_week_step`` à la main, tirage pour tirage."""
    regime = dgp.Regime(n_ranks=3, a=-3.0, b=6.0, p_choc=0.05, sigma=0.1)
    base_rng = np.random.default_rng(999)
    checkpoint = copy.deepcopy(base_rng.bit_generator.state)

    manual_rng = np.random.default_rng()
    manual_rng.bit_generator.state = copy.deepcopy(checkpoint)
    stress_kpi, hidden = 0.2, 0.1
    for _ in range(2):  # skip_weeks
        r = dgp.dynamics_week_step(manual_rng, stress_kpi, hidden, regime, mitigation_active=0.0)
        stress_kpi, hidden = r.stress_kpi, r.hidden
    issue_manual = False
    for _ in range(4):  # weeks
        r = dgp.dynamics_week_step(manual_rng, stress_kpi, hidden, regime, mitigation_active=0.0)
        stress_kpi, hidden = r.stress_kpi, r.hidden
        issue_manual = issue_manual or r.fires

    issue_fn = dgp.replay_without_action(checkpoint, 0.2, 0.1, regime, skip_weeks=2, weeks=4)
    assert issue_fn == issue_manual


def test_replay_without_action_does_not_mutate_caller_state():
    """``replay_without_action`` consomme un CLONE -- l'état passé en argument reste intact."""
    regime = dgp.Regime(n_ranks=3, a=-3.0, b=6.0, p_choc=0.05, sigma=0.1)
    original_rng = np.random.default_rng(42)
    state_before = copy.deepcopy(original_rng.bit_generator.state)
    checkpoint = copy.deepcopy(original_rng.bit_generator.state)

    dgp.replay_without_action(checkpoint, 0.1, 0.1, regime, skip_weeks=0, weeks=4)

    assert original_rng.bit_generator.state == state_before
    assert checkpoint == state_before  # l'appelant n'a pas non plus vu SON dict muté


def test_mitigation_yields_nonzero_delta_on_a_real_but_bounded_fraction():
    """K_MITIG donne un signal causal RÉEL, ni nul ni « toujours gagnant ».

    Reproduit la mesure de calibration documentée sur :data:`dgp.K_MITIG` :
    à mitigation substantielle (0.3, plausible à K_MITIG=25 pour un effet
    observé de l'ordre de 1 %), une fraction MESURABLE mais MINORITAIRE des
    essais voit son issue à 4 semaines basculer entre les deux branches --
    ni ~0 % (signal mort) ni proche de 100 % (déterministe, pas de calibration
    d'évènement rare réaliste).
    """
    regimes = dgp.sample_regimes(seed=55, n_chains=20)
    n_trials = 0
    n_nonzero = 0
    for regime in regimes:
        for trial in range(10):
            rng = np.random.default_rng(dgp.derive_seed(regime.params_id, "mitig_test", trial))
            stress_kpi, hidden = 0.0, 0.0
            for _ in range(6):  # échauffe le stress à un niveau plausible en campagne
                r = dgp.dynamics_week_step(rng, stress_kpi, hidden, regime, mitigation_active=0.0)
                stress_kpi, hidden = r.stress_kpi, r.hidden
            checkpoint = copy.deepcopy(rng.bit_generator.state)

            issue_without = dgp.replay_without_action(
                checkpoint, stress_kpi, hidden, regime, skip_weeks=0, weeks=4
            )
            shadow = np.random.default_rng()
            shadow.bit_generator.state = copy.deepcopy(checkpoint)
            sk2, hd2, issue_with = stress_kpi, hidden, False
            for _ in range(4):
                r2 = dgp.dynamics_week_step(shadow, sk2, hd2, regime, mitigation_active=0.3)
                sk2, hd2 = r2.stress_kpi, r2.hidden
                issue_with = issue_with or r2.fires

            n_trials += 1
            n_nonzero += int(issue_without != issue_with)

    fraction = n_nonzero / n_trials
    assert fraction > 0.0, "K_MITIG=25 : aucun delta_u_vrai non nul -- signal causal mort"
    assert fraction < 0.5, (
        f"taux de bascule suspect ({100 * fraction:.1f} %) -- pas réaliste pour un évènement rare"
    )


def test_effective_window_start_floors_at_tour_plus_one():
    """Régression : sans ce plancher, un délai nul (``date_effet <= tour``) désalignait
    d'une semaine la fenêtre rejouée (``replay_without_action``) et la fenêtre relue dans
    ``event_fired_timeline`` -- deux ensembles de semaines différents, capables de faire
    diverger ``delta_u_vrai`` même quand aucune mitigation n'est jamais active (ex.
    ``ne_rien_faire``, dont l'effet vrai est TOUJOURS nul). Trouvé par inspection d'une
    campagne réelle, pas par la seule relecture du code -- cf. run_random_campaign.py."""
    sys.path.append(str(_FACTORY_DIR))
    import run_random_campaign as rrc

    # Délai nul ou négatif (date_effet <= tour, ex. ne_rien_faire ou expedition_express
    # avec un délai tiré à 0) : la fenêtre est plancherée à tour + 1 (checkpoint pris
    # APRÈS les tirages de la semaine ``tour`` -- rien avant ``tour + 1`` n'est rejouable).
    assert rrc._effective_window_start(date_effet=5, tour=5) == 6
    assert rrc._effective_window_start(date_effet=3, tour=5) == 6
    # Délai strictement positif (date_effet > tour) : la fenêtre démarre bien à date_effet.
    assert rrc._effective_window_start(date_effet=8, tour=5) == 8
    assert rrc._effective_window_start(date_effet=6, tour=5) == 6


def test_ne_rien_faire_shadow_matches_true_continuation_zero_delay():
    """Régression bout-en-bout : ``ne_rien_faire`` (délai TOUJOURS nul -> date_effet ==
    tour) ne doit jamais faire diverger la relecture fantôme de la VRAIE continuation du
    flux dynamique -- exactement le scénario où le bug de désalignement se manifestait."""
    sys.path.append(str(_FACTORY_DIR))
    import run_random_campaign as rrc

    from supplyscore.services.orchestrator import SupplyScoreService

    db_dir = tempfile.mkdtemp(prefix="test_ne_rien_faire_")
    service = SupplyScoreService(db_dir=db_dir)
    try:
        project = service.seed_demo(n_ranks=2, seed=1)
        node = service.repo.nodes_by_project(project.id)[0]
        regime = dgp.Regime(n_ranks=2, a=-2.0, b=8.0, p_choc=0.08, sigma=0.15)  # régime "chaud"
        dyn_rng = np.random.default_rng(123456)
        op_rng = np.random.default_rng(654321)
        ctx = rrc._build_ctx(node, service.registry.list_milestones(node.id))
        active_effects: dict[str, list[tuple[int, int, float]]] = {node.id: []}

        record = rrc._run_intervention(
            service,
            node.id,
            node,
            dgp.FALLBACK_CATALOGUE["ne_rien_faire"],
            ctx,
            tour=3,
            op_rng=op_rng,
            dyn_rng=dyn_rng,
            stress_kpi_now=0.3,
            hidden_now=0.2,
            stress_latent_now=0.35,
            regime=regime,
            active_effects=active_effects,
        )
        assert record["date_effet"] == 3  # ne_rien_faire : délai nul par construction
        assert record["effet_vrai_param"] == 0.0
        assert active_effects[node.id] == []  # aucune mitigation n'est jamais active
        # stress_latent : journalisé en clé de PREMIER NIVEAU (vérité-terrain), jamais
        # dans etat_avant (observable seul) -- les deux règles vérifiées simultanément.
        assert record["stress_latent"] == 0.35
        assert "stress_latent" not in record["etat_avant"]

        # dyn_rng n'a PAS été consommé par _run_intervention lui-même (seul un CLONE de
        # son état l'est, dans replay_without_action) : le continuer À LA MAIN, sur le
        # MÊME objet, donne la VRAIE continuation semaine par semaine.
        stress_kpi, hidden = 0.3, 0.2
        issue_true_continuation = False
        for _ in range(dgp.EFFECT_WINDOW_WEEKS):
            r = dgp.dynamics_week_step(dyn_rng, stress_kpi, hidden, regime, mitigation_active=0.0)
            stress_kpi, hidden = r.stress_kpi, r.hidden
            issue_true_continuation = issue_true_continuation or r.fires

        assert record["_issue_without"] == issue_true_continuation
    finally:
        service.close()


def test_intervention_record_has_frozen_schema_fields():
    """Schéma figé de ``interventions_truth.jsonl`` : tous les champs requis présents,
    ``stress_latent`` au premier niveau (vérité-terrain) et ABSENT de ``etat_avant``."""
    sys.path.append(str(_FACTORY_DIR))
    import run_random_campaign as rrc

    from supplyscore.services.orchestrator import SupplyScoreService

    db_dir = tempfile.mkdtemp(prefix="test_schema_")
    service = SupplyScoreService(db_dir=db_dir)
    try:
        project = service.seed_demo(n_ranks=2, seed=2)
        node = service.repo.nodes_by_project(project.id)[0]
        regime = dgp.Regime(n_ranks=2, a=-2.0, b=8.0, p_choc=0.08, sigma=0.15)
        dyn_rng = np.random.default_rng(11)
        op_rng = np.random.default_rng(22)
        ctx = rrc._build_ctx(node, service.registry.list_milestones(node.id))
        active_effects: dict[str, list[tuple[int, int, float]]] = {node.id: []}

        record = rrc._run_intervention(
            service,
            node.id,
            node,
            dgp.FALLBACK_CATALOGUE["expedition_express"],
            ctx,
            tour=1,
            op_rng=op_rng,
            dyn_rng=dyn_rng,
            stress_kpi_now=0.4,
            hidden_now=0.1,
            stress_latent_now=0.42,
            regime=regime,
            active_effects=active_effects,
        )
        for field in (
            "tour",
            "node",
            "action_id",
            "etat_avant",
            "stress_latent",
            "decidee",
            "executee",
            "date_effet",
            "effet_vrai_param",
            "delta_u_vrai",
            "resultat_operationnel",
            "effets_voisins",
        ):
            assert field in record, f"champ requis manquant : {field}"
        assert record["stress_latent"] == 0.42
        assert "stress_latent" not in record["etat_avant"]
        assert record["decidee"] is True
    finally:
        service.close()


# --- Pas de fuite du stress latent dans l'observable (D21/D32) -----------------------


def test_build_ctx_never_leaks_latent_stress():
    """``run_random_campaign._build_ctx`` n'expose QUE des grandeurs observables."""
    sys.path.append(str(_FACTORY_DIR))
    import run_random_campaign as rrc

    from supplyscore.domain.models import SupplyNode, UrgencyState

    node = SupplyNode(id="n1", name="Test", urgency=UrgencyState(ur_local=0.4, ud_local=0.3))
    ctx = rrc._build_ctx(node, [])

    forbidden = {"s", "stress", "stress_latent", "stress_kpi", "hidden", "latent"}
    assert not (forbidden & set(ctx.keys())), f"fuite potentielle du latent : {ctx.keys()}"
    assert set(ctx.keys()) == {
        "ur_local",
        "ud_local",
        "adequation",
        "false_urgency",
        "hidden_risk",
        "kpis",
        "has_active_milestone",
    }


# --- Aléa d'évènement : bornes et acceptation par compute_impacts --------------------


def test_gravite_bucket_thresholds():
    assert dgp.gravite_bucket(0.0) == "mineure"
    assert dgp.gravite_bucket(0.5) == "majeure"
    assert dgp.gravite_bucket(0.99) == "critique"


def test_draw_event_params_within_field_bounds():
    from supplyscore.domain.events import EVENT_CALIBRATION

    rng = np.random.default_rng(5)
    for event_type in dgp.EVENT_POOL:
        spec = EVENT_CALIBRATION[event_type]
        for s in (0.0, 0.3, 0.7, 1.0):
            jitter = rng.random(dgp.JITTER_K)
            params = dgp.draw_event_params(event_type, s, jitter)
            for f in spec.fields:
                value = params[f.name]
                if f.kind == "choice":
                    assert value in f.choices
                    continue
                if f.minimum is not None:
                    assert value >= f.minimum - 1e-9
                if f.maximum is not None:
                    assert value <= f.maximum + 1e-9


def test_draw_event_params_strictly_positive_duration_fields():
    """À stress NUL (le cas limite), les champs de durée restent strictement positifs."""
    from supplyscore.domain.events import EVENT_CALIBRATION

    strictly_positive = {"duree_arret_h", "retard_h", "duree_prevue_h"}
    rng = np.random.default_rng(11)
    for event_type in dgp.EVENT_POOL:
        spec = EVENT_CALIBRATION[event_type]
        for f in spec.fields:
            if f.name in strictly_positive:
                jitter = rng.random(dgp.JITTER_K)
                params = dgp.draw_event_params(event_type, 0.0, jitter)
                assert params[f.name] > 0.0


def test_draw_event_params_accepted_by_compute_impacts():
    """Les paramètres tirés ne font jamais lever ``compute_impacts`` (bornes/validation)."""
    from supplyscore.domain.events import compute_impacts
    from supplyscore.domain.models import KPIBundle

    kpis = KPIBundle()  # bundle vide : cas le plus défavorable (tous les KPIs à None)
    rng = np.random.default_rng(13)
    for event_type in dgp.EVENT_POOL:
        for s in (0.0, 0.2, 0.5, 0.8, 1.0):
            jitter = rng.random(dgp.JITTER_K)
            params = dgp.draw_event_params(event_type, s, jitter)
            compute_impacts(event_type, params, kpis)  # ne doit pas lever


# --- Déclarant synthétique (palier 0) -------------------------------------------------


def test_synthetic_respond_shape_and_bounds():
    rng = np.random.default_rng(7)
    response = dgp.synthetic_respond("n1", 3, {"ur_local": 0.6}, rng, bias=0.05)
    assert len(response["bipolar"]) == 6
    assert all(-8 <= v <= 8 for v in response["bipolar"])
    assert len(response["scores_ui"]) == 4
    assert all(1 <= v <= 6 for v in response["scores_ui"])


def test_bipolar_saaty_roundtrip():
    from supplyscore.core.ahp import bipolar_to_saaty

    for v in range(-8, 9):
        assert dgp._bipolar_from_saaty(bipolar_to_saaty(v)) == v


def test_synthetic_respond_mostly_consistent_ahp():
    """Le déclarant synthétique doit quasi-toujours passer le seuil de cohérence de Saaty."""
    from supplyscore.core.ahp import run_ahp

    rng = np.random.default_rng(2024)
    n_trials = 300
    n_consistent = 0
    for i in range(n_trials):
        features = {"ur_local": float(rng.uniform(0.0, 1.0))}
        response = dgp.synthetic_respond("n", i, features, rng, bias=float(rng.normal(0.0, 0.1)))
        comparisons, _scores = dgp.response_to_ahp_inputs(response)
        result = run_ahp(comparisons, n=4)
        n_consistent += int(result.is_consistent)
    assert n_consistent / n_trials > 0.95, f"seulement {n_consistent}/{n_trials} cohérents"


def test_response_to_ahp_inputs_rejects_malformed_response():
    with pytest.raises(ValueError):
        dgp.response_to_ahp_inputs({"bipolar": [1, 2], "scores_ui": [1, 2, 3, 4]})


# --- Catalogue d'actions de repli -----------------------------------------------------


def test_fallback_catalogue_has_required_actions():
    catalogue = dgp.load_action_catalogue()
    for action_id in ("expedition_express", "replanifier_jalon", "ne_rien_faire"):
        assert action_id in catalogue
        action = catalogue[action_id]
        for attr in (
            "id",
            "libelle",
            "preconditions",
            "apply_to_rollout",
            "apply_to_project",
            "delai_effet_weeks",
            "cout",
            "risque_secondaire",
            "incompatibles",
            "objectifs_operationnels",
        ):
            assert hasattr(action, attr), f"{action_id} : attribut manquant {attr}"


def test_ne_rien_faire_preconditions_always_true():
    catalogue = dgp.load_action_catalogue()
    assert catalogue["ne_rien_faire"].preconditions({}) is True


def test_objectif_atteint_requires_threshold():
    action = dgp.FALLBACK_CATALOGUE["expedition_express"]
    assert dgp.objectif_atteint(action, 0.5, 0.30) is True  # baisse de 0.20 >= seuil 0.15
    assert dgp.objectif_atteint(action, 0.5, 0.40) is False  # baisse de 0.10 < seuil 0.15
    assert dgp.objectif_atteint(action, None, 0.30) is False


# --- Calibration du taux d'évènement (ordre de grandeur, tolérance large) ------------


def test_average_event_rate_in_target_band():
    """Taux d'évènement médian sur le plan QMC dans un ordre de grandeur raisonnable.

    Tolérance volontairement LARGE (pas [3, 4] %) : ``a`` peut atteindre -2 sur
    certains régimes du plan (borne fournie, hors périmètre U6), ce qui à lui
    seul donne déjà sigmoid(-2) ≈ 12 %/semaine à stress nul -- irréductible par
    ``KAPPA_BADNESS``. Ce test garde-fou détecte une régression GROSSIÈRE de
    calibration (ex. une taux moyen à 50 % ou à 0.01 %), pas un écart fin.
    """
    regimes = dgp.sample_regimes(seed=321, n_chains=24)
    rates = []
    for regime in regimes:
        rng = np.random.default_rng(dgp.derive_seed(regime.params_id, "calib"))
        stress_kpi, hidden = 0.0, 0.0
        fires = 0
        weeks = 20
        for _ in range(weeks):
            for _node in range(5):
                r = dgp.dynamics_week_step(rng, stress_kpi, hidden, regime, mitigation_active=0.0)
                stress_kpi, hidden = r.stress_kpi, r.hidden
                fires += int(r.fires)
        rates.append(fires / (weeks * 5))
    median_rate = float(np.median(rates))
    assert 0.01 <= median_rate <= 0.12, (
        f"taux médian hors bande large [1%, 12%] : {median_rate:.3f}"
    )
