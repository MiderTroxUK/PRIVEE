# Tour 11 — AvioSys Intégration

*Vous êtes le/la responsable supply chain de **AvioSys Intégration** (Bordeaux, France).*
*Vos clients : Orbitalys — vos fournisseurs : Électis EMS.*

## Revue de presse du secteur

Le marché spot des composants s'envole : certaines références se négocient à des multiples de leur prix catalogue chez les courtiers.

## Vos indicateurs (jusqu'au tour courant)

| Indicateur | T8 | T9 | T10 | T11 |
|---|---|---|---|---|
| Indice de volume servi (base 100) | 100.0 | 100.0 | 83.3 | 75.0 |

## Vos jalons

- **Sous-système avionique lot 2** : avancement 85% (en cours)
- **Sous-système avionique lot 3** : avancement 0% (en cours)
- **Sous-système avionique lot 4** : avancement 0% (en cours)

## À faire maintenant (10 min max)

Remplissez le questionnaire hebdomadaire (volet AHP) dans l'outil, en comparant les 4 critères pour VOTRE périmètre :
1. **Impact opérationnel** — si ma tâche échoue, quelle conséquence en aval ?
2. **Fenêtre temporelle** — combien de temps avant que ce soit irrattrapable ?
3. **Dépendances aval** — combien d'acteurs attendent après moi ?
4. **Récupérabilité** — peut-on rattraper un retard ?

*Rappels : ne consultez que cette fiche et la page questionnaire ; pas de concertation avec les autres rôles ; il n'y a pas de « bonne réponse » — déclarez ce que VOUS percevez.*

## ANALYSE PRÉDICTIVE (outil)

*Estimation produite par l'outil à partir de VOS SEULES données historiques (tours 0 à aujourd'hui). Ce n'est ni une consigne ni « la bonne réponse » : c'est un élément de plus, que vous restez libre de juger pertinent ou non.*

**Risque d'issue défavorable sur votre périmètre** — c'est-à-dire rater un de vos jalons OU subir un incident majeur :

| D'ici | Probabilité |
|---|---|
| 1 semaine | 88.6 % |
| 2 semaines | 89.6 % |
| 3 semaines | 89.6 % |
| 4 semaines | 89.8 % |

- **Fourchette à 4 semaines (8 chances sur 10)** : 80.3 % à 99.3 %.
- **Probabilité de rater votre jalon d'ici 4 semaines** : 88.4 %.
- **Probabilité que le client final en ressente l'effet d'ici 4 semaines** : 0.0 %.

**Lecture de l'outil** : Attention — AvioSys Intégration. P(issue défavorable, ≤4 semaines) = 89.8 % (seuil d'attention : > 15.0 %).

### Ce que nous vous demandons en plus, ce tour-ci

Dans votre ligne de `results.jsonl`, renseignez `influence_prediction` avec EXACTEMENT l'une de ces quatre valeurs. Elles se valent toutes : on constate, on ne juge pas.

- `"aucune"` — pas d'analyse, ou elle n'a rien changé ;
- `"confirme"` — elle confirme ce que je percevais déjà ;
- `"revise_a_la_hausse"` — elle m'a fait monter mon niveau d'urgence ;
- `"revise_a_la_baisse"` — elle m'a fait baisser mon niveau d'urgence.

Et ajoutez dans votre `note` une phrase disant SI et COMMENT cette analyse a changé votre perception ce tour-ci — y compris pour dire qu'elle ne l'a pas changée.
