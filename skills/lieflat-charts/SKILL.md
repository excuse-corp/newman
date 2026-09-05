---
name: lieflat-charts
description: Template-driven data visualization and HTML report generation using Lieflat Charts. Use when Codex needs to turn data into polished single-file HTML charts, chart pages, bilingual-ready reports, visual reports, annual/monthly reports, white papers, posters, dashboard-style briefs, or when the user explicitly invokes lieflat-charts. Default to chart mode unless the user asks for a full report.
---

# Lieflat Charts

Use this skill to turn data into polished single-file HTML charts or full HTML reports by reusing the bundled Lieflat templates. Keep the design output identical in spirit to the original library: template-first, data-proportional, restrained, editorial, and validated.

## Fast Path

For ordinary chart requests, do not load the full design law. Execute this short path:

1. Classify the data shape and requested reading speed.
2. Search `catalog.md` for 1-3 plausible candidates; prefer the priority rules below.
3. Read only the selected gallery file and only the relevant card/render block.
4. Read `mono-tokens.js`; read `color-presets.js` only when using a color preset or custom color roles.
5. Build a single-file HTML output from the selected template skeleton, replacing data, title, subtitle, legend notes, and source.
6. Run a syntax check on extracted inline script or `node --check` on generated JavaScript when practical.

Escalate to `references/full-design-law.md` only when the request is ambiguous, high-stakes visually, report-sized, custom-color-heavy, map/interactive/new-chart work, or when a quality check fails.

## Output Mode

- Default to **chart mode** for “visualize this data”, “analyze this table”, “make a chart”, “make a few charts”, or “PPT insert” style requests.
- Use **report mode** only when the user explicitly asks for a report, annual report, monthly report, white paper, research one-pager, poster, brief, notebook, dashboard report, or other complete narrative deliverable.
- Follow the input language unless the user specifies otherwise. Do not mix Chinese and English inside one report version.

## Template Priority

- Always generate from bundled templates, not a from-scratch lookalike.
- Default priority is **Lupi Editorial → Lupi Basics → Glance**.
- Main templates are **L1–L15 与 F1–F13**. Use these first when they can encode the data honestly.
- Backup templates are **L16–L20、F14–F17、G19–G22**. Use them only when the main set lacks the right data contract, except for the direct-hit cases below.
- Direct-hit backup cases: OHLC four-value series → **F17 Candlestick**; five-number summary plus outliers → **F15 Tick Box**; one entity across 3-6 continuous dimensions → **L20 Parallel Coordinates**; full-year 52×7 date heatmap → **L17 Calendar Heat**; continuous multi-series composition where total and mix both matter → **F16 Stream Ribbon**.
- Use Glance directly when the user asks for Glance, dashboard, monitoring, weekly report, or “three-second/quick-read” output; otherwise use Glance only after Lupi/Basics do not fit.
- Use Maps only when the user explicitly asks for maps, geography, country/state coloring, or choropleth.

## Quick Selection Map

Use this as a routing shortcut, then verify the exact row in `catalog.md`.

| Data shape | First candidates |
|---|---|
| Few categories, ranking, simple comparison | F1, F5, L2; quick-read: G3 |
| Multi-select percentages, independent 0-100 values | L15; quick-read: G3 |
| 100% composition / shares | L14, F4; quick-read: G4; near-equal showpiece: G2 |
| Positive/negative categories | G10 |
| Daily time series | F2 for <=30 days; F3 for 30-60 days; L3 for ~90 days; G1 for daily ranges |
| Cumulative growth / one hero total | G18 |
| Before/after or this-year/last-year | F12 or F6 |
| Funnel / staged drop-off | L13 |
| Waterfall / bridge | F9 |
| Progress to target | F11; quick-read: G18 |
| Scatter, relationship, small entity set | F8; animated multi-view: G9 |
| Raw distribution / many records | G15; dense unit-preserving: L18 |
| Histogram / meaningful bins | F14 |
| Box/whisker summary plus outliers | F15 Tick Box |
| Matrix, category x category x value | L4 or L9; dense: L16; quick-read labels: G20 |
| Weekday x hour heat | F10 or G14 |
| Hierarchy only | G7 |
| Hierarchy plus positive weights | F13 |
| Multi-series composition over continuous time | F16 Stream Ribbon |
| OHLC prices | F17 Candlestick |
| 3-6 continuous dimensions per entity | L20 Parallel Coordinates |
| Small network | G6/G11; poster: L6 |
| Large network / paths / flow tracing | B1, B2, B3; aggregate flow only: G22 |
| US/world choropleth | M1/M2 only after explicit map request |

