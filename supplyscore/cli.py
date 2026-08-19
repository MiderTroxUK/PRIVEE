r"""Interface en ligne de commande de SupplyScore (Lot 17.3).

Point d'entree UNIQUE du serveur web local : la commande ``supplyscore``
(entry point ``[project.scripts]``) et ``python -m supplyscore.cli`` appellent
:func:`main`. L'ancien ``run_app.py`` a la racine du depot n'est plus qu'un
mince wrapper retro-compatible qui reexporte :func:`main` et
:func:`resolve_db_dir`.

Usage :
    supplyscore [--db-dir CHEMIN] [--migrate-data] [--demo] [--port 8050]
                [--debug] [--log-level INFO] [--log-dir CHEMIN]
                [--no-backup] [--open-browser]

Resolution du repertoire des bases (Lot 17.1 - donnees hors dossier
synchronise cloud, faiblesse #21) :

(a) ``--db-dir`` explicite : prioritaire, utilise tel quel ;
(b) sinon, si un ``data_store/`` herite contient des bases : avec
    ``--migrate-data`` elles sont migrees (sauvegarde zip puis deplacement)
    vers l'emplacement par defaut hors synchronisation, qui devient la
    cible ; SANS le flag, le comportement historique est conserve
    (``data_store``) avec un avertissement logge ;
(c) sinon, l'emplacement par defaut ``%LOCALAPPDATA%\SupplyScore\data``
    (cree au besoin).

Les journaux vont par defaut dans ``%LOCALAPPDATA%\SupplyScore\logs``
(``--log-dir`` pour les rediriger).

Sauvegarde automatique au demarrage (Lot 17.2) : apres la construction du
service et AVANT le lancement du serveur,
:meth:`~supplyscore.data.backup.ServiceSauvegarde.backup_auto` cree une
archive si la plus recente a plus de 24 h, puis applique la retention
(20 archives conservees). Une base corrompue
(:class:`~supplyscore.data.backup.IntegriteError`) arrete TOUT avec le code
de sortie 2 : on ne lance PAS l'application sur des bases corrompues -
restaurer d'abord une archive saine (``python -m supplyscore.tools.restore``)
puis relancer. ``--no-backup`` saute cette etape (tests / developpement).

L'option ``--demo`` genere un projet de TEST aleatoire (seed_demo) uniquement
si la base est vide - donnees simulees, jamais pour la production.

Notes PyInstaller (futur paquet one-folder - RIEN n'est code ici, pieges
documentes pour memoire) :

- Dash et Plotly embarquent des ressources non-Python (bundles JS,
  ``package.json``, schemas de validation) invisibles a l'analyse statique :
  construire avec ``--collect-data dash --collect-data plotly`` sous peine
  de page blanche au premier rendu ;
- declarer les pages Dash en ``hiddenimports``
  (``--hidden-import supplyscore.web_ui.pages.<module>`` pour chaque page de
  ``supplyscore/web_ui/pages/``) : tout import resolu dynamiquement echappe
  a l'analyse de PyInstaller ;
- le point d'entree du binaire reste :func:`main` (``supplyscore.cli:main``).
"""

from __future__ import annotations

import argparse
import atexit
import logging
import sys
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path

from supplyscore import __version__
from supplyscore.data.backup import IntegriteError, ServiceSauvegarde
from supplyscore.infra.logging import configure_logging
from supplyscore.infra.paths import (
    default_data_dir,
    default_log_dir,
    legacy_data_dir,
    migrate_legacy_data,
)
from supplyscore.web_ui import get_service
from supplyscore.web_ui.app import create_app

#: Delai (secondes) avant l'ouverture du navigateur : ``app.run`` bloque le thread principal, l'ouverture est donc programmee AVANT le demarrage du serveur, sur un thread minuteur - le serveur ecoute bien avant l'echeance.
DELAI_NAVIGATEUR_S = 1.5

#: Code de sortie quand une base corrompue est detectee au demarrage.
EXIT_BASE_CORROMPUE = 2


def resolve_db_dir(
    arg_db_dir: str | None,
    migrate: bool,
    cwd: Path | str = ".",
    data_dir_factory: Callable[[], Path] = default_data_dir,
) -> Path:
    """Resout le repertoire des bases SQLite (testable sans lancer le serveur).

    Regles, dans l'ordre :

    (a) ``arg_db_dir`` explicite (option ``--db-dir``) : prioritaire ;
    (b) sinon, si :func:`~supplyscore.infra.paths.legacy_data_dir` detecte un
        ``data_store/`` peuple sous ``cwd`` : avec ``migrate`` les bases sont
        migrees via :func:`~supplyscore.infra.paths.migrate_legacy_data` vers
        ``data_dir_factory()`` qui devient la cible ; sans ``migrate``, le
        repertoire herite est conserve (comportement historique) et un
        avertissement " risque de corruption " est logge ;
    (c) sinon ``data_dir_factory()``, cree au besoin.

    Args:
        arg_db_dir: valeur de ``--db-dir`` (``None`` si absente).
        migrate: valeur du flag ``--migrate-data``.
        cwd: dossier de lancement ou chercher le ``data_store`` herite.
        data_dir_factory: fabrique de l'emplacement par defaut
            (:func:`~supplyscore.infra.paths.default_data_dir` en production ;
            injectable dans les tests).

    Returns:
        Le repertoire des bases SQLite a utiliser.

    Raises:
        FileExistsError: si la migration est demandee alors que la cible
            contient deja des bases SQLite.
    """
    logger = logging.getLogger("supplyscore")
    if arg_db_dir is not None:
        return Path(arg_db_dir)
    legacy = legacy_data_dir(cwd)
    if legacy is not None:
        target = data_dir_factory()
        if migrate:
            deplaces = migrate_legacy_data(legacy, target)
            logger.info(
                "Migration des données : %d fichier(s) déplacé(s) de %s vers %s "
                "(sauvegarde zip dans %s).",
                len(deplaces),
                legacy,
                target,
                target.parent / "backups_migration",
            )
            return target
        logger.warning(
            "Bases SQLite détectées dans %s — données dans un dossier synchronisé cloud — "
            "risque de corruption ; lancez avec --migrate-data pour les déplacer vers %s.",
            legacy,
            target,
        )
        return legacy
    target = data_dir_factory()
    target.mkdir(parents=True, exist_ok=True)
    return target


