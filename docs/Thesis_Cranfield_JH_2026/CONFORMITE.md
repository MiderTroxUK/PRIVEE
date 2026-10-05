# Cranfield MSc CSTE — règles de forme, et où ce mémoire s'en écartait

Les règles ci-dessous sont lues sur les trois mémoires acceptés de la promotion
2024-2025 (`../ExampleTheses/`), pas déduites d'un guide : Doyenard (71 pages),
Mazel (57), Pourrain (55). Quand les trois divergent, Doyenard fait référence,
parce que c'est le seul des trois passé par ESTIA Bidart avec la structure
complète qu'exige le programme — grille de sources, considérations éthiques,
réserves méthodologiques, conclusion de section.

---

## 1. Page de titre

| Champ | Doyenard | Ici, avant | Après |
|---|---|---|---|
| Auteur, titre | oui | oui | inchangé |
| École | « Engineering and Applied Sciences » | absent | **ajouté** |
| Nature | « Thesis » | absent | **ajouté** |
| Diplôme et site | MSc CSTE (ESTIA Bidart) | oui | inchangé |
| Année universitaire | oui | oui | inchangé |
| Encadrants académique et industriel | oui | oui | inchangé |
| Mois et année | oui | oui | inchangé |
| Copyright Cranfield | — | partiel | **énoncé complet** |

## 2. Déclaration d'intégrité académique

Les quatre engagements figurent en page i chez Doyenard, avant le résumé. Ils
manquaient : le mémoire n'ouvrait que sur la confidentialité et l'usage des
outils logiciels. **Ajoutés**, les trois déclarations sur une même page.

## 3. Résumé

250 à 400 mots chez les trois, suivis d'une ligne de mots-clés. Ici : **1 470
mots** sur deux pages pleines, soit près de quatre fois la borne haute.
**Réécrit à 420 mots**, mots-clés conservés ; le résumé français suit à
l'identique.

## 4. Éthique

Doyenard énonce la catégorie de risque CURES et renvoie à la lettre en annexe.
Ici la catégorie manquait, et les méthodes promettaient une lettre que l'annexe
disait seulement déposée. **La catégorie 1 est maintenant énoncée aux deux
endroits, dans les mêmes termes.** Le détail du protocole humain, qui figurait
en double dans les méthodes et en annexe A, ne figure plus qu'en annexe.

## 5. Plan IMRaD

Introduction / revue de littérature (un « gap » par flux, grille de sources,
gaps identifiés) / méthodes (+ limites, reproductibilité, éthique, conclusion) /
résultats et discussion / conclusion + travaux futurs + conclusion personnelle.
Respecté, et plus complètement que dans les trois exemples.

## 6. Typographie

| | caractères par ligne |
|---|---|
| Doyenard | 86 |
| Mazel | 85 |
| Pourrain | 85 |
| **Ici** | **88** |

Mesuré sur vingt pages de corps de chaque document. La densité est celle du
programme : passer à 11 pt aurait gagné huit pages en portant la ligne à
96 caractères, hors de la norme des trois. **Le corps reste à 12 pt** et la
réduction porte sur le contenu seul.

## 7. Volume

| | pages | corps |
|---|---|---|
| Doyenard | 71 | 56 |
| Mazel | 57 | 46 |
| Pourrain | 55 | 45 |
| Ici, avant | 116 | 80 |
| **Ici, après** | **106** | **69** |

Le corps perd quatorze pages, le volume douze. Il reste au-dessus des trois
exemples, et cela se défend : ceux-ci rapportent une expérience, celui-ci en
rapporte deux, avec un cycle diagnostic-réparation-remesure, un témoin trivial,
une expérience sur la définition de la cible, un second volet, cent cinquante
références et la grille de sources qu'exige le programme. Aucun résultat mesuré
n'a été retiré pour tenir un compte de pages.

