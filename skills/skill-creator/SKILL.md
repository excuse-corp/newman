---
name: skill-creator
description: Create or update Newman skills in the workspace using the current skill conventions.
when_to_use: Use when the user wants to create, revise, package, or standardize a skill.
---

# Skill Creator

Use this skill when the task is to create a new skill or improve an existing one.

## Goal

Produce a reusable skill directory with a high-quality `SKILL.md`, plus any lightweight `templates/`, `references/`, `scripts/`, or runtime bootstrap files that directly support the workflow.

## Workflow

1. Inspect existing skills first with `list_dir`, `search_files`, and `read_file`.
2. Confirm the target skill name, purpose, trigger scenario, and runtime assumptions from the user's request.
3. Use the local template files in this skill before writing anything from scratch.
4. Keep `SKILL.md` short and procedural. Put bulky details in `references/`.
5. If a skill ships Python code with third-party packages, prefer a skill-local environment and wrapper script over relying on global packages.
6. If the task spans multiple files, create or update a plan with `update_plan`.

## Required skill structure

Every new skill should look like this unless the user explicitly asks for less:

```text
skills/
  <skill_name>/
    SKILL.md
    templates/              # optional
    references/             # optional
    scripts/                # optional
    requirements.txt        # optional, for Python dependencies
    pyproject.toml          # optional alternative to requirements.txt
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

## Python dependency isolation

- If the skill includes Python code with third-party packages, explain the runtime setup explicitly in `SKILL.md`.
- Prefer a local virtual environment at `<skill-root>/.venv` for Python-based skills instead of depending on system-wide packages.
- Explain `.venv` in beginner-friendly language when helpful: it is a private Python environment just for this skill, so its packages do not conflict with other skills or the machine's global Python.
- Commit the dependency manifest and bootstrap entrypoint, not the generated `.venv` directory, unless the user explicitly wants the environment checked in.
- Prefer a wrapper entrypoint such as `scripts/run.sh`, `scripts/bootstrap.sh`, or `scripts/run.py` that creates `.venv` if missing, installs dependencies, and then runs the real script with the skill-local interpreter.
- In the skill instructions, tell the agent to use the wrapper entrypoint instead of calling bare `python` directly.

## Templates and references

- Base template: `skills/skill-creator/templates/SKILL_TEMPLATE.md`
- Authoring notes: `skills/skill-creator/references/skill_guidelines.md`

Read these supporting files when you need them; do not assume them from memory.
