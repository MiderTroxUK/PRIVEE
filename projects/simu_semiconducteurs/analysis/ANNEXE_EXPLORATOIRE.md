# Annexe — analyses exploratoires (hors registre pré-enregistré)

Ce document journalise les analyses menées HORS du registre gelé de
`PROTOCOLE.md` §5 (hypothèses HA1-HA6, verrouillé à J5 avant le premier tour
réel). Chaque entrée est datée, explique pourquoi l'analyse sort du
registre, et référence ses fichiers de sortie.

**Règle** : ces analyses n'engagent jamais le protocole. Elles ne modifient,
ne rejouent ni ne réinterprètent aucune hypothèse gelée — les verdicts de
`analyse_campagne.py` / `rapport.md` restent l'unique source de vérité
pré-enregistrée. `PROTOCOLE.md` et `data/prepared/` (pack gelé) ne sont
jamais touchés par ces analyses.

---

## 2026-07-21 — Diagnostic HA4 : balayage de seuil du signal prédictif

**Constat déclencheur.** Le test HA4 gelé (`analyse_campagne.ha4()` : H =
max(Ur−Ud, 0) >= 0.5, horizon 4 tours) a échoué avec TP≈0 sur les snapshots
dry run. Or l'inspection des séries montre que H est structurellement
compressé en fin de campagne : dès qu'un nœud sature (Ur = 1.0), Ud le
rattrape rapidement (Ud ≈ 0.98) et H s'écrase mécaniquement (H ≈ 0.02) —
bien en dessous du seuil pré-enregistré de 0.5, quel que soit le pouvoir
prédictif réel de la métrique sous-jacente.

**Pourquoi cette analyse est hors registre.** HA4 est gelé au seuil 0.5 et à
la métrique H telle que définie dans `analyse_campagne.ha4()` (voir
PROTOCOLE.md §5). Son verdict « NON CONFIRMÉE » reste tel quel dans
`rapport.md` — ce diagnostic ne le rejoue pas et ne le modifie pas. Il
répond à une question différente et non pré-enregistrée : indépendamment du
seuil 0.5, existe-t-il un pouvoir discriminant QUELCONQUE dans Ur/Ud/H à cet
horizon ? Si oui, c'est le seuil pré-enregistré qui était mal calibré, pas
la métrique qui est vide de contenu — distinction qui conditionne la
décision GO/pivot pour la suite du pipeline HÉLIOS.

**Méthode.** Balayage complet de seuil sur 5 signaux candidats
(`hidden_risk`, `H_local = max(Ur_local−Ud_local, 0)`, `ur`, `ur_local`,
`gap = Ur−Ud` non tronqué) : ROC complète, AUC (Mann-Whitney avec
correction d'ex-aequo, hand-rolled), IC95 par bootstrap CLUSTER sur les 8
`node_id` (1000 tirages, seed fixe = reproductible), PR-AUC (average
precision), meilleurs seuils F1 et Youden avec matrices de confusion. Le
tout sur les deux jeux de snapshots (dry run v6 et pilote LLM, quand
disponible), plus une analyse de lag (k=1..4) sur le signal le plus
discriminant, pour distinguer un vrai signal précurseur d'un simple effet
de contemporanéité (« nowcast »). Détecteur naïf (`Ur_local >= 0.5`)
recalculé pour comparaison. Script entièrement autonome (stdlib), aucun
import de `analyse_campagne` ni de `CalibrationService`.

**Résultat (dry run v6, 19 tours, 144 points nœud×tour valides, 37
positifs)** : meilleure AUC = `H_local` à 0.526 (IC95 [0.289, 0.777]) — ni
un signal net (> 0.65), ni du bruit pur partout ([0.45, 0.55] pour tous les
signaux : `hidden_risk` et `gap` tombent nettement en dessous, à 0.32 et
0.31). Verdict rendu : zone grise, traité par défaut comme NON-GO tant que
le signal n'est pas plus net. Le jeu « pilote LLM »
(`analysis/llm_pilot_run/snapshots/`) n'existait pas encore au moment de
cette exécution — dépendance d'une autre unité du plan HÉLIOS v7 en cours
de fusion en parallèle ; le script est prêt à le traiter dès qu'il
apparaîtra (relancer le script suffit, aucune modification nécessaire).

**Sorties.**
- `analysis/diagnostic_ha4.py` — script d'analyse (autonome, hors couverture
  pytest, cf. `pyproject.toml` `[tool.coverage.run] source = ["supplyscore"]`).
- `analysis/diagnostic_ha4.md` — tables signal × AUC/IC95/PR-AUC/seuils F1 et
  Youden, table de lag k=1..4, baseline naïve, verdict explicite.
- `analysis/figures_diagnostic_ha4/*.png` — courbes ROC et AUC-vs-lag
  (best-effort ; non générées si matplotlib est indisponible, comme dans
  `analyse_campagne.write_outputs`).

**Portée.** N'affecte ni `PROTOCOLE.md` ni `data/prepared/` (pack gelé).
N'importe pas et ne modifie pas `analyse_campagne.py` : les deux scripts
sont indépendants et `analyse_campagne.py` continue de tourner à
l'identique.
