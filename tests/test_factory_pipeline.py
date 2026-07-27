"""Tests de l'orchestrateur HÉLIOS v7 (U14) : projects/factory/run_pipeline.py.

Ce module de test vit hors de la couverture ``supplyscore`` (cf.
``pyproject.toml``, ``[tool.coverage.run] source = ["supplyscore"]``) mais
reste découvert par ``pytest tests -q`` (``testpaths = ["tests"]``) : il
vérifie la logique propre à U14 (reprise sur panne, porte causale, étapes
optionnelles, parallélisme par ProcessPoolExecutor) contre de FAUX scripts
sœurs minimaux, puisque les vraies unités U4-U18 n'existent pas dans ce
worktree (U14 est codé contre leurs contrats gelés, pas contre leur code).
"""

from __future__ import annotations

import json
import sqlite3
import sys
import textwrap
from pathlib import Path

import pytest

_FACTORY_DIR = Path(__file__).resolve().parent.parent / "projects" / "factory"
if str(_FACTORY_DIR) not in sys.path:
    sys.path.insert(0, str(_FACTORY_DIR))

import run_pipeline  # noqa: E402 -- après l'insertion sys.path ci-dessus, nécessaire

# --------------------------------------------------------------------------
# Faux scripts sœurs (sources minimales, ASCII, sans dépendance)
# --------------------------------------------------------------------------

_FETCH_OPENDATA_SRC = """
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--all", action="store_true")
    p.parse_args()
    print("opendata OK")
"""

_VARIANTS_SRC = """
    import argparse
    from pathlib import Path
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    lo, hi = args.seeds.split("..")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for i in range(int(lo), int(hi) + 1):
        (out / f"variant_{i:02d}").mkdir(exist_ok=True)
    print(f"variants OK {lo}..{hi}")
"""

_RUN_CAMPAIGN_SRC = """
    import argparse
    import os
    import sys
    from pathlib import Path
    p = argparse.ArgumentParser()
    p.add_argument("--prepared", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--seed", required=True)
    p.add_argument("--behavior", default=None)
    p.add_argument("--rollout", action="store_true")
    args = p.parse_args()
    poison = os.environ.get("FAKE_FAIL_SEED")
    if poison is not None and args.seed == poison:
        print(f"echec volontaire (test) pour seed={args.seed}", file=sys.stderr)
        sys.exit(1)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"run_seed_{args.seed}.marker").write_text(args.behavior or "default")
    print(f"run_campaign OK seed={args.seed}")
"""

_RUN_RANDOM_CAMPAIGN_SRC = """
    import argparse
    import sqlite3
    from pathlib import Path
    p = argparse.ArgumentParser()
    p.add_argument("--chains", required=True)
    p.add_argument("--weeks", required=True)
    p.add_argument("--seed", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--tier", required=True)
    p.add_argument("--rollout", action="store_true")
    args = p.parse_args()
    out = Path(args.out)
    run_dir = out / f"chain_{args.seed}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "marker.txt").write_text("ok")
    db = run_dir / "registry.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE projects (id TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO projects (id) VALUES (?)", (f"proj_{args.seed}",))
    conn.commit()
    conn.close()
    print(f"random_campaign OK seed={args.seed}")
"""

_LLM_FARM_SRC = """
    import argparse
    from pathlib import Path
    p = argparse.ArgumentParser()
    p.add_argument("--runs-dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--max-calls", required=True)
    args = p.parse_args()
    Path(args.runs_dir).mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text('{"trace": true}\\n')
    print("llm_farm OK")
"""

_BEHAVIOR_MODEL_SRC = """
    import os
    verdict = os.environ.get("FAKE_T1_VERDICT", "RETENU")
    print(f"Verdict T1 : {verdict}")
"""

_BUILD_DATASET_SRC = """
    import argparse
    from pathlib import Path
    p = argparse.ArgumentParser()
    p.add_argument("--runs", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--append", action="store_true")
    p.add_argument("--interventions", action="store_true")
    args = p.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    kind = "interventions" if args.interventions else "dataset"
    out.write_text(f"{kind}_csv_header\\n")
    print(f"build_dataset OK ({kind})")
"""

