"""Tests du point d'entree CLI ``supplyscore`` (Lot 17.3).

Couvre ``build_parser`` (defauts, ``--no-backup``, ``--open-browser``),
``main`` sans serveur reel (faux ``dash.Dash.run``) : code 0, service seede et
ferme proprement, sauvegarde automatique appelee/sautee, code 2 sans lancement
sur base corrompue, minuteur d'ouverture du navigateur - et la
retro-compatibilite du wrapper ``run_app``.
"""

from __future__ import annotations

import logging
import sys
import webbrowser
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import dash
import pytest

from supplyscore import cli
from supplyscore.data.backup import IntegriteError, ServiceSauvegarde
from supplyscore.web_ui import get_service, set_service

# ``run_app.py`` vit a la racine du projet (hors package installe) : on ajoute la racine au sys.path pour importer le wrapper retro-compatible.
_RACINE = Path(__file__).resolve().parents[1]
if str(_RACINE) not in sys.path:
    sys.path.insert(0, str(_RACINE))

import run_app  # noqa: E402

# Aides


class _FauxAtexit:
    """Capture les fonctions enregistrees, sans toucher au vrai ``atexit``."""

    def __init__(self) -> None:
        self.enregistres: list[Any] = []

    def register(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        self.enregistres.append(func)
        return func


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[SimpleNamespace]:
    """Environnement isole : ``app.run`` espionne, atexit capture, service nettoye."""
    runs: list[dict[str, Any]] = []

    def faux_run(self: dash.Dash, *args: Any, **kwargs: Any) -> None:
        runs.append(kwargs)

    monkeypatch.setattr(dash.Dash, "run", faux_run)
    faux_atexit = _FauxAtexit()
    monkeypatch.setattr(cli, "atexit", faux_atexit)
    db_dir = tmp_path / "data"
    log_dir = tmp_path / "logs"
    yield SimpleNamespace(
        runs=runs,
        atexit=faux_atexit,
        db_dir=db_dir,
        log_dir=log_dir,
        argv=["--db-dir", str(db_dir), "--log-dir", str(log_dir)],
    )
    # Nettoyage : libere le service global et ses fichiers SQLite (Windows).
    try:
        service = get_service()
    except RuntimeError:
        service = None
    set_service(None)
    if service is not None:
        service.close()  # idempotent : sans effet si le test a deja ferme


# build_parser


def test_build_parser_defauts() -> None:
    args = cli.build_parser().parse_args([])
    assert args.db_dir is None
    assert args.migrate_data is False
    assert args.demo is False
    assert args.port == 8050
    assert args.debug is False
    assert args.log_level == "INFO"
    assert args.log_dir is None
    assert args.no_backup is False
    assert args.open_browser is False


def test_build_parser_nouvelles_options() -> None:
    args = cli.build_parser().parse_args(["--no-backup", "--open-browser", "--port", "9000"])
    assert args.no_backup is True
    assert args.open_browser is True
    assert args.port == 9000


# main : lancement nominal


def test_main_demo_sans_backup_lance_et_seede(
    env: SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main([*env.argv, "--demo", "--no-backup", "--port", "8123"])

    assert code == 0
    # Serveur " lance " une fois, en local, sur le port demande, sans debug.
    assert env.runs == [{"host": "127.0.0.1", "port": 8123, "debug": False}]
    # La base etait vide : la demo a ete generee.
    service = get_service()
    assert service.registry.list_nodes()
    assert "Démo générée" in capsys.readouterr().out
    # Fermeture propre enregistree a la sortie : on l'execute sans erreur.
    assert service.close in env.atexit.enregistres
    for fermer in env.atexit.enregistres:
        fermer()


def test_main_service_absent_avertit_et_lance(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def get_service_ko() -> Any:
        raise RuntimeError("pas de service")

    monkeypatch.setattr(cli, "get_service", get_service_ko)

    with caplog.at_level(logging.WARNING, logger="supplyscore"):
        code = cli.main([*env.argv, "--no-backup"])

    assert code == 0
    assert len(env.runs) == 1
    assert "non initialisé" in caplog.text
    assert env.atexit.enregistres == []


# main : sauvegarde automatique


def test_main_sauvegarde_auto_appelee(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    appels: list[ServiceSauvegarde] = []

    def faux_backup_auto(self: ServiceSauvegarde, *args: Any, **kwargs: Any) -> None:
        appels.append(self)

    monkeypatch.setattr(ServiceSauvegarde, "backup_auto", faux_backup_auto)

    code = cli.main([*env.argv, "--demo"])

    assert code == 0
    assert len(appels) == 1
    assert appels[0].db_dir == env.db_dir
    # L'horloge du service horodate les archives (mode " jeu " respecte).
    assert appels[0].clock is get_service().clock
    assert len(env.runs) == 1


def test_main_no_backup_saute_la_sauvegarde(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    appels: list[ServiceSauvegarde] = []

    def faux_backup_auto(self: ServiceSauvegarde, *args: Any, **kwargs: Any) -> None:
        appels.append(self)

    monkeypatch.setattr(ServiceSauvegarde, "backup_auto", faux_backup_auto)

    code = cli.main([*env.argv, "--no-backup"])

    assert code == 0
    assert appels == []
    assert len(env.runs) == 1


def test_main_sauvegarde_auto_cree_une_archive(env: SimpleNamespace) -> None:
    """Sans espion : la vraie sauvegarde produit un zip dans db_dir/backups."""
    code = cli.main(env.argv)

    assert code == 0
    archives = list((env.db_dir / "backups").glob("SupplyScore_*.zip"))
    assert len(archives) == 1


def test_main_base_corrompue_code_2_sans_lancement(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def backup_corrompu(self: ServiceSauvegarde, *args: Any, **kwargs: Any) -> None:
        raise IntegriteError("registry.sqlite : integrity_check KO")

    monkeypatch.setattr(ServiceSauvegarde, "backup_auto", backup_corrompu)

    with caplog.at_level(logging.CRITICAL, logger="supplyscore"):
        code = cli.main(env.argv)

    assert code == cli.EXIT_BASE_CORROMPUE == 2
    assert env.runs == []  # app.run JAMAIS appele sur des bases corrompues
    assert "ne sera PAS lancé" in caplog.text
    assert "supplyscore.tools.restore" in caplog.text


# main : ouverture du navigateur


def test_main_open_browser_programme_le_minuteur(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    minuteries: list[tuple[float, Any, list[Any]]] = []

    class FauxTimer:
        def __init__(self, delai: float, fonction: Any, args: Any = None) -> None:
            minuteries.append((delai, fonction, list(args or [])))

        def start(self) -> None:
            pass

    monkeypatch.setattr(cli.threading, "Timer", FauxTimer)

    code = cli.main([*env.argv, "--no-backup", "--open-browser", "--port", "8442"])

    assert code == 0
    assert minuteries == [(cli.DELAI_NAVIGATEUR_S, webbrowser.open, ["http://127.0.0.1:8442/"])]
    assert len(env.runs) == 1


def test_main_sans_open_browser_aucun_minuteur(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timer_interdit(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("aucun minuteur ne doit être créé sans --open-browser")

    monkeypatch.setattr(cli.threading, "Timer", timer_interdit)

    code = cli.main([*env.argv, "--no-backup"])

    assert code == 0
    assert len(env.runs) == 1


# Retro-compatibilite du wrapper run_app


def test_run_app_reexporte_resolve_db_dir() -> None:
    """``from run_app import resolve_db_dir`` (test_infra_paths) reste valable."""
    assert run_app.resolve_db_dir is cli.resolve_db_dir


def test_run_app_reexporte_main() -> None:
    assert run_app.main is cli.main
