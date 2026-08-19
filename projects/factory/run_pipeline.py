r"""Orchestrateur bout-en-bout HELIOS v7 (U14) : prevision + prescription contrefactuelle.

Enchaine, dans l'ordre, les etapes des unites soeurs U4-U13 et U15-U18 en
appelant leurs CLI FIGEES (chaque etape = un sous-processus
``.venv\\Scripts\\python.exe <script> <args>``). Ce module n'importe JAMAIS le
code d'une unite soeur : il ne connait que leurs contrats de ligne de commande,
figes dans le plan v7. Tout maillon absent produit un echec propre nommant
l'unite (ex. " maillon manquant : U6 - projects/factory/run_random_campaign.py ")
et un code de sortie non nul - jamais une trace Python brute.

Etapes (dans l'ordre) :
    opendata (U13, optionnelle) -> variants (U4) -> helios_runs (U5) ->
    random_chains (U6) -> llm_traces (U7, optionnelle) -> t1_refit (U7) ->
    amplified_runs (U5, si T1 RETENU) -> dataset (U8) ->
    interventions_extract (U8) -> action_effects (U17, PORTE CAUSALE) ->
    train (U10) -> smoke (U6 + U11 + U12).

Reprise sur panne : ``pipeline_state.json`` (dans ``--work``) consigne le
statut de chaque etape et, pour les etapes parallelisees (helios_runs,
random_chains, amplified_runs), la liste des items deja termines. Relancer la
commande relit cet etat et saute tout ce qui est deja fait - ``--reset``
l'efface pour repartir de zero.

Porte de validation causale (D32) : ``fit_action_effects.py --validate``
(U17) ecrit dans un dossier de STAGING, jamais directement dans
``<work>/models/``. Si le verdict global est PASS, le contenu du staging est
copie dans ``<work>/models/`` ; sinon il y reste (jamais publie) et un message
FR explique pourquoi - l'artefact predictif (U10) est, lui, toujours publie.

Voir ``PIPELINE.md`` (meme dossier) pour le schema de flux complet, les 32
decisions du plan, la table de couts mesures et les hypotheses d'integration
prises faute des scripts reels des unites soeurs (elles sont absentes de ce
worktree par construction - U14 est l'orchestrateur, pas un integrateur final).

Usage :
    .venv\\Scripts\\python.exe projects/factory/run_pipeline.py [--full|--xl]
        [--work DOSSIER] [--reset] [--llm-runs N] [--tier {0,1,2}]
        [--max-workers N] [--base-seed N]
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime as dt
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

#: Racine du depot, derivee de l'emplacement de ce fichier (``projects/factory/run_pipeline.py`` -> deux niveaux au-dessus).
_DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Version du schema de ``pipeline_state.json`` (bascule si le format change).
STATE_SCHEMA_VERSION = 1

#: Cout mesure par campagne (HELIOS ou chaine aleatoire), cf. tableau de couts de PIPELINE.md - sert uniquement a l'estimation affichee avant lancement, jamais a une decision du pipeline.
CAMPAIGN_COST_S = 30

#: Graine reservee du smoke test final (U6 --chains 1 --weeks 6), choisie loin de toute plage de graines utilisee par variants/helios_runs/ random_chains/amplified_runs, meme au profil --xl (2000 chaines) - la chaine de smoke doit etre authentiquement neuve, jamais vue a l'entrainement.
SMOKE_SEED = 9_000_000

#: Decalage de graine des runs amplifies (U5 + declarant RidgeDeclarant), choisi loin des graines 1..N des variantes et bien en-deca de SMOKE_SEED.
AMPLIFY_SEED_OFFSET = 500_000


# Erreurs


class PipelineError(RuntimeError):
    """Base commune : toute erreur qui doit interrompre proprement le pipeline."""


class MaillonManquantError(PipelineError):
    """Un script d'une unite soeur (contrat gele) est absent du depot."""


class EtapeEchoueeError(PipelineError):
    """Une etape a echoue (code de sortie non nul, sortie invalide, etc.)."""

    def __init__(self, stage: str, unit: str, detail: str) -> None:
        """Construit le message d'erreur standard d'une etape en echec.

        Args:
            stage: nom interne de l'etape (ex. ``"dataset"``).
            unit: unite soeur responsable du script appele (ex. ``"U8"``).
            detail: detail court (code de sortie, nombre d'items en echec...).
        """
        self.stage = stage
        self.unit = unit
        self.detail = detail
        super().__init__(f"étape « {stage} » ({unit}) en échec : {detail}")


# Profils


@dataclasses.dataclass(frozen=True)
class Profile:
    """Un profil de volumetrie du pipeline (nombre de campagnes, options)."""

    name: str
    n_variants: int
    n_chains: int
    tier: int
    rollout: bool
    llm_runs: int
    fast_training: bool


#: Profils predefinis. ``default`` est le profil de developpement rapide ; ``full`` et ``xl`` sont les profils de campagne reelle (cf. PIPELINE.md).
PROFILES: dict[str, Profile] = {
    "default": Profile(
        "default",
        n_variants=5,
        n_chains=5,
        tier=0,
        rollout=False,
        llm_runs=0,
        fast_training=True,
    ),
    "full": Profile(
        "full",
        n_variants=60,
        n_chains=150,
        tier=0,
        rollout=True,
        llm_runs=20,
        fast_training=False,
    ),
    "xl": Profile(
        "xl",
        n_variants=60,
        n_chains=2000,
        tier=0,
        rollout=True,
        llm_runs=20,
        fast_training=False,
    ),
}


# Configuration


@dataclasses.dataclass
class Config:
    """Configuration resolue d'une execution du pipeline (issue de argparse)."""

    repo_root: Path
    work_dir: Path
    profile: Profile
    python_exe: Path
    max_workers: int
    base_seed: int
    state_path: Path = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        """Derive les chemins qui decoulent de ``work_dir``."""
        self.state_path = self.work_dir / "pipeline_state.json"

    @property
    def runs_dir(self) -> Path:
        """Dossier commun des runs HELIOS + chaines aleatoires + amplifies."""
        return self.work_dir / "runs"

    @property
    def models_dir(self) -> Path:
        """Dossier final des modeles publies (artefact predictif + effets)."""
        return self.work_dir / "models"

    def script(self, *parts: str) -> Path:
        """Chemin absolu d'un script soeur, relatif a la racine du depot."""
        return self.repo_root.joinpath(*parts)


