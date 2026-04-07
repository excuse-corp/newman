import { FormEvent, startTransition, useEffect, useRef, useState } from "react";

type ViewKey = "chat" | "memory" | "skills" | "files" | "plugins" | "control";

type SessionSummary = {
  session_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
};

type SessionMessage = {
  id: string;
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  created_at: string;
  metadata: Record<string, unknown>;
};

type MessageAttachment = {
  filename: string;
  content_type: string;
  path: string;
  summary?: string;
};

type CheckpointRecord = {
  checkpoint_id: string;
  summary: string;
  created_at: string;
  metadata?: Record<string, unknown>;
};

type PlanStepStatus = "pending" | "in_progress" | "completed";

type PlanStep = {
  step: string;
  status: PlanStepStatus;
};

type SessionPlan = {
  explanation: string | null;
  steps: PlanStep[];
  updated_at: string;
  current_step: string | null;
  progress: {
    total: number;
    completed: number;
    in_progress: number;
    pending: number;
  };
};

type SessionPayload = {
  session: {
    session_id: string;
    title: string;
    messages: SessionMessage[];
    metadata: Record<string, unknown>;
    updated_at: string;
  };
  plan: SessionPlan | null;
  checkpoint: CheckpointRecord | null;
};

type AuditEntry = {
  event: string;
  data: Record<string, unknown>;
};

type PluginRecord = {
  name: string;
  version: string;
  description: string;
  enabled: boolean;
  plugin_path: string;
  skill_count: number;
  hook_count: number;
  mcp_server_count: number;
};

type PluginLoadError = {
  plugin_path: string;
  plugin_name: string | null;
  message: string;
};

type SkillRecord = {
  name: string;
  source: string;
  plugin_name: string | null;
  path: string;
  summary: string;
};

type MemoryFiles = Record<string, { path: string; content: string }>;

type FileEntry = {
  name: string;
  path: string;
  type: "dir" | "file";
};

type FileDirPayload = {
  path: string;
  type: "dir";
  entries: FileEntry[];
};

type FileContentPayload = {
  path: string;
  type: "file";
  content: string;
};

type KnowledgeDocument = {
  document_id: string;
  title: string;
  source_path: string;
  stored_path: string;
  size_bytes: number;
  imported_at: string;
};

type KnowledgeHit = {
  document_id: string;
  title: string;
  stored_path: string;
  snippet: string;
  score: number;
  lexical_score: number;
  vector_score: number;
  rerank_score: number;
  line_number: number | null;
  chunk_index: number | null;
  page_number: number | null;
  location_label: string | null;
};

type SchedulerTask = {
  task_id: string;
  name: string;
  cron: string;
  enabled: boolean;
  status: string;
  next_run_at: string | null;
  last_run_at: string | null;
  last_error: string;
  run_count: number;
  action: {
    type: string;
    prompt: string;
    session_id: string | null;
  };
};

type ChannelStatus = {
  platform: string;
  enabled: boolean;
  webhook_token_configured: boolean;
};

type AppHealth = {
  ok: boolean;
  version: string;
  provider: string;
  sandbox_enabled: boolean;
  tools: string[];
  knowledge_documents: number;
  plugins_enabled: number;
  scheduler_running: boolean;
};

type ReadyInfo = {
  ok: boolean;
  knowledge_dir: string;
  sessions_dir: string;
  plugins_dir: string;
  skills_dir: string;
  mcp_dir: string;
  scheduler_dir: string;
  channels_dir: string;
};

type ApprovalRequest = {
  approval_request_id: string;
  tool: string;
  arguments: Record<string, unknown>;
  reason: string;
  timeout_seconds: number;
};

type TimelineItem = {
  id: string;
  event: string;
  data: Record<string, unknown>;
  live?: boolean;
};

const navItems: Array<{ id: ViewKey; label: string; hint: string }> = [
  { id: "chat", label: "Chat", hint: "对话" },
  { id: "memory", label: "Memory", hint: "记忆" },
  { id: "skills", label: "Skills", hint: "技能" },
  { id: "files", label: "Files", hint: "文件" },
  { id: "plugins", label: "Plugins", hint: "扩展" },
  { id: "control", label: "Control", hint: "控制" }
];

const LEFT_MIN = 220;
const LEFT_MAX = 360;
const RIGHT_MIN = 280;
const RIGHT_MAX = 520;
const HANDLE_WIDTH = 8;

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function formatTime(value: string | null | undefined) {
  if (!value) return "未记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function buildEventSummary(item: TimelineItem) {
  const data = item.data;
  switch (item.event) {
    case "tool_call_started":
      return `调用 ${String(data.tool ?? "")}`;
    case "tool_call_finished":
      if (data.success === false) {
        return `${String(data.tool ?? "")} · ${String(data.frontend_message ?? data.summary ?? "执行失败")}`;
      }
      return `${String(data.tool ?? "")} · ${String(data.summary ?? "")}`;
    case "tool_error_feedback":
      return `${String(data.tool ?? "")} 出错 · ${String(data.frontend_message ?? data.summary ?? "")}`;
    case "tool_approval_request":
      return `审批等待 · ${String(data.tool ?? "")}`;
    case "checkpoint_created":
      return "创建了新的 checkpoint";
    case "attachment_received":
      return `收到 ${String(data.count ?? 0)} 个图片附件`;
    case "attachment_processed":
      return `完成 ${String(data.count ?? 0)} 个图片解析`;
    case "hook_triggered":
      return String(data.message ?? "触发插件 hook");
    case "plan_updated":
      return String(data.summary ?? "计划已更新");
    case "final_response":
      return "本轮响应完成";
    case "error":
      return `${String(data.code ?? "ERROR")} · ${String(data.message ?? "运行异常")}`;
    default:
      return item.event;
  }
}

