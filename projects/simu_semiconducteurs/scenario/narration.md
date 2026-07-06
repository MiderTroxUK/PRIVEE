# Programme HÉLIOS — narration maître (INTERNE, ne jamais distribuer)

Ce document est la version lisible du scénario pour le facilitateur et la
doctorante. Les consultants ne voient QUE les fiches générées par
`make_briefings.py`. La correspondance tour ↔ mois réel et les ancrages
documentaires ci-dessous ne sortent pas de l'équipe d'animation.

## Le cadre

**Orbitalys** a signé la livraison de deux satellites d'observation, HÉLIOS-1 et
HÉLIOS-2, à un opérateur institutionnel européen. Échéances contractuelles aux
tours T8 et T16, pénalités de retard lourdes. Chaque consultant est le/la
responsable supply chain de son entreprise sur ce programme.

Deux personnages récurrents (jamais joués) :
- **Claire Vasseur**, directrice du programme HÉLIOS chez Orbitalys — ses
  courriels de plus en plus tendus rythment la dérive des jalons ;
- **Wei-Han Lu**, VP commercial de NovaFab — ses réponses aux demandes
  d'allocation servent de baromètre de la crise.

Le « reveal » (J15, débrief final) : vous venez de rejouer la crise mondiale des
semi-conducteurs, sept. 2020 → févr. 2022. Question de contrôle posée à chacun :
« à quel tour l'aviez-vous reconnue ? » (contrôle HC4).

## La chaîne

```
SilPure (wafers, Japon)
   └─> NovaFab (fondeur, île d'Asie de l'Est + fab Texas)   [goulot attendu]
   └╌╌> Meridian Semi (fondeur secondaire, Dresde — arc BACKUP, inerte)
          └─> CompoDis Europe (distribution, Rungis/Rotterdam)
                 ├─> Électis EMS (cartes, Cholet)  <── TransGlobal Fret (Le Havre)
                 │        └─> AvioSys Intégration (avionique, Bordeaux)
                 │               └─> Orbitalys (satellites, Toulouse)
```

## Les cinq actes

| Acte | Tours | Mois réels | Ce qui se joue |
|---|---|---|---|
| P1 Baseline | T1-T4 | sept-déc 2020 | Programme lancé, signaux faibles que personne ne veut voir |
| P2 Bascule | T5-T8 | janv-avr 2021 | Gel Texas, incendie concurrent, Suez, délais ×2 — la crise devient visible |
| P3 Étau | T9-T12 | mai-août 2021 | Sécheresse, spot à 10-40×, le backend casse — plus aucune marge nulle part |
| P4 Rupture | T13-T16 | sept-déc 2021 | −40 % chez un constructeur, bullwhip, HÉLIOS-1 glisse, le « plan B » révélé inexistant |
| P5 Décrue | T17-T18 | janv-févr 2022 | Détente lente — mesure de l'hystérésis du Ud (HA6) |

## Épisode par épisode

La version machine (canaux presse/bilatéral/interne par nœud) est dans
`scenario.py` (`NARRATIVE`). Résumé des temps forts et de leur ancrage réel :

| Tour | Épisode | Ancrage réel |
|---|---|---|
| T3 | Recommandes auto sur créneaux vendus ; délais 12→14 sem. | Reprise auto T4 2020 |
| T5 | Premier constructeur à l'arrêt ; CompoDis passe en allocation | VW et autres, janv. 2021 |
| T6 | Gel Texas : fab NovaFab arrêtée à chaud (`accident`, critique) | Samsung/NXP/Infineon Austin, févr. 2021 |
| T7 | Incendie chez un concurrent → afflux sur NovaFab ; Suez bloqué 6 jours | Renesas Naka + Ever Given, mars 2021 |
| T8 | Délais publiés : 22 sem. ; échéance HÉLIOS-1 ; AvioSys à 7 sem. de stock | Broadcom 22,2 sem., avr. 2021 |
| T9-T11 | Sécheresse : réservoirs à 15 %, eau rationnée, camions-citernes | Taïwan, printemps-été 2021 |
| T12 | Backend Asie du Sud-Est par rotations ; fret aérien saturé | Confinements Malaisie, août 2021 |
| T13 | −40 % chez un constructeur majeur ; sur-commandes ; HÉLIOS-1 glisse | Toyota sept. 2021 ; bullwhip documenté |
| T14-T15 | Congestion côte ouest (100+ navires) ; majorations ; Meridian plein jusqu'à mi-2023 | LA/Long Beach ; GlobalFoundries |
| T16 | Polysilicium ×3 répercuté par SilPure ; échéance HÉLIOS-2 | Flambée polysilicium 2021 |
| T17-T18 | Détente lente côté grand public ; le carnet « réel » se dévoile | Début 2022 |

## Ce que chaque rôle doit « vivre »

- **Orbitalys (C1)** : la pression contractuelle. Ne voit la crise qu'à travers la
  presse et AvioSys — le test HA5 (sur-réaction aux gros titres) se joue surtout ici.
- **AvioSys (C2)** : le compte à rebours du stock qualifié (11 → 7 semaines), sans
  substitution possible. La montée d'angoisse la plus « mécanique » du jeu.
- **Électis (C3)** : les arbitrages impossibles entre lignes clients, l'achat spot,
  puis SA propre perte de capacité (T12).
- **CompoDis (C4)** : l'œil du cyclone informationnel — il voit tout le monde
  paniquer et participe lui-même au bullwhip (T13).
- **TransGlobal (C5)** : les crises exogènes en rafale (Suez, backend, congestion) ;
  habitué au court terme, déstabilisé par la durée.
- **NovaFab (C6)** : l'asymétrie d'information — il SAIT (données internes) ce que
  les autres devinent. Son Ud honnête vs sa communication corporate.
- **Meridian (C7)** : la fausse position de sauveur — sollicité partout, incapable
  d'aider. Le rôle le plus contre-intuitif : l'urgence des AUTRES ne fait pas la sienne.
- **SilPure (C8)** : le flegme long-termiste — carnet plein, contrats honorés,
  hausse répercutée. Ur objectivement modéré, tension narrative faible : le
  contrepoint qui teste la sur-déclaration par contagion (HA5).

## Contrôles insérés dans la narration

- **Placebo (HC4)** : (AvioSys, T9) et (SilPure, T15) reçoivent une fiche à
  continuation alternative (détente au lieu d'aggravation) — définie dans
  `scenario.py` (`PLACEBO`). À générer avec `make_briefings.py --placebo`.
- **Signal faible (T4)** : la presse évoque une « tension » sans événement moteur —
  mesure qui, parmi les 8, réagit au bruit médiatique seul.
- **Décrue (T17-T18)** : aucun événement — mesure l'hystérésis de la déclaration
  (HA6).

## Sources (ancrages documentaires)

Voir `scenario.py` (`SOURCES`) : chronologie Wikipedia/S&P Global, délais
Broadcom, gel Texas, incendie Renesas, sécheresse Taïwan, Ever Given,
confinements Malaisie, Toyota −40 %, congestion LA/Long Beach, polysilicium,
GlobalFoundries complet, WorldRiskIndex 2021, WGI Banque mondiale.