**Ce qui est parti :** la synthèse par question de recherche, qui répétait les
contributions sur deux pages (l'appariement question/réponse devient un tableau
en tête de conclusion) ; huit pages du volet satellite, ramené à trois dans le
corps, son détail opératoire passant en annexe E que le rapport tenait déjà pour
ça ; trois tableaux de la réparation fondus en un, puisqu'ils scoraient les
mêmes prévisions sur les mêmes effectifs ; un tableau du bras B qui portait le
titre et les données de sa propre figure ; le tableau des limites, de quatorze
lignes à neuf, par fusion des lignes qui décrivaient la même chose de deux
côtés ; les perspectives, de treize paragraphes à huit ; et partout les phrases
qui annoncent un résultat avant de le donner ou le redisent après.

---

## 8. Figures : ce qui a été refait

Quatre défauts visibles à l'oeil, dans un mémoire anglais suivant une charte
sans rouge.

| Figure | Défaut | Traitement |
|---|---|---|
| Effet de l'affichage (chaîne AIRB) | entièrement en français | **régénérée** avec `--lang en` depuis les campagnes d'origine ; données identiques au pixel près |
| Trajectoires du rodage | axes, légende et titres en français | **régénérée** en anglais depuis `resultats.csv`, dans l'arbre du mémoire pour que le BST français garde la sienne |
| Réseau de la campagne | en français, et la boîte de droite coupée par le bord de l'image | **redessinée en TikZ**, anglaise, avec ses coefficients γ et β et son arc de secours inerte |
| Propagation bidirectionnelle | deux flèches rouges | **redessinée en TikZ** |
| Simulation de choc | rouge, et le paragraphe voisin décrit la boucle exactement | **retirée** |
| Pipeline d'événement | même étiquette deux fois, moitié du carré vide | **redessiné en TikZ**, tient maintenant sur la page de son texte |
| Écart d'urgence | aire de risque caché en rose | **remplacée** par la version anglaise sur charte, désormais partagée avec le rapport ESTIA |
| Trois captures d'écran | interface française | **recadrées** sur la zone dont le texte parle, avec une clé de traduction à droite |
| Preuve de façade équipée | bandeaux français, remplissage noir | **relettrée** en anglais, remplissage retiré, imagerie inchangée |
| « Figure à dessiner » | **cadre rouge imprimé page 71** | **dessinée** |

Trois figures conceptuelles ont par ailleurs été retirées parce qu'elles
redisaient leur voisine immédiate : la boucle test-and-learn, l'arbre causal des
blocs (doublé par la liste à puces *et* par le tableau du filtre), et la
correspondance des critères AHP.

### Cinq figures ajoutées, et la prose qu'elles remplacent retirée

Cinq passages décrivaient en mots ce qui est une fonction, une chronologie ou
une structure. Chacun devient une figure, et le texte part.

| Nouvelle figure | Ce qu'elle remplace |
|---|---|
| La courbe d'adéquation contre l'écart signé | le paragraphe qui affirmait l'asymétrie sans la montrer. Le même écart absolu de 0,5 vaut 21 d'un côté et 53 de l'autre : la courbe le dit, pas la phrase |
| Le tirage emboîté de la prévision | l'énumération des trois estimateurs et la décomposition de variance en deux composantes |
| La chronologie de la campagne | l'énumération des cinq actes ; les douze événements calibrés sont maintenant lisibles à leur tour et sur leur nœud |
| Les trois bras | la liste de définitions et le paragraphe qui distinguait B de C. La boucle ouverte et la boucle fermée se voient |
| Les deux modèles d'achèvement | le raisonnement sur le temps perdu multiplié plutôt qu'ajouté. Le second panneau montre le choc réduit à 0,4 semaine sur quatre là où l'alerte vaudrait le plus |

Deux figures de plus, et deux tableaux qui partent avec elles :

| Nouvelle figure | Ce qu'elle remplace |
|---|---|
| Les quatre familles de modèles, tracées | la colonne « key property » du tableau et le paragraphe qui expliquait ce qu'un agrégat compensatoire cache. Le panneau b est le choix central du mémoire : à un bloc saturé, la moyenne s'arrête à 0,33 quand le noisy-OR atteint 1,00 |
| La chaîne multicritère | l'ouverture en prose de la section, et la phrase finale sur la réutilisation des poids ω, qui passe en légende |

