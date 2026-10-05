# ALTEN Design System

The visual system of **ALTEN** — a French-headquartered world leader in Engineering and IT Services. Everything here is reverse-engineered from the Group's official PowerPoint theme, icon pack and corporate factsheet, so the values are the real ones: exact hex codes from the theme XML, exact type sizes and offsets from the slide masters, and the real logo and icon artwork extracted as SVG.

<blockquote>
WE ARE A WORLD LEADER IN ENGINEERING AND IT SERVICES.<br>
At ALTEN, we see our specialists as architects — today's designers of tomorrow's world.
</blockquote>

Baseline: **BUILDING TOMORROW'S WORLD TODAY**. Founded 1988. 57,400 employees, 51,000 engineers, 6,500+ clients, 30+ countries, €4.10 billion revenue (2025). 70 % Engineering / 30 % IT Services.

---

## What ALTEN actually designs

ALTEN is a services group, not a software product company. There is **no app and no product UI** in the material provided. The design system therefore covers the surfaces ALTEN really publishes:

| Surface | Source | Where it lives here |
|---|---|---|
| 16:9 presentation deck (the primary surface) | `2025/2026 ALTEN Templates.potx` — 60 masters, 3 themes | `ui_kits/presentation/`, `slides/` |
| Reference-project one-pager | `2026-Reference-Project-Templates.pptx` | `ui_kits/reference_project/` |
| A4 portrait document | `2026 A4 ALTEN_Template_Portrait.potx` | `ui_kits/print_document/` |
| Corporate factsheet ("ALTEN Essentials") | `ALTEN Essentiel_A3_2026_EN_WEB.pdf` | `ui_kits/print_document/` |
| Icon library | `Icons pack - April 2026.potx` | `assets/icons/` (466 SVGs) |

The 2025 theme replaced the 2024 one and is described in the Group tutorial as *"more spacious for better content readability and to better align with the Group's new graphic charter"*; it is mandatory for all new Communications Department material. The 2026 theme continues it with a lighter yellow accent (`#FFDA65`) and adds the reference-project and A4 templates.

### Sources given to me
- Local folder `ALTEN PPT/` (read-only mount) and `uploads/`:
  `2024 / 2025 / 2026 ALTEN Templates .potx`, `2025 ALTEN Templates PC CLIENT.pptx`, `2025 LIGHT ALTEN Templates.pptx`, `2026 A4 ALTEN_Template_Portrait.potx`, `2026-Reference-Project-Templates.pptx`, `Icons pack - April 2026.potx`, `ALTEN Essentiel_A3_2026_EN_WEB.pdf`, and four theme/Copilot tutorial decks (EN + FR).
- No Figma file, no repository, no web export, no brand-book PDF beyond the A3 factsheet.
- **`2026 ALTEN Templates Powerpoint.potx` could not be read** — it exceeds the 30 MiB import limit. Its theme colours are identical to the 2025 file (both declare the `Alten` colour scheme), and the 2026 A4 + reference-project templates were read in full, so the palette and type are confirmed; individual 2026 master geometry is not.
- The brief also named **CRANFIELD** and **ESTIA** alongside ALTEN. No Cranfield University or ESTIA material was supplied, so nothing here represents either institution. See "Open questions".

---

## Content fundamentals

**Register.** Corporate, declarative, engineering-confident. Short factual sentences. No marketing froth, no exclamation marks, no questions to the reader, no emoji anywhere.

**Person.** "We" for ALTEN, "our" for its people and assets, "you"/"your" only in internal how-to material (the theme tutorials: *"This explanatory document aims to show you how to use the new 2025 theme"*). Client-facing copy never addresses the reader as "you".

**Casing.** This is the most distinctive rule:
- Slide and document **titles are uppercase**, always (the master sets `cap="all"`).
- Paragraph labels are uppercase too, but smaller and blue: `TITLE OF THE PARAGRAPH`, `OUR POSITIONING`, `OUR OBJECTIVES`, `OUR VISION`.
- Body copy is sentence case.
- Statistic captions are uppercase and letterspaced: `EMPLOYEES`, `IN REVENUE`, `WORLDWIDE COVERAGE`.

**Sentence shapes that recur.** Verb-first capability statements ("We operate in all sectors:", "We carry out complex and highly technical projects…"). Colon-then-list. A rhetorical fragment used exactly once per document as a pivot: *"Our strength? A bottom-up approach where our consultants, in contact with field realities, define R&D priorities."*

