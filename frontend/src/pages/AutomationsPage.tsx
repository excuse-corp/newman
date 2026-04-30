import { useEffect, useMemo, useState, type FormEvent } from "react"
import "./automations-page.css"

type SessionOption = {
  id: string
  title: string
  updatedAt: string
  messageCount: number
  hasConversation: boolean
  background: boolean
  scheduled: boolean
  triggerType: string | null
  sourceTaskId: string | null
}

type SchedulerTaskAction = {
  type: "session_message" | "background_task"
  prompt: string
  session_id?: string | null
}

type SchedulerTaskRecord = {
  task_id: string
  name: string
  cron: string
  timezone: string
  description?: string | null
  action: SchedulerTaskAction
  enabled: boolean
  max_retries: number
  status: "pending" | "running" | "completed" | "failed" | "disabled"
  created_at: string
  updated_at: string
  last_run_at?: string | null
  next_run_at?: string | null
  last_run_session_id?: string | null
  last_run_turn_id?: string | null
  last_success_at?: string | null
  failure_count: number
  last_run_outcome?: "success" | "failed" | "skipped_conflict" | "skipped_missing_session" | "approval_blocked" | null
  last_skip_reason?: string | null
  source: "chat" | "automation_page" | "api"
  last_error: string
  run_count: number
  human_schedule?: string | null
}

type SchedulerRunRecord = {
  run_id: string
  task_id: string
  trigger_kind: "cron" | "manual_run"
  outcome: "success" | "failed" | "skipped_conflict" | "skipped_missing_session" | "approval_blocked"
  scheduled_for: string
  started_at: string
  finished_at: string
  session_id?: string | null
  turn_id?: string | null
  message: string
}

type SchedulerAlert = {
  alert_id: string
  task_id: string
  task_name: string
  severity: string
  message: string
  created_at: string
  acknowledged: boolean
}

type SchedulerTaskListResponse = {
  tasks: SchedulerTaskRecord[]
}

type SchedulerTaskResponse = {
  task: SchedulerTaskRecord
}

type SchedulerRunsResponse = {
  runs: SchedulerRunRecord[]
}

type SchedulerAlertsResponse = {
  alerts: SchedulerAlert[]
}

type SchedulerDraft = {
  name: string
  description: string
  prompt: string
  cron: string
  timezone: string
  actionType: SchedulerTaskAction["type"]
  sessionId: string
  maxRetries: number
  enabled: boolean
  source: "chat" | "automation_page" | "api"
}

type AutomationsPageProps = {
  apiBase: string
  sessions: SessionOption[]
  activeSession: SessionOption | null
  onOpenSession: (sessionId: string) => void
  onRefreshSessions: (preferredSessionId?: string | null) => Promise<void> | void
}

const cronPresets: Array<{ label: string; value: string; helper: string }> = [
  { label: "工作日晨报", value: "30 9 * * 1-5", helper: "周一到周五 09:30" },
  { label: "每日复盘", value: "0 18 * * *", helper: "每天 18:00" },
  { label: "每小时巡检", value: "0 * * * *", helper: "整点执行" },
  { label: "每周一同步", value: "0 10 * * 1", helper: "每周一 10:00" }
]

const statusMeta: Record<
  SchedulerTaskRecord["status"],
  {
    label: string
    tone: "green" | "orange" | "blue" | "ink"
  }
> = {
  pending: { label: "待运行", tone: "blue" },
  running: { label: "执行中", tone: "orange" },
  completed: { label: "最近成功", tone: "green" },
  failed: { label: "最近失败", tone: "orange" },
  disabled: { label: "已停用", tone: "ink" }
}

const outcomeMeta: Record<
  NonNullable<SchedulerTaskRecord["last_run_outcome"]>,
  {
    label: string
    tone: "green" | "orange" | "ink"
  }
> = {
  success: { label: "成功", tone: "green" },
  failed: { label: "失败", tone: "orange" },
  skipped_conflict: { label: "冲突跳过", tone: "ink" },
  skipped_missing_session: { label: "会话失效", tone: "ink" },
  approval_blocked: { label: "审批阻塞", tone: "orange" }
}

function formatDateTime(value: string | null | undefined) {
  if (!value) {
    return "暂无"
  }
  return new Intl.DateTimeFormat("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value))
}

function localTimezone() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai"
}

