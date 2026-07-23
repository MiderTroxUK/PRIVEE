"""Déclarants Ud — brique partagée entre les deux paliers (U7).

Ce module porte ce qui est COMMUN aux deux paliers de déclarants :

- le contrat gelé ``respond(node_id, tour, features, rng) -> {"bipolar":
  list[int] (6 dans [-8, 8]), "scores_ui": list[int] (4 dans [1, 6])}`` —
  implémenté ici par :class:`RidgeDeclarant` (palier 1) et par
  ``llm_farm.ClaudeCliDeclarant`` (palier 2, même signature) ;
- la reconstruction, en LECTURE SEULE depuis ``data/prepared/``, du dict
  ``features`` attendu par ce contrat (valeur courante, delta 1, delta 2 sur
  les 9 ``kpi_paths`` de ``make_briefings.FIELD_LABELS``, plus
  ``event_flag``/``press_flag``) ;
- la vectorisation de ``features`` en x(p, t) numérique, utilisée à la fois
  par l'ajustement (``analysis/behavior_model.py``) et par l'échantillonnage
  (:class:`RidgeDeclarant`) — UNE seule définition, pour que les deux
  restent structurellement synchronisés.

Volontairement scénario-agnostique : ce module n'importe ni ``scenario``
(HÉLIOS) ni ``supplyscore`` — seuls ``node_ids``/``n_tours`` sont passés par
l'appelant. Il vit dans ``projects/factory`` (et non ``simu_semiconducteurs``)
pour rester réutilisable par une future campagne.
"""

from __future__ import annotations

import csv
import json
import random
from collections.abc import Sequence
from pathlib import Path

import numpy as np

#: Ordre canonique des 9 chemins KPI montrés au consultant — DOIT rester
#: synchronisé avec ``make_briefings.FIELD_LABELS`` (vérifié par une
#: assertion au chargement de ``analysis/behavior_model.py``, seule source
#: de vérité pour le libellé français ; ici on ne retient que l'ordre).
KPI_PATHS: tuple[str, ...] = (
    "network.demand",
    "inventory.flow_rate",
    "time.lead_time_h",
    "cost.op_cost",
    "risk.cost_volatility",
    "risk.failure_probability",
    "oee.performance",
    "oee.availability",
    "inventory.current_volume_m3",
)

#: 3 features par KPI (val, d1, d2) + event_flag + press_flag.
N_FEATURES: int = 3 * len(KPI_PATHS) + 2

#: Les 10 dimensions de sortie du questionnaire AHP : 4 notes UI [1, 6] puis
#: 6 comparaisons bipolaires [-8, 8] (ordre des paires = PAIRS gelé, cf.
#: llm_farm.py et supplyscore.web_ui.pages.questionnaire.PAIRS).
SCORE_DIMS: tuple[str, ...] = tuple(f"scores_ui_{k}" for k in range(4))
BIPOLAR_DIMS: tuple[str, ...] = tuple(f"bipolar_{k}" for k in range(6))
DIMENSIONS: tuple[str, ...] = SCORE_DIMS + BIPOLAR_DIMS

#: Tours où la revue de presse (canal commun à tous les nœuds) porte un
#: signal notable dans le scénario HÉLIOS (cf. scenario.NARRATIVE) — gelé
#: dans le contrat U7, pas dérivé dynamiquement.
DEFAULT_PRESS_TOURS: frozenset[int] = frozenset({6, 7, 13})


# --- Reconstruction des features depuis data/prepared/ (lecture seule) -------------


def kpi_history(prepared_dir: Path, n_tours: int) -> dict[tuple[str, str], dict[int, float]]:
    """Historique creux ``{(node_id, kpi_path): {tour: valeur}}``.

    Lit UNIQUEMENT ``tour_NN.csv`` (mêmes fichiers que
    ``make_briefings._node_data_upto``) : un couple (nœud, KPI) absent d'un
    ``tour_NN.csv`` n'a pas changé ce tour-là (valeur portée depuis le
    dernier tour où il apparaît — cf. :func:`carried_value`), jamais une
    valeur absente par construction (anti-fuite structurelle : aucune
    lecture de l'état vivant du service).

    Args:
        prepared_dir: dossier ``data/prepared`` (lecture seule).
        n_tours: dernier tour de campagne (inclus).

    Returns:
        Dict creux indexé par (nœud, chemin KPI), valeurs par tour observé.
    """
    prepared_dir = Path(prepared_dir)
    hist: dict[tuple[str, str], dict[int, float]] = {}
    for t in range(n_tours + 1):
        path = prepared_dir / f"tour_{t:02d}.csv"
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = (row["node_id"], row["kpi_path"])
                hist.setdefault(key, {})[t] = float(row["valeur"])
    return hist


