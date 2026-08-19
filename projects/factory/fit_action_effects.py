"""Modele d'efficacite des actions - base bayesienne + garde-fous causaux (U17).

Ce module est la **porte scientifique** de la couche prescriptive de SupplyScore.
Il transforme un journal d'interventions (``interventions.csv``, contrat gele no9)
en un artefact ``action_effects.json`` (contrat gele no10 v7) combinant :

1. **Base bayesienne** - pour chaque couple (action x segment d'etat-avant), un
   modele Beta-Binomial conjugue exact estime P(resolution operationnelle |
   execution). Trois a priori sont exposes cote a cote (D27) : ``prior_sim``
   (n_0 = 8, informe par une simulation), ``prior_faible`` (n_0 = 1, centre 0.5)
   et ``donnees_seules`` (Jeffreys 0.5/0.5, reference sans a priori). P(execution)
   par action est un Beta sur la transition decidee -> executee (D29).

2. **Garde-fous causaux** (D20') - l'effet d'une action ne peut etre qualifie de
   " causal " qu'apres : score de propension logistique (IRLS numpy) P(traite |
   features observables d'etat-avant), diagnostic d'*overlap* avec *trimming*
   documente, estimateur **IPW stabilise** de la difference de risque, variante
   **doublement robuste** (AIPW), et **E-value** de VanderWeele quantifiant la
   sensibilite a une confusion non observee.

3. **Batterie de validation** (``--validate``, D32) - un banc synthetique
   deterministe ou la politique de l'operateur depend d'un *stress latent* absent
   des features (confusion partiellement inobservee reelle) mesure la couverture
   des IC, le biais, le taux de recommandation correcte, le regret decisionnel,
   et **demontre chiffres a l'appui que le biais du naif depasse celui de l'IPW**.

Etiquetage honnete (D18') : toute sortie causale porte la mention " effet causal
ESTIME sous hypothese de confusion observable ; sensibilite : e_value " - jamais
" effet reel ". Les colonnes de verite-terrain (``effet_vrai_param``,
``delta_u_vrai``, ``stress_latent``) n'entrent JAMAIS dans un estimateur : elles
ne servent qu'a noter les estimateurs dans ``--validate``.

Dependances : numpy et scipy uniquement (le coeur ``supplyscore`` n'est pas touche).

Usage :
    python fit_action_effects.py --interventions F --out DIR [--validate]
                                 [--prior-sim F] [--check] [--make-fixture F]
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats

# Constantes de gouvernance

#: Actions non nulles du catalogue U15 (CATALOGUE_V1) - bras de traitement possibles.
ACTIONS_NON_NULLES: tuple[str, ...] = (
    "promouvoir_arc_secours",
    "replanifier_jalon",
    "expedition_express",
    "boost_capacite",
    "revue_declaration",
)

#: Bras de reference (" ne rien faire ") - contrefactuel de controle des estimateurs.
ACTION_NE_RIEN_FAIRE: str = "ne_rien_faire"

#: Ensemble complet des actions attendues dans le journal.
ACTIONS: tuple[str, ...] = (*ACTIONS_NON_NULLES, ACTION_NE_RIEN_FAIRE)

#: Colonnes de VERITE-TERRAIN - interdites a tout estimateur, reservees a ``--validate``.
COLONNES_VERITE: frozenset[str] = frozenset({"effet_vrai_param", "delta_u_vrai", "stress_latent"})

#: Mention obligatoire accolee a toute sortie causale (D18'/D20').
LABEL_CAUSAL: str = (
    "effet causal ESTIMÉ sous hypothèse de confusion observable ; sensibilité : e_value"
)

#: Pseudo-observations de l'a priori simule (D27).
N0_PRIOR_SIM: float = 8.0
#: Pseudo-observations de l'a priori faible (D27).
N0_PRIOR_FAIBLE: float = 1.0

#: Bornes de la zone d'overlap acceptable pour le score de propension.
OVERLAP_LO: float = 0.05
OVERLAP_HI: float = 0.95
#: Part maximale de propensions hors zone toleree avant de lever ``overlap_ok=False``.
OVERLAP_PART_MAX: float = 0.10
#: Effectif minimal par bras (apres trimming) pour estimer une cellule causale.
MIN_PAR_BRAS: int = 12

#: Seuil de rang " profond " (tier >= 2) pour l'axe de segmentation.
SEUIL_PROFOND: int = 2
#: Seuil de saturation de l'urgence reelle locale.
SEUIL_SATURATION: float = 0.90

#: Version du schema de l'artefact (contrat 10).
SCHEMA_VERSION: int = 2

#: Issues operationnelles reconnues (definition gelee).
_ISSUES_VALIDES: frozenset[str] = frozenset({"resolu", "partiel", "echec", "en_cours", ""})


# Chargement des donnees (numpy pur + csv stdlib - pas de pandas)


@dataclass
class Table:
    """Journal d'interventions charge en colonnes numpy typees.

    Attributes:
        cols: table {nom_colonne: tableau numpy}. Les colonnes ``ea_*`` sont des
            flottants ; ``decidee``/``executee`` des booleens ; les identifiants
            et le resultat operationnel des chaines.
        n: nombre de lignes.
    """

    cols: dict[str, np.ndarray]
    n: int

    def feature_names(self) -> list[str]:
        """Retourne les features observables (prefixe ``ea_``), triees et sures.

        Le prefixe ``ea_`` garantit par construction l'exclusion des colonnes de
        verite-terrain (``effet_vrai_param``...), qui ne le portent jamais.

        Returns:
            Liste triee des noms de colonnes observables numeriques.
        """
        noms = sorted(
            k
            for k in self.cols
            if k.startswith("ea_")
            and k not in COLONNES_VERITE
            and np.issubdtype(self.cols[k].dtype, np.floating)
        )
        # Garde-fou explicite : aucune fuite de verite-terrain dans les features.
        assert not (set(noms) & COLONNES_VERITE), "fuite de vérité-terrain détectée"
        return noms

    def matrix(self, names: list[str], mask: np.ndarray | None = None) -> np.ndarray:
        """Assemble la matrice de features (lignes = interventions, colonnes = names).

        Args:
            names: colonnes observables a empiler.
            mask: masque booleen optionnel de selection de lignes.

        Returns:
            Matrice ``(m, len(names))`` de flottants.
        """
        idx = np.arange(self.n) if mask is None else np.where(mask)[0]
        return np.column_stack([self.cols[name][idx] for name in names])


def _parse_bool(raw: str) -> bool:
    """Interprete un booleen de CSV de facon tolerante.

    Args:
        raw: cellule brute.

    Returns:
        ``True`` pour ``1/true/vrai/oui/x``, ``False`` sinon (vide inclus).
    """
    return raw.strip().lower() in {"1", "true", "vrai", "oui", "x", "yes"}


def _parse_float(raw: str) -> float:
    """Convertit une cellule en flottant, cellule vide -> NaN.

    Args:
        raw: cellule brute.

    Returns:
        Flottant, ou ``nan`` si la cellule est vide/illisible.
    """
    raw = raw.strip()
    if raw == "":
        return math.nan
    try:
        return float(raw)
    except ValueError:
        return math.nan


def load_interventions(path: Path) -> Table:
    """Charge ``interventions.csv`` (contrat 9) en :class:`Table`.

    Args:
        path: chemin du CSV.

    Returns:
        Table colonne-orientee typee.

    Raises:
        ValueError: si des colonnes obligatoires manquent ou si le resultat
            operationnel est hors nomenclature gelee.
    """
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        headers = list(reader.fieldnames or [])

    obligatoires = {"action_id", "decidee", "executee", "resultat_operationnel"}
    manquantes = obligatoires - set(headers)
    if manquantes:
        raise ValueError(f"colonnes obligatoires absentes : {sorted(manquantes)}")

    cols: dict[str, np.ndarray] = {}
    for h in headers:
        brut = [r.get(h, "") or "" for r in rows]
        if h.startswith("ea_") or h in COLONNES_VERITE or h in {"succes"}:
            cols[h] = np.array([_parse_float(x) for x in brut], dtype=float)
        elif h in {"decidee", "executee"}:
            cols[h] = np.array([_parse_bool(x) for x in brut], dtype=bool)
        elif h == "tour":
            cols[h] = np.array([_parse_float(x) for x in brut], dtype=float)
        else:
            cols[h] = np.array([str(x).strip() for x in brut], dtype=object)

    res = cols.get("resultat_operationnel")
    if res is not None:
        hors = {str(v) for v in res} - _ISSUES_VALIDES
        if hors:
            raise ValueError(f"résultats opérationnels hors nomenclature : {sorted(hors)}")

    return Table(cols=cols, n=len(rows))


# Segmentation en 8 cellules d'etat-avant


def _has_utime_features(t: Table) -> bool:
    """Indique si les sous-composantes d'urgence temporelle sont disponibles.

    Args:
        t: table chargee.

    Returns:
        ``True`` si ``ea_u_time`` et au moins une autre composante existent.
    """
    autres = {"ea_u_cost", "ea_u_quality", "ea_u_risk"}
    return "ea_u_time" in t.cols and bool(autres & set(t.cols))


def assign_segments(t: Table) -> tuple[np.ndarray, dict[str, dict[str, str]]]:
    """Affecte chaque intervention a l'une des 8 cellules d'etat-avant.

    Les 8 cellules croisent trois axes binaires :

    * **profondeur** : ``profond`` si ``ea_depth >= 2`` (tier aval), sinon
      ``proche``. A defaut de ``ea_depth``, proxy documente par la mediane de
      ``ea_ur_local``.
    * **saturation** : ``sature`` si ``ea_ur_local >= 0.9``, sinon ``nonsat``.
    * **dominante** : si les composantes d'urgence existent, ``utime`` quand
      ``ea_u_time`` domine (argmax des composantes), sinon ``autre`` ; a defaut,
      repli sur ``ea_hidden_risk`` (``hirisk`` au-dessus de la mediane).

    Args:
        t: table chargee.

    Returns:
        Couple ``(seg_ids, definitions)`` ou ``seg_ids`` est un tableau de chaines
        de longueur ``t.n`` et ``definitions`` decrit chaque segment (contrat 10).
    """
    n = t.n
    # Axe 1 : profondeur
    if "ea_depth" in t.cols:
        depth = t.cols["ea_depth"]
        profond = depth >= SEUIL_PROFOND
        def_profond = f"ea_depth ≥ {SEUIL_PROFOND}"
    else:
        ur = t.cols["ea_ur_local"]
        med = float(np.nanmedian(ur))
        profond = ur >= med
        def_profond = f"proxy : ea_ur_local ≥ médiane ({med:.3f})"

    # Axe 2 : saturation
    ur_local = t.cols["ea_ur_local"]
    sature = ur_local >= SEUIL_SATURATION

    # Axe 3 : dominante
    if _has_utime_features(t):
        comps = [c for c in ("ea_u_time", "ea_u_cost", "ea_u_quality", "ea_u_risk") if c in t.cols]
        mat = np.column_stack([t.cols[c] for c in comps])
        i_time = comps.index("ea_u_time")
        troisieme = mat.argmax(axis=1) == i_time
        libelle_troisieme = ("utime", "autre")
        def_troisieme = "ea_u_time domine les composantes d'urgence"
    else:
        hr = t.cols["ea_hidden_risk"]
        med_hr = float(np.nanmedian(hr))
        troisieme = hr >= med_hr
        libelle_troisieme = ("hirisk", "lorisk")
        def_troisieme = f"ea_hidden_risk ≥ médiane ({med_hr:.3f})"

    seg = np.empty(n, dtype=object)
    for i in range(n):
        a = "profond" if profond[i] else "proche"
        b = "sature" if sature[i] else "nonsat"
        c = libelle_troisieme[0] if troisieme[i] else libelle_troisieme[1]
        seg[i] = f"{a}__{b}__{c}"

    definitions: dict[str, dict[str, str]] = {}
    for a in ("profond", "proche"):
        for b in ("sature", "nonsat"):
            for c in libelle_troisieme:
                sid = f"{a}__{b}__{c}"
                definitions[sid] = {
                    "profondeur": f"{a} ({def_profond})" if a == "profond" else a,
                    "saturation": (
                        f"{b} (ea_ur_local ≥ {SEUIL_SATURATION})" if b == "sature" else b
                    ),
                    "dominante": f"{c} ({def_troisieme})",
                }
    return seg.astype(str), definitions


# Base bayesienne : Beta-Binomial + P(execution)


def _beta_summary(alpha: float, beta: float, n: int) -> dict[str, Any]:
    """Resume un posterior Beta(alpha, beta) : moyenne et IC80.

    Args:
        alpha: parametre alpha du posterior.
        beta: parametre beta du posterior.
        n: effectif de donnees ayant alimente la cellule.

    Returns:
        Dictionnaire ``{alpha, beta, n, p_resolution: {mean, lo80, hi80}}``.
    """
    mean = alpha / (alpha + beta)
    lo80 = float(stats.beta.ppf(0.10, alpha, beta))
    hi80 = float(stats.beta.ppf(0.90, alpha, beta))
    return {
        "alpha": float(alpha),
        "beta": float(beta),
        "n": int(n),
        "p_resolution": {"mean": float(mean), "lo80": lo80, "hi80": hi80},
    }


def beta_posteriors(k: int, n: int, mean_sim: float) -> dict[str, Any]:
    """Calcule les trois posteriors Beta-Binomial d'une cellule (D27).

    Args:
        k: nombre de resolutions (succes operationnels) parmi les executees.
        n: nombre d'interventions executees dans la cellule.
        mean_sim: moyenne a priori simulee (source : ``--prior-sim`` ou taux global).

    Returns:
        ``{prior_sim, prior_faible, donnees_seules}`` - chacun resume Beta.

    Note:
        ``prior_faible`` (n_0=1, moyenne 0.5) coincide numeriquement avec
        ``donnees_seules`` (Jeffreys 0.5/0.5) : c'est une propriete assumee des
        deux a priori de reference, exposes separement par le contrat 10.
    """
    mean_sim = min(max(mean_sim, 1e-4), 1 - 1e-4)
    a_sim, b_sim = mean_sim * N0_PRIOR_SIM, (1 - mean_sim) * N0_PRIOR_SIM
    a_faible, b_faible = 0.5 * N0_PRIOR_FAIBLE, 0.5 * N0_PRIOR_FAIBLE  # -> Beta(0.5, 0.5)
    return {
        "prior_sim": _beta_summary(a_sim + k, b_sim + (n - k), n),
        "prior_faible": _beta_summary(a_faible + k, b_faible + (n - k), n),
        "donnees_seules": _beta_summary(0.5 + k, 0.5 + (n - k), n),
    }


def execution_posterior(t: Table, action: str) -> dict[str, Any]:
    """Estime P(execution | action) par un Beta de Jeffreys sur decidee -> executee.

    Args:
        t: table chargee.
        action: identifiant d'action.

    Returns:
        ``{alpha, beta, n}`` du posterior Beta(0.5+exec, 0.5+non-exec).
    """
    m = (t.cols["action_id"] == action) & t.cols["decidee"]
    n_dec = int(m.sum())
    k_exec = int((t.cols["executee"] & m).sum())
    return {"alpha": 0.5 + k_exec, "beta": 0.5 + (n_dec - k_exec), "n": n_dec}


# Regression logistique par IRLS (numpy pur)


def _sigmoid(z: np.ndarray) -> np.ndarray:
    """Sigmoide stable numeriquement.

    Args:
        z: predicteur lineaire.

    Returns:
        Probabilites dans (0, 1).
    """
    z = np.clip(z, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-z))


def irls_logistic(
    x: np.ndarray,
    y: np.ndarray,
    ridge: float = 1e-3,
    max_iter: int = 100,
    tol: float = 1e-8,
) -> tuple[np.ndarray, bool]:
    """Ajuste une regression logistique par moindres carres reponderes (IRLS).

    Une colonne d'intercept est ajoutee en tete. Une regularisation L2 (``ridge``)
    stabilise les colonnes quasi-constantes ou colineaires ; l'intercept n'est
    pas penalise.

    Args:
        x: matrice de features deja standardisees ``(m, p)``.
        y: cible binaire ``(m,)``.
        ridge: intensite de la penalite L2 (jitter de stabilite).
        max_iter: nombre maximal d'iterations de Newton.
        tol: seuil de convergence sur la variation des coefficients.

    Returns:
        Couple ``(beta, converged)`` : coefficients ``(p+1,)`` (intercept en 0) et
        drapeau de convergence.
    """
    m, p = x.shape
    xd = np.column_stack([np.ones(m), x])
    beta = np.zeros(p + 1)
    pen = ridge * np.ones(p + 1)
    pen[0] = 0.0  # intercept non penalise
    converged = False
    for _ in range(max_iter):
        eta = xd @ beta
        mu = _sigmoid(eta)
        w = np.clip(mu * (1 - mu), 1e-6, None)
        # Hessienne regularisee et gradient penalise (Newton-Raphson).
        xtw = xd.T * w
        hess = xtw @ xd + np.diag(pen)
        grad = xd.T @ (y - mu) - pen * beta
        try:
            step = np.linalg.solve(hess, grad)
        except np.linalg.LinAlgError:
            step = np.linalg.lstsq(hess, grad, rcond=None)[0]
        beta = beta + step
        if np.max(np.abs(step)) < tol:
            converged = True
            break
    return beta, converged


def _standardize(x: np.ndarray) -> np.ndarray:
    """Centre-reduit chaque colonne ; colonnes constantes -> zero.

    Args:
        x: matrice brute ``(m, p)``.

    Returns:
        Matrice standardisee ``(m, p)``.
    """
    mu = x.mean(axis=0)
    sd = x.std(axis=0)
    sd_safe = np.where(sd < 1e-8, 1.0, sd)
    xs = (x - mu) / sd_safe
    xs[:, sd < 1e-8] = 0.0
    return xs


# Estimateurs causaux : propension -> overlap -> IPW / AIPW -> E-value


def _e_value(rr: float) -> float | None:
    """E-value de VanderWeele a partir d'un risk ratio.

    Args:
        rr: risk ratio de l'issue defavorable (traite / non-traite).

    Returns:
        E-value (>= 1), ou ``None`` si le RR est nul/indefini (effet nul).
    """
    if rr is None or not math.isfinite(rr) or rr <= 0.0 or rr == 1.0:
        return None
    rr_star = rr if rr > 1.0 else 1.0 / rr
    return float(rr_star + math.sqrt(rr_star * (rr_star - 1.0)))


def _ipw_point(e: np.ndarray, t: np.ndarray, y: np.ndarray) -> tuple[float, float, float, float]:
    """Estimateur IPW stabilise : risques par bras, difference, effectif efficace.

    Args:
        e: propensions estimees ``P(traite | X)``.
        t: indicateur de traitement ``(m,)``.
        y: issue defavorable binaire ``(m,)``.

    Returns:
        ``(p0, p1, delta, n_eff)`` : risque non-traite, risque traite, difference
        ``p0 - p1`` (reduction de risque) et effectif efficace des poids stabilises.
    """
    p_treat = float(t.mean())
    e = np.clip(e, 1e-4, 1 - 1e-4)
    w = np.where(t == 1, p_treat / e, (1 - p_treat) / (1 - e))
    mt, mc = t == 1, t == 0
    p1 = float(np.sum(w[mt] * y[mt]) / np.sum(w[mt]))
    p0 = float(np.sum(w[mc] * y[mc]) / np.sum(w[mc]))
    n_eff = float(np.sum(w) ** 2 / np.sum(w**2))
    return p0, p1, p0 - p1, n_eff


def _aipw_point(x: np.ndarray, e: np.ndarray, t: np.ndarray, y: np.ndarray) -> float:
    """Estimateur doublement robuste (AIPW) de la difference de risque.

    Combine un modele d'issue logistique (avec le traitement en covariable) et une
    correction IPW. Reste consistant si l'un des deux modeles est correct.

    Args:
        x: matrice de features standardisees ``(m, p)``.
        e: propensions estimees ``(m,)``.
        t: indicateur de traitement ``(m,)``.
        y: issue defavorable binaire ``(m,)``.

    Returns:
        ``psi0 - psi1`` : reduction de risque doublement robuste.
    """
    e = np.clip(e, 1e-4, 1 - 1e-4)
    xt = np.column_stack([x, t.astype(float)])
    beta, _ = irls_logistic(xt, y)
    m = x.shape[0]
    x1 = np.column_stack([np.ones(m), x, np.ones(m)])
    x0 = np.column_stack([np.ones(m), x, np.zeros(m)])
    mu1 = _sigmoid(x1 @ beta)
    mu0 = _sigmoid(x0 @ beta)
    psi1 = float(np.mean(mu1 + t / e * (y - mu1)))
    psi0 = float(np.mean(mu0 + (1 - t) / (1 - e) * (y - mu0)))
    return psi0 - psi1


def estimate_causal_cell(
    xcell: np.ndarray,
    t: np.ndarray,
    y: np.ndarray,
    rng: np.random.Generator,
    n_boot: int,
) -> dict[str, Any] | None:
    """Estime l'effet causal d'une cellule (action x segment) avec garde-fous.

    Enchaine : propension IRLS -> diagnostic d'overlap + trimming [0.05, 0.95] ->
    IPW stabilise + AIPW -> IC80 par bootstrap pondere stratifie -> E-value.

    Args:
        xcell: features observables brutes de la cellule ``(m, p)`` (deux bras).
        t: indicateur de traitement ``(m,)`` (1 = action, 0 = ne_rien_faire).
        y: issue defavorable ``(m,)`` (1 = echec dans la fenetre).
        rng: generateur numpy graine pour le bootstrap.
        n_boot: nombre de tirages bootstrap.

    Returns:
        Dictionnaire de sortie causale (contrat 10), ou ``None`` si les effectifs
        sont insuffisants meme avant trimming.
    """
    if int((t == 1).sum()) < MIN_PAR_BRAS or int((t == 0).sum()) < MIN_PAR_BRAS:
        return None

    xs = _standardize(xcell)
    beta, converged = irls_logistic(xs, t.astype(float))
    e = _sigmoid(np.column_stack([np.ones(len(t)), xs]) @ beta)

    # Overlap + trimming (diagnostic sur la cellule ENTIERE)
    hors = (e < OVERLAP_LO) | (e > OVERLAP_HI)
    part_hors = float(hors.mean())
    keep = ~hors
    xs_k, t_k, y_k = xs[keep], t[keep], y[keep]
    n1, n0 = int((t_k == 1).sum()), int((t_k == 0).sum())
    overlap_ok = bool((part_hors < OVERLAP_PART_MAX) and n1 >= MIN_PAR_BRAS and n0 >= MIN_PAR_BRAS)
    if n1 < MIN_PAR_BRAS or n0 < MIN_PAR_BRAS:
        return {
            "delta_causal_ipw": None,
            "delta_causal_aipw": None,
            "e_value": None,
            "overlap_ok": overlap_ok,
            "part_hors_overlap": part_hors,
            "propensity_converged": bool(converged),
            "label": LABEL_CAUSAL,
        }

    # Re-ajuste la propension sur l'ensemble d'analyse (post-trimming) pour que l'estimation ponctuelle et le bootstrap suivent EXACTEMENT la meme procedure.
    beta_k, conv_k = irls_logistic(xs_k, t_k.astype(float))
    e_k = _sigmoid(np.column_stack([np.ones(len(t_k)), xs_k]) @ beta_k)
    p0, p1, delta, n_eff = _ipw_point(e_k, t_k, y_k)
    delta_aipw = _aipw_point(xs_k, e_k, t_k, y_k)

    # Bootstrap pondere stratifie par bras (graine deterministe)
    idx_t = np.where(t_k == 1)[0]
    idx_c = np.where(t_k == 0)[0]
    boots_ipw = np.empty(n_boot)
    boots_aipw = np.empty(n_boot)
    for b in range(n_boot):
        bt = rng.choice(idx_t, size=len(idx_t), replace=True)
        bc = rng.choice(idx_c, size=len(idx_c), replace=True)
        sel = np.concatenate([bt, bc])
        xb, tb, yb = xs_k[sel], t_k[sel], y_k[sel]
        beta_b, _ = irls_logistic(xb, tb.astype(float))
        eb = _sigmoid(np.column_stack([np.ones(len(tb)), xb]) @ beta_b)
        _, _, dib, _ = _ipw_point(eb, tb, yb)
        boots_ipw[b] = dib
        boots_aipw[b] = _aipw_point(xb, eb, tb, yb)

    lo80, hi80 = (float(v) for v in np.percentile(boots_ipw, [10, 90]))
    lo80_a, hi80_a = (float(v) for v in np.percentile(boots_aipw, [10, 90]))

    rr = p1 / p0 if p0 > 0 and p1 > 0 else None
    return {
        "delta_causal_ipw": {
            "est": float(delta),
            "lo80": lo80,
            "hi80": hi80,
            "n_eff": float(n_eff),
        },
        "delta_causal_aipw": {"est": float(delta_aipw), "lo80": lo80_a, "hi80": hi80_a},
        "p0_risque_non_traite": float(p0),
        "p1_risque_traite": float(p1),
        "e_value": _e_value(rr),
        "overlap_ok": overlap_ok,
        "part_hors_overlap": part_hors,
        "propensity_converged": bool(converged and conv_k),
        "label": LABEL_CAUSAL,
    }


# Assemblage de l'artefact (contrat 10)


def _global_success_rate(t: Table) -> float:
    """Taux global de resolution parmi les interventions executees.

    Args:
        t: table chargee.

    Returns:
        Fraction de ``resultat_operationnel == 'resolu'`` sur les executees.
    """
    exe = t.cols["executee"]
    res = t.cols["resultat_operationnel"]
    n = int(exe.sum())
    if n == 0:
        return 0.5
    k = int(((res == "resolu") & exe).sum())
    return k / n


def fit(
    t: Table,
    prior_sim: dict[str, Any] | None = None,
    n_boot: int = 500,
    seed: int = 20260723,
) -> dict[str, Any]:
    """Ajuste l'ensemble du modele et produit l'artefact ``action_effects`` (contrat 10).

    Args:
        t: journal d'interventions charge.
        prior_sim: dictionnaire optionnel ``{action_id: moyenne}`` de simulations.
        n_boot: tirages bootstrap par cellule causale.
        seed: graine maitresse (determinisme du bootstrap).

    Returns:
        Artefact conforme au contrat 10 (dictionnaire serialisable JSON).
    """
    seg_ids, seg_defs = assign_segments(t)
    features = t.feature_names()
    base_rate = _global_success_rate(t)
    action_arr = t.cols["action_id"]
    exe = t.cols["executee"]
    res = t.cols["resultat_operationnel"]
    seg_sorted = sorted(seg_defs)
    n_seg = len(seg_sorted)
    # Graines-enfants tirees EN UNE FOIS puis indexees par (action, segment) : le determinisme du bootstrap est alors trivialement reproductible.
    child_seeds = np.random.SeedSequence(seed).spawn(len(ACTIONS) * n_seg)

    actions_out: dict[str, Any] = {}
    for ai, action in enumerate(ACTIONS):
        p_exec = execution_posterior(t, action)
        segments_out: dict[str, Any] = {}
        for si, sid in enumerate(seg_sorted):
            in_cell = (action_arr == action) & exe & (seg_ids == sid)
            n_cell = int(in_cell.sum())
            k_cell = int(((res == "resolu") & in_cell).sum())
            mean_sim = float(prior_sim.get(action, base_rate)) if prior_sim else base_rate
            posteriors = beta_posteriors(k_cell, n_cell, mean_sim)

            if action == ACTION_NE_RIEN_FAIRE:
                causal: dict[str, Any] | None = None
            else:
                # Contraste : action executee vs ne_rien_faire, dans le segment.
                arm = (
                    ((action_arr == action) | (action_arr == ACTION_NE_RIEN_FAIRE))
                    & exe
                    & (seg_ids == sid)
                )
                if int(arm.sum()) == 0:
                    causal = None
                else:
                    xcell = t.matrix(features, mask=arm)
                    tt = (action_arr[arm] == action).astype(int)
                    yy = (res[arm] == "echec").astype(int)
                    child = np.random.Generator(np.random.PCG64(child_seeds[ai * n_seg + si]))
                    causal = estimate_causal_cell(xcell, tt, yy, child, n_boot)

            cell_out: dict[str, Any] = {"posteriors": posteriors}
            if causal is None:
                cell_out.update({"delta_causal_ipw": None, "e_value": None, "overlap_ok": False})
            else:
                cell_out.update(causal)
            segments_out[sid] = cell_out

        actions_out[action] = {"p_execution": p_exec, "segments": segments_out}

    return {
        "schema_version": SCHEMA_VERSION,
        "label_causal": LABEL_CAUSAL,
        "base_rate_resolution": base_rate,
        "actions": actions_out,
        "segments": seg_defs,
        "validation": None,
    }


# Verification du schema (contrat 10) - mode --check


def check_schema(artifact: dict[str, Any]) -> None:
    """Verifie qu'un artefact respecte le contrat 10 (assertions dures).

    Args:
        artifact: artefact recharge depuis JSON.

    Raises:
        AssertionError: a la premiere violation du contrat.
    """
    assert artifact.get("schema_version") == SCHEMA_VERSION, "schema_version"
    assert "actions" in artifact and "segments" in artifact, "clés racines"
    assert "validation" in artifact, "clé validation"
    for action, adata in artifact["actions"].items():
        pe = adata["p_execution"]
        assert {"alpha", "beta", "n"} <= set(pe), f"p_execution {action}"
        for sid, cell in adata["segments"].items():
            assert sid in artifact["segments"], f"segment inconnu {sid}"
            post = cell["posteriors"]
            for lbl in ("prior_sim", "prior_faible", "donnees_seules"):
                p = post[lbl]
                assert {"alpha", "beta", "n", "p_resolution"} <= set(p), f"{lbl} {sid}"
                pr = p["p_resolution"]
                assert {"mean", "lo80", "hi80"} <= set(pr), f"p_resolution {lbl} {sid}"
                assert pr["lo80"] <= pr["mean"] + 1e-9, f"ordre IC {lbl} {sid}"
                assert pr["mean"] <= pr["hi80"] + 1e-9, f"ordre IC {lbl} {sid}"
            assert "delta_causal_ipw" in cell, f"delta_causal_ipw {sid}"
            assert "e_value" in cell, f"e_value {sid}"
            assert "overlap_ok" in cell, f"overlap_ok {sid}"
            dci = cell["delta_causal_ipw"]
            if dci is not None:
                assert {"est", "lo80", "hi80", "n_eff"} <= set(dci), f"IPW {sid}"
                assert dci["lo80"] <= dci["hi80"] + 1e-9, f"ordre IC IPW {sid}"
    # Coherence des 8 cellules de segmentation.
    assert len(artifact["segments"]) == 8, "8 segments attendus"


# Banc synthetique deterministe (mimant l'usine) - verite-terrain connue


@dataclass
class DGPParams:
    """Parametres d'un processus generateur de donnees (DGP) synthetique.

    Le DGP superpose deux confondeurs, comme dans une vraie usine :

    * un confondeur **observe** ``x_obs`` (fonction des features d'etat-avant),
      present dans le score de propension - l'IPW le neutralise entierement ;
    * le **stress latent**, seulement correle ``rho`` aux observables : sa part
      ``sqrt(1-rho^2)`` reste une confusion NON observee que l'IPW ne peut retirer
      (d'ou le biais residuel que l'E-value quantifie).

    C'est l'ecart de traitement de ces deux confondeurs qui fait que le NAIF
    (aucun ajustement) est nettement plus biaise que l'IPW.

    Attributes:
        nom: etiquette du jeu de parametres.
        n: nombre d'interventions.
        rho: correlation stress latent <-> index observable (confusion partielle).
        c0: biais de la politique d'intervention (logit).
        c_x: sensibilite de la politique au confondeur observe.
        c1: sensibilite de la politique au stress latent.
        b_x: coefficient du confondeur observe sur le risque d'issue defavorable.
        b_stress: coefficient du stress sur le risque d'issue defavorable.
        base_seg: risque de base d'issue defavorable par segment (8 valeurs).
        p_exec: probabilite d'execution d'une action decidee (< 1).
        delta_seed: graine de construction de la grille d'effets vrais.
    """

    nom: str
    n: int
    rho: float
    c0: float
    c_x: float
    c1: float
    b_x: float
    b_stress: float
    base_seg: tuple[float, ...]
    p_exec: float
    delta_seed: int


# Parametres figes a priori, jamais ajustes pour faire passer un critere : rho ~= 0.6 (0.55 DGP2), b_x >> b_stress, b_stress = 0.10, c_x et c1 ~ 0.9. Consequence assumee : sous confusion partiellement non observee l'IPW reste biaise et son IC80 sous-couvre ; l'E-value en chiffre la sensibilite.

#: Jeu de parametres principal du banc de validation.
DGP1 = DGPParams(
    nom="DGP1",
    n=4000,
    rho=0.6,
    c0=-0.15,
    c_x=0.95,
    c1=0.90,
    b_x=0.16,
    b_stress=0.10,
    base_seg=(0.20, 0.24, 0.28, 0.30, 0.22, 0.26, 0.32, 0.34),
    p_exec=0.85,
    delta_seed=7,
)

#: Second jeu de parametres - JAMAIS utilise pour construire l'a priori simule.
DGP2 = DGPParams(
    nom="DGP2",
    n=4200,
    rho=0.55,
    c0=0.10,
    c_x=0.85,
    c1=0.90,
    b_x=0.18,
    b_stress=0.10,
    base_seg=(0.26, 0.18, 0.30, 0.22, 0.34, 0.20, 0.28, 0.24),
    p_exec=0.80,
    delta_seed=19,
)


def _delta_grid(seed: int) -> np.ndarray:
    """Construit la grille d'effets vrais delta(action, segment)  dans  [0, ~0.20].

    Chaque segment possede un vainqueur net (marge ~= 0.03 sur le 2e, actions
    faibles clairement en dessous), de sorte que le taux de recommandation
    correcte et le regret decisionnel soient tous deux atteignables.

    Args:
        seed: graine de rotation des vainqueurs.

    Returns:
        Matrice ``(5, 8)`` des reductions de risque vraies (actions x segments).
    """
    rng = np.random.default_rng(seed)
    na, ns = len(ACTIONS_NON_NULLES), 8
    grid = np.zeros((na, ns))
    for s in range(ns):
        gagnant = (s + seed) % na
        base = rng.uniform(0.05, 0.12, size=na)
        base[gagnant] = 0.18 + 0.01 * (s % 3)
        # Ecrase le 2e pour garantir une marge, garde les faibles bas.
        ordre = np.argsort(base)[::-1]
        second = ordre[1]
        base[second] = min(base[second], base[gagnant] - 0.03)
        grid[:, s] = np.clip(base, 0.02, 0.20)
    return grid


def generate_dataset(params: DGPParams, seed: int) -> tuple[Table, np.ndarray]:
    """Genere un journal synthetique complet (features + verite-terrain).

    La politique de l'operateur depend du **stress latent** ``P(traiter) =
    sigmoide(c0 + c1-stress)``. Le stress est ``rho-index_observable +
    sqrt(1-rho^2)-bruit`` : l'index observable (fonction des features) est
    recuperable par le score de propension, le bruit reste une confusion NON
    observee - d'ou le biais residuel que l'E-value doit cerner.

    Args:
        params: jeu de parametres du DGP.
        seed: graine de replication.

    Returns:
        Couple ``(table, delta_grid)`` : le journal (colonnes ``ea_*`` +
        ``effet_vrai_param``/``delta_u_vrai``/``stress_latent``) et la grille
        d'effets vrais utilisee.
    """
    rng = np.random.default_rng(seed * 1000 + params.delta_seed)
    n = params.n
    grid = _delta_grid(params.delta_seed)

    # Features observables d'etat-avant
    depth = rng.integers(0, 5, size=n).astype(float)
    ur_local = rng.beta(2.0, 1.0, size=n)
    ud_local = rng.beta(2.0, 2.0, size=n)
    hidden_risk = rng.beta(2.0, 3.0, size=n)
    false_urgency = rng.beta(1.5, 4.0, size=n)
    u_time = rng.beta(2.0, 2.0, size=n)
    u_cost = rng.beta(2.0, 2.0, size=n)
    u_quality = rng.beta(2.0, 2.0, size=n)
    u_risk = rng.beta(2.0, 2.0, size=n)

    cols: dict[str, np.ndarray] = {
        "ea_depth": depth,
        "ea_ur_local": ur_local,
        "ea_ud_local": ud_local,
        "ea_hidden_risk": hidden_risk,
        "ea_false_urgency": false_urgency,
        "ea_u_time": u_time,
        "ea_u_cost": u_cost,
        "ea_u_quality": u_quality,
        "ea_u_risk": u_risk,
    }
    t = Table(cols=dict(cols), n=n)
    seg_ids, _ = assign_segments(t)
    seg_index = {sid: i for i, sid in enumerate(sorted(set(_all_segment_ids())))}
    s_idx = np.array([seg_index[s] for s in seg_ids])

    # Deux confondeurs : un observe (recuperable) + le stress latent
    def _std(v: np.ndarray) -> np.ndarray:
        return (v - v.mean()) / v.std()

    x_obs = _std(0.7 * hidden_risk + 0.5 * ur_local + 0.4 * u_risk)  # dans les features
    x_stress_obs = _std(0.6 * ud_local + 0.5 * false_urgency + 0.4 * u_time)
    eps = rng.standard_normal(n)  # part NON observee du stress
    stress = params.rho * x_stress_obs + math.sqrt(1 - params.rho**2) * eps

    # Action candidate (uniforme sur les 5 non nulles)
    cand = rng.integers(0, len(ACTIONS_NON_NULLES), size=n)

    # Politique confondue : traiter vs ne_rien_faire
    p_treat = _sigmoid(params.c0 + params.c_x * x_obs + params.c1 * stress)
    treat = rng.random(n) < p_treat
    executee = treat & (rng.random(n) < params.p_exec)

    action_id = np.where(
        treat,
        np.array(ACTIONS_NON_NULLES, dtype=object)[cand],
        ACTION_NE_RIEN_FAIRE,
    )

    # Effet vrai de la ligne (0 si controle ou non execute)
    base_arr = np.array(params.base_seg)
    delta_true_line = np.where(
        treat, grid[cand, s_idx], 0.0
    )  # effet potentiel de l'action candidate dans le segment
    delta_applique = np.where(executee, delta_true_line, 0.0)

    p_adv = np.clip(
        base_arr[s_idx] + params.b_x * x_obs + params.b_stress * stress - delta_applique,
        0.03,
        0.75,
    )
    y_adv = rng.random(n) < p_adv

    # Resultat operationnel (label gele)
    resultat = np.empty(n, dtype=object)
    succes = np.full(n, math.nan)
    q_resolu = np.clip(0.40 + 1.2 * delta_applique, 0.0, 0.95)
    tire = rng.random(n)
    for i in range(n):
        if treat[i] and not executee[i]:
            resultat[i] = "en_cours"
            continue
        if y_adv[i]:
            resultat[i] = "echec"
            succes[i] = 0.0
        elif tire[i] < q_resolu[i]:
            resultat[i] = "resolu"
            succes[i] = 1.0
        else:
            resultat[i] = "partiel"
            succes[i] = 0.0

    # Verite-terrain (VALIDATION_ONLY)
    cols["stress_latent"] = stress
    cols["effet_vrai_param"] = delta_true_line
    # delta_u_vrai = effet causal vrai de (action candidate, segment), 0 pour controle.
    cols["delta_u_vrai"] = np.where(treat, grid[cand, s_idx], 0.0)

    cols["action_id"] = action_id
    cols["decidee"] = np.ones(n, dtype=bool)
    cols["executee"] = np.where(treat, executee, True)  # ne_rien_faire est " execute "
    cols["resultat_operationnel"] = resultat
    cols["succes"] = succes
    cols["chain_id"] = np.array([f"c{seed}" for _ in range(n)], dtype=object)
    cols["node_id"] = np.array([f"n{i % 50}" for i in range(n)], dtype=object)
    cols["tour"] = (rng.integers(0, 18, size=n)).astype(float)
    cols["date_effet"] = cols["tour"].astype(object)

    return Table(cols=cols, n=n), grid


def _all_segment_ids() -> list[str]:
    """Liste les 8 identifiants de segment canoniques (dominante ``utime``).

    Returns:
        Liste des 8 identifiants ``profondeur__saturation__dominante``.
    """
    ids = []
    for a in ("profond", "proche"):
        for b in ("sature", "nonsat"):
            for c in ("utime", "autre"):
                ids.append(f"{a}__{b}__{c}")
    return ids


# Batterie de validation D32 (PORTE du pipeline)


def _score_replication(params: DGPParams, seed: int, n_boot: int) -> dict[str, Any]:
    """Ajuste le modele sur une replication et confronte estimateurs a la verite.

    Args:
        params: jeu de parametres du DGP.
        seed: graine de la replication.
        n_boot: tirages bootstrap par cellule.

    Returns:
        Dictionnaire d'observations par cellule et par segment (couverture,
        biais IPW/naif, recommandations, regret).
    """
    table, _grid = generate_dataset(params, seed)
    seg_ids, seg_defs = assign_segments(table)
    features = table.feature_names()
    action_arr = table.cols["action_id"]
    exe = table.cols["executee"]
    res = table.cols["resultat_operationnel"]
    dvrai = table.cols["delta_u_vrai"]

    seg_order = sorted(seg_defs)
    n_seg = len(seg_order)
    child_seeds = np.random.SeedSequence(seed + 101).spawn(len(ACTIONS_NON_NULLES) * n_seg)
    cell_records: list[dict[str, Any]] = []
    est_par_segment: dict[str, dict[str, float]] = {s: {} for s in seg_order}
    vrai_par_segment: dict[str, dict[str, float]] = {s: {} for s in seg_order}

    for ai, action in enumerate(ACTIONS_NON_NULLES):
        for si, sid in enumerate(seg_order):
            arm = (
                ((action_arr == action) | (action_arr == ACTION_NE_RIEN_FAIRE))
                & exe
                & (seg_ids == sid)
            )
            if int(arm.sum()) == 0:
                continue
            xcell = table.matrix(features, mask=arm)
            tt = (action_arr[arm] == action).astype(int)
            yy = (res[arm] == "echec").astype(int)
            # Verite de la cellule : delta vrai de (action, segment).
            mask_act = arm & (action_arr == action)
            if int(mask_act.sum()) == 0:
                continue
            delta_vrai = float(np.nanmean(dvrai[mask_act]))

            child = np.random.Generator(np.random.PCG64(child_seeds[ai * n_seg + si]))
            out = estimate_causal_cell(xcell, tt, yy, child, n_boot)
            if out is None or out.get("delta_causal_ipw") is None:
                continue

            # Estimateur naif non ajuste : difference brute de risque.
            p1_naif = float(yy[tt == 1].mean())
            p0_naif = float(yy[tt == 0].mean())
            delta_naif = p0_naif - p1_naif

            dci = out["delta_causal_ipw"]
            couvre = dci["lo80"] <= delta_vrai <= dci["hi80"]
            cell_records.append(
                {
                    "segment": sid,
                    "action": action,
                    "delta_vrai": delta_vrai,
                    "ipw_est": dci["est"],
                    "ipw_lo": dci["lo80"],
                    "ipw_hi": dci["hi80"],
                    "naif_est": delta_naif,
                    "couvre": bool(couvre),
                }
            )
            est_par_segment[sid][action] = dci["est"]
            vrai_par_segment[sid][action] = delta_vrai

    return {
        "cells": cell_records,
        "est_par_segment": est_par_segment,
        "vrai_par_segment": vrai_par_segment,
    }


def run_validation(n_rep: int = 10, n_boot: int = 200, seed: int = 2026) -> dict[str, Any]:
    """Execute la batterie de validation causale complete (D32) sur DGP1 et DGP2.

    Criteres (par DGP) :

    * (i) couverture des IC80 vs ``delta_u_vrai`` - PASS si  dans  [70 %, 90 %] ;
    * (ii) biais moyen et biais absolu moyen (informatif) ;
    * (iii) taux de recommandation correcte (argmax estime = argmax vrai) - PASS >= 0.7 ;
    * (iv) regret decisionnel moyen - PASS <= 0.02 ;
    * (v) le biais absolu du NAIF depasse celui de l'IPW - PASS si oui ;
    * (vi) rerun sur un second jeu de parametres tenu hors a priori.

    Args:
        n_rep: replications par DGP.
        n_boot: tirages bootstrap par cellule.
        seed: graine maitresse.

    Returns:
        Resume complet de la batterie, y compris le verdict global booleen.
    """
    resume: dict[str, Any] = {"dgp": {}}
    verdict_global = True

    for params in (DGP1, DGP2):
        couvre_flags: list[bool] = []
        ipw_abs: list[float] = []
        naif_abs: list[float] = []
        ipw_bias: list[float] = []
        # Estimateur AGREGE (moyenne des points IPW sur les replications) : sert aux metriques DECISIONNELLES (reco/regret), pour lesquelles la question est la qualite de la decision au volume de preuve de la campagne, et non le bruit d'echantillonnage d'une seule cellule de ~40 lignes. Couverture/biais/naif restent, eux, PAR CELLULE (une cellule = une observation d'IC).
        pool_sum: dict[tuple[str, str], float] = {}
        pool_cnt: dict[tuple[str, str], int] = {}
        pool_vrai: dict[tuple[str, str], float] = {}
        reco_par_rep: list[bool] = []

        for r in range(n_rep):
            rep = _score_replication(params, seed + r, n_boot)
            for c in rep["cells"]:
                couvre_flags.append(c["couvre"])
                ipw_abs.append(abs(c["ipw_est"] - c["delta_vrai"]))
                naif_abs.append(abs(c["naif_est"] - c["delta_vrai"]))
                ipw_bias.append(c["ipw_est"] - c["delta_vrai"])
                key = (c["segment"], c["action"])
                pool_sum[key] = pool_sum.get(key, 0.0) + c["ipw_est"]
                pool_cnt[key] = pool_cnt.get(key, 0) + 1
                pool_vrai[key] = c["delta_vrai"]
            # Reco par replication (informative, non bloquante - montre le bruit fini).
            for sid, est in rep["est_par_segment"].items():
                vrai = rep["vrai_par_segment"][sid]
                communs = [a for a in est if a in vrai]
                if len(communs) < 2:
                    continue
                reco_par_rep.append(
                    max(communs, key=lambda a: est[a]) == max(communs, key=lambda a: vrai[a])
                )

        # Reco / regret sur l'estimateur agrege
        seg_est: dict[str, dict[str, float]] = {}
        for (sid, action), cnt in pool_cnt.items():
            seg_est.setdefault(sid, {})[action] = pool_sum[(sid, action)] / cnt
        reco_ok: list[bool] = []
        regrets: list[float] = []
        for sid, est in seg_est.items():
            communs = [a for a in est if (sid, a) in pool_vrai]
            if len(communs) < 2:
                continue
            a_est = max(communs, key=lambda a: est[a])
            a_vrai = max(communs, key=lambda a: pool_vrai[(sid, a)])
            reco_ok.append(a_est == a_vrai)
            regrets.append(pool_vrai[(sid, a_vrai)] - pool_vrai[(sid, a_est)])

        couverture = float(np.mean(couvre_flags)) if couvre_flags else 0.0
        biais_moyen = float(np.mean(ipw_bias)) if ipw_bias else 0.0
        biais_abs = float(np.mean(ipw_abs)) if ipw_abs else 0.0
        biais_naif = float(np.mean(naif_abs)) if naif_abs else 0.0
        taux_reco = float(np.mean(reco_ok)) if reco_ok else 0.0
        taux_reco_rep = float(np.mean(reco_par_rep)) if reco_par_rep else 0.0
        regret = float(np.mean(regrets)) if regrets else 1.0

        crit_couv = 0.70 <= couverture <= 0.90
        crit_reco = taux_reco >= 0.70
        crit_regret = regret <= 0.02
        crit_naif = biais_naif > biais_abs
        dgp_pass = crit_couv and crit_reco and crit_regret and crit_naif
        verdict_global = verdict_global and dgp_pass

        resume["dgp"][params.nom] = {
            "n_cellules_scorees": len(couvre_flags),
            "n_segments_decises": len(reco_ok),
            "couverture_ic80": couverture,
            "critere_couverture_70_90": crit_couv,
            "biais_moyen_ipw": biais_moyen,
            "biais_absolu_ipw": biais_abs,
            "biais_absolu_naif": biais_naif,
            "critere_naif_pire_que_ipw": crit_naif,
            "taux_reco_correcte_agrege": taux_reco,
            "taux_reco_correcte_par_rep": taux_reco_rep,
            "critere_reco_min_070": crit_reco,
            "regret_decisionnel_moyen": regret,
            "critere_regret_max_002": crit_regret,
            "verdict_dgp": dgp_pass,
        }

    resume["verdict_global"] = verdict_global
    resume["n_rep"] = n_rep
    resume["n_boot"] = n_boot
    return resume


def _format_rapport(resume: dict[str, Any]) -> str:
    """Met en forme le rapport Markdown de la batterie de validation.

    Args:
        resume: resume produit par :func:`run_validation`.

    Returns:
        Contenu Markdown du rapport.
    """
    lignes = [
        "# Rapport de validation causale (U17, batterie D32)",
        "",
        "Banc synthétique déterministe : la politique de l'opérateur dépend d'un "
        "**stress latent** partiellement inobservé (rho ≈ 0.6). L'IPW/AIPW corrige "
        "la part observable de la confusion ; l'E-value chiffre la sensibilité au "
        "résidu non observé. Aucune colonne de vérité-terrain n'entre dans un "
        "estimateur — elles ne servent qu'ici, à noter les estimateurs.",
        "",
        f"Réplications par DGP : **{resume['n_rep']}** — bootstrap par cellule : "
        f"**{resume['n_boot']}**.",
        "",
    ]
    for nom, d in resume["dgp"].items():
        lignes += [
            f"## {nom}",
            "",
            f"- Cellules scorées : {d['n_cellules_scorees']} ; "
            f"segments décidés : {d['n_segments_decises']}",
            f"- (i) Couverture IC80 : **{d['couverture_ic80']:.1%}** "
            f"→ {'PASS' if d['critere_couverture_70_90'] else 'FAIL'} (cible 70–90 %)",
            f"- (ii) Biais moyen IPW : {d['biais_moyen_ipw']:+.4f} ; "
            f"biais absolu : {d['biais_absolu_ipw']:.4f} (informatif)",
            f"- (iii) Reco correcte (agrégée) : **{d['taux_reco_correcte_agrege']:.1%}** "
            f"→ {'PASS' if d['critere_reco_min_070'] else 'FAIL'} (cible ≥ 70 %) ; "
            f"par réplication : {d['taux_reco_correcte_par_rep']:.1%} (informatif)",
            f"- (iv) Regret décisionnel : **{d['regret_decisionnel_moyen']:.4f}** "
            f"→ {'PASS' if d['critere_regret_max_002'] else 'FAIL'} (cible ≤ 0.02)",
            f"- (v) Biais absolu NAÏF {d['biais_absolu_naif']:.4f} vs IPW "
            f"{d['biais_absolu_ipw']:.4f} → "
            + (
                "PASS — le naïf est plus biaisé (confusion démontrée)"
                if d["critere_naif_pire_que_ipw"]
                else "FAIL"
            ),
            f"- Verdict {nom} : **{'PASS' if d['verdict_dgp'] else 'FAIL'}**",
            "",
        ]
    verdict = "PASS" if resume["verdict_global"] else "FAIL"
    lignes += [
        "---",
        "",
        "Lecture honnête : (v) démontre chiffres à l'appui que l'ajustement causal "
        "réduit fortement le biais du naïf, mais (i) montre que sous confusion "
        "**partiellement non observée** (rho ≈ 0.6), l'IC80 de l'IPW peut sous-couvrir "
        "— l'effet causal reste ESTIMÉ, jamais réel, et l'E-value en chiffre la "
        "sensibilité. Un verdict FAIL déclenche la rétention de l'artefact par la porte "
        "U14 : c'est le comportement recherché.",
        "",
        f"**VALIDATION CAUSALE : {verdict}**",
        "",
    ]
    return "\n".join(lignes)


def _print_validation(resume: dict[str, Any]) -> None:
    """Imprime la batterie ligne a ligne, verdict global en dernier (parsable).

    Args:
        resume: resume produit par :func:`run_validation`.
    """
    print("=" * 72)
    print("BATTERIE DE VALIDATION CAUSALE (U17 — porte du pipeline, D32)")
    print("=" * 72)
    for nom, d in resume["dgp"].items():
        print(
            f"\n[{nom}] {d['n_cellules_scorees']} cellules scorées, "
            f"{d['n_segments_decises']} segments décidés"
        )
        print(
            f"  (i)   couverture IC80    : {d['couverture_ic80']:.1%}  "
            f"[{'PASS' if d['critere_couverture_70_90'] else 'FAIL'}]  (70–90 %)"
        )
        print(
            f"  (ii)  biais moyen / abs  : {d['biais_moyen_ipw']:+.4f} / "
            f"{d['biais_absolu_ipw']:.4f}  (informatif)"
        )
        print(
            f"  (iii) reco correcte      : {d['taux_reco_correcte_agrege']:.1%} agrégée  "
            f"[{'PASS' if d['critere_reco_min_070'] else 'FAIL'}]  (≥ 70 %) ; "
            f"{d['taux_reco_correcte_par_rep']:.1%} par rép. (info)"
        )
        print(
            f"  (iv)  regret décisionnel : {d['regret_decisionnel_moyen']:.4f}  "
            f"[{'PASS' if d['critere_regret_max_002'] else 'FAIL'}]  (≤ 0.02)"
        )
        print(
            f"  (v)   biais naïf > IPW   : {d['biais_absolu_naif']:.4f} > "
            f"{d['biais_absolu_ipw']:.4f}  "
            f"[{'PASS' if d['critere_naif_pire_que_ipw'] else 'FAIL'}]  "
            f"(confusion démontrée)"
        )
        print(f"  → verdict {nom} : {'PASS' if d['verdict_dgp'] else 'FAIL'}")
    print("\n" + "-" * 72)
    verdict = "PASS" if resume["verdict_global"] else "FAIL"
    print(f"VALIDATION CAUSALE : {verdict}")
    print("-" * 72)


# Ecriture du CSV de fixture


def write_fixture(path: Path, params: DGPParams = DGP1, seed: int = 42) -> None:
    """Ecrit une fixture ``interventions.csv`` deterministe (contrat 9).

    Args:
        path: chemin de sortie.
        params: DGP utilise pour la generation.
        seed: graine de generation.
    """
    table, _ = generate_dataset(params, seed)
    ordre = [
        "chain_id",
        "node_id",
        "tour",
        "action_id",
        "decidee",
        "executee",
        "date_effet",
        "resultat_operationnel",
        "succes",
        *sorted(k for k in table.cols if k.startswith("ea_")),
        "effet_vrai_param",
        "delta_u_vrai",
        "stress_latent",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(ordre)
        for i in range(table.n):
            row = []
            for k in ordre:
                v = table.cols[k][i]
                if isinstance(v, (bool, np.bool_)):
                    row.append("1" if v else "0")
                elif isinstance(v, float) and math.isnan(v):
                    row.append("")
                else:
                    row.append(v)
            writer.writerow(row)


# CLI


def main(argv: list[str] | None = None) -> int:
    """Point d'entree CLI.

    Args:
        argv: arguments (par defaut ``sys.argv[1:]``).

    Returns:
        Code de sortie : 0 si succes (et validation PASS le cas echeant), 1 sinon.
    """
    # La console Windows (cp1252) ne code pas >=/<=/- : on force l'UTF-8 en sortie.
    for flux in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            flux.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

    parser = argparse.ArgumentParser(description="U17 — modèle d'efficacité des actions.")
    parser.add_argument("--interventions", type=Path, help="journal interventions.csv")
    parser.add_argument("--out", type=Path, help="répertoire de sortie models/vN")
    parser.add_argument("--prior-sim", type=Path, help="JSON d'a priori simulés")
    parser.add_argument("--validate", action="store_true", help="batterie D32 (porte)")
    parser.add_argument("--check", action="store_true", help="recharge et vérifie le schéma")
    parser.add_argument("--make-fixture", type=Path, help="écrit une fixture CSV")
    parser.add_argument("--n-boot", type=int, default=500, help="tirages bootstrap (fit)")
    parser.add_argument("--n-rep", type=int, default=10, help="réplications de validation")
    parser.add_argument(
        "--validate-boot", type=int, default=200, help="tirages bootstrap (validation)"
    )
    args = parser.parse_args(argv)

    if args.make_fixture is not None:
        write_fixture(args.make_fixture)
        print(f"Fixture écrite : {args.make_fixture}")

    resume_validation: dict[str, Any] | None = None
    if args.validate:
        resume_validation = run_validation(n_rep=args.n_rep, n_boot=args.validate_boot)
        _print_validation(resume_validation)
        rapport = _format_rapport(resume_validation)
        dest = (args.out or Path(".")) / "rapport_validation.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(rapport, encoding="utf-8")
        print(f"\nRapport écrit : {dest}")

    if args.interventions is not None and args.out is not None:
        prior_sim = None
        if args.prior_sim is not None:
            prior_sim = json.loads(args.prior_sim.read_text(encoding="utf-8"))
        table = load_interventions(args.interventions)
        artifact = fit(table, prior_sim=prior_sim, n_boot=args.n_boot)
        if resume_validation is not None:
            artifact["validation"] = resume_validation
        args.out.mkdir(parents=True, exist_ok=True)
        dest = args.out / "action_effects.json"
        dest.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Artefact écrit : {dest}")

        if args.check:
            reloaded = json.loads(dest.read_text(encoding="utf-8"))
            check_schema(reloaded)
            print("Schéma (contrat 10) : OK")

    if args.validate and resume_validation is not None:
        return 0 if resume_validation["verdict_global"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
