# -*- coding: utf-8 -*-
"""Find every section that opens on a float instead of on a sentence.

A heading followed straight by a figure or table makes the reader meet a
diagram before being told what the section is for.
"""
import glob
import io
import re

PATTERN = (r"\\(?:sub)*section\{([^}]*)\}\s*\n"
           r"(?:\\label\{[^}]*\}\s*\n)?"
           r"(?:%%[^\n]*\n)*"
           r"\s*\\begin\{(?:figure|table|longtable)")
PAT = re.compile(PATTERN)

paths = (sorted(glob.glob(r"C:\PRIVEE\AZURE\docs\Thesis_Cranfield_JH_2026"
                          r"\Sections\*.tex"))
         + sorted(glob.glob(r"C:\PRIVEE\AZURE\docs\Thesis_Cranfield_JH_2026"
                            r"\Sections\Appendices\*.tex")))

found = 0
for path in paths:
    s = io.open(path, encoding="utf-8").read()
    for m in PAT.finditer(s):
        title = m.group(1).encode("ascii", "replace").decode()
        print(f"  {path.split(chr(92))[-1]:<24} {title[:54]}")
        found += 1
print(f"{found} sections open on a float")
