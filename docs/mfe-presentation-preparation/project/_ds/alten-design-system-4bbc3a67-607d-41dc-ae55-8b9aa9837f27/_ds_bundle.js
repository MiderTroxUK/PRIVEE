/* @ds-bundle: {"format":4,"namespace":"ALTENDesignSystem_4bbc3a","components":[{"name":"AccentBar","sourcePath":"components/brand/AccentBar.jsx"},{"name":"Baseline","sourcePath":"components/brand/Baseline.jsx"},{"name":"FrameDevice","sourcePath":"components/brand/FrameDevice.jsx"},{"name":"Logo","sourcePath":"components/brand/Logo.jsx"},{"name":"BulletList","sourcePath":"components/content/BulletList.jsx"},{"name":"ColumnCard","sourcePath":"components/content/ColumnCard.jsx"},{"name":"DataTable","sourcePath":"components/content/DataTable.jsx"},{"name":"FactChip","sourcePath":"components/content/FactChip.jsx"},{"name":"IconHeading","sourcePath":"components/content/IconHeading.jsx"},{"name":"KeyFigure","sourcePath":"components/content/KeyFigure.jsx"},{"name":"NumberedList","sourcePath":"components/content/NumberedList.jsx"},{"name":"Quote","sourcePath":"components/content/Quote.jsx"},{"name":"SectionLabel","sourcePath":"components/content/SectionLabel.jsx"},{"name":"Icon","sourcePath":"components/media/Icon.jsx"},{"name":"ChapterHeading","sourcePath":"components/slide/ChapterHeading.jsx"},{"name":"SlideFrame","sourcePath":"components/slide/SlideFrame.jsx"},{"name":"SlideTitle","sourcePath":"components/slide/SlideTitle.jsx"},{"name":"Button","sourcePath":"components/ui/Button.jsx"}],"sourceHashes":{"components/brand/AccentBar.jsx":"d2621b06d879","components/brand/Baseline.jsx":"43b8929c802a","components/brand/FrameDevice.jsx":"28b02b7e65e9","components/brand/Logo.jsx":"8536ee370b65","components/content/BulletList.jsx":"9828d282e29d","components/content/ColumnCard.jsx":"622200a69f1a","components/content/DataTable.jsx":"fc1b7078185f","components/content/FactChip.jsx":"6f98b567c7e1","components/content/IconHeading.jsx":"0b99bd754271","components/content/KeyFigure.jsx":"2128ff808d8e","components/content/NumberedList.jsx":"f8b122a69f22","components/content/Quote.jsx":"5ea1f115376b","components/content/SectionLabel.jsx":"821c325a9a2b","components/media/Icon.jsx":"172c9d96a166","components/slide/ChapterHeading.jsx":"8b952b3aee83","components/slide/SlideFrame.jsx":"7088294b0ad3","components/slide/SlideTitle.jsx":"776daa93a910","components/ui/Button.jsx":"8df954af4b41","tools/dump.js":"e7f8fb26f419","tools/ico.js":"ec38c52057ad","tools/icocat.js":"39d96f0f5d89","tools/unzip.js":"aa83b0f2205e","ui_kits/presentation/DeckShell.jsx":"bb6e74d22e1e","ui_kits/presentation/Slides.jsx":"a7f18e84a807","ui_kits/print_document/Pages.jsx":"ec72fd17c90b","ui_kits/reference_project/RefProjectSheet.jsx":"96d3ccd55344"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.ALTENDesignSystem_4bbc3a = window.ALTENDesignSystem_4bbc3a || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// components/brand/AccentBar.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** The 6 pt rule that runs down the left edge of every ALTEN content slide.
 *  Solid navy by default; `gradient` uses the navy → blue → yellow wash. */
function AccentBar({
  tone = 'navy',
  width,
  orientation = 'vertical',
  style,
  ...rest
}) {
  const w = width || 'var(--accent-bar-w)';
  const bg = tone === 'gradient' ? orientation === 'vertical' ? 'var(--gradient-brand)' : 'var(--gradient-brand-h)' : tone === 'white' ? 'var(--alten-white)' : tone === 'blue' ? 'var(--alten-blue)' : tone === 'yellow' ? 'var(--alten-yellow)' : 'var(--accent-bar)';
  const vertical = orientation === 'vertical';
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      background: bg,
      width: vertical ? w : '100%',
      height: vertical ? '100%' : w,
      flex: '0 0 auto',
      ...style
    }
  }, rest));
}
Object.assign(__ds_scope, { AccentBar });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/brand/AccentBar.jsx", error: String((e && e.message) || e) }); }

// components/brand/Baseline.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** The ALTEN corporate baseline lockup: "BUILDING TOMORROW'S" set in Arial
 *  Black over "WORLD TODAY" set in Arial and letterspaced 0.15 em.
 *  Copy is fixed — it is the Group signature. */
function Baseline({
  tone = 'light',
  size = 48,
  align = 'left',
  style,
  ...rest
}) {
  const color = tone === 'light' ? 'var(--alten-white)' : 'var(--alten-navy-ink)';
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      color,
      textAlign: align,
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-display)',
      fontWeight: 'var(--weight-display)',
      textTransform: 'uppercase',
      lineHeight: 'var(--leading-display)',
      fontSize: size * 0.6 + 'px',
      letterSpacing: 0
    }
  }, "Building tomorrow\u2019s"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-sans)',
      fontWeight: 'var(--weight-regular)',
      textTransform: 'uppercase',
      lineHeight: 'var(--leading-display)',
      fontSize: size + 'px',
      letterSpacing: 'var(--tracking-wide)'
    }
  }, "World today"));
}
Object.assign(__ds_scope, { Baseline });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/brand/Baseline.jsx", error: String((e && e.message) || e) }); }

// components/brand/FrameDevice.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** The recurring ALTEN "open frame" device — a thin, slightly-skewed
 *  three-sided rectangle that brackets photography and cover imagery.
 *  Drawn with borders only, so it stays crisp at any size. */
function FrameDevice({
  tone = 'white',
  thickness = 2,
  skew = 4,
  inset = '8%',
  open = 'left',
  children,
  style,
  ...rest
}) {
  const color = tone === 'yellow' ? 'var(--alten-yellow)' : tone === 'sky' ? 'var(--alten-sky)' : tone === 'navy' ? 'var(--alten-navy)' : 'var(--alten-white)';
  const side = {
    left: 'borderLeft',
    right: 'borderRight',
    top: 'borderTop',
    bottom: 'borderBottom'
  }[open] || 'borderLeft';
  const border = `${thickness}px solid ${color}`;
  const frame = {
    borderTop: border,
    borderRight: border,
    borderBottom: border,
    borderLeft: border,
    [side]: 'none'
  };
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      position: 'relative',
      ...style
    }
  }, rest), children, /*#__PURE__*/React.createElement("div", {
    "aria-hidden": "true",
    style: {
      position: 'absolute',
      inset,
      transform: `skewY(-${skew}deg)`,
      pointerEvents: 'none',
      ...frame
    }
  }));
}
Object.assign(__ds_scope, { FrameDevice });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/brand/FrameDevice.jsx", error: String((e && e.message) || e) }); }

// components/brand/Logo.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const SRC = {
  full: {
    color: 'assets/logo/alten-logo-color.png',
    white: 'assets/logo/alten-logo-white.svg',
    navy: 'assets/logo/alten-logo-navy.svg',
    black: 'assets/logo/alten-logo-black.svg'
  },
  mark: {
    color: 'assets/logo/alten-mark-color.png',
    white: 'assets/logo/alten-mark.svg',
    navy: 'assets/logo/alten-mark.svg',
    black: 'assets/logo/alten-mark.svg'
  },
  wordmark: {
    color: 'assets/logo/alten-wordmark-navy.svg',
    white: 'assets/logo/alten-wordmark-white.svg',
    navy: 'assets/logo/alten-wordmark-navy.svg',
    black: 'assets/logo/alten-wordmark.svg'
  }
};

/** The ALTEN logo. Never redraw or recolour the mark: the four logo colours
 *  (#FAEA27 / #E52629 / #1B94D2 / #020203) are fixed. Only the wordmark
 *  changes tone, white on navy or photography, black/navy on white. */
function Logo({
  variant = 'full',
  tone = 'color',
  height,
  width,
  base = '',
  alt = 'ALTEN',
  style,
  ...rest
}) {
  const src = (SRC[variant] || SRC.full)[tone] || SRC[variant].color;
  const h = height || (variant === 'wordmark' ? 14 : 56);
  return /*#__PURE__*/React.createElement("img", _extends({
    src: base + src,
    alt: alt,
    style: {
      display: 'block',
      height: typeof h === 'number' ? h + 'px' : h,
      width: width ? typeof width === 'number' ? width + 'px' : width : 'auto',
      ...style
    }
  }, rest));
}
Object.assign(__ds_scope, { Logo });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/brand/Logo.jsx", error: String((e && e.message) || e) }); }

// components/content/BulletList.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** Body copy list. The masters use a plain Arial bullet in accent blue with
 *  5 pt space before and after each item and 90 % leading. */
