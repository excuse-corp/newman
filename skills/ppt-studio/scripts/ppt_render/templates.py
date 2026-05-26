"""Slide template layouts.

Each template is a function: layout(data, theme) -> list[Element].
All positioning logic lives here. The HTML and PPTX renderers (core.py)
consume the element list generically.

Canvas: 960 x 540 px. Margin: 40px. Title bar: 0-90px region.
"""

from .core import rect, oval, line, text, CANVAS_W, CANVAS_H

MARGIN = 40
TITLE_Y = 30
TITLE_H = 44


# ── Shared helpers ──────────────────────────────────────────

def _title_bar(theme, title, dark_bg=False):
    """Accent bar + title at top-left. Returns element list."""
    title_color = theme["accent"] if dark_bg else theme["text_dark"]
    return [
        line(MARGIN, TITLE_Y, 5, TITLE_H, theme["secondary"]),
        text(MARGIN + 16, TITLE_Y - 4, CANVAS_W - MARGIN * 2 - 16, TITLE_H + 8,
             title or "", size=26, color=title_color, font=theme["fontHeading"],
             bold=True, valign="middle"),
    ]


def _page_badge(theme, page):
    """Small page number bottom-right."""
    if page is None:
        return []
    return [text(CANVAS_W - 70, CANVAS_H - 28, 40, 18,
                 f"{page:02d}", size=11, color=theme["secondary"],
                 font=theme["fontBody"], align="right", valign="middle")]


def _grid_layout(n):
    """Return (cols, rows, card_h, last_row_center) for n cards."""
    table = {
        1: (1, 1, 300, False),
        2: (2, 1, 300, False),
        3: (3, 1, 300, False),
        4: (2, 2, 200, False),
        5: (3, 2, 200, True),
        6: (3, 2, 200, False),
        7: (4, 2, 180, True),
        8: (4, 2, 180, False),
        9: (3, 3, 130, False),
    }
    if n < 1 or n > 9:
        raise ValueError(f"card grid supports 1-9 cards, got {n}")
    return table[n]


# ══════════════════════════════════════════════════════════
# cover / cover_pro
# ══════════════════════════════════════════════════════════

def cover_pro(data, theme):
    els = []
    # dark full background
    els.append(rect(0, 0, CANVAS_W, CANVAS_H, theme["primary"]))
    # decorative circle top-right
    els.append(oval(CANVAS_W - 140, -80, 240, 240, theme["secondary"], opacity=0.08))
    # department badge
    els.append(line(MARGIN, 30, 4, 32, theme["secondary"]))
    els.append(text(MARGIN + 12, 30, 600, 32, data.get("department", ""),
                    size=12, color=theme["secondary"], font=theme["fontBody"],
                    valign="middle"))
    # main title
    els.append(text(MARGIN, 150, 720, 160, data.get("title", ""),
                    size=40, color=theme["accent"], font=theme["fontHeading"],
                    bold=True, line_height=1.25))
    # subtitle with rule
    els.append(line(MARGIN, 320, 90, 3, theme["secondary"]))
    els.append(text(MARGIN + 105, 308, 500, 30, data.get("subtitle", ""),
                    size=18, color=theme["secondary"], font=theme["fontBody"],
                    valign="middle"))
    # bottom stats bar
    bar_y = CANVAS_H - 70
    els.append(rect(0, bar_y, CANVAS_W, 1, theme["secondary"], opacity=0.4))
    stats = data.get("bottom_stats", [])
    for i, st in enumerate(stats):
        sx = MARGIN + i * 220
        els.append(oval(sx, bar_y + 22, 14, 14, theme["secondary"]))
        els.append(text(sx + 24, bar_y + 16, 190, 26, st.get("text", ""),
                        size=12, color=theme["secondary"], font=theme["fontBody"],
                        valign="middle"))
    if data.get("date"):
        els.append(text(CANVAS_W - 200, bar_y + 16, 160, 26, data["date"],
                        size=12, color=theme["secondary"], font=theme["fontBody"],
                        align="right", valign="middle"))
    return els


cover = cover_pro  # alias


# ══════════════════════════════════════════════════════════
# section_break / section_break_minimal
# ══════════════════════════════════════════════════════════