def carried_value(
    hist: dict[tuple[str, str], dict[int, float]],
    node_id: str,
    kpi_path: str,
    tour: int,
) -> float | None:
    """Dernière valeur connue de ``(node_id, kpi_path)`` au tour <= ``tour``.

    Args:
        hist: historique creux produit par :func:`kpi_history`.
        node_id: identifiant du nœud.
        kpi_path: chemin KPI (ex. ``"network.demand"``).
        tour: tour courant (la recherche ne regarde jamais au-delà).

    Returns:
        La valeur portée, ou ``None`` si ce KPI n'a jamais été observé pour
        ce nœud jusqu'à ce tour inclus — jamais une extrapolation.
    """
    series = hist.get((node_id, kpi_path))
    if not series:
        return None
    known = [t for t in series if t <= tour]
    if not known:
        return None
    return series[max(known)]


def _event_nodes_by_tour(prepared_dir: Path, n_tours: int) -> dict[int, set[str]]:
    """``{tour: {node_id ayant un événement ce tour-là}}`` depuis events_NN.json."""
    prepared_dir = Path(prepared_dir)
    out: dict[int, set[str]] = {}
    for t in range(n_tours + 1):
        path = prepared_dir / f"events_{t:02d}.json"
        nodes: set[str] = set()
        if path.exists():
            events = json.loads(path.read_text(encoding="utf-8"))
            nodes = {ev.get("node") for ev in events if ev.get("node")}
        out[t] = nodes
    return out


def reconstruct_features(
    prepared_dir: Path,
    node_ids: Sequence[str],
    n_tours: int,
    *,
    kpi_paths: Sequence[str] = KPI_PATHS,
    press_tours: frozenset[int] = DEFAULT_PRESS_TOURS,
) -> dict[tuple[str, int], dict]:
    """Reconstruit le dict ``features`` du contrat gelé pour chaque (nœud, tour).

    Pour chaque chemin KPI : ``val`` = dernière valeur connue (0.0 si ce KPI
    n'a jamais été observé pour ce nœud — un nœud sans ce KPI porte un
    vecteur neutre plutôt qu'une valeur manquante, cf. :func:`vectorize_features`),
    ``d1``/``d2`` = différences 1/2 par rapport aux tours précédents (``None``
    tant que l'historique est trop court, jamais une extrapolation).
    ``event_flag``/``press_flag`` sont lus depuis ``events_NN.json`` /
    ``press_tours``.

    Args:
        prepared_dir: dossier ``data/prepared`` (lecture seule).
        node_ids: nœuds à couvrir.
        n_tours: dernier tour de campagne (inclus) ; produit des entrées
            pour tours 0..n_tours.
        kpi_paths: ordre des 9 chemins KPI (défaut :data:`KPI_PATHS`).
        press_tours: tours à presse notable (défaut :data:`DEFAULT_PRESS_TOURS`).

    Returns:
        ``{(node_id, tour): features}`` où ``features`` suit exactement le
        contrat gelé U7.
    """
    prepared_dir = Path(prepared_dir)
    hist = kpi_history(prepared_dir, n_tours)
    events_by_tour = _event_nodes_by_tour(prepared_dir, n_tours)
    out: dict[tuple[str, int], dict] = {}
    for node_id in node_ids:
        for t in range(n_tours + 1):
            feat: dict = {}
            for path in kpi_paths:
                v0 = carried_value(hist, node_id, path, t)
                v1 = carried_value(hist, node_id, path, t - 1) if t >= 1 else None
                v2 = carried_value(hist, node_id, path, t - 2) if t >= 2 else None
                d1 = (v0 - v1) if (v0 is not None and v1 is not None) else None
                d2 = None
                if d1 is not None and v1 is not None and v2 is not None:
                    d2 = d1 - (v1 - v2)
                feat[path] = {"val": v0 if v0 is not None else 0.0, "d1": d1, "d2": d2}
            feat["event_flag"] = node_id in events_by_tour.get(t, set())
            feat["press_flag"] = t in press_tours
            out[(node_id, t)] = feat
    return out


