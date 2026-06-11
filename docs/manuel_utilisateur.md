# Manuel utilisateur SupplyScore

> Ce manuel s'adresse à l'**animateur** d'une session (qui prépare le projet et pilote les
> tours de jeu) et aux **joueurs** (qui incarnent chacun un nœud de la chaîne et remplissent
> leur revue hebdomadaire). Pour l'administration du poste (sauvegardes, logs, restauration),
> voir [exploitation.md](exploitation.md). Pour les formules et leurs preuves, voir
> [modele_mathematique.md](modele_mathematique.md).

## Table des matières

1. [Démarrage rapide](#1-démarrage-rapide)
2. [Les concepts en une page](#2-les-concepts-en-une-page)
3. [Animer un serious game](#3-animer-un-serious-game)
4. [Guide par page](#4-guide-par-page)
5. [FAQ](#5-faq)

---

## 1. Démarrage rapide

Prérequis : Windows, Python 3.12, [uv](https://docs.astral.sh/uv/).

```powershell
# installer (une fois) — crée .venv et installe tout depuis uv.lock
$env:UV_LINK_MODE='copy'; uv sync

# lancer avec des données de démonstration (TEST uniquement, générées aléatoirement)
.venv\Scripts\python.exe run_app.py --demo

# -> http://127.0.0.1:8050
```

> `UV_LINK_MODE='copy'` est nécessaire si le dossier du projet est synchronisé cloud
> (les liens physiques y échouent). Pour les **données** en revanche, ne PAS utiliser un
> dossier synchronisé — voir [exploitation.md](exploitation.md#1-emplacement-des-données).

Options de `run_app.py` :

| Option | Effet | Défaut |
|---|---|---|
| `--db-dir` | répertoire des bases SQLite | `data_store` |
| `--demo` | si la base est vide, génère un projet de TEST aléatoire (n_ranks=3, seed=42) | désactivé |
| `--port` | port d'écoute HTTP | `8050` |
| `--debug` | mode debug Dash (rechargement à chaud) | désactivé |
| `--log-level` | niveau de journalisation (`DEBUG`, `INFO`, `WARNING`…) | `INFO` |

Les données `--demo` sont **simulées, pour test et démonstration uniquement** — jamais pour
des décisions réelles.

---

## 2. Les concepts en une page

**Le but** : mesurer, pour chaque maillon d'une chaîne logistique, l'écart entre ce que les
humains *déclarent* urgent et ce que les données *montrent* urgent.

- **Ud — urgence déclarée** ∈ [0,1] : issue du **questionnaire AHP** hebdomadaire
  (4 critères : impact opérationnel, fenêtre temporelle, dépendances aval, récupérabilité ;
  comparaisons par paires de Saaty, cohérence exigée CR < 0,10), lissée d'une semaine à
  l'autre (EMA, ρ = 0,3).
- **Ur — urgence réelle** ∈ [0,1] : modélisée depuis les **KPIs** du nœud (temps, capacité,
  OEE, risque, coût, CO₂) agrégés par OU probabiliste, modulée par l'avancement des
  **jalons** (déclaré vs théorique). Les poids des blocs sont ajustables par projet
  (page Pondération, méthode FBWM).
- **A — adéquation** ∈ [0,100] : confrontation Ud/Ur avec pénalité **asymétrique**
  (Prospect Theory) ; se décompose en deux pathologies exclusives :
  - **F — fausse urgence** (Ud > Ur) : panique injustifiée ;
  - **H — risque caché** (Ur > Ud) : danger invisible, **pénalisé ~2,25× plus fort** que F.
- **Rangs 0 → N** : le graphe est un DAG orienté fournisseur → client ; rang 0 = client
  final, rang N = fournisseur profond. **Ud descend** (le besoin du client tire l'amont),
  **Ur remonte** (le risque des fournisseurs contamine l'aval).
- **Horloge bimodale, par projet** : mode **réel** (le temps du poste s'écoule, les
  deadlines se rapprochent toutes seules) ou mode **jeu** (le temps n'avance que quand
  l'animateur clique « Avancer d'une semaine »). Toutes les saisies sont rattachées à une
  **semaine ISO** (« 2026-S24 ») selon l'horloge du projet.
- **Opérateur** : chaque écriture est signée par l'opérateur courant (champ « Opérateur : »
  en haut à droite de la barre de navigation) — c'est ce qui permet le multi-joueurs sur un
  seul poste et l'analyse post-jeu.

Dérivations, bornes, cas chiffrés et références : [modele_mathematique.md](modele_mathematique.md).

---

## 3. Animer un serious game

C'est le parcours de référence de l'application (prouvé de bout en bout par
`tests/test_jalon1_session.py`). Une session = un projet en mode jeu, un joueur par nœud,
des tours d'une semaine simulée.

### 3.1 Préparer la partie

1. Page **Projets** (`/`) : carte « Nouveau projet » → créer le projet de la session
   (ou « Générer une démo » pour une chaîne d'entraînement — données de TEST).
2. Carte **« Horloge du projet »** : mode « Temps de jeu (serious game) » →
   « Appliquer le mode ». Le temps du projet est désormais figé entre les tours ; le bouton
   « Avancer d'une semaine » devient l'unique moteur du temps.
3. En haut à droite, renseigner l'opérateur « animateur » (champ « Opérateur : »). Chaque
   joueur saisira son propre nom avant de jouer — les écritures sont signées.

### 3.2 Onboarder chaque joueur / nœud (wizard, ~30 min par nœud)

Page **Onboarding** (`/onboarding`) : « Créer le brouillon » crée immédiatement le nœud
(badgé « incomplet », contribution neutre aux scores), puis 4 sections :

1. **Identité** — nom, type, localisation, tags, connexions aux autres nœuds (coefficients
   γ/β par arc, nature nominal/backup) ;
2. **Cahier des charges** — livrables et quantités, **jalons datés** (proto, série,
   livraison…), budget et coûts cibles, exigences qualité, pénalités ;
3. **KPIs** — saisie guidée des KPIs initiaux (unités, info-bulles, bornes affichées) ;
4. **Première évaluation** — le premier questionnaire AHP du joueur (c'est lui qui répond !).

À tout moment : « Enregistrer le brouillon et quitter » — le brouillon est **persisté en
base** (pas dans le navigateur) ; la carte « Brouillons en cours » permet de **reprendre**
exactement où on s'était arrêté, même après redémarrage du poste. Une section ne s'enregistre
que si elle est valide (messages d'erreur par champ, rien n'est écrit sinon). À la validation
de la section 4, le nœud devient « complet » et entre dans le calcul des scores.

### 3.3 Le tour de jeu type

1. **L'animateur** (page Projets, carte Horloge) clique **« Avancer d'une semaine »** :
   tous les scores sont réévalués, et tous les nœuds « à jour » passent « en retard » —
   les badges hebdo disent à chacun qu'il doit jouer.
2. **Chaque joueur**, à son tour sur le poste : sélectionner son nom (« Opérateur : »),
   ouvrir **Hebdo** (`/hebdo`), choisir son nœud, dérouler les **4 volets** (budget
   15-20 min, ≤ 12 clics si rien n'a changé) :
   - **Volet 1 — Évaluation AHP** : sliders pré-remplis avec la semaine passée ;
     « Confirmer à l'identique » re-soumet en un clic si rien n'a changé ;
   - **Volet 2 — KPIs de la semaine** : tableau de différences (valeur S−1 | nouvelle
     valeur, vide = inchangé) ; bouton « Rien n'a changé » par bloc ; un KPI déjà touché
     par un événement de la semaine porte un avertissement (anti double comptage) ;
   - **Volet 3 — Jalons** : pour chaque jalon actif, statut et % d'avancement déclaré,
     avec l'avancement *théorique* en regard (« théorique 62 % / déclaré 40 % → retard ») ;
   - **Volet 4 — Événements & décision** : déclarer les événements de la semaine (14 types
     calibrés : panne, grève, hausse tarif, rupture matière…) — **« Prévisualiser »**
     montre l'impact KPI avant/après, « Confirmer » l'applique de façon **réversible** ;
     les événements ouverts des semaines passées sont relancés (« toujours en cours ? ») ;
     enfin, la carte « Décision prise cette semaine » **trace la décision du joueur avec
     un instantané des scores au moment T** — c'est la matière première de l'analyse
     post-jeu.
3. **L'animateur** suit la partie au Dashboard pendant et entre les tours (§3.4), puis
   relance un tour.

### 3.4 Suivre la partie (Dashboard)

Page **Dashboard** (`/dashboard`) :

- carte **« Questionnaires à jour : x/y »** + colonne « Hebdo » par nœud (À jour /
  En retard (n sem.) / Manquant) : qui n'a pas joué ;
- **DAG coloré par adéquation** A (carte « Chaîne logistique ») : où ça fait mal ;
- carte **« Priorités PROMETHEE II »** : classement multicritère des nœuds à traiter en
  premier ;
- tableau « Détail des nœuds » (Ud/Ur/A/F/H) avec lien **« Expliquer »** par ligne →
  page d'explication du score (`/node/<id>/explication`) : décomposition exacte de Ud par
  critère, d'Ur par bloc KPI, part locale vs propagée, équation d'adéquation instanciée —
  de quoi répondre à « pourquoi A = 38 ? » devant les joueurs ;
- carte « Évolution temporelle » : trajectoires des scores semaine après semaine.

### 3.5 Clôturer la session

Page **Projets**, carte **« Exporter & sauvegarder »** :

1. **« Exporter le projet (xlsx) »** : un classeur complet (nœuds, arcs, jalons,
   évaluations, historique des urgences, snapshots KPI, événements, décisions, revues
   hebdo, journal d'audit) pour l'analyse hors application ;
2. Page **Rapport** (`/rapport`) : « Générer le rapport de session » → un HTML autonome
   imprimable : évolution des scores, chronologie événements/décisions, **calibration
   prédiction/réalité** (le score H a-t-il prédit les vraies ruptures ? matrice de
   confusion, courbe de calibration) ;
3. **« Sauvegarder les bases maintenant »** : archive zip cohérente de toutes les bases
   (voir [exploitation.md](exploitation.md)).

---

## 4. Guide par page

Onze pages dans la barre de navigation, plus deux pages par nœud (routes `/node/<id>`).

| Page | Rôle | À ne pas faire |
|---|---|---|
| **Projets** (`/`) | Créer/sélectionner un projet, ajouter des nœuds, statuts de tâche, horloge réel/jeu, paramètres du calcul (u_time analytique ou Monte Carlo), export et sauvegarde. | Ne pas utiliser « Générer une démo » dans un projet réel : données aléatoires de TEST. |
| **Onboarding** (`/onboarding`) | Wizard 4 sections pour créer un nœud complet ; brouillon persisté en base et repris à tout moment. | Ne pas ressaisir un nœud de zéro si un brouillon existe — « Reprendre » depuis la carte « Brouillons en cours ». |
| **Hebdo** (`/hebdo`) | La revue hebdomadaire guidée d'un nœud en 4 volets : AHP, diff KPI, jalons, événements & décision. C'est la page des joueurs. | Ne pas saisir un même fait deux fois (événement au volet 4 **et** correction manuelle du KPI au volet 2) — l'avertissement de double comptage est là pour ça. |
| **Questionnaire** (`/questionnaire`) | Mode expert historique : évaluation AHP + saisie KPI directes, calcul de Ud en direct avec contrôle de cohérence (CR). | Préférer Hebdo pour le rituel courant ; une évaluation incohérente (CR ≥ 0,10) est refusée. |
| **Dashboard** (`/dashboard`) | Vue d'ensemble : indicateurs globaux, DAG coloré par A, priorités PROMETHEE II, détail Ud/Ur/A/F/H par nœud, évolution temporelle. | Ne pas interpréter un « — » comme un bon score : c'est une absence d'évaluation (voir FAQ). |
| **Simulation** (`/simulation`) | What-if sans persistance : choc unitaire, scénarios composites multi-chocs, criticité systématique (tornado top 15), scénarios enregistrés. | La carte « Appliquer réellement » est la SEULE action persistante de la page — ne pas la confondre avec la simulation. |
| **Édition** (`/edition`) | Tableau éditable des KPIs courants, filtré par projet/bloc/tags ; toute édition est validée, auditée et recalcule les scores. | Ne pas s'étonner d'un rejet : une valeur hors bornes est refusée et la cellule restaurée. |
| **Pondération** (`/ponderation`) | Questionnaire FBWM (2n−3 comparaisons) pour pondérer les blocs KPI d'Ur, par projet et semaine ; aperçu live des poids et de la cohérence. | Ne pas confondre avec l'AHP du questionnaire : l'AHP pondère les 4 critères de Ud, le FBWM les blocs d'Ur. |
| **Graphe** (`/graphe`) | Éditeur de structure : arcs (γ/β/δ, nominal/backup), ajout/suppression confirmée, taxonomie des tags, statuts. | Ne pas chercher à créer un cycle : le contrôle anti-cycle refuse l'arc avant toute écriture. |
| **Rapport** (`/rapport`) | Génère le rapport de session HTML autonome (scores, chronologie, calibration prédiction/réalité). | Nécessite un projet actif ; horizon de calibration 1–12 semaines (4 par défaut). |
| **Admin** (`/admin`) | Vue « données brutes » des tables SQLite, en lecture seule par défaut ; édition cellule par cellule après déverrouillage explicite, revalidée et auditée. | **Zone avancée.** Ne déverrouiller l'édition qu'en connaissance de cause ; les tables d'historique (`audit_log`, `urgency_history`, `kpi_snapshots`, `weekly_reviews`, `decisions`) sont inéditables par construction — ne pas essayer de les « corriger ». |
| **Fiche nœud** (`/node/<id>`) | Vue 360° d'un nœud : identité, cahier des charges versionné, jalons, KPIs, évaluations, événements, journal d'audit ; chaque carte est rééditable avec les validations du wizard. | Ne pas modifier plusieurs cartes « en parallèle » : une seule carte en édition à la fois. |
| **Explication** (`/node/<id>/explication`) | « Pourquoi ce score ? » : décomposition exacte de Ud, d'Ur (par bloc, part locale vs propagée) et de l'équation d'adéquation, avec liens vers l'historique d'audit. | Page en lecture seule — c'est l'instrument de défense du score, pas un endroit où le changer. |

---

## 5. FAQ

**Pourquoi la colonne A affiche « — » pour un nœud ?**
Le nœud n'a **jamais été évalué** cette semaine-là (statut hebdo « Manquant ») ou est encore
en brouillon d'onboarding. L'application refuse de calculer une adéquation contre un Ud
inexistant (cela fabriquerait des risques cachés artificiels) : elle affiche « — » et le
badge hebdo correspondant. Remplir le volet 1 de l'Hebdo fait apparaître le score.

**Pourquoi le statut de ma tâche est revenu à ACTIVE alors que je l'avais passé à DONE ?**
Dès qu'un nœud possède des **jalons**, son statut est **dérivé des jalons** (règle
pessimiste : ≥ 1 jalon actif → ACTIVE ; aucun actif et ≥ 1 terminé → DONE ; tous abandonnés
→ ABANDONED) et écrase le statut manuel à chaque évaluation. Pour terminer le nœud, terminez
ses jalons (volet 3 de l'Hebdo). Le statut manuel ne fait foi que pour les nœuds sans jalon.

**Le score a bougé alors que personne n'a rien saisi — pourquoi ?**
Le projet est en mode **temps réel** : l'horloge du poste court, le temps restant avant les
deadlines diminue, donc `u_time` (probabilité de retard) monte tout seul. C'est le
comportement voulu en exploitation réelle. En serious game, passez le projet en mode
**jeu** (carte « Horloge du projet ») : le temps n'avance alors qu'au clic
« Avancer d'une semaine ».

**« Annuler » un événement échoue avec un message de conflit — pourquoi ?**
L'annulation restaure chaque KPI à sa valeur d'avant l'événement, **uniquement si rien ne
l'a réécrit entre-temps**. Si le KPI a été modifié depuis (édition manuelle, autre
événement), l'application refuse toute restauration partielle silencieuse et liste les
champs en conflit. À vous d'arbitrer : corriger le KPI à la main (page Édition ou volet 2
de l'Hebdo), en connaissance des deux valeurs. C'est un choix assumé du modèle — une
annulation « magique » serait mathématiquement malhonnête.
