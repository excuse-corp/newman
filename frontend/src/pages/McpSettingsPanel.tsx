import { useEffect, useMemo, useState } from "react"
import { fetchJson } from "../lib/api"

type McpTransport = "inline" | "http_json" | "http_sse" | "mcp_http" | "mcp_sse" | "stdio"
type McpRiskLevel = "low" | "medium" | "high" | "critical"
type McpServerSource = "project" | "plugin" | "project+plugin"

type McpToolSpec = {
  name: string
  description: string
  input_schema: Record<string, unknown>
  risk_level: McpRiskLevel
}

type McpResourceSpec = {
  uri: string
  name: string
  description: string
  mime_type?: string | null
  content?: string
}

type McpServerConfig = {
  name: string
  transport: McpTransport
  url?: string | null
  command: string[]
  args: string[]
  env: Record<string, string>
  enabled: boolean
  requires_approval: boolean
  argument_path_guard: boolean
  timeout_seconds: number
  headers: Record<string, string>
  tools: McpToolSpec[]
  resources: McpResourceSpec[]
}

type McpServerStatus = {
  name: string
  transport: string
  enabled: boolean
  tool_count: number
  resource_count: number
  status: "connected" | "disabled" | "error" | string
  detail: string
  last_checked_at: string
}

type McpServersResponse = {
  servers: McpServerConfig[]
  server_sources?: Record<string, McpServerSource>
  statuses: McpServerStatus[]
}

type McpUpsertResponse = {
  server: McpServerConfig
  status: McpServerStatus | null
}

type McpReconnectResponse = {
  server_name: string
  status: McpServerStatus
}

type McpServerDraft = {
  name: string
  transport: McpTransport
  url: string
  commandText: string
  argsText: string
  envText: string
  headersText: string
  enabled: boolean
  requiresApproval: boolean
  argumentPathGuard: boolean
  timeoutSeconds: string
}

type McpSettingsPanelProps = {
  apiBase: string
}

const transportOptions: Array<{ id: McpTransport; label: string; helper: string }> = [
  { id: "mcp_http", label: "MCP HTTP", helper: "标准 JSON-RPC / streamable" },
  { id: "mcp_sse", label: "MCP SSE", helper: "官方旧版 SSE endpoint" },
  { id: "http_json", label: "HTTP JSON", helper: "/tools · /resources · /invoke" },
  { id: "http_sse", label: "HTTP SSE", helper: "Newman REST shim + SSE 响应" },
  { id: "stdio", label: "stdio", helper: "本地子进程" },
  { id: "inline", label: "inline", helper: "内联工具" },
]

const emptyRecordJson = "{}"

function emptyDraft(): McpServerDraft {
  return {
    name: "",
    transport: "mcp_http",
    url: "",
    commandText: "",
    argsText: "",
    envText: emptyRecordJson,
    headersText: emptyRecordJson,
    enabled: true,
    requiresApproval: false,
    argumentPathGuard: true,
    timeoutSeconds: "20",
  }
}

function formatJsonRecord(record: Record<string, string>) {
  return Object.keys(record).length > 0 ? JSON.stringify(record, null, 2) : emptyRecordJson
}

function serverToDraft(server: McpServerConfig): McpServerDraft {
  return {
    name: server.name,
    transport: server.transport,
    url: server.url ?? "",
    commandText: (server.command ?? []).join("\n"),
    argsText: (server.args ?? []).join("\n"),
    envText: formatJsonRecord(server.env ?? {}),
    headersText: formatJsonRecord(server.headers ?? {}),
    enabled: server.enabled,
    requiresApproval: server.requires_approval,
    argumentPathGuard: server.argument_path_guard,
    timeoutSeconds: String(server.timeout_seconds ?? 20),
  }
}

function splitLines(value: string) {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean)
}

function isHttpMcpTransport(transport: McpTransport) {
  return transport === "http_json" || transport === "http_sse" || transport === "mcp_http" || transport === "mcp_sse"
}

