# Skill Authoring Guidelines

Use these guidelines when creating or revising a skill.

## Keep the entry file short

- Put only the core workflow in `SKILL.md`.
- Move long examples, schemas, or reference material into `references/`.

## Write for execution

- Tell the agent what to inspect first.
- Tell the agent which tools to prefer.
- Tell the agent what not to do.

## Good frontmatter

- `name` should be the stable skill id.
- `description` should be a short capability summary.
- `when_to_use` should describe the trigger scenario in plain language.

## Prefer repeatable workflows

- Skills should capture a reusable way of working, not one-off project state.
- Avoid embedding temporary file paths unless the skill is intentionally workspace-specific.

## Reuse existing conventions

- Inspect similar skills before inventing a new layout.
- Keep headings and folder names consistent with existing workspace skills when possible.

## Isolate Python dependencies when needed

- If a skill includes Python code that depends on third-party packages, prefer a skill-local virtual environment at `<skill-root>/.venv`.
- For beginners: `.venv` is a private Python installation for just that skill. It keeps package versions for one skill from breaking another skill or the machine's global Python setup.
- Commit the files that describe and bootstrap the environment, such as `requirements.txt`, `pyproject.toml`, and a wrapper script. Do not commit the generated `.venv` folder unless the user explicitly asks for that.
- In `SKILL.md`, instruct the agent to run the wrapper script rather than invoking bare `python` directly.
- Make wrapper scripts idempotent when possible: create `.venv` if missing, install dependencies, then run the actual script using the interpreter inside `.venv`.
