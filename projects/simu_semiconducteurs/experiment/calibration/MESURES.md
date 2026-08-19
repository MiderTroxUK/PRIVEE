# Couche de prévision — mesures consolidées

Toutes les valeurs de ce fichier sont **mesurées**, jamais estimées. Chaque
tableau dit sur quoi il a été mesuré et avec quel outil. Rien n'est supprimé :
les mesures périmées restent, datées, parce qu'une valeur abandonnée dit
pourquoi on a bifurqué.

Dernière mise à jour : 2026-08-19.

---

## 1. Progression du score, rejeu HÉLIOS gelé

Rejeu du bras A (déclarations humaines figées, seul le modèle change), scoré
contre la **cible endogène du produit** : jalon raté OU événement critique.
Outil : `mesures_avant_reparation/outils/score_endogene.py`.

| Horizon | skill AVANT | skill APRÈS | AUC AVANT | AUC APRÈS |
|---|---|---|---|---|
| 1 semaine | −1,278 | **−0,646** | 0,736 | **0,793** |
| 2 semaines | −0,690 | **−0,401** | 0,636 | **0,671** |
| 3 semaines | −0,654 | **−0,360** | 0,641 | **0,657** |
| 4 semaines | −0,553 | **−0,272** | 0,654 | **0,721** |

**Le déficit de Brier est divisé par deux à chaque horizon, et l'AUC monte
partout.** Le skill reste négatif : moins faux, pas encore bon.

### Décomposition de l'écart

| Étape | skill moyen | AUC moyenne | coût diagnostique |
|---|---|---|---|
| départ | −0,794 | 0,667 | 4,12 |
| + correctifs structurels | −0,562 | 0,730 | 2,00 |
| + KPI complets, λ calibré | **−0,420** | 0,710 | 2,00 |

Les correctifs et les données comptent chacun pour environ la moitié du gain.

---

## 2. Poids calés, et sur quelle preuve

Balayage sur 12 points de grille, campagne gelée, KPI complets.
Outil : `balayage.py`.

| Paramètre | Valeur retenue | Preuve |
|---|---|---|
| `LAMBDA_ARRET` | **1,0** | skill −0,420 contre −0,489 à 0,4 ; AUC 0,710 contre 0,707 |
| `RATTRAPAGE_HEBDO` | **0,0** | skill −0,420 contre −0,448 (0,15) et −0,490 (≥0,35) |

Les deux valeurs se défendent aussi **sans** la mesure : retenir moins que la
durée observée, ou supposer un rattrapage, sont deux hypothèses optimistes que
rien n'étaye. La mesure et la prudence pointent au même endroit.

> **Ordre important** : λ n'a d'effet que depuis que le retard s'ACCUMULE dans
> `time.delay_h`. Sous l'ancienne sémantique lissée, le balayage le trouvait
> indifférent. Une calibration ne vaut que pour le modèle sur lequel elle a été
> faite.

---

## 3. Couverture des indicateurs

Mesurée sur la base de campagne, 8 nœuds × 42 KPI.

| | avant | après |
|---|---|---|
| couverture globale | 25,6 % | **49,1 %** |
| KPI vides sur tous les nœuds | 24 / 42 | 20 / 42 |
| blocs d'urgence actifs | 3 / 6 | **6 / 6** |

Détail et justification de chaque valeur injectée : `KPI_INJECTES.md`.

---

## 4. La couche de calibration EMOS — entraînée, mesurée, PAS branchée

Artefact entraîné sur l'usine synthétique (`train_predictor.py`, 4 480 lignes
utilisables), exporté dans `models/latest/artifact.json`.

### Sur l'usine synthétique (sa cible d'entraînement)

| modèle | Brier | skill | AUC |
|---|---|---|---|
| rollout brut | 0,1269 | +20,3 % | 0,792 |
| **EMOS** | **0,1101** | **+30,8 %** | **0,850** |

### Sur HÉLIOS (la cible du produit) — le test qui tranche

Outil : `test_emos.py`, rejeu complet, cible endogène.

| Horizon | skill brut | skill calibré | AUC brute | AUC calibrée |
|---|---|---|---|---|
| 1 semaine | −0,646 | **−0,413** | 0,793 | 0,759 |
| 2 semaines | −0,401 | **−0,212** | 0,671 | 0,613 |
| 3 semaines | −0,360 | **−0,208** | 0,657 | 0,557 |
| 4 semaines | −0,272 | **−0,223** | 0,721 | **0,580** |

**Verdict : ne PAS brancher en l'état.** La couche améliore la calibration à
tous les horizons mais **dégrade l'AUC de 0,72 à 0,58** à 4 semaines. Elle
échange du classement contre du niveau — mauvais marché quand le classement est
justement ce que le modèle réussit.

### Pourquoi, et ce qu'il faut faire

L'artefact est entraîné sur `y1` = « un événement critique/défaut touche le nœud
exactement à t+1 ». Le produit affiche `p_issue_h4` = « jalon raté **OU**
événement critique, cumulé sur (t, t+4] ». **Horizon différent, cible
différente.** L'artefact ne peut pas classer les cas pilotés par le jalon : il
n'en a jamais vu.

C'est exactement le piège déjà identifié — *une évaluation contre la mauvaise
cible peut condamner un système qui fonctionne*, et symétriquement une
calibration contre la mauvaise cible peut dégrader un système qui fonctionne.

**Chantier restant, cadré** : `build_dataset.py` (contrat 4 gelé) doit émettre
un label alignant la cible d'entraînement sur celle du produit. Blocage
identifié : les snapshots de l'usine ne portent que `ur`/`ud`/`adequation`/
`blocs`/`forecast` — **pas la vérité jalon**. Il faut donc l'ajouter à l'écriture
des snapshots avant de pouvoir construire le label.

### Un gain déjà acquis

Deux des cinq features de l'artefact (`ur_local`, `d1_ur_local`) étaient
**imputées à leur moyenne d'entraînement** faute d'être journalisées — alors
qu'elles sont calculées deux lignes plus haut dans le harnais. Elles sont
désormais écrites dans `predictions_log.jsonl`. La calibration ne travaille plus
sur une information partielle.

---

## 5. Ce que la campagne en boucle fermée montre

Campagne `bras_c_complet` : 8 personas, modèles capables, aucune instruction
hors bac à sable, protocole de reprise sur échec de cohérence.

### La chaîne causale fonctionne — pour la composante événement

NovaFab au tour du choc (gel du Texas) :

| campagne | p_issue_h4 T5 → T6 | réaction du déclarant |
|---|---|---|
| avant correctifs | 0,092 → 0,166 | *« outil valide position basse malgré crise médiatisée »* → aucune action |
| **après** | 0,088 → **0,214** | *« l'outil bascule en Attention, cette fois c'est du concret »* → **replanifie son jalon** |

**Réserve honnête** : `p_jalon_rate` reste à 0,000 dans les deux cas au tour du
choc. Le retard accumulé vaut 154,7 h moteur contre 672 h de marge — le jalon
n'est réellement pas menacé. Le déclarant a agi sur `p_issue`, pas sur le jalon.
C'est la compression temporelle du scénario (1 tour = 1 mois réel), pas un
défaut du modèle.

### Le bloc jalon réagit quand l'avancement dérive

Orbitalys, échéance T8 :

| tour | p_issue_h4 | p_jalon | ce qui se passe |
|---|---|---|---|
| T4 | 0,190 | 0,120 | nominal |
| T5 | 0,098 | 0,026 | nominal |
| T6 | 0,052 | 0,000 | nominal |
| **T7** | **1,000** | **1,000** | avancement recule 88 % → 80 %, échéance dans 1 tour |

Vérifié à la main : il reste 20 % d'un cycle AIT de 39 semaines à faire en une
semaine de marge. **Le modèle a raison, et il alerte un tour avant.** Le
déclarant révise à la hausse (Ud 0,050 → 0,591) et engage une expédition express.

**Réserve** : 0,052 → 1,000 est une marche d'escalier, pas une rampe. L'opérateur
n'a aucun préavis graduel. À traiter côté interface.

### Le risque caché est détecté

Tour 3, avant toute prévision visible :

| nœud | Ur | Ud | adéquation | risque caché |
|---|---|---|---|---|
| **orbitalys** | 0,934 | 0,075 | **3,8 / 100** | **0,859** |

Le nœud de rang 0 est mesuré en danger extrême pendant que son responsable écrit
« dans les clous ». C'est la raison d'être de la comparaison des deux signaux —
et ce n'était **pas visible** avant la complétion des KPI, faute de données sur
ce nœud.

Vérification anti-saturation : `u_time = 0,76`, les cinq autres blocs
contribuent modestement, les sept autres nœuds ont `u_time = 0,00`. Pas
d'emballement.

---

## 5bis. La sur-confiance de P(jalon raté), et sa vraie cause

### Le symptôme, mesuré

Sur les 120 prévisions du rejeu gelé, `p_jalon_rate` sortait **exactement 0 ou
1 dans 95 % des cas** — 2 prévisions seulement dans la zone exploitable
(0,05–0,95). Ce n'est pas une probabilité, c'est un interrupteur.

Les déclarants l'ont dit avec leurs mots avant que je le mesure :

> *« l'outil affichait 0 % de risque de raté alors qu'un jalon vient d'être
> raté — je ne lui fais plus confiance sur ce point »* (AvioSys, T13)
>
> *« l'outil affiche 100 % à tous les horizons, un chiffre qui sonne faux »*
> (Électis, T13)

