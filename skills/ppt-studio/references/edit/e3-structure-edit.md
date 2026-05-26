# E3 — Structural Edit

Structural changes within the original layout's capacity: add/remove paragraphs in a list, add/remove slides, reorder slides, duplicate slides, merge same-style text blocks.

**Prerequisites:** Read `safety.md`, `workflow.md`, `e1-text-replace.md`, `e2-format-tweak.md`. E3 builds on E1's run-level editing and E2's `copy_run_format` helper.

---

## The risk profile

E3 operations modify *collections* (paragraphs in a frame, slides in a deck) rather than just leaf attributes. They have two failure modes E1/E2 don't:

1. **Content overflow** — added content exceeds the original shape's capacity, gets clipped or pushed off-slide
2. **Reference corruption** — when you delete/copy/reorder slides, internal XML relationships (rels) can break

Both can produce files that *open* in PowerPoint but look wrong, or that fail to open at all. **Always verify after E3** by re-running `pptx_inspect.py` on the output.

---

## Imports

```python
from pptx import Presentation
from pptx.util import Pt, Inches, Emu
from pptx.dml.color import RGBColor
from copy import deepcopy
from lxml import etree
```

---

## Section A — Paragraph-level operations

These edit the paragraph collection inside a single text frame.

### Recipe A1: Add a new bullet to a list

User: "第3页的列表加一条 'XXX'"

```python
slide = prs.slides[2]
shape = slide.shapes[3]  # the list shape (located via inspect)
tf = shape.text_frame

# Step 1: Find a "template" paragraph to copy formatting from
# (Usually the last existing bullet)
template_p = tf.paragraphs[-1]
template_r = template_p.runs[0] if template_p.runs else None

# Step 2: Add the new paragraph
new_p = tf.add_paragraph()

# Step 3: Copy paragraph-level properties (indent, bullet, level)
# python-pptx doesn't expose all of these directly; copy via XML
new_p._pPr = deepcopy(template_p._pPr) if template_p._pPr is not None else new_p._pPr
new_p.level = template_p.level  # bullet indentation level

# Step 4: Add run with the new text and matching format
new_run = new_p.add_run()
new_run.text = "XXX"
if template_r:
    # Use copy_run_format from e2
    copy_run_format(template_r, new_run)
```

**Overflow check (mandatory):**

```python
def check_overflow(shape):
    """Rough overflow detection. Returns True if text likely overflows the shape."""
    tf = shape.text_frame
    # Count total characters (rough proxy for height)
    total_chars = sum(len(p.text) for p in tf.paragraphs)
    line_count = len(tf.paragraphs)
    
    # Rough estimate: shape height in pt vs estimated content height
    shape_h_pt = shape.height / 12700  # EMU to pt
    estimated_h = line_count * 24  # ~24pt per line at default size
    
    if estimated_h > shape_h_pt * 1.1:  # 10% tolerance
        return True
    return False

if check_overflow(shape):
    print("WARNING: adding this bullet likely causes overflow. Consider escalating to G'.")
```

This overflow check is **rough** (no font metrics, ignores wrapping). For mission-critical cases, ask the user to verify visually after edit.

### Recipe A2: Remove a paragraph

User: "第3页列表的第2条删掉"

```python
slide = prs.slides[2]
shape = slide.shapes[3]
tf = shape.text_frame

# Target: paragraph index 1 (0-indexed for "第2条")
target_p = tf.paragraphs[1]
target_p._p.getparent().remove(target_p._p)
```

**Quirk:** A text frame must have at least one paragraph. If you remove all paragraphs, PowerPoint may show errors. Check before removing:

```python
if len(tf.paragraphs) == 1:
    # Don't remove the last paragraph — clear its text instead
    tf.paragraphs[0].runs[0].text = "" if tf.paragraphs[0].runs else ""
else:
    target_p._p.getparent().remove(target_p._p)
```

### Recipe A3: Reorder paragraphs

User: "第3页的第1条和第2条对换"

```python
tf = shape.text_frame
p_list = list(tf.paragraphs)
target_a = p_list[0]._p
target_b = p_list[1]._p

# XML reorder: insert b before a
parent = target_a.getparent()
parent.remove(target_b)
parent.insert(list(parent).index(target_a), target_b)
```

---

## Section B — Slide-level operations

These edit the slide collection.

### Recipe B1: Delete a slide

python-pptx has no high-level `slides.remove()` — must manipulate XML.

