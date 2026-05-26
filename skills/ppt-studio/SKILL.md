---
name: ppt-studio
description: Create new PowerPoint presentations OR edit/extend existing ones with
  precision. Use this skill when the user wants to (a) build a new slide deck from
  scratch — triggers like "做PPT/做个汇报/做一份slides/pptx"; (b) modify an existing PPT they
  uploaded — triggers like "改这份PPT/替换文字/调字号/删页/合并/加页/扩写"; (c) regenerate or restyle
  a deck using an uploaded PPT as content source — triggers like "翻新/重做风格/参考这份做新的";
  or (d) any task where a .pptx file is the input, output, or both. Always consult
  this skill the moment a .pptx is involved, even casually mentioned.
when_to_use: Use when the user asks for work related to ppt-studio.
---

# ppt-studio

A unified PPT skill with three technical paths:
- **G (Generate)** — build new decks from scratch via render.py (HTML preview + python-pptx export)
- **E (Edit)** — modify uploaded .pptx files via python-pptx, preserving original structure
- **G' (Insert)** — generate new pages and splice them into an existing deck

## STEP 0 — Triage (mandatory before anything else)

Do NOT start working until you have answered both questions below.

### Q1: Did the user upload a `.pptx` file?

Check `/mnt/user-data/uploads/` for any `.pptx`.

- **No upload** → Path **G** (new deck). Read only `references/generate/`. Skip the rest of this document.
- **One upload** → Continue to Q2.
- **Multiple uploads** → Ask the user which file is the target to edit, and what role the others play (content source? style reference?). Do not guess.

### Q2: What does the user want to do with the uploaded file?

Match the user's request against this table. The signal is the **verb + scope**, not the topic.

| User signal (Chinese / English) | Path |
|---|---|
| 改字 / 改数字 / 改标题 / 替换文字 / "把X改成Y" / "find and replace" | **E1** |
| 改字号 / 加粗 / 改颜色 / 调字体 / "make bigger/bolder/red" (E2 includes E1 capabilities) | **E2** |
| 加一条 / 删一条 / 删第N页 / 复制页 / 合并两页 / 调顺序 (original layout still fits) | **E3** |
| 扩写某页 / 把一页拆成N页 / 在原PPT中新增N页 (keep most of original deck, add/expand specific pages) | **G'** |
| 整体翻新 / 用这份的内容重做一版 / 参考这份做新的 (treat upload as content source, build fresh deck) | **G** |
| Vague: "改一下" / "优化一下" / "看着办" | **Ask the user** with `ask_user_input_v0` to choose between "精准改内容（保留原版式）" / "扩写/新增页" / "整体重做" |

### Q3: Will the change fit within the original layout? (only for additions / expansions)

When user wants to add content within an existing page, judge whether the original text frame or shape has room:
- 3 bullets → 4 bullets: usually fits → **E3**
- 3 bullets → 8 bullets: probably overflows → **G'**
- "expand this sentence into a longer one": fits → **E1 / E2**
- "expand this page into 3 pages": doesn't fit → **G'**
- "add a new slide about XXX": new structure → **G'**

If unsure, run `pptx_inspect.py` first to see actual shape dimensions (each shape's coordinates and approximate text capacity), then decide.

---

## After triage, read ONLY the relevant references

| Path | Read these directories | Do NOT read |
|---|---|---|
| G | `references/generate/` | edit/, insert/ |
| E1 / E2 / E3 | `references/edit/` + `references/shared/` | generate/, insert/ |
| G' | `references/insert/` + `references/generate/` + `references/shared/` | edit/ (it's about preserving, G' is about generating) |

**Why this matters:** Cross-reading the wrong path's docs causes Claude to mix incompatible toolchains (render.py's dual-render engine vs. the python-pptx edit scripts) and produce broken output. The triage above is binding.

---

## Path G — Generate New Deck

Build a slide deck from scratch. The user provides content, you produce a polished `.pptx`.

**Entry point:** Read `references/generate/workflow.md` for the full procedure (outline → palette → slide plan → plan.json → HTML preview + QA → PPTX export).

**Toolchain:** plan.json → `render.py --preview` (HTML preview, same layout logic as PPTX) → user confirms → `render.py --export` (python-pptx, editable text boxes). See `references/generate/render-architecture.md` for the dual-render design.

**Output:** `.pptx` saved to `/mnt/user-data/outputs/`, then `present_files`.

---

## Path E — Edit Existing Deck

Modify the user's `.pptx` while preserving its original shapes, layouts, themes, and editability.

**Before doing anything in Path E:**
1. Read `references/edit/safety.md` first — it defines what python-pptx can and cannot reliably do, and when an operation should escalate to G'.
2. Then read `references/edit/workflow.md` for the 4-step procedure (inspect → locate → edit → save).
3. Run `scripts/pptx_inspect.py` on the uploaded PPT before editing — never edit blind.

