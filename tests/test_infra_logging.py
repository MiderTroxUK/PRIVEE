"""Tests de la journalisation applicative (``supplyscore.infra.logging``)."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from supplyscore.infra.logging import (
    BACKUP_COUNT,
    LOG_FILENAME,
    MAX_BYTES,
    configure_logging,
)


@pytest.fixture
def logger_propre() -> Iterator[logging.Logger]:
    """Restaure l'état du logger « supplyscore » après chaque test.

    Les handlers ajoutés pendant le test sont retirés et fermés (important
    sous Windows pour le nettoyage de tmp_path), le niveau initial est rétabli.
    """
    logger = logging.getLogger("supplyscore")
    handlers_initiaux = list(logger.handlers)
    niveau_initial = logger.level
    yield logger
    for handler in list(logger.handlers):
        if handler not in handlers_initiaux:
            logger.removeHandler(handler)
            handler.close()
    logger.setLevel(niveau_initial)


def _flush(logger: logging.Logger) -> None:
    for handler in logger.handlers:
        handler.flush()


def test_ecrit_fichier_et_format(tmp_path: Path, logger_propre: logging.Logger) -> None:
    """Un log INFO est écrit dans tmp_path/logs/supplyscore.log au format FR."""
    log_dir = tmp_path / "logs"
    logger = configure_logging(level="INFO", log_dir=log_dir)
    logger.info("message de test")
    _flush(logger)

    fichier = log_dir / LOG_FILENAME
    assert fichier.is_file()
    contenu = fichier.read_text(encoding="utf-8")
    motif = r"^\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2} \| INFO     \| supplyscore \| message de test$"
    assert re.search(motif, contenu, re.MULTILINE), contenu


def test_accepte_log_dir_en_chaine(tmp_path: Path, logger_propre: logging.Logger) -> None:
    """``log_dir`` peut être une chaîne ; le dossier est créé au besoin."""
    log_dir = tmp_path / "sous" / "logs"
    logger = configure_logging(log_dir=str(log_dir))
    logger.info("via chaîne")
    _flush(logger)
    assert "via chaîne" in (log_dir / LOG_FILENAME).read_text(encoding="utf-8")


def test_handlers_attendus(tmp_path: Path, logger_propre: logging.Logger) -> None:
    """Le logger reçoit un handler fichier rotatif (2 Mo × 5) et une console."""
    logger = configure_logging(log_dir=tmp_path / "logs")
    rotatifs = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    consoles = [
        h
        for h in logger.handlers
        if isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler)
    ]
    assert len(rotatifs) == 1
    assert len(consoles) == 1
    assert rotatifs[0].maxBytes == MAX_BYTES == 2_000_000
    assert rotatifs[0].backupCount == BACKUP_COUNT == 5


def test_idempotent_pas_de_duplication(tmp_path: Path, logger_propre: logging.Logger) -> None:
    """Rappeler configure_logging ne duplique ni handlers ni lignes de log."""
    log_dir = tmp_path / "logs"
    premier = configure_logging(log_dir=log_dir)
    nb_handlers = len(premier.handlers)

    second = configure_logging(log_dir=log_dir)
    assert second is premier
    assert len(second.handlers) == nb_handlers

    second.info("ligne unique")
    _flush(second)
    contenu = (log_dir / LOG_FILENAME).read_text(encoding="utf-8")
    assert contenu.count("ligne unique") == 1


def test_niveau_respecte(tmp_path: Path, logger_propre: logging.Logger) -> None:
    """En niveau INFO, les messages DEBUG sont filtrés."""
    log_dir = tmp_path / "logs"
    logger = configure_logging(level="INFO", log_dir=log_dir)
    logger.debug("message-debug-filtre")
    logger.info("message-info-visible")
    _flush(logger)

    contenu = (log_dir / LOG_FILENAME).read_text(encoding="utf-8")
    assert "message-debug-filtre" not in contenu
    assert "message-info-visible" in contenu


def test_niveau_debug_et_casse(tmp_path: Path, logger_propre: logging.Logger) -> None:
    """Le niveau est insensible à la casse ; en DEBUG, les debug passent."""
    log_dir = tmp_path / "logs"
    logger = configure_logging(level="debug", log_dir=log_dir)
    logger.debug("debug-visible")
    _flush(logger)
    assert "debug-visible" in (log_dir / LOG_FILENAME).read_text(encoding="utf-8")
