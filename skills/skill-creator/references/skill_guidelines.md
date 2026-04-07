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