## Design Contract

These rules preserve the original design effect without loading the long law every time:

- Keep the chosen template's geometry, data encoding, animation rhythm, and engine. Replace content, not the visual language.
- Use the card quartet: conclusion title, explanatory subtitle/legend, chart, uppercase source line.
- Make visuals proportional to values. Bars must not use broken axes; area uses sqrt-scaled radius when radius encodes value.
- Use real units: one dot/tick/line should represent a real record, person, event, percentage point, or clearly stated aggregation.
- Keep the Mono grammar unless one color system is justified: paper gray background, charcoal text/data, gray ladder, Inter typography, solid fills, no shadows, no glow, no decorative gradients.
- Respect minimum text sizes: half-card SVG labels >=6.5px; full-width labels >=5.5px. If labels do not fit, use hover/tooltip or reduce shown labels, not microscopic text.
- Use reveal-on-scroll and click-to-replay when the source template uses it. Include reduced-motion fallback from `mono-tokens.js` when applicable.
- Do not add interaction to decorative elements. Add hover/pin only when an element maps to a real record and static reading is insufficient.
- One chart carries one independent conclusion. Multi-chart pages should avoid repeated silhouettes and repeated conclusions.

For exact edge-case wording, refusal rules, and the full historical design law, read `references/full-design-law.md`.

## Color Contract

- Default to Mono when color has no stable data meaning.
- A whole HTML output or related chart set must use exactly one color system: Mono, porcelain, palm, wire, or one user-provided custom system.
- Use porcelain for ordered/single-series blue-ish work, palm for <=4 unordered categories or warm/natural work, and wire for restrained mono work with one controlled highlight.
- For custom colors, define roles instead of scattering hex values: `BG`, `TXT`, `MUT`, `GRID`, `DATA`; add `HERO`, `RAMP`, or `CAT` only when needed.
- Color cannot be the only cue. Keep labels, position, length, area, or annotations sufficient after color is removed.
- If using `templates/color/`, treat those files as color references only; the structure source remains the root `templates/*-gallery.html` file.

## Report Mode

When the user asks for a full narrative report:

1. Read `report-catalog.md`; compare at least 3 candidate report templates unless fewer fit.
2. Lock one language version and one report template from `templates/reports/`.
3. Preserve that report's page width, grid, section order, visual density, color system, and chart-slot relationships.
4. Replace all demo data, sources, conclusions, legends, and content-specific copy.
5. Select each chart slot from `catalog.md` and the relevant gallery template; do not use the report layout as permission to invent chart geometry.
6. Read `references/full-design-law.md` if changing report color systems, replacing chart slots, or producing a publication-grade artifact.

## Implementation Notes

- `catalog.md` is the selection index. Use `rg` for data-shape terms, chart numbers, and card titles instead of reading every gallery.
- Root gallery files are structural sources: `templates/lupi-gallery.html`, `templates/basics-gallery.html`, `templates/glance-gallery.html`, `templates/maps-gallery.html`, and `templates/big-*.html`.
- Color gallery files under `templates/color/` are skin references, not structural sources.
- `mono-tokens.js` supplies typography, layout tokens, deterministic `rnd`, reveal helpers, and CSS. Inline what the final HTML needs.
- `color-presets.js` supplies porcelain, palm, and wire roles. Use one preset only.
- Chart.js charts must mount on `<canvas>`; ECharts charts mount on a normal div and may use SVG renderer when the source template does.
- Do not use `Math.random()` in templates or final generated artifacts; use deterministic data or `rnd()`.

## Validation

- For ordinary final artifacts, run the fastest relevant checks: syntax-check generated scripts, inspect obvious label overlap, and verify the chart renders if a browser check is already cheap.
- Run `node scripts/validate.mjs` from the skill root after editing the skill package itself.
- Do not run `scripts/smoke-new-charts.mjs` during ordinary user chart generation. It is a slow maintenance smoke test for gallery/template development.
- Before delivering, verify: template identity preserved, values proportional, color system singular, labels legible, no demo data left, no broken CDN assumption hidden from the user, and source line updated.

## Full Law Escalation

Read `references/full-design-law.md` before acting when:

- Creating or translating a chart type not directly covered by `catalog.md`.
- Handling custom brand colors, reference-image translation, dense multi-chart pages, maps, big interactive charts, or full reports.
- Choosing a backup template outside the direct-hit cases.
- Resolving conflicts between data honesty, label density, animation, color, and template aesthetics.
- The user explicitly asks for strict Lieflat fidelity, publication-ready polish, or unchanged design behavior.

