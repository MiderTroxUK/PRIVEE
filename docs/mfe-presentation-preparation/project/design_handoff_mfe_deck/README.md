# Handoff: MFE defence deck, three diagram and imagery tasks

## Overview

`MfeDefence.dc.html` is a 43-slide, 20-minute engineering defence deck for John Hoarau's
ESTIA MFE (ALTEN Sud-Ouest, Innovation Division, Toulouse Lab, 13 April to 16 October 2026).
It is built and working. Three jobs are left, all of them visual craft that wants a real
tool rather than hand-written CSS boxes:

1. **Slide 9: the seven-step pipeline diagram** as an SVG (spec in `CLAUDE_CODE_DIAGRAM_SPEC.md`)
2. **Slide 10: the V-cycle** as an SVG, optional (spec below, task 2)
3. **App screenshots**: capture SupplyScore on the HELIOS campaign and build six new BUILD slides (task 3)

Do them in that order. Each is independently revertible.

## About the design files

`MfeDefence.dc.html` is the **live deliverable**, not a throwaway reference: the author
presents from it and exports PPTX and PDF from it. So this is not a "recreate in your
framework" handoff. It is a targeted modification of a file that already works.

Constraints that follow from that:

- **Inline styles only.** No stylesheets, no CSS classes. The only legal `<style>` content
  is `@font-face`, `@keyframes` and body resets, in `<helmet>` at the top of the template.
- **Edit with string replacement, not whole-file rewrites.** The file is ~225 KB of
  hand-positioned markup and the author has made direct edits to it.
- Slides are `<section data-screen-label="NN">` children of an `<x-import>` mounting
  `deck-stage.js`. Each carries its speaker notes in `data-speaker-notes`. Preserve
  them: at three to five words of on-slide text, the notes carry the whole talk.
- Each section is 1280 × 720, `position:relative`, `overflow:hidden`. Children are
  absolutely positioned. There is no flow layout to lean on.

## Fidelity

**High fidelity.** Exact colours, type sizes and offsets below are the real ALTEN 2026
values, taken from the Group PowerPoint masters. Match them; do not approximate.

## The hard layout rule (this is what broke three times already)

Every block is absolutely positioned with a hardcoded `top`. Nothing reflows. So if you
change any content, **measure the rendered result and re-set the `top` of everything
below it.** Do not estimate wrap counts.

```js
// run in the preview console; sections other than the current one are display:none
const sec = document.querySelector('deck-stage section[data-screen-label="10"]');
sec.style.display = 'block'; sec.style.visibility = 'hidden';
const sr = sec.getBoundingClientRect(), sc = sr.width / 1280;
[...sec.children].forEach(el => { const r = el.getBoundingClientRect();
  console.log(Math.round((r.top - sr.top)/sc), Math.round((r.bottom - sr.top)/sc),
              (el.textContent||'').trim().slice(0,30)); });
sec.style.display = ''; sec.style.visibility = '';
```

Two ceilings:
- Slides carrying the seven-step **spine strip** (`top:592px`): all other content must end
  by **y ≤ 580**.
- Slides without it: end by **y ≤ 680** (the footer wordmark sits at `bottom:23px`).

Right margin: content ends at **x = 1243** (`left:37` + `width:1206`). Padded boxes that
declare a `width` carry `box-sizing:border-box`. Keep it, or the box overruns the slide.

---

## Task 1: Slide 9, the seven-step pipeline diagram

Full brief in **`CLAUDE_CODE_DIAGRAM_SPEC.md`** (same folder). Summary: replace the CSS
flex chain with `assets/mfe/pipeline.svg`, a 1206 × 300 viewBox placed at x=37, y=176.
The slide is titled "HOW THE WORK RAN"; note it is now **slide 9**, not slide 8 as the
spec's older text says. The company slide was split in two after that spec was written.

---

## Task 2: Slide 10, the V-cycle (optional, lower priority)