function BulletList({
  items = [],
  tone = 'light',
  size = 'md',
  marker = 'dot',
  style,
  ...rest
}) {
  const dark = tone !== 'light';
  const color = dark ? 'var(--text-on-dark)' : 'var(--text-body)';
  const mark = dark ? 'var(--alten-sky)' : 'var(--alten-blue)';
  return /*#__PURE__*/React.createElement("ul", _extends({
    style: {
      listStyle: 'none',
      margin: 0,
      padding: 0,
      color,
      fontFamily: 'var(--font-text)',
      fontSize: size === 'sm' ? 'var(--slide-caption)' : size === 'lg' ? 'var(--slide-body)' : 'var(--slide-body-sm)',
      lineHeight: 'var(--leading-snug)',
      display: 'flex',
      flexDirection: 'column',
      gap: 7,
      ...style
    }
  }, rest), items.map((it, i) => /*#__PURE__*/React.createElement("li", {
    key: i,
    style: {
      display: 'flex',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("span", {
    "aria-hidden": "true",
    style: {
      color: mark,
      flex: '0 0 auto',
      fontWeight: marker === 'pipe' ? 700 : 400
    }
  }, marker === 'pipe' ? '|' : marker === 'dash' ? '—' : '\u2022'), /*#__PURE__*/React.createElement("span", {
    style: {
      textWrap: 'pretty'
    }
  }, it))));
}
Object.assign(__ds_scope, { BulletList });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/content/BulletList.jsx", error: String((e && e.message) || e) }); }

// components/content/ColumnCard.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** The card from the "3 Columns Shadows" master: full-bleed image on top,
 *  Arial Black heading, Calibri body. Square corners, soft drop shadow,
 *  no border. On the grey-background variant the shadow is dropped. */
function ColumnCard({
  image,
  imageAlt = '',
  title,
  label,
  children,
  elevated = true,
  tone = 'card',
  style,
  ...rest
}) {
  const bg = tone === 'panel' ? 'var(--surface-panel)' : tone === 'navy' ? 'var(--surface-navy)' : 'var(--surface-card)';
  const dark = tone === 'navy';
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      background: bg,
      boxShadow: elevated ? 'var(--shadow-card)' : 'none',
      borderRadius: 'var(--radius-none)',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
      ...style
    }
  }, rest), image && /*#__PURE__*/React.createElement("img", {
    src: image,
    alt: imageAlt,
    style: {
      display: 'block',
      width: '100%',
      height: 112,
      objectFit: 'cover'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '16px 18px 20px'
    }
  }, label && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-text)',
      fontWeight: 'var(--weight-bold)',
      fontSize: 'var(--slide-caption)',
      textTransform: 'uppercase',
      letterSpacing: '0.02em',
      color: dark ? 'var(--alten-sky)' : 'var(--text-subtitle)',
      marginBottom: 6
    }
  }, label), title && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-display)',
      fontWeight: 'var(--weight-display)',
      fontSize: 'var(--text-xl)',
      lineHeight: 'var(--leading-display)',
      textTransform: 'uppercase',
      color: dark ? 'var(--text-on-dark)' : 'var(--text-title)',
      marginBottom: 10
    }
  }, title), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-text)',
      fontSize: 'var(--slide-body-sm)',
      lineHeight: 'var(--leading-snug)',
      color: dark ? 'var(--alten-sky)' : 'var(--text-body)'
    }
  }, children)));
}
Object.assign(__ds_scope, { ColumnCard });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/content/ColumnCard.jsx", error: String((e && e.message) || e) }); }

// components/content/DataTable.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** The ALTEN table: navy header row in white uppercase Calibri bold, body
 *  rows separated by hairline rules, no vertical rules, no zebra fill. */
function DataTable({
  columns = [],
  rows = [],
  align = 'left',
  dense = false,
  style,
  ...rest
}) {
  const pad = dense ? '7px 10px' : '10px 14px';
  return /*#__PURE__*/React.createElement("table", _extends({
    style: {
      width: '100%',
      borderCollapse: 'collapse',
      fontFamily: 'var(--font-text)',
      fontSize: dense ? 'var(--slide-caption)' : 'var(--slide-body-sm)',
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, columns.map((c, i) => /*#__PURE__*/React.createElement("th", {
    key: i,
    style: {
      background: 'var(--surface-navy)',
      color: 'var(--text-on-dark)',
      fontWeight: 'var(--weight-bold)',
      textTransform: 'uppercase',
      letterSpacing: '0.02em',
      textAlign: i === 0 ? 'left' : align,
      padding: pad,
      whiteSpace: 'nowrap'
    }
  }, c)))), /*#__PURE__*/React.createElement("tbody", null, rows.map((r, ri) => /*#__PURE__*/React.createElement("tr", {
    key: ri
  }, r.map((cell, ci) => /*#__PURE__*/React.createElement("td", {
    key: ci,
    style: {
      borderBottom: 'var(--border-hairline-w) solid var(--border-hairline)',
      padding: pad,
      color: ci === 0 ? 'var(--text-title)' : 'var(--text-body)',
      fontWeight: ci === 0 ? 'var(--weight-bold)' : 'var(--weight-regular)',
      textAlign: ci === 0 ? 'left' : align
    }
  }, cell))))));
}
Object.assign(__ds_scope, { DataTable });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/content/DataTable.jsx", error: String((e && e.message) || e) }); }

// components/content/FactChip.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** Icon + short label pair from the Reference-Project footer strip
 *  ("XXX FTE", "Service contract"). 8 pt Arial bold under a blue glyph. */
function FactChip({
  icon,
  iconAlt = '',
  label,
  tone = 'light',
  iconSize = 30,
  style,
  ...rest
}) {
  const dark = tone !== 'light';
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      gap: 6,
      textAlign: 'center',
      ...style
    }
  }, rest), icon && /*#__PURE__*/React.createElement("img", {
    src: icon,
    alt: iconAlt,
    style: {
      width: iconSize,
      height: iconSize,
      display: 'block'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-sans)',
      fontWeight: 'var(--weight-bold)',
      fontSize: 'var(--slide-footnote)',
      lineHeight: 'var(--leading-snug)',
      color: dark ? 'var(--text-on-dark)' : 'var(--text-title)',
      maxWidth: 92
    }
  }, label));
}
Object.assign(__ds_scope, { FactChip });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/content/FactChip.jsx", error: String((e && e.message) || e) }); }

// components/content/IconHeading.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** Column header from the 2026 Reference-Project one-pager: a navy square
 *  holding a white glyph, with a sky-blue uppercase caption overlapping its
 *  lower edge. Used for ABOUT / ALTEN ACTIVITIES / STANDARDS & TOOLS. */
function IconHeading({
  icon,
  label,
  size = 60,
  tone = 'navy',
  style,
  ...rest
}) {
  const bg = tone === 'blue' ? 'var(--alten-blue)' : 'var(--surface-navy)';
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      display: 'inline-flex',
      flexDirection: 'column',
      alignItems: 'center',
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement("div", {
    style: {
      width: size,
      height: size,
      background: bg,
      display: 'grid',
      placeItems: 'center'
    }
  }, icon), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: -10,
      background: 'var(--surface-page)',
      padding: '2px 8px',
      fontFamily: 'var(--font-text)',
      fontWeight: 'var(--weight-bold)',
      fontSize: 'var(--slide-label)',
      textTransform: 'uppercase',
      letterSpacing: '0.02em',
      color: 'var(--alten-sky)',
      textAlign: 'center',
      lineHeight: 1.15
    }
  }, label));
}
Object.assign(__ds_scope, { IconHeading });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/content/IconHeading.jsx", error: String((e && e.message) || e) }); }

// components/content/KeyFigure.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** A headline statistic — "57,400 EMPLOYEES", "+30 COUNTRIES", "95 %".
 *  Arial Black numeral over an uppercase Calibri label. */
function KeyFigure({
  value,
  label,
  note,
  tone = 'light',
  size = 'md',
  align = 'left',
  style,
  ...rest
}) {
  const dark = tone !== 'light';
  const px = size === 'lg' ? 'var(--text-4xl)' : size === 'sm' ? 'var(--text-xl)' : 'var(--text-3xl)';
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      textAlign: align,
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-display)',
      fontWeight: 'var(--weight-display)',
      fontSize: px,
      lineHeight: 'var(--leading-display)',
      color: dark ? 'var(--text-on-dark)' : 'var(--text-title)'
    }
  }, value), label && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-text)',
      fontWeight: 'var(--weight-bold)',
      fontSize: 'var(--slide-caption)',
      textTransform: 'uppercase',
      letterSpacing: 'var(--tracking-wide)',
      marginTop: 6,
      color: dark ? 'var(--alten-sky)' : 'var(--text-subtitle)'
    }
  }, label), note && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-text)',
      fontSize: 'var(--slide-caption)',
      marginTop: 4,
      color: dark ? 'var(--alten-sky)' : 'var(--text-muted)'
    }
  }, note));
}
Object.assign(__ds_scope, { KeyFigure });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/content/KeyFigure.jsx", error: String((e && e.message) || e) }); }

// components/content/NumberedList.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** The 01 / 02 / 03 step list: two-digit navy numeral, blue label, body copy. */
function NumberedList({
  items = [],
  tone = 'light',
  columns = 1,
  style,
  ...rest
}) {
  const dark = tone !== 'light';
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(' + columns + ',1fr)',
      gap: 24,
      ...style
    }
  }, rest), items.map((it, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      display: 'flex',
      gap: 14,
      alignItems: 'flex-start'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-display)',
      fontWeight: 'var(--weight-display)',
      fontSize: 'var(--text-2xl)',
      lineHeight: 'var(--leading-display)',
      color: dark ? 'var(--alten-sky)' : 'var(--alten-blue)',
      flex: '0 0 auto'
    }
  }, String(it.number != null ? it.number : i + 1).padStart(2, '0')), /*#__PURE__*/React.createElement("div", null, it.title && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-text)',
      fontWeight: 'var(--weight-bold)',
      fontSize: 'var(--slide-label)',
      textTransform: 'uppercase',
      color: dark ? 'var(--text-on-dark)' : 'var(--text-title)',
      marginBottom: 4
    }
  }, it.title), it.body && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-text)',
      fontSize: 'var(--slide-body-sm)',
      lineHeight: 'var(--leading-snug)',
      color: dark ? 'var(--alten-sky)' : 'var(--text-body)'
    }
  }, it.body)))));
}
Object.assign(__ds_scope, { NumberedList });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/content/NumberedList.jsx", error: String((e && e.message) || e) }); }

// components/content/Quote.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** Pull quote. The deck sets the quotation marks as part of the text in
 *  36 pt Arial Black; the attribution runs underneath in Arial blue. */
function Quote({
  children,
  author,
  role,
  tone = 'light',
  size = 'md',
  style,
  ...rest
}) {
  const dark = tone !== 'light';
  return /*#__PURE__*/React.createElement("blockquote", _extends({
    style: {
      margin: 0,
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-display)',
      fontWeight: 'var(--weight-display)',
      fontSize: size === 'lg' ? 'var(--slide-chapter)' : 'var(--text-2xl)',
      lineHeight: 'var(--leading-display)',
      textWrap: 'pretty',
      color: dark ? 'var(--text-on-dark)' : 'var(--text-title)'
    }
  }, "\u201C", children, "\u201D"), (author || role) && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 18,
      fontFamily: 'var(--font-sans)',
      fontSize: 'var(--slide-subtitle)',
      color: dark ? 'var(--alten-sky)' : 'var(--text-subtitle)'
    }
  }, author, role ? /*#__PURE__*/React.createElement("span", {
    style: {
      color: dark ? 'var(--alten-sky)' : 'var(--text-muted)'
    }
  }, " \u2014 ", role) : null));
}
Object.assign(__ds_scope, { Quote });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/content/Quote.jsx", error: String((e && e.message) || e) }); }

