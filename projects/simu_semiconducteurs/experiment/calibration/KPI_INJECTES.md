# KPI injectés — justification et miroir de la crise réelle

Complétion des `BASELINE_KPIS` du scénario HÉLIOS, décidée et posée par le
pilote de l'expérience (Master AI), 2026-08-19.

**Rien n'a été supprimé.** Les valeurs d'origine sont conservées telles quelles ;
chaque ajout est marqué `# --- Complétion U19` dans `scenario.py`.

---

## 1. Pourquoi injecter

Mesure sur la base avant complétion : **couverture KPI 25,6 %** (8 nœuds ×
42 KPI). 24 indicateurs vides sur *tous* les nœuds.

Conséquences constatées, pas supposées :

| Symptôme | Cause |
|---|---|
| Orbitalys (rang 0) sans aucun KPI hors risque | le nœud dont l'urgence EST celle du programme n'avait rien à dire |
| `u_perf`, `u_cost`, `u_co2` = `None` sur presque tous les nœuds | blocs jamais renseignés |
| P(jalon raté) = 0 par construction sur 3 nœuds | `lead_time_h` absent → repli documenté `u_base = 0` |

Le modèle agrégeait **trois blocs sur six**. Un skill de Brier négatif dans ces
conditions est un diagnostic sur les **données**, pas sur les mathématiques.

Après complétion : **couverture 49,1 %**, et les **six blocs actifs sur les huit
nœuds**.

---

## 2. Règle suivie

> Chaque valeur injectée doit correspondre à un ordre de grandeur **documenté du
> secteur pendant la crise 2020-2022**, et rester cohérente avec l'arc long de
> cette crise. Pas de valeur choisie pour améliorer un score.

Les KPI restants vides le sont **volontairement** : le bloc géographique de
`time` (`speed_kmh`, `distance_range_km`, `refuel_time_h`) et
`network.distance_km` décrivent un transport routier physique que le scénario ne
modélise pas. Les remplir serait inventer, pas compléter.

---

## 3. Lead times — le cœur du miroir

L'arc réel de la crise est une **explosion des délais** : ~12 semaines en 2020,
~26 semaines au pic 2022 (série Susquehanna). Le scénario le rejoue en portant
la dérive sur le distributeur, qui la subit, et non sur le fondeur, dont le
cycle propre reste stable — un fondeur n'est pas « en retard » sur ses jalons
parce que ses clients attendent.

| Nœud | Lead time posé | Ancrage réel |
|---|---|---|
| **orbitalys** | 39 sem. réelles | AIT satellite (assemblage, intégration, tests) ≈ 9 mois chez un maître d'œuvre européen — Thales Alenia Space / Airbus D&S |
| **electis** | 8 sem. réelles | cycle CMS complet hors pénurie — Asteelflash / Lacroix |
| **compodis** | 12 sem. réelles | **base 2020 du distributeur** ; la dérive vers 25 sem. arrive par événements |
| **silpure** | 14 sem. réelles | croissance de lingot Czochralski + découpe + polissage — Shin-Etsu / SUMCO |

Le choix `compodis = 12` est le plus important du lot. Sans base, **le premier
retard fournisseur *définissait* le lead time au lieu de le décaler** — le
distributeur n'avait pas de « avant-crise » auquel se comparer. C'est
exactement la dérive 12 → 25 semaines que la littérature documente.

Cohérence avec la vérité terrain : Orbitalys à 39 semaines réelles pour un jalon
HÉLIOS-1 dû à T8 (8 tours = 8 mois réels) est **volontairement tendu** — et ce
jalon a effectivement été raté (livré T14).

---

## 4. OEE — qui encaisse, qui absorbe

La hiérarchie posée reflète qui, dans la crise réelle, tenait et qui pliait.

