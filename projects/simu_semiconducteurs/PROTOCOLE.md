# PROTOCOLE — Campagne de validation « Programme HÉLIOS »

Manuel d'opération de l'expérimentation (15 jours ouvrés). Version pré-enregistrée :
ce document est GELÉ à J5 avant le premier tour réel ; toute modification
ultérieure est consignée en annexe avec sa justification, jamais appliquée
silencieusement.

- **Objet** : valider empiriquement le score d'adéquation Ud/Ur de SupplyScore sur
  la crise des semi-conducteurs 2020-2022 rejouée (voir `scenario/narration.md`),
  avec 8 consultants (Ud humain, questionnaire AHP) et un Ur alimenté par des
  données réelles (INSEE, WSTS ; voir `data/raw/MANIFEST.md`).
- **Rôles** : facilitateur (injection, distribution, clôture, journal) ; doctorante
  (contrôle du protocole, placebo, relecture HC9 des fiches) ; 8 consultants
  (volet AHP uniquement) ; John (arbitrages, GO/NO-GO à J4).
- **Livrables générés** : `analysis/snapshots/tour_NN.json` (scores),
  sauvegardes zip par tour, journal de campagne (`JOURNAL.md`, tenu à la main).

---

## 1. Calendrier des 15 jours ouvrés

