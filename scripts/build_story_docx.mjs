/**
 * build_story_docx.mjs — generates docs/SupplyScore_Story.docx
 *
 * "The Number That Disagrees": the SupplyScore narrative, objectives to next steps.
 * Audience: Cranfield, ALTEN management, ALTEN engineering.
 *
 * Every figure in the document was re-derived from the repository on 2026-08-13.
 * Provenance for each one is listed in Appendix A of the generated document.
 *
 * Run from the repository root, with the docx npm package available:
 *   node scripts/build_story_docx.mjs [--out <path>]
 *
 * The docx package is not vendored in this repository (it is a documentation
 * tool, not a runtime dependency). Install it in a scratch directory and point
 * NODE_PATH at it, or run `npm install docx` in a sandbox and run from there.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, TableOfContents,
  Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle, ImageRun, PageBreak,
  PageOrientation, Footer, PageNumber, LevelFormat, convertInchesToTwip,
} = require("docx");

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..");
const DOCS = path.join(REPO, "docs");
const OUT = process.argv.includes("--out")
  ? process.argv[process.argv.indexOf("--out") + 1]
  : path.join(DOCS, "SupplyScore_Story.docx");

/* ------------------------------------------------------------------ brand */
// ALTEN 2025 brand book. Body text is navy, never black. Ochre is a fill
// colour only: the brand forbids ochre text at any size, on any background.
const NAVY = "043962";
const AZURE = "008BD2";
const AZURE_DARK = "176F98";
const OCHRE = "FFDA65";
const OCHRE_PALE = "FFEF86";
const LIGHT = "EBF3F9";
const ICE = "B2E0F5";
const GREY = "8C8C9A";
const RULE = "8D9CAD";
const WHITE = "FFFFFF";
const FONT = "Calibri";
const MONO = "Consolas";

const CONTENT_W = 9638; // A4 (11906 dxa) minus 1134 dxa margins each side

/* ---------------------------------------------------------------- helpers */
const T = (text, o = {}) => new TextRun({
  text, font: o.font || FONT, color: o.color || NAVY, size: o.size || 21,
  bold: !!o.bold, italics: !!o.italics, allCaps: !!o.caps, break: o.break,
});
const B = (text, o = {}) => T(text, { ...o, bold: true });
const I = (text, o = {}) => T(text, { ...o, italics: true });
const M = (text, o = {}) => T(text, { ...o, font: MONO, size: o.size || 19, color: o.color || AZURE_DARK });

/** Body paragraph. Accepts a string or an array of runs. */
const P = (content, o = {}) => new Paragraph({
  children: typeof content === "string" ? [T(content, o)] : content,
  spacing: { after: o.after ?? 140, line: o.line ?? 276 },
  alignment: o.align,
  indent: o.indent,
  keepNext: o.keepNext,
});

const H1 = (text) => new Paragraph({
  children: [T(text, { size: 34, bold: true, color: AZURE })],
  heading: HeadingLevel.HEADING_1,
  spacing: { before: 400, after: 200 },
  keepNext: true,
});
const H2 = (text) => new Paragraph({
  children: [T(text, { size: 25, bold: true, color: NAVY })],
  heading: HeadingLevel.HEADING_2,
  spacing: { before: 300, after: 140 },
  keepNext: true,
});

/** Small eyebrow line above a part title. Dark azure: readable on white. */
const KICKER = (text) => new Paragraph({
  children: [T(text, { size: 17, bold: true, color: AZURE_DARK, caps: true })],
  spacing: { before: 320, after: 40 },
  keepNext: true,
});

/** The recurring beat. One per part; read in sequence they carry the thread. */
const REFRAIN = (text) => new Paragraph({
  children: [I(text, { size: 23, color: AZURE_DARK })],
  spacing: { before: 220, after: 340, line: 300 },
  border: { top: { style: BorderStyle.SINGLE, size: 12, color: AZURE, space: 10 } },
});

const BULLET = (content, o = {}) => new Paragraph({
  children: typeof content === "string" ? [T(content)] : content,
  numbering: { reference: "story-bullets", level: o.level ?? 0 },
  spacing: { after: o.after ?? 80, line: 276 },
});

const CAPTION = (text) => new Paragraph({
  children: [T(text, { size: 17, color: GREY, italics: true })],
  spacing: { after: 240 },
  alignment: AlignmentType.CENTER,
});

/**
 * Boxed panel. Two flavours, both used throughout:
 *   "mechanism" (pale blue, engineering: the formula and the rejected alternative)
 *   "evidence"  (pale ochre, Cranfield: hypothesis, threshold, verdict, scope)
 */
function PANEL(label, kind, children) {
  const fill = kind === "evidence" ? OCHRE_PALE : LIGHT;
  const edge = kind === "evidence" ? OCHRE : AZURE;
  return new Table({
    columnWidths: [CONTENT_W],
    width: { size: CONTENT_W, type: WidthType.DXA },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 2, color: fill },
      bottom: { style: BorderStyle.SINGLE, size: 2, color: fill },
      right: { style: BorderStyle.SINGLE, size: 2, color: fill },
      left: { style: BorderStyle.SINGLE, size: 24, color: edge },
      insideHorizontal: { style: BorderStyle.NONE, size: 0, color: fill },
      insideVertical: { style: BorderStyle.NONE, size: 0, color: fill },
    },
    rows: [new TableRow({
      cantSplit: true, // a panel that breaks across pages reads as an empty box
      children: [new TableCell({
        width: { size: CONTENT_W, type: WidthType.DXA },
        shading: { type: ShadingType.CLEAR, fill, color: "auto" },
        margins: { top: 160, bottom: 160, left: 220, right: 200 },
        children: [
          new Paragraph({
            children: [T(label, { size: 17, bold: true, color: AZURE_DARK, caps: true })],
            spacing: { after: 90 },
          }),
          ...children,
        ],
      })],
    })],
  });
}

/** Data table. Header row navy with ice text; body ruled in brand grey-blue. */
function TABLE(headers, rows, widths, o = {}) {
  const total = widths.reduce((a, b) => a + b, 0);
  const scaled = widths.map((w) => Math.round((w / total) * CONTENT_W));
  scaled[scaled.length - 1] = CONTENT_W - scaled.slice(0, -1).reduce((a, b) => a + b, 0);

  const cell = (content, i, opts = {}) => new TableCell({
    width: { size: scaled[i], type: WidthType.DXA },
    shading: { type: ShadingType.CLEAR, fill: opts.fill || WHITE, color: "auto" },
    margins: { top: 70, bottom: 70, left: 110, right: 110 },
    verticalAlign: "center",
    children: [new Paragraph({
      children: typeof content === "string"
        ? [T(content, { size: opts.size || 19, bold: opts.bold, color: opts.color || NAVY,
                        font: opts.mono ? MONO : FONT })]
        : content,
      spacing: { after: 0, line: 250 },
      alignment: opts.align,
      // keepNext on every row but the last pulls the whole table onto one page,
      // so a table whose last row is the punchline never gets orphaned.
      keepNext: opts.keepNext,
    })],
  });

  const bodyRows = rows.map((r, ri) => new TableRow({
    cantSplit: true,
    children: r.map((cnt, i) => {
      const opts = { fill: ri % 2 ? LIGHT : WHITE, keepNext: o.keepTogether && ri < rows.length - 1 };
      if (o.mono && o.mono.includes(i)) opts.mono = true;
      if (o.bold && o.bold.includes(i)) opts.bold = true;
      return cell(cnt, i, opts);
    }),
  }));

  const headerRow = o.noHeader ? [] : [new TableRow({
    tableHeader: true,
    cantSplit: true,
    children: headers.map((h, i) =>
      cell(h, i, { fill: NAVY, color: ICE, bold: true, size: 18, keepNext: o.keepTogether })),
  })];

  return new Table({
    columnWidths: scaled,
    width: { size: CONTENT_W, type: WidthType.DXA },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 4, color: RULE },
      bottom: { style: BorderStyle.SINGLE, size: 4, color: RULE },
      left: { style: BorderStyle.NONE, size: 0, color: RULE },
      right: { style: BorderStyle.NONE, size: 0, color: RULE },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 2, color: RULE },
      insideVertical: { style: BorderStyle.NONE, size: 0, color: RULE },
    },
    rows: [...headerRow, ...bodyRows],
  });
}