def build_parser() -> argparse.ArgumentParser:
    """Construit l'analyseur d'arguments de l'orchestrateur.

    Returns:
        L'analyseur configure (voir le docstring du module pour l'usage).
    """
    parser = argparse.ArgumentParser(
        prog="run_pipeline.py",
        description=(
            "Orchestrateur bout-en-bout HÉLIOS v7 (U14) : enchaîne les étapes "
            "prévision + prescription contrefactuelle des unités sœurs avec "
            "reprise sur panne et porte de validation causale."
        ),
    )
    parser.add_argument(
        "--work",
        default=None,
        help="Dossier de travail (défaut : projects/factory/factory_work/, gitignoré).",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Efface l'état précédent (pipeline_state.json) avant de démarrer.",
    )
    profil_grp = parser.add_mutually_exclusive_group()
    profil_grp.add_argument(
        "--full",
        action="store_true",
        help="Profil complet : 60 variantes, 150 chaînes, 20 traces LLM, rollouts.",
    )
    profil_grp.add_argument(
        "--xl",
        action="store_true",
        help="Profil XL : 2000 chaînes (~2 jours documentés, cf. PIPELINE.md).",
    )
    parser.add_argument(
        "--llm-runs",
        type=int,
        default=None,
        help="Nombre d'appels LLM (défaut du profil : 0, sauf --full/--xl = 20).",
    )
    parser.add_argument(
        "--tier",
        type=int,
        default=0,
        choices=(0, 1, 2),
        help="Palier des déclarants synthétiques U6 (défaut : 0).",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="Travailleurs parallèles (défaut : os.cpu_count() - 1).",
    )
    parser.add_argument(
        "--base-seed",
        type=int,
        default=1000,
        help="Graine de base des chaînes aléatoires U6 (défaut : 1000).",
    )
    # Option interne (non documentee dans PIPELINE.md) : permet aux tests de pointer l'orchestrateur vers une fausse racine de depot sans toucher au vrai. Aucun contrat gele ne porte sur les flags de run_pipeline.py lui-meme (seuls ceux des unites soeurs le sont).
    parser.add_argument("--repo-root", default=None, help=argparse.SUPPRESS)
    return parser


def build_config(args: argparse.Namespace) -> Config:
    """Resout la configuration a partir des arguments analyses.

    Args:
        args: espace de noms retourne par ``build_parser().parse_args(...)``.

    Returns:
        La configuration prete a l'emploi pour toutes les etapes.
    """
    repo_root = Path(args.repo_root).resolve() if args.repo_root else _DEFAULT_REPO_ROOT
    profile_name = "xl" if args.xl else "full" if args.full else "default"
    base = PROFILES[profile_name]
    llm_runs = args.llm_runs if args.llm_runs is not None else base.llm_runs
    profile = dataclasses.replace(base, tier=args.tier, llm_runs=llm_runs)
    work_dir = (
        Path(args.work).resolve() if args.work else repo_root / "projects/factory/factory_work"
    )
    # Comparaison explicite a None (pas un test de verite) : --max-workers 0 ou negatif doit etre borne a 1, jamais transmis tel quel a ProcessPoolExecutor (qui leve ValueError sur un nombre <= 0 - pas l'echec propre promis ici).
    if args.max_workers is not None:
        max_workers = max(1, args.max_workers)
    else:
        max_workers = max(1, (os.cpu_count() or 2) - 1)
    return Config(
        repo_root=repo_root,
        work_dir=work_dir,
        profile=profile,
        python_exe=Path(sys.executable),
        max_workers=max_workers,
        base_seed=args.base_seed,
    )


# Etat (reprise sur panne)


def _now() -> str:
    """Horodatage ISO 8601 UTC, a la seconde pres."""
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def new_state(profile_name: str) -> dict[str, Any]:
    """Cree un etat de pipeline neuf (aucune etape commencee).

    Args:
        profile_name: nom du profil actif, consigne pour information.

    Returns:
        Le dictionnaire d'etat initial (a sauvegarder via :func:`save_state`).
    """
    now = _now()
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "profile": profile_name,
        "created_at": now,
        "updated_at": now,
        "stages": {},
    }


def load_state(path: Path) -> dict[str, Any]:
    """Charge l'etat persiste, ou repart d'un etat neuf s'il est illisible.

    Args:
        path: chemin de ``pipeline_state.json``.

    Returns:
        Le dictionnaire d'etat (jamais ``None`` - un etat neuf en repli).
    """
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"état illisible ({path}) : {exc} — repart d'un état neuf.", file=sys.stderr)
        return new_state("inconnu")
    data.setdefault("stages", {})
    return data


def save_state(path: Path, state: dict[str, Any]) -> None:
    """Sauvegarde atomique de l'etat (fichier temporaire puis remplacement).

    L'ecriture atomique evite un ``pipeline_state.json`` tronque si le
    processus est interrompu pendant l'ecriture - important pour la reprise
    sur panne, qui est la raison d'etre de ce fichier.

    Args:
        path: chemin de destination.
        state: dictionnaire d'etat a serialiser.
    """
    state["updated_at"] = _now()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    payload = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True)
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def _fail_msg(script_name: str, result: subprocess.CompletedProcess[str]) -> str:
    """Message FR standard d'echec d'un sous-processus soeur (code non nul).

    Args:
        script_name: nom du script appele (ex. ``"variants.py"``).
        result: resultat du sous-processus (on lit ``returncode``).

    Returns:
        Un message court, uniforme sur toutes les etapes.
    """
    return f"{script_name} a échoué (code {result.returncode})"


# Utilitaires sous-processus