| Jour | Qui | Contenu |
|---|---|---|
| J1 | Facilitateur | Scénario finalisé + acquisition et vérification des séries (fait : voir MANIFEST). |
| J2 | Facilitateur | Pipeline de préparation + pack gelé (`HASHES.sha256`) (fait). |
| J3 | Facilitateur | Scripts setup/inject/export + générateur de fiches (fait). |
| J4 | Facilitateur + doctorante | **Dry run complet** (fait : 5 itérations, v5 validée) ; relecture HC9 d'un échantillon de fiches ; contrôle anti-fuite manuel ; **GO/NO-GO**. |
| J5 | Tous (30 min) | **Kickoff HÉLIOS** : présentation du programme, remise des cartes de rôle, « signature » du contrat + **T0 d'entraînement** ; gel du présent protocole. |
| J6-J14 | Consultants 20 min/j ; facilitateur ~30 min/j | **Campagne : 2 tours/jour** (T impair le matin, T pair en fin de journée) → 18 tours en 9 jours ouvrés. |
| J14 (soir) | Facilitateur | Marge : rattrapage des tours incomplets (la campagne peut glisser d'½ journée sans casser le calendrier). |
| J15 | Facilitateur + doctorante | Analyse (`analysis/analyse_campagne.py`) + **débrief-reveal** collectif (30 min) : révélation de la crise réelle, question « à quel tour l'aviez-vous reconnue ? » (HC4), restitution des courbes à chaud. |

Si la campagne déborde de plus de 2 tours à J14 : tronquer la fenêtre à T16
(décembre 2021) plutôt que bâcler les réponses — décision pré-actée ici.

## 2. Journée type de campagne

| Heure | Action | Commande |
|---|---|---|
| 8h45 | Injection du tour N (KPIs + jalons + événements) | `inject_tour.py --tour N --db-dir <DB>` |
| 8h50 | Génération + distribution des fiches du tour | `make_briefings.py --tour N` (+ `--placebo` aux tours 9 et 15) |
| 9h00-11h00 | Fenêtre de réponse du matin (AHP dans l'UI, ≤ 10 min/consultant) | — |
| 11h00 | Vérifier la couverture 8/8, relancer les manquants | `export_state.py --db-dir <DB>` |
| 11h30 | Clôture du tour N | `inject_tour.py --tour N --advance-only --db-dir <DB>` |
| 16h30 | Injection tour N+1 + fiches | idem matin |
| 16h45-17h45 | Fenêtre de réponse du soir | — |
| 17h45 | Couverture, relances, clôture, journal de campagne | idem matin + note dans `JOURNAL.md` |

La clôture (`--advance-only`) produit automatiquement le snapshot du tour et la
sauvegarde zip. La couverture DOIT être vérifiée AVANT la clôture (après
`advance_week`, la semaine courante repart à zéro — constaté au dry run).

## 3. Instructions consultants (à joindre à la carte de rôle)

1. Deux fois par jour (matin, fin de journée), lisez VOTRE fiche du tour puis
   remplissez le volet AHP dans l'outil : ≤ 10 minutes.
2. Les 4 critères comparés : impact opérationnel, fenêtre temporelle,
   dépendances aval, récupérabilité.
3. L'outil refuse un questionnaire incohérent (CR ≥ 0.10) : il vous guide vers
   la comparaison la plus contradictoire — 2 tentatives, sinon prévenez le
   facilitateur (règle de report).
4. Vous ne voyez QUE votre fiche. Pas de concertation entre rôles pendant la
   campagne (déjeuners compris — parlez d'autre chose).
5. N'ouvrez ni le tableau de bord ni les scores : uniquement la page
   questionnaire. Vos scores vous seront montrés au débrief.
6. Il n'y a pas de bonne réponse : déclarez ce que vous percevez, pas ce que
   vous croyez attendu.

## 4. Contingences (pré-actées)

| Situation | Règle |
|---|---|
| Consultant absent sur un créneau | Le facilitateur pose « confirmer à l'identique » avec la note `absent_T{N}` — tracé, exclu des analyses de réactivité. |
| 2 absences consécutives | Nœud marqué pour analyse de sensibilité (exclusion testée en U10). |
| CR ≥ 0.10 après 2 tentatives | Report « à l'identique » avec note `cr_echec_T{N}`. |
| Incident technique | Base sauvegardée à chaque clôture (`backups/`) ; restauration : dézipper la dernière archive dans le db-dir. |
| AHP > 10 min constaté à T0 | Passage à 1 tour/jour et fenêtre tronquée à T16 (HC2). |
| Débordement > 2 tours à J14 | Troncature à T16 (jamais de bâclage). |

## 5. Registre d'hypothèses pré-enregistré

Le registre complet (hypothèses testables HA1-HA6 avec prédictions chiffrées et
critères de réfutation ; hypothèses assumées HB/HC/HD avec statut, impact si
faux et test de sensibilité) est celui du plan d'expérimentation validé — il est
reproduit dans `analysis/analyse_campagne.py` (docstring) qui implémente
chaque test. Résumé des hypothèses testées :

| # | Prédiction | Métrique |
|---|---|---|
| HA1 latence cognitive | corrélation croisée Ud/Ur maximale à lag ≥ 1 pour ≥ 5 nœuds/8 | Spearman décalé, bootstrap IC95 |
| HA2 détection précoce | H > 0.3 sur NovaFab à au moins un tour de T6-T12 (avant T13) | série H(t) |
| HA3 criticité structurelle | NovaFab top-1 par delta_ur_final parmi les fournisseurs PROFONDS (rang ≥ 4 : NovaFab, Meridian, SilPure) sur ≥ 80 % des tours informatifs (réseau non saturé) | rang par tour ; tours saturés exclus (dégénérescence documentée, cf. §6.7 — reformulé au dry run v5 AVANT gel) |
| HA4 validité prédictive | précision ET rappel > 0.5 au seuil H ≥ 0.5, horizon 4 tours | matrice de confusion |
| HA5 simple urgence | ΔUd des nœuds NON touchés > 0 aux tours à événement de presse (T6, T7, T13) | ΔUd touchés vs non touchés |
| HA6 hystérésis | pente de décroissance Ud < 50 % de celle de Ur sur T17-T18 | pentes comparées |

Toute analyse hors de cette liste est étiquetée EXPLORATOIRE dans le rapport.

## 6. Décisions méthodologiques actées au dry run (à connaître pour l'analyse)

Cinq itérations de dry run (v1-v5) ont calibré le scénario. Décisions et
constats à retenir — tous documentés dans les commentaires de `scenario.py` :

1. `env_exposure`/`political_risk` sont des aléas mensuels [0, 0.10] rebasés
   depuis WRI/WGI (les indices bruts saturent le OU probabiliste).
2. Chaque nœud garde toujours un jalon ACTIVE (sinon le modèle le passe DONE
   et son Ur tombe à 0 — comportement documenté du moteur).
3. Les jalons en dérive sont re-planifiés officiellement (revue de programme),
   comme dans la réalité — sinon un jalon dépassé épingle u_time à 1.0.
4. La couverture de stock d'AvioSys passe par flow/demand (la sémantique volume
   du modèle mesure la saturation d'entrepôt, pas la couverture).
5. Les délais clients (12 → 25 semaines) sont portés par CompoDis qui les
   subit ; NovaFab porte son cycle de production propre (stable).
6. L'érosion hebdomadaire des événements (`apply_weekly_decay`) est déclenchée
   par le facilitateur à chaque tour (« semaine sans nouvel incident »).
7. **Pour HA3** : quand le réseau est saturé, `delta_ur_final` s'écrase à 0 pour
   tout le monde (le risque déjà réalisé n'est plus « choquable » — comportement
   documenté du service) et `delta_ur_max` mesure alors « qui est calme »
   (signal inversé, constaté au dry run v5). Décision : les tours saturés sont
   EXCLUS du test HA3, la comparaison se fait entre fournisseurs profonds
   (rang ≥ 4) uniquement — comparer NovaFab à CompoDis mesurerait la proximité
   topologique du rang 0, pas la criticité intrinsèque. Constat à verser au BST.
8. La décrue P5 du Ur de NovaFab est FAIBLE (0.955 → 0.911) — historiquement
   honnête (les facturations mondiales restaient hautes début 2022). HA6 se
   lira surtout sur l'écart de pente Ud vs Ur, pas sur une chute du Ur.

## 7. Aveuglement et intégrité

- Les consultants n'accèdent qu'à la page questionnaire (règle de protocole ;
  pas de verrou technique — limite documentée HC7).
- Pack de données gelé avant T1 (`data/prepared/HASHES.sha256`) ; toute
  régénération en cours de campagne invaliderait l'expérimentation.
- Fiches placebo : (AvioSys, T9) et (SilPure, T15) — remises par la doctorante
  aux consultants concernés SANS mention de leur nature ; consigné dans le
  journal. Au débrief, l'écart de leur Ud à ces tours est le contrôle HC4.
- Tout écart au protocole (absence, retard, question d'un consultant qui
  révèle une info) est consigné dans `JOURNAL.md` le jour même.

## 8. Affectation des rôles

| Consultant | operator_id | Entreprise | Nœud |
|---|---|---|---|
| (nom à compléter) | C1 | Orbitalys | orbitalys |
| (nom à compléter) | C2 | AvioSys Intégration | aviosys |
| (nom à compléter) | C3 | Électis EMS | electis |
| (nom à compléter) | C4 | CompoDis Europe | compodis |
| (nom à compléter) | C5 | TransGlobal Fret | transglobal |
| (nom à compléter) | C6 | NovaFab Semiconductors | novafab |
| (nom à compléter) | C7 | Meridian Semi | meridian |
| (nom à compléter) | C8 | SilPure Materials | silpure |

Attribution recommandée : NE PAS donner NovaFab/CompoDis (rôles les plus
chargés en information) aux consultants les plus expérimentés en supply chain —
répartir l'expérience entre les rangs pour ne pas confondre effet de rôle et
effet d'expertise (décision d'affectation consignée au journal avant T0).

## 9. Base de campagne

- Emplacement : `%LOCALAPPDATA%\SupplyScore\simu_semiconducteurs\` — JAMAIS dans
  un dossier synchronisé cloud (WAL + sync = risque de corruption, documenté
  au dépôt).
- Initialisation : `setup_scenario.py --db-dir <DB>` (une seule fois).
- Le dry run utilise `simu_semiconducteurs_dryrun` — base distincte, jetable.