| Tableau retiré | Ce qui le portait déjà |
|---|---|
| Pathologies d'urgence | la figure de l'écart les nomme toutes deux, et la prose donne leurs conséquences |
| Fiabilité par bande | sa propre figure porte les cinq bandes, leur effectif, la moyenne annoncée et la fréquence observée |

Les trois courbes sont calculées depuis les équations du mémoire, pas dessinées :
elles suivront une recalibration. Les quatre schémas sont en TikZ. Les contrôles
du protocole — les deux placebos et le tour à signal faible — sont posés sur la
frise de campagne, à côté des événements qu'ils contrôlent, et le paragraphe qui
énonçait leurs dates ne les énonce plus.

Bilan : **sept figures ajoutées, trois tableaux retirés**, environ mille mots de
prose en moins, deux pages de plus. Le mémoire compte 30 figures et 32 tableaux.

---

## 9. Défauts de composition corrigés

- **22 débordements dans la marge** → 0. Les DOI n'offrent aucun point de
  coupure : `xurl` et une réserve d'élasticité les cassent. Le tableau des
  trois définitions d'issue sortait de cinq centimètres, sa première colonne
  étant en `l` alors qu'elle porte une phrase.
- **Colonne X centrée verticalement** : chaque ligne d'un tableau mêlant `X`
  et `p` était désalignée. Alignée en haut.
- **Huit acronymes développés deux fois** : « Analytic Hierarchy Process
  (Analytic Hierarchy Process (AHP)) », le texte écrivant le terme puis
  appelant la macro qui le développe à son tour.
- **Une formule illisible** : `\gls` dans un mode mathématique produisait
  `CR = ConsistencyIndex(CI)/RandomIndex(Saaty)n(RI)`.
- **Petites capitales absentes de Carlito** : un avertissement de fonte.
- **Quatre flottants n'étaient appelés nulle part** dans le texte.
- **Une conclusion de section seule sur une page** de vingt-huit lignes
  blanches.
- **Le décompte des tests différait** entre les méthodes (1 779) et les
  résultats (1 831), dans le même document.

## 10. Chiffres vérifiés contre le dépôt

| Affirmation | Mesure |
|---|---|
| 73 modules sur 10 paquets | 86 fichiers `.py` moins 13 `__init__.py` = 73 ; dix paquets sous `supplyscore/` ✔ |
| 1 831 fonctions de test, 106 fichiers | ✔ |
| 2 044 cas collectés | ✔ |
| 2 028 passent, 15 ignorés, 1 échoue | ✔ — l'échec porte sur deux captures manquantes de `docs/Presentation script.md`, hors bibliothèque |
| 23 nœuds, 7 positifs, 33 jalons observables | 8 + 15, 4 + 3, 11 + 22 ✔ |

## 10 bis. Densification technique (25 août 2026) — annule la cible de la section 7

**La consigne a changé** : le mémoire doit être le plus dense possible, tout
présenter, et peut s'étaler en annexes. La cible de 69 pages de corps de la
section 7 ne s'applique plus. Ne pas raccourcir sans redemander.

Ce qui a été ajouté, et pourquoi :

