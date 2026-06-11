"""Tests du Lot 17.2 — sauvegarde automatique avec rétention (FixedClock pilotée).

Couvre :meth:`ServiceSauvegarde.backup_si_obsolete` (création si absente ou
trop vieille, fraîcheur lue dans le NOM du zip, noms inattendus ignorés),
:meth:`ServiceSauvegarde.appliquer_retention` (suppression des plus anciennes
au-delà du quota, ``garder >= 1``), :meth:`ServiceSauvegarde.backup_auto`
(enchaînement des deux, IntegriteError remonte) et la carte « Exporter &
sauvegarder » de la page Projets (liste des dernières sauvegardes).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from supplyscore.core.clock import FixedClock
from supplyscore.data.backup import (
    RETENTION_DEFAUT,
    IntegriteError,
    ServiceSauvegarde,
)
from supplyscore.services import SupplyScoreService
from supplyscore.web_ui import set_service
from supplyscore.web_ui.pages import projects

#: Mercredi 2026-06-10 12:00 locale — epoch ENTIER : le nom du zip (résolution
#: à la seconde) se re-parse exactement sur cet instant.
_DEBUT = datetime(2026, 6, 10, 12, 0)
T0 = float(int(_DEBUT.timestamp()))
HEURE = 3600.0


def _store_minimal(tmp_path: Path) -> Path:
    """Crée un répertoire de données contenant une petite base SQLite valide."""
    store = tmp_path / "store"
    store.mkdir()
    conn = sqlite3.connect(str(store / "registry.sqlite"))
    try:
        conn.execute("CREATE TABLE marqueur (x INTEGER)")
        conn.commit()
    finally:
        conn.close()
    return store


def _zips_factices(dest: Path, n: int, debut: datetime = _DEBUT) -> list[Path]:
    """Crée ``n`` zips factices horodatés d'heure en heure, du plus ancien au plus récent."""
    dest.mkdir(parents=True, exist_ok=True)
    chemins: list[Path] = []
    for i in range(n):
        quand = debut + timedelta(hours=i)
        chemin = dest / f"SupplyScore_{quand.strftime('%Y%m%d_%H%M%S')}.zip"
        chemin.write_bytes(b"factice")
        chemins.append(chemin)
    return chemins


# --- backup_si_obsolete -----------------------------------------------------------------


def test_si_obsolete_sans_sauvegarde_cree(tmp_path):
    """Aucune archive existante -> une sauvegarde est créée immédiatement."""
    store = _store_minimal(tmp_path)
    sauvegarde = ServiceSauvegarde(store, clock=FixedClock(T0))

    cree = sauvegarde.backup_si_obsolete(max_age_h=24.0)

    assert cree is not None and cree.is_file()
    assert sauvegarde.list_backups() == [cree]


def test_si_obsolete_sauvegarde_fraiche_ne_cree_rien(tmp_path):
    """Archive du même instant (horloge figée) -> None, rien de nouveau."""
    store = _store_minimal(tmp_path)
    sauvegarde = ServiceSauvegarde(store, clock=FixedClock(T0))
    premier = sauvegarde.backup_all()

    assert sauvegarde.backup_si_obsolete(max_age_h=24.0) is None
    assert sauvegarde.list_backups() == [premier]


def test_si_obsolete_apres_25h_cree(tmp_path):
    """Horloge avancée de 25 h (> 24 h) -> une nouvelle archive est créée."""
    store = _store_minimal(tmp_path)
    horloge = FixedClock(T0)
    sauvegarde = ServiceSauvegarde(store, clock=horloge)
    premier = sauvegarde.backup_all()

    horloge.set(T0 + 25 * HEURE)
    second = sauvegarde.backup_si_obsolete(max_age_h=24.0)

    assert second is not None and second != premier
    assert sauvegarde.list_backups() == [second, premier]