def _require(cfg: Config, script: Path, unit: str) -> None:
    """Verifie qu'un script soeur existe, sinon leve :class:`MaillonManquantError`.

    Args:
        cfg: configuration courante (pour exprimer le chemin relativement a
            la racine du depot dans le message).
        script: chemin absolu du script attendu.
        unit: nom de l'unite responsable (ex. ``"U6"``), cite dans le message.

    Raises:
        MaillonManquantError: si ``script`` n'existe pas.
    """
    if script.exists():
        return
    try:
        rel = script.relative_to(cfg.repo_root).as_posix()
    except ValueError:
        rel = script.as_posix()
    raise MaillonManquantError(f"maillon manquant : {unit} — {rel}")


def _print_tail(text: str, n: int = 15, label: str = "") -> None:
    """Imprime les ``n`` dernieres lignes de ``text``, prefixees pour lisibilite.

    Args:
        text: sortie brute (stdout ou stderr) d'un sous-processus.
        n: nombre de lignes finales a afficher.
        label: prefixe optionnel (ex. ``"stderr"``).
    """
    lines = text.rstrip().splitlines()
    prefix = f"  [{label}] " if label else "  | "
    for line in lines[-n:]:
        print(f"{prefix}{line}")


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Execute une commande soeur, sortie capturee, et l'affiche brievement.

    Args:
        cmd: liste argv de la commande a executer.

    Returns:
        Le resultat complet (code, stdout, stderr) - jamais leve en cas de
        code non nul : c'est a l'appelant de decider (certaines etapes
        tolerent un echec, d'autres non).
    """
    print("  $ " + " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        _print_tail(result.stdout)
    if result.returncode != 0 and result.stderr:
        _print_tail(result.stderr, label="stderr")
    return result


def _subprocess_worker(cmd: list[str]) -> tuple[int, str, str]:
    """Fonction de NIVEAU MODULE (picklable) executee dans chaque processus du pool.

    ``ProcessPoolExecutor`` sous Windows utilise ``spawn`` : la fonction
    soumise doit etre importable par son chemin de module, donc definie ici
    au niveau module (jamais une fermeture locale).

    Args:
        cmd: liste argv de la commande a executer.

    Returns:
        Tuple ``(code_retour, stdout, stderr)``.
    """
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def _run_parallel_items(
    cfg: Config,
    state: dict[str, Any],
    stage_name: str,
    items: list[tuple[str, list[str]]],
    unit: str,
) -> None:
    """Execute les items manquants d'une etape en parallele, reprise par item.

    ``items`` est la liste COMPLETE ``(cle, commande)`` de l'etape. Les cles
    deja presentes dans ``done_items`` de l'etat sont sautees. L'etat est
    reecrit apres CHAQUE item termine avec succes - granularite de reprise
    fine, coeur du lot " reprise sur panne " de U14 : si le processus est tue
    au milieu de 150 chaines, relancer ne referra QUE celles qui manquent.

    Un item en echec (code non nul ou exception du travailleur) n'interrompt
    PAS les autres items deja soumis, pour preserver le progres ; l'etape est
    declaree en echec (:class:`EtapeEchoueeError`) seulement apres que le lot
    complet ait fini.

    Args:
        cfg: configuration courante.
        state: etat global du pipeline (mute en place).
        stage_name: nom de l'etape (cle dans ``state["stages"]``).
        items: liste ``(cle, commande)`` - la cle identifie l'item pour la
            reprise (ex. le numero de graine).
        unit: unite soeur responsable, citee en cas d'echec.

    Raises:
        EtapeEchoueeError: si au moins un item a echoue.
    """
    st = state["stages"].setdefault(stage_name, {})
    done = set(st.get("done_items", []))
    total = len(items)
    todo = [(k, cmd) for k, cmd in items if k not in done]
    st["total"] = total
    if not todo:
        st["status"] = "ok"
        st.setdefault("finished_at", _now())
        save_state(cfg.state_path, state)
        print(f"[{stage_name}] {total}/{total} déjà fait(s) — passage.")
        return

    workers = min(cfg.max_workers, len(todo))
    print(f"[{stage_name}] {len(todo)}/{total} restant(s) à exécuter ({workers} travailleur(s)).")
    failures: list[str] = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_subprocess_worker, cmd): key for key, cmd in todo}
        for future in concurrent.futures.as_completed(futures):
            key = futures[future]
            try:
                code, _out, err = future.result()
            except Exception as exc:  # processus tue, erreur de pickling, etc.
                failures.append(key)
                print(f"[{stage_name}] item {key} : exception du travailleur — {exc!r}")
                continue
            if code != 0:
                failures.append(key)
                print(f"[{stage_name}] item {key} : code {code} — {err.strip()[-300:]}")
                continue
            done.add(key)
            st["done_items"] = sorted(done)
            save_state(cfg.state_path, state)

    if failures:
        st["status"] = "echec"
        st["detail"] = f"{len(failures)}/{len(todo)} item(s) en échec : {sorted(failures)}"
        save_state(cfg.state_path, state)
        raise EtapeEchoueeError(stage_name, unit, st["detail"])

    st["status"] = "ok"
    st["finished_at"] = _now()
    save_state(cfg.state_path, state)
    print(f"[{stage_name}] {total}/{total} terminé(s).")


def _variant_dirs(cfg: Config) -> list[Path]:
    """Liste les dossiers de variantes produits par l'etape ``variants``.

    Hypothese d'integration (cf. PIPELINE.md) : chaque sous-dossier immediat
    de ``<work>/prepared_variants/`` est une variante ; elles sont triees par
    nom et appariees aux graines 1..N dans cet ordre par les etapes en aval.

    Args:
        cfg: configuration courante.

    Returns:
        La liste triee des dossiers de variantes (vide si le dossier racine
        n'existe pas encore).
    """
    root = cfg.work_dir / "prepared_variants"
    if not root.exists():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir())


def _parse_t1_verdict(output: str) -> str | None:
    """Cherche le verdict RETENU/NON RETENU imprime par ``behavior_model.py`` (U7).

    Args:
        output: stdout + stderr concatenes du sous-processus.

    Returns:
        ``"RETENU"``, ``"NON RETENU"``, ou ``None`` si aucune ligne ne le dit.
    """
    lines = output.splitlines()
    for line in lines:
        if "NON RETENU" in line:
            return "NON RETENU"
    for line in lines:
        if "RETENU" in line:
            return "RETENU"
    return None


def _parse_global_verdict(output: str) -> str | None:
    """Cherche le verdict global PASS/FAIL de ``fit_action_effects.py --validate`` (U17).

    U17 imprime un verdict PAR CRITERE de la batterie D32 puis un verdict
    GLOBAL. Heuristique documentee (PIPELINE.md) : on cherche d'abord une
    ligne mentionnant " global " (insensible a la casse) portant PASS/FAIL ;
    a defaut, on retient la DERNIERE occurrence de PASS/FAIL, en supposant
    que la ligne de synthese conclut la sortie.

    Args:
        output: stdout + stderr concatenes du sous-processus.

    Returns:
        ``"PASS"``, ``"FAIL"``, ou ``None`` si indetectable.
    """
    lines = output.splitlines()
    for line in lines:
        if "global" in line.lower():
            match = re.search(r"\b(PASS|FAIL)\b", line)
            if match:
                return match.group(1)
    for line in reversed(lines):
        match = re.search(r"\b(PASS|FAIL)\b", line)
        if match:
            return match.group(1)
    return None


def _discover_db_project(smoke_dir: Path) -> tuple[Path, str] | None:
    """Decouvre ``(db_dir, project_id)`` de la chaine fraiche produite par U6.

    Heuristique documentee (PIPELINE.md), faute du script reel de U6 dans ce
    worktree :

    1. cherche un fichier ``*.json`` sous ``smoke_dir`` contenant une cle de
       dossier (``db_dir``|``db_path``|``database``) ET une cle de projet
       (``project_id``|``project``) ;
    2. a defaut, cherche un fichier ``.sqlite`` UNIQUE et y lit
       ``SELECT id FROM projects ORDER BY rowid DESC LIMIT 1`` (schema
       registre SupplyScore standard).

    Args:
        smoke_dir: dossier de sortie du run de smoke (U6).

    Returns:
        ``(db_dir, project_id)`` si trouve, sinon ``None``.
    """
    for manifest in sorted(smoke_dir.rglob("*.json")):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        db_key = next((k for k in ("db_dir", "db_path", "database") if k in data), None)
        proj_key = next((k for k in ("project_id", "project") if k in data), None)
        if db_key is None or proj_key is None:
            continue
        candidate = Path(str(data[db_key]))
        db_dir = candidate if candidate.is_absolute() else (manifest.parent / candidate).resolve()
        return db_dir, str(data[proj_key])

    sqlite_files = sorted(smoke_dir.rglob("*.sqlite"))
    if len(sqlite_files) == 1:
        db_file = sqlite_files[0]
        try:
            conn = sqlite3.connect(str(db_file))
            try:
                row = conn.execute("SELECT id FROM projects ORDER BY rowid DESC LIMIT 1").fetchone()
            finally:
                conn.close()
            if row:
                return db_file.parent, str(row[0])
        except sqlite3.Error:
            pass
    return None


def _format_duration(seconds: float) -> str:
    """Formate une duree en secondes vers une chaine FR lisible (s/min/h/j).

    Args:
        seconds: duree en secondes.

    Returns:
        Chaine du type ``"3 h 12 min"``.
    """
    total = round(seconds)
    if total < 60:
        return f"{total} s"
    minutes, s = divmod(total, 60)
    if minutes < 60:
        return f"{minutes} min {s:02d} s"
    hours, m = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} h {m:02d} min"
    days, h = divmod(hours, 24)
    return f"{days} j {h:02d} h"


def _print_estimate(cfg: Config) -> None:
    """Affiche l'estimation de temps AVANT lancement (cf. tableau de couts).

    Args:
        cfg: configuration courante.
    """
    p = cfg.profile
    n_campaigns = p.n_variants + p.n_chains
    sequential_s = n_campaigns * CAMPAIGN_COST_S
    parallel_s = sequential_s / cfg.max_workers
    print("=== Estimation avant lancement ===")
    print(
        f"Profil {p.name} : {p.n_variants} variante(s) HÉLIOS + {p.n_chains} chaîne(s) "
        f"aléatoire(s) (tier {p.tier}) = {n_campaigns} campagne(s), rollout={p.rollout}, "
        f"LLM={p.llm_runs}, entraînement rapide={p.fast_training}."
    )
    print(f"Travailleurs parallèles : {cfg.max_workers} (os.cpu_count() - 1, sauf --max-workers).")
    print(
        f"Temps estimé (helios_runs + random_chains, hors surcoût rollout) : "
        f"{_format_duration(sequential_s)} séquentiel -> ~ {_format_duration(parallel_s)} "
        f"à {cfg.max_workers} travailleurs (~{CAMPAIGN_COST_S} s/campagne, mesure du plan)."
    )
    if p.rollout:
        print("Rollouts activés : +0.5 à 1 jour de surcoût documenté (non recalculé ici).")
    print("Estimations indicatives ; les durées mesurées sont imprimées après chaque étape.\n")


# Etapes


def stage_opendata(cfg: Config, state: dict[str, Any]) -> None:
    """Etape ``opendata`` (U13, OPTIONNELLE) : ``fetch_opendata.py --all``.

    Sautee avec un avis FR (pas un echec) si
    ``projects/factory/opendata/MANIFEST.md`` est absent - c'est la seule
    etape du pipeline qui tolere nativement l'absence de son unite.

    Args:
        cfg: configuration courante.
        state: etat global du pipeline (mute en place).
    """
    name = "opendata"
    st = state["stages"].setdefault(name, {})
    manifest = cfg.script("projects/factory/opendata/MANIFEST.md")
    if not manifest.exists():
        st.update(status="sautee", detail="U13 — MANIFEST.md absent : étape optionnelle sautée.")
        print(f"[{name}] U13 absent (MANIFEST.md introuvable) — étape optionnelle sautée.")
        save_state(cfg.state_path, state)
        return
    if st.get("status") == "ok":
        print(f"[{name}] déjà fait — passage.")
        return
    script = cfg.script("projects/factory/opendata/fetch_opendata.py")
    _require(cfg, script, "U13")
    t0 = time.monotonic()
    result = _run([str(cfg.python_exe), str(script), "--all"])
    if result.returncode != 0:
        st.update(status="echec", detail=_fail_msg("fetch_opendata.py --all", result))
        save_state(cfg.state_path, state)
        raise EtapeEchoueeError(name, "U13", f"code {result.returncode}")
    st.update(status="ok", duration_s=time.monotonic() - t0, finished_at=_now())
    save_state(cfg.state_path, state)


def stage_variants(cfg: Config, state: dict[str, Any]) -> None:
    """Etape ``variants`` (U4) : ``variants.py --seeds 1..N --out <work>/prepared_variants/``.

    Args:
        cfg: configuration courante.
        state: etat global du pipeline (mute en place).
    """
    name = "variants"
    st = state["stages"].setdefault(name, {})
    if st.get("status") == "ok":
        print(f"[{name}] déjà fait — passage.")
        return
    script = cfg.script("projects/simu_semiconducteurs/scenario/variants.py")
    _require(cfg, script, "U4")
    out = cfg.work_dir / "prepared_variants"
    out.mkdir(parents=True, exist_ok=True)
    n = cfg.profile.n_variants
    cmd = [str(cfg.python_exe), str(script), "--seeds", f"1..{n}", "--out", str(out)]
    t0 = time.monotonic()
    result = _run(cmd)
    if result.returncode != 0:
        st.update(status="echec", detail=_fail_msg("variants.py", result))
        save_state(cfg.state_path, state)
        raise EtapeEchoueeError(name, "U4", f"code {result.returncode}")
    found = _variant_dirs(cfg)
    st.update(
        status="ok",
        n_expected=n,
        n_found=len(found),
        duration_s=time.monotonic() - t0,
        finished_at=_now(),
    )
    if len(found) != n:
        print(
            f"[{name}] avertissement : {n} variante(s) demandée(s), "
            f"{len(found)} dossier(s) trouvé(s) sous {out}."
        )
    save_state(cfg.state_path, state)


def stage_helios_runs(cfg: Config, state: dict[str, Any]) -> None:
    """Etape ``helios_runs`` (U5) : une campagne HELIOS par variante, en parallele.

    Args:
        cfg: configuration courante.
        state: etat global du pipeline (mute en place).
    """
    name = "helios_runs"
    st = state["stages"].setdefault(name, {})
    if st.get("status") == "ok":
        print(f"[{name}] déjà fait — passage.")
        return
    script = cfg.script("projects/simu_semiconducteurs/scripts/run_campaign.py")
    _require(cfg, script, "U5")
    variants = _variant_dirs(cfg)
    if not variants:
        st.update(status="echec", detail="aucune variante trouvée sous prepared_variants/")
        save_state(cfg.state_path, state)
        raise EtapeEchoueeError(
            name, "U4/U5", "prepared_variants/ vide (l'étape variants a-t-elle réussi ?)"
        )

    def build_cmd(seed: int, variant_dir: Path) -> list[str]:
        cmd = [
            str(cfg.python_exe),
            str(script),
            "--prepared",
            str(variant_dir),
            "--out",
            str(cfg.runs_dir),
            "--seed",
            str(seed),
        ]
        if cfg.profile.rollout:
            cmd.append("--rollout")
        return cmd

    items = [(str(i), build_cmd(i, variants[i - 1])) for i in range(1, len(variants) + 1)]
    _run_parallel_items(cfg, state, name, items, unit="U5")


def stage_random_chains(cfg: Config, state: dict[str, Any]) -> None:
    """Etape ``random_chains`` (U6) : N chaines aleatoires independantes, en parallele.

    Chaque chaine est un appel separe avec ``--chains 1`` (plutot qu'un seul
    appel ``--chains N``) pour obtenir un vrai parallelisme au niveau
    processus - chaque sous-processus produit son propre db-dir temporaire
    par conception des runners (cf. contrat U6).

    Args:
        cfg: configuration courante.
        state: etat global du pipeline (mute en place).
    """
    name = "random_chains"
    st = state["stages"].setdefault(name, {})
    if st.get("status") == "ok":
        print(f"[{name}] déjà fait — passage.")
        return
    script = cfg.script("projects/factory/run_random_campaign.py")
    _require(cfg, script, "U6")

    def build_cmd(seed: int) -> list[str]:
        cmd = [
            str(cfg.python_exe),
            str(script),
            "--chains",
            "1",
            "--weeks",
            "18",
            "--seed",
            str(seed),
            "--out",
            str(cfg.runs_dir),
            "--tier",
            str(cfg.profile.tier),
        ]
        if cfg.profile.rollout:
            cmd.append("--rollout")
        return cmd

    items = [(str(i), build_cmd(cfg.base_seed + i)) for i in range(cfg.profile.n_chains)]
    _run_parallel_items(cfg, state, name, items, unit="U6")


def stage_llm_traces(cfg: Config, state: dict[str, Any]) -> None:
    """Etape ``llm_traces`` (U7, OPTIONNELLE) : ``llm_farm.py`` (traces T2).

    Sautee si ``--llm-runs`` resout a 0 (defaut du profil ``default``).

    Args:
        cfg: configuration courante.
        state: etat global du pipeline (mute en place).
    """
    name = "llm_traces"
    st = state["stages"].setdefault(name, {})
    if cfg.profile.llm_runs <= 0:
        st.update(status="sautee", detail="--llm-runs 0 : étape optionnelle sautée.")
        print(f"[{name}] --llm-runs 0 — étape optionnelle sautée.")
        save_state(cfg.state_path, state)
        return
    if st.get("status") == "ok":
        print(f"[{name}] déjà fait — passage.")
        return
    script = cfg.script("projects/factory/llm_farm.py")
    _require(cfg, script, "U7")
    runs_llm = cfg.work_dir / "runs_llm"
    runs_llm.mkdir(parents=True, exist_ok=True)
    out = cfg.work_dir / "traces_t2.jsonl"
    cmd = [
        str(cfg.python_exe),
        str(script),
        "--runs-dir",
        str(runs_llm),
        "--out",
        str(out),
        "--model",
        "haiku",
        "--max-calls",
        str(cfg.profile.llm_runs),
    ]
    t0 = time.monotonic()
    result = _run(cmd)
    if result.returncode != 0:
        st.update(status="echec", detail=_fail_msg("llm_farm.py", result))
        save_state(cfg.state_path, state)
        raise EtapeEchoueeError(name, "U7", f"code {result.returncode}")
    st.update(status="ok", duration_s=time.monotonic() - t0, finished_at=_now())
    save_state(cfg.state_path, state)


def stage_t1_refit(cfg: Config, state: dict[str, Any]) -> None:
    """Etape ``t1_refit`` (U7) : ``behavior_model.py``, verdict RETENU/NON RETENU.

    Sautee (repli T1 compte) si ``llm_traces`` n'est pas passee a ``ok`` -
    sans traces T2, il n'y a rien a refitter.

    Args:
        cfg: configuration courante.
        state: etat global du pipeline (mute en place).
    """
    name = "t1_refit"
    st = state["stages"].setdefault(name, {})
    if state["stages"].get("llm_traces", {}).get("status") != "ok":
        st.update(
            status="sautee",
            verdict=None,
            detail="llm_traces non exécutée — refit T1 sauté (repli T1 compté).",
        )
        print(f"[{name}] llm_traces non exécutée — refit T1 sauté.")
        save_state(cfg.state_path, state)
        return
    if st.get("status") == "ok":
        print(f"[{name}] déjà fait — verdict archivé : {st.get('verdict')}.")
        return
    script = cfg.script("projects/simu_semiconducteurs/analysis/behavior_model.py")
    _require(cfg, script, "U7")
    t0 = time.monotonic()
    result = _run([str(cfg.python_exe), str(script)])
    output = f"{result.stdout or ''}\n{result.stderr or ''}"
    verdict = _parse_t1_verdict(output)
    if result.returncode != 0:
        st.update(status="echec", verdict=verdict, detail=_fail_msg("behavior_model.py", result))
        save_state(cfg.state_path, state)
        raise EtapeEchoueeError(name, "U7", f"code {result.returncode}")
    st.update(status="ok", verdict=verdict, duration_s=time.monotonic() - t0, finished_at=_now())
    print(f"[{name}] verdict : {verdict or 'NON DÉTECTÉ (aucune ligne RETENU/NON RETENU trouvée)'}")
    save_state(cfg.state_path, state)


def stage_amplified_runs(cfg: Config, state: dict[str, Any]) -> None:
    """Etape ``amplified_runs`` : campagnes HELIOS supplementaires avec RidgeDeclarant.

    Re-execute U5 (``run_campaign.py``) sur les MEMES dossiers de variantes
    que ``helios_runs``, mais avec ``--behavior
    projects.factory.declarants:RidgeDeclarant`` (contrat U5) : le declarant
    ridge T1 fraichement valide remplace le declarant par defaut, ce qui
    " amplifie " le dataset avec un comportement plus realiste. N'a lieu que
    si ``t1_refit`` a rendu le verdict ``RETENU`` (repli T1 compte sinon).

    Args:
        cfg: configuration courante.
        state: etat global du pipeline (mute en place).
    """
    name = "amplified_runs"
    st = state["stages"].setdefault(name, {})
    verdict = state["stages"].get("t1_refit", {}).get("verdict")
    if verdict != "RETENU":
        st.update(
            status="sautee",
            detail=f"verdict T1 = {verdict!r} (!= RETENU) — pas d'amplification comportementale.",
        )
        print(f"[{name}] {st['detail']}")
        save_state(cfg.state_path, state)
        return
    if st.get("status") == "ok":
        print(f"[{name}] déjà fait — passage.")
        return
    script = cfg.script("projects/simu_semiconducteurs/scripts/run_campaign.py")
    _require(cfg, script, "U5")
    variants = _variant_dirs(cfg)
    if not variants:
        st.update(status="echec", detail="aucune variante disponible pour l'amplification.")
        save_state(cfg.state_path, state)
        raise EtapeEchoueeError(name, "U4/U5", "prepared_variants/ vide")

    def build_cmd(seed: int, variant_dir: Path) -> list[str]:
        cmd = [
            str(cfg.python_exe),
            str(script),
            "--prepared",
            str(variant_dir),
            "--out",
            str(cfg.runs_dir),
            "--seed",
            str(seed),
            "--behavior",
            "projects.factory.declarants:RidgeDeclarant",
        ]
        if cfg.profile.rollout:
            cmd.append("--rollout")
        return cmd

    items = [
        (f"amp{i}", build_cmd(AMPLIFY_SEED_OFFSET + i, variants[i - 1]))
        for i in range(1, len(variants) + 1)
    ]
    _run_parallel_items(cfg, state, name, items, unit="U5/U7")


def stage_dataset(cfg: Config, state: dict[str, Any]) -> None:
    """Etape ``dataset`` (U8) : ``build_dataset.py --runs ... --out dataset.csv --append``.

    Args:
        cfg: configuration courante.
        state: etat global du pipeline (mute en place).
    """
    name = "dataset"
    st = state["stages"].setdefault(name, {})
    if st.get("status") == "ok":
        print(f"[{name}] déjà fait — passage.")
        return
    script = cfg.script("projects/factory/build_dataset.py")
    _require(cfg, script, "U8")
    out = cfg.work_dir / "dataset.csv"
    cmd = [
        str(cfg.python_exe),
        str(script),
        "--runs",
        str(cfg.runs_dir),
        "--out",
        str(out),
        "--append",
    ]
    t0 = time.monotonic()
    result = _run(cmd)
    if result.returncode != 0:
        st.update(status="echec", detail=_fail_msg("build_dataset.py", result))
        save_state(cfg.state_path, state)
        raise EtapeEchoueeError(name, "U8", f"code {result.returncode}")
    st.update(status="ok", duration_s=time.monotonic() - t0, finished_at=_now())
    save_state(cfg.state_path, state)


def stage_interventions_extract(cfg: Config, state: dict[str, Any]) -> None:
    """Etape ``interventions_extract`` (U8) : ``build_dataset.py --interventions``.

    Args:
        cfg: configuration courante.
        state: etat global du pipeline (mute en place).
    """
    name = "interventions_extract"
    st = state["stages"].setdefault(name, {})
    if st.get("status") == "ok":
        print(f"[{name}] déjà fait — passage.")
        return
    script = cfg.script("projects/factory/build_dataset.py")
    _require(cfg, script, "U8")
    out = cfg.work_dir / "interventions.csv"
    cmd = [
        str(cfg.python_exe),
        str(script),
        "--runs",
        str(cfg.runs_dir),
        "--interventions",
        "--out",
        str(out),
    ]
    t0 = time.monotonic()
    result = _run(cmd)
    if result.returncode != 0:
        st.update(status="echec", detail=_fail_msg("build_dataset.py --interventions", result))
        save_state(cfg.state_path, state)
        raise EtapeEchoueeError(name, "U8", f"code {result.returncode}")
    st.update(status="ok", duration_s=time.monotonic() - t0, finished_at=_now())
    save_state(cfg.state_path, state)


def stage_action_effects(cfg: Config, state: dict[str, Any]) -> None:
    """Etape ``action_effects`` (U17) : PORTE DE VALIDATION CAUSALE (D32).

    ``fit_action_effects.py --validate`` ecrit toujours dans un dossier de
    STAGING (jamais directement dans ``<work>/models/``). Le verdict global
    PASS/FAIL est extrait de sa sortie :

    - PASS : le contenu du staging est copie dans ``<work>/models/`` (fusion
      avec l'artefact predictif U10, publie separement par ``stage_train``) ;
    - FAIL (ou verdict indetermine) : RIEN n'est copie - l'artefact d'effets
      causaux reste dans ``staging_action_effects/``, jamais publie. Un
      message FR explique pourquoi. Le pipeline continue : l'artefact
      predictif sera publie normalement par l'etape ``train``.

    Args:
        cfg: configuration courante.
        state: etat global du pipeline (mute en place).
    """
    name = "action_effects"
    st = state["stages"].setdefault(name, {})
    if st.get("status") == "ok":
        print(f"[{name}] déjà fait — passage (publié={st.get('published')}).")
        return
    script = cfg.script("projects/factory/fit_action_effects.py")
    _require(cfg, script, "U17")
    interventions = cfg.work_dir / "interventions.csv"
    staging = cfg.work_dir / "staging_action_effects"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(cfg.python_exe),
        str(script),
        "--interventions",
        str(interventions),
        "--out",
        str(staging),
        "--validate",
    ]
    t0 = time.monotonic()
    result = _run(cmd)
    output = f"{result.stdout or ''}\n{result.stderr or ''}"
    verdict = _parse_global_verdict(output)
    if result.returncode != 0:
        st.update(
            status="echec",
            validate_verdict=verdict,
            detail=_fail_msg("fit_action_effects.py", result),
        )
        save_state(cfg.state_path, state)
        raise EtapeEchoueeError(name, "U17", f"code {result.returncode}")

    published = False
    if verdict == "PASS":
        cfg.models_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(staging, cfg.models_dir, dirs_exist_ok=True)
        published = True
        print(
            f"[{name}] PORTE CAUSALE : --validate = PASS — artefact d'effets publié dans models/."
        )
    else:
        print(
            f"[{name}] PORTE CAUSALE : --validate = {verdict or 'INDÉTERMINÉ'} — l'artefact "
            "d'effets causaux N'EST PAS publié (reste dans staging_action_effects/). "
            "L'artefact prédictif (U10) sera publié normalement à l'étape suivante."
        )
    st.update(
        status="ok",
        validate_verdict=verdict,
        published=published,
        duration_s=time.monotonic() - t0,
        finished_at=_now(),
    )
    save_state(cfg.state_path, state)


def stage_train(cfg: Config, state: dict[str, Any]) -> None:
    """Etape ``train`` (U10) : ``train_predictor.py --dataset ... --out <work>/models/``.

    Publie TOUJOURS l'artefact predictif, independamment du verdict de la
    porte causale (seul l'artefact d'effets d'actions est conditionne).

    Args:
        cfg: configuration courante.
        state: etat global du pipeline (mute en place).
    """
    name = "train"
    st = state["stages"].setdefault(name, {})
    if st.get("status") == "ok":
        print(f"[{name}] déjà fait — passage.")
        return
    script = cfg.script("projects/factory/train_predictor.py")
    _require(cfg, script, "U10")
    dataset = cfg.work_dir / "dataset.csv"
    cfg.models_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(cfg.python_exe),
        str(script),
        "--dataset",
        str(dataset),
        "--out",
        str(cfg.models_dir),
    ]
    if cfg.profile.fast_training:
        cmd.append("--fast")
    t0 = time.monotonic()
    result = _run(cmd)
    if result.returncode != 0:
        st.update(status="echec", detail=_fail_msg("train_predictor.py", result))
        save_state(cfg.state_path, state)
        raise EtapeEchoueeError(name, "U10", f"code {result.returncode}")
    st.update(status="ok", duration_s=time.monotonic() - t0, finished_at=_now())
    save_state(cfg.state_path, state)


def stage_smoke(cfg: Config, state: dict[str, Any]) -> None:
    """Etape ``smoke`` : chaine fraiche (U6) + ``predict``/``insights`` (U11/U12).

    Genere UNE chaine aleatoire neuve avec la graine reservee
    :data:`SMOKE_SEED` (hors de toute plage utilisee a l'entrainement), puis
    tente ``python -m supplyscore.tools.predict`` et
    ``python -m supplyscore.tools.insights`` dessus. L'absence de U11/U12 (ou
    l'echec de la decouverte automatique du db-dir/projet) est TOLEREE :
    l'etape se termine en statut ``"partiel"`` plutot que d'interrompre le
    pipeline, puisque tous les artefacts utiles ont deja ete publies par les
    etapes precedentes.

    Args:
        cfg: configuration courante.
        state: etat global du pipeline (mute en place).
    """
    name = "smoke"
    st = state["stages"].setdefault(name, {})
    if st.get("status") in ("ok", "partiel"):
        print(f"[{name}] déjà fait — passage (statut={st['status']}).")
        return
    script = cfg.script("projects/factory/run_random_campaign.py")
    _require(cfg, script, "U6")
    smoke_dir = cfg.work_dir / "runs_smoke"
    smoke_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(cfg.python_exe),
        str(script),
        "--chains",
        "1",
        "--weeks",
        "6",
        "--seed",
        str(SMOKE_SEED),
        "--out",
        str(smoke_dir),
        "--tier",
        str(cfg.profile.tier),
    ]
    t0 = time.monotonic()
    result = _run(cmd)
    if result.returncode != 0:
        st.update(status="echec", detail=_fail_msg("run_random_campaign.py (smoke)", result))
        save_state(cfg.state_path, state)
        raise EtapeEchoueeError(name, "U6", f"code {result.returncode}")

    results: dict[str, str] = {}
    discovery = _discover_db_project(smoke_dir)
    if discovery is None:
        results["decouverte"] = "echec"
        print(
            f"[{name}] découverte automatique du db-dir/projet impossible sous {smoke_dir} "
            "(aucun manifest.json exploitable, aucune base .sqlite unique) — "
            "CLIs predict/insights sautées (smoke partiel)."
        )
    else:
        db_dir, project_id = discovery
        results["decouverte"] = "ok"
        model = cfg.work_dir / "models" / "models" / "v1" / "artifact.json"
        for tool, module, unit in (
            ("predict", "supplyscore.tools.predict", "U11"),
            ("insights", "supplyscore.tools.insights", "U12"),
        ):
            cmd2 = [
                str(cfg.python_exe),
                "-m",
                module,
                "--db-dir",
                str(db_dir),
                "--project",
                project_id,
                "--model",
                str(model),
            ]
            result2 = _run(cmd2)
            if result2.returncode == 0:
                results[tool] = "ok"
            elif "No module named" in (result2.stderr or ""):
                results[tool] = "absent"
                print(
                    f"[{name}] maillon manquant : {unit} — module {module} (toléré, smoke partiel)."
                )
            else:
                results[tool] = f"echec:{result2.returncode}"
                print(f"[{name}] {module} a échoué (code {result2.returncode}).")

    predict_ok = results.get("predict") == "ok"
    insights_ok = results.get("insights") == "ok"
    complete = discovery is not None and predict_ok and insights_ok
    st.update(
        status="ok" if complete else "partiel",
        results=results,
        duration_s=time.monotonic() - t0,
        finished_at=_now(),
    )
    if discovery is not None:
        st["db_dir"] = str(discovery[0])
        st["project_id"] = discovery[1]
    save_state(cfg.state_path, state)
    print(f"[{name}] statut={'ok' if complete else 'partiel'} — {results}")


# Point d'entree

#: Etapes du pipeline, DANS L'ORDRE (cf. docstring du module et PIPELINE.md).
STAGES: list[tuple[str, Any]] = [
    ("opendata", stage_opendata),
    ("variants", stage_variants),
    ("helios_runs", stage_helios_runs),
    ("random_chains", stage_random_chains),
    ("llm_traces", stage_llm_traces),
    ("t1_refit", stage_t1_refit),
    ("amplified_runs", stage_amplified_runs),
    ("dataset", stage_dataset),
    ("interventions_extract", stage_interventions_extract),
    ("action_effects", stage_action_effects),
    ("train", stage_train),
    ("smoke", stage_smoke),
]


def main(argv: list[str] | None = None) -> int:
    """Point d'entree de l'orchestrateur.

    Args:
        argv: arguments de ligne de commande (``sys.argv[1:]`` si ``None``).

    Returns:
        ``0`` si toutes les etapes ont pu s'executer (certaines pouvant etre
        sautees ou partielles) ; ``1`` si le pipeline s'est interrompu a une
        etape (maillon manquant ou etape en echec - voir
        ``pipeline_state.json`` pour le detail).
    """
    args = build_parser().parse_args(argv)
    cfg = build_config(args)
    cfg.work_dir.mkdir(parents=True, exist_ok=True)

    if args.reset and cfg.state_path.exists():
        cfg.state_path.unlink()
        print(f"--reset : état précédent supprimé ({cfg.state_path}).")

    state = load_state(cfg.state_path) if cfg.state_path.exists() else new_state(cfg.profile.name)
    previous_profile = state.get("profile")
    has_progress = any(s.get("status") == "ok" for s in state["stages"].values())
    if has_progress and previous_profile not in (None, "inconnu", cfg.profile.name):
        print(
            f"AVERTISSEMENT : état précédent construit avec le profil "
            f"{previous_profile!r}, relancé avec {cfg.profile.name!r} — les étapes déjà "
            "« ok » ne seront PAS rejouées avec les nouveaux volumes (nombre de "
            "variantes/chaînes différent). Utilisez --reset pour changer de profil "
            "proprement.",
            file=sys.stderr,
        )
    state["profile"] = cfg.profile.name
    save_state(cfg.state_path, state)

    _print_estimate(cfg)

    for stage_name, stage_fn in STAGES:
        t0 = time.monotonic()
        try:
            stage_fn(cfg, state)
        except PipelineError as exc:
            st = state["stages"].setdefault(stage_name, {})
            st["status"] = "bloque"
            st["detail"] = str(exc)
            state["blocked_stage"] = stage_name
            save_state(cfg.state_path, state)
            print(f"\nPIPELINE INTERROMPU à l'étape « {stage_name} » : {exc}", file=sys.stderr)
            return 1
        except Exception as exc:  # filet de securite : jamais de trace non consignee
            st = state["stages"].setdefault(stage_name, {})
            st["status"] = "bloque"
            st["detail"] = f"erreur inattendue : {exc!r}"
            state["blocked_stage"] = stage_name
            save_state(cfg.state_path, state)
            print(
                f"\nPIPELINE INTERROMPU (erreur inattendue) à l'étape « {stage_name} » : {exc!r}",
                file=sys.stderr,
            )
            return 1
        print(f"[{stage_name}] durée mesurée : {_format_duration(time.monotonic() - t0)}.\n")

    state.pop("blocked_stage", None)
    save_state(cfg.state_path, state)
    print("Pipeline HÉLIOS terminé (voir pipeline_state.json pour le détail par étape).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
