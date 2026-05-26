# Typography & Spacing

Fonts, type scale, and spacing tokens. Every value here renders identically in the HTML preview and the PPTX export, since both share render.py's layout() functions.

> Note: For colors see `palettes.md`. For decoration techniques see `visual-language.md`.

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

**Rule of thumb**: adjacent type levels should differ by ≥ 4pt or one weight step. No same-size headings stacked together.

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
