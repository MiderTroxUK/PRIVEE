"""Journalisation applicative de SupplyScore.

Configure le logger racine ``supplyscore`` avec un handler fichier rotatif
(``logs/supplyscore.log``, 5 × 2 Mo) et un handler console, au format
horodaté français. L'appel de :func:`configure_logging` est idempotent :
le rappeler remplace les handlers gérés par ce module sans les dupliquer.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

#: Format des lignes de log (niveau aligné sur 8 caractères).
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
#: Format de date français (jour/mois/année).
DATE_FORMAT = "%d/%m/%Y %H:%M:%S"
#: Nom du fichier de log applicatif.
LOG_FILENAME = "supplyscore.log"
#: Taille maximale d'un fichier de log avant rotation (2 Mo).
MAX_BYTES = 2_000_000
#: Nombre de fichiers de sauvegarde conservés lors des rotations.
BACKUP_COUNT = 5

#: Attribut marquant les handlers posés par ce module (idempotence).
_MANAGED_FLAG = "_supplyscore_managed"


def configure_logging(level: str = "INFO", log_dir: Path | str = "logs") -> logging.Logger:
    """Configure le logger racine ``supplyscore`` (fichier rotatif + console).

    Crée le dossier ``log_dir`` au besoin, puis attache au logger
    ``supplyscore`` un :class:`~logging.handlers.RotatingFileHandler`
    (``supplyscore.log``, 2 Mo, 5 sauvegardes, UTF-8) et un handler console.
    La fonction est idempotente : un nouvel appel remplace les handlers
    posés par un appel précédent au lieu de les dupliquer.

    Args:
        level: Niveau de journalisation (``"DEBUG"``, ``"INFO"``, ...),
            insensible à la casse.
        log_dir: Dossier des fichiers de log, créé s'il n'existe pas.

    Returns:
        Le logger ``supplyscore`` configuré.

    Raises:
        ValueError: si ``level`` n'est pas un niveau de logging connu.
    """
    logger = logging.getLogger("supplyscore")
    logger.setLevel(level.upper())

    # Idempotence : on retire (et ferme) les handlers posés par un appel
    # précédent, sans toucher aux handlers étrangers éventuels.
    for handler in list(logger.handlers):
        if getattr(handler, _MANAGED_FLAG, False):
            logger.removeHandler(handler)
            handler.close()

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    file_handler = RotatingFileHandler(
        log_path / LOG_FILENAME,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    for handler in (file_handler, console_handler):
        setattr(handler, _MANAGED_FLAG, True)
        logger.addHandler(handler)

    return logger
