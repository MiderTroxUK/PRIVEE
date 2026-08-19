"""Simulation Monte Carlo des dates d'achevement sur le DAG (phase E13).

API publique :
- SimulateurLeadTime : moteur de simulation vectorise (PERT stochastique) ;
- ResultatMC         : resultat immuable (u_time, IC95, quantiles d'achevement) ;
- LoiLeadTime        : parametres resolus de la loi du lead time d'un noeud ;
- resoudre_loi       : detection de la famille de loi d'un noeud ;
- tirer_lead_times   : tirages vectorises d'une loi resolue.
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
