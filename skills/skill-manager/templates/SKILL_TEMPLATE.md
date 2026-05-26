---
name: <skill_name>
description: <one-line description of what the skill helps with>
when_to_use: <when this skill should be used>
---

# <Skill Title>

## Goal

<Describe the reusable outcome this skill is meant to produce.>

## Workflow

1. <First concrete step>
2. <Second concrete step>
3. <Third concrete step>

## Workflow Gates

- <If a step requires user approval, revision, option selection, or missing information before continuing, call `request_user_input` with `kind`, `prompt`, `content` when relevant, `skill_name`, and `phase`, then stop the turn.>
- <Use `kind: "confirm"` for approvals, `kind: "choice"` for explicit options, and `kind: "free_text"` for open-ended input.>
- <Do not rely on a normal final answer as a waiting-for-confirmation checkpoint.>
- <If the user says "continue" while a gate is pending, treat it as approval of that gate only; still ask for later required gates explicitly.>

## Constraints

- <Important boundary or non-goal>
- <Safety or scope constraint>

## Runtime Guidance

- <If this skill uses Python with third-party packages, prefer a skill-local `.venv` plus a wrapper script instead of relying on global packages.>
- <Name the script or entrypoint the agent should run, rather than telling it to call bare `python` directly.>

## Tool Guidance

- <Which tools to prefer and why>
- <Use `request_user_input` for workflow gates that must pause for user input before continuing.>
- <Use `update_plan` only in Plan mode; if a checklist is necessary, enter or rely on Plan mode first.>