def section_break(data, theme):
    els = [rect(0, 0, CANVAS_W, CANVAS_H, theme["primary"])]
    # giant faint background number
    num = data.get("section_number", "")
    if num:
        els.append(text(CANVAS_W - 380, 20, 400, 420, num, size=300,
                        color=theme["secondary"], font=theme["fontHeading"],
                        bold=True, opacity=0.12))
    # accent bar + title on top
    els.append(line(MARGIN, 230, 80, 5, theme["secondary"]))
    els.append(text(MARGIN, 250, 600, 70, data.get("title", ""),
                    size=40, color=theme["accent"], font=theme["fontHeading"],
                    bold=True))
    if data.get("subtitle"):
        els.append(text(MARGIN, 330, 600, 40, data["subtitle"],
                        size=18, color=theme["secondary"], font=theme["fontBody"]))
    return els


def section_break_minimal(data, theme):
    els = [rect(0, 0, CANVAS_W, CANVAS_H, theme["primary"])]
    num = data.get("section_number", "")
    if num:
        els.append(text(MARGIN, 200, 200, 30, num, size=15,
                        color=theme["secondary"], font=theme["fontBody"], bold=True))
    els.append(line(MARGIN, 240, 60, 4, theme["secondary"]))
    els.append(text(MARGIN, 256, 700, 70, data.get("title", ""),
                    size=38, color=theme["accent"], font=theme["fontHeading"],
                    bold=True))
    if data.get("subtitle"):
        els.append(text(MARGIN, 336, 700, 36, data["subtitle"],
                        size=17, color=theme["secondary"], font=theme["fontBody"]))
    return els


# ══════════════════════════════════════════════════════════
# card_grid (parametric 1-9)
# ══════════════════════════════════════════════════════════

def card_grid(data, theme):
    cards = data.get("cards", [])
    cols, rows, card_h, last_row_center = _grid_layout(len(cards))
    els = [rect(0, 0, CANVAS_W, CANVAS_H, theme["bg_light"])]
    els += _title_bar(theme, data.get("title", ""))

    gap = 18
    area_top = 100
    grid_w = CANVAS_W - MARGIN * 2
    card_w = (grid_w - (cols - 1) * gap) / cols
    grid_h = card_h * rows + (rows - 1) * gap
    area_h = CANVAS_H - area_top - 50
    grid_top = area_top + (area_h - grid_h) / 2

    n = len(cards)
    for i, c in enumerate(cards):
        row = i // cols
        col = i % cols
        if last_row_center and row == rows - 1:
            last_count = n - (rows - 1) * cols
            last_w = last_count * card_w + (last_count - 1) * gap
            start_x = MARGIN + (grid_w - last_w) / 2
            cx = start_x + col * (card_w + gap)
        else:
            cx = MARGIN + col * (card_w + gap)
        cy = grid_top + row * (card_h + gap)
        # card background + top accent
        els.append(rect(cx, cy, card_w, card_h, "FFFFFF"))
        els.append(line(cx, cy, card_w, 3, theme["secondary"]))
        # content: small dot, heading, body — top-aligned with padding
        pad = 20
        els.append(oval(cx + pad, cy + pad, 14, 14, theme["secondary"]))
        els.append(text(cx + pad, cy + pad + 26, card_w - pad * 2, 30,
                        c.get("heading", ""), size=15, color=theme["text_dark"],
                        font=theme["fontHeading"], bold=True))
        els.append(text(cx + pad, cy + pad + 60, card_w - pad * 2,
                        card_h - pad - 86, c.get("text", ""),
                        size=11, color=theme["text_body"], font=theme["fontBody"],
                        line_height=1.6))
    els += _page_badge(theme, data.get("page"))
    return els


# ══════════════════════════════════════════════════════════
# icon_list (parametric 1-8)
# ══════════════════════════════════════════════════════════