### Deux fausses pistes, écartées par la mesure

1. **σ mis à l'échelle linéairement.** Le travail restant est une somme
   d'incréments : sa variance décroît linéairement, donc σ en √(1−p), pas en
   (1−p). Le correctif est **statistiquement juste et a été gardé**, mais il est
   **SANS AUCUN EFFET MESURABLE** ici : scores et binarité identiques au
   millième près. À écrire tel quel — une correction juste n'est pas forcément
   une correction utile.

2. **Un piège de mesure, trouvé en route.** Le tirage de l'avancement était
   effectué même à σ = 0, consommant le générateur et décalant tous les tirages
   suivants. Deux mesures « avec » et « sans » n'étaient donc pas comparables,
   et ma première conclusion en était fausse. Corrigé : σ = 0 est désormais un
   vrai no-op, vérifié par égalité stricte des journaux.

### La vraie cause

Le rollout n'avait **qu'une seule source d'aléa** : le tirage du lead time.
L'échéance est fixe, le choc est fixe, et surtout **l'avancement du jalon
entrait comme une valeur EXACTE**.

Or l'avancement est une DÉCLARATION. C'est la grandeur la moins fiable du
dispositif — et c'est précisément celle que SupplyScore existe pour mettre en
doute. L'outil mesure l'écart entre urgence déclarée et urgence réelle parce
que les chiffres auto-déclarés sont optimistes, puis sa propre prévision
traitait le `progress` auto-déclaré comme une certitude.

### Le correctif et sa mesure

`SIGMA_AVANCEMENT` (défaut 0,10) bruite l'avancement déclaré par réplicat.

| σ | skill h4 | binarité | zone exploitable |
|---|---|---|---|
| 0 | −0,272 | 95,0 % | 2 / 120 |
| 0,10 | **−0,231** | **86,7 %** | **10 / 120** |

Le skill s'améliore de façon **monotone** sur 0 / 0,02 / 0,04 / 0,06 / 0,10.

**Réserve explicite** : l'AUC baisse en apparence (0,72 → 0,58 à 4 semaines),
mais son IC95 vaut [0,54 ; 0,92] avec 26 issues seulement. **L'écart est dans le
bruit et ne peut pas être affirmé** — le paramètre n'a donc PAS été réglé sur
l'AUC. Avec 90 points scorables, on ne règle rien sur une différence d'AUC.

### Ce qui reste ouvert sur ce point

86,7 % de binarité reste beaucoup. σ constant est un premier jet : l'historique
Ud/Ur d'un nœud dit déjà si ses déclarations sont optimistes, et devrait piloter
cet écart-type **nœud par nœud**. Un déclarant fiable mérite un σ plus étroit
qu'un déclarant optimiste — et cette information, l'outil la possède déjà.

---

## 5ter. Une classe de KPI qui manque

Plusieurs déclarants ont signalé la même chose, indépendamment :

> *« l'outil redonne encore 5,0 % comme les trois dernières semaines — il ne
> capte pas ce que je vois dans mon carnet »* (SilPure, T10, carnet plein
> jusqu'à fin 2022)

Le modèle mesure le flux COURANT (`network.demand`, `inventory.flow_rate`) mais
pas l'**horizon de réservation** — « ma capacité est vendue jusqu'à telle date ».
Dans la crise réelle, « capacités vendues jusqu'à fin 2022 » a été le signal le
plus prédictif de tous, et c'est structurellement invisible pour l'outil.

C'est un manque **général**, pas propre aux semi-conducteurs : tout maillon
contraint par un carnet a cette information, et elle précède de plusieurs mois
la dégradation des KPI de flux.

---

## 5quater. Le résultat final de la boucle fermée

La campagne complète (T0 → T18, 19 tours, 8 déclarants, 152 déclarations, aucun
échec de cohérence non résolu) se juge sur l'ÉTAT FINAL de la chaîne, pas sur la
précision des prévisions : dès que les personas agissent, une rupture évitée
grâce à l'alerte fait passer une bonne prévision pour fausse.

### Le chiffre brut, et pourquoi il trompe

Scénario gelé : **6 jalons ratés sur 11**. Boucle fermée : **0 non terminé**.

Ce 6 → 0 ne veut PAS dire « six jalons sauvés ». Le détail :

| jalon | gelé | boucle fermée | lecture |
|---|---|---|---|
| electis série B | raté (livré T14) | **tenu à T13** | **réellement sauvé** |
| orbitalys HÉLIOS-1 | raté (livré T14) | échéance 8 → 14, livré | glissement ASSUMÉ |
| aviosys lot 2 | raté | 11 → 12, livré | glissement assumé |
| aviosys lot 3 | raté | 16 → 18, livré | glissement assumé |
| novafab allocation | raté | 10 → 12, livré | glissement assumé |
| **compodis S1** | **tenu à T9** | **9 → 11**, livré | **replanifié pour rien** |

- **1 jalon réellement sauvé** — tenu à sa date d'origine alors qu'il était raté
  dans la vérité gelée.
- **4 glissements transformés en décalages ANNONCÉS À L'AVANCE** plutôt que
  découverts à l'échéance. Ce n'est pas « sauvé », mais ce n'est pas rien :
  un client prévenu six semaines avant n'est pas un client mis devant le fait
  accompli.
- **1 décalage INUTILE** : CompoDis a replanifié un jalon qu'il aurait tenu.
  C'est le coût de la sur-réaction, et il est mesurable.

### Ce que ça dit sur l'outil

Le bénéfice principal observé n'est pas la prédiction du raté, c'est
**l'anticipation du glissement**. Les déclarants ont utilisé `replanifier_jalon`
comme un aveu précoce plutôt que comme un échec tardif — et c'est le levier le
plus employé de la campagne.

Le coût, lui, est du même ordre que le bénéfice sur cet échantillon : un jalon
sauvé contre un jalon décalé pour rien. **Avec 11 jalons, aucune de ces deux
observations n'est statistiquement établie.** Ce sont des faits de campagne, pas
des résultats.

### Reconnaissance du scénario

Les déclarants ont identifié la reconstitution de la crise 2020-2022 aux tours
5 (Électis), 6 (CompoDis) et 7 (Orbitalys, AvioSys, TransGlobal) — tous sur la
même paire d'événements, tempête du Texas et blocage de Suez. Aucun n'a signalé
que cela ait changé sa façon de jouer, mais le fait doit être écrit : à partir
du tour 7, les déclarants savaient globalement où allait l'histoire.

### Réserve de validité interne

Le modèle a changé deux fois PENDANT cette campagne : σ en racine au tour 15
(sans effet mesurable) et incertitude d'avancement au tour 16. Les observations
comportementales qui comptent — désarmement au tour 4, réaction au choc du tour
6, alerte au tour 7, jalon sauvé au tour 11 — sont toutes ANTÉRIEURES à ces
changements. Les tours 16-18 ne sont pas comparables aux précédents.

---

## 6. Ce qui reste

1. **Ré-entraîner la calibration sur la cible du produit** — bloqué sur
   l'extension des snapshots de l'usine (vérité jalon). C'est le dernier
   verrou entre −0,27 et un skill positif.
2. **Déclarer l'ignorance dans l'interface.** Face à un choc exogène, afficher
   une probabilité basse d'allure confiante reste pire que ne rien afficher.
   Correction non mathématique, non implémentée.
3. **Lisser l'alerte de jalon.** Le passage 0,05 → 1,00 en un tour est correct
   mais inexploitable comme préavis.
4. **`RATTRAPAGE_HEBDO = 0` sur horizon long.** Le retard n'a plus aucun retour
   à zéro : un nœud accidenté porte sa pénalité indéfiniment. À revoir sur une
   campagne de plusieurs mois — le rattrapage réel se mesure, il ne se postule
   pas.

---

## 7. Transposition hors semi-conducteurs

Ce qui se transporte : la **méthode**. Mesurer la couverture KPI avant de
calibrer ; distinguer un paramètre de risque d'un état accumulé ; vérifier
qu'une couche de calibration prédit bien la même chose que ce qu'affiche le
produit ; calibrer sur une vérité terrain connue et appliquer tel quel.

Ce qui ne se transporte pas : les valeurs de `KPI_INJECTES.md`, ancrées sur la
crise des semi-conducteurs 2020-2022. Elles sont des données de scénario, pas du
modèle.

---

## 8. Mesures de référence pour les rapports — rejeu du 2026-08-19 (soir)

> Ajouté, rien de retiré. Les tableaux ci-dessus restent : ils décrivent des
> états intermédiaires du code. Cette section est la **seule** dont les chiffres
> ont été repris dans le MFE, la thèse Cranfield et le BST, et elle a été
> obtenue en rejouant la campagne gelée sur le code **tel qu'il est aujourd'hui**
> (λ = 1,0 ; rattrapage = 0,0 ; σ = 0,10 modulé par `hidden_risk` ;
> `COUT_CHOC_SEMAINE` = 1,0).

### Protocole exact, reproductible

```
python .../mesures_avant_reparation/outils/replay_a.py <dossier> 18
python .../mesures_avant_reparation/outils/score_endogene.py <dossier>/out/predictions_log.jsonl
```

Le second rejeu isole le correctif structurel en forçant
`SUPPLYSCORE_SIGMA_AVANCEMENT=0`.

### Les trois états du modèle, même cible, mêmes échantillons

Cible : **engagement initial** (jalon jugé sur l'échéance d'origine, points
censurés exclus). n = 112 / 104 / 96 / 90 ; positifs = 7 / 14 / 20 / 26.

| Horizon | skill gelé | skill structure | skill + incertitude | AUC gelé | AUC structure | AUC + incertitude |
|---|---|---|---|---|---|---|
| 1 sem. | −1,278 | **−0,646** | −0,687 | 0,736 | **0,793** | 0,729 |
| 2 sem. | −0,690 | −0,401 | **−0,367** | 0,636 | **0,671** | 0,634 |
| 3 sem. | −0,654 | −0,360 | **−0,286** | 0,641 | **0,657** | 0,602 |
| 4 sem. | −0,553 | −0,272 | **−0,216** | 0,654 | **0,721** | 0,584 |

**Lecture honnête, celle qui a été écrite dans les rapports :**

- Le **correctif structurel** améliore les DEUX axes à TOUS les horizons. C'est
  le seul résultat propre du lot : rien n'a été échangé contre rien.
- L'**incertitude d'avancement** est un troc. Elle gagne en calibration à
  h ≥ 2, en perd un peu à h = 1, et fait baisser l'AUC. Cette baisse **n'est pas
  interprétable** : l'IC95 de l'AUC à 4 semaines vaut [0,21 ; 0,87] avec 26
  positifs et contient toutes les valeurs de sa ligne.
- Le paramètre a donc été gardé sur la calibration et sur l'argument physique
  (un avancement déclaré n'entre pas dans une prévision comme une certitude),
  **jamais sur l'AUC**.

### Correction d'un chiffre publié plus haut

Le §5bis annonce une binarité de 95,0 % « sur les 120 prévisions du rejeu
gelé ». Mesuré directement sur le journal gelé
(`mesures_avant_reparation/bras_a_rejeu/predictions_log.jsonl`), c'est
**85,0 %** (102/120), zone exploitable 14/120. Les 95,0 % correspondaient à un
état intermédiaire du code, pas au journal gelé. Chiffres de référence :

| état | binaires (0 ou 1 exacts) | zone (0,05 ; 0,95) | prévisions ≥ 0,5 à h4 |
|---|---|---|---|
| gelé | 102 / 120 (85,0 %) | 14 | 21 (moy. 0,948) |
| structure seule | 89 / 120 (74,2 %) | 10 | 10 (moy. 1,000) |
| structure + incertitude | **86 / 120 (71,7 %)** | **17** | 10 (moy. 0,958) |

Le correctif structurel enlève des fausses certitudes sans créer de nuances
(zone 14 → 10) ; c'est l'incertitude d'avancement qui élargit la zone
exploitable (10 → 17).

### La preuve mécanique du bloc aveugle

C'est la formulation la plus forte du diagnostic, et elle ne dépend d'aucun
choix de scoring :

| | `time.delay_h` non nul | max atteint |
|---|---|---|
| campagne gelée, 8 nœuds × 41 snapshots | **0 fois** | 0,0 h |
| après correctif, NovaFab | 27 snapshots / 41 | **371,2 h** |

Les autres nœuds restent à 0 : ils ne portent aucun événement d'arrêt de
capacité, ce qui est correct.

### La cible : trois définitions, et l'écart entre elles

Même journal gelé, horizon 4 semaines, même modèle :

| définition de l'issue | n | taux de base | AUC | skill |
|---|---|---|---|---|
| production (échéance courante) | 120 | 0,050 | 0,485 | −3,36 |
| naïve (tout événement) | 75 | 0,387 | 0,484 | −0,64 |
| **engagement initial**, censurés exclus | 90 | 0,289 | **0,654** | **−0,55** |

La définition de la vérité déplace le skill d'un facteur 6 et l'AUC du hasard à
0,654, **sans qu'une ligne du modèle ne change**. La troisième est celle
retenue : une replanification est l'aveu d'un glissement, donc une vérité où le
re-datage efface le raté juge la prévision sur l'issue qu'elle devait justement
annoncer.

Conséquence sur la queue confiante : **0/21** sous la cible production,
**5/21** sous l'engagement initial (T8 et T9 NovaFab, T10 et T15 AvioSys, T12
Orbitalys).

### Les jalons, jugés sur l'engagement initial

Onze jalons ont une échéance d'origine dans la campagne (sept sont à T20–T22,
donc non observables). Résultat :

