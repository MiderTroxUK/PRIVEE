# Brief — Usine à données multi-agents et prédicteur de rupture transférable

> **Objectif en une phrase.** Faire jouer des crises supply chain réelles par des agents
> LLM sur des chaînes générées aléatoirement, en tirer des milliers d'observations
> étiquetées, entraîner un prédicteur de rupture qui **généralise à toute chaîne**, puis
> le tester sur HÉLIOS pour mesurer s'il change la perception des décideurs — et, quand
> on leur rend leur liberté d'action, **quelles crises il permet d'éviter**.

---

## 0. Le principe qui commande tout le reste

**Le moteur tire la vérité. L'agent maître la raconte.**

Si l'agent maître LLM invente librement les événements, la vérité terrain n'existe plus
et aucune prédiction n'est scorable. La règle est donc stricte :

| Qui | Fait quoi | Ne fait jamais |
|---|---|---|
| **Moteur (code)** | tire le calendrier de crise, les chocs, leurs dates et amplitudes ; les écrit dans `verite.json` AVANT la partie | — |
| **Agent maître (LLM)** | met en scène, donne le contexte, le tempo, rédige les fiches, joue la presse et les fournisseurs | inventer un choc, changer une date, révéler le futur |
| **Agents de nœud (LLM)** | pilotent leur nœud : déclarent leur urgence, décident des actions | voir un autre nœud, voir la vérité, anticiper un tour |

Sans cette séparation, on produit une belle simulation **inexploitable scientifiquement**.

---

## 1. Pré-requis bloquant — réparer le cœur AVANT de produire des données

Un run de diagnostic sur HÉLIOS (juillet 2026, 12 tours × 8 personas + rejeu complet du
pilote) a mis en évidence quatre défauts **dans le cœur du modèle**, pas dans le scénario.
Lancer l'usine avec ces défauts reviendrait à entraîner un modèle à imiter un mécanisme
cassé : il serait bien calibré, sur du bruit.

| # | Défaut | Preuve mesurée | Correction attendue |
|---|---|---|---|
| 1 | Les événements n'atteignent jamais les jalons : `u_time` ne lit que `time.lead_time_h` | Usine arrêtée 4 semaines → `P(jalon raté) = 0 %`, jalon effectivement raté | Router les événements vers la capacité et le **lead time effectif** ; faire dépendre le risque de jalon de l'avancement réel autant que du lead time nominal |
| 2 | Détecteur d'imminence, pas prédicteur | Orbitalys : 0 % pendant 4 tours, puis **100 % le jour de l'échéance** | Intégrer la dérive d'avancement et la marge consommée, pas seulement la marge résiduelle |
| 3 | Les chocs ne se propagent pas sur le DAG | Un fondeur s'arrête : son client **+0,6 pt**, son fournisseur **−0,2 pt** | Propager l'impact d'un événement en amont et en aval, comme le fait déjà l'urgence |
| 4 | Sortie instable | Un nœud passe de **99,6 % à 6,2 %** en trois tours, sur un jalon finalement tenu | Lissage temporel et/ou intervalle affiché ; un indicateur qui oscille de 6 à 100 % est inutilisable |

Ces quatre corrections sont **générales** : elles valent pour n'importe quelle supply
chain. Aucune n'est un ajustement sur HÉLIOS. C'est la condition pour que l'usine produise
des données qui veulent dire quelque chose.

**Critère de sortie de l'étape 1** : sur un cas de test unitaire, un arrêt d'usine de N
semaines doit faire monter `P(jalon raté)` du nœud concerné ET l'urgence de son client
direct, de façon monotone et stable.

---

## 2. L'usine — architecture d'une partie

### 2.1 Génération de la chaîne

- **Taille** : nombre de nœuds tiré uniformément dans **[4, 25]**, profondeur 2 à 6 rangs.
- **Topologie** : un client final (rang 0), arborescence de fournisseurs, quelques arcs
  de secours inertes (`ArcKind.BACKUP`) — ce sont eux qui rendront les actions possibles.
- **Base technique** : `RandomSupplyChainGenerator` et `SupplyScoreService.seed_demo(n_ranks, seed)`
  produisent déjà nœuds, arcs, KPIs, jalons, tags et première évaluation. Ne pas réécrire.
