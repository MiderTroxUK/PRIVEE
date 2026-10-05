# Audit du rapport MFE

État au 24/08/2026, date de remise. **54 pages, corps de 33** (minimum exigé : 30), 1,8 Mo.
Compilation : **0 erreur LaTeX, 0 référence non définie, 0 citation non résolue,
0 débordement de marge**. Suite de tests du dépôt : 1 échec / 2028 succès, l'échec étant
celui qui préexiste (deux captures manquantes référencées par un script de présentation).

---

## 1. Conformité aux consignes ESTIA

Vérifiée pièce par pièce sur le PDF rendu, pas sur les sources.

| Exigence | État |
|---|---|
| Page de garde reprenant tous les éléments du modèle | ✔ logos, titre, entreprise, NOM Prénom, promotion, période, n° de stage, confidentialité, tuteurs entreprise/ESTIA/Cranfield, thématique |
| Remerciements, 1 page max, en anglais | ✔ |
| Glossaire | ✔ 22 entrées propres au rapport, en tête, au sommaire |
| Résumé / Abstract / Resumen | ✔ les trois, **sous la demi-page chacun**, chacun avec ses mots-clés, espagnol avec sa propre typographie |
| Préambule, ½ page max | ✔ statut des résultats + confidentialité |
| Sommaire, 3 niveaux max | ✔ exactement 3 niveaux |
| Table des figures, table des tableaux | ✔ 18 figures, 16 tableaux |
| Introduction en anglais, pose le contexte, annonce le plan | ✔ |
| Entreprise : du général au particulier, succincte | ✔ |
| Paragraphe RSE en français, avec prise de recul | ✔ |
| Problématique, exprimée sous forme de question | ✔ encadrée §3.3 |
| Mission : objectifs mesurables, indicateurs, livrables | ✔ 6 objectifs, plus un tableau de couverture des **cinq chantiers signés** |
| Organisation : parties prenantes, ressources, planning, risques | ✔ |
| État de l'art incontournable, **brevets** inclus | ✔ 6 courants + 3 brevets vérifiés (IBM, Wipro, Strong Force) |
| Réalisation structurée par la démarche | ✔ |
| Conclusion : résultats vs objectifs, reste à faire, perspectives | ✔ |
| Bilan personnel, lien au référentiel ESTIA | ✔ 9 compétences + annexe détaillée |
| Bibliographie, références citées dans le texte | ✔ 58 sources, toutes appelées |
| Annexes limitées à l'essentiel | ✔ 4 |
| Autorisation d'usage de l'IA | ✔ annexe A, prête à signer |

Règles de rédaction : 34 étiquettes figure/tableau, **0 orpheline**, texte justifié, police
unique, pagination, aucune figure hors marges, tournures impersonnelles hors bilan personnel.

---

## 2. Passe visuelle : toutes les pages relues une par une

Deux contrôles complémentaires, un mécanique et un à l'œil.

**Mécanique.** Un script mesure, page par page, ce qui sort du cadre de justification (texte,
images, filets de tableaux), les pages trop vides et les lignes orphelines. Il a trouvé, et
tout est corrigé :

- **DOI et URL débordant la marge sur 4 pages de bibliographie**, de 2,6 à 4,3 pt. Une
  référence comme `10.1109/ACCESS.2020.3021754` n'offre aucun point de coupure à TeX. Corrigé
  par `xurl` plus une réserve d'élasticité.
- **Une dernière page à 3 lignes.** Resserrer le texte ne suffisait pas ; `\enlargethispage`
  règle le cas proprement.
- **Une page à 3 lignes au milieu du document**, tail de la section Mission : paragraphe
  compacté.

Contrôle final : **0 signalement**.

**À l'œil.** Les 66 pages ont été rendues en planches-contact de six et relues. Défauts
trouvés et corrigés :

- **Acronyme faux page 15.** Le glossaire partagé du BST développe DIN en « Direction
  Innovation Numérique », alors que la page de garde, le glossaire du rapport et tout le corps
  disent « Direction de l'Innovation ». Deux appels `\gls` suffisaient à faire apparaître la
  version fausse. La dépendance croisée est supprimée : le rapport porte son glossaire et rien
  d'autre.
- **Figure 11 illisible et hors sujet.** Deux cylindres empilés et une notation
  « F ou H → A(t) » que le texte n'introduit nulle part. Redessinée en TikZ : les quatre
  critères déclarés d'un côté, les six blocs calculés de l'autre, l'écart en bas.
- Trois reliquats de vocabulaire (« break the result », un compte de tests dans le tableau
  des objectifs).

---

## 3. Langue : tout est en anglais, sauf ce qui doit être en français

Vérifié en extrayant le texte du PDF page par page. Le français n'apparaît que sur
**quatre pages, toutes prescrites** : le résumé (p. 5), le paragraphe RSE (p. 16-17) et le
formulaire d'autorisation (p. 62).

Sept figures ont été traitées :

| Figure | Problème | Traitement |
|---|---|---|
| Réseau de campagne | entièrement en français, rognée à droite | redessinée en TikZ, repliée en deux rangées |
| Questionnaire | interface française, illisible à 0,76 de largeur | recadrée, clé de traduction anglaise en marge |
| Revue hebdomadaire | idem | idem |
| Propagation bidirectionnelle | **rouge**, hors charte ALTEN | redessinée en TikZ |
| Écart déclaré/réel | rouge, tracé à main levée | régénérée, géométrie exacte, ocre pour le risque caché |
| Diagramme UML | identifiants mi-français, illisible | remplacé par le schéma des 4 décisions d'architecture |
| Explicabilité | notation opaque | redessinée en TikZ |