def icon_list(data, theme):
    items = data.get("items", [])
    n = len(items)
    if n < 1 or n > 8:
        raise ValueError(f"icon_list supports 1-8 items, got {n}")
    els = [rect(0, 0, CANVAS_W, CANVAS_H, theme["bg_light"])]
    els += _title_bar(theme, data.get("title", ""))

    area_top = 100
    area_h = CANVAS_H - area_top - 40
    row_h = area_h / n
    for i, it in enumerate(items):
        row_y = area_top + i * row_h
        center_y = row_y + row_h / 2
        # numbered circle
        circ = 38
        els.append(oval(MARGIN, center_y - circ / 2, circ, circ, theme["primary"]))
        els.append(text(MARGIN, center_y - circ / 2, circ, circ, str(i + 1),
                        size=16, color=theme["accent"], font=theme["fontHeading"],
                        bold=True, align="center", valign="middle"))
        # label + description
        tx = MARGIN + circ + 18
        tw = CANVAS_W - tx - MARGIN
        els.append(text(tx, center_y - 22, tw, 24, it.get("label", ""),
                        size=14, color=theme["text_dark"], font=theme["fontHeading"],
                        bold=True, valign="middle"))
        els.append(text(tx, center_y + 4, tw, 20, it.get("description", ""),
                        size=11, color=theme["text_body"], font=theme["fontBody"],
                        valign="top"))
    els += _page_badge(theme, data.get("page"))
    return els


# ══════════════════════════════════════════════════════════
# kpi_dashboard (parametric 1-6 KPIs + 1-4 detail cards)
# ══════════════════════════════════════════════════════════

def kpi_dashboard(data, theme):
    kpis = data.get("kpis", [])
    details = data.get("detail_cards", [])
    if len(kpis) > 6:
        raise ValueError(f"kpi_dashboard: max 6 KPIs, got {len(kpis)}")
    if len(details) > 4:
        raise ValueError(f"kpi_dashboard: max 4 detail cards, got {len(details)}")
    els = [rect(0, 0, CANVAS_W, CANVAS_H, theme["bg_light"])]
    els += _title_bar(theme, data.get("title", ""))

    # KPI row
    gap = 14
    kn = len(kpis)
    kpi_w = (CANVAS_W - MARGIN * 2 - (kn - 1) * gap) / kn if kn else 0
    kpi_y, kpi_h = 100, 110
    for i, k in enumerate(kpis):
        kx = MARGIN + i * (kpi_w + gap)
        els.append(rect(kx, kpi_y, kpi_w, kpi_h, theme["primary"], radius=6))
        els.append(text(kx, kpi_y + 20, kpi_w, 56, k.get("value", ""),
                        size=44, color=theme["accent"], font=theme["fontHeading"],
                        bold=True, align="center", valign="middle"))
        els.append(text(kx, kpi_y + 76, kpi_w, 24, k.get("label", ""),
                        size=11, color=theme["secondary"], font=theme["fontBody"],
                        align="center", valign="middle"))

    # detail cards
    dn = len(details)
    if dn:
        dgap = 16
        det_w = (CANVAS_W - MARGIN * 2 - (dn - 1) * dgap) / dn
        det_y = kpi_y + kpi_h + 20
        det_h = CANVAS_H - det_y - 50
        for i, det in enumerate(details):
            dx = MARGIN + i * (det_w + dgap)
            els.append(rect(dx, det_y, det_w, det_h, "FFFFFF"))
            els.append(line(dx, det_y, det_w, 3, theme["secondary"]))
            pad = 18
            els.append(text(dx + pad, det_y + pad, det_w - pad * 2, 28,
                            det.get("heading", ""), size=14,
                            color=theme["text_dark"], font=theme["fontHeading"],
                            bold=True))
            els.append(text(dx + pad, det_y + pad + 34, det_w - pad * 2,
                            det_h - pad - 52, det.get("text", ""),
                            size=11, color=theme["text_body"],
                            font=theme["fontBody"], line_height=1.6))
    els += _page_badge(theme, data.get("page"))
    return els


# ══════════════════════════════════════════════════════════
# big_statement / big_statement_minimal
# ══════════════════════════════════════════════════════════

def big_statement(data, theme):
    els = [rect(0, 0, CANVAS_W, CANVAS_H, theme["primary"])]
    els.append(oval(CANVAS_W - 200, -100, 320, 320, theme["secondary"], opacity=0.1))
    els.append(text(MARGIN + 10, 60, 120, 120, "\u201C", size=120,
                    color=theme["secondary"], font=theme["fontHeading"], bold=True))
    els.append(text(80, 180, CANVAS_W - 160, 180, data.get("statement", ""),
                    size=32, color=theme["accent"], font=theme["fontHeading"],
                    bold=True, align="center", valign="middle", line_height=1.4))
    if data.get("attribution"):
        els.append(text(80, 400, CANVAS_W - 160, 36,
                        "— " + data["attribution"], size=14,
                        color=theme["secondary"], font=theme["fontBody"],
                        align="center"))
    return els


