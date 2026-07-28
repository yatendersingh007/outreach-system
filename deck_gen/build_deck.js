// X Analyst firm-specific pitch deck renderer (pptxgenjs).
// Usage: node build_deck.js <data.json>   (data.json.output = target .pptx path)
// Pure renderer: all content (fixed + custom) comes from the JSON; Python owns it.
// Visual system tuned to the original Kingbird PDF: serif display type, rounded
// borderless cards, gold icons.
const pptxgen = require("pptxgenjs");
const fs = require("fs");
const path = require("path");

const dataPath = process.argv[2];
if (!dataPath) { console.error("usage: node build_deck.js <data.json>"); process.exit(1); }
const d = JSON.parse(fs.readFileSync(dataPath, "utf-8"));

// --- Design system ---------------------------------------------------------
const NAVY = "1B2A4A", WHITE = "FFFFFF", CREAM = "F8F6F1", CARD = "F5F0E8";
const GOLD = "C5A84A", CHARCOAL = "2D3436", LIGHT = "CDD4E0", MUTED = "6B7280";
const NAVYCARD = "223457", CHIP = "2A3F66", DESCGRAY = "55606E";
const SERIF = "Georgia", SANS = "Calibri";       // Part A: serif display + clean sans body
const RAD = 0.08;                                  // rounded-card radius

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.author = "X Analyst";
pres.title = `X Analyst — Built for ${d.firmName || "your firm"}`;

// --- Icons (gold PNGs pre-rendered into deck_gen/icons; graceful if absent) --
const ICON_DIR = path.join(__dirname, "icons");
const _iconCache = {};
function icon(name) {
  if (!name) return null;
  if (name in _iconCache) return _iconCache[name];
  try {
    const buf = fs.readFileSync(path.join(ICON_DIR, name + ".png"));
    return (_iconCache[name] = "image/png;base64," + buf.toString("base64"));
  } catch (e) { return (_iconCache[name] = null); }
}
function addIcon(s, name, x, y, sz) {
  const data = icon(name);
  if (data) s.addImage({ data, x, y, w: sz, h: sz });
  return !!data;
}

// --- Helpers ---------------------------------------------------------------
function rcard(s, x, y, w, h, fill, line) {
  const opt = { x, y, w, h, fill: { color: fill }, rectRadius: RAD };
  opt.line = line ? line : { type: "none" };
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, opt);
}
function sectionLabel(s, text) {
  s.addText((text || "").toUpperCase(), { x: 0.5, y: 0.32, w: 9, h: 0.3, fontFace: SANS, fontSize: 11, color: GOLD, bold: true, charSpacing: 6, margin: 0 });
}
// Shrink a display title so it fits one line at the given width (the original
// deck's long titles sit at ~24-26pt on one line; ours were wrapping/overlapping).
function fitFont(text, wIn, base, min = 24, factor = 125) {
  const n = (text || "").length || 1;
  return Math.max(min, Math.min(base, Math.floor((wIn * factor) / n)));
}
function title(s, text, opts = {}) {
  const w = opts.w ?? 9;
  const fs = fitFont(text, w, opts.fontSize ?? 34);
  s.addText(text, { x: 0.5, y: opts.y ?? 0.6, w, h: opts.h ?? 0.8, fontFace: SERIF, fontSize: fs, bold: true, color: opts.color ?? CHARCOAL, align: "left", valign: "top", margin: 0, wrap: true });
}
function intro(s, text, y, color = MUTED, w = 9) {
  s.addText(text, { x: 0.5, y, w, h: 0.5, fontFace: SANS, fontSize: 12, italic: true, color, margin: 0, lineSpacingMultiple: 1.1 });
}
function lines(items, o) {
  return items.map((t, i) => ({ text: t, options: { breakLine: i < items.length - 1, ...o } }));
}
function bullets(items, o = {}) {
  const b = o.square ? { code: "25AA", indent: 16 } : { indent: 14 };
  const opts = { bullet: b, breakLine: true, paraSpaceAfter: o.paraSpaceAfter ?? 4, color: o.color, fontSize: o.fontSize };
  return items.map((t) => ({ text: t, options: { ...opts } }));
}

