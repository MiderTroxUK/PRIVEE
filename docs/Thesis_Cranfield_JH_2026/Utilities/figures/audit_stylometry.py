# -*- coding: utf-8 -*-
"""Two follow-ups the first pass raised.

1. TTR falls mechanically with length, so a 30,000-word body cannot be compared
   to a 200-word benchmark. MATTR uses a fixed window and is comparable.
2. Locate the five first-person sentences, and the protocol description that
   recurs three times.
"""
import re
import statistics as st
from pathlib import Path

ROOT = Path(r"C:\PRIVEE\AZURE\docs\Thesis_Cranfield_JH_2026\Sections")
FILES = [ROOT / f for f in ("1.Introduction.tex", "2.LiteratureReview.tex",
                            "3.Methods.tex", "4.ResultsDiscussion.tex",
                            "5.Conclusion.tex")]


def strip_latex(t):
    t = re.sub(r"(?m)^\s*%.*$", "", t)
    for env in ("tikzpicture", "equation", "align", "algorithmic", "algorithm",
                "tabularx", "longtable", "figure", "table"):
        t = re.sub(r"\\begin\{" + env + r"\*?\}.*?\\end\{" + env + r"\*?\}",
                   " ", t, flags=re.S)
    t = re.sub(r"\$[^$]*\$", "X", t)
    t = re.sub(r"\\(label|ref|autocite|cite\w*|includegraphics|input|gls|url)"
               r"\s*(\[[^\]]*\])?\{[^}]*\}", " ", t)
    t = re.sub(r"\\(textbf|emph|textit|texttt)\{([^}]*)\}", r"\2", t)
    t = re.sub(r"\\[a-zA-Z@]+\*?", " ", t)
    return re.sub(r"[{}~]", " ", t)


def mattr(words, window=500):
    """Moving-average type-token ratio: comparable across text lengths."""
    if len(words) < window:
        return len(set(words)) / len(words)
    return st.mean(len(set(words[i:i + window])) / window
                   for i in range(0, len(words) - window, 100))


print("MATTR, 500-word window (length-controlled):")
allw = []
for p in FILES:
    w = [x.lower() for x in re.findall(r"[A-Za-z][A-Za-z'-]+",
                                       strip_latex(p.read_text(encoding="utf-8")))]
    allw += w
    print(f"  {p.name:<24} {mattr(w):.3f}   ({len(w)} words)")
print(f"  {'WHOLE BODY':<24} {mattr(allw):.3f}   ({len(allw)} words)")

print("\nfirst-person sentences, and where they sit:")
for p in FILES:
    txt = strip_latex(p.read_text(encoding="utf-8")).replace("\n", " ")
    for m in re.finditer(r"[^.]*\b(I|my|we)\s+[a-z][^.]*\.", txt):
        frag = " ".join(m.group(0).split())
        if len(frag) > 30:
            print(f"  {p.name[:18]:<18} {frag[:104]}")

print("\nthe thrice-repeated protocol description:")
for p in FILES:
    txt = strip_latex(p.read_text(encoding="utf-8")).replace("\n", " ")
    for m in re.finditer(r"[^.]*confined to its own[^.]*\.", txt):
        print(f"  {p.name[:18]:<18} {' '.join(m.group(0).split())[:112]}")