_FIT_ACTION_EFFECTS_SRC = """
    import argparse
    import os
    from pathlib import Path
    p = argparse.ArgumentParser()
    p.add_argument("--interventions", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--validate", action="store_true")
    args = p.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "action_effects.json").write_text('{"schema_version": 2}\\n')
    verdict = os.environ.get("FAKE_VALIDATE_VERDICT", "PASS")
    print("=== batterie D32 ===")
    print(f"critere couverture IC : {verdict}")
    print(f"verdict global : {verdict}")
"""

_TRAIN_PREDICTOR_SRC = """
    import argparse
    from pathlib import Path
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--fast", action="store_true")
    args = p.parse_args()
    model_dir = Path(args.out) / "models" / "v1"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "artifact.json").write_text('{"trained": true}\\n')
    print("train_predictor OK")
"""


def _write_script(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")


def _build_full_fake_repo(root: Path) -> None:
    """Peuple ``root`` avec un script factice par contrat gelé + MANIFEST U13."""
    _write_script(root / "projects/factory/opendata/fetch_opendata.py", _FETCH_OPENDATA_SRC)
    manifest = root / "projects/factory/opendata/MANIFEST.md"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("# manifest factice\n", encoding="utf-8")
    _write_script(root / "projects/simu_semiconducteurs/scenario/variants.py", _VARIANTS_SRC)
    _write_script(root / "projects/simu_semiconducteurs/scripts/run_campaign.py", _RUN_CAMPAIGN_SRC)
    _write_script(root / "projects/factory/run_random_campaign.py", _RUN_RANDOM_CAMPAIGN_SRC)
    _write_script(root / "projects/factory/llm_farm.py", _LLM_FARM_SRC)
    _write_script(
        root / "projects/simu_semiconducteurs/analysis/behavior_model.py", _BEHAVIOR_MODEL_SRC
    )
    _write_script(root / "projects/factory/build_dataset.py", _BUILD_DATASET_SRC)
    _write_script(root / "projects/factory/fit_action_effects.py", _FIT_ACTION_EFFECTS_SRC)
    _write_script(root / "projects/factory/train_predictor.py", _TRAIN_PREDICTOR_SRC)


def _config(repo_root: Path, work: Path, *extra_args: str) -> run_pipeline.Config:
    args = run_pipeline.build_parser().parse_args(
        ["--repo-root", str(repo_root), "--work", str(work), *extra_args]
    )
    return run_pipeline.build_config(args)


# --------------------------------------------------------------------------
# Fonctions pures
# --------------------------------------------------------------------------


def test_parse_t1_verdict_recognises_both_lines():
    assert run_pipeline._parse_t1_verdict("bruit\nVerdict T1 : RETENU\n") == "RETENU"
    assert run_pipeline._parse_t1_verdict("Verdict T1 : NON RETENU\n") == "NON RETENU"
    assert run_pipeline._parse_t1_verdict("rien a voir ici") is None


def test_parse_global_verdict_prefers_global_line():
    sortie = "critere A : PASS\ncritere B : FAIL\nverdict global : FAIL\n"
    assert run_pipeline._parse_global_verdict(sortie) == "FAIL"
    assert run_pipeline._parse_global_verdict("PASS quelque part\n") == "PASS"
    assert run_pipeline._parse_global_verdict("rien") is None


def test_format_duration_thresholds():
    assert run_pipeline._format_duration(5) == "5 s"
    assert run_pipeline._format_duration(65) == "1 min 05 s"
    assert run_pipeline._format_duration(3661) == "1 h 01 min"
    assert run_pipeline._format_duration(90000) == "1 j 01 h"


def test_discover_db_project_via_manifest(tmp_path: Path):
    smoke_dir = tmp_path / "smoke"
    (smoke_dir / "db").mkdir(parents=True)
    (smoke_dir / "manifest.json").write_text(
        json.dumps({"db_dir": "db", "project_id": "proj1"}), encoding="utf-8"
    )
    result = run_pipeline._discover_db_project(smoke_dir)
    assert result is not None
    db_dir, project_id = result
    assert project_id == "proj1"
    assert db_dir == (smoke_dir / "db").resolve()


def test_discover_db_project_via_unique_sqlite(tmp_path: Path):
    smoke_dir = tmp_path / "smoke"
    smoke_dir.mkdir()
    db_file = smoke_dir / "registry.sqlite"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE projects (id TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO projects (id) VALUES ('proj2')")
    conn.commit()
    conn.close()
    assert run_pipeline._discover_db_project(smoke_dir) == (smoke_dir, "proj2")


def test_discover_db_project_fails_gracefully(tmp_path: Path):
    smoke_dir = tmp_path / "smoke"
    smoke_dir.mkdir()
    assert run_pipeline._discover_db_project(smoke_dir) is None


# --------------------------------------------------------------------------
# Maillon manquant / reset
# --------------------------------------------------------------------------


def test_missing_unit_fails_cleanly_naming_first_unit(tmp_path: Path):
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    work = tmp_path / "work"
    code = run_pipeline.main(["--repo-root", str(fake_repo), "--work", str(work)])
    assert code == 1
    state = json.loads((work / "pipeline_state.json").read_text(encoding="utf-8"))
    # opendata est optionnelle (MANIFEST.md absent) : sautée, pas bloquante.
    assert state["stages"]["opendata"]["status"] == "sautee"
    # U4 (variants) est le PREMIER maillon réellement manquant.
    assert state["blocked_stage"] == "variants"
    assert "maillon manquant : U4" in state["stages"]["variants"]["detail"]
    assert "variants.py" in state["stages"]["variants"]["detail"]


def test_reset_clears_previous_state(tmp_path: Path):
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    work = tmp_path / "work"
    run_pipeline.main(["--repo-root", str(fake_repo), "--work", str(work)])
    state_path = work / "pipeline_state.json"
    assert state_path.exists()
    data = json.loads(state_path.read_text(encoding="utf-8"))
    data["stages"]["variants"]["status"] = "ok"  # falsifie un succès
    state_path.write_text(json.dumps(data), encoding="utf-8")

    run_pipeline.main(["--repo-root", str(fake_repo), "--work", str(work), "--reset"])
    data2 = json.loads(state_path.read_text(encoding="utf-8"))
    # état neuf : le pipeline a dû ré-échouer proprement, pas hériter du faux "ok".
    assert data2["stages"]["variants"]["status"] != "ok"
    assert data2["blocked_stage"] == "variants"


# --------------------------------------------------------------------------
# Porte de validation causale (D32)
# --------------------------------------------------------------------------


def test_causal_gate_fail_withholds_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake_repo = tmp_path / "repo"
    _write_script(fake_repo / "projects/factory/fit_action_effects.py", _FIT_ACTION_EFFECTS_SRC)
    work = tmp_path / "work"
    work.mkdir()
    (work / "interventions.csv").write_text("dummy\n", encoding="utf-8")
    monkeypatch.setenv("FAKE_VALIDATE_VERDICT", "FAIL")

    cfg = _config(fake_repo, work)
    state = run_pipeline.new_state(cfg.profile.name)
    run_pipeline.stage_action_effects(cfg, state)

    st = state["stages"]["action_effects"]
    assert st["status"] == "ok"
    assert st["validate_verdict"] == "FAIL"
    assert st["published"] is False
    assert not (cfg.models_dir / "action_effects.json").exists()
    assert (work / "staging_action_effects" / "action_effects.json").exists()


def test_causal_gate_pass_publishes_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake_repo = tmp_path / "repo"
    _write_script(fake_repo / "projects/factory/fit_action_effects.py", _FIT_ACTION_EFFECTS_SRC)
    work = tmp_path / "work"
    work.mkdir()
    (work / "interventions.csv").write_text("dummy\n", encoding="utf-8")
    monkeypatch.setenv("FAKE_VALIDATE_VERDICT", "PASS")

    cfg = _config(fake_repo, work)
    state = run_pipeline.new_state(cfg.profile.name)
    run_pipeline.stage_action_effects(cfg, state)

    st = state["stages"]["action_effects"]
    assert st["status"] == "ok"
    assert st["validate_verdict"] == "PASS"
    assert st["published"] is True
    assert (cfg.models_dir / "action_effects.json").exists()


# --------------------------------------------------------------------------
# Parallélisme + reprise fine par item (helios_runs)
# --------------------------------------------------------------------------


def test_helios_runs_resumes_only_failed_item(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake_repo = tmp_path / "repo"
    _write_script(fake_repo / "projects/simu_semiconducteurs/scenario/variants.py", _VARIANTS_SRC)
    _write_script(
        fake_repo / "projects/simu_semiconducteurs/scripts/run_campaign.py", _RUN_CAMPAIGN_SRC
    )
    work = tmp_path / "work"
    cfg = _config(fake_repo, work, "--max-workers", "2")
    state = run_pipeline.new_state(cfg.profile.name)

    run_pipeline.stage_variants(cfg, state)
    assert state["stages"]["variants"]["status"] == "ok"
    assert state["stages"]["variants"]["n_found"] == cfg.profile.n_variants == 5

    monkeypatch.setenv("FAKE_FAIL_SEED", "2")
    with pytest.raises(run_pipeline.EtapeEchoueeError):
        run_pipeline.stage_helios_runs(cfg, state)
    st = state["stages"]["helios_runs"]
    assert st["status"] == "echec"
    assert set(st["done_items"]) == {"1", "3", "4", "5"}
    assert not (cfg.runs_dir / "run_seed_2.marker").exists()

    monkeypatch.delenv("FAKE_FAIL_SEED", raising=False)
    run_pipeline.stage_helios_runs(cfg, state)  # reprise : ne rejoue QUE l'item "2"
    st = state["stages"]["helios_runs"]
    assert st["status"] == "ok"
    assert set(st["done_items"]) == {"1", "2", "3", "4", "5"}
    for i in range(1, 6):
        assert (cfg.runs_dir / f"run_seed_{i}.marker").exists()


def test_helios_runs_already_done_short_circuits(tmp_path: Path):
    """Un item déjà dans done_items n'est jamais soumis au pool une seconde fois."""
    fake_repo = tmp_path / "repo"
    work = tmp_path / "work"
    cfg = _config(fake_repo, work)
    state = run_pipeline.new_state(cfg.profile.name)
    state["stages"]["helios_runs"] = {"status": "ok", "done_items": ["1"], "total": 1}
    # Aucun script sœur nécessaire : le statut "ok" fait sauter l'étape entière.
    run_pipeline.stage_helios_runs(cfg, state)
    assert state["stages"]["helios_runs"]["status"] == "ok"


# --------------------------------------------------------------------------
# amplified_runs conditionné au verdict T1
# --------------------------------------------------------------------------


def test_amplified_runs_skipped_when_t1_not_retenu(tmp_path: Path):
    fake_repo = tmp_path / "repo"
    work = tmp_path / "work"
    cfg = _config(fake_repo, work)
    state = run_pipeline.new_state(cfg.profile.name)
    state["stages"]["t1_refit"] = {"status": "ok", "verdict": "NON RETENU"}
    # Aucun script sœur requis : sautée avant même l'appel à _require.
    run_pipeline.stage_amplified_runs(cfg, state)
    assert state["stages"]["amplified_runs"]["status"] == "sautee"


def test_amplified_runs_executes_with_ridge_declarant_when_retenu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fake_repo = tmp_path / "repo"
    _write_script(fake_repo / "projects/simu_semiconducteurs/scenario/variants.py", _VARIANTS_SRC)
    _write_script(
        fake_repo / "projects/simu_semiconducteurs/scripts/run_campaign.py", _RUN_CAMPAIGN_SRC
    )
    _write_script(
        fake_repo / "projects/simu_semiconducteurs/analysis/behavior_model.py", _BEHAVIOR_MODEL_SRC
    )
    work = tmp_path / "work"
    cfg = _config(fake_repo, work, "--max-workers", "2")
    state = run_pipeline.new_state(cfg.profile.name)

    run_pipeline.stage_variants(cfg, state)
    state["stages"]["llm_traces"] = {"status": "ok"}
    monkeypatch.setenv("FAKE_T1_VERDICT", "RETENU")
    run_pipeline.stage_t1_refit(cfg, state)
    assert state["stages"]["t1_refit"]["verdict"] == "RETENU"

    run_pipeline.stage_amplified_runs(cfg, state)
    assert state["stages"]["amplified_runs"]["status"] == "ok"
    for i in range(1, cfg.profile.n_variants + 1):
        marker = cfg.runs_dir / f"run_seed_{run_pipeline.AMPLIFY_SEED_OFFSET + i}.marker"
        assert marker.read_text(encoding="utf-8") == "projects.factory.declarants:RidgeDeclarant"


def test_t1_refit_skipped_without_llm_traces(tmp_path: Path):
    fake_repo = tmp_path / "repo"
    work = tmp_path / "work"
    cfg = _config(fake_repo, work)
    state = run_pipeline.new_state(cfg.profile.name)
    # llm_traces jamais passée à "ok" (état neuf) -> repli T1 compté, aucun script requis.
    run_pipeline.stage_t1_refit(cfg, state)
    assert state["stages"]["t1_refit"]["status"] == "sautee"
    assert state["stages"]["t1_refit"]["verdict"] is None


# --------------------------------------------------------------------------
# Pipeline complet, profil par défaut, contre de faux scripts
# --------------------------------------------------------------------------


def test_full_default_pipeline_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake_repo = tmp_path / "repo"
    _build_full_fake_repo(fake_repo)
    work = tmp_path / "work"
    monkeypatch.setenv("FAKE_VALIDATE_VERDICT", "PASS")

    code = run_pipeline.main(
        ["--repo-root", str(fake_repo), "--work", str(work), "--max-workers", "2"]
    )
    assert code == 0

    state = json.loads((work / "pipeline_state.json").read_text(encoding="utf-8"))
    assert "blocked_stage" not in state
    stages = state["stages"]
    assert stages["opendata"]["status"] == "ok"
    assert stages["variants"]["status"] == "ok"
    assert stages["helios_runs"]["status"] == "ok"
    assert stages["random_chains"]["status"] == "ok"
    # profil par défaut : --llm-runs 0 -> toute la chaîne T2/T1/amplification est sautée.
    assert stages["llm_traces"]["status"] == "sautee"
    assert stages["t1_refit"]["status"] == "sautee"
    assert stages["amplified_runs"]["status"] == "sautee"
    assert stages["dataset"]["status"] == "ok"
    assert stages["interventions_extract"]["status"] == "ok"
    assert stages["action_effects"]["status"] == "ok"
    assert stages["action_effects"]["published"] is True
    assert stages["train"]["status"] == "ok"
    # Smoke best-effort (toléré) : depuis la fusion des 18 unités, les CLIs
    # supplyscore.tools.predict/insights (U11/U12) EXISTENT et sont réellement
    # invoquées. La chaîne de smoke produite par U6 n'expose que des snapshots
    # JSON (db-dir jetable), donc predict/insights ne peuvent pas s'y connecter
    # (statut « partiel », résultat « echec:N ») — jamais « absent ». Rendre ce
    # smoke pleinement vert demanderait à U6 de persister une base ≥ 4 semaines
    # d'historique et à U14 de la cibler (suite notée, hors périmètre de fusion).
    assert stages["smoke"]["status"] in ("ok", "partiel")
    assert stages["smoke"]["results"]["predict"] != "absent"
    assert stages["smoke"]["results"]["insights"] != "absent"

    assert (work / "models" / "models" / "v1" / "artifact.json").exists()
    assert (work / "models" / "action_effects.json").exists()
    assert (work / "dataset.csv").exists()
    assert (work / "interventions.csv").exists()


def test_full_pipeline_second_run_resumes_and_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Deuxième lancement (sans --reset) : toutes les étapes déjà « ok » sont sautées."""
    fake_repo = tmp_path / "repo"
    _build_full_fake_repo(fake_repo)
    work = tmp_path / "work"
    monkeypatch.setenv("FAKE_VALIDATE_VERDICT", "PASS")

    code1 = run_pipeline.main(
        ["--repo-root", str(fake_repo), "--work", str(work), "--max-workers", "2"]
    )
    assert code1 == 0
    state1 = json.loads((work / "pipeline_state.json").read_text(encoding="utf-8"))

    code2 = run_pipeline.main(
        ["--repo-root", str(fake_repo), "--work", str(work), "--max-workers", "2"]
    )
    assert code2 == 0
    state2 = json.loads((work / "pipeline_state.json").read_text(encoding="utf-8"))

    for name in ("variants", "helios_runs", "random_chains", "dataset", "train"):
        assert state1["stages"][name]["status"] == state2["stages"][name]["status"] == "ok"
        # "finished_at" du deuxième run doit être identique : l'étape n'a PAS été rejouée.
        assert state1["stages"][name].get("finished_at") == state2["stages"][name].get(
            "finished_at"
        )
