"""Tests des emplacements de données hors cloud (Lot 17.1).

Couvre ``supplyscore.infra.paths`` (emplacements par défaut, détection du
``data_store`` hérité, assistant de migration) et la résolution du répertoire
des bases de ``run_app.resolve_db_dir`` (fonction pure, testée sans serveur).
"""

from __future__ import annotations

import logging
import sqlite3
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest

from supplyscore.data.backup import ServiceSauvegarde
from supplyscore.infra.paths import (
    default_data_dir,
    default_log_dir,
    legacy_data_dir,
    migrate_legacy_data,
)

# ``run_app.py`` vit à la racine du projet (hors package installé) : on ajoute
# la racine au sys.path pour importer sa fonction de résolution pure.
_RACINE = Path(__file__).resolve().parents[1]
if str(_RACINE) not in sys.path:
    sys.path.insert(0, str(_RACINE))

from run_app import resolve_db_dir  # noqa: E402

# --- Aides -------------------------------------------------------------------------


def _creer_base(path: Path) -> None:
    """Crée une vraie base SQLite minimale (integrity_check « ok »)."""
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
        conn.commit()
    finally:
        conn.close()


def _creer_legacy(tmp_path: Path, *, residus_wal: bool = False) -> Path:
    """Crée ``tmp_path/data_store`` avec deux bases (et des résidus WAL au besoin)."""
    legacy = tmp_path / "data_store"
    legacy.mkdir()
    _creer_base(legacy / "registry.sqlite")
    _creer_base(legacy / "client.sqlite")
    if residus_wal:
        (legacy / "client.sqlite-wal").write_bytes(b"residu wal")
        (legacy / "client.sqlite-shm").write_bytes(b"residu shm")
    return legacy


def _fabrique(cible: Path) -> Callable[[], Path]:
    """Fabrique injectable retournant toujours ``cible`` (sans la créer)."""

    def interne() -> Path:
        return cible

    return interne


# --- Emplacements par défaut --------------------------------------------------------


def test_default_data_dir_contient_supplyscore() -> None:
    chemin = default_data_dir()
    assert "SupplyScore" in chemin.parts
    assert chemin.name == "data"
    assert chemin.is_absolute()


def test_default_log_dir_contient_supplyscore() -> None:
    chemin = default_log_dir()
    assert "SupplyScore" in chemin.parts
    assert chemin.name == "logs"
    assert chemin.is_absolute()


def test_default_dirs_partagent_le_meme_parent() -> None:
    assert default_data_dir().parent == default_log_dir().parent


# --- Détection du data_store hérité -------------------------------------------------


def test_legacy_data_dir_sans_dossier(tmp_path: Path) -> None:
    assert legacy_data_dir(tmp_path) is None


def test_legacy_data_dir_dossier_sans_base(tmp_path: Path) -> None:
    data_store = tmp_path / "data_store"
    data_store.mkdir()
    (data_store / "notes.txt").write_text("pas une base", encoding="utf-8")
    assert legacy_data_dir(tmp_path) is None


def test_legacy_data_dir_avec_base(tmp_path: Path) -> None:
    legacy = _creer_legacy(tmp_path)
    assert legacy_data_dir(tmp_path) == legacy


def test_legacy_data_dir_accepte_cwd_en_chaine(tmp_path: Path) -> None:
    legacy = _creer_legacy(tmp_path)
    assert legacy_data_dir(str(tmp_path)) == legacy


# --- Assistant de migration ----------------------------------------------------------


def test_migration_sauvegarde_puis_deplace(tmp_path: Path) -> None:
    """La migration crée le zip de sécurité PUIS déplace les bases (legacy vidé).

    Les résidus ``-wal``/``-shm`` périmés sont absorbés par SQLite lors de la
    sauvegarde (ouverture de chaque base) : quoi qu'il arrive, le dossier
    hérité ne contient plus AUCUN fichier SQLite après migration.
    """
    legacy = _creer_legacy(tmp_path, residus_wal=True)
    cible = tmp_path / "appdata" / "data"

    deplaces = migrate_legacy_data(legacy, cible)

    # Liste retournée : les bases, triées (résidus périmés purgés par SQLite).
    assert deplaces == ["client.sqlite", "registry.sqlite"]
    # Cible peuplée, source vidée (plus aucun fichier SQLite ni résidu).
    for nom in deplaces:
        assert (cible / nom).is_file()
    assert list(legacy.glob("*.sqlite*")) == []
    # Sauvegarde zip de sécurité dans <cible>.parent/backups_migration.
    zips = sorted((tmp_path / "appdata" / "backups_migration").glob("SupplyScore_*.zip"))
    assert len(zips) == 1
    with zipfile.ZipFile(zips[0]) as archive:
        assert sorted(archive.namelist()) == ["client.sqlite", "registry.sqlite"]