**Numbers.** English material uses comma thousands separators and a leading `+` for "more than": `57,400`, `+6,500`, `+30 COUNTRIES`, `€4.10 billion`, `70%`. French-origin material keeps a thin space before `%` (`70 %`) and comma decimals (`4,10`) — match the language you are writing in. Scores are written `85/100`.

**Vocabulary to keep.** Engineering and IT Services; specialists; consultants; Labs; sustainable innovation; Smart Digital; CoC (Centre of Competence); FTE; ramp-up; work package; cluster. Sector names are fixed and always in this order: Aeronautics, Space, Defence, Security & Naval, Automotive, Rail & Mobility, Energy & Environment, Life Sciences & Health, Industrial Equipment & Electronics, Telecoms, Banking, Finance & Insurance, Retail, Services & Medias, Public Services & Government.

**Bilingual by default.** Group decks carry EN and FR end cards side by side (`TO LEARN MORE ABOUT…` / `POUR EN SAVOIR + SUR…`). The French version uses `+` as shorthand for "plus". Templates ship with French shape names and French placeholder text; keep FR and EN copy at the same length so a layout works in both.

**Placeholder conventions in the templates** (useful to recognise, never to ship): `Xxxxxx`, `XX / XX / XXXX`, `XXX FTE`, `Lorem ipsum…`, and red instruction boxes ("Photo can be changed", "Add the client logo") that must be deleted before use.

---

## Visual foundations

**Colour.** One brand colour — navy `#063C67` — plus a blue ladder for hierarchy and a single warm accent. `#043962` is the exact navy used for title *text*; `#1D93C9` carries subtitles, bullets, icons and links; `#7ECBEE` is the on-navy secondary; `#B1DFF4` picks out one word inside a chapter title; `#FFDA65` is the only warm colour and appears almost exclusively as the last stop of the gradient or a small triangular marker. Greys (`#858591`, `#C0C0C8`) are for page numbers and hairlines only. Max two background colours per deck: white and navy.

**The gradient is the signature.** `navy → blue at 48 % → yellow` (`--gradient-brand`), used vertically as a full-slide chapter wash, horizontally as a divider rule, and reduced to `navy → blue` for the reference-project side panel. There is a second, cooler navy wash (`--gradient-navy`) for the "Blue background" master. No other gradients exist — and no purple, no pink, no multi-hue meshes.

**Type.** Two typefaces, three roles. **Arial Black** for every heading, always uppercase, always 90 % leading, zero tracking. **Arial** for subtitles and for the letterspaced lockups (0.15 em / 0.30 em). **Calibri** for all running copy at 9–14 pt. That is the whole system; the theme's own font scheme is left at Office defaults because the masters set faces per shape.

**Layout.** A 6 pt navy rule runs down the left edge of every content slide — it is the system's most recognisable structural mark. Titles sit 21 pt from the left and 10 pt from the top. Content starts at 86 pt. Columns run 3, 4, 6 or 7 up with a 12 pt gap. The A L T E N wordmark is locked to the bottom-right corner at ~42 × 4 pt with the page number to its left in grey. Nothing floats or centres by default; everything is flush left.

**Backgrounds and imagery.** White or navy flat fills, the two gradients, or full-bleed photography. Photography is consistently **cool and blue-dominant**: aerial infrastructure, tunnels and data abstractions, wide mountain landscapes, aircraft, robotics, glass architecture. No warmth, no grain, no duotone, no illustration, no pattern, no texture. Where type sits on a photo it gets a navy scrim graded up from the base (`--scrim-photo`) or a flat 86 % navy panel — never a rounded capsule or a blur.

**The frame device.** A thin (1–3 pt), slightly skewed, three-sided rectangle drawn over imagery in white, yellow or pale blue. One per composition, never filled, never closed on all four sides. It is the only decorative graphic in the system besides the small triangular markers on chapter slides.

**Corners.** Zero. Every rectangle in every master is `prst="rect"`. Cards, images, panels, tables and buttons are all square. The only rounded shapes in the whole source set are two sticker glyphs in the icon pack.

**Borders and rules.** Hairlines at 0.75–1 pt in `#C0C0C8` under table rows and between list items; a 3 pt white rule above cover footers. No card borders — separation comes from shadow or from the grey panel fill.

**Shadow.** Soft, low-contrast, downward. `--shadow-card` (`0 4px 31px rgba(0,0,0,.17)`) on the "3 Columns Shadows" cards; `--shadow-sm` on floating photos. No inner shadows, no coloured glows, no double shadows. Cards on the grey panel background carry no shadow at all.

