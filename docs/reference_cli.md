# Référence de la ligne de commande

> Vérifié contre SupplyScore v2.0.0. Source de vérité : supplyscore/cli.py, supplyscore/tools/restore.py, scripts/.

Cette page décrit tous les points d'entrée exécutables du projet : la commande `supplyscore` qui lance le serveur web local, l'outil de restauration des sauvegardes, les lanceurs Windows du dossier `scripts/`, les scripts de démonstration et la CI locale. L'utilisation de l'application elle-même est couverte par le [manuel utilisateur](manuel_utilisateur.md) ; les procédures de sauvegarde et de restauration sont détaillées dans le [guide d'exploitation](exploitation.md).

| Point d'entrée | Rôle | Section |
|---|---|---|
| `supplyscore`, `python -m supplyscore.cli` | Serveur web local | 1 à 3 |
| `python -m supplyscore.tools.restore` | Restauration d'une sauvegarde | 4 |
| `scripts/Installer.ps1`, `scripts/SupplyScore.bat`, `scripts/SupplyScore.ps1` | Installation et lancement en un clic | 5 |
| `scripts/demo_scenario.py`, `scripts/demo_screenshots.py` | Matériel de démonstration | 6 |
| `scripts/ci.ps1` | CI locale | 7 |
| `run_app.py` | Wrapper hérité | 9 |

## 1. La commande supplyscore

Le serveur web local a un point d'entrée unique : la fonction `main()` de `supplyscore/cli.py`, déclarée dans la section `[project.scripts]` de `pyproject.toml` :

```toml
[project.scripts]
supplyscore = "supplyscore.cli:main"
```

Trois invocations équivalentes appellent cette même fonction. L'exécutable installé dans le venv convient au quotidien, `uv run` évite d'activer le venv, et `python -m` cible un interpréteur précis (c'est la forme employée par les lanceurs de `scripts/`) :

```powershell
# exécutable installé par uv sync dans le venv
.\.venv\Scripts\supplyscore.exe

# via uv, sans activer le venv
uv run supplyscore --demo --open-browser

# module Python explicite
.\.venv\Scripts\python.exe -m supplyscore.cli --port 8099
```

L'exécutable `.venv\Scripts\supplyscore.exe` apparaît lors du `uv sync` (section 5) : si la commande est introuvable, l'environnement n'a simplement pas encore été synchronisé. L'aide intégrée récapitule les options et leurs défauts :

```powershell
.\.venv\Scripts\supplyscore.exe --help
```

`build_parser()` définit neuf options :

| Option | Type | Défaut | Effet |
|---|---|---|---|
| `--db-dir` | chemin | aucun (résolution automatique, section 2) | Répertoire des bases SQLite, prioritaire sur toute autre règle. |
| `--migrate-data` | drapeau | désactivé | Migre un `data_store/` hérité vers l'emplacement par défaut, avec sauvegarde zip de sécurité avant déplacement. |
| `--demo` | drapeau | désactivé | Si la base est vide, génère un projet de test aléatoire (`seed_demo`, `n_ranks=3`, `seed=42`). |
| `--port` | entier | `8050` | Port d'écoute HTTP du serveur local (lié à 127.0.0.1). |
| `--debug` | drapeau | désactivé | Mode debug de Dash, avec rechargement à chaud. |
| `--log-level` | chaîne | `INFO` | Niveau de journalisation (`DEBUG`, `INFO`, `WARNING`...). |
| `--log-dir` | chemin | `%LOCALAPPDATA%\SupplyScore\logs` | Dossier des fichiers journaux. |
| `--no-backup` | drapeau | désactivé | Saute la sauvegarde automatique au démarrage (tests, développement). |
| `--open-browser` | drapeau | désactivé | Ouvre le navigateur par défaut sur l'application, 1,5 s après le lancement du serveur. |

Quelques lancements types, copiables tels quels depuis la racine du dépôt :

```powershell
# lancement standard : données dans %LOCALAPPDATA%\SupplyScore\data
.\.venv\Scripts\supplyscore.exe --open-browser

# base de démonstration jetable sur un port secondaire
.\.venv\Scripts\supplyscore.exe --db-dir C:\Temp\ss-demo --demo --port 8099

# migration unique d'un data_store hérité vers l'emplacement par défaut
.\.venv\Scripts\supplyscore.exe --migrate-data

# journaux verbeux dans un dossier de travail
.\.venv\Scripts\supplyscore.exe --log-level DEBUG --log-dir C:\Temp\ss-logs
```

L'option `--demo` ne fait rien si le registre contient déjà des nœuds : elle ne remplace jamais des données existantes. Le projet généré est constitué de données de test aléatoires, sans valeur métier. Pour un jeu de données de démonstration réaliste et scénarisé, utilisez plutôt `scripts/demo_scenario.py` (section 6).

Le serveur écoute uniquement sur `127.0.0.1` : l'application n'est pas joignable depuis une autre machine, quel que soit le port choisi. L'arrêt se fait par Ctrl+C dans la console ; la fermeture du service (connexions SQLite comprises) est garantie par un gestionnaire `atexit` enregistré au démarrage. Les options se combinent librement, et les lanceurs Windows de la section 5 comme le `run_app.py` hérité de la section 9 acceptent exactement les mêmes : il n'existe qu'un seul analyseur d'arguments pour tous les chemins d'entrée.

## 2. Résolution du répertoire de données

`resolve_db_dir()` (dans `supplyscore/cli.py`, appuyé sur `supplyscore/infra/paths.py`) choisit le répertoire des bases SQLite en appliquant trois règles, dans cet ordre :

1. `--db-dir` explicite : le chemin est utilisé tel quel, aucune autre règle ne s'applique.
2. Un `data_store/` hérité existe sous le dossier de lancement et contient au moins une base `*.sqlite` (détection par `legacy_data_dir()`). Deux cas :
   avec `--migrate-data`, les bases sont migrées par `migrate_legacy_data()` vers l'emplacement par défaut, qui devient le répertoire actif ;
   sans le drapeau, le comportement historique est conservé : `data_store/` reste le répertoire actif et un avertissement « risque de corruption » est journalisé à chaque démarrage.
3. Sinon, l'emplacement par défaut `%LOCALAPPDATA%\SupplyScore\data` (calculé par `platformdirs`, sans sous-dossier éditeur), créé au besoin.

Le maintien du comportement historique dans la règle 2 est délibéré : un poste qui a toujours travaillé dans `data_store/` continue de fonctionner à l'identique tant que la migration n'a pas été demandée explicitement. La migration ne se déclenche jamais d'elle-même.

La migration de la règle 2 procède en trois temps :

1. Refus immédiat (`FileExistsError`, rien n'est touché) si la cible contient déjà des bases `*.sqlite` ; le message invite à les déplacer ou à choisir un autre emplacement via `--db-dir`.
2. Sauvegarde zip de sécurité de toutes les bases du `data_store` dans `%LOCALAPPDATA%\SupplyScore\backups_migration`, avant tout déplacement.
3. Déplacement de chaque base, accompagnée de ses éventuels résidus `-wal` et `-shm`, vers la cible.

Une base corrompue dans le `data_store` fait échouer la sauvegarde de sécurité de l'étape 2 et bloque la migration : rien n'est déplacé. En cas de succès, le journal indique le nombre de fichiers déplacés, la source, la cible et l'emplacement du zip de sécurité. La migration est une opération unique : au lancement suivant, le `data_store/` ne contient plus de base, la règle 2 ne s'applique plus et la règle 3 prend le relais, ce qui pointe naturellement sur les bases migrées.

```powershell
# séquence type de migration, depuis la racine du dépôt
.\.venv\Scripts\supplyscore.exe --migrate-data    # migre puis démarre sur la cible
.\.venv\Scripts\supplyscore.exe                   # les lancements suivants n'ont plus besoin du flag
```

Les journaux suivent la même logique d'emplacement hors synchronisation : `%LOCALAPPDATA%\SupplyScore\logs` par défaut, redirigeable par `--log-dir`. Le répertoire de données effectivement retenu est tracé dans la première ligne de journal du démarrage (section 3, étape 3).

**Ne stockez pas les bases dans un dossier synchronisé cloud (OneDrive, Dropbox).** Les bases SQLite en mode WAL y présentent un risque réel de corruption : le client de synchronisation peut copier les fichiers `.sqlite`, `-wal` et `-shm` à des instants incohérents. C'est précisément la raison d'être de l'emplacement par défaut hors synchronisation et de l'avertissement journalisé quand un `data_store/` hérité est conservé.

## 3. Séquence de démarrage et codes de sortie

`main()` enchaîne les étapes suivantes, dans cet ordre exact :

1. Analyse des arguments par `build_parser()`.
2. Configuration de la journalisation : le dossier vient de `--log-dir`, ou à défaut de `%LOCALAPPDATA%\SupplyScore\logs`.
3. Résolution du répertoire de données (section 2), puis trace de démarrage avec la version, le port et le chemin retenu.
4. Création de l'application Dash (`create_app`) et récupération du service ; sa fermeture est enregistrée via `atexit`. Si le service n'est pas disponible après `create_app`, un avertissement est journalisé et le démarrage continue.
5. Sauvegarde automatique, sauf si `--no-backup` est posé : `ServiceSauvegarde.backup_auto()` crée une archive `SupplyScore_AAAAMMJJ_HHMMSS.zip` dans `<db_dir>/backups` si la plus récente a plus de 24 h (ou s'il n'en existe aucune), puis applique la rétention en conservant les 20 archives les plus récentes (`RETENTION_DEFAUT` dans `supplyscore/data/backup.py`). L'âge se lit dans le nom des archives ; les fichiers au nom inattendu sont ignorés.
6. Seed de démonstration si `--demo` est posé et que le registre est vide : `seed_demo(n_ranks=3, seed=42)`.
7. Programmation de l'ouverture du navigateur si `--open-browser` est posé : `app.run` bloque le thread principal, l'ouverture est donc différée de 1,5 s (`DELAI_NAVIGATEUR_S`) sur un thread minuteur démarré avant le serveur.
8. Démarrage du serveur sur `127.0.0.1` et le port choisi. Le retour est 0 quand le serveur s'arrête (Ctrl+C).

La sauvegarde de l'étape 5 s'appuie sur l'API native `sqlite3.Connection.backup`, qui produit une copie cohérente même si une base est ouverte par ailleurs. Chaque base est vérifiée par `PRAGMA integrity_check` avant d'être archivée ; une base corrompue lève `IntegriteError`, rien n'est archivé et le démarrage s'arrête là. Les fichiers `-wal` et `-shm` ne sont pas archivés : l'API native absorbe leur contenu dans la copie. Les archives s'inspectent directement :

```powershell
Get-ChildItem "$env:LOCALAPPDATA\SupplyScore\data\backups\SupplyScore_*.zip" | Sort-Object Name -Descending
```

Quand une archive est créée, son chemin est tracé dans le journal (« Sauvegarde automatique créée ») ; quand la dernière sauvegarde est encore assez fraîche, rien n'est créé et la rétention s'applique quand même. `--no-backup` saute les deux opérations, création et rétention : l'option est pensée pour les tests et le développement, pas pour l'usage courant.

| Code | Constante | Signification |
|---|---|---|
| 0 | | Arrêt normal du serveur. |
| 2 | `EXIT_BASE_CORROMPUE` | Base corrompue détectée par la sauvegarde automatique : le serveur n'est pas lancé. |

Le code 2 est volontairement bloquant : l'application ne démarre jamais sur des bases corrompues. Restaurez d'abord une archive saine (section 4) puis relancez. Le lanceur `SupplyScore.ps1` (section 5) intercepte ce code et affiche la consigne de restauration à l'utilisateur final.

Aucun autre code de sortie n'est défini : une exception imprévue pendant le démarrage remonte telle quelle, avec la trace Python correspondante.

## 4. Restauration d'une sauvegarde

L'outil de restauration s'invoque comme module Python :

```powershell
.\.venv\Scripts\python.exe -m supplyscore.tools.restore <archive.zip> [--db-dir CHEMIN] [--force]
```

| Argument | Type | Défaut | Effet |
|---|---|---|---|
| `zip_path` | positionnel, obligatoire | | Archive `SupplyScore_AAAAMMJJ_HHMMSS.zip` à restaurer. |
| `--db-dir` | chemin | `data_store` | Répertoire cible des bases SQLite, créé au besoin. |
| `--force` | drapeau | désactivé | Met les bases existantes à l'abri avant de restaurer. |

Le défaut `data_store` correspond à l'ancien emplacement local au projet : si l'application utilise l'emplacement par défaut actuel, passez `--db-dir` explicitement, avec la même valeur que celle de la commande `supplyscore`. Arrêtez l'application avant de restaurer (fermer la console suffit) : restaurer sous un serveur actif laisserait des connexions ouvertes sur des fichiers déplacés.

```powershell
# restauration vers l'emplacement par défaut de l'application
.\.venv\Scripts\python.exe -m supplyscore.tools.restore `
    "$env:LOCALAPPDATA\SupplyScore\data\backups\SupplyScore_20260611_090000.zip" `
    --db-dir "$env:LOCALAPPDATA\SupplyScore\data" --force
```

Les bases déjà présentes dans la cible ne sont jamais détruites. Sans `--force`, la restauration est refusée dès qu'une base `*.sqlite` existe dans la cible, avec un message qui indique le nombre de bases en place et la marche à suivre. Avec `--force`, les bases existantes et leurs résidus `-wal`, `-shm` et `-journal` sont d'abord déplacés dans un sous-répertoire daté `avant_restauration_AAAAMMJJ_HHMMSS/` de la cible, puis l'archive est dépliée. Ce sous-répertoire sert de filet : si la restauration ne donne pas le résultat attendu, les fichiers mis à l'abri peuvent être remis en place à la main.

Seuls les membres `*.sqlite` de l'archive sont extraits, et tout chemin embarqué dans le zip est neutralisé : les fichiers atterrissent directement dans la cible, jamais dans un sous-dossier imposé par l'archive. Après copie, chaque base restaurée passe un `PRAGMA integrity_check` ; un échec interrompt l'outil avec une erreur. Une restauration réussie liste les bases sur la sortie standard :

```text
2 base(s) restaurée(s) dans C:\Users\jhoarau\AppData\Local\SupplyScore\data :
  - registry.sqlite
  - a1b2c3d4.sqlite
```

L'archive contient le registre (`registry.sqlite`) et les bases client (`<client_id>.sqlite`) telles qu'elles existaient au moment de la sauvegarde.

Les codes de retour sont 0 quand la restauration aboutit (la liste des bases restaurées s'affiche sur la sortie standard) et 1 en cas d'erreur, quelle qu'elle soit : archive introuvable, zip invalide, archive sans base `*.sqlite`, cible déjà peuplée sans `--force`, ou base corrompue après restauration. Le message d'erreur, en français, sort sur la sortie d'erreur.

Pour choisir l'archive, l'ordre lexicographique des noms `SupplyScore_AAAAMMJJ_HHMMSS.zip` coïncide avec l'ordre chronologique : la commande `Get-ChildItem` triée de la section 3 affiche la plus récente en premier. En cas de corruption détectée au démarrage (code 2), la plus récente est le bon point de départ ; si elle est elle-même corrompue, remontez d'archive en archive.

Procédure pas à pas : [exploitation.md §4](exploitation.md).

## 5. Lanceurs Windows

Trois fichiers du dossier `scripts/` couvrent l'installation et le lancement sans ligne de commande.

`scripts/Installer.ps1` installe ou met à jour l'environnement d'exécution en trois étapes :

1. Vérification de la présence de l'outil `uv` ; s'il est introuvable, le script affiche la commande d'installation (`winget install astral-sh.uv`) et sort avec le code 1.
2. Synchronisation de l'environnement virtuel `.venv` par `uv sync`, après avoir posé `UV_LINK_MODE=copy` : le mode copie fonctionne sur tous les systèmes de fichiers Windows, dossiers synchronisés compris, là où les liens physiques échouent.
3. Vérification de l'installation : le Python du venv doit exister et `import supplyscore` doit réussir ; la version importée est affichée.

Chaque étape annonce sa progression (« Étape 1/3 », « Étape 2/3 », « Étape 3/3 ») et se conclut par un `OK` ou un `ÉCHEC` explicite, ce qui rend le diagnostic immédiat quand l'installation est faite par un utilisateur non développeur.

Le script est relançable sans risque, `uv sync` étant idempotent : relancer `Installer.ps1` après une mise à jour du dépôt suffit à resynchroniser les dépendances. Un échec de `uv sync` propage son code de retour ; les autres échecs sortent avec le code 1, et le succès avec 0 après avoir indiqué la commande de lancement.

```powershell
.\scripts\Installer.ps1
```

`scripts/SupplyScore.bat` est le lanceur double-clic. Il tient en une ligne et délègue tout au script PowerShell voisin, en lui transmettant les arguments reçus (`%*`) :

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0SupplyScore.ps1" %*
```

`scripts/SupplyScore.ps1` résout le Python du venv (`.venv\Scripts\python.exe`) relativement à la racine du dépôt. S'il est introuvable, le script sort avec le code 1 en invitant à lancer d'abord `Installer.ps1`. Sinon il annonce le démarrage (« Ctrl+C pour arrêter le serveur ») et exécute `python -m supplyscore.cli --open-browser` en y ajoutant tels quels tous les arguments passés au script : un double-clic sur le `.bat` lance donc l'application et ouvre le navigateur, et un appel paramétré reste possible. Si la CLI retourne le code 2 (base corrompue, section 3), le lanceur affiche un message d'arrêt et la consigne de restauration, puis sort avec ce même code ; tout autre code est transmis tel quel.

```powershell
# double-clic sur scripts\SupplyScore.bat, ou en ligne de commande :
.\scripts\SupplyScore.ps1
.\scripts\SupplyScore.ps1 --demo --port 8099
.\scripts\SupplyScore.bat --db-dir C:\Temp\ss-demo
```

## 6. Scripts de démonstration

Deux scripts préparent le matériel de présentation. Le déroulé complet de la démonstration, commandes de régénération comprises, est dans [presentation/DEMO_20MIN.md](presentation/DEMO_20MIN.md).

`scripts/demo_scenario.py` construit le programme AERIS (drone cargo AER-200, identifiant de projet `prog-aeris`) : 10 nœuds répartis sur 4 rangs, de l'assemblage final à Toulouse (rang 0) aux matières premières à Casablanca et Antofagasta (rang 3), reliés par 9 arcs orientés fournisseur vers client auxquels s'ajoute un arc de secours d'AccuPol vers Voltech. La construction pose aussi une taxonomie de tags (catégories Procédé et Région), trois jalons par nœud (Proto, Qualification, Livraison série 1, décalés selon le rang), des cahiers des charges pour quatre acteurs clés, les évaluations AHP initiales et une pondération FBWM des blocs d'Ur, dont les poids et le xi* sont imprimés sur la console. Le script simule ensuite 8 semaines de serious game : revue hebdomadaire complète des 10 nœuds (4 volets), événements calibrés et décisions tracées.

Les 10 acteurs et leur place dans la chaîne :

| Nœud | Rang | Ville | Produit |
|---|---|---|---|
| Aeris Industries (assemblage final) | 0 | Toulouse | Drone cargo AER-200 |
| Mecanika SAS | 1 | Lyon | Nacelle équipée |
| Voltech GmbH | 1 | Hambourg | Module propulsion |
| Composites Atlantique | 2 | Nantes | Panneaux carbone |
| Ferralu Forge | 2 | Gdansk | Carters forgés |
| CellTech Batteries | 2 | Dresde | Pack batterie 800V |
| PowerChip Semiconducteurs | 2 | Hsinchu | Contrôleurs de puissance |
| AccuPol (secours) | 2 | Poznan | Cellules LFP |
| Mines & Alliages Atlas | 3 | Casablanca | Alliages aluminium |
| Lithium Andes | 3 | Antofagasta | Carbonate de lithium |

La dramaturgie est scriptée semaine par semaine. Une non-conformité qualité frappe Ferralu Forge en S2, puis un retard fournisseur de 120 h touche PowerChip en S3 ; le joueur en sous-déclare l'urgence pendant trois semaines, ce qui rend le risque caché H visible au dashboard. Une grève chez Mines & Alliages Atlas (S4) fait remonter le choc le long de la branche fonderie, et la crise PowerChip culmine en S6 avec une perte de capacité de 25 % et l'activation du fournisseur de secours AccuPol. En S7 et S8 la chaîne se stabilise, mais le client final panique à retardement (urgence déclarée à 0,85 alors que Ur redescend), ce qui produit une fausse urgence F en fin de partie.

Les événements injectés, chacun assorti d'une décision tracée :

| Semaine | Nœud | Événement |
|---|---|---|
| S2 | Ferralu Forge | Non-conformité qualité (rebuts fonderie) |
| S3 | PowerChip | Retard fournisseur de 120 h |
| S4 | Mines & Alliages Atlas | Grève (96 h prévues, 60 % de l'effectif) |
| S5 | CellTech | Hausse de l'énergie de 18 % |
| S6 | PowerChip | Perte de capacité de 25 % |
| S7 | Lithium Andes | Perturbation transport (48 h, surcoût 15 000) |

| Option | Défaut | Effet |
|---|---|---|
| `--db-dir` | `%LOCALAPPDATA%\SupplyScore\demo_aeris` | Répertoire des bases de la démo. |
| `--reset` | désactivé | Vide d'abord le répertoire de bases de la démo. |
| `--artefacts` | `docs/presentation/artefacts` | Dossier de dépôt de l'export et du rapport. |

Le script refuse de s'exécuter (code 1) si le répertoire contient déjà des bases : relancez avec `--reset` pour repartir de zéro. Pendant la simulation, chaque semaine imprime le nœud à la pire adéquation avec ses valeurs A, Ud et Ur, ce qui permet de suivre la dramaturgie en direct. En sortie, le script dépose un export xlsx et un rapport de session HTML dans le dossier `--artefacts`, puis imprime un tableau Ud, Ur, A, F, H des 10 nœuds. **Toutes les données produites sont simulées, à usage de démonstration uniquement.**

```powershell
.\.venv\Scripts\python.exe scripts\demo_scenario.py --reset
.\.venv\Scripts\supplyscore.exe --db-dir "$env:LOCALAPPDATA\SupplyScore\demo_aeris" --port 8060
```

`scripts/demo_screenshots.py` capture l'application dans Chrome headless (mode `--headless=new`, chromedriver pris dans le cache `%LOCALAPPDATA%\supplyscore\chromedriver`, le même que `tests/ui/conftest.py`). Le serveur doit déjà tourner sur `--base-url`, pointé sur les bases de la démo : le script ne lance rien lui-même. Il lit `registry.sqlite` en lecture seule pour découvrir le projet et les nœuds remarquables (le client, un nœud de rang 1, le nœud le plus profond, celui à la pire adéquation), injecte la sélection de projet et d'opérateur dans le `sessionStorage` du navigateur, puis visite 13 pages et enregistre des PNG 1920x1080, doublés d'une variante `-pleine-page.png` quand le contenu dépasse l'écran. Aucune écriture en base n'a lieu.

| Capture | Page visitée |
|---|---|
| `01-projets` | `/` |
| `02-onboarding` | `/onboarding` |
| `03-hebdo` | `/hebdo` |
| `04-questionnaire` | `/questionnaire` |
| `05-dashboard` | `/dashboard` |
| `06-simulation` | `/simulation` |
| `07-edition` | `/edition` |
| `08-ponderation` | `/ponderation` |
| `09-graphe` | `/graphe` |
| `10-rapport` | `/rapport` |
| `11-admin` | `/admin` |
| `12-fiche-noeud` | `/node/<nœud de rang 1>` |
| `13-explication` | `/node/<pire adéquation>/explication` |

| Option | Défaut | Effet |
|---|---|---|
| `--base-url` | `http://127.0.0.1:8060` | URL du serveur SupplyScore déjà actif. |
| `--db-dir` | `%LOCALAPPDATA%\SupplyScore\demo_presentation` | Bases à inspecter pour découvrir projet et nœuds. |
| `--out` | `docs/presentation/screenshots` | Dossier des PNG produits. |
| `--operator` | `Animateur` | Nom d'opérateur injecté dans la session. |
| `--only` | aucun | Ne capture que les pages dont le slug contient ce texte. |
| `--rapport` | dernier `Rapport_*.html` des artefacts | Rapport HTML à capturer en scène 17. |
| `--scenes` | désactivé | Capture aussi 4 scènes interactives (14 à 17). |

Les scènes interactives activées par `--scenes` couvrent la revue hebdo du nœud en crise (`14-hebdo-noeud-crise`), un choc simulé sur un nœud profond (`15-simulation-choc`), la criticité systématique (`16-simulation-criticite`) et le rapport de session HTML ouvert dans le navigateur (`17-rapport-session`). Le script retourne 1 si une capture des pages 01 à 13 pèse 30 Ko ou moins, signe probable d'une page vide ; les captures concernées sont listées en fin d'exécution.

```powershell
# le serveur tourne déjà sur le port 8060 avec les bases de la démo
.\.venv\Scripts\python.exe scripts\demo_screenshots.py --db-dir "$env:LOCALAPPDATA\SupplyScore\demo_aeris" --scenes
```

## 7. CI locale : scripts/ci.ps1

`scripts/ci.ps1` exécute la chaîne de qualité en local, sans réseau, et reste compatible Windows PowerShell 5.1 (aucun `&&` ni `||`). Le script vérifie d'abord que `ruff.exe`, `mypy.exe` et `python.exe` existent dans `.venv\Scripts` (code 1 sinon, avec une invite à synchroniser le venv), se place à la racine du dépôt, puis enchaîne les étapes dans cet ordre :

1. `ruff check supplyscore run_app.py tests`
2. `ruff format --check supplyscore run_app.py tests`
3. `mypy supplyscore run_app.py` (sautée par `-SkipMypy`)
4. Contrôle des écritures directes : recherche des motifs `.save_node(` et `.save_arc(` dans `supplyscore\web_ui` et `run_app.py` ; toute occurrence fait échouer le pipeline, car toute écriture métier doit passer par `MutationService`.
5. `pytest tests --cov=supplyscore --cov-report=term --cov-report=xml` ; le seuil `fail_under = 90` de `pyproject.toml` fait échouer l'étape sous 90 % de couverture, et le rapport `coverage.xml` est écrit à la racine du dépôt.
6. Avec `-Benchmarks` : pose `SUPPLYSCORE_BENCH=1` puis lance `pytest tests/benchmarks --benchmark-only --benchmark-autosave --benchmark-storage=docs/benchmarks` ; les rapports s'archivent dans `docs/benchmarks` et la variable est retirée en fin d'étape.
7. Avec `-Ui` : pose `SUPPLYSCORE_UI=1` puis lance `pytest tests/ui -q -m ui` (Chrome headless) ; sans Chrome ni chromedriver les tests se skippent, et la variable est retirée en fin d'étape.

Le pipeline s'arrête à la première étape en échec et propage son code de retour ; chaque étape affiche un bandeau `=== nom de l'étape ===` puis `OK` ou `ÉCHEC` avec le code obtenu. Quand tout est vert, le script affiche « CI locale : toutes les étapes sont vertes. » et sort avec 0. Le périmètre du contrôle de l'étape 4 est volontairement limité : `supplyscore/services/orchestrator.py` conserve le droit d'écrire directement, seuls `supplyscore\web_ui` et `run_app.py` sont scannés.

| Switch | Effet |
|---|---|
| `-SkipMypy` | Saute l'étape mypy. |
| `-Benchmarks` | Ajoute les bancs de performance après la suite rapide. |
| `-Ui` | Ajoute les tests navigateur après la suite rapide. |

```powershell
.\scripts\ci.ps1
.\scripts\ci.ps1 -SkipMypy
.\scripts\ci.ps1 -Benchmarks -Ui
```

## 8. Variables d'environnement

| Variable | Lue par | Effet |
|---|---|---|
| `SUPPLYSCORE_BENCH` | `tests/benchmarks/conftest.py` | À `1`, active les bancs de performance, skippés sinon. Posée par `ci.ps1 -Benchmarks`. |
| `SUPPLYSCORE_UI` | `tests/ui/conftest.py` | À `1`, active les tests navigateur marqués `ui`, skippés sinon. Posée par `ci.ps1 -Ui`. |
| `HYPOTHESIS_PROFILE` | `tests/conftest.py` | Profil Hypothesis : `dev` (50 exemples, défaut) ou `ci` (300 exemples). Posée à `ci` par `.github/workflows/ci.yml`. |
| `UV_LINK_MODE` | l'outil `uv` (posée par `scripts/Installer.ps1`) | À `copy`, force la copie des fichiers au lieu des liens physiques, qui échouent dans les dossiers synchronisés cloud. |
| `DASH_TEST_CHROMEPATH` | `tests/ui/conftest.py` | Chemin explicite du binaire Chrome, prioritaire sur les emplacements standards puis sur le `PATH`. |

Les deux variables `SUPPLYSCORE_*` servent de garde : sans elles, les suites lentes (bancs de performance, navigateur) sont collectées mais skippées, ce qui maintient la suite rapide sous contrôle. `ci.ps1` les pose puis les retire dans un bloc `finally`, elles ne fuient donc pas dans la session PowerShell appelante. Pour un lancement manuel de pytest, en dehors de `ci.ps1` :

```powershell
$env:SUPPLYSCORE_UI = '1'; .\.venv\Scripts\python.exe -m pytest tests/ui -m ui
$env:HYPOTHESIS_PROFILE = 'ci'; .\.venv\Scripts\python.exe -m pytest tests
```

`DASH_TEST_CHROMEPATH` n'est utile que si Chrome est installé hors des emplacements standards (`Program Files`, `Program Files (x86)`, `%LOCALAPPDATA%`) : `tests/ui/conftest.py` la consulte en premier, avant ces emplacements puis le `PATH`.

`UV_LINK_MODE` se pose aussi à la main pour une synchronisation sans passer par `Installer.ps1`, par exemple après l'ajout d'une dépendance :

```powershell
$env:UV_LINK_MODE = 'copy'; uv sync
```

## 9. run_app.py (hérité)

`run_app.py`, à la racine du dépôt, est l'ancien point d'entrée, conservé pour compatibilité.
Il réexporte `main` et `resolve_db_dir` depuis `supplyscore.cli`, sans aucune logique propre.
`python run_app.py [options]` reste fonctionnel, avec exactement les options de la section 1.
`from run_app import resolve_db_dir` reste valable ; `tests/test_infra_paths.py` s'appuie sur ce réexport.
