"""Fixtures partagees et profils Hypothesis de la suite de tests.

Les fixtures locales des modules de test existants (``service`` dans
``test_integration.py`` et ``test_webui.py``, ``repo``, ``chain``, etc.)
restent prioritaires - les noms choisis ici ne les masquent pas.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from hypothesis import settings

from supplyscore.services import SupplyScoreService

# Profils Hypothesis ``dev`` (defaut) : rapide en local. ``ci`` : plus exhaustif, selectionne via la variable d'environnement HYPOTHESIS_PROFILE=ci.
settings.register_profile("dev", max_examples=50)
settings.register_profile("ci", max_examples=300)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


@pytest.fixture
def tmp_store(tmp_path: Path) -> Path:
    """Repertoire de stockage temporaire (existant) pour les bases JSON."""
    store = tmp_path / "store"
    store.mkdir()
    return store


@pytest.fixture
def service_demo(tmp_path: Path) -> SupplyScoreService:
    """Service seede avec un petit projet de demonstration reproductible."""
    svc = SupplyScoreService(db_dir=tmp_path / "demo_store")
    svc.seed_demo(n_ranks=2, seed=1)
    return svc