def build_parser() -> argparse.ArgumentParser:
    """Construit l'analyseur d'arguments de la commande ``supplyscore``.

    Returns:
        L'analyseur configure avec toutes les options du serveur local.
    """
    parser = argparse.ArgumentParser(
        prog="supplyscore",
        description="Lance l'interface web SupplyScore (Dash).",
    )
    parser.add_argument(
        "--db-dir",
        default=None,
        help=(
            "Répertoire des bases SQLite (prioritaire). Défaut : "
            "%%LOCALAPPDATA%%\\SupplyScore\\data, ou le data_store hérité s'il existe."
        ),
    )
    parser.add_argument(
        "--migrate-data",
        action="store_true",
        help=(
            "Migre les bases d'un data_store hérité vers l'emplacement par défaut "
            "hors dossier synchronisé (sauvegarde zip de sécurité avant déplacement)."
        ),
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Si la base est vide, génère un projet de TEST aléatoire (n_ranks=3, seed=42).",
    )
    parser.add_argument(
        "--port", type=int, default=8050, help="Port d'écoute HTTP (défaut : 8050)."
    )
    parser.add_argument(
        "--debug", action="store_true", help="Active le mode debug de Dash (rechargement à chaud)."
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Niveau de journalisation (DEBUG, INFO, WARNING... — défaut : INFO).",
    )
    parser.add_argument(
        "--log-dir",
        default=None,
        help="Dossier des journaux (défaut : %%LOCALAPPDATA%%\\SupplyScore\\logs).",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Saute la sauvegarde automatique au démarrage (tests / développement).",
    )
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Ouvre le navigateur par défaut sur l'application une fois le serveur démarré.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Analyse les arguments, construit l'application et lance le serveur.

    Args:
        argv: arguments de la ligne de commande (``sys.argv[1:]`` si ``None``).

    Returns:
        ``0`` si le serveur s'est arrete normalement ;
        :data:`EXIT_BASE_CORROMPUE` (2) si la sauvegarde automatique a detecte
        une base corrompue - le serveur n'est alors PAS lance : on ne joue pas
        un serious game sur des donnees irrecuperables.
    """
    args = build_parser().parse_args(argv)

    log_dir = Path(args.log_dir) if args.log_dir is not None else default_log_dir()
    logger = configure_logging(level=args.log_level, log_dir=log_dir)

    db_dir = resolve_db_dir(args.db_dir, args.migrate_data)
    logger.info("Démarrage de SupplyScore v%s — port %s, base : %s", __version__, args.port, db_dir)

    app = create_app(db_dir=str(db_dir))

    try:
        service = get_service()
    except RuntimeError:
        service = None
        logger.warning("Service SupplyScore non initialisé après create_app.")

    if service is not None:
        close = getattr(service, "close", None)
        if callable(close):
            atexit.register(close)

    # Sauvegarde automatique (Lot 17.2) - APRES la creation du service (les bases existent), AVANT toute ecriture de la session et AVANT app.run. Une base corrompue interdit le lancement (code 2).
    if not args.no_backup:
        clock = service.clock if service is not None else None
        try:
            archive = ServiceSauvegarde(db_dir, clock=clock).backup_auto()
        except IntegriteError as exc:
            logger.critical(
                "Base corrompue détectée par la sauvegarde automatique : %s — "
                "SupplyScore ne sera PAS lancé sur des bases corrompues. "
                "Restaurez une archive saine (python -m supplyscore.tools.restore) "
                "puis relancez.",
                exc,
            )
            return EXIT_BASE_CORROMPUE
        if archive is not None:
            logger.info("Sauvegarde automatique créée : %s", archive)

    if service is not None and args.demo and not service.registry.list_nodes():
        project = service.seed_demo(n_ranks=3, seed=42)
        print(f"Démo générée : « {project.name} » (données de TEST aléatoires).")

    if args.open_browser:
        # ``app.run`` bloque le thread principal : impossible d'ouvrir le navigateur " apres le demarrage du serveur ". L'ouverture est donc programmee AVANT app.run, differee de DELAI_NAVIGATEUR_S sur un thread minuteur - le serveur ecoute bien avant l'echeance.
        url = f"http://127.0.0.1:{args.port}/"
        threading.Timer(DELAI_NAVIGATEUR_S, webbrowser.open, [url]).start()

    app.run(host="127.0.0.1", port=args.port, debug=args.debug)
    return 0


if __name__ == "__main__":  # pragma: no cover - couvert par l'entry point
    sys.exit(main())
