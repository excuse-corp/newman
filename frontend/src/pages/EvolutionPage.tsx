import { useEffect, useMemo, useState } from "react"
import "./evolution-page.css"

type EvolutionStatus = "running" | "applied" | "skipped" | "failed" | "partial" | "rolled_back"
type EvolutionTrigger = "new_session_created" | "turn_interval" | "manual"

type EvolutionChange = {
  change_id: string
  kind: "memory_update" | "skill_update"
  action: "append" | "create" | "update" | "delete"
  target_path: string
  summary: string
  reason: string
  diff: string
  before_exists: boolean
  snapshot_path?: string | null
  validation_status: "not_run" | "passed" | "failed" | "rolled_back"
  validation_errors: string[]
}

type EvolutionRun = {
  run_id: string
  trigger: EvolutionTrigger
  source_session_id?: string | null
  status: EvolutionStatus
  created_at: string
  updated_at: string
  summary: string
  message_range: number[]
  user_turn_count: number
  changes: EvolutionChange[]
  errors: string[]
  metadata: Record<string, unknown>
}

type EvolutionRunsResponse = {
  runs: EvolutionRun[]
}

type EvolutionRunResponse = {
  run: EvolutionRun
}

type EvolutionPageProps = {
  apiBase: string
}

const statusMeta: Record<EvolutionStatus, { label: string; tone: "green" | "orange" | "blue" | "ink" | "red" }> = {
  running: { label: "运行中", tone: "blue" },
  applied: { label: "已应用", tone: "green" },
  skipped: { label: "已跳过", tone: "ink" },
  failed: { label: "失败", tone: "red" },
  partial: { label: "部分应用", tone: "orange" },
  rolled_back: { label: "已回滚", tone: "ink" }
}