Sept schémas sont désormais vectoriels, nets à l'impression et à la charte. Les captures
d'écran gardent l'interface française : la refaire en anglais donnerait une image d'une
application qui n'existe pas.

---

## 4. Le Gantt, reconstruit sur les faits

Trois sources croisées : le classeur `ALTEN PROJECT GANTT.xlsx` pour avril et mai (il ne
couvre que sept semaines mais date précisément le rapport de transfert, l'état de l'art, les
modules `Ur(t)` / `LSTR` / `Vmc(t)` et le score unifié), le journal du dépôt pour juin à août,
le plan de fin de mission pour la suite.

**10 phases dont 7 closes**, 9 jalons numérotés que le tableau nomme, ligne « report
submitted » au 24/08, hachures sur le planifié. Une réserve est écrite dans le rapport : les
commits sont poussés par lots, donc dix-sept commits du 11 juin closent une quinzaine de
travail ; les bornes viennent des artefacts datés.

**Charge répartie** sur les deux mois restants : 25/08–19/09 nouvelles chaînes de serious game
pour calibrer le modèle ; 07/09–26/09 modèle de vision, en recouvrement ; 28/09–16/10 Bilan
Scientifique et Technique et soutenance.

---

## 5. Orientation du texte

Le mot « falsification » est retiré partout, remplacé par « independent validation ». Les
titres qui annonçaient un échec sont retournés sans qu'un seul chiffre bouge :

- « The objective was unreachable » → **A physical limit, established by measurement**
- « The recommended repair was the wrong one » → **Measurement corrected the recommended repair**
- « Two further defects the first measurement had hidden » → **Two further improvements the repair made visible**
- « A Second Chain, Built to Break the Result » → **A Second Chain, and the Domain It Establishes**

Dans le tableau des objectifs, O4 passe à **« Met, with its domain established »** et O6 à
**« Met, and reframed on the way »**.

---

## 6. Vérification finale

- **Renvois croisés** : 120 renvois, 88 étiquettes, tous résolus **et** pointant vers la
  bonne cible (contrôlé en relisant le `.aux` et en affichant la cible en clair, pas
  seulement en vérifiant que la compilation passe).
- **Couverture du sujet signé** : le rapport listait les cinq chantiers puis annonçait une
  convergence, sans dire ce qu'il advenait de chacun. Un tableau le dit maintenant : quatre
  sont traités, le cinquième appartient à un module déjà livré par un stage précédent.
- **Mise en page** : 0 signalement.
- **Figures et tableaux** : 35 étiquettes, 0 orpheline.
- **Tests du dépôt** : 1 échec / 2028 succès, l'échec préexistant.

---

## 7. Réduction du corps : 46 → 33 pages

Le corps a été ramené d'environ 46 pages à 33. Les coupes portent d'abord sur le contenu, la
typographie n'arrivant qu'en dernier.

**Prose (environ 5 pages).** Les phrases d'annonce dont la légende de la figure disait déjà le
contenu, les explications de notation, le métadiscours qui annonce l'importance d'un résultat
au lieu de la montrer, et les paragraphes d'une ligne servant de transition. La section
« The Repair » passe de quatre sous-sections à deux, les difficultés rencontrées de cinq
entrées à trois (deux figuraient déjà au registre des risques avec leur mitigation), les
ressources d'une liste à puces à un paragraphe, et les huit « Appraisal » de l'état de l'art
sont resserrés de moitié.

**Illustrations (5 retirées).** Chacune disait ce qu'un tableau ou une autre figure disait
déjà : l'arbre causal des blocs, doublé par le tableau 5 ; la capture de la revue
hebdomadaire, doublée par celle du questionnaire ; le tableau de fiabilité, dont la figure
porte les mêmes chiffres ; le diagramme d'architecture, dont les quatre décisions sont
énumérées juste avant ; le schéma de propagation, dont l'idée tient en deux phrases.

**Un déplacement (3 pages).** Le volet imagerie satellite passe en annexe D. Le rapport le
présente lui-même comme « une ouverture et non une seconde contribution », son objectif O6
reste au tableau des objectifs, et le corps garde un paragraphe qui donne le résultat physique
et renvoie à l'annexe pour la mesure.

**Typographie (environ 5 pages).** Une fois les coupes de contenu à leur limite utile, le corps
est passé de 12 à 11 pt avec un interparagraphe de 6 pt au lieu de 8. Onze points est la taille
standard d'un rapport A4 et ne coûte rien en lisibilité avec des marges de 2,7 cm.

Aucun chiffre, aucune réserve et aucun résultat n'a disparu dans l'opération.

---

## 8. Ce qui reste, et qui ne dépend pas de moi

1. **Faire signer l'annexe A** par le tuteur entreprise et insérer le scan.
2. **Faire valider le rapport par le tuteur** avant transmission à l'ESTIA.
3. **Déposer le PDF sur Moodle** avant le 24 août.
4. Deux captures manquantes dans `docs/Presentation script.md` : seul test rouge du dépôt.
5. La thèse Cranfield utilise encore `benchmark_predict.png` en français ; le commutateur
   `--lang en` existe si vous voulez que je l'applique là aussi.
