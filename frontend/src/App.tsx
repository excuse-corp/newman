import { useEffect, useLayoutEffect, useRef, useState, type ChangeEvent, type KeyboardEvent } from "react";
import logo from "./assets/newman-logo.png";
import MessageContent, { type ChatAttachment } from "./chat/MessageContent";
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
  turn_id?: string | null;
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
  output?: string | null;
  turnId?: string | null;
  tags?: Array<{ label: string; tone: StatusTagTone }>;
};

type SecondaryCardType = "terminal" | "file" | "search" | "network" | "plan" | "generic";
type TimelineNodeKind = "thinking" | "progress" | "system_meta";
type TimelineNodeState = "running" | "completed" | "failed" | "pending" | "approved" | "rejected" | "recovering" | "updated";

type TimelineSecondaryItem = {
  id: string;
  parentId: string;
  state: TimelineNodeState;
  label: string;
  toolName?: string | null;
  cardType: SecondaryCardType;
  subtitle: string;
  statusLabel: string;
  statusTone: StatusTagTone;
  meta: string[];
  command?: string | null;
  output?: string | null;
  outputLineCount: number;
  detail: TraceEntry;
};

type TimelineNode = {
  id: string;
  kind: TimelineNodeKind;
  state: TimelineNodeState;
  time: string;
  primaryText: string;
  secondaryItems: TimelineSecondaryItem[];
  detail: TraceEntry;
};

type TurnAnswerPhase = "waiting" | "streaming" | "finalizing" | "persisted" | "failed";
type TurnStatus = "running" | "needs_approval" | "completed" | "failed";

type TurnMessage = {
  id: string;
  content: string;
  attachments: ChatAttachment[];
  createdAt: string;
  persisted: boolean;
  approvalMode?: TurnApprovalMode | null;
};

type TurnAnswer = {
  detailId: string;
  content: string;
  createdAt: string;
  phase: TurnAnswerPhase;
  source: "live" | "session";
  assistantMessageId?: string | null;
  finishReason?: string | null;
  errorMessage?: string | null;
};

type ChatTurn = {
  id: string;
  requestId?: string | null;
  userMessage: TurnMessage;
  answer: TurnAnswer | null;
  timeline: TimelineNode[];
  status: TurnStatus;
  isLive: boolean;
};

type LiveTurnState = {
  sessionId: string;
  localId: string;
  requestId: string | null;
  serverTurnId: string | null;
  userMessage: TurnMessage;
  answer: TurnAnswer;
  status: TurnStatus;
};

type ComposerAttachment = ChatAttachment & {
  file: File;
  previewUrl: string;
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

function makeAttachmentId(seed: string, index: number) {
  return `${seed}:${index}`;
}

function parseMessageAttachments(value: unknown): ChatAttachment[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.flatMap((item, index) => {
    if (!item || typeof item !== "object") {
      return [];
    }
    const filename = "filename" in item && typeof item.filename === "string" && item.filename ? item.filename : `image-${index + 1}`;
    const contentType =
      "content_type" in item && typeof item.content_type === "string" && item.content_type
        ? item.content_type
        : "application/octet-stream";
    return [
      {
        id: makeAttachmentId("path" in item && typeof item.path === "string" ? item.path : filename, index),
        filename,
        contentType,
        path: "path" in item && typeof item.path === "string" ? item.path : null,
        previewUrl: null,
        summary: "summary" in item && typeof item.summary === "string" ? item.summary : null,
        sizeBytes: null,
      },
    ];
  });
}

function readOriginalMessageContent(metadata: Record<string, unknown>, fallback: string) {
  return typeof metadata.original_content === "string" ? metadata.original_content : fallback;
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
  if (skill.source === "system") {
    return "系统";
  }
  if (skill.plugin_name) {
    return `插件 · ${skill.plugin_name}`;
  }
  return skill.source;
}

const TOOL_SEMANTIC_MAP: Record<
  string,
  {
    label: string;
    cardType: SecondaryCardType;
    runningText: string;
    completedText: string;
  }
> = {
  read_file: { label: "read_file", cardType: "file", runningText: "我先读取一下相关文件", completedText: "相关文件我已经看过了" },
  list_dir: { label: "list_dir", cardType: "file", runningText: "我先看一下目录结构", completedText: "目录结构我已经确认了" },
  list_files: { label: "list_files", cardType: "file", runningText: "我先整理一下文件列表", completedText: "文件列表我已经拿到了" },
  search_files: { label: "search_files", cardType: "search", runningText: "我先检索一下相关文件", completedText: "相关文件我已经找到了" },
  grep: { label: "grep", cardType: "search", runningText: "我先搜索一下文件内容", completedText: "匹配内容我已经找到了" },
  fetch_url: { label: "fetch_url", cardType: "network", runningText: "我先看一下网页资料", completedText: "网页资料我已经取回来了" },
  terminal: { label: "terminal", cardType: "terminal", runningText: "我先运行一条命令确认情况", completedText: "命令我已经执行完了" },
  write_file: { label: "write_file", cardType: "file", runningText: "我先创建对应文件", completedText: "文件我已经创建好了" },
  edit_file: { label: "edit_file", cardType: "file", runningText: "我先修改对应文件", completedText: "文件我已经改好了" },
  update_plan: { label: "update_plan", cardType: "plan", runningText: "我先整理一下执行步骤", completedText: "执行步骤我已经更新了" },
  search_knowledge_base: {
    label: "search_knowledge_base",
    cardType: "search",
    runningText: "我先检索一下知识资料",
    completedText: "知识结果我已经找到了"
  }
};

function resolveToolSemantic(toolName: string | null | undefined) {
  if (!toolName) {
    return {
      label: "工具",
      cardType: "generic" as const,
      runningText: "我先获取完成任务需要的信息",
      completedText: "这一步我已经完成了"
    };
  }
  if (toolName.startsWith("mcp__")) {
    return {
      label: toolName,
      cardType: "generic" as const,
      runningText: "我先调用一下外部能力",
      completedText: "外部能力调用我已经完成了"
    };
  }
  return (
    TOOL_SEMANTIC_MAP[toolName] ?? {
      label: toolName,
      cardType: "generic" as const,
      runningText: "我先获取完成任务需要的信息",
      completedText: "这一步我已经完成了"
    }
  );
}

function summarizeUserIntent(userPrompt: string | null | undefined) {
  if (!userPrompt) {
    return null;
  }
  const normalized = userPrompt.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return null;
  }
  return `你想了解「${compactString(normalized, 24)}」`;
}

function formatDuration(durationMs: unknown) {
  if (typeof durationMs !== "number" || !Number.isFinite(durationMs) || durationMs <= 0) {
    return null;
  }
  if (durationMs < 1000) {
    return `${durationMs}ms`;
  }
  if (durationMs < 10_000) {
    return `${(durationMs / 1000).toFixed(1)}s`;
  }
  return `${Math.round(durationMs / 1000)}s`;
}

function formatCompactPath(path: string | null | undefined) {
  if (!path) {
    return null;
  }
  const fileName = extractName(path);
  const parent = extractParentPath(path, null);
  if (!parent || parent === ".") {
    return fileName;
  }
  return `${extractName(parent)}/${fileName}`;
}

function formatUrlTarget(rawUrl: string | null | undefined) {
  if (!rawUrl) {
    return null;
  }
  try {
    const url = new URL(rawUrl);
    return url.hostname.replace(/^www\./, "") || rawUrl;
  } catch {
    return rawUrl;
  }
}

