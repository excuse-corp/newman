# E2 — Text + Format Tweak

Everything E1 does, plus lightweight format changes on specific runs: font size, bold/italic/underline, color, font name.

E2 is a **superset of E1**. If the user wants both text change and format change in one operation, use E2.

**Prerequisites:** Read `safety.md`, `workflow.md`, and `e1-text-replace.md`. Run-level editing principles from E1 still apply.

---

## What E2 can change

| Attribute | Code | Notes |
|---|---|---|
| Font size | `run.font.size = Pt(18)` | Use `Pt` from `pptx.util` |
| Bold | `run.font.bold = True/False/None` | `None` means "inherit" |
| Italic | `run.font.italic = True/False/None` | |
| Underline | `run.font.underline = True/False` | Single-line underline only |
| Color (RGB) | `run.font.color.rgb = RGBColor(0x3D, 0x2A, 0x1E)` | Solid colors |
| Font name | `run.font.name = "Microsoft YaHei"` | Must exist on opener's system |

**What E2 cannot change:** position, size of the shape itself, fill color of the shape (only text color), paragraph-level alignment, line spacing, indentation. Those edge cases push into E3 territory or beyond.

---

## Imports you'll need

```python
from pptx import Presentation
from pptx.util import Pt
from pptx.dml.color import RGBColor
```

---

## Recipe 1: Bold a specific phrase within a run

User: "把第3页标题里的 '重要' 两个字加粗"

This is the trickiest E2 case — the target phrase is inside a run, but only part of it should become bold. You have to **split the run into 3 runs**: before / target / after.

```python
def split_run_at_phrase(paragraph, run_idx, phrase):
    """Split a run into [before, phrase, after] runs. Returns the middle run."""
    run = paragraph.runs[run_idx]
    text = run.text
    if phrase not in text:
        return None
    
    before, _, after = text.partition(phrase)
    
    # Truncate original run to "before"
    run.text = before
    
    # Insert "phrase" run after current
    from copy import deepcopy
    phrase_r = deepcopy(run._r)
    phrase_r.find(".//{http://schemas.openxmlformats.org/drawingml/2006/main}t").text = phrase
    run._r.addnext(phrase_r)
    
    # Insert "after" run
    after_r = deepcopy(run._r)
    after_r.find(".//{http://schemas.openxmlformats.org/drawingml/2006/main}t").text = after
    phrase_r.addnext(after_r)
    
    # Re-read paragraph.runs to get the new middle run
    return paragraph.runs[run_idx + 1]

# Usage:
slide = prs.slides[2]
shape = slide.shapes[0]  # title
paragraph = shape.text_frame.paragraphs[0]

# Find which run contains "重要"
for i, run in enumerate(paragraph.runs):
    if "重要" in run.text:
        middle = split_run_at_phrase(paragraph, i, "重要")
        if middle:
            middle.font.bold = True
        break
```

**Why the deepcopy:** Copying the XML element preserves all the original run's formatting (font, size, color). The middle run inherits everything, you only modify what you explicitly change (bold).

**Simpler alternative:** If the entire run already contains exactly "重要" and nothing else, no split needed — just `run.font.bold = True`.

---

## Recipe 2: Change font size on a whole text frame

User: "把第2页的正文字号调大一号"