User: "删掉第5页"

```python
def delete_slide(prs, slide_idx):
    """Delete slide at 0-indexed slide_idx."""
    # 1. Get the slide and its rId in the presentation's slide list
    slides = prs.slides
    slide_id_list = slides._sldIdLst
    slide_to_delete = list(slide_id_list)[slide_idx]
    rId = slide_to_delete.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']
    
    # 2. Drop the relationship (frees the slide part from the deck)
    prs.part.drop_rel(rId)
    
    # 3. Remove from the slide list
    slide_id_list.remove(slide_to_delete)

delete_slide(prs, 4)  # delete slide 5 (0-indexed = 4)
```

**Verify after delete:** `len(prs.slides)` should be one less than before.

### Recipe B2: Duplicate a slide

User: "把第3页复制一份放在第4页"

```python
def duplicate_slide(prs, src_idx, dst_idx=None):
    """Duplicate slide at src_idx. If dst_idx is None, append at the end."""
    source = prs.slides[src_idx]
    
    # Create a blank slide with the same layout
    blank_layout = source.slide_layout
    new_slide = prs.slides.add_slide(blank_layout)
    
    # Copy all shapes from source to new
    for shape in source.shapes:
        new_el = deepcopy(shape.element)
        new_slide.shapes._spTree.insert_element_before(new_el, 'p:extLst')
    
    # If dst_idx specified, move new slide to that position
    if dst_idx is not None and dst_idx != len(prs.slides) - 1:
        slide_id_list = prs.slides._sldIdLst
        new_slide_id = list(slide_id_list)[-1]  # the one we just appended
        slide_id_list.remove(new_slide_id)
        slide_id_list.insert(dst_idx, new_slide_id)
    
    return new_slide

duplicate_slide(prs, 2, 3)  # duplicate slide 3 (idx 2), place at position 4 (idx 3)
```

**Known limitations of this approach:**
- Images and charts are **shallow-copied** — they share the same media file underneath. If you later edit the duplicate's image, both originals change. For safer image duplication, you'd need to clone the image part too. For text-only slide duplication, this works.
- Hyperlinks pointing to other slides may point to the wrong target after reordering — verify if the deck uses internal links.

### Recipe B3: Reorder slides

User: "把第5页移到第2页之前"

```python
def move_slide(prs, src_idx, dst_idx):
    """Move slide from src_idx to dst_idx (both 0-indexed)."""
    slide_id_list = prs.slides._sldIdLst
    slides = list(slide_id_list)
    
    target = slides[src_idx]
    slide_id_list.remove(target)
    slide_id_list.insert(dst_idx, target)

move_slide(prs, 4, 1)  # move slide 5 to position 2
```

### Recipe B4: Merge two slides

User: "把第2页和第3页合并成一页"

**Important:** This is a hard operation. The two slides may have different layouts, overlapping shape positions, and incompatible visual structures. Before doing this:

1. **Run inspect on both slides.** Look at shape positions and overall layout.
2. **Decide a strategy** with the user:
   - "Keep page 2's layout, append page 3's content to it"
   - "Keep page 3's layout, prepend page 2's content"
   - "Create a new layout combining both"

Strategy 1 and 2 are E3. Strategy 3 is **G'** (regenerate the merged page).

