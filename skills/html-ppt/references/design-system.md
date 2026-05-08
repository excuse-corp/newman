# Design System — Constrained for HTML ↔ PPTX Fidelity

Every choice here renders nearly identically in both browser CSS and pptxgenjs. Do NOT use properties outside this system.

---

## Slide Dimensions

- Aspect ratio: **16:9**
- PPTX: `LAYOUT_16x9` → 10" × 5.625"
- HTML preview: `max-width: 960px`, `aspect-ratio: 16/9` (960 × 540px)
- Coordinate mapping: 1 inch = 96px

---

## Safe Fonts

### For Chinese Content
- **Chinese text**: Microsoft YaHei (微软雅黑) — use for both heading and body when content is primarily Chinese
- **English text in Chinese decks**: Arial or Calibri

### Heading Fonts (English)
| Font | Character |
|------|-----------|
| Georgia | Serif, elegant |
| Arial Black | Bold, impactful |
| Trebuchet MS | Modern, friendly |
| Cambria | Classic serif |
| Impact | Ultra bold display |
| Palatino Linotype | Refined serif |

### Body Fonts (English)
| Font | Character |
|------|-----------|
| Calibri | Clean, modern |
| Arial | Universal neutral |
| Calibri Light | Lighter variant |
| Garamond | Elegant serif body |

### Recommended Pairings
| Heading → Body | Vibe |
|----------------|------|
| Georgia → Calibri | Professional, classic |
| Arial Black → Arial | Bold, corporate |
| Trebuchet MS → Calibri | Friendly, modern |
| Cambria → Calibri Light | Elegant, understated |
| Palatino Linotype → Garamond | Editorial, refined |

---

## Color Palettes

Choose ONE palette. All hex values are 6-digit, NO `#` prefix in pptxgenjs.

Each palette has 6 semantic roles:

| Key | Role |
|-----|------|
| `primary` | Main brand color. Dark slide backgrounds, decorative blocks |
| `secondary` | Accent shapes, card borders, decorative elements |
| `accent` | Text on dark backgrounds, highlights |
| `text_dark` | Headings on light backgrounds |
| `text_body` | Body text on light backgrounds |
| `bg_light` | Light slide backgrounds |

### Palette Definitions

**暗夜金沙 (Dark Gold)** — 深沉大气，适合年度汇报、总结类
深色背景搭配金色点缀，庄重感与高级感并存。底部统计栏、卡片边框用金色，正文白色。
`primary: 2A2A2A · secondary: C9A86C · accent: FFFFFF · text_dark: 2A2A2A · text_body: A0A0A0 · bg_light: 3A3A3A`

**科技紫蓝 (Tech Purple)** — 科技感，适合技术调研、创新汇报
顶部渐变色带（用紫蓝纯色近似），浅灰底，淡蓝卡片。图标用蓝紫色圆形背景。
`primary: 5B4FC4 · secondary: 7EC8E3 · accent: FFFFFF · text_dark: 2D2D5E · text_body: 5A5A7A · bg_light: F2F5FA`

**学院红蓝 (Academic Red-Blue)** — 正式严谨，适合制度、管理、流程类
白色底，深蓝标题栏，中国红作为关键强调色，用于流程箭头和重点标记。
`primary: 1A3C8A · secondary: D42427 · accent: FFFFFF · text_dark: 1A3C8A · text_body: 4A4A4A · bg_light: FFFFFF`

**政务蓝白 (Gov Blue)** — 简洁权威，适合政策解读、宏观分析
纯白底，宝蓝色标题和强调，极简线条，适合大段文字阅读。
`primary: 0052CC · secondary: 3B7DD8 · accent: FFFFFF · text_dark: 0052CC · text_body: 333333 · bg_light: FFFFFF`

**银灰商务 (Silver Business)** — 低调专业，适合绩效、目录、制度类
浅灰背景带微妙纹理感，深蓝色作为序号和结构色，内容区用白/浅灰条带。
`primary: 1B2B7B · secondary: 4A6FA5 · accent: FFFFFF · text_dark: 1B2B7B · text_body: 555555 · bg_light: EDEDED`

---

## Style Recipes

Style recipes define the **shape language** applied consistently across all slides. Choose ONE per presentation.

### Sharp — Corporate, authoritative
- Card corners: **0px / 0 rectRadius** (square)
- Accent bars: **thin rectangles, 4px / 0.04" wide**
- Decorative blocks: **hard edges, right angles**
- Best with: Midnight Executive, Charcoal Minimal, Ocean Deep

### Soft — Modern, approachable
- Card corners: **8px / rectRadius: 0.08**
- Accent bars: **medium rectangles, 6px / 0.06" wide**
- Decorative blocks: **slight rounding, gentle feel**
- Best with: Forest & Moss, Teal Trust, Warm Terracotta

### Rounded — Friendly, playful
- Card corners: **16px / rectRadius: 0.16**
- Accent bars: **rounded pill shapes**
- Decorative blocks: **generous rounding, oval accents**
- Best with: Coral Energy, Berry & Cream

---

## Design Language — Making Slides Look Designed

This is the most critical section. The difference between a "slide" and a "designed slide" is the presence of **structural visual elements** beyond text and content. Every slide MUST use at least 2-3 of these techniques.

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

## Typography Scale

Fixed sizes — do not invent intermediate values.

| Role | Size (pt/pptx) | Size (px/html) | Weight |
|------|----------------|-----------------|--------|
| Slide title | 40 | 40px | Bold |
| Subtitle / tagline | 20 | 20px | Normal |
| Section header | 28 | 28px | Bold |
| Body text | 16 | 16px | Normal |
| Small label / caption | 12 | 12px | Normal |
| Stat number (big) | 64 | 64px | Bold |
| Stat label | 14 | 14px | Normal |
| Decorative number | 120-200 | 120-200px | Bold |

---

## Spacing System

| Token | Inches | Pixels | Use |
|-------|--------|--------|-----|
| xs | 0.125" | 12px | Tight inner gaps |
| sm | 0.25" | 24px | Between related elements |
| md | 0.5" | 48px | Between content blocks |
| lg | 0.75" | 72px | Section separation |
| xl | 1.0" | 96px | Major structural gaps |
| margin | 0.6" | 58px | Slide edge margin |

---

## Shape Properties

### Allowed
- **Rectangle**: fill color, border (solid, 1-3pt)
- **Rounded Rectangle**: fill color, border, rectRadius per style recipe
- **Circle / Oval**: fill color, border — useful as decorative backgrounds
- **Line**: color, width (1-3pt), solid or dashed
- **Solid fills only**: No gradients, no patterns

### NOT Allowed
- Gradients (no pptxgenjs native support)
- Complex shadows (engine differences)
- Blur effects
- Text box rotation (renders differently)

### Allowed BUT Use Carefully
- **Transparency on shapes**: Supported in pptxgenjs via `transparency: N` (0-100). HTML uses `opacity: 0.N`. Slight inconsistencies may occur but acceptable for decorative background shapes that don't need pixel-perfect match. Use sparingly (20-40% transparency).

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
- [ ] Only safe fonts used
- [ ] All colors from chosen palette, 6-digit hex
- [ ] Style recipe applied consistently (corner radius, accent bar style)
- [ ] Every content slide has decorative geometric elements
- [ ] Every non-cover/end slide has page number badge
- [ ] Spacing uses defined tokens
- [ ] Font sizes from scale only
- [ ] Text fits within containers
