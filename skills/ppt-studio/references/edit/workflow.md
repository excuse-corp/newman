# E-Path Workflow

The 4-step procedure for all E1 / E2 / E3 operations.

**Prerequisites:** You have completed STEP 0 triage in SKILL.md and confirmed the user wants Path E. You have read `safety.md`.

---

## The 4 steps

```
1. INSPECT  → run pptx_inspect.py, see what shapes exist
2. LOCATE   → match user's request to specific slide_idx + shape_idx
3. EDIT     → execute the appropriate recipe (E1/E2/E3)
4. SAVE     → write to /mnt/user-data/outputs/ + present_files
```

Each step has a checkpoint. **Do not skip ahead** even if the request seems obvious.

---

## Step 1 — INSPECT

Run the inspector on the uploaded PPT:

```bash
python /mnt/skills/user/ppt-studio/scripts/pptx_inspect.py /mnt/user-data/uploads/<file>.pptx
```

Output looks like this (truncated):

```
=== Slide 1 ===
  [s1_0]  TEXT_BOX     "有趣灵魂的AI蒸馏计划"            x=0.42 y=2.10 w=5.80 h=0.80  runs=1
  [s1_1]  TEXT_BOX     "一场不太正经的社科×AI实验招募"   x=0.42 y=3.00 w=5.80 h=0.50  runs=1
  [s1_2]  AUTO_SHAPE   "" (rect, fill=#3D2A1E)            x=0.00 y=0.00 w=3.80 h=5.62
  [s1_3]  PICTURE      <image, 320x240>                   x=6.50 y=1.20 w=2.80 h=2.10

=== Slide 2 ===
  [s2_0]  TEXT_BOX     "这是个什么实验？"                 x=0.60 y=0.42 w=5.40 h=0.50  runs=1
  [s2_4]  GROUP        (3 shapes inside)                  x=0.60 y=1.20 w=8.80 h=3.20
    [s2_4.0]  AUTO_SHAPE  ""                              ...
    [s2_4.1]  TEXT_BOX    "实验是什么"                   ...
    [s2_4.2]  TEXT_BOX    "大家一起捏出一个有人格..."    ...
```

**What to extract from the inspect output:**
- Shape IDs (`s{slide}_{shape}` format) — these are how you reference targets
- Shape type — TEXT_BOX / PICTURE / TABLE / GROUP / SMART_ART / CHART / AUTO_SHAPE
- Text preview — to confirm you're locating the right one
- Position and size — for overflow checks (E3)

**Checkpoint:** Did the inspect output include the content the user wants to change? If not, the file may be malformed or the user's request references something that doesn't exist. Ask for clarification before proceeding.

---

## Step 2 — LOCATE

Match the user's request to specific shape IDs. Three common matching patterns:

### Pattern A — User specifies by content
User: "把'2024年度报告'改成'2025年度报告'"
→ Search inspect output for "2024年度报告"
→ Find `[s1_0]`
→ Target: `slide=1, shape=0`

### Pattern B — User specifies by position
User: "第3页的标题"
→ Slide 3 in inspect output
→ Look for top-most TEXT_BOX (smallest y) on that slide
→ Target: `slide=3, shape=X`

### Pattern C — User specifies by category (bulk)
User: "所有页眉换成'信息管理部'"
→ Identify the page-header pattern (typically a small TEXT_BOX near y=0.0-0.5 on every slide)
→ Target: list of (slide, shape) pairs across all slides

**Confirmation step (mandatory when ambiguous):**

If there's any chance you've located the wrong shape — multiple matches, ambiguous position, or a critical change — confirm with the user *before* editing:

> 我找到的目标是：第3页的标题文本框，内容"2024年度报告总结"。要改为"2025年度报告总结"，对吗?

If the inspect output reveals the target is a SmartArt, Chart, or sits inside a deeply-nested group — re-check `safety.md` before proceeding.

**Checkpoint:** Have you written down the exact (slide_idx, shape_idx) targets? If you can't list them concretely, you haven't located yet.

---

## Step 3 — EDIT

Based on the path determined in triage, open the corresponding recipe file:

| Path | Recipe file |
|---|---|
| E1 (text only) | `e1-text-replace.md` |
| E2 (text + format) | `e2-format-tweak.md` |
| E3 (structural) | `e3-structure-edit.md` |

Each recipe file contains:
- Python code templates you can adapt
- Common pitfalls specific to that operation
- Verification snippets to confirm the edit worked

**Universal rules during the edit step:**

1. **Work on a copy.** Load the original from `/mnt/user-data/uploads/`, save to `/mnt/user-data/outputs/`. Never modify in place.
2. **Edit run-by-run, not paragraph-by-paragraph or text-frame-by-text-frame.** See `safety.md` "quirky" section.
3. **Preserve formatting by default.** Only change attributes the user explicitly asked about.
4. **One slide at a time.** Even for bulk edits, iterate explicitly — don't try to write clever one-liners that hide what's changing.
5. **Print before/after for sanity.** During development, print `(slide_idx, shape_idx, old_text, new_text)` so you can verify.

**Checkpoint:** After the edit, the modified Presentation object should be in memory. You haven't saved yet.

---

## Step 4 — SAVE

```python
output_path = "/mnt/user-data/outputs/<original_filename>_edited.pptx"
prs.save(output_path)
```

**Filename convention:**
- Default: `{original_stem}_edited.pptx`
- If multiple edit sessions: `{original_stem}_edited_v2.pptx`, etc.
- If user specified a name: honor it

After saving:

1. Call `present_files` with the output path
2. Write a 1-2 line summary in chat:
   > 已修改第3页标题"2024" → "2025"，其他内容未动。

3. If the operation was E3 or near-overflow, add a verification hint:
   > 建议打开文件确认列表项位置和间距正常。

---

## Verification (recommended for E3, optional for E1/E2)

Re-run `pptx_inspect.py` on the output file and compare:

```bash
python pptx_inspect.py /mnt/user-data/outputs/<file>_edited.pptx
```

Spot-check:
- Did the target shapes update?
- Did any non-target shapes change unexpectedly?
- Did slide count change as intended (E3 only)?

If anything looks off, do not present the file. Diagnose first.

---

## Common workflow mistakes

| Mistake | Why it's bad |
|---|---|
| Editing before inspecting | You don't know what shapes exist; high risk of changing the wrong one |
| Skipping the LOCATE confirmation when ambiguous | You'll edit the wrong shape and have to redo |
| Using `text_frame.text = "..."` to set text | Wipes all run formatting |
| Modifying the file in `/mnt/user-data/uploads/` | Uploads is read-only; will throw |
| Saving without `present_files` | User can't see the file |
| Producing a long postamble explaining what you did | Keep it to 1-2 lines |