| | tenus à la date d'origine |
|---|---|
| scénario gelé (bras A) | **5 / 11** |
| boucle fermée (bras C) | **5 / 11** |

La boucle change **quel** jalon est tenu, pas **combien** : électis série B
sauvé, compodis S1 replanifié pour rien. Le « 6 ratés → 0 non terminé » du
§5quater est vrai et trompeur, parce qu'il compte les échéances replanifiées.

### État de la suite de tests

`pytest -q -p no:randomly` : **2 028 passés, 1 échec, 15 ignorés** sur 2 044
collectés (1 831 fonctions `def test_` dans 106 fichiers). L'échec unique est
`test_docs_coherence.py::test_liens_relatifs_existent`, pré-existant et sans
rapport : `docs/Presentation script.md` référence deux captures d'écran
absentes du disque (`presentation/screenshots/18-schema-strates.png` et
`19-architecture-donnees.png`).

Sans `-p no:randomly`, trois tests de démo échouent par intermittence : l'ordre
aléatoire fait fuiter un état partagé entre fixtures. C'est un défaut des tests,
pas du modèle, et il est traité séparément.

### Constantes du modèle vérifiées contre le code (pour les rapports)

| affirmation des documents | source | verdict |
|---|---|---|
| 6 blocs d'urgence | `ur_model.BLOCKS` | exact |
| `Ur = 1 − Π (1 − u_m)^ω_m` | `ur_model.ur_local` | exact |
| `u_risk` = p(panne) × temps de récup. × sévérité | `ur_model.u_risk` | exact |
| 4 critères AHP | `core/ahp.py` | exact |
| λ_sous = 2,25 ; λ_sur = 1,0 ; α = 0,88 | `core/adequation.py` | exact |
| n₀ = 26 pseudo-observations | `domain/events.py` | exact |
| 14 types d'événements calibrés | `events._HANDLERS` | exact |
| 12 événements dans le scénario | `scenario.EVENTS` | exact |
| Orbitalys A = 15,3 pour Ud 0,409 / Ur 1,000 | `adequation_asym` → 15,3355 | exact |
| 73 modules / 10 paquets / 106 fichiers de test | arborescence | exact |
| **1 779 tests automatisés** | ancien décompte | **périmé → 1 831** |
| **65 modules / 1 425 tests** (BST) | ancien décompte | **périmé → 73 / 1 831** |

### Une incohérence entre deux chaînes de mesure, non résolue

Le BST rapporte pour HA4 `TP=0 FP=2 TN=105 FN=37` (source :
`analysis/llm_pilot_run/rapport_pilot.md`, produit par `analyse_campagne.py`).
Le service de calibration de production, lu sur `db_arm_a`, donne pour la même
hypothèse `VP=0 FP=3 FN=8 VN=141` sur 152 nœud-semaines à 4 semaines.

Les deux verdicts coïncident (précision et rappel nuls), mais les matrices sont
très différentes : `analyse_campagne.py` n'applique manifestement pas la même
définition d'issue que `CalibrationService.outcomes`. **À trancher avant de
publier les deux chiffres côte à côte.** Ils ne le sont pas aujourd'hui : le BST
cite le pilote, la thèse cite le service de production, et chacun le dit.

---

## 9. Seconde passe de vérification documentaire — 2026-08-19 (nuit)

> Balayage exhaustif des affirmations des trois rapports contre le code, au-delà
> des chiffres de campagne déjà couverts au §8.

### 9.1 Ce qui a dérivé : l'indice de criticité

Le code a gagné un **départage en log-survie** que les trois documents
ignoraient, et qui répond précisément à une limitation qu'ils présentaient comme
ouverte.

| affirmation des documents | code réel | verdict |
|---|---|---|
| tri = ΔUr_final, puis **ΔUr_max**, puis nom | tri = ΔUr_final, puis **Δℓ_final**, puis nom | **faux, corrigé** |
| « l'indice dégénère en saturation réseau » (limitation ouverte) | dégénérescence **traitée** par Δℓ | **périmé, corrigé** |
| criticité probabiliste | **absente des trois documents** | **manque, ajouté** |
| couche de prévision (rollout, AR(1), Beta, bootstrap) | **jamais décrite** dans la thèse | **manque, ajouté** |
| « le bras C est conçu mais non exécuté » (Méthodes de la thèse) | exécuté en version agents | **périmé, corrigé** |

Mécanique vérifiée : ℓ(p) = −ln(1−p) sur un jumeau ε-régularisé
(`_EPS_SAT = 1e-9`, valeurs clipées à 1−ε, facteurs de survie jamais nuls),
`graph/propagation.py::simulate_shock_detailed` → `ShockDetail.delta_ell`.
Invariant testé : `tests/property/test_prop_delta_ell.py` —
hors saturation, le classement par Δℓ_final est **identique** à celui par
ΔUr_final (ℓ strictement croissante, référence commune au client final).

### 9.2 La mesure : H3 redevient mesurable

Outil : `h3_delta_ell.py` (scratchpad), sur les snapshots par tour.
Leader parmi les fournisseurs profonds {novafab, meridian, silpure}.

| | tours informatifs / 19 | novafab top-1 |
|---|---|---|
| pilote gelé, critère ΔUr seul | 10 | 7 → **70 %** |
| rejeu réparé, critère ΔUr seul | 10 | 9 → **90 %** |
| rejeu réparé, **ΔUr puis Δℓ** | **17** | 16 → **94 %** |

