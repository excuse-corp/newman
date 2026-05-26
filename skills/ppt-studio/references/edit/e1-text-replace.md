# E1 — Text-Only Replacement

Change text content of existing text frames. Font, size, color, position, alignment — all preserved.

**Prerequisites:** Read `safety.md` and `workflow.md`. You have inspected the file and located the target shape(s).

---

## The golden rule

```python
# ✗ NEVER do this — wipes all run formatting
shape.text_frame.text = "new text"
paragraph.text = "new text"

# ✓ ALWAYS edit at the run level
for run in paragraph.runs:
    run.text = new_text
```

`text_frame.text =` and `paragraph.text =` collapse all runs into a single unformatted run, destroying the original font/size/color. This is the #1 cause of broken E1 output.

---

## Recipe 1: Single text replacement (most common)

User: "把第3页标题里的 '2024' 改成 '2025'"

```python
from pptx import Presentation

prs = Presentation("/mnt/user-data/uploads/deck.pptx")

# Target: slide 3, shape 0 (located via inspect)
slide = prs.slides[2]  # 0-indexed
shape = slide.shapes[0]

# Find the run containing "2024" and replace
for paragraph in shape.text_frame.paragraphs:
    for run in paragraph.runs:
        if "2024" in run.text:
            run.text = run.text.replace("2024", "2025")

prs.save("/mnt/user-data/outputs/deck_edited.pptx")
```

**Why this preserves formatting:** Each run carries its own font/size/color/bold properties. Replacing only `run.text` leaves all those properties untouched.

---

## Recipe 2: Replace entire text frame content (single-run case)

User: "把第1页副标题换成 '一场不太正经的实验招募'"

If the target text frame has a single run, the cleanest approach:

```python
slide = prs.slides[0]
shape = slide.shapes[1]  # the subtitle

# Single-run case: just replace that one run's text
tf = shape.text_frame
if len(tf.paragraphs) == 1 and len(tf.paragraphs[0].runs) == 1:
    tf.paragraphs[0].runs[0].text = "一场不太正经的实验招募"
else:
    # Multi-run case: see Recipe 3
    ...
```

**Why check single-run first:** Most simple text boxes (titles, subtitles) have exactly one run. The cleanest replacement is to swap the text of that one run.

---

## Recipe 3: Replace multi-run text (preserve formatting of first run, drop others)

User: "把第2页第二张卡片的标题换成 '你的参与方式'"
But the original is: `"你需要" (bold) + "做什么" (regular)` — two runs with different formatting.

Decision: ask user which formatting style to keep, or default to the first run.

```python
tf = shape.text_frame
paragraph = tf.paragraphs[0]

# Keep first run's formatting, drop others
first_run = paragraph.runs[0]
first_run.text = "你的参与方式"

# Remove subsequent runs from the paragraph
for run in paragraph.runs[1:]:
    run._r.getparent().remove(run._r)
```

**Warning:** If the original multi-run formatting was *meaningful* (e.g., a keyword in red), do NOT silently collapse it. Ask the user:
> 原文本里有不同格式的部分（"你需要"加粗，"做什么"正常）。新文本要全部用加粗格式，还是全部用正常格式？

---

## Recipe 4: Bulk replace across the whole deck

User: "把所有页里的 '信管院' 改成 '信管部'"

```python
def replace_in_runs(text_frame, old, new):
    """Replace `old` with `new` in every run of a text frame."""
    for paragraph in text_frame.paragraphs:
        for run in paragraph.runs:
            if old in run.text:
                run.text = run.text.replace(old, new)

def walk_shapes(shapes, fn):
    """Recurse into groups."""
    for shape in shapes:
        if shape.shape_type == 6:  # GROUP
            walk_shapes(shape.shapes, fn)
        elif shape.has_text_frame:
            fn(shape.text_frame)

count = 0
for slide_idx, slide in enumerate(prs.slides):
    def counter(tf, _s=slide_idx):
        nonlocal count
        for p in tf.paragraphs:
            for r in p.runs:
                if "信管院" in r.text:
                    count += 1
    walk_shapes(slide.shapes, counter)
    walk_shapes(slide.shapes, lambda tf: replace_in_runs(tf, "信管院", "信管部"))

print(f"Replaced {count} occurrences across {len(prs.slides)} slides")
```

**Note the GROUP recursion.** Groups contain nested shapes; without recursion, you miss any text inside grouped cards / containers.

**Verify after bulk operations.** Print the count and spot-check a few slides via `pptx_inspect.py` re-run.

---

## Recipe 5: Replace text in a table cell

Tables are nested: `shape.table.rows[i].cells[j].text_frame`.

```python
shape = slide.shapes[2]  # a table shape
table = shape.table

# Target: row 1, col 2
cell = table.rows[1].cells[2]
tf = cell.text_frame

# Same run-level edit as before
for paragraph in tf.paragraphs:
    for run in paragraph.runs:
        if "old_value" in run.text:
            run.text = run.text.replace("old_value", "new_value")
```

**Quirk:** Some table cells start empty with no `runs` (just paragraphs with no runs). To write into an empty cell, use:

```python
if not cell.text_frame.paragraphs[0].runs:
    p = cell.text_frame.paragraphs[0]
    run = p.add_run()
    run.text = "new value"
    # Optionally copy formatting from a sibling cell
else:
    # normal run replacement
```

---

## Recipe 6: Replace text inside a Group shape

Groups contain other shapes — including other groups. Always recurse.

```python
from pptx.enum.shapes import MSO_SHAPE_TYPE

def edit_text_recursive(shapes, old, new):
    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            edit_text_recursive(shape.shapes, old, new)
        elif shape.has_text_frame:
            for paragraph in shape.text_frame.paragraphs:
                for run in paragraph.runs:
                    if old in run.text:
                        run.text = run.text.replace(old, new)

edit_text_recursive(slide.shapes, "2024", "2025")
```

---

## Edge cases to watch for

| Situation | What happens | What to do |
|---|---|---|
| Target text spans multiple runs (e.g. "2024" is "20" + "24") | `run.text` contains only part of the search string; replace misses | Inspect the runs; if split, ask user — or use `paragraph.text` for read-only matching, then rebuild |
| Empty text frame | No paragraphs / no runs | Use `tf.add_paragraph()` then `p.add_run()` |
| Auto-shape with default text "Text Box 1" placeholder | Placeholder text behaves slightly differently | Treat same as text frame; should work |
| Text in a chart label or axis | Chart text is in a separate XML namespace | E1 cannot reach it; escalate or refuse |
| Text in SmartArt | SmartArt is opaque | Refuse; see safety.md |
| Hyperlinked run | Run has `.hyperlink`; preserved as long as you only set `.text` | Safe |

---

## Verification snippet

After editing, dump the changed runs to confirm:

```python
# Before save, print what changed
for slide_idx, slide in enumerate(prs.slides, 1):
    for shape_idx, shape in enumerate(slide.shapes):
        if shape.has_text_frame:
            text = shape.text_frame.text
            if any(marker in text for marker in ["2025", "信管部"]):  # whatever you replaced to
                print(f"  s{slide_idx}_{shape_idx}: {text[:60]}")
```

If the expected slides don't show up in the output, the replacement didn't hit. Diagnose before saving.

---

## When E1 is not enough — escalate

| User actually wants | Path |
|---|---|
| Change text AND make it bold/colored | **E2** |
| Add a NEW line of text to a list | **E3** |
| Replace text but original frame can't hold the new length | **G'** (regenerate page) |
| Replace text in a chart label | **G'** or refuse |
| Replace text in SmartArt | refuse or convert to plain shapes first |
