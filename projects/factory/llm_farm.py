"""Ferme de sous-agents LLM (palier 2, U7) - declarants ``claude -p`` par persona.

:class:`ClaudeCliDeclarant` implemente le MEME contrat gele que
``declarants.RidgeDeclarant`` (palier 1) : ``respond(node_id, tour,
features, rng) -> {"bipolar": list[int], "scores_ui": list[int]}``. Chaque
appel construit un prompt AUTONOME - rien au-dela du dossier du persona
lui-meme (son identite structurelle, ses 9 indicateurs jusqu'au tour
courant, ses 6 dernieres declarations) - puis invoque ``claude -p`` en
sous-processus.

Anti-fuite (imperatif du plan U7) : ce module n'importe JAMAIS
``scenario.PERSONAS`` / ``NARRATIVE`` / ``SOURCES`` / ``TOUR_TO_MONTH`` /
``PLACEBO`` - ce contenu est explicitement INTERNE au facilitateur (cf.
l'en-tete de ``scenario.py``) et ne doit pas fuiter dans un prompt envoye a
un tiers. Seule l'identite STRUCTURELLE du noeud (id, nom, rang, label) est
lue depuis ``scenario.NODES`` pour nommer le role joue ; la " mission " est
un gabarit generique, independant du scenario HELIOS, pour que la ferme
reste reutilisable hors de cette campagne.

Validation d'une reponse : schema + plages, puis coherence AHP (CR < 0.10,
cf. ``supplyscore.core.ahp``). Une incoherence declenche UNE relance
nommant la paire la plus contradictoire (``max |log(A_ij) - log(w_i/w_j)|``)
en demandant de ne reviser QUE cette paire ; un echec de format declenche
une relance generique. Deuxieme echec (quelle qu'en soit la cause) -> repli
sur un ``RidgeDeclarant`` (palier 1) si fourni, sinon report de la derniere
declaration connue - compte dans ``fallback_count`` et journalise par trace.

Usage :
    python llm_farm.py --dry-run
    python llm_farm.py --dry-run --node compodis --tour 7
    python llm_farm.py --runs-dir DATA_PREPARED --out traces.jsonl --model haiku --max-calls 20
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

_FACTORY_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _FACTORY_DIR.parent.parent  # racine de CE worktree
_PROJECT_DIR = _REPO_ROOT / "projects" / "simu_semiconducteurs"
_SCRIPTS_DIR = _PROJECT_DIR / "scripts"
_SCENARIO_DIR = _PROJECT_DIR / "scenario"

for _p in (str(_REPO_ROOT), str(_FACTORY_DIR), str(_SCRIPTS_DIR), str(_SCENARIO_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import make_briefings  # noqa: E402  (FIELD_LABELS + _fmt_value : meme formatage que les fiches)
import scenario  # noqa: E402  (NODES uniquement : id/name/rank/label - JAMAIS PERSONAS/NARRATIVE)
from declarants import (  # noqa: E402
    KPI_PATHS,
    RidgeDeclarant,
    reconstruct_features,
)

from supplyscore.core import (  # noqa: E402
    CONSISTENCY_THRESHOLD,
    CRITERIA,
    bipolar_to_saaty,
    run_ahp,
)

#: Les 6 paires (i, j) comparees par le questionnaire AHP - duplique de ``supplyscore.web_ui.pages.questionnaire.PAIRS`` (on evite d'importer web_ui, qui tire Dash, depuis un script CLI batch). Ordre VERIFIE contre les traces pilotes (poids AHP recalcules a l'identique, cf. rapport U7).
PAIRS: list[tuple[int, int]] = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]

#: Nombre de declarations passees gardees dans le prompt (contrat U7).
HISTORY_LEN = 6

_RETRY_TECHNICAL_MSG = (
    "\n\n## Correction demandée\n\nVotre appel précédent a échoué techniquement "
    "(pas de réponse exploitable). Merci de renvoyer directement l'objet JSON "
    "demandé, sans texte autour."
)
_RETRY_FORMAT_MSG = (
    "\n\n## Correction demandée\n\nVotre réponse précédente n'était pas un JSON "
    'valide au format demandé. Merci de renvoyer UNIQUEMENT l\'objet JSON '
    '{"bipolar": [...], "scores_ui": [...], "note": "..."}, sans texte autour '
    "ni bloc de code."
)


# Identite structurelle (anti-fuite : jamais PERSONAS/NARRATIVE)


def _node_identity() -> dict[str, dict[str, Any]]:
    """``{node_id: {"name", "rank", "label"}}`` - structurel uniquement."""
    return {
        n["id"]: {"name": n["name"], "rank": n["rank"], "label": n["label"]} for n in scenario.NODES
    }


# Construction du prompt autonome


def _role_card(node_id: str, meta: dict[str, Any]) -> str:
    """Carte de role GENERIQUE (gabarit procedural, pas le texte PERSONAS)."""
    name = meta.get("name", node_id)
    label = meta.get("label", "")
    rank = meta.get("rank")
    rank_txt = f"rang {rank}" if rank is not None else "rang non précisé"
    return (
        f"Vous êtes le/la responsable supply chain de « {name} » ({label}, "
        f"{rank_txt}) au sein d'une chaîne d'approvisionnement industrielle "
        "multi-niveaux. Chaque mois, vous répondez à un questionnaire "
        "structuré sur VOTRE seule perception de l'urgence : il n'y a pas de "
        "bonne réponse, déclarez ce que vous percevez, pas ce que vous croyez "
        "attendu. Vous ne voyez que vos propres indicateurs et votre propre "
        "historique — jamais ceux des autres acteurs de la chaîne."
    )


def _recent_points(entry: dict) -> list[tuple[int, float]]:
    """Reconstruit jusqu'a 3 points recents (offsets 0, -1, -2) depuis val/d1/d2.

    Le contrat gele remplit ``val`` a 0.0 (jamais ``None``) quand un KPI n'a
    jamais ete observe pour ce noeud (cf. ``declarants.reconstruct_features``)
    - la distinction " jamais observe " vs " vaut vraiment 0.0 " est donc
    perdue dans ``features`` seul. On la retrouve par une heuristique
    documentee : val=0.0 ET d1=None ET d2=None ne peut survenir QUE via ce
    remplissage, sauf le cas rare (accepte) d'une toute premiere observation
    qui vaudrait PILE 0.0. Sans ce filtre, la fiche afficherait un faux
    " 0.0 " pour un indicateur qui ne s'applique tout simplement pas a ce
    noeud - trompeur pour le modele interroge.
    """
    val = entry.get("val")
    d1 = entry.get("d1")
    d2 = entry.get("d2")
    if val is None or (val == 0.0 and d1 is None and d2 is None):
        return []
    pts = [(0, val)]
    if d1 is not None:
        v1 = val - d1
        pts.append((-1, v1))
        if d2 is not None:
            v2 = v1 - (d1 - d2)
            pts.append((-2, v2))
    return pts


def _tour_sheet(tour: int, features: dict) -> str:
    """Table des indicateurs (T-2/T-1/T), libelles et formatage de make_briefings."""
    lines = ["| Indicateur | T-2 | T-1 | T (courant) |", "|---|---|---|---|"]
    any_row = False
    for path in KPI_PATHS:
        entry = features.get(path) or {}
        pts = _recent_points(entry)
        if not pts:
            continue  # KPI jamais observe pour ce noeud (cf. declarants.reconstruct_features)
        any_row = True
        by_offset = dict(pts)
        cells = [
            make_briefings._fmt_value(path, by_offset[off]) if off in by_offset else "—"
            for off in (-2, -1, 0)
        ]
        label = make_briefings.FIELD_LABELS.get(path, path)
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    body = "\n".join(lines) if any_row else "(aucun indicateur observé pour vous à ce stade)"
    extra = []
    if features.get("event_flag"):
        extra.append("Un événement notable a affecté vos opérations ce mois-ci.")
    if features.get("press_flag"):
        extra.append("La presse du secteur évoque des tensions ce mois-ci.")
    footer = ("\n\n" + " ".join(extra)) if extra else ""
    return f"## Vos indicateurs au tour {tour}\n\n{body}{footer}"


def _history_section(history: list[dict]) -> str:
    if not history:
        return "## Votre historique\n\n(première déclaration : aucun historique)"
    lines = ["## Vos dernières déclarations", ""]
    for h in history[-HISTORY_LEN:]:
        note = f" — « {h['note']} »" if h.get("note") else ""
        lines.append(
            f"- Tour {h['tour']} : comparaisons {h['bipolar']}, notes {h['scores_ui']}{note}"
        )
    return "\n".join(lines)


def _instructions_section() -> str:
    pair_lines = "\n".join(
        f"{k + 1}. « {CRITERIA[i]} » vs « {CRITERIA[j]} » : entier de -8 (le second "
        "domine largement) à +8 (le premier domine largement), 0 = importance égale."
        for k, (i, j) in enumerate(PAIRS)
    )
    score_lines = "\n".join(f"- {c} : note de 1 (faible) à 6 (critique)." for c in CRITERIA)
    return (
        "## Ce qu'on vous demande\n\n"
        "1) Comparez les 4 critères deux à deux (6 comparaisons) :\n"
        f"{pair_lines}\n\n"
        "2) Notez chacun des 4 critères isolément :\n"
        f"{score_lines}\n\n"
        "Critères, dans l'ordre : " + ", ".join(CRITERIA) + ".\n\n"
        "Répondez UNIQUEMENT avec un objet JSON, sans texte autour, de la forme :\n"
        '{"bipolar": [c1, c2, c3, c4, c5, c6], "scores_ui": [s1, s2, s3, s4], '
        '"note": "un court commentaire libre"}\n'
        "où c1..c6 sont vos 6 comparaisons (entiers dans [-8, 8], dans l'ordre "
        "ci-dessus) et s1..s4 vos 4 notes (entiers dans [1, 6])."
    )


def build_prompt(
    node_id: str, tour: int, features: dict, history: list[dict], node_meta: dict[str, dict]
) -> str:
    """Prompt AUTONOME pour une persona/tour - rien au-dela de son propre dossier."""
    meta = node_meta.get(node_id, {})
    return "\n\n".join(
        [
            _role_card(node_id, meta),
            _tour_sheet(tour, features),
            _history_section(history),
            _instructions_section(),
        ]
    )


# Appel CLI + extraction robuste du JSON


def _call_claude(prompt: str, model: str, claude_bin: str, timeout: float) -> str:
    """Appelle ``claude -p <prompt> --output-format json --model <model>``.

    ATTENTION (risque documente, observe en testant ce module) : si
    ``claude_bin`` resout vers un script ``.cmd``/``.bat`` sur Windows (cas
    frequent d'une CLI installee via ``npm install -g`` - ``claude.cmd``),
    Windows route l'appel via ``cmd.exe /c``, dont le parseur est oriente
    LIGNE : un saut de ligne dans un argument entre guillemets TRONQUE
    l'argument a la premiere ligne. ``prompt`` etant multi-paragraphe, un tel
    shim recevrait un prompt tronque SANS ERREUR visible. Une vraie ``.exe``
    (CreateProcess direct, jamais retokenisee par un shell) n'a pas ce
    probleme - c'est le chemin attendu pour le binaire ``claude`` reel, mais
    si ce risque se confirme en production, transmettre le prompt par
    fichier temporaire ou stdin plutot qu'en argument positionnel.

    Returns:
        Le texte brut de stdout (enveloppe JSON de la CLI).

    Raises:
        FileNotFoundError: binaire introuvable (declenche un repli immediat,
            sans nouvelle tentative - cf. :meth:`ClaudeCliDeclarant._try_respond`).
        RuntimeError: process en erreur ou delai depasse.
    """
    try:
        proc = subprocess.run(
            [claude_bin, "-p", prompt, "--output-format", "json", "--model", model],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"claude -p a dépassé le délai ({timeout}s)") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p a échoué (code {proc.returncode}) : {proc.stderr[:300]}")
    return proc.stdout


def _parse_envelope(stdout: str) -> str:
    """Extrait le champ ``result`` de l'enveloppe JSON de ``claude --output-format json``."""
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Sortie claude non-JSON : {stdout[:200]!r}") from exc
    if isinstance(envelope, dict) and "result" in envelope:
        return str(envelope["result"])
    raise ValueError(f"Enveloppe claude inattendue (pas de champ 'result') : {stdout[:200]!r}")


_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json_payload(raw_result_text: str) -> dict:
    """Extrait ``{"bipolar":..., "scores_ui":...}`` du texte du modele.

    Tolere : JSON direct, bloc de code ```(json)```, JSON entoure de texte.
    """
    text = raw_result_text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _FENCE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Réponse du modèle non parsable en JSON : {text[:200]!r}")


def _checked_int(value: Any, lo: int, hi: int, field: str) -> int:
    try:
        v = round(float(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"'{field}' contient une valeur non numérique : {value!r}") from exc
    if not lo <= v <= hi:
        raise ValueError(f"'{field}' hors de [{lo}, {hi}] : {value!r}")
    return v


def _validate_payload(payload: dict) -> tuple[list[int], list[int], str]:
    """Valide schema + plages ; leve ``ValueError`` (declenche une relance) sinon."""
    if not isinstance(payload, dict):
        raise ValueError("La réponse n'est pas un objet JSON.")
    bipolar_raw = payload.get("bipolar")
    scores_raw = payload.get("scores_ui")
    if not isinstance(bipolar_raw, list) or len(bipolar_raw) != 6:
        raise ValueError(f"'bipolar' doit être une liste de 6 entiers, reçu : {bipolar_raw!r}")
    if not isinstance(scores_raw, list) or len(scores_raw) != 4:
        raise ValueError(f"'scores_ui' doit être une liste de 4 entiers, reçu : {scores_raw!r}")
    bipolar = [_checked_int(v, -8, 8, "bipolar") for v in bipolar_raw]
    scores_ui = [_checked_int(v, 1, 6, "scores_ui") for v in scores_raw]
    note = str(payload.get("note", "")).strip()
    return bipolar, scores_ui, note


def _compute_cr(bipolar: list[int]) -> tuple[float, list[float]]:
    """CR + poids AHP depuis les 6 comparaisons bipolaires (ordre :data:`PAIRS`)."""
    comparisons = {pair: bipolar_to_saaty(v) for pair, v in zip(PAIRS, bipolar, strict=True)}
    result = run_ahp(comparisons, n=4)
    return result.consistency_ratio, list(result.weights)


def _most_contradictory_pair(bipolar: list[int], weights: list[float]) -> tuple[int, int]:
    """Paire (i, j) maximisant ``|log(A_ij) - log(w_i/w_j)|`` (cf. plan U7)."""
    best_pair = PAIRS[0]
    best_score = -1.0
    for pair, v in zip(PAIRS, bipolar, strict=True):
        i, j = pair
        score = abs(math.log(bipolar_to_saaty(v)) - math.log(weights[i] / weights[j]))
        if score > best_score:
            best_score = score
            best_pair = pair
    return best_pair


def _reask_message(pair: tuple[int, int]) -> str:
    i, j = pair
    return (
        "\n\n## Correction demandée\n\nVotre jeu de comparaisons n'est pas cohérent "
        f"(incohérence de Saaty). La comparaison la plus contradictoire est "
        f"« {CRITERIA[i]} » vs « {CRITERIA[j]} ». Révisez UNIQUEMENT cette "
        "comparaison (gardez les 5 autres et les 4 notes inchangées) et renvoyez "
        "l'objet JSON complet, toujours au même format."
    )


# Declarant palier 2


class ClaudeCliDeclarant:
    """Palier 2 - declarant ``claude -p`` par persona (contrat gele ``respond()``).

    Attributes:
        fallback_count: nombre de replis declenches (echec persistant).
        traces: une entree par appel a :meth:`respond` (journal complet,
            format proche des ``sandbox_<node>/results.jsonl`` pilotes).
    """

    def __init__(
        self,
        model: str = "haiku",
        claude_bin: str = "claude",
        fallback: RidgeDeclarant | None = None,
        timeout: float = 120.0,
        max_calls: int | None = None,
        node_meta: dict[str, dict] | None = None,
    ) -> None:
        """Construit le declarant palier 2.

        Args:
            model: modele passe a ``--model``.
            claude_bin: nom/chemin du binaire ``claude`` - pointer vers un
                binaire inexistant force le chemin de repli (tests).
            fallback: :class:`RidgeDeclarant` optionnel utilise en repli ;
                a defaut, la derniere declaration connue est reportee (ou
                une reponse neutre si le noeud n'a encore aucun historique).
            timeout: delai (s) par appel sous-processus.
            max_calls: plafond GLOBAL d'appels ``claude`` reels (thread-safe) ;
                ``None`` = illimite. Une fois epuise, ``respond`` va
                directement au repli sans tenter d'appel.
            node_meta: identite structurelle ``{node_id: {...}}`` ; par
                defaut :func:`_node_identity` (scenario.NODES, sans PERSONAS).
        """
        self.model = model
        self.claude_bin = claude_bin
        self.fallback = fallback
        self.timeout = timeout
        self.max_calls = max_calls
        self.node_meta = node_meta if node_meta is not None else _node_identity()
        self.fallback_count = 0
        self.traces: list[dict] = []
        self._history: dict[str, list[dict]] = {}
        self._calls_made = 0
        self._lock = threading.Lock()

    def respond(
        self, node_id: str, tour: int, features: dict, rng: random.Random
    ) -> dict[str, list[int]]:
        """Contrat gele - cf. docstring de module pour le detail du flux."""
        history = list(self._history.get(node_id, []))
        prompt = build_prompt(node_id, tour, features, history, self.node_meta)
        trace: dict[str, Any] = {
            "node_id": node_id,
            "tour": tour,
            "attempts": 0,
            "cr_echec": False,
        }
        result = self._try_respond(prompt, trace)
        if result is None:
            result = self._fall_back(node_id, tour, features, rng, trace)
        bipolar, scores_ui, note = result
        entry = {"tour": tour, "bipolar": bipolar, "scores_ui": scores_ui, "note": note}
        with self._lock:
            hist = self._history.setdefault(node_id, [])
            hist.append(entry)
            del hist[:-HISTORY_LEN]
            trace.update({"bipolar": bipolar, "scores_ui": scores_ui, "note": note})
            self.traces.append(trace)
        return {"bipolar": bipolar, "scores_ui": scores_ui}

    def _consume_call_budget(self) -> bool:
        if self.max_calls is None:
            return True
        with self._lock:
            if self._calls_made >= self.max_calls:
                return False
            self._calls_made += 1
            return True

    def _try_respond(self, prompt: str, trace: dict) -> tuple[list[int], list[int], str] | None:
        """Jusqu'a 2 tentatives ; renvoie ``None`` si aucune n'aboutit (-> repli)."""
        current_prompt = prompt
        reason = "budget épuisé"
        for attempt in (1, 2):
            if not self._consume_call_budget():
                trace["fallback_reason"] = "budget --max-calls épuisé"
                trace["cr_echec"] = False
                return None
            trace["attempts"] = attempt
            try:
                stdout = _call_claude(current_prompt, self.model, self.claude_bin, self.timeout)
            except FileNotFoundError as exc:
                trace["fallback_reason"] = f"binaire claude introuvable : {exc}"
                trace["cr_echec"] = False
                return None
            except RuntimeError as exc:
                reason = "technique"
                trace.setdefault("errors", []).append(str(exc))
                current_prompt = prompt + _RETRY_TECHNICAL_MSG
                continue
            try:
                text = _parse_envelope(stdout)
                payload = _extract_json_payload(text)
                bipolar, scores_ui, note = _validate_payload(payload)
            except ValueError as exc:
                reason = "format"
                trace.setdefault("errors", []).append(str(exc))
                current_prompt = prompt + _RETRY_FORMAT_MSG
                continue
            cr, weights = _compute_cr(bipolar)
            trace["cr"] = cr
            if cr < CONSISTENCY_THRESHOLD:
                return bipolar, scores_ui, note
            reason = "cr"
            trace.setdefault("errors", []).append(f"CR={cr:.3f} >= {CONSISTENCY_THRESHOLD}")
            if attempt == 1:
                pair = _most_contradictory_pair(bipolar, weights)
                current_prompt = prompt + _reask_message(pair)
        trace["fallback_reason"] = f"échec persistant après relance ({reason})"
        trace["cr_echec"] = reason == "cr"
        return None

    def _fall_back(
        self, node_id: str, tour: int, features: dict, rng: random.Random, trace: dict
    ) -> tuple[list[int], list[int], str]:
        with self._lock:
            self.fallback_count += 1
        trace["fallback"] = True
        if self.fallback is not None:
            out = self.fallback.respond(node_id, tour, features, rng)
            return out["bipolar"], out["scores_ui"], "(repli palier 1)"
        history = self._history.get(node_id)
        if history:
            last = history[-1]
            note = "(repli : report du dernier tour)"
            return list(last["bipolar"]), list(last["scores_ui"]), note
        return [0, 0, 0, 0, 0, 0], [3, 3, 3, 3], "(repli neutre : aucun historique)"


# Rapport de fidelite palier 2 vs palier 1


def _ud_from_declaration(rec: dict) -> float:
    """Ud (0..1) recalcule depuis bipolar+scores_ui, memes formules que le moteur."""
    comparisons = {pair: bipolar_to_saaty(v) for pair, v in zip(PAIRS, rec["bipolar"], strict=True)}
    result = run_ahp(comparisons, n=4)
    scores9 = np.array([1.0 + (s - 1.0) * 8.0 / 5.0 for s in rec["scores_ui"]])
    ud = (float(np.asarray(result.weights) @ scores9) - 1.0) / 8.0
    return float(np.clip(ud, 0.0, 1.0))


def _rank_bucket(rank: int) -> str:
    if rank <= 1:
        return "aval (rang 0-1)"
    if rank <= 3:
        return "milieu (rang 2-3)"
    return "amont (rang 4-5)"


def compare_tiers(
    t1_samples: list[dict], t2_traces: list[dict], node_ranks: dict[str, int] | None = None
) -> dict:
    """Rapport de fidelite palier 2 (LLM) vs palier 1 (ridge).

    Trois volets, imprimes ET retournes :
        - KS (Kolmogorov-Smirnov) sur les distributions de Ud, par palier de
          rang (aval/milieu/amont) - cible ``p > 0.05`` (pas de difference
          significative entre les deux paliers) ;
        - autocorrelation lag-1 des declarations (Ud), moyennee par noeud ;
        - taux d'echec CR persistant (palier 2 uniquement, ``cr_echec``).

    Args:
        t1_samples: sorties ``RidgeDeclarant.respond`` enrichies de
            ``{"node_id", "tour"}`` : ``[{"node_id","tour","bipolar","scores_ui"}, ...]``.
        t2_traces: traces :attr:`ClaudeCliDeclarant.traces` (meme forme +
            ``cr_echec`` optionnel).
        node_ranks: rang par noeud ; defaut = ``scenario.NODES``.

    Returns:
        ``{"ks": {bucket: {statistic, pvalue, pass}}, "autocorr":
        {"tier1", "tier2"}, "cr_echec_rate": float}``.
    """
    from scipy import stats

    ranks = node_ranks or {n["id"]: n["rank"] for n in scenario.NODES}

    def _grouped(records: list[dict]) -> dict[str, list[float]]:
        out: dict[str, list[float]] = {}
        for rec in records:
            bucket = _rank_bucket(ranks.get(rec["node_id"], 3))
            out.setdefault(bucket, []).append(_ud_from_declaration(rec))
        return out

    g1, g2 = _grouped(t1_samples), _grouped(t2_traces)
    ks_report: dict[str, dict] = {}
    print("\n=== compare_tiers : fidélité palier 2 (LLM) vs palier 1 (ridge) ===")
    for bucket in sorted(set(g1) | set(g2)):
        a, b = g1.get(bucket, []), g2.get(bucket, [])
        if len(a) < 2 or len(b) < 2:
            print(f"[{bucket}] échantillon trop petit (n1={len(a)}, n2={len(b)}) — ignoré")
            continue
        stat, pvalue = stats.ks_2samp(a, b)
        passed = bool(pvalue > 0.05)
        ks_report[bucket] = {"statistic": float(stat), "pvalue": float(pvalue), "pass": passed}
        verdict = "OK" if passed else "ÉCART"
        print(
            f"[{bucket}] KS={stat:.3f} p={pvalue:.3f} (cible p>0.05) -> {verdict} "
            f"(n1={len(a)}, n2={len(b)})"
        )

    def _lag1_autocorr(records: list[dict]) -> float | None:
        by_node: dict[str, list[tuple[int, float]]] = {}
        for rec in records:
            by_node.setdefault(rec["node_id"], []).append((rec["tour"], _ud_from_declaration(rec)))
        coeffs = []
        for series in by_node.values():
            series.sort(key=lambda p: p[0])
            values = np.asarray([v for _, v in series])
            if len(values) < 3 or np.std(values[:-1]) == 0 or np.std(values[1:]) == 0:
                continue
            coeffs.append(float(np.corrcoef(values[:-1], values[1:])[0, 1]))
        return float(np.mean(coeffs)) if coeffs else None

    ac1, ac2 = _lag1_autocorr(t1_samples), _lag1_autocorr(t2_traces)
    print(f"Autocorrélation lag-1 (moyenne par nœud) : palier1={ac1}, palier2={ac2}")

    cr_echecs = sum(1 for rec in t2_traces if rec.get("cr_echec"))
    cr_rate = cr_echecs / len(t2_traces) if t2_traces else 0.0
    print(
        f"Taux d'échec CR persistant (palier 2, repli déclenché) : "
        f"{cr_rate:.1%} ({cr_echecs}/{len(t2_traces)})"
    )

    return {"ks": ks_report, "autocorr": {"tier1": ac1, "tier2": ac2}, "cr_echec_rate": cr_rate}


# CLI


def _run_campaign(
    runs_dir: Path,
    out_path: Path,
    model: str,
    max_calls: int | None,
    claude_bin: str,
    node_ids: list[str],
    n_tours: int,
    fallback: RidgeDeclarant | None,
) -> ClaudeCliDeclarant:
    """Rejoue toute la campagne (tous noeuds x tous tours), 8 personas en parallele."""
    features_by_nt = reconstruct_features(runs_dir, node_ids, n_tours)
    declarant = ClaudeCliDeclarant(
        model=model, claude_bin=claude_bin, fallback=fallback, max_calls=max_calls
    )

    def _run_node(node_id: str) -> None:
        rng = random.Random(f"llm_farm-{node_id}")
        for t in range(n_tours + 1):
            declarant.respond(node_id, t, features_by_nt[(node_id, t)], rng)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(_run_node, node_ids))

    out_path.write_text(
        "\n".join(json.dumps(tr, ensure_ascii=False) for tr in declarant.traces), encoding="utf-8"
    )
    print(f"[llm_farm] {len(declarant.traces)} déclaration(s) écrite(s) -> {out_path}")
    print(f"[llm_farm] replis (fallback_count) : {declarant.fallback_count}")
    return declarant


def main(argv: list[str] | None = None) -> int:
    """CLI : ``--dry-run`` (affiche un prompt) ou rejoue une campagne complete."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, help="Dossier data/prepared (lecture seule)")
    parser.add_argument(
        "--out", type=Path, default=Path("traces.jsonl"), help="Fichier JSONL de sortie"
    )
    parser.add_argument("--model", default="haiku", help="Modèle claude (--model de la CLI)")
    parser.add_argument("--claude-bin", default="claude", help="Binaire claude (tests de repli)")
    parser.add_argument(
        "--max-calls", type=int, default=None, help="Plafond d'appels claude réels"
    )
    parser.add_argument(
        "--fallback-params", type=Path, default=None, help="behavior_params.json (repli palier 1)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Affiche un prompt complet sans appeler claude"
    )
    parser.add_argument(
        "--node", default=None, help="Nœud pour --dry-run (défaut : premier de scenario.NODES)"
    )
    parser.add_argument("--tour", type=int, default=1, help="Tour pour --dry-run (défaut : 1)")
    args = parser.parse_args(argv)

    node_ids = [n["id"] for n in scenario.NODES]
    n_tours = scenario.N_TOURS

    if args.dry_run:
        node_id = args.node or node_ids[0]
        prepared_dir = args.runs_dir or (_PROJECT_DIR / "data" / "prepared")
        features_by_nt = reconstruct_features(prepared_dir, node_ids, n_tours)
        features = features_by_nt.get((node_id, args.tour), {})
        print(build_prompt(node_id, args.tour, features, [], _node_identity()))
        return 0

    if not args.runs_dir:
        parser.error("--runs-dir requis hors --dry-run")
    fallback = RidgeDeclarant(args.fallback_params) if args.fallback_params else None
    _run_campaign(
        args.runs_dir,
        args.out,
        args.model,
        args.max_calls,
        args.claude_bin,
        node_ids,
        n_tours,
        fallback,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
