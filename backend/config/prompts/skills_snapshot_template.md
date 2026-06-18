## Skills
A skill is a set of local instructions stored in a `SKILL.md` file. Below is the list of skills available in this session.

### Available skills
- This snapshot is generated at runtime from workspace `skills/` and enabled plugin skills. If it has not been refreshed yet, read the current `backend_data/memory/SKILLS_SNAPSHOT.md`.

### How to use skills
- Trigger rules: if the user names a skill, or the task clearly matches a skill description, you must use that skill for this turn.
- Progressive disclosure: do not preload skill bodies. First decide which single skill is most relevant, then read its `SKILL.md` with `read_file`.
- If the skill references sibling files such as `references/`, `templates/`, or `scripts/`, inspect only the files needed for the current task.
- Prefer using existing tools (`read_file`, `list_dir`, `search_files`, `write_file`, `edit_file`, `update_plan`, `terminal`) exactly as the skill instructs.
- Do not read multiple skills up front unless the user explicitly asks for a comparison.