Slide 10 was "FIVE LOOPS, NOT ONE PASS", five flat cards that read as a five-step line
rather than as iteration. It has been replaced by a **V-cycle diagram built in HTML**:
requirements, specification and design descending the left arm, implementation at the
apex, then tests, integration and validation ascending the right arm, with dashed
"verifies" links between the levels that face each other, and an ochre band recording
that the V ran five times and that loop 0 was dropped in April.

That version works and is measured clean. Converting it to SVG is **optional** and worth
doing only if task 1 lands well and the two diagrams would benefit from sharing one visual
language. If you do it, the same constraints apply as task 1, plus:

- Keep the V readable as a V. The current version earns that with staircase offsets
  (left arm at x 60, 170, 280; right arm at x 920, 810, 700; apex centred at 455).
- The dashed horizontal links are load-bearing: they are what makes it a V-cycle rather
  than a flowchart. Do not drop them for tidiness.
- The whole diagram must fit y 148 to 500, because the ochre band sits at 534.

---

## Task 3: capture SupplyScore on HELIOS, then build the BUILD slides

### Why HELIOS and not AERIS

Every screenshot currently in the deck comes from the **AERIS demo scenario** (10 nodes,
4 ranks, 8 weeks). Every result in part 4 comes from the **HELIOS campaign** (the
semiconductor shortage: 8 nodes, 19 turns, 152 declarations per arm, 3 arms). The ground
rules forbid mixing the two on one slide, which is why the current interface slides carry
no campaign numbers.

Re-capturing on HELIOS data removes that constraint: the interface slides and the results
slides would then describe the same campaign, and the presenter can point at the same
node in both halves of the talk. That is the point of this task.

If HELIOS cannot be reconstituted from the campaign runs, **stop and say so**. Keep the
AERIS captures rather than labelling AERIS screens with HELIOS numbers.

### Running the app and the capture script

The capture script does not start the server. Two steps.

1. Start the app against the HELIOS databases:
   ```
   python -m supplyscore.cli --open-browser
   ```
   (or `scripts\SupplyScore.ps1`, which resolves the venv Python itself). The project id
   is `helios` (see `docs/Thesis_Cranfield_JH_2026/Utilities/figures/derive.py`). The AERIS
   demo databases live at `%LOCALAPPDATA%\SupplyScore\demo_aeris`; locate or rebuild the
   HELIOS equivalent before capturing.

2. Capture:
   ```
   .\.venv\Scripts\python.exe scripts\demo_screenshots.py \
       --db-dir "<HELIOS db dir>" --scenes --out docs/presentation/screenshots_helios
   ```

What the script does, per `docs/reference_cli.md`: headless Chrome (`--headless=new`,
chromedriver from `%LOCALAPPDATA%\supplyscore\chromedriver`), reads `registry.sqlite`
read-only to discover the project and the notable nodes (the client, a rank-1 node, the
deepest node, the worst-adequacy node), injects the project and operator selection into
`sessionStorage`, then visits 13 pages and writes 1920x1080 PNGs plus a
`-pleine-page.png` variant wherever the content exceeds the viewport. **No database
writes.** It exits 1 if any of pages 01 to 13 weighs 30 KB or less, which usually means a
blank page; the offending captures are listed at the end of the run.

`--scenes` adds four interactive scenes: `14-hebdo-noeud-crise` (the weekly review of the
node in crisis), `15-simulation-choc` (a simulated shock on a deep node),
`16-simulation-criticite` (systematic criticality) and `17-rapport-session` (the HTML
session report opened in the browser).

Set `PYTHONIOENCODING=utf-8` first or printing non-ASCII crashes on cp1252.

### The 17 captures, and what each is worth on a slide

