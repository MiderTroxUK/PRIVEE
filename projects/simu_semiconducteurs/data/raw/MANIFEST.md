# MANIFEST des données brutes — campagne HÉLIOS

Généré par fetch_data.py le 2026-07-03. Fenêtre de campagne : 2020-07 -> 2022-02.

## Séries INSEE (API BDM, licence ouverte Etalab)

| Slug | idbank | Description | Granularité | Points fenêtre | Première | Dernière | Statut | SHA256 |
|---|---|---|---|---|---|---|---|---|
| insee_ipi_naf261 | 010768009 | Indice brut de la production industrielle (base 100 en 2021)… | mensuelle | 20 | 1990-01 | 2026-05 | OK | 970a913c866d1760… |
| insee_defaillances_ensemble | 001656157 | Défaillances d'entreprises — ensemble (données CVS)… | trimestrielle | 7 | 1990-Q1 | 2026-Q1 | OK | 942ea18fd10754a0… |
| insee_defaillances_industrie | 001656101 | Défaillances d'entreprises — industrie… | mensuelle | 20 | 1990-12 | 2026-04 | OK | 3b2426712d12f834… |
| insee_ipp_industrie | 010764313 | Indice de prix de production de l'industrie française — ense… | mensuelle | 20 | 2015-01 | 2026-05 | OK | 00a18f4a0f6b4998… |
| insee_tuc_manuf | 001586738 | Taux d'utilisation des capacités de production — industrie m… | trimestrielle | 7 | 1976-Q2 | 2026-Q2 | OK | 69bf688fa36a91ae… |
| insee_ipp_composants | 010764217 | Indice de prix de production — CPF 26.1 composants et cartes… | mensuelle | 20 | 2015-01 | 2026-05 | OK | 9e9649fd8ab3aa63… |

## WSTS Historical Billings Report

- Page : https://www.wsts.org/67/Historical-Billings-Report
- Statut : Téléchargé automatiquement depuis https://www.wsts.org/esraCMS/extension/media/f/WST/7644/WSTS-Historical-Billings-Report-Apr_2026.xlsx (sha256 e03f4871a10e710f…).

## Étapes manuelles restantes (compte requis — utilisateur)

1. **Kaggle — Semiconductor shortage (1985-2021)** :
   https://www.kaggle.com/datasets/ramjasmaurya/semiconductor-shortages19852021
   -> déposer le CSV dans ce dossier sous `kaggle_semiconductor_shortage.csv`.
   Contrôle d'authenticité AVANT usage : la description doit citer la source
   primaire (FRED/BLS) ; sinon, écarter (HD5).
2. **Kaggle — Logistics and Supply Chain Dataset (SoCal 2021-2024)** :
   https://www.kaggle.com/datasets/datasetengineer/logistics-and-supply-chain-dataset
   -> déposer sous `kaggle_socal_logistics.csv`. Même contrôle HD5 :
   provenance réelle citée, sinon écarté (le plan tient sans).

## Séries écartées / non trouvées (documenté, jamais inventé)

- Indice de fret public couvrant 2020-2022 sans licence : non identifié à ce
  stade -> le bloc cost de TransGlobal reste piloté par les événements
  calibrés (surcoûts documentés) + IPP industrie en contexte.
- Série silicium/polysilicium publique : non identifiée en accès libre ->
  bloc cost de SilPure piloté par l'événement hausse_tarif (T16, +18 %
  documenté) et l'IPP en contexte.
- env_exposure / political_risk : valeurs U5bis posées depuis WorldRiskIndex
  2021 et WGI (constantes gelées, sensibilité ±50 % en U10) — pas de série
  temporelle nécessaire (baseline lente).