# Poster image briefs, version 2

Critique of the five generated images and the rewritten briefs. Written 2026-08-13
against `HOARAU_Poster_MScCSTE_V3.html`.

## Read this first: three of these five should not be AI-generated at all

Images 2, 3 and 4 are **diagrams**, not illustrations. Their entire value is exact
text and exact geometry: a table whose cells must be right, a formula that must be
typeset correctly, a graph whose arrows must point in provably opposite directions.
Diffusion models cannot guarantee either. That is not a prompting failure, it is what
the tool is. Every text defect below (`attolated`, `dyn. dyn.`, `Everstream : Resilinc`,
the mangled `Ur_local`) comes from asking an image generator to be a typesetter.

Recommendation: **build 2, 3 and 4 as SVG instead.** Correct by construction, exact
ALTEN hex values, real typeset math, infinite resolution at A1, editable forever, and
no regeneration lottery. Keep 1 and 5 as generated art, where the loose, illustrative
quality is genuinely an asset.

The briefs below are written for regeneration anyway, in case you want to try again.

---

## Target canvases (measured from the live poster)

| # | File | Pane on the poster | Canvas to generate |
|---|---|---|---|
| 1 | `two_pathologies.jpg` | 364 × 91 mm | **3.5:1**, 4200 × 1200 px |
| 2 | `empty_column.jpg` | 364 × 91 mm | **3.5:1**, 4200 × 1200 px |
| 3 | `noisy_or_detectors.jpg` | 180 × 118 mm | **3:2**, 2400 × 1600 px |
| 4 | `dag_propagation.jpg` | 180 × 118 mm | **3:2**, 2400 × 1600 px |
| 5 | `turn_six.jpg` | 364 × 102 mm | **3.5:1**, 4200 × 1200 px |

Current files are all 1.79:1 or 1.49:1, so 1, 2 and 5 letterbox and waste roughly half
the pane width.

## Palette, binding on every image

`navy #043962` · `azure #008BD2` · `ochre #FFDA65` · `ice #B2E0F5` · `grey #8C8C9A` ·
`rule #CDCEDA` · white background.

**Never any red.** It is excluded from the ALTEN design palette. Never set text in
ochre on white. No 3D, no bevels, no drop shadows, no gradients except a flat node
fill ramp where stated.

---

# 1. two_pathologies.jpg

## What is wrong

1. **The scale is semantically inverted, and this is fatal.** The pan carrying `2.25×`
   is the *raised* one. A balance says the raised pan is lighter. The image therefore
   states that hidden risk weighs **less** than false urgency, which is the exact
   opposite of the poster's thesis. Anyone who reads balances will read it backwards.
2. **Hidden risk has no visual subject.** The brief asked for one small node, pulsing,
   unnoticed. There is a dark dot at the extreme right edge, half cropped by the frame,
   invisible at poster distance. The right panel currently shows "calm room" and nothing
   else, so it reads as *good*, not as *danger nobody is looking at*.
3. **It is not the same room twice.** Different screen grid, different desk layout,
   different perspective. The parallel that makes the point is lost.
4. **Glyph noise.** The left wall carries at least six different glyph types (triangle,
   truck, gear, shield, megaphone, document). It reads as clip-art scatter.
5. **The operators face the wrong way.** On the right they face their screens. They
   should be turned away from the one screen that matters.
6. **Mismatched vanishing points** across the centre seam.

## Rewritten brief

