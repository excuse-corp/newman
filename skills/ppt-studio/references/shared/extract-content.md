# Extract Content from an Uploaded PPT

How to pull text, structure, and outline information out of a user-uploaded `.pptx` so it can feed a new generation (Path G case c) or new-page generation (Path G').

**When this file is read:**
- **Path G case (c)** — user uploaded a PPT and wants to "regenerate / redo with this content"
- **Path G'** — user wants to expand or replace pages, and you need the source content to inform new pages

**Prerequisites:** You have run `pptx_inspect.py` and have a structured view of the deck.

---

## Two extraction depths

Pick the depth that matches the task.

### Depth 1: Outline only
For Path G case (c) when the user only wants the structure and topics, with content freshly rewritten.

Per slide:
- Slide number
- Page title (the top-most text, usually placeholder idx 0)
- 1-line content summary (truncate body text to ~60 chars)

Output as a markdown numbered list. Show this to the user as the basis for Phase 1 outline confirmation.

### Depth 2: Full text dump
For Path G' when generating a replacement / inserted page that should preserve specific content from the original.

Per slide:
- Slide number
- All text content, grouped by shape
- Tables as markdown tables
- Image presence noted (but image bytes not extracted here — see "Images" section below)

---

## Reference implementation

```python
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE


def extract_text_from_shape(shape, depth_full=False):
    """Return text content from a shape. Recurses into groups."""
    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        parts = []
        for child in shape.shapes:
            t = extract_text_from_shape(child, depth_full)
            if t:
                parts.append(t)
        return "\n".join(parts)
    
    if shape.shape_type == MSO_SHAPE_TYPE.TABLE:
        return extract_table(shape.table)
    
    if shape.has_text_frame:
        return shape.text_frame.text.strip()
    
    return ""


def extract_table(table):
    """Convert a PPTX table to a markdown table string."""
    rows = []
    for row in table.rows:
        cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
        rows.append("| " + " | ".join(cells) + " |")
    # Insert markdown table separator after header row
    if rows:
        sep_cols = len(table.rows[0].cells)
        rows.insert(1, "| " + " | ".join(["---"] * sep_cols) + " |")
    return "\n".join(rows)


def get_title_text(slide):
    """Try to find the slide's title — usually placeholder idx 0."""
    for shape in slide.shapes:
        try:
            if shape.is_placeholder and shape.placeholder_format.idx == 0:
                return shape.text_frame.text.strip() if shape.has_text_frame else ""
        except (AttributeError, ValueError):
            continue
    # Fallback: top-most text-bearing shape
    text_shapes = [s for s in slide.shapes if s.has_text_frame and s.text_frame.text.strip()]
    if text_shapes:
        text_shapes.sort(key=lambda s: s.top or 0)
        return text_shapes[0].text_frame.text.strip().split("\n")[0]
    return ""


def get_body_text(slide):
    """Concatenate all non-title text from a slide."""
    title = get_title_text(slide)
    parts = []
    for shape in slide.shapes:
        text = extract_text_from_shape(shape, depth_full=True)
        if text and text != title:
            parts.append(text)
    return "\n".join(parts)


def get_body_summary(slide):
    """Like get_body_text but tables become '(table: NxM)' markers, suitable for outline summaries."""
    title = get_title_text(slide)
    parts = []
    for shape in slide.shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.TABLE:
            tbl = shape.table
            parts.append(f"(table: {len(tbl.rows)}×{len(tbl.columns)})")
            continue
        text = extract_text_from_shape(shape, depth_full=True)
        if text and text != title:
            parts.append(text)
    return " · ".join(parts)


def has_image(slide):
    """Check if any shape on the slide is a picture (recursive into groups)."""
    def walk(shapes):
        for s in shapes:
            if s.shape_type == MSO_SHAPE_TYPE.PICTURE:
                return True
            if s.shape_type == MSO_SHAPE_TYPE.GROUP:
                if walk(s.shapes):
                    return True
        return False
    return walk(slide.shapes)


def extract_outline(pptx_path):
    """Depth 1: produce an outline list."""
    prs = Presentation(pptx_path)
    outline = []
    for idx, slide in enumerate(prs.slides, start=1):
        title = get_title_text(slide) or "(no title)"
        body = get_body_summary(slide)
        summary = body[:60] + ("…" if len(body) > 60 else "")
        outline.append({
            "page": idx,
            "title": title,
            "summary": summary,
            "has_image": has_image(slide),
        })
    return outline


def extract_full_text(pptx_path):
    """Depth 2: produce full text dump per slide."""
    prs = Presentation(pptx_path)
    slides_data = []
    for idx, slide in enumerate(prs.slides, start=1):
        slide_data = {
            "page": idx,
            "title": get_title_text(slide),
            "shapes": [],
        }
        for shape in slide.shapes:
            text = extract_text_from_shape(shape, depth_full=True)
            if not text:
                continue
            slide_data["shapes"].append({
                "type": str(shape.shape_type).split(".")[-1] if shape.shape_type else "UNKNOWN",
                "text": text,
            })
        if has_image(slide):
            slide_data["has_image"] = True
        slides_data.append(slide_data)
    return slides_data
```

---

## How to use the output

### For Path G case (c) — outline mode

After running `extract_outline()`, present to the user:

```markdown
我从你的 PPT 提取出以下结构：

1. 「2024年度信管部工作总结」— 部门基本情况 / 主要工作 / 数据指标…
2. 「核心业务进展」— 三大领域 / 重点项目 / 团队协作…
3. 「数据成果」— 关键 KPIs / 用户增长 / 满意度…
...

是否用这个结构作为新 PPT 的大纲？需要调整 / 增删页面吗？
```

Then proceed to Phase 1 of `generate/workflow.md` with the confirmed outline.

### For Path G' — full text mode

After running `extract_full_text()`, you have the source material to inform the new generated page. Pass it as context when building `plan.json` for the new slides.

Example: user says "expand page 3 into 3 pages":
1. Extract page 3's full text via `extract_full_text()`
2. Show the extracted content to the user
3. Discuss how to split it across 3 new pages
4. Generate plan.json for the 3 new pages using this content
5. Hand off to `insert/workflow.md` for splicing

---

## Special cases

### Long PPTs (50+ slides)

Outline mode handles this fine (60 chars/slide × 50 = 3KB).

Full text mode can blow up — a content-heavy 50-slide deck may have tens of KB of text. For Path G' you usually only need 1-3 specific slides' content, so **extract only the slides you need**:

```python
# Extract only specific slides
def extract_full_text_for_slides(pptx_path, slide_nums):
    """slide_nums is a list of 1-based indices."""
    prs = Presentation(pptx_path)
    out = []
    for num in slide_nums:
        if 1 <= num <= len(prs.slides):
            slide = prs.slides[num - 1]
            # ... same as extract_full_text inner loop
    return out
```

### Slides with speakers notes

Notes are not extracted by default. To include them:

```python
notes_frame = slide.notes_slide.notes_text_frame
notes_text = notes_frame.text.strip() if notes_frame else ""
```

Ask the user whether to include speaker notes in the extraction (they often contain content the user wants in the new version).

### Charts and SmartArt

These contain text that isn't reachable via the standard text-frame API:

- **Charts**: data labels, axis titles, legend entries are inside the chart XML. Limited python-pptx support. For full-content extraction, surface "(chart: <type> with <N> data series)" as a note to the user, and ask them to describe the chart data verbatim if it's critical.
- **SmartArt**: text is in `<dgm:t>` elements inside diagram XML. Not directly extractable. Note "(SmartArt — content not auto-extractable)" and ask the user.

### Images

Image bytes can be extracted but usually shouldn't be at this stage. Just note `has_image: True` per slide. If Path G' needs to reuse an image, extract it explicitly later via:

```python
for shape in slide.shapes:
    if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
        image = shape.image
        with open(f"/tmp/extracted_image_{slide_num}.{image.ext}", "wb") as f:
            f.write(image.blob)
```

---

## What this file does NOT cover

- **Color / font extraction** → see `shared/extract-theme.md`
- **Shape positions / dimensions** → not part of content extraction; use `pptx_inspect.py` if needed
- **Slide layouts / masters** → not needed; the new deck will use fresh layouts from Path G

---

## Quick reference

| Goal | Function | Output |
|---|---|---|
| Show user what's in the deck | `extract_outline()` | list of `{page, title, summary, has_image}` |
| Feed content into new page generation | `extract_full_text()` | list of `{page, title, shapes:[{type, text}]}` |
| Specific slides only | `extract_full_text_for_slides([3,5,7])` | same shape, filtered |
| Get speaker notes | `slide.notes_slide.notes_text_frame.text` | string |
| Get image bytes | `shape.image.blob` | bytes |