function getMessageAttachments(message: SessionMessage): MessageAttachment[] {
  const raw = message.metadata.attachments;
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((item): item is MessageAttachment => typeof item === "object" && item !== null && "filename" in item && "path" in item)
    .map((item) => ({
      filename: String(item.filename),
      content_type: String(item.content_type ?? ""),
      path: String(item.path),
      summary: item.summary ? String(item.summary) : undefined
    }));
}

async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error?.error?.message ?? `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

async function apiSend<T>(path: string, method: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: {
      "Content-Type": "application/json"
    },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error?.error?.message ?? `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

function App() {
  const [activeView, setActiveView] = useState<ViewKey>("chat");
  const [leftWidth, setLeftWidth] = useState(260);
  const [rightWidth, setRightWidth] = useState(360);
  const [dragging, setDragging] = useState<null | "left" | "right">(null);
  const [viewportWidth, setViewportWidth] = useState(() => window.innerWidth);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [sessionData, setSessionData] = useState<SessionPayload | null>(null);
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [selectedTimelineId, setSelectedTimelineId] = useState<string | null>(null);
  const [draftMessage, setDraftMessage] = useState("");
  const [selectedImages, setSelectedImages] = useState<File[]>([]);
  const [pendingApproval, setPendingApproval] = useState<ApprovalRequest | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [statusNote, setStatusNote] = useState("正在连接 Newman 工作台...");
  const [memoryFiles, setMemoryFiles] = useState<MemoryFiles>({});
  const [selectedMemoryKey, setSelectedMemoryKey] = useState("memory");
  const [memoryDraft, setMemoryDraft] = useState("");
  const [skills, setSkills] = useState<SkillRecord[]>([]);
  const [plugins, setPlugins] = useState<PluginRecord[]>([]);
  const [pluginErrors, setPluginErrors] = useState<PluginLoadError[]>([]);
  const [workspacePayload, setWorkspacePayload] = useState<FileDirPayload | FileContentPayload | null>(null);
  const [knowledgeDocuments, setKnowledgeDocuments] = useState<KnowledgeDocument[]>([]);
  const [knowledgeQuery, setKnowledgeQuery] = useState("Phase 3");
  const [knowledgeHits, setKnowledgeHits] = useState<KnowledgeHit[]>([]);
  const [schedulerTasks, setSchedulerTasks] = useState<SchedulerTask[]>([]);
  const [channelStatus, setChannelStatus] = useState<ChannelStatus[]>([]);
  const [health, setHealth] = useState<AppHealth | null>(null);
  const [readyInfo, setReadyInfo] = useState<ReadyInfo | null>(null);
  const [taskForm, setTaskForm] = useState({ name: "夜间回顾", cron: "0 21 * * *", prompt: "请根据今天的会话总结工作进展" });
  const [knowledgeImportPath, setKnowledgeImportPath] = useState("docs/Newman_API_v1.md");
  const [knowledgeUploadFile, setKnowledgeUploadFile] = useState<File | null>(null);
  const streamAbortRef = useRef<AbortController | null>(null);

  const selectedTimeline = timeline.find((item) => item.id === selectedTimelineId) ?? null;
  const isMobile = viewportWidth <= 980;
  const sessionMessages = sessionData?.session.messages ?? [];
  const activePlan = sessionData?.plan ?? (sessionData?.session.metadata.plan as SessionPlan | undefined) ?? null;
  const contextUsage = Math.min(100, Math.max(8, sessionMessages.length * 8));
  const activeMemoryFile = memoryFiles[selectedMemoryKey];

  const sessionCountLabel = `${sessions.length} sessions`;

  useEffect(() => {
    const onResize = () => setViewportWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    if (!dragging) return;
    const onPointerMove = (event: PointerEvent) => {
      if (dragging === "left") {
        setLeftWidth(clamp(event.clientX, LEFT_MIN, LEFT_MAX));
        return;
      }
      const width = window.innerWidth - event.clientX - 6;
      setRightWidth(clamp(width, RIGHT_MIN, RIGHT_MAX));
    };
    const onPointerUp = () => setDragging(null);
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
    };
  }, [dragging]);

  useEffect(() => {
    void bootstrap();
    return () => {
      streamAbortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    setMemoryDraft(activeMemoryFile?.content ?? "");
  }, [activeMemoryFile?.content, selectedMemoryKey]);

  useEffect(() => {
    const keys = Object.keys(memoryFiles);
    if (!keys.length) return;
    if (memoryFiles[selectedMemoryKey]) return;
    setSelectedMemoryKey(keys.includes("memory") ? "memory" : keys[0]);
  }, [memoryFiles, selectedMemoryKey]);

  async function bootstrap() {
    try {
      await Promise.all([
        refreshSessions(),
        refreshMemory(),
        refreshSkills(),
        refreshPlugins(),
        refreshWorkspace("."),
        refreshKnowledgeDocuments(),
        refreshSchedulerTasks(),
        refreshChannels(),
        refreshHealth()
      ]);
      setStatusNote("工作台已就绪，可以开始新的任务。");
    } catch (error) {
      setStatusNote(error instanceof Error ? error.message : "初始化失败");
    }
  }

  async function refreshSessions(preferredSessionId?: string | null) {
    const data = await apiGet<SessionSummary[]>("/api/sessions");
    startTransition(() => setSessions(data));
    const nextSessionId = preferredSessionId ?? activeSessionId ?? data[0]?.session_id ?? null;
    if (nextSessionId) {
      await loadSession(nextSessionId);
    } else {
      setActiveSessionId(null);
      setSessionData(null);
      setTimeline([]);
    }
  }

  async function loadSession(sessionId: string) {
    const [sessionPayload, auditPayload] = await Promise.all([
      apiGet<SessionPayload>(`/api/sessions/${sessionId}`),
      apiGet<{ session_id: string; events: string[] }>(`/api/audit/${sessionId}`)
    ]);
    const parsedTimeline = auditPayload.events.map((line, index) => {
      const parsed = JSON.parse(line) as AuditEntry;
      return {
        id: `${parsed.event}-${index}`,
        event: parsed.event,
        data: parsed.data
      };
    });
    startTransition(() => {
      setActiveSessionId(sessionId);
      setSessionData(sessionPayload);
      setTimeline(parsedTimeline);
      setSelectedTimelineId(parsedTimeline.length ? parsedTimeline[parsedTimeline.length - 1].id : null);
    });
  }

  async function ensureSession(seedTitle?: string) {
    if (activeSessionId) return activeSessionId;
    const created = await apiSend<{ session_id: string; title: string; created: boolean }>(
      "/api/sessions",
      "POST",
      { title: seedTitle ?? "新的工作流" }
    );
    await refreshSessions(created.session_id);
    return created.session_id;
  }

  async function sendMessage(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const content = draftMessage.trim();
    const images = selectedImages;
    if ((!content && images.length === 0) || streaming) return;
    try {
      setStatusNote("Newman 正在处理这条消息...");
      setDraftMessage("");
      setStreaming(true);
      setSelectedImages([]);
      const sessionId = await ensureSession(content.slice(0, 20) || "图片输入");
      const controller = new AbortController();
      streamAbortRef.current = controller;
      const body = new FormData();
      body.set("content", content);
      for (const image of images) {
        body.append("images", image);
      }

      const response = await fetch(`/api/sessions/${sessionId}/messages`, {
        method: "POST",
        body,
        signal: controller.signal
      });

      if (!response.ok || !response.body) {
        const error = await response.json().catch(() => ({}));
        setStatusNote(error?.error?.message ?? "消息发送失败");
        setStreaming(false);
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      let assistantContent = "";

      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";

        for (const frame of frames) {
          const line = frame
            .split("\n")
            .find((item) => item.startsWith("data:"));
          if (!line) continue;
          const payload = JSON.parse(line.replace(/^data:\s*/, ""));
          const eventType = payload.event as string;
          const data = payload.data as Record<string, unknown>;
          const timelineId = `${eventType}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;

          setTimeline((current) => [...current, { id: timelineId, event: eventType, data, live: true }]);
          setSelectedTimelineId(timelineId);

          if (eventType === "assistant_delta") {
            assistantContent = String(data.content ?? assistantContent);
            setStatusNote("正在生成最终回答...");
          }
          if (eventType === "tool_approval_request") {
            setPendingApproval(data as unknown as ApprovalRequest);
            setStatusNote(`等待审批: ${String(data.tool ?? "")}`);
          }
          if (eventType === "tool_approval_resolved") {
            setPendingApproval(null);
          }
          if (eventType === "tool_error_feedback") {
            setStatusNote(String(data.frontend_message ?? data.summary ?? "工具执行出现异常"));
          }
          if (eventType === "error") {
            setStatusNote(String(data.message ?? "运行异常"));
          }
          if (eventType === "plan_updated") {
            const plan = (data.plan as SessionPlan | undefined) ?? null;
            if (plan) {
              setSessionData((current) =>
                current
                  ? {
                      ...current,
                      plan,
                      session: {
                        ...current.session,
                        metadata: {
                          ...current.session.metadata,
                          plan
                        }
                      }
                    }
                  : current
              );
            }
            setStatusNote(String(data.summary ?? "计划已更新。"));
          }
          if (eventType === "stream_completed") {
            setStreaming(false);
          }
        }

        if (done) break;
      }

      await refreshSessions(sessionId);
      setPendingApproval(null);
      setStreaming(false);
      setStatusNote(assistantContent ? "本轮任务已完成。" : "流式任务已结束。");
    } catch (error) {
      setStreaming(false);
      setStatusNote(error instanceof Error ? error.message : "消息发送失败");
    }
  }

  function getWorkspaceParentPath() {
    if (!workspacePayload?.path || workspacePayload.path === "/root/newman") return ".";
    const segments = workspacePayload.path.split("/").filter(Boolean);
    segments.pop();
    return `/${segments.join("/")}`;
  }

  async function refreshMemory() {
    const payload = await apiGet<{ files: MemoryFiles }>("/api/workspace/memory");
    setMemoryFiles(payload.files);
  }

  async function saveMemory() {
    if (!selectedMemoryKey) return;
    await apiSend(`/api/workspace/memory/${selectedMemoryKey}`, "PUT", { content: memoryDraft });
    await refreshMemory();
    setStatusNote(`${selectedMemoryKey} 已保存。`);
  }

  async function refreshSkills() {
    const payload = await apiGet<{ skills: SkillRecord[] }>("/api/skills");
    setSkills(payload.skills);
  }

  async function refreshPlugins() {
    const payload = await apiGet<{ plugins: PluginRecord[]; errors?: PluginLoadError[] }>("/api/plugins");
    setPlugins(payload.plugins);
    setPluginErrors(payload.errors ?? []);
  }

  async function togglePlugin(plugin: PluginRecord) {
    const endpoint = plugin.enabled ? "disable" : "enable";
    await apiSend(`/api/plugins/${plugin.name}/${endpoint}`, "POST");
    await Promise.all([refreshPlugins(), refreshSkills(), refreshHealth()]);
    setStatusNote(`${plugin.name} 已${plugin.enabled ? "停用" : "启用"}。`);
  }

  async function refreshWorkspace(path: string) {
    const payload = await apiGet<FileDirPayload | FileContentPayload>(`/api/workspace/files?path=${encodeURIComponent(path)}`);
    setWorkspacePayload(payload);
  }

  async function refreshKnowledgeDocuments() {
    const payload = await apiGet<{ documents: KnowledgeDocument[] }>("/api/knowledge/documents");
    setKnowledgeDocuments(payload.documents);
  }

  async function importKnowledge() {
    await apiSend("/api/knowledge/documents/import", "POST", { source_path: knowledgeImportPath });
    await refreshKnowledgeDocuments();
    setStatusNote("知识文档已导入。");
  }

  async function uploadKnowledgeFile() {
    if (!knowledgeUploadFile) return;
    const body = new FormData();
    body.set("file", knowledgeUploadFile);
    const response = await fetch("/api/knowledge/documents/upload", {
      method: "POST",
      body
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error?.error?.message ?? `${response.status} ${response.statusText}`);
    }
    setKnowledgeUploadFile(null);
    await refreshKnowledgeDocuments();
    setStatusNote("知识文件已上传并导入。");
  }

  async function searchKnowledge() {
    const payload = await apiSend<{ query: string; hits: KnowledgeHit[] }>("/api/knowledge/search", "POST", {
      query: knowledgeQuery,
      limit: 5
    });
    setKnowledgeHits(payload.hits);
  }

  async function refreshSchedulerTasks() {
    const payload = await apiGet<{ tasks: SchedulerTask[] }>("/api/scheduler/tasks");
    setSchedulerTasks(payload.tasks);
  }

  async function createTask() {
    await apiSend("/api/scheduler/tasks", "POST", {
      name: taskForm.name,
      cron: taskForm.cron,
      action: {
        type: "background_task",
        prompt: taskForm.prompt
      },
      enabled: true,
      max_retries: 5
    });
    await refreshSchedulerTasks();
    setStatusNote("调度任务已创建。");
  }

  async function runTask(taskId: string) {
    await apiSend(`/api/scheduler/tasks/${taskId}/run`, "POST");
    await refreshSchedulerTasks();
    await refreshSessions();
    setStatusNote("调度任务已立即执行。");
  }

  async function refreshChannels() {
    const payload = await apiGet<{ channels: ChannelStatus[] }>("/api/channels/status");
    setChannelStatus(payload.channels);
  }

  async function refreshHealth() {
    const [healthPayload, readyPayload] = await Promise.all([apiGet<AppHealth>("/healthz"), apiGet<ReadyInfo>("/readyz")]);
    setHealth(healthPayload);
    setReadyInfo(readyPayload);
  }

  async function resolveApproval(approved: boolean) {
    if (!pendingApproval || !activeSessionId) return;
    const path = approved ? "approve" : "reject";
    await apiSend(`/api/sessions/${activeSessionId}/${path}`, "POST", {
      approval_request_id: pendingApproval.approval_request_id
    });
    setPendingApproval(null);
    setStatusNote(approved ? "审批已通过。" : "审批已拒绝。");
  }

  async function manualCompress() {
    if (!activeSessionId) return;
    await apiSend(`/api/sessions/${activeSessionId}/compress`, "POST");
    await loadSession(activeSessionId);
    setStatusNote("已手动创建 checkpoint。");
  }

  async function restoreCheckpoint() {
    if (!activeSessionId) return;
    await apiSend(`/api/sessions/${activeSessionId}/restore-checkpoint`, "POST");
    await loadSession(activeSessionId);
    setStatusNote("已从 checkpoint 恢复上下文。");
  }

  async function createSession() {
    const created = await apiSend<{ session_id: string }>("/api/sessions", "POST", { title: "新的工作流" });
    await refreshSessions(created.session_id);
    setStatusNote("新会话已创建。");
  }

  function getPlanPillClass(status: PlanStepStatus) {
    if (status === "completed") return "pill pill-green";
    if (status === "in_progress") return "pill pill-blue";
    return "pill pill-orange";
  }

  function getPlanStatusLabel(status: PlanStepStatus) {
    if (status === "completed") return "completed";
    if (status === "in_progress") return "in progress";
    return "pending";
  }

  function renderPlanCard(plan: SessionPlan) {
    return (
      <article className="plan-card">
        <div className="plan-card-head">
          <div>
            <div className="pill pill-blue">Plan</div>
            <h3>多阶段任务规划</h3>
          </div>
          <small>
            {plan.progress.completed}/{plan.progress.total} completed · {formatTime(plan.updated_at)}
          </small>
        </div>
        {plan.explanation ? <p className="plan-copy">{plan.explanation}</p> : null}
        <div className="plan-metrics">
          <div>
            <span>In Progress</span>
            <strong>{plan.progress.in_progress}</strong>
          </div>
          <div>
            <span>Completed</span>
            <strong>{plan.progress.completed}</strong>
          </div>
          <div>
            <span>Pending</span>
            <strong>{plan.progress.pending}</strong>
          </div>
        </div>
        <div className="plan-step-list">
          {plan.steps.map((step, index) => (
            <div key={`${step.step}-${index}`} className={`plan-step ${step.status}`}>
              <span className={getPlanPillClass(step.status)}>{getPlanStatusLabel(step.status)}</span>
              <strong>{step.step}</strong>
            </div>
          ))}
        </div>
      </article>
    );
  }

  function renderChatWorkspace() {
    return (
      <>
        <section className="chat-header">
          <div>
            <div className="eyebrow">Task Console</div>
            <h2>{sessionData?.session.title ?? "开启新的任务"}</h2>
          </div>
          <div className="header-actions">
            <button type="button" className="soft-button" onClick={() => void manualCompress()} disabled={!activeSessionId}>
              手动压缩
            </button>
            <button
              type="button"
              className="soft-button"
              onClick={() => void restoreCheckpoint()}
              disabled={!activeSessionId || !sessionData?.checkpoint}
            >
              恢复 checkpoint
            </button>
            <div className="context-meter">
              <span>Context</span>
              <strong>{contextUsage}%</strong>
            </div>
          </div>
        </section>

        <section className="chat-grid">
          <div className="conversation-pane">
            {sessionData?.checkpoint ? (
              <article className="checkpoint-card">
                <div className="pill pill-orange">Checkpoint</div>
                <p>{sessionData.checkpoint.summary}</p>
              </article>
            ) : null}

            {activePlan ? renderPlanCard(activePlan) : null}

            {sessionMessages.length === 0 ? (
              <div className="empty-state-pane">
                <div className="empty-state-inner">
                  <div className="poster-mark">NEWMAN / WORKBENCH</div>
                  <h2 className="empty-state-title">把任务拆给本地 Agent，而不是把问题丢进黑盒。</h2>
                  <p className="empty-state-copy">
                    这里会同时显示会话、工具轨迹、审批、错误恢复和证据细节。先发一条消息，或者从左侧切回历史会话。
                  </p>
                </div>
              </div>
            ) : (
              <div className="message-stack">
                {sessionMessages.map((message) => (
                  <article key={message.id} className={`message-card ${message.role}`}>
                    <header>
                      <span>{message.role.toUpperCase()}</span>
                      <time>{formatTime(message.created_at)}</time>
                    </header>
                    {getMessageAttachments(message).length ? (
                      <div className="attachment-list">
                        {getMessageAttachments(message).map((attachment) => (
                          <div key={`${message.id}-${attachment.path}`} className="attachment-item">
                            <strong>{attachment.filename}</strong>
                            <small>{attachment.summary || attachment.content_type}</small>
                          </div>
                        ))}
                      </div>
                    ) : null}
                    <pre>{message.content}</pre>
                  </article>
                ))}
              </div>
            )}

            <form className="composer-bar" onSubmit={(event) => void sendMessage(event)}>
              {selectedImages.length ? (
                <div className="attachment-list composer-attachments">
                  {selectedImages.map((file) => (
                    <div key={`${file.name}-${file.size}`} className="attachment-item">
                      <strong>{file.name}</strong>
                      <small>{Math.round(file.size / 1024)} KB</small>
                    </div>
                  ))}
                </div>
              ) : null}
              <textarea
                value={draftMessage}
                onChange={(event) => setDraftMessage(event.target.value)}
                placeholder="描述目标、限制条件，或者附带图片一起发送"
              />
              <div className="composer-actions">
                <label className="soft-button file-picker">
                  添加图片
                  <input
                    type="file"
                    accept=".jpg,.jpeg,.png,image/jpeg,image/png"
                    multiple
                    onChange={(event) => setSelectedImages(Array.from(event.target.files ?? []))}
                  />
                </label>
                {selectedImages.length ? (
                  <button type="button" className="soft-button" onClick={() => setSelectedImages([])}>
                    清空图片
                  </button>
                ) : null}
              </div>
              <button type="submit" className="solid-button" disabled={streaming}>
                {streaming ? "处理中..." : "发送"}
              </button>
            </form>
          </div>

          <div className="trace-pane">
            <div className="section-head">
              <span>Trace</span>
              <small>{timeline.length} events</small>
            </div>
            <div className="trace-list">
              {timeline.length === 0 ? <div className="empty-mini">本轮还没有过程事件。</div> : null}
              {timeline.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className={`trace-item ${selectedTimelineId === item.id ? "active" : ""}`}
                  onClick={() => setSelectedTimelineId(item.id)}
                >
                  <span className="trace-event">{item.event}</span>
                  <strong>{buildEventSummary(item)}</strong>
                </button>
              ))}
            </div>
          </div>
        </section>
      </>
    );
  }

  function renderMemoryWorkspace() {
    return (
      <section className="workspace-grid">
        <div className="workspace-sidebar">
          <div className="section-head">
            <span>Stable Memory</span>
            <small>{Object.keys(memoryFiles).length} files</small>
          </div>
          <div className="memory-tabs">
            {Object.keys(memoryFiles).map((key) => (
              <button
                key={key}
                type="button"
                className={`memory-tab ${selectedMemoryKey === key ? "active" : ""}`}
                onClick={() => setSelectedMemoryKey(key)}
              >
                {key}
              </button>
            ))}
          </div>
        </div>
        <div className="workspace-main">
          <div className="section-head">
            <span>{selectedMemoryKey}</span>
            <small>{activeMemoryFile?.path ?? ""}</small>
          </div>
          <textarea className="editor-surface" value={memoryDraft} onChange={(event) => setMemoryDraft(event.target.value)} />
          <div className="toolbar-row">
            <button type="button" className="solid-button" onClick={() => void saveMemory()}>
              保存
            </button>
          </div>
        </div>
      </section>
    );
  }

  function renderSkillsWorkspace() {
    return (
      <section className="cards-view">
        {skills.map((skill) => (
          <article key={skill.path} className="info-card skill-card">
            <div className="pill">{skill.source}</div>
            <h3>{skill.name}</h3>
            <p>{skill.summary || "该 skill 暂无摘要。"} </p>
            <footer>
              <span>{skill.plugin_name ? `Plugin: ${skill.plugin_name}` : "Workspace Skill"}</span>
              <code>{skill.path}</code>
            </footer>
          </article>
        ))}
      </section>
    );
  }

  function renderFilesWorkspace() {
    return (
      <section className="workspace-grid">
        <div className="workspace-sidebar">
          <div className="section-head">
            <span>Workspace Files</span>
            <small>{workspacePayload?.path ?? ""}</small>
          </div>
          {workspacePayload?.type === "dir" ? (
            <div className="file-list">
              {workspacePayload.path !== "/root/newman" ? (
                <button type="button" className="file-entry back" onClick={() => void refreshWorkspace(getWorkspaceParentPath())}>
                  ..
                </button>
              ) : null}
              {workspacePayload.entries.map((entry) => (
                <button
                  key={entry.path}
                  type="button"
                  className={`file-entry ${entry.type}`}
                  onClick={() => void refreshWorkspace(entry.path)}
                >
                  <span>{entry.name}</span>
                  <small>{entry.type}</small>
                </button>
              ))}
            </div>
          ) : null}
        </div>
        <div className="workspace-main">
          {workspacePayload?.type === "file" ? (
            <>
              <div className="section-head">
                <span>{workspacePayload.path}</span>
                <small>前 20KB</small>
              </div>
              <pre className="code-surface">{workspacePayload.content}</pre>
            </>
          ) : (
            <div className="empty-mini">选择一个文件查看内容，或继续下钻目录。</div>
          )}
        </div>
      </section>
    );
  }

  function renderPluginsWorkspace() {
    return (
      <section className="cards-view">
        {pluginErrors.map((error, index) => (
          <article key={`${error.plugin_path}-${index}`} className="info-card plugin-card">
            <div className="pill pill-orange">invalid</div>
            <h3>{error.plugin_name ?? "plugin load error"}</h3>
            <p>{error.message}</p>
            <footer>
              <code>{error.plugin_path}</code>
            </footer>
          </article>
        ))}
        {plugins.map((plugin) => (
          <article key={plugin.name} className="info-card plugin-card">
            <div className={`pill ${plugin.enabled ? "pill-green" : "pill-orange"}`}>{plugin.enabled ? "enabled" : "disabled"}</div>
            <h3>{plugin.name}</h3>
            <p>{plugin.description}</p>
            <ul className="metric-list">
              <li>{plugin.skill_count} skills</li>
              <li>{plugin.hook_count} hooks</li>
              <li>{plugin.mcp_server_count} mcp servers</li>
            </ul>
            <footer>
              <code>{plugin.plugin_path}</code>
              <button type="button" className="soft-button" onClick={() => void togglePlugin(plugin)}>
                {plugin.enabled ? "停用" : "启用"}
              </button>
            </footer>
          </article>
        ))}
      </section>
    );
  }

  function renderControlWorkspace() {
    return (
      <section className="control-grid">
        <article className="info-card hero-card">
          <div className="pill pill-blue">System Health</div>
          <h3>Newman Local Control Plane</h3>
          <p>{statusNote}</p>
          <div className="metric-grid">
            <div>
              <span>Provider</span>
              <strong>{health?.provider ?? "-"}</strong>
            </div>
            <div>
              <span>Tools</span>
              <strong>{health?.tools.length ?? 0}</strong>
            </div>
            <div>
              <span>Plugins</span>
              <strong>{health?.plugins_enabled ?? 0}</strong>
            </div>
            <div>
              <span>Scheduler</span>
              <strong>{health?.scheduler_running ? "running" : "idle"}</strong>
            </div>
          </div>
          <div className="path-grid">
            {readyInfo
              ? Object.entries(readyInfo)
                  .filter(([key]) => key !== "ok")
                  .map(([key, value]) => (
                    <div key={key}>
                      <span>{key}</span>
                      <code>{String(value)}</code>
                    </div>
                  ))
              : null}
          </div>
        </article>

        <article className="info-card">
          <div className="section-head">
            <span>Knowledge</span>
            <small>{knowledgeDocuments.length} docs</small>
          </div>
          <div className="inline-form">
            <input value={knowledgeImportPath} onChange={(event) => setKnowledgeImportPath(event.target.value)} placeholder="导入路径" />
            <button type="button" className="soft-button" onClick={() => void importKnowledge()}>
              导入
            </button>
          </div>
          <div className="inline-form">
            <input
              value={knowledgeUploadFile?.name ?? ""}
              readOnly
              placeholder="上传 PDF / Word / PPT / Excel / 图片"
            />
            <label className="soft-button file-picker">
              选择文件
              <input
                type="file"
                accept=".md,.txt,.json,.csv,.py,.yaml,.yml,.log,.pdf,.docx,.pptx,.xlsx,.jpg,.jpeg,.png"
                onChange={(event) => setKnowledgeUploadFile(event.target.files?.[0] ?? null)}
              />
            </label>
            <button type="button" className="solid-button" onClick={() => void uploadKnowledgeFile()} disabled={!knowledgeUploadFile}>
              上传
            </button>
          </div>
          <div className="inline-form">
            <input value={knowledgeQuery} onChange={(event) => setKnowledgeQuery(event.target.value)} placeholder="知识搜索" />
            <button type="button" className="solid-button" onClick={() => void searchKnowledge()}>
              Search
            </button>
          </div>
          <div className="stack-list">
            {knowledgeHits.map((hit) => (
              <div key={`${hit.document_id}-${hit.line_number}`} className="stack-item">
                <strong>{hit.title}</strong>
                <p>{hit.snippet}</p>
                <small>
                  score {hit.score} · lexical {hit.lexical_score} · vector {hit.vector_score} · rerank {hit.rerank_score}
                </small>
                <small>
                  {hit.location_label ?? `line ${hit.line_number ?? "-"}`} · chunk {hit.chunk_index ?? "-"} · {hit.stored_path}
                </small>
              </div>
            ))}
          </div>
        </article>

        <article className="info-card">
          <div className="section-head">
            <span>Scheduler</span>
            <small>{schedulerTasks.length} tasks</small>
          </div>
          <div className="task-form">
            <input value={taskForm.name} onChange={(event) => setTaskForm((current) => ({ ...current, name: event.target.value }))} placeholder="任务名" />
            <input value={taskForm.cron} onChange={(event) => setTaskForm((current) => ({ ...current, cron: event.target.value }))} placeholder="Cron" />
            <textarea
              value={taskForm.prompt}
              onChange={(event) => setTaskForm((current) => ({ ...current, prompt: event.target.value }))}
              placeholder="触发时发送的 prompt"
            />
            <button type="button" className="solid-button" onClick={() => void createTask()}>
              创建任务
            </button>
          </div>
          <div className="stack-list">
            {schedulerTasks.map((task) => (
              <div key={task.task_id} className="stack-item">
                <div className="stack-head">
                  <strong>{task.name}</strong>
                  <button type="button" className="soft-button" onClick={() => void runTask(task.task_id)}>
                    立即执行
                  </button>
                </div>
                <p>{task.action.prompt}</p>
                <small>
                  {task.cron} · {task.status} · next {formatTime(task.next_run_at)}
                </small>
              </div>
            ))}
          </div>
        </article>

        <article className="info-card">
          <div className="section-head">
            <span>Channels</span>
            <small>{channelStatus.length} adapters</small>
          </div>
          <div className="stack-list">
            {channelStatus.map((channel) => (
              <div key={channel.platform} className="stack-item">
                <div className="stack-head">
                  <strong>{channel.platform}</strong>
                  <div className={`pill ${channel.enabled ? "pill-green" : "pill-orange"}`}>{channel.enabled ? "enabled" : "disabled"}</div>
                </div>
                <small>token configured: {channel.webhook_token_configured ? "yes" : "no"}</small>
              </div>
            ))}
          </div>
        </article>
      </section>
    );
  }

  return (
    <div
      className={`screen-shell ${dragging ? "is-resizing" : ""}`}
      style={{
        gridTemplateColumns: isMobile ? "1fr" : `${leftWidth}px ${HANDLE_WIDTH}px minmax(0, 1fr)`,
        ["--drawer-width" as string]: `${isMobile ? 0 : rightWidth}px`
      }}
    >
      <aside className="left-rail">
        <div className="brand">
          <div className="brand-logo" />
          <div className="brand-copy">
            <div className="eyebrow">Local-first Agent Workbench</div>
            <h1>Newman</h1>
          </div>
        </div>

        <nav className="rail-nav" aria-label="workspace nav">
          {navItems.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`rail-nav-item ${activeView === item.id ? "active" : ""}`}
              onClick={() => setActiveView(item.id)}
            >
              <span>{item.label}</span>
              <small>{item.hint}</small>
            </button>
          ))}
        </nav>

        <section className="rail-section">
          <div className="rail-section-head">
            <span>会话</span>
            <small>{sessionCountLabel}</small>
            <button type="button" className="icon-action" onClick={() => void createSession()}>
              +
            </button>
          </div>
          <div className="session-list">
            {sessions.map((session) => (
              <button
                key={session.session_id}
                type="button"
                className={`session-row ${session.session_id === activeSessionId ? "active" : ""}`}
                onClick={() => void loadSession(session.session_id)}
              >
                <strong>{session.title}</strong>
                <small>
                  {session.message_count} msgs · {formatTime(session.updated_at)}
                </small>
              </button>
            ))}
          </div>
        </section>

        <footer className="rail-footer">
          <div className="status-card">
            <span>Status</span>
            <strong>{streaming ? "Streaming" : "Idle"}</strong>
            <p>{statusNote}</p>
          </div>
        </footer>
      </aside>

      {!isMobile ? (
        <div
          className="resize-handle"
          onPointerDown={() => setDragging("left")}
          role="separator"
          aria-orientation="vertical"
          aria-label="调整左侧栏宽度"
        />
      ) : null}

      <main className="center-stage">
        {activeView === "chat" ? renderChatWorkspace() : null}
        {activeView === "memory" ? renderMemoryWorkspace() : null}
        {activeView === "skills" ? renderSkillsWorkspace() : null}
        {activeView === "files" ? renderFilesWorkspace() : null}
        {activeView === "plugins" ? renderPluginsWorkspace() : null}
        {activeView === "control" ? renderControlWorkspace() : null}
      </main>

      {!isMobile ? (
        <aside className="detail-drawer" style={{ width: rightWidth }}>
          <div className="section-head">
            <span>Evidence Drawer</span>
            <small>{selectedTimeline ? selectedTimeline.event : "session detail"}</small>
          </div>
          {selectedTimeline ? (
            <div className="drawer-scroll">
              <div className="pill pill-blue">{selectedTimeline.event}</div>
              <p className="drawer-summary">{buildEventSummary(selectedTimeline)}</p>
              {selectedTimeline.data.error_code ? <p className="drawer-summary">错误码: {String(selectedTimeline.data.error_code)}</p> : null}
              {selectedTimeline.data.risk_level ? <p className="drawer-summary">风险级别: {String(selectedTimeline.data.risk_level)}</p> : null}
              {selectedTimeline.data.recovery_class ? (
                <p className="drawer-summary">恢复类型: {String(selectedTimeline.data.recovery_class)}</p>
              ) : null}
              {selectedTimeline.data.recommended_next_step ? (
                <p className="drawer-summary">建议下一步: {String(selectedTimeline.data.recommended_next_step)}</p>
              ) : null}
              <pre className="json-surface">{JSON.stringify(selectedTimeline.data, null, 2)}</pre>
            </div>
          ) : sessionData ? (
            <div className="drawer-scroll">
              <div className="pill">Session Meta</div>
              <pre className="json-surface">{JSON.stringify(sessionData.session.metadata, null, 2)}</pre>
            </div>
          ) : (
            <div className="empty-mini">选中一条 trace 事件，这里会展示证据详情。</div>
          )}
        </aside>
      ) : null}

      {pendingApproval ? (
        <div className="approval-backdrop">
          <div className="approval-modal">
            <div className="pill pill-orange">Approval Required</div>
            <h3>{pendingApproval.tool}</h3>
            <p>{pendingApproval.reason}</p>
            <pre className="json-surface">{JSON.stringify(pendingApproval.arguments, null, 2)}</pre>
            <div className="approval-actions">
              <button type="button" className="soft-button" onClick={() => void resolveApproval(false)}>
                Reject
              </button>
              <button type="button" className="solid-button" onClick={() => void resolveApproval(true)}>
                Approve
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default App;