**Décomposition propre :**

- *Effet du seul critère* (mêmes données, rejeu réparé) : 10 → 17 tours
  informatifs, 90 % → 94 %. **Δℓ récupère 7 des 9 tours saturés.**
- *Effet du seul modèle+KPI* (critère ancien figé) : 70 % → 90 %, tours
  informatifs inchangés à 10.

**Réserve écrite dans les trois documents** : ce n'est **PAS** un verdict H3.
H3 est pré-enregistrée sur la campagne gelée avec le code d'alors ; rejouer une
hypothèse sur un modèle modifié ne teste plus ce que le registre demandait. Deux
choses ont changé à la fois, et seule la première est isolée proprement. Ce qui
est défendable : la dégénérescence qui rendait la moitié de la campagne
illisible a largement disparu, et la grandeur testée par H3 passe son seuil de
80 % sur le système réparé.

### 9.3 Constantes et structures vérifiées cette passe (toutes exactes)

| affirmation | source vérifiée |
|---|---|
| 4 critères AHP, libellés exacts | `core/ahp.CRITERIA` |
| seuil de cohérence CR < 0,10 | `ahp.CONSISTENCY_THRESHOLD = 0.10` |
| lissage EMA de Ud, ρ = 0,3 | `ahp.ud_smoothed(rho=0.3)` |
| échelle linguistique BWM : 5 jugements, TFN jusqu'à 4,5 | `mcda/fbwm.ECHELLE_LINGUISTIQUE` |
| défuzzification GMIR (l + 4m + u)/6 | `fbwm._gmir` |
| repli silencieux sur poids uniformes | `fbwm` (documenté et implémenté) |
| PROMETHEE II : fonction de préférence Type V par défaut | `mcda/promethee` |
| WAL, integrity_check avant archivage, `sqlite3.backup` natif | `data/backup.py` |
| sauvegardes toutes les 24 h, rétention 20 archives | `backup.RETENTION_DEFAUT = 20`, `max_age_h = 24.0` |
| export Excel à **12 onglets** | `services/exports._build_sheets` : 4 + 7 + 1 |
| tous les chemins de module cités | 13/13 existent |
| K = 20 tirages externes, n = 2000 trajectoires, h = 4 | `services/forecast.K_EXTERNES`, défauts |
| `p_issue` = issue de `CalibrationService` (jalon raté OU événement grave) | équivalence figée, docstring `forecast.py` |

### 9.4 Sévérités de la criticité probabiliste (ajoutées aux documents)

Tirées de `EVENT_CALIBRATION`, deux familles à poids égal, gravité pondérée par
fréquence terrain décroissante (0,6 / 0,3 / 0,1) :

| famille | mineure | intermédiaire | critique |
|---|---|---|---|
| accident / panne | 0,4 | 0,7 | 1,0 |
| alerte financière | 0,3 | 0,6 | 0,9 |

Choc en **cliquet** — `max(ur_local, sévérité)` — même sémantique que le moteur
d'événements : une défaillance n'améliore jamais l'état. Sorties :
`p_impact_final = P(ΔUr_final > 0,2)`, `q50_ell`, `q90_ell`. Lecture seule,
seedée, déterministe.

### 9.5 Ambiguïté levée, pas corrigée

« 18 tours de jeu » (conception, 2 tours/jour × 9 jours) contre « 19 tours »
(exécution, T0 à T18). Les deux sont vrais : T0 porte les premières
déclarations, les 18 actes suivent. Une phrase l'explicite désormais dans le
BST plutôt que de laisser le lecteur arbitrer.

### 9.6 Ce qui reste, et que je n'ai pas tranché

1. **`docs/Presentation script.md`** référence deux captures absentes
   (`presentation/screenshots/18-schema-strates.png`,
   `19-architecture-donnees.png`) — seul échec de la suite de tests.
   Candidats plausibles dans le dépôt :
   `BST_DISCO_JH_2026/Images/2.Problem/three_layer_architecture.png` et
   `BST_DISCO_JH_2026/Images/4.Operations/uml_architecture.png`. Repointer les
   liens est une décision éditoriale : **non faite**.
2. **HA4 : deux chaînes de mesure divergentes** (cf. §8) — toujours ouvert.
3. **`services/forecast.py`** porte des modifications non attribuées
   (`COUT_CHOC_SEMAINE`, `porte_retard`, `completion_base`) que les documents
   décrivent désormais. À vérifier avant commit.

---

## 10. Le résultat qui manquait : le ciblage par NŒUD — 2026-08-19

> Outil : `risque_cache_par_noeud.py`. C'est la mesure qui a fait réorienter le
> MFE et la thèse, et elle était sous nos yeux depuis le début.

### La bonne question

Tout le scoring de la campagne évalue la maille **(nœud, semaine)** sur une
fenêtre de 4 semaines : « le nœud X subira-t-il une issue défavorable entre t+1
et t+4 ? ». Ce n'est pas la question d'un coordinateur. La sienne est :
**« lequel de mes fournisseurs dois-je regarder cette semaine ? »**

C'est une question sur des NŒUDS, pas sur des nœud-semaines. Le signal y répond,
et bien.

### Protocole

À chaque tour, nœuds classés par risque caché H = [Ur − Ud]+ ; ensemble signalé
(H > 0,10) confronté à l'ensemble des nœuds qui rateront un jalon à son échéance
**contractuelle**. 4 nœuds sur 8 sont positifs : orbitalys, aviosys, electis,
novafab. Rien n'utilise la couche de prévision.

### Résultat, bras A GELÉ (le modèle d'origine, pré-enregistré)

| tours | signalés | précision | rappel | fausses alertes |
|---|---|---|---|---|
| **T0 → T5** | aviosys, electis, orbitalys | **1,00** | **0,75** | **0** |
| T6 → T18 | variable | ≤ 0,50 | 0,25 | 1 à 3 |

**Six tours consécutifs, précision parfaite, zéro fausse alerte.** Les trois
nœuds signalés sont trois des quatre futurs défaillants. Le quatrième (novafab)
n'est jamais signalé tôt — d'où un rappel plafonné à 3/4.

Et sur chacun de ces six tours, **le nœud le plus mal noté est orbitalys**, qui
rate son jalon T8 et ne livre qu'à T14 : le signalement précède le raté de
**huit tours**, alors qu'orbitalys déclare une urgence de **0,001**.

### Pourquoi ça s'éteint après T6 — et pourquoi ce n'est PAS un défaut

Quand la crise devient publique, tous les déclarants montent leur urgence, Ud
rattrape Ur, et une grandeur définie comme [Ur − Ud]+ **se referme par
construction**. Une mesure d'écart de perception ne peut pas survivre à la
disparition de l'écart de perception.

Ce n'est donc pas une limite à réparer, c'est un **périmètre à écrire** :
l'outil est un instrument d'**alerte précoce**, pas de gestion de crise. Et il
est au plus net exactement là où une alerte vaut encore quelque chose.

### Ce que la réparation change ici : la lisibilité, pas l'ordre

| tour 3, orbitalys | adéquation | nœud suivant | écart |
|---|---|---|---|
| campagne telle que jouée | 26,6 / 100 | 46,0 | ×1,7 |
| après réparation + KPI complets | **2,2 / 100** | 44,6 | **×20** |

Les nœuds signalés sont **les mêmes**. Ce qui change est la séparation : un
nœud à 26,6 dans un champ dont le suivant est à 46,0 est une anomalie qu'un
analyste attentif remarque ; à 2,2 contre 44,6, aucun tableau de bord ne peut
la masquer.

### Portée statistique — à écrire à chaque fois

8 nœuds, 4 positifs, 1 scénario. Une précision de 1,00 tenue sur six tours avec
trois nœuds signalés est une **observation encourageante, pas un taux estimé**.
Avec 4 positifs, aucun intervalle de confiance ne vaut la peine d'être imprimé.

C'est exactement l'argument « il faut plus de données » : ce n'est pas le modèle
qu'il faut changer, c'est le nombre de chaînes sur lesquelles on le fait tourner.

---

## 11. Les affirmations du résumé d'origine, vérifiées une à une

| affirmation | verdict | preuve |
|---|---|---|
| « ne discrimine pas mieux que le hasard » | **dépend de la cible, et sous-dimensionné** | AUC 0,372–0,555 sous la cible production (IC contiennent 0,5) mais **0,654–0,736** sous l'engagement initial. 2 à 6 positifs : indécidable dans les deux sens. |
| « fortement mal calibrée » | **VRAI, robuste** | skill négatif sous les trois cibles, et encore −0,216 après réparation. Seule affirmation qui survit intacte. |
| « 21 prévisions à 0,948, suivies de l'issue **aucune** fois » | **VRAI sous la cible production, FAUX sous l'engagement initial** | 0/21 contre **5/21**. Le « aucune fois » vient du fait qu'une échéance replanifiée cesse de compter comme ratée. |
| « un seul bloc l'explique : le bloc temporel lit une grandeur qu'aucun choc n'atteint » | **VRAI, et mieux prouvé qu'avant** | `time.delay_h` écrit non nul **0 fois** sur 8 nœuds × 41 snapshots. Depuis : **réparé**. |
| « les huit déclarants ont revu à la baisse ou maintenu, deux tours avant l'événement critique » | **VRAI, exact** | T4 : 5 baisses, 3 confirmations, 0 hausse. Événement critique à T6. |

