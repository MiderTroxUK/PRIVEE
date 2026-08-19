r"""Emplacements des donnees et journaux hors dossier synchronise cloud (Lot 17.1).

Les bases SQLite en mode WAL stockees dans un dossier synchronise (OneDrive,
Dropbox...) presentent un risque reel de corruption - faiblesse #21 : le
client de synchronisation peut copier ``*.sqlite``, ``-wal`` et ``-shm`` a
des instants incoherents. Ce module fournit les emplacements par defaut hors
synchronisation (``%LOCALAPPDATA%\SupplyScore`` sous Windows, via
:mod:`platformdirs`) ainsi qu'un assistant de migration depuis l'ancien
``data_store/`` local au projet, avec sauvegarde zip de securite AVANT tout
deplacement.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from platformdirs import user_data_dir

from supplyscore.data.backup import ServiceSauvegarde

#: Nom de l'application pour :mod:`platformdirs` (sans sous-dossier editeur).
APP_NAME = "SupplyScore"

#: Nom du repertoire herite des bases, relatif au dossier de lancement.
LEGACY_DIR_NAME = "data_store"

#: Sous-repertoire (frere du dossier cible) recevant le zip de securite.
MIGRATION_BACKUP_DIR_NAME = "backups_migration"

#: Suffixes des fichiers annexes SQLite residuels qui suivent leur base.
_SUFFIXES_ANNEXES = ("-wal", "-shm")


def default_data_dir() -> Path:
    r"""Emplacement par defaut des bases SQLite, hors dossier synchronise cloud.

    Returns:
        ``%LOCALAPPDATA%\SupplyScore\data`` sous Windows (equivalent
        :mod:`platformdirs` ailleurs). Le repertoire n'est PAS cree ici :
        c'est a l'appelant de le creer s'il decide de l'utiliser.
    """
    return Path(user_data_dir(APP_NAME, appauthor=False)) / "data"


def default_log_dir() -> Path:
    r"""Emplacement par defaut des journaux, hors dossier synchronise cloud.

    Returns:
        ``%LOCALAPPDATA%\SupplyScore\logs`` sous Windows (equivalent
        :mod:`platformdirs` ailleurs). Le repertoire n'est PAS cree ici :
        :func:`supplyscore.infra.logging.configure_logging` s'en charge.
    """
    return Path(user_data_dir(APP_NAME, appauthor=False)) / "logs"


def legacy_data_dir(cwd: Path | str = ".") -> Path | None:
    """Detecte l'ancien repertoire de donnees ``data_store`` a migrer.

    Args:
        cwd: dossier de lancement de l'application (``"."`` par defaut).

    Returns:
        ``<cwd>/data_store`` s'il existe et contient au moins une base
        ``*.sqlite`` ; ``None`` sinon (rien a migrer).
    """
    candidat = Path(cwd) / LEGACY_DIR_NAME
    if candidat.is_dir() and any(p.is_file() for p in candidat.glob("*.sqlite")):
        return candidat
    return None


def migrate_legacy_data(legacy: Path, target: Path) -> list[str]:
    """Migre les bases SQLite de l'ancien ``data_store`` vers ``target``.

    Assistant de migration en trois temps :

    1. refus immediat (:class:`FileExistsError`) si ``target`` contient deja
       des bases ``*.sqlite`` - rien n'est alors touche ;
    2. sauvegarde de securite AVANT tout deplacement :
       :meth:`~supplyscore.data.backup.ServiceSauvegarde.backup_all` archive
       les bases de ``legacy`` dans ``target.parent / "backups_migration"`` ;
    3. deplacement (:func:`shutil.move`) de chaque ``*.sqlite`` - et de ses
       eventuels residus ``-wal``/``-shm`` - de ``legacy`` vers ``target``
       (cree au besoin).

    Args:
        legacy: ancien repertoire contenant les bases (``data_store``).
        target: nouveau repertoire des bases (``default_data_dir()``...).

    Returns:
        Noms des fichiers deplaces, bases puis residus, dans l'ordre trie
        des bases.

    Raises:
        FileExistsError: si ``target`` contient deja des bases ``*.sqlite``.
        FileNotFoundError: si ``legacy`` ne contient aucune base ``*.sqlite``.
        supplyscore.data.backup.IntegriteError: si une base de ``legacy`` est
            corrompue - la sauvegarde echoue et rien n'est deplace.
    """
    if target.is_dir() and any(p.is_file() for p in target.glob("*.sqlite")):
        raise FileExistsError(
            f"Le répertoire cible {target} contient déjà des bases SQLite : migration refusée. "
            "Déplacez-les ou choisissez un autre emplacement (--db-dir) avant de relancer."
        )
    ServiceSauvegarde(legacy).backup_all(target.parent / MIGRATION_BACKUP_DIR_NAME)
    target.mkdir(parents=True, exist_ok=True)
    deplaces: list[str] = []
    for base in sorted(p for p in legacy.glob("*.sqlite") if p.is_file()):
        annexes = [base.with_name(base.name + suffixe) for suffixe in _SUFFIXES_ANNEXES]
        for fichier in [base, *annexes]:
            if fichier.is_file():
                shutil.move(str(fichier), str(target / fichier.name))
                deplaces.append(fichier.name)
    return deplaces
