# Couche de prévision — état, mesures, et plan

> Journal de travail. **Rien n'est supprimé ici** : les mesures périmées sont
> barrées ou datées, jamais effacées — une valeur abandonnée dit pourquoi on
> a bifurqué, et c'est souvent l'information la plus utile plus tard.

Dernière mise à jour : 2026-08-19.

---

## 1. Ce que l'outil cherche à faire

SupplyScore confronte **deux signaux** sur chaque nœud d'une chaîne :

| Signal | Origine | Nature |
|---|---|---|
| **Ur** — urgence réelle | calculée depuis les KPI, propagée sur le DAG | mesure |
| **Ud** — urgence déclarée | questionnaire AHP hebdomadaire du responsable | perception |

L'**adéquation** entre les deux est le livrable : Ur haute + Ud basse = *risque
caché* ; l'inverse = *fausse urgence*. La couche de prévision projette Ur à
1–4 semaines et en tire P(jalon raté) et P(impact client).

**Contrainte permanente** : l'outil doit valoir pour n'importe quelle chaîne
d'approvisionnement. HÉLIOS (crise des semi-conducteurs 2020-2022) est un banc
d'essai à vérité terrain connue, pas la cible. Toute constante calibrée doit
se défendre par un argument physique, pas seulement par son score sur HÉLIOS.

---

## 2. Réparations faites (2026-08-19)

Les trois estimateurs de P(jalon raté) modélisaient l'achèvement comme un cycle
complet démarrant maintenant. Modèle corrigé, identique dans les trois :

```
achèvement = t + (1 − avancement) × lead_time + temps_perdu
                 └──── proportionnel ────┘     └── additif ──┘
```

| Fichier | Ce qui a changé |
|---|---|
| `core/ur_model.py` | `u_base_jalon` : socle sur travail restant + temps perdu |
| `core/explain.py` | même appel, trace expose `retard_choc_h` |
| `services/forecast.py` | `completion = t + lead×reste + retard` |
| `mc/lead_time.py` | `C_i = S_i + L_i×reste + R_i` |
| `domain/events.py` | 5 chocs de capacité → `risk.recovery_time_h` (additif) |

**Piège évité, à retenir** : router l'arrêt dans `lead_time_h` le fait
multiplier par `(1 − avancement)` — le choc s'évapore précisément sur les
jalons proches de l'échéance. NovaFab retombait de 84,6 % à 0,0 % sur un jalon
réellement raté. C'est pour ça que le temps perdu est *additif*.

### Résultats de calibration (balayage 12 points, `balayage.py`)

| | skill Brier | AUC | coût diagnostique |
|---|---|---|---|
| avant | −0,794 | 0,667 | 4,12 |
| **après, rattrapage = 0** | **−0,562** | **0,730** | **2,00** |

λ (`LAMBDA_ARRET`) s'est révélé **indifférent** : le scénario compresse un mois
réel en un tour moteur, donc le « gel de 4 semaines » ne pèse que 154,7 h
moteur. La compression narrative borne ce que le modèle peut détecter.

**Le skill reste négatif.** Moins faux, pas encore bon.

---

## 3. LA mesure qui change la priorité : couverture KPI 25,6 %

Mesuré sur la base du bras C, 8 nœuds × 42 KPI = 336 cases :

| | nombre |
|---|---|
| KPI renseignés sur les 8 nœuds | **5** / 42 |
| KPI partiellement renseignés | 13 / 42 |
| KPI **vides sur tous les nœuds** | **24** / 42 |

**Couverture globale : 25,6 %.**

### Le détail qui fait mal

`time.lead_time_h` — la grandeur centrale de P(jalon raté) — n'est renseignée
que sur **5 nœuds sur 8**. Les trois autres reçoivent un socle de risque de
**0,0 par construction**, via le repli documenté « lead time absent → u_base =
0 ». Ce n'est pas une prédiction, c'est une absence de donnée qui se présente
comme une prédiction rassurante.

Blocs entièrement vides : **`co2` (5/5)**, `oee.production_time_h` et
`oee.operating_time_h`, `cost.product_cost` / `fuel_cost` / `risk_cost` /
`storage_cost`, tout le sous-bloc géographique de `time`
(`speed_kmh`, `distance_range_km`, `time_range_h`, `refuel_time_h`), et les
bornes triangulaires du lead time (`min`/`mode`/`max`).

Conséquence directe : `u_co2` et `u_cost` sont **None** sur tous les nœuds,
`u_perf` sur la plupart. L'agrégation Ur ne repose donc que sur `time`, `cap`
et `risk` — trois blocs sur six. **Le modèle vote avec la moitié de ses
électeurs absents.**

### Pourquoi c'est la priorité n°1

Aucune quantité de calibration ne compense une entrée manquante. Un skill de
Brier négatif sur un modèle nourri au quart est un diagnostic sur les
**données**, pas sur les mathématiques. Remplir les KPI est aussi la seule
action de cette liste qui soit *générale* par nature : elle vaut pour toute
chaîne, elle n'ajuste aucune constante à HÉLIOS.

---

## 4. Corrections de méthode (demandées 2026-08-19)

### 4.1 Ne plus souffler aux personas — appliqué

Lors de la campagne T0–T6, les personas ont reçu par message des éléments qui
ne venaient pas de l'outil : « bien joué pour le tour 1 », « ton action a été
appliquée », « vise CR < 0,10 ». **C'est de la contamination** : le déclarant a
reçu un retour qu'aucun opérateur réel n'aurait eu, et ses décisions
postérieures en sont teintées.

