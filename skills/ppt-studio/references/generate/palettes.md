# Color Palettes

Choose ONE palette per presentation. All hex values are 6-digit, NO `#` prefix.

> Note: This file holds the color side of the design system only. For fonts/sizes see `typography.md`. For decoration techniques see `visual-language.md`.

---

## Theme Keys (Mandatory)

Every palette declares exactly these 6 color roles plus 2 font fields. Never invent alternative keys.

| Key | Role |
|-----|------|
| `primary` | Main brand color. Dark slide backgrounds, decorative blocks |
| `secondary` | Accent shapes, card borders, decorative elements |
| `accent` | Text on dark backgrounds, highlights |
| `text_dark` | Headings on light backgrounds |
| `text_body` | Body text on light backgrounds |
| `bg_light` | Light slide backgrounds |
| `fontHeading` | Heading font family |
| `fontBody` | Body font family |

---

## Color Role Contract (v3)

These rules are **empirical** — they were derived by trying palettes and observing failures. Edit them only when new evidence accumulates.

### `primary` — main color, large surfaces
- **Brightness band**: lightness ≤ 40% (dark) OR ≥ 90% (very light). Mid-tones forbidden — text overlaid on a mid-tone primary fails contrast in both directions.
- **Default assumption used by templates**: dark. If you choose a light primary, you must also swap white text → dark text in helpers that render on top.
- **Saturation**: keep moderate (0–70%). Highly saturated primary (e.g. neon, pure red) looks cheap at scale.

