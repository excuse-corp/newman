---
name: html-ppt
description: 'Create high-quality PowerPoint presentations. Trigger on: ''make me
  a PPT'', ''create a presentation'', ''build a slide deck'', ''html-ppt'', or any
  request for a polished presentation from content.'
when_to_use: Use when the user asks for work related to html-ppt.
---

# HTML-PPT Skill

Five-phase workflow: **Outline → Color → Slide Plan → HTML Preview → PPTX + Per-Slide QA**

Important workflow gate rule:
- When a phase requires user confirmation, selection, or revision, call `request_user_input` and stop the turn.
- Do not use a normal final answer to ask for approval.
- Do not mark a phase complete until the user has explicitly approved or selected the required option.
- If the user replies "继续" while a gate is pending, treat it as approval of the current gate only, then move to the next gate and call `request_user_input` again if that next phase requires user input.

---

## Phase 1: Outline

Generate a numbered outline from the user's content.

Then call `request_user_input`:
- `kind`: `confirm`
- `skill_name`: `html-ppt`
- `phase`: `outline`
- `content`: the full outline
- `prompt`: ask whether the outline is approved or needs revision
- `options`: approve / revise

Stop after this tool call. Do not proceed to color selection in the same turn.

---

## Phase 2: Color Selection

Read `references/design-system.md` for the 5 built-in palettes. Present all options to the user — **never auto-select**. If user describes a custom direction, build a palette using the 6-key theme structure.

Then call `request_user_input`:
- `kind`: `choice`
- `skill_name`: `html-ppt`
- `phase`: `color_selection`
- `content`: the palette options
- `prompt`: ask the user to choose one palette or describe a custom direction
- `options`: one option per built-in palette, plus a custom option if useful

Stop after this tool call. Do not choose a palette yourself.

---

## Phase 3: Slide Plan

Read `references/templates.md` and `references/templates-advanced.md`.

**Template matching:**

| Content Type | Template |
|-------------|----------|
| Cover + metrics | `cover_pro` |
| Chapter divider | `section_break` |
| 2-3 content zones | `grid_content` |
| Single structured topic | `structured_content` |
| 3-6 showcase items | `card_grid` |
| KPIs + detail | `kpi_dashboard` |
| Key message | `big_statement` |
| Closing | `end` |

**Rules:** Vary layouts — never the same template 3× in a row. Template must fit content amount: sparse content → simpler template; don't force it.

**Theme keys** (mandatory, never invent alternatives):
`primary · secondary · accent · text_dark · text_body · bg_light · fontHeading · fontBody`

Present the plan per slide (page / template / content mapping).

Then call `request_user_input`:
- `kind`: `confirm`
- `skill_name`: `html-ppt`
- `phase`: `slide_plan`
- `content`: the slide-by-slide template plan
- `prompt`: ask whether the layout/template plan is approved or needs revision
- `options`: approve / revise

Stop after this tool call. Do not generate HTML until the user approves the slide plan.

---

## Phase 4: HTML Preview

Generate a single `.jsx` artifact: slides as scrollable 16:9 cards (`max-width: 960px`, `overflow: hidden`), page badges on content slides, no animations.

Write the preview artifact only to a path allowed by the current workspace, such as the current working directory or an existing workspace output directory discovered with `list_dir`. Do not target `/root/newman/output/` unless that path is confirmed writable in this run.

If `write_file` fails, do not answer as if generation has started or completed. Fix the path and retry the write in the same turn when possible. If no writable path is available, return a clear blocked response that says the HTML artifact was not generated.

After rendering, self-check: empty zones → fix or switch template; overflow → reduce content; imbalanced columns → redistribute. Show to user, iterate on feedback. This phase may end with an `artifact_ready` response only after the HTML file is successfully written and previewable.

---

## Phase 5: PPTX Export + Per-Slide QA

```bash
python3 html2pptx.py slides.json output.pptx
python /mnt/skills/public/pptx/scripts/office/soffice.py --headless --convert-to pdf output.pptx
rm -f slide-*.jpg && pdftoppm -jpeg -r 150 output.pdf slide
```

**QA loop** (read `references/qa-prompt.md` for the full sub-agent prompt):

```
FOR each slide_N.jpg:
  iteration = 0
  WHILE iteration < 3:
    score = qa_review(slide_N.jpg)          # invoke sub-agent with qa-prompt.md
    IF score.weighted >= 6.0 AND score.min_dim > 3: BREAK
    apply score.PRIORITY_FIX first
    apply [CRITICAL] and [CONTENT] fixes
    apply [DESIGN][POLISH] only if iteration < 2
    regenerate → re-rasterize slide N
    iteration += 1
  IF still failing: log ⚠️ ONE_LINE_VERDICT, continue
```

**Fix rules by type:**

| Type | When | Action |
|------|------|--------|
| [CRITICAL][COLOR] | Always | White card on dark bg; FFFFFF/CCE0FF text |
| [CONTENT] | Always | Increase container `h` +0.3–0.5; reduce fontSize -1–2pt |
| [DENSITY] | iter < 3 | Shrink container to fit content; add content to fill zone |
| [DESIGN][POLISH] | iter ≤ 1 | Accent bar, deco elements, font size gap ≥ 4pt |

**Output summary** after all slides:
```
✅ Passed: [slides] | 🔄 Fixed: [slide N: N iter, what changed] | ⚠️ Flagged: [slide N: ONE_LINE_VERDICT]
DECK-WIDE PATTERNS: [issues on 3+ slides → fix in helper function]
```

Copy final `.pptx` to `/mnt/user-data/outputs/` and present.

---

## Design Principles

1. **Contrast first** — White on dark. Dark on light. Same-family adjacent colors always fail.
2. **Card boundaries must be obvious** — Cards on dark slides: white/light fill only.
3. **Template fits content** — Empty space is a bug. Sparse content → simpler template.
4. **QA is mandatory** — Weighted score < 6.0 or any dimension ≤ 3 = must fix.
5. **PRIORITY_FIX first** — Highest score-per-change fix always goes first.

---

## File Reference

| File | Phase |
|------|-------|
| `references/design-system.md` | 2 — palettes, fonts |
| `references/templates.md` | 3 — base templates |
| `references/templates-advanced.md` | 3 — advanced templates |
| `references/qa-prompt.md` | 5 — QA sub-agent prompt |
| `references/pitfalls.md` | 5 — python-pptx traps |
| `scripts/html2pptx.py` | 5 — primary generator (Playwright bg + python-pptx text) |
| `scripts/json2pptx.py` | 5 — fallback generator (pure python-pptx) |

## Goal

Use this skill to apply the uploaded workflow and bundled resources.

## Workflow

1. Read `SKILL.md` first.
2. Inspect only the bundled resources needed for the task.
3. Use scripts through the documented entrypoints when deterministic execution is needed.

## Constraints

- Keep changes scoped to the user's request.
- Do not load large bundled files unless they are directly relevant.

## Bundled Resources

- `references/design-system.md`
- `references/pitfalls.md`
- `references/qa-prompt.md`
- `references/templates-advanced.md`
- `references/templates.md`
- `scripts/html2pptx.py`
- `scripts/json2pptx.py`

## Python Runtime

- Run bundled Python scripts through `python scripts/run_python.py scripts/<script>.py` from the skill root.
- The wrapper creates `<skill-root>/.venv`, installs `requirements.txt`, and runs the target script with the skill-local interpreter.
- Do not commit or copy the generated `.venv` directory.