// components/content/SectionLabel.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** The small uppercase Calibri-bold label that heads a paragraph or column:
 *  12 pt, blue, no rule. Used as "TITLE OF THE PARAGRAPH" throughout. */
function SectionLabel({
  children,
  tone = 'blue',
  size = 'md',
  style,
  ...rest
}) {
  const color = tone === 'navy' ? 'var(--text-title)' : tone === 'sky' ? 'var(--alten-sky)' : tone === 'white' ? 'var(--text-on-dark)' : 'var(--text-subtitle)';
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      fontFamily: 'var(--font-text)',
      fontWeight: 'var(--weight-bold)',
      fontSize: size === 'sm' ? 'var(--slide-caption)' : 'var(--slide-label)',
      textTransform: 'uppercase',
      letterSpacing: '0.02em',
      color,
      marginBottom: 6,
      ...style
    }
  }, rest), children);
}
Object.assign(__ds_scope, { SectionLabel });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/content/SectionLabel.jsx", error: String((e && e.message) || e) }); }

// components/media/Icon.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const cache = {};

/** A glyph from the ALTEN icon pack. The SVGs are single-colour and paint
 *  through `--icon-color` (falling back to ALTEN blue), so the component
 *  inlines the file and sets that variable — a plain <img> also works and
 *  renders the default blue. */
function Icon({
  name,
  group = 'communication',
  size = 28,
  color = 'var(--alten-blue)',
  base = '',
  title,
  style,
  ...rest
}) {
  const url = base + 'assets/icons/' + group + '/' + name + '.svg';
  const [markup, setMarkup] = React.useState(cache[url] || null);
  React.useEffect(() => {
    if (cache[url]) {
      setMarkup(cache[url]);
      return;
    }
    let live = true;
    fetch(url).then(r => r.ok ? r.text() : '').then(t => {
      const clean = t.replace(/width="\d+"\s*height="\d+"/, '').replace(/<\?xml[^>]*\?>/, '');
      cache[url] = clean;
      if (live) setMarkup(clean);
    }).catch(() => {});
    return () => {
      live = false;
    };
  }, [url]);
  const box = {
    display: 'inline-block',
    width: size,
    height: size,
    flex: '0 0 auto',
    lineHeight: 0,
    '--icon-color': color,
    ...style
  };
  if (!markup) return /*#__PURE__*/React.createElement("span", _extends({
    role: "img",
    "aria-label": title || name,
    style: box
  }, rest));
  return /*#__PURE__*/React.createElement("span", _extends({
    role: "img",
    "aria-label": title || name,
    title: title,
    style: box,
    dangerouslySetInnerHTML: {
      __html: markup.replace('<svg', '<svg width="100%" height="100%"')
    }
  }, rest));
}
Object.assign(__ds_scope, { Icon });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/media/Icon.jsx", error: String((e && e.message) || e) }); }

// components/slide/ChapterHeading.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** Chapter / section opener: an oversized sky-blue number and a 36 pt
 *  Arial Black white headline. Emphasised words inside the headline are set
 *  in --alten-sky-pale in the source decks. */
function ChapterHeading({
  number,
  title,
  emphasis,
  style,
  ...rest
}) {
  const parts = emphasis && typeof title === 'string' ? title.split(emphasis) : null;
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      position: 'absolute',
      left: 12,
      top: 172,
      right: 60,
      display: 'flex',
      alignItems: 'flex-start',
      gap: 44,
      ...style
    }
  }, rest), number != null && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-display)',
      fontWeight: 'var(--weight-display)',
      fontSize: 'var(--slide-chapter-num)',
      lineHeight: 'var(--leading-display)',
      color: 'var(--alten-sky)',
      flex: '0 0 auto',
      paddingTop: 4
    }
  }, number, "."), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-display)',
      fontWeight: 'var(--weight-display)',
      fontSize: 'var(--slide-chapter)',
      lineHeight: 'var(--leading-display)',
      color: 'var(--text-on-dark)',
      maxWidth: 600
    }
  }, parts && parts.length === 2 ? /*#__PURE__*/React.createElement(React.Fragment, null, parts[0], /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--text-emphasis)'
    }
  }, emphasis), parts[1]) : title));
}
Object.assign(__ds_scope, { ChapterHeading });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/slide/ChapterHeading.jsx", error: String((e && e.message) || e) }); }

// components/slide/SlideFrame.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** The 16:9 ALTEN slide canvas and its chrome: left accent rule, the
 *  bottom-right A L T E N wordmark and the grey page number. Everything is
 *  positioned from the 720 x 405 pt master, scaled to 960 x 540 px. */
function SlideFrame({
  children,
  tone = 'light',
  pageNumber,
  total,
  bar = 'navy',
  bleed = false,
  base = '',
  width = 960,
  style,
  ...rest
}) {
  const dark = tone !== 'light';
  const bg = tone === 'navy' ? 'var(--surface-navy)' : tone === 'gradient' ? 'var(--gradient-chapter)' : tone === 'navy-gradient' ? 'var(--gradient-navy)' : 'var(--surface-page)';
  const barFill = bar === 'gradient' ? 'var(--gradient-brand)' : bar === 'white' ? 'var(--alten-white)' : bar === 'blue' ? 'var(--alten-blue)' : bar === 'yellow' ? 'var(--alten-yellow)' : dark ? 'var(--alten-white)' : 'var(--accent-bar)';
  const scale = width / 960;
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      width: width + 'px',
      height: width * 9 / 16 + 'px',
      position: 'relative',
      overflow: 'hidden',
      background: bg,
      fontFamily: 'var(--font-text)',
      color: dark ? 'var(--text-on-dark)' : 'var(--text-body)',
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      transform: 'scale(' + scale + ')',
      transformOrigin: 'top left',
      width: 960,
      height: 540
    }
  }, children, bar !== 'none' && /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 0,
      top: 0,
      bottom: 0,
      width: 'var(--accent-bar-w)',
      background: barFill
    }
  }), !bleed && /*#__PURE__*/React.createElement("img", {
    src: base + (dark ? 'assets/logo/alten-wordmark-white.svg' : 'assets/logo/alten-wordmark-navy.svg'),
    alt: "ALTEN",
    style: {
      position: 'absolute',
      right: 16,
      bottom: 14,
      width: 56,
      display: 'block'
    }
  }), pageNumber != null && /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      right: 84,
      bottom: 10,
      fontFamily: 'var(--font-text)',
      fontSize: 'var(--slide-page-num)',
      color: dark ? 'var(--alten-sky)' : 'var(--text-faint)',
      letterSpacing: 0
    }
  }, pageNumber, total ? ' | ' + total : ' |')));
}
Object.assign(__ds_scope, { SlideFrame });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/slide/SlideFrame.jsx", error: String((e && e.message) || e) }); }

// components/slide/SlideTitle.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** Slide title block: uppercase Arial Black navy title at 24 pt with an
 *  Arial blue subtitle at 13 pt directly beneath it. Sits at x = 21 pt,
 *  y = 10 pt on every "Title – Subtitle" master. */
function SlideTitle({
  title,
  subtitle,
  tone = 'light',
  size = 'regular',
  align = 'left',
  style,
  ...rest
}) {
  const dark = tone !== 'light';
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      position: 'absolute',
      left: 28,
      top: 13,
      right: 28,
      textAlign: align,
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-display)',
      fontWeight: 'var(--weight-display)',
      fontSize: size === 'long' ? 'var(--slide-title-long)' : 'var(--slide-title)',
      lineHeight: 'var(--leading-display)',
      textTransform: 'uppercase',
      color: dark ? 'var(--text-on-dark)' : 'var(--text-title)'
    }
  }, title), subtitle && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-sans)',
      fontSize: 'var(--slide-subtitle)',
      lineHeight: 'var(--leading-snug)',
      marginTop: 6,
      color: dark ? 'var(--alten-sky)' : 'var(--text-subtitle)'
    }
  }, subtitle));
}
Object.assign(__ds_scope, { SlideTitle });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/slide/SlideTitle.jsx", error: String((e && e.message) || e) }); }

// components/ui/Button.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** Intentional addition — the source templates are PowerPoint and contain no
 *  interactive controls. Built strictly from brand tokens: square corners,
 *  Arial Black uppercase label with wide tracking, navy / blue / outline. */
function Button({
  children,
  variant = 'primary',
  size = 'md',
  disabled = false,
  icon,
  as = 'button',
  href,
  style,
  ...rest
}) {
  const pad = size === 'sm' ? '8px 16px' : size === 'lg' ? '16px 32px' : '12px 24px';
  const fs = size === 'sm' ? 'var(--text-xs)' : size === 'lg' ? 'var(--text-md)' : 'var(--text-sm)';
  const base = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 10,
    padding: pad,
    fontFamily: 'var(--font-display)',
    fontWeight: 'var(--weight-display)',
    fontSize: fs,
    textTransform: 'uppercase',
    letterSpacing: 'var(--tracking-wide)',
    borderRadius: 'var(--radius-none)',
    border: 'var(--border-w) solid transparent',
    cursor: disabled ? 'not-allowed' : 'pointer',
    textDecoration: 'none',
    opacity: disabled ? 'var(--disabled-opacity)' : 1,
    transition: 'background var(--duration-fast) var(--ease-standard),color var(--duration-fast) var(--ease-standard)'
  };
  const skin = {
    primary: {
      background: 'var(--alten-navy)',
      color: 'var(--alten-white)'
    },
    blue: {
      background: 'var(--alten-blue)',
      color: 'var(--alten-white)'
    },
    outline: {
      background: 'transparent',
      color: 'var(--alten-navy)',
      borderColor: 'var(--alten-navy)'
    },
    ghost: {
      background: 'transparent',
      color: 'var(--alten-blue)'
    },
    onDark: {
      background: 'var(--alten-white)',
      color: 'var(--alten-navy)'
    }
  }[variant] || {};
  const Tag = as === 'a' ? 'a' : 'button';
  return /*#__PURE__*/React.createElement(Tag, _extends({
    href: as === 'a' ? href : undefined,
    disabled: Tag === 'button' ? disabled : undefined,
    style: {
      ...base,
      ...skin,
      ...style
    }
  }, rest), icon, children);
}
Object.assign(__ds_scope, { Button });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/ui/Button.jsx", error: String((e && e.message) || e) }); }

