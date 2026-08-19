"""Tests in-process du CLI de restauration (couverture E9 - le subprocess est aveugle)."""

import pytest

from supplyscore.core.clock import FixedClock
from supplyscore.data.backup import ServiceSauvegarde
from supplyscore.services import SupplyScoreService
from supplyscore.tools.restore import build_parser, main

T0 = 1_750_000_000.0


@pytest.fixture
def backup_zip(tmp_path):
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(T0))
    try:
        svc.seed_demo(n_ranks=1, seed=2)
        return ServiceSauvegarde(svc.db_dir, clock=svc.clock).backup_all()
    finally:
        svc.close()


def test_main_restaure_avec_succes(backup_zip, tmp_path, capsys):
    cible = tmp_path / "cible"
    code = main([str(backup_zip), "--db-dir", str(cible)])
    assert code == 0
    sortie = capsys.readouterr().out
    assert "restaurée" in sortie
    assert (cible / "registry.sqlite").exists()


def test_main_zip_inexistant(tmp_path, capsys):
    code = main([str(tmp_path / "absent.zip"), "--db-dir", str(tmp_path / "cible")])
    assert code == 1
    assert "Erreur" in capsys.readouterr().err


def test_main_refuse_repertoire_occupe_sans_force(backup_zip, tmp_path, capsys):
    cible = tmp_path / "cible"
    assert main([str(backup_zip), "--db-dir", str(cible)]) == 0
    # second passage sans --force : refus francais
    assert main([str(backup_zip), "--db-dir", str(cible)]) == 1
    assert "force" in capsys.readouterr().err.lower()
    # avec --force : les anciennes bases sont mises a l'abri
    assert main([str(backup_zip), "--db-dir", str(cible), "--force"]) == 0
    abris = list(cible.glob("avant_restauration_*"))
    assert abris, "les bases existantes doivent être déplacées, jamais détruites"


def test_build_parser_defauts():
    args = build_parser().parse_args(["archive.zip"])
    assert args.db_dir == "data_store"
    assert args.force is False
