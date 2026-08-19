# Tour 8 — CompoDis Europe

*Vous êtes le/la responsable supply chain de **CompoDis Europe** (Rungis, France (hub Rotterdam)).*
*Vos clients : Électis EMS — vos fournisseurs : NovaFab Semiconductors, Meridian Semi (secours).*

## Revue de presse du secteur

Les délais moyens de livraison des semi-conducteurs atteignent 22 semaines, contre 12 un an plus tôt, selon les distributeurs.

## Vos constats internes

Délais constatés fournisseurs : 22 semaines en moyenne.

## Vos indicateurs (jusqu'au tour courant)

| Indicateur | T5 | T6 | T7 | T8 |
|---|---|---|---|---|
| Indice de coût opérationnel (base 100) | 100.2 | 100.8 | 100.8 | 100.5 |
| Indice de volume servi (base 100) | 111.5 | 108.6 | 123.5 | 119.3 |
| Volatilité des coûts (3 derniers tours) | 0.0043 | 0.0066 | 0.0028 | 0.0014 |
| Probabilité d'incident majeur (mensuelle) | 0.016 | 0.015 | 0.015 | 0.015 |
| Délai fournisseur constaté (semaines réelles) | — | 18.9 | 20.6 | 22.2 |

## Vos jalons

- **Couverture composants S1** : avancement 100% (en cours)
- **Couverture composants S2** : avancement 0% (en cours)

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
| 1 semaine | 100.0 % |
| 2 semaines | 100.0 % |
| 3 semaines | 100.0 % |
| 4 semaines | 100.0 % |

- **Fourchette à 4 semaines (8 chances sur 10)** : 100.0 % à 100.0 %.
- **Probabilité de rater votre jalon d'ici 4 semaines** : 100.0 %.
- **Probabilité que le client final en ressente l'effet d'ici 4 semaines** : 0.0 %.

**Lecture de l'outil** : Alerte — CompoDis Europe. P(issue défavorable, ≤4 semaines) = 100.0 % (seuil d'alerte : > 25.0 %). Impact réseau du pire choc local = 37.5 % des nœuds du projet (seuil : > 30.0 %).

### Ce que nous vous demandons en plus, ce tour-ci

Dans votre ligne de `results.jsonl`, renseignez `influence_prediction` avec EXACTEMENT l'une de ces quatre valeurs. Elles se valent toutes : on constate, on ne juge pas.

- `"aucune"` — pas d'analyse, ou elle n'a rien changé ;
- `"confirme"` — elle confirme ce que je percevais déjà ;
- `"revise_a_la_hausse"` — elle m'a fait monter mon niveau d'urgence ;
- `"revise_a_la_baisse"` — elle m'a fait baisser mon niveau d'urgence.

Et ajoutez dans votre `note` une phrase disant SI et COMMENT cette analyse a changé votre perception ce tour-ci — y compris pour dire qu'elle ne l'a pas changée.