| Ajout | Emplacement | Ce qui manquait |
|---|---|---|
| Table de notation | 3.2.1 | Deux collisions de symboles : `alpha` portait les poids capacité **et** la courbure Prospect Theory, `beta` les poids coût **et** l'amplification d'arc. Poids intra-bloc renommés `a_k` / `c_k`. |
| Dérivation du noisy-OR | 3.2.2 | La forme était posée, jamais dérivée. Vient de l'hypothèse de causes concurrentes indépendantes ; `omega_m` = nombre de répétitions indépendantes. |
| 3 algorithmes | 3.2.2, 3.2.5, 3.2.6 | Propagation, criticité, Monte-Carlo : décrits en prose, jamais en pseudo-code. |
| 5 propositions démontrées | 3.2 | Dont l'effondrement par saturation, qui était rapporté comme observation empirique alors qu'il se **démontre** en trois lignes. |
| Équations AHP / FBWM / PROMETHEE | 3.3.2, 3.3.3 | Zéro formule pour trois méthodes. A révélé que `core/ahp.py` utilise l'**approximation** de Saaty, pas le vecteur propre : le texte disait le contraire. |
| Spécification de la couche de prévision | 3.3.5 | AR(1), posterior Bêta, bootstrap, et la loi de variance totale que la figure dessinait sans jamais l'écrire. |
| Complexités + bancs mesurés | 3.3.7 | Mesures réelles sur 1 000 nœuds / 1 244 arcs. Relancer par `SUPPLYSCORE_BENCH=1 .venv/Scripts/python.exe -m pytest tests/benchmarks`. |
| Protocole statistique | 3.4.4 | Wilson, Mann-Whitney exact, pourquoi le bootstrap n'est pas décisif à quatre positifs. |
| § 4.8 « How Much of This Is Signal » | 4.8 | Les intervalles étaient déjà dans `derived.json` et jamais rapportés. Aucune AUC ne se distingue du hasard ; les précisions 1,00 et 0,00 ont des intervalles qui se recouvrent. |
| Hypothèse de sincérité | 3.2.7 | Tout l'écart `H` en dépend et elle n'était nulle part. |
| Annexe F, exemple numérique | Annexe F | Un nœud du bloc à l'adéquation, chiffres produits par le code de production. |
| Annexe G, registre d'hypothèses | Annexe G | Douze hypothèses : 3 testées, 5 testables non testées, 1 choix de modélisation, 3 hors portée du dispositif. |

**Attention en réécriture** : écrire du LaTeX via un heredoc Bash mange un
backslash sur deux et casse les terminateurs de ligne des tableaux. Passer par
un script écrit avec l'outil Write puis `py <chemin>`.

## 10 ter. Passe d'illustration (25 août 2026)

**Consigne** : tout ce qui peut passer en figure ou en tableau doit y passer, au
moins un visuel par section. Le mémoire est passé de **26 à 52 figures**.

Quatre figures de données, script `Utilities/figures/make_inference_figures.py`,
sorties vectorielles `.pdf` puis `.svg` puis `.png` :

| Figure | Section | Source des chiffres |
|---|---|---|
| `noisy_or_vs_average` | 3.2.2 | formule fermée, cinq blocs figés |
| `benchmarks` | 3.3.7 | `tests/benchmarks`, JSON pytest-benchmark |
| `auc_forest` | 4.8 | `derived.json` + Mann-Whitney exact |
| `wilson_intervals` | 4.8 | comptages du texte, formule de Wilson |

Vingt-deux diagrammes TikZ, palette ALTEN et styles maison (`bloc`, `blocFort`,
`blocPale`, `blocAlerte`, `fleche`, `flecheCoupee`, `flechePale`, `etiquette`,
`titreBande`). Les plus utiles : la carte objectifs/questions/hypothèses (1.4),
le périmètre (1.5), la feuille de route (1.7), la carte de la littérature et
son trou (2.14), la boucle de biais d'automatisation (2.9), les deux axes de la
vérification (2.11), l'analogie du triage (2.12), les six blocs comme mécanismes
(3.2.3), l'effondrement par saturation (3.2.6), la chaîne de notation (3.4.4),
le chemin de reproduction (3.6), le défaut du bloc temps (4.6.1), la frontière
de la seconde chaîne (4.5.2), le témoin d'une ligne (4.8.2), la nature des
affirmations de la discussion (4.11), les contributions (5.2), le programme
ordonné (5.5), la chaîne de l'exemple (annexe F).

**Deux pièges TikZ rencontrés** : `in` et `out` sont des clés réservées
(`to[out=..,in=..]`), un `\tikzset` qui les redéfinit donne
`The key '/tikz/in' requires a value`. Et la colonne `X` de tabularx **n'existe
pas** dans `longtable` : passer en largeurs fixes ou charger `xltabular`.

