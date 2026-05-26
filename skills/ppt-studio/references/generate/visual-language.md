# Visual Language

The decoration techniques, shape rules, and design principles that make a slide look *designed* rather than typed.

> Note: For colors see `palettes.md`. For fonts/sizes see `typography.md`.

---

## Style Recipes

Style recipes define the **shape language** applied consistently across all slides. Choose ONE per presentation, paired with the palette.

### Sharp — Corporate, authoritative
- Card corners: **0px / 0 rectRadius** (square)
- Accent bars: **thin rectangles, 4px / 0.04" wide**
- Decorative blocks: **hard edges, right angles**
- Best with: 暗夜金沙, 学院红蓝, 政务蓝白, 银灰商务

### Soft — Modern, approachable
- Card corners: **8px / rectRadius: 0.08**
- Accent bars: **medium rectangles, 6px / 0.06" wide**
- Decorative blocks: **slight rounding, gentle feel**
- Best with: 科技紫蓝, and most palettes when audience is internal/non-formal

### Rounded — Friendly, playful
- Card corners: **16px / rectRadius: 0.16**
- Accent bars: **rounded pill shapes**
- Decorative blocks: **generous rounding, oval accents**
- Best with: consumer-facing decks, not for government/academic contexts

---

## Design Language — Making Slides Look Designed

This is the most critical section. The difference between a "slide" and a "designed slide" is the presence of **structural visual elements** beyond text and content. Every slide should use at least 2-3 of these techniques.

### Technique 1: Color Block Bleeds

Large geometric shapes that extend to or beyond slide edges, creating bold visual anchors.

```
┌──────────────────────────────┐
│████████████│                 │  ← Left 35% filled with primary color
│████████████│   Content       │     Content sits on the remaining space
│████████████│   goes here     │
│████████████│                 │
└──────────────────────────────┘
```

Implementation (PPTX):
```javascript
// Left bleed block — covers left 35% of slide
slide.addShape(pres.shapes.RECTANGLE, {
  x: 0, y: 0, w: 3.5, h: 5.625,
  fill: { color: theme.primary }
});
```