### `secondary` — accent / point color, small surfaces
- **Surface use**: short accent bars, card borders, number badges, decorative shapes. Total surface area should not exceed ~10% of any slide.
- **Cross-tone rule** (depends on primary's character):
  - **Neutral primary** (saturation < 15%, e.g. near-black/gray): any secondary with saturation ≥ 15% qualifies. Hue free.
  - **Low-saturation primary + low-saturation secondary** (both sat < 35%): require lightness Δ ≥ 15%. This is the "muted/Morandi" path — same-family micro-differentiation is intentional.
  - **Otherwise (mid/high-saturation)**: require hue Δ ≥ 30° OR lightness Δ ≥ 40%.
- **Contrast against primary**: ≥ 3:1.
- **Contrast against bg_light**: ≥ 1.8:1 (decoration-grade, not text-grade — see "Implementation Notes" below).

### `accent` — text on dark backgrounds
- Almost always `FFFFFF`. Use `F5F5F5` or a very-light tinted off-white only if pure white is too harsh for the brand vibe.
- **Never** a saturated color.

### `text_dark` — headings on light backgrounds
- Contrast against `bg_light` ≥ 7:1 (WCAG AAA for headings).
- Usually `primary` itself works, if primary is dark.

### `text_body` — body copy on light backgrounds
- Contrast against `bg_light` ≥ 4.5:1 (WCAG AA).
- Should be softer than `text_dark` — typically a mid gray (#444–#666).

### `bg_light` — light slide backgrounds
- Lightness ≥ 92%.
- Cards on this background are pure white `FFFFFF`. If `bg_light` is also pure white, cards rely on borders (1pt secondary) instead of fill contrast.

---

## Forbidden Patterns

1. ❌ **Same-family stack** (cross-tone fails): primary and secondary share hue family AND lightness band, e.g. `1B2B7B` deep blue + `4A6FA5` mid blue. This was the "Silver Business" v1 failure mode.
2. ❌ **Mid-tone primary**: lightness in 41–89% range. White text won't read, dark text won't read.
3. ❌ **Saturated accent**: `accent` set to anything outside the near-white range.
4. ❌ **More than 3 hue families** in one palette (primary + secondary = max 2 hues; neutrals don't count).

---

## Implementation Notes (How Colors Actually Render)

This block matters when adding new palettes — it explains why some contrast thresholds are loose:

**secondary serves two distinct purposes in templates**:
1. **Decoration** (accent bars, borders, decorative shapes, large faded numbers): only needs to be **visible**, not legible. Threshold: 1.8:1 against bg_light.
2. **Text-bearing surface** (badge backgrounds, summary bar fills) where text sits *on top of* secondary: needs text-grade contrast.

For low-saturation palettes (Morandi, Mist, Quiet Academic), **the template code should NOT place text directly on secondary** — text uses `primary` as background instead. See `visual-language.md` for which elements use which color.

---

## Where Each Role Renders (Reference Table)

| Slide element | Color used | Notes |
|---|---|---|
| Dark slide full background | `primary` | cover, section_break, big_statement, end |
| Light slide full background | `bg_light` | two_column, icon_list, card_grid, timeline, kpi_dashboard |
| Color block bleed (left/right 35–45%) | `primary` | cover, image_text |
| Main text on dark bg | `accent` (≈ white) | titles, body on primary background |
| Secondary text on dark bg | `secondary` | subtitles, captions, meta info |
| Heading on light bg | `text_dark` | titles on bg_light |
| Body text on light bg | `text_body` | paragraphs on bg_light |
| Short accent bar / divider | `secondary` | next to titles, under headings |
| Card fill on light slide | `FFFFFF` (hardcoded) | white cards on bg_light |
| Card fill on dark slide | `bg_light` | light cards on primary bg |
| Card border | `secondary` (1pt) | both light and dark slides |
| Number badge background | `secondary` (mid-sat palettes) or `primary` (low-sat palettes) | template logic should branch |
| Icon circle background | `primary` | strong contrast |
| Large decorative number (section_break) | `secondary` + 18% opacity (HTML rgba) | wallpaper-style overlay |
| Decorative circle/shape (background) | `secondary` + 15–30% opacity | based on slide darkness |

---

## Palette Definitions

12 palettes total. Names split into 2 groups: **Modern (preferred)** for new decks, **Legacy** for compatibility with older content.

### Modern Palettes (preferred, designed under contract v3)

#### 1. 石墨极简 (Graphite Minimal)
冷调中性,安静理性。适合研究汇报、产品文档、技术分享。
- `primary: 1A1A1A` 近黑 · `secondary: 7894A6` 千鸟格蓝灰 · `bg_light: F5F5F5`
- `accent: FFFFFF` · `text_dark: 1A1A1A` · `text_body: 5C5C5C`

#### 2. 深空靖蓝 (Midnight Indigo)
低饱和深色发布会风。适合年度汇报、战略发布。
- `primary: 1C2438` 深空蓝灰 · `secondary: 8FA3B8` 雾蓝灰 · `bg_light: F4F5F8`
- `accent: FFFFFF` · `text_dark: 1C2438` · `text_body: 5B6478`

#### 3. 米白暖棕 (Warm Editorial)
杂志感、人文气质。适合人物、文化、研究专题。
- `primary: 3D2A1E` 深棕 · `secondary: B89178` 奶咖 · `bg_light: F8F2E8`
- `accent: FFFFFF` · `text_dark: 3D2A1E` · `text_body: 7A5F4F`

#### 4. 莫兰迪雾蓝 (Muted Mist)
冷暖中和,柔美现代。适合产品设计、文创策划、女性向内容。
- `primary: 3D4A5C` 雾灰蓝 · `secondary: B89A8C` 灰粉橡 · `bg_light: F2F0EC`
- `accent: FFFFFF` · `text_dark: 3D4A5C` · `text_body: 555E6A`

#### 5. 克制学院蓝 (Quiet Academic)
低调政务/学术风。适合制度解读、流程规范、合规说明。比"政务蓝白"更克制,推荐替代。
- `primary: 2A3D52` 灰学院蓝 · `secondary: 8B97A5` 银灰蓝 · `bg_light: F6F7F9`
- `accent: FFFFFF` · `text_dark: 2A3D52` · `text_body: 4F5868`

#### 6. 森林墨绿 (Forest Ink)
自然冷静感。适合可持续话题、农林相关、生态主题。
- `primary: 1F3329` 深森林 · `secondary: A8967E` 亚麻土 · `bg_light: F4F2EC`
- `accent: FFFFFF` · `text_dark: 1F3329` · `text_body: 586259`

#### 7. 烟阳粉 (Smoke Rose)
柔和编辑设计。适合时尚、文化、消费品类内容。
- `primary: 3D3640` 烟紫深灰 · `secondary: B58D8D` 烟玫瑰 · `bg_light: F7F3F0`
- `accent: FFFFFF` · `text_dark: 3D3640` · `text_body: 6E6470`

### Legacy Palettes (compatibility, less preferred for new decks)

#### 8. 暗夜金沙 (Dark Gold)
深色背景搭配金色点缀,庄重感与高级感并存。**注意**:金色 `C9A86C` 与近黑 primary 之间偏黄,在中性氛围下显土豪味,慎用现代场景。
- `primary: 2A2A2A · secondary: C9A86C · accent: FFFFFF · text_dark: 2A2A2A · text_body: A0A0A0 · bg_light: 3A3A3A`

#### 9. 科技紫蓝 (Tech Purple)
科技感,适合技术调研、创新汇报。但紫蓝 secondary `7EC8E3` 在 2025 年后审美中显得"AI PPT 模板感",可考虑替换为深空靖蓝。
- `primary: 5B4FC4 · secondary: 7EC8E3 · accent: FFFFFF · text_dark: 2D2D5E · text_body: 5A5A7A · bg_light: F2F5FA`

#### 10. 学院红蓝 (Academic Red-Blue)
红蓝撞色,正式严谨。适合党政、制度类。`D42427` 中国红是关键差异色,保留以满足该场景。
- `primary: 1A3C8A · secondary: D42427 · accent: FFFFFF · text_dark: 1A3C8A · text_body: 4A4A4A · bg_light: FFFFFF`

#### 11. 政务蓝白 (Gov Blue)
纯白底 + 宝蓝。**克制学院蓝(#5)是更安静的替代**,但本款仍适合严格政务规范场景。
- `primary: 0052CC · secondary: 3B7DD8 · accent: FFFFFF · text_dark: 0052CC · text_body: 333333 · bg_light: FFFFFF`

#### 12. 银灰商务 (Silver Business)
⚠️ **违反契约**:primary `1B2B7B` 和 secondary `4A6FA5` 同色系。新建文档**不推荐**,仅为旧文档兼容。
- `primary: 1B2B7B · secondary: 4A6FA5 · accent: FFFFFF · text_dark: 1B2B7B · text_body: 555555 · bg_light: EDEDED`

---

## Selection Rules

- **Always present multiple palettes to the user — never auto-select.** Wait for confirmation.
- For new decks, **default the suggestion set to the 7 Modern palettes**. Include Legacy palettes only if the user's brief specifies a tone they cover (e.g. "需要党政红蓝" → include #10).
- If the user describes a custom direction, build a palette using the 6-key structure and **run the Contract Self-Check below** before showing it.
- Pair the palette with a style recipe (see `visual-language.md` — Sharp / Soft / Rounded).

### Contract Self-Check (run before adding any new palette)

```
□ primary lightness ≤ 40% OR ≥ 90% (no mid-tones)?
□ cross-tone passes for primary's saturation tier?
    - neutral primary (sat<15): secondary has sat ≥ 15
    - low-sat both (sat<35): lightness Δ ≥ 15
    - other: hue Δ ≥ 30 OR lightness Δ ≥ 40
□ secondary vs primary contrast ≥ 3:1
□ secondary vs bg_light contrast ≥ 1.8:1 (decoration grade)
□ accent lightness ≥ 92% (near-white)
□ text_dark vs bg_light contrast ≥ 7:1
□ text_body vs bg_light contrast ≥ 4.5:1
□ at most 2 chromatic hue families (primary + secondary)
```

If any check fails, fix before using.

---

## Changelog

- **v3** (current): Cross-tone rule restructured to handle (a) neutral primary, (b) low-saturation paired primary+secondary, (c) other. The original "hue Δ≥60° OR L Δ≥40%" rule was found to be physically impossible for dark-primary palettes (since secondary cannot simultaneously be very-bright-for-dark-bg AND very-dark-for-light-bg). Decoration vs text contrast separated.
- **v2**: Added separate thresholds for dark-primary vs neutral-primary.
- **v1** (deprecated): Single rule of "hue Δ≥60° OR L Δ≥40%". Failed for several palettes including the demo Morandi family.