def vectorize_features(features: dict, kpi_paths: Sequence[str] = KPI_PATHS) -> list[float]:
    """Vectorise ``features`` (contrat gelé) en x(p, t) numérique, ordre fixe.

    Pour chaque chemin KPI (ordre ``kpi_paths``) : ``val`` (0.0 si absent),
    ``d1``/``d2`` (0.0 si ``None``/absent) ; puis ``event_flag``,
    ``press_flag`` (0.0/1.0). Longueur toujours ``3*len(kpi_paths) + 2``
    (:data:`N_FEATURES` pour l'ordre par défaut), quel que soit le nœud.

    Args:
        features: dict du contrat gelé (cf. :func:`reconstruct_features`).
        kpi_paths: ordre des chemins KPI (défaut :data:`KPI_PATHS`).

    Returns:
        Vecteur x(p, t), longueur fixe.
    """
    x: list[float] = []
    for path in kpi_paths:
        entry = features.get(path) or {}
        x.append(float(entry.get("val", 0.0) or 0.0))
        d1 = entry.get("d1")
        x.append(float(d1) if d1 is not None else 0.0)
        d2 = entry.get("d2")
        x.append(float(d2) if d2 is not None else 0.0)
    x.append(1.0 if features.get("event_flag") else 0.0)
    x.append(1.0 if features.get("press_flag") else 0.0)
    return x


def clip_round_int(value: float, lo: int, hi: int) -> int:
    """Arrondit à l'entier le plus proche puis borne à ``[lo, hi]``."""
    return int(min(max(round(value), lo), hi))


# --- Palier 1 : échantillonneur ridge -----------------------------------------------


class RidgeDeclarant:
    """Palier 1 — déclarant échantillonné par le modèle ridge (behavior_model.py).

    Implémente le contrat gelé ``respond(node_id, tour, features, rng) ->
    {"bipolar": list[int], "scores_ui": list[int]}``. Charge
    ``behavior_params.json`` (poids w_d, phi_d, intercepts alpha par
    persona + un persona générique ``"__generic__"`` (alpha=0) pour un
    ``node_id`` inconnu du jeu d'entraînement, pools de résidus pour le
    tirage bootstrap).

    État interne : dernière déclaration produite par nœud (terme AR),
    remise à zéro (0.0) tant qu'aucune déclaration n'a encore été émise
    pour ce nœud — cf. :meth:`respond`.
    """

    def __init__(self, params_path: str | Path) -> None:
        """Charge les paramètres sérialisés par ``analysis/behavior_model.py``.

        Args:
            params_path: chemin vers ``behavior_params.json``.
        """
        data = json.loads(Path(params_path).read_text(encoding="utf-8"))
        self.kpi_paths: tuple[str, ...] = tuple(data["kpi_paths"])
        self.dimensions: tuple[str, ...] = tuple(data["dimensions"])
        self._weights: dict[str, np.ndarray] = {
            dim: np.asarray(w, dtype=float) for dim, w in data["weights"].items()
        }
        self._phi: dict[str, float] = dict(data["phi"])
        self._alpha: dict[str, dict[str, float]] = dict(data["alpha"])
        self._residuals: dict[str, list[float]] = dict(data["residuals"])
        self._state: dict[str, dict[str, float]] = {}

    def respond(
        self, node_id: str, tour: int, features: dict, rng: random.Random
    ) -> dict[str, list[int]]:
        """Contrat gelé : prédiction ridge + résidu bootstrap, bornée/arrondie.

        ``tour`` n'entre pas directement dans la prédiction : la dépendance
        temporelle passe par le terme AR (état interne par nœud), fidèle à
        y_d(p,t) = alpha + x(p,t)·w_d + phi_d·y_d(p,t-1) + eps.

        Args:
            node_id: identifiant du nœud (persona).
            tour: tour courant (non utilisé directement, cf. ci-dessus).
            features: dict du contrat gelé (cf. :func:`reconstruct_features`).
            rng: générateur utilisé pour le tirage bootstrap du résidu —
                déterministe si ``rng`` l'est.

        Returns:
            ``{"bipolar": [6 int dans [-8,8]], "scores_ui": [4 int dans [1,6]]}``.
        """
        del tour
        x = np.asarray(vectorize_features(features, self.kpi_paths), dtype=float)
        alpha_node = self._alpha.get(node_id) or self._alpha.get("__generic__", {})
        prev = self._state.get(node_id, {})
        scores_ui: list[int] = []
        bipolar: list[int] = []
        new_state: dict[str, float] = {}
        for dim in self.dimensions:
            pred = (
                alpha_node.get(dim, 0.0)
                + float(x @ self._weights[dim])
                + self._phi.get(dim, 0.0) * prev.get(dim, 0.0)
            )
            pool = self._residuals.get(dim) or [0.0]
            sample = pred + rng.choice(pool)
            lo, hi = (1, 6) if dim in SCORE_DIMS else (-8, 8)
            v = clip_round_int(sample, lo, hi)
            new_state[dim] = float(v)
            (scores_ui if dim in SCORE_DIMS else bipolar).append(v)
        self._state[node_id] = new_state
        return {"bipolar": bipolar, "scores_ui": scores_ui}
