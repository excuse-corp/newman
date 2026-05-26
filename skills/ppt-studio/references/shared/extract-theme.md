# Extract Theme from an Uploaded PPT

How to pull colors and fonts out of a user-uploaded `.pptx` so newly generated pages don't clash visually with the original deck.

**When this file is read:**
- **Path G'** — generating new pages to splice into an existing deck; new pages must match the original's visual theme
- **Path G case (c)** (optional) — user wants to redo the deck "with the original's colors"

**Output:** A `theme` dict matching the 8-key `plan.json` schema from `generate/workflow.md`:
```
primary · secondary · accent · text_dark · text_body · bg_light · fontHeading · fontBody
```

---

## The hard part: which colors are "the theme"?

A real PPT contains dozens of colors across shapes, text, fills, borders, and theme defaults. Picking the right 3-4 to be the deck's "theme colors" is genuinely ambiguous. Our approach:

1. **Collect** every color used in the deck, weighted by visual prominence (area for fills, count for text)
2. **Group** into dark / mid / light buckets
3. **Auto-assign** candidates to the 6 color slots in plan.json's theme
4. **Always show** the result to the user with the option to swap or correct

Auto-assignment is a starting point, not a verdict. **Always confirm with the user.**

---

## Reference implementation

```python
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.dml.color import RGBColor
from collections import Counter, defaultdict


# ---------- color collection ----------

def get_shape_fill_hex(shape):
    """Return solid fill color as #RRGGBB, or None."""
    try:
        fill = shape.fill
        if fill.type != 1:  # 1 = SOLID
            return None
        rgb = fill.fore_color.rgb
        return f"#{str(rgb).upper()}" if rgb else None
    except (AttributeError, ValueError, Exception):
        return None


def get_run_color_hex(run):
    """Return run's font color as #RRGGBB, or None (if theme-inherited)."""
    try:
        rgb = run.font.color.rgb
        return f"#{str(rgb).upper()}" if rgb else None
    except (AttributeError, ValueError):
        return None


def shape_area_pt(shape):
    """Approximate shape area in pt² (for weighting fills)."""
    try:
        w = (shape.width or 0) / 12700  # EMU → pt
        h = (shape.height or 0) / 12700
        return w * h
    except (AttributeError, TypeError):
        return 0


def collect_colors(pptx_path):
    """Walk all slides and collect color usage statistics.
    
    Returns:
      {
        'fills': Counter({hex: area_total, ...}),
        'text':  Counter({hex: char_count, ...}),
      }
    """
    prs = Presentation(pptx_path)
    fills = Counter()
    text_colors = Counter()
    
    def walk_shapes(shapes):
        for shape in shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                walk_shapes(shape.shapes)
                continue
            
            # Fill color (weighted by area)
            fill_hex = get_shape_fill_hex(shape)
            if fill_hex:
                fills[fill_hex] += shape_area_pt(shape)
            
            # Text colors (weighted by character count)
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    for run in para.runs:
                        c = get_run_color_hex(run)
                        if c:
                            text_colors[c] += len(run.text)
    
    for slide in prs.slides:
        walk_shapes(slide.shapes)
    
    return {"fills": fills, "text": text_colors}


# ---------- color bucketing ----------

def hex_to_rgb(hex_str):
    """'#RRGGBB' → (r, g, b) tuple."""
    h = hex_str.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def luminance(hex_str):
    """Perceived luminance, 0 (black) to 1 (white)."""
    r, g, b = hex_to_rgb(hex_str)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def bucket_by_luminance(hex_str):
    """Sort a color into dark / mid / light."""
    L = luminance(hex_str)
    if L < 0.35:
        return "dark"
    elif L < 0.75:
        return "mid"
    else:
        return "light"


def saturation(hex_str):
    """HSV saturation, 0 to 1."""
    r, g, b = (c / 255 for c in hex_to_rgb(hex_str))
    cmax = max(r, g, b)
    cmin = min(r, g, b)
    return 0 if cmax == 0 else (cmax - cmin) / cmax


# ---------- auto-assignment ----------

def auto_assign_theme(color_data):
    """Suggest a plan.json theme dict from collected color stats.
    
    Returns a dict with the 6 color keys, plus 'candidates' (alternatives the user might prefer).
    """
    fills = color_data["fills"]
    text = color_data["text"]
    
    # Bucket fills by luminance, sort each bucket by total area
    by_bucket = defaultdict(list)
    for hex_color, area in fills.most_common():
        by_bucket[bucket_by_luminance(hex_color)].append((hex_color, area))
    
    darks = by_bucket["dark"]
    mids = by_bucket["mid"]
    lights = by_bucket["light"]
    
    # Primary: largest-area dark fill (or mid if no darks)
    primary = (darks[0][0] if darks else
               mids[0][0] if mids else
               "#333333")
    
    # bg_light: largest-area light fill (or white default)
    bg_light = lights[0][0] if lights else "#FFFFFF"
    
    # Secondary: a mid-tone with reasonable saturation, not too close to primary
    candidates_for_secondary = [c for c, _ in mids if c != primary]
    candidates_for_secondary.sort(key=saturation, reverse=True)
    secondary = (candidates_for_secondary[0] if candidates_for_secondary
                 else (darks[1][0] if len(darks) > 1 else "#888888"))
    
    # Accent: white by default (matches most palettes); user may override
    accent = "#FFFFFF" if luminance(primary) < 0.5 else "#000000"
    
    # Text colors: from text usage
    text_sorted = text.most_common()
    dark_texts = [(c, n) for c, n in text_sorted if bucket_by_luminance(c) == "dark"]
    mid_texts = [(c, n) for c, n in text_sorted if bucket_by_luminance(c) == "mid"]
    
    text_dark = dark_texts[0][0] if dark_texts else "#1A1A1A"
    text_body = (mid_texts[0][0] if mid_texts
                 else (dark_texts[1][0] if len(dark_texts) > 1 else "#555555"))
    
    return {
        "primary":    primary.lstrip("#"),
        "secondary":  secondary.lstrip("#"),
        "accent":     accent.lstrip("#"),
        "text_dark":  text_dark.lstrip("#"),
        "text_body":  text_body.lstrip("#"),
        "bg_light":   bg_light.lstrip("#"),
        "candidates": {
            "darks":  [c.lstrip("#") for c, _ in darks[:5]],
            "mids":   [c.lstrip("#") for c, _ in mids[:5]],
            "lights": [c.lstrip("#") for c, _ in lights[:5]],
            "text":   [c.lstrip("#") for c, _ in text_sorted[:5]],
        }
    }


# ---------- font extraction ----------

def collect_fonts(pptx_path):
    """Collect font usage by size, to distinguish heading vs body fonts."""
    prs = Presentation(pptx_path)
    font_usage = []  # list of (font_name, size_pt, char_count)
    
    def walk_shapes(shapes):
        for shape in shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                walk_shapes(shape.shapes)
                continue
            if not shape.has_text_frame:
                continue
            for para in shape.text_frame.paragraphs:
                for run in para.runs:
                    name = run.font.name
                    size = run.font.size.pt if run.font.size else None
                    text_len = len(run.text)
                    if name and text_len > 0:
                        font_usage.append((name, size, text_len))
    
    for slide in prs.slides:
        walk_shapes(slide.shapes)
    
    return font_usage


def auto_assign_fonts(font_usage):
    """Pick heading and body fonts based on size + frequency."""
    if not font_usage:
        return {"fontHeading": "Microsoft YaHei", "fontBody": "Microsoft YaHei"}
    
    # Group by font name, track sizes seen and total chars
    by_font = defaultdict(lambda: {"sizes": [], "chars": 0})
    for name, size, chars in font_usage:
        by_font[name]["chars"] += chars
        if size is not None:
            by_font[name]["sizes"].append(size)
    
    # Heading font: the one used in the largest sizes (top quartile)
    # Body font: the one with the most characters (commonly the body)
    all_sizes = [s for usage in by_font.values() for s in usage["sizes"]]
    if not all_sizes:
        most_used = max(by_font.items(), key=lambda x: x[1]["chars"])[0]
        return {"fontHeading": most_used, "fontBody": most_used}
    
    large_threshold = sorted(all_sizes)[int(len(all_sizes) * 0.75)] if all_sizes else 24
    
    heading_candidates = [(name, max(usage["sizes"]) if usage["sizes"] else 0, usage["chars"])
                          for name, usage in by_font.items()
                          if any(s >= large_threshold for s in usage["sizes"])]
    body_candidates = sorted(by_font.items(), key=lambda x: x[1]["chars"], reverse=True)
    
    heading_font = (max(heading_candidates, key=lambda x: x[1])[0]
                    if heading_candidates
                    else body_candidates[0][0])
    body_font = body_candidates[0][0]
    
    return {"fontHeading": heading_font, "fontBody": body_font}


# ---------- top-level entry ----------

def extract_theme(pptx_path):
    """Top-level: extract a complete theme dict + candidates for user confirmation."""
    color_data = collect_colors(pptx_path)
    theme = auto_assign_theme(color_data)
    
    font_usage = collect_fonts(pptx_path)
    fonts = auto_assign_fonts(font_usage)
    
    theme.update(fonts)
    return theme
```