// --- Slide 1: Cover (navy) -------------------------------------------------
function cover() {
  const s = pres.addSlide(); s.background = { color: NAVY };
  s.addText("X   A N A L Y S T", { x: 0.5, y: 0.4, w: 9, h: 0.35, fontFace: SANS, fontSize: 13, color: GOLD, bold: true, charSpacing: 5, margin: 0 });
  // Original hierarchy: large white value headline, then the client-name line in gold.
  s.addText(d.coverTagline, { x: 0.5, y: 1.28, w: 9, h: 1.45, fontFace: SERIF, fontSize: 44, bold: true, color: WHITE, margin: 0, valign: "top", lineSpacingMultiple: 1.02 });
  s.addText(d.coverTitle, { x: 0.5, y: 2.82, w: 9, h: 0.85, fontFace: SERIF, fontSize: 40, bold: true, color: GOLD, margin: 0, valign: "top" });
  s.addText(d.coverSubtitle, { x: 0.5, y: 3.85, w: 8.7, h: 1.0, fontFace: SANS, fontSize: 13, color: LIGHT, margin: 0, lineSpacingMultiple: 1.15 });
  s.addText("PREPARED FOR", { x: 0.5, y: 4.78, w: 6, h: 0.25, fontFace: SANS, fontSize: 9, color: GOLD, bold: true, charSpacing: 3, margin: 0 });
  s.addText(d.firmLegal, { x: 0.5, y: 5.02, w: 6.5, h: 0.4, fontFace: SERIF, fontSize: 15, color: WHITE, bold: true, margin: 0 });
  s.addText(`CONFIDENTIAL  |  ${d.year}`, { x: 5.5, y: 5.06, w: 4, h: 0.4, fontFace: SANS, fontSize: 11, color: LIGHT, align: "right", margin: 0 });
}

// --- Slide 2: Agenda (WHITE bg, tall navy cards) ---------------------------
function agenda() {
  const s = pres.addSlide(); s.background = { color: WHITE };
  title(s, d.agenda.title, { y: 0.4, fontSize: 34, h: 0.7 });
  intro(s, d.agenda.subtitle, 1.15);
  const n = d.agenda.items.length, cw = 1.66, gap = (9 - n * cw) / (n - 1), x0 = 0.5;
  const cy = 1.75, ch = 3.4;
  d.agenda.items.forEach((it, i) => {
    const x = x0 + i * (cw + gap);
    rcard(s, x, cy, cw, ch, NAVY);
    s.addText(it.num, { x, y: cy + 0.4, w: cw, h: 0.55, fontFace: SERIF, fontSize: 24, bold: true, color: GOLD, align: "center", margin: 0 });
    s.addText(it.label, { x: x + 0.1, y: cy + 1.1, w: cw - 0.2, h: 0.7, fontFace: SERIF, fontSize: 16, bold: true, color: WHITE, align: "center", valign: "top", margin: 0, lineSpacingMultiple: 1.0 });
    s.addText(it.desc, { x: x + 0.14, y: cy + 1.85, w: cw - 0.28, h: 1.35, fontFace: SANS, fontSize: 10, color: LIGHT, align: "center", valign: "top", margin: 0, lineSpacingMultiple: 1.08 });
  });
}

