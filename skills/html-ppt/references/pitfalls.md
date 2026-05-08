# Common Pitfalls — python-pptx

Read this BEFORE writing any python-pptx code. These issues cause file corruption, visual bugs, or broken output.

---

## Critical — File Corruption

### 1. ALWAYS use RGBColor for hex colors
```python
from pptx.dml.color import RGBColor
run.font.color.rgb = RGBColor(0xFF, 0x00, 0x00)   # ✅ CORRECT
run.font.color.rgb = "#FF0000"                     # ❌ TypeError
```

### 2. Transparency requires XML manipulation — no direct API
python-pptx has no `.transparency` property on shapes. Use the XML approach:
```python
from pptx.oxml.ns import qn
import lxml.etree as etree

def set_alpha(shape, transparency_pct):
    sp_pr = shape._element.spPr
    solid = sp_pr.find(qn('a:solidFill'))
    srgb = solid.find(qn('a:srgbClr'))
    for a in srgb.findall(qn('a:alpha')):
        srgb.remove(a)
    alpha_el = etree.SubElement(srgb, qn('a:alpha'))
    alpha_el.set('val', str(int((1 - transparency_pct/100) * 100000)))
```

---

## Critical — Silent Bugs

### 3. Inches() / Pt() are NOT interchangeable
Always use `Inches()` for position/size, `Pt()` for font sizes:
```python
txBox = slide.shapes.add_textbox(Inches(1), Inches(0.5), Inches(4), Inches(1))
run.font.size = Pt(24)     # ✅
run.font.size = Inches(24) # ❌ silently wrong — 24 inches of font height
```

### 4. add_textbox requires a run to set font properties
```python
tf = txBox.text_frame
p = tf.paragraphs[0]
# ❌ WRONG — paragraph has no run yet
p.font.size = Pt(20)  # AttributeError

# ✅ CORRECT — add a run first
run = p.add_run()
run.text = "Hello"
run.font.size = Pt(20)
```

### 5. word_wrap must be set on text_frame, not paragraph
```python
tf.word_wrap = True    # ✅ correct level
p.word_wrap = True     # ❌ AttributeError
```

### 6. vertical_anchor must use MSO_ANCHOR enum, not strings
```python
from pptx.enum.text import MSO_ANCHOR
tf.vertical_anchor = MSO_ANCHOR.MIDDLE   # ✅
tf.vertical_anchor = "middle"            # ❌ silently ignored
```

### 7. Slide background requires .background.fill.solid()
```python
bg = slide.background
fill = bg.fill
fill.solid()
fill.fore_color.rgb = RGBColor(0x1A, 0x2B, 0x4A)  # ✅
```

### 8. Shape auto-type integers — use correct codes
```python
# Shape type codes used in add_shape(type_int, ...):
# 1 = RECTANGLE, 9 = OVAL
slide.shapes.add_shape(1, Inches(x), Inches(y), Inches(w), Inches(h))
```

### 9. Blank slide layout index is 6, not 0
```python
blank_layout = prs.slide_layouts[6]   # ✅ completely blank
blank_layout = prs.slide_layouts[0]   # ❌ "Title Slide" with placeholders
```

---

## Critical — Contrast & Visibility (THE MOST COMMON VISUAL FAILURE)

### 10. NEVER use similar-family colors for cards on dark backgrounds
White card on dark bg = maximum clarity. Same-hue card on dark bg = invisible.

```python
# ❌ WRONG — card blends into dark bg
shape.fill.fore_color.rgb = RGBColor(0x1A, 0x4F, 0xAA)  # on 0052CC bg

# ✅ CORRECT — WHITE card on dark bg (maximum contrast)
shape.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
run.font.color.rgb = RGBColor(0x1A, 0x1A, 0x2E)  # dark text on white
```

### 11. Safe color pairings reference

| Element | Background | Text Color | Card Border |
|---------|-----------|------------|-------------|
| Main title | `primary` | `accent` (FFFFFF) | — |
| Subtitle / tagline | `primary` | `secondary` or `CCDDFF` | — |
| Card on dark slide | `FFFFFF` (white) | `text_dark` or `333333` | optional |
| Card on dark slide (alt) | dark card | `FFFFFF` | `CCE0FF` 2px required |
| KPI number | `primary` | `accent` | — |
| Bottom bar on dark slide | `secondary` | `primary` bold | — |
| Card on light slide | `FFFFFF` | `text_dark` | `secondary` 1px |

---

## Visual — Common Mistakes

### 12. Text overflows container — increase `h` or reduce `fs`
python-pptx does NOT auto-clip. Set container `h` large enough.
Chinese text is wider than English at the same font size.

### 13. Use thin RECTANGLE for horizontal rules, not LINE shape
LINE shapes render inconsistently across viewers. Use a 0.01–0.03 in tall RECTANGLE:
```python
rect(slide, x, y, width, 0.02, fill="3B7DD8")  # ✅ reliable thin rule
```

### 14. Each presentation needs a fresh Presentation() instance
```python
prs = Presentation()   # ✅ fresh instance per deck
```

### 15. Picture z-order — background images must go behind shapes
```python
pic = slide.shapes.add_picture(path, ...)
# Move to back:
slide.shapes._spTree.remove(pic._element)
slide.shapes._spTree.insert(2, pic._element)  # 2 = behind all other shapes
```

### 16. Multiline text — split on "\n" and add paragraphs
```python
for i, line in enumerate(text.split("\n")):
    p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
    run = p.add_run()
    run.text = line
```

---

## QA Process

### Step 1: Generate & Rasterize
```bash
python3 html2pptx.py slides.json output.pptx
python /mnt/skills/public/pptx/scripts/office/soffice.py --headless --convert-to pdf output.pptx
rm -f slide-*.jpg
pdftoppm -jpeg -r 150 output.pdf slide
ls -1 "$PWD"/slide-*.jpg
```

### Step 2: Per-Slide QA Agent Loop
See `SKILL.md` Phase 5 for the full QA Sub-Agent invocation pattern.

For each slide image, check:
- **Contrast** (CRITICAL): All text immediately readable against its background
- **Content visibility**: No clipped text, no missing content
- **Layout & density**: No large empty zones, no overflow
- **Visual design**: Decorative elements present, clear hierarchy
- **Color consistency**: Colors match theme palette
- **Page badge**: Visible on all non-cover/end slides

### Step 3: Fix and Re-verify
Apply targeted fixes to the specific template function. Re-rasterize and re-check.
One fix often creates another problem — always re-run QA after every fix.
Maximum 3 iterations per slide.
