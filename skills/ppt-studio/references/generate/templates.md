# Slide Templates

12 templates, each implemented as a `layout()` function in
`scripts/ppt_render/templates.py`. This file documents **what each template
is for and what fields its plan.json entry takes** — the rendering code
lives in `render.py`, not here.

> The schemas below are the contract. `render.py` reads exactly these
> fields; unknown fields are ignored, missing optional fields fall back to
> empty. See `render-architecture.md` for how layout() / to_html() /
> to_pptx() work.

---

## Template Selection Guide

| Content type | Template |
|---|---|
| Cover with metrics | `cover_pro` |
| Cover, simple | `cover` (alias of cover_pro) |
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
- Template must fit content: sparse content → simpler template. Empty space is a bug.
- Parametric caps: `card_grid` ≤ 9 cards, `icon_list` ≤ 8 items,
  `kpi_dashboard` ≤ 6 KPIs / ≤ 4 detail cards. Over-cap → split across slides.

---

# Cover & Dividers

## cover_pro / cover

Full dark background. Large left-aligned title, subtitle with a short rule.
Bottom bar carries up to ~3 stat chips and a right-aligned date. Top-left
department badge with accent bar. Decorative faint circle top-right.
`cover` is an alias — identical layout.

```json
{
  "template": "cover_pro",
  "department": "string  (e.g. '信息管理部 · 年度工作汇报')",
  "title": "string  (large; \\n for a 2-line break)",
  "subtitle": "string  (shown after a short rule)",
  "bottom_stats": [ { "text": "string" } ],
  "date": "string  (e.g. '2026年4月', right-aligned)"
}
```

## section_break

Full `primary` background. A giant faint section number anchors the right
side. Title in white with an accent bar; optional subtitle below.

```json
{
  "template": "section_break",
  "section_number": "string  (e.g. '03')",
  "title": "string",
  "subtitle": "string  (optional)"
}
```

## section_break_minimal

Quiet divider. Small section number, accent bar, title, optional subtitle.
No giant background number. Use when `section_break` feels too expressive.

```json
{
  "template": "section_break_minimal",
  "section_number": "string  (optional, e.g. '03')",
  "title": "string",
  "subtitle": "string  (optional)"
}
```

---

# Content Layouts

## card_grid

Parametric card showcase, **1–9 cards**. Light background, title bar at top.
Each card: white fill, top accent line, a dot, a heading, and body text.
Auto-layout by count: 1→1×1, 2→1×2, 3→1×3, 4→2×2, 5→3+2 (centered),
6→2×3, 7→4+3 (centered), 8→2×4, 9→3×3.

```json
{
  "template": "card_grid",
  "title": "string",
  "cards": [ { "heading": "string", "text": "string" } ]
}
```

## icon_list

Vertical numbered list, **1–8 items**. Light background, title bar at top.
Each row: a numbered circle, a bold label, and a description line.

```json
{
  "template": "icon_list",
  "title": "string",
  "items": [ { "label": "string", "description": "string" } ]
}
```

## structured_content

One detailed topic broken into sub-sections. Light background. A bordered
white card holds a numbered badge + heading, then a list of sections (each
a dot + heading + text). Optional dark bottom bar for a summary line.

```json
{
  "template": "structured_content",
  "title": "string",
  "number_badge": "string  (e.g. '01')",
  "heading": "string  (card heading)",
  "sections": [ { "heading": "string", "text": "string" } ],
  "bottom_bar": { "heading": "string", "text": "string" }
}
```

## grid_content

Multi-zone dashboard on a dark background. A left card (~38%, number +
heading + content) and a stack of right cards (each a heading + label/value
items). Optional bottom bar.

```json
{
  "template": "grid_content",
  "title": "string",
  "subtitle": "string  (optional)",
  "left_card": { "number": "string", "heading": "string", "content": "string" },
  "right_cards": [
    { "heading": "string",
      "items": [ { "label": "string", "text": "string" } ] }
  ],
  "bottom_bar": { "heading": "string", "text": "string" }
}
```

---

# Data Display

## kpi_dashboard

KPI strip + supporting detail. Light background, title bar at top.
A row of **1–6 KPI tiles** (big number + label), then **1–4 detail cards**
(white, top accent line, heading + body text).

```json
{
  "template": "kpi_dashboard",
  "title": "string",
  "kpis": [ { "value": "string", "label": "string" } ],
  "detail_cards": [ { "heading": "string", "text": "string" } ]
}
```

---

# Emphasis

## big_statement

A single key message on a dark background. Large centered statement, a
decorative quote mark and faint circle, optional attribution line.

```json
{
  "template": "big_statement",
  "statement": "string  (\\n for line breaks)",
  "attribution": "string  (optional)"
}
```

## big_statement_minimal

Quiet version of `big_statement`. Centered statement with a short rule
above; no quote mark, no decorative circle. Optional attribution.

```json
{
  "template": "big_statement_minimal",
  "statement": "string  (\\n for line breaks)",
  "attribution": "string  (optional)"
}
```

---

# Closing

## end

Closing slide. Dark background, centered title, a short rule, optional
subtitle and contact line. Decorative corner block and faint circle.

```json
{
  "template": "end",
  "title": "string  (e.g. '感谢阅读')",
  "subtitle": "string  (optional)",
  "contact": "string  (optional)"
}
```

---

## Deck Composition Notes

**Dark/light rhythm.** Alternate dark and light slides:
cover (dark) → content (light) → content (light) → section_break (dark) →
content (light) → kpi_dashboard (light) → big_statement (dark) →
end (dark).

**Recommended distribution (≈10 slides):**
1× cover_pro · 1× section_break · 3–4× card_grid / icon_list /
structured_content · 1× kpi_dashboard · 1× grid_content ·
1× big_statement · 1× end.

**Never:**
- Repeat the same content template 3+ times in a row.
- Ship a slide with no decorative geometric element (accent bars, dots,
  numbered circles — the templates supply these; don't strip them).
- Center every slide's content — vary alignment.
- Leave a zone more than ~30% empty — switch to a simpler template instead.
