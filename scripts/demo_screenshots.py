"""Captures d'écran de l'application pour une présentation (Chrome headless).

Usage :
    .venv\\Scripts\\python.exe scripts\\demo_screenshots.py
        [--base-url http://127.0.0.1:8060]
        [--db-dir %LOCALAPPDATA%\\SupplyScore\\demo_presentation]
        [--out docs\\presentation\\screenshots]

Le script découvre le projet et les nœuds dans ``registry.sqlite`` (lecture
seule), injecte la sélection de projet/opérateur dans le ``sessionStorage``
(stores Dash de session), visite chaque page et enregistre des PNG 1920x1080
(+ une variante pleine page pour les pages longues). L'application doit déjà
tourner sur ``--base-url``. Outil de présentation uniquement — aucune écriture
en base.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

#: Cache local des chromedrivers (même emplacement que tests/ui/conftest.py).
_CACHE_DRIVERS = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "supplyscore" / "chromedriver"
)


def _prepend_chromedriver_path() -> None:
    """Prépend au PATH le chromedriver le plus récent du cache local."""
    if not _CACHE_DRIVERS.is_dir():
        return
    versions = sorted(
        (d for d in _CACHE_DRIVERS.iterdir() if (d / "chromedriver.exe").is_file()),
        key=lambda d: tuple(int(x) for x in d.name.split(".")),
        reverse=True,
    )
    if versions:
        os.environ["PATH"] = str(versions[0]) + os.pathsep + os.environ.get("PATH", "")


def _registry_ids(db_dir: Path) -> dict:
    """Projet actif + nœuds remarquables (client, rang 1, nœud le plus profond)."""
    db = db_dir / "registry.sqlite"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        proj = con.execute(
            "select id, name, owner_node_id from projects order by created_at desc limit 1"
        ).fetchone()
        if proj is None:
            raise SystemExit(f"Aucun projet dans {db}")
        project_id, name, owner_id = proj
        nodes = con.execute(
            "select id, name, rank from nodes where project_id = ? order by rank, name",
            (project_id,),
        ).fetchall()
        worst = con.execute(
            "select u.node_id, n.name from node_urgency u join nodes n on n.id = u.node_id "
            "where n.project_id = ? order by u.adequation limit 1",
            (project_id,),
        ).fetchone()
    finally:
        con.close()
    deepest = max(nodes, key=lambda n: n[2])
    rank1 = next((n for n in nodes if n[2] == 1), deepest)
    return {
        "project_id": project_id,
        "project_name": name,
        "owner_id": owner_id,
        "rank1_id": rank1[0],
        "rank1_name": rank1[1],
        "deepest_id": deepest[0],
        "deepest_name": deepest[1],
        "worst_id": worst[0] if worst else owner_id,
        "worst_name": worst[1] if worst else "",
    }


def _pages(ids: dict) -> list[tuple[str, str, float, bool]]:
    """(slug, chemin, délai de rendu en s, capture pleine page en plus)."""
    return [
        ("01-projets", "/", 4.0, True),
        ("02-onboarding", "/onboarding", 3.0, True),
        ("03-hebdo", "/hebdo", 3.0, True),
        ("04-questionnaire", "/questionnaire", 3.0, True),
        ("05-dashboard", "/dashboard", 8.0, True),
        ("06-simulation", "/simulation", 5.0, True),
        ("07-edition", "/edition", 4.0, False),
        ("08-ponderation", "/ponderation", 3.0, True),
        ("09-graphe", "/graphe", 6.0, True),
        ("10-rapport", "/rapport", 4.0, True),
        ("11-admin", "/admin", 4.0, False),
        ("12-fiche-noeud", f"/node/{ids['rank1_id']}", 4.0, True),
        ("13-explication", f"/node/{ids['worst_id']}/explication", 5.0, True),
    ]


def _select_dropdown(driver, css_id: str, texte: str) -> bool:
    """Sélectionne une option d'un dcc.Dropdown par son texte (plusieurs stratégies)."""
    import time as _time

    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    _ = Keys  # import conservé pour d'éventuelles stratégies clavier
    driver.find_element(By.CSS_SELECTOR, f"#{css_id}").click()
    _time.sleep(1.0)
    cible = texte.lower()[:18]
    # Dropdown Dash 4 : options « .dash-dropdown-option » dans un portail radix.
    clique = False
    for opt in driver.find_elements(By.CSS_SELECTOR, ".dash-dropdown-option"):
        try:
            if cible in (opt.text or "").lower():
                opt.click()
                clique = True
                break
        except Exception:
            continue
    if not clique:
        return False
    _time.sleep(0.8)
    valeur = driver.find_element(By.CSS_SELECTOR, f"#{css_id}").text or ""
    return cible.split()[0] in valeur.lower()


