# Tour 5 — Électis EMS

*Vous êtes le/la responsable supply chain de **Électis EMS** (Cholet, France).*
*Vos clients : AvioSys Intégration — vos fournisseurs : CompoDis Europe, TransGlobal Fret.*

## Revue de presse du secteur

Un grand constructeur automobile européen annonce des arrêts de lignes faute de puces. Le mot « pénurie » entre dans les titres.

## Vos échanges clients / fournisseurs

CompoDis officialise un « mode allocation » sur une partie de son catalogue : les volumes demandés ne seront pas tous servis.

## Vos indicateurs (jusqu'au tour courant)

| Indicateur | T2 | T3 | T4 | T5 |
|---|---|---|---|---|
| Indice de coût opérationnel (base 100) | 100.3 | 100.9 | 102.1 | 103.3 |
| Disponibilité de l'outil (0-1) | 0.93 | 0.94 | 0.94 | 0.95 |
| Performance de production (0-1) | 0.98 | 1.00 | 0.99 | 0.97 |
| Volatilité des coûts (3 derniers tours) | 0.0005 | 0.0024 | 0.0072 | 0.0096 |

## Vos jalons

- **Cartes HÉLIOS série A** : avancement 100% (en cours)
- **Cartes HÉLIOS série B** : avancement 0% (en cours)
- **Cartes HÉLIOS série C** : avancement 0% (en cours)

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
| 2 semaines | 3.0 % |
| 3 semaines | 4.8 % |
| 4 semaines | 6.8 % |

- **Fourchette à 4 semaines (8 chances sur 10)** : 0.0 % à 14.4 %.
- **Probabilité de rater votre jalon d'ici 4 semaines** : 0.0 %.
- **Probabilité que le client final en ressente l'effet d'ici 4 semaines** : 0.0 %.

**Lecture de l'outil** : Info — Électis EMS. P(issue défavorable, ≤4 semaines) = 6.8 % (sous les seuils d'alerte et d'attention).

### Ce que nous vous demandons en plus, ce tour-ci

Dans votre ligne de `results.jsonl`, renseignez `influence_prediction` avec EXACTEMENT l'une de ces quatre valeurs. Elles se valent toutes : on constate, on ne juge pas.

- `"aucune"` — pas d'analyse, ou elle n'a rien changé ;
- `"confirme"` — elle confirme ce que je percevais déjà ;
- `"revise_a_la_hausse"` — elle m'a fait monter mon niveau d'urgence ;
- `"revise_a_la_baisse"` — elle m'a fait baisser mon niveau d'urgence.

Et ajoutez dans votre `note` une phrase disant SI et COMMENT cette analyse a changé votre perception ce tour-ci — y compris pour dire qu'elle ne l'a pas changée.