Implementation (HTML):
```jsx
<div style={{
  position: 'absolute', left: 0, top: 0,
  width: '35%', height: '100%',
  backgroundColor: `#${theme.primary}`
}} />
```

Variations:
- **Top band**: `x:0, y:0, w:10, h:2.2` — top 40% filled
- **Bottom bar**: `x:0, y:4.6, w:10, h:1.025` — bottom strip
- **Corner block**: `x:6.5, y:0, w:3.5, h:2.5` — top-right quadrant
- **Diagonal split**: Use two overlapping rectangles at angles (approximate with a tall thin rotated rect in PPTX, or clip-path in HTML)

### Technique 2: Accent Bars and Dividers

Thin colored lines or rectangles that create structure and visual hierarchy.

```javascript
// Vertical accent bar next to title
slide.addShape(pres.shapes.RECTANGLE, {
  x: 0.6, y: 0.4, w: 0.06, h: 0.5,
  fill: { color: theme.secondary }
});
// Title text starts after the bar
slide.addText(title, {
  x: 0.85, y: 0.4, w: 8, h: 0.5, ...
});
```

```javascript
// Horizontal divider under title
slide.addShape(pres.shapes.RECTANGLE, {
  x: 0.6, y: 1.1, w: 2.0, h: 0.04,
  fill: { color: theme.secondary }
});
```

The bar should be **short**, not spanning the full slide width. A 2-inch accent line looks intentional; a full-width line looks like a default separator.

### Technique 3: Background Shape Overlays

Large shapes placed behind content to create depth and visual zones.

```javascript
// Large circle peeking from top-right corner (decorative)
slide.addShape(pres.shapes.OVAL, {
  x: 7.5, y: -1.5, w: 4, h: 4,
  fill: { color: theme.secondary }  // Use a light/muted color
});
```

```javascript
// Offset rectangle creating a "card" effect
slide.addShape(pres.shapes.RECTANGLE, {
  x: 0.4, y: 1.2, w: 9.2, h: 3.8,
  fill: { color: "FFFFFF" }
});
// Content sits on top of this white card
```

### Technique 4: Asymmetric Layouts

Never default to centered everything. Professional slides use deliberate asymmetry.

**40/60 split** instead of 50/50:
- Left column: x: 0.6, w: 3.4 (36%)
- Right column: x: 4.4, w: 5.0 (53%)

**Title anchored left, content offset**:
- Title at x: 0.6 (left-aligned, large)
- Content block at x: 1.2 (slightly indented from title)

**Staggered cards** instead of aligned grid:
- Card 1 at y: 1.2
- Card 2 at y: 1.4 (slightly lower — creates visual movement)
- Card 3 at y: 1.2

### Technique 5: Number/Text as Decoration

Use oversized text or numbers as background decorative elements.

```javascript
// Giant faded number behind content
slide.addText("01", {
  x: -0.5, y: 0.5, w: 4, h: 4,
  fontSize: 200, fontFace: theme.fontHeading,
  color: theme.secondary,  // Same as background-ish, subtle
  bold: true, margin: 0
});
// Normal content on top
slide.addText(title, { x: 0.8, y: 2.0, ... });
```

### Technique 6: Dual-Tone Backgrounds

Split the slide background into two colors.

```javascript
// Top half: primary, Bottom half: bg_light
slide.background = { color: theme.primary };
slide.addShape(pres.shapes.RECTANGLE, {
  x: 0, y: 2.8, w: 10, h: 2.825,
  fill: { color: theme.bg_light }
});
// Cards or content that span across the split line
```

### Applying to Slide Types

| Slide Type | Recommended Techniques |
|------------|----------------------|
| cover | Color block bleed (left or full), oversized decorative text, corner shape |
| section_break | Full dark background, accent bar, giant number decoration |
| two_column | Vertical accent bar beside title, card backgrounds for columns |
| icon_list | Subtle background circle overlay, accent bar beside title |
| stats_callout | Dual-tone background (cards span the split), accent divider |
| timeline | Horizontal accent line as timeline backbone, background color band |
| comparison | Two-tone columns (left card / right card with different top accents) |
| big_statement | Full color bleed, oversized decorative quotation mark or shape |
| image_text | Color block bleed on image side, accent bar beside text |
| end | Full dark background, decorative corner shape, centered content |

---

## Shape Properties

### Allowed
- **Rectangle**: fill color, border (solid, 1-3pt)
- **Rounded Rectangle**: fill color, border, rectRadius per style recipe
- **Circle / Oval**: fill color, border — useful as decorative backgrounds
- **Line**: color, width (1-3pt), solid or dashed
- **Solid fills only**: No gradients, no patterns

### NOT Allowed
- Gradients (not supported by the renderer)
- Complex shadows (engine differences)
- Blur effects
- Text box rotation (renders differently)

### Allowed BUT Use Carefully
- **Transparency on shapes**: pass `opacity` (0.0-1.0) to a rect/oval element. render.py applies it consistently in both the HTML preview and the PPTX export. Use sparingly (0.08-0.25) for decorative background shapes.

---

## Image Placeholders

### HTML Preview
```html
<div style="
  width: 100%; height: 100%;
  background: #E8E8E8;
  border: 2px dashed #BBBBBB;
  display: flex; align-items: center; justify-content: center;
  color: #888888; font-size: 14px;
">📷 建议配图：[主题描述]</div>
```

### PPTX
```javascript
slide.addShape(pres.shapes.RECTANGLE, {
  x: X, y: Y, w: W, h: H,
  fill: { color: "E8E8E8" },
  line: { color: "BBBBBB", width: 1, dashType: "dash" }
});
slide.addText("建议配图：" + label, {
  x: X, y: Y, w: W, h: H,
  fontSize: 12, color: "888888",
  fontFace: "Calibri", align: "center", valign: "middle"
});
```

---

## Icon Usage

Use react-icons (FA, MD, HI, BI libraries). Render to PNG for PPTX, SVG or emoji for HTML.

| Size | Inches | Pixels | Use |
|------|--------|--------|-----|
| Small | 0.3" | 29px | Inline with text |
| Medium | 0.5" | 48px | Feature icon in circle |
| Large | 0.8" | 77px | Hero icon |

Always place icons on contrasting circle backgrounds using the palette colors.

---

## Rendering Parity Checklist

Before finalizing:
- [ ] Only safe fonts used (from `typography.md`)
- [ ] All colors from chosen palette, 6-digit hex (from `palettes.md`)
- [ ] Style recipe applied consistently (corner radius, accent bar style)
- [ ] Every content slide has decorative geometric elements
- [ ] Every non-cover/end slide has page number badge
- [ ] Spacing uses defined tokens
- [ ] Font sizes from scale only
- [ ] Text fits within containers