**Transparency and blur.** Transparency only in the photo scrims and in the 86 % navy overlay. **No backdrop blur anywhere** — it does not exist in the source.

**Motion.** PowerPoint is the native medium, so there is no authored motion: slide changes are cuts and the only moving asset is one looping background video. Screen work should stay quiet — 140–220 ms token-tinted transitions, no lift, no scale, no bounce, no parallax.

**Interaction states** (for the web work this system enables): hover = navy lightened / white tinted by `--hover-tint`; press = darkened by `--press-tint`, no shrink; focus = 2 px white + 2 px blue ring; disabled = 40 % opacity. Links are `#2980B6` underlined, going navy on hover.

---

## Iconography

The Group ships a single, large, purpose-built icon library — `Icons pack - April 2026.potx` — and its own cover slide states the rule: *"All icons are native ppt shapes: can be colored with the Fill Tool, can be enlarged without loss of quality."* There is no icon font, no third-party set (no Lucide, no Font Awesome), no PNG icons, no emoji, and no unicode glyphs used as icons. The only unicode marks in the templates are the `•` bullet and `●` rating dots in tables.

Because the glyphs were vector PowerPoint shapes, I converted the DrawingML geometry directly to SVG — **466 icons**, no redrawing, no substitutions. They live in `assets/icons/<group>/<name>.svg`:

| Group | Count | Contents |
|---|---|---|
| `sectors` | 132 | industries and engineering sub-domains — aeronautics, powertrain, TCMS, MRO, nuclear, pharmaceutical… |
| `project` | 48 | delivery, quality, documents, work packages, process |
| `people` | 46 | roles, HR, competence, recruitment, certification |
| `business` | 44 | growth, cost, finance, strategy, geography |
| `flags` | 40 | 40 countries and regions |
| `digital` | 38 | data, AI, code, UX, hardware |
| `security` | 37 | cyber, cloud, infrastructure, network |
| `illustrative` | 31 | larger multi-colour scene icons |
| `communication` | 28 | channels, UI actions, social (LinkedIn, Xing, Kununu, Glassdoor, TikTok) |
| `commitments` | 14 | CSR, diversity, environment |
| `misc` | 5 | stickers and one-offs |

**Style.** Single-weight thin line drawings, open counters, rounded terminals, drawn on a square field, native colour `#1D93C9`. They are outline-only — there are no filled or duotone variants except the `illustrative` group, which keeps its own multi-colour palette.

**Colouring.** Each mono SVG paints through `--icon-color` with a `#1D93C9` fallback, so a plain `<img>` renders ALTEN blue and the `Icon` component (which inlines the file) can tint it to navy, white or sky. Never recolour an `illustrative` icon.

**If a glyph is missing:** search `assets/icons/` first, then say so and ask. Do not draw a replacement and do not pull one from another library — the line weight will not match.

### Logo
The real logo was extracted from the 2026 A4 template as vector: `assets/logo/alten-logo.svg` (mark + wordmark, wordmark on `currentColor`), plus `-white`, `-navy`, `-black` variants for `<img>` use, `alten-mark.svg`, `alten-wordmark.svg` and the full-colour raster `alten-logo-color.png`. The mark's four colours (`#FAEA27`, `#E52629`, `#1B94D2`, `#020203`) are fixed and are never used for anything else. Clear space is about half the mark's width. On covers the logo always sits in front of the imagery.

---

## Font substitutions — please confirm

No font binaries were provided, and Arial Black, Arial and Calibri cannot be redistributed. Each role is therefore a stack: the real font first, a metric-compatible Google Fonts fallback second.

| Role | Brand font | Fallback loaded | Notes |
|---|---|---|---|
| `--font-display` | Arial Black | **Archivo Black** | Closest free heavy grotesque; slightly narrower than Arial Black, so long uppercase titles will set a touch shorter. |
| `--font-sans` | Arial | **Arimo** | Metrically compatible with Arial. |
| `--font-text` | Calibri | **Carlito** | Metrically compatible with Calibri. |

**Ask:** if ALTEN can share licensed webfont files (or has moved to a licensed brand face), send them and I will replace the fallbacks with real `@font-face` rules.

---

## Components

Reusable primitives, grouped by concern. The source is a document identity, so these are document/presentation primitives rather than app widgets.

