# SupplyScore — Démo & présentation 20 min (Programme AERIS)

Tout le matériel de cette présentation est régénérable (voir §7). Le scénario
de démo est le **« Programme AERIS — drone cargo AER-200 »** : 10 acteurs
nommés sur 4 rangs, **8 semaines de serious game déjà jouées** avec une vraie
dramaturgie. Données simulées, à annoncer comme telles.

## 1. L'histoire que racontent les données (à connaître par cœur)

| Semaine | Événement | Effet visible |
|---|---|---|
| S1-S2 | Démarrage, non-conformité qualité chez **Ferralu Forge** (rebuts fonderie) | premières dérives |
| S3 | **Retard fournisseur 120 h chez PowerChip** — la joueuse « Mei » SOUS-DÉCLARE son urgence pendant 4 semaines | le **risque caché H** s'installe |
| S4 | **Grève chez Mines & Alliages Atlas** (96 h, 60 % de l'effectif) | le choc remonte la branche fonderie |
| S5 | Jalon « Qualification » terminé EN AVANCE chez Composites Atlantique ; hausse énergie CellTech +18 % | contraste vert/rouge |
| S6 | **Perte de capacité 25 % chez PowerChip** → décision tracée : « activation du plan de secours AccuPol » | la crise éclate |
| S7-S8 | La chaîne se stabilise… mais le **client final panique à retardement** (Ud 0,85 quand Ur redescend) | **fausse urgence F** généralisée |

**État final (ce que le public voit au dashboard)** : pire nœud = PowerChip
(A = 46,5, Ur = 1,00, **H = 0,24** — seul risque caché), **6 fausses urgences**
ailleurs (la panique du programme s'est diffusée), A moyen 68,7. Moralité en
une phrase : *« le seul vrai danger est précisément là où personne ne crie »*.

## 2. Pré-vol (15 min avant de présenter)

```powershell
# 1. (si besoin) régénérer le scénario — ~1 min
.venv\Scripts\python.exe scripts\demo_scenario.py --reset

# 2. lancer l'app sur la base AERIS
.venv\Scripts\supplyscore.exe --db-dir "$env:LOCALAPPDATA\SupplyScore\demo_aeris" --port 8060 --no-backup
# -> http://127.0.0.1:8060
```

Checklist dans le navigateur :
- [ ] Page **Projets** : sélectionner « Programme AERIS — drone cargo AER-200 » (bouton « Sélectionner »).
- [ ] Vérifier carte **Horloge du projet** : mode « Temps de jeu (serious game) » actif (le script l'a posé). NE PAS rester en temps réel, sinon les scores dérivent pendant que vous parlez.
- [ ] Renseigner **Opérateur :** (barre de navigation) = votre nom.
- [ ] Ouvrir en onglets : `/dashboard`, `/hebdo`, `/simulation`, `/rapport`.
- [ ] Plan B prêt : `docs/presentation/screenshots/` + le rapport HTML de `docs/presentation/artefacts/` ouverts dans un autre onglet.

## 3. Déroulé minuté (20 min)

### 0:00-2:00 — Le problème (slides)
Toute chaîne d'approvisionnement souffre de deux maladies **invisibles dans
les tableaux de bord classiques** : la *fausse urgence* F (on crie au loup,
on paie des stocks tampons pour rien) et le *risque caché* H (les capteurs
hurlent, personne ne déclare — on découvre la rupture trop tard). Ces deux
erreurs ne coûtent pas le même prix : la panique est récupérable, le danger
invisible ne l'est pas. **Aucune plateforme du marché (Everstream, Resilinc,
Interos) ne mesure l'écart entre ce que les humains déclarent et ce que les
données montrent.** C'est ce que fait SupplyScore.

### 2:00-4:30 — Le modèle en 90 secondes (slides)
- **Ud** : questionnaire AHP (Saaty 1977) — l'urgence *déclarée* chaque semaine, avec rejet automatique des réponses incohérentes (CR ≥ 0,10).
- **Ur** : 6 familles de KPIs = 6 **détecteurs de fumée** (temps, capacité, OEE, risque, coût, CO₂) combinés en OU probabiliste — un seul détecteur saturé suffit à déclencher l'alarme, une moyenne aurait noyé le signal.
- **A** : la confrontation Ud/Ur, pénalisée par la **Prospect Theory** (Kahneman-Tversky) : sous-estimer coûte **2,25×** plus cher que paniquer — λ=2,25 et α=0,88 sont les constantes *mesurées* par les prix Nobel, pas un réglage maison.
- **Propagation sur le graphe** : le besoin descend (client → fournisseurs), le risque remonte (fournisseurs → client), comme un bouchon remonte une autoroute.
- Le chiffre choc à montrer : même écart maximal, **A = 29,3** si on panique pour rien, **A = 0** si on ne voit pas le danger.

### 4:30-6:00 — Le terrain de jeu (slide puis bascule app)
Présenter AERIS : un programme de drone cargo, 10 acteurs de l'assemblage
final (Toulouse) au lithium (Chili), **8 semaines de jeu déjà jouées par 10
joueurs identifiés**. Annoncer : données simulées, générées par le moteur de
test du projet.

### 6:00-9:00 — DÉMO 1 : le Dashboard, « où ça fait mal »
`/dashboard`. Dérouler dans l'ordre :
1. Les cartes : 10/10 questionnaires à jour, A moyen 68,7, **pire adéquation 46,5 = PowerChip**, 1 risque caché, 6 fausses urgences.
2. Le **DAG coloré** : la chaîne entière d'un coup d'œil, taille = urgence réelle, l'arc pointillé = fournisseur de secours AccuPol.
3. Tableau « Détail des nœuds » : colonnes Ud/Ur/**A/F/H** — montrer que PowerChip est le SEUL avec H > 0 pendant que cinq autres ont F > 0 : *« tout le monde panique, sauf celui qui devrait »*.
4. Carte « Priorités PROMETHEE II » : le classement multicritère dit qui traiter en premier.
5. Carte « Évolution temporelle » : la trajectoire sur 8 semaines — on VOIT la crise de S3 s'installer puis la panique tardive du client.

### 9:00-11:00 — DÉMO 2 : « Pourquoi A = 46,5 ? » (l'anti-boîte noire)
Depuis le tableau, cliquer « **Expliquer** » sur PowerChip → `/node/powerchip/explication` :
- l'alerte rouge : *« Retard avéré : l'échéance est dépassée, u_time est forcé à 1 — cause unique »* ;
- la décomposition de Ud critère par critère (dernière évaluation de « Mei », CR affiché) ;
- « Qui tire le besoin déclaré ? » : 52,6 % local, le reste tiré par Voltech et Mecanika (γ des arcs) ;
- **l'équation instanciée** : `pénalité = 2.25×0.24^0.88` → A = 46,5, avec la phrase de gouvernance affichée : *« le danger invisible est pire que la fausse urgence »* ;
- le journal d'audit en bas : chaque chiffre est traçable (qui, quand, quelle source, quel événement).
Message : **aucun score n'est une boîte noire — l'outil se défend tout seul.**

### 11:00-14:30 — DÉMO 3 : le tour de jeu EN DIRECT (les modifications live)
C'est le moment fort : on joue la semaine 9 devant le public.
1. Barre de navigation : taper l'opérateur **Mei**.
2. Page **Projets** → carte « Horloge du projet » → « **Avancer d'une semaine** » : tous les scores sont réévalués, tous les badges hebdo passent « En retard » — *un clic = un tour de jeu pour toute la chaîne*.
3. Page **Hebdo** → choisir « PowerChip Semiconducteurs » → dérouler les 4 volets :
   - Volet 1 (AHP prérempli de la semaine passée) : **monter les notes des critères** — Mei « avoue » enfin l'ampleur du problème — « Enregistrer l'évaluation » ;
   - Volet 3 (jalons) : passer le jalon « Proto » à **terminé** (la pièce est enfin sortie) ;
   - Volet 4 : « Décision prise cette semaine » → saisir « Volume re-routé vers AccuPol confirmé » (décision tracée avec snapshot des scores) ;
   - « Clôturer la revue ».
4. Retour `/dashboard` : **le H de PowerChip fond, son A remonte** (~46 → 75+), la carte « Risques cachés » passe à 0. *« Le score ne récompense pas la bonne nouvelle : il récompense la déclaration honnête ET le jalon réellement clôturé. »*

### 14:30-17:00 — DÉMO 4 : et si ? (simulation sans risque)
`/simulation` :
1. « Nœud à choquer » = **Lithium Andes**, bouton « Défaillance totale (1.0) », « **Simuler** » : le DAG montre la contamination rang 3 → rang 0 (ΔUr max +0,37 sur CellTech) — *rien n'est persisté, on joue sur une copie*.
2. « **Analyser la criticité (top 15)** » : la **tornado** classe automatiquement les nœuds dont la défaillance ferait le plus mal au client final — c'est le plan de continuité qui s'écrit tout seul.
3. (Si question hostile) `/edition` : saisir un KPI hors bornes → rejet propre + cellule restaurée ; ou `/graphe` : tenter un arc qui crée un cycle → refus avant toute écriture.

### 17:00-19:00 — La preuve & l'avancement (slides ou app selon le temps)
1. `/rapport` → « Générer le rapport » : HTML autonome — synthèse, chronologie événements/décisions, **calibration prédiction/réalité** (« le score H a-t-il prédit les vraies ruptures ? »). Si le temps manque : montrer le screenshot 17.
2. Chiffres d'avancement (slide) — voir §5.

### 19:00-20:00 — Limites honnêtes & suite
- Probabilités et scores, **pas des prophéties** ; un score n'est jamais plus frais que la dernière saisie (saisie manuelle assumée, pas d'ERP).
- Écarté volontairement (décisions documentées) : TTR/TTS Simchi-Levi (candidat n°1 pour la suite), centre d'alertes, Neo4j, multi-postes.
- **Prochaine étape : le serious game réel** — c'est le banc d'essai final, il servira à recalibrer les impacts d'événements sur des données constatées.

## 4. Plan de slides Canva (suggestion, 10 slides)

| # | Slide | Visuel |
|---|---|---|
| 1 | Titre : « SupplyScore — mesurer l'écart entre ce qu'on déclare et ce qui se passe » | logo/DAG stylisé |
| 2 | Les 2 maladies : fausse urgence F vs risque caché H | schéma 2 colonnes + « 29,3 vs 0 » |
| 3 | Le modèle : Ud (AHP) / Ur (6 capteurs, OU probabiliste) / A (Prospect 2,25×) / propagation | 4 icônes + 1 formule chacune |
| 4 | Le terrain : Programme AERIS, 10 acteurs, 4 rangs, 8 semaines jouées | `09-graphe.png` ou carte des villes |
| 5 | DÉMO (transition) — secours : | `05-dashboard-pleine-page.png` |
| 6 | L'explicabilité — secours : | `13-explication-pleine-page.png` |
| 7 | Le tour de jeu — secours : | `14-hebdo-noeud-crise-pleine-page.png` |
| 8 | Et si ? — secours : | `15-simulation-choc.png` + `16-simulation-criticite-pleine-page.png` |
| 9 | La preuve : 18 phases, 1 607 tests, 94,1 %, budgets perf ×6, 4 bugs réels trouvés par les tests | tableau §5 + `17-rapport-session.png` |
| 10 | Limites honnêtes + prochaines étapes (serious game réel) | liste courte |

Toutes les captures : `docs/presentation/screenshots/` (1920 px de large,
versions « -pleine-page » pour les pages longues).

## 5. Chiffres clés vérifiés (sources : git log, CHANGELOG, bancs archivés)

| Chiffre | Valeur |
|---|---|
| Phases livrées | **18/18** (E0-E17), 3 jalons, toutes taguées, v2.0.0 |
| Tests | 144 (v1) → **1 592 rapides + 8 parcours navigateur réels + 7 bancs = 1 607** |
| Couverture | **94,1 %** (seuil bloquant 90 %) |
| Perf @1 000 nœuds | propagation 12,5 ms (budget 80) · incrémentale 1,3 ms (budget 5) · Monte Carlo 10 000 tirages 0,74 s (budget 2 s) |
| Application | 13 pages, ~90 callbacks tous protégés (aucune erreur brute, messages en français) |
| Robustesse | 4 vrais bugs trouvés par les tests de propriétés/bancs (div/0 CO₂, monotonie sur dénormalisés, horodatage mode jeu, cache SQLite à l'échelle) — corrigés avec régression |

## 6. Questions pièges (réponses en 1 phrase)

- **« 2,25, calibré sur quoi ? »** — Constante d'aversion à la perte mesurée par Tversky & Kahneman (1992) ; choix de gouvernance documenté, recalibrable après le serious game.
- **« L'AHP est incohérent. »** — Seuil de Saaty CR < 0,10 bloquant + 4 critères seulement ; pour les 6 blocs d'Ur on utilise FBWM (2n−3 comparaisons).
- **« KPI manquant = tout va bien ? »** — Non : bloc ignoré et poids renormalisés — ni optimiste ni pessimiste.
- **« Pourquoi pas une moyenne des 6 blocs ? »** — Une rupture matière totale noyée dans 5 blocs sains donnerait 0,17 : absurde. Le OU probabiliste fait sonner l'alarme dès qu'UN détecteur sature.
- **« Une tâche terminée coupe la chaîne ? »** — Non : DONE = « je n'émets plus d'urgence propre », l'aval reste exposé à l'amont (décision de modélisation documentée).
- **« Vous prédisez les ruptures ? »** — Non : on rend visible le *désalignement* perception/mesure ; la décision reste humaine, tracée, auditée — et le rapport de calibration confronte a posteriori prédictions et réalité.

## 7. Tout régénérer

```powershell
# scénario (bases dans %LOCALAPPDATA%\SupplyScore\demo_aeris, ~1 min)
.venv\Scripts\python.exe scripts\demo_scenario.py --reset

# captures (app lancée sur :8060 au préalable)
.venv\Scripts\python.exe scripts\demo_screenshots.py --db-dir "$env:LOCALAPPDATA\SupplyScore\demo_aeris" --scenes
```

Artefacts générés par le scénario dans `docs/presentation/artefacts/` :
export xlsx complet (12 feuilles) + rapport de session HTML (à ouvrir avec
internet pour les figures). La base de démo vit HORS du dépôt et n'affecte
jamais les données réelles (`--db-dir` dédié).
