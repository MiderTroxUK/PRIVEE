# MFE ESTIA 2026 — Ground rules for the defence

Everything established while reworking `MFE-ESTIA - Copie.pptx` into
`MFE-ESTIA - Revised.pptx` on 29 August 2026: the school's rules, the tutor's review,
the facts checked against the code, and the conventions the deck now follows.

Sources are cited so every line can be re-checked. Where a source disagrees with the
code, the code wins and the disagreement is recorded.

---

## 1. The rules the school actually marks

Two documents govern the oral, and only two. The Cranfield thesis PDF contains no
defence rules at all.

- `Consignes évaluations Alternance 5 et MFE 2025-2026 VF.pdf` (22 pp, updated 06/10/2025)
- `FEXXX Evaluation_oral_MFE VF.docx` (the marking grid, footer FE846 V6, 08/01/2026)

### 1.1 Format

| Rule | Value | Source |
|---|---|---|
| Presentation | **20 minutes** | Consignes p.5 and p.8 |
| Questions | **10 minutes** | same |
| Total | 30 minutes | "L'élève dispose de 30 minutes pour convaincre" |
| Language | **Entirely in English** (Cranfield track) | Consignes p.7, highlighted in the source |
| Pass mark | **12/20**, else the defence is retaken | grid, closing lines |
| Slide count | **Not fixed anywhere** | absent from both documents |

**The language rule is a validity condition, not a points criterion.** The grid ends with
"La soutenance doit être réalisée intégralement en anglais ou espagnol" followed by
"Si l'une de ces conditions n'est pas remplie l'élève devra refaire sa soutenance." Any
French in the spoken talk risks a retake, not a fraction of a point. French *inside a
screenshot* is a different thing and is defensible if named out loud, which slides 14 and
16 now do.

Do not confuse this with the Alternance 5 oral, which is 8+2 minutes in French.

### 1.2 The grid, verbatim, out of 20

**PRESENTATION ORALE — 5 points**

| Criterion | Max |
|---|---|
| Présentation, tenue, élocution | 2 |
| Aisance en anglais ou en espagnol | 1 |
| Respect du temps alloué | 1 |
| Qualité du support de présentation | 1 |

**TRAVAIL TECHNIQUE — 10 points**

| Criterion | Max |
|---|---|
| Difficulté du sujet | 1 |
| Partie introductive : contexte, enjeux, problématique, mission | 1 |
| **Structuration de la démarche** | **2** |
| **Présentation du travail réalisé et des résultats** | **2** |
| Conclusion | 1 |
| **Maîtrise du sujet** | **2** |
| Atteinte de l'objectif | 1 |

**RÉPONSES AUX QUESTIONS — 5 points**, three questions, scale 1 to 5. The jury writes the
questions down by name. **A quarter of the mark is earned after the last slide.**

Each line is circled on Médiocre / Passable / Moyen / Bon / Très bon.

### 1.3 The running order the school prescribes (Consignes p.8)

This maps almost one-to-one onto the technical criteria. In order:

1. Plan of the talk.
2. Context, problem and its stakes, then the company context and its need. **End the
   introduction by stating the mission, its objectives, and the performance indicators.**
3. The general project methodology (V-cycle, DMAIC, company charter).
4. Project management: material and time constraints, **stakeholders**, a planning.
5. **The existing situation**, the need in context, the functionalities of the product to build.
6. The design of the solution, with **a hardware diagram and a software diagram**.
7. The realisation and the results.
8. Validation and tests; compare the final product with the initial objectives.
9. Project management again: phases, particular difficulties, **resources the company
   committed, role in the team, human relations, and the deliverables left behind**.
10. Company-side balance: does the product meet the need, is it used, is there a follow-up.
11. **Personal balance** (bilan personnel).

### 1.4 The oral checklist (Consignes p.20-21), items the deck can act on