---

## How to use the output

### Step 1: Run extraction and show user

```python
theme = extract_theme("/mnt/user-data/uploads/deck.pptx")
print(theme)
```

Output looks like:
```python
{
    "primary":    "3D2A1E",
    "secondary":  "B89178",
    "accent":     "FFFFFF",
    "text_dark":  "2A1F18",
    "text_body":  "5F4A3E",
    "bg_light":   "F4ECDD",
    "fontHeading": "Microsoft YaHei",
    "fontBody":   "Source Han Sans CN",
    "candidates": {
        "darks":  ["3D2A1E", "2A1F18", ...],
        "mids":   ["B89178", "8C6F5A", ...],
        ...
    }
}
```

### Step 2: Present to user

Show the user a confirmation message before locking in:

> 我从你的 PPT 提取了以下主题：
> 
> | 角色 | 颜色 | 说明 |
> |---|---|---|
> | primary（主色）| `#3D2A1E` 深棕 | 用于标题、强调色块 |
> | secondary（辅色）| `#B89178` 奶咖 | 用于装饰、副元素 |
> | bg_light（背景）| `#F4ECDD` 米白 | 主要背景色 |
> | text_dark（主文字）| `#2A1F18` | 标题文字 |
> | text_body（正文）| `#5F4A3E` | 正文文字 |
> | accent（点缀）| `#FFFFFF` 白 | 深色块上的对比文字/元素 |
> 
> 字体：标题 Microsoft YaHei，正文 Source Han Sans CN
> 
> 这套主题是否符合你原 PPT 的风格？如需调整：
> - 主色想换成 `B89178`（奶咖）？
> - 或者从其他候选色里挑：`...`
> - 字体保持还是换？