def _scenes(driver, base_url: str, ids: dict, out: Path, rapport_html: Path | None):
    """Captures interactives : hebdo remplie, choc simulé, criticité, rapport."""
    import time as _time

    from selenium.webdriver.common.by import By

    resultats = []

    def shot(slug: str, fullpage: bool = True) -> None:
        target = out / f"{slug}.png"
        driver.set_window_size(1920, 1080)
        _time.sleep(0.5)
        driver.save_screenshot(str(target))
        note = f"{target.stat().st_size // 1024} Ko"
        if fullpage:
            height = driver.execute_script(
                "return Math.min(6000, Math.max(document.body.scrollHeight, 1080))"
            )
            if height > 1140:
                driver.set_window_size(1920, int(height) + 120)
                _time.sleep(1.0)
                (out / f"{slug}-pleine-page.png").unlink(missing_ok=True)
                driver.save_screenshot(str(out / f"{slug}-pleine-page.png"))
                note += " + pleine page"
        print(f"OK  {slug}.png ({note})")
        resultats.append(slug)

    nom_crise = ids["worst_name"] or ids["deepest_name"]

    # Scène A — revue hebdo du nœud en crise (4 volets remplis).
    driver.get(base_url + "/hebdo")
    _time.sleep(3.0)
    if _select_dropdown(driver, "hebdo-node-dd", nom_crise):
        _time.sleep(4.0)
        shot("14-hebdo-noeud-crise")
    else:
        print("?? scène hebdo : sélection du nœud échouée")

    # Scène B — choc simulé sur un nœud profond (défaillance totale par défaut).
    driver.get(base_url + "/simulation")
    _time.sleep(3.0)
    if _select_dropdown(driver, "sim-node-dd", ids["deepest_name"]):
        driver.find_element(By.CSS_SELECTOR, "#sim-run-btn").click()
        _time.sleep(7.0)
        shot("15-simulation-choc")
    else:
        print("?? scène simulation : sélection du nœud échouée")

    # Scène C — criticité systématique (tornado top 15).
    try:
        driver.find_element(By.CSS_SELECTOR, "#sim-crit-btn").click()
        _time.sleep(20.0)
        shot("16-simulation-criticite")
    except Exception as exc:
        print(f"?? scène criticité : {exc}")

    # Scène D — rapport de session HTML (fichier généré par le scénario).
    if rapport_html and rapport_html.is_file():
        driver.get(rapport_html.resolve().as_uri())
        _time.sleep(6.0)
        shot("17-rapport-session")
    return resultats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8060")
    parser.add_argument(
        "--db-dir",
        default=str(
            Path(os.environ.get("LOCALAPPDATA", "")) / "SupplyScore" / "demo_presentation"
        ),
    )
    parser.add_argument(
        "--out", default=str(Path(__file__).resolve().parents[1] / "docs/presentation/screenshots")
    )
    parser.add_argument("--operator", default="Animateur")
    parser.add_argument("--only", default=None, help="Ne capturer que les slugs contenant ce texte")
    parser.add_argument("--rapport", default=None,
                        help="Chemin du rapport HTML généré (scène 17)")
    parser.add_argument("--scenes", action="store_true",
                        help="Capturer aussi les scènes interactives (14-17)")
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ids = _registry_ids(Path(args.db_dir))
    print(f"Projet : {ids['project_name']} ({ids['project_id'][:8]}…)")

    _prepend_chromedriver_path()
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--hide-scrollbars")
    options.add_argument("--force-device-scale-factor=1")
    driver = webdriver.Chrome(options=options)
    try:
        # Premier chargement puis injection des stores de session Dash.
        driver.get(args.base_url + "/")
        time.sleep(2.0)
        store_project = json.dumps(
            {"project_id": ids["project_id"], "name": ids["project_name"]}
        )
        store_operator = json.dumps({"name": args.operator})
        driver.execute_script(
            "window.sessionStorage.setItem('store-project', arguments[0]);"
            "window.sessionStorage.setItem('store-operator', arguments[1]);",
            store_project,
            store_operator,
        )

        results = []
        for slug, path, settle, fullpage in _pages(ids):
            if args.only and args.only not in slug:
                continue
            driver.set_window_size(1920, 1080)
            driver.get(args.base_url + path)
            time.sleep(settle)
            target = out / f"{slug}.png"
            driver.save_screenshot(str(target))
            size_kb = target.stat().st_size // 1024
            full_kb = ""
            if fullpage:
                height = driver.execute_script(
                    "return Math.min(6000, Math.max(document.body.scrollHeight, 1080))"
                )
                if height > 1140:  # ne dupliquer que si la page dépasse vraiment l'écran
                    driver.set_window_size(1920, int(height) + 120)
                    time.sleep(1.0)
                    target_full = out / f"{slug}-pleine-page.png"
                    driver.save_screenshot(str(target_full))
                    full_kb = f" + pleine page {target_full.stat().st_size // 1024} Ko"
            status = "OK " if size_kb > 30 else "?? (petite image, page vide ?)"
            print(f"{status} {slug}.png ({size_kb} Ko){full_kb}")
            results.append((slug, size_kb))

        if args.scenes:
            rapport = Path(args.rapport) if args.rapport else None
            if rapport is None:
                artefacts = Path(__file__).resolve().parents[1] / "docs/presentation/artefacts"
                candidats = sorted(artefacts.glob("Rapport_*.html"))
                rapport = candidats[-1] if candidats else None
            _scenes(driver, args.base_url, ids, out, rapport)

        suspects = [s for s, kb in results if kb <= 30]
        if suspects:
            print(f"\nATTENTION, captures suspectes : {', '.join(suspects)}")
            return 1
        print(f"\n{len(results)} pages capturées dans {out}")
        return 0
    finally:
        driver.quit()


if __name__ == "__main__":
    sys.exit(main())