| Capture | Already on a slide | Worth adding |
|---|---|---|
| `01-projets` | no | multi-tenant: one database per node, projects side by side |
| `02-onboarding` | no | **yes.** The 4-step wizard is the data-quality gate for everything else: identity and topology, then specs and milestones, then the KPI baseline, then the baseline AHP matrix |
| `03-hebdo` | slide 29 (AERIS) | re-shoot on HELIOS |
| `04-questionnaire` | slide 20 (AERIS) | re-shoot on HELIOS |
| `05-dashboard` | slides 26, 27, 28 (AERIS, three crops) | re-shoot on HELIOS |
| `06-simulation` | no | **yes.** Monte Carlo lead-time distribution, which is the machinery behind result 2 |
| `07-edition` | no | low value, skip unless a slide needs it |
| `08-ponderation` | slide 21 (AERIS) | re-shoot on HELIOS |
| `09-graphe` | slide 30 (AERIS) | re-shoot on HELIOS |
| `10-rapport` | no | **yes.** The calibration view: did the H score predict the real ruptures |
| `11-admin` | no | low value, skip |
| `12-fiche-noeud` | slide 30 (score chips crop) | re-shoot on HELIOS |
| `13-explication` | slide 25 (AERIS) | re-shoot on HELIOS, this is the hero interface slide |
| `14-hebdo-noeud-crise` | no | **yes.** The weekly review of the node that is actually failing, concrete where slide 29 is generic |
| `15-simulation-choc` | no | **yes.** A shock on a deep node, pairs with the criticality slide |
| `16-simulation-criticite` | slide 31 (AERIS) | re-shoot on HELIOS |
| `17-rapport-session` | no | **yes.** Evidence for the "every number reproducible from raw artefacts" claim in part 5 |

Six new slides, in that priority order. They belong in the BUILD run, currently slides 25
to 32, with the spine strip showing **BUILD** lit.

### The crop protocol, which is not optional

Five interface screenshots in this deck were unreadable postage stamps before being
re-cropped, so the method is written down. It has been proven on six images.

1. **Never put a full-page capture in a landscape box.** `object-fit:contain` scales to the
   height and leaves the width empty; a 1898x2139 source in a 1207x401 box draws at 29% of
   the box and under 3px of text.
2. **Crop to the panel the slide's title claims**, not to the top of the page. Slide 25
   claims "why this score, term by term", so the crop is the card that decomposes the score.
3. **Measure the source, do not eyeball a scaled preview.** Scan the PNG row by row for
   non-white pixels to find the real content bands, then put the crop edges inside the white
   gaps between cards. Cropping by eye is what cut a figure's axis labels through the digits.
4. **Set the box to the crop's ratio** and size it so the scale lands at or above 1.0.
   Below about 0.7 the source text drops under the 16px floor.
5. **Plotly clips value labels at the plot edge.** When the top bar's label is truncated in
   the source, widening the crop cannot recover it: mask it with a white rectangle so the bar
   runs cleanly to the edge, and state the value in slide text instead. Do not caption the
   defect.
6. **Nothing below 16px** on the slide, chrome excluded.

### After inserting slides

- Preserve every `data-speaker-notes`, and write real notes for new slides: three to five
  words go on the slide, the substance goes in the note.
- Renumber every footer. Each slide carries its number in a div matching `n | <total>`;
  the total appears on all of them and must be updated when the count changes.
- Re-measure every slide (see the hard layout rule above). The last five rounds of defects
  were all "content moved and the block below it did not".
- The interface is in French. That is deliberate, the deck names it out loud on slide 20,
  and it must not be re-rendered or cropped out.

---

## Design tokens

Exact ALTEN 2026 values. The bound design system at
`_ds/alten-design-system-4bbc3a67-607d-41dc-ae55-8b9aa9837f27/` is loaded by `ds-base.js`
in `<helmet>`; its `tokens/*.css` carry these as `var(--*)`.