- **Reproductibilité** : tout dérive d'une graine unique inscrite au manifeste.

### 2.2 Choix de la crise — catalogue de crises réelles

Chaque partie rejoue une **crise historique réelle**, modélisée comme un scénario de jeu.
Chaque fiche de crise définit : le choc initial, sa date, sa durée, son mode de
propagation, ses précurseurs observables, et sa part strictement imprévisible.

| Crise | Année | Choc | Précurseurs observables |
|---|---|---|---|
| Blocage du canal de Suez (Ever Given) | 2021 | transport bloqué 6 j, effets 3 mois | congestion portuaire, taux de fret |
| Inondations de Thaïlande (disques durs) | 2011 | capacité mondiale −30 % | météo saisonnière, concentration géographique |
| Fukushima (composants auto/électronique) | 2011 | rupture brutale multi-tiers | dépendance mono-source |
| Restriction chinoise sur les terres rares | 2010 | quota export −40 % | tensions commerciales, stocks |
| COVID — équipements de protection | 2020 | demande ×10, capacité figée | signaux épidémiques précoces |
| Crise énergétique européenne | 2022 | coût énergie ×5, arrêts d'usines | prix spot gaz, stocks stratégiques |
| Lait infantile (fermeture Abbott) | 2022 | mono-source arrêtée | inspections qualité, concentration marché |
| Mer Rouge / reroutage | 2023 | +14 j de transit | assurance maritime, incidents |
| Éruption Eyjafjallajökull (fret aérien) | 2010 | fret aérien EU à l'arrêt 6 j | aucun — choc pur |
| Grève portuaire côte ouest US | 2014 | congestion 5 mois | négociations sociales publiques |

**Exclusion stricte** : la **pénurie de semi-conducteurs 2020-2022** est réservée à
HÉLIOS, la chaîne de test. Elle ne doit **jamais** servir à l'entraînement — sinon fuite
et résultat invalide.

**Point de conception essentiel** : chaque crise doit mêler une part **apprenable**
(précurseurs présents dans les KPIs) et une part **irréductiblement imprévisible** (choc
exogène). Sans la première, rien à apprendre. Sans la seconde, le modèle apprend une
fausse toute-puissance et n'exprimera jamais son ignorance — ce qui est dangereux en
production.

### 2.3 L'agent maître

**Rôle** : facilitateur et metteur en scène. Il reçoit du moteur le calendrier de la
partie (déjà tiré, vérité connue) et le déroule tour par tour.

Ce qu'il fait :
- pose le contexte initial (secteur, produit, enjeux contractuels, jalons) ;
- à chaque tour, rédige les **fiches de nœud** à partir des KPIs fournis par le moteur ;
- joue les voix extérieures : presse, clients, fournisseurs hors périmètre ;
- fixe le tempo et clôt les tours.

Ce qu'il ne fait **jamais** :
- inventer un événement, en déplacer un, en changer l'amplitude ;
- révéler à un nœud ce qui concerne un autre nœud ;
- laisser filtrer une date réelle ou le nom de la crise rejouée (les joueurs ne doivent
  pas pouvoir « reconnaître » la crise et jouer avec le recul historique).

**Contrôle automatique** : après génération, un test anti-fuite vérifie qu'aucune fiche ne
contient le nom d'un autre nœud, une date réelle, ou un terme du catalogue de crises.

### 2.4 Les agents de nœud

- **Un agent par nœud**, soit 4 à 25 par partie.
- **Bac à sable étanche** : chacun ne lit que son dossier (carte de rôle, instructions,
  ses propres fiches de tour, son historique de déclarations). Aucune sortie possible.
- **Carte de rôle** : décrit une **voix** (ton, vocabulaire métier, peurs, réflexes de
  crise) — jamais un niveau d'inquiétude. C'est ce qui garantit que l'urgence déclarée
  mesure un jugement et non une consigne.
- **Sortie par tour** (schéma figé, identique pour toutes les parties) :
  - `bipolar` : 6 comparaisons AHP par paires, entiers dans [−8, +8]
  - `scores_ui` : 4 notes de gravité, entiers dans [1, 6]
  - `cr`, `is_consistent`, `attempts`, `cr_echec` : contrôle de cohérence (CR < 0,10,
    2 tentatives, sinon report tracé)
  - `ud_raw`, `ud_smoothed` : urgence déclarée, lissée (ρ = 0,3)
  - `note` : une phrase à la première personne, dans le ton du rôle
  - `action_envisagee` + `influence_prediction` quand ces modes sont actifs

