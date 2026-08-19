"""Tests des emplacements de donnees hors cloud (Lot 17.1).

Couvre ``supplyscore.infra.paths`` (emplacements par defaut, detection du
``data_store`` herite, assistant de migration) et la resolution du repertoire
des bases de ``run_app.resolve_db_dir`` (fonction pure, testee sans serveur).
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

# ``run_app.py`` vit a la racine du projet (hors package installe) : on ajoute la racine au sys.path pour importer sa fonction de resolution pure.
_RACINE = Path(__file__).resolve().parents[1]
if str(_RACINE) not in sys.path:
    sys.path.insert(0, str(_RACINE))

from run_app import resolve_db_dir  # noqa: E402

# Aides


def _creer_base(path: Path) -> None:
    """Cree une vraie base SQLite minimale (integrity_check " ok ")."""
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
        conn.commit()
    finally:
        conn.close()


def _creer_legacy(tmp_path: Path, *, residus_wal: bool = False) -> Path:
    """Cree ``tmp_path/data_store`` avec deux bases (et des residus WAL au besoin)."""
    legacy = tmp_path / "data_store"
    legacy.mkdir()
    _creer_base(legacy / "registry.sqlite")
    _creer_base(legacy / "client.sqlite")
    if residus_wal:
        (legacy / "client.sqlite-wal").write_bytes(b"residu wal")
        (legacy / "client.sqlite-shm").write_bytes(b"residu shm")
    return legacy


def _fabrique(cible: Path) -> Callable[[], Path]:
    """Fabrique injectable retournant toujours ``cible`` (sans la creer)."""

    def interne() -> Path:
        return cible

    return interne


# Emplacements par defaut


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


# Detection du data_store herite


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


# Assistant de migration


def test_migration_sauvegarde_puis_deplace(tmp_path: Path) -> None:
    """La migration cree le zip de securite PUIS deplace les bases (legacy vide).

    Les residus ``-wal``/``-shm`` perimes sont absorbes par SQLite lors de la
    sauvegarde (ouverture de chaque base) : quoi qu'il arrive, le dossier
    herite ne contient plus AUCUN fichier SQLite apres migration.
    """
    legacy = _creer_legacy(tmp_path, residus_wal=True)
    cible = tmp_path / "appdata" / "data"

    deplaces = migrate_legacy_data(legacy, cible)

    # Liste retournee : les bases, triees (residus perimes purges par SQLite).
    assert deplaces == ["client.sqlite", "registry.sqlite"]
    # Cible peuplee, source videe (plus aucun fichier SQLite ni residu).
    for nom in deplaces:
        assert (cible / nom).is_file()
    assert list(legacy.glob("*.sqlite*")) == []
    # Sauvegarde zip de securite dans <cible>.parent/backups_migration.
    zips = sorted((tmp_path / "appdata" / "backups_migration").glob("SupplyScore_*.zip"))
    assert len(zips) == 1
    with zipfile.ZipFile(zips[0]) as archive:
        assert sorted(archive.namelist()) == ["client.sqlite", "registry.sqlite"]


def test_migration_deplace_les_residus_wal_restants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Les residus ``-wal``/``-shm`` encore presents apres sauvegarde sont deplaces.

    La vraie sauvegarde purge les residus perimes en ouvrant chaque base ; on
    la remplace ici par un enregistreur d'appel pour simuler des residus qui
    survivent (fichiers redeposes par le client de synchronisation cloud...).
    """
    legacy = _creer_legacy(tmp_path, residus_wal=True)
    cible = tmp_path / "appdata" / "data"
    appels: list[Path] = []

    def faux_backup(self: ServiceSauvegarde, dest_dir: Path) -> Path:
        appels.append(Path(dest_dir))
        return Path(dest_dir) / "SupplyScore_factice.zip"

    monkeypatch.setattr(ServiceSauvegarde, "backup_all", faux_backup)

    deplaces = migrate_legacy_data(legacy, cible)

    # La sauvegarde a bien ete demandee AVANT le deplacement, au bon endroit.
    assert appels == [tmp_path / "appdata" / "backups_migration"]
    # Bases triees, chacune suivie de ses residus encore presents.
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
    """Cible deja peuplee : refus en francais, rien n'est deplace ni sauvegarde."""
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
    """Aucune base dans le dossier herite : la sauvegarde prealable refuse."""
    legacy = tmp_path / "data_store"
    legacy.mkdir()
    with pytest.raises(FileNotFoundError):
        migrate_legacy_data(legacy, tmp_path / "cible")


def test_migration_bases_restent_lisibles(tmp_path: Path) -> None:
    """Les bases migrees restent des bases SQLite valides."""
    legacy = _creer_legacy(tmp_path)
    cible = tmp_path / "appdata" / "data"
    migrate_legacy_data(legacy, cible)
    conn = sqlite3.connect(str(cible / "client.sqlite"))
    try:
        assert conn.execute("SELECT x FROM t").fetchone() == (1,)
    finally:
        conn.close()


# Resolution du repertoire des bases (run_app.resolve_db_dir)


def test_resolve_a_db_dir_explicite_prioritaire(tmp_path: Path) -> None:
    """(a) ``--db-dir`` explicite : utilise tel quel, fabrique jamais appelee."""
    _creer_legacy(tmp_path)  # meme avec un data_store herite present

    def fabrique_interdite() -> Path:
        raise AssertionError("data_dir_factory ne doit pas être appelée en cas (a)")

    explicite = tmp_path / "ailleurs"
    resultat = resolve_db_dir(
        str(explicite), migrate=True, cwd=tmp_path, data_dir_factory=fabrique_interdite
    )
    assert resultat == explicite
    # Le data_store herite n'a pas ete touche.
    assert (tmp_path / "data_store" / "registry.sqlite").is_file()


def test_resolve_b_legacy_sans_flag_conserve_et_avertit(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """(b) sans ``--migrate-data`` : comportement historique + avertissement logge."""
    legacy = _creer_legacy(tmp_path)
    cible = tmp_path / "appdata" / "data"

    with caplog.at_level(logging.WARNING, logger="supplyscore"):
        resultat = resolve_db_dir(
            None, migrate=False, cwd=tmp_path, data_dir_factory=_fabrique(cible)
        )

    assert resultat == legacy
    assert (legacy / "registry.sqlite").is_file()  # rien n'a ete deplace
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
    """(c) ni --db-dir ni data_store herite : emplacement par defaut, cree."""
    cible = tmp_path / "appdata" / "data"
    resultat = resolve_db_dir(None, migrate=False, cwd=tmp_path, data_dir_factory=_fabrique(cible))
    assert resultat == cible
    assert cible.is_dir()


def test_resolve_c_flag_migration_sans_legacy_inoffensif(tmp_path: Path) -> None:
    """(c) ``--migrate-data`` sans data_store herite : simple emplacement par defaut."""
    cible = tmp_path / "appdata" / "data"
    resultat = resolve_db_dir(None, migrate=True, cwd=tmp_path, data_dir_factory=_fabrique(cible))
    assert resultat == cible
    assert cible.is_dir()