> Ultra-wide banner, 3.5:1, 4200 × 1200 px. Flat vector editorial illustration, no
> photorealism, no 3D, no shadows.
>
> ONE control room, drawn TWICE, left half and right half, from the **same camera
> angle** with the **same desk layout and the same 5 × 4 screen grid** in both halves.
> The two halves must be recognisably the identical room.
>
> LEFT HALF: every screen carries **the same single warning triangle glyph**, repeated,
> filled ochre `#FFDA65`. Three navy silhouettes stand, arms raised, one holding a phone;
> loose sheets of paper in the air.
>
> RIGHT HALF: every screen shows a flat calm line in ice `#B2E0F5`, **except exactly one
> screen**, positioned in the upper-left of that half so it is well inside the frame and
> never near an edge. That one screen is filled navy `#043962` with a single ochre dot at
> its centre and three concentric ochre rings radiating from it. It must be the highest
> contrast object in the right half. The three navy silhouettes sit at their desks with
> their **backs turned to that screen**, facing the opposite direction.
>
> CENTRE, exactly on the midline: a balance scale. **The right pan hangs LOW and the left
> pan rides HIGH.** The beam tilts down to the right. On the low right pan sits a solid
> navy block bearing `2.25×` in ochre. The left pan is empty. Getting this tilt right is
> the single most important instruction in this brief: the heavier side is the right.
>
> Two full-width navy caption bars along the bottom, one under each half, white text,
> rendered EXACTLY and with no other text anywhere in the image:
> `FALSE URGENCY   F = [Ud − Ur]+`
> `HIDDEN RISK   H = [Ur − Ud]+`
>
> Do NOT: raise the pan carrying 2.25×; use more than one glyph type on the left wall;
> place the alerting screen near any edge; draw faces; use red; add any caption other than
> the two given strings.

---

# 2. empty_column.jpg

## What is wrong

1. **`Markov / dyn. dyn. Bayesian`** — the word "dyn." is duplicated. A plain text defect
   on a poster that will be read at 40 cm by an examiner.
2. **`Everstream : Resilinc : Interos`** — colons instead of separators. It reads as a
   ratio between three companies.
3. **The empty cells are invisible.** They are hairline grey dashes. The emptiness is the
   entire argument of the figure, and it currently reads as blank space where the renderer
   failed, not as a deliberate "this approach does not do this".
4. **The ochre divider is a hairline.** SupplyScore does not read as the answer column.
5. **Inconsistent tick colouring.** SupplyScore's row-1 tick is azure like all the others,
   then rows 2 and 3 are ochre. A reader cannot tell whether ochre means "SupplyScore" or
   "the differentiating capability".
6. **45° rotated headers** are hard to read at poster distance and the last one collides
   with the divider.

## Rewritten brief

> Ultra-wide banner, 3.5:1, 4200 × 1200 px. Flat editorial matrix. No outer border, no
> title inside the image, no chrome, no 3D.
>
> Six columns, headers set **horizontally, not rotated**, in two short stacked lines each
> so they fit. Three rows, labels left-aligned at the left edge.
>
> Column headers, rendered EXACTLY:
> `Ripple-effect` / `models` · `Markov and` / `dynamic Bayesian` · `Bayesian SC` /
> `risk networks` · `TTR / TTS` / `stress tests` · `Everstream · Resilinc` / `· Interos` ·
> `SupplyScore`
>
> Row labels, rendered EXACTLY:
> `Scores physical reality` · `Scores human declaration` · `Scores the gap`
>
> Cells. Row 1: a filled azure `#008BD2` disc with a white tick, in all six columns.
> Rows 2 and 3, columns 1 to 5: **an open circle outlined in grey `#CDCEDA` with a clearly
> visible diagonal slash through it**, sized the same as the ticked discs. Not a small
> dash. The empty state must be as visually heavy as the filled state, so the reader sees a
> wall of "no" rather than a gap.
> Rows 2 and 3, column 6 only: a filled ochre `#FFDA65` disc with a navy tick.
>
> Separate the SupplyScore column with a **solid ochre vertical band 12 px wide** running
> the full height, and set its header in navy bold at 1.3× the size of the other headers.
>
> Do NOT: rotate any text; duplicate any word; use colons between the three company names;
> render the empty cells as dashes or leave them blank; add a title, legend or caption.

---

# 3. noisy_or_detectors.jpg

## What is wrong

1. **They do not read as smoke detectors.** They read as industrial fans, turbines or
   speaker cones. The whole metaphor, "six detectors, any one of which can trip the
   alarm", does not land.