### 2.5 La boucle de tour

```
Pour chaque tour t de 0 à T (T ≈ 18) :
  1. moteur   : érosion hebdomadaire des effets d'événements
  2. moteur   : injection des KPIs, jalons et événements du tour (issus de verite.json)
  3. moteur   : recalcul complet de l'état (obligatoire — sinon la fraîcheur des
                prédictions varie selon les tours et fausse toute comparaison)
  4. maître   : rédaction et distribution des fiches, une par nœud
  5. nœuds    : déclaration (et action, selon le mode)
  6. moteur   : collecte, contrôle de cohérence, soumission
  7. moteur   : avance d'une semaine, écriture de l'instantané
```

### 2.6 Ce que la partie enregistre

| Fichier | Contenu |
|---|---|
| `verite.json` | calendrier des chocs, dates, amplitudes, crise source, graine — **écrit avant la partie** |
| `chaine.json` | topologie, arcs nominaux et de secours, jalons et échéances contractuelles |
| `tour_NN.json` | par nœud : Ud, Ur, adéquation, risque caché, blocs KPI, criticité |
| `declarations.jsonl` | une ligne par (nœud, tour) au schéma figé ci-dessus |
| `predictions.jsonl` | prévisions horizon 1 à 4 semaines, **journalisées même quand elles ne sont pas montrées** |
| `interventions.jsonl` | actions décidées / exécutées / résultat opérationnel (modes avec action) |

---

## 3. Volume et économie

Une partie de 15 nœuds × 19 tours = **285 tours d'agent**. À 200 parties, on atteindrait
57 000 tours d'agent : hors budget.

**Stratégie à trois étages** (déjà implémentée dans `projects/factory/declarants.py` et
`llm_farm.py`) :

| Étage | Qui déclare | Parties | Rôle |
|---|---|---|---|
| **T2** | agents LLM réels | **15 à 25** | capturer le comportement humain authentique |
| **T1** | modèle de comportement ajusté sur les traces T2 (ridge, AR(1), biais par persona) | **150 à 200** | amplifier à coût nul |
| **T0** | profils synthétiques simples | à volonté | remplissage et tests de robustesse |

Le modèle T1 n'est utilisé pour amplifier **que s'il passe un test de fidélité** contre
T2 : distributions d'urgence comparables (Kolmogorov-Smirnov), autocorrélation de même
ordre, taux d'échec de cohérence similaire. Sinon on augmente le quota T2.

**Cible** : ≈ 200 parties × ~12 nœuds × 19 tours ≈ **45 000 observations** étiquetées.

---

## 4. Entraînement du prédicteur

### 4.1 La cible

Une ligne = (partie, nœud, tour). L'étiquette est l'**issue défavorable** dans la fenêtre
(t, t+h] : jalon raté, nœud abandonné, ou événement de gravité critique — la définition
déjà en vigueur dans le service de calibration, et **une seule dans tout le système**.

Horizons h = 1, 2, 3, 4 semaines. Points censurés (fenêtre incomplète sans issue
observée) : **exclus**, jamais comptés comme négatifs.

### 4.2 Les variables — sans aucune identité

C'est la condition du transfert. Aucun identifiant de nœud, de chaîne ou de crise.

- **Locales** : urgence déclarée et réelle, adéquation, risque caché, fausse urgence,
  et les six blocs KPI (temps, capacité, performance, risque, coût, CO₂)
- **Dynamiques** : différences à 1-4 semaines, moyennes mobiles, temps écoulé depuis le
  dernier événement
- **Bayésiennes** : a posteriori Beta du taux d'incident du nœud (a priori de force 26)
- **Structurelles normalisées** : profondeur relative, degrés entrant/sortant, taille de
  chaîne en log, fraction de chaîne impactée par une défaillance du nœud
- **Voisinage à un saut** : urgence moyenne et maximale des fournisseurs directs, part de
  fournisseurs saturés, coefficient de transmission moyen
- **Simulation** : probabilité issue des rollouts Monte Carlo et dispersion d'ensemble