// --- Slide 3: Firm profile (white) -----------------------------------------
function profile() {
  const s = pres.addSlide(); s.background = { color: WHITE };
  sectionLabel(s, d.profile.section);
  title(s, d.profile.title, { y: 0.6, w: 9, h: 0.7, fontSize: 30 });
  const stats = (d.profile.stats || []).slice(0, 4), nStats = stats.length;
  const bw = nStats >= 3 ? 5.5 : 6.3;      // widen bullet column when few stats
  s.addText(d.profile.lead, { x: 0.5, y: 1.4, w: bw, h: 0.9, fontFace: SERIF, fontSize: 14, italic: true, color: MUTED, margin: 0, lineSpacingMultiple: 1.12 });
  s.addText(bullets(d.profile.bullets, { fontSize: 10.5, color: CHARCOAL, square: true, paraSpaceAfter: 5 }),
    { x: 0.5, y: 2.35, w: bw, h: 2.9, fontFace: SANS, valign: "top", margin: 0 });

  function statBox(x, y, w, h, st) {
    rcard(s, x, y, w, h, CARD);
    s.addText(st.value, { x: x + 0.18, y: y + 0.12, w: w - 0.36, h: 0.42, fontFace: SERIF, fontSize: 22, bold: true, color: GOLD, margin: 0, valign: "top" });
    s.addText(st.label, { x: x + 0.18, y: y + 0.56, w: w - 0.36, h: 0.4, fontFace: SANS, fontSize: 9.5, bold: true, color: CHARCOAL, margin: 0, valign: "top", lineSpacingMultiple: 0.95 });
    if (st.sublabel) s.addText(st.sublabel, { x: x + 0.18, y: y + 0.98, w: w - 0.36, h: 0.26, fontFace: SANS, fontSize: 7.5, color: MUTED, margin: 0, valign: "top" });
  }
  if (nStats === 4) {                        // full 2x2 grid
    const sx = [6.2, 7.95], sy = [1.4, 2.75];
    stats.forEach((st, i) => statBox(sx[i % 2], sy[Math.floor(i / 2)], 1.65, 1.28, st));
  } else if (nStats === 3) {                 // 2 on top + 1 full-width below (no empty cell)
    statBox(6.2, 1.4, 1.65, 1.28, stats[0]);
    statBox(7.95, 1.4, 1.65, 1.28, stats[1]);
    statBox(6.2, 2.75, 3.4, 1.28, stats[2]);
  } else if (nStats > 0) {                   // 1-2 boxes stacked vertically on the right
    const x = 6.95, w = 2.55, h = 1.28;
    stats.forEach((st, i) => statBox(x, 1.5 + i * (h + 0.2), w, h, st));
  }
  if (d.profile.capitalStack) {           // full-width navy callout bar (original style)
    rcard(s, 0.5, 4.95, 9, 0.5, NAVY);
    s.addText([{ text: "Capital stack complexity:  ", options: { bold: true } }, { text: d.profile.capitalStack, options: {} }],
      { x: 0.75, y: 4.95, w: 8.5, h: 0.5, fontFace: SANS, fontSize: 10.5, italic: true, color: GOLD, align: "center", valign: "middle", margin: 0 });
  }
}

// --- Slide 4: Comparison (white) -------------------------------------------
function comparison() {
  // Original slide 4 is a full-navy slide: muted-navy "traditional" card vs a
  // bright GOLD "X Analyst approach" card (navy bold text).
  const s = pres.addSlide(); s.background = { color: NAVY };
  sectionLabel(s, d.comparison.section);
  title(s, d.comparison.title, { y: 0.6, fontSize: 30, color: WHITE });
  intro(s, d.comparison.intro, 1.45, LIGHT);
  const cy = 2.25, ch = 2.5;
  rcard(s, 0.5, cy, 4.35, ch, NAVYCARD);
  s.addText(d.comparison.leftHeader.toUpperCase(), { x: 0.75, y: cy + 0.22, w: 3.9, h: 0.3, fontFace: SANS, fontSize: 11, bold: true, color: "9BA4B5", charSpacing: 3, margin: 0 });
  s.addText(lines(d.comparison.leftItems.map(t => "–   " + t), { color: LIGHT }), { x: 0.75, y: cy + 0.62, w: 3.85, h: ch - 0.8, fontFace: SANS, fontSize: 10.5, margin: 0, paraSpaceAfter: 6, valign: "top" });
  rcard(s, 5.15, cy, 4.35, ch, GOLD);
  s.addText(d.comparison.rightHeader.toUpperCase(), { x: 5.4, y: cy + 0.22, w: 3.9, h: 0.3, fontFace: SANS, fontSize: 11, bold: true, color: NAVY, charSpacing: 3, margin: 0 });
  s.addText(lines(d.comparison.rightItems.map(t => "●   " + t), { color: NAVY, bold: true }), { x: 5.4, y: cy + 0.62, w: 3.85, h: ch - 0.8, fontFace: SANS, fontSize: 10.5, margin: 0, paraSpaceAfter: 6, valign: "top" });
  s.addText(d.comparison.result, { x: 0.5, y: 5.0, w: 9, h: 0.45, fontFace: SANS, fontSize: 10.5, italic: true, color: GOLD, align: "center", margin: 0 });
}

