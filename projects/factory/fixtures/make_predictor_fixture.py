"""Genere une fixture synthetique ``dataset.csv`` (contrat 4) pour tester train_predictor.py (U10).

U10 n'a pas acces, dans son worktree isole, a la sortie reelle de ``build_dataset.py``
(U8, unite soeur) : ce script fabrique donc directement une fixture CSV conforme au
contrat 4 gele - memes 47 colonnes, meme ordre, memes conventions (cellule vide =
manquant, jamais 0 silencieux) - mais engendree par un DGP (" data generating process ")
logistique CONNU, pour que les metriques d'evaluation de train_predictor.py (Brier,
AUC, etc.) aient un sens verifiable : un modele correctement specifie doit recuperer
un AUC nettement > 0.5 sur ce jeu, un modele mal specifie ou un bug de pipeline doit
le faire chuter near 0.5.

Taille deliberement petite (" tiny fixture ") : 40 chaines x 8 noeuds x 15 tours
(t=0..14) = 4800 lignes, reparties en 5 regimes DGP (``dgp_params_id`` = dgp_0..dgp_4,
8 chaines chacun) qui partagent le MEME mecanisme causal (memes coefficients de pente)
mais un niveau de base different (intercept) - utile pour que l'axe d'evaluation
" leave-dgp-out " de train_predictor.py soit reellement informatif (generaliser la
FORME du risque a un regime de base inedit, pas seulement memoriser un taux).

DGP (connu, documente) - decalage causal IMPORTANT, voir commentaire dans
``_simulate_chain_nodes`` : p_true doit etre evalue sur l'etat COURANT (t) pour
engendrer l'evenement SUIVANT (t+1), jamais l'inverse, sinon aucun modele ne peut
apprendre le label depuis les features de sa propre ligne :
    p_true(t) = sigmoid(k0[regime] + k_ur-ur_local(t) + k_hidden-hidden_risk(t)
                         + k_d1-d1_ur_local(t))
    evenement_a(t+1) ~ Bernoulli(p_true(t))   - " evenement " = definition gelee
    (gravite critique|defaut) du plan v7, ici un simple indicateur booleen par
    (chaine, noeud, tour). Donc y1(t) = evenement_a(t+1) est exactement
    Bernoulli(p_true(t)) : le label de la ligne t est bien fonction des features
    DE la ligne t.

Les labels y1/y4, le posterieur Beta-Bernoulli (prior partage N0=26), les
differences arriere d1..d4, l'EMA (rho=0.3), event_recent/weeks_since_event et le
voisinage (arcs = chaine lineaire noeud i -> noeud i+1) repliquent EXACTEMENT la
semantique decrite dans feature_schema.json (U8) - voir chaque etape commentee
ci-dessous. ``p_rollout``/``spread`` (bloc MC) sont un forecast VOLONTAIREMENT
mal calibre (attenue + biaise + bruite) derive de p_true : cela donne a EMOS un
vrai travail de recalibration a faire, et permet de verifier que la regle de
decision (EMOS vs rollout brut) peut basculer dans les deux sens selon
``--rollout-atten``/``--rollout-noise-sd`` - les defauts (0.75 / 0.9) donnent un
rollout brut nettement moins bon qu'EMOS ; ``--rollout-atten 1.0
--rollout-noise-sd 0.05`` (rollout quasi parfait) fait basculer la regle de
decision vers la branche degeneree (isotonique seule sur p_rollout), utilise
pour la verification manuelle des deux branches de train_predictor.py.

Usage::

    python make_predictor_fixture.py --out projects/factory/fixtures/predictor_dataset.csv
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Any

import numpy as np

# Constantes de forme (alignees sur feature_schema.json / build_dataset.py)

N_REGIMES = 5
CHAINS_PER_REGIME = 8
N_NODES = 8
N_TOURS = 15  # t = 0..14
HORIZON = 4
N0_BETA = 26.0
RHO_EMA = 0.3
EPS = 1e-4

U_BLOC_KEYS = ("u_time", "u_cap", "u_perf", "u_risk", "u_cost", "u_co2")

# Mecanisme causal PARTAGE entre regimes (seul l'intercept k0 varie par regime) : seule la FORME du risque doit etre apprise pour generaliser a un regime inedit. Coefficients + persistance/bruit de l'AR(1) calibres empiriquement (voir revue manuelle) pour que le AUC " oracle " (probabilite vraie du DGP, jamais accessible a un modele reel) atteigne ~=0.83-0.87 avec des taux de base ~=16-29 % selon le regime - assez separable pour qu'un pipeline correct le recouvre nettement au-dessus du hasard, et qu'un bug de pipeline (fuite de colonne, feature decalee dans le temps, etc.) fasse visiblement chuter l'AUC realise.
K_UR = 6.0
K_HIDDEN = 4.0
K_D1 = 3.0
AR1_PERSISTENCE = 0.55
AR1_INNOVATION_SD = 0.9
K0_BY_REGIME = np.linspace(-4.6, -3.4, N_REGIMES)

COLUMNS = [
    "chain_id",
    "node_id",
    "dgp_params_id",
    "y1",
    f"y{HORIZON}",
    "ud",
    "ur",
    "ud_local",
    "ur_local",
    "hidden_risk",
    "false_urgency",
    "adequation",
    *U_BLOC_KEYS,
    *[f"d{k}_ur_local" for k in range(1, HORIZON + 1)],
    *[f"d{k}_H" for k in range(1, HORIZON + 1)],
    "ema_ur_local",
    "event_recent",
    "weeks_since_event",
    "beta_mean",
    "beta_var",
    "beta_n",
    "p_retard_jalon",
    "p_impact_final",
    "delta_ell_final",
    "delta_ell_max",
    "p_rollout",
    "spread",
    "depth_frac",
    "in_deg",
    "out_deg",
    "log_n_nodes",
    "impact_frac",
    "mean_ur_pred",
    "max_ur_pred",
    "frac_pred_satures",
    "mean_beta_in",
]


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _logit(p: float) -> float:
    p = min(max(p, EPS), 1.0 - EPS)
    return math.log(p / (1.0 - p))


def _simulate_chain_nodes(
    rng: np.random.Generator, k0: float, rollout_atten: float, rollout_noise_sd: float
) -> list[dict[str, Any]]:
    """Simule les N_NODES series temporelles brutes d'une chaine (sans voisinage).

    Retourne une liste de dicts (un par noeud), chacun contenant des tableaux numpy
    indexes par tour t=0..N_TOURS-1 : ur_local, hidden_risk, d1_ur_local (pour le
    DGP), event_at (0/1 realise), et toutes les colonnes deja calculables SANS
    connaitre les autres noeuds (le voisinage est rempli dans un second temps par
    l'appelant, une fois tous les noeuds de la chaine disponibles).
    """
    nodes: list[dict[str, Any]] = []
    for _n in range(N_NODES):
        # risque latent AR(1) en espace logit -> ur_local
        x = np.empty(N_TOURS)
        x[0] = _logit(0.30) + rng.normal(0.0, 0.6)
        for t in range(1, N_TOURS):
            x[t] = (
                AR1_PERSISTENCE * x[t - 1]
                + (1 - AR1_PERSISTENCE) * _logit(0.30)
                + rng.normal(0.0, AR1_INNOVATION_SD)
            )
        ur_local = np.clip(1.0 / (1.0 + np.exp(-x)), 0.02, 0.98)

        ud_local = np.clip(ur_local + rng.normal(0.0, 0.09, N_TOURS), 0.0, 1.0)
        hidden_risk = np.maximum(ur_local - ud_local, 0.0)
        false_urgency = np.maximum(ud_local - ur_local, 0.0)
        ur = np.clip(ur_local + rng.normal(0.0, 0.04, N_TOURS), 0.0, 1.0)
        ud = np.clip(ud_local + rng.normal(0.0, 0.04, N_TOURS), 0.0, 1.0)
        adequation = 100.0 * np.clip(1.0 - np.abs(ud - ur), 0.0, 1.0)

        d1_ur_local = np.full(N_TOURS, np.nan)
        d1_ur_local[1:] = ur_local[1:] - ur_local[:-1]

        # DGP connu : p_next_event(t) = P(evenement a t+1 | etat a t) IMPORTANT (decalage causal) : le label y1(t) = event_at(t+1) doit etre engendre a partir de l'etat COURANT (t), jamais de l'etat futur (t+1) - sinon aucun modele ne peut apprendre le label a partir des features de la ligne t (le seul historique disponible au moment de la prediction) et l'AUC recouvrable reste proche de 0.5 par construction. p_next_event(t) sert donc DEUX roles coherents : (a) tirer event_at(t+1), (b) servir de base a p_rollout(t) (le forecast MC a la ligne t VISE la meme cible que y1(t), c'est le principe meme d'un rollout).
        d1_for_dgp = np.where(np.isnan(d1_ur_local), 0.0, d1_ur_local)
        logit_p_next = k0 + K_UR * ur_local + K_HIDDEN * hidden_risk + K_D1 * d1_for_dgp
        p_next_event = 1.0 / (1.0 + np.exp(-logit_p_next))

        event_at = np.zeros(N_TOURS, dtype=int)
        event_at[0] = int(rng.uniform(0.0, 1.0) < p_next_event[0])  # amorcage, sans effet sur y1/y4
        for t in range(1, N_TOURS):
            event_at[t] = int(rng.uniform(0.0, 1.0) < p_next_event[t - 1])

        # bloc MC (p_rollout/spread) : forecast VOLONTAIREMENT mal calibre
        p_rollout = np.full(N_TOURS, np.nan)
        spread = np.full(N_TOURS, np.nan)
        for t in range(1, N_TOURS):
            noise = rng.normal(0.0, rollout_noise_sd)
            mis_logit = (
                rollout_atten * _logit(float(p_next_event[t]))
                + (1 - rollout_atten) * _logit(0.15)
                + noise
            )
            p_rollout[t] = min(max(_sigmoid(mis_logit), EPS), 1.0 - EPS)
            spread[t] = min(max(0.06 + 0.55 * abs(noise) + rng.uniform(0.0, 0.05), 0.01), 0.95)

        # blocs u_* (decomposition log-survie) : plausibles, ~8% manquants
        u_blocs = {}
        for key in U_BLOC_KEYS:
            base = rng.beta(2.0, 5.0, N_TOURS) * 0.6 + 0.25 * ur_local
            vals = np.clip(base + rng.normal(0.0, 0.05, N_TOURS), 0.0, 1.0)
            miss = rng.uniform(0.0, 1.0, N_TOURS) < 0.08
            vals = vals.astype(object)
            vals[miss] = None
            u_blocs[key] = vals

        # MC secondaire (impact/Deltal) : manquant au tour 0
        p_impact_final = np.clip(0.5 * p_next_event + rng.uniform(0.0, 0.1, N_TOURS), 0.0, 1.0)
        delta_ell_final = np.clip(rng.normal(0.3, 0.15, N_TOURS) * ur_local, 0.0, None)
        delta_ell_max = delta_ell_final + np.abs(rng.normal(0.0, 0.05, N_TOURS))
        impact_frac = np.clip(0.1 + 0.4 * ur_local + rng.normal(0.0, 0.05, N_TOURS), 0.0, 1.0)

        nodes.append(
            {
                "ur_local": ur_local,
                "ud_local": ud_local,
                "hidden_risk": hidden_risk,
                "false_urgency": false_urgency,
                "ur": ur,
                "ud": ud,
                "adequation": adequation,
                "d1_ur_local": d1_ur_local,
                "event_at": event_at,
                "p_rollout": p_rollout,
                "spread": spread,
                "u_blocs": u_blocs,
                "p_impact_final": p_impact_final,
                "delta_ell_final": delta_ell_final,
                "delta_ell_max": delta_ell_max,
                "impact_frac": impact_frac,
            }
        )
    return nodes


def _diff_k(arr: np.ndarray, t: int, k: int) -> float | None:
    if t - k < 0:
        return None
    return float(arr[t] - arr[t - k])


def build_fixture_rows(
    rollout_atten: float = 0.75, rollout_noise_sd: float = 0.9, seed: int = 20260724
) -> list[dict[str, Any]]:
    """Construit toutes les lignes de la fixture (dict pret pour csv.DictWriter).

    Args:
        rollout_atten: coefficient d'attenuation du rollout MC vers p_true (1.0 =
            rollout parfaitement informatif ; plus bas = plus miscalibre). Sert a
            piloter volontairement l'issue de la regle de decision EMOS-vs-rollout.
        rollout_noise_sd: ecart-type du bruit gaussien (espace logit) ajoute au
            rollout MC.
        seed: graine du generateur, fixe pour reproductibilite.
    """
    rng = np.random.default_rng(seed)

    # Passe 1 : simulation brute par chaine (sans voisinage, sans label/beta).
    chains: dict[str, list[dict[str, Any]]] = {}
    dgp_of_chain: dict[str, str] = {}
    for regime in range(N_REGIMES):
        for c in range(CHAINS_PER_REGIME):
            chain_id = f"chain_{regime}_{c:02d}"
            dgp_of_chain[chain_id] = f"dgp_{regime}"
            chains[chain_id] = _simulate_chain_nodes(
                rng, K0_BY_REGIME[regime], rollout_atten, rollout_noise_sd
            )

    # Taux de base global (toutes chaines/noeuds/tours confondus) -> prior Beta partage.
    total_obs = 0
    total_events = 0
    for nodes in chains.values():
        for node in nodes:
            total_obs += N_TOURS
            total_events += int(node["event_at"].sum())
    base_rate = total_events / total_obs if total_obs else 0.0
    alpha0 = base_rate * N0_BETA
    beta0 = (1.0 - base_rate) * N0_BETA

    # Passe 2 : labels censures, dynamique, posterieur bayesien, structurel - puis voisinage (necessite les series ur/beta_mean deja calculees des AUTRES noeuds de la meme chaine, d'ou une passe separee apres celle-ci).
    rows: list[dict[str, Any]] = []
    rows_by_chain_tour_node: dict[tuple[str, int, int], dict[str, Any]] = {}

    last_tour = N_TOURS - 1
    for chain_id, nodes in chains.items():
        dgp_id = dgp_of_chain[chain_id]
        for n_idx, node in enumerate(nodes):
            node_id = f"node_{n_idx}"
            event_at = node["event_at"]

            # Posterieur Beta-Bernoulli sequentiel (n_obs = t+1, jamais de trou).
            successes_cum = np.cumsum(event_at)

            for t in range(N_TOURS):
                n_obs = t + 1
                successes = int(successes_cum[t])
                a_post = alpha0 + successes
                b_post = beta0 + (n_obs - successes)
                beta_mean = a_post / (a_post + b_post)
                beta_var = (a_post * b_post) / (((a_post + b_post) ** 2) * (a_post + b_post + 1))

                # y1 : evenement a t+1, censure si t+1 depasse le dernier tour.
                if t + 1 <= last_tour:
                    y1: int | None = int(event_at[t + 1])
                else:
                    y1 = None

                # y{HORIZON} : fenetre (t, t+H] - trouve => 1 meme si fenetre partielle ; sinon 0 seulement si la fenetre est ENTIEREMENT observee ; censure autrement (jamais 0 silencieux).
                window = [u for u in range(t + 1, t + HORIZON + 1) if u <= last_tour]
                found = any(bool(event_at[u]) for u in window)
                if found:
                    yh: int | None = 1
                elif t + HORIZON <= last_tour:
                    yh = 0
                else:
                    yh = None

                # event_recent : fenetre arriere [t-2, t] inclusive.
                back_start = max(0, t - 2)
                event_recent = int(any(bool(event_at[u]) for u in range(back_start, t + 1)))

                # weeks_since_event : dernier u<=t avec evenement, sinon vide.
                past_events = [u for u in range(0, t + 1) if event_at[u]]
                weeks_since_event = (t - max(past_events)) if past_events else None

                # EMA(rho=0.3), jamais manquante (demarre a ur_local(0)).
                if t == 0:
                    ema = float(node["ur_local"][0])
                else:
                    prev_ema = rows_by_chain_tour_node[(chain_id, t - 1, n_idx)]["_ema"]
                    ema = (1 - RHO_EMA) * prev_ema + RHO_EMA * float(node["ur_local"][t])

                row: dict[str, Any] = {
                    "chain_id": chain_id,
                    "node_id": node_id,
                    "dgp_params_id": dgp_id,
                    "y1": y1,
                    f"y{HORIZON}": yh,
                    "ud": float(node["ud"][t]),
                    "ur": float(node["ur"][t]),
                    "ud_local": float(node["ud_local"][t]),
                    "ur_local": float(node["ur_local"][t]),
                    "hidden_risk": float(node["hidden_risk"][t]),
                    "false_urgency": float(node["false_urgency"][t]),
                    "adequation": float(node["adequation"][t]),
                    "d1_ur_local": _diff_k(node["ur_local"], t, 1),
                    "d2_ur_local": _diff_k(node["ur_local"], t, 2),
                    "d3_ur_local": _diff_k(node["ur_local"], t, 3),
                    "d4_ur_local": _diff_k(node["ur_local"], t, 4),
                    "d1_H": _diff_k(node["hidden_risk"], t, 1),
                    "d2_H": _diff_k(node["hidden_risk"], t, 2),
                    "d3_H": _diff_k(node["hidden_risk"], t, 3),
                    "d4_H": _diff_k(node["hidden_risk"], t, 4),
                    "ema_ur_local": ema,
                    "event_recent": event_recent,
                    "weeks_since_event": weeks_since_event,
                    "beta_mean": float(beta_mean),
                    "beta_var": float(beta_var),
                    "beta_n": n_obs,
                    "p_retard_jalon": None,  # reservee : toujours vide (schema v1)
                    "p_impact_final": None if t == 0 else float(node["p_impact_final"][t]),
                    "delta_ell_final": None if t == 0 else float(node["delta_ell_final"][t]),
                    "delta_ell_max": None if t == 0 else float(node["delta_ell_max"][t]),
                    "p_rollout": None if t == 0 else float(node["p_rollout"][t]),
                    "spread": None if t == 0 else float(node["spread"][t]),
                    "depth_frac": n_idx / (N_NODES - 1),
                    "in_deg": 0 if n_idx == 0 else 1,
                    "out_deg": 0 if n_idx == N_NODES - 1 else 1,
                    "log_n_nodes": math.log(N_NODES),
                    "impact_frac": None if t == 0 else float(node["impact_frac"][t]),
                    # voisinage rempli en passe 3
                    "mean_ur_pred": None,
                    "max_ur_pred": None,
                    "frac_pred_satures": None,
                    "mean_beta_in": None,
                    "_ema": ema,  # champ prive, retire avant ecriture
                }
                for key in U_BLOC_KEYS:
                    v = node["u_blocs"][key][t]
                    row[key] = None if v is None else float(v)

                rows_by_chain_tour_node[(chain_id, t, n_idx)] = row
                rows.append(row)

    # Passe 3 : voisinage - chaine lineaire noeud i -> noeud i+1 (predecesseur = i-1).
    for chain_id in chains:
        for t in range(N_TOURS):
            for n_idx in range(1, N_NODES):
                pred_row = rows_by_chain_tour_node[(chain_id, t, n_idx - 1)]
                row = rows_by_chain_tour_node[(chain_id, t, n_idx)]
                row["mean_ur_pred"] = pred_row["ur"]
                row["max_ur_pred"] = pred_row["ur"]
                row["frac_pred_satures"] = 1.0 if pred_row["ur"] >= 0.999 else 0.0
                row["mean_beta_in"] = pred_row["beta_mean"]

    for row in rows:
        del row["_ema"]
    return rows


def _to_csv_cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    return str(v)


def write_fixture_csv(rows: list[dict[str, Any]], out_path: Path) -> None:
    """Ecrit les lignes au format CSV du contrat 4 (cellule vide = manquant)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: _to_csv_cell(row.get(col)) for col in COLUMNS})


