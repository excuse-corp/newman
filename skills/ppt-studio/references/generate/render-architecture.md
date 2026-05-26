# Render Architecture

## Core Principle: Single Layout Logic, Dual Output

Every template implements **three functions** from one shared data source:

```
plan.json
  ↓
layout(data, theme)     ← 唯一的布局逻辑，计算所有元素的坐标/颜色/字号
  ↓ returns elements[]
  ├─→ to_html(elements)    → HTML字符串（预览用）
  └─→ to_pptx(elements, slide)  → python-pptx调用（导出用）
```

Because `layout()` runs once and feeds both renderers, the HTML preview and the PPTX background are **pixel-identical**. There is no separate "approximate preview" code.

---

## Element Types

`layout()` returns a list of element dicts. Each element is one of:

```python
# Rectangle / color block / card background
{ "type": "rect",
  "x": 0, "y": 0, "w": 960, "h": 540,   # pixels (HTML) / auto-converted to inches (PPTX)
  "fill": "2A3D52",                        # 6-digit hex, no #
  "opacity": 1.0,                          # optional, 0.0–1.0
  "radius": 0 }                            # corner radius px; 0 = sharp

# Text box
{ "type": "text",
  "x": 40, "y": 30, "w": 880, "h": 60,
  "text": "标题文字",
  "font": "Microsoft YaHei",
  "size": 28,                              # px (HTML) / pt (PPTX) — same value, same scale
  "color": "FFFFFF",
  "bold": True,
  "align": "left",                         # left / center / right
  "valign": "top",                         # top / middle / bottom
  "wrap": True }

# Line / divider
{ "type": "line",
  "x": 40, "y": 100, "w": 4, "h": 28,    # vertical bar: w=4, h=28
  "fill": "8B97A5" }

# Oval / decorative circle
{ "type": "oval",
  "x": -60, "y": -60, "w": 220, "h": 220,
  "fill": "8B97A5",
  "opacity": 0.08 }
```

---

## Coordinate System

- Canvas: **960 × 540 px** (16:9, matches HTML at 1× scale)
- PPTX conversion: `inches = px / 96` (1 inch = 96px)
- Origin: top-left (0, 0)
- Elements may have negative x/y (for decorative shapes that bleed off-edge)

---

## How render.py Works

```
render.py --plan plan.json --preview preview.html
  1. Load plan.json
  2. For each slide: call TEMPLATES[template].layout(data, theme)
  3. Call to_html(elements) → HTML string
  4. Wrap all slides in a page with labels → write preview.html

render.py --plan plan.json --rasterize qa/
  1. Same as above but render each slide's HTML in headless Playwright
  2. Screenshot each slide → qa/slide-1.jpg, qa/slide-2.jpg ...

render.py --plan plan.json --export output.pptx
  1. Load plan.json
  2. For each slide: call TEMPLATES[template].layout(data, theme)
  3. Call to_pptx(elements, slide) → python-pptx slide object
  4. Save presentation → output.pptx
```

---

## Adding a New Template

1. Add entry to `TEMPLATES` dict in `render.py`
2. Implement `layout(data, theme) -> list[dict]` — all positioning logic here
3. `to_html` and `to_pptx` are generic renderers that consume elements — **no per-template code needed in them**
4. Add schema to `templates.md` and `workflow.md` appendix
5. Add to template selection table in `workflow.md`

---

## Pixel → Inch Conversion Reference

| px | inches | Common use |
|---|---|---|
| 40 | 0.417" | Slide margin |
| 96 | 1.0" | 1 inch |
| 160 | 1.667" | Title bar height |
| 480 | 5.0" | Half-width card |
| 540 | 5.625" | Full slide height |
| 960 | 10.0" | Full slide width |

---

## Why Not HTML → Screenshot → PPTX?

The previous architecture (`html2pptx.js`) used Puppeteer to screenshot the HTML and paste it as a background image, then overlaid editable text boxes calculated separately. This caused:

1. **Two codebases**: `html()` for the screenshot and `texts()` for text coordinates — different logic, guaranteed drift
2. **Text coordinate errors**: px→inch conversion done by hand per element, error-prone
3. **No true preview**: the Phase 4 HTML was hand-written by Claude, not generated from the same code

The new architecture eliminates all three problems by making `layout()` the single source of truth.

---

## Module Layout

```
scripts/
  render.py              # CLI entry point (--preview / --rasterize / --export)
  ppt_render/
    __init__.py
    core.py              # element model + to_html() + to_pptx() renderers
    templates.py         # all template layout() functions + TEMPLATES registry
```

`render.py` is the only file invoked directly. It imports `ppt_render`.

---

## Dependencies

```
playwright          # headless browser for --rasterize
                    # (pip install playwright; chromium is pre-installed in this env)
python-pptx         # PPTX generation
Pillow              # image handling
```

All three are pre-installed in the skill's runtime environment. If missing:

```bash
pip install --break-system-packages playwright python-pptx Pillow
```

---

## Known Renderer Parity Notes

The HTML and PPTX outputs share `layout()`, so positions match. Two areas
need care because HTML (Chromium) and PPTX (PowerPoint / LibreOffice)
render text differently:

1. **Line spacing** — `to_pptx()` converts `line_height` to a point value
   (`size * line_height`), not a multiplier. The multiplier form is
   interpreted inconsistently across PowerPoint and LibreOffice.
2. **Theme shadows** — `to_pptx()` strips the `<p:style>` element that
   python-pptx attaches to every shape, because LibreOffice applies its
   `effectRef` drop-shadow even when an empty `<a:effectLst/>` is present.
   Without stripping, every rect/oval gets an unwanted shadow.

If a new renderer-parity bug appears, fix it in `core.py` (the renderer),
never by hand-tuning individual template coordinates.