// --- Slide 5: Six functions (white) — cards with gold icons ----------------
function sixFunctions() {
  const s = pres.addSlide(); s.background = { color: WHITE };
  sectionLabel(s, d.sixFunctions.section);
  title(s, d.sixFunctions.title, { y: 0.58, fontSize: 28 });
  intro(s, d.sixFunctions.intro, 1.35);
  const cw = 2.95, ch = 1.55, gx = 0.075, gy = 0.12, x0 = 0.5, y0 = 1.82;
  d.sixFunctions.cards.forEach((c, i) => {
    const x = x0 + (i % 3) * (cw + gx), y = y0 + Math.floor(i / 3) * (ch + gy);
    rcard(s, x, y, cw, ch, CARD);
    const hasIc = addIcon(s, c.icon, x + 0.24, y + 0.2, 0.32);
    const hx = hasIc ? x + 0.66 : x + 0.24;
    s.addText(c.header, { x: hx, y: y + 0.16, w: x + cw - 0.22 - hx, h: 0.58, fontFace: SERIF, fontSize: 12.5, bold: true, color: NAVY, margin: 0, valign: "top", lineSpacingMultiple: 0.95 });
    s.addText(c.desc, { x: x + 0.24, y: y + 0.78, w: cw - 0.46, h: ch - 0.9, fontFace: SANS, fontSize: 9, color: CHARCOAL, margin: 0, lineSpacingMultiple: 1.05, valign: "top" });
  });
  s.addText(d.sixFunctions.footer, { x: 0.5, y: 5.12, w: 9, h: 0.35, fontFace: SANS, fontSize: 9.5, italic: true, color: MUTED, margin: 0 });
}

// --- Slides 6-8: Service detail (white) — icon beside column header --------
function serviceDetail(sd) {
  const s = pres.addSlide(); s.background = { color: WHITE };
  sectionLabel(s, sd.header);
  title(s, sd.title, { y: 0.58, fontSize: 28 });
  const cardY = 1.5, cardH = 3.85, cardW = 4.35;    // tall cream cards (original style)
  const col = (cx, header, iconName, items) => {
    rcard(s, cx, cardY, cardW, cardH, CARD);
    const ix = cx + 0.32, iy = cardY + 0.34;
    const hasIc = addIcon(s, iconName, ix, iy, 0.34);
    s.addText(header, { x: hasIc ? ix + 0.5 : ix, y: iy - 0.05, w: cardW - 0.9, h: 0.42, fontFace: SERIF, fontSize: 15, bold: true, color: NAVY, margin: 0, valign: "top" });
    s.addText(bullets(items, { fontSize: 9.5, color: CHARCOAL, paraSpaceAfter: 4, square: true }),
      { x: cx + 0.34, y: cardY + 0.98, w: cardW - 0.62, h: cardH - 1.15, fontFace: SANS, valign: "top", margin: 0, lineSpacingMultiple: 1.02 });
  };
  col(0.5, sd.leftHeader, sd.leftIcon, sd.leftBullets);
  col(5.15, sd.rightHeader, sd.rightIcon, sd.rightBullets);
}