function buildDefaultDraft(activeSession: SessionOption | null): SchedulerDraft {
  return {
    name: "",
    description: "",
    prompt: "",
    cron: "30 9 * * 1-5",
    timezone: localTimezone(),
    actionType: activeSession ? "session_message" : "background_task",
    sessionId: activeSession?.id ?? "",
    maxRetries: 1,
    enabled: true,
    source: activeSession ? "chat" : "automation_page"
  }
}

function extractErrorMessage(payload: unknown, fallback: string) {
  if (payload && typeof payload === "object") {
    const record = payload as Record<string, unknown>
    if (typeof record.detail === "string" && record.detail) {
      return record.detail
    }
    if (typeof record.message === "string" && record.message) {
      return record.message
    }
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

function buildTaskTargetLabel(task: SchedulerTaskRecord, sessionsById: Map<string, SessionOption>) {
  if (task.action.type === "background_task") {
    return "后台新会话"
  }
  const session = task.action.session_id ? sessionsById.get(task.action.session_id) : null
  return session ? `继续会话 · ${session.title}` : "继续既有会话"
}

function compactText(value: string, limit = 88) {
  const normalized = value.replace(/\s+/g, " ").trim()
  if (normalized.length <= limit) {
    return normalized
  }
  return `${normalized.slice(0, limit - 1)}…`
}

function taskSourceLabel(task: SchedulerTaskRecord) {
  if (task.source === "chat") {
    return "聊天入口"
  }
  if (task.source === "automation_page") {
    return "任务页"
  }
  return "API"
}

export default function AutomationsPage({ apiBase, sessions, activeSession, onOpenSession, onRefreshSessions }: AutomationsPageProps) {
  const [tasks, setTasks] = useState<SchedulerTaskRecord[]>([])
  const [alerts, setAlerts] = useState<SchedulerAlert[]>([])
  const [runs, setRuns] = useState<SchedulerRunRecord[]>([])
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [editorTaskId, setEditorTaskId] = useState<string | null>(null)
  const [editorOpen, setEditorOpen] = useState(false)
  const [draft, setDraft] = useState<SchedulerDraft>(() => buildDefaultDraft(activeSession))
  const [loading, setLoading] = useState(false)
  const [runsLoading, setRunsLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [busyTaskId, setBusyTaskId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const sessionsById = useMemo(() => new Map(sessions.map((session) => [session.id, session])), [sessions])
  const sortedSessions = useMemo(
    () => [...sessions].sort((left, right) => new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime()),
    [sessions]
  )
  const enabledTaskCount = useMemo(() => tasks.filter((task) => task.enabled).length, [tasks])
  const sessionTaskCount = useMemo(() => tasks.filter((task) => task.action.type === "session_message").length, [tasks])
  const backgroundTaskCount = tasks.length - sessionTaskCount
  const runCount = useMemo(() => tasks.reduce((total, task) => total + task.run_count, 0), [tasks])
  const selectedTask = tasks.find((task) => task.task_id === selectedTaskId) ?? null
  const selectedStatus = selectedTask ? statusMeta[selectedTask.status] : null
  const selectedOutcome = selectedTask?.last_run_outcome ? outcomeMeta[selectedTask.last_run_outcome] : null

  useEffect(() => {
    void refreshDashboard()
  }, [apiBase])

  useEffect(() => {
    if (tasks.length === 0) {
      setSelectedTaskId(null)
      return
    }
    if (!selectedTaskId || !tasks.some((task) => task.task_id === selectedTaskId)) {
      setSelectedTaskId(tasks[0].task_id)
    }
  }, [tasks, selectedTaskId])

  useEffect(() => {
    if (!selectedTaskId) {
      setRuns([])
      return
    }
    void loadRuns(selectedTaskId)
  }, [selectedTaskId, apiBase])

  function resetDraft(targetSession: SessionOption | null = activeSession) {
    setEditorTaskId(null)
    setDraft(buildDefaultDraft(targetSession))
  }

  function openCreateTask(targetSession: SessionOption | null = activeSession) {
    resetDraft(targetSession)
    setEditorOpen(true)
  }

  function closeEditor() {
    setEditorOpen(false)
    resetDraft(activeSession)
  }

  async function refreshDashboard(preferredTaskId?: string | null) {
    setLoading(true)
    setError(null)
    try {
      const [tasksPayload, alertsPayload] = await Promise.all([
        requestJson<SchedulerTaskListResponse>(`${apiBase}/api/scheduler/tasks`),
        requestJson<SchedulerAlertsResponse>(`${apiBase}/api/scheduler/alerts`)
      ])
      await onRefreshSessions()
      setTasks(tasksPayload.tasks)
      setAlerts(alertsPayload.alerts)
      if (preferredTaskId) {
        setSelectedTaskId(preferredTaskId)
      }
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "加载定时任务失败")
    } finally {
      setLoading(false)
    }
  }

  async function loadRuns(taskId: string) {
    setRunsLoading(true)
    try {
      const payload = await requestJson<SchedulerRunsResponse>(`${apiBase}/api/scheduler/tasks/${taskId}/runs?limit=12`)
      setRuns(payload.runs)
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "加载运行记录失败")
    } finally {
      setRunsLoading(false)
    }
  }

  function populateDraftFromTask(task: SchedulerTaskRecord) {
    setEditorTaskId(task.task_id)
    setEditorOpen(true)
    setDraft({
      name: task.name,
      description: task.description ?? "",
      prompt: task.action.prompt,
      cron: task.cron,
      timezone: task.timezone,
      actionType: task.action.type,
      sessionId: task.action.session_id ?? "",
      maxRetries: task.max_retries,
      enabled: task.enabled,
      source: task.source
    })
  }

  async function submitTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!draft.name.trim() || !draft.prompt.trim() || !draft.cron.trim()) {
      setError("名称、Prompt 和 cron 不能为空")
      return
    }
    if (draft.actionType === "session_message" && !draft.sessionId) {
      setError("继续既有会话时必须绑定一个会话")
      return
    }

    setSaving(true)
    setError(null)
    setNotice(null)
    try {
      const payload = {
        name: draft.name.trim(),
        description: draft.description.trim() || null,
        cron: draft.cron.trim(),
        timezone: draft.timezone.trim(),
        enabled: draft.enabled,
        max_retries: draft.maxRetries,
        source: draft.source,
        action: {
          type: draft.actionType,
          prompt: draft.prompt.trim(),
          session_id: draft.actionType === "session_message" ? draft.sessionId : null
        }
      }
      const response = editorTaskId
        ? await requestJson<SchedulerTaskResponse>(`${apiBase}/api/scheduler/tasks/${editorTaskId}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
          })
        : await requestJson<SchedulerTaskResponse>(`${apiBase}/api/scheduler/tasks`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
          })
      await refreshDashboard(response.task.task_id)
      await loadRuns(response.task.task_id)
      setNotice(editorTaskId ? "任务已更新" : "任务已创建")
      setEditorOpen(false)
      resetDraft(activeSession)
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "保存任务失败")
    } finally {
      setSaving(false)
    }
  }

  async function runTaskNow(taskId: string) {
    setBusyTaskId(taskId)
    setError(null)
    setNotice(null)
    try {
      await requestJson<SchedulerTaskResponse>(`${apiBase}/api/scheduler/tasks/${taskId}/run`, {
        method: "POST"
      })
      await refreshDashboard(taskId)
      await loadRuns(taskId)
      setNotice("任务已触发")
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "立即执行失败")
    } finally {
      setBusyTaskId(null)
    }
  }

  async function toggleTask(task: SchedulerTaskRecord) {
    setBusyTaskId(task.task_id)
    setError(null)
    try {
      await requestJson<SchedulerTaskResponse>(`${apiBase}/api/scheduler/tasks/${task.task_id}/${task.enabled ? "disable" : "enable"}`, {
        method: "POST"
      })
      await refreshDashboard(task.task_id)
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "切换任务状态失败")
    } finally {
      setBusyTaskId(null)
    }
  }

  async function deleteTask(task: SchedulerTaskRecord) {
    if (!window.confirm(`确认删除任务「${task.name}」吗？`)) {
      return
    }
    setBusyTaskId(task.task_id)
    setError(null)
    try {
      await requestJson<{ deleted: boolean }>(`${apiBase}/api/scheduler/tasks/${task.task_id}`, {
        method: "DELETE"
      })
      await refreshDashboard(selectedTaskId === task.task_id ? null : selectedTaskId)
      if (editorTaskId === task.task_id) {
        closeEditor()
      }
      setNotice("任务已删除")
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "删除任务失败")
    } finally {
      setBusyTaskId(null)
    }
  }

  return (
    <section className={`workspace-page automations-page ${editorOpen ? "editor-open" : ""}`}>
      <div className="automations-toolbar">
        <div className="automations-toolbar-main">
          <h2>Automations</h2>
          <span>{enabledTaskCount} 启用</span>
          <span>{alerts.length} 告警</span>
          <span>{runCount} 次运行</span>
        </div>
        <div className="automations-toolbar-actions">
          <button type="button" className="workspace-secondary-button" onClick={() => void refreshDashboard(selectedTaskId)} disabled={loading}>
            {loading ? "刷新中" : "刷新"}
          </button>
          <button type="button" className="workspace-primary-button" onClick={() => openCreateTask(activeSession)}>
            + 新建任务
          </button>
        </div>
      </div>

      {error ? <div className="workspace-alert error">{error}</div> : null}
      {notice ? <div className="workspace-alert success">{notice}</div> : null}

      <div className="automations-console">
        <aside className="automations-list-panel">
          <div className="automations-panel-head">
            <h3>任务列表</h3>
            <span>最近 · 启用 · 后台</span>
          </div>

          <div className="automations-task-list">
            {!loading && tasks.length === 0 ? (
              <div className="workspace-empty">
                <button type="button" className="automation-link-button" onClick={() => openCreateTask(activeSession)}>
                  创建第一个定时任务
                </button>
              </div>
            ) : null}

            {tasks.map((task) => {
              const status = statusMeta[task.status]
              const outcome = task.last_run_outcome ? outcomeMeta[task.last_run_outcome] : null
              return (
                <button
                  key={task.task_id}
                  type="button"
                  className={`automations-task-row ${selectedTaskId === task.task_id ? "selected" : ""}`}
                  onClick={() => setSelectedTaskId(task.task_id)}
                >
                  <span className="automations-task-row-title">
                    <strong>{task.name}</strong>
                    <span className={`automation-badge tone-${status.tone}`}>{task.enabled ? "启用" : "停用"}</span>
                  </span>
                  <span className="automations-task-row-schedule">{task.human_schedule || `${task.cron} · ${task.timezone}`}</span>
                  <span className="automations-task-row-meta">
                    <span>{task.action.type === "background_task" ? "后台新会话" : "继续会话"}</span>
                    {outcome ? <span className={`automation-dot tone-${outcome.tone}`} aria-hidden="true" /> : null}
                  </span>
                </button>
              )
            })}
          </div>
        </aside>

        <main className="automations-detail-panel">
          {!selectedTask ? (
            <div className="automations-empty-detail">
              <h3>暂无任务</h3>
              <button type="button" className="workspace-primary-button" onClick={() => openCreateTask(activeSession)}>
                + 新建任务
              </button>
            </div>
          ) : (
            <>
              <section className="automations-task-detail">
                <div className="automations-detail-head">
                  <div className="automations-detail-title">
                    <div className="automations-badge-row">
                      {selectedStatus ? <span className={`automation-badge tone-${selectedStatus.tone}`}>{selectedStatus.label}</span> : null}
                      {selectedOutcome ? <span className={`automation-badge tone-${selectedOutcome.tone}`}>{selectedOutcome.label}</span> : null}
                      <span className="automation-badge ghost">{selectedTask.action.type === "background_task" ? "后台" : "会话"}</span>
                    </div>
                    <h3>{selectedTask.name}</h3>
                    <p>{selectedTask.human_schedule || `${selectedTask.cron} · ${selectedTask.timezone}`}</p>
                  </div>

                  <div className="automations-detail-actions">
                    <button
                      type="button"
                      className="workspace-primary-button"
                      disabled={busyTaskId === selectedTask.task_id}
                      onClick={() => void runTaskNow(selectedTask.task_id)}
                    >
                      {busyTaskId === selectedTask.task_id ? "执行中" : "立即执行"}
                    </button>
                    <button type="button" className="workspace-secondary-button" onClick={() => populateDraftFromTask(selectedTask)}>
                      编辑
                    </button>
                    <button
                      type="button"
                      className="workspace-secondary-button"
                      disabled={busyTaskId === selectedTask.task_id}
                      onClick={() => void toggleTask(selectedTask)}
                    >
                      {selectedTask.enabled ? "停用" : "启用"}
                    </button>
                    <button
                      type="button"
                      className="workspace-danger-button"
                      disabled={busyTaskId === selectedTask.task_id}
                      onClick={() => void deleteTask(selectedTask)}
                    >
                      删除
                    </button>
                  </div>
                </div>

                {selectedTask.description ? <p className="automations-description-line">{selectedTask.description}</p> : null}
                <div className="automations-prompt-preview">{compactText(selectedTask.action.prompt || "暂无 Prompt", 140)}</div>

                <dl className="automations-detail-grid">
                  <div>
                    <dt>目标</dt>
                    <dd>{buildTaskTargetLabel(selectedTask, sessionsById)}</dd>
                  </div>
                  <div>
                    <dt>下次</dt>
                    <dd>{formatDateTime(selectedTask.next_run_at)}</dd>
                  </div>
                  <div>
                    <dt>最近</dt>
                    <dd>{formatDateTime(selectedTask.last_run_at)}</dd>
                  </div>
                  <div>
                    <dt>最近成功</dt>
                    <dd>{formatDateTime(selectedTask.last_success_at)}</dd>
                  </div>
                  <div>
                    <dt>重试</dt>
                    <dd>{selectedTask.max_retries} 次</dd>
                  </div>
                  <div>
                    <dt>来源</dt>
                    <dd>{taskSourceLabel(selectedTask)}</dd>
                  </div>
                </dl>

                {selectedTask.last_error ? <div className="workspace-alert error">{selectedTask.last_error}</div> : null}
                {selectedTask.last_skip_reason ? <div className="workspace-empty">{selectedTask.last_skip_reason}</div> : null}
              </section>

              <section className="automations-runs-panel">
                <div className="automations-panel-head">
                  <h3>最近运行</h3>
                  {selectedTask.last_run_session_id ? (
                    <button type="button" className="automation-link-button" onClick={() => onOpenSession(selectedTask.last_run_session_id as string)}>
                      打开最近会话
                    </button>
                  ) : (
                    <span>{runs.length} 条</span>
                  )}
                </div>

                <div className="automations-run-table">
                  {runsLoading ? <div className="workspace-empty">正在加载运行记录...</div> : null}
                  {!runsLoading && runs.length === 0 ? <div className="workspace-empty">这个任务还没有运行记录。</div> : null}
                  {!runsLoading
                    ? runs.map((run) => {
                        const meta = outcomeMeta[run.outcome]
                        return (
                          <article key={run.run_id} className="automation-run-row">
                            <span className={`automation-run-state tone-${meta.tone}`}>{meta.label}</span>
                            <strong>{formatDateTime(run.finished_at)}</strong>
                            <p>{compactText(run.message || "无运行摘要", 92)}</p>
                            <span>{run.trigger_kind === "manual_run" ? "手动" : "定时"}</span>
                          </article>
                        )
                      })
                    : null}
                </div>
              </section>

              {alerts.length > 0 ? (
                <section className="automations-alert-strip">
                  <div className="automations-panel-head">
                    <h3>最近告警</h3>
                    <span>{alerts.length} 条</span>
                  </div>
                  <div className="automations-alert-list">
                    {alerts.slice(0, 4).map((alert) => (
                      <article key={alert.alert_id} className={`automation-alert-row ${alert.severity === "warning" ? "warning" : "error"}`}>
                        <strong>{alert.task_name}</strong>
                        <p>{compactText(alert.message, 98)}</p>
                        <span>{formatDateTime(alert.created_at)}</span>
                      </article>
                    ))}
                  </div>
                </section>
              ) : null}
            </>
          )}
        </main>
      </div>

      {editorOpen ? (
        <>
          <button type="button" className="automations-editor-scrim" aria-label="关闭编辑面板" onClick={closeEditor} />
          <aside className="automations-editor-drawer" aria-label={editorTaskId ? "编辑定时任务" : "创建定时任务"}>
            <form className="automations-editor-form" onSubmit={submitTask}>
              <div className="automations-editor-head">
                <div>
                  <span className="automations-section-kicker">{editorTaskId ? "Edit Task" : "Create Task"}</span>
                  <h3>{editorTaskId ? "编辑定时任务" : "创建定时任务"}</h3>
                </div>
                <button type="button" className="workspace-secondary-button" onClick={closeEditor}>
                  关闭
                </button>
              </div>

              <div className="automations-editor-scroll">
                <div className="automations-form-section">
                  <div className="automations-field-grid automations-field-grid-compact">
                    <label className="automations-field">
                      <span className="workspace-field-label">任务名称</span>
                      <input
                        className="workspace-text-input"
                        value={draft.name}
                        onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
                        placeholder="例如：每周一跟进客户线索"
                      />
                    </label>

                    <label className="automations-field">
                      <span className="workspace-field-label">时区</span>
                      <input
                        className="workspace-text-input"
                        value={draft.timezone}
                        onChange={(event) => setDraft((current) => ({ ...current, timezone: event.target.value }))}
                        placeholder="Asia/Shanghai"
                      />
                    </label>

                    <label className="automations-field">
                      <span className="workspace-field-label">任务说明</span>
                      <input
                        className="workspace-text-input"
                        value={draft.description}
                        onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))}
                        placeholder="给列表页看的说明，可选"
                      />
                    </label>
                  </div>
                </div>

                <div className="automations-form-section">
                  <div className="automations-preset-row">
                    {cronPresets.map((preset) => (
                      <button
                        key={preset.value}
                        type="button"
                        className={`automation-preset ${draft.cron === preset.value ? "active" : ""}`}
                        onClick={() => setDraft((current) => ({ ...current, cron: preset.value }))}
                      >
                        <strong>{preset.label}</strong>
                        <span>{preset.helper}</span>
                      </button>
                    ))}
                  </div>
                </div>

                <div className="automations-form-section">
                  <div className="automations-compact-grid">
                    <label className="automations-field">
                      <span className="workspace-field-label">Cron</span>
                      <input
                        className="workspace-text-input"
                        value={draft.cron}
                        onChange={(event) => setDraft((current) => ({ ...current, cron: event.target.value }))}
                        placeholder="例如 30 9 * * 1-5"
                      />
                      <small>当前支持 5 段 cron，weekday 采用标准用户语义：0/7=周日，1=周一。</small>
                    </label>

                    <div className="automations-target-panel">
                      <span className="workspace-field-label">目标</span>
                      <div className="automations-target-toggle">
                        <button
                          type="button"
                          className={`automation-toggle-chip ${draft.actionType === "session_message" ? "active" : ""}`}
                          onClick={() =>
                            setDraft((current) => ({
                              ...current,
                              actionType: "session_message",
                              sessionId: current.sessionId || activeSession?.id || "",
                              source: activeSession ? "chat" : current.source
                            }))
                          }
                        >
                          继续既有会话
                        </button>
                        <button
                          type="button"
                          className={`automation-toggle-chip ${draft.actionType === "background_task" ? "active" : ""}`}
                          onClick={() =>
                            setDraft((current) => ({
                              ...current,
                              actionType: "background_task",
                              sessionId: "",
                              source: "automation_page"
                            }))
                          }
                        >
                          后台新会话
                        </button>
                      </div>

                      {draft.actionType === "session_message" ? (
                        <label className="automations-field">
                          <span className="workspace-field-label">绑定会话</span>
                          <select
                            className="workspace-text-input automations-select"
                            value={draft.sessionId}
                            onChange={(event) => setDraft((current) => ({ ...current, sessionId: event.target.value, source: "chat" }))}
                          >
                            <option value="">请选择会话</option>
                            {sortedSessions.map((session) => (
                              <option key={session.id} value={session.id}>
                                {session.title}
                                {activeSession?.id === session.id ? " · 当前会话" : ""}
                              </option>
                            ))}
                          </select>
                        </label>
                      ) : (
                        <div className="automations-inline-note">每次触发会新建一个 `[Scheduled]` 会话，并保留审计事件。</div>
                      )}
                    </div>
                  </div>
                </div>

                <div className="automations-form-section">
                  <div className="automations-execution-grid">
                    <label className="automations-field">
                      <span className="workspace-field-label">执行 Prompt</span>
                      <textarea
                        className="automations-textarea"
                        value={draft.prompt}
                        onChange={(event) => setDraft((current) => ({ ...current, prompt: event.target.value }))}
                        placeholder="定时触发时要发送给 Newman 的内容"
                      />
                    </label>

                    <div className="automations-settings-stack">
                      <label className="automations-field">
                        <span className="workspace-field-label">失败重试</span>
                        <input
                          className="workspace-text-input"
                          type="number"
                          min={0}
                          max={5}
                          value={draft.maxRetries}
                          onChange={(event) =>
                            setDraft((current) => ({
                              ...current,
                              maxRetries: Math.max(0, Math.min(5, Number(event.target.value) || 0))
                            }))
                          }
                        />
                      </label>

                      <label className="automations-checkbox">
                        <input
                          type="checkbox"
                          checked={draft.enabled}
                          onChange={(event) => setDraft((current) => ({ ...current, enabled: event.target.checked }))}
                        />
                        <span>创建后立即启用</span>
                      </label>
                    </div>
                  </div>
                </div>
              </div>

              <div className="automations-editor-actions">
                <button type="button" className="workspace-secondary-button" onClick={closeEditor}>
                  取消
                </button>
                <button type="submit" className="workspace-primary-button" disabled={saving}>
                  {saving ? "保存中..." : editorTaskId ? "保存更新" : "创建任务"}
                </button>
              </div>
            </form>
          </aside>
        </>
      ) : null}
    </section>
  )
}