For strategy 1 (keep page A, append page B's text content):

```python
def merge_text_into(target_slide, source_slide):
    """Append all text content from source_slide into target_slide's first multi-line text frame."""
    # Find the target text frame (usually the body/content placeholder)
    target_tf = None
    for shape in target_slide.shapes:
        if shape.has_text_frame and len(shape.text_frame.paragraphs) > 1:
            target_tf = shape.text_frame
            break
    
    if not target_tf:
        print("WARNING: no suitable target text frame in target slide")
        return
    
    # Collect text from source slide (skip titles, just body text)
    for shape in source_slide.shapes:
        if not shape.has_text_frame:
            continue
        if shape.is_placeholder and shape.placeholder_format.idx == 0:
            continue  # skip title placeholder
        
        for paragraph in shape.text_frame.paragraphs:
            if not paragraph.text.strip():
                continue
            
            new_p = target_tf.add_paragraph()
            new_p._pPr = deepcopy(paragraph._pPr) if paragraph._pPr is not None else new_p._pPr
            for run in paragraph.runs:
                new_run = new_p.add_run()
                new_run.text = run.text
                copy_run_format(run, new_run)

# Usage:
merge_text_into(prs.slides[1], prs.slides[2])  # merge slide 3's content into slide 2
delete_slide(prs, 2)  # then delete slide 3

# Check overflow on the now-merged slide
target_shape = prs.slides[1].shapes[X]  # whichever was the target
if check_overflow(target_shape):
    print("WARNING: merged content overflows target frame. Escalate to G'.")
```

**If overflow happens after merge:** revert and tell the user the two pages can't be merged in-place — escalate to G'.

---

## Section C — Shape-level operations

Less common; mostly for completeness.

### Recipe C1: Resize a shape

User: "第3页的内容卡片再宽一点"

```python
slide = prs.slides[2]
shape = slide.shapes[1]

# Currently 4 inches wide; make it 5
shape.width = Inches(5)

# Position is the left edge; shape stays anchored at its left edge unless you also adjust .left
```

**Watch out:** Widening one shape can cause it to overlap with adjacent shapes. python-pptx doesn't auto-arrange. Inspect after to verify.

### Recipe C2: Recolor a shape's fill

User: "把第3页的强调色块换成深蓝"

```python
from pptx.enum.shapes import MSO_SHAPE_TYPE

slide = prs.slides[2]
target_shape = slide.shapes[2]  # the colored rectangle

if target_shape.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE:
    fill = target_shape.fill
    fill.solid()
    fill.fore_color.rgb = RGBColor(0x1A, 0x3D, 0x6F)
```

**For lines/borders:** use `shape.line.color.rgb`.

### Recipe C3: Delete a shape

User: "第3页的水印图删了"

```python
slide = prs.slides[2]
target_shape = slide.shapes[5]  # the watermark

sp = target_shape._element
sp.getparent().remove(sp)
```

---

## Section D — Bulk operations across slides

### Recipe D1: Apply a paragraph-level change to all slides

User: "所有页的正文段间距加大"

```python
from pptx.util import Pt

def adjust_paragraph_spacing(tf, space_after_pt):
    for p in tf.paragraphs:
        p.space_after = Pt(space_after_pt)

for slide in prs.slides:
    for shape in slide.shapes:
        if not shape.has_text_frame:
            continue
        # Heuristic: skip titles (usually placeholder idx 0)
        if shape.is_placeholder and shape.placeholder_format.idx == 0:
            continue
        adjust_paragraph_spacing(shape.text_frame, 6)
```

**Bulk operations are E3 by definition** — even if each individual change is simple, the scale makes overflow / unintended consequences likely. Always verify by re-running `pptx_inspect.py` after.

---

## Overflow handling — central concept

E3 is the path where overflow risk is highest. Adopt this discipline:

| Operation | Overflow risk | Required check |
|---|---|---|
| Add 1 paragraph to a list | Low-medium | Run `check_overflow()` after; print warning |
| Add 3+ paragraphs to a list | High | Run overflow check; if positive, revert + escalate to G' |
| Merge two slides | High | Always check after; if overflow, escalate |
| Delete paragraphs | None | Skip check |
| Reorder slides | None | Skip check |
| Resize shape larger | Low (may cause adjacent overlap, not overflow) | Inspect adjacent shapes |
| Recolor / restyle | None | Skip check |

**When overflow is detected:**
1. Do not save the broken file
2. Tell the user: "添加这些内容后超出了原版式的容量，建议重新生成这一页（G'路径）。要继续吗？"
3. If user agrees → switch to G' path
4. If user insists on E3 → save anyway with explicit warning, let them visually adjust

---

## Verification after E3

Always re-run inspect:

```bash
python pptx_inspect.py /mnt/user-data/outputs/<file>_edited.pptx
```

Compare with pre-edit inspect output:
- **For B-section operations:** slide count changed as expected?
- **For A-section operations:** paragraph count on target shape changed as expected?
- **For overflow-risk operations:** open the file visually and check (or ask user to)

---

## When E3 is not enough — escalate

| User actually wants | Path |
|---|---|
| Add content that exceeds the layout's capacity | **G'** |
| Restructure the page's visual layout (not just add/remove content) | **G'** |
| Merge two slides with incompatible visual layouts | **G'** |
| Cross-cutting visual changes (e.g. "重新设计整套配色") | **G** |
| Add new pages with new design themes | **G'** |
| Modify SmartArt or Chart structure | **G'** or refuse |
