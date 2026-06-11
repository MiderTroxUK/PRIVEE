"""Sauvegarde et restauration manuelles des bases SQLite de supplyscore (Lot 7.2).

Objectif : protéger les données du serious game. La sauvegarde s'appuie sur
l'API native :meth:`sqlite3.Connection.backup`, qui produit une copie COHÉRENTE
même si la base est ouverte ailleurs (serveur web en cours d'exécution), puis
archive toutes les copies dans un zip horodaté
``SupplyScore_AAAAMMJJ_HHMMSS.zip``.

Garde-fous :

- ``PRAGMA integrity_check`` sur CHAQUE base avant archivage — une base
  corrompue lève :class:`IntegriteError` et RIEN n'est archivé ;
- à la restauration, les bases déjà présentes ne sont JAMAIS détruites : avec
  ``force=True`` elles sont déplacées dans
  ``avant_restauration_AAAAMMJJ_HHMMSS/`` ;
- les fichiers ``-wal``/``-shm`` ne sont pas archivés : le backup natif absorbe
  leur contenu dans la copie.

Restauration en ligne de commande : ``python -m supplyscore.tools.restore``.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

from supplyscore.core.clock import Clock, SystemClock


class IntegriteError(Exception):
    """Base SQLite corrompue détectée (avant archivage ou après restauration)."""


def _horodatage(ts: float) -> str:
    """Formate un epoch en horodatage local compact « AAAAMMJJ_HHMMSS ».

    Args:
        ts: instant en secondes epoch.

    Returns:
        Libellé « AAAAMMJJ_HHMMSS » en heure locale du poste.
    """
    return datetime.fromtimestamp(ts).strftime("%Y%m%d_%H%M%S")


def _exiger_integrite(conn: sqlite3.Connection, message: str) -> None:
    """Lève :class:`IntegriteError` si ``PRAGMA integrity_check`` ne répond pas « ok ».

    Args:
        conn: connexion ouverte sur la base à vérifier.
        message: début du message d'erreur (français) ; le détail SQLite y est
            ajouté entre parenthèses.

    Raises:
        IntegriteError: si la vérification échoue ou si le fichier n'est pas
            une base SQLite lisible.
    """
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.DatabaseError as exc:
        raise IntegriteError(f"{message} ({exc})") from exc
    resultat = "" if row is None else str(row[0])
    if resultat != "ok":
        raise IntegriteError(f"{message} (integrity_check : {resultat})")


class ServiceSauvegarde:
    """Sauvegarde manuelle des bases SQLite d'un répertoire de données.

    Archive le registre (``registry.sqlite``) et toutes les bases client
    (``<client_id>.sqlite``) dans un zip horodaté, via des copies cohérentes
    produites par l'API native :meth:`sqlite3.Connection.backup` — la copie
    est sûre même si l'application tient les bases ouvertes.
    """

    def __init__(self, db_dir: Path | str, clock: Clock | None = None) -> None:
        """Initialise le service de sauvegarde.

        Args:
            db_dir: répertoire contenant les bases SQLite (``data_store``...).
            clock: source de temps pour horodater les archives (heure locale) ;
                :class:`SystemClock` par défaut.
        """
        self.db_dir = Path(db_dir)
        self.clock: Clock = clock if clock is not None else SystemClock()

    def backup_all(self, dest_dir: Path | str | None = None) -> Path:
        """Archive toutes les bases ``*.sqlite`` de ``db_dir`` dans un zip horodaté.

        Chaque base est d'abord vérifiée (``PRAGMA integrity_check``) puis
        copiée via :meth:`sqlite3.Connection.backup` vers un fichier
        temporaire ; les copies sont ensuite zippées et les temporaires
        nettoyés. Les fichiers ``-wal``/``-shm`` ne sont pas archivés (le
        backup natif absorbe leur contenu).

        Args:
            dest_dir: répertoire de dépôt du zip (créé au besoin) ;
                ``db_dir/backups`` par défaut.

        Returns:
            Chemin du zip ``SupplyScore_AAAAMMJJ_HHMMSS.zip`` créé.

        Raises:
            FileNotFoundError: si aucune base ``*.sqlite`` n'existe dans ``db_dir``.
            IntegriteError: si une base est corrompue — rien n'est alors archivé.
        """
        sources = sorted(p for p in self.db_dir.glob("*.sqlite") if p.is_file())
        if not sources:
            raise FileNotFoundError(f"Aucune base *.sqlite à sauvegarder dans {self.db_dir}.")
        dest = Path(dest_dir) if dest_dir is not None else self.db_dir / "backups"
        zip_name = f"SupplyScore_{_horodatage(self.clock.now())}.zip"
        with tempfile.TemporaryDirectory(prefix="supplyscore_backup_") as tmp:
            tmp_dir = Path(tmp)
            copies = [self._copier_coherent(source, tmp_dir / source.name) for source in sources]
            dest.mkdir(parents=True, exist_ok=True)
            zip_path = dest / zip_name
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for copie in copies:
                    archive.write(copie, arcname=copie.name)
        return zip_path

    def list_backups(self, dest_dir: Path | str | None = None) -> list[Path]:
        """Liste les archives de sauvegarde présentes, les plus récentes d'abord.

        Args:
            dest_dir: répertoire des archives ; ``db_dir/backups`` par défaut.

        Returns:
            Chemins des ``SupplyScore_*.zip`` triés par nom décroissant (l'ordre
            lexicographique des horodatages coïncide avec l'ordre chronologique).
            Liste vide si le répertoire n'existe pas.
        """
        dest = Path(dest_dir) if dest_dir is not None else self.db_dir / "backups"
        if not dest.is_dir():
            return []
        return sorted(
            (p for p in dest.glob("SupplyScore_*.zip") if p.is_file()),
            key=lambda p: p.name,
            reverse=True,
        )

    @staticmethod
    def _copier_coherent(source_path: Path, copie_path: Path) -> Path:
        """Vérifie l'intégrité d'une base puis la copie via le backup natif SQLite.

        Args:
            source_path: base SQLite source (peut être ouverte par ailleurs).
            copie_path: chemin du fichier de copie à produire.

        Returns:
            ``copie_path``, une fois la copie cohérente écrite.

        Raises:
            IntegriteError: si la base source échoue ``PRAGMA integrity_check``
                (aucune copie n'est alors produite).
        """
        source = sqlite3.connect(str(source_path))
        try:
            _exiger_integrite(source, f"Base corrompue détectée avant archivage : {source_path}")
            copie = sqlite3.connect(str(copie_path))
            try:
                source.backup(copie)
            finally:
                copie.close()
        finally:
            source.close()
        return copie_path


def restore_backup(zip_path: Path | str, db_dir: Path | str, *, force: bool = False) -> list[str]:
    """Restaure les bases SQLite d'une archive de sauvegarde dans ``db_dir``.

    Les bases déjà présentes ne sont jamais détruites : sans ``force`` la
    restauration est refusée ; avec ``force=True`` elles sont d'abord déplacées
    (avec leurs résidus ``-wal``/``-shm``/``-journal``) dans
    ``db_dir/avant_restauration_AAAAMMJJ_HHMMSS/``. Chaque base restaurée est
    vérifiée par ``PRAGMA integrity_check``.

    Args:
        zip_path: archive ``SupplyScore_*.zip`` produite par
            :meth:`ServiceSauvegarde.backup_all`.
        db_dir: répertoire cible des bases (créé au besoin).
        force: autorise la restauration par-dessus des bases existantes.

    Returns:
        Noms des fichiers de base restaurés, dans l'ordre de l'archive.

    Raises:
        FileNotFoundError: si l'archive n'existe pas.
        ValueError: si l'archive ne contient aucune base ``*.sqlite``.
        FileExistsError: si ``db_dir`` contient déjà des bases et que ``force``
            est faux.
        IntegriteError: si une base restaurée échoue ``PRAGMA integrity_check``.
    """
    archive_path = Path(zip_path)
    cible_dir = Path(db_dir)
    if not archive_path.is_file():
        raise FileNotFoundError(f"Archive de sauvegarde introuvable : {archive_path}")
    with zipfile.ZipFile(archive_path) as archive:
        membres = [nom for nom in archive.namelist() if nom.endswith(".sqlite")]
        if not membres:
            raise ValueError(f"Aucune base *.sqlite dans l'archive {archive_path}.")
        cible_dir.mkdir(parents=True, exist_ok=True)
        existantes = sorted(p for p in cible_dir.glob("*.sqlite") if p.is_file())
        if existantes and not force:
            raise FileExistsError(
                f"Le répertoire {cible_dir} contient déjà {len(existantes)} base(s) SQLite : "
                "utilisez --force pour les mettre à l'abri (avant_restauration_*) "
                "avant la restauration."
            )
        if existantes:
            _mettre_a_l_abri(cible_dir, existantes)
        restaurees: list[str] = []
        for membre in membres:
            nom = Path(membre).name  # neutralise tout chemin embarqué dans l'archive
            destination = cible_dir / nom
            with archive.open(membre) as flux, destination.open("wb") as sortie:
                shutil.copyfileobj(flux, sortie)
            restaurees.append(nom)
    for nom in restaurees:
        conn = sqlite3.connect(str(cible_dir / nom))
        try:
            _exiger_integrite(conn, f"Base corrompue après restauration : {cible_dir / nom}")
        finally:
            conn.close()
    return restaurees


def _mettre_a_l_abri(cible_dir: Path, bases: list[Path]) -> None:
    """Déplace les bases existantes (et leurs résidus WAL) hors du répertoire cible.

    Les fichiers sont déplacés — jamais détruits — dans un sous-répertoire
    ``avant_restauration_AAAAMMJJ_HHMMSS/`` daté de l'heure locale courante.

    Args:
        cible_dir: répertoire contenant les bases à mettre à l'abri.
        bases: bases ``*.sqlite`` à déplacer (leurs éventuels fichiers
            ``-wal``/``-shm``/``-journal`` suivent).
    """
    abri = cible_dir / f"avant_restauration_{_horodatage(time.time())}"
    abri.mkdir(parents=True, exist_ok=True)
    for base in bases:
        annexes = [base.with_name(base.name + suffixe) for suffixe in ("-wal", "-shm", "-journal")]
        for fichier in [base, *annexes]:
            if fichier.is_file():
                shutil.move(str(fichier), str(abri / fichier.name))
