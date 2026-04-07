---
name: skill-creator
description: Create or update Newman skills in the workspace using the current skill conventions.
when_to_use: Use when the user wants to create, revise, package, or standardize a skill.
---

# Skill Creator

Use this skill when the task is to create a new skill or improve an existing one.

## Goal

Produce a reusable skill directory with a high-quality `SKILL.md`, plus any lightweight `templates/`, `references/`, or `scripts/` files that directly support the workflow.

## Workflow

1. Inspect existing skills first with `list_dir`, `search_files`, and `read_file`.
2. Confirm the target skill name, purpose, and trigger scenario from the user's request.
3. Use the local template files in this skill before writing anything from scratch.
4. Keep `SKILL.md` short and procedural. Put bulky details in `references/`.
5. If the task spans multiple files, create or update a plan with `update_plan`.

## Required skill structure

Every new skill should look like this unless the user explicitly asks for less:

```text
skills/
  <skill_name>/
    SKILL.md
    templates/              # optional
    references/             # optional
    scripts/                # optional
```

## SKILL.md requirements

- Include YAML frontmatter with:
  - `name`
  - `description`
  - `when_to_use`
- Keep the body focused on:
  - Goal
  - Workflow
  - Constraints
  - Tool guidance
- Prefer concrete instructions over abstract philosophy.

## Tool guidance

- Prefer `read_file` to inspect existing skills and templates.
- Prefer `write_file` for new files and `edit_file` for targeted updates.
- Use `search_files` to find similar skills or repeated conventions.
- Use `terminal` only when file tools are insufficient.

## Templates and references

- Base template: `skills/skill-creator/templates/SKILL_TEMPLATE.md`
- Authoring notes: `skills/skill-creator/references/skill_guidelines.md`

Read these supporting files when you need them; do not assume them from memory.