| Token | Hex | Use |
|---|---|---|
| navy | `#063C67` | strong fills, the 11px left rule |
| title navy | `#043962` | title and card-heading text |
| azure | `#1D93C9` | subtitles, rules, arrowheads, icons, step numbers |
| dark azure | `#176F98` | numeric text on light fills |
| ice | `#7ECBEE` | text on navy only |
| pale blue | `#B1DFF4` | secondary text on navy |
| blue card | `#E9F5FB` | light card fill |
| grey card | `#F4F4F6` | neutral card fill |
| grey card 2 | `#E9E9ED` | de-emphasised card fill |
| ochre | `#FFDA65` | **one thing per slide**, and the slide says what |
| strong ochre | `#FFC800` | bar fills only |
| pale ochre | `#FFF6DA` | highlighted table row |
| grey text | `#858591` | captions, page numbers |
| rule | `#C0C0C8` | hairlines |
| body text | `#4A4A55` | secondary body copy |

Type: **Arial Black** (fallback Archivo Black) for every heading, uppercase, `line-height:.9`.
**Arial** (fallback Arimo) for eyebrows and labels, `letter-spacing:.14em` to `.16em`
uppercase. **Calibri** (fallback Carlito) for running copy.

Sizes in use: title 43px (34px where a title would otherwise wrap into the subtitle),
subtitle 23px, card heading 22–30px, body 18–21px, caption 16px, eyebrow 13–15px.
**Nothing below 16px.**

Geometry: left rule 11px navy. Title at `left:37, top:18`, max `width:1000px` (the locator
occupies x ≥ 1084). Subtitle at `top:74`. Content column `left:37, width:1206`. Footer
wordmark `right:26, bottom:23, width:75`. Locator chips 30 × 26 at `right:26, top:20`;
page number under them at `top:52`.

**Zero border radius anywhere.** No gradients on content (the brand gradient is a chapter
device this deck does not use). No shadows. No em dashes in any copy. English only.

## Assets

- `assets/icons/<group>/<name>.svg`: 466 ALTEN icons, native colour `#1D93C9`. Search here
  before drawing anything. If a glyph is missing, say so rather than substituting from
  another library: the line weight will not match.
- `assets/logo/`: `alten-wordmark-navy.svg`, `alten-wordmark-white.svg`, `alten-logo-color.png`.
- `assets/mfe/`: `gantt.png`, `questionnaire-ahp.png`, `urgency-gap.png`, `logo-estia.png`,
  `disco-network.png` (no longer used: the DISCO framing was cut), `reliability-armA.png`,
  `influence-armB.png`.
- `assets/mfe/app/`: the application screenshots listed in task 3.
- `assets/images/`: five ALTEN brand photographs, cool and blue-dominant.

## Ground truth for any factual question

`AZURE/docs/MFE_ESTIA_JH_2026/SOUTENANCE_GROUND_RULES.md` in the author's local folder.
§2 maps the supervisor's 21 review points, §3 lists the facts verified against the
codebase (and the deck errors they corrected), §6 holds every number with its confidence
interval, §7 the visual and mechanical rules. **Where that document and the deck's prose
disagree, that document wins.** Do not invent a figure; if a number is missing, ask.

Two live cautions from §9: the "510 declarations" figure does not reconstruct from the
campaign records, and "11 ALTEN Labs" is a site count where a peer deck shows nine
thematic domains.

## Files in this bundle

- `MfeDefence.dc.html`: the deck (copy of the working file; make your edits in the
  project root copy, not this one)
- `CLAUDE_CODE_DIAGRAM_SPEC.md`: task 1, the seven-step pipeline diagram, in full

## Acceptance, all three tasks

1. Deck still loads with a clean console and 39 slides.
2. Every slide re-measured: no block overlaps another, nothing crosses y=580 on a
   spine slide or y=680 elsewhere, nothing past x=1243.
3. Exactly one ochre element per slide.
4. No text below 16px.
5. Speaker notes preserved on every slide you touch.
6. Prints identically through the deck's PDF path (one page per slide).
