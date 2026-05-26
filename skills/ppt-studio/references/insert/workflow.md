# Insert Path (G') Workflow

Generate new pages via Path G's rendering pipeline, then splice them into the user's existing deck.

**Prerequisites:** STEP 0 triage in SKILL.md has chosen Path G'. You have read `safety.md` from `references/edit/` to understand why G' is needed (operation exceeds E-path capacity).

---

## When this path runs

Triggered by:
- User wants to **expand** one page into multiple pages
- User wants to **insert new pages** with new content
- User wants to **replace a specific page** with a redesigned version
- An E3 operation overflowed the original frame and was escalated here

If the user wants to **regenerate the entire deck**, use Path G (case c) instead — not G'.

---

## The 5-step procedure

```
1. EXTRACT  → pull source content + theme from the original PPT
2. SCOPE    → confirm with user what to generate (how many pages, what content)
3. GENERATE → run Path G to produce a small .pptx of just the new pages
4. SPLICE   → use pptx_insert.py to merge new pages into the original
5. DELIVER  → save + present_files + disclose visual differences
```

Each step has a clear checkpoint. Do not skip ahead.

---

## Step 1 — EXTRACT

Pull the source material from the original deck.

### 1a. Extract content
Read `references/shared/extract-content.md`. Run `extract_full_text_for_slides()` on the page(s) the user wants to expand or replace. If the user is **adding net-new pages** with no source content, skip 1a.

### 1b. Extract theme
Read `references/shared/extract-theme.md`. Run `extract_theme()` on the original PPT to capture its colors and fonts.

**Show the extracted theme to the user** and confirm before proceeding. The user may want to:
- Use the extracted theme as-is (most common)
- Tweak one or two colors
- Override entirely (e.g. "use a completely different palette for the new pages — make them stand out")

**Checkpoint:** Do you have a confirmed `theme` dict and (optionally) extracted source content?

---

## Step 2 — SCOPE

Confirm with the user what pages to generate. The output of this step is a concrete plan: page count, position in original deck, content per page.

Ask whichever questions are unclear:

| User said | You need to clarify |
|---|---|
| "把第3页拆成3页" | Which content goes on each of the 3 new pages? Show the extracted text, suggest a split, ask user to confirm. |
| "在第5页后面加2页" | What goes on each new page? Topic? Template style? |
| "重做第7页" | What's wrong with the current page 7? Show extracted content, ask what to change. |

The result is essentially a **mini-outline for the new pages**. Run this through Path G's Phase 1 (outline confirmation gate).

**Where the new pages will be placed:**
- "Insert N pages after slide X" → splice at position X+1 (1-based)
- "Replace slide X" → delete slide X, then splice new pages at position X
- "Append at end" → splice at len(original.slides) + 1

**Checkpoint:** A clear outline of new pages + a target position.

---

## Step 3 — GENERATE

Run Path G to produce a small `.pptx` containing **only the new pages**.

Read `references/generate/workflow.md`. Note these adjustments for G':
- **Skip Phase 1 outline gate** — you already got the mini-outline approved in Step 2
- **Skip Phase 2 palette selection** — use the extracted (or user-overridden) theme
- **Do not skip Phase 4 (preview)** — even for 1-2 pages, the preview gate catches layout problems before the expensive render

**Output:** a small `.pptx`, e.g. `/home/claude/new_pages.pptx`, containing N new pages.

**Checkpoint:** You have `new_pages.pptx` with the expected number of pages, and the user has approved its visual via Phase 4 preview.

---

## Step 4 — SPLICE

Use `pptx_insert.py` to combine the new pages into the original deck.

```bash
python /mnt/skills/user/ppt-studio/scripts/pptx_insert.py \
  --original /mnt/user-data/uploads/<original>.pptx \
  --new-pages /home/claude/new_pages.pptx \
  --at <position> \
  --mode insert \
  --output /mnt/user-data/outputs/<original>_extended.pptx
```

Modes:
- `insert` — insert new pages at `--at` position (1-based), original pages shift down
- `replace` — replace the slide at `--at` with the new pages
- `append` — add new pages at the end (`--at` ignored)

The script handles:
- Copying the new pages' shapes XML into newly-created slides on the original deck
- Cloning image parts (background PNGs from Path G's rendering) into the target deck
- Re-establishing relationships
- Optional position adjustment

For implementation details, read `references/insert/insert-recipes.md`.

**Checkpoint:** Output `.pptx` exists, opens in PowerPoint, has the expected slide count.

---

## Step 5 — DELIVER

```python
output_path = "/mnt/user-data/outputs/<original_stem>_extended.pptx"
# (pptx_insert.py already wrote here in Step 4)
```

Then:
1. Call `present_files` with the output path
2. **Mandatory disclosure** — tell the user explicitly:
   > 我在你原 PPT 的第 X 页位置插入了 N 页新内容。新页使用了从原 PPT 提取的配色 (`primary: #XXX`...) 保持视觉一致性，但因为新页是用不同的渲染管道生成的，**视觉风格可能与原页面有细微差异**——比如装饰元素、字体渲染、间距等。建议打开文件预览后确认效果。

3. If the user reports the visual mismatch is too big, suggest **falling back to Path G** to regenerate the whole deck for full visual consistency.

---

## Filename conventions

| Operation | Output filename |
|---|---|
| Insert N pages | `{original_stem}_extended.pptx` |
| Replace pages | `{original_stem}_revised.pptx` |
| Append at end | `{original_stem}_extended.pptx` |

If user runs G' multiple times, append `_v2`, `_v3`, etc.

---

## Common failure modes

| Failure | Cause | Fix |
|---|---|---|
| Script fails copying image part | Original PPT or new pages PPT corrupted | Re-run extract; if persistent, fall back to Path G |
| Slide count wrong after splice | Position miscalculated (1-based vs 0-based) | The script uses **1-based positions** to match user mental model |
| Inserted page renders as blank | Background image part rel didn't propagate | Re-run with `--verbose` for diagnostics; usually a missing media part |
| Inserted page visual very off from rest | Theme extraction missed key colors | Re-run Step 1b with user manually correcting the theme |
| Original deck has password protection | Can't open at all | Tell user to remove password first |

---

## When G' is not enough — fall back

| Situation | Fall back to |
|---|---|
| Inserted pages look too different from rest, user wants visual consistency | **Path G** — regenerate whole deck using extracted content |
| User wants to insert pages with totally different theme (intentional contrast) | Stay in G' but skip theme extraction step |
| Original PPT has critical interactive elements (forms, complex animations) | Refuse G' — these are lost during XML manipulation; ask user to manually edit in PowerPoint |
| Inserting more than 50% of total deck length | Suggest Path G — at that scale, regenerating is cleaner than splicing |

---

## Quick checklist

Before delivering:
- ☐ Theme extracted and confirmed by user
- ☐ New page content / outline confirmed by user
- ☐ Path G preview approved by user
- ☐ Splice operation completed without errors
- ☐ Output file slide count matches expectations
- ☐ Visual disclosure given to user