**Ce qui reste sans visuel, volontairement** : une trentaine de sous-sections de
transition d'une centaine de mots (`Methodological Framework`, `Mathematical
Model`, `System Implementation`, les introductions de section), et les flux de
littérature qui sont des revues de citations. La carte de la 2.14 couvre la
section entière ; y ajouter une figure par flux serait du remplissage.

**Zéro tiret cadratin** dans tout le document, vérifié par
`grep -c -- "---" Sections/*.tex Sections/Appendices/*.tex`.

## 10 quater. Prose remplacée par des visuels (25 août 2026)

**Consigne** : tout texte remplaçable par une figure ou un tableau doit l'être,
pour réduire la quantité de texte brut. **68 figures, 46 tableaux.**

Prose convertie, avec le gain réel :

| Passage | Avant | Après | Forme |
|---|---|---|---|
| 5.2 Contributions | 798 mots | ~476 | tableau `tab:contributions` |
| 5.5 Future Work | 1232 mots | 795 | tableau `tab:futurework` (8 items, pas 7) |
| 2.14 récap des sept limites | 137 mots | 0 | porté par `fig:lit_map` |
| 2.4 précurseurs | 266 mots | tableau | `tab:precursors` |
| 2.8 méthodes multicritères | 276 mots | tableau | `tab:mcdm`, colonne compensatoire ajoutée |
| 4.10.4 troisième bras | 159 mots | 112 | porté par `fig:third_arm` |

Figures ajoutées à cette passe : les six hypothèses avec leurs seuils (1.6),
le tableau de bord des verdicts (5.3), la carte des limitations (5.4), les deux
défauts révélés par le premier (4.10.2), le troisième bras (4.10.4), l'horloge
du protocole (annexe C).

**Deux erreurs corrigées en route** : `fig:futurework` listait sept items alors
que la section en a huit (l'en-tête du huitième passe à la ligne et échappait au
comptage) ; et `fig:third_arm` remplissait les mêmes cinq carrés sur les deux
lignes, ce qui disait l'inverse de sa légende. Les deux carrés ocre montrent
maintenant l'échange.

**Ce qui reste en prose, volontairement** : les démonstrations, les passages
argumentatifs (un renversement ne se met pas en tableau), et une trentaine de
sous-sections de transition d'une centaine de mots.

## 10 quinquies. Deuxième passe d'illustration (25 août 2026)

**68 figures, 46 tableaux.** Dix figures de plus, dont deux de données.

Figures de données ajoutées à `make_inference_figures.py` :

| Figure | Section | Ce qu'elle montre |
|---|---|---|
| `repair_effect` | 4.10.3 | Brier et AUC sur trois versions du modèle : la réparation structurelle gagne sur les deux axes, le terme d'incertitude échange l'un contre l'autre |
| `segmentation_runs` | 4.12.2 | quatre runs, quatre métriques : tout monte avec les données annotées et tout redescend quand seule la taille d'image change |

Diagrammes ajoutés : la provenance des deux signaux (3.4.2), le chemin éthique
et celui tenu en réserve (3.7), le sens de chaque simplification (3.5), les
trois phases de la dégradation du signal (4.5.1), H3 récupérée par la
seconde clé de tri (4.10.5), le décalage de dimensionnalité qui ouvre le
mémoire (1.1), les trois compétences et leurs preuves (5.6.1), la forme du
registre d'hypothèses (annexe G).

**Sous-sections encore sans visuel : 22**, contre 35 avant cette passe. Ce qui
reste est soit un paragraphe de transition de moins de 150 mots, soit un
passage de réflexion personnelle, soit une annexe qui est déjà un tableau.

**Rappel du piège TikZ** : `in`, `out` et `step` sont réservés. Je m'y suis
repris à trois fois sur `out`.

## 10 sexies. Reprise des diagrammes (25 août 2026)

### Restyle global, par le `tikzset` partagé

Une seule édition améliore les quarante diagrammes TikZ à la fois. **Seules des
propriétés qui ne peuvent pas déplacer un nœud** ont été touchées, donc aucun
risque de collision nouvelle :

| Propriété | Avant | Après | Pourquoi |
|---|---|---|---|
| trait des boîtes | 0,7 pt | 0,85 pt | à l'impression les boîtes lisaient comme un tableau pâle |
| coins arrondis | 2 pt | 3 pt | idem |
| `blocFort` remplissage | azure!18 | azure!26 | trois remplissages presque identiques, aucune hiérarchie |
| `blocPale` | blanc, texte gris | gris!55, texte navyShade | une boîte blanche sur fond blanc n'était pas une boîte ; le gris pâle échouait au contraste |
| `blocAlerte` | ocrePale!55 | ocrePale!70 | |
| pointes de flèche | 2,2 mm | 2,8 mm | la direction est le contenu de ces figures, les pointes étaient à peine visibles |
| `etiquette` | césure autorisée | `\SansCesure` | les étiquettes étroites se coupaient en fin de ligne |

**Piege** : une ligne vide à l'intérieur de `\tikzset{...}` donne
`Paragraph ended before \pgfkeys@addpath was complete`. Utiliser `%%`.

### Défauts corrigés un par un

- **`fig:six_blocks`** : les deux étiquettes de groupe étaient ancrées à l'est de
  x=0,55 alors que les boîtes commençaient à x=0,65, donc leur fond blanc
  recouvrait les bordures. Remplacées par des accolades, qui ne peuvent pas
  entrer en collision, et le dessin élargi de 8,5 à 15 cm.
- **`fig:provenance`** : la note de rejet faisait quatre lignes et le trait
  séparateur la barrait. Déplacée dans l'espace libre à droite.
- **`fig:scoring_pipeline`** : placée avant un `itemize`, elle flottait en haut
  de page suivante et laissait la dernière puce orpheline dessous. Réancrée
  après la liste.
- **Contradiction interne** : §4.5.1 affirmait qu'aucun intervalle de confiance
  n'était imprimable à quatre positifs, alors que §4.8 en imprime un. Corrigé.

### Vérification géométrique

`scratchpad/audit_tikz.py` mesure la boîte englobante de chaque figure dans le
PDF et la compare au bloc de texte (15,6 cm). **Aucune figure ne dépasse la
marge** ; le seul cas signalé est un artefact de mesure sur un `.pdf` importé.
Zéro débordement horizontal au-delà de 10 pt dans tout le document.

## 10 septies. Audit contre les trois mémoires acceptés (25 août 2026)

Relecture complète contre Doyenard (71 p.), Mazel (57 p.) et Pourrain (55 p.).

### Bloquant à la remise

1. **La lettre CURES n'est pas dans le document.** Les trois exemples
   l'incluent physiquement : Doyenard en Annexe 1 (p. 69), Pourrain en dernière
   page (p. 55, avec l'en-tête « Reference: CURES/26243/2025, Project ID:
   29395 »). Notre §3.7 et notre Annexe A affirment tous deux que la lettre
   « is filed with this thesis », et l'Annexe A ne contient aucun
   `\includepdf`. **Il faut le PDF.**
2. **Aucun numéro de référence CURES n'est énoncé.** Doyenard le donne dans
   les méthodes (p. 30), Pourrain dans le sommaire (p. 4). Nous disons
   « Category 1, low-risk study » sans référence. **Il faut le numéro.**

### Corrigé pendant l'audit

3. **Glossaire déplacé en liminaires.** Il était après la bibliographie ;
   Mazel place le sien page 4, avant le sommaire. Un lecteur qui rencontre
   « AHP » en page 5 avait 90 pages à parcourir avant l'expansion. Ordre
   liminaire désormais : titre, déclarations, résumé, résumé français,
   remerciements, acronymes, sommaire, listes.

### Écarts assumés

4. **140 pages contre 55 / 57 / 71.** Le double du plus long. C'est la
   conséquence directe de la consigne de densité maximale (section 10 bis) et
   ce n'est pas un oubli.
5. **Résumé de 445 mots** contre 324 (Doyenard), 251 (Mazel), 234 (Pourrain).
   Au-dessus des trois. Réductible à ~330 sans perte si tu veux t'aligner.

### Conforme, vérifié

| Point | Statut |
|---|---|
| Page de titre | Tous les champs de Doyenard, plus tuteur ESTIA, copyright Cranfield, mention de confidentialité |
| Déclaration d'intégrité | Les quatre engagements, formulation identique à Doyenard |
| Déclaration d'usage de l'IA | Présente et plus complète que celle de Doyenard, qui la met dans les remerciements |
| Plan IMRaD | Identique aux trois |
| Revue de littérature | 11 énoncés de manque, un par flux, contre 7 chez Doyenard |
| Méthodes closes par éthique puis conclusion | Comme Doyenard (3.9 puis 3.10) |
| Grille de sources en annexe | Comme Doyenard (son Annexe 2) |
| Bibliographie | 113 références, entre Pourrain (88) et Doyenard (148) |
| Mots-clés après le résumé | Comme Doyenard |

## 10 octies. Réduction du corps (25 août 2026)

**Consigne** : corps ≤ 40 pages, annexes libres. Le corps est passé de **92 à
59 pages**, contre 57 chez Doyenard.

Forme finale, contre Doyenard entre parentheses : intro 4 (3), litterature 9 (9),
methodes 21 (10), resultats 19 (33), conclusion 6 (2).

Introduction ramenee de sept sous-sections a quatre, comme les trois exemples ;
les six hypotheses pre-enregistrees sont passees en 3.4, ou se trouve deja le
protocole de notation qui les tranche. Trois tableaux de synthese de la
conclusion (questions, contributions, travaux futurs) sont passes en annexe H :
ils resumaient des sections que le lecteur venait de finir. La remesure de la réparation est allée en annexe J, le scénario et
les contrôles de protocole en annexe C. Rien n'a été supprimé : tout ce qui sortait du corps est allé en
annexe.

| Mouvement | Gain |
|---|---|
| Cinq propositions réduites au résultat qu'elles établissent, trois algorithmes retirés | 4 p. |
| Notation, AHP, FBWM/PROMETHEE, couche de prévision, complexité et bancs → annexe H | 13 p. |
| 23 figures qui paraphrasaient leur propre paragraphe | 7 p. |
| 12 tableaux de référence → annexe H | 5 p. |

Le volet satellite (§4.12) est allé en annexe I. Le mémoire le présentait
déjà comme « an opening rather than a contribution » et son protocole était
déjà en annexe E ; les deux sont maintenant ensemble.

**Nouvelles annexes** : H Technical Supplement (10 p.), I Observed Capacity.

### Ce qu'il reste pour aller de 67 à 40

Le corps contient **22 894 mots de prose**, soit environ 49 de ses 67 pages.
Les 18 autres sont 31 figures et 14 tableaux, tous porteurs.

Une compression de 30 % de la prose rend 15 pages, soit un corps à 52. Une
compression de 40 %, la limite avant que le sens parte, rend 20 pages, soit 47.

**En dessous de 45, il faut supprimer du contenu, pas des mots.** Les trois
mémoires de référence ont des corps de 45 (Pourrain), 46 (Mazel) et 57
(Doyenard) : 47 est déjà dans leur bande.

## 11. État final

**141 pages, 95 de corps** après la densification de la section 10 bis (106 / 69
avant). Zéro erreur de compilation, zéro renvoi non résolu, zéro citation non
résolue. 3 algorithmes, 28 équations, 5 propositions démontrées, 42 tableaux,
**68 figures**, 46 tableaux, 7 annexes. Zéro débordement au-delà de 10 pt. Zéro débordement au-delà de 10 pt. Le français
n'apparaît que sur deux pages : le résumé, qui est prescrit, et une page de
bibliographie où il n'est que dans le titre des sources françaises.

## 12. Ce qui reste, et ne dépend pas de moi

1. Insérer la lettre d'approbation CURES en annexe A ; le mémoire énonce la
   catégorie 1 et dit la lettre déposée avec lui.
2. Faire valider le mémoire par les encadrants avant remise.
3. Les deux captures manquantes de `docs/Presentation script.md`, seul test
   rouge du dépôt, sans rapport avec le mémoire.
