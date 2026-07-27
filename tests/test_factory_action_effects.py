"""Tests unitaires du modèle d'efficacité des actions U17 (projects/factory).

Ces tests valident la MACHINERIE (schéma, exclusion de la vérité-terrain, maths des
posteriors et de l'E-value, déterminisme du bootstrap) et deux PROPRIÉTÉS scientifiques
robustes du banc de validation — SANS exécuter la batterie complète (lente) et sans
exiger un verdict PASS (le verdict honnête est FAIL, cf. action_effects_schema.md).

Le module `fit_action_effects` vit sous `projects/` (hors couverture) : on l'importe via
le chemin absolu.
"""

from __future__ import annotations

import math
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

_FACTORY = Path(__file__).resolve().parents[1] / "projects" / "factory"
sys.path.insert(0, str(_FACTORY))

fae = pytest.importorskip("fit_action_effects")


def test_features_excluent_la_verite_terrain() -> None:
    """Aucune colonne de vérité-terrain ne peut entrer comme feature d'estimateur."""
    table, _ = fae.generate_dataset(fae.DGP1, seed=1)
    feats = table.feature_names()
    assert set(feats).isdisjoint(fae.COLONNES_VERITE)
    assert all(f.startswith("ea_") for f in feats)
    # Les colonnes de vérité existent bien dans la table (mais hors features).
    assert {"effet_vrai_param", "delta_u_vrai", "stress_latent"} <= set(table.cols)


def test_beta_posteriors_maths_et_coincidence_jeffreys() -> None:
    """prior_sim suit m·N₀+k ; prior_faible et donnees_seules coïncident (Jeffreys)."""
    post = fae.beta_posteriors(k=3, n=10, mean_sim=0.4)
    ps = post["prior_sim"]
    assert ps["alpha"] == pytest.approx(0.4 * 8 + 3)
    assert ps["beta"] == pytest.approx(0.6 * 8 + 7)
    assert ps["n"] == 10
    # Beta(0.5+k, 0.5+n-k) pour les deux références.
    for lbl in ("prior_faible", "donnees_seules"):
        assert post[lbl]["alpha"] == pytest.approx(0.5 + 3)
        assert post[lbl]["beta"] == pytest.approx(0.5 + 7)
    # IC80 ordonné.
    pr = ps["p_resolution"]
    assert pr["lo80"] <= pr["mean"] <= pr["hi80"]


def test_e_value_regle_inversion_et_nul() -> None:
    """E-value : symétrique par inversion RR↔1/RR ; None sur l'effet nul."""
    assert fae._e_value(1.0) is None
    assert fae._e_value(0.0) is None
    # RR = 2 → E = 2 + sqrt(2) ; RR = 0.5 → même E (inversion).
    e_haut = fae._e_value(2.0)
    e_bas = fae._e_value(0.5)
    assert e_haut == pytest.approx(2 + math.sqrt(2))
    assert e_bas == pytest.approx(e_haut)
    assert e_haut > 1.0


def test_irls_retrouve_le_signe_des_coefficients() -> None:
    """La régression logistique IRLS retrouve le sens de la dépendance."""
    rng = np.random.default_rng(0)
    x = rng.standard_normal((400, 2))
    logit = 1.5 * x[:, 0] - 1.0 * x[:, 1]
    y = (rng.random(400) < fae._sigmoid(logit)).astype(float)
    beta, converged = fae.irls_logistic(x, y)
    assert converged
    assert beta[1] > 0.5  # coefficient de x0 positif
    assert beta[2] < -0.3  # coefficient de x1 négatif


def test_ipw_point_non_confondu_retrouve_le_risque() -> None:
    """Sans confusion (propension ≈ 0.5), l'IPW retrouve la différence de risque brute."""
    n = 600
    e = np.full(n, 0.5)
    t = np.array([1, 0] * (n // 2))
    # risque traité 0.2, non traité 0.5 → delta attendu +0.3.
    rng = np.random.default_rng(3)
    y = np.where(t == 1, rng.random(n) < 0.2, rng.random(n) < 0.5).astype(float)
    p0, p1, delta, n_eff = fae._ipw_point(e, t, y)
    assert delta == pytest.approx(p0 - p1)
    assert delta == pytest.approx(0.3, abs=0.08)
    assert 0 < n_eff <= n


def test_fit_produit_un_artefact_conforme_au_contrat() -> None:
    """fit() produit un artefact que check_schema valide (contrat 10)."""
    table, _ = fae.generate_dataset(replace(fae.DGP1, n=1600), seed=5)
    artefact = fae.fit(table, n_boot=40, seed=123)
    fae.check_schema(artefact)  # ne lève pas
    assert artefact["schema_version"] == fae.SCHEMA_VERSION
    assert set(artefact["actions"]) == set(fae.ACTIONS)
    assert len(artefact["segments"]) == 8
    # ne_rien_faire : causal null, mais base + p_execution présents.
    nrf = artefact["actions"][fae.ACTION_NE_RIEN_FAIRE]
    assert {"alpha", "beta", "n"} <= set(nrf["p_execution"])
    for cell in nrf["segments"].values():
        assert cell["delta_causal_ipw"] is None
        assert "posteriors" in cell
    # Étiquetage honnête présent partout où il y a du causal.
    assert "ESTIMÉ" in artefact["label_causal"]
    assert "réel" not in artefact["label_causal"]


def test_fit_est_deterministe() -> None:
    """Deux ajustements sur les mêmes données et même graine sont identiques (bootstrap)."""
    table, _ = fae.generate_dataset(replace(fae.DGP1, n=1600), seed=5)
    a1 = fae.fit(table, n_boot=40, seed=999)
    a2 = fae.fit(table, n_boot=40, seed=999)

    def _ipw(art: dict) -> list:
        out = []
        for act in sorted(art["actions"]):
            for sid in sorted(art["actions"][act]["segments"]):
                dci = art["actions"][act]["segments"][sid]["delta_causal_ipw"]
                out.append(None if dci is None else (dci["est"], dci["lo80"], dci["hi80"]))
        return out

    assert _ipw(a1) == _ipw(a2)


def test_naif_plus_biaise_que_ipw_sous_confusion() -> None:
    """Propriété-clé : sous confusion, le biais du naïf DÉPASSE celui de l'IPW."""
    ipw_abs: list[float] = []
    naif_abs: list[float] = []
    for r in range(3):
        rep = fae._score_replication(replace(fae.DGP1, n=2500), seed=700 + r, n_boot=25)
        for c in rep["cells"]:
            ipw_abs.append(abs(c["ipw_est"] - c["delta_vrai"]))
            naif_abs.append(abs(c["naif_est"] - c["delta_vrai"]))
    assert ipw_abs, "au moins une cellule scorée attendue"
    # Marge nette (l'écart réel est ~0.16 vs ~0.09).
    assert np.mean(naif_abs) > np.mean(ipw_abs) * 1.2


def test_ipw_quasi_non_biaise_sans_confusion() -> None:
    """Contrôle : sans confusion, l'IPW est ~sans biais (valide la machinerie)."""
    ctrl = replace(fae.DGP1, n=2500, c_x=0.0, c1=0.0, b_x=0.0, b_stress=0.0)
    biais: list[float] = []
    for r in range(3):
        rep = fae._score_replication(ctrl, seed=800 + r, n_boot=25)
        for c in rep["cells"]:
            biais.append(c["ipw_est"] - c["delta_vrai"])
    assert biais
    assert abs(float(np.mean(biais))) < 0.04