2. **The formula is ASCII-mangled.** `Ur_local` renders with a literal underscore and
   `ω_m` with a literal underscore, sitting next to properly typeset formulas in the
   poster's text column. It looks amateurish by comparison.
3. **The product operator has no index.** `∏` should carry `m` beneath it.
4. **The strike-through on MEAN = 0.17 is a single thin diagonal**, indistinguishable from
   a scratch or a compression artifact.
5. **Dead grey band** across the top 8 % of the canvas doing nothing.
6. **The alarm arcs read as motion blur** rather than sound.

## Rewritten brief

> 3:2 landscape, 2400 × 1600 px. Flat vector, no 3D, no shadows.
>
> Six **ceiling smoke detectors** in one row, drawn face-on and unmistakably as smoke
> detectors: a shallow circular disc with a narrow raised rim, a small vent grille arc on
> the lower third, and one small indicator LED. Not fans, not turbines, not speakers, no
> radial blades.
>
> Five are navy `#043962` with an unlit ice `#B2E0F5` LED. The second one is filled ochre
> `#FFDA65` with a lit LED and **three thick concentric ochre arcs** radiating from its
> upper edge, drawn as bold solid crescents, not thin motion lines.
>
> Labels beneath each, small caps navy, EXACT strings:
> `TIME` `CAPACITY` `PERFORMANCE` `RISK` `COST` `CO₂`
>
> Below, two chips side by side, equal height. LEFT chip: grey `#8C8C9A` fill, text
> `MEAN = 0.17` in white, with a **bold X drawn across the whole chip in navy**, two thick
> strokes corner to corner, unmistakably a rejection mark and not a scratch. RIGHT chip:
> navy fill, text `PROBABILISTIC OR = 1.00` in ochre.
>
> Beneath both chips, one line of **properly typeset mathematics**, navy, with real
> subscripts and superscripts and no underscore characters visible:
> U with subscript "r,local", then `= 1 −`, then a large `∏` with a small `m` directly
> beneath it, then `(1 − u` subscript `m` `)` superscript `ω` subscript `m`.
>
> No ceiling rail, no grey band, white background throughout.
>
> Do NOT: draw radial blades or fan shapes; render any underscore character; omit the
> index under the product sign; use a thin line for the rejection mark.

---

# 4. dag_propagation.jpg

## What is wrong

1. **`attolated`.** Bottom-left label reads "declared need attolated by γ". The word is
   "attenuated". A spelling error, on a poster, at an examined submission.
2. **Every label appears twice.** "declared need descends, attenuated by γ" top-left and
   "declared need attolated by γ" bottom-left; "physical risk climbs, scaled by β"
   top-right and "physical risk, scaled by β" bottom-right. Four labels doing the work of
   two, one of them misspelled.
3. **The two flows are not counter-directional, and this is fatal.** Azure and ochre
   arrows both loop in both directions around the diagram. The one idea the figure exists
   to convey, that need travels one way and risk travels the other, is absent.
4. **There is no tier structure.** The brief asked for five ranked tiers, left to right.
   The result is an amorphous cloud with no readable ordering.
5. **The node glyphs are arbitrary.** The same factory, truck and satellite icons repeat
   without corresponding to any role or rank.
6. **The dashed backup arc is drawn as a large X across the centre**, which reads as
   somebody having crossed out the middle of the diagram.
7. **No end labels.** Nothing says which side is the deep supplier and which is the final
   customer.

## Rewritten brief

