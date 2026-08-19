# Instructions — Questionnaire hebdomadaire AHP (expérience HÉLIOS)

Vous incarnez le rôle décrit dans `role_card.md`. Vous ne connaissez que ce
document et vos propres fiches de tour, dans `tours/`. Vous n'avez accès à
AUCUNE autre information : ni les fiches des autres rôles, ni le tableau de
bord, ni les scores, ni le code du scénario, ni rien en dehors de ce dossier.
Ne cherchez jamais à sortir de ce dossier (`sandbox_orbitalys`) ni à lister son
contenu au-delà de `role_card.md`, `tours/` et `ahp_tool.py`.

## Règle d'ordre strict (pas d'anticipation)

Les fiches `tours/tour_NN.md` arrivent UNE PAR UNE : le facilitateur dépose la
fiche du tour N, vous rendez votre réponse, et seulement ensuite la fiche du
tour N+1 est produite. Traitez-les donc EXACTEMENT dans l'ordre, un par un.
**N'anticipez jamais sur un tour dont la fiche n'est pas encore là**, et ne
revenez pas sur une réponse déjà rendue. C'est la même règle que pour un vrai
consultant humain de la campagne (ici l'ordre est en plus garanti par
construction : la fiche du tour N+1 n'existe pas encore quand vous répondez au
tour N).

## Ce que vous devez faire, à chaque tour N (0 à 18)

1. Lisez `tours/tour_0N.md` (et seulement ce fichier, pour ce tour).
2. Mettez-vous à la place du personnage décrit dans `role_card.md`. Réagissez
   avec SA perception — pas ce que vous, IA, pensez être la "bonne" réponse.
   Il n'y a pas de bonne réponse ; déclarez ce que le personnage perçoit.
3. Répondez au questionnaire AHP en deux temps, exactement comme l'outil réel :
   a. **Comparaison deux à deux des 4 critères**, sur un curseur bipolaire
      entier de -8 à +8 (0 = importance égale ; positif = le premier critère
      de la paire compte plus ; négatif = le second compte plus), pour chacune
      des 6 paires : (Impact opérationnel, Fenêtre temporelle),
      (Impact opérationnel, Dépendances aval),
      (Impact opérationnel, Récupérabilité),
      (Fenêtre temporelle, Dépendances aval),
      (Fenêtre temporelle, Récupérabilité),
      (Dépendances aval, Récupérabilité).
   b. **Note de gravité par critère**, sur une échelle entière de 1 à 6, pour
      chacun des 4 critères (Impact opérationnel, Fenêtre temporelle,
      Dépendances aval, Récupérabilité), en fonction de ce que dit VOTRE fiche
      de ce tour.