// tools/dump.js
try { (() => {
globalThis.dumpSlide = async function (z, path) {
  const x = await z.readText(path);
  const out = [];
  const sldSz = null;
  // split by shapes
  const shapes = x.split(/(?=<p:sp>|<p:pic>|<p:graphicFrame>|<p:grpSp>)/);
  for (const s of shapes) {
    const nm = (s.match(/<p:cNvPr[^>]*name="([^"]*)"/) || [])[1];
    if (!nm) continue;
    const off = s.match(/<a:off x="(-?\d+)" y="(-?\d+)"\/><a:ext cx="(\d+)" cy="(\d+)"/);
    const geo = off ? `@${(off[1] / 12700).toFixed(0)},${(off[2] / 12700).toFixed(0)} ${(off[3] / 12700).toFixed(0)}x${(off[4] / 12700).toFixed(0)}pt` : '';
    const fill = [...s.matchAll(/<a:solidFill><a:(srgbClr val|schemeClr val)="([^"]+)"/g)].map(m => m[2]).join(',');
    const prst = (s.match(/prstGeom prst="([^"]+)"/) || [])[1] || '';
    const runs = [...s.matchAll(/<a:rPr([^>]*)\/?>([\s\S]*?)?<a:t>([^<]*)<\/a:t>/g)].map(m => {
      const a = m[1];
      const sz = (a.match(/sz="(\d+)"/) || [])[1];
      const b = /b="1"/.test(a) ? 'B' : '';
      const caps = (a.match(/cap="(\w+)"/) || [])[1] || '';
      const face = (m[2] || '').match(/latin typeface="([^"]+)"/);
      const col = (m[2] || '').match(/(srgbClr val|schemeClr val)="([^"]+)"/);
      const spc = (a.match(/spc="(-?\d+)"/) || [])[1];
      return `[${face ? face[1] : ''} ${sz ? sz / 100 + 'pt' : ''}${b} ${col ? col[2] : ''} ${caps} ${spc ? 'spc' + spc : ''}] "${m[3]}"`;
    });
    out.push(`  ${nm} ${geo} ${prst} fill:${fill}\n    ` + runs.join('\n    '));
  }
  return out.join('\n');
};
})(); } catch (e) { __ds_ns.__errors.push({ path: "tools/dump.js", error: String((e && e.message) || e) }); }

// tools/ico.js
try { (() => {
globalThis.icoExtract = function (xml, opts) {
  opts = opts || {};
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  const A = 'http://schemas.openxmlformats.org/drawingml/2006/main';
  const P = 'http://schemas.openxmlformats.org/presentationml/2006/main';
  const q = (el, tag) => el.getElementsByTagNameNS(A, tag);
  const q1 = (el, tag) => q(el, tag)[0];
  const kid = (el, nm) => [...el.children].filter(c => c.localName === nm)[0];
  function xfrmOf(el) {
    const spPr = kid(el, 'spPr') || kid(el, 'grpSpPr');
    if (!spPr) return null;
    const x = [...spPr.children].filter(c => c.localName === 'xfrm')[0];
    if (!x) return null;
    const off = q1(x, 'off'),
      ext = q1(x, 'ext'),
      chOff = q1(x, 'chOff'),
      chExt = q1(x, 'chExt');
    return {
      x: +off.getAttribute('x'),
      y: +off.getAttribute('y'),
      cx: +ext.getAttribute('cx'),
      cy: +ext.getAttribute('cy'),
      chx: chOff ? +chOff.getAttribute('x') : null,
      chy: chOff ? +chOff.getAttribute('y') : null,
      chcx: chExt ? +chExt.getAttribute('cx') : null,
      chcy: chExt ? +chExt.getAttribute('cy') : null,
      rot: +(x.getAttribute('rot') || 0),
      flipH: x.getAttribute('flipH') === '1',
      flipV: x.getAttribute('flipV') === '1'
    };
  }
  function fillOf(el) {
    const spPr = kid(el, 'spPr') || kid(el, 'grpSpPr');
    if (!spPr) return null;
    const direct = [...spPr.children].filter(c => ['noFill', 'solidFill', 'gradFill', 'blipFill', 'pattFill'].includes(c.localName))[0];
    if (!direct) return null;
    if (direct.localName === 'noFill') return 'none';
    if (direct.localName !== 'solidFill') return null;
    const s = q1(direct, 'srgbClr');
    if (s) return '#' + s.getAttribute('val');
    const sc = q1(direct, 'schemeClr');
    if (sc) return '@' + sc.getAttribute('val');
    return null;
  }
  function lnOf(el, mapS) {
    const spPr = kid(el, 'spPr');
    if (!spPr) return null;
    const ln = [...spPr.children].filter(c => c.localName === 'ln')[0];
    if (!ln) return null;
    if (q1(ln, 'noFill')) return null;
    const sf = q1(ln, 'solidFill');
    let col = null;
    if (sf) {
      const s = q1(sf, 'srgbClr');
      const sc = q1(sf, 'schemeClr');
      col = s ? '#' + s.getAttribute('val') : sc ? '@' + sc.getAttribute('val') : null;
    }
    const w = +(ln.getAttribute('w') || 0);
    if (!col && !w) return null;
    return {
      col: col || '@inherit',
      w: (w || 9525) * mapS
    };
  }
  function pathData(sp, sx, sy, ox, oy, fh, fv, W, H) {
    const cg = q1(sp, 'custGeom');
    if (!cg) return null;
    const out = [];
    for (const path of q(cg, 'path')) {
      const pw = +(path.getAttribute('w') || 0),
        ph = +(path.getAttribute('h') || 0);
      const fx = pw ? 1 / pw : 0,
        fy = ph ? 1 / ph : 0;
      const X = v => fh ? ox + W - +v * fx * sx : ox + +v * fx * sx;
      const Y = v => fv ? oy + H - +v * fy * sy : oy + +v * fy * sy;
      let cur = [0, 0];
      for (const c of path.children) {
        const pts = [...c.getElementsByTagNameNS(A, 'pt')];
        const nm = c.localName;
        if (nm === 'moveTo') {
          cur = [X(pts[0].getAttribute('x')), Y(pts[0].getAttribute('y'))];
          out.push('M' + cur[0].toFixed(2) + ' ' + cur[1].toFixed(2));
        } else if (nm === 'lnTo') {
          cur = [X(pts[0].getAttribute('x')), Y(pts[0].getAttribute('y'))];
          out.push('L' + cur[0].toFixed(2) + ' ' + cur[1].toFixed(2));
        } else if (nm === 'cubicBezTo') {
          const a = pts.map(p => [X(p.getAttribute('x')), Y(p.getAttribute('y'))]);
          cur = a[2];
          out.push('C' + a.map(p => p[0].toFixed(2) + ' ' + p[1].toFixed(2)).join(' '));
        } else if (nm === 'quadBezTo') {
          const a = pts.map(p => [X(p.getAttribute('x')), Y(p.getAttribute('y'))]);
          cur = a[1];
          out.push('Q' + a.map(p => p[0].toFixed(2) + ' ' + p[1].toFixed(2)).join(' '));
        } else if (nm === 'arcTo') {
          const wR = +c.getAttribute('wR') * fx * sx,
            hR = +c.getAttribute('hR') * fy * sy;
          const st = +c.getAttribute('stAng') / 60000 * Math.PI / 180,
            sw = +c.getAttribute('swAng') / 60000 * Math.PI / 180;
          const ccx = cur[0] - wR * Math.cos(st),
            ccy = cur[1] - hR * Math.sin(st);
          const ex = ccx + wR * Math.cos(st + sw),
            ey = ccy + hR * Math.sin(st + sw);
          const large = Math.abs(sw) > Math.PI ? 1 : 0,
            sweep = sw > 0 ? 1 : 0;
          out.push('A' + wR.toFixed(2) + ' ' + hR.toFixed(2) + ' 0 ' + large + ' ' + sweep + ' ' + ex.toFixed(2) + ' ' + ey.toFixed(2));
          cur = [ex, ey];
        } else if (nm === 'close') {
          out.push('Z');
        }
      }
    }
    return out.join(' ');
  }
  // walk a top-level shape/group, produce {paths:[{d,fill}], box}
  function collect(node, map, acc, inheritFill) {
    const kids = [...node.children].filter(c => ['sp', 'grpSp', 'pic'].includes(c.localName));
    for (const k of kids) {
      const f = fillOf(k) || inheritFill;
      if (k.localName === 'grpSp') {
        const xf = xfrmOf(k);
        let m2 = map;
        if (xf && xf.chcx) {
          const s2x = xf.cx / xf.chcx,
            s2y = xf.cy / xf.chcy;
          m2 = {
            sx: map.sx * s2x,
            sy: map.sy * s2y,
            ox: map.ox + (xf.x - xf.chx * s2x) * map.sx,
            oy: map.oy + (xf.y - xf.chy * s2y) * map.sy
          };
        }
        collect(k, m2, acc, f);
      } else if (k.localName === 'sp') {
        const xf = xfrmOf(k);
        if (!xf) continue;
        const ox = map.ox + xf.x * map.sx,
          oy = map.oy + xf.y * map.sy;
        const d = pathData(k, xf.cx * map.sx, xf.cy * map.sy, ox, oy, xf.flipH, xf.flipV, xf.cx * map.sx, xf.cy * map.sy);
        if (d) acc.push({
          d,
          fill: f,
          ln: lnOf(k, (map.sx + map.sy) / 2)
        });
      }
    }
  }
  const results = [];
  const spTree = doc.getElementsByTagNameNS(P, 'spTree')[0];
  const labels = [];
  const nodes = [];
  const nameOf = n => {
    const c = kid(kid(n, 'nvSpPr') || kid(n, 'nvGrpSpPr') || n, 'cNvPr');
    return c ? c.getAttribute('name') : '';
  };
  (function walk(parent, map, inGraphic) {
    for (const k of [...parent.children]) {
      if (!['sp', 'grpSp', 'pic'].includes(k.localName)) continue;
      const xf = xfrmOf(k);
      if (!xf) continue;
      const abs = {
        x: map.ox + xf.x * map.sx,
        y: map.oy + xf.y * map.sy,
        cx: xf.cx * map.sx,
        cy: xf.cy * map.sy
      };
      const isG = (opts.match || /^Graphique/i).test(nameOf(k));
      if (k.localName === 'sp') {
        const tx = [...k.getElementsByTagNameNS(A, 't')].map(t => t.textContent).join(' ').trim();
        if (tx) labels.push({
          tx,
          x: abs.x + abs.cx / 2,
          cy: abs.y + abs.cy / 2
        });
      }
      if (isG && !inGraphic) {
        nodes.push({
          node: k,
          map,
          abs
        });
      }
      if (k.localName === 'grpSp') {
        let m2 = map;
        if (xf.chcx) {
          const s2x = xf.cx / xf.chcx,
            s2y = xf.cy / xf.chcy;
          m2 = {
            sx: map.sx * s2x,
            sy: map.sy * s2y,
            ox: map.ox + (xf.x - xf.chx * s2x) * map.sx,
            oy: map.oy + (xf.y - xf.chy * s2y) * map.sy
          };
        }
        walk(k, m2, inGraphic || isG);
      }
    }
  })(spTree, {
    sx: 1,
    sy: 1,
    ox: 0,
    oy: 0
  }, false);
  for (const {
    node,
    map,
    abs
  } of nodes) {
    const name = nameOf(node);
    const xf0 = xfrmOf(node);
    const xf = {
      x: abs.x,
      y: abs.y,
      cx: abs.cx,
      cy: abs.cy
    };
    const acc = [];
    if (node.localName === 'grpSp') {
      const sx = xf0.chcx ? xf0.cx / xf0.chcx * map.sx : map.sx,
        sy = xf0.chcy ? xf0.cy / xf0.chcy * map.sy : map.sy;
      collect(node, {
        sx,
        sy,
        ox: abs.x - (xf0.chx || 0) * sx,
        oy: abs.y - (xf0.chy || 0) * sy
      }, acc, fillOf(node));
    } else {
      const d = pathData(node, xf.cx, xf.cy, xf.x, xf.y, xf0.flipH, xf0.flipV, xf.cx, xf.cy);
      if (d) acc.push({
        d,
        fill: fillOf(node),
        ln: lnOf(node, map.sx)
      });
    }
    if (!acc.length) continue;
    // label: nearest text box whose vertical center is below the icon and horizontally overlapping
    const icx = xf.x + xf.cx / 2,
      ibot = xf.y + xf.cy;
    let best = null,
      bestD = Infinity;
    for (const l of labels) {
      const dx = Math.abs(l.x - icx),
        dy = l.cy - ibot;
      if (dy < -xf.cy * 0.6 || dy > xf.cy * 1.9) continue;
      if (dx > xf.cx * 1.4) continue;
      const dist = dx * 0.6 + Math.abs(dy);
      if (dist < bestD) {
        bestD = dist;
        best = l.tx;
      }
    }
    results.push({
      name,
      label: best,
      x: xf.x,
      y: xf.y,
      w: xf.cx,
      h: xf.cy,
      paths: acc
    });
  }
  return results;
};
globalThis.icoMerge = function (rs) {
  const out = [];
  for (const r of rs) {
    let hit = null;
    for (const o of out) {
      if (o.name !== r.name) continue;
      const ox2 = o.x + o.w,
        oy2 = o.y + o.h,
        rx2 = r.x + r.w,
        ry2 = r.y + r.h;
      const gapX = Math.max(o.x - rx2, r.x - ox2),
        gapY = Math.max(o.y - ry2, r.y - oy2);
      const tol = Math.max(o.w, o.h, r.w, r.h) * 0.35;
      if (gapX < tol && gapY < tol) {
        hit = o;
        break;
      }
    }
    if (hit) {
      const nx = Math.min(hit.x, r.x),
        ny = Math.min(hit.y, r.y);
      const nx2 = Math.max(hit.x + hit.w, r.x + r.w),
        ny2 = Math.max(hit.y + hit.h, r.y + r.h);
      hit.x = nx;
      hit.y = ny;
      hit.w = nx2 - nx;
      hit.h = ny2 - ny;
      hit.paths = hit.paths.concat(r.paths);
      hit.label = hit.label || r.label;
    } else out.push({
      ...r,
      paths: r.paths.slice()
    });
  }
  return out;
};
globalThis.icoSvg = function (r, theme) {
  const pad = 0;
  const vb = [r.x, r.y, r.w, r.h];
  const W = Math.max(1, Math.round(r.w / 1000)),
    H = Math.max(1, Math.round(r.h / 1000));
  const fills = new Set(r.paths.map(p => p.fill || '@inherit').filter(f => f !== 'none'));
  const mono = fills.size <= 1;
  const body = r.paths.map(p => {
    let f = p.fill;
    if (f !== 'none') {
      if (mono || !f || f[0] === '@') f = 'var(--icon-color,#1D93C9)';
    }
    let s = '';
    if (p.ln) {
      let c = p.ln.col;
      if (mono || c[0] === '@') c = 'var(--icon-color,#1D93C9)';
      s = ' stroke="' + c + '" stroke-width="' + p.ln.w.toFixed(1) + '" stroke-linecap="round" stroke-linejoin="round"';
    }
    const st = f === 'var(--icon-color,#1D93C9)' ? ' fill="#1D93C9" style="fill:var(--icon-color,#1D93C9)"' : ' fill="' + f + '"';
    return '<path' + st + s + ' d="' + p.d + '"/>';
  }).join('');
  return '<svg xmlns="http://www.w3.org/2000/svg" width="' + W + '" height="' + H + '" viewBox="' + vb.map(v => +v.toFixed(1)).join(' ') + '">' + body + '</svg>';
};
})(); } catch (e) { __ds_ns.__errors.push({ path: "tools/ico.js", error: String((e && e.message) || e) }); }

