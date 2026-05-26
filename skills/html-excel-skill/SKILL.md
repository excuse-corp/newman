---
name: html-excel-skill
description: Convert Excel files to HTML for LLM-friendly viewing/editing, with bidirectional Excel↔HTML conversion. Supports merged cells, formulas, multiple sheets, multi-file operations, and split/merge workflows.
when_to_use: Use when the user asks to view, edit, analyze, process, convert, split, or manipulate Excel files, or mentions 'excel', 'xlsx', 'spreadsheet', '表格'.
---

# HTML-Excel Skill

Bidirectional Excel ↔ HTML bridge: Excel → HTML for LLM understanding → edit/analyze → Excel/HTML output.

## Goal

Make Excel files readable and editable by LLMs through HTML as an intermediate representation. The agent reads Excel as HTML, performs user-requested operations, then writes results back to Excel or HTML for download.

## Directory Structure

```
skills/html-excel-skill/
  SKILL.md              # This file
  scripts/
    excel2html.py       # Excel → HTML (primary generator)
    html2excel.py       # HTML → Excel (writeback)
    run_python.py       # Wrapper entry point
  requirements.txt      # Python dependencies
```

## Workflow

### Step 1: Convert Excel to HTML

When user uploads one or more Excel files, first convert each to HTML:

```bash
python3 skills/html-excel-skill/scripts/run_python.py skills/html-excel-skill/scripts/excel2html.py <input.xlsx> [output.html]
```

- If no output path is given, the script auto-generates `<input>.html` next to the source file.
- For multiple files, run the command once per file.
- Each output HTML is a self-contained file with tabs for multiple sheets, styled table, and embedded metadata for writeback.

After generating, **write the HTML to a path the user can preview** (current workspace or an output directory discovered via `list_dir`). Then present the HTML to the user via Newman's HTML preview mechanism.

### Step 2: Present and Discuss

Show the user the HTML preview. Based on their request:

- **View / Analyze**: Read the HTML directly in conversation. Summarize, answer questions, point out patterns.
- **Edit / Modify**: When the user asks to change data, generate a plan of cell-level operations (see "Operation Commands" below).
- **Calculate**: Apply formulas or transformations, then update the HTML.
- **Split**: If the user wants to split one Excel into multiple, plan which rows/sheets go to which output file.

### Step 3: Write Back (when needed)

After processing, if the user wants an Excel download:

```bash
python3 skills/html-excel-skill/scripts/run_python.py skills/html-excel-skill/scripts/html2excel.py <input.html> [output.xlsx]
```

- The HTML must contain the embedded metadata (`data-*` attributes) from the original conversion for accurate writeback.
- If the user only modified content (not structure), writeback is straightforward.
- If the user restructured (added/removed rows/columns), the script handles it via the metadata.

### Step 4: Deliver

- For HTML download: the generated `.html` file is ready as-is.
- For Excel download: run `html2excel.py` and present the `.xlsx` file.
- For multi-file outputs: generate each file separately and list all output paths.

## HTML Format Specification

Each generated HTML file contains:

```html
<html>
<head>
  <meta charset="utf-8">
  <title>{filename}</title>
  <style>/* Table styling: borders, alternating rows, merged cell display */</style>
</head>
<body>
  <!-- If multiple sheets: tab navigation -->
  <div class="sheet-tabs">
    <button class="tab active" data-sheet="0">Sheet1</button>
    <button class="tab" data-sheet="1">Sheet2</button>
  </div>

  <!-- Each sheet as a table, hidden/shown by tabs -->
  <div class="sheet" data-sheet="0" data-merges='[["A1","B2"], ...]' data-formulas='{"C3": "=SUM(A1:A2)", ...}'>
    <table>
      <thead><tr><th>A</th><th>B</th>...</tr></thead>
      <tbody>
        <tr>
          <td data-cell="A1" data-type="number" data-raw="42">42</td>
          <td data-cell="B1" data-type="string" data-raw="Hello">Hello</td>
          <td data-cell="C1" data-type="formula" data-formula="=SUM(A1:A2)" data-raw="52">52</td>
        </tr>
        <!-- Merged cells: use colspan/rowspan + display:none on covered cells -->
        <tr>
          <td data-cell="A2" data-merge="A1:B2" colspan="2" rowspan="2">Merged content</td>
          <td data-cell="C2" data-covered="true" style="display:none"></td>
        </tr>
      </tbody>
    </table>
  </div>

  <script>/* Tab switching logic */</script>
</body>
</html>
```

### Key data-* attributes on `<td>`:

| Attribute | Purpose |
|-----------|---------|
| `data-cell` | Cell reference (e.g. "A1", "C3") |
| `data-type` | "number", "string", "formula", "date", "boolean", "empty" |
| `data-raw` | Original value as string (for writeback) |
| `data-formula` | Excel formula string (if cell is formula) |
| `data-merge` | Merge range (e.g. "A1:B2") on the top-left cell |
| `data-covered` | "true" if this cell is covered by a merge from another cell |

### Key data-* attributes on `<div class="sheet">`:

| Attribute | Purpose |
|-----------|---------|
| `data-sheet` | Sheet index |
| `data-merges` | JSON array of merge ranges for this sheet |
| `data-formulas` | JSON object of cell→formula mappings |

## Operation Commands

When the user asks to modify data, the agent should plan operations as a list of structured commands. These are **internal instructions** the agent follows — not user-facing:

```
# Cell update
SET cell=<ref> sheet=<name> value=<new_value> [formula=<formula>]

# Insert row/column
INSERT row=<index> sheet=<name> [count=<n>]
INSERT col=<letter> sheet=<name> [count=<n>]

# Delete row/column
DELETE row=<index> sheet=<name> [count=<n>]
DELETE col=<letter> sheet=<name> [count=<n>]

# Add sheet
ADD_SHEET name=<name>

# Delete sheet
DEL_SHEET name=<name>

# Split by criteria
SPLIT by=<column> values=<v1,v2,...> outputs=<file1.xlsx,file2.xlsx>
```

After planning, apply changes to the HTML directly (edit the HTML file), then optionally write back to Excel.

## Constraints

- **Token management**: For tables > 200 rows, do NOT embed the full HTML in conversation. Instead, show a summary (row count, column names, first 10 rows) and let the user drill down.
- **Formula fidelity**: Always preserve the original formula string in `data-formula`. The displayed value is the calculated result; the formula is for writeback.
- **Merge preservation**: Merged cells must render correctly in HTML (colspan/rowspan) AND preserve merge info for writeback.
- **Multi-file tracking**: When processing multiple Excel files, maintain a mapping of `filename → HTML path` in your internal context. Never confuse which HTML came from which Excel.
- **Writeback safety**: Before writing Excel, always confirm with the user if the operation is destructive (deleting rows/columns/sheets). Use `request_user_input` with `kind: "confirm"` for destructive operations.
- **Output path**: Write user-facing files to the current working directory or an output directory discovered via `list_dir`. Do not hardcode `/root/newman/output/`.

## Runtime Guidance

- Use `run_python.py` as the entry point for all Python scripts. It creates a local `.venv`, installs `requirements.txt`, and runs the target script.
- Do NOT call bare `python3` directly on the excel scripts.
- Use `write_file` for new HTML files and `edit_file` for targeted modifications.
- Use `request_user_input` when the user needs to choose download format (HTML vs Excel) or confirm destructive operations.