- **Number the slides and put the name on the first one.**
- Zero spelling mistakes.
- Make sure diagrams, figures and graphs are legible.
- Unpack technical vocabulary for the audience.
- State the stakeholders and the environment.
- Show the working method and the tools, not only the results.
- Be factual, be precise, put numbers on things.
- Do not forget to conclude.
- Link back to ESTIA teaching.
- **The talk is about the student, not the company.**

### 1.5 Two traps

- **RSE/CSR and the CI/CE/CST competency mapping are REPORT requirements, not oral grid
  criteria.** They earn nothing on the oral grid. Keeping a light competency strip on the
  personal-assessment slide is good practice, not an obligation.
- The RSE paragraph is the one part of the **report** that must be in French.

---

## 2. What Sébastien Perthuisot asked for, and where it now lives

Transcribed from the review recording. Every item is now addressed.

| # | His point | Where it landed |
|---|---|---|
| 1 | "Le backbone c'est le score." DISCO already combines CO2, cost and risk. The mission is to add a **fourth** score. Say it before any digital-twin talk, on slide 3. | Slide 3 rebuilt: three numbered score cards plus a fourth ochre card "URGENCY · NO SCORE AT ALL", closing with "My mission is that fourth score." |
| 2 | "Hier on gérait des projets. Aujourd'hui on gère des urgences. Demain il faut regarder l'urgence véritable." | Slide 4, top band: YESTERDAY / TODAY / TOMORROW, ahead of the research question. |
| 3 | The research question is right, but foreground the human-versus-computed comparison rather than the twin. | Kept verbatim (it is thesis-faithful) but now preceded by the ramp and followed by the three constraints. |
| 4 | Colour coding on THE WEEK is arbitrary: why is the demo yellow and Monday the same as the programme director? | Recoloured on one rule with a printed legend: **blue = the team's own rhythm, ochre = someone outside the team judges the week**. Wednesday now says "Taken in place of the scrum". |
| 5 | Why a one-week sprint? Answer: new consultants arrive every Monday afternoon. | Ochre band on slide 8, stated in one sentence. |
| 6 | "Se planter fait partie du truc, c'était de la R&D." | Retitled "TEST AND LEARN COUNTS ONLY IF SOMETHING WAS DROPPED", closing line "Dropped in April, at a cost of three weeks. It was R&D, and the loop is what caught it." |
| 7 | Six months in big phases, but it loops fast inside them. | Slide 9 subtitle: "10 phases · 9 milestones · one week inside each of them". |
| 8 | Literature: "raconte-moi l'histoire", six bullets, nothing joins them, and the gap matters most. | Retitled "LITERATURE: WHAT NOBODY JOINS UP", subtitle "Six streams, three patents, and one empty box". |
| 9 | Reintegrate the human. Industry 4.0 → 5.0, the Tesla case. | Ochre note on slide 11 citing the European Commission (2021) and Tesla's own 2018 letter. **Fremont, not Texas** (see §4). |
| 10 | "Je ne suis pas fan de la slide objectifs. Moi je t'ai demandé ce score. Objectif et vue globale." | Slide 5 became THE MISSION AND ITS OBJECTIVES: the mission in three moves (ELICIT / COMPUTE / COMPARE) above the five objectives. |
| 11 | **The one big diagram**, built backwards from the conclusion: situation → declaration tool → calculator → adequacy → result → "not convinced, built the interface and the agents" → loops → test on a known crisis → forecast. | **New slide 6, "HOW THE WORK RAN".** Five-box instrument, five loop chips, the "loop 0 did not convince me" band, and the two validation questions numbered 6 and 7. |
| 12 | "The mission comes before." | Mission moved from position 11 to position 5, inside agenda part 1 where the label already promised it. |
| 13 | A phase locator top-right so the jury knows where it is. | Five-chip locator on every content slide, current part in ochre, slide number under it. |
| 14 | "Tu ne m'as pas parlé de l'interface, je ne l'ai pas vue." | **New slide 16, SUPPLYSCORE: THE APPLICATION.** Full-width explainability page, plus the questionnaire and the shock simulation, plus the eleven page names. |
| 15 | PROMETHEE was mentioned and never reused. Put it in the computation. | Moved to the computed side on slide 13, and removed from the declared-side caption on slide 12 where it was wrong. |
| 16 | The UML is unreadable, but fine for the academic. | Kept, reframed as "why every write can be traced back", with the scale line underneath. |
| 17 | "Si je ne sais pas qui a marqué semi-conducteur." | Slide 19 title: **RESULT 1: THE SEMICONDUCTOR SHORTAGE**. |
| 18 | Result 2 is unexplained: say what you were trying to do. | Slide 20 title: **RESULT 2: CAN IT FORECAST A CRISIS?**, plus a navy "THE HONEST READING" block. |
| 19 | "C'est confus entre l'anglais et le français. Tu l'appelles comment ?" | Deck is 100% English. Slide 22 states: SupplyScore is the tool, DISCO is the DIN's serious game, Smart & Green Supply Chain is the programme. |
| 20 | "Small positive results, ça veut dire quoi ?" | Replaced by "Seven positives across two chains", plus two limits that were promised in the subtitle and missing from the slide. |
| 21 | "Qu'est-ce que tu as appris, toi ?" | **New slide 24, WHAT I TAKE FROM IT**: three lessons from the thesis personal conclusion plus the direction they point. |

