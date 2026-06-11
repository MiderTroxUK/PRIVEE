"""Sauvegarde et restauration des bases SQLite de supplyscore (Lots 7.2 et 17.2).

Objectif : protéger les données du serious game. La sauvegarde s'appuie sur
l'API native :meth:`sqlite3.Connection.backup`, qui produit une copie COHÉRENTE
même si la base est ouverte ailleurs (serveur web en cours d'exécution), puis
archive toutes les copies dans un zip horodaté
``SupplyScore_AAAAMMJJ_HHMMSS.zip``.

Le Lot 17.2 ajoute la sauvegarde AUTOMATIQUE avec rétention :
:meth:`ServiceSauvegarde.backup_auto` (API unique pour le démarrage de
l'application) crée une archive si la plus récente est trop vieille
(:meth:`~ServiceSauvegarde.backup_si_obsolete`) puis supprime les archives les
plus anciennes au-delà du quota (:meth:`~ServiceSauvegarde.appliquer_retention`,
:data:`RETENTION_DEFAUT` archives conservées par défaut).

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

import re
import shutil
import sqlite3
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

from supplyscore.core.clock import Clock, SystemClock

#: Nombre d'archives conservées par défaut par la rétention (Lot 17.2).
RETENTION_DEFAUT: int = 20

#: Motif STRICT du nom d'archive produit par :meth:`ServiceSauvegarde.backup_all`.
_MOTIF_NOM_ARCHIVE = re.compile(r"SupplyScore_(\d{8}_\d{6})\.zip")


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


def _ts_depuis_nom(path: Path) -> float | None:
    """Extrait l'epoch local du nom d'une archive ``SupplyScore_AAAAMMJJ_HHMMSS.zip``.

    Le parse est ROBUSTE : le nom doit correspondre exactement au motif produit
    par :meth:`ServiceSauvegarde.backup_all` ET porter une date calendaire
    valide (« SupplyScore_20269999_999999.zip » est rejeté). Les fichiers au
    nom inattendu retournent ``None`` et sont ignorés PARTOUT par la mécanique
    automatique du Lot 17.2 : ni pris en compte pour l'âge de la dernière
    sauvegarde, ni comptés ni supprimés par la rétention.

    Args:
        path: chemin (ou nom) d'une archive candidate.

    Returns:
        L'instant d'archivage en secondes epoch (heure locale du poste), ou
        ``None`` si le nom ne suit pas le format attendu.
    """
    match = _MOTIF_NOM_ARCHIVE.fullmatch(path.name)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d_%H%M%S").timestamp()
    except ValueError:
        return None


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

    def backup_si_obsolete(
        self, max_age_h: float = 24.0, dest_dir: Path | str | None = None
    ) -> Path | None:
        """Crée une sauvegarde si la plus récente est trop vieille (ou absente).

        L'âge se lit dans le NOM des archives (``SupplyScore_AAAAMMJJ_HHMMSS.zip``),
        comparé à l'horloge du service : si la plus récente a STRICTEMENT plus
        de ``max_age_h`` heures — ou s'il n'existe aucune archive au nom
        conforme — :meth:`backup_all` est appelé. Les fichiers au nom inattendu
        sont ignorés (voir :func:`_ts_depuis_nom`).

        Args:
            max_age_h: âge maximal toléré de la dernière sauvegarde, en heures.
            dest_dir: répertoire des archives ; ``db_dir/backups`` par défaut.

        Returns:
            Le chemin du zip créé, ou ``None`` si la dernière sauvegarde est
            encore assez fraîche.

        Raises:
            FileNotFoundError: si aucune base ``*.sqlite`` n'existe dans ``db_dir``.
            IntegriteError: si une base est corrompue — rien n'est alors archivé.
        """
        horodatees = self._archives_horodatees(dest_dir)
        if horodatees:
            age_h = (self.clock.now() - horodatees[0][1]) / 3600.0
            if age_h <= max_age_h:
                return None
        return self.backup_all(dest_dir)

    def appliquer_retention(
        self, garder: int = RETENTION_DEFAUT, dest_dir: Path | str | None = None
    ) -> list[Path]:
        """Supprime les archives les PLUS ANCIENNES au-delà du quota ``garder``.

        Seules les archives au nom conforme ``SupplyScore_AAAAMMJJ_HHMMSS.zip``
        participent à la rétention — les fichiers au nom inattendu ne sont ni
        comptés ni supprimés (voir :func:`_ts_depuis_nom`). L'ancienneté est
        celle de l'horodatage porté par le nom.

        Args:
            garder: nombre d'archives à conserver, >= 1.
            dest_dir: répertoire des archives ; ``db_dir/backups`` par défaut.

        Returns:
            Les chemins supprimés, du plus récent au plus ancien (liste vide si
            le quota n'est pas dépassé).

        Raises:
            ValueError: si ``garder`` est inférieur à 1.
        """
        if garder < 1:
            raise ValueError(f"garder doit être >= 1, reçu {garder}")
        horodatees = self._archives_horodatees(dest_dir)
        supprimees = [path for path, _ts in horodatees[garder:]]
        for path in supprimees:
            path.unlink()
        return supprimees

    def backup_auto(
        self,
        max_age_h: float = 24.0,
        garder: int = RETENTION_DEFAUT,
        dest_dir: Path | str | None = None,
    ) -> Path | None:
        """Sauvegarde automatique : crée si obsolète PUIS applique la rétention.

        API UNIQUE destinée au démarrage de l'application (Lot 17.1 y branche
        l'appel) : enchaîne :meth:`backup_si_obsolete` puis
        :meth:`appliquer_retention`. ``garder`` est validé AVANT toute
        création d'archive.

        Args:
            max_age_h: âge maximal toléré de la dernière sauvegarde, en heures.
            garder: nombre d'archives à conserver après rétention, >= 1.
            dest_dir: répertoire des archives ; ``db_dir/backups`` par défaut.

        Returns:
            Le chemin du zip créé, ou ``None`` si aucune sauvegarde n'était
            nécessaire.

        Raises:
            ValueError: si ``garder`` est inférieur à 1 (aucune archive créée).
            FileNotFoundError: si aucune base ``*.sqlite`` n'existe dans ``db_dir``.
            IntegriteError: si une base est corrompue — rien n'est alors archivé.
        """
        if garder < 1:
            raise ValueError(f"garder doit être >= 1, reçu {garder}")
        cree = self.backup_si_obsolete(max_age_h=max_age_h, dest_dir=dest_dir)
        self.appliquer_retention(garder=garder, dest_dir=dest_dir)
        return cree

    def _archives_horodatees(self, dest_dir: Path | str | None) -> list[tuple[Path, float]]:
        """Archives au nom conforme et leur epoch, de la plus récente à la plus ancienne.

        Args:
            dest_dir: répertoire des archives ; ``db_dir/backups`` par défaut.

        Returns:
            Couples ``(chemin, epoch)`` triés par horodatage décroissant ; les
            fichiers au nom inattendu sont exclus (voir :func:`_ts_depuis_nom`).
        """
        couples: list[tuple[Path, float]] = []
        for path in self.list_backups(dest_dir):
            ts = _ts_depuis_nom(path)
            if ts is not None:
                couples.append((path, ts))
        couples.sort(key=lambda couple: couple[1], reverse=True)
        return couples

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