**Aucune n'est inventée.** Deux sont plus fragiles qu'annoncé, et toutes deux
pour la même raison : elles dépendent d'une définition de l'issue que le résumé
ne nommait pas.

Ce que le résumé d'origine **omettait**, et qui est le vrai résultat : le signal
d'adéquation désigne les bons nœuds, tôt, sans fausse alerte (§10).

---

## 12. Banc d'essai V0 / V1 / V2, et la réponse au « et si la chaîne n'avait pas de choc ? »

> Outils : `banc.py`, `rejeu_bras.py`, `recalage.py`, `graphe_banc.py`,
> `pack_endogene.py`. Graphe : `docs/Thesis_Cranfield_JH_2026/Images/benchmark_horizon.png`.

### 12.0 Un bug qui rendait V0 impossible

`run_campaign.py --rollout` appelait `ForecastService.forecast_node`. Cette
méthode **n'existe pas** : le service expose `rollout(...)`. L'appel échouait à
chaque tour, et le `except Exception` « best effort » transformait la panne en
une ligne de journal. **La campagne synthétique n'a jamais produit une seule
prévision depuis la fusion de U9.**

Corrigé, et le piège avec : l'échec légitime (historique trop court aux
premiers tours) est journalisé et la campagne continue ; l'échec de
programmation (API absente) interrompt, puisque `--rollout` a été demandé.

### 12.1 LA mesure : décomposition endogène / exogène

Même journal, même modèle, trois définitions de l'issue. Rejeu V1 réparé :

| cible | AUC h1 | skill h1 | AUC h4 | skill h4 |
|---|---|---|---|---|
| **jalon** (endogène) | **0,822** | −0,779 | 0,602 | **−0,185** |
| **événement** (exogène) | **0,171** | **−9,460** | 0,387 | −4,907 |
| contrat (mélange, cible produit) | 0,729 | −0,687 | 0,584 | −0,216 |

**L'AUC de la part exogène est 0,17.** Ce n'est pas « imprévu », c'est
**anti-prédit** : le modèle met une probabilité PLUS BASSE là où le choc tombe.
C'est la signature attendue — un choc scripté frappe un nœud que le modèle
juge sain (c'est ce qui en fait un choc), et le modèle monte APRÈS coup.

**Réponse à la question posée** : oui, sur une chaîne sans choc exogène la
prévision serait nettement meilleure, et le chiffre le dit — la part que le
modèle peut voir venir score 0,82 d'AUC pendant que la part qu'il ne peut pas
voir venir score 0,17 et tire le mélange vers le bas.

### 12.2 L'horizon de 4 semaines était bien trop court

V0 synthétique, cible jalon, horizons 1 à 10 :

| h | 1 | 2 | 3 | 4 | 5 | **6** | 7 | **8** | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| skill | −1,79 | −0,55 | −0,27 | −0,15 | −0,03 | **+0,130** | +0,105 | **+0,174** | +0,129 | +0,063 |
| AUC | 0,943 | 0,853 | 0,780 | 0,741 | 0,727 | 0,766 | 0,775 | **0,813** | 0,827 | 0,816 |

**Le skill devient positif à h6 et culmine à h8.** Physiquement cohérent : les
jalons sont espacés de 5 à 8 tours et les lead times valent 12 à 25 semaines
réelles. Demander une fenêtre de 4 semaines, c'était demander au modèle de
DATER un glissement qu'il ne peut voir venir que sur un arc plus long.

L'horizon est désormais balayable par `SUPPLYSCORE_HORIZON_PREVISION`
(défaut 4, aucune mesure antérieure ne change).

### 12.3 Le banc V0 / V1 / V2

Cible jalon, meilleur skill atteint et AUC associée :

| | meilleur skill | à h | AUC à cet horizon | n |
|---|---|---|---|---|
| **V0** synthétique | **+0,174** | 8 | 0,813 | 84 |
| **V1** LLM aveugle | −0,127 | 6 | 0,717 | 78 |
| **V2** LLM + prévision | **+0,159** | 4 | 0,802 | 37 |

**Réserves à écrire à chaque fois.** V2 s'arrête au tour 11 (les données du
bras B s'arrêtent là) : à h ≥ 8 tous ses points sont positifs, le taux de base
vaut 1,0 et le score n'a plus de sens. V1 garde un skill négatif à tous les
horizons alors que son AUC monte jusqu'à 0,830 — dissociation classique entre
classement et niveau.

### 12.4 Le recalage post-hoc ne sauve PAS l'affaire — réfuté deux fois

Régression isotone, validation croisée **en laissant un nœud dehors** (le
recalage ne voit jamais le nœud sur lequel il est scoré) :

| h | skill brut | skill recalé | AUC brute | AUC recalée |
|---|---|---|---|---|
| 1 | −1,787 | **−0,302** | 0,943 | 0,951 |
| 4 | −0,149 | −0,255 | 0,741 | 0,661 |
| **8** | **+0,174** | **−0,066** | **0,813** | **0,646** |
| 10 | +0,063 | −0,153 | 0,816 | 0,651 |

Sauf à h1 — où le brut est grossièrement sur-confiant et où n'importe quel
écrasement monotone aide — le recalage **dégrade tout**, y compris le
classement. Avec 8 nœuds, une isotone ajustée sur 7 n'a rien appris de
transférable au huitième.

C'est la **deuxième** méthode de recalage réfutée après l'EMOS (§4). Deux
approches indépendantes, même conclusion : **à cette taille d'échantillon, une
couche de calibration ne généralise pas.** Le levier est l'horizon, pas le
recalage.

### 12.5 Le pack endogène : un résultat qui contredit l'attente, et pourquoi

`pack_endogene.py` construit HÉLIOS-E : pack officiel copié, **tous les
événements vidés**, deux fournisseurs (compodis, electis) dont le lead time
monte en rampe. Campagne complète jouée, 19 tours.

Résultat sur la cible produit, h8 : **skill +0,111, AUC 0,792** contre
**+0,174 et 0,813** pour le pack standard. Le pack sans choc est **légèrement
MOINS bon**.

**Pourquoi, et c'est le vrai enseignement** : la vérité jalon du harnais est
**scriptée** (`MILESTONE_DRIFT`, `MILESTONE_DONE` dans `scenario.py`), elle ne
DÉCOULE pas des KPI. J'ai donc dégradé le lead time de deux fournisseurs sans
que la vérité en tienne compte : j'ai fabriqué des faux positifs, et le scoreur
me l'a fait payer. C'est le comportement correct d'un scoreur honnête.

**Conséquence pour la campagne que vous voulez** : pour tester réellement « un
ou deux fournisseurs qui prennent du retard », il faut que **l'issue du jalon
découle de la trajectoire des KPI** au lieu d'être écrite à l'avance. Sinon on
injecte un signal que la vérité terrain ignore. C'est un chantier de scénario,
pas de modèle, et c'est identifié.

### 12.6 Ce que ça dit du chemin vers une prévision qui marche

Trois choses, toutes mesurées :

1. **Allonger l'horizon à 6-8 semaines** — le seul levier qui rende le skill
   positif, sans rien changer au modèle.
2. **Séparer les deux natures d'issue** dans ce que le produit affiche. Mélanger
   une part prédictible (AUC 0,82) et une part anti-prédite (AUC 0,17) sous un
   seul chiffre, c'est garantir un mauvais chiffre.
3. **Ne pas compter sur un recalage post-hoc** à cette échelle : réfuté deux
   fois, en validation honnête les deux fois.

### 12.7 σ redevient indifférent une fois l'horizon correct

Balayage `SUPPLYSCORE_SIGMA_AVANCEMENT` sur V0, cible jalon, h = 8 :

| σ | skill h8 | AUC h8 | skill h4 | AUC h4 |
|---|---|---|---|---|
| 0 | +0,180 | 0,802 | −0,150 | 0,700 |
| 0,10 | +0,174 | 0,813 | −0,149 | 0,741 |
| 0,20 | +0,174 | 0,804 | −0,137 | 0,756 |

À h8, les trois valeurs sont indiscernables. L'incertitude d'avancement gagnait
sur les horizons COURTS, là où la binarité de `p_jalon_rate` faisait mal. Une
fois l'horizon porté à la bonne échelle, elle ne sert plus à rien — elle
compensait un horizon trop court.

Elle reste gardée pour l'argument physique (un avancement déclaré n'est pas une
certitude) et parce qu'elle aide à h3-h4, qui restent les horizons affichés par
défaut. Mais il faut écrire que **ce n'est pas elle qui fait le résultat**.

---

## 13. La vérité jalon dérivée des KPI — et la première prévision qui marche

> Outils : `verite_derivee.py`, `pack_endogene.py`, `banc.py --pack`,
> `recalage.py --pack`, `graphe_endogene.py`.
> Figure : `docs/Thesis_Cranfield_JH_2026/Images/benchmark_endogene.png`.

### 13.1 La règle, et pourquoi elle n'a aucune constante ajustée

Pour un jalon partant au tour `s` avec échéance d'origine `d`, le rythme
**nominal** vaut `r0 = 1/(d − s)` par tour. La santé du tour le module :

```
progrès_t = min(progrès_{t−1} + r0 × santé_t , 1)
santé_t   = clip( (L0/Lt) × (OEE_t/OEE_0) × (1 − perte_t) , 0 , plafond )
```