**Deadline he set: 2 September.**

---

## 3. Facts verified against the code, not against the prose

Checked in `C:\PRIVEE\AZURE\supplyscore\`. These corrected real errors in the old deck.

### 3.1 Where each MCDA method actually sits

| Method | Side | Evidence |
|---|---|---|
| **AHP** (Saaty) | **Declared Ud** | `core/ahp.py:21-26`, four criteria; `:43` `CONSISTENCY_THRESHOLD = 0.10` |
| **Fuzzy BWM** | **Computed Ur**, weights the six KPI blocks | `mcda/fbwm.py:283`; call site `web_ui/pages/ponderation.py:178` |
| **PROMETHEE II** | **Computed Ur**, ranks nodes on the six blocks | `mcda/promethee.py:241`; wired at `services/orchestrator.py:518-530` |

`Ud` is **never** a PROMETHEE criterion. The old slide 11 caption
"DECLARED Ud — AHP, FUZZY BWM AND PROMETHEE II" was wrong on two of three. Fixed.

The module docstring states the split outright: PROMETHEE II for "le classement
multicritere des noeuds", FBWM for "la ponderation floue des blocs KPI d'Ur".

### 3.2 The numbers that were wrong on the slides

| Was on the deck | Truth | Evidence |
|---|---|---|
| "penalty ×1 / penalty ×2" | **λ_over = 1.0, λ_under = 2.25**, with curvature α = 0.88, and the mapping is exponential, not linear | `core/adequation.py:40-44`, `:164-174` |
| README badge "1614 tests" | **2044 collected** (2028 pass, 15 skip, 1 fail) | `pytest --collect-only -q` |
| "γ attenuates / β amplifies" as a mathematical property | **Both recurrences are the identical noisy-OR form**; the local variable is called `attenuation` in both. Only the direction and the coefficient differ | `graph/propagation.py:189-194` and `:229-234` |

The 2.25 wording is now on slide 12 and attributed to Prospect Theory. The γ/β wording on
slide 15 now says "Same propagation law both ways. Only the direction and the coefficient
differ." That is the defensible claim; the physical reading (demand descends, risk ascends)
survives as a *directional* statement.

### 3.3 Facts that check out and are safe to say

- `ur = 1 - Π_m (1 - u_m)^ω_m` over non-None blocks with ω_m > 0 — `core/ur_model.py:580-593`.
- Six blocks, named `time, cap, perf, risk, cost, co2` — `core/ur_model.py:19`.
- Adequacy A on [0, 100] — `core/adequation.py:173-174`.
- False urgency F = max(Ud − Ur, 0); hidden risk H = max(Ur − Ud, 0) — `core/adequation.py:89-113`.
- The web UI exposes **11 static routes** plus `/node/<id>` and `/node/<id>/explication` — `web_ui/app.py:53-65`.
- **73 modules, 2044 tests, multi-tenant, one database per node.**
- The campaign ran at **ω_m = 1 throughout**, so every reported result concerns the plain
  noisy-OR, not the weighted generalisation. Worth knowing if the jury probes the weights.

### 3.4 Naming

- The tool is **SupplyScore**: `pyproject.toml:2`, `SupplyScoreService`, Dash title.
- **"DISCO" appears zero times in the codebase.** It is the DIN's separate serious game and
  digital twin (fictitious satellite chain, 22 suppliers) that SupplyScore is written *for*.
- **Smart & Green Supply Chain** is the programme. In the ALTEN Labs domain list it is
  written "Smart Quality & Green Supply Chain".

Say it in that order and the confusion Perthuisot flagged disappears.

---

## 4. External claims, and how far each one holds

### 4.1 Tesla — use Fremont, never Texas

Perthuisot said "sa Factory du Texas". **That is the wrong plant and it would collapse
under a jury question.**

- The documented episode is the **2018 Model 3 ramp at Fremont, California**.
- Musk, 13 April 2018: "Excessive automation at Tesla was a mistake. To be precise, my
  mistake. Humans are underrated."
- Stronger and more citable, Tesla's own Q1 2018 update letter (Exhibit 99.1 to a Form 8-K,
  filed 2 May 2018, CIK 1318605): *"we made a mistake by adding too much automation too
  quickly"*, and it names the areas where automation was "temporarily dialed back":
  portions of the battery module line, part of the material flow system, and two steps of
  general assembly.
- **There is no documented over-automation or human-reintegration story at Gigafactory
  Texas.** Searches return the opposite narrative (Optimus, Cybertruck line robots).
- Two cautions if pressed: the same letter *defends* automation ("we are as committed to it
  as ever"), so cite a scoped, temporary rollback, not a repudiation. And the 2025 reports
  of workers pulled off Giga Texas Cybertruck lines are demand-driven downsizing, not an
  automation reversal.

The slide says "Tesla called over-automation at Fremont a mistake in its own 2018 update
letter." That is accurate and survives challenge.

### 4.2 Industry 5.0

European Commission, DG Research and Innovation, 2021: human-centricity, sustainability and
resilience. Safe as a one-line citation for "the field is putting the human back".

### 4.3 PROMETHEE — do not say "the reference in risk management"

Perthuisot said "PROMETHEE c'est quand même la référence dans la gestion de risque."
**That is not supportable.** What is:

- The most widely used method of the **outranking family**, having overtaken ELECTRE there.
- Roughly **1400 academic publications**, "always one of the top 5 methods used".
- **Third overall** behind AHP and TOPSIS in Danielson's composite ranking (4th on raw
  publication count, behind VIKOR).
- Documented strength areas: environmental management, sustainability, energy planning,
  supply-chain evaluation. **Risk is never attached to PROMETHEE in that source.**
- Source: Danielson, M. (2023), *Widely Used Multi-Criteria Decision Analysis Methods*,
  Stockholm University. Self-hosted working paper, not peer-reviewed — pair it with a
  refereed source if the claim is challenged. It ranks *usage*, explicitly "rather than
  evaluating theoretical performance".

The deck therefore does not claim PROMETHEE is a risk-management reference. It says what
PROMETHEE does in this system, which is rank nodes.

### 4.4 The defence is public

ESTIA invites the public to all MFE defences, "sauf mention expresse de présentation à huis
clos", with prior registration. The title slide is marked **Confidential: YES**, so check
with the scolarité whether this one is closed.

---

## 5. What the peer deck (Liam Jones, ALTEN Toulouse) settles

Same ALTEN supervisor (S. Perthuisot), different school (INSA/UPHF, advisor S. Chaabane),
adjacent subject. 33 slides, English throughout, slide-numbered.

**It contains no ALTEN key figures at all** — no founding year, no country count, no
headcount, no lab count, and **no RSE content**. So it neither confirms nor contradicts
"1988 / +30 countries / 11 ALTEN Labs / 31% R&D on environment", and it cannot plug the
RSE gap.

**One thing to be ready for:** Jones' slide 5 shows **nine ALTEN Labs *domains*** under the
DIN. The deck says **11 ALTEN Labs**. These are probably different units of count (thematic
domains versus physical lab sites). Keep the sourced figure, but be able to say what a
"Lab" is if asked.

**Where Jones is ahead:** a documented DIN org chart (DIN → Programme → Project → Pilote
d'Innovation → Interns/Consultants), and a habit of naming an obstacle on every technical
slide and resolving it on the next.

**Where this deck is ahead, and it is most of the grid:** Jones has no Gantt, no
stakeholders, no risk or constraint slide, no competency mapping, and a four-bullet personal
assessment. Do not copy his structure.

**One line worth borrowing, and now on slide 1:** "Figures are original work unless
indicated. ALTEN material used with permission."

**The complementarity answer, if the jury asks how this fits ALTEN's wider programme:**
Jones built the structural and geographic substrate (graph, GIS, discrete-event simulation)
and explicitly left "disruption events" to future work. This project builds the decision
layer that sits on top of exactly such a substrate.

---

## 6. The numbers to have ready

Verified against `docs/Thesis_Cranfield_JH_2026/Sections/`.

### The result that works
- Turns T0–T5, before the crisis is public: **precision 1.00, recall 0.75, zero false alarms**.
- Four of eight nodes eventually miss; the flag catches three.
- The satellite prime is worst-scoring on all six turns, misses at turn 8, delivers at 14.
  **Flagged eight turns ahead, while its own manager declares Ud = 0.001.**
- After T6: precision ≤ 0.50, recall 0.25, 1 to 3 false alarms per turn. **This is a scope
  statement, not a defect** — once the shortage is public everyone raises their urgency,
  Ud converges on Ur, and [Ur − Ud]⁺ shrinks by construction.

### The boundary
- Second chain (AIRB, 15 nodes, no exogenous shock): **precision at rank 3 is 0.00** for
  both [Ur − Ud]⁺ and the adequacy score, against a base rate of 0.20.
- Mechanism: the three degrading suppliers declare 0.94, 0.88, 0.98 at turn 0 *before*
  their indicators move, still 0.97 and 0.96 at turn 16 against a computed 1.00. The gap is
  bounded by 0.03. **Nothing is concealed, so nothing is detected.**
- The line to say: *"They minimised in action and maximised in measurement. A gap defined
  between a computed state and a declared perception detects blindness, not discretion."*

### The result that fails
- 120 prospective forecasts, production outcome definition: **Brier skill −6.93 / −4.14 /
  −3.77 / −3.36** at 1–4 weeks. AUC 0.555 / 0.372 / 0.428 / 0.485.
- **21 confident forecasts announced a mean of 0.948. None materialised.** Confusion matrix
  at 0.5: 0 TP, 21 FP, 6 FN, 93 TN.
- Cause, one sentence: across eight nodes and 41 snapshots each, **the accumulated-delay
  field the time block needs was written non-zero exactly zero times.**
- Right-censoring is ruled out: dropping every forecast whose window runs past the last turn
  leaves n = 88, still 0 TP, and the skill gets *worse* (−7.82).

### The repair
- Original-commitment target. Before: −1.278 / −0.690 / −0.654 / −0.553.
  Structure: −0.646 / −0.401 / −0.360 / −0.272.
  Plus uncertainty: −0.687 / −0.367 / −0.286 / −0.216.
- **"The repair moves the system from badly wrong to less wrong, not to useful."**
- The obvious repair was wrong: routing lost time into the *lead time* attenuates to nothing
  on exactly the milestones nearest their deadline. Lost time must be **added to the
  completion date**: C = t + (1−p)L + R.

### The most damaging number, and say it before the jury finds it
- **A one-line calendar baseline** (work outstanding ÷ nominal lead time, no simulation, no
  fitted parameter, none of the six blocks) **outranks 500 Monte-Carlo trajectories at six
  horizons of eight.** At one week AUC 0.908 versus 0.826.
- What the simulation layer does earn: it converts an ordering into a scale, Brier skill
  −1.601 against the baseline's −4.851. *"A calibration wrapper around a lead-time ratio,
  which is a defensible thing to be, and not what the interface presents."*

### The display effect
- Chain 2, first exposure: 11 of 15 say the forecast confirms what they thought, 2 revise
  down, **none revises up**.
- Across all 15 turns with a forecast visible: **upward revisions outnumber downward 26 to 9**.
  *"The display does not sedate the operator; it transfers authority from the shop floor to
  the model."*

### Sample bounds, to state on every rate
- Two chains, **23 nodes (8 + 15), seven positives, 33 observable milestones**.
- Wilson: chain 1 precision 3/3 = 1.00 [0.44, 1.00]; recall 3/4 = 0.75 [0.30, 0.95];
  chain 2 precision 0/3 = 0.00 [0.00, 0.56].
- **None of the eight arm A AUCs is distinguishable from chance** (smallest p = 0.192), and
  the two chains' precision intervals overlap. The chain-1 versus chain-2 boundary is
  *"a hypothesis the campaign generated rather than a result the campaign established"*.
- One hypothesis of six confirmed (H5, contagion: ΔUd +0.079 on press turns against +0.005
  on calm turns).

### Three findings that survive any sample size
1. The u_time defect is a property of a code path, reproducible with one observation.
2. The saturation collapse of the criticality ranking is a proved theorem, not an inference.
3. The three outcome definitions score *identical* forecasts, so their spread is a fact
   about definitions, not an estimate. **Calibration moves by a factor of five while
   discrimination barely moves (AUC 0.485 → 0.484).**

### Two numbers to be careful with
- **HÉLIOS is 8 nodes / 19 turns / 152 declarations per arm / 3 arms.** The slide's
  "510 declarations" is a report figure that does not obviously reconstruct from
  152 × 3 = 456 plus the second chain. **Check it against the report before the defence.**
- **Do not mix the AERIS demo scenario** (10 nodes, 4 ranks, 8 weeks — the source of every
  screenshot) with HÉLIOS numbers on the same slide.

---

## 7. Deck conventions now in force

### Structure, 25 slides

| # | Slide | Part |
|---|---|---|
| 1 | Title | — |
| 2 | Plan | — |
| 3 | The company and the programme (three scores + the fourth) | 1 |
| 4 | The problem (yesterday/today/tomorrow, RQ, constraints) | 1 |
| 5 | The mission and its objectives | 1 |
| 6 | **How the work ran** (the big schema) | 1 |
| 7 | Plan | — |
| 8 | The week | 2 |
| 9 | Phases and milestones | 2 |
| 10 | Plan | — |
| 11 | Literature: what nobody joins up | 3 |
| 12 | The urgency score, term by term | 3 |
| 13 | Real urgency | 3 |
| 14 | Declared urgency | 3 |
| 15 | The adequacy | 3 |
| 16 | **SupplyScore: the application** | 3 |
| 17 | SupplyScore: architecture | 3 |
| 18 | Plan | — |
| 19 | Result 1: the semiconductor shortage | 4 |
| 20 | Result 2: can it forecast a crisis? | 4 |
| 21 | Plan | — |
| 22 | Objectives vs. outcomes | 5 |
| 23 | Limits and what comes next | 5 |
| 24 | **What I take from it** | 5 |
| 25 | Thank you | — |

### Timing, 20 minutes

The five plan dividers cost about 10 seconds each. That leaves roughly **19 minutes for
20 content slides, about 57 seconds each.** Three slides deserve more and should be paid
for elsewhere: **slide 6 (~90s)**, **slide 19 (~105s)**, **slide 20 (~105s)**.

Rehearse with a clock. *Respect du temps alloué* is worth a full point.

### Visual rules

- Palette, as the template actually uses it: navy `063C67`, title navy `043962`, azure
  `1D93C9`, dark azure `176F98`, ice `7ECBEE`, grey card `F4F4F6`, blue card `E9F5FB`,
  ochre `FFDA65`, pale ochre `FFF6DA`, strong ochre `FFC800`, grey text `858591`,
  rule `C0C0C8`.
- Fonts: **Arial Black** for titles and card headings, **Arial** for body. Both are
  ALTEN-sanctioned Office substitutes for Metropolis.
- Sizes: title 32.25pt (26pt when a title would otherwise run into the locator), card
  heading 16.5pt, body 13.5pt, small body 10.5pt, caption 9pt, letter-spaced eyebrow
  11.25pt with `spc="158"`.
- **Never write body text in ochre.** Ochre is a fill. On navy, use ice `7ECBEE`.
- **Ochre means one thing per slide** and the slide says what: the missing score (3), the
  future (4), the decision point (8), the adequacy (6), the sharp window (19).
- Left margin 0.39in, right margin 12.94in, so a full-width band is 12.55in.
- The locator occupies x ≥ 11.30, so **no title may exceed about 10.8in of text.**

### Mechanical rules

- **Numbers on every slide.** Content slides carry them top-right under the locator; plan
  and closing slides bottom-left.
- **No em dashes** anywhere, titles and captions included. Use a colon or parentheses.
- **English only**, including "Innovation Division · Toulouse Lab", never "Direction de
  l'Innovation". French inside a screenshot is fine and is named out loud.
- Every figure legible from the back of the room, or explicitly waved off as detail.

---

## 8. Build and QA pipeline (this machine)

No LibreOffice and no `markitdown` here. What works:

- **Python**: `py -3` (3.12), python-pptx 1.0.2, pymupdf, pypdf. Always set
  `PYTHONIOENCODING=utf-8` or printing non-ASCII crashes on cp1252.
- **Rendering**: PowerPoint COM through PowerShell is the only route to slide images.
  `$pres.SaveCopyAs($dir + "\slides.png", 18)` writes one PNG per slide into a
  `slides` subfolder. Script kept at `scratchpad/mfe/render.ps1`.
- **Editing**: unzip → `add_slide.py` for duplicates → repack → python-pptx for content.
  Do all structural work *before* editing any slide's content.
- **Reordering**: manipulate `p.slides._sldIdLst` directly.
- **Never write a Python script through a bash heredoc.** Use the Write tool. Confirmed
  again this session: a heredoc containing quotes and backslashes broke the shell.
- **`settext` must set `run.text` on run 0 and delete the rest.** Assigning
  `text_frame.text` collapses the paragraph to one unstyled run and loses the template.
- **Two shapes on a slide can share a name.** Slide 3 has two called "Text 20"; disambiguate
  by position.
- **Cloned slides inherit the source's title and subtitle box widths.** A longer title then
  wraps into the subtitle. Widen `Text 1` and `Text 2` to 11.6in after cloning.
- `<a:normAutofit/>` is not recomputed by python-pptx, so longer replacement text overflows
  silently. **Render and look at every slide you touched.**

The build is five idempotent stages, `build1.py` … `build5.py`, run by `all.sh` from
`base.pptx`. Re-running the chain reproduces the deck exactly.

---

## 9. Open items for John

1. **Check "510 declarations" on slide 22** against the report. It does not obviously
   reconstruct from the campaign records (§6).
2. **Be ready on "11 ALTEN Labs"** — a peer deck from the same division shows nine domains.
3. **Confirm whether this defence is closed** (huis clos), given "Confidential: YES".
4. **Rehearse with a clock**, and decide whether to cut one plan divider if it runs long.
5. Optionally fix `README.md:3`, which still badges 1614 tests against 2044 collected.
6. Optionally fix the thesis figure `fig:mcda_pipeline`
   (`Sections/Appendices/H.Technical.tex:314`), whose arrow from `U_d,local` into the
   PROMETHEE II box the code does not support. The surrounding prose is correct.