def test_si_obsolete_age_limite_ne_cree_rien(tmp_path):
    """Âge EXACTEMENT égal à max_age_h -> pas obsolète (strictement plus vieux exigé)."""
    store = _store_minimal(tmp_path)
    horloge = FixedClock(T0)
    sauvegarde = ServiceSauvegarde(store, clock=horloge)
    sauvegarde.backup_all()

    horloge.set(T0 + 24 * HEURE)
    assert sauvegarde.backup_si_obsolete(max_age_h=24.0) is None


def test_si_obsolete_ignore_noms_inattendus(tmp_path):
    """Fichiers au nom non conforme -> ignorés pour l'âge : la sauvegarde est créée."""
    store = _store_minimal(tmp_path)
    backups = store / "backups"
    backups.mkdir()
    # Nom hors motif ET nom au motif correct mais à la date calendaire invalide.
    (backups / "SupplyScore_notes.zip").write_bytes(b"hors motif")
    (backups / "SupplyScore_20269999_999999.zip").write_bytes(b"date invalide")
    sauvegarde = ServiceSauvegarde(store, clock=FixedClock(T0))

    cree = sauvegarde.backup_si_obsolete(max_age_h=24.0)

    assert cree is not None and cree.is_file()


# --- appliquer_retention ----------------------------------------------------------------


def test_retention_garde_les_20_plus_recentes(tmp_path):
    """25 zips factices -> les 5 plus anciens supprimés et retournés, 20 conservés."""
    store = _store_minimal(tmp_path)
    chemins = _zips_factices(store / "backups", 25)
    sauvegarde = ServiceSauvegarde(store, clock=FixedClock(T0))

    supprimees = sauvegarde.appliquer_retention(garder=RETENTION_DEFAUT)

    # Retournées du plus récent au plus ancien parmi les 5 supprimées.
    assert supprimees == list(reversed(chemins[:5]))
    assert not any(p.exists() for p in supprimees)
    assert sauvegarde.list_backups() == list(reversed(chemins[5:]))


def test_retention_sous_le_quota_ne_supprime_rien(tmp_path):
    """Moins d'archives que le quota -> aucune suppression, liste vide."""
    store = _store_minimal(tmp_path)
    chemins = _zips_factices(store / "backups", 3)
    sauvegarde = ServiceSauvegarde(store, clock=FixedClock(T0))

    assert sauvegarde.appliquer_retention(garder=RETENTION_DEFAUT) == []
    assert all(p.exists() for p in chemins)


def test_retention_ignore_noms_inattendus(tmp_path):
    """Les fichiers au nom non conforme ne sont NI comptés NI supprimés."""
    store = _store_minimal(tmp_path)
    chemins = _zips_factices(store / "backups", 3)
    intrus = store / "backups" / "SupplyScore_notes.zip"
    intrus.write_bytes(b"hors motif")
    sauvegarde = ServiceSauvegarde(store, clock=FixedClock(T0))

    supprimees = sauvegarde.appliquer_retention(garder=1)

    assert supprimees == [chemins[1], chemins[0]]
    assert intrus.exists(), "un nom inattendu ne doit jamais être supprimé"
    assert chemins[2].exists()


def test_retention_garder_invalide(tmp_path):
    """garder = 0 -> ValueError, aucune archive touchée."""
    store = _store_minimal(tmp_path)
    chemins = _zips_factices(store / "backups", 2)
    sauvegarde = ServiceSauvegarde(store, clock=FixedClock(T0))

    with pytest.raises(ValueError, match="garder"):
        sauvegarde.appliquer_retention(garder=0)
    assert all(p.exists() for p in chemins)


# --- backup_auto ------------------------------------------------------------------------


def test_backup_auto_enchaine_creation_et_retention(tmp_path):
    """backup_auto crée l'archive manquante PUIS ramène le stock au quota."""
    store = _store_minimal(tmp_path)
    chemins = _zips_factices(store / "backups", RETENTION_DEFAUT)  # 20 anciennes
    horloge = FixedClock(T0 + 48 * HEURE)  # la plus récente a 29 h -> obsolète
    sauvegarde = ServiceSauvegarde(store, clock=horloge)

    cree = sauvegarde.backup_auto(max_age_h=24.0, garder=RETENTION_DEFAUT)

    assert cree is not None and cree.is_file()
    restantes = sauvegarde.list_backups()
    assert len(restantes) == RETENTION_DEFAUT
    assert restantes[0] == cree
    assert not chemins[0].exists(), "la plus ancienne doit avoir été supprimée"
    # Second appel immédiat : archive fraîche -> None, stock inchangé.
    assert sauvegarde.backup_auto(max_age_h=24.0, garder=RETENTION_DEFAUT) is None
    assert sauvegarde.list_backups() == restantes


