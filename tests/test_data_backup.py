"""Tests du Lot 7.2 - sauvegarde/restauration manuelles des bases SQLite."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from supplyscore.core.clock import FixedClock
from supplyscore.data.backup import IntegriteError, ServiceSauvegarde, restore_backup
from supplyscore.services import SupplyScoreService

RACINE_PROJET = Path(__file__).resolve().parents[1]
T0 = 1_750_000_000.0


def _etats_urgence(svc: SupplyScoreService) -> dict[str, dict[str, float | None]]:
    """Capture champ a champ les UrgencyState de tous les noeuds du service."""
    etats: dict[str, dict[str, float | None]] = {}
    for node in svc.repo.nodes():
        u = node.urgency
        etats[node.id] = {
            "ud_local": u.ud_local,
            "ur_local": u.ur_local,
            "ud": u.ud,
            "ur": u.ur,
            "adequation": u.adequation,
            "false_urgency": u.false_urgency,
            "hidden_risk": u.hidden_risk,
            "timestamp": u.timestamp,
        }
    return etats


def _store_seede(tmp_path: Path) -> tuple[Path, Path]:
    """Cree un store seede puis ferme et sa sauvegarde : (store, zip_path)."""
    store = tmp_path / "store"
    with SupplyScoreService(db_dir=store, clock=FixedClock(T0)) as svc:
        svc.seed_demo(n_ranks=2, seed=1)
    zip_path = ServiceSauvegarde(store, clock=FixedClock(T0)).backup_all()
    return store, zip_path


# backup_all


def test_backup_all_bases_ouvertes(tmp_path):
    """Cycle complet : backup natif reussi alors que toutes les bases sont OUVERTES."""
    store = tmp_path / "store"
    svc = SupplyScoreService(db_dir=store, clock=FixedClock(T0))
    try:
        svc.seed_demo(n_ranks=2, seed=1)
        node_ids = [n.id for n in svc.repo.nodes()]
        assert node_ids, "le seed de démo doit produire des nœuds"
        # Les bases sont encore ouvertes (service non ferme) : le backup natif doit produire une copie coherente malgre les fichiers -wal/-shm.
        assert list(store.glob("*.sqlite-wal")), "WAL attendu tant que le service est ouvert"
        zip_path = ServiceSauvegarde(store, clock=FixedClock(T0)).backup_all()
    finally:
        svc.close()

    assert zip_path.is_file()
    assert zip_path.parent == store / "backups"
    assert re.fullmatch(r"SupplyScore_\d{8}_\d{6}\.zip", zip_path.name)
    with zipfile.ZipFile(zip_path) as archive:
        noms = set(archive.namelist())
    attendu = {"registry.sqlite"} | {f"{nid}.sqlite" for nid in node_ids}
    assert noms == attendu
    assert not any(nom.endswith(("-wal", "-shm")) for nom in noms)


def test_backup_refuse_base_corrompue(tmp_path):
    """Registre corrompu (octets nuls en tete) -> IntegriteError, aucun zip cree."""
    store = tmp_path / "store"
    with SupplyScoreService(db_dir=store, clock=FixedClock(T0)) as svc:
        svc.seed_demo(n_ranks=2, seed=1)
    with (store / "registry.sqlite").open("r+b") as f:
        f.write(b"\x00" * 256)

    sauvegarde = ServiceSauvegarde(store, clock=FixedClock(T0))
    with pytest.raises(IntegriteError, match="corrompue"):
        sauvegarde.backup_all()
    assert sauvegarde.list_backups() == []


def test_list_backups_tri_desc(tmp_path):
    """list_backups retourne les archives triees par nom decroissant."""
    store = tmp_path / "store"
    with SupplyScoreService(db_dir=store, clock=FixedClock(T0)) as svc:
        svc.seed_demo(n_ranks=2, seed=1)
    horloge = FixedClock(T0)
    sauvegarde = ServiceSauvegarde(store, clock=horloge)
    premier = sauvegarde.backup_all()
    horloge.set(T0 + 86_400.0)  # +1 jour : nom strictement superieur
    second = sauvegarde.backup_all()

    assert premier.name < second.name
    assert sauvegarde.list_backups() == [second, premier]


# restore_backup


def test_restore_repertoire_neuf_etats_identiques(tmp_path):
    """Backup -> restore sur repertoire neuf -> memes noeuds et UrgencyState champ a champ."""
    store = tmp_path / "store"
    svc = SupplyScoreService(db_dir=store, clock=FixedClock(T0))
    svc.seed_demo(n_ranks=2, seed=1)
    attendu = _etats_urgence(svc)
    zip_path = ServiceSauvegarde(store, clock=FixedClock(T0)).backup_all()
    svc.close()

    neuf = tmp_path / "restored"
    restaurees = restore_backup(zip_path, neuf)
    assert "registry.sqlite" in restaurees
    assert len(restaurees) == 1 + len(attendu)
    assert sorted(restaurees) == sorted(p.name for p in neuf.glob("*.sqlite"))

    with SupplyScoreService(db_dir=neuf, clock=FixedClock(T0)) as svc2:
        svc2.load_graph_from_registry()
        obtenu = _etats_urgence(svc2)
    assert obtenu == attendu


def test_restore_sans_force_refuse_repertoire_occupe(tmp_path):
    """db_dir occupe sans force -> FileExistsError mentionnant --force, rien touche."""
    _, zip_path = _store_seede(tmp_path)
    occupe = tmp_path / "occupe"
    occupe.mkdir()
    ancienne = occupe / "ancienne.sqlite"
    ancienne.write_bytes(b"contenu d'avant restauration")

    with pytest.raises(FileExistsError, match="--force"):
        restore_backup(zip_path, occupe)
    assert ancienne.read_bytes() == b"contenu d'avant restauration"
    assert list(occupe.glob("avant_restauration_*")) == []


def test_restore_force_met_les_bases_a_l_abri(tmp_path):
    """Avec force : anciennes bases deplacees dans avant_restauration_*, nouvelles en place."""
    _, zip_path = _store_seede(tmp_path)
    occupe = tmp_path / "occupe"
    occupe.mkdir()
    ancienne = occupe / "ancienne.sqlite"
    ancienne.write_bytes(b"contenu d'avant restauration")

    restaurees = restore_backup(zip_path, occupe, force=True)

    assert (occupe / "registry.sqlite").is_file()
    assert not ancienne.exists(), "l'ancienne base doit avoir été déplacée, pas écrasée"
    abris = list(occupe.glob("avant_restauration_*"))
    assert len(abris) == 1
    assert (abris[0] / "ancienne.sqlite").read_bytes() == b"contenu d'avant restauration"
    assert sorted(restaurees) == sorted(p.name for p in occupe.glob("*.sqlite"))


def test_restore_zip_inexistant(tmp_path):
    """Archive absente -> FileNotFoundError avec message francais."""
    with pytest.raises(FileNotFoundError, match="introuvable"):
        restore_backup(tmp_path / "absente.zip", tmp_path / "cible")


# CLI python -m supplyscore.tools.restore


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Lance ``python -m supplyscore.tools.restore`` et capture la sortie en UTF-8."""
    env = {**os.environ, "PYTHONUTF8": "1"}
    return subprocess.run(
        [sys.executable, "-m", "supplyscore.tools.restore", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=RACINE_PROJET,
        env=env,
    )


def test_cli_restore_ok(tmp_path):
    """Restauration via le module executable : code retour 0 et liste affichee."""
    _, zip_path = _store_seede(tmp_path)
    cible = tmp_path / "cible_cli"

    resultat = _run_cli(str(zip_path), "--db-dir", str(cible))

    assert resultat.returncode == 0, resultat.stderr
    assert "registry.sqlite" in resultat.stdout
    assert (cible / "registry.sqlite").is_file()


def test_cli_zip_inexistant(tmp_path):
    """Archive inexistante : code retour 1 et message d'erreur francais."""
    resultat = _run_cli(str(tmp_path / "absente.zip"), "--db-dir", str(tmp_path / "cible"))

    assert resultat.returncode == 1
    assert "Erreur" in resultat.stderr
    assert "introuvable" in resultat.stderr