> 3:2 landscape, 2400 × 1600 px. Flat vector network diagram, no 3D, no shadows.
>
> Eight nodes arranged in **five clearly separated vertical tiers, left to right**, with
> generous whitespace between tiers so the ranking is unmistakable: tier 1 has 1 node,
> tier 2 has 2, tier 3 has 2, tier 4 has 2, tier 5 has 1.
>
> Nodes are rounded rectangles. Fill graded by tier along a ramp from ice `#B2E0F5` at the
> left to navy `#043962` at the right. Each carries one simple white or navy glyph
> matching its role: wafer, furnace, circuit board, truck, satellite.
>
> Small navy labels outside the frame edges, EXACT strings:
> under the leftmost tier: `deep supplier`
> under the rightmost tier: `final customer`
>
> **Two flows, and they must be strictly opposite.** Draw the azure `#008BD2` arrows so
> that **every single one points right to left**, entering each node from its right side.
> Draw the ochre `#FFDA65` arrows so that **every single one points left to right**,
> entering each node from its left side. No loops, no bidirectional arcs, no azure arrow
> pointing right, no ochre arrow pointing left. Route azure arcs above the node row and
> ochre arcs below it, so the two streams never overlap.
>
> Exactly TWO labels in the whole image, each appearing ONCE, EXACT strings:
> `declared need descends, attenuated by γ` placed once above the azure stream
> `physical risk climbs, scaled by β` placed once below the ochre stream
>
> One single dashed grey `#CDCEDA` arc between two specific adjacent nodes in tier 3 and
> tier 4, labelled once: `backup arc, deliberately inert`. It must connect two nodes, not
> cross the diagram.
>
> Do NOT: repeat any label; spell "attenuated" any other way; draw arrows of one colour in
> both directions; cross the two streams; draw an X across the centre; omit the tier
> separation.

---

# 5. turn_six.jpg

## What is wrong

1. **Every number is printed twice.** `99.6%` appears large in the centre and again small
   on the arc; `0.0%` likewise. It reads as a rendering mistake.
2. **The gauges are not identical, and the brief said they must be.** The left arc is
   thicker and of larger radius than the right. The entire visual argument is "same
   instrument, opposite readings, and the confident one is wrong", which only works if
   the two are drawn identically apart from needle and fill.
3. **A 0 % gauge with a completely full grey arc is contradictory.** Full fill reads as
   full value. The zero gauge should show an empty track, outlined only.
4. **A white notch** sits between the end of the ochre fill and the needle on the left
   gauge.
5. **The small on-arc percentages are white or pale grey on light fill** and are
   effectively illegible.
6. **The factory-and-snowflake glyph overlaps into an unreadable blob.**
7. **The punchline is the weakest type in the image.** `near anti-correlated` is set
   lowercase and small while `TURN 6`, which carries no argument, is set large and caps.

## Rewritten brief

> Ultra-wide banner, 3.5:1, 4200 × 1200 px. Flat vector diagnostic infographic, no 3D,
> no shadows, no skeuomorphic metal.
>
> A narrow navy header bar across the full width, white text, EXACT: `TURN 6`.
>
> Two semicircular gauges, placed on the left third and the right third, with generous
> space between them. **The two gauges must be geometrically identical**: same centre
> height, same radius, same track thickness, same needle length, same tick marks. Only
> the fill and the needle angle differ.
>
> LEFT gauge, labelled `CompoDis` beneath in bold navy: track filled ochre `#FFDA65` from
> the left end round to the needle, needle at the far right of the sweep, no gap between
> fill and needle. One number only, set large in navy inside the arc: `99.6%`.
>
> RIGHT gauge, labelled `NovaFab` beneath in bold navy: track drawn as an **empty
> outline** in grey `#CDCEDA`, unfilled, needle at the far left of the sweep. One number
> only, set large in navy inside the arc: `0.0%`.
>
> Beneath each gauge, one card with a thin grey border, identical size and identical
> internal alignment. Left card: a navy tick glyph, then two lines, EXACT:
> `Milestone delivered ON TIME`
> `(due T9, delivered T9)`
> Right card: a small factory glyph and, **beside it, not overlapping it**, a snowflake
> glyph, then three lines, EXACT:
> `Milestone MISSED`
> `(due T10, delivered T11)`
> `fab frozen since T6`
>
> A navy bar across the full width at the bottom, **the same height as the header bar**,
> text in white set in caps at the same size as `TURN 6`, EXACT:
> `NEAR ANTI-CORRELATED`
>
> Do NOT: print any percentage more than once; fill the zero gauge; draw the two gauges at
> different sizes; overlap the factory and snowflake; set the bottom line smaller than the
> header.