// --- Slide 9: Why X Analyst (navy) — circular icon chips -------------------
function why() {
  const s = pres.addSlide(); s.background = { color: NAVY };
  title(s, d.why.title, { y: 0.4, fontSize: 32, color: WHITE, h: 0.6 });
  s.addText(d.why.subtitle, { x: 0.5, y: 1.08, w: 9, h: 0.4, fontFace: SANS, fontSize: 13, italic: true, color: LIGHT, margin: 0 });
  const cw = 4.35, ch = 1.42, gx = 0.3, gy = 0.16, x0 = 0.5, y0 = 1.68;
  d.why.cards.forEach((c, i) => {
    const x = x0 + (i % 2) * (cw + gx), y = y0 + Math.floor(i / 2) * (ch + gy);
    rcard(s, x, y, cw, ch, NAVYCARD);
    // circular chip with icon
    s.addShape(pres.shapes.OVAL, { x: x + 0.22, y: y + 0.42, w: 0.55, h: 0.55, fill: { color: CHIP } });
    addIcon(s, c.icon, x + 0.335, y + 0.535, 0.32);
    const tx = x + 0.95;
    s.addText(c.header, { x: tx, y: y + 0.18, w: x + cw - 0.22 - tx, h: 0.35, fontFace: SERIF, fontSize: 14.5, bold: true, color: GOLD, margin: 0 });
    s.addText(c.desc, { x: tx, y: y + 0.55, w: x + cw - 0.22 - tx, h: ch - 0.66, fontFace: SANS, fontSize: 10.5, color: LIGHT, margin: 0, lineSpacingMultiple: 1.05, valign: "top" });
  });
  s.addText(d.why.costLine, { x: 0.5, y: 5.08, w: 9, h: 0.4, fontFace: SANS, fontSize: 11, italic: true, color: GOLD, margin: 0 });
}

// --- Slide 10: Engagement model (white) ------------------------------------
function engagement() {
  const s = pres.addSlide(); s.background = { color: WHITE };
  title(s, d.engagement.title, { y: 0.4, fontSize: 30, h: 0.6 });
  intro(s, d.engagement.intro, 1.15);
  const by = 1.75, bh = 3.35;
  // Left navy card
  const bx = 0.5, bw = 4.35;
  rcard(s, bx, by, bw, bh, NAVY);
  s.addText(d.engagement.boxTitle, { x: bx + 0.3, y: by + 0.28, w: bw - 0.6, h: 0.5, fontFace: SERIF, fontSize: 21, bold: true, color: WHITE, margin: 0 });
  s.addText(d.engagement.boxSub, { x: bx + 0.3, y: by + 0.82, w: bw - 0.6, h: 0.3, fontFace: SANS, fontSize: 10.5, italic: true, color: GOLD, margin: 0 });
  s.addText(d.engagement.bestForLabel.toUpperCase(), { x: bx + 0.3, y: by + 1.22, w: bw - 0.6, h: 0.25, fontFace: SANS, fontSize: 9, bold: true, color: GOLD, charSpacing: 2, margin: 0 });
  s.addText(d.engagement.bestFor, { x: bx + 0.3, y: by + 1.47, w: bw - 0.6, h: 0.6, fontFace: SANS, fontSize: 9.5, italic: true, color: LIGHT, margin: 0, lineSpacingMultiple: 1.05 });
  s.addText(bullets(d.engagement.bullets, { fontSize: 9.5, color: WHITE, paraSpaceAfter: 3, square: true }), { x: bx + 0.3, y: by + 2.18, w: bw - 0.6, h: 1.05, fontFace: SANS, valign: "top", margin: 0 });
  // Right cream card: header + two-column (bold navy label / gray description)
  const rx = 5.15, rw = 4.35;
  rcard(s, rx, by, rw, bh, CARD);
  s.addText(d.engagement.carryHeader, { x: rx + 0.3, y: by + 0.28, w: rw - 0.6, h: 0.4, fontFace: SERIF, fontSize: 15, bold: true, color: NAVY, margin: 0 });
  const rowH = (bh - 1.05) / d.engagement.carry.length;
  let ry = by + 0.92;
  d.engagement.carry.forEach((c) => {
    s.addText(c.label, { x: rx + 0.3, y: ry, w: 1.4, h: rowH, fontFace: SANS, fontSize: 9.5, bold: true, color: NAVY, margin: 0, valign: "top", lineSpacingMultiple: 1.0 });
    s.addText(c.desc, { x: rx + 1.75, y: ry, w: rw - 2.05, h: rowH, fontFace: SANS, fontSize: 9, color: DESCGRAY, margin: 0, valign: "top", lineSpacingMultiple: 1.02 });
    ry += rowH;
  });
  s.addText(d.engagement.footer, { x: 0.5, y: 5.2, w: 9, h: 0.35, fontFace: SANS, fontSize: 9.5, italic: true, color: MUTED, align: "center", margin: 0 });
}