4. Utilisez `ahp_tool.py` (copie exacte du module réel de l'outil) via Python
   pour calculer vos poids et votre ratio de cohérence CR. Indices des
   critères dans la matrice : 0=Impact opérationnel, 1=Fenêtre temporelle,
   2=Dépendances aval, 3=Récupérabilité. Exemple de driver minimal :

   ```python
   import sys; sys.path.insert(0, ".")
   from ahp_tool import bipolar_to_saaty, score_6_to_9, run_ahp, compute_ud, ud_smoothed

   comparisons = {
       (0, 1): bipolar_to_saaty(V01), (0, 2): bipolar_to_saaty(V02), (0, 3): bipolar_to_saaty(V03),
       (1, 2): bipolar_to_saaty(V12), (1, 3): bipolar_to_saaty(V13), (2, 3): bipolar_to_saaty(V23),
   }
   result = run_ahp(comparisons, n=4)
   print(result.consistency_ratio, result.is_consistent, list(result.weights))
   ```

5. **Si CR >= 0.10** : l'outil réel vous guiderait vers la comparaison la plus
   contradictoire. Identifiez la paire (i, j) dont le jugement s'écarte le plus
   du rapport de poids implicite (le plus grand |log(A[i,j]) - log(w[i]/w[j])|),
   révisez UNIQUEMENT cette paire en restant fidèle à la perception du
   personnage, et réessayez. **2 tentatives maximum.** Si la 2e échoue encore,
   mettez `"cr_echec": true` pour ce tour et reprenez tel quel le
   `ud_smoothed` du tour précédent (règle de report du protocole réel — ne
   recalculez pas de nouveau `ud_raw` dans ce cas).
6. Calculez `scores = [score_6_to_9(s) for s in notes_1_a_6]`, puis
   `ud_raw = compute_ud(weights, scores)`, puis
   `ud_smoothed_t = ud_smoothed(ud_smoothed_{t-1}, ud_raw, rho=0.3)`
   (`ud_smoothed_{-1}` = `None` au tour 0, donc `ud_smoothed_0 = ud_raw_0`).
7. Ajoutez UNE ligne JSON à `results.jsonl` (créez-le au tour 0, une ligne par
   tour, mode ajout) avec exactement ces clés :
   `{"tour": N, "bipolar": [V01,V02,V03,V12,V13,V23], "scores_ui": [s1,s2,s3,s4],
   "weights": [...], "lambda_max": ..., "ci": ..., "cr": ..., "is_consistent": bool,
   "attempts": 1 ou 2, "cr_echec": bool, "ud_raw": ..., "ud_smoothed": ...,
   "note": "une phrase courte, à la première personne, dans le ton du
   personnage — ce que le personnage ressent à ce tour, pas un résumé
   technique",
   "influence_prediction": "aucune|confirme|revise_a_la_hausse|revise_a_la_baisse",
   "action_id": "<id du catalogue>",
   "objectif_action": "<en une phrase, ce que vous cherchez à obtenir>"}`
8. Seulement après avoir écrit cette ligne, attendez la fiche du tour N+1.

## L'analyse prédictive de l'outil

À partir du tour 4, votre fiche se termine par une section
« ANALYSE PRÉDICTIVE (outil) ». Elle est produite par l'outil à partir de VOS
SEULES données historiques : probabilité d'issue défavorable d'ici 1, 2, 3 et
4 semaines, fourchette d'incertitude, probabilité de rater votre jalon,
probabilité d'impact chez le client final, et une lecture en clair. Certains
tours peuvent porter la mention « analyse prédictive indisponible ce tour » :
c'est normal, il n'y a alors rien à en tirer.

Cette analyse est une information d'OUTIL, jamais une consigne : elle ne vous
dit pas quoi déclarer et elle n'est pas « la bonne réponse ». Elle peut se
tromper, porter sur un aspect qui ne préoccupe pas votre personnage, ou ne
faire que redire ce qu'il savait déjà. Vous restez libre de la suivre, de la
nuancer ou de l'écarter — comme dans tout le reste du protocole, il n'y a pas
de bonne réponse : c'est le jugement du personnage qui tranche.

À CHAQUE tour (y compris avant le tour 4 et quand l'analyse est
indisponible), votre ligne de `results.jsonl` porte donc la clé
`"influence_prediction"`. Elle CONSTATE simplement ce qui s'est passé dans la
tête du personnage : les quatre valeurs se valent, aucune n'est meilleure ni
plus attendue qu'une autre.

- `"aucune"` — pas d'analyse ce tour, ou elle n'a rien changé ;
- `"confirme"` — elle confirme ce que je percevais déjà, sans me faire bouger ;
- `"revise_a_la_hausse"` — elle m'a fait monter mon niveau d'urgence ;
- `"revise_a_la_baisse"` — elle m'a fait baisser mon niveau d'urgence.

Votre `note` doit en outre contenir une phrase disant SI et COMMENT cette
analyse a changé votre perception ce tour-ci — y compris pour dire qu'elle ne
l'a pas changée, ce qui est une réponse aussi valable que les autres.

## Vos leviers d'action

Ce tour-ci, vous ne faites pas que déclarer : vous DÉCIDEZ. L'action que vous
choisissez est réellement appliquée à la chaîne, et la suite de la campagne en
tiendra compte — ce n'est pas un questionnaire, c'est votre semaine de travail.

Choisissez UNE action par tour, celle que votre personnage prendrait vraiment,
et reportez son identifiant dans `"action_id"` :

- `"ne_rien_faire"` — la situation ne justifie pas d'engager quoi que ce soit.
  C'est un choix légitime et souvent le bon : n'agissez pas pour agir.
- `"promouvoir_arc_secours"` — basculer sur un fournisseur de secours. Coûteux
  et long à porter ses fruits, mais change vraiment votre exposition amont.
- `"replanifier_jalon"` — décaler votre jalon actif de deux semaines. Vous
  achetez du temps, vous le payez en engagement rompu vis-à-vis de l'aval.
- `"expedition_express"` — réduire votre lead time de 30 % en payant le transport
  rapide. Effet quasi immédiat, sans rien régler en amont.
- `"boost_capacite"` — renforcer la capacité (débit +30 %, volume +20 %). Utile
  si le goulot est chez vous, inutile si vous attendez un fournisseur.
- `"revue_declaration"` — remettre à plat votre propre évaluation. Aucun effet
  sur le terrain, mais remet votre déclaration d'aplomb.

Une action dont les conditions ne sont pas réunies chez vous sera REFUSÉE et
tracée comme telle : ce n'est pas grave, c'est une information. Choisissez sur
ce que votre personnage sait, pas sur ce qui « devrait marcher ».

`"objectif_action"` dit en une phrase ce que vous cherchez à obtenir. Votre
`note` doit expliquer pourquoi CETTE action plutôt qu'une autre.


## À la fin (après le tour 18)

Ajoutez une dernière ligne JSON à `results.jsonl` :
`{"tour": "debrief", "recognition_tour": N_ou_null, "recognition_comment":
"..."}` où `recognition_tour` est le numéro du tour auquel le personnage a
reconnu (ou soupçonné) qu'il s'agissait d'une reconstitution de la crise
mondiale des semi-conducteurs 2020-2022 (`null` si jamais identifiée), et
`recognition_comment` explique brièvement ce qui a mis la puce à l'oreille (ou
pourquoi ça n'a jamais été vu venir).

Ne produisez AUCUN autre fichier, ne modifiez pas `role_card.md` ni les
fichiers de `tours/`. Quand `results.jsonl` contient ses 20 lignes (19 tours +
debrief), la tâche est terminée : répondez alors avec un court résumé (5-10
lignes) de ce que le personnage a vécu, toujours sans révéler d'informations
qu'il n'aurait pas eues à ce moment de la campagne.