Règle désormais : **un persona ne reçoit que ce que le bac à sable contient.**
Tout retour légitime (échec de cohérence, action refusée, effet d'une action)
doit passer par la **fiche de tour générée par le harnais**, jamais par le
canal de coordination. Si l'information mérite d'atteindre le déclarant, elle
mérite d'être produite par l'outil.

> Les données T0–T6 restent exploitables mais doivent être **étiquetées
> « coordination contaminée »** dans toute comparaison. Elles ne sont pas
> supprimées.

### 4.2 Une seconde tentative avant de reconduire

Aujourd'hui un CR ≥ 0,10 après 2 essais internes déclenche immédiatement le
repli (reconduction du tour précédent). Observé : 2 échecs sur 56
déclarations (Orbitalys T0, AvioSys T3).

À faire : le harnais doit **rendre la main une fois de plus** au déclarant, en
lui servant par sa fiche l'indication que l'outil réel donnerait (la paire la
plus contradictoire), et ne reconduire qu'après ce second refus. C'est ce que
fait l'outil avec un humain.

### 4.3 Personas joués par des modèles capables

Haiku a tenu le protocole (56 déclarations, 2 échecs de cohérence, actions
argumentées). Mais la qualité du raisonnement compte pour la suite : on veut
observer *comment* un déclarant arbitre entre sa fiche, la presse et
l'analyse. Passer à un modèle plus capable pour les campagnes de mesure.

---

## 5. Ce que la campagne T0–T6 a déjà établi

Campagne bras C (boucle fermée), 8 personas, 56 déclarations, 16 actions
réellement appliquées, 1 refusée sur précondition fausse.

**Au tour 4 — première visibilité de la prévision : 8 déclarants sur 8 apaisés
ou confortés, 0 révision à la hausse.** Compte identique à la campagne
d'origine, obtenu cette fois avec le modèle réparé et calibré.

| nœud | Ud T3 | Ud T4 | Δ |
|---|---|---|---|
| novafab | 0,638 | 0,527 | **−0,111** |
| compodis | 0,860 | 0,764 | −0,095 |
| transglobal | 0,883 | 0,796 | −0,086 |
| orbitalys | 0,657 | 0,583 | −0,075 |
| meridian | 0,678 | 0,609 | −0,069 |
| silpure | 0,704 | 0,731 | +0,027 |
| aviosys | 0,674 | 0,724 | +0,050 |
| electis | 0,589 | 0,694 | +0,106 |

**Conclusion : le désarmement n'est pas un défaut de calibration.** Réparer la
chaîne causale et recalibrer ne l'enlève pas. NovaFab, dont l'usine gèle deux
tours plus tard, baisse le plus, en écrivant : *« l'outil valide que la
situation s'apaise, mes actions payent »*, puis au tour 5 : *« outil valide
position basse (9,2 %) malgré crise médiatisée »*.

**Asymétrie observée** : tant que le choc est invisible, l'outil désarme ; dès
qu'il devient visible dans la fiche, les déclarants se réarment seuls et
contredisent explicitement l'analyse (*« l'outil lag la réalité »*, *« outil
dit mieux mais c'est faux »*). Mais à ce stade le choc a eu lieu.

---

## 6. Plan, dans l'ordre

### A. Remplir les KPI (priorité 1, générale)

Porter la couverture de 25,6 % vers ≥ 80 %, en distinguant strictement :

- **dérivé** — calculable depuis ce qui existe (`oee.production_time_h` et
  `operating_time_h` depuis `availability` ; `time.lead_time_min/mode/max`
  depuis μ et σ) ;
- **assumé** — posé par défaut documenté, étiqueté comme tel ;
- **scripté** — issu de la narration HÉLIOS, donc NON transposable.

Un KPI rempli doit porter son étiquette d'origine, sinon on ne saura plus ce
qui est mesure et ce qui est hypothèse.

### B. Re-mesurer sur le rejeu gelé

Rejouer le bras A avec les KPI complets. **Sans toucher aux constantes.**
On veut savoir ce que la donnée seule apporte, avant tout réglage.

### C. Régler les constantes, ensuite seulement

Élargir le balayage aux paramètres du modèle Ur (`kappa_retard`,
`kappa_avance`, `omega`, `alpha_cap`, `beta_cost`) une fois les entrées
complètes. Régler avant d'avoir rempli reviendrait à compenser un manque de
données par un biais de modèle — et ce biais ne se transporterait pas.

### D. Recalibration post-hoc

Le classement est bon, le niveau reste faux : cas d'école de l'isotonique /
EMOS. La couche existe (U10), à entraîner **sur l'usine synthétique**, jamais
sur HÉLIOS.

### E. Campagne propre, sans contamination

Modèle capable, aucune instruction hors bac à sable, seconde tentative sur
échec de cohérence. Comparable au bras A d'origine et au bras C contaminé.

### F. Analyse des micro-changements

Quelles variations précoces (KPI, action, tour) déplacent réellement l'issue.
C'est ce qui donnera les signaux à privilégier dans la couche de prévision — et
c'est la partie transposable hors semi-conducteurs.

---

## 7. Réserves ouvertes

- **`RATTRAPAGE_HEBDO = 0`** gagne sur HÉLIOS et se défend comme hypothèse
  prudente, mais prive `risk.recovery_time_h` de tout retour à zéro. Sur un
  horizon long, un nœud accidenté porte sa pénalité indéfiniment. À revoir sur
  une campagne longue — le rattrapage réel se mesure, il ne se postule pas.
- **L'ignorance n'est pas déclarée.** Face à un choc exogène, afficher « 0,0 %
  de rater votre jalon » et « en voie de résolution » est pire que ne rien
  afficher. Correction non implémentée, et ce n'est pas une correction
  mathématique.
- **Compression temporelle du scénario** : 1 tour = 1 mois réel. Elle borne ce
  que le modèle peut détecter et rend λ indifférent. À ne pas confondre avec un
  défaut du modèle.
