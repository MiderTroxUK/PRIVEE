"""Depose la carte de role de chaque declarant dans son bac a sable.

Un participant reel recoit sa carte de role au lancement, une fois, et la relit
quand il veut. La deposer dans le bac a sable plutot que de la repeter a chaque
relance a deux vertus : le message de coordination se reduit a « c'est votre
tour », donc il ne peut plus rien contenir qui teinte la declaration ; et la
carte est un artefact du dispositif, verifiable apres coup, au lieu d'un texte
qui vivrait seulement dans l'historique du coordinateur.

La carte dit un METIER et un CARACTERE. Elle ne dit jamais quoi declarer, ni ce
qui se passe ailleurs dans la chaine.

Usage :
    python cartes_role.py <dossier_campagne>
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "scenario"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import scenario  # noqa: E402

GABARIT = """# Votre carte de role — {nom}

**Vous etes {role}.**

{profil}

Vous jouez cette personne. Vous ecrivez comme elle, vous jugez comme elle.

## Ce que vous avez le droit de consulter

Votre fiche du mois (`out/tour_NN/{node}.md`), vos propres declarations passees
(`reponses/{node}.jsonl`), et le cas echeant un retour de l'application depose
dans `retours/{node}/`. **Rien d'autre.** Vous ignorez tout de la situation des
autres acteurs de la chaine, et vous n'allez pas la chercher.

## Ce qu'on vous demande chaque mois

Comparer quatre criteres deux a deux :

1. **Impact operationnel** — si ma tache echoue, quelle consequence en aval ?
2. **Fenetre temporelle** — combien de temps avant que ce soit irrattrapable ?
3. **Dependances aval** — combien d'acteurs attendent apres moi ?
4. **Recuperabilite** — peut-on rattraper un retard ?

Les six comparaisons, dans cet ordre : (1v2), (1v3), (1v4), (2v3), (2v4), (3v4).
Chacune est un entier de **-8 a +8** : positif si le PREMIER critere compte plus
que le second, negatif si c'est l'inverse, 0 si egalite. Restez transitif — si A
compte plus que B et B plus que C, alors A doit dominer C d'autant plus.

Puis la gravite percue sur chacun des quatre criteres, entier de **1** (aucune)
a **6** (maximale).

## Comment repondre

AJOUTEZ une ligne a la fin de `reponses/{node}.jsonl`, sans rien ecraser, en
UTF-8 :

```
{{"tour": N, "node_id": "{node}", "bipolar": [a,b,c,d,e,f], "scores_ui": [g,h,i,j], "note": "votre phrase"}}
```

La note : une ou deux phrases a la premiere personne, dans votre style, sur ce
que vous percevez de VOTRE situation ce mois-ci.

Il n'y a pas de bonne reponse. Declarez ce que VOUS percevez.
"""


def main() -> None:
    """Ecrit une carte par noeud dans ``<campagne>/roles/``."""
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    dossier = Path(sys.argv[1]) / "roles"
    dossier.mkdir(parents=True, exist_ok=True)
    noms = {n["id"]: n["name"] for n in scenario.NODES}
    for node, carte in scenario.PERSONAS.items():
        (dossier / f"{node}.md").write_text(
            GABARIT.format(node=node, nom=noms.get(node, node),
                           role=carte["role"], profil=carte["profil"]),
            encoding="utf-8")
    print(f"{len(scenario.PERSONAS)} cartes de role ecrites dans {dossier}")


if __name__ == "__main__":
    main()
