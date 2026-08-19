# Tour 12 — SilPure Materials

*Vous êtes le/la responsable supply chain de **SilPure Materials** (Kyūshū, Japon).*
*Vos clients : NovaFab Semiconductors — vos fournisseurs : (aucun en amont).*

## Revue de presse du secteur

Vague épidémique en Asie du Sud-Est : les usines d'assemblage et de test de composants tournent par rotations réduites. Le maillon aval de la filière, peu connu du grand public, devient le sujet.

## Vos indicateurs (jusqu'au tour courant)

| Indicateur | T9 | T10 | T11 | T12 |
|---|---|---|---|---|
| Indice de coût opérationnel (base 100) | 105.9 | 107.2 | 109.0 | 110.1 |
| Volatilité des coûts (3 derniers tours) | 0.0021 | 0.0067 | 0.0117 | 0.0108 |
| Probabilité d'incident majeur (mensuelle) | 0.008 | 0.008 | 0.007 | 0.007 |

## Vos jalons

- **Contrat wafers annuel** : avancement 87% (en cours)
- **Contrat wafers année suivante** : avancement 0% (en cours)

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
| 1 semaine | 1.0 % |
| 2 semaines | 1.8 % |
| 3 semaines | 3.0 % |
| 4 semaines | 4.0 % |

- **Fourchette à 4 semaines (8 chances sur 10)** : 0.0 % à 11.3 %.
- **Probabilité de rater votre jalon d'ici 4 semaines** : 0.0 %.
- **Probabilité que le client final en ressente l'effet d'ici 4 semaines** : 0.0 %.

**Lecture de l'outil** : Info — SilPure Materials. P(issue défavorable, ≤4 semaines) = 4.0 % (sous les seuils d'alerte et d'attention).

### Ce que nous vous demandons en plus, ce tour-ci

Dans votre ligne de `results.jsonl`, renseignez `influence_prediction` avec EXACTEMENT l'une de ces quatre valeurs. Elles se valent toutes : on constate, on ne juge pas.

- `"aucune"` — pas d'analyse, ou elle n'a rien changé ;
- `"confirme"` — elle confirme ce que je percevais déjà ;
- `"revise_a_la_hausse"` — elle m'a fait monter mon niveau d'urgence ;
- `"revise_a_la_baisse"` — elle m'a fait baisser mon niveau d'urgence.

Et ajoutez dans votre `note` une phrase disant SI et COMMENT cette analyse a changé votre perception ce tour-ci — y compris pour dire qu'elle ne l'a pas changée.