def test_backup_auto_garder_invalide_ne_cree_rien(tmp_path):
    """garder = 0 -> ValueError AVANT toute création d'archive."""
    store = _store_minimal(tmp_path)
    sauvegarde = ServiceSauvegarde(store, clock=FixedClock(T0))

    with pytest.raises(ValueError, match="garder"):
        sauvegarde.backup_auto(garder=0)
    assert sauvegarde.list_backups() == []


def test_backup_auto_integrite_remonte(tmp_path):
    """Base corrompue -> IntegriteError REMONTE, aucune archive créée."""
    store = _store_minimal(tmp_path)
    with (store / "registry.sqlite").open("r+b") as f:
        f.write(b"\x00" * 256)
    sauvegarde = ServiceSauvegarde(store, clock=FixedClock(T0))

    with pytest.raises(IntegriteError, match="corrompue"):
        sauvegarde.backup_auto()
    assert sauvegarde.list_backups() == []


# --- carte « Exporter & sauvegarder » de la page Projets ---------------------------------


@pytest.fixture
def service_web(tmp_path):
    """Service web partagé par les callbacks de la page Projets (horloge figée)."""
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(T0))
    set_service(svc)
    yield svc
    set_service(None)
    svc.close()


def test_carte_projets_liste_vide_avant_sauvegarde(service_web):
    """Sans archive, la carte affiche une invitation française claire."""
    rendu = str(projects.backup_list_callback(0))
    assert "Dernières sauvegardes" in rendu
    assert "aucune pour l'instant" in rendu


def test_carte_projets_liste_les_sauvegardes(service_web):
    """Après le bouton « Sauvegarder », la liste contient le nom du zip et sa taille."""
    msg, refresh = projects.backup_now_callback(1, 0)
    texte_msg = str(msg)
    assert "Sauvegarde créée" in texte_msg
    assert f"(rétention : {RETENTION_DEFAUT})" in texte_msg
    assert refresh == 1

    zips = ServiceSauvegarde(service_web.db_dir).list_backups()
    assert len(zips) == 1
    rendu = str(projects.backup_list_callback(refresh))
    assert "Dernières sauvegardes" in rendu
    assert zips[0].name in rendu
    assert "Ko" in rendu


def test_carte_projets_liste_limitee_a_trois(service_web):
    """Seules les 3 archives les plus récentes apparaissent dans la carte."""
    horloge = FixedClock(T0)
    sauvegarde = ServiceSauvegarde(service_web.db_dir, clock=horloge)
    zips = []
    for i in range(4):
        horloge.set(T0 + i * HEURE)
        zips.append(sauvegarde.backup_all())

    rendu = str(projects.backup_list_callback(1))
    assert zips[0].name not in rendu, "la plus ancienne ne doit plus être affichée"
    assert all(z.name in rendu for z in zips[1:])


def test_layout_contient_la_liste_et_la_retention(service_web):
    """Le layout expose le Div backup-list et mentionne la rétention dans la carte."""
    texte = str(projects.layout())
    assert "backup-list" in texte
    assert f"rétention : {RETENTION_DEFAUT} archives" in texte


def test_taille_lisible_ko_et_mo():
    """Formatage français des tailles : Ko entiers, Mo à une décimale (virgule)."""
    assert projects._taille_lisible(512) == "1 Ko"
    assert projects._taille_lisible(10 * 1024) == "10 Ko"
    assert projects._taille_lisible(int(2.5 * 1024 * 1024)) == "2,5 Mo"
