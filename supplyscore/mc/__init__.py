"""Simulation Monte Carlo des dates d'achèvement sur le DAG (phase E13).

API publique :
- SimulateurLeadTime : moteur de simulation vectorisé (PERT stochastique) ;
- ResultatMC         : résultat immuable (u_time, IC95, quantiles d'achèvement) ;
- LoiLeadTime        : paramètres résolus de la loi du lead time d'un nœud ;
- resoudre_loi       : détection de la famille de loi d'un nœud ;
- tirer_lead_times   : tirages vectorisés d'une loi résolue.
"""

from supplyscore.mc.lead_time import (
    LoiLeadTime,
    ResultatMC,
    SimulateurLeadTime,
    resoudre_loi,
    tirer_lead_times,
)

__all__ = [
    "LoiLeadTime",
    "ResultatMC",
    "SimulateurLeadTime",
    "resoudre_loi",
    "tirer_lead_times",
]