**`components/brand/`**
- `Logo` — mark, wordmark or full lockup, four tones.
- `Baseline` — the locked BUILDING TOMORROW'S / WORLD TODAY lockup.
- `AccentBar` — the 6 pt left rule, solid or gradient.
- `FrameDevice` — the thin skewed open frame over imagery.

**`components/slide/`**
- `SlideFrame` — the 16:9 canvas with accent rule, corner wordmark and page number.
- `SlideTitle` — uppercase Arial Black title + blue Arial subtitle at master offsets.
- `ChapterHeading` — oversized sky number + 36 pt white chapter title.

**`components/content/`**
- `SectionLabel` — the small uppercase blue paragraph label.
- `BulletList` — body list with dot, pipe or dash markers.
- `NumberedList` — the 01 / 02 / 03 step list.
- `KeyFigure` — headline statistic with letterspaced caption.
- `Quote` — the scale-only pull quote.
- `ColumnCard` — image-over-text card from the 3/4-column masters.
- `FactChip` — icon over a bold 8 pt label.
- `IconHeading` — navy icon square with an overlapping sky caption.
- `DataTable` — navy header, hairline rows, no zebra.

**`components/media/`**
- `Icon` — a glyph from the ALTEN icon pack.

**`components/ui/`**
- `Button` — see below.

### Intentional additions
- **`Icon`** — a wrapper so the 466 extracted glyphs are addressable by name and tintable. The glyph set is ALTEN's; the wrapper is mine.
- **`Button`** — the sources contain no interactive control at all. Consumers building web or app work need one, so it is assembled strictly from brand tokens (square, navy, Arial Black uppercase, 0.15 em tracking). Flagged in its `prompt.md` as an addition. No other interactive primitive was invented: there is no Input, Select, Switch, Tabs, Dialog, Toast or Avatar here, because nothing in the sources defines them.

---

## Index

```
styles.css                 the single entry point consumers link
tokens/                    colors · typography · spacing · elevation · motion · base
assets/logo/               ALTEN logo, SVG + raster, four tones
assets/brand/              frame-outline devices, "Thank you." lockup
assets/images/             10 brand photographs (cool, blue-dominant)
assets/icons/<group>/      466 SVG glyphs from the April 2026 icon pack
components/<group>/        18 primitives (see above), each with .d.ts + .prompt.md + a card
guidelines/                22 foundation specimen cards (Colors · Type · Spacing · Brand)
slides/                    10 sample slides, one per master type, 1280 × 720
ui_kits/presentation/      interactive 16:9 deck — 8 masters
ui_kits/reference_project/ the 2026 reference-project one-pager, 3 layouts
ui_kits/print_document/    A4 cover, A4 text page, Essentials factsheet
templates/                 3 ready-to-copy starting folders (deck · reference one-pager · A4 doc)
tools/                     the PPTX/DrawingML → SVG extraction scripts used to build this
SKILL.md                   Agent Skills entry point
```

Design System tab groups: **Colors**, **Type**, **Spacing**, **Brand**, **Components**, **Slides**, **Presentation deck**, **Reference project**, **Print document**.

### Templates
Consuming projects can copy a whole starting folder from `templates/`. Each contains a `.dc.html` entry and a `ds-base.js` whose single `base` line points at this design system.

| Template | What it gives you |
|---|---|
| `templates/presentation-deck/` | Six-slide 16:9 deck — cover, summary, key figures, gradient chapter, 3-column content, navy closing |
| `templates/reference-project/` | The dense reference one-pager with the added-value panel and fact strip |
| `templates/a4-document/` | A4 portrait cover + text page spread |

---

## Open questions

1. **CRANFIELD and ESTIA.** The brief named them with ALTEN but supplied no material. Are they co-branded partners on a specific piece, or separate identities that need their own systems? Nothing here represents them.
2. **Fonts.** Can you share licensed webfont files for Arial Black / Arial / Calibri, or the Group's current licensed faces?
3. **The 2026 master file.** `2026 ALTEN Templates Powerpoint.potx` was over the import limit. If you can send a trimmed copy (or just its `ppt/slideLayouts/` folder) I will verify the 2026 master geometry against what is here.
4. **Web presence.** alten.com has its own visual language that no source file covers. If web work is in scope, share a URL set or an export and I will add a web UI kit.
5. **Charts.** The Essentials factsheet's turnover and CSR-score charts have no reusable style definition in the sources. If charts matter, send the intended spec (bar style, axis treatment, colour order) and I will add a chart section.
