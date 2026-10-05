# -*- coding: utf-8 -*-
"""Scan the thesis prose for the AI tells in the supplied rule set.

Profile: technical-blog. The exempt list is applied, so robust / comprehensive /
seamless / ecosystem / leverage / facilitate / underpin / streamline are not
flagged; delve / tapestry / beacon / embark / testament to / game-changer /
harness still are.

LaTeX is stripped before matching so that command names, labels and maths do
not produce phantom hits.
"""
import re
from pathlib import Path

ROOT = Path(r"C:\PRIVEE\AZURE\docs\Thesis_Cranfield_JH_2026\Sections")
FILES = sorted(ROOT.glob("*.tex")) + sorted((ROOT / "Appendices").glob("*.tex"))

TIER1 = [
    "delve", "tapestry", "realm", "paradigm", "embark", "beacon",
    "testament to", "cutting-edge", "pivotal", "underscore", "meticulous",
    "game-chang", "utilize", "watershed", "nestled", "vibrant", "thriving",
    "showcas", "deep dive", "dive into", "unpack", "bustling", "intricate",
    "intricacies", "ever-evolving", "enduring", "daunting", "holistic",
    "actionable", "impactful", "learnings", "thought leader", "best practices",
    "at its core", "synergy", "synergies", "interplay", "in order to",
    "due to the fact that", "commence", "ascertain", "endeavor", "boasts",
    "symphony", "landscape",
]
TIER2 = [
    "navigat", "foster", "elevate", "unleash", "empower", "bolster",
    "spearhead", "resonate", "revolutioni", "nuanced", "crucial",
    "multifaceted", "myriad", "plethora", "encompass", "catalyz", "reimagin",
    "galvaniz", "augment", "cultivat", "illuminat", "elucidat", "juxtapos",
    "transformative", "cornerstone", "paramount", "poised", "burgeoning",
    "nascent", "quintessential", "overarching", "harness",
]
PHRASES = {
    "hedge stack": r"\b(could|may|might|will)\s+(potentially|eventually|ultimately)\b",
    "filler": r"(it is important to note that|it's worth noting that|"
              r"the reality is that|in terms of|at the end of the day|"
              r"needless to say)",
    "transition": r"(?<![a-z])(Moreover|Furthermore|Additionally|"
                  r"That being said|In conclusion|In summary|To summarize|"
                  r"When it comes to)\b",
    "confidence cue": r"(?<![a-z])(Notably|Interestingly|Surprisingly|"
                      r"Importantly|Undoubtedly|Without a doubt|Certainly)\b",
    "vague endorsement": r"worth (reading|noting|paying attention|a look|"
                         r"exploring|checking out|your time)",
    "hollow intensifier": r"\b(truly|quite frankly|to be honest|"
                          r"let's be clear|genuinely)\b",
    "vague attribution": r"(experts (believe|say|agree)|studies show|"
                         r"research suggests|industry leaders)",
    "let's construction": r"\bLet's \w+",
    "rhetorical opener": r"(?<![a-z])(But what|So why|What's next\?)",
    "false concession": r"\bWhile [^.]{5,60}, [^.]{5,60} remains\b",
    "significance inflation": r"(marking a pivotal|watershed moment|"
                              r"the future looks bright|only time will tell)",
    "meaning-telling": r"(represents a broader|speaks to a larger|"
                       r"symbolizes a commitment)",
    "copula avoidance": r"\b(serves as|stands as|presents itself as)\b",
    "real-adjective inflation": r"\b(real|actual|genuine|true) "
                                r"(utility|value|impact|insight|understanding)\b",
    "em dash": r"---|\u2014",
    "template": r"a \w+ step (towards|forward)|Whether you're",
}


def strip_latex(text: str) -> str:
    """Remove the parts of a .tex file that are not prose."""
    text = re.sub(r"(?m)^\s*%.*$", "", text)              # comment lines
    text = re.sub(r"\$[^$]*\$", " MATH ", text)           # inline maths
    text = re.sub(r"\\begin\{(tikzpicture|equation|align|algorithmic|"
                  r"algorithm)\*?\}.*?\\end\{\1\*?\}", " ", text, flags=re.S)
    text = re.sub(r"\\(label|ref|autocite|cite\w*|includegraphics|input|"
                  r"gls|texttt|url)\s*(\[[^\]]*\])?\{[^}]*\}", " ", text)
    text = re.sub(r"\\[a-zA-Z@]+\*?", " ", text)          # remaining commands
    return text


total = 0
for path in FILES:
    prose = strip_latex(path.read_text(encoding="utf-8"))
    lines = prose.split("\n")
    hits = []
    for n, line in enumerate(lines, 1):
        low = line.lower()
        for w in TIER1:
            if w in low:
                hits.append(("T1", w, n, line.strip()[:96]))
        for w in TIER2:
            if w in low:
                hits.append(("T2", w, n, line.strip()[:96]))
        for name, pat in PHRASES.items():
            for m in re.finditer(pat, line, re.I if name != "transition" else 0):
                hits.append(("PH", f"{name}: {m.group(0)[:34]}", n, line.strip()[:96]))
    if hits:
        print(f"\n=== {path.name} ===")
        for tier, what, n, ctx in hits:
            print(f"  [{tier}] {what:<44} l.{n}")
        total += len(hits)

print(f"\n{'=' * 70}\n{total} hits")