// --- Slide 11: Timeline (white) --------------------------------------------
function timeline() {
  const s = pres.addSlide(); s.background = { color: WHITE };
  title(s, d.timeline.title, { y: 0.4, fontSize: 27, h: 0.6 });
  intro(s, d.timeline.intro, 1.12);
  const n = d.timeline.weeks.length, cw = 2.2, gap = (9 - n * cw) / (n - 1), x0 = 0.5, y = 1.75, ch = 2.9;
  d.timeline.weeks.forEach((wk, i) => {
    const x = x0 + i * (cw + gap);
    rcard(s, x, y, cw, ch, CREAM);
    s.addShape(pres.shapes.OVAL, { x: x + 0.24, y: y + 0.24, w: 0.55, h: 0.55, fill: { color: NAVY } });
    s.addText(String(wk.num), { x: x + 0.24, y: y + 0.24, w: 0.55, h: 0.55, fontFace: SERIF, fontSize: 20, bold: true, color: GOLD, align: "center", valign: "middle", margin: 0 });
    s.addText(wk.week.toUpperCase(), { x: x + 0.24, y: y + 0.9, w: cw - 0.48, h: 0.25, fontFace: SANS, fontSize: 9, bold: true, color: GOLD, charSpacing: 1, margin: 0 });
    s.addText(wk.title, { x: x + 0.24, y: y + 1.15, w: cw - 0.48, h: 0.5, fontFace: SERIF, fontSize: 12.5, bold: true, color: CHARCOAL, margin: 0, valign: "top" });
    s.addText(wk.desc, { x: x + 0.24, y: y + 1.66, w: cw - 0.48, h: ch - 1.78, fontFace: SANS, fontSize: 8.5, color: CHARCOAL, margin: 0, lineSpacingMultiple: 1.02, valign: "top" });
  });
  s.addText(d.timeline.footer, { x: 0.5, y: 4.95, w: 9, h: 0.4, fontFace: SANS, fontSize: 11, italic: true, bold: true, color: CHARCOAL, margin: 0 });
}

// --- Slide 12: Fit points (white) — full-width cream rounded rows ----------
const FIT_ICONS = ["scale-balanced", "coins", "file-lines", "layer-group", "magnifying-glass-dollar"];
// Match each fit row's icon to the FUNCTION it describes (same icon-to-function
// map as slides 5-8), so iconography stays consistent across the deck.
function fitIcon(label, i) {
  const s = (label || "").toLowerCase();
  if (/waterfall|fund account/.test(s)) return "calculator";
  if (/property.*account|property-level|property mgmt/.test(s)) return "layer-group";
  if (/asset manage/.test(s)) return "chart-line";
  if (/underwrit|acquisition|due diligence/.test(s)) return "magnifying-glass-dollar";
  if (/investor|reporting/.test(s)) return "file-lines";
  if (/capital market|debt|refinanc|lender/.test(s)) return "coins";
  return FIT_ICONS[i % FIT_ICONS.length];
}
function fit() {
  const s = pres.addSlide(); s.background = { color: WHITE };
  sectionLabel(s, d.fit.section);
  title(s, d.fit.title, { y: 0.58, fontSize: 28 });
  intro(s, d.fit.intro, 1.35);
  const pts = d.fit.points.slice(0, 5), n = pts.length;
  const top = 1.8, gap = 0.12, availH = 5.4 - top;
  const rowH = (availH - (n - 1) * gap) / n;
  pts.forEach((p, i) => {
    const y = top + i * (rowH + gap);
    rcard(s, 0.5, y, 9.0, rowH, CARD);
    addIcon(s, fitIcon(p.boldLabel, i), 0.75, y + rowH / 2 - 0.16, 0.32);
    s.addText(p.boldLabel, { x: 1.25, y, w: 2.35, h: rowH, fontFace: SERIF, fontSize: 13, bold: true, color: CHARCOAL, margin: 0, valign: "middle", lineSpacingMultiple: 1.0 });
    s.addText(p.description, { x: 3.75, y, w: 5.55, h: rowH, fontFace: SANS, fontSize: 10, color: DESCGRAY, margin: 0, valign: "middle", lineSpacingMultiple: 1.05 });
  });
}

