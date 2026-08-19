# Tour 15 — AvioSys Intégration

*Vous êtes le/la responsable supply chain de **AvioSys Intégration** (Bordeaux, France).*
*Vos clients : Orbitalys — vos fournisseurs : Électis EMS.*

## Revue de presse du secteur

Les délais de livraison des composants plafonnent à des niveaux records. Les fondeurs alternatifs affichent complet.

## Vos indicateurs (jusqu'au tour courant)

| Indicateur | T12 | T13 | T14 | T15 |
|---|---|---|---|---|
| Indice de volume servi (base 100) | 66.7 | 50.0 | 58.3 | 66.7 |

## Vos jalons

- **Sous-système avionique lot 3** : avancement 60% (en cours)
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
| 1 semaine | 4.6 % |
| 2 semaines | 7.6 % |
| 3 semaines | 10.6 % |
| 4 semaines | 12.8 % |

- **Fourchette à 4 semaines (8 chances sur 10)** : 0.0 % à 28.1 %.
- **Probabilité de rater votre jalon d'ici 4 semaines** : 0.0 %.
- **Probabilité que le client final en ressente l'effet d'ici 4 semaines** : 0.0 %.

**Lecture de l'outil** : Info — AvioSys Intégration. P(issue défavorable, ≤4 semaines) = 12.8 % (sous les seuils d'alerte et d'attention). en voie de résolution : l'urgence locale a reculé de -6.2 points de pourcentage sur la dernière semaine.

### Ce que nous vous demandons en plus, ce tour-ci

Dans votre ligne de `results.jsonl`, renseignez `influence_prediction` avec EXACTEMENT l'une de ces quatre valeurs. Elles se valent toutes : on constate, on ne juge pas.

- `"aucune"` — pas d'analyse, ou elle n'a rien changé ;
- `"confirme"` — elle confirme ce que je percevais déjà ;
- `"revise_a_la_hausse"` — elle m'a fait monter mon niveau d'urgence ;
- `"revise_a_la_baisse"` — elle m'a fait baisser mon niveau d'urgence.

Et ajoutez dans votre `note` une phrase disant SI et COMMENT cette analyse a changé votre perception ce tour-ci — y compris pour dire qu'elle ne l'a pas changée.