function coerceStringRecord(value: unknown, label: string): Record<string, string> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} 必须是 JSON object`)
  }
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).map(([key, rawValue]) => [key, String(rawValue)])
  )
}

function parseRecordJson(value: string, label: string): Record<string, string> {
  const trimmed = value.trim()
  if (!trimmed) return {}
  try {
    return coerceStringRecord(JSON.parse(trimmed) as unknown, label)
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new Error(`${label} 不是合法 JSON`)
    }
    throw error
  }
}

function draftToServer(draft: McpServerDraft): McpServerConfig {
  const name = draft.name.trim()
  if (!name) {
    throw new Error("请填写 MCP server 名称")
  }

  const timeoutSeconds = Number(draft.timeoutSeconds)
  if (!Number.isFinite(timeoutSeconds) || timeoutSeconds <= 0) {
    throw new Error("超时时间需要是大于 0 的数字")
  }

  const server: McpServerConfig = {
    name,
    transport: draft.transport,
    url: draft.url.trim() || null,
    command: splitLines(draft.commandText),
    args: splitLines(draft.argsText),
    env: draft.transport === "stdio" ? parseRecordJson(draft.envText, "Env") : {},
    enabled: draft.enabled,
    requires_approval: draft.requiresApproval,
    argument_path_guard: draft.argumentPathGuard,
    timeout_seconds: Math.round(timeoutSeconds),
    headers: isHttpMcpTransport(draft.transport) ? parseRecordJson(draft.headersText, "Headers") : {},
    tools: [],
    resources: [],
  }

  if (isHttpMcpTransport(server.transport) && !server.url) {
    throw new Error("HTTP MCP 需要填写 URL")
  }
  if (server.transport === "stdio" && server.command.length === 0) {
    throw new Error("stdio MCP 需要填写 command")
  }
  return server
}

function transportLabel(transport: string) {
  return transportOptions.find((option) => option.id === transport)?.label ?? transport
}

function sourceLabel(source: McpServerSource | undefined) {
  if (source === "plugin") return "插件"
  if (source === "project+plugin") return "插件覆盖"
  return "本地配置"
}

function statusLabel(status: McpServerStatus | undefined) {
  if (!status) return "未检查"
  if (status.status === "connected") return "已连接"
  if (status.status === "disabled") return "已停用"
  if (status.status === "error") return "错误"
  return status.status
}

function statusTone(status: McpServerStatus | undefined) {
  if (!status) return "subtle"
  if (status.status === "connected") return "success"
  if (status.status === "error") return "danger"
  return "subtle"
}

function summarizeHeaders(headers: Record<string, string>) {
  const keys = Object.keys(headers)
  if (keys.length === 0) return "无 headers"
  return keys.includes("Authorization") ? `${keys.length} headers · 含 Authorization` : `${keys.length} headers`
}

function mapImportedTransport(value: unknown, hasUrl: boolean): McpTransport {
  const normalized = String(value ?? "").trim().toLowerCase().replace(/_/g, "-")
  if (!normalized) return hasUrl ? "mcp_http" : "stdio"
  if (["mcp-http", "streamable-http", "streamable", "http", "http-stream"].includes(normalized)) return "mcp_http"
  if (["mcp-sse", "sse", "server-sent-events"].includes(normalized)) return "mcp_sse"
  if (["http-json", "rest", "newman-http-json"].includes(normalized)) return "http_json"
  if (["http-sse", "newman-http-sse"].includes(normalized)) return "http_sse"
  if (normalized === "stdio") return "stdio"
  if (normalized === "inline") return "inline"
  throw new Error(`暂不支持 MCP transport: ${String(value)}`)
}

function normalizeImportedServers(rawText: string): McpServerConfig[] {
  const parsed = JSON.parse(rawText) as unknown
  if (!parsed || typeof parsed !== "object") {
    throw new Error("导入内容必须是 JSON object")
  }

  const record = parsed as Record<string, unknown>
  const rawServers = record.mcpServers ?? record.mcp_servers ?? record.servers
  const entries = Array.isArray(rawServers)
    ? rawServers.map((item) => [typeof item === "object" && item && "name" in item ? String((item as Record<string, unknown>).name) : "", item] as const)
    : rawServers && typeof rawServers === "object"
      ? Object.entries(rawServers as Record<string, unknown>)
      : []

  const servers = entries.map(([entryName, rawValue]) => {
    if (!rawValue || typeof rawValue !== "object" || Array.isArray(rawValue)) {
      throw new Error(`MCP server ${entryName || "<unknown>"} 配置必须是 object`)
    }
    const item = rawValue as Record<string, unknown>
    const name = String(item.name ?? entryName).trim()
    const url = typeof item.url === "string" ? item.url.trim() : ""
    const transport = mapImportedTransport(item.transport ?? item.type, Boolean(url))
    const command = Array.isArray(item.command)
      ? item.command.map(String)
      : typeof item.command === "string"
        ? [item.command]
        : []
    const args = Array.isArray(item.args) ? item.args.map(String) : []
    const headers = item.headers ? coerceStringRecord(item.headers, "Headers") : {}
    const env = item.env ? coerceStringRecord(item.env, "Env") : {}

    if (!name) {
      throw new Error("存在未命名的 MCP server")
    }
    return {
      name,
      transport,
      url: url || null,
      command,
      args,
      env,
      enabled: item.enabled !== false,
      requires_approval: Boolean(item.requires_approval ?? item.requiresApproval),
      argument_path_guard: item.argument_path_guard === false ? false : item.argumentPathGuard === false ? false : true,
      timeout_seconds:
        typeof item.timeout_seconds === "number"
          ? item.timeout_seconds
          : typeof item.timeoutSeconds === "number"
            ? item.timeoutSeconds
            : url
              ? 60
              : 20,
      headers,
      tools: [],
      resources: [],
    }
  })

  if (servers.length === 0) {
    throw new Error("没有识别到 mcpServers / mcp_servers / servers")
  }
  return servers
}

export default function McpSettingsPanel({ apiBase }: McpSettingsPanelProps) {
  const [servers, setServers] = useState<McpServerConfig[]>([])
  const [statuses, setStatuses] = useState<McpServerStatus[]>([])
  const [serverSources, setServerSources] = useState<Record<string, McpServerSource>>({})
  const [selectedServerName, setSelectedServerName] = useState<string | null>(null)
  const [draft, setDraft] = useState<McpServerDraft>(() => emptyDraft())
  const [importText, setImportText] = useState("")
  const [importOpen, setImportOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [importing, setImporting] = useState(false)
  const [reconnectingName, setReconnectingName] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const statusByName = useMemo(
    () => new Map(statuses.map((status) => [status.name, status])),
    [statuses]
  )
  const selectedServer = selectedServerName ? servers.find((server) => server.name === selectedServerName) ?? null : null
  const selectedStatus = selectedServerName ? statusByName.get(selectedServerName) : undefined
  const selectedSource = selectedServerName ? serverSources[selectedServerName] : undefined
  const projectServerCount = Object.values(serverSources).filter((source) => source === "project" || source === "project+plugin").length
  const connectedCount = statuses.filter((status) => status.status === "connected").length
  const errorCount = statuses.filter((status) => status.status === "error").length
  const selectedIsProjectManaged = !selectedServerName || selectedSource === "project"
  const canSaveDraft = selectedIsProjectManaged && !saving && !loading
  const canMutateSelected = Boolean(selectedServerName && selectedSource === "project")

  async function loadMcpServers(signal?: AbortSignal, preferredName?: string | null) {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchJson<McpServersResponse>(`${apiBase}/api/mcp/servers`, { signal })
      if (signal?.aborted) return
      setServers(data.servers)
      setStatuses(data.statuses)
      setServerSources(data.server_sources ?? {})

      const candidateName = preferredName === undefined ? selectedServerName : preferredName
      const nextSelectedName = candidateName && data.servers.some((server) => server.name === candidateName)
        ? candidateName
        : data.servers[0]?.name ?? null
      setSelectedServerName(nextSelectedName)
      setDraft(nextSelectedName ? serverToDraft(data.servers.find((server) => server.name === nextSelectedName)!) : emptyDraft())
    } catch (loadError) {
      if (signal?.aborted) return
      setError(loadError instanceof Error ? loadError.message : "MCP 配置加载失败")
    } finally {
      if (!signal?.aborted) {
        setLoading(false)
      }
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    void loadMcpServers(controller.signal)
    return () => controller.abort()
  }, [apiBase])

  function updateDraft<Key extends keyof McpServerDraft>(key: Key, value: McpServerDraft[Key]) {
    setDraft((current) => ({ ...current, [key]: value }))
    setError(null)
    setNotice(null)
  }

  function startNewServer() {
    setSelectedServerName(null)
    setDraft(emptyDraft())
    setError(null)
    setNotice(null)
  }

  function startEditingServer(server: McpServerConfig) {
    setSelectedServerName(server.name)
    setDraft(serverToDraft(server))
    setError(null)
    setNotice(null)
  }

  async function saveDraft() {
    if (!canSaveDraft) return
    setSaving(true)
    setError(null)
    setNotice(null)
    try {
      const payload = draftToServer(draft)
      await fetchJson<McpUpsertResponse>(`${apiBase}/api/mcp/servers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      setNotice(`已保存 ${payload.name}，状态已重新检查。`)
      await loadMcpServers(undefined, payload.name)
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "MCP 配置保存失败")
    } finally {
      setSaving(false)
    }
  }

  async function deleteSelectedServer() {
    if (!selectedServerName || !canMutateSelected) return
    if (!window.confirm(`确认删除 MCP server「${selectedServerName}」吗？`)) return
    setDeleting(true)
    setError(null)
    setNotice(null)
    try {
      await fetchJson<{ deleted: boolean; server_name: string }>(
        `${apiBase}/api/mcp/servers/${encodeURIComponent(selectedServerName)}`,
        { method: "DELETE" }
      )
      setNotice(`已删除 ${selectedServerName}`)
      await loadMcpServers(undefined, null)
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "MCP 配置删除失败")
    } finally {
      setDeleting(false)
    }
  }

  async function reconnectSelectedServer() {
    if (!selectedServerName || !canMutateSelected) return
    setReconnectingName(selectedServerName)
    setError(null)
    setNotice(null)
    try {
      const data = await fetchJson<McpReconnectResponse>(
        `${apiBase}/api/mcp/servers/${encodeURIComponent(selectedServerName)}/reconnect`,
        { method: "POST" }
      )
      setNotice(`${data.server_name} 已重连：${statusLabel(data.status)}`)
      await loadMcpServers(undefined, selectedServerName)
    } catch (reconnectError) {
      setError(reconnectError instanceof Error ? reconnectError.message : "MCP 重连失败")
    } finally {
      setReconnectingName(null)
    }
  }

  async function importServers() {
    setImporting(true)
    setError(null)
    setNotice(null)
    try {
      const importedServers = normalizeImportedServers(importText)
      await Promise.all(
        importedServers.map((server) =>
          fetchJson<McpUpsertResponse>(`${apiBase}/api/mcp/servers`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(server),
          })
        )
      )
      setImportText("")
      setImportOpen(false)
      setNotice(`已导入 ${importedServers.length} 个 MCP server。`)
      await loadMcpServers(undefined, importedServers[0]?.name ?? null)
    } catch (importError) {
      setError(importError instanceof Error ? importError.message : "MCP JSON 导入失败")
    } finally {
      setImporting(false)
    }
  }

  return (
    <div className="mcp-settings-shell">
      <article className="workspace-card settings-card mcp-settings-sidebar">
        <div className="workspace-card-head">
          <div>
            <h3>MCP Servers</h3>
            <p>管理本地配置中的 MCP server，并查看运行时连接状态。</p>
          </div>
          <div className="workspace-inline-actions">
            <button type="button" className="workspace-secondary-button" onClick={() => void loadMcpServers()} disabled={loading}>
              {loading ? "刷新中..." : "刷新"}
            </button>
            <button type="button" className="workspace-primary-button" onClick={startNewServer}>
              新增
            </button>
          </div>
        </div>

        <div className="workspace-card-body">
          <div className="workspace-info-grid compact mcp-summary-grid">
            <div className="workspace-mini-card">
              <span className="workspace-mini-label">总数</span>
              <strong>{servers.length}</strong>
            </div>
            <div className="workspace-mini-card">
              <span className="workspace-mini-label">本地配置</span>
              <strong>{projectServerCount}</strong>
            </div>
            <div className="workspace-mini-card">
              <span className="workspace-mini-label">已连接</span>
              <strong>{connectedCount}</strong>
            </div>
            <div className="workspace-mini-card">
              <span className="workspace-mini-label">错误</span>
              <strong>{errorCount}</strong>
            </div>
          </div>

          {loading && servers.length === 0 ? <div className="workspace-empty">正在加载 MCP servers...</div> : null}
          {!loading && servers.length === 0 ? <div className="workspace-empty">当前还没有 MCP server 配置。</div> : null}

          {servers.length > 0 ? (
            <div className="mcp-server-list" aria-label="MCP server 列表">
              {servers.map((server) => {
                const status = statusByName.get(server.name)
                const active = server.name === selectedServerName
                return (
                  <button
                    key={server.name}
                    type="button"
                    className={`mcp-server-row ${active ? "active" : ""}`}
                    onClick={() => startEditingServer(server)}
                  >
                    <span className="mcp-server-row-main">
                      <strong>{server.name}</strong>
                      <span>
                        {transportLabel(server.transport)} · {sourceLabel(serverSources[server.name])} · {summarizeHeaders(server.headers ?? {})}
                      </span>
                    </span>
                    <span className="mcp-server-row-meta">
                      <span className={`workspace-pill ${statusTone(status)}`}>{statusLabel(status)}</span>
                      <span>{status?.tool_count ?? 0} tools</span>
                    </span>
                  </button>
                )
              })}
            </div>
          ) : null}
        </div>
      </article>

      <article className="workspace-card settings-card mcp-settings-editor-card">
        <div className="workspace-card-head">
          <div>
            <h3>{selectedServer ? `编辑 ${selectedServer.name}` : "新增 MCP Server"}</h3>
            <p>
              {selectedServer
                ? `${sourceLabel(selectedSource)} · ${statusLabel(selectedStatus)} · 最近检查 ${selectedStatus?.last_checked_at ? new Date(selectedStatus.last_checked_at).toLocaleString("zh-CN", { hour12: false }) : "暂无"}`
                : "保存后会写入 backend_data/mcp/servers.yaml，并立即刷新运行时能力。"}
            </p>
          </div>
          <div className="workspace-inline-actions">
            <button type="button" className="workspace-secondary-button" onClick={() => setImportOpen((current) => !current)}>
              {importOpen ? "收起导入" : "导入 JSON"}
            </button>
            <button
              type="button"
              className="workspace-secondary-button"
              onClick={() => void reconnectSelectedServer()}
              disabled={!canMutateSelected || reconnectingName !== null}
            >
              {reconnectingName === selectedServerName ? "重连中..." : "重连"}
            </button>
            <button
              type="button"
              className="workspace-danger-button"
              onClick={() => void deleteSelectedServer()}
              disabled={!canMutateSelected || deleting}
            >
              {deleting ? "删除中..." : "删除"}
            </button>
            <button type="button" className="workspace-primary-button" onClick={() => void saveDraft()} disabled={!canSaveDraft}>
              {saving ? "保存中..." : "保存"}
            </button>
          </div>
        </div>

        <div className="workspace-card-body">
          {error ? <div className="workspace-alert error">{error}</div> : null}
          {notice ? <div className="workspace-alert success">{notice}</div> : null}
          {!selectedIsProjectManaged ? (
            <div className="workspace-alert">
              这个 server 来自插件 manifest，当前页面只展示运行状态；请到对应插件目录修改配置。
            </div>
          ) : null}
          {selectedStatus?.detail ? <div className="workspace-alert error">{selectedStatus.detail}</div> : null}

          {importOpen ? (
            <div className="mcp-import-box">
              <div className="workspace-detail-block">
                <span className="workspace-field-label">Claude/Cursor 风格 JSON</span>
                <textarea
                  className="workspace-editor mcp-import-editor"
                  value={importText}
                  onChange={(event) => setImportText(event.target.value)}
                  placeholder={'{\n  "mcpServers": {\n    "demo": {\n      "url": "https://example.com/mcp",\n      "headers": { "Authorization": "Bearer ..." }\n    }\n  }\n}'}
                  spellCheck={false}
                />
              </div>
              <div className="workspace-inline-actions mcp-import-actions">
                <button type="button" className="workspace-secondary-button" onClick={() => setImportOpen(false)} disabled={importing}>
                  取消
                </button>
                <button type="button" className="workspace-primary-button" onClick={() => void importServers()} disabled={importing || !importText.trim()}>
                  {importing ? "导入中..." : "批量导入并保存"}
                </button>
              </div>
              <p className="workspace-tiny-note">
                导入会按 transport/type 自动识别：有 URL 默认 MCP HTTP；sse 映射 MCP SSE；command/args 默认 stdio。含 token 的 headers 会写入本机 backend_data/mcp/servers.yaml。
              </p>
            </div>
          ) : null}

          <div className="mcp-form-grid">
            <label className="workspace-detail-block">
              <span className="workspace-field-label">名称</span>
              <input
                className="workspace-text-input"
                value={draft.name}
                onChange={(event) => updateDraft("name", event.target.value)}
                placeholder="例如 mcp-law-search-service"
                disabled={!selectedIsProjectManaged}
              />
            </label>

            <label className="workspace-detail-block">
              <span className="workspace-field-label">Transport</span>
              <select
                className="workspace-text-input"
                value={draft.transport}
                onChange={(event) => updateDraft("transport", event.target.value as McpTransport)}
                disabled={!selectedIsProjectManaged}
              >
                {transportOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label} - {option.helper}
                  </option>
                ))}
              </select>
            </label>

            <label className="workspace-detail-block mcp-form-wide">
              <span className="workspace-field-label">URL</span>
              <input
                className="workspace-text-input"
                value={draft.url}
                onChange={(event) => updateDraft("url", event.target.value)}
                placeholder="https://example.com/mcp"
                disabled={!selectedIsProjectManaged || !isHttpMcpTransport(draft.transport)}
              />
            </label>

            <label className="workspace-detail-block">
              <span className="workspace-field-label">Timeout 秒</span>
              <input
                className="workspace-text-input"
                value={draft.timeoutSeconds}
                type="number"
                min="1"
                step="1"
                onChange={(event) => updateDraft("timeoutSeconds", event.target.value)}
                disabled={!selectedIsProjectManaged}
              />
            </label>

            <div className="mcp-toggle-grid">
              <label className="mcp-toggle-row">
                <input
                  type="checkbox"
                  checked={draft.enabled}
                  onChange={(event) => updateDraft("enabled", event.target.checked)}
                  disabled={!selectedIsProjectManaged}
                />
                <span>启用</span>
              </label>
              <label className="mcp-toggle-row">
                <input
                  type="checkbox"
                  checked={draft.requiresApproval}
                  onChange={(event) => updateDraft("requiresApproval", event.target.checked)}
                  disabled={!selectedIsProjectManaged}
                />
                <span>调用需确认</span>
              </label>
              <label className="mcp-toggle-row">
                <input
                  type="checkbox"
                  checked={draft.argumentPathGuard}
                  onChange={(event) => updateDraft("argumentPathGuard", event.target.checked)}
                  disabled={!selectedIsProjectManaged}
                />
                <span>参数路径保护</span>
              </label>
            </div>

            <label className="workspace-detail-block mcp-form-wide">
              <span className="workspace-field-label">Headers JSON</span>
              <textarea
                className="workspace-editor mcp-json-editor"
                value={draft.headersText}
                onChange={(event) => updateDraft("headersText", event.target.value)}
                spellCheck={false}
                disabled={!selectedIsProjectManaged || !isHttpMcpTransport(draft.transport)}
              />
            </label>

            <label className="workspace-detail-block">
              <span className="workspace-field-label">Command（一行一个片段）</span>
              <textarea
                className="workspace-editor mcp-command-editor"
                value={draft.commandText}
                onChange={(event) => updateDraft("commandText", event.target.value)}
                placeholder={"python\n-m\nmy_mcp_server"}
                spellCheck={false}
                disabled={!selectedIsProjectManaged || draft.transport !== "stdio"}
              />
            </label>

            <label className="workspace-detail-block">
              <span className="workspace-field-label">Args（一行一个参数）</span>
              <textarea
                className="workspace-editor mcp-command-editor"
                value={draft.argsText}
                onChange={(event) => updateDraft("argsText", event.target.value)}
                spellCheck={false}
                disabled={!selectedIsProjectManaged || draft.transport !== "stdio"}
              />
            </label>

            <label className="workspace-detail-block mcp-form-wide">
              <span className="workspace-field-label">Env JSON</span>
              <textarea
                className="workspace-editor mcp-json-editor"
                value={draft.envText}
                onChange={(event) => updateDraft("envText", event.target.value)}
                spellCheck={false}
                disabled={!selectedIsProjectManaged || draft.transport !== "stdio"}
              />
            </label>
          </div>

          <div className="mcp-runtime-note">
            <strong>运行时命名</strong>
            <span>连接成功后工具会注册为 mcp__server__tool；会话里先激活工具，再调用具体 schema。</span>
          </div>
        </div>
      </article>
    </div>
  )
}
