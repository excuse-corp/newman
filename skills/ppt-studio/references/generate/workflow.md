# Generate Path Workflow

The 5-phase workflow for building a new PowerPoint deck from scratch.

**Prerequisites:** You have completed STEP 0 triage in SKILL.md and confirmed the user wants Path G.

**Process at a glance:**
**Outline → Color → Slide Plan + plan.json → HTML Preview + QA → PPTX Export**

The skill assembles a `plan.json` describing the deck (theme + per-slide template data), then `render.py` renders it to both an HTML preview and a final `.pptx` file. The two outputs share the same rendering logic, so **what you see in the HTML preview is exactly what you get in the PPTX**.

See `render-architecture.md` for the dual-render design.

---

## Quick Reference

The workflow has **two mandatory user gates**.

| You are at | Read | Decide | Gate? |
|---|---|---|---|
| Just got a request | Phase 1 | Outline | ✋ user confirms outline |
| Outline approved | `palettes.md`, `visual-language.md` | Palette + style recipe | ✋ user confirms palette |
| Palette confirmed | `templates.md` | Template per slide | 🛑 **MANDATORY GATE**: present slide plan, wait for explicit approval |
| Slide plan confirmed | Phase 4 | Write plan.json → render HTML preview → QA loop | 🛑 **MANDATORY GATE**: present HTML preview, wait for explicit approval |
| Preview approved | Phase 5 | Export PPTX | — no further gates |

> Gates exist because layout errors caught at Phase 4 are free to fix; errors caught after PPTX export cost multiple re-renders.

Files referenced throughout (all in `references/generate/`):
- `palettes.md` — 12 palettes + color contract + self-check
- `typography.md` — fonts, sizes, spacing
- `visual-language.md` — decoration techniques, style recipes
- `templates.md` — all 15 templates with schemas
- `render-architecture.md` — dual-render design (layout / toHTML / toPPTX)
- `qa-prompt.md` — QA sub-agent prompt + scoring rubric

Scripts (in `/mnt/skills/user/ppt-studio/scripts/`):
- `render.py` — main renderer: `--preview` outputs HTML, `--export` outputs PPTX

---

## Phase 1: Outline

Read the user's request. Produce a numbered outline (page → topic → 1-line content hint). Ask the user to confirm before continuing.

**If the user uploaded a PPTX as content source:**
- Read `references/shared/extract-content.md`
- Pull text/structure from the uploaded PPT, then produce the outline normally

---

## Phase 2: Color & Style Selection

Read `palettes.md` and `visual-language.md`.

Present 3–5 palette options — **never auto-select**. Default to the 7 Modern palettes. Suggest a matching style recipe per palette. Wait for confirmation before proceeding.

---

## Phase 3: Slide Plan → write plan.json

Read `templates.md`.

**Template matching:**

| Content Type | Template |
|--|--|
| Cover with metrics | `cover_pro` |
| Cover, simple | `cover` |
| Chapter divider, expressive | `section_break` |
| Chapter divider, quiet | `section_break_minimal` |
| Variable-count item showcase (1–9) | `card_grid` |
| Vertical numbered list (1–8) | `icon_list` |
| KPIs + supporting detail | `kpi_dashboard` |
| Multi-zone dashboard | `grid_content` |
| Detailed single topic with sub-sections | `structured_content` |
| Key message, expressive | `big_statement` |
| Key message, quiet | `big_statement_minimal` |
| Closing | `end` |

**Rules:**
- Vary layouts — never the same template 3× in a row.
- Parametric caps: `card_grid` ≤ 9, `icon_list` ≤ 8, `kpi_dashboard` ≤ 6 KPIs / ≤ 4 details. Over-cap → split across slides.

### MANDATORY gate: present slide plan

Present the plan as a table: `page | template | content summary`. Stop and wait for explicit confirmation before proceeding.

If the user approves → **immediately write `plan.json`** to `/home/claude/plan.json`.