**Three sub-paths (escalating capability):**

### E1 — Text-only replacement
Change text content of existing text frames. Font, size, color, position all preserved exactly.
**Read:** `references/edit/e1-text-replace.md`
**Example:** "把第3页标题里的 '2024' 改成 '2025'", "所有页眉换成'信息管理部'"

### E2 — Text + format tweak (superset of E1)
Everything E1 does, plus lightweight format changes on specific runs (font size, bold/italic, color).
**Read:** `references/edit/e2-format-tweak.md` (after e1-text-replace.md)
**Example:** "标题加粗", "把'重要'两个字标红", "正文字号大一号", "把'XXX'改成'YYY'并加粗"

### E3 — Structural edit (within layout capacity)
Add/remove paragraphs in a list, add/remove slides, reorder slides, merge same-style text blocks.
**Read:** `references/edit/e3-structure-edit.md`
**Example:** "第3页的列表加一条'XXX'", "删掉第5页", "把第2页和第3页合并"

If the operation outgrows E3's capacity (content overflows the original frame), escalate to G'.

---

## Path G' — Generate + Insert

For requests that expand the original deck: insert new pages, or replace specific pages whose content has outgrown the original layout. The original deck is the host; new pages are spliced in.

**Use G', not G, when:** the user wants to keep most of the original deck intact and add/expand specific pages.
**Use G, not G', when:** the user wants a fully new deck, treating the upload only as content reference.

**Entry point:** Read `references/insert/workflow.md`.

**Procedure:**
1. Extract theme (colors, fonts) from the original PPT via `references/insert/theme-extract.md` — so new pages don't visually clash
2. Generate the new page(s) via Path G's standard flow, but only the pages we need
3. Splice the new pages into the original deck via `scripts/pptx_insert.py` (insert at position, or replace specific slides)
4. **Always tell the user** that newly inserted pages may have slight visual differences from the original pages, since they're built by a different rendering pipeline

---

## After-task hygiene (all paths)

1. Save the final `.pptx` to `/mnt/user-data/outputs/`
2. Call `present_files` with that path
3. Keep the chat summary to 1-2 lines describing what changed
4. If you used E3 or any near-overflow operation, suggest the user open the file and verify before sharing it onward

---

## Common pitfalls

- **Skipping triage** — the #1 cause of failure. Always answer Q1 and Q2 before any tool call.
- **Reading both `generate/` and `edit/`** — they describe incompatible toolchains. Read only the one for your path.
- **Trying to "edit" by regenerating** — if the user uploaded a PPT and asked to change one word, do NOT regenerate the whole deck. That destroys their original work. Use E1.
- **Trying to "generate" by editing** — if the user wants a new deck, do NOT try to template off some old PPT. Use G.
- **Forgetting `pptx_inspect.py`** — never edit a PPT blind. Always inspect first to know what shapes exist.
- **Silently producing visual mismatches in G'** — always disclose that newly inserted pages may differ stylistically.
- **Hand-writing HTML for preview (Path G)** — never use `show_widget` or write HTML by hand as a preview. The ONLY valid preview is the file from `render.py --preview`, delivered via `present_files`. A widget or hand-written HTML looks different from the PPTX and misleads the user into approving something they won't actually get.
- **Running QA after PPTX export** — QA belongs in Phase 4b on the HTML-rasterized images, not Phase 5. If QA runs post-export, fixes require a full re-export.

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

- `references/edit/e1-text-replace.md`
- `references/edit/e2-format-tweak.md`
- `references/edit/e3-structure-edit.md`
- `references/edit/safety.md`
- `references/edit/workflow.md`
- `references/generate/palettes.md`
- `references/generate/pitfalls.md`
- `references/generate/qa-prompt.md`
- `references/generate/render-architecture.md`
- `references/generate/templates.md`
- `references/generate/typography.md`
- `references/generate/visual-language.md`
- `references/generate/workflow.md`
- `references/insert/insert-recipes.md`
- `references/insert/workflow.md`
- `references/shared/extract-content.md`
- `references/shared/extract-theme.md`
- `scripts/ppt_render/__init__.py`
- `scripts/ppt_render/core.py`
- `scripts/ppt_render/templates.py`
- `scripts/pptx_insert.py`
- `scripts/pptx_inspect.py`
- `scripts/render.py`

## Python Runtime

- Run bundled Python scripts through `python scripts/run_python.py scripts/<script>.py` from the skill root.
- The wrapper creates `<skill-root>/.venv`, installs `requirements.txt`, and runs the target script with the skill-local interpreter.
- Do not commit or copy the generated `.venv` directory.
