# Common Pitfalls

Two categories: **renderer pitfalls** (Python toolchain quirks) and
**design pitfalls** (visual failures, toolchain-independent).

The design pitfalls are the ones that actually fail QA — read those carefully.

---

## Renderer Pitfalls (render.py / ppt_render)

These are already handled inside `core.py`. Listed here so you understand
why the code does what it does, and what to watch for if you edit it.

### R0. Never use show_widget as a preview (most common failure)

The `show_widget` tool renders an inline chat widget. It is tempting to use it for a "quick preview" because it's fast and doesn't require writing files. **Do not do this.**

- The widget HTML is written by Claude from scratch — it is a different codebase from `render.py`'s templates
- The user sees the widget and approves it, then gets a PPTX that looks different
- This was the #1 failure mode of the previous architecture (html2pptx.js)

**The only valid Phase 4 preview is:**
```bash
python render.py --plan plan.json --preview preview.html
# then: present_files preview.html
```

If `render.py` errors out, fix the error. Do not fall back to show_widget.
All `theme.*` values and any color passed to `rect()`/`text()` are 6-digit
hex with no `#`. The `hexclean()` helper strips it defensively, but plan.json
should never contain `#`.

### R2. Line spacing is point-based, not a multiplier
`to_pptx()` converts `line_height` to a point value (`size * line_height`).
PowerPoint and LibreOffice interpret the multiplier form differently — the
multiplier makes multi-line titles overlap their neighbors in LibreOffice.
If you add a template, pass `line_height` as a ratio (1.25, 1.4, …); the
renderer does the conversion.

### R3. Theme shadows are stripped
python-pptx attaches a `<p:style>` with an `effectRef` (drop shadow) to
every shape. LibreOffice renders that shadow even when an empty
`<a:effectLst/>` is present. `_strip_shape_style()` removes it so shapes
stay flat. Do not re-add `<p:style>`.

### R4. CJK font must be set explicitly
python-pptx's `font.name` only sets the Latin typeface. `_set_ea_font()`
adds the `<a:ea>` element so Chinese text uses the intended font. Any new
text path must call it (the shared `_add_text()` already does).

### R5. Negative coordinates are fine
Decorative shapes (circles bleeding off-edge) use negative x/y. Both
renderers clip at the canvas edge via `overflow:hidden` (HTML) and the
slide boundary (PPTX). This is intentional.

### R6. Opacity
`opacity` on a rect/oval works in both renderers (`<a:alpha>` in PPTX).
On text it also works but use sparingly — only for giant faint background
numbers like `section_break`.

---

## Design Pitfalls — Contrast & Visibility

**This section is the #1 source of QA failures.** It applies regardless of
toolchain — it is about color choices in `plan.json` (the `theme`) and in
template layouts.

### D1. Never put a same-family card on a same-family background
The most common failure: a medium-tone card on a dark background of the
same hue. Up close on a bright monitor they look distinct; in a projected
room or a screenshot the delta vanishes and cards disappear.

**The squint test:** blur your eyes at the slide. Can you still count the
cards? If not, the color delta is too small.

Card hierarchy for dark-background slides:

| Priority | Card fill | Text color | When |
|---|---|---|---|
| **Best** | `FFFFFF` white | `primary` or `333333` | Always preferred on dark slides |
| Good | light tint (`bg_light`) | `text_dark` | When pure white feels stark |
| Acceptable | dark card + bright border | `accent` text | Only if a dark theme is mandatory |
| **Never** | same-family mid-tone | any | Always blends into the background |

The built-in templates already follow this — `card_grid`, `kpi_dashboard`
detail cards, etc. all use white card fills. If you build a new template,
do the same.

### D2. Never use the secondary color for body text on the primary background
`secondary` on `primary` (e.g. a muted blue-grey on dark navy) is
near-invisible. On dark slides, body and subtitle text should be `accent`
(white) or a light tint. The cover/section templates already do this.

### D3. Safe pairings

| Element | Background | Text |
|---|---|---|
| Main title | `primary` (dark) | `accent` (white) |
| Subtitle / tagline | `primary` (dark) | `secondary` is OK here *only* if it is light enough; prefer `accent` |
| Card on dark slide | `FFFFFF` | `text_dark` or `333333` |
| Card on light slide | `FFFFFF` / `bg_light` | `text_body` |
| Title on light slide | `bg_light` | `text_dark` |

When in doubt, run the squint test on the rasterized QA image.

---

## Design Pitfalls — Layout & Composition

### D4. Empty space is a bug
A card sized for 6 lines holding 2 lines looks broken. Fixes, in order of
preference: (a) switch to a simpler template, (b) reduce card count so each
card is smaller, (c) add genuine content. Never ship a slide with a zone
more than ~30% empty.

### D5. All slides look the same
Never use the same template 3× in a row. Vary the layout. The deck should
have a dark/light rhythm (cover dark → content light → divider dark → …).

### D6. Text-only slides
Every slide needs geometric elements — accent bars, color blocks,
numbered circles, dividers. A slide with only text reads as a Word document.
The templates supply these automatically; do not strip them.

### D7. Missing page numbers
Every slide except cover/section-break/end carries a page badge. The
`_page_badge()` helper handles this; pass `page` in plan.json (or let
`render.py` default it to slide position).

### D8. Everything centered
Avoid centering all content. Asymmetric layouts (left-anchored titles,
40/60 splits) feel designed; full symmetry feels static. The templates are
already asymmetric — don't fight them.

---

## QA Process (Phase 4b)

```bash
# rasterize the HTML preview into per-slide images
python /mnt/skills/user/ppt-studio/scripts/render.py \
  --plan plan.json --rasterize qa/

# for each qa/slide-N.jpg, run the QA sub-agent (see qa-prompt.md)
```

Per slide, check: contrast (squint test), no clipped text, no empty zones,
decorative elements present, colors match theme, page badge present.

Apply fixes to `plan.json` (content/colors) or `render.py` (layout/sizing),
re-rasterize, re-check. One fix often surfaces another — always re-run QA
after a fix. Max 3 iterations per slide. See `qa-prompt.md` for the loop.