def test_migration_deplace_les_residus_wal_restants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Les résidus ``-wal``/``-shm`` encore présents après sauvegarde sont déplacés.

    La vraie sauvegarde purge les résidus périmés en ouvrant chaque base ; on
    la remplace ici par un enregistreur d'appel pour simuler des résidus qui
    survivent (fichiers redéposés par le client de synchronisation cloud...).
    """
    legacy = _creer_legacy(tmp_path, residus_wal=True)
    cible = tmp_path / "appdata" / "data"
    appels: list[Path] = []

    def faux_backup(self: ServiceSauvegarde, dest_dir: Path) -> Path:
        appels.append(Path(dest_dir))
        return Path(dest_dir) / "SupplyScore_factice.zip"

    monkeypatch.setattr(ServiceSauvegarde, "backup_all", faux_backup)

    deplaces = migrate_legacy_data(legacy, cible)

    # La sauvegarde a bien été demandée AVANT le déplacement, au bon endroit.
    assert appels == [tmp_path / "appdata" / "backups_migration"]
    # Bases triées, chacune suivie de ses résidus encore présents.
    assert deplaces == [
        "client.sqlite",
        "client.sqlite-wal",
        "client.sqlite-shm",
        "registry.sqlite",
    ]
    for nom in deplaces:
        assert (cible / nom).is_file()
    assert list(legacy.glob("*.sqlite*")) == []


def test_migration_refusee_si_cible_occupee(tmp_path: Path) -> None:
    """Cible déjà peuplée : refus en français, rien n'est déplacé ni sauvegardé."""
    legacy = _creer_legacy(tmp_path)
    cible = tmp_path / "cible"
    cible.mkdir()
    _creer_base(cible / "registry.sqlite")

    with pytest.raises(FileExistsError, match="migration refusée"):
        migrate_legacy_data(legacy, cible)

    assert (legacy / "registry.sqlite").is_file()
    assert (legacy / "client.sqlite").is_file()
    assert not (tmp_path / "backups_migration").exists()


def test_migration_legacy_sans_base(tmp_path: Path) -> None:
    """Aucune base dans le dossier hérité : la sauvegarde préalable refuse."""
    legacy = tmp_path / "data_store"
    legacy.mkdir()
    with pytest.raises(FileNotFoundError):
        migrate_legacy_data(legacy, tmp_path / "cible")


def test_migration_bases_restent_lisibles(tmp_path: Path) -> None:
    """Les bases migrées restent des bases SQLite valides."""
    legacy = _creer_legacy(tmp_path)
    cible = tmp_path / "appdata" / "data"
    migrate_legacy_data(legacy, cible)
    conn = sqlite3.connect(str(cible / "client.sqlite"))
    try:
        assert conn.execute("SELECT x FROM t").fetchone() == (1,)
    finally:
        conn.close()


# --- Résolution du répertoire des bases (run_app.resolve_db_dir) ---------------------


def test_resolve_a_db_dir_explicite_prioritaire(tmp_path: Path) -> None:
    """(a) ``--db-dir`` explicite : utilisé tel quel, fabrique jamais appelée."""
    _creer_legacy(tmp_path)  # même avec un data_store hérité présent

    def fabrique_interdite() -> Path:
        raise AssertionError("data_dir_factory ne doit pas être appelée en cas (a)")

    explicite = tmp_path / "ailleurs"
    resultat = resolve_db_dir(
        str(explicite), migrate=True, cwd=tmp_path, data_dir_factory=fabrique_interdite
    )
    assert resultat == explicite
    # Le data_store hérité n'a pas été touché.
    assert (tmp_path / "data_store" / "registry.sqlite").is_file()


def test_resolve_b_legacy_sans_flag_conserve_et_avertit(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """(b) sans ``--migrate-data`` : comportement historique + avertissement loggé."""
    legacy = _creer_legacy(tmp_path)
    cible = tmp_path / "appdata" / "data"

    with caplog.at_level(logging.WARNING, logger="supplyscore"):
        resultat = resolve_db_dir(
            None, migrate=False, cwd=tmp_path, data_dir_factory=_fabrique(cible)
        )

    assert resultat == legacy
    assert (legacy / "registry.sqlite").is_file()  # rien n'a été déplacé
    assert not cible.exists()
    assert "risque de corruption" in caplog.text
    assert "--migrate-data" in caplog.text


def test_resolve_b_legacy_avec_flag_migre(tmp_path: Path) -> None:
    """(b) avec ``--migrate-data`` : migration vers la cible, qui devient le db_dir."""
    legacy = _creer_legacy(tmp_path, residus_wal=True)
    cible = tmp_path / "appdata" / "data"

    resultat = resolve_db_dir(None, migrate=True, cwd=tmp_path, data_dir_factory=_fabrique(cible))

    assert resultat == cible
    assert (cible / "registry.sqlite").is_file()
    assert (cible / "client.sqlite").is_file()
    assert list(legacy.glob("*.sqlite*")) == []
    assert list((tmp_path / "appdata" / "backups_migration").glob("SupplyScore_*.zip"))


def test_resolve_c_defaut_cree(tmp_path: Path) -> None:
    """(c) ni --db-dir ni data_store hérité : emplacement par défaut, créé."""
    cible = tmp_path / "appdata" / "data"
    resultat = resolve_db_dir(None, migrate=False, cwd=tmp_path, data_dir_factory=_fabrique(cible))
    assert resultat == cible
    assert cible.is_dir()


def test_resolve_c_flag_migration_sans_legacy_inoffensif(tmp_path: Path) -> None:
    """(c) ``--migrate-data`` sans data_store hérité : simple emplacement par défaut."""
    cible = tmp_path / "appdata" / "data"
    resultat = resolve_db_dir(None, migrate=True, cwd=tmp_path, data_dir_factory=_fabrique(cible))
    assert resultat == cible
    assert cible.is_dir()
