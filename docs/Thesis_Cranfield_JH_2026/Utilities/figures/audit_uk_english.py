# -*- coding: utf-8 -*-
"""Check the thesis for US spellings and usages that a UK examiner would mark.

The French resume is excluded. So are bibliography keys, labels, file paths and
maths, since an American source title or a module name is not a spelling error
in the author's prose.

Note on -ize: it is valid UK English (Oxford spelling, used by OUP and Nature).
It is only a defect if the document mixes the two, so both forms are counted
and the ratio reported rather than flagged outright.
"""
import re
from collections import Counter
from pathlib import Path

ROOT = Path(r"C:\PRIVEE\AZURE\docs\Thesis_Cranfield_JH_2026\Sections")
FILES = [p for p in sorted(ROOT.glob("*.tex")) + sorted((ROOT / "Appendices").glob("*.tex"))
         if "Resume" not in p.name]

# US form -> UK form. Only unambiguous pairs.
PAIRS = {
    "analyze": "analyse", "analyzed": "analysed", "analyzing": "analysing",
    "analyzes": "analyses", "paralyze": "paralyse",
    "behavior": "behaviour", "behavioral": "behavioural",
    "behaviors": "behaviours", "behaviorally": "behaviourally",
    "color": "colour", "colors": "colours", "colored": "coloured",
    "favor": "favour", "favors": "favours", "favorable": "favourable",
    "labor": "labour", "neighbor": "neighbour", "neighboring": "neighbouring",
    "rumor": "rumour", "endeavor": "endeavour", "harbor": "harbour",
    "center": "centre", "centered": "centred", "centers": "centres",
    "fiber": "fibre", "liter": "litre", "meter": "metre", "meters": "metres",
    "theater": "theatre",
    "catalog": "catalogue", "dialog": "dialogue", "analog": "analogue",
    "defense": "defence", "offense": "offence", "pretense": "pretence",
    "practicing": "practising", "licensed": "licenced",
    "modeling": "modelling", "modeled": "modelled",
    "labeling": "labelling", "labeled": "labelled", "labels": None,
    "traveled": "travelled", "traveling": "travelling",
    "canceled": "cancelled", "canceling": "cancelling",
    "signaled": "signalled", "signaling": "signalling",
    "totaled": "totalled", "fueled": "fuelled",
    "fulfill": "fulfil", "fulfillment": "fulfilment",
    "skillful": "skilful", "willful": "wilful",
    "enrollment": "enrolment", "installment": "instalment",
    "gray": "grey", "plow": "plough", "draft": None,
    "toward": "towards", "afterward": "afterwards", "backward": None,
    "math": "maths", "airplane": "aeroplane", "aluminum": "aluminium",
    "program": "programme", "programs": "programmes",
    "judgment": "judgement", "acknowledgment": "acknowledgement",
    "aging": "ageing", "artifact": "artefact", "artifacts": "artefacts",
    "specialty": "speciality", "estimation": None,
}
PAIRS = {k: v for k, v in PAIRS.items() if v}


def strip(t):
    """Remove everything that is not the author's running prose."""
    t = re.sub(r"(?m)^\s*%.*$", "", t)
    t = re.sub(r"\$[^$]*\$", " ", t)
    for env in ("tikzpicture", "equation", "align", "algorithmic", "algorithm"):
        t = re.sub(r"\\begin\{" + env + r"\*?\}.*?\\end\{" + env + r"\*?\}",
                   " ", t, flags=re.S)
    t = re.sub(r"\\(label|ref|autocite|textcite|cite\w*|includegraphics|input|"
               r"gls\w*|url|texttt)\s*(\[[^\]]*\])?\{[^}]*\}", " ", t)
    t = re.sub(r"\\[a-zA-Z@]+\*?", " ", t)
    return t


hits = Counter()
ize = ise = 0
for path in FILES:
    prose = strip(path.read_text(encoding="utf-8"))
    for n, line in enumerate(prose.split("\n"), 1):
        for w in re.findall(r"[A-Za-z][a-z]+", line):
            low = w.lower()
            if low in PAIRS:
                hits[(path.name, low, PAIRS[low])] += 1
            if re.search(r"is[ei]?(ing|ed|s|ation)?$", low):
                pass
        for m in re.finditer(r"\b\w+?(iz|is)(e|es|ed|ing|ation|ations)\b", line):
            if m.group(1) == "iz":
                ize += 1
            else:
                ise += 1

if hits:
    print("US spellings in the author's prose:")
    for (fname, us, uk), n in sorted(hits.items(), key=lambda kv: -kv[1]):
        print(f"  {fname:<24} {us:<16} -> {uk:<16} x{n}")
else:
    print("US spellings in the author's prose: none")

print(f"\n-ize / -ise family: {ize} with z, {ise} with s")
print("  (both are valid UK English; only a mixture is a defect)")
