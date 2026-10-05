# Claude Code brief: the SupplyScore pipeline diagram

Paste this file into Claude Code as the task. It has everything needed; do not
ask the deck author for more input before producing a first version.

## What to build

One **SVG diagram**, `assets/mfe/pipeline.svg`, that replaces the CSS box chain
currently on **slide 9 ("HOW THE WORK RAN")** of `MfeDefence.dc.html`.

This diagram is the single most important visual in a 20-minute MFE defence. It
is the answer to a specific request from the ALTEN supervisor: *one big diagram,
built backwards from the conclusion*. It is on screen for about 90 seconds while
the speaker narrates the whole project against it, and it is the map the jury
refers back to for the following 15 minutes.

## The content, exactly

A seven-step chain, left to right. Steps 1 to 4 are grouped under the heading
**THE INSTRUMENT**; steps 5 to 7 under **VALIDATION**.

| # | Label | Caption | Group |
|---|---|---|---|
| 1 | SITUATION | A twin that scores state | Instrument |
| 2 | DECLARATION TOOL | Elicit the human signal | Instrument |
| 3 | CALCULATOR | Six blocks, non-compensatory | Instrument |
| 4 | ADEQUACY | The distance between them | Instrument |
| 5 | BUILD | The interface and the agents | Validation |
| 6 | TEST | Does it find a known crisis? | Validation |
| 7 | FORECAST | Can it forecast one? | Validation |

Three relationships must be legible without narration:

1. **The forward chain**, 1 through 7, with arrows.
2. **Step 5 is a pivot, not a step.** Steps 1 to 4 produced an instrument that
   was not convincing on its own; step 5 is where the author built the operator
   interface and the agent population to test it. Step 5 carries the
   slide's single ochre fill for that reason.
3. **Steps 6 and 7 are two questions with different answers.** 6 succeeded
   (precision 1.00 before the crisis went public), 7 failed (negative Brier
   skill at every horizon). Mark them as a matched pair of questions. Do **not**
   encode the answers in the diagram: the speaker reveals those later, and
   pre-empting the failure on slide 8 spoils the arc.

Add one line under the chain, at caption size: `Built backwards from the conclusion.`

## Hard constraints

**Canvas.** 1206 × 300 px viewBox, `preserveAspectRatio="xMidYMid meet"`. It is
placed at x=37, y=176 inside a 1280 × 720 slide. Nothing may bleed outside the
viewBox.

**Palette.** Use only these, and use them as fills, never as body text colour:

| Token | Hex | Use |
|---|---|---|
| navy | `#063C67` | strong fills, arrowheads on the validation half |
| title navy | `#043962` | step labels |
| azure | `#1D93C9` | rules, arrowheads, group headings, step numbers |
| dark azure | `#176F98` | numeric text if needed |
| ice | `#7ECBEE` | text on navy only |
| blue card | `#E9F5FB` | instrument step fills |
| grey card | `#F4F4F6` | validation step fills |
| ochre | `#FFDA65` | **step 5 only, once on the diagram** |
| grey text | `#858591` | captions |
| rule | `#C0C0C8` | hairlines |

**Type.** Step labels: Arial Black (fallback Archivo Black), uppercase, 19px,
`letter-spacing: 0`. Captions: Arial, 17px. Group headings: Arial Bold, 14px,
uppercase, `letter-spacing: .16em`, azure. Step numbers: Arial Black, 24px.
Nothing below **16px**: the deck's floor for a 1280-wide slide, and the school's
checklist marks legibility explicitly.

**No decoration.** Boxes, arrows, rules, type. No gradients, no drop shadows, no
rounded-corner flourishes beyond a 0 or 2px radius, no icons, no illustration,
no emoji. The deck's whole visual argument is that it is an engineering document.

**No em dashes** anywhere in the diagram text. Colons or parentheses.

**English only.**

## Technical requirements

- Hand-written SVG, no build step, no external font files: reference font
  families by name in `font-family` attributes so the deck's already-loaded
  Archivo Black and Arimo webfonts apply.
- Text as `<text>` elements, never as paths. It must stay selectable, searchable
  and translatable, and the PowerPoint export path converts SVG text to native
  text runs.
- Every element gets a stable, meaningful `id` (`step-3`, `arrow-3-4`,
  `group-instrument`) so the deck author can restyle one piece without reading
  the whole file.
- Wrap each step in a `<g>` with `role="img"` and an `<title>` giving the label
  and caption, so the diagram is readable by assistive technology and so hover
  tooltips work in the browser.
- Total file under 20 KB.

## Then: wire it into the deck

Replace the flex chain in slide 9 of `MfeDefence.dc.html` (the block between the
group headings and the navy band) with:

```html
<img src="assets/mfe/pipeline.svg" alt="The seven-step project chain: situation, declaration tool, calculator, adequacy, build, test, forecast" style="position:absolute;left:37px;top:176px;width:1206px;height:300px">
```

Use `dc_html_str_replace`, not a whole-file rewrite. Leave everything else on the
slide alone: the title, the locator, the navy band, the speaker notes. Note slide 9 no longer carries a spine strip: it was removed as redundant under a diagram that already is the chain.

## Acceptance criteria

1. Renders identically in Chrome and in the PDF print path.
2. Readable at 40% zoom (the thumbnail rail) as seven grouped blocks; readable at
   100% as seven labelled steps with captions.
3. Exactly one ochre element in the whole diagram.
4. No text smaller than 16px.
5. The instrument/validation split is visible before any text is read.

## Second task, if the first lands well

The deck has three further hand-drawn CSS schematics that would be better as
SVGs built to the same rules. In priority order:

1. **The dropped time curve.** (The slide that carried this was cut as redundant; the curve is now only worth drawing if the author reinstates it.) Currently a CSS linear-gradient faking a
   rising line inside a box. Should be a plotted curve: urgency flat then
   rising steeply into a deadline, with the y-axis labelled `urgency` and the
   x-axis `time to deadline`, plus a second flat line labelled
   `a node on time but out of capacity` sitting at zero the whole way across.
   That second line is the entire argument for why the model was dropped, and
   right now the slide asserts it in words instead of showing it.
2. **Slide 23, the propagation ladder.** Four tiers with gamma descending on the
   left and beta ascending on the right. The CSS grid version works but the two
   arrow columns do not visually connect to the tiers they act on.
3. **Slide 31, the campaign timeline.** 19 turn cells, T0 to T18, first six ochre
   ("signal sharp"), remainder grey ("crisis public"). Wants proper turn ticks and
   a marked turn 8, where the satellite prime actually missed.

Do these as separate files (`timecurve.svg`, `propagation.svg`, `timeline.svg`)
and wire them in one at a time, so any one can be reverted independently.

## Context you may want

- `AZURE/docs/MFE_ESTIA_JH_2026/SOUTENANCE_GROUND_RULES.md`: §2 item 11 is the
  origin of this diagram; §7 holds the deck's full visual and mechanical rules.
- `_template/mfe-defence/palette.dc.html`: the reference slide palette the deck
  is built from. Read it for the house style; do not edit it.