| Nœud | dispo / perf / qualité | Lecture |
|---|---|---|
| compodis | 0,97 / 0,95 / 0,999 | entrepôt : la préparation de commandes ne tombe pas, c'est l'appro qui manque |
| silpure | 0,96 / 0,94 / 0,998 | fours en marche continue ; pureté wafer : rebut rare mais total |
| transglobal | 0,94 / 0,90 / 0,99 | **perf 0,90 = congestion portuaire structurelle 2021** (LA/Long Beach, Suez) |
| aviosys | 0,94 / 0,91 / 0,995 | aéronautique : reprise coûteuse, zéro tolérance |
| orbitalys | 0,90 / 0,88 / 0,995 | AIT : créneaux de salle blanche contraints, qualité non négociable |

Le point de miroir : **l'aéro et le spatial ont été les perdants de
l'allocation**. L'automobile et le grand public ont surenchéri ; les volumes
aéro, faibles et à qualification lourde, sont passés après. D'où des
disponibilités plus basses en aval (orbitalys, aviosys) qu'en amont, et un
`recovery_time_h` de 26 semaines réelles chez AvioSys — la requalification d'un
composant aéronautique prend réellement ~6 mois.

---

## 5. CO₂ — proportionné à l'intensité réelle

`u_co2` était `None` partout. Les valeurs posées suivent l'intensité énergétique
réelle des maillons (g/h moteur) :

| Profil | op + mix | cible | max |
|---|---|---|---|
| fabs (novafab, meridian, silpure) | 6 300 – 9 000 | 6 300 – 8 600 | 11 800 – 16 000 |
| transport (transglobal) | 3 700 | 3 400 | 6 500 |
| EMS / intégration | 1 600 – 2 300 | 1 400 – 2 100 | 2 600 – 4 000 |
| entrepôt (compodis) | 1 000 | 1 000 | 1 900 |

Une fab consomme un ordre de grandeur de plus qu'un entrepôt — c'est le fait
saillant du secteur. Le transport a un `op_emission` élevé mais un `energy_mix`
faible : ses émissions sont du carburant, pas de l'électricité de site.

**Statut : assumé.** Aucune série CO₂ réelle n'a été utilisée. Ces valeurs
activent le bloc et respectent les proportions ; elles ne prétendent pas être
mesurées.

---

## 6. Bug trouvé par cette injection

Le remplissage a immédiatement révélé un défaut de mon propre correctif :
**AvioSys sortait `u_time = 1,0` dès le tour 0**.

Cause : j'avais routé le temps de production perdu vers `risk.recovery_time_h`.
Or ce champ portait déjà une autre grandeur — les **26 semaines de
requalification aéronautique** posées en référentiel. Le nœud le plus prudent du
réseau était donc déclaré comme ayant déjà perdu 1 005 heures de production.

Deux sémantiques incompatibles dans un seul champ :

| Champ | Nature | Qui le lit |
|---|---|---|
| `risk.recovery_time_h` | **paramètre** — « combien de temps pour se remettre » | `u_risk` |
| `time.delay_h` | **état** — « combien de production réellement perdue » | les 3 estimateurs de P(jalon raté) |

Corrigé : le temps perdu est désormais **cumulé dans `time.delay_h`** (champ qui
existait, était contraint, et que rien ne lisait). `recovery_time_h` retrouve sa
sémantique d'origine.

À noter : ce bug était **invisible tant que les KPI étaient vides**. Remplir les
données a fait apparaître un défaut du modèle. C'est un argument de plus pour
compléter avant de calibrer.

---

## 7. Ce qu'il reste à ne pas oublier

- Les valeurs OEE, CO₂ et coût sont **assumées**, pas mesurées. Elles doivent
  être étiquetées comme telles dans toute publication.
- Les lead times sont **ancrés** sur des ordres de grandeur documentés du
  secteur, mais restent des ordres de grandeur.
- Hors semi-conducteurs, **rien de ce fichier ne se transporte** : ce sont des
  données de scénario. Ce qui se transporte, c'est la méthode — mesurer la
  couverture, compléter ce qui est ancrable, laisser vide ce qui serait inventé,
  et étiqueter la différence.
- `RATTRAPAGE_HEBDO = 0` a été calibré **avant** ce changement de sémantique. La
  valeur doit être re-balayée maintenant que le retard s'accumule au lieu d'être
  lissé.
