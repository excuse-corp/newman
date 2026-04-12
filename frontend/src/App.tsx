import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import logo from "./assets/newman-logo.png";
import "./styles.css";

type WorkspacePage = "chat" | "memory" | "skills" | "files" | "settings";
type MemoryKey = "memory" | "user";
type TurnApprovalMode = "manual" | "auto_approve_level2";
type StatusTagTone = "blue" | "green" | "orange";

type MemoryFile = {
  path: string;
  content: string;
  updated_at?: string | null;
};

type MemoryWorkspaceResponse = {
  files: Record<string, MemoryFile>;
  latest_updated_at: string | null;
};

type PendingApproval = {
  approval_request_id: string;
  tool: string;
  arguments: Record<string, unknown>;
  reason: string;
  timeout_seconds: number;
  remaining_seconds: number;
};

type PendingApprovalResponse = {
  session_id: string;
  pending: PendingApproval | null;
};

type SessionSummaryRecord = {
  session_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
};

type SessionMessageRecord = {
  id: string;
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  created_at: string;
  metadata: Record<string, unknown>;
};

type SessionRecordDetail = {
  session_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages: SessionMessageRecord[];
  metadata: Record<string, unknown>;
};

type SessionDetailResponse = {
  session: SessionRecordDetail;
  plan?: {
    explanation?: string | null;
    current_step?: string | null;
    progress?: Record<string, number>;
    steps?: Array<{ step: string; status: string }>;
  } | null;
  context_usage?: {
    estimated_tokens: number;
    context_window: number | null;
    pressure: number | null;
    remaining_tokens: number | null;
  } | null;
};

type SessionEventPayload = {
  event: string;
  data: Record<string, unknown>;
  request_id?: string;
  ts: number;
};

type SessionEventsResponse = {
  session_id: string;
  events: SessionEventPayload[];
};

type SessionAuditResponse = {
  session_id: string;
  events: unknown[];
};

type CreateSessionResponse = {
  session_id: string;
  title: string;
  created: boolean;
};

type TraceEntry = {
  id: string;
  type: "trace" | "tool" | "skill" | "agent" | "result";
  time: string;
  text: string;
  detailTitle: string;
  summary: string;
  inputs: string[];
  citations: string[];
  tags?: Array<{ label: string; tone: StatusTagTone }>;
};

type SkillSummary = {
  name: string;
  source: string;
  plugin_name?: string | null;
  path: string;
  description: string;
  when_to_use?: string | null;
  summary: string;
};

type SkillDetail = SkillSummary & {
  content: string;
  readonly: boolean;
  available: boolean;
  tool_dependencies: string[];
  usage_limits_summary: string;
  directory_path: string;
};

type SkillsListResponse = {
  skills: SkillSummary[];
};

type SkillDetailResponse = {
  skill: SkillDetail;
};

type WorkspaceEntry = {
  name: string;
  path: string;
  type: "dir" | "file";
};

type WorkspaceDirectoryResponse = {
  path: string;
  type: "dir";
  entries: WorkspaceEntry[];
};

type WorkspaceFileResponse = {
  path: string;
  type: "file";
  content: string;
};

type WorkspaceBrowserResponse = WorkspaceDirectoryResponse | WorkspaceFileResponse;

type ChatSession = {
  id: string;
  title: string;
  updatedAt: string;
  messageCount: number;
  hasConversation: boolean;
};

type KnowledgeDocument = {
  document_id: string;
  title: string;
  source_path: string;
  stored_path: string;
  size_bytes: number;
  content_type: string;
  parser: string;
  chunk_count: number;
  page_count: number | null;
  imported_at: string;
};

type KnowledgeDocumentsResponse = {
  documents: KnowledgeDocument[];
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
  plugin_name?: string | null;
  message: string;
};

type PluginsResponse = {
  plugins: PluginRecord[];
  errors: PluginLoadError[];
};

const navItems: Array<{ id: Exclude<WorkspacePage, "settings">; label: string; hint: string }> = [
  { id: "chat", label: "Chat", hint: "对话" },
  { id: "memory", label: "Memory", hint: "记忆" },
  { id: "skills", label: "Skills", hint: "技能" },
  { id: "files", label: "Files", hint: "文件" }
];

const approvalModeMeta: Record<
  TurnApprovalMode,
  {
    label: string;
    helper: string;
  }
> = {
  auto_approve_level2: {
    label: "全部默认通过",
    helper: "本轮命中 Level 2 的工具默认放行，不再逐个弹确认。"
  },
  manual: {
    label: "逐个手动确认",
    helper: "本轮每个命中 Level 2 的工具都需要你点击确认后才继续。"
  }
};

const LEFT_MIN = 180;
const LEFT_MAX = 360;
const RIGHT_MIN = 260;
const RIGHT_MAX = 460;
const HANDLE_WIDTH = 8;

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function readStoredNumber(key: string, fallback: number, min: number, max: number) {
  const raw = window.localStorage.getItem(key);
  const parsed = raw ? Number(raw) : Number.NaN;
  if (Number.isFinite(parsed)) {
    return clamp(parsed, min, max);
  }
  return fallback;
}

function isWorkspacePage(value: string | null): value is WorkspacePage {
  return value === "chat" || value === "memory" || value === "skills" || value === "files" || value === "settings";
}

function getApiBase() {
  if (import.meta.env.VITE_API_BASE) {
    return import.meta.env.VITE_API_BASE;
  }
  return `${window.location.protocol}//${window.location.hostname}:8005`;
}

