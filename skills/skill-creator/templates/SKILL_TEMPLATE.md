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

## Constraints

- <Important boundary or non-goal>
- <Safety or scope constraint>

## Runtime Guidance

- <If this skill uses Python with third-party packages, prefer a skill-local `.venv` plus a wrapper script instead of relying on global packages.>
- <Name the script or entrypoint the agent should run, rather than telling it to call bare `python` directly.>

## Tool Guidance

- <Which tools to prefer and why>