const triggerLabels: Record<EvolutionTrigger, string> = {
  new_session_created: "新会话触发",
  turn_interval: "20 turn 增量",
  manual: "手动触发"
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "暂无"
  return new Intl.DateTimeFormat("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value))
}

function compactPath(value: string) {
  const normalized = value.replace(/\\/g, "/")
  const parts = normalized.split("/")
  if (parts.length <= 4) return normalized
  return `${parts.slice(0, 2).join("/")}/.../${parts.slice(-2).join("/")}`
}

function extractErrorMessage(payload: unknown, fallback: string) {
  if (payload && typeof payload === "object") {
    const record = payload as Record<string, unknown>
    if (typeof record.detail === "string" && record.detail) return record.detail
    if (typeof record.message === "string" && record.message) return record.message
  }
  return fallback
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  const text = await response.text()
  const payload = text ? JSON.parse(text) : null
  if (!response.ok) {
    throw new Error(extractErrorMessage(payload, `请求失败 (${response.status})`))
  }
  return payload as T
}

export default function EvolutionPage({ apiBase }: EvolutionPageProps) {
  const [runs, setRuns] = useState<EvolutionRun[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [selectedRun, setSelectedRun] = useState<EvolutionRun | null>(null)
  const [loading, setLoading] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [rollingBack, setRollingBack] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const selectedStatus = selectedRun ? statusMeta[selectedRun.status] : null
  const appliedCount = useMemo(
    () => selectedRun?.changes.filter((change) => change.validation_status === "passed").length ?? 0,
    [selectedRun]
  )

  useEffect(() => {
    void loadRuns()
  }, [apiBase])

  useEffect(() => {
    if (!selectedRunId) {
      setSelectedRun(null)
      return
    }
    void loadRun(selectedRunId)
  }, [apiBase, selectedRunId])

  async function loadRuns(preferredRunId?: string | null) {
    setLoading(true)
    setError(null)
    try {
      const data = await requestJson<EvolutionRunsResponse>(`${apiBase}/api/evolution/runs`)
      setRuns(data.runs)
      const nextSelected = preferredRunId ?? selectedRunId ?? data.runs[0]?.run_id ?? null
      setSelectedRunId(nextSelected)
      if (!nextSelected) {
        setSelectedRun(null)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载进化日志失败")
    } finally {
      setLoading(false)
    }
  }

  async function loadRun(runId: string) {
    setDetailLoading(true)
    setError(null)
    try {
      const data = await requestJson<EvolutionRunResponse>(`${apiBase}/api/evolution/runs/${encodeURIComponent(runId)}`)
      setSelectedRun(data.run)
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载进化详情失败")
    } finally {
      setDetailLoading(false)
    }
  }

  async function rollbackSelectedRun() {
    if (!selectedRun || selectedRun.status === "rolled_back" || selectedRun.changes.length === 0) return
    const confirmed = window.confirm("确认回滚这次自动进化吗？相关文件会恢复到变更前的快照。")
    if (!confirmed) return

    setRollingBack(true)
    setNotice(null)
    setError(null)
    try {
      const data = await requestJson<EvolutionRunResponse>(
        `${apiBase}/api/evolution/runs/${encodeURIComponent(selectedRun.run_id)}/rollback`,
        { method: "POST" }
      )
      setSelectedRun(data.run)
      setNotice("已回滚本次进化")
      await loadRuns(data.run.run_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : "回滚失败")
    } finally {
      setRollingBack(false)
    }
  }

  return (
    <section className="evolution-page">
      <div className="evolution-toolbar">
        <div className="evolution-toolbar-main">
          <h2>Evolution Log</h2>
          <span>自动更新 MEMORY.md 和 Skill 目录的审计记录</span>
        </div>
        <div className="evolution-toolbar-actions">
          {notice ? <span className="evolution-notice">{notice}</span> : null}
          <button type="button" className="evolution-button" onClick={() => void loadRuns()} disabled={loading}>
            {loading ? "刷新中..." : "刷新"}
          </button>
        </div>
      </div>

      {error ? <div className="evolution-alert">{error}</div> : null}

      <div className="evolution-console">
        <aside className="evolution-run-panel">
          <div className="evolution-panel-head">
            <h3>自动进化记录</h3>
            <span>{runs.length} 条</span>
          </div>
          <div className="evolution-run-list">
            {loading ? <div className="evolution-empty">正在加载进化日志...</div> : null}
            {!loading && runs.length === 0 ? <div className="evolution-empty">还没有自动进化记录。</div> : null}
            {runs.map((run) => {
              const meta = statusMeta[run.status]
              return (
                <button
                  key={run.run_id}
                  type="button"
                  className={`evolution-run-row ${selectedRunId === run.run_id ? "selected" : ""}`}
                  onClick={() => setSelectedRunId(run.run_id)}
                >
                  <div className="evolution-run-row-head">
                    <span>{triggerLabels[run.trigger] ?? run.trigger}</span>
                    <b className={`evolution-status ${meta.tone}`}>{meta.label}</b>
                  </div>
                  <p>{run.summary || "无文件变更"}</p>
                  <small>{formatDateTime(run.updated_at)} · {run.changes.length} 个文件变更</small>
                </button>
              )
            })}
          </div>
        </aside>

        <section className="evolution-detail-panel">
          <div className="evolution-panel-head">
            <h3>详情</h3>
            {selectedRun ? <span>{selectedRun.run_id.slice(0, 10)}</span> : null}
          </div>

          {detailLoading ? <div className="evolution-empty detail">正在加载详情...</div> : null}

          {!detailLoading && !selectedRun ? (
            <div className="evolution-empty detail">选择一条记录查看 diff 和验证结果。</div>
          ) : null}

          {!detailLoading && selectedRun ? (
            <>
              <div className="evolution-detail-summary">
                <div>
                  <span>状态</span>
                  <b className={`evolution-status ${selectedStatus?.tone ?? "ink"}`}>{selectedStatus?.label}</b>
                </div>
                <div>
                  <span>触发</span>
                  <b>{triggerLabels[selectedRun.trigger] ?? selectedRun.trigger}</b>
                </div>
                <div>
                  <span>用户 turn</span>
                  <b>{selectedRun.user_turn_count}</b>
                </div>
                <div>
                  <span>已应用</span>
                  <b>{appliedCount}</b>
                </div>
              </div>

              <div className="evolution-detail-actions">
                <span>来源 session：{selectedRun.source_session_id ?? "暂无"}</span>
                <button
                  type="button"
                  className="evolution-button danger"
                  disabled={rollingBack || selectedRun.status === "rolled_back" || selectedRun.changes.length === 0}
                  onClick={() => void rollbackSelectedRun()}
                >
                  {rollingBack ? "回滚中..." : "回滚本次进化"}
                </button>
              </div>

              {selectedRun.errors.length > 0 ? (
                <div className="evolution-error-list">
                  {selectedRun.errors.map((item) => (
                    <p key={item}>{item}</p>
                  ))}
                </div>
              ) : null}

              <div className="evolution-change-list">
                {selectedRun.changes.length === 0 ? <div className="evolution-empty">这次运行没有产生文件变更。</div> : null}
                {selectedRun.changes.map((change) => (
                  <article className="evolution-change" key={change.change_id}>
                    <div className="evolution-change-head">
                      <div>
                        <h4>{change.summary || `${change.kind} · ${change.action}`}</h4>
                        <p>{compactPath(change.target_path)}</p>
                      </div>
                      <b className={`evolution-status ${change.validation_status === "passed" ? "green" : change.validation_status === "rolled_back" ? "ink" : "orange"}`}>
                        {change.validation_status}
                      </b>
                    </div>
                    {change.reason ? <p className="evolution-change-reason">{change.reason}</p> : null}
                    {change.validation_errors.length > 0 ? (
                      <div className="evolution-error-list compact">
                        {change.validation_errors.map((item) => (
                          <p key={item}>{item}</p>
                        ))}
                      </div>
                    ) : null}
                    {change.diff ? <pre className="evolution-diff">{change.diff}</pre> : null}
                  </article>
                ))}
              </div>
            </>
          ) : null}
        </section>
      </div>
    </section>
  )
}