When the user says "字号大一号", interpret as "+2pt" by convention (matches how PowerPoint's font-size buttons step).

```python
slide = prs.slides[1]
shape = slide.shapes[2]  # body text

for paragraph in shape.text_frame.paragraphs:
    for run in paragraph.runs:
        # Read current size; may be None if inherited from layout
        current = run.font.size
        if current is None:
            # Get inherited size — check the paragraph's font, then layout
            # Simpler approach: ask user for absolute target size
            print(f"Warning: run uses inherited size; setting to 18pt as default")
            run.font.size = Pt(18)
        else:
            run.font.size = Pt(current.pt + 2)
```

**Pitfall:** `run.font.size` returns `None` when the run inherits its size from the layout/master. You can't `+2` to `None`. Either:
- Set an absolute size (ask user)
- Or read the inherited size by walking up the layout chain (complex)

When in doubt, **ask the user for the target size in pt** rather than guessing.

---

## Recipe 3: Change color on specific runs

User: "把第3页所有的'¥'符号标红"

```python
RED = RGBColor(0xC0, 0x1A, 0x1A)

slide = prs.slides[2]
for shape in slide.shapes:
    if not shape.has_text_frame:
        continue
    for paragraph in shape.text_frame.paragraphs:
        for run in paragraph.runs:
            if "¥" in run.text:
                # If the run contains ONLY "¥" or pure currency strings, color the whole run
                # If "¥" is embedded in larger text, split first (see Recipe 1)
                if run.text.strip() == "¥" or run.text.replace("¥", "").replace(" ", "").replace(",", "").isdigit():
                    run.font.color.rgb = RED
                else:
                    # Need run-splitting to color just the symbol
                    # ... (use split_run_at_phrase from Recipe 1)
                    pass
```

**Common colors (hex → RGBColor):**
```python
RED      = RGBColor(0xC0, 0x1A, 0x1A)  # warm red, not stark
DARKRED  = RGBColor(0x79, 0x1F, 0x1F)
BLUE     = RGBColor(0x18, 0x5F, 0xA5)
GREEN    = RGBColor(0x3B, 0x6D, 0x11)
ORANGE   = RGBColor(0xBA, 0x75, 0x17)
GRAY     = RGBColor(0x5F, 0x5E, 0x5A)
BLACK    = RGBColor(0x00, 0x00, 0x00)
WHITE    = RGBColor(0xFF, 0xFF, 0xFF)
```

If the user specifies a color casually ("红色" / "蓝色"), use these defaults. If they specify a precise hex / RGB, honor that.

---

## Recipe 4: Bold an entire run (or entire text frame)

User: "把第1页标题加粗"

```python
slide = prs.slides[0]
shape = slide.shapes[0]  # title

for paragraph in shape.text_frame.paragraphs:
    for run in paragraph.runs:
        run.font.bold = True
```

Same pattern works for `italic`, `underline`, etc.

---

## Recipe 5: Change font name across the deck

User: "把所有标题字体换成思源黑体"

```python
def is_title_shape(shape, slide):
    """Heuristic: title shapes are placeholders with idx 0 or top-most text box."""
    if shape.is_placeholder:
        ph = shape.placeholder_format
        if ph.idx == 0 or ph.type in (13, 14, 15):  # title placeholders
            return True
    return False

target_font = "Source Han Sans CN"  # 思源黑体

for slide in prs.slides:
    for shape in slide.shapes:
        if is_title_shape(shape, slide) and shape.has_text_frame:
            for paragraph in shape.text_frame.paragraphs:
                for run in paragraph.runs:
                    run.font.name = target_font
```

**Font availability warning:** Tell the user:
> 字体已设为"思源黑体"。如果打开者电脑没有安装这个字体，PowerPoint 会自动替换成默认字体显示。建议把字体文件随PPT一起发送。

---

## Recipe 6: Copy formatting from one run to another (helper utility)

When you need to add a new run that matches existing formatting (e.g., adding a list item in E3, or filling an empty cell from E1 Recipe 5):

```python
def copy_run_format(src_run, dst_run):
    """Copy font/size/color/bold/italic from src to dst."""
    src_f = src_run.font
    dst_f = dst_run.font
    
    if src_f.name is not None:
        dst_f.name = src_f.name
    if src_f.size is not None:
        dst_f.size = src_f.size
    if src_f.bold is not None:
        dst_f.bold = src_f.bold
    if src_f.italic is not None:
        dst_f.italic = src_f.italic
    
    # Color is trickier — only copy if it's an explicit RGB
    try:
        if src_f.color.rgb is not None:
            dst_f.color.rgb = src_f.color.rgb
    except AttributeError:
        pass  # theme color, skip
```

**Use case:** Adding a new bullet "第4项" that should match the existing "第1项 / 第2项 / 第3项" styling:

```python
tf = shape.text_frame
new_p = tf.add_paragraph()
new_run = new_p.add_run()
new_run.text = "第4项"

# Match the first bullet's format
src = tf.paragraphs[0].runs[0]
copy_run_format(src, new_run)
```

---

## Edge cases

| Situation | What happens | Mitigation |
|---|---|---|
| User says "字号大一号" but `run.font.size` is `None` | Inherited from layout; can't do relative math | Ask user for absolute target size, or set sensible default (18pt body, 28pt title) |
| User says "颜色变深一点" | Subjective; depends on current color | Ask for absolute color, or shift -30 on each RGB channel as a guess (then ask if good) |
| Multiple runs in one paragraph have different sizes | Applying "size +2" to all keeps the relative hierarchy | Verify after — print all run sizes |
| User wants underline but the run already has italic | Both can coexist; just set `underline = True` | Trivial; no special handling |
| Theme color (not RGB) on existing run | `run.font.color.rgb` raises AttributeError or returns None | Wrap reads in try/except (see Recipe 6) |
| Setting size with float | `Pt(17.5)` works; PowerPoint rounds to 0.5pt | Allow it; user gets what they asked for |

---

## Verification snippet

After E2, print per-run formatting to confirm:

```python
def dump_runs(slide, slide_idx):
    for shape_idx, shape in enumerate(slide.shapes):
        if not shape.has_text_frame:
            continue
        for p_idx, p in enumerate(shape.text_frame.paragraphs):
            for r_idx, r in enumerate(p.runs):
                f = r.font
                size = f.size.pt if f.size else "inherited"
                color = f.color.rgb if (f.color and hasattr(f.color, 'rgb') and f.color.rgb) else "inherited"
                print(f"  s{slide_idx}_{shape_idx}.p{p_idx}.r{r_idx}: "
                      f"'{r.text[:30]}' size={size} bold={f.bold} color={color}")

# Dump only the slides you edited
for i in [3, 5]:
    print(f"=== Slide {i} ===")
    dump_runs(prs.slides[i-1], i)
```

If the changes don't appear in the dump, the edit didn't take effect.

---

## When E2 is not enough — escalate

| User actually wants | Path |
|---|---|
| Change paragraph alignment / line spacing / indentation | **E3** (paragraph-level operations) |
| Resize the shape itself, not just the text | **E3** |
| Recolor the shape's fill (not its text) | **E3** |
| Apply consistent styling across all slides (rebrand) | **G** (whole-deck regenerate) |
| Restyle while also adding decorative elements | **G'** (regenerate that page) |