function formatDateTime(value: string | null | undefined) {
  if (!value) {
    return "暂无";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

function formatBytes(size: number) {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function extractName(path: string) {
  const segments = path.split(/[\\/]/).filter(Boolean);
  return segments[segments.length - 1] ?? path;
}

function extractParentPath(path: string, rootPath: string | null) {
  const normalized = path.endsWith("/") && path.length > 1 ? path.slice(0, -1) : path;
  if (rootPath && normalized === rootPath) {
    return rootPath;
  }
  const lastSlash = normalized.lastIndexOf("/");
  if (lastSlash <= 0) {
    return rootPath ?? ".";
  }
  return normalized.slice(0, lastSlash);
}

function formatPathLabel(path: string, rootPath: string | null) {
  if (!path) {
    return ".";
  }
  if (rootPath && path.startsWith(rootPath)) {
    const relative = path.slice(rootPath.length).replace(/^\/+/, "");
    return relative || ".";
  }
  return path;
}

function isOpenableWorkspacePath(path: string, rootPath: string | null) {
  return Boolean(path && rootPath && path.startsWith(rootPath));
}

function skillSourceLabel(skill: SkillSummary | SkillDetail) {
  if (skill.source === "workspace") {
    return "工作区";
  }
  if (skill.plugin_name) {
    return `插件 · ${skill.plugin_name}`;
  }
  return skill.source;
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const text = await response.text();
  let payload: unknown = null;

  if (text) {
    try {
      payload = JSON.parse(text) as unknown;
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    let message = `请求失败：${response.status}`;
    if (payload && typeof payload === "object" && payload !== null) {
      const detail = "detail" in payload ? payload.detail : "message" in payload ? payload.message : null;
      if (typeof detail === "string" && detail.trim()) {
        message = detail;
      }
    }
    throw new Error(message);
  }

  return payload as T;
}

function mapSessionSummary(record: SessionSummaryRecord): ChatSession {
  return {
    id: record.session_id,
    title: record.title,
    updatedAt: record.updated_at,
    messageCount: record.message_count,
    hasConversation: record.message_count > 0
  };
}

function formatEventTime(ts: number) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  }).format(new Date(ts));
}

function stringifyForPanel(value: unknown) {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  return JSON.stringify(value, null, 2);
}

function buildTraceEntry(event: SessionEventPayload, index: number): TraceEntry | null {
  const id = `${event.ts}-${index}-${event.event}`;
  const tool = typeof event.data.tool === "string" ? event.data.tool : null;
  const summary = typeof event.data.summary === "string" ? event.data.summary : null;
  const frontendMessage = typeof event.data.frontend_message === "string" ? event.data.frontend_message : null;
  const reason = typeof event.data.reason === "string" ? event.data.reason : null;
  const message = typeof event.data.message === "string" ? event.data.message : null;
  const inputs: string[] = [];
  const citations: string[] = [];
  const tags: Array<{ label: string; tone: StatusTagTone }> = [];

  if ("arguments" in event.data) {
    const rendered = stringifyForPanel(event.data.arguments);
    if (rendered) {
      inputs.push(`arguments = ${rendered}`);
    }
  }
  if ("plan" in event.data) {
    const rendered = stringifyForPanel(event.data.plan);
    if (rendered) {
      inputs.push(`plan = ${rendered}`);
    }
  }
  if ("context" in event.data) {
    const rendered = stringifyForPanel(event.data.context);
    if (rendered) {
      inputs.push(`context = ${rendered}`);
    }
  }
  if ("recommended_next_step" in event.data) {
    const rendered = stringifyForPanel(event.data.recommended_next_step);
    if (rendered) {
      citations.push(`next = ${rendered}`);
    }
  }
  if ("request_id" in event && event.request_id) {
    citations.push(`request_id = ${event.request_id}`);
  }

  switch (event.event) {
    case "tool_call_started":
      return {
        id,
        type: "tool",
        time: formatEventTime(event.ts),
        text: tool ? `正在调用 ${tool}` : "正在调用工具",
        detailTitle: tool ?? "工具调用",
        summary: reason ?? "工具开始执行。",
        inputs,
        citations
      };
    case "tool_call_finished": {
      const success = Boolean(event.data.success);
      if (success) {
        tags.push({ label: "成功", tone: "green" });
      } else {
        tags.push({ label: "失败", tone: "orange" });
      }
      return {
        id,
        type: "tool",
        time: formatEventTime(event.ts),
        text: tool ? `${tool} ${success ? "已完成" : "执行失败"}` : success ? "工具已完成" : "工具执行失败",
        detailTitle: tool ?? "工具结果",
        summary: frontendMessage ?? summary ?? (success ? "工具执行完成。" : "工具执行失败。"),
        inputs,
        citations,
        tags
      };
    }
    case "tool_error_feedback":
      tags.push({ label: "错误恢复", tone: "orange" });
      return {
        id,
        type: "tool",
        time: formatEventTime(event.ts),
        text: tool ? `${tool} 需要恢复处理` : "工具需要恢复处理",
        detailTitle: tool ?? "错误反馈",
        summary: frontendMessage ?? summary ?? "后端返回了结构化错误反馈。",
        inputs,
        citations,
        tags
      };
    case "plan_updated":
      tags.push({ label: "计划更新", tone: "blue" });
      return {
        id,
        type: "trace",
        time: formatEventTime(event.ts),
        text: "执行计划已更新",
        detailTitle: "计划更新",
        summary: summary ?? "Agent 更新了本轮任务计划。",
        inputs,
        citations,
        tags
      };
    case "hook_triggered":
      return {
        id,
        type: "skill",
        time: formatEventTime(event.ts),
        text: message ?? "插件 Hook 已触发",
        detailTitle: typeof event.data.event === "string" ? event.data.event : "Hook",
        summary: message ?? "插件 Hook 返回了一条说明信息。",
        inputs,
        citations
      };
    case "checkpoint_created":
      tags.push({ label: "Checkpoint", tone: "blue" });
      return {
        id,
        type: "trace",
        time: formatEventTime(event.ts),
        text: "上下文已压缩并创建 checkpoint",
        detailTitle: "Checkpoint",
        summary: summary ?? "上下文压力达到阈值，系统已创建 checkpoint。",
        inputs,
        citations,
        tags
      };
    case "attachment_received":
      return {
        id,
        type: "trace",
        time: formatEventTime(event.ts),
        text: "已接收附件，开始预处理",
        detailTitle: "附件接收",
        summary: "图片附件已上传，等待多模态预解析。",
        inputs,
        citations
      };
    case "attachment_processed":
      return {
        id,
        type: "trace",
        time: formatEventTime(event.ts),
        text: "附件预处理完成",
        detailTitle: "附件解析",
        summary: "多模态摘要已写入本轮上下文。",
        inputs,
        citations
      };
    case "tool_approval_request":
      tags.push({ label: "待审批", tone: "orange" });
      return {
        id,
        type: "trace",
        time: formatEventTime(event.ts),
        text: tool ? `${tool} 等待审批` : "工具等待审批",
        detailTitle: "审批请求",
        summary: reason ?? "该操作需要人工确认后继续。",
        inputs,
        citations,
        tags
      };
    case "tool_approval_resolved": {
      const approved = Boolean(event.data.approved);
      tags.push({ label: approved ? "已批准" : "已拒绝", tone: approved ? "green" : "orange" });
      return {
        id,
        type: "trace",
        time: formatEventTime(event.ts),
        text: approved ? "审批已通过" : "审批已拒绝",
        detailTitle: "审批结果",
        summary: approved ? "工具调用恢复执行。" : "工具调用已被拒绝。",
        inputs,
        citations,
        tags
      };
    }
    case "error":
      tags.push({ label: "错误", tone: "orange" });
      return {
        id,
        type: "trace",
        time: formatEventTime(event.ts),
        text: message ?? "本轮执行中断",
        detailTitle: "运行错误",
        summary: frontendMessage ?? message ?? "运行时返回错误。",
        inputs,
        citations,
        tags
      };
    default:
      return null;
  }
}

function normalizeSessionEventPayload(payload: unknown): SessionEventPayload | null {
  if (typeof payload === "string") {
    try {
      return normalizeSessionEventPayload(JSON.parse(payload) as unknown);
    } catch {
      return null;
    }
  }
  if (!payload || typeof payload !== "object") {
    return null;
  }

  const event = "event" in payload && typeof payload.event === "string" ? payload.event : null;
  const data = "data" in payload && payload.data && typeof payload.data === "object" ? payload.data : null;
  const ts = "ts" in payload && typeof payload.ts === "number" ? payload.ts : null;
  const requestId = "request_id" in payload && typeof payload.request_id === "string" ? payload.request_id : undefined;

  if (!event || !data || ts === null) {
    return null;
  }

  return {
    event,
    data: data as Record<string, unknown>,
    request_id: requestId,
    ts
  };
}

function App() {
  const apiBase = getApiBase();
  const [activePage, setActivePage] = useState<WorkspacePage>(() => {
    const stored = window.localStorage.getItem("newman-active-page");
    return isWorkspacePage(stored) ? stored : "chat";
  });
  const [chatSessions, setChatSessions] = useState<ChatSession[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [activeSessionId, setActiveSessionId] = useState(() => window.localStorage.getItem("newman-active-session-id") ?? "");
  const [activeSessionDetail, setActiveSessionDetail] = useState<SessionRecordDetail | null>(null);
  const [activeContextUsage, setActiveContextUsage] = useState<SessionDetailResponse["context_usage"]>(null);
  const [sessionEvents, setSessionEvents] = useState<SessionEventPayload[]>([]);
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [chatNotice, setChatNotice] = useState<string | null>(null);
  const [sendingMessage, setSendingMessage] = useState(false);
  const [streamingContent, setStreamingContent] = useState("");
  const [openSessionMenuId, setOpenSessionMenuId] = useState<string | null>(null);
  const [memoryFiles, setMemoryFiles] = useState<Record<MemoryKey, MemoryFile>>({
    memory: { path: "", content: "", updated_at: null },
    user: { path: "", content: "", updated_at: null }
  });
  const [memoryDrafts, setMemoryDrafts] = useState<Record<MemoryKey, string>>({
    memory: "",
    user: ""
  });
  const [memoryLatestUpdatedAt, setMemoryLatestUpdatedAt] = useState<string | null>(null);
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [memorySaving, setMemorySaving] = useState(false);
  const [memoryError, setMemoryError] = useState<string | null>(null);
  const [memorySaveNotice, setMemorySaveNotice] = useState<string | null>(null);
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [skillsError, setSkillsError] = useState<string | null>(null);
  const [selectedSkillName, setSelectedSkillName] = useState<string | null>(null);
  const [skillDetail, setSkillDetail] = useState<SkillDetail | null>(null);
  const [skillDetailLoading, setSkillDetailLoading] = useState(false);
  const [skillDraft, setSkillDraft] = useState("");
  const [skillSaveNotice, setSkillSaveNotice] = useState<string | null>(null);
  const [skillImportPath, setSkillImportPath] = useState("");
  const [skillSaving, setSkillSaving] = useState(false);
  const [skillDeleting, setSkillDeleting] = useState(false);
  const [skillImporting, setSkillImporting] = useState(false);
  const [workspacePath, setWorkspacePath] = useState(".");
  const [workspaceRootPath, setWorkspaceRootPath] = useState<string | null>(null);
  const [workspaceView, setWorkspaceView] = useState<WorkspaceBrowserResponse | null>(null);
  const [workspaceLoading, setWorkspaceLoading] = useState(false);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [knowledgeDocuments, setKnowledgeDocuments] = useState<KnowledgeDocument[]>([]);
  const [knowledgeLoading, setKnowledgeLoading] = useState(false);
  const [knowledgeError, setKnowledgeError] = useState<string | null>(null);
  const [plugins, setPlugins] = useState<PluginRecord[]>([]);
  const [pluginErrors, setPluginErrors] = useState<PluginLoadError[]>([]);
  const [pluginsLoading, setPluginsLoading] = useState(false);
  const [pluginsError, setPluginsError] = useState<string | null>(null);
  const [pluginsNotice, setPluginsNotice] = useState<string | null>(null);
  const [pluginBusyName, setPluginBusyName] = useState<string | null>(null);
  const [leftWidth, setLeftWidth] = useState(() => readStoredNumber("newman-left-rail-width", 220, LEFT_MIN, LEFT_MAX));
  const [rightWidth, setRightWidth] = useState(() =>
    readStoredNumber("newman-right-drawer-width", 320, RIGHT_MIN, RIGHT_MAX)
  );
  const [dragging, setDragging] = useState<null | "left" | "right">(null);
  const [viewportWidth, setViewportWidth] = useState(() => window.innerWidth);
  const [openDetailId, setOpenDetailId] = useState<string | null>(null);
  const [approvalMenuOpen, setApprovalMenuOpen] = useState(false);
  const [pendingApproval, setPendingApproval] = useState<PendingApproval | null>(null);
  const [approvalActionLoading, setApprovalActionLoading] = useState<null | "approve" | "reject">(null);
  const [approvalError, setApprovalError] = useState<string | null>(null);
  const [composerValue, setComposerValue] = useState("");
  const [turnApprovalMode, setTurnApprovalMode] = useState<TurnApprovalMode>("manual");
  const conversationPaneRef = useRef<HTMLElement | null>(null);
  const activeSessionIdRef = useRef(activeSessionId);

  useEffect(() => {
    activeSessionIdRef.current = activeSessionId;
  }, [activeSessionId]);

  useEffect(() => {
    window.localStorage.setItem("newman-active-page", activePage);
  }, [activePage]);

  useEffect(() => {
    if (activeSessionId) {
      window.localStorage.setItem("newman-active-session-id", activeSessionId);
      return;
    }
    window.localStorage.removeItem("newman-active-session-id");
  }, [activeSessionId]);

  useEffect(() => {
    window.localStorage.setItem("newman-left-rail-width", `${leftWidth}`);
  }, [leftWidth]);

  useEffect(() => {
    window.localStorage.setItem("newman-right-drawer-width", `${rightWidth}`);
  }, [rightWidth]);

  useEffect(() => {
    const onResize = () => setViewportWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    const handleWindowClick = () => {
      setOpenSessionMenuId(null);
      setApprovalMenuOpen(false);
    };
    window.addEventListener("click", handleWindowClick);
    return () => window.removeEventListener("click", handleWindowClick);
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

  async function loadChatSessions(signal?: AbortSignal, preferredId?: string | null) {
    setSessionsLoading(true);
    setSessionsError(null);

    try {
      const data = await fetchJson<SessionSummaryRecord[]>(`${apiBase}/api/sessions`, { signal });
      if (signal?.aborted) {
        return;
      }

      const nextSessions = data.map(mapSessionSummary);
      setChatSessions(nextSessions);

      const storedId = preferredId === undefined ? activeSessionIdRef.current : preferredId;
      if (storedId && nextSessions.some((item) => item.id === storedId)) {
        setActiveSessionId(storedId);
      } else if (!activeSessionIdRef.current && nextSessions[0]?.id) {
        setActiveSessionId(nextSessions[0].id);
      } else if (storedId && !nextSessions.some((item) => item.id === storedId)) {
        setActiveSessionId(nextSessions[0]?.id ?? "");
      }
    } catch (error) {
      if (signal?.aborted) {
        return;
      }
      setSessionsError(error instanceof Error ? error.message : "会话列表加载失败");
    } finally {
      if (!signal?.aborted) {
        setSessionsLoading(false);
      }
    }
  }

  async function loadChatWorkspace(sessionId: string, signal?: AbortSignal) {
    setChatLoading(true);
    setChatError(null);

    try {
      const detail = await fetchJson<SessionDetailResponse>(`${apiBase}/api/sessions/${encodeURIComponent(sessionId)}`, { signal });

      let nextEvents: SessionEventPayload[] = [];
      try {
        const events = await fetchJson<SessionEventsResponse>(`${apiBase}/api/sessions/${encodeURIComponent(sessionId)}/events`, { signal });
        nextEvents = events.events
          .map((event) => normalizeSessionEventPayload(event))
          .filter((event): event is SessionEventPayload => event !== null);
      } catch (eventsError) {
        if (signal?.aborted) {
          return;
        }
        try {
          const audit = await fetchJson<SessionAuditResponse>(`${apiBase}/api/audit/${encodeURIComponent(sessionId)}`, { signal });
          nextEvents = audit.events
            .map((event) => normalizeSessionEventPayload(event))
            .filter((event): event is SessionEventPayload => event !== null);
        } catch (auditError) {
          console.warn("Failed to load session events", { sessionId, eventsError, auditError });
        }
      }

      if (signal?.aborted || activeSessionIdRef.current !== sessionId) {
        return;
      }

      setActiveSessionDetail(detail.session);
      setActiveContextUsage(detail.context_usage ?? null);
      setSessionEvents(nextEvents);
      setChatSessions((currentSessions) =>
        currentSessions.map((session) =>
          session.id === sessionId
            ? {
                ...session,
                title: detail.session.title,
                updatedAt: detail.session.updated_at,
                messageCount: detail.session.messages.length,
                hasConversation: detail.session.messages.length > 0
              }
            : session
        )
      );
    } catch (error) {
      if (signal?.aborted) {
        return;
      }
      setChatError(error instanceof Error ? error.message : "会话内容加载失败");
    } finally {
      if (!signal?.aborted && activeSessionIdRef.current === sessionId) {
        setChatLoading(false);
      }
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void loadChatSessions(controller.signal);
    return () => controller.abort();
  }, [apiBase]);

  useEffect(() => {
    if (!activeSessionId) {
      setActiveSessionDetail(null);
      setActiveContextUsage(null);
      setSessionEvents([]);
      setStreamingContent("");
      setChatLoading(false);
      return;
    }

    const controller = new AbortController();
    setOpenDetailId(null);
    void loadChatWorkspace(activeSessionId, controller.signal);
    return () => controller.abort();
  }, [activeSessionId, apiBase]);

  useEffect(() => {
    if (activePage !== "chat" || !activeSessionId) {
      setPendingApproval(null);
      setApprovalError(null);
      return;
    }

    let cancelled = false;

    async function loadPendingApproval() {
      try {
        const data = await fetchJson<PendingApprovalResponse>(`${apiBase}/api/sessions/${encodeURIComponent(activeSessionId)}/pending-approval`);
        if (cancelled) return;
        setPendingApproval(data.pending);
        setApprovalError(null);
      } catch (error) {
        if (cancelled) return;
        setApprovalError(error instanceof Error ? error.message : "审批状态加载失败");
      }
    }

    void loadPendingApproval();
    const timer = window.setInterval(() => {
      void loadPendingApproval();
    }, 2500);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activePage, activeSessionId, apiBase]);

  useEffect(() => {
    if (!pendingApproval) return;

    const timer = window.setInterval(() => {
      setPendingApproval((current) => {
        if (!current) return current;
        return {
          ...current,
          remaining_seconds: Math.max(0, current.remaining_seconds - 1)
        };
      });
    }, 1000);

    return () => window.clearInterval(timer);
  }, [pendingApproval?.approval_request_id]);

  useEffect(() => {
    if (activePage !== "memory") return;

    const controller = new AbortController();

    async function loadMemoryWorkspace() {
      setMemoryLoading(true);
      setMemoryError(null);
      setMemorySaveNotice(null);

      try {
        const data = await fetchJson<MemoryWorkspaceResponse>(`${apiBase}/api/workspace/memory`, {
          signal: controller.signal
        });
        if (controller.signal.aborted) return;

        const nextFiles = {
          memory: data.files.memory ?? { path: "", content: "", updated_at: null },
          user: data.files.user ?? { path: "", content: "", updated_at: null }
        };

        setMemoryFiles(nextFiles);
        setMemoryDrafts({
          memory: nextFiles.memory.content,
          user: nextFiles.user.content
        });
        setMemoryLatestUpdatedAt(data.latest_updated_at);
      } catch (error) {
        if (controller.signal.aborted) return;
        setMemoryError(error instanceof Error ? error.message : "Memory 加载失败");
      } finally {
        if (!controller.signal.aborted) {
          setMemoryLoading(false);
        }
      }
    }

    void loadMemoryWorkspace();

    return () => controller.abort();
  }, [activePage, apiBase]);

  useEffect(() => {
    if (activePage !== "chat") return;
    if (!activeSessionDetail || activeSessionDetail.messages.length === 0) return;

    const frame = window.requestAnimationFrame(() => {
      const pane = conversationPaneRef.current;
      if (!pane) return;
      pane.scrollTo({
        top: pane.scrollHeight,
        behavior: "smooth"
      });
    });

    return () => window.cancelAnimationFrame(frame);
  }, [activePage, activeSessionId, activeSessionDetail, streamingContent, sessionEvents.length]);

  async function loadSkillsWorkspace(signal?: AbortSignal, preferredName?: string | null) {
    setSkillsLoading(true);
    setSkillsError(null);

    try {
      const data = await fetchJson<SkillsListResponse>(`${apiBase}/api/skills`, { signal });
      if (signal?.aborted) return;

      setSkills(data.skills);
      const currentName = preferredName === undefined ? selectedSkillName : preferredName;
      const matched = currentName && data.skills.some((item) => item.name === currentName);
      const nextSelectedName = matched ? currentName : data.skills[0]?.name ?? null;
      setSelectedSkillName(nextSelectedName);
      if (!nextSelectedName) {
        setSkillDetail(null);
        setSkillDraft("");
      }
    } catch (error) {
      if (signal?.aborted) return;
      setSkillsError(error instanceof Error ? error.message : "Skills 加载失败");
    } finally {
      if (!signal?.aborted) {
        setSkillsLoading(false);
      }
    }
  }

  useEffect(() => {
    if (activePage !== "skills") return;

    const controller = new AbortController();
    void loadSkillsWorkspace(controller.signal);
    return () => controller.abort();
  }, [activePage, apiBase]);

  useEffect(() => {
    const skillName = selectedSkillName ?? "";
    if (activePage !== "skills" || !skillName) return;

    const controller = new AbortController();

    async function loadSkillDetail() {
      setSkillDetailLoading(true);
      setSkillsError(null);

      try {
        const data = await fetchJson<SkillDetailResponse>(`${apiBase}/api/skills/${encodeURIComponent(skillName)}`, {
          signal: controller.signal
        });
        if (controller.signal.aborted) return;
        setSkillDetail(data.skill);
        setSkillDraft(data.skill.content);
      } catch (error) {
        if (controller.signal.aborted) return;
        setSkillsError(error instanceof Error ? error.message : "Skill 详情加载失败");
      } finally {
        if (!controller.signal.aborted) {
          setSkillDetailLoading(false);
        }
      }
    }

    void loadSkillDetail();

    return () => controller.abort();
  }, [activePage, selectedSkillName, apiBase]);

  async function loadWorkspaceBrowser(targetPath: string, signal?: AbortSignal) {
    setWorkspaceLoading(true);
    setWorkspaceError(null);

    try {
      const url = new URL(`${apiBase}/api/workspace/files`);
      url.searchParams.set("path", targetPath);
      const data = await fetchJson<WorkspaceBrowserResponse>(url.toString(), { signal });
      if (signal?.aborted) return;

      setWorkspaceView(data);
      setWorkspacePath(targetPath);
      if (targetPath === "." || !workspaceRootPath) {
        setWorkspaceRootPath((current) => current ?? data.path);
      }
    } catch (error) {
      if (signal?.aborted) return;
      setWorkspaceError(error instanceof Error ? error.message : "工作区加载失败");
    } finally {
      if (!signal?.aborted) {
        setWorkspaceLoading(false);
      }
    }
  }

  async function loadKnowledgeDocuments(signal?: AbortSignal) {
    setKnowledgeLoading(true);
    setKnowledgeError(null);

    try {
      const data = await fetchJson<KnowledgeDocumentsResponse>(`${apiBase}/api/knowledge/documents`, { signal });
      if (signal?.aborted) return;
      setKnowledgeDocuments(data.documents);
    } catch (error) {
      if (signal?.aborted) return;
      setKnowledgeError(error instanceof Error ? error.message : "资料列表加载失败");
    } finally {
      if (!signal?.aborted) {
        setKnowledgeLoading(false);
      }
    }
  }

  useEffect(() => {
    if (activePage !== "files") return;

    const controller = new AbortController();
    void loadWorkspaceBrowser(workspacePath, controller.signal);
    return () => controller.abort();
  }, [activePage, apiBase, workspacePath]);

  useEffect(() => {
    if (activePage !== "files") return;

    const controller = new AbortController();
    void loadKnowledgeDocuments(controller.signal);
    return () => controller.abort();
  }, [activePage, apiBase]);

  async function loadPluginsWorkspace(signal?: AbortSignal) {
    setPluginsLoading(true);
    setPluginsError(null);

    try {
      const data = await fetchJson<PluginsResponse>(`${apiBase}/api/plugins`, { signal });
      if (signal?.aborted) return;
      setPlugins(data.plugins);
      setPluginErrors(data.errors);
    } catch (error) {
      if (signal?.aborted) return;
      setPluginsError(error instanceof Error ? error.message : "插件列表加载失败");
    } finally {
      if (!signal?.aborted) {
        setPluginsLoading(false);
      }
    }
  }

  useEffect(() => {
    if (activePage !== "settings") return;

    const controller = new AbortController();
    void loadPluginsWorkspace(controller.signal);
    return () => controller.abort();
  }, [activePage, apiBase]);

  const isMobile = viewportWidth <= 820;
  const activeSession = chatSessions.find((session) => session.id === activeSessionId) ?? null;
  const visibleMessages =
    activeSessionDetail?.messages.filter((message) => message.role === "user" || message.role === "assistant") ?? [];
  const traceEntries = sessionEvents
    .map((event, index) => buildTraceEntry(event, index))
    .filter((entry): entry is TraceEntry => entry !== null);
  const selectedDetail =
    activePage === "chat"
      ? traceEntries.find((entry) => entry.id === openDetailId) ??
        (openDetailId?.startsWith("assistant:")
          ? (() => {
              const assistantId = openDetailId.slice("assistant:".length);
              const assistantMessage = visibleMessages.find((message) => message.id === assistantId && message.role === "assistant");
              if (!assistantMessage) {
                return null;
              }
              return {
                id: openDetailId,
                type: "result" as const,
                time: formatDateTime(assistantMessage.created_at),
                text: assistantMessage.content,
                detailTitle: "最终回答",
                summary: assistantMessage.content,
                inputs: [],
                citations: []
              };
            })()
          : null)
      : null;
  const showEmptyChatState =
    activePage === "chat" &&
    !chatLoading &&
    !sendingMessage &&
    visibleMessages.length === 0 &&
    !streamingContent.trim();
  const contextPressure = activeContextUsage?.pressure ?? null;
  const contextProgress = contextPressure === null ? null : Math.min(Math.max(contextPressure, 0), 1);
  const contextPercent = contextPressure === null ? null : Math.max(0, Math.round(contextPressure * 100));
  const contextRingProgress = contextProgress ?? 0;
  const activeApprovalMode = approvalModeMeta[turnApprovalMode];
  const hasMemoryChanges =
    memoryDrafts.memory !== memoryFiles.memory.content || memoryDrafts.user !== memoryFiles.user.content;
  const hasSkillChanges = Boolean(skillDetail && skillDraft !== skillDetail.content);
  const currentWorkspaceLabel = workspaceView ? formatPathLabel(workspaceView.path, workspaceRootPath) : ".";
  const isWorkspaceRoot = Boolean(workspaceView && workspaceRootPath && workspaceView.path === workspaceRootPath);
  const latestTraceEntries = traceEntries.slice(-12);

  const switchPage = (nextPage: WorkspacePage) => {
    setActivePage(nextPage);
    setOpenSessionMenuId(null);
    setApprovalMenuOpen(false);
    if (nextPage !== "chat") {
      setOpenDetailId(null);
    }
  };

  async function ensureSession() {
    if (activeSessionId) {
      return activeSessionId;
    }

    const data = await fetchJson<CreateSessionResponse>(`${apiBase}/api/sessions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({})
    });
    const nextSession = {
      id: data.session_id,
      title: data.title,
      updatedAt: new Date().toISOString(),
      messageCount: 0,
      hasConversation: false
    };
    setChatSessions((currentSessions) => [nextSession, ...currentSessions]);
    setActiveSessionId(data.session_id);
    return data.session_id;
  }

  async function consumeSseStream(response: Response, onEvent: (payload: SessionEventPayload) => void) {
    if (!response.body) {
      throw new Error("消息流为空");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop() ?? "";

      for (const chunk of chunks) {
        const dataLines = chunk
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trim())
          .filter(Boolean);

        if (dataLines.length === 0) {
          continue;
        }

        const payload = JSON.parse(dataLines.join("\n")) as SessionEventPayload;
        onEvent(payload);
      }

      if (done) {
        break;
      }
    }
  }

  const submitComposer = async () => {
    const trimmed = composerValue.trim();
    if (!trimmed || sendingMessage) return;

    setChatError(null);
    setChatNotice(null);
    setSendingMessage(true);

    try {
      const sessionId = await ensureSession();
      const optimisticUserMessage: SessionMessageRecord = {
        id: `local-user-${Date.now()}`,
        role: "user",
        content: trimmed,
        created_at: new Date().toISOString(),
        metadata: { approval_mode: turnApprovalMode }
      };

      if (activeSessionIdRef.current === sessionId) {
        setActiveSessionDetail((currentDetail) => {
          if (!currentDetail || currentDetail.session_id !== sessionId) {
            return {
              session_id: sessionId,
              title: activeSession?.title ?? "未命名会话",
              created_at: optimisticUserMessage.created_at,
              updated_at: optimisticUserMessage.created_at,
              messages: [optimisticUserMessage],
              metadata: {}
            };
          }
          return {
            ...currentDetail,
            updated_at: optimisticUserMessage.created_at,
            messages: [...currentDetail.messages, optimisticUserMessage]
          };
        });
        setStreamingContent("");
      }

      setChatSessions((currentSessions) =>
        currentSessions.map((session) =>
          session.id === sessionId
            ? {
                ...session,
                hasConversation: true,
                messageCount: Math.max(1, session.messageCount),
                updatedAt: optimisticUserMessage.created_at
              }
            : session
        )
      );
      setComposerValue("");
      switchPage("chat");

      const response = await fetch(`${apiBase}/api/sessions/${encodeURIComponent(sessionId)}/messages`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          content: trimmed,
          approval_mode: turnApprovalMode
        })
      });

      if (!response.ok) {
        const message = await response.text();
        throw new Error(message || `请求失败：${response.status}`);
      }

      await consumeSseStream(response, (payload) => {
        if (activeSessionIdRef.current !== sessionId) {
          return;
        }

        setSessionEvents((currentEvents) => [...currentEvents, payload]);

        if (payload.event === "assistant_delta") {
          setStreamingContent(typeof payload.data.content === "string" ? payload.data.content : "");
        }

        if (payload.event === "final_response") {
          setStreamingContent(typeof payload.data.content === "string" ? payload.data.content : "");
        }

        if (payload.event === "error") {
          setChatError(typeof payload.data.message === "string" ? payload.data.message : "消息流执行失败");
        }
      });

      await loadChatSessions(undefined, sessionId);
      await loadChatWorkspace(sessionId);
      setStreamingContent("");
    } catch (error) {
      setChatError(error instanceof Error ? error.message : "发送消息失败");
    } finally {
      setSendingMessage(false);
    }
  };

  const resolveApproval = async (action: "approve" | "reject") => {
    if (!pendingApproval) return;

    setApprovalActionLoading(action);
    setApprovalError(null);

    try {
      await fetchJson<{ approved: boolean }>(`${apiBase}/api/sessions/${encodeURIComponent(activeSessionId)}/${action}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ approval_request_id: pendingApproval.approval_request_id })
      });
      setPendingApproval(null);
    } catch (error) {
      setApprovalError(error instanceof Error ? error.message : "审批操作失败");
    } finally {
      setApprovalActionLoading(null);
    }
  };

  const handleComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey) {
      return;
    }
    event.preventDefault();
    void submitComposer();
  };

  const toggleDetail = (id: string) => {
    if (openDetailId === id) {
      setOpenDetailId(null);
      return;
    }
    setOpenDetailId(id);
  };

  const toggleSessionMenu = (sessionId: string) => {
    setOpenSessionMenuId((currentId) => (currentId === sessionId ? null : sessionId));
  };

  const createDraftSession = async () => {
    setSessionsError(null);
    setChatNotice(null);

    try {
      const data = await fetchJson<CreateSessionResponse>(`${apiBase}/api/sessions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({})
      });
      await loadChatSessions(undefined, data.session_id);
      setActiveSessionId(data.session_id);
      switchPage("chat");
    } catch (error) {
      setSessionsError(error instanceof Error ? error.message : "新建会话失败");
    }
  };

  const renameSession = async (sessionId: string) => {
    const target = chatSessions.find((session) => session.id === sessionId);
    const nextTitle = window.prompt("请输入新的会话标题", target?.title ?? "");
    if (!nextTitle || !nextTitle.trim()) {
      setOpenSessionMenuId(null);
      return;
    }

    try {
      const data = await fetchJson<{ updated: boolean; title: string; updated_at: string }>(
        `${apiBase}/api/sessions/${encodeURIComponent(sessionId)}`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({ title: nextTitle.trim() })
        }
      );
      setChatSessions((currentSessions) =>
        currentSessions.map((session) =>
          session.id === sessionId ? { ...session, title: data.title, updatedAt: data.updated_at } : session
        )
      );
      if (activeSessionDetail?.session_id === sessionId) {
        setActiveSessionDetail({ ...activeSessionDetail, title: data.title, updated_at: data.updated_at });
      }
    } catch (error) {
      setSessionsError(error instanceof Error ? error.message : "会话重命名失败");
    }
    setOpenSessionMenuId(null);
  };

  const deleteSession = async (sessionId: string) => {
    if (!window.confirm("确认删除这个会话吗？")) {
      setOpenSessionMenuId(null);
      return;
    }

    try {
      await fetchJson<{ deleted: boolean }>(`${apiBase}/api/sessions/${encodeURIComponent(sessionId)}`, {
        method: "DELETE"
      });
    } catch (error) {
      setSessionsError(error instanceof Error ? error.message : "会话删除失败");
      setOpenSessionMenuId(null);
      return;
    }

    const nextSessions = chatSessions.filter((session) => session.id !== sessionId);
    setChatSessions(nextSessions);
    if (activeSessionId === sessionId) {
      setActiveSessionId(nextSessions[0]?.id ?? "");
      if (nextSessions.length === 0) {
        setActiveSessionDetail(null);
        setSessionEvents([]);
      }
    }
    setOpenSessionMenuId(null);
  };

  const updateMemoryDraft = (key: MemoryKey, value: string) => {
    setMemoryDrafts((currentDrafts) => ({
      ...currentDrafts,
      [key]: value
    }));
    setMemorySaveNotice(null);
  };

  const saveMemoryFiles = async () => {
    setMemorySaving(true);
    setMemoryError(null);
    setMemorySaveNotice(null);

    try {
      const responses = await Promise.all(
        (["memory", "user"] as MemoryKey[]).map((key) =>
          fetchJson<{ updated_at: string | null }>(`${apiBase}/api/workspace/memory/${key}`, {
            method: "PUT",
            headers: {
              "Content-Type": "application/json"
            },
            body: JSON.stringify({ content: memoryDrafts[key] })
          })
        )
      );

      setMemoryFiles((currentFiles) => ({
        memory: { ...currentFiles.memory, content: memoryDrafts.memory, updated_at: responses[0].updated_at },
        user: { ...currentFiles.user, content: memoryDrafts.user, updated_at: responses[1].updated_at }
      }));
      setMemoryLatestUpdatedAt(responses[0].updated_at ?? responses[1].updated_at ?? new Date().toISOString());
      setMemorySaveNotice("已保存到 MEMORY.md 和 USER.md");
    } catch (error) {
      setMemoryError(error instanceof Error ? error.message : "Memory 保存失败");
    } finally {
      setMemorySaving(false);
    }
  };

  const saveSelectedSkill = async () => {
    if (!skillDetail || skillDetail.readonly) return;

    setSkillSaving(true);
    setSkillsError(null);
    setSkillSaveNotice(null);

    try {
      const data = await fetchJson<SkillDetailResponse>(`${apiBase}/api/skills/${encodeURIComponent(skillDetail.name)}`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ content: skillDraft })
      });

      setSkillDetail(data.skill);
      setSkillDraft(data.skill.content);
      setSkillSaveNotice("Skill 已保存，后续会话可使用最新说明。");
      await loadSkillsWorkspace(undefined, data.skill.name);
    } catch (error) {
      setSkillsError(error instanceof Error ? error.message : "Skill 保存失败");
    } finally {
      setSkillSaving(false);
    }
  };

  const importSkill = async () => {
    const trimmed = skillImportPath.trim();
    if (!trimmed) return;

    setSkillImporting(true);
    setSkillsError(null);
    setSkillSaveNotice(null);

    try {
      const data = await fetchJson<SkillDetailResponse>(`${apiBase}/api/skills/import`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ source_path: trimmed })
      });
      setSkillImportPath("");
      setSkillSaveNotice(`已导入 ${data.skill.name}`);
      await loadSkillsWorkspace(undefined, data.skill.name);
    } catch (error) {
      setSkillsError(error instanceof Error ? error.message : "Skill 导入失败");
    } finally {
      setSkillImporting(false);
    }
  };

  const deleteSelectedSkill = async () => {
    if (!skillDetail || skillDetail.readonly) return;
    if (!window.confirm(`确认删除 Skill「${skillDetail.name}」吗？`)) {
      return;
    }

    setSkillDeleting(true);
    setSkillsError(null);
    setSkillSaveNotice(null);

    try {
      await fetchJson<{ deleted: boolean }>(`${apiBase}/api/skills/${encodeURIComponent(skillDetail.name)}`, {
        method: "DELETE"
      });
      setSkillDetail(null);
      setSkillDraft("");
      setSkillSaveNotice(`已删除 ${skillDetail.name}`);
      await loadSkillsWorkspace();
    } catch (error) {
      setSkillsError(error instanceof Error ? error.message : "Skill 删除失败");
    } finally {
      setSkillDeleting(false);
    }
  };

  const refreshFilesWorkspace = async () => {
    await Promise.all([loadWorkspaceBrowser(workspacePath), loadKnowledgeDocuments()]);
  };

  const togglePluginEnabled = async (plugin: PluginRecord) => {
    setPluginBusyName(plugin.name);
    setPluginsError(null);
    setPluginsNotice(null);

    try {
      const endpoint = plugin.enabled ? "disable" : "enable";
      await fetchJson<{ plugin: PluginRecord }>(`${apiBase}/api/plugins/${encodeURIComponent(plugin.name)}/${endpoint}`, {
        method: "POST"
      });
      setPlugins((currentPlugins) =>
        currentPlugins.map((item) => (item.name === plugin.name ? { ...item, enabled: !item.enabled } : item))
      );
      setPluginsNotice(plugin.enabled ? `已停用 ${plugin.name}` : `已启用 ${plugin.name}`);
    } catch (error) {
      setPluginsError(error instanceof Error ? error.message : "插件切换失败");
    } finally {
      setPluginBusyName(null);
    }
  };

  const rescanPlugins = async () => {
    setPluginsLoading(true);
    setPluginsError(null);
    setPluginsNotice(null);

    try {
      const data = await fetchJson<PluginsResponse>(`${apiBase}/api/plugins/rescan`, {
        method: "POST"
      });
      setPlugins(data.plugins);
      setPluginErrors(data.errors);
      setPluginsNotice("插件目录已重新扫描");
    } catch (error) {
      setPluginsError(error instanceof Error ? error.message : "插件重扫失败");
    } finally {
      setPluginsLoading(false);
    }
  };

  const renderChatComposer = (variant: "footer" | "hero") => {
    const isHero = variant === "hero";
    const shellClassName = variant === "hero" ? "composer-shell composer-shell-hero" : "composer-shell composer-shell-footer";
    const inputClassName = variant === "hero" ? "composer-input composer-input-hero" : "composer-input";

    return (
      <div className={`composer-main ${variant === "hero" ? "composer-main-hero" : ""}`}>
        <div className={shellClassName}>
          {!isHero && activePage === "chat" && pendingApproval ? (
            <div className="approval-popover" role="dialog" aria-modal="true" aria-labelledby="approval-modal-title">
              <div className="approval-popover-frame">
                <div className="approval-popover-summary">
                  <div className="approval-popover-titlebar">
                    <div>
                      <p className="approval-popover-eyebrow">待确认工具操作</p>
                      <h3 id="approval-modal-title">{pendingApproval.tool}</h3>
                    </div>
                    <div className="approval-popover-countdown">
                      <span>{pendingApproval.remaining_seconds}s</span>
                    </div>
                  </div>

                  <p className="approval-popover-copy">{pendingApproval.reason || "这一步需要你确认后我才能继续"}</p>
                </div>

                <div className="approval-popover-details">
                  <div className="approval-popover-detail">
                    <span className="approval-popover-label">本轮策略</span>
                    <p>{activeApprovalMode.label}</p>
                  </div>
                  <div className="approval-popover-detail">
                    <span className="approval-popover-label">超时处理</span>
                    <p>{pendingApproval.timeout_seconds}s 后自动拒绝</p>
                  </div>
                </div>

                <div className="approval-popover-arguments-wrap">
                  <span className="approval-popover-label">参数预览</span>
                  <pre className="approval-popover-arguments">{JSON.stringify(pendingApproval.arguments, null, 2)}</pre>
                </div>

                {approvalError ? <div className="workspace-alert error">{approvalError}</div> : null}

                <div className="approval-popover-actions">
                  <button
                    type="button"
                    className="approval-popover-button ghost"
                    onClick={() => void resolveApproval("reject")}
                    disabled={approvalActionLoading !== null}
                  >
                    {approvalActionLoading === "reject" ? "拒绝中..." : "拒绝"}
                  </button>
                  <button
                    type="button"
                    className="approval-popover-button solid"
                    onClick={() => void resolveApproval("approve")}
                    disabled={approvalActionLoading !== null}
                  >
                    {approvalActionLoading === "approve" ? "允许中..." : "允许继续"}
                  </button>
                </div>
              </div>
            </div>
          ) : null}

          <textarea
            className={inputClassName}
            value={composerValue}
            onChange={(event) => setComposerValue(event.target.value)}
            onKeyDown={handleComposerKeyDown}
            aria-label="message composer"
            placeholder={sendingMessage ? "当前正在执行，稍等这一轮完成…" : "输入你的任务，按 Enter 发送；Shift + Enter 换行"}
            rows={3}
            disabled={sendingMessage}
          />

          <div className="composer-subbar">
            <div className="composer-subbar-left">
              <button type="button" className="attach-trigger" aria-label="添加附件">
                +
              </button>

              {!isHero ? (
                <div
                  className={`approval-mini approval-mini-inline ${approvalMenuOpen ? "open" : ""}`}
                  onClick={(event) => event.stopPropagation()}
                >
                  <button
                    type="button"
                    className="approval-mini-trigger"
                    title={activeApprovalMode.helper}
                    aria-haspopup="menu"
                    aria-expanded={approvalMenuOpen}
                    aria-label="选择本轮审批策略"
                    onClick={() => setApprovalMenuOpen((current) => !current)}
                  >
                    <span className="approval-mini-value">{activeApprovalMode.label}</span>
                    <span className="approval-mini-caret" aria-hidden="true" />
                  </button>

                  {approvalMenuOpen ? (
                    <div className="approval-mini-menu" role="menu">
                      {(Object.entries(approvalModeMeta) as Array<[TurnApprovalMode, (typeof approvalModeMeta)[TurnApprovalMode]]>).map(
                        ([mode, meta]) => (
                          <button
                            key={mode}
                            type="button"
                            className={`approval-mini-option ${turnApprovalMode === mode ? "active" : ""}`}
                            role="menuitemradio"
                            aria-checked={turnApprovalMode === mode}
                            onClick={() => {
                              setTurnApprovalMode(mode);
                              setApprovalMenuOpen(false);
                            }}
                          >
                            <span className="approval-mini-option-copy">{meta.label}</span>
                            <span className="approval-mini-option-check" aria-hidden="true">
                              {turnApprovalMode === mode ? "✓" : ""}
                            </span>
                          </button>
                        )
                      )}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>

            <div className="composer-subbar-right">
              <div
                className={`context-ring ${contextProgress === null ? "is-empty" : ""}`}
                style={{ ["--context-progress" as string]: String(contextRingProgress) }}
                aria-label={contextPercent === null ? "Context 使用率暂不可用" : `Context 使用率 ${contextPercent}%`}
                title={
                  contextPercent === null
                    ? "当前还没有可用的上下文使用量数据"
                    : activeContextUsage?.context_window
                      ? `Context 使用率 ${contextPercent}% (${activeContextUsage.estimated_tokens}/${activeContextUsage.context_window} tokens)`
                      : `已估算 ${activeContextUsage?.estimated_tokens ?? 0} tokens`
                }
              >
                <span>{contextPercent === null ? "--" : `${contextPercent}%`}</span>
              </div>

              <button
                type="button"
                className="send-trigger send-trigger-inline"
                onClick={() => void submitComposer()}
                disabled={!composerValue.trim() || sendingMessage}
                aria-label="发送"
              >
                <svg viewBox="0 0 20 20" aria-hidden="true">
                  <path
                    d="M5.25 14.75 14.75 5.25M7 5.25h7.75V13"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div
      className={`screen-shell ${dragging ? "is-resizing" : ""}`}
      style={{
        gridTemplateColumns: isMobile ? "1fr" : `${leftWidth}px ${HANDLE_WIDTH}px minmax(0, 1fr)`,
        ["--drawer-width" as string]: `${rightWidth}px`
      }}
    >
      <aside className="left-rail">
        <div className="brand">
          <div className="brand-logo">
            <img src={logo} alt="Newman logo" className="brand-logo-image" />
          </div>
          <div className="brand-copy">
            <h1>Newman</h1>
          </div>
        </div>

        <nav className="rail-nav" aria-label="workspace nav">
          {navItems.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`rail-nav-item ${activePage === item.id ? "active" : ""}`}
              onClick={() => switchPage(item.id)}
              aria-current={activePage === item.id ? "page" : undefined}
            >
              <span>{item.label}</span>
              <small>{item.hint}</small>
            </button>
          ))}
        </nav>

        <section className="rail-section">
          <div className="rail-section-head">
            <span>会话</span>
            <button type="button" className="icon-action" aria-label="新建会话" onClick={() => void createDraftSession()}>
              +
            </button>
          </div>

          {sessionsError ? <div className="workspace-alert error">{sessionsError}</div> : null}
          {sessionsLoading && chatSessions.length === 0 ? <div className="workspace-empty">正在加载会话...</div> : null}

          <div className="session-list">
            {!sessionsLoading && chatSessions.length === 0 ? <div className="workspace-empty">当前还没有会话，点击右上角开始。</div> : null}
            {chatSessions.map((session) => (
              <div
                key={session.id}
                className={`session-row ${activeSessionId === session.id ? "active" : ""} ${
                  openSessionMenuId === session.id ? "menu-open" : ""
                }`}
              >
                <button
                  type="button"
                  className="session-main"
                  onClick={() => {
                    setActiveSessionId(session.id);
                    setOpenSessionMenuId(null);
                    switchPage("chat");
                  }}
                  aria-current={activeSessionId === session.id && activePage === "chat" ? "page" : undefined}
                >
                  <span className="session-title">{session.title}</span>
                </button>

                <div className="session-actions">
                  <button
                    type="button"
                    className="session-more"
                    aria-label={`${session.title} 更多操作`}
                    aria-expanded={openSessionMenuId === session.id}
                    onClick={(event) => {
                      event.stopPropagation();
                      toggleSessionMenu(session.id);
                    }}
                  >
                    <span />
                    <span />
                    <span />
                  </button>

                  {openSessionMenuId === session.id ? (
                    <div className="session-menu" role="menu" onClick={(event) => event.stopPropagation()}>
                      <button
                        type="button"
                        className="session-menu-item"
                        role="menuitem"
                        onClick={() => void renameSession(session.id)}
                      >
                        <svg viewBox="0 0 24 24" aria-hidden="true">
                          <path
                            d="M4 20h4.5L19 9.5 14.5 5 4 15.5V20Zm2-2v-1.67l8.5-8.5 1.67 1.67-8.5 8.5H6ZM18.71 7.79l-2.5-2.5 1.09-1.08a1.5 1.5 0 0 1 2.12 0l1.37 1.37a1.5 1.5 0 0 1 0 2.12l-1.08 1.09Z"
                            fill="currentColor"
                          />
                        </svg>
                        <span>重命名</span>
                      </button>
                      <button
                        type="button"
                        className="session-menu-item danger"
                        role="menuitem"
                        onClick={() => void deleteSession(session.id)}
                      >
                        <svg viewBox="0 0 24 24" aria-hidden="true">
                          <path
                            d="M9 3h6l1 2h4v2H4V5h4l1-2Zm1 6h2v8h-2V9Zm4 0h2v8h-2V9ZM7 9h2v8H7V9Zm-1 12a2 2 0 0 1-2-2V8h16v11a2 2 0 0 1-2 2H6Z"
                            fill="currentColor"
                          />
                        </svg>
                        <span>删除</span>
                      </button>
                    </div>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </section>

        <footer className="rail-footer">
          <button
            type="button"
            className={`settings-trigger ${activePage === "settings" ? "active" : ""}`}
            onClick={() => switchPage("settings")}
          >
            Settings &amp; Plugins
          </button>
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
        {activePage === "memory" ? (
          <section className="memory-workspace">
            <div className="memory-workspace-head">
              <div>
                <p className="memory-eyebrow">Memory Workspace</p>
                <h2>直接编辑 `MEMORY.md` 和 `USER.md`</h2>
              </div>
              <div className="memory-head-actions">
                <span className="memory-save-notice">最近更新 {formatDateTime(memoryLatestUpdatedAt)}</span>
                {memorySaveNotice ? <span className="memory-save-notice">{memorySaveNotice}</span> : null}
                <button
                  type="button"
                  className="memory-save-button"
                  onClick={() => void saveMemoryFiles()}
                  disabled={memoryLoading || memorySaving || !hasMemoryChanges}
                >
                  {memorySaving ? "保存中..." : "保存修改"}
                </button>
              </div>
            </div>

            {memoryError ? <div className="memory-alert error">{memoryError}</div> : null}
            {memoryLoading ? <div className="memory-loading-card">正在加载 Memory 文件...</div> : null}

            {!memoryLoading ? (
              <div className="memory-editor-grid">
                <article className="memory-editor-card">
                  <div className="memory-editor-head">
                    <div>
                      <h3>MEMORY.md</h3>
                      <p>{memoryFiles.memory.path || "/api/workspace/memory/memory"}</p>
                    </div>
                    <span className="workspace-tiny-note">更新时间 {formatDateTime(memoryFiles.memory.updated_at)}</span>
                  </div>
                  <textarea
                    className="memory-editor-input"
                    value={memoryDrafts.memory}
                    onChange={(event) => updateMemoryDraft("memory", event.target.value)}
                    spellCheck={false}
                  />
                </article>

                <article className="memory-editor-card">
                  <div className="memory-editor-head">
                    <div>
                      <h3>USER.md</h3>
                      <p>{memoryFiles.user.path || "/api/workspace/memory/user"}</p>
                    </div>
                    <span className="workspace-tiny-note">更新时间 {formatDateTime(memoryFiles.user.updated_at)}</span>
                  </div>
                  <textarea
                    className="memory-editor-input"
                    value={memoryDrafts.user}
                    onChange={(event) => updateMemoryDraft("user", event.target.value)}
                    spellCheck={false}
                  />
                </article>
              </div>
            ) : null}
          </section>
        ) : null}

        {activePage === "chat" ? (
          <>
            <section
              ref={conversationPaneRef}
              className={`conversation-pane ${showEmptyChatState ? "conversation-pane-empty" : ""}`}
            >
              {showEmptyChatState ? (
                <div className="chat-empty-state">
                  <div className="chat-empty-brand">
                    <div className="chat-empty-brand-mark">
                      <img src={logo} alt="Newman logo" className="chat-empty-brand-image" />
                    </div>
                    <div className="chat-empty-brand-copy">
                      <h2>
                        <span className="chat-empty-brand-name">Newman</span>
                        <span className="chat-empty-brand-for">for</span>
                        <span className="chat-empty-brand-cn">牛马</span>
                      </h2>
                    </div>
                  </div>

                  {renderChatComposer("hero")}
                </div>
              ) : (
                <>
                  {chatError ? <div className="workspace-alert error">{chatError}</div> : null}
                  {chatNotice ? <div className="workspace-alert success">{chatNotice}</div> : null}
                  {chatLoading ? <div className="workspace-empty">正在加载会话内容...</div> : null}

                  {!chatLoading && visibleMessages.length === 0 && latestTraceEntries.length === 0 && !streamingContent ? (
                    <div className="workspace-empty">这个会话还没有内容，直接开始提需求就行。</div>
                  ) : null}

                  {!chatLoading ? (
                    <>
                      {visibleMessages.map((message) =>
                        message.role === "user" ? (
                          <div key={message.id}>
                            <div className="user-row">
                              <div className="user-bubble">
                                <p>{message.content}</p>
                              </div>
                            </div>
                          </div>
                        ) : (
                          <div key={message.id}>
                            <div className="trace-row">
                              <button
                                type="button"
                                className={`trace-bubble wide final clickable ${
                                  openDetailId === `assistant:${message.id}` ? "active" : ""
                                }`}
                                onClick={() => toggleDetail(`assistant:${message.id}`)}
                              >
                                <p className="trace-copy">{message.content}</p>
                              </button>
                            </div>
                          </div>
                        )
                      )}

                      {latestTraceEntries.length > 0 ? (
                        <div className="trace-column">
                          {latestTraceEntries.map((entry) => (
                            <div key={entry.id} className={`trace-row ${entry.tags?.length ? "" : "compact"}`}>
                              <button
                                type="button"
                                className={`trace-bubble ${entry.tags?.length ? "wide" : "compact"} clickable ${
                                  openDetailId === entry.id ? "active" : ""
                                }`}
                                onClick={() => toggleDetail(entry.id)}
                              >
                                {entry.tags?.length ? (
                                  <>
                                    <p className="trace-title">{entry.text}</p>
                                    <div className="trace-tags">
                                      {entry.tags.map((tag) => (
                                        <span key={tag.label} className={`status-tag ${tag.tone}`}>
                                          {tag.label}
                                        </span>
                                      ))}
                                    </div>
                                  </>
                                ) : (
                                  entry.text
                                )}
                              </button>
                            </div>
                          ))}
                        </div>
                      ) : null}

                      {sendingMessage || streamingContent ? (
                        <div className="trace-row">
                          <div className="trace-bubble wide final">
                            <p className="trace-copy">{streamingContent || "正在生成回答..."}</p>
                          </div>
                        </div>
                      ) : null}
                    </>
                  ) : null}
                </>
              )}
            </section>

            {!showEmptyChatState ? <footer className="composer-bar">{renderChatComposer("footer")}</footer> : null}
          </>
        ) : null}

        {activePage === "skills" ? (
          <section className="workspace-page">
            <div className="workspace-page-head">
              <div>
                <p className="workspace-eyebrow">Skills Workspace</p>
                <h2>管理可用 Skills，并维持当前工作台可解释性</h2>
                <div className="workspace-page-meta">
                  <span className="workspace-pill">{skills.length} 个 Skill</span>
                  <span className="workspace-pill subtle">Skill 是说明书，不是直接执行器</span>
                </div>
              </div>
              <div className="workspace-page-actions">
                <button
                  type="button"
                  className="workspace-secondary-button"
                  onClick={() => void loadSkillsWorkspace()}
                  disabled={skillsLoading}
                >
                  刷新列表
                </button>
              </div>
            </div>

            {skillsError ? <div className="workspace-alert error">{skillsError}</div> : null}
            {skillSaveNotice ? <div className="workspace-alert success">{skillSaveNotice}</div> : null}

            <div className="workspace-grid">
              <article className="workspace-card">
                <div className="workspace-card-head">
                  <div>
                    <h3>可用 Skill</h3>
                    <p>左侧挑选，右侧查看 `SKILL.md`、依赖工具和使用限制。</p>
                  </div>
                </div>

                <div className="workspace-card-body workspace-card-scroll">
                  <div className="skill-import-block">
                    <label className="workspace-field-label" htmlFor="skill-import-path">
                      手动导入 Skill 文件夹
                    </label>
                    <div className="skill-import-row">
                      <input
                        id="skill-import-path"
                        className="workspace-text-input"
                        value={skillImportPath}
                        onChange={(event) => setSkillImportPath(event.target.value)}
                        placeholder="例如 skills/my_custom_skill"
                      />
                      <button
                        type="button"
                        className="workspace-primary-button"
                        onClick={() => void importSkill()}
                        disabled={skillImporting || !skillImportPath.trim()}
                      >
                        {skillImporting ? "导入中..." : "导入"}
                      </button>
                    </div>
                  </div>

                  {skillsLoading ? <div className="workspace-empty">正在加载 Skills...</div> : null}

                  {!skillsLoading ? (
                    <div className="workspace-list">
                      {skills.length === 0 ? <div className="workspace-empty">当前还没有可用 Skill。</div> : null}
                      {skills.map((skill) => (
                        <button
                          key={`${skill.source}-${skill.name}-${skill.path}`}
                          type="button"
                          className={`skills-item ${selectedSkillName === skill.name ? "active" : ""}`}
                          onClick={() => {
                            setSelectedSkillName(skill.name);
                            setSkillSaveNotice(null);
                          }}
                        >
                          <div className="skills-item-head">
                            <strong>{skill.name}</strong>
                            <span className={`workspace-pill ${skill.source === "workspace" ? "accent" : "subtle"}`}>
                              {skillSourceLabel(skill)}
                            </span>
                          </div>
                          <p>{skill.description || skill.summary || "暂无简介"}</p>
                          <div className="skills-item-meta">
                            <span>{skill.when_to_use || "未填写 when_to_use"}</span>
                          </div>
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              </article>

              <article className="workspace-card">
                <div className="workspace-card-head">
                  <div>
                    <h3>{skillDetail?.name || selectedSkillName || "Skill 详情"}</h3>
                    <p>{skillDetail ? skillDetail.path : "选择一个 Skill 后查看详情、编辑内容并保存。"}</p>
                  </div>
                  <div className="workspace-inline-actions">
                    <button
                      type="button"
                      className="workspace-secondary-button"
                      onClick={() => void saveSelectedSkill()}
                      disabled={!skillDetail || skillDetail.readonly || !hasSkillChanges || skillSaving}
                    >
                      {skillSaving ? "保存中..." : "保存"}
                    </button>
                    <button
                      type="button"
                      className="workspace-danger-button"
                      onClick={() => void deleteSelectedSkill()}
                      disabled={!skillDetail || skillDetail.readonly || skillDeleting}
                    >
                      {skillDeleting ? "删除中..." : "删除"}
                    </button>
                  </div>
                </div>

                <div className="workspace-card-body workspace-card-scroll">
                  {skillDetailLoading ? <div className="workspace-empty">正在加载 Skill 详情...</div> : null}

                  {!skillDetailLoading && !skillDetail ? (
                    <div className="workspace-empty">先从左侧选择一个 Skill，或导入新的 Skill 文件夹。</div>
                  ) : null}

                  {!skillDetailLoading && skillDetail ? (
                    <>
                      <div className="workspace-info-grid">
                        <div className="workspace-mini-card">
                          <span className="workspace-mini-label">来源</span>
                          <strong>{skillSourceLabel(skillDetail)}</strong>
                        </div>
                        <div className="workspace-mini-card">
                          <span className="workspace-mini-label">当前状态</span>
                          <strong>{skillDetail.available ? "当前可用" : "当前不可用"}</strong>
                        </div>
                        <div className="workspace-mini-card">
                          <span className="workspace-mini-label">目录</span>
                          <strong>{skillDetail.directory_path}</strong>
                        </div>
                        <div className="workspace-mini-card">
                          <span className="workspace-mini-label">编辑权限</span>
                          <strong>{skillDetail.readonly ? "只读" : "可编辑"}</strong>
                        </div>
                      </div>

                      <div className="workspace-detail-block">
                        <span className="workspace-field-label">作用说明</span>
                        <p className="workspace-copy">{skillDetail.description || skillDetail.summary || "暂无简介"}</p>
                      </div>

                      <div className="workspace-detail-block">
                        <span className="workspace-field-label">依赖 Tool</span>
                        <div className="workspace-pill-row">
                          {skillDetail.tool_dependencies.length === 0 ? (
                            <span className="workspace-pill subtle">未识别出明确依赖</span>
                          ) : (
                            skillDetail.tool_dependencies.map((toolName) => (
                              <span key={toolName} className="workspace-pill accent">
                                {toolName}
                              </span>
                            ))
                          )}
                        </div>
                      </div>

                      <div className="workspace-detail-block">
                        <span className="workspace-field-label">使用限制</span>
                        <p className="workspace-copy">
                          {skillDetail.usage_limits_summary || "暂未提取到明确限制，可直接查看下方 SKILL.md。"}
                        </p>
                      </div>

                      <div className="workspace-detail-block">
                        <span className="workspace-field-label">SKILL.md</span>
                        <textarea
                          className="workspace-editor"
                          value={skillDraft}
                          onChange={(event) => {
                            setSkillDraft(event.target.value);
                            setSkillSaveNotice(null);
                          }}
                          spellCheck={false}
                          disabled={skillDetail.readonly}
                        />
                        <span className="workspace-tiny-note">
                          {skillDetail.readonly
                            ? "插件内置 Skill 当前只读，可查看但不能直接修改。"
                            : "保存后会立即刷新 Skill 列表，后续会话会使用新版本说明。"}
                        </span>
                      </div>
                    </>
                  ) : null}
                </div>
              </article>
            </div>
          </section>
        ) : null}

        {activePage === "files" ? (
          <section className="workspace-page">
            <div className="workspace-page-head">
              <div>
                <p className="workspace-eyebrow">Files Workspace</p>
                <h2>浏览当前工作区和最近导入资料，快速定位上下文文件</h2>
                <div className="workspace-page-meta">
                  <span className="workspace-pill">{workspaceRootPath ? extractName(workspaceRootPath) : "workspace"}</span>
                  <span className="workspace-pill subtle">{knowledgeDocuments.length} 份知识资料</span>
                </div>
              </div>
              <div className="workspace-page-actions">
                <button
                  type="button"
                  className="workspace-secondary-button"
                  onClick={() => void refreshFilesWorkspace()}
                  disabled={workspaceLoading || knowledgeLoading}
                >
                  刷新内容
                </button>
              </div>
            </div>

            {workspaceError ? <div className="workspace-alert error">{workspaceError}</div> : null}
            {knowledgeError ? <div className="workspace-alert error">{knowledgeError}</div> : null}

            <div className="files-grid">
              <article className="workspace-card">
                <div className="workspace-card-head">
                  <div>
                    <h3>工作区浏览</h3>
                    <p>当前路径：{currentWorkspaceLabel}</p>
                  </div>
                  <div className="workspace-inline-actions">
                    <button
                      type="button"
                      className="workspace-secondary-button"
                      onClick={() => setWorkspacePath(extractParentPath(workspaceView?.path ?? ".", workspaceRootPath))}
                      disabled={!workspaceView || isWorkspaceRoot}
                    >
                      返回上一级
                    </button>
                  </div>
                </div>

                <div className="workspace-card-body workspace-card-scroll">
                  {workspaceLoading ? <div className="workspace-empty">正在读取工作区...</div> : null}

                  {!workspaceLoading && workspaceView?.type === "dir" ? (
                    <div className="workspace-list">
                      {workspaceView.entries.length === 0 ? <div className="workspace-empty">当前目录为空。</div> : null}
                      {workspaceView.entries.map((entry) => (
                        <button
                          key={entry.path}
                          type="button"
                          className="workspace-list-row"
                          onClick={() => setWorkspacePath(entry.path)}
                        >
                          <div className="workspace-list-row-main">
                            <span className={`workspace-item-mark ${entry.type}`}>{entry.type === "dir" ? "DIR" : "FILE"}</span>
                            <strong>{entry.name}</strong>
                          </div>
                          <span className="workspace-row-path">{entry.type === "dir" ? "进入目录" : "查看内容"}</span>
                        </button>
                      ))}
                    </div>
                  ) : null}

                  {!workspaceLoading && workspaceView?.type === "file" ? (
                    <div className="workspace-file-preview">
                      <div className="workspace-preview-meta">
                        <span className="workspace-pill accent">{extractName(workspaceView.path)}</span>
                        <span className="workspace-pill subtle">{workspaceView.content.length} 字符预览</span>
                      </div>
                      <pre>{workspaceView.content}</pre>
                    </div>
                  ) : null}
                </div>
              </article>

              <div className="workspace-side-column">
                <article className="workspace-card">
                  <div className="workspace-card-head">
                    <div>
                      <h3>{workspaceView?.type === "file" ? "当前文件摘要" : "当前目录摘要"}</h3>
                      <p>帮助你快速理解当前工作区上下文。</p>
                    </div>
                  </div>

                  <div className="workspace-card-body">
                    {workspaceView ? (
                      <>
                        <div className="workspace-mini-card">
                          <span className="workspace-mini-label">绝对路径</span>
                          <strong>{workspaceView.path}</strong>
                        </div>
                        <div className="workspace-mini-card">
                          <span className="workspace-mini-label">当前类型</span>
                          <strong>{workspaceView.type === "dir" ? "目录" : "文件"}</strong>
                        </div>
                        <div className="workspace-mini-card">
                          <span className="workspace-mini-label">
                            {workspaceView.type === "dir" ? "条目数量" : "预览大小"}
                          </span>
                          <strong>
                            {workspaceView.type === "dir"
                              ? `${workspaceView.entries.length} 项`
                              : `${formatBytes(new Blob([workspaceView.content]).size)}`}
                          </strong>
                        </div>
                      </>
                    ) : (
                      <div className="workspace-empty">等待工作区内容加载。</div>
                    )}
                  </div>
                </article>

                <article className="workspace-card">
                  <div className="workspace-card-head">
                    <div>
                      <h3>最近导入资料</h3>
                      <p>展示解析后的知识文件，便于回到引用源头。</p>
                    </div>
                  </div>

                  <div className="workspace-card-body workspace-card-scroll">
                    {knowledgeLoading ? <div className="workspace-empty">正在加载资料...</div> : null}

                    {!knowledgeLoading ? (
                      <div className="workspace-list">
                        {knowledgeDocuments.length === 0 ? <div className="workspace-empty">当前还没有导入资料。</div> : null}
                        {knowledgeDocuments.map((document) => {
                          const openPath = isOpenableWorkspacePath(document.source_path, workspaceRootPath)
                            ? document.source_path
                            : isOpenableWorkspacePath(document.stored_path, workspaceRootPath)
                              ? document.stored_path
                              : null;

                          return (
                            <div key={document.document_id} className="document-card">
                              <div className="document-card-head">
                                <strong>{document.title}</strong>
                                <span className="workspace-pill subtle">{document.parser}</span>
                              </div>
                              <p>{document.source_path}</p>
                              <div className="document-card-meta">
                                <span>{document.chunk_count} chunks</span>
                                <span>{document.page_count ? `${document.page_count} 页` : "单文件"}</span>
                                <span>{formatDateTime(document.imported_at)}</span>
                              </div>
                              <div className="workspace-inline-actions">
                                <button
                                  type="button"
                                  className="workspace-secondary-button"
                                  onClick={() => {
                                    if (openPath) {
                                      setWorkspacePath(openPath);
                                    }
                                  }}
                                  disabled={!openPath}
                                >
                                  {openPath ? "在工作区打开" : "不可直接跳转"}
                                </button>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    ) : null}
                  </div>
                </article>
              </div>
            </div>
          </section>
        ) : null}

        {activePage === "settings" ? (
          <section className="workspace-page">
            <div className="workspace-page-head">
              <div>
                <p className="workspace-eyebrow">Settings / Plugins</p>
                <h2>集中查看插件状态、启停结果和加载异常</h2>
                <div className="workspace-page-meta">
                  <span className="workspace-pill">{plugins.filter((plugin) => plugin.enabled).length} 个已启用插件</span>
                  <span className="workspace-pill subtle">{pluginErrors.length} 条加载告警</span>
                </div>
                <p className="workspace-tiny-note">聊天中心区已启用 MiSans，字体资源来自 Xiaomi HyperOS 官方 CDN。</p>
              </div>
              <div className="workspace-page-actions">
                <button
                  type="button"
                  className="workspace-secondary-button"
                  onClick={() => void rescanPlugins()}
                  disabled={pluginsLoading}
                >
                  {pluginsLoading ? "扫描中..." : "重新扫描插件"}
                </button>
              </div>
            </div>

            {pluginsError ? <div className="workspace-alert error">{pluginsError}</div> : null}
            {pluginsNotice ? <div className="workspace-alert success">{pluginsNotice}</div> : null}

            <div className="workspace-stack">
              <article className="workspace-card">
                <div className="workspace-card-head">
                  <div>
                    <h3>插件列表</h3>
                    <p>保留当前工作台风格，只补管理页面，不改整体视觉语义。</p>
                  </div>
                </div>

                <div className="workspace-card-body">
                  {pluginsLoading && plugins.length === 0 ? <div className="workspace-empty">正在加载插件...</div> : null}

                  {!pluginsLoading || plugins.length > 0 ? (
                    <div className="plugin-grid">
                      {plugins.map((plugin) => (
                        <article key={plugin.name} className="plugin-card">
                          <div className="plugin-card-head">
                            <div>
                              <h4>{plugin.name}</h4>
                              <p>v{plugin.version}</p>
                            </div>
                            <span className={`workspace-pill ${plugin.enabled ? "accent" : "subtle"}`}>
                              {plugin.enabled ? "已启用" : "已停用"}
                            </span>
                          </div>
                          <p className="plugin-card-copy">{plugin.description || "暂无插件描述"}</p>
                          <div className="plugin-card-stats">
                            <span>{plugin.skill_count} Skills</span>
                            <span>{plugin.hook_count} Hooks</span>
                            <span>{plugin.mcp_server_count} MCP</span>
                          </div>
                          <p className="plugin-card-path">{plugin.plugin_path}</p>
                          <button
                            type="button"
                            className={plugin.enabled ? "workspace-danger-button" : "workspace-primary-button"}
                            onClick={() => void togglePluginEnabled(plugin)}
                            disabled={pluginBusyName === plugin.name}
                          >
                            {pluginBusyName === plugin.name ? "处理中..." : plugin.enabled ? "停用插件" : "启用插件"}
                          </button>
                        </article>
                      ))}
                    </div>
                  ) : null}
                </div>
              </article>

              <article className="workspace-card">
                <div className="workspace-card-head">
                  <div>
                    <h3>加载异常</h3>
                    <p>如果插件目录有清单、版本或权限问题，会集中显示在这里。</p>
                  </div>
                </div>

                <div className="workspace-card-body">
                  {pluginErrors.length === 0 ? (
                    <div className="workspace-empty">当前没有插件加载异常。</div>
                  ) : (
                    <div className="workspace-list">
                      {pluginErrors.map((error, index) => (
                        <div key={`${error.plugin_path}-${index}`} className="workspace-list-row static">
                          <div className="workspace-list-row-main">
                            <span className="workspace-item-mark error">ERR</span>
                            <strong>{error.plugin_name || extractName(error.plugin_path)}</strong>
                          </div>
                          <p className="workspace-row-copy">
                            {error.message}
                            <br />
                            {error.plugin_path}
                          </p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </article>
            </div>
          </section>
        ) : null}
      </main>

      <aside className={`right-drawer ${activePage === "chat" && selectedDetail ? "open" : ""}`}>
        <div
          className="drawer-resize-handle"
          onPointerDown={() => setDragging("right")}
          role="separator"
          aria-orientation="vertical"
          aria-label="调整右侧栏宽度"
        />

        {activePage === "chat" && selectedDetail ? (
          <div className="drawer-inner">
            <div className="drawer-head">
              <h3>详情</h3>
              <button type="button" className="drawer-close" aria-label="关闭" onClick={() => setOpenDetailId(null)}>
                ×
              </button>
            </div>

            <div className="drawer-tabs">
              <button type="button" className="drawer-tab active">
                Trace
              </button>
              <button type="button" className="drawer-tab">
                Tool IO
              </button>
              <button type="button" className="drawer-tab">
                引用
              </button>
            </div>

            <section className="drawer-card">
              <span className="drawer-label">{selectedDetail.detailTitle}</span>
              <p>{selectedDetail.summary}</p>
            </section>

            <section className="drawer-card">
              <span className="drawer-label">输入输出</span>
              {selectedDetail.inputs.length > 0 ? (
                <ul className="drawer-list">
                  {selectedDetail.inputs.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p>当前条目没有额外输入输出详情。</p>
              )}
            </section>

            <section className="drawer-card">
              <span className="drawer-label">引用与来源</span>
              {selectedDetail.citations.length > 0 ? (
                <ul className="drawer-list">
                  {selectedDetail.citations.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p>当前条目没有额外引用信息。</p>
              )}
            </section>
          </div>
        ) : null}
      </aside>

    </div>
  );
}

export default App;
