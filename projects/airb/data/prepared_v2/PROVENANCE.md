# Pack AIRB

Construit par `scripts/build_pack.py` depuis `scenario/scenario.py`.
Aucune serie externe : les ordres de grandeur sont poses, les entites fictives.

- 19 tours, 15 noeuds, 30 arcs.
- Aucun evenement exogene : tous les `events_NN.json` sont vides.
- Degradation endogene sur compolam, harnetec, titanor (lead time, disponibilite, volatilite de cout).
- `milestones_NN.json` doit ensuite etre recalcule par `verite_derivee.py` :
  la verite jalon DECOULE des KPI, elle n'est pas ecrite ici.