> Writing plan.json here (not in Phase 5) is intentional. Phase 4 renders directly from plan.json, so the HTML preview and the PPTX are driven by the same file.

> ⛔ **HARD RULE: after user approves the slide plan, the next action MUST be `bash_tool` writing plan.json and running `render.py --preview`. Do NOT use `show_widget` or write any HTML by hand. A hand-written widget preview is NOT the same as the PPTX output and will mislead the user.**

See the **JSON Plan Schema** appendix at the end of this file for field reference.

---

## Phase 4: HTML Preview + QA — MANDATORY

> ⛔ **HARD RULE: the preview shown to the user in Phase 4 MUST be the HTML file produced by `render.py --preview`, delivered via `present_files`. Do NOT use `show_widget`, do NOT write HTML by hand, do NOT render an inline chat widget as a substitute. The only valid preview is the file from `render.py`. Anything else diverges from the PPTX output.**

### Step 4a: Render HTML preview

```bash
python /mnt/skills/user/ppt-studio/scripts/render.py \
  --plan /home/claude/plan.json \
  --preview /home/claude/preview.html
```

This generates a standalone `preview.html` containing all slides stacked vertically, each labeled `Slide N: <template>`. The HTML is produced by the same `layout()` + `toHTML()` functions that will later produce the PPTX background — **it is not an approximation**.

Call `present_files` with `/home/claude/preview.html` so the user can open it in a browser.

Tell the user: "请在浏览器中打开这个 HTML 文件预览效果，确认后我再生成 PPTX。"

### Step 4b: QA sub-agent loop

While the user reviews the HTML, run the QA loop on the preview:

```bash
# Rasterize each slide from the HTML for QA
python /mnt/skills/user/ppt-studio/scripts/render.py \
  --plan /home/claude/plan.json \
  --rasterize /home/claude/qa/
# Outputs: qa/slide-1.jpg, qa/slide-2.jpg, ...
```

For each `slide-N.jpg`, invoke the QA sub-agent using the prompt in `qa-prompt.md`. Apply fixes to `plan.json`, re-render the affected slide, re-check. See qa-prompt.md for the full loop logic.

**Fix translation table (Phase 4 version):**

| QA suggestion involves | Fix lives in |
|---|---|
| Color of an element | Edit `theme.*` values in `plan.json` |
| Content amount | Edit slide content fields in `plan.json` |
| Card height / layout density | Switch templates or reduce card count in `plan.json` |
| Decorative element or text size | Edit template code in `render.py` (see `render-architecture.md`) |

After QA loop completes, re-render preview.html with fixes applied.

### Step 4c: MANDATORY user gate

Present the (QA-corrected) preview to the user. **Stop and wait for explicit feedback.**

Acceptable:
- "好的，生成 PPT" / "Looks good, export"
- "改第 N 页的 X" → update plan.json → re-render preview → loop back to 4b

Unacceptable (must ask again):
- silence
- comments only on content, not layout

---

## Phase 5: PPTX Export

User has approved the preview. Run:

```bash
python /mnt/skills/user/ppt-studio/scripts/render.py \
  --plan /home/claude/plan.json \
  --export /home/claude/output.pptx
```

The `--export` path uses the same `layout()` functions as `--preview`, so the PPTX background layer is pixel-identical to the HTML preview. The only addition is editable text boxes overlaid by python-pptx.

Copy to outputs and present:

```bash
cp /home/claude/output.pptx /mnt/user-data/outputs/<filename>.pptx
```

Then call `present_files`.

**No QA loop in Phase 5.** The HTML preview already passed QA in Phase 4. If the user spots an issue after seeing the PPTX, go back to Phase 4 (update plan.json → re-preview → re-export).

---

## Design Principles

