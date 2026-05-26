# QA Sub-Agent Prompt

## When QA Runs

**Phase 4b** — after `render.py --rasterize` produces `qa/slide-N.jpg` from the HTML preview.

QA runs on the HTML-rasterized images, **not** on the final PPTX. Because the HTML preview and PPTX share the same `layout()` logic, passing QA at Phase 4 means the PPTX will also pass. There is no separate QA loop in Phase 5.

---

## Scoring Model

Weighted Score = D1×0.15 + D2×0.20 + D3×0.25 + D4×0.20 + D5×0.20

| Dim | Topic | Weight |
|-----|-------|--------|
| D1 | Typography | 0.15 |
| D2 | Color & Contrast | 0.20 |
| D3 | Layout & Composition | 0.25 |
| D4 | Visual Expression | 0.20 |
| D5 | Premium & Polish | 0.20 |

Thresholds: ≥8.0 approved · 6.0–7.9 approved with notes · <6.0 fail · any dim ≤3 auto-fail

---

## Prompt (send this with each slide image)

```
You are a strict presentation design QA reviewer. Score this slide across 5 dimensions (1–10 each).
Be harsh — 7 = acceptable with issues, 9+ = genuinely polished, ≤5 = must fix.

━━━ D1 TYPOGRAPHY (×0.15) ━━━
- Font appropriate for professional context; Chinese+English pairing quality
- Title/body/caption size hierarchy: gap between levels ≥ 4pt
- Body line spacing 1.3–1.5×; bold vs regular weight contrast creates focal points
- ≤ 2 font families; no text clipping, truncation, or contrast failure
Score killers: all text same size, no weight variation, clipped text.

━━━ D2 COLOR & CONTRAST (×0.20) ━━━
- Color tone unified; primary/secondary/accent ratio ~6:3:1
- Text contrast passes WCAG AA (≥4.5:1) — squinting to read = fail
- Colors are doing information work (levels, categories, emphasis)
- No color pollution; palette feels premium not cheap

CRITICAL CAPS — any of these caps D2 score at 4:
▸ Same-family card on dark bg (mid-blue card on dark-blue bg) → cap 4
▸ Squint test: blur eyes, can you count the cards? No → cap 5
▸ Secondary-color text on primary-color bg (nearly invisible) → cap 4

━━━ D3 LAYOUT & COMPOSITION (×0.25) ━━━
- Visual flow natural (Z/F-pattern or clear center-out)
- Elements grid-aligned; no floating or misaligned pieces
- No zone >30% dead space; no zone overstuffed
- Title/content/decorative zones proportionally balanced
Score killers: large empty bottom half, unbalanced columns, floating elements.

━━━ D4 VISUAL EXPRESSION (×0.20) ━━━
- Information form matches content type (process→flow, data→chart)
- Not a pure text wall; key numbers/data visually emphasized
- Icon/illustration style consistent; visuals reduce reading cost
- Core message has clear visual emphasis (size, color, isolation)
Score killers: uniform visual weight, no focal point, text-only on data-heavy slide.

━━━ D5 PREMIUM & POLISH (×0.20) ━━━
- Unified design language; details (borders, spacing, accents) consistent
- No cheap signals: blurry assets, distorted shapes, over-the-top effects
- 3-second trust test: first-time viewer — does this build credibility instantly?
- Gap vs reference-quality decks (McKinsey / Apple Keynote)?
Score killers: clashing decorative elements, inconsistent borders, anything that reads as rushed.

━━━ VERDICT (return exactly this, no extra text) ━━━

D1_TYPOGRAPHY: X/10
D2_COLOR: X/10
D3_LAYOUT: X/10
D4_EXPRESSION: X/10
D5_POLISH: X/10
WEIGHTED_SCORE: X.X
APPROVED: true/false

TOP_3_ISSUES (only if false, ordered by score impact):
1. [Dx][TAG] element → problem → exact fix → score delta
2. [Dx][TAG] element → problem → exact fix → score delta
3. [Dx][TAG] element → problem → exact fix → score delta

PRIORITY_FIX: [Dx] element → change → estimated weighted score gain

ONE_LINE_VERDICT: [one sentence: main weakness + what fixing it would achieve]

Tags: [CRITICAL] [CONTENT] [DENSITY] [DESIGN] [COLOR] [POLISH]
```

---

## QA Loop Logic

```
FOR each qa/slide-N.jpg:
  iteration = 0
  WHILE iteration < 3:
    send image + prompt → parse verdict
    IF APPROVED OR (WEIGHTED_SCORE ≥ 6.0 AND no dimension ≤ 3): BREAK
    apply PRIORITY_FIX first
    apply [CRITICAL] and [CONTENT] fixes from TOP_3_ISSUES
    apply [DESIGN][POLISH] only if iteration < 2
    update plan.json → re-run render.py --rasterize for this slide only → re-check
    iteration += 1
  IF still failing after 3 iterations: log ⚠️ ONE_LINE_VERDICT and continue
```

After all slides pass (or are flagged), re-run `render.py --preview` to regenerate the final preview.html with all fixes applied. Then present to user for Phase 4c gate.

---

## Fix Translation

All QA fixes go into `plan.json` or `render.py` — never hand-patch the HTML.

| QA issue | Fix location |
|---|---|
| Wrong color on an element | `theme.*` in plan.json |
| Too much / too little content | slide content fields in plan.json |
| Card layout density | switch template or reduce card count in plan.json |
| Decorative element position or size | `layout()` function in render.py |
| Font size or weight | `layout()` function in render.py |

---

## Output Summary

After all slides:
```
✅ Passed: [slide numbers]
🔄 Fixed: [slide N: N iterations, what changed]
⚠️ Flagged: [slide N: ONE_LINE_VERDICT]
DECK-WIDE PATTERNS: [issues on 3+ slides → fix in shared layout code]
```