### 4.3 Modèle et validation

- **Primaire** : correction statistique des rollouts (post-traitement type EMOS) —
  `logit(p) = a·logit(p_simulé) + b·dispersion + c·variables_clés + d`, puis calibration
  isotonique. Petit modèle, donc transfert maximal.
- **Concurrents obligatoires** : rollout brut sans apprentissage, et modèle appris complet
  (régression logistique pénalisée, gradient boosting). Si le rollout brut gagne,
  l'artefact se réduit à la calibration seule — décision codée, pas discrétionnaire.
- **Trois axes d'évaluation**, avec réglage des hyperparamètres **uniquement** dans les
  plis d'entraînement :
  1. **chaînes jamais vues** (regroupement par partie) — le test du transfert
  2. **régimes jamais vus** (regroupement par jeu de paramètres du générateur)
  3. **temporel strict** (entraîner sur les premiers tours, tester sur les derniers)
- **Métriques** : score de Brier et gain sur la climatologie, aire sous la courbe ROC,
  aire sous la courbe précision-rappel (prioritaire vu le déséquilibre), diagramme de
  fiabilité.
- **Incertitude** : rééchantillonnage par chaînes pour produire un intervalle à 80 %.

### 4.4 Règle absolue de non-contamination

La calibration s'entraîne **sur l'usine** et s'applique **telle quelle** à HÉLIOS. Aucun
paramètre n'est jamais ajusté sur la chaîne de test. Le système doit valoir pour toute
supply chain, pas pour celle sur laquelle on l'a réglé.

---

## 5. Test sur HÉLIOS — trois bras

HÉLIOS (crise des semi-conducteurs 2020-2022, 8 nœuds, 19 tours, vérité terrain gelée,
KPIs ancrés sur des séries réelles) est la chaîne d'épreuve. Elle n'entre jamais dans
l'entraînement.

### Bras A — référence

Les personas déclarent sans aucune prédiction. **Déjà joué** : les données existent
(pilote LLM complet, 8 nœuds × 19 tours).

### Bras B — perception informée

Mêmes personas, mêmes fiches, **plus** l'analyse prédictive de leur propre nœud.
Boucle ouverte : ils déclarent, ils n'agissent pas, la réalité ne change pas — donc les
prédictions restent scorables contre la vérité gelée.

**Ce qu'on mesure** : la prédiction est-elle juste (Brier, ROC, fiabilité) ? Et être
informé change-t-il la perception (latence de réaction, écart Ud/Ur, champ
`influence_prediction`) ?

**Résultat de la campagne « avant réparation »**, à battre : le classement était bon
(ROC ≈ 0,64-0,74) mais les probabilités quatre fois trop basses, et huit personas sur
huit se sont **apaisés** deux tours avant le choc majeur.

### Bras C — liberté d'action, comme dans la vraie vie

Les nœuds reçoivent la prédiction **et** la main : ils peuvent modifier leurs KPIs,
promouvoir un fournisseur de secours, replanifier un jalon, expédier en express, négocier
une allocation, ou ne rien faire. Chaque action est réellement appliquée à l'état de la
chaîne et inscrite au journal d'interventions.

**Le piège à ne pas manquer** : dès que les nœuds agissent, la vérité de référence
n'existe plus. Une rupture évitée grâce à l'alerte fait passer une **bonne** prédiction
pour fausse. Le bras C ne se juge donc **pas** sur la précision des prédictions.

**Comment mesurer « quelles crises on a évitées »** — trois instruments combinés :

1. **Comparaison d'états finaux, C contre A** : mêmes crise, mêmes nœuds, même durée.
   On compte les jalons tenus, les ruptures subies, les pénalités encourues, le coût des
   actions engagées. C'est la mesure d'utilité, et la seule qui répond vraiment à la
   question.
2. **Contrefactuel apparié** : pour chaque action exécutée, le moteur rejoue la même
   semaine **sans** l'action, sur les **mêmes tirages aléatoires**. L'écart mesure l'effet
   de cette action précise, indépendamment de la chance.