def big_statement_minimal(data, theme):
    els = [rect(0, 0, CANVAS_W, CANVAS_H, theme["primary"])]
    els.append(line(CANVAS_W / 2 - 30, 180, 60, 3, theme["secondary"]))
    els.append(text(80, 210, CANVAS_W - 160, 160, data.get("statement", ""),
                    size=30, color=theme["accent"], font=theme["fontHeading"],
                    bold=True, align="center", valign="middle", line_height=1.45))
    if data.get("attribution"):
        els.append(text(80, 390, CANVAS_W - 160, 36,
                        "— " + data["attribution"], size=14,
                        color=theme["secondary"], font=theme["fontBody"],
                        align="center"))
    return els


# ══════════════════════════════════════════════════════════
# structured_content
# ══════════════════════════════════════════════════════════

def structured_content(data, theme):
    els = [rect(0, 0, CANVAS_W, CANVAS_H, theme["bg_light"])]
    els += _title_bar(theme, data.get("title", ""))
    # bordered card
    card_x, card_y = MARGIN, 100
    card_w = CANVAS_W - MARGIN * 2
    bottom = data.get("bottom_bar")
    card_h = (CANVAS_H - card_y - (90 if bottom else 50))
    els.append(rect(card_x, card_y, card_w, card_h, "FFFFFF"))
    els.append(line(card_x, card_y, card_w, 3, theme["secondary"]))
    # number badge + heading
    if data.get("number_badge"):
        els.append(rect(card_x + 24, card_y + 22, 40, 40, theme["primary"], radius=4))
        els.append(text(card_x + 24, card_y + 22, 40, 40, data["number_badge"],
                        size=18, color=theme["accent"], font=theme["fontHeading"],
                        bold=True, align="center", valign="middle"))
    els.append(text(card_x + 78, card_y + 24, card_w - 110, 36,
                    data.get("heading", ""), size=18, color=theme["text_dark"],
                    font=theme["fontHeading"], bold=True, valign="middle"))
    # sections
    secs = data.get("sections", [])
    sec_top = card_y + 80
    sec_area = card_h - 100
    sec_h = sec_area / max(len(secs), 1)
    for i, sec in enumerate(secs):
        sy = sec_top + i * sec_h
        els.append(oval(card_x + 28, sy + 4, 12, 12, theme["secondary"]))
        els.append(text(card_x + 52, sy, card_w - 90, 24,
                        sec.get("heading", ""), size=13, color=theme["text_dark"],
                        font=theme["fontHeading"], bold=True))
        els.append(text(card_x + 52, sy + 26, card_w - 90, sec_h - 34,
                        sec.get("text", ""), size=11, color=theme["text_body"],
                        font=theme["fontBody"], line_height=1.55))
    # bottom bar
    if bottom:
        bb_y = CANVAS_H - 76
        els.append(rect(MARGIN, bb_y, card_w, 44, theme["primary"], radius=4))
        els.append(text(MARGIN + 20, bb_y, 200, 44, bottom.get("heading", ""),
                        size=13, color=theme["accent"], font=theme["fontHeading"],
                        bold=True, valign="middle"))
        els.append(text(MARGIN + 200, bb_y, card_w - 220, 44, bottom.get("text", ""),
                        size=11, color=theme["secondary"], font=theme["fontBody"],
                        valign="middle"))
    els += _page_badge(theme, data.get("page"))
    return els


# ══════════════════════════════════════════════════════════
# grid_content
# ══════════════════════════════════════════════════════════