Chaque facteur vaut **1 au nominal**, donc `santé = 1` fait atteindre exactement
1,0 au tour `d` : ni avant, ni après. **La règle est calibrée par construction**,
sans une seule constante réglée à la main. Un fournisseur dont le lead time
double avance deux fois moins vite et rate son échéance — c'est la physique
qu'on voulait, et c'est désormais LA vérité.

Aucune replanification n'est émise : replanifier est une **décision**, pas une
physique. Échéance contractuelle et échéance courante coïncident donc dans un
pack dérivé — ce qui supprime au passage toute l'ambiguïté de cible du §11.

### 13.2 Vérification : la règle ne casse rien et fait rater qui doit rater

Pack HÉLIOS-E, quatre fournisseurs qui dérivent à des dates et vitesses
différentes (compodis T1, transglobal T2, electis T3, silpure T5) :

| nœud | jalon | échéance | achevé | verdict |
|---|---|---|---|---|
| orbitalys | HÉLIOS-1 | 8 | **T8** | tenu |
| orbitalys | HÉLIOS-2 | 16 | **T16** | tenu |
| aviosys | lot 1 / 2 / 3 | 6 / 11 / 16 | **T6 / T11 / T16** | tenu |
| novafab | allocation | 10 | **T10** | tenu |
| **electis** | série A | 6 | T7 | **RATÉ** |
| **electis** | série B | 13 | T15 | **RATÉ** |
| **compodis** | couverture S1 | 9 | T12 | **RATÉ** |
| **transglobal** | flux annuel | 12 | jamais | **RATÉ** |
| **silpure** | contrat annuel | 15 | jamais | **RATÉ** |

**Les six nœuds sains tiennent leurs échéances au tour près.** Seuls les
quatre qui dérivent ratent. 5 ratés sur 11 observables, répartis sur 4 nœuds et
sur les tours 6 à 15 — un échantillon qui a une chance de vouloir dire quelque
chose.

### 13.3 Le résultat : skill POSITIF, et classement conservé

Campagne complète jouée sur ce pack, scorée contre **sa propre** vérité
(`banc.py --pack`), recalage isotone validé **en laissant un nœud dehors** :

| h | n | pos | skill brut | AUC brute | **skill recalé** | **AUC recalée** |
|---|---|---|---|---|---|---|
| **1** | 126 | 5 | −4,012 | 0,913 | **+0,126** | **0,881** |
| **2** | 119 | 10 | −1,691 | 0,846 | **+0,098** | **0,765** |
| **3** | 112 | 15 | −1,171 | 0,727 | **+0,013** | 0,604 |
| 4 | 104 | 20 | −0,864 | 0,610 | −0,345 | 0,422 |
| 6 | 90 | 28 | −0,720 | 0,432 | −0,596 | 0,237 |

**C'est la première configuration du projet où le skill est positif ET le
classement tient.** Le modèle ordonne presque parfaitement à une semaine
(AUC 0,913) et annonce le mauvais niveau ; une carte monotone corrige le niveau
sans casser l'ordre, sur des nœuds que le recalage n'a jamais vus.

### 13.4 Deux régimes, deux prescriptions OPPOSÉES

C'est le résultat le plus utile de la série, et il n'était pas prévisible :

| chaîne | horizon à retenir | recalage | skill | AUC |
|---|---|---|---|---|
| **avec chocs exogènes** (HÉLIOS) | **6 à 8 semaines** | **non** | +0,174 | 0,813 |
| **endogène** (dérive fournisseur) | **1 à 3 semaines** | **oui** | +0,126 | 0,881 |

Pourquoi opposées :

- **Avec chocs**, la part exogène est anti-prédite (§12.1). Allonger l'horizon
  la dilue dans la part endogène et laisse le signal jalon dominer. Le recalage
  échoue parce que le classement brut n'est pas assez bon pour qu'une carte
  monotone ait de quoi s'accrocher.
- **En endogène**, la dérive est visible tôt et le classement à court horizon
  est excellent (0,91). Le recalage a de la matière. Mais **allonger l'horizon
  détruit tout** : sur une chaîne purement endogène, tout fournisseur qui dérive
  finit par échouer, l'issue devient quasi certaine partout, et il n'y a plus
  rien à ordonner. L'AUC passe sous 0,5 dès h5.

**Conséquence produit** : l'horizon affiché ne peut pas être une constante. Il
dépend de la nature des risques de la chaîne — ce qui est une propriété
mesurable de l'historique d'un projet, pas un réglage arbitraire.

### 13.5 Réserves, à écrire à chaque fois

- **5 positifs sur 11 jalons observables, 8 nœuds, un scénario.** Un skill de
  +0,126 sur 5 positifs est un signe encourageant, pas un taux.
- Le recalage est validé en laissant un nœud dehors, ce qui est honnête, mais
  avec 4 nœuds porteurs de positifs chaque pli est mince.
- La dérive est une rampe linéaire. Une dégradation réelle est plus
  irrégulière, et rien ne dit que le modèle tiendrait aussi bien dessus.
- Le premier pack endogène (§12.5, deux fournisseurs, vérité SCRIPTÉE) donnait
  un résultat **inverse**. La différence tient entièrement à la vérité : tant
  qu'elle ne découlait pas des KPI, dégrader un fournisseur ne faisait que
  fabriquer des faux positifs. **La leçon est de méthode, pas de modèle.**

---

## 14. Faire voir venir : la pente, et le bug qui l'interdisait

### 14.1 Le défaut de modèle

`resoudre_loi` lit `node.kpis.time` — un **instantané**. Dans le rollout,
`completion_base = t + lead_time × reste` est calculé **une fois** avant la
boucle hebdomadaire et ne bouge plus. Un fournisseur dont le cycle s'allonge de
30 h par semaine est donc projeté comme s'il restait stable indéfiniment.

**Le modèle voyait le NIVEAU d'un KPI et jamais sa DÉRIVÉE.** Or une
dégradation progressive est précisément le seul type de dégradation qu'on
puisse voir venir.

### 14.2 Le bug qui rendait le correctif impossible

En implémentant la pente, l'estimateur est sorti à **zéro partout**. Cause :

