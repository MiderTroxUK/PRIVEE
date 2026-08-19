"""Infrastructure des tests navigateur de bout en bout (Lot 16.7).

Regles d'execution (memes principes que ``tests/benchmarks/conftest.py``) :

- le marqueur ``ui`` est enregistre ICI (conftest local, aucun reglage pytest
  global) ;
- la suite rapide SAUTE tous les tests marques ``ui`` a la collecte tant que
  la variable d'environnement ``SUPPLYSCORE_UI`` ne vaut pas ``"1"`` (posee
  par ``scripts/ci.ps1 -Ui``) ;
- si Chrome ou chromedriver sont indisponibles, les tests sont SKIPPES avec
  un message explicite - JAMAIS d'echec d'infrastructure ;
- Chrome tourne en HEADLESS via le hook ``pytest_setup_options`` de
  dash.testing (options consommees par la fixture ``dash_duo`` standard).

NOTE chromedriver : l'extra ``dash[testing]`` epingle ``selenium <= 4.2.0``,
qui NE contient PAS Selenium Manager (arrive en 4.6) - le driver doit donc
etre trouvable sur le PATH du processus. :func:`_raison_indisponibilite`
cherche chromedriver sur le PATH, puis dans un cache local
(``%LOCALAPPDATA%/supplyscore/chromedriver/<version>``), et en dernier
recours le telecharge depuis " Chrome for Testing " (meme role que Selenium
Manager) ; tout echec se traduit par un skip gracieux.
"""

from __future__ import annotations

import functools
import io
import os
import re
import shutil
import urllib.request
import zipfile
from pathlib import Path

import pytest

from supplyscore.services import SupplyScoreService
from supplyscore.web_ui import set_service
from supplyscore.web_ui.app import create_app

#: Emplacements habituels de Chrome sous Windows (+ variable DASH_TEST_CHROMEPATH).
_CHROME_CANDIDATS: tuple[Path, ...] = (
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
    / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", r"C:\nonexistent"))
    / "Google/Chrome/Application/chrome.exe",
)

#: Cache local des chromedrivers telecharges (hors depot, par version complete).
_CACHE_DRIVERS = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "supplyscore" / "chromedriver"
)

#: Gabarit d'URL " Chrome for Testing " du zip chromedriver win64 d'une version.
_URL_CHROMEDRIVER = "https://storage.googleapis.com/chrome-for-testing-public/{version}/win64/chromedriver-win64.zip"


def pytest_configure(config: pytest.Config) -> None:
    """Enregistre le marqueur local des tests navigateur (porte par tous les tests UI)."""
    config.addinivalue_line(
        "markers",
        "ui: test navigateur de bout en bout — exécuté seulement si SUPPLYSCORE_UI=1",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """SKIP tous les tests marques ``ui`` si SUPPLYSCORE_UI != '1' (suite rapide)."""
    if os.environ.get("SUPPLYSCORE_UI") == "1":
        return
    skip_ui = pytest.mark.skip(
        reason="test navigateur : poser SUPPLYSCORE_UI=1 (ou scripts/ci.ps1 -Ui)"
    )
    for item in items:
        if "ui" in item.keywords:
            item.add_marker(skip_ui)


def pytest_setup_options():
    """Options Chrome des fixtures dash.testing : headless, fenetre 1400x1000."""
    from selenium.webdriver.chrome.options import Options

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1400,1000")
    return options


# Resolution Chrome / chromedriver (skip gracieux, jamais d'echec d'infra)


def _chrome_exe() -> Path | None:
    """Binaire Chrome : DASH_TEST_CHROMEPATH, emplacements standards, puis PATH."""
    declare = os.environ.get("DASH_TEST_CHROMEPATH")
    if declare and Path(declare).is_file():
        return Path(declare)
    for candidat in _CHROME_CANDIDATS:
        if candidat.is_file():
            return candidat
    via_path = shutil.which("chrome")
    return Path(via_path) if via_path else None


def _versions_chrome(chrome: Path) -> list[str]:
    """Versions completes installees (dossiers " 149.0.7827.102 "), plus recentes d'abord."""
    versions = [
        d.name
        for d in chrome.parent.iterdir()
        if d.is_dir() and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", d.name)
    ]
    return sorted(versions, key=lambda v: tuple(int(x) for x in v.split(".")), reverse=True)


def _telecharger_chromedriver(version: str) -> Path | None:
    """Telecharge le chromedriver win64 de ``version`` dans le cache local."""
    cible = _CACHE_DRIVERS / version
    exe = cible / "chromedriver.exe"
    if exe.is_file():
        return exe
    with urllib.request.urlopen(_URL_CHROMEDRIVER.format(version=version), timeout=60) as flux:
        archive = zipfile.ZipFile(io.BytesIO(flux.read()))
    membre = next((n for n in archive.namelist() if n.endswith("chromedriver.exe")), None)
    if membre is None:
        return None
    cible.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(archive.read(membre))
    return exe


@functools.lru_cache(maxsize=1)
def _raison_indisponibilite() -> str | None:
    """None si Chrome ET chromedriver sont prets, sinon le motif de skip (francais).

    Effet de bord assume : le dossier du chromedriver retenu est PREPENDU au
    PATH du processus (c'est la que selenium 4.2 le cherche).
    """
    chrome = _chrome_exe()
    if chrome is None:
        return "Chrome introuvable sur ce poste : tests navigateur sautés."
    if shutil.which("chromedriver"):
        return None  # deja sur le PATH : on lui fait confiance
    versions = _versions_chrome(chrome)
    if not versions:
        return f"Version de Chrome indéterminable depuis {chrome} : tests navigateur sautés."
    for version in versions:
        try:
            exe = _telecharger_chromedriver(version)
        except Exception:  # reseau coupe, zip corrompu... : on tente la version suivante
            exe = None
        if exe is not None:
            os.environ["PATH"] = str(exe.parent) + os.pathsep + os.environ.get("PATH", "")
            return None
    return (
        f"chromedriver indisponible (PATH, cache {_CACHE_DRIVERS} et téléchargement "
        f"Chrome for Testing pour Chrome {versions[0]}) : tests navigateur sautés."
    )


@pytest.fixture(scope="session")
def _infra_navigateur() -> None:
    """Skip gracieux de la session UI si Chrome ou chromedriver manquent."""
    raison = _raison_indisponibilite()
    if raison is not None:
        pytest.skip(raison)


# Application sous test


@pytest.fixture
def app_seedee(tmp_path: Path, _infra_navigateur: None):
    """Application Dash complete sur un service seede (demo n_ranks=2, seed=1).

    Le service vit dans ``tmp_path`` (bases SQLite jetables) ; ``create_app``
    pose le service GLOBAL du module web_ui - il est nettoye en teardown pour
    ne pas fuiter d'un test a l'autre.
    """
    service = SupplyScoreService(db_dir=tmp_path / "ui_store")
    service.seed_demo(n_ranks=2, seed=1)
    app = create_app(service=service)
    yield app
    set_service(None)
    service.close()