def grid_content(data, theme):
    els = [rect(0, 0, CANVAS_W, CANVAS_H, theme["primary"])]
    # title (on dark)
    els += _title_bar(theme, data.get("title", ""), dark_bg=True)
    if data.get("subtitle"):
        els.append(text(MARGIN + 16, 70, CANVAS_W - MARGIN * 2, 24,
                        data["subtitle"], size=12, color=theme["secondary"],
                        font=theme["fontBody"]))
    area_top = 105
    bottom = data.get("bottom_bar")
    area_h = CANVAS_H - area_top - (70 if bottom else 40)
    # left card 38%, right cards 58%
    lc = data.get("left_card", {})
    left_w = (CANVAS_W - MARGIN * 2) * 0.38
    right_x = MARGIN + left_w + 16
    right_w = CANVAS_W - MARGIN - right_x
    els.append(rect(MARGIN, area_top, left_w, area_h, theme["bg_light"]))
    els.append(text(MARGIN + 18, area_top + 18, left_w - 36, 40,
                    lc.get("number", ""), size=30, color=theme["secondary"],
                    font=theme["fontHeading"], bold=True))
    els.append(text(MARGIN + 18, area_top + 62, left_w - 36, 30,
                    lc.get("heading", ""), size=15, color=theme["text_dark"],
                    font=theme["fontHeading"], bold=True))
    els.append(text(MARGIN + 18, area_top + 96, left_w - 36, area_h - 110,
                    lc.get("content", ""), size=11, color=theme["text_body"],
                    font=theme["fontBody"], line_height=1.6))
    # right cards
    rcs = data.get("right_cards", [])
    rn = max(len(rcs), 1)
    rgap = 12
    rc_h = (area_h - (rn - 1) * rgap) / rn
    for i, rc in enumerate(rcs):
        ry = area_top + i * (rc_h + rgap)
        els.append(rect(right_x, ry, right_w, rc_h, theme["bg_light"]))
        els.append(text(right_x + 16, ry + 12, right_w - 32, 26,
                        rc.get("heading", ""), size=13, color=theme["text_dark"],
                        font=theme["fontHeading"], bold=True))
        items = rc.get("items", [])
        iy = ry + 42
        for it in items:
            els.append(text(right_x + 16, iy, 110, 20, it.get("label", ""),
                            size=10, color=theme["text_dark"],
                            font=theme["fontHeading"], bold=True))
            els.append(text(right_x + 130, iy, right_w - 146, 20,
                            it.get("text", ""), size=10, color=theme["text_body"],
                            font=theme["fontBody"]))
            iy += 24
    # bottom bar
    if bottom:
        bb_y = CANVAS_H - 60
        els.append(rect(MARGIN, bb_y, CANVAS_W - MARGIN * 2, 36,
                        theme["secondary"], radius=4))
        els.append(text(MARGIN + 16, bb_y, 180, 36, bottom.get("heading", ""),
                        size=12, color=theme["primary"], font=theme["fontHeading"],
                        bold=True, valign="middle"))
        els.append(text(MARGIN + 180, bb_y, CANVAS_W - MARGIN * 2 - 196, 36,
                        bottom.get("text", ""), size=11, color=theme["primary"],
                        font=theme["fontBody"], valign="middle"))
    els += _page_badge(theme, data.get("page"))
    return els


# ══════════════════════════════════════════════════════════
# end
# ══════════════════════════════════════════════════════════

def end(data, theme):
    els = [rect(0, 0, CANVAS_W, CANVAS_H, theme["primary"])]
    els.append(rect(CANVAS_W - 260, CANVAS_H - 160, 260, 160,
                    theme["secondary"], opacity=0.22))
    els.append(oval(-60, -60, 200, 200, theme["secondary"], opacity=0.12))
    els.append(text(80, 200, CANVAS_W - 160, 60, data.get("title", ""),
                    size=40, color=theme["accent"], font=theme["fontHeading"],
                    bold=True, align="center", valign="middle"))
    els.append(line(CANVAS_W / 2 - 30, 272, 60, 2, theme["secondary"]))
    if data.get("subtitle"):
        els.append(text(80, 290, CANVAS_W - 160, 30, data["subtitle"],
                        size=16, color=theme["secondary"], font=theme["fontBody"],
                        align="center"))
    if data.get("contact"):
        els.append(text(80, 340, CANVAS_W - 160, 24, data["contact"],
                        size=12, color=theme["secondary"], font=theme["fontBody"],
                        align="center"))
    return els


# ── Registry ────────────────────────────────────────────────

TEMPLATES = {
    "cover": cover,
    "cover_pro": cover_pro,
    "section_break": section_break,
    "section_break_minimal": section_break_minimal,
    "card_grid": card_grid,
    "icon_list": icon_list,
    "kpi_dashboard": kpi_dashboard,
    "big_statement": big_statement,
    "big_statement_minimal": big_statement_minimal,
    "structured_content": structured_content,
    "grid_content": grid_content,
    "end": end,
}
