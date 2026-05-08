# Advanced Slide Templates

These templates add complex, dashboard-style layouts with higher information density and stronger visual structure. They supplement the base 10 templates.

These layouts are inspired by professional presentation design: multi-zone grids, nested cards, bottom summary bars, icon chip rows, and bordered sections.

---

## Table of Contents

11. [cover_pro](#11-cover_pro) — Cover with bottom stats bar
12. [grid_content](#12-grid_content) — Multi-zone dashboard layout
13. [structured_content](#13-structured_content) — Bordered sections with summary bar
14. [card_grid](#14-card_grid) — 2x2 or 3-column card grid
15. [kpi_dashboard](#15-kpi_dashboard) — Stats top + detail cards bottom

---

## 11. cover_pro

**Visual**: Full dark background. Large title left-aligned, subtitle with horizontal rule. Bottom bar with 3 icon+stat chips and date aligned right. Top-left has department badge with accent bar.

### Schema
```json
{
  "template": "cover_pro",
  "department": "string (e.g. '信息管理部 · 年度工作汇报')",
  "title": "string (large, can be 2 lines)",
  "subtitle": "string (with dash prefix line)",
  "bottom_stats": [
    { "icon": "FaDatabase", "text": "1.12亿条数据底座" },
    { "icon": "FaRobot", "text": "368万次AI交互" }
  ],
  "date": "string (e.g. '2025年12月')"
}
```

### PPTX
```javascript
slide.background = { color: theme.primary };

// Top-left department badge
slide.addShape(pres.shapes.RECTANGLE, {
  x: 0.4, y: 0.3, w: 0.05, h: 0.35,
  fill: { color: theme.secondary }
});
slide.addText(data.department, {
  x: 0.6, y: 0.3, w: 6, h: 0.35,
  fontSize: 12, fontFace: theme.fontBody,
  color: theme.secondary, margin: 0
});

// Main title (large, left-aligned, can wrap 2 lines)
slide.addText(data.title, {
  x: 0.5, y: 1.3, w: 8.5, h: 2.0,
  fontSize: 48, fontFace: theme.fontHeading,
  color: theme.accent, bold: true, margin: 0
});

// Horizontal rule before subtitle
slide.addShape(pres.shapes.RECTANGLE, {
  x: 0.5, y: 3.5, w: 1.5, h: 0.04,
  fill: { color: theme.secondary }
});

// Subtitle
slide.addText(data.subtitle, {
  x: 2.2, y: 3.35, w: 6, h: 0.5,
  fontSize: 22, fontFace: theme.fontBody,
  color: theme.secondary, margin: 0
});

// Bottom stats bar background
slide.addShape(pres.shapes.RECTANGLE, {
  x: 0, y: 4.8, w: 10, h: 0.825,
  fill: { color: theme.primary }  // slightly lighter or use a line above
});
slide.addShape(pres.shapes.LINE, {
  x: 0.4, y: 4.8, w: 9.2, h: 0,
  line: { color: theme.secondary, width: 1 }
});

// Stats chips (icon + text, evenly spaced)
const stats = data.bottom_stats || [];
stats.forEach((st, i) => {
  const x = 0.5 + i * 2.8;
  // Icon circle (small)
  slide.addShape(pres.shapes.OVAL, {
    x: x, y: 4.95, w: 0.35, h: 0.35,
    fill: { color: theme.secondary }
  });
  // Optional: render icon via iconToBase64Png
  slide.addText(st.text, {
    x: x + 0.45, y: 4.95, w: 2.2, h: 0.35,
    fontSize: 12, fontFace: theme.fontBody,
    color: theme.secondary, margin: 0, valign: "middle"
  });
});

// Date (right-aligned)
if (data.date) {
  slide.addText(data.date, {
    x: 7.5, y: 4.95, w: 2, h: 0.35,
    fontSize: 14, fontFace: theme.fontBody,
    color: theme.secondary, align: "right", margin: 0, valign: "middle"
  });
}
```

---

## 12. grid_content

**Visual**: The most information-dense template. Title with accent bar at top. Below is a multi-zone grid: left column ~40% has a main card (with number badge + heading + content), right column ~60% has 2-3 stacked cards. Bottom strip has a full-width summary bar.

This is the "dashboard slide" — multiple content zones coexist on one page.

### Schema
```json
{
  "template": "grid_content",
  "title": "string",
  "subtitle": "string (optional, small text under title)",
  "left_card": {
    "number": "01",
    "heading": "string",
    "content": "string or structured content"
  },
  "right_cards": [
    {
      "icon": "FaUsers",
      "heading": "string",
      "items": [
        { "label": "string", "text": "string" }
      ]
    }
  ],
  "bottom_bar": {
    "icon": "FaFlag",
    "heading": "string",
    "text": "string"
  }
}
```

### PPTX
```javascript
slide.background = { color: theme.primary };

// Title with accent bar
slide.addShape(pres.shapes.RECTANGLE, {
  x: 0.4, y: 0.3, w: 0.06, h: 0.5,
  fill: { color: theme.secondary }
});
slide.addText(data.title, {
  x: 0.65, y: 0.3, w: 8, h: 0.5,
  fontSize: 26, fontFace: theme.fontHeading,
  color: theme.accent, bold: true, margin: 0
});
if (data.subtitle) {
  slide.addText(data.subtitle, {
    x: 0.65, y: 0.85, w: 8, h: 0.3,
    fontSize: 12, fontFace: theme.fontBody,
    color: theme.text_body, margin: 0
  });
}

// --- Left card (40%) ---
const leftX = 0.4, leftW = 3.8, cardY = 1.3;
// Card background (slightly lighter than slide bg)
slide.addShape(pres.shapes.RECTANGLE, {
  x: leftX, y: cardY, w: leftW, h: 3.2,
  fill: { color: theme.bg_light },
  line: { color: theme.secondary, width: 1 }
});

// Number badge inside left card
const lc = data.left_card || {};
slide.addShape(pres.shapes.RECTANGLE, {
  x: leftX + 0.15, y: cardY + 0.15, w: 0.55, h: 0.4,
  fill: { color: theme.secondary }
});
slide.addText(lc.number || "01", {
  x: leftX + 0.15, y: cardY + 0.15, w: 0.55, h: 0.4,
  fontSize: 16, fontFace: theme.fontHeading,
  color: theme.primary, bold: true, align: "center", valign: "middle", margin: 0
});
slide.addText(lc.heading || "", {
  x: leftX + 0.85, y: cardY + 0.15, w: leftW - 1.1, h: 0.4,
  fontSize: 16, fontFace: theme.fontBody,
  color: theme.text_dark, bold: true, margin: 0, valign: "middle"
});

// Left card body content
slide.addText(String(lc.content || ""), {
  x: leftX + 0.2, y: cardY + 0.8, w: leftW - 0.4, h: 2.2,
  fontSize: 13, fontFace: theme.fontBody,
  color: theme.text_body, margin: 0, valign: "top"
});

// --- Right cards (55%) ---
const rightX = 4.5, rightW = 5.1;
const rightCards = data.right_cards || [];
const rcCount = rightCards.length;
const rcGap = 0.2;
const rcH = rcCount > 0 ? (3.2 - (rcCount - 1) * rcGap) / rcCount : 3.2;

rightCards.forEach((rc, i) => {
  const cy = cardY + i * (rcH + rcGap);
  // Card bg
  slide.addShape(pres.shapes.RECTANGLE, {
    x: rightX, y: cy, w: rightW, h: rcH,
    fill: { color: theme.bg_light },
    line: { color: theme.secondary, width: 1 }
  });
  // Heading with icon
  slide.addText(rc.heading || "", {
    x: rightX + 0.4, y: cy + 0.1, w: rightW - 0.6, h: 0.35,
    fontSize: 14, fontFace: theme.fontBody,
    color: theme.text_dark, bold: true, margin: 0
  });

  // Items within card (2-column layout if multiple items)
  const items = rc.items || [];
  if (items.length <= 2) {
    items.forEach((item, j) => {
      const ix = rightX + 0.3 + j * (rightW / 2 - 0.2);
      slide.addText(item.label || "", {
        x: ix, y: cy + 0.5, w: rightW / 2 - 0.4, h: 0.25,
        fontSize: 12, fontFace: theme.fontBody,
        color: theme.secondary, bold: true, margin: 0
      });
      slide.addText(item.text || "", {
        x: ix, y: cy + 0.75, w: rightW / 2 - 0.4, h: rcH - 1.0,
        fontSize: 11, fontFace: theme.fontBody,
        color: theme.text_body, margin: 0, valign: "top"
      });
    });
  }
});

// --- Bottom summary bar ---
if (data.bottom_bar) {
  const bb = data.bottom_bar;
  const barY = 4.7;
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.4, y: barY, w: 9.2, h: 0.65,
    fill: { color: theme.secondary }
  });
  slide.addText(bb.heading || "", {
    x: 0.65, y: barY + 0.05, w: 3, h: 0.25,
    fontSize: 14, fontFace: theme.fontBody,
    color: theme.primary, bold: true, margin: 0
  });
  slide.addText(bb.text || "", {
    x: 0.65, y: barY + 0.3, w: 8.7, h: 0.3,
    fontSize: 11, fontFace: theme.fontBody,
    color: theme.primary, margin: 0
  });
}
```

---

## 13. structured_content

**Visual**: Dark background. Title with accent bar. Main content area is a bordered card containing multiple sections, each with icon + bold heading + body text, separated by thin horizontal lines. Bottom has a highlighted callout bar (different color) for summary/conclusion.

### Schema
```json
{
  "template": "structured_content",
  "title": "string",
  "subtitle": "string (optional)",
  "number_badge": "string (e.g. '01')",
  "heading": "string (card main heading)",
  "sections": [
    {
      "icon": "FaFile",
      "heading": "string",
      "text": "string"
    }
  ],
  "callout": {
    "icon": "FaChartLine",
    "text": "string"
  },
  "bottom_bar": {
    "heading": "string",
    "text": "string"
  }
}
```

### PPTX
```javascript
slide.background = { color: theme.primary };

// Title + accent bar (same pattern)
// ...

// Main bordered card
const cardX = 0.4, cardY = 1.2, cardW = 9.2, cardH = 2.8;
slide.addShape(pres.shapes.RECTANGLE, {
  x: cardX, y: cardY, w: cardW, h: cardH,
  line: { color: theme.secondary, width: 1 },
  fill: { color: theme.primary }  // same as bg, just border visible
});

// Number badge
slide.addShape(pres.shapes.RECTANGLE, {
  x: cardX + 0.15, y: cardY + 0.15, w: 0.55, h: 0.4,
  fill: { color: theme.secondary }
});
slide.addText(data.number_badge || "01", {
  x: cardX + 0.15, y: cardY + 0.15, w: 0.55, h: 0.4,
  fontSize: 16, fontFace: theme.fontHeading,
  color: theme.primary, bold: true, align: "center", valign: "middle", margin: 0
});
slide.addText(data.heading || "", {
  x: cardX + 0.85, y: cardY + 0.15, w: cardW - 1.2, h: 0.4,
  fontSize: 18, fontFace: theme.fontBody,
  color: theme.accent, bold: true, margin: 0, valign: "middle"
});

// Sections within card, separated by lines
const sections = data.sections || [];
const sectionStartY = cardY + 0.7;
const sectionH = (cardH - 0.9) / Math.max(sections.length, 1);

sections.forEach((sec, i) => {
  const sy = sectionStartY + i * sectionH;
  // Divider line (except first)
  if (i > 0) {
    slide.addShape(pres.shapes.LINE, {
      x: cardX + 0.3, y: sy, w: cardW - 0.6, h: 0,
      line: { color: theme.secondary, width: 0.5, dashType: "dash" }
    });
  }
  // Section heading
  slide.addText(sec.heading || "", {
    x: cardX + 0.4, y: sy + 0.1, w: cardW - 0.8, h: 0.3,
    fontSize: 14, fontFace: theme.fontBody,
    color: theme.accent, bold: true, margin: 0
  });
  // Section text
  slide.addText(sec.text || "", {
    x: cardX + 0.4, y: sy + 0.4, w: cardW - 0.8, h: sectionH - 0.55,
    fontSize: 12, fontFace: theme.fontBody,
    color: theme.text_body, margin: 0, valign: "top"
  });
});

// Callout bar (inside card, at bottom)
if (data.callout) {
  const coY = cardY + cardH - 0.5;
  slide.addShape(pres.shapes.RECTANGLE, {
    x: cardX + 0.3, y: coY, w: cardW - 0.6, h: 0.4,
    fill: { color: theme.bg_light },
    line: { color: theme.secondary, width: 0.5 }
  });
  slide.addText(data.callout.text || "", {
    x: cardX + 0.6, y: coY, w: cardW - 1.2, h: 0.4,
    fontSize: 11, fontFace: theme.fontBody,
    color: theme.text_dark, align: "center", valign: "middle", margin: 0
  });
}

// Bottom summary bar
if (data.bottom_bar) {
  const bbY = cardY + cardH + 0.2;
  slide.addShape(pres.shapes.RECTANGLE, {
    x: cardX, y: bbY, w: cardW, h: 0.55,
    fill: { color: theme.secondary }
  });
  slide.addText((data.bottom_bar.heading || "") + " " + (data.bottom_bar.text || ""), {
    x: cardX + 0.3, y: bbY, w: cardW - 0.6, h: 0.55,
    fontSize: 12, fontFace: theme.fontBody,
    color: theme.primary, margin: 0, valign: "middle"
  });
}
```

---

## 14. card_grid

**Visual**: Light or dark background. Title with accent bar. 2x2 or 1x3 grid of equal cards, each with icon + heading + short text. Cards have border and optional top accent line.

### Schema
```json
{
  "template": "card_grid",
  "title": "string",
  "subtitle": "string (optional)",
  "columns": 2 | 3,
  "cards": [
    {
      "icon": "FaShieldAlt",
      "heading": "string",
      "text": "string"
    }
  ]
}
```

### PPTX
```javascript
slide.background = { color: theme.bg_light };
addTitleWithAccent(slide, pres, data.title, theme);
addPageBadge(slide, pres, pageNum, theme);

const cards = data.cards || [];
const cols = data.columns || (cards.length <= 4 ? 2 : 3);
const rows = Math.ceil(cards.length / cols);

const gridX = 0.5, gridW = 9.0;
const gridY = 1.3, gridH = 3.9;
const gapX = 0.25, gapY = 0.25;
const cW = (gridW - (cols - 1) * gapX) / cols;
const cH = (gridH - (rows - 1) * gapY) / rows;

cards.forEach((card, i) => {
  const col = i % cols, row = Math.floor(i / cols);
  const x = gridX + col * (cW + gapX);
  const y = gridY + row * (cH + gapY);

  // Card background
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w: cW, h: cH,
    fill: { color: "FFFFFF" },
    line: { color: theme.secondary, width: 1 }
  });
  // Top accent line
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w: cW, h: 0.05,
    fill: { color: theme.primary }
  });

  // Icon circle
  slide.addShape(pres.shapes.OVAL, {
    x: x + 0.2, y: y + 0.25, w: 0.4, h: 0.4,
    fill: { color: theme.primary }
  });
  // Icon rendered via iconToBase64Png inside circle

  // Heading
  slide.addText(card.heading || "", {
    x: x + 0.75, y: y + 0.25, w: cW - 1.0, h: 0.4,
    fontSize: 14, fontFace: theme.fontBody,
    color: theme.text_dark, bold: true, margin: 0, valign: "middle"
  });

  // Text
  slide.addText(card.text || "", {
    x: x + 0.2, y: y + 0.8, w: cW - 0.4, h: cH - 1.1,
    fontSize: 12, fontFace: theme.fontBody,
    color: theme.text_body, margin: 0, valign: "top"
  });
});
```

---

## 15. kpi_dashboard

**Visual**: Mixed layout. Top section has 3-4 KPI stat boxes in a row (number + label). Below is a content area with 2-3 detail cards. This combines stats_callout density with content depth.

### Schema
```json
{
  "template": "kpi_dashboard",
  "title": "string",
  "kpis": [
    { "value": "98%", "label": "客户满意度" }
  ],
  "detail_cards": [
    { "heading": "string", "text": "string" }
  ]
}
```

### PPTX
```javascript
slide.background = { color: theme.bg_light };
addTitleWithAccent(slide, pres, data.title, theme);
addPageBadge(slide, pres, pageNum, theme);

// KPI row at top
const kpis = data.kpis || [];
const kpiCount = kpis.length;
const kpiW = (9.0 - (kpiCount - 1) * 0.2) / kpiCount;
kpis.forEach((kpi, i) => {
  const x = 0.5 + i * (kpiW + 0.2);
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y: 1.2, w: kpiW, h: 1.0,
    fill: { color: theme.primary }
  });
  slide.addText(kpi.value || "", {
    x, y: 1.2, w: kpiW, h: 0.6,
    fontSize: 32, fontFace: theme.fontHeading,
    color: theme.accent, bold: true, align: "center", margin: 0
  });
  slide.addText(kpi.label || "", {
    x, y: 1.8, w: kpiW, h: 0.35,
    fontSize: 12, fontFace: theme.fontBody,
    color: theme.secondary, align: "center", margin: 0
  });
});

// Detail cards below
const details = data.detail_cards || [];
const dCount = details.length;
const dW = (9.0 - (dCount - 1) * 0.25) / dCount;
details.forEach((det, i) => {
  const x = 0.5 + i * (dW + 0.25);
  const y = 2.5;
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w: dW, h: 2.7,
    fill: { color: "FFFFFF" },
    line: { color: theme.secondary, width: 1 }
  });
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w: dW, h: 0.05,
    fill: { color: theme.secondary }
  });
  slide.addText(det.heading || "", {
    x: x + 0.2, y: y + 0.15, w: dW - 0.4, h: 0.35,
    fontSize: 14, fontFace: theme.fontBody,
    color: theme.text_dark, bold: true, margin: 0
  });
  slide.addText(det.text || "", {
    x: x + 0.2, y: y + 0.55, w: dW - 0.4, h: 2.0,
    fontSize: 12, fontFace: theme.fontBody,
    color: theme.text_body, margin: 0, valign: "top"
  });
});
```

---

## Template Selection Update

With the new templates, the matching guide expands:

| Content Type | Template |
|-------------|----------|
| Cover with key metrics | `cover_pro` |
| Multi-topic content (2-3 zones) | `grid_content` |
| Detailed single topic with sub-sections | `structured_content` |
| Feature/capability showcase (3-6 items) | `card_grid` |
| KPIs + detail breakdown | `kpi_dashboard` |

### When to Use Advanced vs Base Templates

- If slide has **1 content type** → use base template (two_column, icon_list, etc.)
- If slide has **2-3 content zones** or **needs summary bar** → use advanced template
- If slide has **4+ small items** to compare → card_grid
- If slide is **data-heavy** with supporting narrative → kpi_dashboard