/** Figure. maxW/maxH in px; aspect preserved. Type must match real bytes. */
function FIG(relPath, caption, maxW = 620, maxH = 400) {
  const abs = path.join(DOCS, relPath);
  const buf = fs.readFileSync(abs);
  const isJpeg = buf[0] === 0xff && buf[1] === 0xd8;
  const dim = isJpeg ? jpegSize(buf) : pngSize(buf);
  const scale = Math.min(maxW / dim.w, maxH / dim.h, 1);
  return [
    new Paragraph({
      children: [new ImageRun({
        data: buf,
        type: isJpeg ? "jpg" : "png",
        transformation: { width: Math.round(dim.w * scale), height: Math.round(dim.h * scale) },
      })],
      alignment: AlignmentType.CENTER,
      spacing: { before: 200, after: 90 },
      keepNext: true,
    }),
    CAPTION(caption),
  ];
}

function pngSize(b) { return { w: b.readUInt32BE(16), h: b.readUInt32BE(20) }; }
function jpegSize(b) {
  let i = 2;
  while (i < b.length) {
    if (b[i] !== 0xff) { i++; continue; }
    const marker = b[i + 1];
    if (marker >= 0xc0 && marker <= 0xcf && ![0xc4, 0xc8, 0xcc].includes(marker)) {
      return { h: b.readUInt16BE(i + 5), w: b.readUInt16BE(i + 7) };
    }
    i += 2 + b.readUInt16BE(i + 2);
  }
  throw new Error("no JPEG SOF marker");
}

/* ------------------------------------------------------------------ cover */
function coverBand() {
  return new Table({
    columnWidths: [CONTENT_W],
    width: { size: CONTENT_W, type: WidthType.DXA },
    borders: {
      top: { style: BorderStyle.NONE, size: 0, color: NAVY },
      bottom: { style: BorderStyle.NONE, size: 0, color: NAVY },
      left: { style: BorderStyle.NONE, size: 0, color: NAVY },
      right: { style: BorderStyle.NONE, size: 0, color: NAVY },
      insideHorizontal: { style: BorderStyle.NONE, size: 0, color: NAVY },
      insideVertical: { style: BorderStyle.NONE, size: 0, color: NAVY },
    },
    rows: [new TableRow({
      children: [new TableCell({
        width: { size: CONTENT_W, type: WidthType.DXA },
        shading: { type: ShadingType.CLEAR, fill: NAVY, color: "auto" },
        margins: { top: 700, bottom: 700, left: 420, right: 420 },
        children: [
          new Paragraph({
            children: [T("ALTEN  ·  Direction Ingénierie Numérique  ·  R&D DISCO",
              { size: 17, bold: true, color: ICE, caps: true })],
            spacing: { after: 320 },
          }),
          new Paragraph({
            children: [T("The Number That Disagrees", { size: 60, bold: true, color: WHITE })],
            spacing: { after: 160 },
          }),
          new Paragraph({
            children: [T("SupplyScore: building a supply chain instrument that can prove its own author wrong",
              { size: 26, color: ICE })],
            spacing: { after: 260, line: 320 },
          }),
          new Paragraph({
            children: [T("From the objective, through what was built and what it measured, to what comes next.",
              { size: 21, color: ICE, italics: true })],
            spacing: { after: 0, line: 300 },
          }),
        ],
      })],
    })],
  });
}

/* --------------------------------------------------------------- document */
const doc = new Document({
  creator: "John Hoarau",
  title: "The Number That Disagrees — SupplyScore",
  description: "The SupplyScore story: objectives, construction, measurement, limits and next steps.",
  features: { updateFields: true },
  styles: {
    default: {
      document: { run: { font: FONT, size: 21, color: NAVY } },
    },
    paragraphStyles: [
      { id: "Title", name: "Title", basedOn: "Normal", next: "Normal",
        run: { font: FONT, size: 60, bold: true, color: NAVY } },
    ],
  },
  numbering: {
    config: [{
      reference: "story-bullets",
      levels: [
        { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 360, hanging: 240 } },
                   run: { color: AZURE, font: FONT } } },
        { level: 1, format: LevelFormat.BULLET, text: "◦", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 240 } },
                   run: { color: AZURE, font: FONT } } },
      ],
    }],
  },
  sections: [{
    properties: {
      page: {
        size: { orientation: PageOrientation.PORTRAIT },
        margin: { top: 1134, bottom: 1134, left: 1134, right: 1134 },
      },
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.RIGHT,
          border: { top: { style: BorderStyle.SINGLE, size: 4, color: RULE, space: 8 } },
          children: [
            T("SupplyScore  ·  The Number That Disagrees  ·  ", { size: 16, color: GREY }),
            new TextRun({ children: [PageNumber.CURRENT], size: 16, color: GREY, font: FONT }),
          ],
        })],
      }),
    },
    children: buildBody(),
  }],
});

