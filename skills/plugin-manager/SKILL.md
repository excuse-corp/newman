---
name: plugin-manager
description: Create and validate Newman plugin drafts from a user's natural-language requirements. Use for plugin packaging requests, not for ordinary standalone Skill creation.
when_to_use: Use when the user asks Newman to create, package, install, or deploy a plugin that combines Skills with CLI tools or other plugin capabilities.
---

# Plugin Manager

Use `plugin_manager` to create a Newman plugin draft from either a structured `PluginSpec` or a natural-language `request`.

## Workflow

1. Extract the plugin name, purpose, Skills, external commands, read/write paths, environment variables, and approval requirements.
2. Prefer generating a `PluginSpec` using only these supported capabilities:
   - plugin metadata;
   - embedded Skills with `SKILL.md` content;
   - external CLI wrapper commands;
   - command timeout, readonly prefixes, approval behavior, and sandbox roots.
3. Do not generate hooks, MCP servers, arbitrary Python tools, secrets, package-install commands, or unrestricted shell commands.
4. Call `plugin_manager` with `operation="create"` and the structured `spec`. If the request is underspecified but still useful as a Skill-only plugin, pass `request` so Newman can scaffold a conservative draft.
5. If the draft is generated, call `plugin_manager` with `operation="validate"` before describing it as installable.
6. Present the manifest, generated files, risk level, preflight requirements, and validation warnings to the user.
7. Installation and enabling are user-controlled API actions. Never claim that a draft is installed or enabled merely because it was generated.

## Safety

- Use environment variable references for credentials; never put secret values in the manifest or Skill files.
- Treat any command with writable roots or `confirmable` approval as high risk.
- A generated plugin is installed disabled and must be explicitly enabled later.
- Prefer a standalone Skill when no executable capability is needed.