function compactString(value: string, maxLength = 88) {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength - 1)}…`;
}

function formatJsonPreview(value: unknown, maxLength = 96) {
  const rendered = stringifyForPanel(value).replace(/\s+/g, " ").trim();
  if (!rendered) {
    return null;
  }
  return compactString(rendered, maxLength);
}

function extractEventArguments(eventData: Record<string, unknown>) {
  return "arguments" in eventData && eventData.arguments && typeof eventData.arguments === "object"
    ? (eventData.arguments as Record<string, unknown>)
    : null;
}

function resolveToolTarget(toolName: string | null | undefined, eventData: Record<string, unknown>) {
  const targetLabel = typeof eventData.target_label === "string" ? eventData.target_label : null;
  if (targetLabel) {
    return targetLabel;
  }

  const argumentsPayload = extractEventArguments(eventData);
  const rawPath =
    (typeof eventData.path === "string" ? eventData.path : null) ??
    (argumentsPayload && typeof argumentsPayload.path === "string" ? argumentsPayload.path : null);
  if (rawPath) {
    return formatCompactPath(rawPath);
  }

  const rawQuery =
    (typeof eventData.query === "string" ? eventData.query : null) ??
    (argumentsPayload && typeof argumentsPayload.query === "string" ? argumentsPayload.query : null);
  if (rawQuery) {
    return `「${compactString(rawQuery, 36)}」相关资料`;
  }

  const rawUrl =
    (typeof eventData.url === "string" ? eventData.url : null) ??
    (argumentsPayload && typeof argumentsPayload.url === "string" ? argumentsPayload.url : null);
  if (rawUrl) {
    return toolName === "fetch_url" ? "网页资料" : formatUrlTarget(rawUrl);
  }

  const resourceName =
    (typeof eventData.resource_name === "string" ? eventData.resource_name : null) ??
    (typeof eventData.title === "string" ? eventData.title : null);
  return resourceName ? compactString(resourceName, 40) : null;
}

function inferResultCount(toolName: string | null | undefined, output: string | null | undefined) {
  if (!output) {
    return null;
  }
  const trimmed = output.trim();
  if (!trimmed) {
    return 0;
  }

  if (toolName === "search_knowledge_base") {
    const hits = trimmed.split("\n").filter((line) => /^\[\d+\]/.test(line.trim())).length;
    return hits || null;
  }

  if (toolName === "search_files" || toolName === "grep") {
    const hits = trimmed
      .split("\n")
      .filter((line) => line.trim() && !line.includes("(结果已截断)") && /^\S+:\d+:/.test(line.trim())).length;
    return hits || null;
  }

  if (toolName === "list_dir" || toolName === "list_files") {
    const hits = trimmed
      .split("\n")
      .filter((line, index) => index > 0 && line.trim() && !line.includes("(结果已截断)")).length;
    return hits || null;
  }

  return null;
}

function resolveProgressPrimaryText(
  toolName: string | null | undefined,
  status: "running" | "completed" | "failed",
  eventData: Record<string, unknown>,
  output?: string | null,
  userPrompt?: string | null
) {
  const semantic = resolveToolSemantic(toolName);
  const summaryText = typeof eventData.summary_text === "string" ? eventData.summary_text : null;
  const intentLead = summarizeUserIntent(userPrompt);

  if (status === "running") {
    if (summaryText) {
      return summaryText;
    }
    return intentLead ? `${intentLead}，${semantic.runningText}` : semantic.runningText;
  }

  if (status === "failed") {
    return typeof eventData.frontend_message === "string" && eventData.frontend_message
      ? eventData.frontend_message
      : "这一步暂时没有成功";
  }

  if (summaryText) {
    return summaryText;
  }

  const count = inferResultCount(toolName, output ?? null);
  if (typeof count === "number") {
    if (toolName === "search_files") {
      return `已找到 ${count} 个相关文件`;
    }
    if (toolName === "grep") {
      return `已找到 ${count} 处匹配`;
    }
    if (toolName === "search_knowledge_base") {
      return `已找到 ${count} 条知识结果`;
    }
  }

  return semantic.completedText;
}

function resolveSecondaryStatusMeta(
  state: TimelineNodeState,
  eventData: Record<string, unknown>,
  fallbackTone: StatusTagTone = "blue"
) {
  if (state === "completed" || state === "approved" || state === "updated") {
    return { label: state === "approved" ? "已批准" : "已完成", tone: "green" as StatusTagTone };
  }
  if (state === "failed" || state === "rejected") {
    return { label: state === "rejected" ? "已拒绝" : "失败", tone: "orange" as StatusTagTone };
  }
  if (state === "pending") {
    return { label: "待审批", tone: "orange" as StatusTagTone };
  }
  if (state === "recovering") {
    return { label: "恢复中", tone: "orange" as StatusTagTone };
  }
  if (typeof eventData.attempt === "number" && eventData.attempt > 1) {
    return { label: `第 ${eventData.attempt} 次`, tone: fallbackTone };
  }
  return { label: "运行中", tone: fallbackTone };
}

function buildToolSecondarySubtitle(toolName: string | null | undefined, eventData: Record<string, unknown>) {
  const args = extractEventArguments(eventData);
  if (toolName === "terminal") {
    return typeof args?.command === "string" && args.command.trim() ? args.command.trim() : "执行命令";
  }
  const target = resolveToolTarget(toolName, eventData);
  if (target) {
    return target;
  }
  if (args) {
    const preview = formatJsonPreview(args);
    if (preview) {
      return preview;
    }
  }
  return "暂无更多参数";
}

function buildTraceDetail(
  id: string,
  type: TraceEntry["type"],
  time: string,
  text: string,
  detailTitle: string,
  summary: string,
  eventData: Record<string, unknown>,
  options?: {
    tags?: Array<{ label: string; tone: StatusTagTone }>;
    output?: string | null;
  }
): TraceEntry {
  const inputs: string[] = [];
  const citations: string[] = [];

  if ("arguments" in eventData) {
    const rendered = stringifyForPanel(eventData.arguments);
    if (rendered) {
      inputs.push(`arguments = ${rendered}`);
    }
  }
  if ("plan" in eventData) {
    const rendered = stringifyForPanel(eventData.plan);
    if (rendered) {
      inputs.push(`plan = ${rendered}`);
    }
  }
  if ("context" in eventData) {
    const rendered = stringifyForPanel(eventData.context);
    if (rendered) {
      inputs.push(`context = ${rendered}`);
    }
  }
  if ("recommended_next_step" in eventData) {
    const rendered = stringifyForPanel(eventData.recommended_next_step);
    if (rendered) {
      citations.push(`next = ${rendered}`);
    }
  }
  if ("request_id" in eventData && typeof eventData.request_id === "string") {
    citations.push(`request_id = ${eventData.request_id}`);
  }

  return {
    id,
    type,
    time,
    text,
    detailTitle,
    summary,
    inputs,
    citations,
    output: options?.output ?? null,
    tags: options?.tags
  };
}

function countOutputLines(output: string | null | undefined) {
  if (!output) {
    return 0;
  }
  return output.split("\n").length;
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

function dedupeSessionEvents(events: SessionEventPayload[]) {
  const seen = new Set<string>();
  const deduped: SessionEventPayload[] = [];
  events.forEach((event) => {
    const key = `${event.ts}:${event.request_id ?? ""}:${event.event}:${JSON.stringify(event.data)}`;
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    deduped.push(event);
  });
  return deduped.sort((left, right) => left.ts - right.ts);
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

function isPaneNearBottom(pane: HTMLElement, threshold = 96) {
  return pane.scrollHeight - pane.scrollTop - pane.clientHeight <= threshold;
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

function buildEventDataWithRequest(event: SessionEventPayload) {
  return event.request_id ? { ...event.data, request_id: event.request_id } : event.data;
}

function buildPlanSubtitle(plan: unknown) {
  if (Array.isArray(plan)) {
    return compactString(
      plan
        .map((step) => {
          if (!step || typeof step !== "object") {
            return null;
          }
          return "step" in step && typeof step.step === "string" ? step.step : null;
        })
        .filter((value): value is string => Boolean(value))
        .slice(0, 3)
        .join(" · ") || "计划已更新",
      96
    );
  }
  if (plan && typeof plan === "object" && "steps" in plan && Array.isArray(plan.steps)) {
    return buildPlanSubtitle(plan.steps);
  }
  if (typeof plan === "string") {
    return compactString(plan, 96);
  }
  return "计划已更新";
}

function buildToolSecondaryMeta(
  toolName: string | null | undefined,
  eventData: Record<string, unknown>,
  output: string | null | undefined
) {
  const meta: string[] = [];
  const duration = formatDuration(eventData.duration_ms);
  if (duration) {
    meta.push(duration);
  }
  if (typeof eventData.attempt_count === "number" && eventData.attempt_count > 1) {
    meta.push(`第 ${eventData.attempt_count} 次`);
  }
  const count = inferResultCount(toolName, output);
  if (typeof count === "number" && count > 0) {
    meta.push(`${count} 条结果`);
  }
  if (toolName === "edit_file" && typeof eventData.replacements === "number") {
    meta.push(`${eventData.replacements} 处替换`);
  }
  return meta;
}

function buildToolSecondaryItem(
  parentId: string,
  event: SessionEventPayload,
  state: TimelineNodeState,
  output: string | null = null,
  userPrompt?: string | null
): TimelineSecondaryItem {
  const eventData = buildEventDataWithRequest(event);
  const toolName = typeof eventData.tool === "string" ? eventData.tool : null;
  const semantic = resolveToolSemantic(toolName);
  const status = resolveSecondaryStatusMeta(state, eventData);
  const detailId = `secondary:${typeof eventData.tool_call_id === "string" ? eventData.tool_call_id : parentId}`;
  const command =
    toolName === "terminal" && typeof extractEventArguments(eventData)?.command === "string"
      ? (extractEventArguments(eventData)?.command as string)
      : null;
  const summary =
    (typeof eventData.frontend_message === "string" && eventData.frontend_message) ||
    (typeof eventData.summary === "string" && eventData.summary) ||
    resolveProgressPrimaryText(
      toolName,
      state === "failed" ? "failed" : state === "completed" ? "completed" : "running",
      eventData,
      output,
      userPrompt
    );

  return {
    id: detailId,
    parentId,
    state,
    label: toolName === "terminal" ? "Shell" : toolName ?? semantic.label,
    toolName,
    cardType: semantic.cardType,
    subtitle: buildToolSecondarySubtitle(toolName, eventData),
    statusLabel: status.label,
    statusTone: status.tone,
    meta: buildToolSecondaryMeta(toolName, eventData, output),
    command,
    output,
    outputLineCount: countOutputLines(output),
    detail: buildTraceDetail(
      detailId,
      "tool",
      formatEventTime(event.ts),
      toolName ?? semantic.label,
      toolName ?? "工具过程",
      summary,
      eventData,
      {
        output,
        tags: [{ label: status.label, tone: status.tone }]
      }
    )
  };
}

function summarizeCommentaryContent(content: string | null | undefined, fallback: string) {
  const normalized = (content ?? "").replace(/\s+/g, " ").trim();
  return normalized || fallback;
}

function summarizeThinkingContent(content: string | null | undefined, state: TimelineNodeState) {
  const normalized = (content ?? "").replace(/\s+/g, " ").trim();
  if (!normalized) {
    return state === "completed" ? "思路整理完成" : "我先理一下思路";
  }
  const firstSentence = normalized.split(/(?<=[。！？.!?])\s+/)[0] || normalized;
  return compactString(firstSentence, 56);
}

function buildThinkingNode(
  ts: number,
  content: string | null = null,
  state: TimelineNodeState = "running",
  detailTitle = "Thinking"
): TimelineNode {
  const time = formatEventTime(ts);
  const nodeId = `node:thinking:${ts}`;
  const primaryText = summarizeThinkingContent(content, state);
  return {
    id: nodeId,
    kind: "thinking",
    state,
    time,
    primaryText,
    secondaryItems: [],
    detail: {
      id: nodeId,
      type: "trace",
      time,
      text: primaryText,
      detailTitle,
      summary: primaryText,
      inputs: [],
      citations: [],
      output: content,
      tags: [{ label: "Thinking", tone: "blue" }]
    }
  };
}

function buildProgressGroupNode(groupId: string, event: SessionEventPayload, primaryText: string): TimelineNode {
  const eventData = buildEventDataWithRequest(event);
  const nodeId = `node:group:${groupId}`;
  const status = resolveSecondaryStatusMeta("running", eventData);
  return {
    id: nodeId,
    kind: "progress",
    state: "running",
    time: formatEventTime(event.ts),
    primaryText,
    secondaryItems: [],
    detail: buildTraceDetail(nodeId, "trace", formatEventTime(event.ts), primaryText, "执行进展", primaryText, eventData, {
      tags: [{ label: status.label, tone: status.tone }]
    })
  };
}

function buildSkillSecondaryItem(parentId: string, event: SessionEventPayload): TimelineSecondaryItem {
  const eventData = buildEventDataWithRequest(event);
  const skillName = typeof eventData.event === "string" ? eventData.event : "Skill";
  const message = typeof eventData.message === "string" && eventData.message ? eventData.message : "这个分析步骤已完成";
  const contextOutput = typeof eventData.context === "undefined" ? null : stringifyForPanel(eventData.context);
  const contextTool =
    eventData.context && typeof eventData.context === "object" && "tool" in eventData.context && typeof eventData.context.tool === "string"
      ? eventData.context.tool
      : null;
  const detailId = `secondary:skill:${parentId}:${event.ts}:${skillName}`;

  return {
    id: detailId,
    parentId,
    state: "completed",
    label: skillName,
    toolName: null,
    cardType: "generic",
    subtitle: message,
    statusLabel: "已完成",
    statusTone: "green",
    meta: contextTool ? ["Skill", contextTool] : ["Skill"],
    output: contextOutput,
    outputLineCount: countOutputLines(contextOutput),
    detail: buildTraceDetail(
      detailId,
      "skill",
      formatEventTime(event.ts),
      skillName,
      "Skill 详情",
      message,
      eventData,
      {
        output: contextOutput,
        tags: [{ label: "Skill", tone: "green" }]
      }
    )
  };
}

function buildAttachmentSecondaryItem(parentId: string, event: SessionEventPayload): TimelineSecondaryItem {
  const eventData = buildEventDataWithRequest(event);
  const files =
    Array.isArray(eventData.files) && eventData.files.every((item) => item && typeof item === "object")
      ? (eventData.files as Array<Record<string, unknown>>)
      : [];
  const count = typeof eventData.count === "number" ? eventData.count : files.length;
  const isProcessed = event.event === "attachment_processed";
  const status = isProcessed ? { label: "已完成", tone: "green" as StatusTagTone } : { label: "处理中", tone: "blue" as StatusTagTone };
  const subtitle =
    files
      .map((item) => {
        const filename = typeof item.filename === "string" ? item.filename : "图片";
        const summary = typeof item.summary === "string" && item.summary ? item.summary : null;
        return summary ? `${filename}: ${summary}` : filename;
      })
      .join("\n") || `${count} 张图片`;
  const detailId = `secondary:attachment:${parentId}`;

  return {
    id: detailId,
    parentId,
    state: isProcessed ? "completed" : "running",
    label: "Images",
    toolName: "image_attachment",
    cardType: "generic",
    subtitle: isProcessed ? "图片预解析已完成" : `已接收 ${count} 张图片`,
    statusLabel: status.label,
    statusTone: status.tone,
    meta: count > 0 ? [`${count} 张图片`] : ["图片附件"],
    output: subtitle,
    outputLineCount: countOutputLines(subtitle),
    detail: buildTraceDetail(
      detailId,
      "result",
      formatEventTime(event.ts),
      "attachment",
      "图片附件",
      isProcessed ? "图片预解析已完成" : `已接收 ${count} 张图片`,
      eventData,
      {
        output: subtitle,
        tags: [{ label: status.label, tone: status.tone }],
      }
    ),
  };
}

function upsertProgressSecondaryItem(node: TimelineNode, item: TimelineSecondaryItem) {
  const existingIndex = node.secondaryItems.findIndex((currentItem) => currentItem.id === item.id);
  if (existingIndex === -1) {
    node.secondaryItems.push(item);
    return;
  }
  node.secondaryItems[existingIndex] = item;
}

function resolveProgressGroupState(items: TimelineSecondaryItem[]): TimelineNodeState {
  if (items.some((item) => item.state === "failed" || item.state === "rejected")) {
    return "failed";
  }
  if (items.some((item) => item.state === "running" || item.state === "pending" || item.state === "recovering")) {
    return "running";
  }
  return items.length > 0 ? "completed" : "running";
}

function refreshProgressGroupNode(
  node: TimelineNode,
  event: SessionEventPayload,
  primaryText: string,
  detailSummary?: string | null
) {
  const eventData = buildEventDataWithRequest(event);
  const nextState = resolveProgressGroupState(node.secondaryItems);
  const status = resolveSecondaryStatusMeta(nextState, eventData);
  node.state = nextState;
  node.time = formatEventTime(event.ts);
  node.primaryText = primaryText;
  node.detail = buildTraceDetail(
    node.id,
    "trace",
    formatEventTime(event.ts),
    primaryText,
    "执行进展",
    detailSummary || primaryText,
    eventData,
    {
      tags: [{ label: status.label, tone: status.tone }]
    }
  );
}

function applyTurnIdToNode(node: TimelineNode, turnId: string) {
  node.detail.turnId = turnId;
  node.secondaryItems.forEach((item) => {
    item.detail.turnId = turnId;
  });
  return node;
}

function preserveNodeIdentity(existingNode: TimelineNode, nextNode: TimelineNode): TimelineNode {
  return {
    ...nextNode,
    id: existingNode.id,
    detail: {
      ...nextNode.detail,
      id: existingNode.id
    },
    secondaryItems: nextNode.secondaryItems.map((item, index) => {
      const existingItem = existingNode.secondaryItems[index];
      const nextId = existingItem?.id ?? item.id;
      return {
        ...item,
        id: nextId,
        parentId: existingNode.id,
        detail: {
          ...item.detail,
          id: nextId
        }
      };
    })
  };
}

function isRunningThinkingNode(node: TimelineNode) {
  return node.kind === "thinking" && node.state === "running";
}

function findNodeById(nodes: TimelineNode[], nodeId: string) {
  const index = nodes.findIndex((node) => node.id === nodeId);
  if (index === -1) {
    return null;
  }
  return { node: nodes[index], index };
}

function buildTimelineNodes(
  events: SessionEventPayload[],
  toolMessages: SessionMessageRecord[],
  assistantToolMessages: SessionMessageRecord[] = [],
  userPrompt?: string | null
) {
  const nodes: TimelineNode[] = [];
  const progressNodeByGroupId = new Map<string, TimelineNode>();
  const toolCallToGroupId = new Map<string, string>();
  const toolMessageByCallId = new Map<string, SessionMessageRecord>();
  const commentaryByGroupId = new Map<string, string>();
  let thinkingNodeId: string | null = null;

  toolMessages.forEach((message) => {
    const toolCallId = typeof message.metadata.tool_call_id === "string" ? message.metadata.tool_call_id : null;
    if (toolCallId) {
      toolMessageByCallId.set(toolCallId, message);
    }
  });

  assistantToolMessages.forEach((message) => {
    const groupId = typeof message.metadata.group_id === "string" ? message.metadata.group_id : null;
    if (!groupId) {
      return;
    }
    const rawCommentary =
      typeof message.metadata.commentary === "string" && message.metadata.commentary
        ? message.metadata.commentary
        : message.content;
    const commentary = summarizeCommentaryContent(rawCommentary, "");
    if (commentary) {
      commentaryByGroupId.set(groupId, commentary);
    }
  });

  const resolveGroupId = (eventData: Record<string, unknown>, toolCallId: string | null) => {
    if (typeof eventData.group_id === "string" && eventData.group_id) {
      return eventData.group_id;
    }
    if (eventData.context && typeof eventData.context === "object" && "group_id" in eventData.context) {
      const nestedGroupId = eventData.context.group_id;
      if (typeof nestedGroupId === "string" && nestedGroupId) {
        return nestedGroupId;
      }
    }
    if (toolCallId) {
      return toolCallToGroupId.get(toolCallId) ?? `legacy:${toolCallId}`;
    }
    return null;
  };

  const ensureProgressNode = (groupId: string, event: SessionEventPayload, primaryText: string) => {
    const existingNode = progressNodeByGroupId.get(groupId);
    if (existingNode) {
      return existingNode;
    }
    const nextNode = buildProgressGroupNode(groupId, event, primaryText);
    nodes.push(nextNode);
    progressNodeByGroupId.set(groupId, nextNode);
    return nextNode;
  };

  events.forEach((event) => {
    const eventData = buildEventDataWithRequest(event);
    const toolCallId = typeof eventData.tool_call_id === "string" ? eventData.tool_call_id : null;
    const toolOutput = toolCallId ? toolMessageByCallId.get(toolCallId)?.content ?? null : null;

    if (event.event === "thinking_delta" || event.event === "thinking_complete") {
      const content = typeof eventData.content === "string" ? eventData.content : "";
      const nextNode = buildThinkingNode(
        event.ts,
        content,
        event.event === "thinking_complete" ? "completed" : "running",
        "当前思路"
      );
      const existingNodeId = thinkingNodeId ?? nodes.find((node) => node.kind === "thinking")?.id ?? null;
      const existing = existingNodeId ? findNodeById(nodes, existingNodeId) : null;
      if (existing) {
        const updatedNode = preserveNodeIdentity(existing.node, nextNode);
        nodes.splice(existing.index, 1);
        nodes.push(updatedNode);
        thinkingNodeId = existing.node.id;
      } else {
        nodes.push(nextNode);
        thinkingNodeId = nextNode.id;
      }
      return;
    }

    if (event.event === "commentary_delta" || event.event === "commentary_complete") {
      const groupId = resolveGroupId(eventData, toolCallId);
      if (!groupId) {
        return;
      }
      const commentary = summarizeCommentaryContent(
        typeof eventData.content === "string" ? eventData.content : commentaryByGroupId.get(groupId) ?? "",
        "我先继续处理这一步"
      );
      commentaryByGroupId.set(groupId, commentary);
      const node = ensureProgressNode(groupId, event, commentary);
      refreshProgressGroupNode(node, event, commentary, commentary);
      return;
    }

    if (event.event === "attachment_received" || event.event === "attachment_processed") {
      const attachmentCount = typeof eventData.count === "number" ? eventData.count : 0;
      const groupId = `attachment:${event.request_id ?? "current"}`;
      const primaryText = event.event === "attachment_processed" ? "图片预解析已完成" : `已接收 ${attachmentCount} 张图片`;
      const node = ensureProgressNode(groupId, event, primaryText);
      const item = buildAttachmentSecondaryItem(node.id, event);
      upsertProgressSecondaryItem(node, item);
      refreshProgressGroupNode(node, event, primaryText, item.detail.summary);
      return;
    }

    if (event.event === "tool_call_started") {
      const groupId = resolveGroupId(eventData, toolCallId);
      if (!groupId) {
        return;
      }
      const primaryText =
        commentaryByGroupId.get(groupId) ||
        resolveProgressPrimaryText("tool" in eventData && typeof eventData.tool === "string" ? eventData.tool : null, "running", eventData, toolOutput, userPrompt);
      const node = ensureProgressNode(groupId, event, primaryText);
      const item = buildToolSecondaryItem(node.id, event, "running", toolOutput, userPrompt);
      upsertProgressSecondaryItem(node, item);
      refreshProgressGroupNode(node, event, primaryText, item.detail.summary);
      if (toolCallId) {
        toolCallToGroupId.set(toolCallId, groupId);
      }
      return;
    }

    if (event.event === "tool_call_finished") {
      const groupId = resolveGroupId(eventData, toolCallId);
      if (!groupId) {
        return;
      }
      const nextState = Boolean(eventData.success) ? "completed" : "failed";
      const primaryText =
        commentaryByGroupId.get(groupId) ||
        resolveProgressPrimaryText("tool" in eventData && typeof eventData.tool === "string" ? eventData.tool : null, nextState, eventData, toolOutput, userPrompt);
      const node = ensureProgressNode(groupId, event, primaryText);
      const item = buildToolSecondaryItem(node.id, event, nextState, toolOutput, userPrompt);
      upsertProgressSecondaryItem(node, item);
      refreshProgressGroupNode(node, event, primaryText, item.detail.summary);
      if (toolCallId) {
        toolCallToGroupId.set(toolCallId, groupId);
      }
      return;
    }

    if (event.event === "hook_triggered") {
      const groupId = resolveGroupId(eventData, toolCallId);
      if (!groupId) {
        return;
      }
      const primaryText =
        commentaryByGroupId.get(groupId) ||
        summarizeCommentaryContent(typeof eventData.message === "string" ? eventData.message : "", "我先继续处理这一步");
      const node = ensureProgressNode(groupId, event, primaryText);
      const item = buildSkillSecondaryItem(node.id, event);
      upsertProgressSecondaryItem(node, item);
      refreshProgressGroupNode(node, event, primaryText, item.detail.summary);
      return;
    }
  });

  return nodes;
}

function parseTimestamp(value: string | null | undefined) {
  if (!value) {
    return null;
  }
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function readTurnId(value: Record<string, unknown>) {
  const turnId = value.turn_id;
  return typeof turnId === "string" && turnId ? turnId : null;
}

function readRequestId(value: Record<string, unknown>) {
  const requestId = value.request_id;
  return typeof requestId === "string" && requestId ? requestId : null;
}

function readApprovalMode(value: Record<string, unknown>) {
  const approvalMode = value.approval_mode;
  return approvalMode === "manual" || approvalMode === "auto_approve_level2" ? approvalMode : null;
}

function isAssistantToolCallMessage(message: SessionMessageRecord) {
  const toolCalls = message.metadata.tool_calls;
  return Array.isArray(toolCalls) && toolCalls.length > 0;
}

function resolveTurnIdForEvent(
  event: SessionEventPayload,
  turns: ChatTurn[],
  turnIds: Set<string>
) {
  const directTurnId = readTurnId(event.data);
  if (directTurnId && turnIds.has(directTurnId)) {
    return directTurnId;
  }
  if (turns.length === 0) {
    return null;
  }

  for (let index = turns.length - 1; index >= 0; index -= 1) {
    const currentTurn = turns[index];
    const start = parseTimestamp(currentTurn.userMessage.createdAt);
    const nextTurn = turns[index + 1] ?? null;
    const nextStart = nextTurn ? parseTimestamp(nextTurn.userMessage.createdAt) : null;
    const afterStart = start === null || event.ts >= start;
    const beforeNext = nextStart === null || event.ts < nextStart;
    if (afterStart && beforeNext) {
      return currentTurn.id;
    }
  }

  return turns[turns.length - 1]?.id ?? null;
}

function buildChatTurns(messages: SessionMessageRecord[], sessionEvents: SessionEventPayload[]) {
  const turns: ChatTurn[] = [];
  const turnsById = new Map<string, ChatTurn>();
  const toolMessagesByTurn = new Map<string, SessionMessageRecord[]>();
  const assistantToolMessagesByTurn = new Map<string, SessionMessageRecord[]>();
  const eventsByTurn = new Map<string, SessionEventPayload[]>();

  messages.forEach((message) => {
    if (message.role !== "user") {
      return;
    }
    const turnId = readTurnId(message.metadata) ?? message.id;
    const turn: ChatTurn = {
      id: turnId,
      requestId: readRequestId(message.metadata),
      userMessage: {
        id: message.id,
        content: readOriginalMessageContent(message.metadata, message.content),
        attachments: parseMessageAttachments(message.metadata.attachments),
        createdAt: message.created_at,
        persisted: true,
        approvalMode: readApprovalMode(message.metadata)
      },
      answer: null,
      timeline: [],
      status: "running",
      isLive: false
    };
    turns.push(turn);
    turnsById.set(turnId, turn);
  });

  messages.forEach((message) => {
    if (message.role !== "tool") {
      return;
    }
    const turnId = readTurnId(message.metadata);
    if (!turnId) {
      return;
    }
    const items = toolMessagesByTurn.get(turnId) ?? [];
    items.push(message);
    toolMessagesByTurn.set(turnId, items);
  });

  messages.forEach((message) => {
    if (message.role !== "assistant" || isAssistantToolCallMessage(message)) {
      if (message.role === "assistant" && isAssistantToolCallMessage(message)) {
        const turnId = readTurnId(message.metadata);
        if (!turnId) {
          return;
        }
        const items = assistantToolMessagesByTurn.get(turnId) ?? [];
        items.push(message);
        assistantToolMessagesByTurn.set(turnId, items);
      }
      return;
    }

    const explicitTurnId = readTurnId(message.metadata);
    let targetTurn = explicitTurnId ? turnsById.get(explicitTurnId) ?? null : null;

    if (!targetTurn) {
      const createdAt = parseTimestamp(message.created_at);
      for (let index = turns.length - 1; index >= 0; index -= 1) {
        const turn = turns[index];
        const turnCreatedAt = parseTimestamp(turn.userMessage.createdAt);
        if (turn.answer) {
          continue;
        }
        if (createdAt === null || turnCreatedAt === null || turnCreatedAt <= createdAt) {
          targetTurn = turn;
          break;
        }
      }
    }

    if (!targetTurn) {
      return;
    }

    targetTurn.answer = {
      detailId: `assistant:${message.id}`,
      content: message.content,
      createdAt: message.created_at,
      phase: "persisted",
      source: "session",
      assistantMessageId: message.id,
      finishReason: typeof message.metadata.finish_reason === "string" ? message.metadata.finish_reason : null
    };
    targetTurn.requestId = targetTurn.requestId ?? readRequestId(message.metadata);
    if (targetTurn.status === "running") {
      targetTurn.status = "completed";
    }
  });

  const turnIds = new Set(turns.map((turn) => turn.id));
  sessionEvents.forEach((event, index) => {
    const turnId = resolveTurnIdForEvent(event, turns, turnIds);
    if (!turnId) {
      return;
    }
    const turn = turnsById.get(turnId);
    if (!turn) {
      return;
    }
    const entries = eventsByTurn.get(turnId) ?? [];
    entries.push(event);
    eventsByTurn.set(turnId, entries);
    turn.requestId = turn.requestId ?? event.request_id ?? null;

    if (event.event === "tool_approval_request") {
      turn.status = "needs_approval";
      return;
    }
    if (event.event === "tool_approval_resolved") {
      const approved = Boolean(event.data.approved);
      turn.status = approved ? (turn.answer ? "completed" : "running") : "failed";
      return;
    }
    if (event.event === "error") {
      turn.status = "failed";
      return;
    }
    if (event.event === "tool_error_feedback") {
      const recoveryClass = event.data.recovery_class;
      if (recoveryClass === "fatal" || recoveryClass === "blocked") {
        turn.status = "failed";
      }
      return;
    }
    if (turn.status === "running" && turn.answer) {
      turn.status = "completed";
    }
  });

  turns.forEach((turn) => {
    if (turn.status === "running" && turn.answer) {
      turn.status = "completed";
    }
    turn.timeline = buildTimelineNodes(
      eventsByTurn.get(turn.id) ?? [],
      toolMessagesByTurn.get(turn.id) ?? [],
      assistantToolMessagesByTurn.get(turn.id) ?? [],
      turn.userMessage.content
    ).map((node) =>
      applyTurnIdToNode(node, turn.id)
    );
  });

  return turns;
}

function matchLiveTurnEvent(event: SessionEventPayload, liveTurn: LiveTurnState) {
  const eventTurnId = readTurnId(event.data);
  if (liveTurn.serverTurnId && eventTurnId === liveTurn.serverTurnId) {
    return true;
  }
  if (liveTurn.requestId && event.request_id === liveTurn.requestId) {
    return true;
  }
  return false;
}

function buildLiveTurn(liveTurn: LiveTurnState, sessionEvents: SessionEventPayload[]): ChatTurn {
  const turnId = liveTurn.serverTurnId ?? liveTurn.localId;
  const turnEvents = sessionEvents.filter((event) => matchLiveTurnEvent(event, liveTurn));
  const timeline = buildTimelineNodes(
    turnEvents,
    [],
    [],
    liveTurn.userMessage.content
  ).map((node) => applyTurnIdToNode(node, turnId));
  const thinkingTs = parseTimestamp(liveTurn.userMessage.createdAt) ?? Date.now();
  const hasRunningThinking = timeline.some(isRunningThinkingNode);
  const shouldShowThinking =
    liveTurn.status === "running" &&
    (liveTurn.answer.phase === "waiting" || liveTurn.answer.phase === "streaming") &&
    !liveTurn.answer.content.trim() &&
    !hasRunningThinking;
  const nextTimeline = shouldShowThinking
    ? [...timeline, applyTurnIdToNode(buildThinkingNode(thinkingTs, null, "running", "当前思路"), turnId)]
    : timeline;

  return {
    id: turnId,
    requestId: liveTurn.requestId,
    userMessage: liveTurn.userMessage,
    answer: liveTurn.answer,
    timeline: nextTimeline,
    status: liveTurn.status,
    isLive: true
  };
}

function turnMatchesLiveTurn(turn: ChatTurn, liveTurn: LiveTurnState | null) {
  if (!liveTurn) {
    return false;
  }
  if (liveTurn.serverTurnId && turn.id === liveTurn.serverTurnId) {
    return true;
  }
  if (liveTurn.requestId && turn.requestId === liveTurn.requestId) {
    return true;
  }
  return false;
}

function resolveAnswerCopy(answer: TurnAnswer | null, status: TurnStatus) {
  if (answer && answer.content.trim()) {
    return answer.content;
  }
  if (answer?.phase === "failed") {
    return answer.errorMessage || "这轮执行暂时中断，请查看过程详情。";
  }
  if (status === "needs_approval") {
    return "这一步需要你确认后我才能继续。";
  }
  if (answer?.phase === "finalizing") {
    return "最终答案已经生成，正在同步到会话记录...";
  }
  if (answer?.phase === "streaming") {
    return "正在生成回答...";
  }
  return "正在准备回答...";
}

function shouldRenderAnswerBubble(turn: ChatTurn) {
  if (!turn.answer) {
    return turn.status !== "completed";
  }

  if (turn.answer.content.trim()) {
    return true;
  }

  if (turn.answer.phase === "failed") {
    return true;
  }

  if (turn.status === "needs_approval") {
    return true;
  }

  return !turn.isLive || !turn.timeline.some(isRunningThinkingNode);
}

function buildAnswerTags(answer: TurnAnswer | null, status: TurnStatus) {
  const tags: Array<{ label: string; tone: StatusTagTone }> = [];
  if (!answer) {
    if (status === "needs_approval") {
      tags.push({ label: "待确认", tone: "orange" });
    } else if (status === "failed") {
      tags.push({ label: "已中断", tone: "orange" });
    }
    return tags;
  }

  if (answer.phase === "failed") {
    tags.push({ label: "已中断", tone: "orange" });
  }

  if (status === "needs_approval") {
    tags.push({ label: "待确认", tone: "orange" });
  }

  if (answer.finishReason === "tool_limit_reached") {
    tags.push({ label: "工具上限", tone: "blue" });
  }

  return tags;
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
  const [liveTurn, setLiveTurn] = useState<LiveTurnState | null>(null);
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
  const [dragging, setDragging] = useState<null | "left">(null);
  const [viewportWidth, setViewportWidth] = useState(() => window.innerWidth);
  const [expandedTimelineIds, setExpandedTimelineIds] = useState<Record<string, boolean>>({});
  const [expandedSecondaryIds, setExpandedSecondaryIds] = useState<Record<string, boolean>>({});
  const [approvalMenuOpen, setApprovalMenuOpen] = useState(false);
  const [pendingApproval, setPendingApproval] = useState<PendingApproval | null>(null);
  const [approvalActionLoading, setApprovalActionLoading] = useState<null | "approve" | "reject">(null);
  const [approvalError, setApprovalError] = useState<string | null>(null);
  const [composerValue, setComposerValue] = useState("");
  const [composerAttachments, setComposerAttachments] = useState<ComposerAttachment[]>([]);
  const [turnApprovalMode, setTurnApprovalMode] = useState<TurnApprovalMode>("manual");
  const conversationPaneRef = useRef<HTMLElement | null>(null);
  const composerFileInputRef = useRef<HTMLInputElement | null>(null);
  const activeSessionIdRef = useRef(activeSessionId);
  const shouldAutoScrollRef = useRef(true);
  const attachmentPreviewUrlsRef = useRef<string[]>([]);
  const liveAttachmentUrlsRef = useRef<string[]>([]);

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
    return () => {
      attachmentPreviewUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
      attachmentPreviewUrlsRef.current = [];
    };
  }, []);

  useEffect(() => {
    const nextLiveUrls =
      liveTurn?.userMessage.attachments
        .map((attachment) => attachment.previewUrl)
        .filter((url): url is string => typeof url === "string" && url.startsWith("blob:")) ?? [];

    liveAttachmentUrlsRef.current
      .filter((url) => !nextLiveUrls.includes(url))
      .forEach((url) => {
        URL.revokeObjectURL(url);
        attachmentPreviewUrlsRef.current = attachmentPreviewUrlsRef.current.filter((item) => item !== url);
      });

    liveAttachmentUrlsRef.current = nextLiveUrls;
  }, [liveTurn]);

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
      setLeftWidth(clamp(event.clientX, LEFT_MIN, LEFT_MAX));
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

  async function loadChatWorkspace(sessionId: string, signal?: AbortSignal, options?: { silent?: boolean }) {
    const silent = options?.silent ?? false;
    if (!silent) {
      setChatLoading(true);
      setChatError(null);
    }

    try {
      const detail = await fetchJson<SessionDetailResponse>(`${apiBase}/api/sessions/${encodeURIComponent(sessionId)}`, { signal });

      let nextEvents: SessionEventPayload[] = [];
      try {
        const eventsUrl = new URL(`${apiBase}/api/sessions/${encodeURIComponent(sessionId)}/events`);
        eventsUrl.searchParams.set("limit", "2000");
        const events = await fetchJson<SessionEventsResponse>(eventsUrl.toString(), { signal });
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
        return false;
      }

      setActiveSessionDetail(detail.session);
      setActiveContextUsage(detail.context_usage ?? null);
      setSessionEvents(dedupeSessionEvents(nextEvents));
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
      return true;
    } catch (error) {
      if (signal?.aborted) {
        return false;
      }
      setChatError(error instanceof Error ? error.message : "会话内容加载失败");
      return false;
    } finally {
      if (!silent && !signal?.aborted && activeSessionIdRef.current === sessionId) {
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
      setLiveTurn(null);
      setChatLoading(false);
      return;
    }

    const controller = new AbortController();
    setActiveSessionDetail(null);
    setActiveContextUsage(null);
    setSessionEvents([]);
    setLiveTurn((currentTurn) => (currentTurn && currentTurn.sessionId !== activeSessionId ? null : currentTurn));
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
    shouldAutoScrollRef.current = true;
  }, [activePage, activeSessionId]);

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
  const persistedSessionEvents = liveTurn ? sessionEvents.filter((event) => !matchLiveTurnEvent(event, liveTurn)) : sessionEvents;
  const persistedTurns = buildChatTurns(activeSessionDetail?.messages ?? [], persistedSessionEvents);
  const visiblePersistedTurns = persistedTurns.filter((turn) => !turnMatchesLiveTurn(turn, liveTurn));
  const displayTurns = liveTurn ? [...visiblePersistedTurns, buildLiveTurn(liveTurn, sessionEvents)] : visiblePersistedTurns;
  const showEmptyChatState =
    activePage === "chat" &&
    !chatLoading &&
    !sendingMessage &&
    displayTurns.length === 0;
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

  useEffect(() => {
    if (activePage !== "chat") return;
    const pane = conversationPaneRef.current;
    if (!pane) return;

    const handleScroll = () => {
      shouldAutoScrollRef.current = isPaneNearBottom(pane);
    };

    handleScroll();
    pane.addEventListener("scroll", handleScroll, { passive: true });
    return () => pane.removeEventListener("scroll", handleScroll);
  }, [activePage, activeSessionId, chatLoading, showEmptyChatState]);

  useLayoutEffect(() => {
    if (activePage !== "chat") return;
    if (!activeSessionDetail && !liveTurn) return;

    const pane = conversationPaneRef.current;
    if (!pane) return;
    if (!shouldAutoScrollRef.current && !isPaneNearBottom(pane)) {
      return;
    }

    pane.scrollTop = pane.scrollHeight;
  }, [activePage, activeSessionId, activeSessionDetail, liveTurn, sessionEvents.length]);

  const switchPage = (nextPage: WorkspacePage) => {
    setActivePage(nextPage);
    setOpenSessionMenuId(null);
    setApprovalMenuOpen(false);
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

  const appendComposerAttachments = (files: File[]) => {
    if (files.length === 0) {
      return;
    }

    setChatError(null);
    setComposerAttachments((current) => [
      ...current,
      ...files
        .filter((file) => file.type === "image/png" || file.type === "image/jpeg")
        .map((file, index) => {
          const previewUrl = URL.createObjectURL(file);
          attachmentPreviewUrlsRef.current.push(previewUrl);
          return {
            id: makeAttachmentId(`${file.name}:${file.lastModified}:${file.size}`, current.length + index),
            file,
            filename: file.name,
            contentType: file.type || "application/octet-stream",
            previewUrl,
            path: null,
            summary: null,
            sizeBytes: file.size,
          };
        }),
    ]);
  };

  const handleComposerFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    if (files.some((file) => file.type !== "image/png" && file.type !== "image/jpeg")) {
      setChatError("当前仅支持 PNG / JPEG 图片附件");
    }
    appendComposerAttachments(files);
    event.target.value = "";
  };

  const removeComposerAttachment = (attachmentId: string) => {
    setComposerAttachments((current) => {
      const target = current.find((attachment) => attachment.id === attachmentId);
      if (target?.previewUrl) {
        URL.revokeObjectURL(target.previewUrl);
        attachmentPreviewUrlsRef.current = attachmentPreviewUrlsRef.current.filter((url) => url !== target.previewUrl);
      }
      return current.filter((attachment) => attachment.id !== attachmentId);
    });
  };

  const submitComposer = async () => {
    const trimmed = composerValue.trim();
    if ((!trimmed && composerAttachments.length === 0) || sendingMessage) return;

    setChatError(null);
    setChatNotice(null);
    setSendingMessage(true);

    try {
      const sessionId = await ensureSession();
      const createdAt = new Date().toISOString();
      const liveTurnLocalId = `live-turn-${Date.now()}`;
      const attachmentSnapshot = composerAttachments.map(({ file: _file, ...attachment }) => attachment);
      setLiveTurn({
        sessionId,
        localId: liveTurnLocalId,
        requestId: null,
        serverTurnId: null,
        userMessage: {
          id: liveTurnLocalId,
          content: trimmed,
          attachments: attachmentSnapshot,
          createdAt,
          persisted: false,
          approvalMode: turnApprovalMode
        },
        answer: {
          detailId: `live-answer:${liveTurnLocalId}`,
          content: "",
          createdAt,
          phase: "waiting",
          source: "live",
          assistantMessageId: null,
          finishReason: null,
          errorMessage: null
        },
        status: "running"
      });

      setChatSessions((currentSessions) =>
        currentSessions.map((session) =>
          session.id === sessionId
            ? {
                ...session,
                hasConversation: true,
                messageCount: Math.max(1, session.messageCount),
                updatedAt: createdAt
              }
            : session
        )
      );
      setComposerValue("");
      setComposerAttachments([]);
      switchPage("chat");

      const response =
        composerAttachments.length > 0
          ? await (() => {
              const body = new FormData();
              if (trimmed) {
                body.append("content", trimmed);
              }
              composerAttachments.forEach((attachment) => {
                body.append("images", attachment.file, attachment.filename);
              });
              body.append("approval_mode", turnApprovalMode);
              return fetch(`${apiBase}/api/sessions/${encodeURIComponent(sessionId)}/messages`, {
                method: "POST",
                body,
              });
            })()
          : await fetch(`${apiBase}/api/sessions/${encodeURIComponent(sessionId)}/messages`, {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
              },
              body: JSON.stringify({
                content: trimmed,
                approval_mode: turnApprovalMode,
              }),
            });

      if (!response.ok) {
        const message = await response.text();
        throw new Error(message || `请求失败：${response.status}`);
      }

      const requestId = response.headers.get("x-request-id");
      setLiveTurn((currentTurn) =>
        currentTurn && currentTurn.localId === liveTurnLocalId
          ? {
              ...currentTurn,
              requestId
            }
          : currentTurn
      );

      await consumeSseStream(response, (payload) => {
        if (activeSessionIdRef.current !== sessionId) {
          return;
        }

        setSessionEvents((currentEvents) => [...currentEvents, payload]);
        if (payload.event === "error") {
          setChatError(typeof payload.data.message === "string" ? payload.data.message : "消息流执行失败");
        }

        setLiveTurn((currentTurn) => {
          if (!currentTurn || currentTurn.localId !== liveTurnLocalId) {
            return currentTurn;
          }

          const nextTurn = {
            ...currentTurn,
            requestId: currentTurn.requestId ?? payload.request_id ?? null,
            serverTurnId: currentTurn.serverTurnId ?? readTurnId(payload.data)
          };

          if (payload.event === "assistant_delta") {
            return {
              ...nextTurn,
              status: "running",
              answer: {
                ...nextTurn.answer,
                phase: "streaming",
                content: typeof payload.data.content === "string" ? payload.data.content : nextTurn.answer.content
              }
            };
          }

          if (
            payload.event === "thinking_delta" ||
            payload.event === "thinking_complete" ||
            payload.event === "commentary_delta" ||
            payload.event === "commentary_complete"
          ) {
            return {
              ...nextTurn,
              status: "running"
            };
          }

          if (payload.event === "final_response") {
            return {
              ...nextTurn,
              status: "completed",
              answer: {
                ...nextTurn.answer,
                phase: "finalizing",
                content: typeof payload.data.content === "string" ? payload.data.content : nextTurn.answer.content,
                finishReason:
                  typeof payload.data.finish_reason === "string" ? payload.data.finish_reason : nextTurn.answer.finishReason,
                assistantMessageId:
                  typeof payload.data.message_id === "string" ? payload.data.message_id : nextTurn.answer.assistantMessageId,
                createdAt: typeof payload.data.created_at === "string" ? payload.data.created_at : nextTurn.answer.createdAt
              }
            };
          }

          if (payload.event === "tool_approval_request") {
            return {
              ...nextTurn,
              status: "needs_approval"
            };
          }

          if (payload.event === "tool_approval_resolved") {
            return {
              ...nextTurn,
              status: Boolean(payload.data.approved) ? "running" : "failed"
            };
          }

          if (payload.event === "error") {
            const message = typeof payload.data.message === "string" ? payload.data.message : "消息流执行失败";
            return {
              ...nextTurn,
              status: "failed",
              answer: {
                ...nextTurn.answer,
                phase: "failed",
                errorMessage: message,
                content: nextTurn.answer.content || message
              }
            };
          }

          return nextTurn;
        });
      });

      await loadChatSessions(undefined, sessionId);
      const refreshed = await loadChatWorkspace(sessionId, undefined, { silent: true });
      if (refreshed && activeSessionIdRef.current === sessionId) {
        setLiveTurn((currentTurn) => (currentTurn && currentTurn.localId === liveTurnLocalId ? null : currentTurn));
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "发送消息失败";
      setChatError(message);
      setLiveTurn((currentTurn) =>
        currentTurn
          ? {
              ...currentTurn,
              status: "failed",
              answer: {
                ...currentTurn.answer,
                phase: "failed",
                errorMessage: message,
                content: currentTurn.answer.content || message
              }
            }
          : currentTurn
      );
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

  const isTimelineExpanded = (node: TimelineNode) => {
    const manual = expandedTimelineIds[node.id];
    if (typeof manual === "boolean") {
      return manual;
    }
    return false;
  };

  const toggleTimelineNode = (node: TimelineNode) => {
    setExpandedTimelineIds((current) => ({
      ...current,
      [node.id]: !isTimelineExpanded(node)
    }));
  };

  const isSecondaryOutputExpanded = (item: TimelineSecondaryItem) => {
    const manual = expandedSecondaryIds[item.id];
    if (typeof manual === "boolean") {
      return manual;
    }
    return item.outputLineCount <= 10 || item.statusLabel === "运行中";
  };

  const toggleSecondaryOutput = (item: TimelineSecondaryItem) => {
    setExpandedSecondaryIds((current) => ({
      ...current,
      [item.id]: !isSecondaryOutputExpanded(item)
    }));
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
          <input
            ref={composerFileInputRef}
            className="composer-file-input"
            type="file"
            accept="image/png,image/jpeg"
            multiple
            onChange={handleComposerFileChange}
            tabIndex={-1}
          />

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
            placeholder={sendingMessage ? "当前正在执行，稍等这一轮完成…" : "输入你的任务，可附图片；按 Enter 发送，Shift + Enter 换行"}
            rows={3}
            disabled={sendingMessage}
          />

          {composerAttachments.length > 0 ? (
            <div className="composer-attachments" aria-label="已选择的图片">
              {composerAttachments.map((attachment) => (
                <div key={attachment.id} className="composer-attachment-chip">
                  <img className="composer-attachment-thumb" src={attachment.previewUrl} alt={attachment.filename} />
                  <div className="composer-attachment-meta">
                    <span className="composer-attachment-name">{attachment.filename}</span>
                    <span className="composer-attachment-size">
                      {typeof attachment.sizeBytes === "number" ? formatBytes(attachment.sizeBytes) : "图片"}
                    </span>
                  </div>
                  <button
                    type="button"
                    className="composer-attachment-remove"
                    aria-label={`移除 ${attachment.filename}`}
                    onClick={() => removeComposerAttachment(attachment.id)}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          ) : null}

          <div className="composer-subbar">
            <div className="composer-subbar-left">
              <button
                type="button"
                className="attach-trigger"
                aria-label="添加附件"
                onClick={() => composerFileInputRef.current?.click()}
                disabled={sendingMessage}
              >
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
                disabled={(!composerValue.trim() && composerAttachments.length === 0) || sendingMessage}
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
        gridTemplateColumns: isMobile ? "1fr" : `${leftWidth}px ${HANDLE_WIDTH}px minmax(0, 1fr)`
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
          showEmptyChatState ? (
            <section
              ref={conversationPaneRef}
              className="conversation-pane conversation-pane-empty"
            >
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
            </section>
          ) : (
            <div className="chat-stage">
              <section
                ref={conversationPaneRef}
                className="conversation-pane conversation-pane-floating"
              >
                {chatError ? <div className="workspace-alert error">{chatError}</div> : null}
                {chatNotice ? <div className="workspace-alert success">{chatNotice}</div> : null}
                {chatLoading ? <div className="workspace-empty">正在加载会话内容...</div> : null}

                {!chatLoading ? (
                  <>
                    {displayTurns.length === 0 ? <div className="workspace-empty">这个会话还没有内容，直接开始提需求就行。</div> : null}

                    {displayTurns.map((turn) => {
                      const answerCopy = resolveAnswerCopy(turn.answer, turn.status);
                      const answerTags = buildAnswerTags(turn.answer, turn.status);
                      const showAnswerBubble = shouldRenderAnswerBubble(turn);
                      return (
                        <div key={turn.id} className={`turn-block ${turn.isLive ? "live" : ""}`}>
                          <div className="user-row">
                            <div className="turn-user-stack">
                              <div className={`user-bubble ${turn.userMessage.attachments.length > 0 ? "has-attachments" : ""}`}>
                                <MessageContent
                                  apiBase={apiBase}
                                  variant="user"
                                  content={turn.userMessage.content}
                                  attachments={turn.userMessage.attachments}
                                />
                              </div>
                            </div>
                          </div>

                          {turn.timeline.length > 0 ? (
                            <div className="timeline-stack trace-turn-column">
                              {turn.timeline.map((node) => {
                                if (node.kind === "thinking") {
                                  if (node.state !== "running" || !turn.isLive) {
                                    return null;
                                  }
                                  return (
                                    <div key={node.id} className="thinking-logo-row" aria-label="Thinking">
                                      <img src={logo} alt="" className="thinking-inline-logo" />
                                      <div className="thinking-inline-copy">
                                        <span className="thinking-inline-word">thinking</span>
                                        <span className="thinking-inline-dots" aria-hidden="true">
                                          <span className="thinking-inline-dot dot-one">.</span>
                                          <span className="thinking-inline-dot dot-two">.</span>
                                          <span className="thinking-inline-dot dot-three">.</span>
                                        </span>
                                      </div>
                                    </div>
                                  );
                                }

                                const expanded = isTimelineExpanded(node);
                                const timelineHint = "查看执行过程";
                                return (
                                  <article
                                    key={node.id}
                                    className={`timeline-node ${expanded ? "expanded" : ""} state-${node.state} kind-${node.kind}`}
                                  >
                                    <button
                                      type="button"
                                      className="timeline-primary-button"
                                      onClick={() => toggleTimelineNode(node)}
                                    >
                                      <div className="timeline-primary-marker">
                                        <span className="timeline-static-dot" />
                                      </div>
                                      <div className="timeline-primary-copy">
                                        <div className="timeline-primary-meta">
                                          <span className="timeline-primary-time">{node.time}</span>
                                          <span className="timeline-primary-hint">{timelineHint}</span>
                                        </div>
                                        <p className="timeline-primary-text">{node.primaryText}</p>
                                      </div>
                                      <span className={`timeline-chevron ${expanded ? "expanded" : ""}`} aria-hidden="true">
                                        ▾
                                      </span>
                                    </button>

                                    {expanded ? (
                                      <div className="timeline-secondary-list">
                                        {node.secondaryItems.map((item) => {
                                          const outputExpanded = isSecondaryOutputExpanded(item);
                                          const outputLines = item.output ? item.output.split("\n") : [];
                                          const visibleOutput =
                                            item.output && !outputExpanded ? outputLines.slice(0, 10).join("\n") : item.output;

                                          return (
                                            <article
                                              key={item.id}
                                              className={`timeline-secondary-card ${item.cardType}`}
                                            >
                                              <div className="timeline-secondary-head">
                                                <div className="timeline-secondary-head-main">
                                                  <div className="timeline-secondary-label-row">
                                                    <span className="timeline-secondary-label">{item.label}</span>
                                                    <span className={`status-tag ${item.statusTone}`}>{item.statusLabel}</span>
                                                  </div>
                                                  <p className="timeline-secondary-subtitle">{item.subtitle}</p>
                                                </div>
                                              </div>

                                              {item.cardType === "terminal" ? (
                                                <div className="timeline-terminal-body">
                                                  <div className="timeline-terminal-shelltag">Shell</div>
                                                  <div className="timeline-terminal-command">$ {item.command || item.subtitle}</div>
                                                  {visibleOutput ? <pre className="timeline-terminal-output">{visibleOutput}</pre> : null}
                                                  {item.output && item.outputLineCount > 10 ? (
                                                    <button
                                                      type="button"
                                                      className="timeline-output-toggle"
                                                      onClick={() => toggleSecondaryOutput(item)}
                                                    >
                                                      {outputExpanded ? "收起输出" : "已运行命令 ⌄"}
                                                    </button>
                                                  ) : null}
                                                </div>
                                              ) : (
                                                <>
                                                  {item.meta.length > 0 ? (
                                                    <div className="timeline-secondary-meta-row">
                                                      {item.meta.map((metaItem) => (
                                                        <span key={`${item.id}-${metaItem}`} className="timeline-secondary-meta">
                                                          {metaItem}
                                                        </span>
                                                      ))}
                                                    </div>
                                                  ) : null}
                                                  {visibleOutput ? <pre className="timeline-secondary-output">{visibleOutput}</pre> : null}
                                                  {item.output && item.outputLineCount > 10 ? (
                                                    <button
                                                      type="button"
                                                      className="timeline-output-toggle"
                                                      onClick={() => toggleSecondaryOutput(item)}
                                                    >
                                                      {outputExpanded ? "收起详情" : "展开更多"}
                                                    </button>
                                                  ) : null}
                                                </>
                                              )}
                                            </article>
                                          );
                                        })}
                                      </div>
                                    ) : null}
                                  </article>
                                );
                              })}
                            </div>
                          ) : null}

                          {showAnswerBubble ? (
                            <div className="trace-row">
                              <div className="trace-bubble wide final answer-bubble">
                                {answerTags.length > 0 ? (
                                  <div className="trace-tags answer-tags">
                                    {answerTags.map((tag) => (
                                      <span key={`${turn.id}-${tag.label}`} className={`status-tag ${tag.tone}`}>
                                        {tag.label}
                                      </span>
                                    ))}
                                  </div>
                                ) : null}
                                <MessageContent apiBase={apiBase} variant="assistant" content={answerCopy} className="trace-copy" />
                              </div>
                            </div>
                          ) : null}
                        </div>
                      );
                    })}
                  </>
                ) : null}
              </section>

              <footer className="composer-bar composer-bar-floating">{renderChatComposer("footer")}</footer>
            </div>
          )
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
                            <span className={`workspace-pill ${skill.source === "system" ? "accent" : "subtle"}`}>
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

    </div>
  );
}

export default App;
