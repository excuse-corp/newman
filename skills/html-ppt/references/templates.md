# Slide Templates

Each template defines a slide layout with:
1. **Schema** — data fields it accepts
2. **Visual Description** — what the slide looks like (decorative elements included)
3. **HTML Implementation** — CSS for preview
4. **PPTX Implementation** — pptxgenjs code for export

All templates use 16:9 (960×540px / 10"×5.625") and the design system from `design-system.md`.

**CRITICAL**: Every template includes decorative geometric elements (color blocks, accent bars, background shapes). These are NOT optional — they are what make the difference between a plain slide and a designed slide.

---

## Table of Contents

1. [cover](#1-cover) — Title slide with color block bleed
2. [section_break](#2-section_break) — Chapter divider with giant number
3. [two_column](#3-two_column) — Split content with accent bar
4. [icon_list](#4-icon_list) — Feature list with circle icons
5. [stats_callout](#5-stats_callout) — Big numbers on dual-tone background
6. [timeline](#6-timeline) — Horizontal process flow
7. [comparison](#7-comparison) — Side-by-side cards with color-coded tops
8. [big_statement](#8-big_statement) — Key message on full bleed
9. [image_text](#9-image_text) — Image + text with color block
10. [end](#10-end) — Closing slide

---

## 1. cover

**Visual**: Left 38% is a solid `primary` color block bleeding to the edge. Title and subtitle sit in the remaining space on a `bg_light` background. A decorative circle (secondary color, partially hidden) peeks from the top-left corner of the color block.

### Schema
```json
{
  "template": "cover",
  "title": "string",
  "subtitle": "string (optional)",
  "meta": "string (optional — date, author, company)"
}
```

### PPTX
```javascript
slide.background = { color: theme.bg_light };

// Left color block bleed
slide.addShape(pres.shapes.RECTANGLE, {
  x: 0, y: 0, w: 3.8, h: 5.625,
  fill: { color: theme.primary }
});

// Decorative circle (peeks from top-left of color block)
slide.addShape(pres.shapes.OVAL, {
  x: -0.8, y: -0.8, w: 3.2, h: 3.2,
  fill: { color: theme.secondary },
  transparency: 30
});

// Short accent bar on the right side
slide.addShape(pres.shapes.RECTANGLE, {
  x: 4.4, y: 2.0, w: 1.2, h: 0.05,
  fill: { color: theme.secondary }
});

// Title — right side
slide.addText(title, {
  x: 4.4, y: 2.2, w: 5.0, h: 1.5,
  fontSize: 40, fontFace: theme.fontHeading,
  color: theme.text_dark, bold: true, margin: 0
});

// Subtitle
if (subtitle) {
  slide.addText(subtitle, {
    x: 4.4, y: 3.7, w: 5.0, h: 0.6,
    fontSize: 20, fontFace: theme.fontBody,
    color: theme.text_body, margin: 0
  });
}

// Meta (bottom-right)
if (meta) {
  slide.addText(meta, {
    x: 4.4, y: 5.0, w: 5.0, h: 0.4,
    fontSize: 12, fontFace: theme.fontBody,
    color: theme.text_body, margin: 0
  });
}
```

### HTML
```jsx
<div style={{ width:'100%', height:'100%', backgroundColor:`#${theme.bg_light}`, position:'relative', overflow:'hidden' }}>
  {/* Left color block */}
  <div style={{ position:'absolute', left:0, top:0, width:'38%', height:'100%', backgroundColor:`#${theme.primary}` }} />
  {/* Decorative circle */}
  <div style={{ position:'absolute', left:'-8%', top:'-15%', width:'33%', aspectRatio:'1', borderRadius:'50%', backgroundColor:`#${theme.secondary}`, opacity:0.3 }} />
  {/* Accent bar */}
  <div style={{ position:'absolute', left:'44%', top:'37%', width:'12.5%', height:'1%', backgroundColor:`#${theme.secondary}` }} />
  {/* Title */}
  <h1 style={{ position:'absolute', left:'44%', top:'41%', width:'52%', fontFamily:theme.fontHeading, fontSize:'40px', fontWeight:'bold', color:`#${theme.text_dark}`, margin:0 }}>{title}</h1>
  {/* Subtitle */}
  {subtitle && <p style={{ position:'absolute', left:'44%', top:'69%', fontFamily:theme.fontBody, fontSize:'20px', color:`#${theme.text_body}` }}>{subtitle}</p>}
  {/* Meta */}
  {meta && <p style={{ position:'absolute', left:'44%', bottom:'5%', fontFamily:theme.fontBody, fontSize:'12px', color:`#${theme.text_body}` }}>{meta}</p>}
</div>
```

---

## 2. section_break

**Visual**: Full `primary` background. Giant decorative number (120pt, secondary color, partially transparent) anchors the left side. Title in white. Thin vertical accent bar on the right edge.

### Schema
```json
{
  "template": "section_break",
  "section_number": "string (e.g. '01')",
  "title": "string",
  "subtitle": "string (optional)"
}
```

### PPTX
```javascript
slide.background = { color: theme.primary };

// Giant decorative number
slide.addText(section_number || "", {
  x: 0.2, y: 0.5, w: 4, h: 3.5,
  fontSize: 160, fontFace: theme.fontHeading,
  color: theme.secondary, bold: true, margin: 0,
  transparency: 60
});

// Title (overlays on top of the number)
slide.addText(title, {
  x: 0.6, y: 2.4, w: 7, h: 0.9,
  fontSize: 36, fontFace: theme.fontHeading,
  color: theme.accent, bold: true, margin: 0
});

// Subtitle
if (subtitle) {
  slide.addText(subtitle, {
    x: 0.6, y: 3.4, w: 7, h: 0.5,
    fontSize: 16, fontFace: theme.fontBody,
    color: theme.secondary, margin: 0
  });
}

// Right accent bar
slide.addShape(pres.shapes.RECTANGLE, {
  x: 9.5, y: 0.85, w: 0.04, h: 3.94,
  fill: { color: theme.secondary }
});
```

---

## 3. two_column

**Visual**: Light background. Title has a vertical accent bar to its left. Content split 45/55 into two columns. Optionally, right column sits on a subtle white card.

### Schema
```json
{
  "template": "two_column",
  "title": "string",
  "left": { "type": "text|bullet_list", "content": "string or string[]" },
  "right": { "type": "text|bullet_list|placeholder_image", "content": "...", "image_label": "..." }
}
```

### PPTX
```javascript
slide.background = { color: theme.bg_light };

// Vertical accent bar beside title
slide.addShape(pres.shapes.RECTANGLE, {
  x: 0.6, y: 0.35, w: 0.06, h: 0.55,
  fill: { color: theme.primary }
});

// Title (offset right of accent bar)
slide.addText(title, {
  x: 0.85, y: 0.35, w: 8, h: 0.55,
  fontSize: 28, fontFace: theme.fontHeading,
  color: theme.text_dark, bold: true, margin: 0
});

// Horizontal divider under title
slide.addShape(pres.shapes.RECTANGLE, {
  x: 0.6, y: 1.1, w: 1.5, h: 0.03,
  fill: { color: theme.secondary }
});

// Left column: x: 0.6, w: 3.8 (40%)
// Right column: x: 4.8, w: 4.8 (50%)
// For bullet_list: use addText with bullet:true
// For placeholder_image: use addPlaceholder helper
```

---

## 4. icon_list

**Visual**: Light background. Title with accent bar. Vertical list of items, each with a colored circle + icon. A large decorative circle (secondary, transparent) sits in the top-right background.

### Schema
```json
{
  "template": "icon_list",
  "title": "string",
  "items": [{ "icon": "FaRocket", "label": "string", "description": "string" }]
}
```

### PPTX
```javascript
slide.background = { color: theme.bg_light };

// Background decorative circle (top-right)
slide.addShape(pres.shapes.OVAL, {
  x: 7.0, y: -1.0, w: 4.5, h: 4.5,
  fill: { color: theme.secondary },
  transparency: 85
});

// Accent bar + Title (same pattern as two_column)
// ...

// Items: each row has circle (0.5x0.5) + icon + label + description
// y spacing: 1.0" per item, max 4 items
items.forEach((item, i) => {
  const yBase = 1.3 + i * 1.0;
  slide.addShape(pres.shapes.OVAL, {
    x: 0.6, y: yBase, w: 0.5, h: 0.5,
    fill: { color: theme.primary }
  });
  // Icon rendered via iconToBase64Png() at 0.26x0.26 centered in circle
  // Label: x:1.3, bold, 16pt
  // Description: x:1.3, y+0.32, 14pt, text_body color
});
```

---

## 5. stats_callout

**Visual**: Dual-tone background — top 55% is `primary`, bottom 45% is `bg_light`. White stat cards span across the split line, creating a floating effect.

### Schema
```json
{
  "template": "stats_callout",
  "title": "string (optional)",
  "stats": [{ "value": "98%", "label": "string", "description": "string (optional)" }]
}
```

### PPTX
```javascript
// Dual-tone background
slide.background = { color: theme.primary };
slide.addShape(pres.shapes.RECTANGLE, {
  x: 0, y: 3.1, w: 10, h: 2.525,
  fill: { color: theme.bg_light }
});

// Title (on dark section, white text)
if (title) {
  slide.addText(title, {
    x: 0.6, y: 0.5, w: 8.8, h: 0.6,
    fontSize: 28, fontFace: theme.fontHeading,
    color: theme.accent, bold: true, margin: 0
  });
}

// Stat cards — positioned to span the split (y: 1.5, h: 3.2)
const count = stats.length;
const cardW = count <= 2 ? 4.0 : 2.6;
const gap = 0.4;
const totalW = count * cardW + (count - 1) * gap;
const startX = (10 - totalW) / 2;

stats.forEach((stat, i) => {
  const x = startX + i * (cardW + gap);
  // White card with top accent line
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y: 1.5, w: cardW, h: 3.2,
    fill: { color: "FFFFFF" }
  });
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y: 1.5, w: cardW, h: 0.06,
    fill: { color: theme.secondary }
  });
  // Value: large, primary color, centered
  slide.addText(stat.value, {
    x, y: 1.8, w: cardW, h: 1.2,
    fontSize: 56, fontFace: theme.fontHeading,
    color: theme.primary, bold: true, align: "center", margin: 0
  });
  // Label + Description below
});
```

---

## 6. timeline

**Visual**: Light background. Title with accent bar. Steps connected by a horizontal line. Each step has a colored circle with number. A thin horizontal accent band (`primary`, 15% opacity) spans the middle.

### Schema
```json
{
  "template": "timeline",
  "title": "string",
  "steps": [{ "number": "01", "label": "string", "description": "string (optional)" }]
}
```

### PPTX
```javascript
slide.background = { color: theme.bg_light };

// Accent bar + title
// ...

// Background horizontal band (subtle)
slide.addShape(pres.shapes.RECTANGLE, {
  x: 0, y: 2.1, w: 10, h: 0.7,
  fill: { color: theme.primary },
  transparency: 90
});

// Steps: evenly spaced, connected by lines
const count = steps.length;
const stepWidth = 8.8 / count;

steps.forEach((step, i) => {
  const cx = 0.6 + stepWidth * i + stepWidth / 2;
  const circleY = 2.15;

  // Connector line (before this step to the next)
  if (i < count - 1) {
    slide.addShape(pres.shapes.LINE, {
      x: cx + 0.3, y: circleY + 0.25,
      w: stepWidth - 0.6, h: 0,
      line: { color: theme.secondary, width: 2 }
    });
  }

  // Number circle
  slide.addShape(pres.shapes.OVAL, {
    x: cx - 0.25, y: circleY, w: 0.5, h: 0.5,
    fill: { color: theme.primary }
  });
  slide.addText(step.number, {
    x: cx - 0.25, y: circleY, w: 0.5, h: 0.5,
    fontSize: 18, fontFace: theme.fontHeading,
    color: theme.accent, bold: true, align: "center", valign: "middle", margin: 0
  });

  // Label and description below
});
```

---

## 7. comparison

**Visual**: Light background. Two white cards side by side, each with a distinct colored top bar (left = primary, right = secondary). Title with accent bar above.

### Schema
```json
{
  "template": "comparison",
  "title": "string",
  "left_label": "string",
  "right_label": "string",
  "left_items": ["string"],
  "right_items": ["string"]
}
```

### PPTX
```javascript
slide.background = { color: theme.bg_light };
// Accent bar + Title...

// Left card
slide.addShape(pres.shapes.RECTANGLE, {
  x: 0.6, y: 1.3, w: 4.1, h: 3.8, fill: { color: "FFFFFF" }
});
slide.addShape(pres.shapes.RECTANGLE, {
  x: 0.6, y: 1.3, w: 4.1, h: 0.06, fill: { color: theme.primary }
});

// Right card
slide.addShape(pres.shapes.RECTANGLE, {
  x: 5.3, y: 1.3, w: 4.1, h: 3.8, fill: { color: "FFFFFF" }
});
slide.addShape(pres.shapes.RECTANGLE, {
  x: 5.3, y: 1.3, w: 4.1, h: 0.06, fill: { color: theme.secondary }
});

// Card labels + bullet items inside each card
```

---

## 8. big_statement

**Visual**: Full `primary` background. A large semi-transparent decorative shape (circle or rectangle) in the background. Statement text centered. Optional attribution below.

### Schema
```json
{
  "template": "big_statement",
  "statement": "string",
  "attribution": "string (optional)"
}
```

### PPTX
```javascript
slide.background = { color: theme.primary };

// Large decorative circle (background)
slide.addShape(pres.shapes.OVAL, {
  x: 6, y: -1, w: 5, h: 5,
  fill: { color: theme.secondary },
  transparency: 80
});

// Large opening quotation mark (decorative)
slide.addText("\u201C", {
  x: 0.8, y: 0.5, w: 2, h: 2,
  fontSize: 160, fontFace: theme.fontHeading,
  color: theme.secondary, bold: true, margin: 0,
  transparency: 50
});

// Statement text
slide.addText(statement, {
  x: 1.2, y: 1.8, w: 7.6, h: 2.2,
  fontSize: 32, fontFace: theme.fontHeading,
  color: theme.accent, bold: true, align: "center", valign: "middle", margin: 0
});

// Attribution
if (attribution) {
  slide.addText("— " + attribution, {
    x: 1.2, y: 4.1, w: 7.6, h: 0.5,
    fontSize: 14, fontFace: theme.fontBody,
    color: theme.secondary, align: "center", margin: 0
  });
}
```

---

## 9. image_text

**Visual**: Left side is a color block (`primary`) with image placeholder inside. Right side has text content on `bg_light`. A thin accent bar separates the two zones. `image_side` can swap.

### Schema
```json
{
  "template": "image_text",
  "title": "string",
  "text": "string or string[]",
  "image_label": "string",
  "image_side": "left|right"
}
```

### PPTX
```javascript
slide.background = { color: theme.bg_light };

const imgSide = data.image_side || "left";
const blockX = imgSide === "left" ? 0 : 5.5;
const contentX = imgSide === "left" ? 5.0 : 0.6;

// Color block behind image area
slide.addShape(pres.shapes.RECTANGLE, {
  x: blockX, y: 0, w: 4.5, h: 5.625,
  fill: { color: theme.primary }
});

// Image placeholder (inside the color block, with margin)
addPlaceholder(slide, pres, blockX + 0.3, 0.5, 3.9, 4.6, data.image_label);

// Accent bar at the split
const barX = imgSide === "left" ? 4.5 : 5.5;
slide.addShape(pres.shapes.RECTANGLE, {
  x: barX, y: 0.8, w: 0.05, h: 4.0,
  fill: { color: theme.secondary }
});

// Title + text on content side
slide.addText(title, {
  x: contentX, y: 0.5, w: 4.2, h: 0.7,
  fontSize: 28, fontFace: theme.fontHeading,
  color: theme.text_dark, bold: true, margin: 0
});
// Body text at contentX, y: 1.4
```

---

## 10. end

**Visual**: Full `primary` background with a large decorative corner shape (secondary). Centered thank-you text. Contact info at bottom.

### Schema
```json
{
  "template": "end",
  "title": "string",
  "subtitle": "string (optional)",
  "contact": "string (optional)"
}
```

### PPTX
```javascript
slide.background = { color: theme.primary };

// Decorative corner block (bottom-right)
slide.addShape(pres.shapes.RECTANGLE, {
  x: 6.5, y: 3.5, w: 3.5, h: 2.125,
  fill: { color: theme.secondary },
  transparency: 30
});

// Decorative circle (top-left)
slide.addShape(pres.shapes.OVAL, {
  x: -1, y: -1, w: 3, h: 3,
  fill: { color: theme.secondary },
  transparency: 80
});

slide.addText(title, {
  x: 1, y: 1.8, w: 8, h: 1,
  fontSize: 40, fontFace: theme.fontHeading,
  color: theme.accent, bold: true, align: "center", margin: 0
});
if (subtitle) {
  slide.addText(subtitle, {
    x: 1, y: 3.0, w: 8, h: 0.6,
    fontSize: 20, fontFace: theme.fontBody,
    color: theme.secondary, align: "center", margin: 0
  });
}
if (contact) {
  slide.addText(contact, {
    x: 1, y: 4.2, w: 8, h: 0.4,
    fontSize: 14, fontFace: theme.fontBody,
    color: theme.secondary, align: "center", margin: 0
  });
}
```

---

## Template Usage Notes

### Recommended Distribution (10-slide deck)
- 1× cover (bookend, dark)
- 1× section_break (divider, dark)
- 2× two_column (detailed content, light)
- 1× icon_list (features, light)
- 1× stats_callout (data, dual-tone)
- 1× timeline (process, light)
- 1× comparison or image_text (light)
- 1× big_statement (key takeaway, dark)
- 1× end (bookend, dark)

### Dark/Light Rhythm
Alternate to create visual rhythm:
cover(dark) → content(light) → content(light) → section_break(dark) → content(light) → stats(dual) → content(light) → big_statement(dark) → content(light) → end(dark)

### NEVER
- Repeat the same content template 3+ times in a row
- Use a slide without any decorative geometric elements
- Center all text on every slide — vary alignment
- Use the same column split ratio on consecutive two_column slides