// tools/icocat.js
try { (() => {
globalThis.ICO_CATS = {
  2: 'sectors',
  3: 'sectors',
  4: 'sectors',
  5: 'sectors',
  6: 'business',
  7: 'people',
  8: 'project',
  9: 'digital',
  10: 'security',
  11: 'commitments',
  12: 'communication',
  13: 'misc',
  14: 'illustrative'
};
globalThis.icoSlug = function (s) {
  return s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[«»"'’]/g, '').replace(/&/g, ' and ').replace(/\|/g, ' ').replace(/[()\/,.:]/g, ' ').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 46);
};
globalThis.icoSimple = function (r) {
  if (r.paths.length > 1) return false;
  const cmds = (r.paths[0].d.match(/[MLCQAZ]/g) || []).length;
  return cmds < 7;
};
})(); } catch (e) { __ds_ns.__errors.push({ path: "tools/icocat.js", error: String((e && e.message) || e) }); }

// tools/unzip.js
try { (() => {
globalThis.unzip = async function (blob) {
  const buf = new Uint8Array(await blob.arrayBuffer());
  const dv = new DataView(buf.buffer);
  let eocd = -1;
  for (let i = buf.length - 22; i >= Math.max(0, buf.length - 70000); i--) {
    if (dv.getUint32(i, true) === 0x06054b50) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) throw new Error('no eocd');
  let cdOff = dv.getUint32(eocd + 16, true);
  let n = dv.getUint16(eocd + 10, true);
  if (cdOff === 0xffffffff || n === 0xffff) {
    for (let i = eocd - 20; i >= 0; i--) {
      if (dv.getUint32(i, true) === 0x07064b50) {
        const z64 = Number(dv.getBigUint64(i + 8, true));
        n = Number(dv.getBigUint64(z64 + 32, true));
        cdOff = Number(dv.getBigUint64(z64 + 48, true));
        break;
      }
    }
  }
  const entries = {};
  let p = cdOff;
  for (let i = 0; i < n; i++) {
    if (dv.getUint32(p, true) !== 0x02014b50) break;
    const method = dv.getUint16(p + 10, true);
    let csize = dv.getUint32(p + 20, true);
    let usize = dv.getUint32(p + 24, true);
    const nameLen = dv.getUint16(p + 28, true);
    const extraLen = dv.getUint16(p + 30, true);
    const commentLen = dv.getUint16(p + 32, true);
    let lho = dv.getUint32(p + 42, true);
    const name = new TextDecoder().decode(buf.subarray(p + 46, p + 46 + nameLen));
    if (lho === 0xffffffff || csize === 0xffffffff || usize === 0xffffffff) {
      let e = p + 46 + nameLen;
      const end = e + extraLen;
      while (e < end) {
        const id = dv.getUint16(e, true),
          sz = dv.getUint16(e + 2, true);
        if (id === 1) {
          let o = e + 4;
          if (usize === 0xffffffff) {
            usize = Number(dv.getBigUint64(o, true));
            o += 8;
          }
          if (csize === 0xffffffff) {
            csize = Number(dv.getBigUint64(o, true));
            o += 8;
          }
          if (lho === 0xffffffff) {
            lho = Number(dv.getBigUint64(o, true));
            o += 8;
          }
        }
        e += 4 + sz;
      }
    }
    entries[name] = {
      method,
      csize,
      usize,
      lho
    };
    p += 46 + nameLen + extraLen + commentLen;
  }
  const read = async name => {
    const e = entries[name];
    if (!e) throw new Error('missing ' + name);
    const lnameLen = dv.getUint16(e.lho + 26, true);
    const lextraLen = dv.getUint16(e.lho + 28, true);
    const start = e.lho + 30 + lnameLen + lextraLen;
    const data = buf.subarray(start, start + e.csize);
    if (e.method === 0) return new Blob([data]);
    const ds = new DecompressionStream('deflate-raw');
    const s = new Blob([data]).stream().pipeThrough(ds);
    return await new Response(s).blob();
  };
  return {
    entries,
    names: Object.keys(entries),
    read,
    readText: async n => await (await read(n)).text()
  };
};
})(); } catch (e) { __ds_ns.__errors.push({ path: "tools/unzip.js", error: String((e && e.message) || e) }); }

// ui_kits/presentation/DeckShell.jsx
try { (() => {
/* global React, DECK */
const deckShellStyles = {
  page: {
    margin: 0,
    minHeight: '100vh',
    background: '#F4F4F6',
    fontFamily: 'var(--font-text)',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 18,
    padding: '22px 0 30px'
  },
  stage: {
    boxShadow: 'var(--shadow-cover)',
    background: '#fff'
  },
  rail: {
    display: 'flex',
    gap: 8,
    flexWrap: 'wrap',
    justifyContent: 'center',
    maxWidth: 1180
  },
  chip: on => ({
    fontFamily: 'var(--font-display)',
    fontWeight: 700,
    fontSize: 11,
    textTransform: 'uppercase',
    letterSpacing: 'var(--tracking-wide)',
    padding: '9px 15px',
    border: 'none',
    cursor: 'pointer',
    background: on ? 'var(--alten-navy)' : '#fff',
    color: on ? '#fff' : 'var(--alten-navy)',
    boxShadow: on ? 'none' : 'inset 0 0 0 1px var(--alten-grey-light)',
    transition: 'background var(--duration-fast) var(--ease-standard)'
  }),
  meta: {
    fontSize: 12,
    color: 'var(--text-muted)',
    letterSpacing: '.04em',
    textTransform: 'uppercase'
  }
};
function DeckShell() {
  const [i, setI] = React.useState(0);
  const go = n => setI((n + DECK.length) % DECK.length);
  React.useEffect(() => {
    const h = e => {
      if (e.key === 'ArrowRight' || e.key === ' ') {
        e.preventDefault();
        go(i + 1);
      }
      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        go(i - 1);
      }
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [i]);
  const Slide = DECK[i].el;
  return /*#__PURE__*/React.createElement("div", {
    style: deckShellStyles.page
  }, /*#__PURE__*/React.createElement("div", {
    style: deckShellStyles.stage,
    onClick: () => go(i + 1)
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 1180,
      height: 663.75,
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      transform: 'scale(' + 1180 / 960 + ')',
      transformOrigin: 'top left'
    }
  }, /*#__PURE__*/React.createElement(Slide, null)))), /*#__PURE__*/React.createElement("div", {
    style: deckShellStyles.rail
  }, DECK.map((s, n) => /*#__PURE__*/React.createElement("button", {
    key: s.id,
    style: deckShellStyles.chip(n === i),
    onClick: () => setI(n)
  }, s.label))), /*#__PURE__*/React.createElement("div", {
    style: deckShellStyles.meta
  }, i + 1, " / ", DECK.length, " \u2014 click the slide or use \u2190 \u2192"));
}
Object.assign(window, {
  DeckShell
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/presentation/DeckShell.jsx", error: String((e && e.message) || e) }); }

// ui_kits/presentation/Slides.jsx
try { (() => {
/* global React */
const {
  SlideFrame,
  SlideTitle,
  ChapterHeading,
  SectionLabel,
  BulletList,
  KeyFigure,
  ColumnCard,
  Quote,
  Logo,
  Icon,
  DataTable
} = window.ALTENDesignSystem_4bbc3a;
const B = '../../';
const IMG = n => B + 'assets/images/' + n + '.jpg';

/* Slides are authored in the master's 960 x 540 coordinate space; SlideFrame
   scales the whole tree to whatever width it is given. */

function CoverSlide() {
  return /*#__PURE__*/React.createElement(SlideFrame, {
    bar: "none",
    bleed: true,
    base: B
  }, /*#__PURE__*/React.createElement("img", {
    src: IMG('aerial-interchange'),
    alt: "",
    style: {
      position: 'absolute',
      left: 0,
      top: 0,
      width: 960,
      height: 475,
      objectFit: 'cover'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 0,
      top: 0,
      width: 960,
      height: 475,
      background: 'var(--scrim-photo)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 0,
      bottom: 0,
      width: 960,
      height: 65,
      background: 'var(--alten-white)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 230,
      top: 210,
      color: '#fff'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-display)',
      fontWeight: 700,
      textTransform: 'uppercase',
      lineHeight: .9,
      fontSize: 29
    }
  }, "Building tomorrow\u2019s"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-sans)',
      textTransform: 'uppercase',
      letterSpacing: 'var(--tracking-wide)',
      lineHeight: .9,
      fontSize: 48,
      marginTop: 4
    }
  }, "World today")), /*#__PURE__*/React.createElement(Logo, {
    variant: "full",
    tone: "white",
    height: 132,
    base: B,
    style: {
      position: 'absolute',
      left: 434,
      top: 405
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 33,
      bottom: 20,
      fontFamily: 'var(--font-sans)',
      fontWeight: 700,
      fontSize: 16,
      color: 'var(--alten-blue)'
    }
  }, "Group Communications"), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      right: 33,
      bottom: 21,
      fontFamily: 'var(--font-sans)',
      fontSize: 14,
      color: 'var(--text-title)'
    }
  }, "03 / 2026"));
}
function SummarySlide() {
  const rows = [['1.', 'Who we are'], ['2.', 'Research & innovation'], ['3.', 'Sectors we serve'], ['4.', 'CSR commitment'], ['5.', 'Working with ALTEN']];
  return /*#__PURE__*/React.createElement(SlideFrame, {
    pageNumber: 2,
    total: 24,
    base: B
  }, /*#__PURE__*/React.createElement(SlideTitle, {
    title: "Summary",
    subtitle: "ALTEN Group presentation \u2014 2026"
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 28,
      top: 128,
      width: 450
    }
  }, rows.map(([n, t]) => /*#__PURE__*/React.createElement("div", {
    key: n,
    style: {
      display: 'flex',
      alignItems: 'baseline',
      gap: 16,
      padding: '13px 0',
      borderBottom: '1px solid var(--border-hairline)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-display)',
      fontWeight: 700,
      fontSize: 24,
      color: 'var(--alten-blue)',
      width: 36
    }
  }, n), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-display)',
      fontWeight: 700,
      fontSize: 21,
      textTransform: 'uppercase',
      color: 'var(--text-title)'
    }
  }, t)))), /*#__PURE__*/React.createElement("img", {
    src: IMG('people-frame'),
    alt: "",
    style: {
      position: 'absolute',
      right: 0,
      top: 0,
      width: 390,
      height: 540,
      objectFit: 'cover'
    }
  }));
}
function ChapterSlide() {
  return /*#__PURE__*/React.createElement(SlideFrame, {
    tone: "gradient",
    bar: "white",
    pageNumber: 9,
    total: 24,
    base: B
  }, /*#__PURE__*/React.createElement(ChapterHeading, {
    number: 2,
    title: "Innovating for a sustainable future",
    emphasis: "sustainable"
  }));
}
function SectorsSlide() {
  const cards = [['aircraft', 'Aeronautics, Space & Defence', 'Complex, highly technical programmes across the value chain of the most prestigious companies worldwide.'], ['robotics', 'Industrial equipment & electronics', 'Manufacturing engineering, quality and industrialisation for European industry.'], ['abstract-data', 'Banking, finance & insurance', 'Data, digital continuity and IT services for regulated environments.']];
  return /*#__PURE__*/React.createElement(SlideFrame, {
    pageNumber: 15,
    total: 24,
    base: B
  }, /*#__PURE__*/React.createElement(SlideTitle, {
    title: "Where we operate",
    subtitle: "Twelve sectors, one engineering model"
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 24,
      top: 115,
      right: 24,
      display: 'grid',
      gridTemplateColumns: 'repeat(3,1fr)',
      gap: 16
    }
  }, cards.map(([img, t, b]) => /*#__PURE__*/React.createElement(ColumnCard, {
    key: t,
    image: IMG(img),
    title: t
  }, b))), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 24,
      bottom: 46,
      right: 24,
      display: 'flex',
      gap: 26,
      alignItems: 'center'
    }
  }, [['sectors', 'aeronautics'], ['sectors', 'automotive'], ['sectors', 'rail'], ['sectors', 'nuclear'], ['sectors', 'life-science'], ['sectors', 'naval'], ['sectors', 'telecoms-and-media'], ['sectors', 'banking']].map(([g, n]) => /*#__PURE__*/React.createElement(Icon, {
    key: n,
    group: g,
    name: n,
    size: 26,
    base: B
  }))));
}
function FiguresSlide() {
  return /*#__PURE__*/React.createElement(SlideFrame, {
    pageNumber: 4,
    total: 24,
    base: B
  }, /*#__PURE__*/React.createElement(SlideTitle, {
    title: "ALTEN in 2026",
    subtitle: "Founded in 1988 \u2014 leader in Engineering, outsourced R&D and IT Services"
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 28,
      top: 128,
      right: 28,
      display: 'grid',
      gridTemplateColumns: 'repeat(4,1fr)',
      gap: 22
    }
  }, /*#__PURE__*/React.createElement(KeyFigure, {
    value: "57,400",
    label: "Employees"
  }), /*#__PURE__*/React.createElement(KeyFigure, {
    value: "51,000",
    label: "Engineers"
  }), /*#__PURE__*/React.createElement(KeyFigure, {
    value: "+6,500",
    label: "Clients"
  }), /*#__PURE__*/React.createElement(KeyFigure, {
    value: "+30",
    label: "Countries"
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 28,
      top: 300,
      right: 28,
      height: 1,
      background: 'var(--border-hairline)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 28,
      top: 330,
      right: 28,
      display: 'grid',
      gridTemplateColumns: 'repeat(3,1fr)',
      gap: 22
    }
  }, /*#__PURE__*/React.createElement(KeyFigure, {
    size: "sm",
    value: "\u20AC4.10 billion",
    label: "In revenue",
    note: "2025"
  }), /*#__PURE__*/React.createElement(KeyFigure, {
    size: "sm",
    value: "11 Labs",
    label: "Around the world",
    note: "Sustainable innovation"
  }), /*#__PURE__*/React.createElement(KeyFigure, {
    size: "sm",
    value: "+100",
    label: "Internal research projects",
    note: "70 % of which are based on AI"
  })));
}
function SplitSlide() {
  return /*#__PURE__*/React.createElement(SlideFrame, {
    pageNumber: 11,
    total: 24,
    base: B
  }, /*#__PURE__*/React.createElement(SlideTitle, {
    title: "Sustainable innovation",
    subtitle: "One of three pillars of the Group CSR strategy"
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 28,
      top: 130,
      width: 470
    }
  }, /*#__PURE__*/React.createElement(SectionLabel, null, "Our approach"), /*#__PURE__*/React.createElement(BulletList, {
    size: "lg",
    items: ['A bottom-up model: consultants in contact with field realities define R&D priorities.', '9 cross-cutting Smart Digital programs answering client challenges.', 'An ecosystem of scientific, technological and academic partners.']
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 26
    }
  }), /*#__PURE__*/React.createElement(Quote, {
    author: "ALTEN Essentials 2026"
  }, "Innovation only makes sense if it has a positive impact over time and on people.")), /*#__PURE__*/React.createElement("img", {
    src: IMG('mountain-summit'),
    alt: "",
    style: {
      position: 'absolute',
      right: 0,
      top: 0,
      width: 400,
      height: 540,
      objectFit: 'cover'
    }
  }));
}
function TableSlide() {
  return /*#__PURE__*/React.createElement(SlideFrame, {
    pageNumber: 18,
    total: 24,
    base: B
  }, /*#__PURE__*/React.createElement(SlideTitle, {
    title: "Turnover evolution",
    subtitle: "France / International split, revenue in \u20ACbn"
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 24,
      top: 120,
      right: 24
    }
  }, /*#__PURE__*/React.createElement(DataTable, {
    align: "right",
    columns: ['Year', 'Turnover €bn', 'France', 'International'],
    rows: [['2019', '2.62', '58.7 %', '41.3 %'], ['2022', '4.07', '68.9 %', '31.1 %'], ['2023', '4.14', '68.1 %', '31.9 %'], ['2024', '4.10', '67.2 %', '32.8 %'], ['2025', '4.10', '65.4 %', '34.6 %']]
  })));
}
function ClosingSlide() {
  return /*#__PURE__*/React.createElement(SlideFrame, {
    tone: "navy",
    bar: "white",
    pageNumber: 24,
    total: 24,
    base: B
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 28,
      top: 172,
      width: 620,
      color: '#fff'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-display)',
      fontWeight: 700,
      fontSize: 35,
      lineHeight: .9,
      textTransform: 'uppercase'
    }
  }, "To learn more about", /*#__PURE__*/React.createElement("br", null), "our vision, commitment & opportunities"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-sans)',
      textTransform: 'uppercase',
      letterSpacing: 'var(--tracking-wide)',
      fontSize: 19,
      color: 'var(--alten-sky)',
      marginTop: 28
    }
  }, "Visit our website"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-display)',
      fontWeight: 700,
      fontSize: 32,
      marginTop: 10
    }
  }, "alten.com")), /*#__PURE__*/React.createElement(Logo, {
    variant: "full",
    tone: "white",
    height: 176,
    base: B,
    style: {
      position: 'absolute',
      right: 52,
      top: 182
    }
  }));
}
const DECK = [{
  id: 'cover',
  label: 'Cover',
  el: CoverSlide
}, {
  id: 'summary',
  label: 'Summary',
  el: SummarySlide
}, {
  id: 'figures',
  label: 'Key figures',
  el: FiguresSlide
}, {
  id: 'chapter',
  label: 'Chapter',
  el: ChapterSlide
}, {
  id: 'sectors',
  label: '3 columns',
  el: SectorsSlide
}, {
  id: 'split',
  label: 'Text + photo',
  el: SplitSlide
}, {
  id: 'table',
  label: 'Table',
  el: TableSlide
}, {
  id: 'closing',
  label: 'Closing',
  el: ClosingSlide
}];
Object.assign(window, {
  DECK,
  CoverSlide,
  SummarySlide,
  ChapterSlide,
  SectorsSlide,
  FiguresSlide,
  SplitSlide,
  TableSlide,
  ClosingSlide
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/presentation/Slides.jsx", error: String((e && e.message) || e) }); }

// ui_kits/print_document/Pages.jsx
try { (() => {
/* global React */
const {
  Logo,
  SectionLabel,
  KeyFigure,
  Icon,
  BulletList,
  AccentBar
} = window.ALTENDesignSystem_4bbc3a;
const B = '../../';
/* A4 portrait = 595 x 842 pt = 794 x 1123 px at 96 dpi, matching
   `2026 A4 ALTEN_Template_Portrait.potx` (7559675 x 10691813 EMU). */
const A4 = {
  width: 794,
  height: 1123,
  position: 'relative',
  background: '#fff',
  overflow: 'hidden',
  boxSizing: 'border-box',
  fontFamily: 'var(--font-text)',
  color: 'var(--text-body)'
};
function CoverPage() {
  return /*#__PURE__*/React.createElement("div", {
    style: A4
  }, /*#__PURE__*/React.createElement("img", {
    src: B + 'assets/images/tech-tunnel.jpg',
    alt: "",
    style: {
      position: 'absolute',
      left: 0,
      top: 0,
      width: 794,
      height: 1079,
      objectFit: 'cover'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 0,
      top: 0,
      width: 794,
      height: 1079,
      background: 'var(--scrim-photo)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 0,
      top: 337,
      width: 794,
      padding: '0 44px',
      boxSizing: 'border-box'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-display)',
      fontWeight: 700,
      fontSize: 53,
      lineHeight: .9,
      textTransform: 'uppercase',
      color: '#fff'
    }
  }, "Very long title of", /*#__PURE__*/React.createElement("br", null), "the presentation")), /*#__PURE__*/React.createElement(Logo, {
    variant: "full",
    tone: "white",
    height: 210,
    base: B,
    style: {
      position: 'absolute',
      left: 170,
      top: 218
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 0,
      bottom: 0,
      width: 794,
      height: 45,
      background: '#fff'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 24,
      bottom: 12,
      fontFamily: 'var(--font-sans)',
      fontWeight: 700,
      fontSize: 15,
      color: 'var(--alten-sky)'
    }
  }, "Xxxxxx Department"), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      right: 24,
      bottom: 13,
      fontFamily: 'var(--font-sans)',
      fontSize: 14,
      color: 'var(--text-title)'
    }
  }, "XX / XX / XXXX"));
}
function TextPage() {
  const para = 'ALTEN supports companies in their technological and sustainable transformation. We carry out complex and highly technical projects throughout the value chain of the most prestigious companies worldwide, across every sector: Aeronautics, Space, Defence, Security & Naval, Automotive, Rail & Mobility, Energy & Environment, Life Sciences & Health, Industrial Equipment & Electronics, Telecoms, Banking, Finance & Insurance, Retail, Services & Medias, Public Services & Government.';
  return /*#__PURE__*/React.createElement("div", {
    style: A4
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 0,
      top: 0,
      bottom: 0,
      width: 8
    }
  }, /*#__PURE__*/React.createElement(AccentBar, {
    tone: "navy"
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '46px 44px 0 52px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-display)',
      fontWeight: 700,
      fontSize: 34,
      lineHeight: .9,
      textTransform: 'uppercase',
      color: 'var(--text-title)'
    }
  }, "Title of the presentation"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-sans)',
      fontSize: 17,
      color: 'var(--text-subtitle)',
      marginTop: 10
    }
  }, "Subtitle of the presentation"), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 40
    }
  }, /*#__PURE__*/React.createElement(SectionLabel, null, "Title of the paragraph"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 15,
      lineHeight: 1.45
    }
  }, para)), /*#__PURE__*/React.createElement("img", {
    src: B + 'assets/images/abstract-glass-wide.jpg',
    alt: "",
    style: {
      display: 'block',
      width: '100%',
      height: 226,
      objectFit: 'cover',
      margin: '34px 0'
    }
  }), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(SectionLabel, null, "Title of the paragraph"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 15,
      lineHeight: 1.45
    }
  }, "Innovation only makes sense if it has a positive impact over time and on people. At a time when the ecological transition is becoming an imperative, technological innovation is an essential lever for transforming our industrial models."), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 18
    }
  }), /*#__PURE__*/React.createElement(BulletList, {
    size: "lg",
    items: ['11 Labs around the world', '9 cross-cutting Smart Digital programs', 'A bottom-up approach driven by consultants in the field']
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      right: 24,
      bottom: 20,
      display: 'flex',
      alignItems: 'center',
      gap: 16
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      color: 'var(--text-faint)'
    }
  }, "2 |"), /*#__PURE__*/React.createElement(Logo, {
    variant: "wordmark",
    tone: "navy",
    height: 7,
    base: B,
    style: {
      width: 56
    }
  })));
}
function FactsheetPage() {
  const sectors = [['aeronautics', 'Aeronautics'], ['space', 'Space'], ['defense-and-security', 'Defence, Security & Naval'], ['automotive', 'Automotive'], ['rail', 'Rail & Mobility'], ['energy-and-environment', 'Energy & Environment'], ['life-science', 'Life Sciences & Health'], ['equipment', 'Industrial Equipment'], ['telecoms-and-media', 'Telecoms'], ['banking-finance-and-insurance', 'Banking, Finance & Insurance'], ['retail-and-services', 'Retail, Services & Media'], ['public-services-and-government', 'Public Services & Government']];
  return /*#__PURE__*/React.createElement("div", {
    style: A4
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      height: 250,
      background: 'var(--surface-navy)',
      padding: '34px 44px',
      boxSizing: 'border-box',
      color: '#fff',
      position: 'relative'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-sans)',
      textTransform: 'uppercase',
      letterSpacing: 'var(--tracking-wide)',
      fontSize: 13,
      color: 'var(--alten-sky)'
    }
  }, "ALTEN Essentials 2026"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-display)',
      fontWeight: 700,
      fontSize: 33,
      lineHeight: .9,
      textTransform: 'uppercase',
      marginTop: 14,
      maxWidth: 520
    }
  }, "We are a world leader in engineering and IT services."), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 14,
      lineHeight: 1.45,
      marginTop: 16,
      maxWidth: 470,
      color: 'var(--alten-sky-pale)'
    }
  }, "At ALTEN, we see our specialists as architects \u2014 today\u2019s designers of tomorrow\u2019s world."), /*#__PURE__*/React.createElement(Logo, {
    variant: "full",
    tone: "white",
    height: 110,
    base: B,
    style: {
      position: 'absolute',
      right: 44,
      top: 34
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 8,
      background: 'var(--gradient-brand-h)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '34px 44px',
      display: 'grid',
      gridTemplateColumns: 'repeat(3,1fr)',
      gap: '26px 22px'
    }
  }, /*#__PURE__*/React.createElement(KeyFigure, {
    size: "sm",
    value: "57,400",
    label: "Employees"
  }), /*#__PURE__*/React.createElement(KeyFigure, {
    size: "sm",
    value: "51,000",
    label: "Engineers"
  }), /*#__PURE__*/React.createElement(KeyFigure, {
    size: "sm",
    value: "+6,500",
    label: "Clients"
  }), /*#__PURE__*/React.createElement(KeyFigure, {
    size: "sm",
    value: "+30",
    label: "Countries"
  }), /*#__PURE__*/React.createElement(KeyFigure, {
    size: "sm",
    value: "\u20AC4.10 billion",
    label: "In revenue"
  }), /*#__PURE__*/React.createElement(KeyFigure, {
    size: "sm",
    value: "11 Labs",
    label: "Around the world"
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '0 44px'
    }
  }, /*#__PURE__*/React.createElement(SectionLabel, null, "Diversified sectoral presence"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(4,1fr)',
      gap: '20px 14px',
      marginTop: 16
    }
  }, sectors.map(([n, l]) => /*#__PURE__*/React.createElement("div", {
    key: n,
    style: {
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      gap: 8,
      textAlign: 'center'
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    group: "sectors",
    name: n,
    size: 38,
    base: B
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-text)',
      fontSize: 11,
      lineHeight: 1.25,
      color: 'var(--text-title)'
    }
  }, l))))), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 44,
      right: 44,
      bottom: 74,
      paddingTop: 18,
      borderTop: '1px solid var(--border-hairline)',
      display: 'flex',
      gap: 26
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement(SectionLabel, {
    size: "sm"
  }, "Engineering / IT split"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      lineHeight: 1.4
    }
  }, "70 % of ALTEN\u2019s activities are dedicated to Engineering & 30 % to IT Services.")), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement(SectionLabel, {
    size: "sm"
  }, "CSR commitment"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      lineHeight: 1.4
    }
  }, "Committed to the United Nations Global Compact since 2010. Score improved from 34/100 in 2012 to 85/100 in 2025."))), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 0,
      bottom: 0,
      width: 794,
      height: 45,
      background: 'var(--surface-navy)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0 24px',
      boxSizing: 'border-box'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-display)',
      fontWeight: 700,
      fontSize: 15,
      letterSpacing: 'var(--tracking-wide)',
      color: '#fff'
    }
  }, "alten.com"), /*#__PURE__*/React.createElement(Logo, {
    variant: "wordmark",
    tone: "white",
    height: 8,
    base: B,
    style: {
      width: 64
    }
  })));
}
const PAGES = [{
  id: 'cover',
  label: 'A4 cover',
  el: CoverPage
}, {
  id: 'text',
  label: 'A4 text page',
  el: TextPage
}, {
  id: 'factsheet',
  label: 'Essentials factsheet',
  el: FactsheetPage
}];
Object.assign(window, {
  PAGES,
  CoverPage,
  TextPage,
  FactsheetPage
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/print_document/Pages.jsx", error: String((e && e.message) || e) }); }

// ui_kits/reference_project/RefProjectSheet.jsx
try { (() => {
/* global React */
const {
  SlideFrame,
  SlideTitle,
  SectionLabel,
  BulletList,
  FactChip,
  IconHeading,
  Icon,
  Logo
} = window.ALTENDesignSystem_4bbc3a;
const B = '../../';

/* The 2026 Reference-Project one-pager. Three text columns under square
   navy icon headers, a gradient "ALTEN ADDED VALUE" panel down the right,
   and a four-fact strip along the bottom. Authored in the master's
   960 x 540 space. */

const COL = {
  fontFamily: 'var(--font-text)',
  fontSize: 12,
  lineHeight: 1.35,
  color: 'var(--text-body)'
};
function AddedValuePanel({
  items
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      right: 0,
      top: 0,
      width: 300,
      height: 540,
      background: 'var(--gradient-panel)',
      color: '#fff',
      padding: '24px 26px',
      boxSizing: 'border-box'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      height: 34,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'flex-end',
      marginBottom: 34
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      background: 'rgba(255,255,255,.14)',
      border: '1px dashed rgba(255,255,255,.55)',
      fontFamily: 'var(--font-text)',
      fontSize: 10,
      letterSpacing: '.06em',
      textTransform: 'uppercase',
      padding: '7px 12px',
      color: 'rgba(255,255,255,.85)'
    }
  }, "Client logo")), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-display)',
      fontWeight: 700,
      fontSize: 24,
      letterSpacing: 'var(--tracking-wider)',
      lineHeight: 1.1
    }
  }, "ALTEN"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-display)',
      fontWeight: 700,
      fontSize: 24,
      letterSpacing: 'var(--tracking-wider)',
      lineHeight: 1.1,
      color: 'var(--alten-sky)',
      marginBottom: 22
    }
  }, "ADDED VALUE"), /*#__PURE__*/React.createElement(BulletList, {
    tone: "dark",
    size: "md",
    items: items
  }));
}
function Column({
  icon,
  label,
  children,
  style
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 14,
      ...style
    }
  }, /*#__PURE__*/React.createElement(IconHeading, {
    label: label,
    size: 52,
    icon: /*#__PURE__*/React.createElement(Icon, {
      group: icon[0],
      name: icon[1],
      color: "#fff",
      size: 26,
      base: B
    })
  }), /*#__PURE__*/React.createElement("div", {
    style: COL
  }, children));
}
function RefProjectSheet({
  variant = 'image'
}) {
  return /*#__PURE__*/React.createElement(SlideFrame, {
    base: B,
    pageNumber: 1
  }, /*#__PURE__*/React.createElement(SlideTitle, {
    title: variant === 'long' ? 'Automated inspection line for a European rail operator' : 'Short title of reference',
    subtitle: "Subtitle about the project and client",
    size: variant === 'long' ? 'long' : 'regular'
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 24,
      top: variant === 'long' ? 128 : 112,
      width: 620,
      display: 'grid',
      gridTemplateColumns: '150px 1fr 1fr',
      gap: 22
    }
  }, /*#__PURE__*/React.createElement(Column, {
    icon: ['communication', 'info'],
    label: "About"
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0
    }
  }, "A three-year service contract covering design, industrialisation and qualification of an automated inspection line.")), /*#__PURE__*/React.createElement(Column, {
    icon: ['project', 'project'],
    label: "Alten activities"
  }, /*#__PURE__*/React.createElement(BulletList, {
    size: "sm",
    items: ['System architecture and mechanical design', 'Software and control-system development', 'Qualification, test benches and documentation', 'On-site ramp-up with the client engineering team']
  })), /*#__PURE__*/React.createElement(Column, {
    icon: ['digital', 'software'],
    label: "Standards & tools"
  }, /*#__PURE__*/React.createElement(BulletList, {
    size: "sm",
    marker: "pipe",
    items: ['EN 50128 | EN 50657', 'CATIA V5 | Creo', 'Polarion | Jira | Git', 'Python | C++ | Simulink']
  }))), variant === 'video' ? /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 210,
      top: 300,
      width: 300,
      height: 168,
      background: 'var(--alten-grey-100)',
      display: 'grid',
      placeItems: 'center'
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    group: "communication",
    name: "play",
    size: 44,
    base: B
  })) : /*#__PURE__*/React.createElement("img", {
    src: B + 'assets/images/robotics.jpg',
    alt: "",
    style: {
      position: 'absolute',
      left: 210,
      top: 300,
      width: 300,
      height: 168,
      objectFit: 'cover'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 24,
      top: 300,
      width: 160
    }
  }, /*#__PURE__*/React.createElement(SectionLabel, {
    size: "sm"
  }, "Results"), /*#__PURE__*/React.createElement(BulletList, {
    size: "sm",
    items: ['−18 % cycle time', '4 sites rolled out', 'Zero safety findings']
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 24,
      bottom: 34,
      width: 620,
      display: 'flex',
      justifyContent: 'space-between',
      paddingRight: 40
    }
  }, /*#__PURE__*/React.createElement(FactChip, {
    icon: B + 'assets/icons/people/fte-capacity.svg',
    label: "120 FTE"
  }), /*#__PURE__*/React.createElement(FactChip, {
    icon: B + 'assets/icons/project/duration.svg',
    label: "Service contract"
  }), /*#__PURE__*/React.createElement(FactChip, {
    icon: B + 'assets/icons/sectors/rail.svg',
    label: "Rail & Mobility"
  }), /*#__PURE__*/React.createElement(FactChip, {
    icon: B + 'assets/icons/flags/germany.svg',
    label: "Germany"
  })), /*#__PURE__*/React.createElement(AddedValuePanel, {
    items: ['One engineering partner across design, software and qualification', 'Cluster model: expertise pooled across four European sites', 'Digital continuity from requirement to test report', 'Ramp-up handled by ALTEN, no client recruitment needed']
  }));
}
Object.assign(window, {
  RefProjectSheet,
  AddedValuePanel,
  Column
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/reference_project/RefProjectSheet.jsx", error: String((e && e.message) || e) }); }

__ds_ns.AccentBar = __ds_scope.AccentBar;

__ds_ns.Baseline = __ds_scope.Baseline;

__ds_ns.FrameDevice = __ds_scope.FrameDevice;

__ds_ns.Logo = __ds_scope.Logo;

__ds_ns.BulletList = __ds_scope.BulletList;

__ds_ns.ColumnCard = __ds_scope.ColumnCard;

__ds_ns.DataTable = __ds_scope.DataTable;

__ds_ns.FactChip = __ds_scope.FactChip;

__ds_ns.IconHeading = __ds_scope.IconHeading;

__ds_ns.KeyFigure = __ds_scope.KeyFigure;

__ds_ns.NumberedList = __ds_scope.NumberedList;

__ds_ns.Quote = __ds_scope.Quote;

__ds_ns.SectionLabel = __ds_scope.SectionLabel;

__ds_ns.Icon = __ds_scope.Icon;

__ds_ns.ChapterHeading = __ds_scope.ChapterHeading;

__ds_ns.SlideFrame = __ds_scope.SlideFrame;

__ds_ns.SlideTitle = __ds_scope.SlideTitle;

__ds_ns.Button = __ds_scope.Button;

})();
