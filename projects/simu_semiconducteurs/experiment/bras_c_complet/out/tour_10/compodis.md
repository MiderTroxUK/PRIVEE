# Tour 10 — CompoDis Europe

*Vous êtes le/la responsable supply chain de **CompoDis Europe** (Rungis, France (hub Rotterdam)).*
*Vos clients : Électis EMS — vos fournisseurs : NovaFab Semiconductors, Meridian Semi (secours).*

## Revue de presse du secteur

La sécheresse s'aggrave. Des fondeurs affrètent des camions-citernes pour alimenter leurs usines. Un fournisseur majeur de wafers annonce que ses capacités sont vendues jusqu'à fin 2022.

## Vos échanges clients / fournisseurs

NovaFab révise ses fenêtres de livraison « pour cause de contraintes industrielles temporaires ».

## Vos indicateurs (jusqu'au tour courant)

| Indicateur | T7 | T8 | T9 | T10 |
|---|---|---|---|---|
| Indice de coût opérationnel (base 100) | 100.8 | 100.5 | 100.2 | 100.5 |
| Indice de volume servi (base 100) | 123.5 | 119.3 | 124.1 | 131.5 |
| Volatilité des coûts (3 derniers tours) | 0.0028 | 0.0014 | 0.0020 | 0.0009 |
| Probabilité d'incident majeur (mensuelle) | 0.015 | 0.015 | 0.015 | 0.015 |
| Délai fournisseur constaté (semaines réelles) | 20.6 | 22.2 | 22.7 | 23.1 |

## Vos jalons

- **Couverture composants S2** : avancement 17% (en cours)

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
| 1 semaine | 1.2 % |
| 2 semaines | 2.6 % |
| 3 semaines | 4.8 % |
| 4 semaines | 6.0 % |

- **Fourchette à 4 semaines (8 chances sur 10)** : 0.0 % à 13.3 %.
- **Probabilité de rater votre jalon d'ici 4 semaines** : 0.0 %.
- **Probabilité que le client final en ressente l'effet d'ici 4 semaines** : 0.0 %.

**Lecture de l'outil** : Info — CompoDis Europe. P(issue défavorable, ≤4 semaines) = 6.0 % (sous les seuils d'alerte et d'attention).

### Ce que nous vous demandons en plus, ce tour-ci

Dans votre ligne de `results.jsonl`, renseignez `influence_prediction` avec EXACTEMENT l'une de ces quatre valeurs. Elles se valent toutes : on constate, on ne juge pas.

- `"aucune"` — pas d'analyse, ou elle n'a rien changé ;
- `"confirme"` — elle confirme ce que je percevais déjà ;
- `"revise_a_la_hausse"` — elle m'a fait monter mon niveau d'urgence ;
- `"revise_a_la_baisse"` — elle m'a fait baisser mon niveau d'urgence.

Et ajoutez dans votre `note` une phrase disant SI et COMMENT cette analyse a changé votre perception ce tour-ci — y compris pour dire qu'elle ne l'a pas changée.