### Step 3: After user confirmation

Use the confirmed theme dict as the `theme` field in `plan.json` for the newly generated pages.

---

## Edge cases

### PPT uses theme colors (not explicit RGB)

PowerPoint themes assign colors by role (`accent1`, `bg1`, etc.) rather than RGB. Shapes using theme colors return `None` from `fill.fore_color.rgb`.

To handle this:
1. Check if `theme` extraction returned very few colors (e.g. only 1-2)
2. If so, fall back to reading the slide master's theme XML directly:

```python
def get_master_theme_colors(pptx_path):
    """Read accent1/2/3 and bg1/2 from the deck's theme XML."""
    import zipfile
    import xml.etree.ElementTree as ET
    
    NS = {
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main"
    }
    
    with zipfile.ZipFile(pptx_path) as z:
        # The first theme is typically ppt/theme/theme1.xml
        theme_xml = z.read("ppt/theme/theme1.xml")
    
    root = ET.fromstring(theme_xml)
    colors = {}
    for color_el in root.iter(f"{{{NS['a']}}}clrScheme"):
        for child in color_el:
            role = child.tag.split("}")[1]  # accent1, bg1, etc.
            srgb = child.find(f".//{{{NS['a']}}}srgbClr")
            sys = child.find(f".//{{{NS['a']}}}sysClr")
            if srgb is not None:
                colors[role] = f"#{srgb.get('val').upper()}"
            elif sys is not None and sys.get("lastClr"):
                colors[role] = f"#{sys.get('lastClr').upper()}"
    
    return colors
```

Map theme roles to plan.json roles:
- `accent1` or `accent2` → `primary` (often the brand color)
- `accent3` or `accent4` → `secondary`
- `lt1` or `bg1` → `bg_light`
- `dk1` or `tx1` → `text_dark`

### CJK + Latin mixed fonts

A PPT may use one font for Chinese (`Microsoft YaHei`) and another for Latin/digits (`Arial`). The auto-assign picks the most-used; CJK-heavy slides naturally favor the CJK font, which is usually what we want.

If the user objects, suggest letting `plan.json` use the CJK font for both `fontHeading` and `fontBody` — render.py sets both the Latin and East-Asian typefaces so a single CJK font covers mixed text.

### Few colors / very minimalist deck

If the deck only uses 2-3 colors total, auto-assignment may leave `accent` or `secondary` as defaults. That's fine — confirm with the user and let them say "leave secondary blank, use accent only".

### PPT was generated from a template with extreme color count

If `collect_colors()` returns dozens of similar shades (e.g. 12 variants of blue), the user probably wants the "anchor" color. Sort by total area and take the top one in each bucket; show the user the top 5 in each bucket as alternatives.

---

## What this file does NOT cover

- **Layout / spacing / typography scale** — the generated pages use Path G's own design system; we only carry over color and font *family*, not font sizes or layouts. This is intentional: forcing inserted pages into the original deck's exact spacing would mean reimplementing the original's templates, which is out of scope.
- **Custom decorative elements** (corner ribbons, custom borders) — these can't be cleanly extracted; if the original deck has signature decoration, the user should mention it so Path G can mimic the style choice.
- **Animation / transitions** — irrelevant to theme.

---

## Quick reference

| Goal | Function | Output |
|---|---|---|
| Get the whole theme dict | `extract_theme(path)` | `{primary, secondary, ..., fontHeading, fontBody, candidates}` |
| Just colors | `collect_colors(path)` | `{fills: Counter, text: Counter}` |
| Just fonts | `collect_fonts(path)` | `[(name, size, chars), ...]` |
| Read theme XML directly (fallback) | `get_master_theme_colors(path)` | `{accent1: "#...", bg1: "#...", ...}` |