/* ===================================================================== body */
function buildBody() {
  const c = [];

  /* -------------------------------------------------------------- cover */
  c.push(coverBand());
  c.push(P(" ", { after: 400 }));
  c.push(TABLE(
    ["", ""],
    [
      ["Author", "John Hoarau, R&D internship, ALTEN Direction Ingénierie Numérique"],
      ["Date", "13 August 2026"],
      ["Version", "1.0"],
      ["Audience", "Cranfield University · ALTEN management · SupplyScore engineering team"],
      ["Subject", "SupplyScore v2.0.0, the AERIS demonstration and the HÉLIOS validation campaign"],
      ["Status", "Evidence level T1 reached. T3 built, frozen and unrun. Four defects open and specified."],
      ["Figures", "Every number in this document was re-derived from the repository on 13 August 2026. Provenance in Appendix A."],
    ],
    [1600, 8038],
    { bold: [0], noHeader: true },
  ));
  c.push(new Paragraph({ children: [new PageBreak()] }));

  /* ---------------------------------------------------------------- TOC */
  c.push(H1("Contents"));
  c.push(new TableOfContents("Contents", { hyperlink: true, headingStyleRange: "1-2" }));
  c.push(new Paragraph({ children: [new PageBreak()] }));

  /* ---------------------------------------------------- executive summary */
  c.push(H1("Executive summary"));

  c.push(P([
    T("Supply chain dashboards measure the world. None of them measures the distance between the world and what people say about it. That distance is where ruptures hide: a line stops while every indicator is green, because the people watching the indicators had already stopped believing them. "),
    B("SupplyScore measures that distance."),
  ]));

  c.push(P([
    T("For each node of a supplier network it computes two urgencies. "),
    B("Ud"), T(", declared urgency, comes from a weekly multi criteria questionnaire answered by the person responsible. "),
    B("Ur"), T(", real urgency, is computed from six blocks of operational indicators. Their confrontation gives an adequacy score "),
    B("A"), T(" and two pathologies: false urgency "),
    M("F = [Ud − Ur]+"), T(" (crying wolf) and hidden risk "),
    M("H = [Ur − Ud]+"), T(" (silent danger). The penalty is deliberately asymmetric, because the two errors do not cost the same."),
  ]));

  c.push(PANEL("What the numbers say, in one line", "mechanism", [
    P([
      T("At equal maximum divergence, panic scores "), B("A = 29.3"),
      T(" and blindness scores "), B("A = 0"),
      T(". Under declaring is penalised 2.25 times more than over declaring, using the loss aversion coefficient measured by Kahneman and Tversky, not a value tuned in house."),
    ], { after: 0 }),
  ]));

  c.push(H2("What was built"));
  c.push(P("SupplyScore v2.0.0 is a working, self contained digital twin and serious game: 86 Python modules across 13 packages, 1 974 automated tests, a blocking coverage gate at 90 per cent, thirteen application pages, and an audit trail that makes every business write traceable to an operator, a week and a rule. It is not a prototype. It runs, it is documented formula by formula against its own source code, and it has been exercised end to end on two scenarios."));

  c.push(H2("What was measured"));
  c.push(P("The HÉLIOS campaign replayed the 2020 to 2022 global semiconductor shortage on authentic public data, with six falsifiable hypotheses frozen before any data existed. The instrumented replay produced a result that is uncomfortable and useful in equal measure:"));
  c.push(BULLET([B("The forecast layer ranks, but it does not calibrate."), T(" Discrimination is real (AUC 0.736 at one turn, 0.654 at four turns against the frozen target definition), yet the Brier skill score is negative at every horizon. The ordering is informative. The probability attached to it is not.")]));
  c.push(BULLET([B("Four structural defects were found, and each one is mechanical and general."), T(" The most serious: the block that produces the probability of missing a milestone never sees the events that would cause one.")]));
  c.push(BULLET([B("The project climbed the evidence ladder out of order."), T(" It tested on a historical replay before the model had ever been trained. That sequencing error is now named, and the correction is specified.")]));

  c.push(H2("Where it stands, and what the next increment buys"));
  c.push(P("Stated plainly: SupplyScore has reached evidence level T1, the historical replay at T3 was attempted early and returned defects rather than validation, and the human campaign that would properly establish T3 is built, frozen and waiting for eight consultants and fifteen working days. The causal layer that would reach T4 currently reports a failure on its own validation battery, and the pipeline refuses to publish it."));
  c.push(P([
    T("That last sentence is the argument of this document. A system that withholds its own output when the output does not pass is worth more than a system that always has an answer. The next increment turns a score into a decision object: "),
    I("risk without action 29 per cent, with action 14 per cent, probability of execution 85 per cent, net value between minus 2 and plus 41 thousand euros, evidence level weak to medium."),
    T(" That contract is already written. What stands between here and there is four named repairs and one campaign."),
  ]));

  c.push(new Paragraph({ children: [new PageBreak()] }));

  /* ============================================================= PART 1 */
  c.push(KICKER("Part 1"));
  c.push(H1("The green dashboard and the stopped line"));

  c.push(P("A production line has stopped. In the room where the decision to escalate should have been taken an hour earlier, the supply chain dashboard is green. Nobody has misread it. Nobody has ignored it. The dashboard is reporting exactly what it was built to report, and the line has stopped anyway."));

  c.push(P("Ask the people in that room what happened and two answers come back, in every industry, in almost the same words. The first: everything has been marked urgent for months, so nothing is. The second: the one thing that actually broke was the thing nobody flagged, because the person closest to it was managing it, expected to manage it, and did not want to be the one crying wolf again."));

  c.push(P("These are two distinct failures and they are usually treated as one, called them both \"communication problems\", and left to management culture. They are not culture. They are measurable quantities, and they have opposite signs."));

  c.push(PANEL("Mechanism: the two pathologies", "mechanism", [
    P([M("F = [Ud − Ur]+"), T("   false urgency. What is declared exceeds what the data supports. Cost: premium transport saturated, buffers paid for nothing, and every subsequent alert believed a little less.")]),
    P([M("H = [Ur − Ud]+"), T("   hidden risk. What the data supports exceeds what is declared. Cost: the rupture arrives without a warning, at the moment when the options for avoiding it have already expired.")], { after: 60 }),
    P([
      T("The two are exclusive by construction: a node has one or the other, never both. That is what makes them usable as a diagnosis rather than a mood."),
    ], { after: 0 }),
  ]));

  c.push(P("An operations manager reading this already knows which of the two costs more, and the model agrees. Panic is expensive and recoverable: money is spent, capacity is wasted, and the situation remains under control. Silence is cheap and irreversible: nothing is spent, and the window in which action was still possible closes unobserved. So the score cannot be symmetric."));

  c.push(P([
    T("SupplyScore penalises under declaration 2.25 times more heavily than over declaration, with a curvature exponent of 0.88. Both constants are taken from the cumulative Prospect Theory measurements of Tversky and Kahneman. The consequence is the number that carries this whole document: for the same absolute divergence of 0.5 between declared and real, panic scores "),
    B("A = 53.1"), T(" and silence scores "), B("A = 21.1"),
    T(". At the extreme, a node that declares nothing while its indicators saturate scores "),
    B("zero"), T(", while a node that panics with nothing behind it still scores 29.3."),
  ]));

  c.push(PANEL("The habit this document keeps: every constant carries its status", "evidence", [
    P("A model is only as defensible as its weakest unlabelled constant. Three statuses are used throughout, and they are never blurred:"),
    BULLET([B("Measured by the literature."), T("  λ = 2.25 and α = 0.88 (Tversky and Kahneman 1992). These are empirical findings, cited, not fitted here.")]),
    BULLET([B("Domain standard."), T("  The consistency threshold CR < 0.10 and Saaty's random index table. Conventions of the field, adopted as conventions and not defended as truths.")]),
    BULLET([B("Governance choice, recalibrable."), T("  The smoothing ρ = 0.3, the Bayesian prior weight of 26 pseudo observations, the arc coefficients γ and β. These are decisions. They are documented as decisions and the campaign exists partly to revise them.")], { after: 0 }),
  ]));

  c.push(REFRAIN("The dashboard was not wrong. It was measuring the wrong thing."));

  /* ============================================================= PART 2 */
  c.push(KICKER("Part 2"));
  c.push(H1("The empty square on the map"));

  c.push(P("Before building anything, the obvious question: surely someone measures this already. The answer, after a survey of both the academic literature and the commercial market, is more interesting than a simple no."));

  c.push(P("Everyone measures a great deal. The ripple effect literature models how a disruption propagates across supplier tiers. Markov and dynamic Bayesian network formulations estimate disruption probabilities over time. Bayesian networks map supply chain risk factors onto outcomes. Simchi-Levi's time to recovery and time to survive stress tests quantify exposure without needing a probability at all. Commercially, Everstream, Resilinc and Interos map multi tier networks and score risk continuously, at a scale no research prototype approaches."));

  c.push(P("Laid side by side, all of that work fills one column and leaves another empty."));

  c.push(TABLE(
    ["Approach", "Scores physical reality", "Scores human declaration", "Scores the gap"],
    [
      ["Ripple effect models (Ivanov et al.)", "Yes", "No", "No"],
      ["Markov / dynamic Bayesian disruption models", "Yes", "No", "No"],
      ["Bayesian supply chain risk networks", "Yes", "No", "No"],
      ["TTR / TTS stress tests (Simchi-Levi, MIT)", "Yes", "No", "No"],
      ["Everstream, Resilinc, Interos", "Yes", "No", "No"],
      ["SupplyScore", "Yes", "Yes", "Yes"],
    ],
    [3400, 2100, 2100, 2038],
    { bold: [0], keepTogether: true },
  ));
  c.push(CAPTION("The scan behind the research question. Every established approach scores the world; the declared-versus-measured column is the one nobody occupies."));

  c.push(P("The empty column is not an oversight by the field. It is a consequence of where the data has historically come from. Risk platforms ingest telemetry, financial filings, weather and news, all of it about the world. The declaration, the human judgement of urgency, is not usually recorded as a quantity at all. It exists in emails, in escalation calls, in the tone of a weekly meeting. To subtract it from anything, you first have to make it a number, weekly, from the person who holds the judgement, in a way that resists both fabrication and fatigue."));

  c.push(H2("The research question"));
  c.push(PANEL("Research question", "evidence", [
    P([
      T("Is the gap between the urgency declared by operators and the urgency computable from operational data "),
      B("measurable"), T(", "), B("propagable"), T(" across a multi tier network, and "),
      B("exploitable"), T(" for detecting two distinct pathologies, false urgency and hidden risk?"),
    ]),
    P([
      B("Working hypothesis. "),
      T("The danger is not only in the indicators. It is in the misalignment between the indicators and the perception of them."),
    ], { after: 0 }),
  ]));

  c.push(H2("What is not claimed"));
  c.push(P("Credibility here is bought by subtraction, so the disclaimers come before the claims rather than after them."));
  c.push(BULLET([B("The propagation mathematics is not novel."), T(" The upstream and downstream formulations are a classical survival product structure, applied in one deterministic pass. They are used because they are correct and bounded, not because they are new.")]));
  c.push(BULLET([B("AHP is not novel, and is heavily criticised."), T(" It is used for a narrow purpose, with four fixed criteria and a blocking consistency check, precisely because the criticisms of AHP at larger criterion counts are well founded.")]));
  c.push(BULLET([B("Neither is Prospect Theory, PROMETHEE II, Monte Carlo PERT, nor noisy-OR aggregation."), T(" Every method in the system is established. The contribution is the quantity they are assembled to compute, and the discipline imposed on the assembly.")]));

  c.push(P("What is claimed is narrower and, if it holds, more useful: that the declared-to-real gap can be elicited weekly without exhausting the operator, propagated coherently across a network, decomposed exactly enough to be defended in front of the person it describes, and tested against recorded outcomes rather than asserted."));

  c.push(REFRAIN("Everyone scores the world. Nobody scores the gap between the world and what we say about it."));

  /* ============================================================= PART 3 */
  c.push(KICKER("Part 3"));
  c.push(H1("Building the instrument"));

  c.push(P("A design meeting, early. Six families of indicators have been agreed as the basis of real urgency: time, capacity, equipment performance, risk, cost and carbon. Each produces a number between 0 and 1. The obvious next step is to average them, weight the average, and move on."));

  c.push(P("Then somebody works a case. A supplier has a total material rupture: its flow indicator is saturated at 1.0. Its other five blocks are healthy, around 0.05, because nothing else is wrong yet. The weighted average returns 0.17. On a dashboard sorted by urgency, that node sits in the calm two thirds of the list. Its line is stopped."));

  c.push(P("The arithmetic disagreed with the factory floor, so the arithmetic changed."));

  c.push(PANEL("Mechanism: why probabilistic OR, and not a mean", "mechanism", [
    P([M("Ur_local = 1 − Π_m (1 − u_m)^ω_m")]),
    P("Read as a smoke detector array. Six detectors, any one of which saturating is sufficient to sound the alarm, because in manufacturing one bottleneck stops the whole line regardless of how well everything else is running. The same total rupture that a mean scored at 0.17 is scored at 1.0 here."),
    P([
      B("Rejected alternative: the weighted mean. "),
      T("Rejected by the number 0.17, on a case where the line was physically stopped."),
    ]),
    P([
      B("A missing block is ignored, never imputed. "),
      T("If a block has no indicators, it returns nothing and the remaining weights renormalise. It is not counted as zero (falsely reassuring) nor as one (falsely alarming). Absence of measurement is not evidence, in either direction."),
    ], { after: 0 }),
  ]));

  c.push(...FIG("BST_DISCO_JH_2026/Images/4.Operations/causal_tree_blocks.png",
    "The six indicator blocks feeding real urgency. Each is computed independently, then combined by weighted probabilistic OR so that a single saturated block is sufficient.", 430, 400));

  c.push(H2("Declared urgency: making a judgement into a number that resists fatigue"));

  c.push(P("The harder half of the instrument is the human half. Asking someone to type an urgency between 0 and 100 every week produces a number that drifts with mood, anchors on last week, and inflates over time. So the questionnaire never asks for the urgency directly. It asks for comparisons."));

  c.push(P("Four criteria, fixed and never expanded: operational impact, time window, downstream dependencies, and recoverability. The respondent compares them in pairs on Saaty's scale, then scores each one. The declared urgency is the weighted combination. Between those two steps sits the guard rail that makes the whole thing usable: a consistency ratio."));

  c.push(PANEL("Mechanism: the consistency guard, and one honest approximation", "mechanism", [
    P([
      T("If a respondent claims A is much more important than B, B much more important than C, and C more important than A, the comparison matrix is internally contradictory. The consistency ratio detects it and the questionnaire "),
      B("refuses the submission"), T(" at CR ≥ 0.10, pointing at the most contradictory pair. This is what stops the weekly ritual from decaying into clicking."),
    ]),
    P([
      B("Four criteria, not more. "),
      T("AHP consistency degrades beyond roughly seven criteria. The richer weighting, over the six blocks of real urgency, is done with the Fuzzy Best-Worst Method instead, which needs 2n−3 comparisons rather than n(n−1)/2."),
    ]),
    P([
      B("The approximation, stated plainly. "),
      T("The priority vector is computed by the classical normalised column mean, not by an exact Perron eigenvector. On a perfectly consistent matrix the two coincide exactly. Under the CR < 0.10 threshold the per component discrepancy is of order 10⁻², below the quantisation noise of Saaty's own discrete 1 to 9 scale. Matrices where the discrepancy would be large are precisely the ones the threshold rejects. Switching to exact power iteration would be a change of about ten lines; the current choice is a documented trade off, not an oversight."),
    ], { after: 0 }),
  ]));

  c.push(H2("Propagation: the need descends, the risk climbs"));

  c.push(P("A node's urgency is not its own. A customer's declared need pulls on its suppliers, attenuated at each arc by a coefficient γ. A deep supplier's physical risk contaminates its customers, scaled at each arc by a coefficient β. The two signals travel in opposite directions along the same directed acyclic graph, and the two passes are what turn a set of per node scores into a network diagnosis."));

  c.push(...FIG("BST_DISCO_JH_2026/Images/4.Operations/urgency_propagation.png",
    "Declared urgency propagates downstream from the final customer; real urgency propagates upstream from deep suppliers. Backup arcs are deliberately inert: they document an alternative without contributing risk.", 400, 380));

  c.push(H2("What makes a score defensible rather than merely correct"));

  c.push(P("A correct score that nobody can interrogate is a correct score that nobody uses. The larger part of the engineering effort went not into the formulas but into making every number answerable, and this is the part that is hardest to see in a demonstration."));

  c.push(BULLET([B("One write path, enforced by the build. "), T("Every business write goes through a single mutation service that validates, diffs, and records an audit line inside the same transaction as the change itself. There cannot exist a committed change without its trace. The invariant is not a convention: the local CI greps the user interface layer for direct write calls and fails the build if it finds one.")]));
  c.push(BULLET([B("Exact decompositions, not attributions. "), T("Declared urgency decomposes additively into per criterion contributions that sum to it with no residual. Real urgency decomposes exactly in log survival space, so each block's share of the result is a fact rather than an estimate. This is what allows the explanation page to answer \"why is my score 46.5\" term by term, in front of the person contesting it.")]));
  c.push(BULLET([B("History that cannot be edited. "), T("Audit log, urgency history, indicator snapshots, weekly reviews and decisions are append only by construction, including in the administrative view. The promise of a defensible history collapses the moment one of those tables becomes editable.")]));
  c.push(BULLET([B("Data integrity taken seriously. "), T("Databases run in write ahead logging mode, backups use the native SQLite backup API so a copy is consistent even with the application running, every archive is integrity checked before being written, and a corrupt database stops startup with a dedicated exit code rather than being silently opened.")]));

  c.push(...FIG("BST_DISCO_JH_2026/Images/4.Operations/explainability_waterfall.png",
    "The two exact decompositions behind any score. Declared urgency splits into per criterion contributions; real urgency splits into per block contributions. Both sum to their total with no residual, which is what allows a contested score to be answered term by term.", 470, 380));

  c.push(REFRAIN("We changed the mathematics because the arithmetic disagreed with the factory floor."));

  /* ============================================================= PART 4 */
  c.push(KICKER("Part 4"));
  c.push(H1("First contact: the AERIS programme"));

  c.push(P("An instrument that has only ever been run on unit tests has not yet been run. AERIS is the first full exercise: a fictional cargo drone programme, ten named companies across four supplier tiers from final assembly in Toulouse to lithium in Chile, played over eight simulated weeks with scripted incidents and a human style decision recorded each week."));

  c.push(P("The week eight state is worth reading carefully, because it is the first time the instrument said something that a conventional dashboard could not."));

  c.push(TABLE(
    ["Node", "Ud declared", "Ur real", "A", "F false urgency", "H hidden risk"],
    [
      ["aeris-oem (final assembly)", "0.84", "0.79", "93.0", "0.04", "0.00"],
      ["mecanika", "0.75", "0.69", "90.7", "0.06", "0.00"],
      ["voltech", "0.75", "0.80", "83.3", "0.00", "0.05"],
      ["accupol (backup supplier)", "0.41", "0.17", "72.7", "0.24", "0.00"],
      ["lithium-andes", "0.60", "0.24", "62.3", "0.36", "0.00"],
      ["minalliages", "0.56", "0.19", "62.0", "0.37", "0.00"],
      ["celltech", "0.69", "0.30", "61.0", "0.38", "0.00"],
      ["ferralu", "0.68", "0.27", "59.3", "0.41", "0.00"],
      ["composites-atl", "0.62", "0.17", "56.4", "0.45", "0.00"],
      ["powerchip", "0.76", "1.00", "46.5", "0.00", "0.24"],
    ],
    [3000, 1330, 1330, 1000, 1600, 1378],
    { bold: [0], keepTogether: true },
  ));
  c.push(CAPTION("AERIS at week 8, reproduced from scripts/demo_scenario.py (seed 42) on 13 August 2026. Simulated data, for demonstration only."));

  c.push(P("Six nodes carry a false urgency above 0.1. They are declaring far more urgency than their indicators support: the programme's anxiety has spread outward and everyone is shouting. Exactly one node carries a material hidden risk, and it is the one at the bottom of the table. PowerChip's indicators are saturated at 1.00 while its operator declares 0.76, and it is the only node in the network whose declaration sits below its reality by any meaningful margin."));

  c.push(P("Everyone panics except the one who should."));

  c.push(...FIG("presentation/screenshots/05-dashboard.png",
    "The AERIS dashboard at week 8. The network graph is coloured by adequacy; the node table carries the declared, real, A, F and H columns. Simulated data.", 620, 330));

  c.push(H2("The question that decides whether the tool survives contact"));

  c.push(P("A serious game produces an argument within about ten minutes of the first bad score. The player whose node is at 46.5 wants to know why, and \"the model says so\" ends the exercise and the credibility of the tool with it."));

  c.push(P("So the score defends itself. The explanation page for PowerChip states the cause in plain language at the top (the deadline has been passed, so the time block is forced to 1), decomposes declared urgency criterion by criterion from the operator's own last questionnaire with its consistency ratio shown, separates how much of the declared need is locally generated against how much is pulled in by downstream customers through the arc coefficients, prints the penalty equation with this node's actual values substituted in, and ends with the audit journal: who wrote what, when, from which source, under which event."));

  c.push(...FIG("presentation/screenshots/13-explication-pleine-page.png",
    "The explanation view for a contested score: cause, criterion by criterion decomposition, local versus propagated share, the instantiated equation, and the audit trail. Simulated data.", 380, 430));

  c.push(REFRAIN("The score's job is not to be believed. It is to be checkable."));

  /* ============================================================= PART 5 */
  c.push(KICKER("Part 5"));
  c.push(H1("HÉLIOS: meeting a real crisis"));

  c.push(P("AERIS proved the instrument works on a scenario built to exercise it, which is a weak claim by design. The interesting question is what happens when the physical side is fed by data nobody wrote for the occasion, and the human side by people who do not know what they are being shown."));

  c.push(P("HÉLIOS replays the global semiconductor shortage from September 2020 to February 2022. Eight fictional companies, each anchored on a documented real actor, deliver two observation satellites for an institutional customer. Eighteen turns, one turn representing one real month. Real urgency is fed by authentic public series (INSEE industrial production and business failures, WSTS worldwide semiconductor billings, US producer price data) plus twelve calibrated driver events pinned to dated events of the real crisis: the Texas freeze, the Renesas fire, the Suez blockage, the Taiwan drought, the Malaysian back end lockdowns, the bullwhip of autumn 2021, the polysilicon price spike."));

  c.push(P("The participants are told none of that. They receive a narrative cover: a space programme, a recurring programme director whose emails grow tenser, a supplier vice president whose answers on allocation serve as the barometer of the crisis. The reveal happens at the debrief, together with the control question: at which turn did you recognise it?"));

  c.push(...FIG("BST_DISCO_JH_2026/Images/4.Operations/campaign_network.png",
    "The HÉLIOS network: eight nodes across six tiers, seven nominal arcs and one deliberately inert backup arc, with the propagation coefficients on each link.", 500, 400));

  c.push(H2("The part that matters is not the scenario. It is the protocol."));

  c.push(P("A scenario can be tuned until it produces the desired result, and everybody involved knows it. The engineering that makes HÉLIOS worth reporting is the set of constraints placed on the experimenter, before the experimenter could know what the data would say."));

  c.push(BULLET([B("Pre-registration, then freezing. "), T("Six hypotheses, each with a numeric threshold and an explicit refutation criterion, were written down and the protocol frozen at day five, before the first real turn. The analysis code implementing each test was written before any data existed. The verdicts are therefore computed by code that could not have been chosen to suit them.")]));
  c.push(BULLET([B("A null baseline imposed on itself. "), T("The hidden risk signal is scored against a deliberately naive detector, \"local real urgency above 0.5\", on exactly the same grid. If the sophisticated signal does not beat the crude one, the adequacy score adds nothing, and the document has to say so.")]));
  c.push(BULLET([B("Structural, not procedural, blinding on the future. "), T("The briefing generator reads only the prepared files of turns up to and including the current one. Future data is not in memory at generation time. The exclusion is a property of the code, not an instruction to a careful operator.")]));
  c.push(BULLET([B("Two placebo briefings. "), T("One participant at turn nine and another at turn fifteen receive a plausible alternative continuation, a de escalation instead of a worsening, with identical underlying data and only the narrative changed. If their declaration follows the placebo, the measurement is reflecting the material supplied rather than a memory of the real crisis.")]));
  c.push(BULLET([B("A frozen, hashed data pack, and one dataset rejected. "), T("All prepared series are fixed by SHA-256 before the first turn. During acquisition, one third party logistics dataset failed the authenticity check and was discarded rather than used with a caveat.")]));

  c.push(PANEL("The six pre-registered hypotheses", "evidence", [
    P("Each states an observable result, a numeric prediction and the threshold below which it is refuted. The consequences of failure were fixed in advance too, which is the part that is usually missing.", { after: 0 }),
  ]));

  c.push(TABLE(
    ["#", "Hypothesis", "Prediction, fixed in advance", "If it fails"],
    [
      ["HA1", "Cognitive latency: declaration follows reality by at least one cycle", "Cross correlation maximal at lag ≥ 1 for at least 5 of 8 nodes", "Operators need no debiasing; the adequacy layer is redundant"],
      ["HA2", "Early detection: hidden risk rises on the crisis origin before it is public", "H > 0.3 on the foundry at some turn in T6 to T12", "Hidden risk is descriptive, not decision support"],
      ["HA3", "Structural criticality: shock simulation ranks the true bottleneck first", "Foundry ranked first among deep suppliers on ≥ 80 % of informative turns", "Network prioritisation cannot be used operationally"],
      ["HA4", "Predictive validity: H predicts recorded adverse outcomes", "Precision and recall both > 0.5 at H ≥ 0.5, four turn horizon", "Same as HA2: descriptive only"],
      ["HA5", "Urgency contagion: untouched nodes still escalate on press turns", "Mean change in declaration positive and above calm turns", "No network level contagion to correct"],
      ["HA6", "Perception hysteresis: declaration falls more slowly than reality", "Declaration decay slope below 50 % of reality's", "Over declaration self corrects; the 2.25 asymmetry must be recalibrated"],
    ],
    [700, 2300, 3600, 3038],
    { bold: [0], keepTogether: true },
  ));
  c.push(CAPTION("The pre-registered register, frozen before the first turn. Source: projects/simu_semiconducteurs/PROTOCOLE.md §5."));

  c.push(REFRAIN("We wrote down how we could be wrong before we could know whether we were."));

  /* ============================================================= PART 6 */
  c.push(KICKER("Part 6"));
  c.push(H1("What actually happened"));

  c.push(P("Three distinct things have been run, and they prove three different amounts. Conflating them would be the easiest way to overstate this project, so they are reported separately, each with an explicit statement of what it does not establish."));

  c.push(H2("Layer one: the mechanical replay"));

  c.push(P("Nineteen turns played end to end with synthetic respondents, producing 152 node-turn observations, with injection, weekly decay, milestone updates, event impacts, propagation, criticality ranking, snapshots, backups and the full analysis chain running unattended at two turns per day."));

  c.push(P("All six hypotheses came back not confirmed. That result is close to meaningless as science and valuable as engineering, and the distinction has to be stated: the synthetic declaration is anchored on the node's own local real urgency, so it cannot lag reality, cannot durably under state it, and cannot over react to a newspaper. HA1, HA5 and HA6 are not interpretable on this data by construction, and HA2 and HA4 are mechanically constrained by the same anchoring."));

  c.push(PANEL("What the mechanical replay does and does not prove", "evidence", [
    P([B("Establishes: "), T("the campaign machinery runs unattended at the required cadence; the guard rails hold (turn idempotence, structural anti lookahead, verifiable pack freezing, placebos generated at the right turns); the scenario is mechanically plausible, with the expected bottleneck saturating at the expected turns; the analysis chain produces the pre registered verdicts without manual intervention.")]),
    P([B("Establishes nothing about: "), T("cognitive latency, contagion, hysteresis, early detection or predictive validity. A synthetic respondent has no psychology to measure.")]),
    P([B("Useful figure: "), T("the null baseline scored precision 0.16 and recall 0.27 on this grid. That is the bar the hidden risk signal has to clear.")], { after: 0 }),
  ]));

  c.push(...FIG("BST_DISCO_JH_2026/Images/4.Operations/helios_dryrun_trajectories.png",
    "Real urgency (solid) against synthetic declared urgency (dashed) across the 19 turns, one panel per node. The crisis propagates as intended: the foundry saturates at turn 8, transport at turn 7 with Suez, and the recovery is slow and partial, as it was historically. Synthetic declarations, not human.", 560, 620));

  c.push(H2("Layer two: the forecast layer, scored against a frozen truth"));

  c.push(P("The forecast layer estimates, for each node and each turn, the probability of an adverse outcome within one to four turns. Because the ground truth of the replay is frozen, these are genuinely prospective predictions that can be scored. Two arms were run: a deterministic replay serving as control, and an arm in which eight persona agents were shown the prediction for their own node and could revise their declaration."));

  c.push(TABLE(
    ["Horizon", "n", "Positives", "Base rate", "Brier", "Brier skill", "AUC", "95 % CI", "PR-AUC"],
    [
      ["1 turn", "112", "7", "6.2 %", "0.134", "−1.278", "0.736", "[0.49, 0.93]", "0.163"],
      ["2 turns", "104", "14", "13.5 %", "0.197", "−0.690", "0.636", "[0.37, 0.87]", "0.205"],
      ["3 turns", "96", "20", "20.8 %", "0.273", "−0.654", "0.641", "[0.39, 0.85]", "0.266"],
      ["4 turns", "90", "26", "28.9 %", "0.319", "−0.553", "0.654", "[0.42, 0.85]", "0.353"],
    ],
    [1150, 700, 950, 1050, 900, 1150, 850, 1450, 1438],
    { bold: [0], keepTogether: true },
  ));
  c.push(CAPTION("Control arm, 120 prospective forecasts over turns 4 to 18, scored against the frozen target definition (missed contractual milestone or critical event). Re-derived 13 August 2026 with experiment/mesures_avant_reparation/outils/score_endogene.py."));

  c.push(P("Two numbers in that table point in opposite directions, and the honest reading requires holding both."));

  c.push(P([
    B("The area under the curve is above chance at every horizon"),
    T(", reaching 0.736 at one turn, and the precision-recall area exceeds the base rate everywhere. The model orders the nodes usefully: asked which node is most at risk, it tends to be right."),
  ]));

  c.push(P([
    B("The Brier skill score is negative at every horizon"),
    T(", from −1.278 to −0.553. Negative skill means the forecast is worse, in squared error, than the trivial strategy of always announcing the base rate. The probability attached to the ordering is not usable."),
  ]));

  c.push(P("A model that ranks well and calibrates badly is a specific and recognisable object. It is useful for triage and dangerous for decision, because the number it prints is the number a manager will act on. Part 7 dissects exactly how the calibration fails, and it is not the way one would guess."));

  c.push(H2("Layer three: what happened to the people who read the forecast"));

  c.push(P("In the second arm, eight persona agents received the prediction for their own node from turn four onward, and each recorded whether it changed their declaration. Turns zero to three, before any prediction was shown, are uniformly \"no influence\", which serves as the internal control."));

  c.push(P("Then the predictions appeared."));

  c.push(TABLE(
    ["Turn", "No influence", "Confirmed", "Revised upward", "Revised downward"],
    [
      ["T0 to T3 (nothing shown)", "33", "0", "0", "0"],
      ["T4, first exposure", "0", "3", "0", "5"],
      ["T5", "0", "5", "3", "0"],
      ["T6, the Texas freeze", "1", "3", "2", "2"],
      ["T7 to T11", "5", "16", "10", "9"],
      ["All turns (n = 97)", "39", "27", "15", "16"],
    ],
    [2900, 1750, 1600, 1750, 1638],
    { bold: [0], keepTogether: true },
  ));
  c.push(CAPTION("Declared influence of the forecast on the operator's own declaration, arm B, 97 declarations over 12 turns. Re-derived from experiment/mesures_avant_reparation/bras_b/results_*.jsonl on 13 August 2026. LLM personas, not humans."));

  c.push(P("At the first exposure, every one of the eight was either confirmed in their existing view or moved downward. Five of eight actively revised their urgency down. Not one revised upward. Two turns later, the Texas freeze arrested the foundry, the only critical event in the scenario."));

  c.push(P("Two qualifications keep this from being overstated, and both matter. First, the personas are language model agents, not people: this is a signal worth pursuing with humans, not a finding about humans. Second, the effect landed on the declared level and not on behaviour. All eight still took an operational action that turn, negotiating allocation, alerting the customer, or ordering early. The forecast made them calmer without making them passive, which is a narrower and more interesting result than simple automation bias."));

  c.push(REFRAIN("The forecast did not fail quietly. It reassured eight people, on the way to a shock."));

  /* ============================================================= PART 7 */
  c.push(KICKER("Part 7"));
  c.push(H1("Limits: what we know is wrong"));

  c.push(P("This section is longer and more specific than the results section, which is the correct proportion for a system at this stage. Each defect below is mechanical, reproducible from artefacts in the repository, and general to any supply chain rather than particular to the test scenario. That last property is a deliberate constraint: a fix that only works on HÉLIOS would be worthless."));

  c.push(H2("Defect 1. The milestone risk block never sees the events that cause missed milestones"));

  c.push(P("The block that produces the probability of missing a milestone reacts to exactly one indicator: nominal lead time. No calibrated event routes to that indicator. A factory can freeze for four weeks and the block will not notice, because a fab shutdown does not change the nominal lead time of the node."));

  c.push(P("Turn six of the HÉLIOS run demonstrates the consequence twice, in opposite directions, on the same turn."));

  c.push(TABLE(
    ["Node", "Announced probability of missing the milestone", "What actually happened", "Verdict"],
    [
      ["CompoDis", "99.6 %", "Milestone \"component coverage S1\", contractual deadline T9, delivered at T9", "Delivered on time"],
      ["NovaFab", "0.0 %", "Milestone \"HÉLIOS wafer allocation\", deadline T10, delivered at T11, while the fab was frozen from T6", "Missed"],
    ],
    [1400, 2900, 3600, 1738],
    { bold: [0], keepTogether: true },
  ));
  c.push(CAPTION("Turn 6 of the arm B run. Re-derived from bras_b/predictions_log.jsonl and scenario.MILESTONES on 13 August 2026."));

  c.push(P("Near certainty announced on the one that landed. Silence on the one that broke, on the very turn its factory stopped. The model is close to anti correlated on this pair. The cause of the false alarm is instructive: a supplier delay had inflated CompoDis's lead time to roughly nineteen weeks, and against three weeks of remaining slack the delay probability saturates mechanically. Nominal lead time says nothing about the actual ability to finish, and the operator persona, acting on that 99.6 per cent, chose to replan the entire schedule on a false positive."));

  c.push(P("NovaFab's probability only began to move at turn seven, reaching 0.034, and turn eight, reaching 0.846: two turns after the freeze, and only through lead time drift."));

  c.push(H2("Defect 2. The shock did not propagate, on a model whose purpose is propagation"));

  c.push(P("The Texas freeze is the largest single event in the scenario. Its effect on the client impact probability of the surrounding nodes, across turns five, six and seven, was as follows: SilPure, the frozen node's own supplier, 0.0 throughout. NovaFab itself, 0.0 throughout. CompoDis, its customer, 0.0 throughout. The final customer moved from 0.050 to 0.056."));

  c.push(P("Neither upstream nor downstream contamination occurred. Since the propagation of risk across the network is the central mechanism the model exists to provide, this is the most structurally serious of the four defects, and it is closely coupled to the first: events that never reach the indicators cannot propagate through them."));

  c.push(H2("Defect 3. The calibration is wrong in both directions at once"));

  c.push(P("The negative Brier skill invites an obvious diagnosis, that the model is systematically under confident and needs its probabilities scaled up. The reliability table says something more awkward."));

  c.push(TABLE(
    ["Announced probability band", "n", "Mean announced", "Actually observed", "Error"],
    [
      ["Below 10 %", "54", "7.2 %", "24.1 %", "understated 3.3×"],
      ["10 % to 20 %", "18", "13.0 %", "44.4 %", "understated 3.4×"],
      ["20 % to 40 %", "1", "35.4 %", "0.0 %", "single point"],
      ["40 % to 90 %", "5", "88.2 %", "40.0 %", "overstated 2.2×"],
      ["Above 90 %", "12", "99.1 %", "25.0 %", "overstated 4.0×"],
    ],
    [3000, 800, 1900, 1900, 2038],
    { bold: [0], keepTogether: true },
  ));
  c.push(CAPTION("Reliability of the four-turn forecast, control arm, n = 90, observed base rate 28.9 %. Re-derived 13 August 2026."));

  c.push(P("Across the eighty per cent of forecasts that sit below twenty per cent, the model understates the real rate by a factor of about three. In the saturated tail, where it announces near certainty, it overstates by a factor of four. It is not under confident. It is confidently wrong at both ends, and the two errors partially cancel in the mean, which is why the average announced probability of 25.4 per cent looks almost right against an observed 28.9 per cent while the skill score is deeply negative."));

  c.push(P("The overstated tail is defect 1 seen from the metrics side: the saturated points are the milestone block pinning itself at certainty. The understated bulk is the same defect seen from the other side, the blindness."));

  c.push(H2("Defect 4. An evaluation against the wrong target nearly condemned a working system"));

  c.push(P("The first scoring of this forecast layer used a plausible looking definition of an adverse outcome: any event occurring on the node within the horizon. It produced this."));

  c.push(TABLE(
    ["Horizon", "AUC against \"any event on the node\"", "AUC against the frozen target definition"],
    [
      ["1 turn", "0.591", "0.736"],
      ["2 turns", "0.551", "0.636"],
      ["3 turns", "0.491", "0.641"],
      ["4 turns", "0.435  (worse than chance)", "0.654"],
    ],
    [1600, 4200, 3838],
    { bold: [0], keepTogether: true },
  ));
  c.push(CAPTION("Same model, same predictions, same data. Only the definition of the outcome changed. Re-derived 13 August 2026 from score_predictions.py and score_endogene.py."));

  c.push(P("At four turns the difference is between a model that is worse than a coin toss and a model carrying real signal. The forecast layer does not estimate the probability of any event; it estimates the probability of an adverse outcome in the precise, frozen sense used by the calibration service, namely a missed milestone or a critical event. Scoring it against a different quantity measured something the model never claimed to predict."));

  c.push(P("The general lesson is worth more than the number: an evaluation against the wrong target can condemn a system that works, silently, with no error message and a plausible looking metric. In this project it was caught because the target definition had been frozen in one place and could be checked. Without that single definition, it would not have been."));

  c.push(H2("Defect 5. The evidence ladder was climbed out of order"));

  c.push(P("The four defects above share one root cause, and naming it is more useful than any of them individually."));

  c.push(P("The intended sequence for this system is: learn on a synthetic factory of many randomised supply chains, generalise through a calibration layer trained on that factory, then test on a historical replay. What happened is that the historical replay ran first. No forecasting artefact had ever been trained. The synthetic factory had never run at scale. The arm B campaign therefore measured the raw simulator, without the ensemble and isotonic calibration layer whose entire purpose is to fix the miscalibration that was then observed and reported as a finding."));

  c.push(P("This was not wasted effort, and the reason matters for the plan in part 8. Running the test early surfaced four defects in the core of the model rather than in the scenario. Had the synthetic factory been run first with those defects in place, it would have generated hundreds of chains carrying them, and the calibration layer would have been carefully trained to be well calibrated on noise. The out of order test was a mistake that prevented a much more expensive one."));

  c.push(H2("Standing limits, independent of the defects"));

  c.push(BULLET([B("No certain prediction. "), T("Probabilities, scores and intervals. A model is a simplification, and this one is documented as such in its own specification.")]));
  c.push(BULLET([B("Freshness equals entry cadence. "), T("There is no ERP connector. Manual entry is an accepted design choice, and a score is never fresher than the last questionnaire.")]));
  c.push(BULLET([B("Event reversal is not guaranteed. "), T("If another process has rewritten an indicator in the meantime, the conflict is surfaced explicitly for a human to arbitrate rather than silently rebased.")]));
  c.push(BULLET([B("The milestone block looks only at the next active milestone. "), T("A distant milestone drifting off course stays invisible until it becomes the next one.")]));
  c.push(BULLET([B("Right censoring in the calibration window. "), T("For recent weeks the observation window runs past the end of the data, so the observed rate is a lower bound.")]));
  c.push(BULLET([B("Statistical power is low, and the campaign design cannot fix it. "), T("Eight consultants, one network, one crisis. The thresholds in the pre-registered hypotheses are decision criteria, not inference tests. Even a complete success would establish that the phenomenon exists and is measurable, not that it generalises.")]));

  c.push(REFRAIN("A model that is confident where it is blind is worse than no model."));

  /* ============================================================= PART 8 */
  c.push(KICKER("Part 8"));
  c.push(H1("Next steps"));

  c.push(P("The corrected sequence is the plan, and the order is not negotiable, because each step is what makes the next one meaningful."));

  c.push(TABLE(
    ["Step", "What it does", "Why it must come in this position", "Evidence level"],
    [
      ["1. Repair the core", "Route calibrated events through to capacity and effective lead time; make milestone risk depend on real progress as well as nominal lead time; restore shock propagation across the graph", "Training on a defective simulator produces a model well calibrated on noise. Everything downstream is invalid until this is done", "Prerequisite"],
      ["2. Run the synthetic factory", "150 to 2 000 randomised supply chains with a versioned data generating process and synthetic declarants", "This is where the model learns. It has never been run at scale", "T1 to T2"],
      ["3. Train and calibrate", "Ensemble and isotonic calibration trained on the factory, validated on held out chains", "This is where the model generalises. It is the layer that was missing when arm B was measured", "T2"],
      ["4. Re-test HÉLIOS", "Identical protocol, trained model, compared against the archived before-repair measurements", "Produces a before and after comparison, which is far stronger evidence than an isolated measurement", "T3"],
      ["5. Human campaign", "Eight consultants, 18 turns over 15 working days, frozen protocol, placebos, blind debrief", "The only step that can settle the cognitive hypotheses. Built and waiting", "T3 to T4"],
    ],
    [1700, 2600, 3600, 1738],
    { bold: [0], keepTogether: true },
  ));
  c.push(CAPTION("The corrected sequence. Evidence levels follow the scale defined in Appendix B."));

  c.push(PANEL("One rule that is not up for discussion", "evidence", [
    P([
      T("The calibration layer is trained on the synthetic factory and applied to HÉLIOS "),
      B("unchanged"),
      T(". It is never tuned on the test scenario. A system that has been adjusted until it performs on its own benchmark has measured nothing, and the whole point is that this must work for supply chains nobody has seen yet."),
    ], { after: 0 }),
  ]));

  c.push(H2("Why step 4 is stronger than it looks"));

  c.push(P("Before the repairs begin, the complete before-repair state is archived in the repository: the replayed control arm across nineteen turns, the arm B campaign across twelve turns and eight personas, both prediction logs, and the scoring tools used to produce every number in part 6 and part 7 of this document. The repair will therefore be measured against a fixed reference rather than asserted. If the corrected model does not beat those figures, that will be visible and reportable."));

  c.push(H2("What the increment delivers"));

  c.push(P("The target is not a better dashboard. It is a change in the type of object the system emits: from a score, which a manager must interpret, to a decision, which a manager can accept or refuse. The output contract is already written and frozen."));

  c.push(PANEL("The end contract, verbatim from the v7 plan", "mechanism", [
    P([B("NovaFab"), T(" — Risk without action: "), B("29 %"), T(" [80 % CI, Monte Carlo and parameter: 21 to 38 %].")], { after: 40 }),
    P([T("Recommended action: "), B("promote the backup arc to Meridian"), T(". Risk with action: "), B("14 %"), T(". Estimated effect: −15 points [80 % CI: −22 to −8], source: matched simulation, IPW corrected on 7 real observations.")], { after: 40 }),
    P([T("P(effect > 0): 92 %. P(operational resolution | execution): 63 % [48 to 74 %]. P(execution): 85 %. P(rupture avoided) = 0.85 × 0.63 ≈ "), B("54 %"), T(".")], { after: 40 }),
    P([T("Net value: "), B("[−2 k€, +41 k€]"), T(" (customer penalties avoided minus estimated cost), or \"heuristic ranking\" if costs are not quantified. Time to effect: 1 to 2 weeks.")], { after: 40 }),
    P([T("Evidence level: "), B("weak to medium"), T(" — simulated prior plus 7 real observations; recommendation robust across all three prior choices. Model uncertainty: not quantified (simulator).")], { after: 40 }),
    P([T("Portfolio: compatible with the 2 other retained actions (budget 3 of 5 consumed).")], { after: 0 }),
  ]));

  c.push(P("Every clause of that output is a commitment the system currently cannot fully honour, which is why it is printed here in full rather than paraphrased. The probability of execution is there because a recommendation nobody carries out has no value. The evidence level is there because a recommendation whose support is thin should say so. The net value falls back to a heuristic ranking when costs are not available, rather than inventing them."));

  c.push(H2("And the gate stays shut"));

  c.push(P("The causal layer that would estimate the effect of an action currently reports a failure on its own validation battery: confidence interval coverage of 66 and 57 per cent against a required 70 under latent confounding, with the machinery validated at around 80 per cent on an unconfounded control, and a naive bias of 0.156 against 0.090 for the corrected estimator, which demonstrates that the confounding is real rather than hypothetical."));

  c.push(P("The pipeline's response to that failure is automatic and was designed before the failure occurred. The effects artefact is written to a staging directory, the global verdict is read, and on anything other than a pass nothing is copied into the published model directory. The forecast is still published. The prescriptive layer is not. Nobody overrode it, and the reason to mention it here is that this is the behaviour the whole document has been arguing for: the last measurement that disagreed with us was made by the system itself, and the system won."));

  c.push(REFRAIN("The last measurement that disagreed with us was made by the system itself."));

  /* =========================================================== APPENDIX */
  c.push(new Paragraph({ children: [new PageBreak()] }));
  c.push(H1("Appendix A. Provenance of every figure in this document"));

  c.push(P("No number appears in this document without a source that a reader can check. Where published documents in the repository disagreed with each other, the value was re-derived from the underlying artefacts and the disagreement is noted."));

  c.push(TABLE(
    ["Figure", "Value used", "How it was obtained"],
    [
      ["Automated tests", "1 974", "pytest --collect-only, run 13 August 2026. Supersedes 1 425, 1 592 and 1 614 quoted in older documents"],
      ["Modules and packages", "86 modules, 13 packages", "File count over supplyscore/, 13 August 2026"],
      ["Version, coverage gate", "v2.0.0, 90 % blocking", "pyproject.toml"],
      ["A = 53.1 vs 21.1, and 29.3 vs 0", "as printed", "docs/modele_mathematique.md §10 reference cases, cross-checked against the adequacy engine"],
      ["AERIS week 8 table", "as printed", "scripts/demo_scenario.py --reset, seed 42, re-run 13 August 2026"],
      ["Dry run verdicts, null baseline", "precision 0.16, recall 0.27", "projects/simu_semiconducteurs/analysis/rapport.md"],
      ["Forecast scoring, both arms", "as printed", "experiment/mesures_avant_reparation/outils/score_endogene.py, re-run 13 August 2026"],
      ["Wrong-target contrast", "0.435 vs 0.654", "score_predictions.py against score_endogene.py, same logs, 13 August 2026"],
      ["Reliability bands", "as printed", "Binned from the control arm log, four turn horizon, 13 August 2026"],
      ["Turn 6 milestone pair", "99.6 % and 0.0 %", "bras_b/predictions_log.jsonl field p_jalon_rate, cross-checked against scenario.MILESTONES and MILESTONE_DONE"],
      ["Propagation figures", "0.050 to 0.056", "bras_b/predictions_log.jsonl field p_impact_client, turns 5 to 7"],
      ["Influence of the forecast", "as printed", "bras_b/results_*.jsonl field influence_prediction, 97 declarations. Note: rapport_experience.md reports different counts from an earlier partial run and was not used"],
      ["Causal validation failure", "66 / 57 %, bias 0.156 vs 0.090", "U17 validation report, v7 plan record"],
      ["End contract", "verbatim", "v7 plan, \"Contrat de fin\" section"],
    ],
    [2600, 2100, 4938],
    { bold: [0] },
  ));

  c.push(H1("Appendix B. The evidence ladder"));

  c.push(P("The scale below is the one defined in the v7 plan and used throughout this document. It is reproduced here so that every claim in the text can be placed on it."));

  c.push(TABLE(
    ["Level", "Definition", "Status"],
    [
      ["T1", "Functioning, on synthetic data", "Reached. Nineteen turn replay end to end, property based tests, blocking coverage gate"],
      ["T2", "Generalisation across randomised chains and held out regimes", "Not reached. The synthetic factory has never been run at scale. This is step 2 of the plan"],
      ["T3", "Historical replay against a documented crisis", "Attempted early and out of order. Returned four defects rather than validation. The human campaign that would establish it properly is built, frozen and unrun"],
      ["T4", "Utility: observation, then controlled intervention", "Not reached. The causal validation battery currently fails and the pipeline withholds the artefact"],
    ],
    [900, 3200, 5538],
    { bold: [0], keepTogether: true },
  ));

  c.push(P("The honest one line summary of this project's status: T1 reached, T2 skipped, T3 attempted early and instructive, T4 gated shut by the system's own validation. The plan in part 8 exists to put those back in order.", { after: 300 }));

  c.push(H1("Appendix C. The thread, read on its own"));

  c.push(P("The eight lines below close the eight parts of this document. Read in sequence, they are the argument."));

  const refrains = [
    "The dashboard was not wrong. It was measuring the wrong thing.",
    "Everyone scores the world. Nobody scores the gap between the world and what we say about it.",
    "We changed the mathematics because the arithmetic disagreed with the factory floor.",
    "The score's job is not to be believed. It is to be checkable.",
    "We wrote down how we could be wrong before we could know whether we were.",
    "The forecast did not fail quietly. It reassured eight people, on the way to a shock.",
    "A model that is confident where it is blind is worse than no model.",
    "The last measurement that disagreed with us was made by the system itself.",
  ];
  refrains.forEach((r, i) => {
    c.push(new Paragraph({
      children: [T(`${i + 1}.  `, { size: 21, bold: true, color: AZURE }), I(r, { size: 22, color: NAVY })],
      spacing: { after: 130, line: 290 },
      indent: { left: 240 },
    }));
  });

  c.push(P(" ", { after: 200 }));
  c.push(PANEL("In one sentence", "evidence", [
    P([I("Every honest measurement in this project contradicted a belief, and each contradiction is why the instrument can now be trusted.", { size: 24 })], { after: 0 }),
  ]));

  return c;
}

/* ------------------------------------------------------------------- write */
const buf = await Packer.toBuffer(doc);
fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, buf);
console.log(`Written: ${OUT}  (${(buf.length / 1024).toFixed(0)} KB)`);
