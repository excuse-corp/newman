# E-Path Safety Boundaries

This file defines what python-pptx can reliably do, what it cannot, and when an E-path operation should escalate to G' or refuse outright.

**Read this before any other edit/* file.** All recipes assume you have internalized these boundaries.

---

## Core principle

Path E exists to **preserve** the user's original PPT — its master slides, layouts, themes, fonts, and shape positions. Every operation either:
- **Modifies a leaf attribute** (text, font size, color, image bytes) → safe
- **Modifies the slide collection** (add/remove/reorder slides) → mostly safe
- **Modifies shape geometry or relationships** → risky, often unsafe

If you can't tell which category an operation falls into, **assume risky** and re-check this file.

---

## What python-pptx can do reliably

### Safe operations (E1 / E2 / E3)

| Operation | Mechanism | Notes |
|---|---|---|
| Change text in a run | `run.text = "..."` | Font, size, color preserved automatically |
| Change font size | `run.font.size = Pt(N)` | Use `Pt()` from `pptx.util` |
| Change font color | `run.font.color.rgb = RGBColor(0xRR, 0xGG, 0xBB)` | Solid colors only |
| Bold / italic / underline | `run.font.bold = True` | Booleans |
| Change font name | `run.font.name = "Microsoft YaHei"` | Must be a font installed on opener's system, or it will substitute |
| Add a paragraph to a text frame | `tf.add_paragraph()` | Copy attributes from a sibling paragraph to preserve style |
| Remove a paragraph | XML-level delete (see e3) | python-pptx has no high-level API for this |
| Replace an image | `pic._element.getparent().replace(...)` with new picture part | Position/size preserved if reusing same anchor |
| Delete a slide | XML-level removal from slide list | python-pptx has no `slides.remove()` — use the workaround in e3 |
| Reorder slides | Move XML element in slide list | Stable |
| Duplicate a slide | Copy XML + re-link relationships | Tricky; use recipe from e3 |
| Modify table cell text | `cell.text = "..."` or per-run for formatting | Wipes cell formatting if you set `.text` directly; use runs for safety |

### Where python-pptx behaves quirkily

| Behavior | Watch out for |
|---|---|
| `text_frame.text = "..."` | This wipes all paragraph/run formatting and collapses to a single run. Always edit `run.text` instead, run by run. |
| `paragraph.text = "..."` | Same problem — collapses runs. Always edit individual runs. |
| Setting `font.size` on a paragraph | Only affects new runs; existing runs keep their size. Iterate runs. |
| Color comparison | `run.font.color.rgb` can return `None` if the color is inherited from theme. Don't assume it's always set. |
| Font name returning `None` | Same as color — may be theme-inherited. |

---

## What python-pptx cannot do (refuse or escalate)

### Hard limits — operation will fail or corrupt the file

| Operation | Why it fails | What to do instead |
|---|---|---|
| Modify SmartArt internal structure | SmartArt is a special XML grammar; python-pptx treats it as opaque | Tell user it's SmartArt and ask them to convert it to plain shapes first, or escalate to G' |
| Modify embedded Chart data | Charts reference embedded xlsx; python-pptx has limited chart API | If user wants chart data changed, escalate to G' or tell user to edit the source xlsx |
| Modify slide master / layout | These are templates; changes affect all slides referencing them | Refuse — way out of E-path scope |
| Modify theme colors / fonts | Theme is at the deck level | Refuse — escalate to G if user wants a re-theme (whole-deck rebuild) |
| Group / ungroup shapes | python-pptx can read groups but cannot reliably re-group | Refuse |
| Add new chart types or restructure charts | Limited API | Escalate to G' |
| Change slide dimensions | Affects all slides | Refuse |
| Modify animations / transitions | python-pptx ignores these | Refuse — preserve them, but cannot edit |
| Edit speaker notes formatting | Notes have their own text frame; editing text is OK, formatting is fragile | E1 only for notes, never E2 |

### Soft limits — possible but high failure rate

| Operation | Failure mode | Mitigation |
|---|---|---|
| Resize a shape to fit new content | python-pptx can set `width` / `height`, but auto-shrink-to-fit isn't a thing | Measure first, warn user, or escalate to G' |
| Merge two text boxes with different fonts | Result has mixed run formatting, looks messy | Ask user which style to keep |
| Edit text in a Group shape | Need to recurse into group contents | OK if you handle recursion; see e1-text-replace.md |
| Replace image without preserving aspect ratio | Stretched image | Always inspect original w/h and decide whether to crop or letterbox |
| Edit a placeholder vs a regular shape | Placeholders inherit from layout | Read placeholder vs shape distinction in e1 before editing |

---

## When to escalate

E path can't do everything. Two different escalation targets:

### Escalate to G' (regenerate the affected page(s), insert back into original deck)

Use G' when **the original deck is mostly fine, but specific pages need to be rebuilt**:

1. **Content overflow after E3** — added bullets/text causes text frame overflow. Run an overflow check after the edit; if it overflows, revert and escalate.
2. **SmartArt or Chart restructuring requested** — these pages can't be edited in place; regenerate them.
3. **User asks to redesign a specific page** — "make this page look nicer", "重做这一页" — page-level visual redo.
4. **Expand one page into multiple** — content growth that needs new pages.
5. **Insert new themed pages** — adding content the original deck doesn't have.

### Escalate to G (treat upload as content source, build a fresh deck)

Use G when **the deck-level visual framework needs to change**:

1. **Whole-deck rebrand / re-theme** — "modernize the design", "换一套风格", "整体重做" — affects every page.
2. **Master slide / layout / theme color changes** — these are deck-level, can't be done in E.
3. **Visual style overhaul** — even if user says "edit", if they want a different design language across slides, it's a regenerate.
4. **More than ~30% of slides need visual redesign** (not content edits — visual redesign).

### Crucial distinction

Bulk **content** changes (e.g. "把全部页眉的'信管院'换成'信管部'", "all dates from 2024 to 2025") stay in **E1/E2** no matter how many pages they touch — they're still safe leaf-attribute edits.

Bulk **visual** changes (e.g. "把所有标题改成新字体并加装饰条") may technically be doable in E2 for font, but anything beyond font/size/color requires regeneration.

When escalating, tell the user:
> This change goes beyond what precise editing can safely do — [reason]. The cleaner path is to [regenerate the affected pages / build a fresh deck from the original content]. Want me to do that?

---

## When to refuse outright

Refuse if:
- User asks to modify a password-protected PPT
- User asks to remove watermarks / copyright marks from a deck they didn't author
- The file is a `.ppt` (legacy binary) not `.pptx` — tell user to save-as `.pptx` first
- File is corrupted (python-pptx raises on `Presentation()` open)

---

## Pre-flight checklist (run mentally before every E operation)

1. ☐ Have I run `pptx_inspect.py` and seen the actual shapes?
2. ☐ Is the target shape a regular shape, placeholder, group, table, SmartArt, or chart?
   - If SmartArt or Chart → see hard limits
   - If Group → recurse
   - If Placeholder → behaves like shape but inherits layout properties
3. ☐ Am I about to set `text_frame.text` or `paragraph.text` directly? (No — use runs.)
4. ☐ After the change, will content fit in the original frame?
5. ☐ Am I modifying the master, layout, or theme? (No — refuse.)
6. ☐ Will I save to `/mnt/user-data/outputs/` (not overwrite original)?

If any answer is wrong, stop and re-plan.
