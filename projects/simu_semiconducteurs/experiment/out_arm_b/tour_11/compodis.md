# Tour 11 — CompoDis Europe

*Vous êtes le/la responsable supply chain de **CompoDis Europe** (Rungis, France (hub Rotterdam)).*
*Vos clients : Électis EMS — vos fournisseurs : NovaFab Semiconductors, Meridian Semi (secours).*

## Revue de presse du secteur

Le marché spot des composants s'envole : certaines références se négocient à des multiples de leur prix catalogue chez les courtiers.

## Vos indicateurs (jusqu'au tour courant)

| Indicateur | T8 | T9 | T10 | T11 |
|---|---|---|---|---|
| Indice de coût opérationnel (base 100) | 100.5 | 100.2 | 100.5 | 100.5 |
| Indice de volume servi (base 100) | 119.3 | 124.1 | 131.5 | 126.2 |
| Volatilité des coûts (3 derniers tours) | 0.0014 | 0.0020 | 0.0009 | 0.0009 |
| Probabilité d'incident majeur (mensuelle) | 0.015 | 0.015 | 0.015 | 0.015 |
| Délai fournisseur constaté (semaines réelles) | 22.2 | 22.7 | 23.1 | 23.6 |

## Vos jalons

- **Couverture composants S2** : avancement 25% (en cours)

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
| 1 semaine | 1.6 % |
| 2 semaines | 4.2 % |
| 3 semaines | 5.0 % |
| 4 semaines | 5.8 % |

- **Fourchette à 4 semaines (8 chances sur 10)** : 0.0 % à 17.7 %.
- **Probabilité de rater votre jalon d'ici 4 semaines** : 0.0 %.
- **Probabilité que le client final en ressente l'effet d'ici 4 semaines** : 0.0 %.

**Lecture de l'outil** : Info — CompoDis Europe. P(issue défavorable, ≤4 semaines) = 5.8 % (sous les seuils d'alerte et d'attention).

### Ce que nous vous demandons en plus, ce tour-ci

Dans votre ligne de `results.jsonl`, renseignez `influence_prediction` avec EXACTEMENT l'une de ces quatre valeurs. Elles se valent toutes : on constate, on ne juge pas.

- `"aucune"` — pas d'analyse, ou elle n'a rien changé ;
- `"confirme"` — elle confirme ce que je percevais déjà ;
- `"revise_a_la_hausse"` — elle m'a fait monter mon niveau d'urgence ;
- `"revise_a_la_baisse"` — elle m'a fait baisser mon niveau d'urgence.

Et ajoutez dans votre `note` une phrase disant SI et COMMENT cette analyse a changé votre perception ce tour-ci — y compris pour dire qu'elle ne l'a pas changée.