def main(argv: list[str] | None = None) -> int:
    """Point d'entree CLI de la generation de fixture."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="Chemin du CSV de sortie")
    parser.add_argument(
        "--rollout-atten",
        type=float,
        default=0.75,
        help="Atténuation du rollout MC vers p_true (défaut 0.75 : EMOS bat le rollout brut)",
    )
    parser.add_argument(
        "--rollout-noise-sd", type=float, default=0.9, help="Écart-type du bruit du rollout MC"
    )
    parser.add_argument("--seed", type=int, default=20260724, help="Graine du générateur")
    args = parser.parse_args(argv)

    rows = build_fixture_rows(
        rollout_atten=args.rollout_atten, rollout_noise_sd=args.rollout_noise_sd, seed=args.seed
    )
    out_path = Path(args.out)
    write_fixture_csv(rows, out_path)

    n_chains = len({r["chain_id"] for r in rows})
    n_y1 = sum(1 for r in rows if r["y1"] is not None)
    rate_y1 = (sum(1 for r in rows if r["y1"] == 1) / n_y1) if n_y1 else float("nan")
    print(
        f"Fixture écrite : {out_path} — {len(rows)} lignes, {n_chains} chaînes, "
        f"{N_REGIMES} régimes DGP.\n"
        f"  y1 : {n_y1} non censurés ({len(rows) - n_y1} censurés), taux de base {rate_y1:.1%}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
