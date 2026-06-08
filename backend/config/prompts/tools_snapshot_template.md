## Tools
Callable tools are provided via function calling in the current turn.
Use the provider tool definitions as the source of truth for available tool names and parameter schemas.

### Tool specs
Generated tool spec files contain path permissions, risk level, approval behavior, timeout, and parameter details.
- Spec path pattern: `backend_data/tool_specs/{tool_name}.md`
- Read a spec file only when parameters, path permissions, or risk details are unclear.

### How to use tools
- Choose only tools present in the current provider tool list.
- Do not invent tool names or call tools that are absent from the current provider tool list.

## MCP Servers
When MCP servers are configured, this file includes server summaries and tool snapshot paths.
MCP tools are grouped by server and are not exposed to the provider by default.
Read the server tool snapshot first, then call `activate_mcp_tool` to expose one specific MCP tool schema.