3. **Modèle d'efficacité des actions** : le journal d'interventions alimente une
   estimation du taux de réussite par type d'action et par contexte, avec correction de
   la confusion (les opérateurs agissent d'abord sur les cas déjà graves) et une mesure
   de sensibilité à ce qu'on n'observe pas.

**Sortie attendue** — pour chaque nœud, une recommandation lisible et auditable :

> **Risque sans action : 29 %.** Risque avec action : **14 %**. Effet estimé : **−15 points**
> (source : simulation appariée, corrigée sur 7 interventions réelles). P(effet > 0) :
> **92 %**. Probabilité que l'action soit réellement exécutée : **85 %**. Probabilité
> d'éviter la rupture : **54 %**. Délai d'effet : 1 à 2 semaines. Valeur nette estimée :
> **[−2 k€, +41 k€]**. Niveau de preuve : **faible à moyen** — a priori simulé plus sept
> observations réelles.

---

## 6. Garde-fous scientifiques — non négociables

1. **Étanchéité des agents** : un nœud ne voit que son dossier. Contrôle automatique sur
   chaque fiche générée.
2. **Pas d'anticipation** : la fiche du tour suivant n'existe pas quand le nœud répond.
3. **Vérité écrite avant la partie**, jamais reconstruite après coup.
4. **HÉLIOS hors entraînement**, sans exception.
5. **Prédictions journalisées dans tous les bras**, y compris quand elles ne sont pas
   montrées — c'est ce qui rend les bras comparables.
6. **Neutralité de présentation** : la prédiction est proposée comme une information, pas
   comme une consigne ; « elle n'a rien changé » doit rester une réponse légitime, sans
   quoi on mesure la docilité et non l'utilité.
7. **Ignorance déclarée** : face à un choc qu'il ne peut pas prévoir, le modèle doit le
   dire. Afficher une probabilité basse d'allure confiante avant un choc exogène est pire
   que ne rien afficher — c'est vérifié : cela a désarmé la vigilance de huit opérateurs
   sur huit.
8. **Échelle de preuve explicite** dans tout rapport : ① fonctionnement sur données
   synthétiques ② généralisation à des chaînes tenues ③ rejeu historique réel
   ④ utilité opérationnelle constatée. Ne jamais présenter un niveau pour un autre.

---

## 7. Livrables et critères de réussite

| # | Livrable | Critère de réussite |
|---|---|---|
| 1 | Cœur réparé | Un arrêt d'usine fait monter le risque de jalon du nœud **et** l'urgence de son client, de façon stable |
| 2 | Catalogue de crises réelles | ≥ 10 crises, chacune avec précurseurs observables **et** part imprévisible assumée |
| 3 | Usine multi-agents | Une partie complète tourne de bout en bout, étanchéité vérifiée automatiquement |
| 4 | Jeu de données | ≈ 45 000 observations, taux d'incident réaliste, aucune variable d'identité |
| 5 | Prédicteur entraîné | Gain de Brier positif **et** précision-rappel supérieure au taux de base **sur les chaînes jamais vues** |
| 6 | Test HÉLIOS bras B | Comparaison avant/après réparation sur les mêmes données de référence |
| 7 | Test HÉLIOS bras C | Nombre de ruptures évitées par rapport au bras A, avec contrefactuel apparié à l'appui |
| 8 | Rapport | Chaque chiffre traçable à sa source ; limites énoncées avant les résultats |

---

## 8. Ordre d'exécution

```
1. Réparer le cœur              ← bloquant, rien ne sert de continuer sans
2. Écrire le catalogue de crises
3. Monter l'usine multi-agents (maître + nœuds)
4. Jouer 15-25 parties en LLM réel        → traces de comportement
5. Ajuster le modèle de comportement       → test de fidélité obligatoire
6. Amplifier à ~200 parties
7. Construire le jeu de données
8. Entraîner, calibrer, valider sur trois axes
9. Tester sur HÉLIOS : bras B, puis bras C
10. Rapport comparatif avant / après
```

**État au 27 juillet 2026** : les briques des étapes 3 à 8 existent et sont testées
(`projects/factory/`, `supplyscore/services/forecast.py`, `supplyscore/domain/actions.py`,
`supplyscore/services/interventions.py`). Aucun modèle n'a encore été entraîné, l'usine
n'a jamais tourné à l'échelle. Les mesures « avant réparation » sont conservées dans
`projects/simu_semiconducteurs/experiment/mesures_avant_reparation/`. **L'étape 1 est le
prochain chantier.**