// --- Slide 13: Pilot / next steps (white) ----------------------------------
function pilot() {
  const s = pres.addSlide(); s.background = { color: WHITE };
  sectionLabel(s, d.pilot.section);
  title(s, d.pilot.title, { y: 0.58, fontSize: 28 });
  intro(s, d.pilot.intro, 1.4);
  let y = 1.92; const step = 0.62; let num = 1;
  d.pilot.steps.forEach((st) => {
    s.addShape(pres.shapes.OVAL, { x: 0.5, y, w: 0.5, h: 0.5, fill: { color: NAVY } });
    s.addText(String(num), { x: 0.5, y, w: 0.5, h: 0.5, fontFace: SERIF, fontSize: 18, bold: true, color: GOLD, align: "center", valign: "middle", margin: 0 });
    s.addText(st.week.toUpperCase(), { x: 1.2, y: y + 0.1, w: 1.35, h: 0.4, fontFace: SANS, fontSize: 10.5, bold: true, color: GOLD, charSpacing: 1, margin: 0, valign: "top" });
    s.addText(st.title, { x: 2.5, y: y + 0.07, w: 2.7, h: 0.45, fontFace: SERIF, fontSize: 12.5, bold: true, color: CHARCOAL, margin: 0, valign: "top" });
    s.addText(st.desc, { x: 5.3, y: y + 0.09, w: 4.2, h: 0.45, fontFace: SANS, fontSize: 10, color: MUTED, margin: 0, valign: "top", lineSpacingMultiple: 1.0 });
    y += step; num++;
  });
  rcard(s, 0.5, 5.05, 9, 0.45, NAVY);
  s.addText(d.pilot.nextStep, { x: 0.75, y: 5.05, w: 8.5, h: 0.45, fontFace: SANS, fontSize: 11, italic: true, color: GOLD, align: "center", valign: "middle", margin: 0 });
}

// --- Slide 14: Thank you (navy) --------------------------------------------
function thankYou() {
  const s = pres.addSlide(); s.background = { color: NAVY };
  s.addText("X   A N A L Y S T", { x: 0.5, y: 0.5, w: 9, h: 0.35, fontFace: SANS, fontSize: 13, color: GOLD, bold: true, charSpacing: 5, margin: 0 });
  s.addText(d.thankYou.title, { x: 0.5, y: 1.85, w: 9, h: 1.1, fontFace: SERIF, fontSize: 44, bold: true, color: WHITE, margin: 0 });
  s.addText(d.thankYou.line, { x: 0.5, y: 3.05, w: 9, h: 1.0, fontFace: SANS, fontSize: 15, color: LIGHT, margin: 0, lineSpacingMultiple: 1.15 });
  s.addText(d.thankYou.url, { x: 0.5, y: 4.62, w: 4, h: 0.35, fontFace: SANS, fontSize: 13, bold: true, color: GOLD, margin: 0 });
  s.addText(d.thankYou.founders, { x: 4.0, y: 4.62, w: 5.5, h: 0.35, fontFace: SANS, fontSize: 10.5, color: LIGHT, align: "right", margin: 0 });
}

// --- Render in order -------------------------------------------------------
cover();
agenda();
profile();
comparison();
sixFunctions();
d.serviceDetails.forEach(serviceDetail);   // slides 6,7,8
why();
engagement();
timeline();
fit();
pilot();
thankYou();

pres.writeFile({ fileName: d.output })
  .then((f) => { console.log("WROTE " + f); })
  .catch((e) => { console.error("RENDER_ERROR " + e.message); process.exit(2); });