1. **Single source of truth** — `plan.json` drives both HTML and PPTX. Never hand-write separate HTML.
2. **Contrast first** — White on dark. Dark on light.
3. **Card boundaries must be obvious** — Cards on dark slides: white/light fill only.
4. **Template fits content** — Empty space is a bug. Sparse content → simpler template.
5. **Parametric over manual** — Let templates handle item count automatically.
6. **Over-cap → split slides** — Never squash; always split.
7. **QA at Phase 4, not Phase 5** — Catching issues in HTML is free; catching them post-PPTX is expensive.

---

## File Reference

| File | Used in Phase | Purpose |
|---|---|---|
| `palettes.md` | 2 | 12 palettes + Color Role Contract v3 |
| `typography.md` | 3 | Font pairings, type scale, spacing tokens |
| `visual-language.md` | 2, 3 | Style recipes, decoration techniques |
| `templates.md` | 3 | All 15 templates with schemas |
| `render-architecture.md` | 4, 5 | Dual-render design: layout / toHTML / toPPTX |
| `qa-prompt.md` | 4b | QA sub-agent prompt + scoring rubric |
| `scripts/render.py` | 4, 5 | Main renderer (--preview / --rasterize / --export) |

---

## JSON Plan Schema (Appendix)

Quick reference for `plan.json` slide fields.

```json
{
  "theme": {
    "primary": "2A3D52", "secondary": "8B97A5", "accent": "FFFFFF",
    "text_dark": "2A3D52", "text_body": "4F5868", "bg_light": "F6F7F9",
    "fontHeading": "Microsoft YaHei", "fontBody": "Microsoft YaHei"
  },
  "slides": [ ... ]
}
```

### `cover_pro` / `cover`
```json
{ "template": "cover_pro", "page": 1,
  "department": "string",
  "title": "string (\\n for line break)",
  "subtitle": "string",
  "bottom_stats": [{ "text": "string" }],
  "date": "string" }
```

### `section_break` / `section_break_minimal`
```json
{ "template": "section_break", "page": 2,
  "section_number": "string (e.g. '01')",
  "title": "string",
  "subtitle": "string (optional)" }
```

### `card_grid` (parametric, 1–9 cards)
```json
{ "template": "card_grid", "page": 3,
  "title": "string",
  "cards": [{ "heading": "string", "text": "string" }] }
```
Auto-layout: 1→1×1, 2→1×2, 3→1×3, 4→2×2, 5→3+2, 6→2×3, 7→4+3, 8→2×4, 9→3×3.

### `icon_list` (parametric, 1–8 items)
```json
{ "template": "icon_list", "page": 4,
  "title": "string",
  "items": [{ "label": "string", "description": "string" }] }
```

### `kpi_dashboard` (parametric, 1–6 KPIs + 1–4 detail_cards)
```json
{ "template": "kpi_dashboard", "page": 5,
  "title": "string",
  "kpis": [{ "value": "string", "label": "string" }],
  "detail_cards": [{ "heading": "string", "text": "string" }] }
```

### `grid_content`
```json
{ "template": "grid_content", "page": 6,
  "title": "string", "subtitle": "string (optional)",
  "left_card": { "number": "01", "heading": "string", "content": "string" },
  "right_cards": [{ "icon": "string", "heading": "string", "items": [{"label":"string","text":"string"}] }],
  "bottom_bar": { "icon": "string", "heading": "string", "text": "string" } }
```

### `structured_content`
```json
{ "template": "structured_content", "page": 7,
  "title": "string", "number_badge": "01", "heading": "string",
  "sections": [{ "icon": "string", "heading": "string", "text": "string" }],
  "callout": { "icon": "string", "text": "string" },
  "bottom_bar": { "heading": "string", "text": "string" } }
```

### `big_statement` / `big_statement_minimal`
```json
{ "template": "big_statement_minimal", "page": 8,
  "statement": "string (\\n for line break)",
  "attribution": "string (optional)" }
```

### `end`
```json
{ "template": "end", "page": 9,
  "title": "string",
  "subtitle": "string (optional)",
  "contact": "string (optional)" }
```