| histoire | horloge utilisée | étendue sur 19 tours | semaines ISO |
|---|---|---|---|
| `urgency_history` | **projet** (`clock_for`) | 133 jours | 20 |
| `kpi_snapshots` | **service** (n'avance jamais) | **0,0 jour** | **1** |

`MutationService` recevait `clock=self.clock`, l'horloge du **service**, alors
que tout le reste du système horodate à `clock_for(project_id)`, l'horloge du
**projet**. Les 43 snapshots KPI d'un nœud portaient donc tous l'instant
d'origine.

**L'historique KPI existait en lignes, pas en temps.** Deux conséquences, toutes
deux réelles :

1. Aucune analyse temporelle des KPI n'était possible — la pente était
   structurellement inestimable.
2. **`kpis_at(node_id, t)` était fausse pour tous ses appelants**
   (`services/weekly.py`, `web_ui/pages/weekly.py`), qui lui passent un lundi en
   temps projet. La « valeur précédente » affichée dans la revue hebdomadaire ne
   bougeait jamais.

Corrigé : `MutationService` reçoit un résolveur `clock_for` et horodate le
snapshot à l'horloge du projet du nœud. Repli explicite sur l'horloge de service
pour les appelants qui n'en fournissent pas. **2 028 tests passent**, seul
l'échec pré-existant des captures manquantes subsiste.

### 14.3 Le correctif de tendance, et sa mesure honnête

Pente hebdomadaire du lead time estimée par moindres carrés sur l'historique du
nœud, extrapolée dans la boucle avec amortissement géométrique et plafonnée à
2× le lead time courant. Piloté par `SUPPLYSCORE_TENDANCE_LEAD_TIME`
(**défaut 0,0 = désactivé**, no-op vérifié à l'octet près sur un rejeu complet).

Campagne endogène, cible produit, g = 0,8 :

| h | AUC sans | AUC avec | skill sans | skill avec |
|---|---|---|---|---|
| 1 | 0,913 | 0,913 | −4,012 | −4,042 |
| 2 | 0,846 | 0,846 | −1,691 | −1,671 |
| 3 | 0,727 | **0,733** | −1,171 | **−1,118** |
| **4** | 0,610 | **0,647** | −0,864 | **−0,811** |
| **5** | 0,491 | **0,523** | −0,790 | **−0,738** |
| 6 | 0,432 | **0,461** | −0,720 | **−0,669** |

Le gain tombe exactement où il doit : nul à h1-h2, où le cumul de pente vaut
1,0 puis 1,8 et ne change rien ; croissant à partir de h3, où l'extrapolation
mord. **À h5, l'AUC repasse au-dessus du hasard (0,491 → 0,523).**

### 14.4 Ce que la tendance ne fait PAS — à écrire

Préavis d'alerte (premier tour où `p_issue_h4 > 0,5` avant l'échéance) :

| nœud | échéance | 1re alerte | préavis |
|---|---|---|---|
| electis | T13 | T5 | **8 tours** |
| compodis | T9 | T7 | 2 tours |
| silpure | T15 | T13 | 2 tours |
| transglobal | T12 | T11 | 1 tour |

**Moyenne 3,2 tours, 4 nœuds défaillants sur 4 alertés avant leur échéance.**

Et ce tableau est **rigoureusement identique avec et sans la tendance.**

Donc, en toute rigueur : la tendance améliore le **classement** aux horizons
moyens, elle ne fait **pas** sonner l'alerte plus tôt. Le seuil de 0,5 sur
`p_issue_h4` est franchi quand l'échéance entre dans la fenêtre et que
l'achèvement estimé la dépasse déjà ; la pente déplace les probabilités sans
suffire à faire franchir ce seuil plus tôt.

Ce qui « voit venir », aujourd'hui, ce n'est pas la tendance : c'est le fait que
4 fournisseurs défaillants sur 4 soient alertés 1 à 8 tours à l'avance, ce qui
était déjà vrai avant. La tendance rend le classement plus juste dans cette
fenêtre, rien de plus.

### 14.5 Ce qu'il faudrait pour vraiment gagner du préavis

Identifié, non fait :

1. **Alerter sur la pente elle-même**, pas seulement sur la probabilité d'issue.
   « Le cycle de ce fournisseur s'allonge de 30 h par semaine depuis 5 semaines »
   est une alerte exploitable bien avant que P(raté) franchisse un seuil.
2. **Abaisser le seuil d'alerte aux horizons longs.** Un 0,5 sur une fenêtre de
   4 semaines est plus exigeant qu'un 0,5 sur une fenêtre de 8.
3. **Étendre la tendance aux autres KPI** — OEE, taux de panne. Seul le lead
   time est extrapolé aujourd'hui.

---

## 15. L'outil devient multi-projet, et AIRB

### 15.1 Ce qui bloquait un utilisateur

`scripts/_common.py` codait en dur `projects/simu_semiconducteurs` et
l'identifiant `helios`. **Le harnais ne savait jouer qu'une seule chaîne** :
instrumenter la sienne imposait d'éditer le code.

Corrigé : le dossier de projet se résout par `SUPPLYSCORE_PROJET_DIR`,
l'identifiant est lu sur le module `scenario` (`PROJECT_ID`), repli sur
`helios`. Aucune commande existante ne change. `verite_derivee.py` et `banc.py`
suivent la même résolution — sans quoi ils dérivaient la vérité d'un projet
depuis les jalons d'un autre, en silence.

### 15.2 AIRB — ce que HÉLIOS ne pouvait pas éprouver

| | HÉLIOS | AIRB |
|---|---|---|
| nœuds | 8 | **15** |
| arcs | 9 | **30** |
| profondeur | 5 rangs, quasi linéaire | 5 rangs, **plusieurs chemins** rang 4 → client |
| chocs exogènes | 12 | **0** |
| vérité jalon | **scriptée** | **dérivée des KPI** |
| jalons observables | 11 | **22** |

Trois fournisseurs s'enlisent, choisis pour être structurellement centraux **à
des rangs différents**, de sorte que leur dégradation se propage par des chemins
distincts : `compolam` (rang 3, trois clients), `harnetec` (rang 3, trois
clients), `titanor` (rang 4, deux clients à deux rangs du client final).

La dégradation touche trois grandeurs à la fois — lead time, disponibilité,
volatilité de coût — parce qu'un fournisseur qui s'enlise ne voit pas seulement
son cycle s'allonger. Ne bouger que le lead time produirait un signal plus
facile à lire que la réalité.

### 15.3 La vérité dérivée se comporte comme prévu

**5 jalons ratés sur 22 observables**, et ils appartiennent **tous les cinq** aux
trois nœuds qui dérivent :

| nœud | jalon | échéance | achevé |
|---|---|---|---|
| compolam | stratifiés lot 1 | 7 | T8 |
| compolam | stratifiés lot 2 | 16 | jamais |
| harnetec | harnais lot 1 | 5 | T6 |
| harnetec | harnais lot 2 | 12 | T15 |
| titanor | contrat titane | 10 | T13 |

**Les douze nœuds sains tiennent leurs dix-sept jalons au tour près.** La règle
n'introduit donc aucun bruit : elle ne fait rater que ce qui doit rater.

### 15.4 Le classement des nœuds : la prévision gagne, le risque caché perd

Précision au rang 3 — parmi les 3 nœuds désignés, combien sont de vrais
défaillants. Taux de base : 3 défaillants sur 15 nœuds = **0,20**.

| classement | précision@3 | contre le hasard |
|---|---|---|
| **`p_issue` (couche de prévision)** | **0,53** | **×2,6** |
| `adequation` | 0,25 | ×1,25 |
| `hidden_risk` | **0,07** | **×0,35 — pire que le hasard** |

Et `p_issue` **converge** : 1/3 sur les premiers tours, **2/3 à partir de T10**
et jusqu'à la fin.

**Le renversement par rapport à HÉLIOS est le résultat, et il s'explique.** Sur
HÉLIOS le risque caché désignait juste (précision 1,00 sur six tours) ; ici il
fait pire que le hasard. La cause est le mode de déclaration : les déclarants
synthétiques d'AIRB portent un **biais FIXE** par profil. Trois des cinq
sous-déclarants sont les nœuds qui dérivent, mais les deux autres sont sains —
donc `hidden_risk` mesure surtout le profil du déclarant, pas l'état du terrain.

C'est la circularité identifiée dans la thèse, prise par l'autre bout : **un
écart déclaré/calculé n'est informatif que si la déclaration vient d'un jugement,
pas d'une formule.** C'est exactement ce que le bras LLM doit trancher.

### 15.5 Scoring de la prévision AIRB

Cible produit, vérité du pack, 184 prévisions :

| h | n | pos | skill | AUC |
|---|---|---|---|---|
| 1 | 181 | 5 | −5,599 | **0,923** |
| 2 | 177 | 10 | −2,234 | **0,872** |
| 3 | 172 | 15 | −1,193 | **0,816** |
| 4 | 167 | 19 | −0,873 | 0,758 |
| 8 | 135 | 31 | −0,167 | 0,654 |

**AUC 0,923 à une semaine** — la meilleure des quatre campagnes du banc. Le
classement est excellent, le niveau reste très faux sur un taux de base de 2,8 %.
Même dissociation que partout ailleurs : le modèle ORDONNE, il n'ANNONCE pas.

### 15.6 Réserve, et ce qui reste

Les déclarants d'AIRB sont **synthétiques** dans cette mesure : un biais fixe par
profil, pas un jugement. Le bras LLM — quinze personas raisonnant sur leur seule
fiche — est monté et fonctionne (fiches générées, harnais multi-projet vérifié),
mais **il n'a pas encore été joué sur l'ensemble de la campagne**. C'est lui, et
lui seul, qui peut dire si `hidden_risk` se rétablit quand la déclaration
redevient un jugement.

### 15.7 Le bras LLM d'AIRB : tour 0 joué, et deux refus utiles

Quinze personas — un agent par nœud, chacun ne voyant QUE sa fiche, aucune
information sur les autres acteurs — ont déclaré au tour 0. Le tour est
**collecté et clos par le harnais SupplyScore** : 15/15 déclarations, couverture
hebdomadaire 15/15, snapshot et sauvegarde écrits.

Le raisonnement des personas est réel, et il produit exactement l'écart que
l'outil existe pour mesurer. Les deux nœuds qui vont s'enliser **disent
eux-mêmes qu'ils minimisent** :

> *« je préfère garder l'œil ouvert plutôt que de crier au loup pour l'instant »*
> (CompoLam, qui ratera deux jalons)
>
> *« tant que je peux sortir des heures sup pour rattraper, je garde ça pour moi
> et je ne m'affole pas »* (HarneTec, qui en ratera deux)
>
> *« qu'on ne vienne pas me reprocher après-coup un délai de 24 semaines »*
> (Titanor, qui en ratera un)

Aucun profil synthétique ne produit ça : un biais fixe déclare bas, il n'explique
pas pourquoi.

**Deux refus du harnais, tous deux justifiés, tous deux de ma faute :**

1. `scores_ui` va de **1 à 6** (mappé sur l'échelle de Saaty 1-9), pas de 0 à 4.
   J'avais déduit l'échelle d'un exemple HÉLIOS au lieu de la lire dans le code.
   Le harnais a refusé la déclaration entière plutôt que de la tronquer.
2. `influence_prediction` est **obligatoire en bras `predict`**. Or au tour 0
   aucune prévision n'est montrée : le tour 0 relève du bras témoin. Protocole
   corrigé — témoin jusqu'à ce que la prévision devienne visible, puis `predict`.

Ces deux refus sont le tool qui fait son travail. Corrigés en demandant aux
personas de **réexprimer** leur jugement sur la bonne échelle, jamais en
recalculant leurs valeurs à leur place.

Un échec de cohérence AHP (`translog`, CR = 0,149) a été traité par le repli
documenté du harnais, sans intervention.

### 15.8 Coût mesuré du bras LLM, pour décider de la suite

| | mesure |
|---|---|
| par déclarant | ~44 000 jetons, ~45 s |
| par tour (15 nœuds, en parallèle) | **~660 000 jetons, ~1 min** |
| campagne complète 19 tours | **~12,5 M jetons** |

Le tour 0 est joué. **La suite est une décision de budget, pas une difficulté
technique** : le harnais, les fiches, la collecte, la vérité dérivée et le
scoring fonctionnent de bout en bout.

---

## 16. AIRB, bras LLM complet : 19 tours, 15 déclarants qui raisonnent

> Outils : `tour_airb.py`, `collecte_personas.py`, `banc.py --pack`,
> `classement_noeuds.py --journal`, `graphe_banc.py`.
> Figure : `docs/Thesis_Cranfield_JH_2026/Images/benchmark_airb.png`.

La campagne annoncée §15.8 a été jouée jusqu'au bout : **19 tours (T0 à T18),
15 personas par tour, 285 déclarations, 225 prévisions journalisées**, chaque
déclarant ne voyant que sa fiche du mois, ses propres déclarations passées et
les retours que l'outil dépose dans son bac à sable.

Le terrain KPI est posé par le scénario et ne dépend pas des déclarations : la
vérité dérivée est donc **la même que celle du bras synthétique** (5 jalons
ratés sur 22 observables, tous sur `compolam`, `harnetec`, `titanor`). Ce qui
change entre les deux bras, c'est **uniquement la déclaration** — donc Ud, donc
les poids AHP qui entrent dans l'agrégation. C'est exactement l'expérience qu'on
voulait : même terrain, deux façons de le déclarer.

### 16.1 Un défaut du dispositif, trouvé en le faisant tourner

`ecrire_retour_outil` cherchait un fichier `out/coherence_NN.json` que **le
harnais n'écrit jamais** : un échec de cohérence AHP n'existe que dans la sortie
de `collect-tour`. Le canal anti-contamination — le seul moyen prévu pour qu'un
déclarant recalé apprenne qu'il l'a été, sans que le coordinateur le lui souffle
— était donc **branché dans le vide depuis le début de la campagne**.

Le repli du harnais (reconduction de la déclaration précédente) a joué
correctement, la campagne reste valide, mais les tours 0 à 10 se sont déroulés
sans qu'aucun déclarant ne reçoive de retour. Corrigé au tour 10 :
`relever_echecs_coherence` lit les lignes `[cr_echec]` de la sortie du harnais
et écrit le fichier que le canal attendait.

**L'effet est immédiat et mesuré :**

| tour | échecs de cohérence | retour reçu au tour suivant |
|---|---|---|
| 9 | 3 | non — canal vide |
| 10 | **5** | oui — 5 nœuds |
| 11 | **1** | oui — 1 nœud |
| 12 à 18 | **0** | — |

Trois des cinq nœuds recalés ont **réexprimé** leur jugement seuls après lecture
du retour : `fibrelia` a recalculé son propre CR (0,126 → 0,03) en resserrant
l'amplitude sans changer l'ordre de ses critères ; `voilure` a reconstruit ses
six comparaisons à partir d'un classement latent unique ; `airb_fal` a réduit
l'amplitude en gardant les signes. Aucun n'a reçu autre chose que le texte de
l'application.

### 16.2 La prévision : le skill devient positif

Cible jalon, vérité dérivée du pack, 225 prévisions :

| h | n | pos | base | skill LLM | AUC LLM | skill synth. | AUC synth. |
|---|---|---|---|---|---|---|---|
| 1 | 151 | 5 | 0,033 | −1,601 | **0,826** | −5,599 | **0,923** |
| 2 | 147 | 9 | 0,061 | −0,639 | 0,781 | −2,234 | 0,872 |
| 3 | 142 | 13 | 0,092 | −0,345 | 0,757 | −1,193 | 0,816 |
| 4 | 137 | 16 | 0,117 | −0,295 | 0,697 | −0,873 | 0,758 |
| 6 | 123 | 22 | 0,179 | −0,147 | 0,616 | −0,501 | 0,657 |
| **7** | 114 | 24 | 0,211 | **+0,044** | 0,667 | −0,231 | 0,685 |
| **8** | 105 | 25 | 0,238 | **+0,068** | 0,633 | −0,167 | 0,654 |

**Le bras LLM atteint un skill positif à h7 et h8 ; le bras synthétique ne
l'atteint jamais.** Le skill est meilleur à TOUS les horizons — de +4,0 points
à h1 à +0,235 à h8. L'AUC, elle, est systématiquement plus basse (0,826 contre
0,923 à h1).

Les deux mouvements vont dans le même sens et disent la même chose : des
déclarations qui varient d'un nœud à l'autre **dispersent** les probabilités
prédites. Le niveau annoncé se rapproche du taux de base — la calibration
s'améliore — mais l'ordre se brouille un peu. Le bras synthétique, avec son
biais fixe par profil, produisait un classement plus propre et un niveau plus
faux.

C'est la troisième fois que le banc sépare CLASSEMENT et NIVEAU, et la première
où l'on voit un réglage qui **échange** l'un contre l'autre.

### 16.3 Le résultat central : `hidden_risk` ne voit rien, et on sait pourquoi

Précision au rang 3, 3 défaillants sur 15 nœuds, taux de base **0,20** :

| classement | AIRB **LLM** | AIRB synthétique | HÉLIOS bras A |
|---|---|---|---|
| `p_issue` (prévision, h4) | **0,56** | 0,53 | — |
| `adequation` | **0,00** | 0,25 | 1,00 (T0–T5) |
| `hidden_risk` | **0,00** | 0,07 | **1,00** (T0–T5) |

`p_issue` désigne juste et **converge** : 2/3 à presque tous les tours à partir
de T11. `hidden_risk` **ne désigne pas une seule fois** un nœud défaillant, sur
19 tours. Ce n'est pas du bruit : c'est systématique, et la cause est lisible
dans les snapshots.

**Ud déclaré par les trois nœuds qui dérivent :**

| tour | compolam | harnetec | titanor |
|---|---|---|---|
| 0 | 0,941 | 0,876 | 0,982 |
| 7 | 0,988 | 0,975 | 0,994 |
| 18 | 0,908 | 0,614 | 0,963 |

Ils déclarent **le maximum de la chaîne, dès le tour 0**, avant que leurs KPI
n'aient bougé. Or `hidden_risk = [Ur − Ud]⁺`. Avec Ur = 1,000 et Ud = 0,969, le
risque caché de `compolam` vaut **0,031** : l'écart ne peut pas s'ouvrir, non
parce que le modèle échoue, mais parce qu'**il n'y a rien de caché**.

En tête du classement, à chaque tour des 19, on trouve `airb_fal`, `aerostruct`,
`sysintegra` — les assembleurs en aval. Au tour 16 :

| nœud | Ur | Ur local | Ud | hidden |
|---|---|---|---|---|
| airb_fal | 1,000 | 0,644 | 0,188 | **0,812** |
| aerostruct | 0,973 | **0,000** | 0,190 | 0,783 |
| sysintegra | 0,953 | **0,000** | 0,172 | 0,780 |

`aerostruct` et `sysintegra` ont une urgence locale **nulle** : leur Ur vient
entièrement de l'amont, par propagation dans le DAG. Ils déclarent ce qu'ils
voient chez eux — rien — pendant que le modèle calcule ce qui leur arrive
dessus. L'écart mesure alors une **exposition héritée**, pas une dissimulation.

### 16.4 Ce que cela dit de l'instrument, et la réserve à écrire

Le point n'est pas que les personas aient été honnêtes. **Leurs cartes de rôle
les décrivaient explicitement comme des dissimulateurs :**

> *« Vous n'aimez pas annoncer une mauvaise nouvelle et vous espérez toujours
> rattraper au tour suivant »* (compolam)
>
> *« Vous encaissez les à-coups en silence tant que vous pensez pouvoir tenir »*
> (harnetec)

Et **ils ont dissimulé** — dans leur prose, tour après tour : *« tant que le lot 2
garde ce rythme je peux encore me passer d'appeler mes trois clients »*
(compolam, T12), *« je garde les heures sup en réserve »*, *« je ne dis rien en
réunion »* (harnetec). Mais au même tour, compolam coche `scores_ui` = [5, 6, 3, 4]
sur une échelle de 1 à 6 : la gravité quasi maximale.

**Ils minimisent en actes et maximisent au questionnaire.** Le formulaire AHP
demande « quelle gravité percevez-vous ? » — un responsable inquiet qui choisit
de se taire répond *fort*, précisément parce qu'il est inquiet. Se taire est un
acte de **communication** ; le questionnaire mesure une **perception**.

D'où la portée exacte de `hidden_risk` : l'écart [Ur − Ud]⁺ détecte un déclarant
dont la **perception** est en dessous du réel — un aveuglement. Il ne détecte pas
un déclarant qui voit juste et n'escalade pas. Les sous-déclarants synthétiques
d'HÉLIOS portaient un biais appliqué **au nombre**, donc l'écart s'ouvrait et la
précision valait 1,00. Un déclarant qui raisonne ne baisse pas le nombre.

**Ce résultat borne §10 et §11** : « le signal d'adéquation désigne les bons
nœuds, tôt, sans fausse alerte » reste vrai sur HÉLIOS et sur des déclarants à
biais numérique ; il est **faux sur AIRB avec des déclarants qui raisonnent**.
La couche de prévision, elle, tient dans les deux cas (0,53 et 0,56).

### 16.5 Réserves

- **Un seul scénario, un seul jeu de personas.** Quinze cartes de rôle écrites
  par le même auteur : le comportement déclaratif observé peut tenir à cette
  écriture autant qu'à la nature d'un déclarant raisonnant. À rejouer avec des
  cartes écrites par un tiers.
- **La déclaration du tour 1 de `translog` est contaminée** : le coordinateur lui
  a soufflé le motif de son échec de cohérence dans le message de relance, au
  lieu de laisser l'outil l'écrire. Une déclaration sur 285.
- **Bras témoin de bout en bout** : la prévision est calculée et journalisée à
  chaque tour, jamais montrée. Mesurer l'effet de l'AFFICHER demande une seconde
  campagne sur sa propre base, déclarations rejouées.
- Aucun choc exogène : le panneau C de la figure est dégénéré pour AIRB (la
  courbe « événement » est vide, « jalon » et « mixte » se superposent). C'est
  le scénario, pas un défaut de mesure.
