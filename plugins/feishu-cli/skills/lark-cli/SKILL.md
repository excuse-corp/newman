---
name: lark-cli
version: 1.0.0
description: "Use when the user wants Newman to operate Lark / Feishu resources through the external `lark-cli` binary."
when_to_use: "Use when the user wants to read or write Feishu resources such as docs, sheets, base, drive, chats, calendar, tasks, whiteboards, approvals, meetings, mail, or related Lark data."
---

# lark-cli bridge

In Newman, use the plugin tools instead of calling `terminal` directly.

## Tools

- `lark_cli_skill` reads the current version-matched Agent Skills embedded inside the installed `lark-cli` binary.
- `lark_cli` executes the real `lark-cli` command with structured argv, sandbox rules, and confirmation handling.

## Workflow

1. Use `lark_cli_skill(args=["list"])` to discover the available Lark skill domains.
2. Read `lark-shared` first with `lark_cli_skill(args=["read", "lark-shared"])` for auth, identity, and safety rules.
3. Read the domain skill that matches the task, for example:
   - `lark_cli_skill(args=["read", "lark-doc"])`
   - `lark_cli_skill(args=["read", "lark-sheets"])`
   - `lark_cli_skill(args=["read", "lark-im"])`
4. If that skill references another markdown file, read it through `lark_cli_skill`, for example `lark_cli_skill(args=["read", "lark-doc", "references/lark-doc-xml.md"])`.
5. Execute the actual operation with `lark_cli`.

## Execution rules

- `lark_cli.args` only contains the argv after `lark-cli`.
- `lark_cli_skill.args` only contains the argv after `lark-cli skills`.
- Use `lark_cli.stdin` for large JSON or text payloads instead of shell quoting.
- For `im +messages-send`, explicit `--chat-id`/`--user-id` and explicit `--as bot|user` always win.
- If the user asks to send a Feishu message without naming a recipient or identity, do not ask only to discover defaults and do not search `.env`. Call `lark_cli` with the message content; Newman may inject configured defaults (`NEWMAN_LARK_DEFAULT_IM_USER_ID`, `NEWMAN_LARK_DEFAULT_IM_IDENTITY`).
- If `lark_cli` returns a missing target or missing identity validation error, then ask the user for the missing value.
- If a write command requires confirmation, ask the user first, then retry with `confirm=true`.
- Do not assume plugin-local skill files are authoritative; always treat `lark_cli_skill` as the source of truth for Lark guidance.
