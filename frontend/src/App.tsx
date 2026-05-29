import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ChangeEvent,
  type ClipboardEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import logo from "./assets/newman-logo.png";
import MessageContent, { type ChatAttachment, type HtmlPreviewPayload } from "./chat/MessageContent";
import { escapeCodeHtml, highlightCode, inferLanguageFromPath } from "./chat/codeHighlight";
import AutomationsPage from "./pages/AutomationsPage";
import EvolutionPage from "./pages/EvolutionPage";
import UsageDashboard from "./pages/UsageDashboard";
import "./styles.css";

type WorkspacePage = "chat" | "automations" | "memory" | "skills" | "evolution" | "settings";
type SettingsTab = "theme" | "config" | "plugins" | "usage";
type MemoryKey = "memory" | "user";
type TurnApprovalMode = "manual" | "auto_allow";
type CollaborationModeName = "default" | "plan";
type PlanStepStatus = "pending" | "in_progress" | "completed" | "blocked" | "cancelled";
type TurnOutcome = "answered" | "awaiting_user" | "artifact_ready" | "task_completed" | "blocked" | "failed";
type AwaitingUserInputKind = "confirm" | "choice" | "free_text";
type UiTheme = "classic" | "coral";
type StatusTagTone = "blue" | "green" | "orange";

type SessionPlanPayload = {
  explanation?: string | null;
  current_step?: string | null;
  progress?: Record<string, number>;
  steps?: Array<{ step: string; status: PlanStepStatus | string }>;
} | null;

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

type AwaitingUserInputOption = {
  label: string;
  value: string;
  description?: string | null;
};

type AwaitingUserInputPayload = {
  requestId: string;
  kind: AwaitingUserInputKind;
  prompt: string;
  content?: string | null;
  options: AwaitingUserInputOption[];
  workflowId?: string | null;
  skillName?: string | null;
  phase?: string | null;
  status?: string | null;
  createdAt?: string | null;
};

type AwaitingUserInputReplyMetadata = {
  requestId?: string | null;
  workflowId?: string | null;
  kind?: string | null;
  skillName?: string | null;
  phase?: string | null;
};

type AwaitingUserInputSelection = {
  value: string;
  label: string;
};

type EnvironmentTimeContext = {
  client_timezone: string;
  client_local_now: string;
};

type EnvironmentLocationContext = {
  city: string;
  source: string;
  precision: string;
  captured_at_utc: string;
  timezone_hint?: string;
};

type EnvironmentContextPayload = {
  time: EnvironmentTimeContext;
  location?: EnvironmentLocationContext;
};

type ResolvedLocationResponse = {
  resolved: boolean;
  city: string | null;
  source: string;
  precision: string;
  captured_at_utc: string;
};

const DEFAULT_CONFIRM_AWAITING_OPTIONS: AwaitingUserInputOption[] = [
  { label: "确认，继续", value: "approved" },
  { label: "需要修改", value: "revise" },
];

type ApprovalRequestLike = Pick<PendingApproval, "tool" | "arguments" | "reason">;
type ApprovalNodePayload = ApprovalRequestLike & {
  approvalRequestId: string;
  summary: string | null;
  timeoutSeconds: number | null;
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
  background?: boolean;
  scheduled?: boolean;
  trigger_type?: string | null;
  source_task_id?: string | null;
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
  plan?: SessionPlanPayload;
  collaboration_mode?: {
    mode: CollaborationModeName;
    source: "manual" | "tool";
    updated_at: string;
  } | null;
  plan_draft?: {
    markdown: string;
    status: "draft" | "awaiting_approval" | "approved";
    updated_at: string;
  } | null;
  approved_plan?: {
    markdown: string;
    approved_at: string;
  } | null;
  workflow_state?: Record<string, unknown> | null;
  awaiting_user_input?: Record<string, unknown> | null;
  context_usage?: {
    effective_context_window: number;
    auto_compact_limit: number;
    soft_compact_limit: number;
    confirmed_prompt_tokens: number | null;
    confirmed_pressure: number | null;
    confirmed_request_kind: string | null;
    confirmed_recorded_at: string | null;
    projected_next_prompt_tokens: number;
    projected_pressure: number | null;
    budget_pressure: number | null;
    projection_source: string;
    projected_over_soft_limit: boolean;
    projected_over_limit: boolean;
    compaction_stage: string | null;
    compaction_fail_streak: number;
    context_irreducible: boolean;
    last_compaction_failure_reason: string | null;
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

type SessionUsageRecord = {
  request_id: string;
  session_id: string | null;
  turn_id: string | null;
  request_kind: string;
  usage_available: boolean;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  created_at: string;
};

type SessionUsageResponse = {
  session_id: string;
  records: SessionUsageRecord[];
  available: boolean;
  error?: string;
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
};

type SecondaryCardType = "terminal" | "file" | "search" | "network" | "plan" | "attachment" | "generic";
type TimelineNodeKind = "thinking" | "progress" | "system_meta" | "answer_start" | "approval";
type TimelineNodeState = "running" | "completed" | "failed" | "pending" | "approved" | "rejected" | "recovering" | "updated";
type TimelineMarkerIconName =
  | "folder"
  | "file"
  | "file_plus"
  | "file_edit"
  | "search"
  | "code_search"
  | "globe"
  | "terminal"
  | "plan"
  | "image"
  | "approval"
  | "generic"
  | "answer";

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
  argumentsPayload?: Record<string, unknown> | null;
  awaitingUserInput?: AwaitingUserInputPayload | null;
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
  approval?: ApprovalNodePayload | null;
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
  respondsToAwaitingUserInput?: AwaitingUserInputReplyMetadata | null;
};

type TurnAnswer = {
  detailId: string;
  content: string;
  attachments: ChatAttachment[];
  createdAt: string;
  phase: TurnAnswerPhase;
  source: "live" | "session";
  assistantMessageId?: string | null;
  finishReason?: string | null;
  turnOutcome?: TurnOutcome | null;
  awaitingUserInput?: AwaitingUserInputPayload | null;
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
  usage: TurnUsageSummary | null;
  durationMs: number | null;
};

type TurnUsageSummary = {
  requestCount: number;
  missingCount: number;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
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

type LiveAnswerQueueItem =
  | {
      kind: "reset";
    }
  | {
      kind: "delta";
      delta: string;
    }
  | {
      kind: "snapshot";
      content: string;
    };

const LIVE_ANSWER_MAX_CHARS_PER_FRAME = 28;
const LIVE_STREAM_BROWSER_YIELD_EVERY_EVENTS = 4;

type PendingFinalAnswer = {
  localId: string;
  content: string;
  attachments: ChatAttachment[];
  finishReason: string | null;
  turnOutcome: TurnOutcome | null;
  awaitingUserInput: AwaitingUserInputPayload | null;
  assistantMessageId: string | null;
  createdAt: string | null;
};

type ComposerAttachment = ChatAttachment & {
  file: File;
  previewUrl: string | null;
};

type HtmlPreviewState = HtmlPreviewPayload & {
  source?: "code_block" | "write_file";
  path?: string | null;
  toolCallId?: string | null;
  streaming?: boolean;
  saveStatus?: "saving" | "saved" | "failed";
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
  import_report?: SkillImportReport;
};

type SkillDocumentView = "preview" | "edit";
type SkillImportMode = "upload" | "path";
type HtmlPreviewView = "preview" | "code";

type SkillUploadItem = {
  id: string;
  file: File;
  relativePath: string;
};

type SkillImportReport = {
  mode: string;
  optimizer: string;
  source_files: string[];
  normalized_files: string[];
  generated_files: string[];
  warnings: string[];
  skill_directory: string;
  file_count: number;
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
  background: boolean;
  scheduled: boolean;
  triggerType: string | null;
  sourceTaskId: string | null;
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

type ProjectConfigResponse = {
  path: string;
  content: string;
  effective_workspace: string;
  source_priority: string[];
  reload_supported: boolean;
};

type UpdateProjectConfigResponse = {
  saved: boolean;
  path: string;
  content: string;
  effective_workspace: string;
  requires_reload: boolean;
  warnings: string[];
};

type ReloadProjectConfigResponse = {
  reloaded: boolean;
  path: string;
  effective_workspace: string;
  warnings: string[];
};

type InterruptTurnResponse = {
  interrupted: boolean;
  session_id: string;
  request_id?: string | null;
  turn_id?: string | null;
  message?: string | null;
  reason?: string | null;
};

const navItems: Array<{ id: Exclude<WorkspacePage, "settings">; label: string; hint: string }> = [
  { id: "chat", label: "Chat", hint: "对话" },
  { id: "automations", label: "Automations", hint: "定时" },
  { id: "memory", label: "Memory", hint: "记忆" },
  { id: "skills", label: "Skills", hint: "技能" },
  { id: "evolution", label: "Evolution", hint: "进化" }
];

const approvalModeMeta: Record<
  TurnApprovalMode,
  {
    label: string;
    helper: string;
  }
> = {
  auto_allow: {
    label: "全部默认通过",
    helper: "本轮所有需要审批的工具都会默认放行；只有命中硬拒绝规则的调用仍会被直接拦截。"
  },
  manual: {
    label: "逐个手动确认",
    helper: "本轮所有需要审批的工具都要你逐个点击确认后才继续。"
  }
};

const MAX_COMPOSER_ATTACHMENTS = 5;
const MAX_COMPOSER_ATTACHMENT_BYTES = 20 * 1024 * 1024;
const COMPOSER_ATTACHMENT_ACCEPT =
  "image/png,image/jpeg,image/webp,.doc,.docx,.xls,.xlsx,.pdf,.ppt,.pptx,.md,.txt,.json,.html,.htm";
const COMPOSER_ATTACHMENT_EXTENSIONS = new Set([
  ".png",
  ".jpg",
  ".jpeg",
  ".webp",
  ".doc",
  ".docx",
  ".xls",
  ".xlsx",
  ".pdf",
  ".ppt",
  ".pptx",
  ".md",
  ".txt",
  ".json",
  ".html",
  ".htm",
]);
const IMAGE_ATTACHMENT_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".webp"]);
const SKILL_UPLOAD_ACCEPT = ".md,.py,.jpg,.jpeg,.png";
const SKILL_UPLOAD_EXTENSIONS = new Set([".md", ".py", ".jpg", ".jpeg", ".png"]);
const MAX_SKILL_UPLOAD_FILES = 200;
const MAX_SKILL_UPLOAD_TOTAL_BYTES = 80 * 1024 * 1024;

type ComposerSlashCommand = {
  id: "plan";
  keyword: string;
  label: string;
  mode: CollaborationModeName;
};

function extractComposerSlashQuery(value: string) {
  const match = value.match(/^\/([^\s\n]*)$/);
  if (!match) {
    return null;
  }
  return match[1].trim().toLowerCase();
}

function buildComposerSlashCommands(): ComposerSlashCommand[] {
  return [
    {
      id: "plan",
      keyword: "plan",
      label: "计划模式",
      mode: "plan"
    }
  ];
}

const uiThemeOptions: Array<{
  id: UiTheme;
  kicker: string;
  label: string;
  description: string;
  previewClass: string;
}> = [
  {
    id: "classic",
    kicker: "Classic",
    label: "原版暖白",
    description: "保留当前这套浅暖白工作台，适合连续阅读、编辑和日常操作。",
    previewClass: "classic"
  },
  {
    id: "coral",
    kicker: "Coral",
    label: "参考图主题",
    description: "按参考图重做配色，采用石墨黑侧栏、暖白主舞台和珊瑚红强调色。",
    previewClass: "coral"
  }
];

const settingsTabOptions: Array<{
  id: SettingsTab;
  label: string;
  description: string;
}> = [
  {
    id: "theme",
    label: "界面主题",
    description: "切换当前工作台主题。"
  },
  {
    id: "config",
    label: "项目配置",
    description: "编辑并重载 newman.yaml。"
  },
  {
    id: "plugins",
    label: "插件与异常",
    description: "管理插件启停并查看加载问题。"
  },
  {
    id: "usage",
    label: "Token 消耗",
    description: "查看真实模型 usage 聚合。"
  }
];

const LEFT_MIN = 180;
const LEFT_MAX = 360;
const HANDLE_WIDTH = 8;
const HTML_PREVIEW_MIN = 360;
const HTML_PREVIEW_MAX = 920;
const HTML_PREVIEW_DEFAULT = 760;
const HTML_PREVIEW_MAIN_MIN = 360;
const TURN_APPROVAL_MODE_STORAGE_KEY = "newman-turn-approval-mode";
const ENVIRONMENT_CITY_CACHE_KEY = "newman-environment-city-cache";
const ENVIRONMENT_CITY_GEOLOCATION_TTL_MS = 6 * 60 * 60 * 1000;

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
  return (
    value === "chat" ||
    value === "automations" ||
    value === "memory" ||
    value === "skills" ||
    value === "evolution" ||
    value === "settings"
  );
}

function isUiTheme(value: string | null): value is UiTheme {
  return value === "classic" || value === "coral";
}

function isTurnApprovalMode(value: string | null): value is TurnApprovalMode {
  return value === "manual" || value === "auto_allow";
}

function isSettingsTab(value: string | null): value is SettingsTab {
  return value === "theme" || value === "config" || value === "plugins" || value === "usage";
}

function localTimezone() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

function padTimePart(value: number) {
  return String(Math.trunc(Math.abs(value))).padStart(2, "0");
}

function toLocalIsoString(value: Date) {
  const year = value.getFullYear();
  const month = padTimePart(value.getMonth() + 1);
  const day = padTimePart(value.getDate());
  const hour = padTimePart(value.getHours());
  const minute = padTimePart(value.getMinutes());
  const second = padTimePart(value.getSeconds());
  const offsetMinutes = -value.getTimezoneOffset();
  const sign = offsetMinutes >= 0 ? "+" : "-";
  const absoluteOffsetMinutes = Math.abs(offsetMinutes);
  const offsetHours = padTimePart(Math.floor(absoluteOffsetMinutes / 60));
  const offsetRemainder = padTimePart(absoluteOffsetMinutes % 60);
  return `${year}-${month}-${day}T${hour}:${minute}:${second}${sign}${offsetHours}:${offsetRemainder}`;
}

function writeCachedEnvironmentLocation(timezone: string, location: EnvironmentLocationContext, ttlMs: number) {
  const expiresAtUtc = new Date(Date.now() + ttlMs).toISOString();
  window.localStorage.setItem(
    ENVIRONMENT_CITY_CACHE_KEY,
    JSON.stringify({
      timezone,
      expires_at_utc: expiresAtUtc,
      location,
    })
  );
}

function readCachedEnvironmentLocation(timezone: string): EnvironmentLocationContext | null {
  const raw = window.localStorage.getItem(ENVIRONMENT_CITY_CACHE_KEY);
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as {
      timezone?: unknown;
      expires_at_utc?: unknown;
      location?: EnvironmentLocationContext;
    };
    if (parsed.timezone !== timezone) {
      return null;
    }
    if (typeof parsed.expires_at_utc !== "string" || !parsed.expires_at_utc) {
      return null;
    }
    const expiresAt = Date.parse(parsed.expires_at_utc);
    if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
      return null;
    }
    const location = parsed.location;
    if (!location || typeof location.city !== "string" || !location.city.trim()) {
      window.localStorage.removeItem(ENVIRONMENT_CITY_CACHE_KEY);
      return null;
    }
    if (location.source === "timezone_inference") {
      window.localStorage.removeItem(ENVIRONMENT_CITY_CACHE_KEY);
      return null;
    }
    return location;
  } catch {
    return null;
  }
}

function buildEnvironmentContext(location: EnvironmentLocationContext | null | undefined): EnvironmentContextPayload {
  const now = new Date();
  const payload: EnvironmentContextPayload = {
    time: {
      client_timezone: localTimezone(),
      client_local_now: toLocalIsoString(now),
    },
  };
  if (location) {
    payload.location = location;
  }
  return payload;
}

function getCurrentGeolocationPosition(options: PositionOptions): Promise<GeolocationPosition> {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error("Geolocation unavailable"));
      return;
    }
    navigator.geolocation.getCurrentPosition(resolve, reject, options);
  });
}

async function readGeolocationPermissionState(): Promise<PermissionState | "unsupported"> {
  if (!navigator.geolocation || !navigator.permissions?.query) {
    return "unsupported";
  }
  try {
    const status = await navigator.permissions.query({ name: "geolocation" as PermissionName });
    return status.state;
  } catch {
    return "unsupported";
  }
}

function formatCompactionStage(stage: string | null | undefined) {
  if (stage === "microcompact") return "最近压缩：Microcompact";
  if (stage === "checkpoint_compact") return "最近压缩：Checkpoint";
  return null;
}

function formatCompactionFailureReason(reason: string | null | undefined) {
  if (reason === "max_failures_reached") return "压缩连续失败次数已达上限";
  if (reason === "nothing_to_compress") return "已没有可继续裁剪的历史";
  if (reason === "post_compaction_still_over_limit") return "压缩后仍接近或超过预算";
  return reason ?? null;
}

function getApiBase() {
  if (import.meta.env.VITE_API_BASE) {
    return import.meta.env.VITE_API_BASE;
  }
  return window.location.origin;
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

function formatMessageTime(value: string | null | undefined) {
  if (!value) {
    return "--:--";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

async function copyTextToClipboard(value: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "true");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  textarea.style.pointerEvents = "none";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();

  const copied = document.execCommand("copy");
  document.body.removeChild(textarea);
  if (!copied) {
    throw new Error("copy_failed");
  }
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

function formatTokenCount(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "--";
  }
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 0 : 1)}m`;
  }
  if (value >= 1_000) {
    return `${(value / 1_000).toFixed(value >= 10_000 ? 0 : 1)}k`;
  }
  return `${Math.max(0, Math.round(value))}`;
}

function readUsageTokenCount(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? Math.round(value) : 0;
}

function buildTurnUsageSummaries(records: SessionUsageRecord[]) {
  const summaries: Record<string, TurnUsageSummary> = {};
  records.forEach((record) => {
    if (!record.turn_id) {
      return;
    }
    const current =
      summaries[record.turn_id] ??
      {
        requestCount: 0,
        missingCount: 0,
        inputTokens: 0,
        outputTokens: 0,
        totalTokens: 0,
      };
    const inputTokens = readUsageTokenCount(record.input_tokens);
    const outputTokens = readUsageTokenCount(record.output_tokens);
    const totalTokens = readUsageTokenCount(record.total_tokens) || inputTokens + outputTokens;
    current.requestCount += 1;
    current.inputTokens += inputTokens;
    current.outputTokens += outputTokens;
    current.totalTokens += totalTokens;
    if (!record.usage_available || totalTokens <= 0) {
      current.missingCount += 1;
    }
    summaries[record.turn_id] = current;
  });
  return summaries;
}

function formatTurnTokenUsage(usage: TurnUsageSummary | null | undefined) {
  if (!usage || usage.requestCount <= 0) {
    return null;
  }
  if (usage.totalTokens <= 0) {
    return "-- tokens";
  }
  return `${new Intl.NumberFormat("zh-CN").format(usage.totalTokens)} tokens`;
}

function formatTurnDuration(durationMs: number | null | undefined) {
  if (typeof durationMs !== "number" || !Number.isFinite(durationMs) || durationMs < 0) {
    return null;
  }
  const totalSeconds = Math.max(0, Math.round(durationMs / 1000));
  if (totalSeconds < 60) {
    return `${totalSeconds}s`;
  }
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes < 60) {
    return `${minutes}m${padTimePart(seconds)}s`;
  }
  const hours = Math.floor(minutes / 60);
  const remainderMinutes = minutes % 60;
  return `${hours}h${padTimePart(remainderMinutes)}m${padTimePart(seconds)}s`;
}

function makeAttachmentId(seed: string, index: number) {
  return `${seed}:${index}`;
}

function getAttachmentExtension(filename: string, fallback?: string | null) {
  if (typeof fallback === "string" && fallback.trim()) {
    return fallback.trim().toLowerCase().startsWith(".") ? fallback.trim().toLowerCase() : `.${fallback.trim().toLowerCase()}`;
  }
  const extension = filename.includes(".") ? `.${filename.split(".").pop()?.toLowerCase() ?? ""}` : "";
  return extension;
}

function isImageAttachmentExtension(extension: string) {
  return IMAGE_ATTACHMENT_EXTENSIONS.has(extension.toLowerCase());
}

function inferImageExtensionFromContentType(contentType: string) {
  const normalized = contentType.toLowerCase().split(";", 1)[0].trim();
  if (normalized === "image/png") return ".png";
  if (normalized === "image/jpeg" || normalized === "image/jpg") return ".jpg";
  if (normalized === "image/webp") return ".webp";
  return null;
}

function formatClipboardTimestamp(date: Date) {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

function normalizeClipboardAttachmentFile(file: File, index: number) {
  const extension = getAttachmentExtension(file.name).toLowerCase();
  if (file.name.trim() && COMPOSER_ATTACHMENT_EXTENSIONS.has(extension)) {
    return file;
  }

  const inferredExtension = inferImageExtensionFromContentType(file.type);
  if (!inferredExtension) {
    return file;
  }

  const baseName = file.name.trim().replace(/\.[^.]*$/, "") || `clipboard-${formatClipboardTimestamp(new Date())}-${index + 1}`;
  return new File([file], `${baseName}${inferredExtension}`, {
    type: file.type,
    lastModified: file.lastModified || Date.now(),
  });
}

function getClipboardImageFiles(clipboardData: DataTransfer) {
  const itemFiles = Array.from(clipboardData.items ?? [])
    .filter((item) => item.kind === "file" && item.type.toLowerCase().startsWith("image/"))
    .map((item) => item.getAsFile())
    .filter((file): file is File => Boolean(file));

  if (itemFiles.length > 0) {
    return itemFiles;
  }

  return Array.from(clipboardData.files ?? []).filter((file) => {
    if (file.type.toLowerCase().startsWith("image/")) {
      return true;
    }
    return isImageAttachmentExtension(getAttachmentExtension(file.name));
  });
}

function isImageAttachmentRecord(attachment: Pick<ChatAttachment, "contentType" | "filename" | "extension" | "kind">) {
  if (attachment.kind === "image") {
    return true;
  }
  if (attachment.contentType.toLowerCase().startsWith("image/")) {
    return true;
  }
  return isImageAttachmentExtension(getAttachmentExtension(attachment.filename, attachment.extension));
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
    const extension =
      "extension" in item && typeof item.extension === "string" && item.extension ? item.extension : getAttachmentExtension(filename);
    return [
      {
        id: makeAttachmentId("path" in item && typeof item.path === "string" ? item.path : filename, index),
        filename,
        contentType,
        source: "source" in item && typeof item.source === "string" ? item.source : null,
        kind: "kind" in item && typeof item.kind === "string" ? item.kind : null,
        extension,
        path: "path" in item && typeof item.path === "string" ? item.path : null,
        previewUrl: null,
        summary: "summary" in item && typeof item.summary === "string" ? item.summary : null,
        sizeBytes: "size_bytes" in item && typeof item.size_bytes === "number" ? item.size_bytes : null,
        workspaceRelativePath:
          "workspace_relative_path" in item && typeof item.workspace_relative_path === "string" ? item.workspace_relative_path : null,
        analysisStatus:
          "analysis_status" in item && typeof item.analysis_status === "string" ? item.analysis_status : null,
        analysisError:
          "analysis_error" in item && typeof item.analysis_error === "string" ? item.analysis_error : null,
      },
    ];
  });
}

function inferAttachmentContentType(filename: string, extension: string | null | undefined) {
  const normalizedExtension = getAttachmentExtension(filename, extension).toLowerCase();
  const normalized = normalizedExtension.replace(/^\./, "");
  if (isImageAttachmentExtension(normalizedExtension)) {
    return normalized === "svg" ? "image/svg+xml" : `image/${normalized === "jpg" ? "jpeg" : normalized}`;
  }
  if (normalized === "html" || normalized === "htm") {
    return "text/html";
  }
  if (normalized === "md" || normalized === "markdown") {
    return "text/markdown";
  }
  if (normalized === "txt") {
    return "text/plain";
  }
  if (normalized === "json") {
    return "application/json";
  }
  if (normalized === "pdf") {
    return "application/pdf";
  }
  return "application/octet-stream";
}

function inferAttachmentKind(filename: string, extension: string | null | undefined, contentType: string) {
  const normalizedExtension = getAttachmentExtension(filename, extension).toLowerCase();
  const normalized = normalizedExtension.replace(/^\./, "");
  if (contentType.startsWith("image/") || isImageAttachmentExtension(normalizedExtension)) {
    return "image";
  }
  if (contentType === "text/html" || normalized === "html" || normalized === "htm") {
    return "html";
  }
  return "document";
}

function isSessionOutputPath(
  path: string | null | undefined,
  workspaceRelativePath: string | null | undefined,
  sessionId: string
) {
  const expectedRelativePrefix = `outputs/chat/${sessionId}/`;
  const relative = (workspaceRelativePath || "").replace(/\\/g, "/").trim();
  if (relative) {
    return relative === expectedRelativePrefix.slice(0, -1) || relative.startsWith(expectedRelativePrefix);
  }
  const normalizedPath = (path || "").replace(/\\/g, "/");
  return normalizedPath.includes(`/${expectedRelativePrefix}`);
}

function buildOutputAttachmentsFromEvents(events: SessionEventPayload[], sessionId: string, _turnId: string) {
  const attachments: ChatAttachment[] = [];
  const seen = new Set<string>();
  const pushAttachment = (
    path: string,
    index: number,
    data: {
      bytes?: number | null;
      contentType?: string | null;
      summary?: string | null;
      workspaceRelativePath?: string | null;
    },
  ) => {
    if (!path || seen.has(path)) {
      return;
    }
    seen.add(path);
    const filename = extractName(path) || `output-${index + 1}`;
    const extension = getAttachmentExtension(filename, null);
    const contentType = data.contentType && data.contentType.trim() ? data.contentType : inferAttachmentContentType(filename, extension);
    attachments.push({
      id: makeAttachmentId(path, index),
      filename,
      contentType,
      source: "assistant_output",
      kind: inferAttachmentKind(filename, extension, contentType),
      extension,
      path,
      previewUrl: null,
      summary: data.summary ?? "生成文件",
      sizeBytes: typeof data.bytes === "number" ? data.bytes : null,
      workspaceRelativePath: data.workspaceRelativePath ?? null,
      analysisStatus: "completed",
      analysisError: null,
    });
  };

  events.forEach((event, index) => {
    if (event.event !== "tool_call_finished") {
      return;
    }
    const tool = typeof event.data.tool === "string" ? event.data.tool : "";
    const rawOutputFiles = Array.isArray(event.data.output_files) ? event.data.output_files : [];
    let hasExplicitOutputFiles = false;
    rawOutputFiles.forEach((rawItem, fileIndex) => {
      if (!rawItem || typeof rawItem !== "object") {
        return;
      }
      const path = typeof rawItem.path === "string" ? rawItem.path : "";
      if (!path) {
        return;
      }
      hasExplicitOutputFiles = true;
      const workspaceRelativePath =
        typeof rawItem.workspace_relative_path === "string" ? rawItem.workspace_relative_path : null;
      if (!isSessionOutputPath(path, workspaceRelativePath, sessionId)) {
        return;
      }
      pushAttachment(path, index * 100 + fileIndex, {
        bytes: typeof rawItem.bytes === "number" ? rawItem.bytes : null,
        contentType: typeof rawItem.content_type === "string" ? rawItem.content_type : null,
        summary:
          typeof rawItem.summary === "string"
            ? rawItem.summary
            : typeof event.data.summary === "string"
              ? event.data.summary
              : "生成文件",
        workspaceRelativePath,
      });
    });
    if (hasExplicitOutputFiles) {
      return;
    }
    if (tool !== "write_file" && tool !== "edit_file") {
      return;
    }
    if (event.data.success !== true) {
      return;
    }
    const path = getEventPathValue(event.data);
    if (!path || !isSessionOutputPath(path, null, sessionId)) {
      return;
    }
    pushAttachment(path, index, {
      bytes: typeof event.data.bytes === "number" ? event.data.bytes : null,
      contentType: typeof event.data.content_type === "string" ? event.data.content_type : null,
      summary: typeof event.data.summary === "string" ? event.data.summary : "生成文件",
      workspaceRelativePath: null,
    });
  });
  return attachments;
}

function mergeChatAttachments(primary: ChatAttachment[], fallback: ChatAttachment[]) {
  if (fallback.length === 0) {
    return primary;
  }
  const merged = [...primary];
  const seen = new Set(primary.map((attachment) => attachment.path || attachment.filename));
  fallback.forEach((attachment) => {
    const key = attachment.path || attachment.filename;
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    merged.push(attachment);
  });
  return merged;
}

function stripLegacyAttachmentAppendix(content: string) {
  const markers = [
    "\n\n## Uploaded Images",
    "\n\n## Uploaded Attachments",
    "\n\n## Attachment Observations",
    "\n\n## Multimodal Parse",
    "\n\n## Normalized User Input",
  ];
  for (const marker of markers) {
    const markerIndex = content.indexOf(marker);
    if (markerIndex !== -1) {
      const stripped = content.slice(0, markerIndex).trimEnd();
      if (stripped) {
        return stripped;
      }
    }
  }
  return content;
}

function readOriginalMessageContent(metadata: Record<string, unknown>, fallback: string) {
  if (typeof metadata.original_content === "string") {
    return metadata.original_content;
  }
  return stripLegacyAttachmentAppendix(fallback);
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

function orderSkillWorkspaceEntries(entries: WorkspaceEntry[], skillFilePath: string | null) {
  return [...entries].sort((left, right) => {
    const leftIsSkillFile = Boolean(skillFilePath && left.path === skillFilePath) || left.name.toLowerCase() === "skill.md";
    const rightIsSkillFile =
      Boolean(skillFilePath && right.path === skillFilePath) || right.name.toLowerCase() === "skill.md";

    if (leftIsSkillFile !== rightIsSkillFile) {
      return leftIsSkillFile ? -1 : 1;
    }

    if (left.type !== right.type) {
      return left.type === "dir" ? -1 : 1;
    }

    return left.name.localeCompare(right.name, "zh-CN", { sensitivity: "base" });
  });
}

function getSkillDirectoryPath(skillPath: string) {
  return extractParentPath(skillPath, null);
}

function getSkillUploadRelativePath(file: File) {
  const maybeDirectoryFile = file as File & { webkitRelativePath?: string };
  return maybeDirectoryFile.webkitRelativePath || file.name;
}

function summarizeSkillUploadFiles(files: SkillUploadItem[]) {
  if (files.length === 0) {
    return "尚未选择文件";
  }
  const totalBytes = files.reduce((sum, item) => sum + item.file.size, 0);
  const topNames = Array.from(new Set(files.map((item) => item.relativePath.split(/[\\/]/).filter(Boolean)[0] ?? item.file.name)));
  return `${files.length} 个文件 · ${formatBytes(totalBytes)} · ${topNames.slice(0, 2).join(" / ")}${topNames.length > 2 ? " ..." : ""}`;
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
  read_file_range: {
    label: "read_file_range",
    cardType: "file",
    runningText: "我先分段读取一下相关文本",
    completedText: "相关文本片段我已经看过了"
  },
  list_dir: { label: "list_dir", cardType: "file", runningText: "我先看一下目录结构", completedText: "目录结构我已经确认了" },
  list_files: { label: "list_files", cardType: "file", runningText: "我先整理一下文件列表", completedText: "文件列表我已经拿到了" },
  search_files: { label: "search_files", cardType: "search", runningText: "我先检索一下相关文件", completedText: "相关文件我已经找到了" },
  grep: { label: "grep", cardType: "search", runningText: "我先搜索一下文件内容", completedText: "匹配内容我已经找到了" },
  google_search: {
    label: "google_search",
    cardType: "search",
    runningText: "我先搜索相关网页资料",
    completedText: "网页搜索结果我已经拿到了"
  },
  fetch_url: { label: "fetch_url", cardType: "network", runningText: "我先看一下网页资料", completedText: "网页资料我已经取回来了" },
  terminal: { label: "terminal", cardType: "terminal", runningText: "我先运行一条命令确认情况", completedText: "命令我已经执行完了" },
  write_file: { label: "write_file", cardType: "file", runningText: "我先创建对应文件", completedText: "文件我已经创建好了" },
  edit_file: { label: "edit_file", cardType: "file", runningText: "我先修改对应文件", completedText: "文件我已经改好了" },
  request_user_input: {
    label: "等待用户输入",
    cardType: "generic",
    runningText: "我需要你确认后再继续",
    completedText: "正在等待你的确认"
  },
  update_plan: { label: "update_plan", cardType: "plan", runningText: "我先整理一下执行步骤", completedText: "执行步骤我已经更新了" },
  enter_plan_mode: {
    label: "enter_plan_mode",
    cardType: "plan",
    runningText: "我先切换到计划模式",
    completedText: "已经进入计划模式"
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

function TimelineMarkerIcon({ name, className }: { name: TimelineMarkerIconName; className?: string }) {
  const props = {
    viewBox: "0 0 20 20",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.35,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    className
  };

  if (name === "folder") {
    return (
      <svg {...props}>
        <path d="M2.75 6.5h4.1l1.9 2h8.5v7.25a1 1 0 0 1-1 1H3.75a1 1 0 0 1-1-1V7.5a1 1 0 0 1 1-1Z" />
        <path d="M2.75 8.5h14.5" />
      </svg>
    );
  }

  if (name === "file") {
    return (
      <svg {...props}>
        <path d="M5.5 2.75h5.5l3.5 3.5v10a1 1 0 0 1-1 1h-8a1 1 0 0 1-1-1v-12a1 1 0 0 1 1-1Z" />
        <path d="M11 2.75v3.5h3.5" />
        <path d="M7.25 10h5.5" />
        <path d="M7.25 13h5.5" />
      </svg>
    );
  }

  if (name === "file_plus") {
    return (
      <svg {...props}>
        <path d="M5.5 2.75h5.5l3.5 3.5v10a1 1 0 0 1-1 1h-8a1 1 0 0 1-1-1v-12a1 1 0 0 1 1-1Z" />
        <path d="M11 2.75v3.5h3.5" />
        <path d="M10 9.5v5" />
        <path d="M7.5 12h5" />
      </svg>
    );
  }

  if (name === "file_edit") {
    return (
      <svg {...props}>
        <path d="M5.5 2.75h5.5l3.5 3.5v10a1 1 0 0 1-1 1h-8a1 1 0 0 1-1-1v-12a1 1 0 0 1 1-1Z" />
        <path d="M11 2.75v3.5h3.5" />
        <path d="m7.25 13.75 5.2-5.2 1.3 1.3-5.2 5.2-2 .7.7-2Z" />
      </svg>
    );
  }

  if (name === "search") {
    return (
      <svg {...props}>
        <circle cx="8.75" cy="8.75" r="4.75" />
        <path d="m12.4 12.4 4.1 4.1" />
      </svg>
    );
  }

  if (name === "code_search") {
    return (
      <svg {...props}>
        <path d="m5.25 8.5-2.5 2 2.5 2" />
        <path d="m14.75 8.5 2.5 2-2.5 2" />
        <circle cx="10" cy="10" r="2.75" />
        <path d="m12.1 12.1 2.65 2.65" />
      </svg>
    );
  }

  if (name === "globe") {
    return (
      <svg {...props}>
        <circle cx="10" cy="10" r="7" />
        <path d="M3.75 10h12.5" />
        <path d="M10 3c1.8 1.9 2.75 4.28 2.75 7s-.95 5.1-2.75 7" />
        <path d="M10 3c-1.8 1.9-2.75 4.28-2.75 7s.95 5.1 2.75 7" />
      </svg>
    );
  }

  if (name === "terminal") {
    return (
      <svg {...props}>
        <rect x="2.75" y="4" width="14.5" height="12" rx="2.25" />
        <path d="m6 8.25 2.25 1.75L6 11.75" />
        <path d="M10.5 12h3.5" />
      </svg>
    );
  }

  if (name === "plan") {
    return (
      <svg {...props}>
        <path d="M6 4.25h8a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-10a1 1 0 0 1 1-1Z" />
        <path d="M7.5 2.75h5" />
        <path d="M7.75 8h4.75" />
        <path d="M7.75 11h4.75" />
        <path d="m6.25 7.75.8.8 1.2-1.55" />
        <path d="m6.25 10.75.8.8 1.2-1.55" />
      </svg>
    );
  }

  if (name === "approval") {
    return (
      <svg {...props}>
        <path d="M10 2.9 14.7 4.7v4.45c0 3-1.78 5.5-4.7 6.95-2.92-1.45-4.7-3.95-4.7-6.95V4.7L10 2.9Z" />
        <path d="m7.45 10.1 1.45 1.5 3.2-3.35" />
      </svg>
    );
  }

  if (name === "image") {
    return (
      <svg {...props}>
        <rect x="3" y="4" width="14" height="12" rx="2" />
        <circle cx="7.2" cy="8.2" r="1.3" />
        <path d="m5 14 3.4-3.6 2.6 2.6 1.9-1.9L15 14" />
      </svg>
    );
  }

  if (name === "answer") {
    return (
      <svg {...props}>
        <circle cx="10" cy="10" r="7" />
        <path d="m6.7 10.1 2.1 2.25 4.5-4.8" />
      </svg>
    );
  }

  return (
    <svg {...props}>
      <rect x="4" y="4" width="5" height="5" rx="1" />
      <rect x="11" y="4" width="5" height="5" rx="1" />
      <rect x="4" y="11" width="5" height="5" rx="1" />
      <rect x="11" y="11" width="5" height="5" rx="1" />
    </svg>
  );
}

function CopyMiniIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.25}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <rect x="5.1" y="2.9" width="7.1" height="8.6" rx="1.4" />
      <path d="M4.3 5.3H3.6a1.3 1.3 0 0 0-1.3 1.3v5.1A1.3 1.3 0 0 0 3.6 13h5.1A1.3 1.3 0 0 0 10 11.7V11" />
    </svg>
  );
}

function CopySuccessMiniIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.35}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M6.05 2.9h4.35l2.75 2.75v5.9a1.45 1.45 0 0 1-1.45 1.45h-5.65A1.45 1.45 0 0 1 4.6 11.55V4.35A1.45 1.45 0 0 1 6.05 2.9Z" />
      <path d="M10.4 2.9v2.75h2.75" />
      <path d="m6.7 8.35 1.1 1.15 2.25-2.4" />
    </svg>
  );
}

function SkillSidebarIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.4}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <rect x="2.75" y="3.25" width="14.5" height="11.5" rx="2.25" />
      <path d="M6 16.25h8" />
      <path d="M8 8.75h1.75l1-1.85 1.25 3 1-1.6H14" />
    </svg>
  );
}

function SkillFolderIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.4}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M2.75 6.5h4.05l1.7 1.8h8.75v7a1 1 0 0 1-1 1H3.75a1 1 0 0 1-1-1v-7.8a1 1 0 0 1 1-1Z" />
    </svg>
  );
}

function SkillFileIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.35}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M5.75 2.75h5l3.5 3.5v9a1 1 0 0 1-1 1h-7.5a1 1 0 0 1-1-1v-11.5a1 1 0 0 1 1-1Z" />
      <path d="M10.75 2.75v3.5h3.5" />
      <path d="M7.3 10h5.3" />
    </svg>
  );
}

function ChevronStrokeIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="m4.25 6 3.75 4 3.75-4" />
    </svg>
  );
}

function PlusSmallIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M8 3.25v9.5" />
      <path d="M3.25 8h9.5" />
    </svg>
  );
}

function ScheduledSessionIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.35}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <rect x="2.75" y="3.25" width="10.5" height="10" rx="1.25" />
      <path d="M5 2.25v2" />
      <path d="M11 2.25v2" />
      <path d="M2.75 6.25h10.5" />
      <path d="M5.2 9.2h2.1" />
      <path d="M5.2 11.35h4.7" />
    </svg>
  );
}

function ApprovalSmallIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.25}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M8 2.75 9.35 4.1l1.9-.1.42 1.86 1.52 1.13-.94 1.66.36 1.88-1.8.6L9.75 12.7 8 11.95l-1.75.75-1.06-1.57-1.8-.6.36-1.88-.94-1.66L4.33 5.86 4.75 4l1.9.1L8 2.75Z" />
      <path d="m6.25 8.1 1.15 1.15L9.8 6.85" />
    </svg>
  );
}

function PlanChecklistStatusIcon({ status, className }: { status: PlanStepStatus; className?: string }) {
  if (status === "completed") {
    return (
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
        <circle cx="8" cy="8" r="5.75" />
        <path d="m5.4 8.1 1.7 1.7 3.5-3.6" />
      </svg>
    );
  }

  if (status === "in_progress") {
    return (
      <svg viewBox="0 0 16 16" fill="none" className={className} aria-hidden="true">
        <circle cx="8" cy="8" r="5.75" stroke="currentColor" strokeWidth={1.4} opacity="0.28" />
        <circle cx="8" cy="8" r="2.25" fill="currentColor" />
      </svg>
    );
  }

  if (status === "blocked") {
    return (
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.45} strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
        <path d="M8 2.4 13.1 5.2v5.6L8 13.6l-5.1-2.8V5.2L8 2.4Z" />
        <path d="M8 5.35v3.2" />
        <circle cx="8" cy="10.85" r="0.45" fill="currentColor" stroke="none" />
      </svg>
    );
  }

  if (status === "cancelled") {
    return (
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.45} strokeLinecap="round" className={className} aria-hidden="true">
        <circle cx="8" cy="8" r="5.75" />
        <path d="M5.4 5.4 10.6 10.6" />
      </svg>
    );
  }

  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.4} className={className} aria-hidden="true">
      <circle cx="8" cy="8" r="5.75" />
    </svg>
  );
}

function RefreshSmallIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M13 5.2A5 5 0 1 0 14 8" />
      <path d="M13 2.75v2.75h-2.75" />
    </svg>
  );
}

function EyePanelIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.25}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M1.65 8c1.52-2.39 3.64-3.6 6.35-3.6S12.83 5.61 14.35 8c-1.52 2.39-3.64 3.6-6.35 3.6S3.17 10.39 1.65 8Z" />
      <circle cx="8" cy="8" r="2.05" />
    </svg>
  );
}

function CodePanelIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.35}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M6.35 4.25 3 8l3.35 3.75" />
      <path d="m9.65 4.25 3.35 3.75-3.35 3.75" />
    </svg>
  );
}

function ClosePanelIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.45}
      strokeLinecap="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M4 4 12 12" />
      <path d="M12 4 4 12" />
    </svg>
  );
}

type MessageHoverShellProps = {
  shellClassName: "user" | "assistant";
  align: "start" | "end";
  timestamp: string;
  copyValue?: string | null;
  copyLabel: string;
  showMeta?: boolean;
  turnUsage?: TurnUsageSummary | null;
  durationMs?: number | null;
  children: ReactNode;
};

function MessageHoverShell({
  shellClassName,
  align,
  timestamp,
  copyValue,
  copyLabel,
  showMeta = true,
  turnUsage = null,
  durationMs = null,
  children,
}: MessageHoverShellProps) {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const canCopy = Boolean(copyValue && copyValue.trim());
  const copyTitle =
    copyState === "copied" ? "已复制" : copyState === "failed" ? "复制失败，请重试" : `复制${copyLabel}`;
  const tokenLabel = formatTurnTokenUsage(turnUsage);
  const durationLabel = formatTurnDuration(durationMs);

  function resetCopyState() {
    setCopyState("idle");
  }

  async function handleCopy() {
    if (!copyValue || !copyValue.trim()) {
      return;
    }

    try {
      await copyTextToClipboard(copyValue);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  }

  return (
    <div className={`message-hover-shell ${shellClassName}`} onMouseLeave={resetCopyState}>
      {children}
      {showMeta ? (
        <div className={`message-hover-meta align-${align}`}>
          {canCopy ? (
            <button
              type="button"
              className={`message-hover-copy is-${copyState}`}
              onClick={() => {
                void handleCopy();
              }}
              aria-label={copyTitle}
              title={copyTitle}
            >
              {copyState === "copied" ? (
                <CopySuccessMiniIcon className="message-hover-copy-icon" />
              ) : (
                <CopyMiniIcon className="message-hover-copy-icon" />
              )}
            </button>
          ) : null}
          <span className="message-hover-time" aria-label={`消息时间 ${formatDateTime(timestamp)}`}>
            {formatMessageTime(timestamp)}
          </span>
          {tokenLabel ? (
            <span
              className="message-hover-stat"
              aria-label={`本轮 token 消耗 ${tokenLabel}`}
              title={`本轮 token 消耗 ${tokenLabel}`}
            >
              {tokenLabel}
            </span>
          ) : null}
          {durationLabel ? (
            <span
              className="message-hover-stat"
              aria-label={`本轮耗时 ${durationLabel}`}
              title={`本轮耗时 ${durationLabel}`}
            >
              {durationLabel}
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function resolveTimelineNodeIcon(node: TimelineNode): TimelineMarkerIconName {
  if (node.kind === "approval") return "approval";
  if (node.kind === "answer_start") return "answer";

  const latestItem = [...node.secondaryItems].reverse().find((item) => item.toolName || item.cardType);
  const toolName = latestItem?.toolName ?? null;

  if (toolName === "request_user_input") return "approval";
  if (toolName === "list_dir" || toolName === "list_files") return "folder";
  if (toolName === "read_file" || toolName === "read_file_range") return "file";
  if (toolName === "write_file") return "file_plus";
  if (toolName === "edit_file") return "file_edit";
  if (toolName === "search_files") return "search";
  if (toolName === "grep") return "code_search";
  if (toolName === "fetch_url") return "globe";
  if (toolName === "terminal") return "terminal";
  if (toolName === "update_plan" || toolName === "enter_plan_mode") return "plan";
  if (toolName && toolName.startsWith("mcp__")) return "generic";

  if (latestItem?.cardType === "file") return "file";
  if (latestItem?.cardType === "search") return "search";
  if (latestItem?.cardType === "network") return "globe";
  if (latestItem?.cardType === "terminal") return "terminal";
  if (latestItem?.cardType === "plan") return "plan";
  if (latestItem?.cardType === "attachment") return "image";

  return "generic";
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

const HASH_PATH_SEGMENT_RE = /^[0-9a-f]{16,}$/i;
const COMPACT_HASH_PATH_RE = /(?:…\/)?(?:[0-9a-f]{16,}\/)+[0-9a-f]{16,}(?:\.[A-Za-z0-9]+)?/gi;

function isHashPathSegment(value: string) {
  const stem = value.replace(/\.[^.]+$/, "");
  return HASH_PATH_SEGMENT_RE.test(stem);
}

function formatToolPathTarget(path: string | null | undefined) {
  if (!path) {
    return null;
  }
  const normalized = path.trim().replace(/\\/g, "/");
  if (!normalized) {
    return null;
  }
  if (`/${normalized}`.includes("/parser_outputs/chat/")) {
    return "匹配到的解析文档";
  }
  if (`/${normalized}`.includes("/user_uploads/chat/")) {
    return "上传附件";
  }
  const parts = normalized.split("/").filter(Boolean);
  if (parts.length >= 2 && isHashPathSegment(parts[parts.length - 1]) && parts.slice(0, -1).some(isHashPathSegment)) {
    return "内部生成文档";
  }
  return formatCompactPath(path);
}

function sanitizeActionBriefForDisplay(value: string) {
  return value
    .replace(/(?:…\/)?(?:parser_outputs|user_uploads)\/chat\/[^\s，。；,;]+/gi, "匹配到的解析文档")
    .replace(COMPACT_HASH_PATH_RE, "匹配到的解析文档")
    .replace(/\s+/g, " ")
    .trim();
}

function getEventPathValue(eventData: Record<string, unknown>) {
  const argumentsPayload = extractEventArguments(eventData);
  const rawPath =
    (typeof eventData.path === "string" ? eventData.path : null) ??
    (argumentsPayload && typeof argumentsPayload.path === "string" ? argumentsPayload.path : null);
  return rawPath?.trim() || null;
}

function isHtmlPath(path: string | null | undefined) {
  return Boolean(path && /\.(html|htm)$/i.test(path.split(/[?#]/, 1)[0]));
}

function looksLikeHtmlMarkup(content: string | null | undefined) {
  const normalized = (content ?? "").trimStart().toLowerCase();
  return normalized.startsWith("<!doctype html") || normalized.startsWith("<html") || normalized.includes("<body");
}

function buildHtmlPreviewTitleFromMarkup(markup: string, fallback = "HTML 实时预览") {
  const titleMatch = markup.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
  if (titleMatch?.[1]) {
    const normalized = titleMatch[1].replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
    if (normalized) {
      return compactString(normalized, 48);
    }
  }

  const headingMatch = markup.match(/<h1[^>]*>([\s\S]*?)<\/h1>/i);
  if (headingMatch?.[1]) {
    const normalized = headingMatch[1].replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
    if (normalized) {
      return compactString(normalized, 48);
    }
  }

  return fallback;
}

function patchHtmlPreviewMarkupForSandbox(markup: string) {
  return markup
    .replace(/\b(?:window|self|globalThis)\s*\.\s*parent\s*\.\s*document\b/g, "document")
    .replace(/\b(?:window|self|globalThis)\s*\.\s*top\s*\.\s*document\b/g, "document")
    .replace(/\bparent\s*\.\s*document\b/g, "document")
    .replace(/\btop\s*\.\s*document\b/g, "document");
}

function isHtmlWriteFileEventData(eventData: Record<string, unknown>) {
  if (eventData.tool !== "write_file") {
    return false;
  }
  const path = getEventPathValue(eventData);
  if (isHtmlPath(path)) {
    return true;
  }
  const argumentsPayload = extractEventArguments(eventData);
  const content = argumentsPayload && typeof argumentsPayload.content === "string" ? argumentsPayload.content : null;
  return looksLikeHtmlMarkup(content);
}

function extractSkillNameFromPath(path: string | null | undefined) {
  if (!path) {
    return null;
  }
  const normalized = path.replace(/\\/g, "/").replace(/\/+$/, "");
  const parts = normalized.split("/").filter(Boolean);
  const fileName = parts[parts.length - 1]?.toLowerCase();
  if (fileName !== "skill.md" || parts.length < 2) {
    return null;
  }
  const skillsIndex = parts.lastIndexOf("skills");
  if (skillsIndex >= 0 && parts[skillsIndex + 1] && parts[skillsIndex + 1].toLowerCase() !== "skill.md") {
    return parts[skillsIndex + 1];
  }
  return parts[parts.length - 2] || null;
}

function resolveSkillNameFromEventData(eventData: Record<string, unknown>) {
  const explicitSkillName = typeof eventData.skill_name === "string" && eventData.skill_name.trim()
    ? eventData.skill_name.trim()
    : null;
  return explicitSkillName ?? extractSkillNameFromPath(getEventPathValue(eventData));
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

const TIMELINE_PRIMARY_TEXT_MAX_CHARS = 96;
const TIMELINE_STRUCTURED_COPY_RE = /(^|\n)\s*(?:#{1,6}\s+|\d+[.、]\s+|[-*]\s+)/;

function looksStructuredTimelineCopy(raw: string, normalized: string) {
  if (normalized.length > TIMELINE_PRIMARY_TEXT_MAX_CHARS * 2) {
    return true;
  }
  if (raw.includes("\n") && TIMELINE_STRUCTURED_COPY_RE.test(raw)) {
    return true;
  }
  if (normalized.includes("## ") || normalized.includes("# ")) {
    return true;
  }
  return false;
}

function isWeakProgressPrimaryText(value: string | null | undefined) {
  const raw = value ?? "";
  const normalized = raw.replace(/\s+/g, " ").trim();
  if (
    !normalized ||
    normalized === "我先继续处理这一步" ||
    normalized === "我先获取完成任务需要的信息" ||
    /^正在准备 .+ 调用参数(?:（[^）]+）)?$/.test(normalized)
  ) {
    return true;
  }
  return looksStructuredTimelineCopy(raw, normalized);
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
    return formatToolPathTarget(rawPath);
  }

  const rawQuery =
    (typeof eventData.query === "string" ? eventData.query : null) ??
    (typeof eventData.q === "string" ? eventData.q : null) ??
    (argumentsPayload && typeof argumentsPayload.query === "string" ? argumentsPayload.query : null) ??
    (argumentsPayload && typeof argumentsPayload.q === "string" ? argumentsPayload.q : null);
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
  _userPrompt?: string | null
) {
  const semantic = resolveToolSemantic(toolName);
  const actionBrief = typeof eventData.action_brief === "string" ? eventData.action_brief.trim() : "";
  const summaryText = typeof eventData.summary_text === "string" ? eventData.summary_text : null;
  const target = resolveToolTarget(toolName, eventData);
  const skillName = resolveSkillNameFromEventData(eventData);

  if (actionBrief) {
    return compactString(sanitizeActionBriefForDisplay(actionBrief), TIMELINE_PRIMARY_TEXT_MAX_CHARS);
  }

  if (summaryText) {
    return summaryText;
  }

  if (status === "failed") {
    return typeof eventData.frontend_message === "string" && eventData.frontend_message
      ? eventData.frontend_message
      : "这一步暂时没有成功";
  }

  if ((toolName === "read_file" || toolName === "read_file_range") && skillName) {
    return status === "running"
      ? `我先读取 ${skillName} Skill 说明，确认该按什么流程做`
      : `已读取 ${skillName} Skill 说明，接下来按这个流程执行`;
  }

  if (status === "running") {
    if (toolName === "read_file" || toolName === "read_file_range") {
      return target ? `我先读取 ${target}，确认里面有哪些可用信息` : semantic.runningText;
    }
    if (toolName === "search_files" || toolName === "grep") {
      return target ? `我先检索 ${target}，定位相关内容` : semantic.runningText;
    }
    if (toolName === "google_search") {
      return target ? `我先搜索 ${target}，确认可引用的信息来源` : semantic.runningText;
    }
    if (toolName === "list_dir" || toolName === "list_files") {
      return target ? `我先查看 ${target} 的结构` : semantic.runningText;
    }
    if (toolName === "update_plan") {
      return "我先把已知信息拆成执行步骤";
    }
    if (toolName === "write_file") {
      if (isHtmlWriteFileEventData(eventData)) {
        return target ? `正在生成 ${target}，预览会随内容更新` : "正在生成 HTML 文件，预览会随内容更新";
      }
      return target ? `我正在创建 ${target}` : semantic.runningText;
    }
    if (toolName === "edit_file") {
      return target ? `我正在修改 ${target}` : semantic.runningText;
    }
    if (toolName === "fetch_url") {
      return target ? `我先读取 ${target} 的网页资料` : semantic.runningText;
    }
    if (toolName === "terminal") {
      return "我先运行命令确认当前状态";
    }
    if (toolName === "request_user_input") {
      return "我需要你确认后再继续";
    }
    return semantic.runningText;
  }

  const count = inferResultCount(toolName, output ?? null);
  if (typeof count === "number") {
    if (toolName === "search_files") {
      return `已找到 ${count} 个相关文件`;
    }
    if (toolName === "grep") {
      return `已找到 ${count} 处匹配`;
    }
  }

  if (toolName === "read_file" || toolName === "read_file_range") {
    return target ? `已从 ${target} 获取到可用信息` : semantic.completedText;
  }
  if (toolName === "list_dir" || toolName === "list_files") {
    return target ? `已确认 ${target} 的结构` : semantic.completedText;
  }
  if (toolName === "google_search") {
    return target ? `已拿到 ${target} 的搜索结果` : semantic.completedText;
  }
  if (toolName === "update_plan") {
    return "执行步骤我已经整理好了";
  }
  if (toolName === "write_file") {
    if (isHtmlWriteFileEventData(eventData)) {
      if (eventData.success === false) {
        return target ? `HTML 写入失败：${target}` : "HTML 写入失败";
      }
      return target ? `HTML 文件已经生成：${target}` : "HTML 文件已经生成";
    }
    return target ? `文件已经创建：${target}` : semantic.completedText;
  }
  if (toolName === "edit_file") {
    return target ? `文件已经修改：${target}` : semantic.completedText;
  }
  if (toolName === "request_user_input") {
    return "正在等待你的确认";
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
  if (toolName === "request_user_input") {
    const awaiting = parseAwaitingUserInputFromToolArguments(args);
    return awaiting ? getAwaitingInputTitle(awaiting) : "等待用户确认";
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
  return "";
}

function buildTimelineToolSummary(node: TimelineNode) {
  if (node.secondaryItems.some((item) => item.toolName === "request_user_input")) {
    return "确认后继续";
  }

  const labels = Array.from(
    new Set(
      node.secondaryItems
        .map((item) => (item.toolName && item.toolName.trim() ? item.toolName.trim() : item.label.trim()))
        .filter(Boolean)
    )
  );

  if (labels.length === 0) {
    return "查看步骤详情";
  }
  if (labels.length === 1) {
    return `调用 ${labels[0]}`;
  }
  if (labels.length === 2) {
    return `调用 ${labels[0]} · ${labels[1]}`;
  }
  return `调用 ${labels[0]} 等 ${labels.length} 个步骤`;
}

function buildTimelineSecondaryResultText(item: TimelineSecondaryItem, options?: { isTurnRunning?: boolean }) {
  const output = item.output?.trim();
  if (output) {
    return output;
  }

  if (options?.isTurnRunning) {
    if (item.state === "pending") {
      return "等待审批通过后开始执行。";
    }
    if (item.state === "recovering") {
      return "正在恢复执行，请稍后查看结果。";
    }
    if (item.state === "running") {
      return "正在执行中，结果返回后会显示在这里。";
    }
  }

  const summary = item.detail.summary.trim();
  if (summary) {
    return summary;
  }

  if (item.toolName !== "terminal") {
    const subtitle = item.subtitle.trim();
    if (subtitle) {
      return subtitle;
    }
  }

  if (item.state === "running") {
    return "正在执行中，结果返回后会显示在这里。";
  }
  if (item.state === "failed" || item.state === "rejected") {
    return "执行失败，当前没有更多可展示的结果。";
  }
  if (item.state === "pending") {
    return "等待审批通过后开始执行。";
  }
  if (item.state === "recovering") {
    return "正在恢复执行，请稍后查看结果。";
  }
  return "本次调用没有返回可展示的结果。";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function buildTimelineCodePreview(toolName: string | null | undefined, rawText: string, source?: unknown) {
  let content = rawText;
  let language: string | null = null;

  if (toolName === "write_file" && isRecord(source)) {
    const path = typeof source.path === "string" ? source.path : null;
    const fileContent = typeof source.content === "string" ? source.content.trim() : "";
    if (fileContent) {
      content = fileContent;
      language = inferLanguageFromPath(path);
    }
  } else if (toolName === "terminal") {
    language = "bash";
  }

  const highlighted = highlightCode(content, language);
  return {
    content,
    language: highlighted.language,
    html: highlighted.html,
  };
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
      const nestedError =
        "error" in payload && payload.error && typeof payload.error === "object" ? payload.error : null;
      const detail =
        "detail" in payload
          ? payload.detail
          : "message" in payload
            ? payload.message
            : nestedError && "message" in nestedError
              ? nestedError.message
              : null;
      if (typeof detail === "string" && detail.trim()) {
        message = detail;
      }
    }
    throw new Error(message);
  }

  return payload as T;
}

function isAbortError(error: unknown) {
  return error instanceof Error && error.name === "AbortError";
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

function readLiveEventText(event: SessionEventPayload, key: string) {
  const value = event.data[key];
  return typeof value === "string" ? value : "";
}

function hasLiveEventText(event: SessionEventPayload, key: string) {
  return Boolean(readLiveEventText(event, key));
}

function sameLiveEventScope(left: SessionEventPayload, right: SessionEventPayload, keys: string[]) {
  if (left.event !== right.event || left.request_id !== right.request_id) {
    return false;
  }
  return keys.every((key) => readLiveEventText(left, key) === readLiveEventText(right, key));
}

function mergeLiveSessionEvent(previous: SessionEventPayload, next: SessionEventPayload) {
  if (
    next.event === "tool_call_output_delta" &&
    hasLiveEventText(next, "tool_call_id") &&
    sameLiveEventScope(previous, next, ["turn_id", "group_id", "tool_call_id", "stream"])
  ) {
    return {
      ...next,
      data: {
        ...previous.data,
        ...next.data,
        delta: `${readLiveEventText(previous, "delta")}${readLiveEventText(next, "delta")}`,
      },
    };
  }

  if (
    next.event === "tool_call_arguments_delta" &&
    hasLiveEventText(next, "tool_call_id") &&
    sameLiveEventScope(previous, next, ["turn_id", "group_id", "tool_call_id"])
  ) {
    return next;
  }

  if (
    (next.event === "thinking_delta" || next.event === "commentary_delta") &&
    (hasLiveEventText(next, "turn_id") || hasLiveEventText(next, "group_id")) &&
    sameLiveEventScope(previous, next, ["turn_id", "group_id"])
  ) {
    return {
      ...next,
      data: {
        ...previous.data,
        ...next.data,
        delta: `${readLiveEventText(previous, "delta")}${readLiveEventText(next, "delta")}`,
      },
    };
  }

  return null;
}

function coalesceLiveSessionEvents(events: SessionEventPayload[]) {
  const coalesced: SessionEventPayload[] = [];
  events.forEach((event) => {
    const previous = coalesced[coalesced.length - 1];
    const merged = previous ? mergeLiveSessionEvent(previous, event) : null;
    if (merged) {
      coalesced[coalesced.length - 1] = merged;
      return;
    }
    coalesced.push(event);
  });
  return coalesced;
}

function mapSessionSummary(record: SessionSummaryRecord): ChatSession {
  return {
    id: record.session_id,
    title: record.title,
    updatedAt: record.updated_at,
    messageCount: record.message_count,
    hasConversation: record.message_count > 0,
    background: record.background === true,
    scheduled: record.scheduled === true,
    triggerType: typeof record.trigger_type === "string" ? record.trigger_type : null,
    sourceTaskId: typeof record.source_task_id === "string" ? record.source_task_id : null
  };
}

function scheduledSessionTitle(title: string) {
  return title.replace(/^\[Scheduled\]\s*/i, "").trim() || "定时任务";
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

function isMachineApprovalReason(reason: string | null | undefined) {
  const normalized = (reason ?? "").trim();
  if (!normalized || normalized === "requires_approval") {
    return true;
  }
  return /^[a-z0-9_.,:/-]+$/i.test(normalized);
}

function resolveApprovalTargetLabel(request: ApprovalRequestLike) {
  return resolveToolTarget(request.tool, {
    tool: request.tool,
    arguments: request.arguments
  });
}

function buildApprovalActionText(toolName: string, argumentsPayload: Record<string, unknown>) {
  if (toolName === "enter_plan_mode") {
    return "进入计划模式";
  }
  const target = resolveApprovalTargetLabel({
    tool: toolName,
    arguments: argumentsPayload,
    reason: "requires_approval"
  });
  if (toolName === "terminal") {
    return "执行命令";
  }
  if (toolName === "write_file") {
    return target ? `创建 ${target}` : "创建文件";
  }
  if (toolName === "edit_file") {
    return target ? `修改 ${target}` : "修改文件";
  }
  if (toolName === "read_file" || toolName === "read_file_range") {
    return target ? `读取 ${target}` : "读取文件";
  }
  if (target) {
    return `处理 ${target}`;
  }
  return "";
}

function buildApprovalOperationText(request: ApprovalRequestLike) {
  const action = buildApprovalActionText(request.tool, request.arguments);
  if (action) {
    return `调用 ${request.tool}，${action}`;
  }
  return `调用 ${request.tool}`;
}

function buildApprovalPrompt(request: ApprovalRequestLike) {
  return `需要获取你的确认：${buildApprovalOperationText(request)}`;
}

function buildApprovalSupportCopy(request: ApprovalRequestLike) {
  const normalizedReason = request.reason?.trim() ?? "";
  if (request.tool === "enter_plan_mode") {
    return "确认后我会切换到计划模式，先拆出待办清单，再按步骤执行并持续更新进度。";
  }
  if (normalizedReason && !isMachineApprovalReason(normalizedReason)) {
    return "确认后我会继续执行这一步；如果拒绝，本次调用会立即停止。";
  }
  if (request.tool === "terminal") {
    return "确认后会继续执行这条命令；如果拒绝，本次调用会立即停止。";
  }
  return "确认后我会继续执行这一步；如果拒绝，本次调用会立即停止。";
}

function buildApprovalPayloadLabel(request: ApprovalRequestLike) {
  if (request.tool === "enter_plan_mode") {
    return "切换说明";
  }
  if (request.tool === "terminal") {
    const command = typeof request.arguments.command === "string" ? request.arguments.command.trim() : "";
    if (command) {
      return "执行命令";
    }
  }
  return "参数预览";
}

function buildApprovalPayloadPreview(request: ApprovalRequestLike) {
  if (request.tool === "enter_plan_mode") {
    const reason = typeof request.arguments.reason === "string" ? request.arguments.reason.trim() : "";
    return reason || "准备进入计划模式";
  }
  if (request.tool === "terminal") {
    const command = typeof request.arguments.command === "string" ? request.arguments.command.trim() : "";
    if (command) {
      return command;
    }
  }
  if (request.tool === "write_file") {
    const content = typeof request.arguments.content === "string" ? request.arguments.content.trim() : "";
    if (content) {
      return content;
    }
  }
  return stringifyForPanel(request.arguments);
}

function buildApprovalNodePrimaryText(approval: ApprovalNodePayload, state: TimelineNodeState) {
  const operation = buildApprovalOperationText(approval);
  if (state === "approved") {
    return `已确认${operation}`;
  }
  if (state === "rejected" || state === "failed") {
    return `已拒绝${operation}`;
  }
  return buildApprovalPrompt(approval);
}

function buildApprovalNodeSupportCopy(approval: ApprovalNodePayload, state: TimelineNodeState) {
  const summary = approval.summary?.trim() ?? "";
  const normalizedReason = approval.reason?.trim() ?? "";
  if (state === "approved") {
    return "这一步已经继续执行，后续结果会继续出现在时间线里。";
  }
  if (state === "rejected" || state === "failed") {
    return "当前调用已停止；如果需要，我可以换一种更低风险的方式继续。";
  }
  if (summary) {
    return summary;
  }
  if (normalizedReason && !isMachineApprovalReason(normalizedReason)) {
    return normalizedReason;
  }
  return buildApprovalSupportCopy(approval);
}

function buildApprovalStateLabel(state: TimelineNodeState) {
  if (state === "approved") {
    return "已允许";
  }
  if (state === "rejected" || state === "failed") {
    return "已拒绝";
  }
  return "待确认";
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

function normalizePlanStepStatus(status: string | null | undefined): PlanStepStatus {
  if (status === "in_progress" || status === "completed" || status === "blocked" || status === "cancelled") {
    return status;
  }
  return "pending";
}

function getPlanSteps(plan: SessionPlanPayload) {
  if (!plan?.steps || !Array.isArray(plan.steps)) {
    return [];
  }
  return plan.steps
    .filter((step): step is { step: string; status: PlanStepStatus | string } => Boolean(step && typeof step.step === "string"))
    .map((step, index) => ({
      id: `plan-step-${index}`,
      index,
      step: step.step,
      status: normalizePlanStepStatus(step.status)
    }));
}

function getPlanProgress(plan: SessionPlanPayload) {
  const steps = getPlanSteps(plan);
  if (plan?.progress && typeof plan.progress === "object") {
    return {
      total: typeof plan.progress.total === "number" ? plan.progress.total : steps.length,
      completed: typeof plan.progress.completed === "number" ? plan.progress.completed : steps.filter((step) => step.status === "completed").length,
      inProgress: typeof plan.progress.in_progress === "number" ? plan.progress.in_progress : steps.filter((step) => step.status === "in_progress").length,
      blocked: typeof plan.progress.blocked === "number" ? plan.progress.blocked : steps.filter((step) => step.status === "blocked").length,
      pending: typeof plan.progress.pending === "number" ? plan.progress.pending : steps.filter((step) => step.status === "pending").length,
      cancelled: typeof plan.progress.cancelled === "number" ? plan.progress.cancelled : steps.filter((step) => step.status === "cancelled").length
    };
  }
  return {
    total: steps.length,
    completed: steps.filter((step) => step.status === "completed").length,
    inProgress: steps.filter((step) => step.status === "in_progress").length,
    blocked: steps.filter((step) => step.status === "blocked").length,
    pending: steps.filter((step) => step.status === "pending").length,
    cancelled: steps.filter((step) => step.status === "cancelled").length
  };
}

function buildPlanProgressFromRawSteps(steps: Array<{ step: string; status: PlanStepStatus | string }>) {
  const normalizedSteps = steps.map((step) => normalizePlanStepStatus(step.status));
  return {
    total: steps.length,
    completed: normalizedSteps.filter((status) => status === "completed").length,
    in_progress: normalizedSteps.filter((status) => status === "in_progress").length,
    blocked: normalizedSteps.filter((status) => status === "blocked").length,
    pending: normalizedSteps.filter((status) => status === "pending").length,
    cancelled: normalizedSteps.filter((status) => status === "cancelled").length,
  };
}

function closePlanSteps(plan: SessionPlanPayload): SessionPlanPayload {
  if (!plan?.steps || !Array.isArray(plan.steps)) {
    return plan;
  }

  let changed = false;
  const steps = plan.steps.map((step) => {
    const status = normalizePlanStepStatus(step.status);
    if (status === "completed" || status === "blocked" || status === "cancelled") {
      return step;
    }
    changed = true;
    return {
      ...step,
      status: "completed" as PlanStepStatus,
    };
  });

  if (!changed) {
    return plan;
  }

  return {
    ...plan,
    steps,
    progress: buildPlanProgressFromRawSteps(steps),
    current_step: null,
  };
}

function eventMarksTurnFinalized(event: SessionEventPayload) {
  return event.event === "turn_completed" || event.event === "final_response";
}

function eventMarksTaskCompleted(event: SessionEventPayload) {
  return eventMarksTurnFinalized(event) && readTurnOutcome(event.data) === "task_completed";
}

function eventMarksSuccessfulTurnFinalized(event: SessionEventPayload) {
  if (!eventMarksTurnFinalized(event)) {
    return false;
  }
  const outcome = readTurnOutcome(event.data);
  return outcome === "answered" || outcome === "artifact_ready" || outcome === "task_completed";
}

function canImplicitlyClosePlanAfterFinalAnswer(plan: SessionPlanPayload) {
  const incompleteSteps = getPlanSteps(plan).filter((step) => step.status !== "completed" && step.status !== "cancelled");
  return incompleteSteps.length === 1 && incompleteSteps[0].status === "in_progress";
}

function shouldClosePlanFromEvent(plan: SessionPlanPayload, event: SessionEventPayload) {
  if (!hasIncompletePlanSteps(plan)) {
    return false;
  }
  if (eventMarksTaskCompleted(event)) {
    return true;
  }
  return eventMarksSuccessfulTurnFinalized(event) && canImplicitlyClosePlanAfterFinalAnswer(plan);
}

function shouldClosePlanFromEvents(plan: SessionPlanPayload, events: SessionEventPayload[]) {
  if (!hasIncompletePlanSteps(plan)) {
    return false;
  }

  let latestPlanUpdatedAt = Number.NEGATIVE_INFINITY;
  let latestTaskCompletedAt = Number.NEGATIVE_INFINITY;
  let latestImplicitCompletionAt = Number.NEGATIVE_INFINITY;
  events.forEach((event) => {
    if (event.event === "plan_updated") {
      latestPlanUpdatedAt = Math.max(latestPlanUpdatedAt, event.ts);
    }
    if (eventMarksTaskCompleted(event)) {
      latestTaskCompletedAt = Math.max(latestTaskCompletedAt, event.ts);
    }
    if (eventMarksSuccessfulTurnFinalized(event)) {
      latestImplicitCompletionAt = Math.max(latestImplicitCompletionAt, event.ts);
    }
  });

  if (latestTaskCompletedAt !== Number.NEGATIVE_INFINITY && latestTaskCompletedAt >= latestPlanUpdatedAt) {
    return true;
  }

  return (
    canImplicitlyClosePlanAfterFinalAnswer(plan) &&
    latestImplicitCompletionAt !== Number.NEGATIVE_INFINITY &&
    latestImplicitCompletionAt >= latestPlanUpdatedAt
  );
}

function closePlanIfTaskCompletedSeen(plan: SessionPlanPayload, events: SessionEventPayload[]) {
  return shouldClosePlanFromEvents(plan, events) ? closePlanSteps(plan) : plan;
}

function hasIncompletePlanSteps(plan: SessionPlanPayload) {
  return getPlanSteps(plan).some((step) => step.status !== "completed" && step.status !== "cancelled");
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

function formatDelaySeconds(value: unknown) {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return null;
  }
  if (value < 1) {
    return `${Math.round(value * 1000)}ms`;
  }
  if (value < 10) {
    return `${value.toFixed(value < 2 ? 1 : 0)}s`;
  }
  return `${Math.round(value)}s`;
}

function buildProviderSecondaryMeta(event: SessionEventPayload, eventData: Record<string, unknown>) {
  const meta: string[] = [];
  const provider = readNonEmptyText(eventData.provider);
  if (provider) {
    meta.push(provider);
  }
  const attemptCount =
    typeof eventData.attempt_count === "number"
      ? eventData.attempt_count
      : typeof eventData.attempt === "number"
        ? eventData.attempt
        : null;
  const maxAttempts = typeof eventData.max_attempts === "number" ? eventData.max_attempts : null;
  if (attemptCount && maxAttempts) {
    meta.push(`第 ${attemptCount}/${maxAttempts} 次`);
  } else if (attemptCount) {
    meta.push(`第 ${attemptCount} 次`);
  }
  const delayLabel = formatDelaySeconds(eventData.delay_seconds);
  if (delayLabel && (event.event === "provider_retry_scheduled" || eventData.will_retry === true)) {
    meta.push(`${delayLabel} 后重试`);
  }
  if (typeof eventData.status_code === "number") {
    meta.push(`HTTP ${eventData.status_code}`);
  }
  return meta;
}

function buildProviderSecondarySummary(
  event: SessionEventPayload,
  eventData: Record<string, unknown>,
  state: Extract<TimelineNodeState, "recovering" | "failed">
) {
  const message = readNonEmptyText(eventData.message) ?? readNonEmptyText(eventData.summary);
  if (event.event === "provider_retry_scheduled") {
    return "主模型连接波动，正在自动重试";
  }
  if (event.event === "provider_fallback_started") {
    return "流式解析异常，正在切到同模型非流式兜底";
  }
  if (state === "recovering") {
    if (eventData.will_transport_fallback === true) {
      return "主模型响应异常，正在准备非流式兜底";
    }
    return "主模型连接波动，正在恢复";
  }
  return message ?? "主模型响应异常，当前无法继续";
}

function buildProviderSecondaryOutput(
  event: SessionEventPayload,
  eventData: Record<string, unknown>,
  state: Extract<TimelineNodeState, "recovering" | "failed">
) {
  const lines: string[] = [];
  const message = readNonEmptyText(eventData.message) ?? readNonEmptyText(eventData.summary);
  if (message) {
    lines.push(message);
  }

  if (event.event === "provider_retry_scheduled") {
    const attempt = typeof eventData.attempt === "number" ? eventData.attempt : null;
    const maxAttempts = typeof eventData.max_attempts === "number" ? eventData.max_attempts : null;
    const delayLabel = formatDelaySeconds(eventData.delay_seconds);
    lines.push(
      attempt && maxAttempts
        ? `准备进行第 ${attempt}/${maxAttempts} 次重试。`
        : attempt
          ? `准备进行第 ${attempt} 次重试。`
          : "准备再次尝试连接主模型。"
    );
    if (delayLabel) {
      lines.push(`等待 ${delayLabel} 后继续。`);
    }
    const reason = readNonEmptyText(eventData.reason);
    if (reason) {
      lines.push(`原因：${reason}`);
    }
  } else if (event.event === "provider_fallback_started") {
    lines.push("流式解析失败，正在切换到同模型非流式响应继续。");
    const category = readNonEmptyText(eventData.from_category);
    if (category) {
      lines.push(`触发原因：${category}`);
    }
  } else {
    const attemptCount = typeof eventData.attempt_count === "number" ? eventData.attempt_count : null;
    const maxAttempts = typeof eventData.max_attempts === "number" ? eventData.max_attempts : null;
    if (attemptCount && maxAttempts) {
      lines.push(`当前尝试 ${attemptCount}/${maxAttempts}。`);
    }
    if (eventData.will_retry === true) {
      const delayLabel = formatDelaySeconds(eventData.delay_seconds);
      lines.push(delayLabel ? `连接将于 ${delayLabel} 后自动重试。` : "正在安排自动重试。");
    } else if (eventData.will_transport_fallback === true) {
      lines.push("正在准备同模型非流式兜底。");
    }
    const retrySuppressedMessage = readNonEmptyText(eventData.retry_suppressed_message);
    if (retrySuppressedMessage) {
      lines.push(retrySuppressedMessage);
    }
    if (eventData.partial_response_visible === true) {
      lines.push("已有部分输出对用户可见。");
    }
  }

  if (typeof eventData.status_code === "number") {
    lines.push(`状态码：HTTP ${eventData.status_code}`);
  }
  const errorCode = readNonEmptyText(eventData.code);
  if (errorCode) {
    lines.push(`错误码：${errorCode}`);
  }

  if (lines.length === 0) {
    return state === "recovering" ? "正在恢复模型响应，请稍后查看结果。" : "主模型响应失败，当前没有更多可展示的细节。";
  }
  return lines.join("\n");
}

function buildProviderSecondaryItem(
  parentId: string,
  event: SessionEventPayload,
  state: Extract<TimelineNodeState, "recovering" | "failed">
): TimelineSecondaryItem {
  const eventData = buildEventDataWithRequest(event);
  const status = resolveSecondaryStatusMeta(state, eventData, "orange");
  const detailId = `secondary:provider:${parentId}`;
  const output = buildProviderSecondaryOutput(event, eventData, state);
  const summary = buildProviderSecondarySummary(event, eventData, state);

  return {
    id: detailId,
    parentId,
    state,
    label: "主模型响应",
    toolName: null,
    cardType: "network",
    subtitle: summary,
    statusLabel: status.label,
    statusTone: status.tone,
    meta: buildProviderSecondaryMeta(event, eventData),
    output,
    outputLineCount: countOutputLines(output),
    detail: buildTraceDetail(
      detailId,
      "agent",
      formatEventTime(event.ts),
      "主模型响应",
      "模型恢复",
      summary,
      eventData,
      {
        output,
      }
    )
  };
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
  const displayOutput =
    toolName === "request_user_input"
      ? null
      : readNonEmptyText(output) ??
        readNonEmptyText(eventData.output_preview) ??
        readNonEmptyText(eventData.display_output) ??
        null;
  const detailId = `secondary:${typeof eventData.tool_call_id === "string" ? eventData.tool_call_id : parentId}`;
  const argumentsPayload = extractEventArguments(eventData);
  const command =
    toolName === "terminal" && typeof argumentsPayload?.command === "string"
      ? (argumentsPayload.command as string)
      : null;
  const summary =
    (typeof eventData.frontend_message === "string" && eventData.frontend_message) ||
    (typeof eventData.summary === "string" && eventData.summary) ||
    resolveProgressPrimaryText(
      toolName,
      state === "failed" ? "failed" : state === "completed" ? "completed" : "running",
      eventData,
      displayOutput,
      userPrompt
    );

  return {
    id: detailId,
    parentId,
    state,
    label: toolName ?? semantic.label,
    toolName,
    cardType: semantic.cardType,
    subtitle: buildToolSecondarySubtitle(toolName, eventData),
    statusLabel: status.label,
    statusTone: status.tone,
    meta: buildToolSecondaryMeta(toolName, eventData, displayOutput),
    command,
    output: displayOutput,
    argumentsPayload,
    awaitingUserInput: toolName === "request_user_input" ? parseAwaitingUserInputFromToolArguments(argumentsPayload) : null,
    outputLineCount: countOutputLines(displayOutput),
    detail: buildTraceDetail(
      detailId,
      "tool",
      formatEventTime(event.ts),
      toolName ?? semantic.label,
      toolName ?? "工具过程",
      summary,
      eventData,
      {
        output: displayOutput,
      }
    )
  };
}

function summarizeCommentaryContent(content: string | null | undefined, fallback: string) {
  const raw = content ?? "";
  const normalized = raw.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return fallback;
  }
  if (looksStructuredTimelineCopy(raw, normalized)) {
    return fallback;
  }
  return compactString(normalized, TIMELINE_PRIMARY_TEXT_MAX_CHARS);
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
    }
  };
}

function buildAnswerStartNode(event: SessionEventPayload): TimelineNode {
  const nodeId = `node:answer_start:${event.ts}:${event.request_id ?? "local"}`;
  const time = formatEventTime(event.ts);
  const eventData = buildEventDataWithRequest(event);
  const primaryText = "开始回答用户问题";

  return {
    id: nodeId,
    kind: "answer_start",
    state: "completed",
    time,
    primaryText,
    secondaryItems: [],
    detail: buildTraceDetail(nodeId, "result", time, primaryText, "回答开始", primaryText, eventData)
  };
}

function buildSystemMetaNode(event: SessionEventPayload, primaryText: string): TimelineNode {
  const nodeId = `node:system:${event.event}:${event.ts}:${event.request_id ?? "local"}`;
  const time = formatEventTime(event.ts);
  const eventData = buildEventDataWithRequest(event);
  return {
    id: nodeId,
    kind: "system_meta",
    state: "updated",
    time,
    primaryText,
    secondaryItems: [],
    detail: buildTraceDetail(nodeId, "result", time, primaryText, "系统消息", primaryText, eventData)
  };
}

function extractApprovalNodePayload(event: SessionEventPayload, fallback: ApprovalNodePayload | null = null): ApprovalNodePayload {
  const eventData = buildEventDataWithRequest(event);
  const approvalRequestId =
    typeof eventData.approval_request_id === "string" && eventData.approval_request_id
      ? eventData.approval_request_id
      : fallback?.approvalRequestId ?? `approval:${event.ts}:${event.request_id ?? "local"}`;
  const argumentsPayload =
    "arguments" in eventData &&
    eventData.arguments &&
    typeof eventData.arguments === "object" &&
    !Array.isArray(eventData.arguments)
      ? (eventData.arguments as Record<string, unknown>)
      : fallback?.arguments ?? {};
  const summary =
    typeof eventData.summary === "string" && eventData.summary.trim()
      ? eventData.summary
      : fallback?.summary ?? null;

  return {
    approvalRequestId,
    tool: typeof eventData.tool === "string" && eventData.tool ? eventData.tool : fallback?.tool ?? "tool",
    arguments: argumentsPayload,
    reason: typeof eventData.reason === "string" && eventData.reason ? eventData.reason : fallback?.reason ?? "requires_approval",
    summary,
    timeoutSeconds:
      typeof eventData.timeout_seconds === "number" ? eventData.timeout_seconds : fallback?.timeoutSeconds ?? null
  };
}

function buildPendingApprovalFromEvent(event: SessionEventPayload): PendingApproval | null {
  const eventData = event.data;
  const approvalRequestId =
    typeof eventData.approval_request_id === "string" && eventData.approval_request_id
      ? eventData.approval_request_id
      : null;
  const tool = typeof eventData.tool === "string" && eventData.tool ? eventData.tool : null;
  const argumentsPayload =
    eventData.arguments && typeof eventData.arguments === "object" && !Array.isArray(eventData.arguments)
      ? (eventData.arguments as Record<string, unknown>)
      : null;
  if (!approvalRequestId || !tool || !argumentsPayload) {
    return null;
  }
  const timeoutSeconds = typeof eventData.timeout_seconds === "number" ? eventData.timeout_seconds : 0;
  return {
    approval_request_id: approvalRequestId,
    turn_id: typeof eventData.turn_id === "string" ? eventData.turn_id : null,
    tool,
    arguments: argumentsPayload,
    reason: typeof eventData.reason === "string" && eventData.reason ? eventData.reason : "requires_approval",
    timeout_seconds: timeoutSeconds,
    remaining_seconds: timeoutSeconds,
  };
}

function buildApprovalNode(
  event: SessionEventPayload,
  state: Extract<TimelineNodeState, "pending" | "approved" | "rejected" | "failed">,
  fallback: ApprovalNodePayload | null = null
): TimelineNode {
  const eventData = buildEventDataWithRequest(event);
  const approval = extractApprovalNodePayload(event, fallback);
  const time = formatEventTime(event.ts);
  const nodeId = `node:approval:${approval.approvalRequestId}`;
  const primaryText = buildApprovalNodePrimaryText(approval, state);
  const summary = buildApprovalNodeSupportCopy(approval, state);
  const preview = buildApprovalPayloadPreview(approval);

  return {
    id: nodeId,
    kind: "approval",
    state,
    time,
    primaryText,
    secondaryItems: [],
    approval,
    detail: buildTraceDetail(nodeId, "trace", time, primaryText, "审批确认", summary, eventData, {
      output: preview || null
    })
  };
}

function refreshApprovalNode(
  node: TimelineNode,
  event: SessionEventPayload,
  state: Extract<TimelineNodeState, "pending" | "approved" | "rejected" | "failed">
) {
  const eventData = buildEventDataWithRequest(event);
  const approval = extractApprovalNodePayload(event, node.approval ?? null);
  const summary = buildApprovalNodeSupportCopy(approval, state);
  const preview = buildApprovalPayloadPreview(approval);
  node.state = state;
  node.time = formatEventTime(event.ts);
  node.primaryText = buildApprovalNodePrimaryText(approval, state);
  node.approval = approval;
  node.detail = buildTraceDetail(node.id, "trace", node.time, node.primaryText, "审批确认", summary, eventData, {
    output: preview || null
  });
}

function buildProgressGroupNode(groupId: string, event: SessionEventPayload, primaryText: string): TimelineNode {
  const eventData = buildEventDataWithRequest(event);
  const nodeId = `node:group:${groupId}`;
  return {
    id: nodeId,
    kind: "progress",
    state: "running",
    time: formatEventTime(event.ts),
    primaryText,
    secondaryItems: [],
    detail: buildTraceDetail(nodeId, "trace", formatEventTime(event.ts), primaryText, "执行进展", primaryText, eventData)
  };
}

function buildSkillSecondaryItem(parentId: string, event: SessionEventPayload): TimelineSecondaryItem {
  const eventData = buildEventDataWithRequest(event);
  const explicitSkillName =
    typeof eventData.skill_name === "string" && eventData.skill_name.trim() ? eventData.skill_name.trim() : null;
  const isSkillUsage = event.event === "skill_used" || Boolean(explicitSkillName);
  const itemName = explicitSkillName ?? (typeof eventData.event === "string" ? eventData.event : "Skill");
  const message =
    (typeof eventData.summary === "string" && eventData.summary) ||
    (typeof eventData.message === "string" && eventData.message) ||
    (isSkillUsage ? "这个 Skill 步骤已完成" : "这个分析步骤已完成");
  const contextOutput = typeof eventData.context === "undefined" ? null : stringifyForPanel(eventData.context);
  const contextTool =
    eventData.context && typeof eventData.context === "object" && "tool" in eventData.context && typeof eventData.context.tool === "string"
      ? eventData.context.tool
      : null;
  const pluginName = typeof eventData.plugin_name === "string" && eventData.plugin_name.trim() ? eventData.plugin_name.trim() : null;
  const description = typeof eventData.description === "string" && eventData.description.trim() ? eventData.description.trim() : null;
  const detailId = `secondary:skill:${parentId}:${event.ts}:${itemName}`;

  return {
    id: detailId,
    parentId,
    state: "completed",
    label: isSkillUsage ? `${itemName} Skill` : itemName,
    toolName: null,
    cardType: "generic",
    subtitle: description ?? message,
    statusLabel: "已完成",
    statusTone: "green",
    meta: [isSkillUsage ? (pluginName ? `插件 ${pluginName}` : "Skill") : "Hook", ...(contextTool ? [contextTool] : [])],
    output: contextOutput ?? description,
    outputLineCount: countOutputLines(contextOutput ?? description),
    detail: buildTraceDetail(
      detailId,
      "skill",
      formatEventTime(event.ts),
      isSkillUsage ? `${itemName} Skill` : itemName,
      isSkillUsage ? "Skill 详情" : "Hook 详情",
      message,
      eventData,
      {
        output: contextOutput ?? description,
      }
    )
  };
}

function resolveAttachmentWarningText(eventData: Record<string, unknown>) {
  const warnings =
    Array.isArray(eventData.warnings) && eventData.warnings.every((item) => typeof item === "string")
      ? (eventData.warnings as string[])
      : [];
  if (warnings.length === 0) {
    return null;
  }
  return warnings.find((item) => item.includes("上下文预算")) ?? warnings[0] ?? null;
}

function upsertProgressSecondaryItem(node: TimelineNode, item: TimelineSecondaryItem) {
  const existingIndex = node.secondaryItems.findIndex((currentItem) => currentItem.id === item.id);
  if (existingIndex === -1) {
    node.secondaryItems.push(item);
    return;
  }
  const existingItem = node.secondaryItems[existingIndex];
  node.secondaryItems[existingIndex] = {
    ...item,
    command: item.command ?? existingItem.command ?? null,
    argumentsPayload: item.argumentsPayload ?? existingItem.argumentsPayload ?? null,
    awaitingUserInput: item.awaitingUserInput ?? existingItem.awaitingUserInput ?? null,
    detail: {
      ...item.detail,
      output: item.detail.output ?? existingItem.detail.output ?? null,
    },
  };
}

function settleProviderRecoveryItem(
  node: TimelineNode,
  event: SessionEventPayload,
  state: Extract<TimelineNodeState, "completed" | "failed">,
  summary: string
) {
  const providerItemId = `secondary:provider:${node.id}`;
  const existingIndex = node.secondaryItems.findIndex((item) => item.id === providerItemId);
  if (existingIndex === -1) {
    return;
  }

  const currentItem = node.secondaryItems[existingIndex];
  if (currentItem.state !== "recovering" && currentItem.state !== "running") {
    return;
  }

  const eventData = buildEventDataWithRequest(event);
  const status = resolveSecondaryStatusMeta(state, eventData, state === "completed" ? "green" : "orange");
  const output = [currentItem.output?.trim(), summary].filter(Boolean).join("\n");
  node.secondaryItems[existingIndex] = {
    ...currentItem,
    state,
    subtitle: summary,
    statusLabel: status.label,
    statusTone: status.tone,
    output,
    outputLineCount: countOutputLines(output),
    detail: buildTraceDetail(
      currentItem.id,
      "agent",
      formatEventTime(event.ts),
      currentItem.label,
      "模型恢复",
      summary,
      eventData,
      {
        output,
      }
    )
  };
  node.state = resolveProgressGroupState(node.secondaryItems);
  node.time = formatEventTime(event.ts);
  node.primaryText = summary;
  node.detail = buildTraceDetail(
    node.id,
    "trace",
    node.time,
    summary,
    "执行进展",
    summary,
    eventData
  );
}

function settleAllProviderRecoveryItems(
  nodes: Iterable<TimelineNode>,
  event: SessionEventPayload,
  state: Extract<TimelineNodeState, "completed" | "failed">,
  summary: string
) {
  for (const node of nodes) {
    settleProviderRecoveryItem(node, event, state, summary);
  }
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
  );
}

function resolveProgressNodePrimaryText(
  node: TimelineNode | null,
  eventName: SessionEventPayload["event"],
  proposedText: string
) {
  const normalized = sanitizeActionBriefForDisplay(proposedText).trim();
  if (!node) {
    return normalized;
  }
  if (!normalized) {
    return node.primaryText;
  }
  if (eventName === "commentary_delta" || eventName === "commentary_complete") {
    if (node.secondaryItems.length > 0 && !isWeakProgressPrimaryText(node.primaryText)) {
      return node.primaryText;
    }
    return normalized;
  }
  if (!node.primaryText || isWeakProgressPrimaryText(node.primaryText)) {
    return normalized;
  }
  return node.primaryText;
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
    approval: nextNode.approval ?? existingNode.approval ?? null,
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
  const approvalNodeByRequestId = new Map<string, TimelineNode>();
  const toolCallToGroupId = new Map<string, string>();
  const toolMessageByCallId = new Map<string, SessionMessageRecord>();
  const toolOutputByCallId = new Map<string, string>();
  const commentaryByGroupId = new Map<string, string>();
  let thinkingNodeId: string | null = null;
  let answerStartNodeId: string | null = null;

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
        : typeof message.metadata.action_brief === "string" && message.metadata.action_brief
          ? message.metadata.action_brief
          : message.content;
    const commentary = summarizeCommentaryContent(sanitizeActionBriefForDisplay(rawCommentary), "");
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

  const resolveToolOutput = (toolCallId: string | null) => {
    if (!toolCallId) {
      return null;
    }
    return toolOutputByCallId.get(toolCallId) ?? toolMessageByCallId.get(toolCallId)?.content ?? null;
  };

  events.forEach((event) => {
    const eventData = buildEventDataWithRequest(event);
    const toolCallId = typeof eventData.tool_call_id === "string" ? eventData.tool_call_id : null;

    if (event.event === "checkpoint_created") {
      nodes.push(buildSystemMetaNode(event, "上下文已压缩"));
      return;
    }

    if (event.event === "turn_interrupted") {
      nodes.push(
        buildSystemMetaNode(
          event,
          typeof eventData.message === "string" && eventData.message ? eventData.message : "当前任务已停止"
        )
      );
      return;
    }

    if (event.event === "collaboration_mode_changed") {
      const modePayload =
        "collaboration_mode" in eventData && eventData.collaboration_mode && typeof eventData.collaboration_mode === "object"
          ? (eventData.collaboration_mode as Record<string, unknown>)
          : null;
      const mode = modePayload && modePayload.mode === "plan" ? "plan" : "default";
      const fallback = mode === "plan" ? "已进入计划模式" : "已回到默认执行模式";
      const summary = typeof eventData.summary === "string" && eventData.summary ? eventData.summary : fallback;
      nodes.push(buildSystemMetaNode(event, summary));
      return;
    }

    if (event.event === "plan_draft_updated") {
      const draftPayload =
        "plan_draft" in eventData && eventData.plan_draft && typeof eventData.plan_draft === "object"
          ? (eventData.plan_draft as Record<string, unknown>)
          : null;
      const status = draftPayload && typeof draftPayload.status === "string" ? draftPayload.status : "draft";
      const fallback =
        status === "approved" ? "规划草案已批准" : status === "awaiting_approval" ? "规划草案待确认" : "规划草案已更新";
      const summary = typeof eventData.summary === "string" && eventData.summary ? eventData.summary : fallback;
      nodes.push(buildSystemMetaNode(event, summary));
      return;
    }

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

    if (event.event === "answer_started") {
      settleAllProviderRecoveryItems(progressNodeByGroupId.values(), event, "completed", "主模型连接已恢复，已继续生成回复。");
      const nextNode = buildAnswerStartNode(event);
      nodes.push(nextNode);
      answerStartNodeId = nextNode.id;
      return;
    }

    if (event.event === "turn_completed") {
      const outcome = readTurnOutcome(eventData);
      const nextState = outcome === "failed" || outcome === "blocked" ? "failed" : "completed";
      const summary = nextState === "completed" ? "主模型连接已恢复，本轮已完成。" : "主模型恢复未能完成，本轮已结束。";
      settleAllProviderRecoveryItems(progressNodeByGroupId.values(), event, nextState, summary);
      return;
    }

    if (event.event === "tool_approval_request") {
      const nextNode = buildApprovalNode(event, "pending");
      const approvalRequestId = nextNode.approval?.approvalRequestId ?? nextNode.id;
      const existingNode = approvalNodeByRequestId.get(approvalRequestId);
      if (existingNode) {
        refreshApprovalNode(existingNode, event, "pending");
      } else {
        nodes.push(nextNode);
        approvalNodeByRequestId.set(approvalRequestId, nextNode);
      }
      return;
    }

    if (event.event === "tool_approval_resolved") {
      const approvalRequestId =
        typeof eventData.approval_request_id === "string" && eventData.approval_request_id ? eventData.approval_request_id : null;
      const nextState = Boolean(eventData.approved) ? "approved" : "rejected";
      const existingNode =
        (approvalRequestId ? approvalNodeByRequestId.get(approvalRequestId) : null) ??
        (approvalRequestId
          ? nodes.find((node) => node.kind === "approval" && node.approval?.approvalRequestId === approvalRequestId)
          : null);
      if (existingNode) {
        refreshApprovalNode(existingNode, event, nextState);
        const resolvedRequestId = existingNode.approval?.approvalRequestId ?? approvalRequestId ?? existingNode.id;
        approvalNodeByRequestId.set(resolvedRequestId, existingNode);
      } else {
        const nextNode = buildApprovalNode(event, nextState);
        nodes.push(nextNode);
        approvalNodeByRequestId.set(nextNode.approval?.approvalRequestId ?? nextNode.id, nextNode);
      }
      return;
    }

    if (event.event === "assistant_delta" && eventData.reset === true) {
      const existingNodeId =
        answerStartNodeId ?? [...nodes].reverse().find((node) => node.kind === "answer_start")?.id ?? null;
      if (!existingNodeId) {
        return;
      }
      const existing = findNodeById(nodes, existingNodeId);
      if (!existing) {
        return;
      }
      nodes.splice(existing.index, 1);
      if (answerStartNodeId === existingNodeId) {
        answerStartNodeId = null;
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
      const existingNode = progressNodeByGroupId.get(groupId) ?? null;
      const primaryText = resolveProgressNodePrimaryText(existingNode, event.event, commentary);
      const node = ensureProgressNode(groupId, event, primaryText);
      settleProviderRecoveryItem(node, event, "completed", "主模型连接已恢复，继续执行。");
      refreshProgressGroupNode(node, event, primaryText, commentary);
      return;
    }

    if (event.event === "skill_used") {
      const groupId = resolveGroupId(eventData, toolCallId);
      if (!groupId) {
        return;
      }
      const skillName = resolveSkillNameFromEventData(eventData) ?? "Skill";
      const proposedText =
        typeof eventData.action_brief === "string" && eventData.action_brief
          ? eventData.action_brief
          : typeof eventData.summary === "string" && eventData.summary
            ? eventData.summary
            : `使用 ${skillName} Skill，先读取它的工作说明`;
      const primaryText = resolveProgressNodePrimaryText(
        progressNodeByGroupId.get(groupId) ?? null,
        event.event,
        proposedText
      );
      const node = ensureProgressNode(groupId, event, primaryText);
      settleProviderRecoveryItem(node, event, "completed", "主模型连接已恢复，继续执行。");
      const item = buildSkillSecondaryItem(node.id, event);
      upsertProgressSecondaryItem(node, item);
      refreshProgressGroupNode(node, event, primaryText, item.detail.summary);
      return;
    }

    if (
      event.event === "stream_error" ||
      event.event === "provider_retry_scheduled" ||
      event.event === "provider_fallback_started"
    ) {
      const groupId =
        (typeof eventData.group_id === "string" && eventData.group_id) || `provider:${event.request_id ?? event.ts}`;
      const nextState =
        event.event === "stream_error" && eventData.will_retry !== true && eventData.will_transport_fallback !== true
          ? "failed"
          : "recovering";
      const primaryText = resolveProgressNodePrimaryText(
        progressNodeByGroupId.get(groupId) ?? null,
        event.event,
        buildProviderSecondarySummary(event, eventData, nextState)
      );
      const node = ensureProgressNode(groupId, event, primaryText);
      const item = buildProviderSecondaryItem(node.id, event, nextState);
      upsertProgressSecondaryItem(node, item);
      refreshProgressGroupNode(node, event, primaryText, item.detail.summary);
      return;
    }

    if (event.event === "attachment_received" || event.event === "attachment_processed") {
      const warningText = event.event === "attachment_processed" ? resolveAttachmentWarningText(eventData) : null;
      if (warningText) {
        nodes.push(buildSystemMetaNode(event, warningText));
      }
      return;
    }

    if (event.event === "tool_call_arguments_delta") {
      if (!toolCallId) {
        return;
      }
      const groupId = resolveGroupId(eventData, toolCallId);
      if (!groupId) {
        return;
      }
      const node = progressNodeByGroupId.get(groupId) ?? null;
      if (node) {
        settleProviderRecoveryItem(node, event, "completed", "主模型连接已恢复，继续执行。");
        const item = buildToolSecondaryItem(node.id, event, "running", null, userPrompt);
        upsertProgressSecondaryItem(node, item);
        refreshProgressGroupNode(node, event, node.primaryText, item.detail.summary);
      }
      toolCallToGroupId.set(toolCallId, groupId);
      return;
    }

    if (event.event === "tool_call_output_delta") {
      if (!toolCallId) {
        return;
      }
      const delta = typeof eventData.delta === "string" ? eventData.delta : "";
      const nextOutput = `${toolOutputByCallId.get(toolCallId) ?? ""}${delta}`;
      toolOutputByCallId.set(toolCallId, nextOutput);
      const groupId = resolveGroupId(eventData, toolCallId);
      if (!groupId) {
        return;
      }
      const toolOutput = resolveToolOutput(toolCallId);
      const primaryText =
        resolveProgressNodePrimaryText(
          progressNodeByGroupId.get(groupId) ?? null,
          event.event,
          commentaryByGroupId.get(groupId) ||
            resolveProgressPrimaryText(
              "tool" in eventData && typeof eventData.tool === "string" ? eventData.tool : null,
              "running",
              eventData,
              toolOutput,
              userPrompt
            )
      );
      const node = ensureProgressNode(groupId, event, primaryText);
      settleProviderRecoveryItem(node, event, "completed", "主模型连接已恢复，继续执行。");
      const item = buildToolSecondaryItem(node.id, event, "running", toolOutput, userPrompt);
      upsertProgressSecondaryItem(node, item);
      refreshProgressGroupNode(node, event, primaryText, item.detail.summary);
      toolCallToGroupId.set(toolCallId, groupId);
      return;
    }

    if (event.event === "tool_call_started") {
      const toolOutput = resolveToolOutput(toolCallId);
      const groupId = resolveGroupId(eventData, toolCallId);
      if (!groupId) {
        return;
      }
      const primaryText =
        resolveProgressNodePrimaryText(
          progressNodeByGroupId.get(groupId) ?? null,
          event.event,
          commentaryByGroupId.get(groupId) ||
            resolveProgressPrimaryText(
              "tool" in eventData && typeof eventData.tool === "string" ? eventData.tool : null,
              "running",
              eventData,
              toolOutput,
              userPrompt
            )
      );
      const node = ensureProgressNode(groupId, event, primaryText);
      settleProviderRecoveryItem(node, event, "completed", "主模型连接已恢复，继续执行。");
      const item = buildToolSecondaryItem(node.id, event, "running", toolOutput, userPrompt);
      upsertProgressSecondaryItem(node, item);
      refreshProgressGroupNode(node, event, primaryText, item.detail.summary);
      if (toolCallId) {
        toolCallToGroupId.set(toolCallId, groupId);
      }
      return;
    }

    if (event.event === "tool_call_finished") {
      const toolOutput = resolveToolOutput(toolCallId);
      const groupId = resolveGroupId(eventData, toolCallId);
      if (!groupId) {
        return;
      }
      const nextState = Boolean(eventData.success) ? "completed" : "failed";
      const primaryText =
        resolveProgressNodePrimaryText(
          progressNodeByGroupId.get(groupId) ?? null,
          event.event,
          commentaryByGroupId.get(groupId) ||
            resolveProgressPrimaryText(
              "tool" in eventData && typeof eventData.tool === "string" ? eventData.tool : null,
              nextState,
              eventData,
              toolOutput,
              userPrompt
            )
      );
      const node = ensureProgressNode(groupId, event, primaryText);
      settleProviderRecoveryItem(node, event, "completed", "主模型连接已恢复，继续执行。");
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
        resolveProgressNodePrimaryText(
          progressNodeByGroupId.get(groupId) ?? null,
          event.event,
          commentaryByGroupId.get(groupId) ||
            summarizeCommentaryContent(typeof eventData.message === "string" ? eventData.message : "", "我先继续处理这一步")
        );
      const node = ensureProgressNode(groupId, event, primaryText);
      settleProviderRecoveryItem(node, event, "completed", "主模型连接已恢复，继续执行。");
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

function computeTurnDurationMs(
  userMessageCreatedAt: string,
  answerCreatedAt: string | null | undefined,
  status: TurnStatus,
  turnEvents: SessionEventPayload[]
) {
  const startedAt = parseTimestamp(userMessageCreatedAt);
  if (startedAt === null) {
    return null;
  }

  const endCandidates: number[] = [];
  const answerTimestamp = parseTimestamp(answerCreatedAt);
  if (answerTimestamp !== null) {
    endCandidates.push(answerTimestamp);
  }

  turnEvents.forEach((event) => {
    if (
      event.event === "turn_completed" ||
      event.event === "final_response" ||
      event.event === "turn_interrupted" ||
      event.event === "error"
    ) {
      endCandidates.push(event.ts);
    }
  });

  if (endCandidates.length === 0) {
    return status === "running" ? null : 0;
  }

  return Math.max(0, Math.max(...endCandidates) - startedAt);
}

function readTurnId(value: Record<string, unknown>) {
  const turnId = value.turn_id;
  return typeof turnId === "string" && turnId ? turnId : null;
}

function readRequestId(value: Record<string, unknown>) {
  const requestId = value.request_id;
  return typeof requestId === "string" && requestId ? requestId : null;
}

function readAwaitingUserInputReply(value: Record<string, unknown>): AwaitingUserInputReplyMetadata | null {
  const raw = value.responds_to_awaiting_user_input;
  if (!isRecord(raw)) {
    return null;
  }
  const requestId = readOptionalString(raw.request_id);
  const workflowId = readOptionalString(raw.workflow_id);
  if (!requestId && !workflowId) {
    return null;
  }
  return {
    requestId,
    workflowId,
    kind: readOptionalString(raw.kind),
    skillName: readOptionalString(raw.skill_name),
    phase: readOptionalString(raw.phase)
  };
}

function awaitingReplyMatchesRequest(reply: AwaitingUserInputReplyMetadata | null | undefined, request: AwaitingUserInputPayload | null | undefined) {
  if (!reply || !request) {
    return false;
  }
  if (reply.requestId && reply.requestId === request.requestId) {
    return true;
  }
  if (reply.workflowId && request.workflowId && reply.workflowId === request.workflowId) {
    return true;
  }
  return false;
}

function readOptionalString(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function normalizeAwaitingInputOptions(
  kind: AwaitingUserInputKind,
  prompt: string,
  rawOptions: AwaitingUserInputOption[]
) {
  if (rawOptions.length > 0) {
    return rawOptions;
  }
  const inferred = extractEnumeratedAwaitingOptions(prompt);
  if (inferred.length >= 2) {
    return inferred;
  }
  return kind === "confirm" ? DEFAULT_CONFIRM_AWAITING_OPTIONS : [];
}

function extractEnumeratedAwaitingOptions(prompt: string): AwaitingUserInputOption[] {
  const markerPattern = /(?:^|[\s\n:：，,；;])([1-9]\d*)[.．、)]\s*/g;
  const markers = Array.from(prompt.matchAll(markerPattern));
  if (markers.length < 2) {
    return [];
  }

  return markers
    .map((match, index): AwaitingUserInputOption | null => {
      const matchIndex = match.index ?? 0;
      const start = matchIndex + match[0].length;
      const end = index + 1 < markers.length ? markers[index + 1].index ?? prompt.length : prompt.length;
      const rawText = prompt.slice(start, end).replace(/\s+/g, " ").trim();
      if (!rawText) {
        return null;
      }
      const { label, description } = splitAwaitingOptionText(rawText);
      if (!label) {
        return null;
      }
      const number = match[1] || String(index + 1);
      return {
        label,
        value: `option_${number}`,
        description,
      };
    })
    .filter((item): item is AwaitingUserInputOption => item !== null);
}

function splitAwaitingOptionText(text: string) {
  const normalized = text.trim();
  const followUpMatch = normalized.match(/[?？。.!！]\s*(?=(如果|如需|请|需要|可提供|补充))/);
  if (!followUpMatch || followUpMatch.index === undefined) {
    return { label: normalized, description: null };
  }
  const boundary = followUpMatch.index + followUpMatch[0].trimEnd().length;
  const label = normalized.slice(0, boundary).trim();
  const description = normalized.slice(boundary).trim();
  return { label, description: description || null };
}

function readTurnOutcome(value: Record<string, unknown>) {
  const outcome = value.turn_outcome;
  return outcome === "answered" ||
    outcome === "awaiting_user" ||
    outcome === "artifact_ready" ||
    outcome === "task_completed" ||
    outcome === "blocked" ||
    outcome === "failed"
    ? outcome
    : null;
}

function parseAwaitingUserInputPayload(value: unknown): AwaitingUserInputPayload | null {
  if (!isRecord(value)) {
    return null;
  }

  const requestId = readOptionalString(value.request_id);
  const prompt = readOptionalString(value.prompt);
  const kind = value.kind;
  if (!requestId || !prompt || (kind !== "confirm" && kind !== "choice" && kind !== "free_text")) {
    return null;
  }

  const rawOptions = Array.isArray(value.options)
    ? value.options
        .map((item): AwaitingUserInputOption | null => {
          if (!isRecord(item)) {
            return null;
          }
          const label = readOptionalString(item.label);
          const optionValue = readOptionalString(item.value);
          if (!label || !optionValue) {
            return null;
          }
          return {
            label,
            value: optionValue,
            description: readOptionalString(item.description)
          };
        })
        .filter((item): item is AwaitingUserInputOption => item !== null)
    : [];
  const options = normalizeAwaitingInputOptions(kind, prompt, rawOptions);

  return {
    requestId,
    kind,
    prompt,
    content: readOptionalString(value.content),
    options,
    workflowId: readOptionalString(value.workflow_id),
    skillName: readOptionalString(value.skill_name),
    phase: readOptionalString(value.phase),
    status: readOptionalString(value.status),
    createdAt: readOptionalString(value.created_at)
  };
}

function readAwaitingUserInput(value: Record<string, unknown>) {
  return parseAwaitingUserInputPayload(value.awaiting_user_input);
}

function parseAwaitingUserInputFromToolArguments(value: unknown): AwaitingUserInputPayload | null {
  if (!isRecord(value)) {
    return null;
  }
  const kind = value.kind;
  const prompt = readOptionalString(value.prompt);
  if (!prompt || (kind !== "confirm" && kind !== "choice" && kind !== "free_text")) {
    return null;
  }
  const rawOptions = Array.isArray(value.options)
    ? value.options
        .map((item): AwaitingUserInputOption | null => {
          if (!isRecord(item)) {
            return null;
          }
          const label = readOptionalString(item.label);
          const optionValue = readOptionalString(item.value);
          if (!label || !optionValue) {
            return null;
          }
          return {
            label,
            value: optionValue,
            description: readOptionalString(item.description)
          };
        })
        .filter((item): item is AwaitingUserInputOption => item !== null)
    : [];
  const options = normalizeAwaitingInputOptions(kind, prompt, rawOptions);
  return {
    requestId: readOptionalString(value.request_id) ?? `tool:${readOptionalString(value.workflow_id) ?? prompt}`,
    kind,
    prompt,
    content: readOptionalString(value.content),
    options,
    workflowId: readOptionalString(value.workflow_id),
    skillName: readOptionalString(value.skill_name),
    phase: readOptionalString(value.phase),
    status: readOptionalString(value.status) ?? "pending",
    createdAt: readOptionalString(value.created_at)
  };
}

function readApprovalMode(value: Record<string, unknown>) {
  const approvalMode = value.approval_mode;
  if (approvalMode === "auto_allow" || approvalMode === "auto_approve_level2") {
    return "auto_allow";
  }
  return approvalMode === "manual" ? approvalMode : null;
}

function isAssistantToolCallMessage(message: SessionMessageRecord) {
  const toolCalls = message.metadata.tool_calls;
  return Array.isArray(toolCalls) && toolCalls.length > 0;
}

function readNonEmptyText(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function isRawToolCallMarkupText(text: string) {
  const normalized = text.trim();
  if (!normalized) {
    return false;
  }
  return normalized.includes("<minimax:tool_call>") || normalized.includes("<invoke") || normalized.includes("<parameter");
}

function buildFailedTurnCopyFromEvent(event: SessionEventPayload) {
  const tool = readNonEmptyText(event.data.tool);
  const frontendMessage = readNonEmptyText(event.data.frontend_message);
  const message = readNonEmptyText(event.data.message);
  const summary = readNonEmptyText(event.data.summary);
  const recommendedNextStep = readNonEmptyText(event.data.recommended_next_step);
  const errorCode = readNonEmptyText(event.data.error_code);
  const category = readNonEmptyText(event.data.category);
  const blocker = frontendMessage ?? message ?? summary;

  if (event.event !== "error" && event.event !== "tool_error_feedback") {
    return null;
  }

  if (errorCode === "NEWMAN-TOOL-005" || category === "user_rejected") {
    return "工具调用申请被用户拒绝或审批超时，当前任务已终止";
  }

  const lines: string[] = [];
  if (tool && blocker) {
    lines.push(`这一步被阻塞了：\`${tool}\` ${blocker}。`);
  } else if (tool) {
    lines.push(`这一步被阻塞了：\`${tool}\`。`);
  }

  const reason = summary && summary !== blocker ? summary : blocker;
  if (reason) {
    if (lines.length > 0) {
      lines.push(`原因：${reason}`);
    } else {
      lines.push(reason);
    }
  }

  if (recommendedNextStep) {
    lines.push(`建议：${recommendedNextStep}`);
  }

  return lines.join("\n").trim() || "这轮执行暂时中断，请查看过程详情。";
}

function synthesizeFailedTurnAnswer(turnId: string, events: SessionEventPayload[]): TurnAnswer | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    const content = buildFailedTurnCopyFromEvent(event);
    if (!content) {
      continue;
    }
    return {
      detailId: `failed:${turnId}:${index}`,
      content,
      attachments: [],
      createdAt: new Date(event.ts).toISOString(),
      phase: "failed",
      source: "session",
      assistantMessageId: null,
      finishReason: event.event,
      turnOutcome: "failed",
      errorMessage: content
    };
  }
  return null;
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
  if (directTurnId) {
    return null;
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

function buildChatTurns(
  sessionId: string,
  messages: SessionMessageRecord[],
  sessionEvents: SessionEventPayload[],
  turnUsageById: Record<string, TurnUsageSummary>
) {
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
        approvalMode: readApprovalMode(message.metadata),
        respondsToAwaitingUserInput: readAwaitingUserInputReply(message.metadata)
      },
      answer: null,
      timeline: [],
      status: "running",
      isLive: false,
      usage: turnUsageById[turnId] ?? null,
      durationMs: null,
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

    const assistantAttachments = parseMessageAttachments(message.metadata.attachments);
    const assistantContent = message.content;
    if (!assistantContent.trim() && assistantAttachments.length === 0) {
      const emptyResponseMessage = "主模型返回了空白内容，当前没有可展示结果。请重试本轮请求。";
      targetTurn.answer = {
        detailId: `assistant:${message.id}`,
        content: emptyResponseMessage,
        attachments: [],
        createdAt: message.created_at,
        phase: "failed",
        source: "session",
        assistantMessageId: message.id,
        finishReason: typeof message.metadata.finish_reason === "string" ? message.metadata.finish_reason : "empty_response",
        turnOutcome: readTurnOutcome(message.metadata) ?? "failed",
        awaitingUserInput: readAwaitingUserInput(message.metadata),
        errorMessage: emptyResponseMessage,
      };
      targetTurn.requestId = targetTurn.requestId ?? readRequestId(message.metadata);
      targetTurn.status = "failed";
      return;
    }

    targetTurn.answer = {
      detailId: `assistant:${message.id}`,
      content: assistantContent,
      attachments: assistantAttachments,
      createdAt: message.created_at,
      phase: "persisted",
      source: "session",
      assistantMessageId: message.id,
      finishReason: typeof message.metadata.finish_reason === "string" ? message.metadata.finish_reason : null,
      turnOutcome: readTurnOutcome(message.metadata),
      awaitingUserInput: readAwaitingUserInput(message.metadata)
    };
    targetTurn.requestId = targetTurn.requestId ?? readRequestId(message.metadata);
    if (targetTurn.status === "running") {
      targetTurn.status = "completed";
    }
  });

  const awaitingParentByReplyTurnId = new Map<string, ChatTurn>();
  turns.forEach((turn, turnIndex) => {
    const reply = turn.userMessage.respondsToAwaitingUserInput;
    if (!reply) {
      return;
    }
    for (let index = turnIndex - 1; index >= 0; index -= 1) {
      const candidate = turns[index];
      if (awaitingReplyMatchesRequest(reply, candidate.answer?.awaitingUserInput)) {
        awaitingParentByReplyTurnId.set(turn.id, candidate);
        return;
      }
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
    if (event.event === "turn_interrupted") {
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
    if (event.event === "tool_call_finished" && event.data.tool === "write_file" && event.data.success === false && isHtmlWriteFileEventData(event.data)) {
      turn.status = "failed";
      return;
    }
    if (turn.status === "running" && turn.answer) {
      turn.status = "completed";
    }
  });

  turns.forEach((turn) => {
    const turnEvents = eventsByTurn.get(turn.id) ?? [];
    const eventAttachments = buildOutputAttachmentsFromEvents(turnEvents, sessionId, turn.id);
    const parentAwaitingTurn = awaitingParentByReplyTurnId.get(turn.id) ?? null;
    const interrupted = turnHasInterruptedEvent(turnEvents);
    if (interrupted && turn.answer && isRawToolCallMarkupText(turn.answer.content)) {
      turn.answer = {
        ...turn.answer,
        content: "",
        errorMessage: null,
      };
    }
    if (turn.status === "failed" && interrupted && !turn.answer && eventAttachments.length > 0) {
      turn.answer = {
        detailId: `interrupted:${turn.id}`,
        content: "",
        attachments: [],
        createdAt: new Date(turnEvents[turnEvents.length - 1]?.ts ?? Date.now()).toISOString(),
        phase: "failed",
        source: "session",
        assistantMessageId: null,
        finishReason: "turn_interrupted",
        turnOutcome: "failed",
        errorMessage: null,
      };
    }
    if (turn.status === "failed" && !interrupted && (!turn.answer || isRawToolCallMarkupText(turn.answer.content))) {
      const failedAnswer = synthesizeFailedTurnAnswer(turn.id, turnEvents);
      if (failedAnswer) {
        turn.answer = failedAnswer;
      }
    }
    if (turn.answer) {
      const mergedCurrentAttachments = mergeChatAttachments(turn.answer.attachments, eventAttachments);
      turn.answer.attachments = mergeChatAttachments(mergedCurrentAttachments, parentAwaitingTurn?.answer?.attachments ?? []);
    }
    if (turn.status === "running" && turn.answer) {
      turn.status = "completed";
    }
    const nextTimeline = buildTimelineNodes(
      turnEvents,
      toolMessagesByTurn.get(turn.id) ?? [],
      assistantToolMessagesByTurn.get(turn.id) ?? [],
      turn.userMessage.content
    ).map((node) =>
      applyTurnIdToNode(node, turn.id)
    );
    if (
      nextTimeline.length === 0 &&
      turn.answer &&
      turn.userMessage.respondsToAwaitingUserInput &&
      !turn.answer.awaitingUserInput &&
      turn.answer.turnOutcome !== "awaiting_user"
    ) {
      const resolvedAt = parseTimestamp(turn.answer.createdAt) ?? parseTimestamp(turn.userMessage.createdAt) ?? Date.now();
      const outcome = turn.answer.turnOutcome ?? (turn.status === "failed" ? "failed" : "answered");
      const summary = outcome === "failed" || outcome === "blocked" ? "确认回复处理失败，本轮已结束" : "已确认，当前任务已完成";
      nextTimeline.push(
        applyTurnIdToNode(
          buildSystemMetaNode(
            {
              event: "awaiting_user_reply_resolved",
              data: {
                turn_id: turn.id,
                turn_outcome: outcome
              },
              ts: resolvedAt,
              ...(turn.requestId ? { request_id: turn.requestId } : {})
            },
            summary
          ),
          turn.id
        )
      );
    }
    turn.timeline = nextTimeline;
    turn.usage = turnUsageById[turn.id] ?? null;
    turn.durationMs = computeTurnDurationMs(
      turn.userMessage.createdAt,
      turn.answer?.createdAt,
      turn.status,
      turnEvents
    );
  });

  return turns;
}

function matchLiveTurnEvent(event: SessionEventPayload, liveTurn: LiveTurnState) {
  const eventTurnId = readTurnId(event.data);
  if (liveTurn.serverTurnId && eventTurnId === liveTurn.serverTurnId) {
    return true;
  }
  if (eventTurnId === liveTurn.localId) {
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
  const hasAnswerStart = timeline.some((node) => node.kind === "answer_start");
  const shouldShowThinking =
    liveTurn.status === "running" &&
    (liveTurn.answer.phase === "waiting" || liveTurn.answer.phase === "streaming") &&
    !hasRunningThinking &&
    !hasAnswerStart;
  const syntheticThinkingCopy = timeline.length > 0 ? "模型正在准备下一步" : null;
  const nextTimeline = shouldShowThinking
    ? [...timeline, applyTurnIdToNode(buildThinkingNode(thinkingTs, syntheticThinkingCopy, "running", timeline.length > 0 ? "等待模型输出" : "当前思路"), turnId)]
    : timeline;

  return {
    id: turnId,
    requestId: liveTurn.requestId,
    userMessage: liveTurn.userMessage,
    answer: liveTurn.answer,
    timeline: nextTimeline,
    status: liveTurn.status,
    isLive: true,
    usage: null,
    durationMs: computeTurnDurationMs(
      liveTurn.userMessage.createdAt,
      liveTurn.answer.createdAt,
      liveTurn.status,
      turnEvents
    ),
  };
}

function shouldPersistLiveSessionEvent(event: SessionEventPayload) {
  if (event.event === "assistant_delta") {
    return event.data.reset === true;
  }
  if (event.event === "final_response") {
    return false;
  }
  return true;
}

function splitLiveAnswerDelta(delta: string) {
  if (delta.length <= LIVE_ANSWER_MAX_CHARS_PER_FRAME) {
    return [delta];
  }
  const segments: string[] = [];
  for (let index = 0; index < delta.length; index += LIVE_ANSWER_MAX_CHARS_PER_FRAME) {
    segments.push(delta.slice(index, index + LIVE_ANSWER_MAX_CHARS_PER_FRAME));
  }
  return segments;
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

function hasSystemMetaNode(turn: ChatTurn) {
  return turn.timeline.some((node) => node.kind === "system_meta");
}

function turnHasInterruptedEvent(events: SessionEventPayload[]) {
  return events.some((event) => event.event === "turn_interrupted");
}

function hasAwaitingInputTimelineCard(turn: ChatTurn, awaiting: AwaitingUserInputPayload | null | undefined) {
  if (!awaiting) {
    return false;
  }
  return turn.timeline.some((node) =>
    node.secondaryItems.some(
      (item) =>
        item.toolName === "request_user_input" &&
        item.awaitingUserInput &&
        (item.awaitingUserInput.requestId === awaiting.requestId ||
          (Boolean(item.awaitingUserInput.workflowId && awaiting.workflowId) &&
            item.awaitingUserInput.workflowId === awaiting.workflowId &&
            item.awaitingUserInput.phase === awaiting.phase) ||
          (item.awaitingUserInput.skillName === awaiting.skillName &&
            item.awaitingUserInput.phase === awaiting.phase &&
            item.awaitingUserInput.prompt === awaiting.prompt))
    )
  );
}

function resolveAnswerCopy(answer: TurnAnswer | null, status: TurnStatus) {
  if (answer && (answer.content.trim() || answer.attachments.length > 0)) {
    return answer.content;
  }
  if (answer?.phase === "failed") {
    return answer.errorMessage || "这轮执行暂时中断，请查看过程详情。";
  }
  if (status === "failed") {
    return "这轮执行暂时中断，请查看过程详情。";
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

function turnHasFailedHtmlWrite(turn: ChatTurn) {
  return turn.timeline.some((node) =>
    node.secondaryItems.some((item) => item.toolName === "write_file" && item.state === "failed" && item.argumentsPayload && isHtmlWriteFileEventData({
      tool: "write_file",
      success: false,
      arguments: item.argumentsPayload
    }))
  );
}

function shouldRenderAnswerBubble(turn: ChatTurn) {
  if (!turn.answer) {
    return false;
  }

  const hasAttachments = turn.answer.attachments.length > 0;

  if (turn.status === "failed" && !turn.answer.content.trim() && !hasAttachments && hasSystemMetaNode(turn)) {
    return false;
  }

  if (turnHasFailedHtmlWrite(turn) && turn.answer.turnOutcome === "answered") {
    return false;
  }

  if (turn.answer.phase === "persisted" || turn.answer.phase === "finalizing") {
    return Boolean(turn.answer.content.trim()) || hasAttachments;
  }

  if (turn.answer.phase === "failed") {
    return Boolean(turn.answer.content.trim()) || Boolean(turn.answer.errorMessage) || hasAttachments;
  }

  if (turn.answer.phase === "streaming") {
    return Boolean(turn.answer.content.trim()) || hasAttachments;
  }

  return false;
}

function shouldRenderAssistantMessageMeta(turn: ChatTurn) {
  if (!turn.answer) {
    return false;
  }
  if (turn.answer.phase === "persisted" || turn.answer.phase === "failed") {
    return true;
  }
  return turn.status === "completed" || turn.status === "failed";
}

function getAwaitingInputTitle(request: AwaitingUserInputPayload) {
  if (request.kind === "choice") {
    return "等待选择";
  }
  if (request.kind === "free_text") {
    return request.options.length > 0 ? "等待选择或补充" : "等待补充";
  }
  return "等待确认";
}

function shouldDraftAwaitingOption(request: AwaitingUserInputPayload, option: AwaitingUserInputOption, index: number) {
  if (request.kind !== "confirm") {
    return false;
  }
  const normalized = `${option.label} ${option.value}`.toLowerCase();
  return index > 0 || /revise|change|edit|modify|修改|调整|补充|修订|重写|不通过/.test(normalized);
}

function buildAwaitingOptionReply(request: AwaitingUserInputPayload, option: AwaitingUserInputOption) {
  if (request.kind === "confirm" && option.value === "approved") {
    return option.label;
  }
  if (option.value && option.value !== option.label) {
    return `我选择：${option.label}（${option.value}）`;
  }
  return option.label;
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
  const [activeSettingsTab, setActiveSettingsTab] = useState<SettingsTab>(() => {
    const stored = window.localStorage.getItem("newman-settings-tab");
    return isSettingsTab(stored) ? stored : "theme";
  });
  const [uiTheme, setUiTheme] = useState<UiTheme>(() => {
    const stored = window.localStorage.getItem("newman-ui-theme");
    return isUiTheme(stored) ? stored : "classic";
  });
  const [chatSessions, setChatSessions] = useState<ChatSession[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [activeSessionId, setActiveSessionId] = useState(() => window.localStorage.getItem("newman-active-session-id") ?? "");
  const [activeSessionDetail, setActiveSessionDetail] = useState<SessionRecordDetail | null>(null);
  const [activePlan, setActivePlan] = useState<SessionPlanPayload>(null);
  const [activeCollaborationMode, setActiveCollaborationMode] = useState<SessionDetailResponse["collaboration_mode"]>(null);
  const [activeContextUsage, setActiveContextUsage] = useState<SessionDetailResponse["context_usage"]>(null);
  const [activeAwaitingUserInput, setActiveAwaitingUserInput] = useState<AwaitingUserInputPayload | null>(null);
  const [awaitingInputSelections, setAwaitingInputSelections] = useState<Record<string, AwaitingUserInputSelection>>({});
  const [awaitingInputDrafts, setAwaitingInputDrafts] = useState<Record<string, string>>({});
  const [sessionEvents, setSessionEvents] = useState<SessionEventPayload[]>([]);
  const [activeTurnUsageById, setActiveTurnUsageById] = useState<Record<string, TurnUsageSummary>>({});
  const [liveSessionEvents, setLiveSessionEvents] = useState<SessionEventPayload[]>([]);
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [sendingMessage, setSendingMessage] = useState(false);
  const [stoppingMessage, setStoppingMessage] = useState(false);
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
  const [skillDocumentView, setSkillDocumentView] = useState<SkillDocumentView>("preview");
  const [skillSaveNotice, setSkillSaveNotice] = useState<string | null>(null);
  const [skillImportMode, setSkillImportMode] = useState<SkillImportMode>("upload");
  const [skillImportPath, setSkillImportPath] = useState("");
  const [skillUploadName, setSkillUploadName] = useState("");
  const [skillUploadFiles, setSkillUploadFiles] = useState<SkillUploadItem[]>([]);
  const [skillImportReport, setSkillImportReport] = useState<SkillImportReport | null>(null);
  const [showSkillImportPanel, setShowSkillImportPanel] = useState(false);
  const [skillSaving, setSkillSaving] = useState(false);
  const [skillDeleting, setSkillDeleting] = useState(false);
  const [skillImporting, setSkillImporting] = useState(false);
  const [skillTreeEntriesByName, setSkillTreeEntriesByName] = useState<Record<string, WorkspaceEntry[]>>({});
  const [skillTreeErrors, setSkillTreeErrors] = useState<Record<string, string>>({});
  const [skillTreeLoadingByName, setSkillTreeLoadingByName] = useState<Record<string, boolean>>({});
  const [skillFolderEntriesByPath, setSkillFolderEntriesByPath] = useState<Record<string, WorkspaceEntry[]>>({});
  const [skillFolderErrors, setSkillFolderErrors] = useState<Record<string, string>>({});
  const [skillFolderLoadingByPath, setSkillFolderLoadingByPath] = useState<Record<string, boolean>>({});
  const [expandedSkillNames, setExpandedSkillNames] = useState<Record<string, boolean>>({});
  const [expandedSkillFolders, setExpandedSkillFolders] = useState<Record<string, boolean>>({});
  const [workspacePath, setWorkspacePath] = useState(".");
  const [workspaceRootPath, setWorkspaceRootPath] = useState<string | null>(null);
  const [workspaceView, setWorkspaceView] = useState<WorkspaceBrowserResponse | null>(null);
  const [workspaceLoading, setWorkspaceLoading] = useState(false);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [plugins, setPlugins] = useState<PluginRecord[]>([]);
  const [pluginErrors, setPluginErrors] = useState<PluginLoadError[]>([]);
  const [pluginsLoading, setPluginsLoading] = useState(false);
  const [pluginsError, setPluginsError] = useState<string | null>(null);
  const [pluginsNotice, setPluginsNotice] = useState<string | null>(null);
  const [projectConfigPath, setProjectConfigPath] = useState("");
  const [projectConfigContent, setProjectConfigContent] = useState("");
  const [projectConfigDraft, setProjectConfigDraft] = useState("");
  const [projectConfigEffectiveWorkspace, setProjectConfigEffectiveWorkspace] = useState("");
  const [projectConfigSourcePriority, setProjectConfigSourcePriority] = useState<string[]>([]);
  const [configWarnings, setConfigWarnings] = useState<string[]>([]);
  const [configLoading, setConfigLoading] = useState(false);
  const [configSaving, setConfigSaving] = useState(false);
  const [configReloading, setConfigReloading] = useState(false);
  const [configError, setConfigError] = useState<string | null>(null);
  const [configNotice, setConfigNotice] = useState<string | null>(null);
  const [pluginBusyName, setPluginBusyName] = useState<string | null>(null);
  const [leftWidth, setLeftWidth] = useState(() => readStoredNumber("newman-left-rail-width", 220, LEFT_MIN, LEFT_MAX));
  const [htmlPreviewWidth, setHtmlPreviewWidth] = useState(() =>
    readStoredNumber("newman-html-preview-width", HTML_PREVIEW_DEFAULT, HTML_PREVIEW_MIN, HTML_PREVIEW_MAX)
  );
  const [dragging, setDragging] = useState<null | "left" | "html-preview">(null);
  const [viewportWidth, setViewportWidth] = useState(() => window.innerWidth);
  const [expandedTimelineIds, setExpandedTimelineIds] = useState<Record<string, boolean>>({});
  const [approvalMenuOpen, setApprovalMenuOpen] = useState(false);
  const [pendingApproval, setPendingApproval] = useState<PendingApproval | null>(null);
  const [approvalActionLoading, setApprovalActionLoading] = useState<null | "approve" | "reject">(null);
  const [approvalError, setApprovalError] = useState<string | null>(null);
  const [planModeUpdating, setPlanModeUpdating] = useState(false);
  const [composerFocused, setComposerFocused] = useState(false);
  const [composerValue, setComposerValue] = useState("");
  const [pendingComposerMode, setPendingComposerMode] = useState<CollaborationModeName | null>(null);
  const [composerAttachments, setComposerAttachments] = useState<ComposerAttachment[]>([]);
  const [turnApprovalMode, setTurnApprovalMode] = useState<TurnApprovalMode>(() => {
    const stored = window.localStorage.getItem(TURN_APPROVAL_MODE_STORAGE_KEY);
    return isTurnApprovalMode(stored) ? stored : "manual";
  });
  const [environmentLocation, setEnvironmentLocation] = useState<EnvironmentLocationContext | null>(() => {
    const timezone = localTimezone();
    return readCachedEnvironmentLocation(timezone);
  });
  const [htmlPreview, setHtmlPreview] = useState<HtmlPreviewState | null>(null);
  const [htmlPreviewView, setHtmlPreviewView] = useState<HtmlPreviewView>("preview");
  const conversationPaneRef = useRef<HTMLElement | null>(null);
  const chatStageRef = useRef<HTMLDivElement | null>(null);
  const htmlPreviewPanelRef = useRef<HTMLElement | null>(null);
  const composerFileInputRef = useRef<HTMLInputElement | null>(null);
  const skillUploadFileInputRef = useRef<HTMLInputElement | null>(null);
  const skillUploadFolderInputRef = useRef<HTMLInputElement | null>(null);
  const composerTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const composerPlanTrayListRef = useRef<HTMLDivElement | null>(null);
  const activeSessionIdRef = useRef(activeSessionId);
  const activeMessageControllerRef = useRef<AbortController | null>(null);
  const shouldAutoScrollRef = useRef(true);
  const lastComposerPlanFocusRef = useRef<string | null>(null);
  const attachmentPreviewUrlsRef = useRef<string[]>([]);
  const liveAttachmentUrlsRef = useRef<string[]>([]);
  const liveSessionEventQueueRef = useRef<SessionEventPayload[]>([]);
  const environmentLocationRef = useRef<EnvironmentLocationContext | null>(environmentLocation);
  const environmentLocationRefreshRef = useRef<Promise<EnvironmentLocationContext | null> | null>(null);
  const environmentLocationPromptAttemptedRef = useRef(false);
  const liveSessionEventFlushFrameRef = useRef<number | null>(null);
  const liveAnswerQueueRef = useRef<LiveAnswerQueueItem[]>([]);
  const liveAnswerFlushFrameRef = useRef<number | null>(null);
  const pendingFinalAnswerRef = useRef<PendingFinalAnswer | null>(null);
  const liveAnswerDrainPromiseRef = useRef<Promise<void> | null>(null);
  const liveAnswerDrainResolverRef = useRef<(() => void) | null>(null);
  const awaitingInputSelectionsRef = useRef<Record<string, AwaitingUserInputSelection>>({});

  const resolveLiveAnswerDrain = () => {
    const resolver = liveAnswerDrainResolverRef.current;
    liveAnswerDrainResolverRef.current = null;
    liveAnswerDrainPromiseRef.current = null;
    if (resolver) {
      resolver();
    }
  };

  const ensureLiveAnswerDrainPromise = () => {
    if (!liveAnswerDrainPromiseRef.current) {
      liveAnswerDrainPromiseRef.current = new Promise<void>((resolve) => {
        liveAnswerDrainResolverRef.current = resolve;
      });
    }
    return liveAnswerDrainPromiseRef.current;
  };

  const resetLiveAnswerStreaming = () => {
    if (liveAnswerFlushFrameRef.current !== null) {
      window.cancelAnimationFrame(liveAnswerFlushFrameRef.current);
      liveAnswerFlushFrameRef.current = null;
    }
    liveAnswerQueueRef.current = [];
    pendingFinalAnswerRef.current = null;
    resolveLiveAnswerDrain();
  };

  const refreshEnvironmentLocation = async ({
    allowPrompt,
  }: {
    allowPrompt: boolean;
  }): Promise<EnvironmentLocationContext | null> => {
    if (environmentLocationRefreshRef.current) {
      return environmentLocationRefreshRef.current;
    }

    const task = (async () => {
      const timezone = localTimezone();
      const fallbackLocation =
        readCachedEnvironmentLocation(timezone) ??
        environmentLocationRef.current;
      const permissionState = await readGeolocationPermissionState();

      if (!allowPrompt) {
        if (permissionState !== "granted") {
          return fallbackLocation;
        }
      } else {
        if (permissionState === "denied") {
          return fallbackLocation;
        }
        if (permissionState === "prompt") {
          if (environmentLocationPromptAttemptedRef.current) {
            return fallbackLocation;
          }
          environmentLocationPromptAttemptedRef.current = true;
        }
      }

      try {
        const position = await getCurrentGeolocationPosition({
          enableHighAccuracy: false,
          timeout: allowPrompt ? 5000 : 2500,
          maximumAge: 15 * 60 * 1000,
        });
        const resolved = await fetchJson<ResolvedLocationResponse>(`${apiBase}/api/runtime/location/resolve`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
          }),
        });
        if (!resolved.resolved || !resolved.city) {
          return fallbackLocation;
        }
        const nextLocation: EnvironmentLocationContext = {
          city: resolved.city,
          source: resolved.source || "browser_geolocation",
          precision: resolved.precision || "city",
          captured_at_utc: resolved.captured_at_utc || new Date().toISOString(),
          timezone_hint: timezone,
        };
        writeCachedEnvironmentLocation(timezone, nextLocation, ENVIRONMENT_CITY_GEOLOCATION_TTL_MS);
        setEnvironmentLocation(nextLocation);
        return nextLocation;
      } catch {
        return fallbackLocation;
      }
    })();

    const trackedTask = task.finally(() => {
      if (environmentLocationRefreshRef.current === trackedTask) {
        environmentLocationRefreshRef.current = null;
      }
    });
    environmentLocationRefreshRef.current = trackedTask;
    return trackedTask;
  };

  useEffect(() => {
    awaitingInputSelectionsRef.current = awaitingInputSelections;
  }, [awaitingInputSelections]);

  const flushLiveSessionEventQueue = () => {
    liveSessionEventFlushFrameRef.current = null;
    const queuedEvents = liveSessionEventQueueRef.current;
    if (queuedEvents.length === 0) {
      return;
    }
    liveSessionEventQueueRef.current = [];
    setLiveSessionEvents((currentEvents) => coalesceLiveSessionEvents([...currentEvents, ...queuedEvents]));
  };

  const scheduleLiveSessionEventFlush = () => {
    if (liveSessionEventFlushFrameRef.current !== null) {
      return;
    }
    liveSessionEventFlushFrameRef.current = window.requestAnimationFrame(() => {
      flushLiveSessionEventQueue();
    });
  };

  const enqueueLiveSessionEvent = (payload: SessionEventPayload) => {
    liveSessionEventQueueRef.current.push(payload);
    scheduleLiveSessionEventFlush();
  };

  const resetLiveSessionEventQueue = () => {
    if (liveSessionEventFlushFrameRef.current !== null) {
      window.cancelAnimationFrame(liveSessionEventFlushFrameRef.current);
      liveSessionEventFlushFrameRef.current = null;
    }
    liveSessionEventQueueRef.current = [];
  };

  const maybeFinalizeLiveAnswer = (targetLocalId: string) => {
    const pendingFinal = pendingFinalAnswerRef.current;
    if (!pendingFinal || pendingFinal.localId !== targetLocalId) {
      if (liveAnswerQueueRef.current.length === 0) {
        resolveLiveAnswerDrain();
      }
      return;
    }
    pendingFinalAnswerRef.current = null;
    setLiveTurn((currentTurn) => {
      if (!currentTurn || currentTurn.localId !== targetLocalId) {
        return currentTurn;
      }
      return {
        ...currentTurn,
        status: "completed",
        answer: {
          ...currentTurn.answer,
          phase: "finalizing",
          content: pendingFinal.content || currentTurn.answer.content,
          attachments: pendingFinal.attachments.length > 0 ? pendingFinal.attachments : currentTurn.answer.attachments,
          finishReason: pendingFinal.finishReason ?? currentTurn.answer.finishReason,
          turnOutcome: pendingFinal.turnOutcome ?? currentTurn.answer.turnOutcome,
          awaitingUserInput: pendingFinal.awaitingUserInput ?? currentTurn.answer.awaitingUserInput,
          assistantMessageId: pendingFinal.assistantMessageId ?? currentTurn.answer.assistantMessageId,
          createdAt: pendingFinal.createdAt ?? currentTurn.answer.createdAt
        }
      };
    });
    resolveLiveAnswerDrain();
  };

  const scheduleLiveAnswerFlush = (targetLocalId: string) => {
    if (liveAnswerFlushFrameRef.current !== null) {
      return;
    }
    ensureLiveAnswerDrainPromise();
    liveAnswerFlushFrameRef.current = window.requestAnimationFrame(() => {
      liveAnswerFlushFrameRef.current = null;

      const queue = liveAnswerQueueRef.current;
      if (queue.length === 0) {
        maybeFinalizeLiveAnswer(targetLocalId);
        return;
      }

      let consumed = 0;
      let deltaText = "";
      let reset = false;
      let snapshotContent: string | null = null;

      while (queue.length > 0) {
        const nextItem = queue[0];
        if (nextItem.kind === "reset") {
          reset = true;
          deltaText = "";
          snapshotContent = null;
          queue.shift();
          consumed += 1;
          continue;
        }
        if (nextItem.kind === "snapshot") {
          snapshotContent = nextItem.content;
          queue.shift();
          consumed += 1;
          break;
        }
        if (consumed > 0 && deltaText.length >= LIVE_ANSWER_MAX_CHARS_PER_FRAME) {
          break;
        }
        deltaText += nextItem.delta;
        queue.shift();
        consumed += 1;
        if (deltaText.length >= LIVE_ANSWER_MAX_CHARS_PER_FRAME) {
          break;
        }
      }

      if (consumed > 0) {
        setLiveTurn((currentTurn) => {
          if (!currentTurn || currentTurn.localId !== targetLocalId) {
            return currentTurn;
          }
          const baseContent = reset ? "" : currentTurn.answer.content;
          const nextContent = snapshotContent !== null ? snapshotContent : `${baseContent}${deltaText}`;
          return {
            ...currentTurn,
            status: "running",
            answer: {
              ...currentTurn.answer,
              phase: nextContent ? "streaming" : "waiting",
              content: nextContent
            }
          };
        });
      }

      if (queue.length > 0) {
        scheduleLiveAnswerFlush(targetLocalId);
        return;
      }
      maybeFinalizeLiveAnswer(targetLocalId);
    });
  };

  const enqueueLiveAnswerEvent = (targetLocalId: string, payload: SessionEventPayload) => {
    if (payload.event === "assistant_delta") {
      if (payload.data.reset === true) {
        liveAnswerQueueRef.current.push({
          kind: "reset"
        });
      } else if (typeof payload.data.delta === "string" && payload.data.delta) {
        splitLiveAnswerDelta(payload.data.delta).forEach((delta) => {
          liveAnswerQueueRef.current.push({
            kind: "delta",
            delta
          });
        });
      } else if (typeof payload.data.content === "string") {
        liveAnswerQueueRef.current.push({
          kind: "snapshot",
          content: payload.data.content
        });
      }
      scheduleLiveAnswerFlush(targetLocalId);
      return;
    }

    if (payload.event === "final_response") {
      pendingFinalAnswerRef.current = {
        localId: targetLocalId,
        content: typeof payload.data.content === "string" ? payload.data.content : "",
        attachments: parseMessageAttachments(payload.data.attachments),
        finishReason: typeof payload.data.finish_reason === "string" ? payload.data.finish_reason : null,
        turnOutcome: readTurnOutcome(payload.data),
        awaitingUserInput: readAwaitingUserInput(payload.data),
        assistantMessageId: typeof payload.data.message_id === "string" ? payload.data.message_id : null,
        createdAt: typeof payload.data.created_at === "string" ? payload.data.created_at : null
      };
      if (liveAnswerQueueRef.current.length === 0) {
        maybeFinalizeLiveAnswer(targetLocalId);
      } else {
        ensureLiveAnswerDrainPromise();
      }
    }
  };

  const applyHtmlPreviewStreamEvent = (payload: SessionEventPayload) => {
    if (payload.event === "tool_call_started" && isHtmlWriteFileEventData(payload.data)) {
      const path = getEventPathValue(payload.data);
      const toolCallId = typeof payload.data.tool_call_id === "string" ? payload.data.tool_call_id : null;
      const argumentsPayload = extractEventArguments(payload.data);
      const content = argumentsPayload && typeof argumentsPayload.content === "string" ? argumentsPayload.content : "";
      if (content) {
        const fallbackTitle = formatCompactPath(path) ?? "HTML 实时预览";
        setHtmlPreview({
          source: "write_file",
          path,
          toolCallId,
          streaming: true,
          saveStatus: "saving",
          content,
          title: buildHtmlPreviewTitleFromMarkup(content, fallbackTitle),
        });
      }
      return;
    }

    if (payload.event === "tool_call_output_delta") {
      if (payload.data.stream !== "file_content" || !isHtmlWriteFileEventData(payload.data)) {
        return;
      }
      const delta = typeof payload.data.delta === "string" ? payload.data.delta : "";
      if (!delta) {
        return;
      }
      const path = getEventPathValue(payload.data);
      const toolCallId = typeof payload.data.tool_call_id === "string" ? payload.data.tool_call_id : null;
      const fallbackTitle = formatCompactPath(path) ?? "HTML 实时预览";
      setHtmlPreview((currentPreview) => {
        const sameStream =
          currentPreview?.source === "write_file" &&
          ((toolCallId && currentPreview.toolCallId === toolCallId) || currentPreview.path === path);
        const content = sameStream ? `${currentPreview.content}${delta}` : delta;
        return {
          source: "write_file",
          path,
          toolCallId,
          streaming: true,
          saveStatus: "saving",
          content,
          title: buildHtmlPreviewTitleFromMarkup(content, fallbackTitle),
        };
      });
      return;
    }

    if (payload.event === "tool_call_finished" && payload.data.tool === "write_file") {
      const path = getEventPathValue(payload.data);
      const toolCallId = typeof payload.data.tool_call_id === "string" ? payload.data.tool_call_id : null;
      const argumentsPayload = extractEventArguments(payload.data);
      const fallbackContent = argumentsPayload && typeof argumentsPayload.content === "string" ? argumentsPayload.content : "";
      const success = payload.data.success !== false;
      setHtmlPreview((currentPreview) => {
        const eventLooksHtml = isHtmlWriteFileEventData(payload.data);
        const matchesCurrentPreview =
          currentPreview?.source === "write_file" &&
          ((toolCallId && currentPreview.toolCallId === toolCallId) || (path && currentPreview.path === path));
        if (!eventLooksHtml && !matchesCurrentPreview) {
          return currentPreview;
        }
        if (currentPreview?.toolCallId && toolCallId && currentPreview.toolCallId !== toolCallId) {
          return currentPreview;
        }
        if (currentPreview?.path && path && currentPreview.path !== path) {
          return currentPreview;
        }
        const content = currentPreview?.content || fallbackContent;
        if (!content) {
          return currentPreview;
        }
        const title = buildHtmlPreviewTitleFromMarkup(content, currentPreview?.title ?? formatCompactPath(path) ?? "HTML 实时预览");
        return {
          source: "write_file",
          path: currentPreview?.path ?? path,
          toolCallId: currentPreview?.toolCallId ?? toolCallId,
          content,
          streaming: false,
          saveStatus: success ? "saved" : "failed",
          title,
        };
      });
    }
  };

  const waitForLiveAnswerDrain = async (targetLocalId: string) => {
    if (liveAnswerQueueRef.current.length === 0) {
      maybeFinalizeLiveAnswer(targetLocalId);
    }
    if (liveAnswerQueueRef.current.length === 0 && !pendingFinalAnswerRef.current) {
      return;
    }
    await ensureLiveAnswerDrainPromise();
  };

  useEffect(() => {
    activeSessionIdRef.current = activeSessionId;
  }, [activeSessionId]);

  useEffect(() => {
    environmentLocationRef.current = environmentLocation;
  }, [environmentLocation]);

  useEffect(() => {
    void refreshEnvironmentLocation({ allowPrompt: false });
  }, [apiBase]);

  useEffect(() => {
    window.localStorage.setItem("newman-active-page", activePage);
  }, [activePage]);

  useEffect(() => {
    window.localStorage.setItem("newman-settings-tab", activeSettingsTab);
  }, [activeSettingsTab]);

  useEffect(() => {
    window.localStorage.setItem("newman-ui-theme", uiTheme);
    document.body.dataset.newmanTheme = uiTheme;
    return () => {
      delete document.body.dataset.newmanTheme;
    };
  }, [uiTheme]);

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
    window.localStorage.setItem("newman-html-preview-width", `${htmlPreviewWidth}`);
  }, [htmlPreviewWidth]);

  useEffect(() => {
    window.localStorage.setItem(TURN_APPROVAL_MODE_STORAGE_KEY, turnApprovalMode);
  }, [turnApprovalMode]);

  useEffect(() => {
    if (activePage !== "chat") {
      setHtmlPreview(null);
      setHtmlPreviewView("preview");
    }
  }, [activePage]);

  useEffect(() => {
    setHtmlPreview(null);
    setHtmlPreviewView("preview");
    setActiveAwaitingUserInput(null);
    setAwaitingInputSelections({});
    setActiveTurnUsageById({});
  }, [activeSessionId]);

  useEffect(() => {
    if (!htmlPreview) {
      return;
    }

    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        setHtmlPreview(null);
        setHtmlPreviewView("preview");
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [htmlPreview]);

  useEffect(() => {
    return () => {
      attachmentPreviewUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
      attachmentPreviewUrlsRef.current = [];
    };
  }, []);

  useEffect(() => {
    return () => {
      activeMessageControllerRef.current?.abort();
      activeMessageControllerRef.current = null;
      resetLiveAnswerStreaming();
      resetLiveSessionEventQueue();
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
      if (dragging === "left") {
        setLeftWidth(clamp(event.clientX, LEFT_MIN, LEFT_MAX));
        return;
      }

      const stageRect = chatStageRef.current?.getBoundingClientRect();
      const panelRight = htmlPreviewPanelRef.current?.getBoundingClientRect().right ?? stageRect?.right ?? window.innerWidth;
      const maxWidth = stageRect
        ? Math.min(HTML_PREVIEW_MAX, Math.max(HTML_PREVIEW_MIN, stageRect.width - HTML_PREVIEW_MAIN_MIN))
        : HTML_PREVIEW_MAX;
      setHtmlPreviewWidth(clamp(panelRight - event.clientX, HTML_PREVIEW_MIN, maxWidth));
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
        if (preferredId === undefined || activeSessionIdRef.current === preferredId) {
          setActiveSessionId(storedId);
        }
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

      let nextTurnUsageById: Record<string, TurnUsageSummary> = {};
      try {
        const usageUrl = new URL(`${apiBase}/api/sessions/${encodeURIComponent(sessionId)}/usage`);
        usageUrl.searchParams.set("limit", "500");
        const usage = await fetchJson<SessionUsageResponse>(usageUrl.toString(), { signal });
        if (usage.available) {
          nextTurnUsageById = buildTurnUsageSummaries(usage.records);
        }
      } catch (usageError) {
        if (signal?.aborted) {
          return;
        }
        console.warn("Failed to load session usage", { sessionId, usageError });
      }

      if (signal?.aborted || activeSessionIdRef.current !== sessionId) {
        return false;
      }

      const dedupedEvents = dedupeSessionEvents(nextEvents);
      setActiveSessionDetail(detail.session);
      setActivePlan(closePlanIfTaskCompletedSeen(detail.plan ?? null, dedupedEvents));
      setActiveCollaborationMode(detail.collaboration_mode ?? null);
      setActiveContextUsage(detail.context_usage ?? null);
      const nextAwaiting = parseAwaitingUserInputPayload(detail.awaiting_user_input);
      setActiveAwaitingUserInput(nextAwaiting);
      setAwaitingInputSelections((currentSelections) => {
        if (!nextAwaiting) {
          return {};
        }
        const nextSelection = currentSelections[nextAwaiting.requestId];
        return nextSelection ? { [nextAwaiting.requestId]: nextSelection } : {};
      });
      setSessionEvents(dedupedEvents);
      setActiveTurnUsageById(nextTurnUsageById);
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

  async function syncSessionCollaborationMode(
    nextMode: CollaborationModeName,
    options?: { createSessionIfMissing?: boolean }
  ) {
    const createSessionIfMissing = options?.createSessionIfMissing ?? true;
    let sessionId = activeSessionIdRef.current;

    if (!sessionId) {
      if (!createSessionIfMissing) {
        return false;
      }
      sessionId = await ensureSession();
      if (!sessionId) {
        return false;
      }
    }

    const data = await fetchJson<{ updated: boolean; collaboration_mode: NonNullable<SessionDetailResponse["collaboration_mode"]> }>(
      `${apiBase}/api/sessions/${encodeURIComponent(sessionId)}/collaboration-mode`,
      {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ mode: nextMode })
      }
    );
    setActiveCollaborationMode(data.collaboration_mode);
    return true;
  }

  async function updateSessionCollaborationMode(
    nextMode: CollaborationModeName,
    options?: { createSessionIfMissing?: boolean; preserveComposerOverride?: boolean }
  ) {
    if (nextMode === "default" && currentCollaborationMode === "plan" && hasIncompletePlanSteps(activePlan)) {
      const confirmed = window.confirm("当前计划还有未完成事项，仍要退出计划模式吗？");
      if (!confirmed) {
        return false;
      }
    }

    setPlanModeUpdating(true);
    setChatError(null);
    if (!options?.preserveComposerOverride) {
      setPendingComposerMode(nextMode);
    }

    try {
      const updated = await syncSessionCollaborationMode(nextMode, {
        createSessionIfMissing: options?.createSessionIfMissing ?? true
      });
      if (!updated) {
        if (!options?.preserveComposerOverride) {
          setPendingComposerMode(null);
        }
        return false;
      }
      return true;
    } catch (error) {
      if (!options?.preserveComposerOverride) {
        setPendingComposerMode(null);
      }
      setChatError(error instanceof Error ? error.message : "切换模式失败");
      return false;
    } finally {
      setPlanModeUpdating(false);
    }
  }

  async function selectComposerSlashCommand(command: ComposerSlashCommand) {
    setComposerValue("");
    setPendingComposerMode(command.mode);
    if (activeSessionIdRef.current) {
      await updateSessionCollaborationMode(command.mode, {
        createSessionIfMissing: false,
        preserveComposerOverride: true
      });
    }
    requestAnimationFrame(() => {
      composerTextareaRef.current?.focus();
    });
  }

  async function removeComposerModeToken() {
    if ((pendingComposerMode ?? currentCollaborationMode) !== "plan") {
      return;
    }

    if (pendingComposerMode === "plan" && currentCollaborationMode !== "plan") {
      setPendingComposerMode(null);
      requestAnimationFrame(() => {
        composerTextareaRef.current?.focus();
      });
      return;
    }

    setPendingComposerMode("default");
    const updated = await updateSessionCollaborationMode("default", {
      createSessionIfMissing: false,
      preserveComposerOverride: true
    });
    if (!updated) {
      setPendingComposerMode(null);
    }
    requestAnimationFrame(() => {
      composerTextareaRef.current?.focus();
    });
  }

  useEffect(() => {
    const controller = new AbortController();
    void loadChatSessions(controller.signal);
    return () => controller.abort();
  }, [apiBase]);

  useEffect(() => {
    if (!activeSessionId) {
      resetLiveAnswerStreaming();
      resetLiveSessionEventQueue();
      setActiveSessionDetail(null);
      setActivePlan(null);
      setActiveCollaborationMode(null);
      setActiveContextUsage(null);
      setSessionEvents([]);
      setLiveSessionEvents([]);
      setLiveTurn(null);
      setChatLoading(false);
      return;
    }

    const controller = new AbortController();
    resetLiveAnswerStreaming();
    resetLiveSessionEventQueue();
    setActiveSessionDetail(null);
    setActivePlan(null);
    setActiveCollaborationMode(null);
    setActiveContextUsage(null);
    setSessionEvents([]);
    setLiveSessionEvents([]);
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
    }, 10000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activePage, activeSessionId, apiBase]);

  useEffect(() => {
    if (!pendingComposerMode) {
      return;
    }
    if ((activeCollaborationMode?.mode ?? "default") === pendingComposerMode) {
      setPendingComposerMode(null);
    }
  }, [activeCollaborationMode, pendingComposerMode]);

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

  async function fetchWorkspaceDirectoryEntries(targetPath: string, signal?: AbortSignal) {
    const url = new URL(`${apiBase}/api/workspace/files`);
    url.searchParams.set("path", targetPath);
    const data = await fetchJson<WorkspaceBrowserResponse>(url.toString(), { signal });
    return data.type === "dir" ? data.entries : [];
  }

  async function loadSkillDirectoryEntries(skillName: string, directoryPath: string, signal?: AbortSignal) {
    setSkillTreeLoadingByName((current) => ({
      ...current,
      [skillName]: true
    }));
    setSkillTreeErrors((current) => {
      const next = { ...current };
      delete next[skillName];
      return next;
    });

    try {
      const entries = await fetchWorkspaceDirectoryEntries(directoryPath, signal);
      if (signal?.aborted) return;

      setSkillTreeEntriesByName((current) => ({
        ...current,
        [skillName]: entries
      }));
    } catch (error) {
      if (signal?.aborted) return;
      setSkillTreeEntriesByName((current) => ({
        ...current,
        [skillName]: []
      }));
      setSkillTreeErrors((current) => ({
        ...current,
        [skillName]: error instanceof Error ? error.message : "Skill 目录读取失败"
      }));
    } finally {
      if (!signal?.aborted) {
        setSkillTreeLoadingByName((current) => ({
          ...current,
          [skillName]: false
        }));
      }
    }
  }

  async function loadSkillFolderEntries(directoryPath: string, signal?: AbortSignal) {
    setSkillFolderLoadingByPath((current) => ({
      ...current,
      [directoryPath]: true
    }));
    setSkillFolderErrors((current) => {
      const next = { ...current };
      delete next[directoryPath];
      return next;
    });

    try {
      const entries = await fetchWorkspaceDirectoryEntries(directoryPath, signal);
      if (signal?.aborted) return;

      setSkillFolderEntriesByPath((current) => ({
        ...current,
        [directoryPath]: entries
      }));
    } catch (error) {
      if (signal?.aborted) return;
      setSkillFolderEntriesByPath((current) => ({
        ...current,
        [directoryPath]: []
      }));
      setSkillFolderErrors((current) => ({
        ...current,
        [directoryPath]: error instanceof Error ? error.message : "目录读取失败"
      }));
    } finally {
      if (!signal?.aborted) {
        setSkillFolderLoadingByPath((current) => ({
          ...current,
          [directoryPath]: false
        }));
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
    if (!selectedSkillName) return;
    setExpandedSkillNames((current) => (
      current[selectedSkillName]
        ? current
        : {
            ...current,
            [selectedSkillName]: true
          }
    ));
  }, [selectedSkillName]);

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

  useEffect(() => {
    if (activePage !== "skills" || !selectedSkillName) return;
    if (Object.prototype.hasOwnProperty.call(skillTreeEntriesByName, selectedSkillName)) return;

    const selectedSkill = skills.find((item) => item.name === selectedSkillName);
    if (!selectedSkill) return;

    const controller = new AbortController();
    void loadSkillDirectoryEntries(selectedSkill.name, getSkillDirectoryPath(selectedSkill.path), controller.signal);
    return () => controller.abort();
  }, [activePage, selectedSkillName, skills, skillTreeEntriesByName]);

  useEffect(() => {
    if (skillDetail?.readonly) {
      setSkillDocumentView("preview");
    }
  }, [skillDetail?.readonly]);

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

  async function loadProjectConfig(signal?: AbortSignal) {
    setConfigLoading(true);
    setConfigError(null);

    try {
      const data = await fetchJson<ProjectConfigResponse>(`${apiBase}/api/config/project`, { signal });
      if (signal?.aborted) return;
      setProjectConfigPath(data.path);
      setProjectConfigContent(data.content);
      setProjectConfigDraft(data.content);
      setProjectConfigEffectiveWorkspace(data.effective_workspace);
      setProjectConfigSourcePriority(data.source_priority);
    } catch (error) {
      if (signal?.aborted) return;
      setConfigError(error instanceof Error ? error.message : "项目配置加载失败");
    } finally {
      if (!signal?.aborted) {
        setConfigLoading(false);
      }
    }
  }

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
    setConfigNotice(null);
    setConfigWarnings([]);
    void loadPluginsWorkspace(controller.signal);
    void loadProjectConfig(controller.signal);
    return () => controller.abort();
  }, [activePage, apiBase]);

  const isMobile = viewportWidth <= 820;
  const isHtmlPreviewFloating = viewportWidth <= 980;
  const maxHtmlPreviewWidth = useMemo(() => {
    const mainStageWidth = viewportWidth - (isMobile ? 0 : leftWidth + HANDLE_WIDTH) - 12;
    return clamp(mainStageWidth - HTML_PREVIEW_MAIN_MIN, HTML_PREVIEW_MIN, HTML_PREVIEW_MAX);
  }, [isMobile, leftWidth, viewportWidth]);
  const effectiveHtmlPreviewWidth = Math.min(htmlPreviewWidth, maxHtmlPreviewWidth);
  const htmlPreviewPanelStyle = {
    "--html-preview-width": `${effectiveHtmlPreviewWidth}px`
  } as CSSProperties;
  const normalizedHtmlPreviewContent = useMemo(() => {
    if (!htmlPreview) {
      return "";
    }

    if (htmlPreview.initialView === "code") {
      const escapedCode = escapeCodeHtml(htmlPreview.content.trimEnd());
      return `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
      body {
        margin: 0;
        background: #fffaf3;
        color: #2d2722;
        font: 13px/1.65 "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      }
      pre {
        box-sizing: border-box;
        min-height: 100vh;
        margin: 0;
        padding: 18px 20px;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
      }
    </style>
  </head>
  <body>
    <pre>${escapedCode || " "}</pre>
  </body>
</html>`;
    }

    const markup = patchHtmlPreviewMarkupForSandbox(htmlPreview.content.trim());
    if (!markup) {
      return "";
    }

    if (/<html[\s>]/i.test(markup) || /<!doctype html/i.test(markup)) {
      return markup;
    }

    return `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
  </head>
  <body>
${markup}
  </body>
    </html>`;
  }, [htmlPreview]);
  const htmlPreviewCode = htmlPreview?.content ?? "";
  const htmlPreviewCodeHighlight = useMemo(
    () => highlightCode(htmlPreviewCode, htmlPreview?.language ?? "html"),
    [htmlPreviewCode, htmlPreview?.language]
  );
  const htmlPreviewBadge = htmlPreview?.saveStatus === "failed" ? "HTML 未保存" : htmlPreview?.initialView === "code" ? "CODE" : "HTML";
  const openHtmlPreview = (payload: HtmlPreviewPayload) => {
    setHtmlPreview(payload);
    setHtmlPreviewView(payload.initialView ?? "preview");
  };
  const liveTurnLocalId = liveTurn?.localId ?? null;
  const liveTurnRequestId = liveTurn?.requestId ?? null;
  const liveTurnServerTurnId = liveTurn?.serverTurnId ?? null;
  const persistedTurns = useMemo(
    () => buildChatTurns(activeSessionDetail?.session_id ?? "", activeSessionDetail?.messages ?? [], sessionEvents, activeTurnUsageById),
    [activeSessionDetail?.session_id, activeSessionDetail?.messages, sessionEvents, activeTurnUsageById]
  );
  const visiblePersistedTurns = useMemo(
    () => persistedTurns.filter((turn) => !turnMatchesLiveTurn(turn, liveTurn)),
    [persistedTurns, liveTurnLocalId, liveTurnRequestId, liveTurnServerTurnId]
  );
  const liveDisplayTurn = useMemo(
    () => (liveTurn ? buildLiveTurn(liveTurn, liveSessionEvents) : null),
    [liveTurn, liveSessionEvents]
  );
  const displayTurns = useMemo(
    () => (liveDisplayTurn ? [...visiblePersistedTurns, liveDisplayTurn] : visiblePersistedTurns),
    [visiblePersistedTurns, liveDisplayTurn]
  );
  const showEmptyChatState =
    activePage === "chat" &&
    !chatLoading &&
    !sendingMessage &&
    displayTurns.length === 0;
  const contextPressure =
    activeContextUsage?.budget_pressure ??
    (activeContextUsage && activeContextUsage.auto_compact_limit > 0
      ? activeContextUsage.projected_next_prompt_tokens / activeContextUsage.auto_compact_limit
      : null);
  const contextProgress = contextPressure === null ? null : Math.min(Math.max(contextPressure, 0), 1);
  const contextPercent = contextPressure === null ? null : Math.max(0, Math.round(contextPressure * 100));
  const contextRingProgress = contextProgress ?? 0;
  const compactionStageLabel = formatCompactionStage(activeContextUsage?.compaction_stage);
  const compactionFailureLabel = formatCompactionFailureReason(activeContextUsage?.last_compaction_failure_reason);
  const contextStatusLabel = activeContextUsage?.context_irreducible
    ? "当前上下文已不可再压缩"
    : compactionFailureLabel
      ? compactionFailureLabel
      : activeContextUsage?.projected_over_limit
        ? "超过硬线，必须压缩"
        : activeContextUsage?.projected_over_soft_limit
          ? "预计下一轮会压缩"
          : compactionStageLabel ?? "正常";
  const contextFailureDetail =
    activeContextUsage && activeContextUsage.compaction_fail_streak > 0
      ? `连续失败 ${activeContextUsage.compaction_fail_streak} 次`
      : null;
  const contextPercentLabel = contextPercent === null ? "--" : contextPercent > 999 ? "999+" : `${contextPercent}%`;
  const contextRingStateClass = activeContextUsage?.context_irreducible
    ? "is-irreducible"
    : activeContextUsage?.projected_over_limit
      ? "is-over"
      : activeContextUsage?.projected_over_soft_limit
        ? "is-soft"
        : "";
  const contextRingTitle =
    !activeContextUsage
      ? "当前还没有上下文使用量数据"
      : [
          `Context 预算使用率 ${contextPercentLabel}`,
          `预计下一轮：${formatTokenCount(activeContextUsage.projected_next_prompt_tokens)} / ${formatTokenCount(
            activeContextUsage.auto_compact_limit
          )} tokens`,
          `已确认：${formatTokenCount(activeContextUsage.confirmed_prompt_tokens)} / ${formatTokenCount(
            activeContextUsage.effective_context_window
          )} tokens`,
          `状态：${contextStatusLabel}`,
          contextFailureDetail,
        ]
          .filter(Boolean)
          .join("\n");
  const activeApprovalMode = approvalModeMeta[turnApprovalMode];
  const currentCollaborationMode = activeCollaborationMode?.mode ?? "default";
  const composerDisplayMode = pendingComposerMode ?? currentCollaborationMode;
  const activeSettingsTabOption =
    settingsTabOptions.find((option) => option.id === activeSettingsTab) ?? settingsTabOptions[0];
  const activePlanSteps = getPlanSteps(activePlan);
  const activePlanProgress = getPlanProgress(activePlan);
  const showComposerPlanTray = composerDisplayMode === "plan" && activePlanSteps.length > 0 && hasIncompletePlanSteps(activePlan);
  const activeComposerPlanStep =
    activePlanSteps.find((step) => step.status === "in_progress") ??
    activePlanSteps.find((step) => step.status === "blocked") ??
    activePlanSteps.find((step) => step.status !== "completed" && step.status !== "cancelled") ??
    null;
  const slashCommandQuery = extractComposerSlashQuery(composerValue);
  const availableSlashCommands =
    composerDisplayMode === "plan"
      ? []
      : buildComposerSlashCommands().filter((command) =>
          slashCommandQuery === null ? false : !slashCommandQuery || command.keyword.includes(slashCommandQuery)
        );

  useLayoutEffect(() => {
    if (!showComposerPlanTray) {
      lastComposerPlanFocusRef.current = null;
      return;
    }
    if (!activeComposerPlanStep) {
      return;
    }
    const targetKey = `${activeComposerPlanStep.id}:${activeComposerPlanStep.status}`;
    if (lastComposerPlanFocusRef.current === targetKey) {
      return;
    }

    const list = composerPlanTrayListRef.current;
    const target = list?.querySelector<HTMLElement>(`[data-plan-step-id="${activeComposerPlanStep.id}"]`);
    if (!target) {
      return;
    }
    target.scrollIntoView({ block: "nearest", inline: "nearest" });
    lastComposerPlanFocusRef.current = targetKey;
  }, [showComposerPlanTray, activeComposerPlanStep?.id, activeComposerPlanStep?.status]);

  const showComposerSlashMenu =
    composerFocused &&
    slashCommandQuery !== null &&
    !sendingMessage &&
    !stoppingMessage &&
    !planModeUpdating &&
    availableSlashCommands.length > 0;
  const hasMemoryChanges =
    memoryDrafts.memory !== memoryFiles.memory.content || memoryDrafts.user !== memoryFiles.user.content;
  const hasSkillChanges = Boolean(skillDetail && skillDraft !== skillDetail.content);
  const selectedSkillSummary = selectedSkillName ? skills.find((item) => item.name === selectedSkillName) ?? null : null;
  const selectedSkillTreeEntries = selectedSkillName
    ? orderSkillWorkspaceEntries(
        skillTreeEntriesByName[selectedSkillName] ?? [],
        skillDetail?.name === selectedSkillName ? skillDetail.path : selectedSkillSummary?.path ?? null
      )
    : [];
  const selectedSkillTreeError = selectedSkillName ? skillTreeErrors[selectedSkillName] ?? null : null;
  const selectedSkillTreeLoading = Boolean(selectedSkillName && skillTreeLoadingByName[selectedSkillName]);
  const skillUploadSummary = summarizeSkillUploadFiles(skillUploadFiles);
  const skillUploadDirectoryInputProps = { webkitdirectory: "", directory: "" };
  const hasProjectConfigChanges = projectConfigDraft !== projectConfigContent;

  const renderSkillTreeNodes = (skill: SkillSummary, entries: WorkspaceEntry[], depth = 0): ReactNode =>
    entries.map((entry) => {
      const isDirectory = entry.type === "dir";
      const isSkillFile = entry.path === skill.path || entry.name.toLowerCase() === "skill.md";
      const isExpanded = isDirectory ? Boolean(expandedSkillFolders[entry.path]) : false;
      const nextDepth = depth + 1;
      const childEntries = isDirectory
        ? orderSkillWorkspaceEntries(skillFolderEntriesByPath[entry.path] ?? [], skill.path)
        : [];
      const childError = isDirectory ? skillFolderErrors[entry.path] ?? null : null;
      const childLoading = isDirectory ? Boolean(skillFolderLoadingByPath[entry.path]) : false;

      return (
        <div key={entry.path} className="skill-tree-branch">
          {isDirectory ? (
            <button
              type="button"
              className={`skill-tree-node dir ${isExpanded ? "expanded" : ""}`}
              onClick={() => {
                const nextExpanded = !isExpanded;
                setExpandedSkillFolders((current) => ({
                  ...current,
                  [entry.path]: nextExpanded
                }));
                if (
                  nextExpanded &&
                  !Object.prototype.hasOwnProperty.call(skillFolderEntriesByPath, entry.path) &&
                  !skillFolderLoadingByPath[entry.path]
                ) {
                  void loadSkillFolderEntries(entry.path);
                }
              }}
              aria-expanded={isExpanded}
              title={entry.path}
              style={{ paddingInlineStart: `${nextDepth * 18}px` }}
            >
              <span className="skill-tree-node-icon" aria-hidden="true">
                <SkillFolderIcon className="skill-tree-node-icon-svg" />
              </span>
              <span className="skill-tree-node-label">{entry.name}</span>
              <span className={`skill-tree-node-trailing ${isExpanded ? "expanded" : ""}`} aria-hidden="true">
                <ChevronStrokeIcon className="skill-tree-node-chevron" />
              </span>
            </button>
          ) : (
            <div
              className={`skill-tree-node file ${isSkillFile ? "primary" : ""}`}
              title={entry.path}
              style={{ paddingInlineStart: `${nextDepth * 18}px` }}
            >
              <span className="skill-tree-node-icon" aria-hidden="true">
                <SkillFileIcon className="skill-tree-node-icon-svg" />
              </span>
              <span className="skill-tree-node-label">{entry.name}</span>
            </div>
          )}

          {isDirectory && isExpanded ? (
            <div className="skill-tree-children nested">
              {childLoading ? (
                <div className="skill-tree-node muted" style={{ paddingInlineStart: `${(nextDepth + 1) * 18}px` }}>
                  正在读取目录...
                </div>
              ) : null}
              {!childLoading && childError ? (
                <div className="skill-tree-node muted" style={{ paddingInlineStart: `${(nextDepth + 1) * 18}px` }}>
                  {childError}
                </div>
              ) : null}
              {!childLoading && !childError ? renderSkillTreeNodes(skill, childEntries, nextDepth) : null}
              {!childLoading && !childError && childEntries.length === 0 ? (
                <div className="skill-tree-node muted" style={{ paddingInlineStart: `${(nextDepth + 1) * 18}px` }}>
                  该目录下暂无可展示项。
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      );
    });

  const scrollConversationToBottom = () => {
    shouldAutoScrollRef.current = true;
    const pane = conversationPaneRef.current;
    if (!pane) return;
    pane.scrollTop = pane.scrollHeight;
  };

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

    scrollConversationToBottom();
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
      hasConversation: false,
      background: false,
      scheduled: false,
      triggerType: null,
      sourceTaskId: null
    };
    activeSessionIdRef.current = data.session_id;
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
    let pendingBrowserYieldEvents = 0;

    try {
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
          if (
            payload.event === "assistant_delta" ||
            payload.event === "final_response" ||
            payload.event === "tool_call_arguments_delta" ||
            payload.event === "tool_call_output_delta"
          ) {
            pendingBrowserYieldEvents += 1;
            if (pendingBrowserYieldEvents >= LIVE_STREAM_BROWSER_YIELD_EVERY_EVENTS) {
              pendingBrowserYieldEvents = 0;
              await new Promise<void>((resolve) => {
                window.requestAnimationFrame(() => resolve());
              });
            }
          }
        }

        if (done) {
          break;
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  const appendComposerAttachments = (files: File[]) => {
    if (files.length === 0) {
      return;
    }

    setChatError(null);
    if (composerAttachments.length + files.length > MAX_COMPOSER_ATTACHMENTS) {
      setChatError("一次最多上传 5 个附件，请移除多余文件后重试");
      return;
    }

    const additions: ComposerAttachment[] = [];
    let nextError: string | null = null;
    files.forEach((file) => {
      const extension = getAttachmentExtension(file.name);
      if (!COMPOSER_ATTACHMENT_EXTENSIONS.has(extension)) {
        nextError ??= `《${file.name}》格式不支持。支持图片、Word、Excel、PDF、PPT、MD、TXT、JSON、HTML`;
        return;
      }
      if (file.size === 0) {
        nextError ??= `《${file.name}》为空文件，无法上传`;
        return;
      }
      if (file.size > MAX_COMPOSER_ATTACHMENT_BYTES) {
        nextError ??= `《${file.name}》超过 20MB，无法上传`;
        return;
      }
      const previewUrl = isImageAttachmentExtension(extension) ? URL.createObjectURL(file) : null;
      if (previewUrl) {
        attachmentPreviewUrlsRef.current.push(previewUrl);
      }
      additions.push({
        id: makeAttachmentId(`${file.name}:${file.lastModified}:${file.size}`, composerAttachments.length + additions.length),
        file,
        filename: file.name,
        contentType: file.type || "application/octet-stream",
        kind: isImageAttachmentExtension(extension) ? "image" : null,
        extension,
        previewUrl,
        path: null,
        summary: null,
        sizeBytes: file.size,
        workspaceRelativePath: null,
        analysisStatus: null,
        analysisError: null,
      });
    });
    if (additions.length > 0) {
      setComposerAttachments((current) => [...current, ...additions]);
    }
    if (nextError) {
      setChatError(nextError);
    }
  };

  const handleComposerFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    appendComposerAttachments(files);
    event.target.value = "";
  };

  const handleComposerPaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    if (sendingMessage || stoppingMessage || planModeUpdating) {
      return;
    }

    const imageFiles = getClipboardImageFiles(event.clipboardData).map((file, index) => normalizeClipboardAttachmentFile(file, index));
    if (imageFiles.length === 0) {
      return;
    }

    event.preventDefault();
    appendComposerAttachments(imageFiles);
  };

  const appendSkillUploadFiles = (files: File[]) => {
    if (files.length === 0) return;

    setSkillsError(null);
    setSkillSaveNotice(null);
    setSkillImportReport(null);

    const currentByPath = new Map(skillUploadFiles.map((item) => [item.relativePath.toLowerCase(), item]));
    const additions: SkillUploadItem[] = [];
    let nextError: string | null = null;
    let totalBytes = skillUploadFiles.reduce((sum, item) => sum + item.file.size, 0);

    files.forEach((file) => {
      const relativePath = getSkillUploadRelativePath(file);
      const extension = getAttachmentExtension(relativePath).toLowerCase();
      if (!SKILL_UPLOAD_EXTENSIONS.has(extension)) {
        nextError ??= `《${relativePath}》格式不支持，仅支持 MD、Python、JPG、PNG`;
        return;
      }
      if (file.size === 0) {
        nextError ??= `《${relativePath}》为空文件，无法上传`;
        return;
      }
      totalBytes += file.size;
      if (totalBytes > MAX_SKILL_UPLOAD_TOTAL_BYTES) {
        nextError ??= "本次 Skill 上传总大小超过 80MB";
        return;
      }
      const key = relativePath.toLowerCase();
      if (currentByPath.has(key) || additions.some((item) => item.relativePath.toLowerCase() === key)) {
        nextError ??= `《${relativePath}》已在待装载列表中`;
        return;
      }
      additions.push({
        id: makeAttachmentId(`${relativePath}:${file.lastModified}:${file.size}`, skillUploadFiles.length + additions.length),
        file,
        relativePath
      });
    });

    if (skillUploadFiles.length + additions.length > MAX_SKILL_UPLOAD_FILES) {
      setSkillsError(`一次最多上传 ${MAX_SKILL_UPLOAD_FILES} 个 Skill 文件`);
      return;
    }
    if (additions.length > 0) {
      setSkillUploadFiles((current) => [...current, ...additions]);
    }
    if (nextError) {
      setSkillsError(nextError);
    }
  };

  const handleSkillUploadFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    appendSkillUploadFiles(Array.from(event.target.files ?? []));
    event.target.value = "";
  };

  const removeSkillUploadFile = (itemId: string) => {
    setSkillUploadFiles((current) => current.filter((item) => item.id !== itemId));
    setSkillImportReport(null);
  };

  const clearSkillUploadFiles = () => {
    setSkillUploadFiles([]);
    setSkillImportReport(null);
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

  const stopActiveComposerRun = async () => {
    if (stoppingMessage) {
      return;
    }
    const controller = activeMessageControllerRef.current;
    if (!controller) {
      return;
    }

    const sessionId = liveTurn?.sessionId ?? activeSessionIdRef.current;
    if (!sessionId) {
      return;
    }

    setStoppingMessage(true);
    setPendingApproval(null);
    setApprovalError(null);
    setChatError(null);

    try {
      const data = await fetchJson<InterruptTurnResponse>(`${apiBase}/api/sessions/${encodeURIComponent(sessionId)}/interrupt`, {
        method: "POST"
      });
      activeMessageControllerRef.current = null;
      controller.abort();
      resetLiveSessionEventQueue();
      setLiveSessionEvents([]);
      setLiveTurn((currentTurn) =>
        currentTurn
          ? {
              ...currentTurn,
              status: "failed",
              answer: {
                ...currentTurn.answer,
                phase: "failed",
                errorMessage: data.message || "当前任务已停止",
                attachments: [],
                content: ""
              }
            }
          : currentTurn
      );
      await loadChatSessions(undefined, sessionId);
      await loadChatWorkspace(sessionId, undefined, { silent: true });
      setLiveTurn(null);
      resetLiveSessionEventQueue();
      setLiveSessionEvents([]);
    } catch (error) {
      setChatError(error instanceof Error ? error.message : "停止当前任务失败");
    } finally {
      setStoppingMessage(false);
    }
  };

  const submitComposer = async (submission?: { content?: string; attachments?: ComposerAttachment[]; clearComposer?: boolean }) => {
    const submittedContent = submission?.content ?? composerValue;
    const submittedAttachments = submission?.attachments ?? composerAttachments;
    const shouldClearComposer = submission?.clearComposer ?? !submission;
    const trimmed = submittedContent.trim();
    if ((!trimmed && submittedAttachments.length === 0) || sendingMessage) return;
    const awaitedRequestAtSubmit = activeAwaitingUserInput?.requestId ?? null;
    const desiredCollaborationMode = pendingComposerMode ?? currentCollaborationMode;

    setChatError(null);
    setSendingMessage(true);
    const controller = new AbortController();
    activeMessageControllerRef.current = controller;

    const finishStreamingState = () => {
      if (activeMessageControllerRef.current === controller) {
        activeMessageControllerRef.current = null;
      }
      setSendingMessage(false);
    };

    try {
      const sessionId = await ensureSession();
      if (controller.signal.aborted) {
        return;
      }

      if (desiredCollaborationMode !== currentCollaborationMode) {
        const synced = await updateSessionCollaborationMode(desiredCollaborationMode, {
          createSessionIfMissing: false,
          preserveComposerOverride: true
        });
        if (!synced || controller.signal.aborted) {
          return;
        }
      }

      scrollConversationToBottom();
      const createdAt = new Date().toISOString();
      const liveTurnLocalId = `live-turn-${Date.now()}`;
      const attachmentSnapshot = submittedAttachments.map(({ file: _file, ...attachment }) => attachment);
      resetLiveAnswerStreaming();
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
          attachments: [],
          createdAt,
          phase: "waiting",
          source: "live",
          assistantMessageId: null,
          finishReason: null,
          turnOutcome: null,
          awaitingUserInput: null,
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
      if (shouldClearComposer) {
        setComposerValue("");
        setComposerAttachments([]);
      }
      resetLiveSessionEventQueue();
      setLiveSessionEvents([]);
      switchPage("chat");
      const environmentContext = buildEnvironmentContext(environmentLocationRef.current);
      void refreshEnvironmentLocation({ allowPrompt: true });

      const response =
        submittedAttachments.length > 0
          ? await (() => {
              const body = new FormData();
              if (trimmed) {
                body.append("content", trimmed);
              }
              submittedAttachments.forEach((attachment) => {
                body.append("attachments", attachment.file, attachment.filename);
              });
              body.append("approval_mode", turnApprovalMode);
              body.append("environment_context", JSON.stringify(environmentContext));
              return fetch(`${apiBase}/api/sessions/${encodeURIComponent(sessionId)}/messages`, {
                method: "POST",
                body,
                signal: controller.signal,
              });
            })()
          : await fetch(`${apiBase}/api/sessions/${encodeURIComponent(sessionId)}/messages`, {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
              },
              signal: controller.signal,
              body: JSON.stringify({
                content: trimmed,
                approval_mode: turnApprovalMode,
                environment_context: environmentContext,
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

        const payloadTurnId = readTurnId(payload.data);
        if (shouldPersistLiveSessionEvent(payload)) {
          enqueueLiveSessionEvent(payload);
        }
        if (payload.event === "assistant_delta" || payload.event === "final_response") {
          enqueueLiveAnswerEvent(liveTurnLocalId, payload);
        }
        applyHtmlPreviewStreamEvent(payload);
        if (payload.event === "error") {
          resetLiveAnswerStreaming();
        }
        if (payload.event === "collaboration_mode_changed") {
          const modePayload =
            "collaboration_mode" in payload.data && payload.data.collaboration_mode && typeof payload.data.collaboration_mode === "object"
              ? (payload.data.collaboration_mode as NonNullable<SessionDetailResponse["collaboration_mode"]>)
              : null;
          if (modePayload) {
            setActiveCollaborationMode(modePayload);
          }
        }
        if (payload.event === "plan_updated") {
          const planPayload =
            "plan" in payload.data && payload.data.plan && typeof payload.data.plan === "object"
              ? (payload.data.plan as NonNullable<SessionPlanPayload>)
              : null;
          setActivePlan(planPayload);
        }
        if (payload.event === "user_input_requested" || payload.event === "final_response") {
          const awaiting = readAwaitingUserInput(payload.data);
          if (awaiting) {
            setActiveAwaitingUserInput(awaiting);
          } else if (payload.event === "final_response" && readTurnOutcome(payload.data) !== "awaiting_user") {
            setActiveAwaitingUserInput(null);
          }
        }
        if (payload.event === "turn_completed" && readTurnOutcome(payload.data) !== "awaiting_user") {
          setActiveAwaitingUserInput(null);
        }
        if (eventMarksTurnFinalized(payload)) {
          setActivePlan((currentPlan) =>
            shouldClosePlanFromEvent(currentPlan, payload) ? closePlanSteps(currentPlan) : currentPlan
          );
        }
        if (payload.event === "tool_approval_request") {
          const approval = buildPendingApprovalFromEvent(payload);
          if (approval) {
            setPendingApproval(approval);
            setApprovalError(null);
          }
        }
        if (payload.event === "tool_approval_resolved") {
          const approvalRequestId =
            typeof payload.data.approval_request_id === "string" && payload.data.approval_request_id
              ? payload.data.approval_request_id
              : null;
          if (approvalRequestId) {
            setPendingApproval((current) =>
              current?.approval_request_id === approvalRequestId ? null : current
            );
          }
        }
        setLiveTurn((currentTurn) => {
          if (!currentTurn || currentTurn.localId !== liveTurnLocalId) {
            return currentTurn;
          }

          const nextServerTurnId = currentTurn.serverTurnId ?? payloadTurnId;
          const nextTurn = {
            ...currentTurn,
            requestId: currentTurn.requestId ?? payload.request_id ?? null,
            serverTurnId: nextServerTurnId
          };

          if (payload.event === "assistant_delta") {
            if (nextTurn.requestId === currentTurn.requestId && nextTurn.serverTurnId === currentTurn.serverTurnId) {
              return currentTurn;
            }
            return nextTurn;
          }

          if (
            payload.event === "thinking_delta" ||
            payload.event === "thinking_complete" ||
            payload.event === "commentary_delta" ||
            payload.event === "commentary_complete" ||
            payload.event === "tool_call_arguments_delta" ||
            payload.event === "tool_call_output_delta"
          ) {
            return {
              ...nextTurn,
              status: "running"
            };
          }

          if (payload.event === "final_response") {
            return nextTurn;
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
                attachments: [],
                content: nextTurn.answer.content || message
              }
            };
          }

          return nextTurn;
        });
      });
      flushLiveSessionEventQueue();
      await waitForLiveAnswerDrain(liveTurnLocalId);
      finishStreamingState();

      await loadChatSessions(undefined, sessionId);
      const refreshed = await loadChatWorkspace(sessionId, undefined, { silent: true });
      if (awaitedRequestAtSubmit) {
        setAwaitingInputSelections((currentSelections) => {
          const currentSelection = currentSelections[awaitedRequestAtSubmit];
          if (!currentSelection) {
            return currentSelections;
          }
          const stillAwaitingSameRequest = activeAwaitingUserInput?.requestId === awaitedRequestAtSubmit;
          const shouldKeepSelection =
            stillAwaitingSameRequest && awaitingInputSelectionsRef.current[awaitedRequestAtSubmit] === currentSelection;
          if (shouldKeepSelection) {
            return currentSelections;
          }
          const { [awaitedRequestAtSubmit]: _removed, ...remainingSelections } = currentSelections;
          return remainingSelections;
        });
      }
      if (refreshed && activeSessionIdRef.current === sessionId) {
        resetLiveSessionEventQueue();
        setLiveSessionEvents([]);
        setLiveTurn((currentTurn) => (currentTurn && currentTurn.localId === liveTurnLocalId ? null : currentTurn));
      }
      resetLiveAnswerStreaming();
    } catch (error) {
      if (controller.signal.aborted || isAbortError(error)) {
        resetLiveAnswerStreaming();
        resetLiveSessionEventQueue();
        return;
      }
      const message = error instanceof Error ? error.message : "发送消息失败";
      setChatError(message);
      resetLiveAnswerStreaming();
      resetLiveSessionEventQueue();
      setLiveTurn((currentTurn) =>
        currentTurn
          ? {
              ...currentTurn,
              status: "failed",
              answer: {
                ...currentTurn.answer,
                phase: "failed",
                errorMessage: message,
                attachments: [],
                content: currentTurn.answer.content || message
              }
            }
          : currentTurn
      );
    } finally {
      finishStreamingState();
    }
  };

  const resolveApproval = async (action: "approve" | "reject", approvalRequestId: string | null = pendingApproval?.approval_request_id ?? null) => {
    if (!approvalRequestId) return;

    setApprovalActionLoading(action);
    setApprovalError(null);

    try {
      await fetchJson<{ approved: boolean }>(`${apiBase}/api/sessions/${encodeURIComponent(activeSessionId)}/${action}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ approval_request_id: approvalRequestId })
      });
      setPendingApproval((current) =>
        current?.approval_request_id === approvalRequestId ? null : current
      );
    } catch (error) {
      setApprovalError(error instanceof Error ? error.message : "审批操作失败");
    } finally {
      setApprovalActionLoading(null);
    }
  };

  const focusComposerWithAwaitingDraft = (draft = "") => {
    setComposerValue((currentValue) => (currentValue.trim() ? currentValue : draft));
    requestAnimationFrame(() => {
      const textarea = composerTextareaRef.current;
      if (!textarea) {
        return;
      }
      textarea.focus();
      const cursorPosition = textarea.value.length;
      textarea.setSelectionRange(cursorPosition, cursorPosition);
    });
  };

  const markAwaitingInputSubmitted = (request: AwaitingUserInputPayload, selection: AwaitingUserInputSelection) => {
    setAwaitingInputSelections((current) => ({
      ...current,
      [request.requestId]: selection,
    }));
  };

  const updateAwaitingInputDraft = (request: AwaitingUserInputPayload, value: string) => {
    setAwaitingInputDrafts((current) => ({
      ...current,
      [request.requestId]: value,
    }));
  };

  const submitAwaitingFreeText = async (request: AwaitingUserInputPayload) => {
    const content = (awaitingInputDrafts[request.requestId] ?? "").trim();
    if (!content) {
      return;
    }
    markAwaitingInputSubmitted(request, { value: "free_text", label: content });
    await submitComposer({
      content,
      attachments: [],
      clearComposer: true
    });
  };

  const submitAwaitingOption = async (
    request: AwaitingUserInputPayload,
    option: AwaitingUserInputOption,
    index: number
  ) => {
    if (shouldDraftAwaitingOption(request, option, index)) {
      markAwaitingInputSubmitted(request, { value: option.value, label: option.label });
      focusComposerWithAwaitingDraft(`${option.label}：`);
      return;
    }
    markAwaitingInputSubmitted(request, { value: option.value, label: option.label });
    await submitComposer({
      content: buildAwaitingOptionReply(request, option),
      attachments: [],
      clearComposer: true
    });
  };

  const renderAwaitingUserInputCard = (request: AwaitingUserInputPayload, turn: ChatTurn, options?: { compact?: boolean }) => {
    const isSameActiveRequest = Boolean(
      activeAwaitingUserInput &&
        (activeAwaitingUserInput.requestId === request.requestId ||
          (Boolean(activeAwaitingUserInput.workflowId && request.workflowId) &&
            activeAwaitingUserInput.workflowId === request.workflowId &&
            activeAwaitingUserInput.phase === request.phase) ||
          (activeAwaitingUserInput.skillName === request.skillName &&
            activeAwaitingUserInput.phase === request.phase &&
            activeAwaitingUserInput.prompt === request.prompt))
    );
    const belongsToLiveTurn = Boolean(turn.isLive && turn.answer?.awaitingUserInput?.requestId === request.requestId);
    const isActiveRequest = isSameActiveRequest || belongsToLiveTurn;
    const submittedSelection = awaitingInputSelections[request.requestId] ?? null;
    const isSubmittedRequest = Boolean(submittedSelection);
    const requestStateClass = isSubmittedRequest ? "submitted" : isActiveRequest ? "active" : "resolved";
    const isActionDisabled = isSubmittedRequest || !isActiveRequest || sendingMessage || stoppingMessage || planModeUpdating;
    const statusLabel = isSubmittedRequest
      ? submittedSelection?.value === "free_text"
        ? "已回复"
        : "已选择"
      : isActiveRequest
        ? (sendingMessage ? "正在发送" : "等待回复")
        : "已处理";
    const title = getAwaitingInputTitle(request);
    const requestOptions = request.options;
    const freeTextDraft = awaitingInputDrafts[request.requestId] ?? "";
    const showInlineReply = requestOptions.length === 0 || request.kind === "free_text";
    const replyPlaceholder =
      requestOptions.length > 0 ? "没有合适选项时，在这里补充具体说明" : "在这里输入你的回复";
    const replyInputId = `awaiting-input-${request.requestId}-${options?.compact ? "compact" : "full"}`;
    const manualReplyHint = showInlineReply ? "你也可以直接输入你所想的。" : "你也可以直接在底部输入你所想的。";

    return (
      <article className={`awaiting-input-card kind-${request.kind} ${options?.compact ? "compact" : ""} ${
        requestStateClass
      }`}>
        <header className="awaiting-input-card-head">
          <span className="awaiting-input-card-icon" aria-hidden="true">
            <TimelineMarkerIcon name="approval" className="awaiting-input-card-icon-svg" />
          </span>
          <div className="awaiting-input-card-head-copy">
            <div className="awaiting-input-card-title-row">
              <h3>{title}</h3>
              <span className={`awaiting-input-status ${requestStateClass}`}>{statusLabel}</span>
            </div>
          </div>
        </header>

        {request.content ? (
          <div className="awaiting-input-content">
            <MessageContent
              apiBase={apiBase}
              variant="assistant"
              content={request.content}
              attachments={[]}
              className="awaiting-input-content-copy"
              onOpenHtmlPreview={openHtmlPreview}
              deferCodeBlocksUntilComplete={turn.isLive && turn.status === "running"}
            />
          </div>
        ) : null}

        <p className="awaiting-input-prompt">{request.prompt}</p>

        {requestOptions.length > 0 ? (
          <div className="awaiting-input-actions" role="group" aria-label={request.prompt}>
            {requestOptions.map((option, index) => {
              const draftsReply = shouldDraftAwaitingOption(request, option, index);
              const isSelectedOption = submittedSelection?.value === option.value;
              return (
                <button
                  key={`${option.value}:${index}`}
                  type="button"
                  className={`awaiting-input-option ${index === 0 && !draftsReply ? "primary" : "secondary"} ${
                    isSelectedOption ? "selected" : ""
                  }`}
                  onClick={() => void submitAwaitingOption(request, option, index)}
                  disabled={isActionDisabled}
                  aria-pressed={isSelectedOption}
                >
                  <span className="awaiting-input-option-label">{option.label}</span>
                  {option.description ? <span className="awaiting-input-option-description">{option.description}</span> : null}
                </button>
              );
            })}
          </div>
        ) : null}

        <p className="awaiting-input-manual-hint">{manualReplyHint}</p>

        {showInlineReply ? (
          <div className={`awaiting-input-reply ${requestOptions.length > 0 ? "with-options" : ""}`}>
            <label className="awaiting-input-reply-label" htmlFor={replyInputId}>
              {requestOptions.length > 0 ? "或者输入具体回复" : "输入回复"}
            </label>
            <textarea
              id={replyInputId}
              className="awaiting-input-reply-textarea"
              value={freeTextDraft}
              onChange={(event) => updateAwaitingInputDraft(request, event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) {
                  return;
                }
                event.preventDefault();
                void submitAwaitingFreeText(request);
              }}
              placeholder={replyPlaceholder}
              rows={3}
              disabled={isActionDisabled}
            />
            <div className="awaiting-input-reply-footer">
              <span className="awaiting-input-reply-hint">Enter 发送，Shift + Enter 换行</span>
              <button
                type="button"
                className={`awaiting-input-reply-submit ${submittedSelection?.value === "free_text" ? "selected" : ""}`}
                onClick={() => void submitAwaitingFreeText(request)}
                disabled={isActionDisabled || !freeTextDraft.trim()}
                aria-pressed={submittedSelection?.value === "free_text"}
              >
                发送回复
              </button>
            </div>
          </div>
        ) : requestOptions.length === 0 ? (
          <div className="awaiting-input-reply-fallback">
            <button
              type="button"
              className={`awaiting-input-reply-submit ${submittedSelection ? "selected" : ""}`}
              onClick={() => {
                markAwaitingInputSubmitted(request, { value: "free_text", label: "下方回复" });
                focusComposerWithAwaitingDraft();
              }}
              disabled={isActionDisabled}
              aria-pressed={Boolean(submittedSelection)}
            >
              在下方输入回复
            </button>
          </div>
        ) : null}
      </article>
    );
  };

  const handleComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Escape" && showComposerSlashMenu) {
      event.preventDefault();
      setComposerValue("");
      return;
    }

    if (
      event.key === "Backspace" &&
      !composerValue &&
      composerDisplayMode === "plan" &&
      !sendingMessage &&
      !stoppingMessage &&
      !planModeUpdating
    ) {
      event.preventDefault();
      void removeComposerModeToken();
      return;
    }

    if (event.key !== "Enter" || event.shiftKey) {
      return;
    }

    if (slashCommandQuery !== null) {
      event.preventDefault();
      if (availableSlashCommands[0]) {
        void selectComposerSlashCommand(availableSlashCommands[0]);
      }
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
    if (node.secondaryItems.some((item) => item.toolName === "request_user_input")) {
      return true;
    }
    return false;
  };

  const toggleTimelineNode = (node: TimelineNode) => {
    setExpandedTimelineIds((current) => ({
      ...current,
      [node.id]: !isTimelineExpanded(node)
    }));
  };

  const toggleSessionMenu = (sessionId: string) => {
    setOpenSessionMenuId((currentId) => (currentId === sessionId ? null : sessionId));
  };

  const createDraftSession = async () => {
    setSessionsError(null);

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
        setActiveTurnUsageById({});
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
    setSkillImportReport(null);

    try {
      const data = await fetchJson<SkillDetailResponse>(`${apiBase}/api/skills/import`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ source_path: trimmed })
      });
      setSkillImportPath("");
      setShowSkillImportPanel(false);
      setSkillSaveNotice(`已导入 ${data.skill.name}`);
      await loadSkillsWorkspace(undefined, data.skill.name);
    } catch (error) {
      setSkillsError(error instanceof Error ? error.message : "Skill 导入失败");
    } finally {
      setSkillImporting(false);
    }
  };

  const uploadSkill = async () => {
    if (skillUploadFiles.length === 0) return;

    setSkillImporting(true);
    setSkillsError(null);
    setSkillSaveNotice(null);
    setSkillImportReport(null);

    try {
      const formData = new FormData();
      const trimmedName = skillUploadName.trim();
      if (trimmedName) {
        formData.append("skill_name", trimmedName);
      }
      formData.append("optimize_with_llm", "true");
      skillUploadFiles.forEach((item) => {
        formData.append("files", item.file, item.relativePath);
      });

      const data = await fetchJson<SkillDetailResponse>(`${apiBase}/api/skills/upload`, {
        method: "POST",
        body: formData
      });
      setSkillUploadFiles([]);
      setSkillUploadName("");
      setShowSkillImportPanel(false);
      setSkillImportReport(data.import_report ?? null);
      setSkillSaveNotice(`已装载 ${data.skill.name}`);
      await loadSkillsWorkspace(undefined, data.skill.name);
    } catch (error) {
      setSkillsError(error instanceof Error ? error.message : "Skill 上传装载失败");
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
      setSkillTreeEntriesByName((current) => {
        const next = { ...current };
        delete next[skillDetail.name];
        return next;
      });
      setSkillTreeErrors((current) => {
        const next = { ...current };
        delete next[skillDetail.name];
        return next;
      });
      setSkillTreeLoadingByName((current) => {
        const next = { ...current };
        delete next[skillDetail.name];
        return next;
      });
      setExpandedSkillNames((current) => {
        const next = { ...current };
        delete next[skillDetail.name];
        return next;
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

  const saveProjectConfig = async () => {
    setConfigSaving(true);
    setConfigError(null);
    setConfigNotice(null);

    try {
      const data = await fetchJson<UpdateProjectConfigResponse>(`${apiBase}/api/config/project`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ content: projectConfigDraft })
      });
      setProjectConfigPath(data.path);
      setProjectConfigContent(data.content);
      setProjectConfigDraft(data.content);
      setProjectConfigEffectiveWorkspace(data.effective_workspace);
      setConfigWarnings(data.warnings);
      setConfigNotice("newman.yaml 已保存，点击 Reload 后才会切到新配置。");
    } catch (error) {
      setConfigError(error instanceof Error ? error.message : "项目配置保存失败");
    } finally {
      setConfigSaving(false);
    }
  };

  const reloadProjectConfig = async () => {
    if (
      hasProjectConfigChanges &&
      !window.confirm("编辑器里还有未保存修改。Reload 只会加载磁盘上的 newman.yaml，确定继续吗？")
    ) {
      return;
    }

    setConfigReloading(true);
    setConfigError(null);
    setConfigNotice(null);

    try {
      const data = await fetchJson<ReloadProjectConfigResponse>(`${apiBase}/api/config/reload`, {
        method: "POST"
      });
      setProjectConfigPath(data.path);
      setProjectConfigEffectiveWorkspace(data.effective_workspace);
      setConfigWarnings(data.warnings);
      setConfigNotice("运行配置已重新加载，后续请求会使用新的 settings。");
      setWorkspacePath(".");
      setWorkspaceRootPath(null);
      setWorkspaceView(null);
      await Promise.all([loadProjectConfig(), loadPluginsWorkspace()]);
    } catch (error) {
      setConfigError(error instanceof Error ? error.message : "项目配置重载失败");
    } finally {
      setConfigReloading(false);
    }
  };

  const refreshSkillsWorkspace = async () => {
    setSkillImportReport(null);
    setSkillTreeEntriesByName({});
    setSkillTreeErrors({});
    setSkillTreeLoadingByName({});
    setSkillFolderEntriesByPath({});
    setSkillFolderErrors({});
    setSkillFolderLoadingByPath({});
    setExpandedSkillFolders({});
    await loadSkillsWorkspace();
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

  const renderComposerPlanTray = (variant: "footer" | "hero") => {
    if (!showComposerPlanTray || variant !== "footer") {
      return null;
    }

    const progressLabel = `${activePlanProgress.completed}/${activePlanProgress.total} 已完成`;

    return (
      <aside className="composer-plan-tray footer" aria-label="当前执行清单">
        <div className="composer-plan-tray-head">
          <span className="composer-plan-tray-kicker">任务清单</span>
          <div className="composer-plan-tray-meta">
            <span className="composer-plan-tray-progress">{progressLabel}</span>
          </div>
        </div>

        <div ref={composerPlanTrayListRef} className="composer-plan-tray-list" role="list" aria-label="当前执行清单">
          {activePlanSteps.map((step) => (
            <div key={step.id} className={`composer-plan-item status-${step.status}`} role="listitem" data-plan-step-id={step.id}>
              <span className="composer-plan-item-icon" aria-hidden="true">
                <PlanChecklistStatusIcon status={step.status} className="composer-plan-item-icon-svg" />
              </span>
              <span className="composer-plan-item-index">{String(step.index + 1).padStart(2, "0")}</span>
              <span className="composer-plan-item-text" title={step.step}>
                {step.step}
              </span>
              {step.status === "in_progress" ? <span className="composer-plan-item-chip">进行中</span> : null}
              {step.status === "blocked" ? <span className="composer-plan-item-chip blocked">阻塞</span> : null}
            </div>
          ))}
        </div>
      </aside>
    );
  };

  const renderChatComposer = (variant: "footer" | "hero") => {
    const isHero = variant === "hero";
    const showPlanSidecar = showComposerPlanTray && variant === "footer";
    const shellClassName = [
      "composer-shell",
      variant === "hero" ? "composer-shell-hero" : "composer-shell-footer",
      showPlanSidecar ? "composer-shell-with-plan" : ""
    ]
      .filter(Boolean)
      .join(" ");
    const inputClassName = variant === "hero" ? "composer-input composer-input-hero" : "composer-input";
    const isComposerEmpty = !composerValue.trim() && composerAttachments.length === 0;
    const showContextMeter = !isHero;

    return (
      <div className={`composer-main ${variant === "hero" ? "composer-main-hero" : ""}`}>
        <div className={shellClassName}>
          <input
            ref={composerFileInputRef}
            className="composer-file-input"
            type="file"
            accept={COMPOSER_ATTACHMENT_ACCEPT}
            multiple
            onChange={handleComposerFileChange}
            tabIndex={-1}
          />

          <div className={`composer-layout ${showPlanSidecar ? "with-plan-sidecar" : ""}`}>
            <div className={`composer-pane composer-pane-main ${showPlanSidecar ? "has-plan-sidecar" : ""}`}>
              {composerDisplayMode === "plan" ? (
                <div className="composer-mode-token-row">
                  <button
                    type="button"
                    className="composer-mode-token"
                    title="当前处于 Plan mode，删除标签可退出"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => {
                      void removeComposerModeToken();
                    }}
                    disabled={sendingMessage || stoppingMessage || planModeUpdating}
                  >
                    <span className="composer-mode-token-icon" aria-hidden="true">
                      <TimelineMarkerIcon name="plan" className="composer-mode-token-icon-svg" />
                    </span>
                    <span className="composer-mode-token-label">计划模式</span>
                    <span className="composer-mode-token-remove" aria-hidden="true">
                      ×
                    </span>
                  </button>
                </div>
              ) : null}

              <textarea
                ref={composerTextareaRef}
                className={inputClassName}
                value={composerValue}
                onChange={(event) => setComposerValue(event.target.value)}
                onKeyDown={handleComposerKeyDown}
                onPaste={handleComposerPaste}
                onFocus={() => setComposerFocused(true)}
                onBlur={() => setComposerFocused(false)}
                aria-label="message composer"
                placeholder={
                  stoppingMessage
                    ? "正在停止当前任务，请稍候…"
                    : sendingMessage
                      ? "当前正在执行，点击右侧按钮可立即停止…"
                      : "输入你的任务，可附附件；按 Enter 发送，Shift + Enter 换行"
                }
                rows={3}
                disabled={sendingMessage || stoppingMessage}
              />

              {showComposerSlashMenu ? (
                <div className="composer-command-menu" role="menu" aria-label="命令菜单">
                  {availableSlashCommands.map((command) => (
                    <button
                      key={command.id}
                      type="button"
                      className="composer-command-item"
                      role="menuitem"
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => {
                        void selectComposerSlashCommand(command);
                      }}
                    >
                      <span className="composer-command-item-icon" aria-hidden="true">
                        <TimelineMarkerIcon name="plan" className="composer-command-item-icon-svg" />
                      </span>
                      <span className="composer-command-item-label">{command.label}</span>
                    </button>
                  ))}
                </div>
              ) : null}

              {composerAttachments.length > 0 ? (
                <div className="composer-attachments" aria-label="已选择的附件">
                  {composerAttachments.map((attachment) => (
                    <div
                      key={attachment.id}
                      className={`composer-attachment-chip ${isImageAttachmentRecord(attachment) ? "image" : "file"}`}
                    >
                      {isImageAttachmentRecord(attachment) && attachment.previewUrl ? (
                        <img className="composer-attachment-thumb" src={attachment.previewUrl} alt={attachment.filename} title={attachment.filename} />
                      ) : (
                        <div className="composer-attachment-file" title={attachment.filename}>
                          <span className="composer-attachment-badge">
                            {getAttachmentExtension(attachment.filename, attachment.extension).replace(/^\./, "").toUpperCase() || "FILE"}
                          </span>
                          <strong className="composer-attachment-name">{attachment.filename}</strong>
                          {typeof attachment.sizeBytes === "number" ? (
                            <span className="composer-attachment-size">{formatBytes(attachment.sizeBytes)}</span>
                          ) : null}
                        </div>
                      )}
                      <button
                        type="button"
                        className="composer-attachment-remove"
                        aria-label={`移除 ${attachment.filename}`}
                        title={`移除 ${attachment.filename}`}
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
                    className="composer-action-button attach-trigger"
                    aria-label="添加附件"
                    onClick={() => composerFileInputRef.current?.click()}
                    disabled={sendingMessage || stoppingMessage || planModeUpdating}
                  >
                    <span className="session-create-button-mark" aria-hidden="true" />
                  </button>

                  {!isHero ? (
                    <div
                      className={`approval-mini approval-mini-inline ${approvalMenuOpen ? "open" : ""}`}
                      onClick={(event) => event.stopPropagation()}
                    >
                      <button
                        type="button"
                        className="composer-action-button approval-mini-trigger"
                        title={activeApprovalMode.helper}
                        aria-haspopup="menu"
                        aria-expanded={approvalMenuOpen}
                        aria-label="选择本轮审批策略"
                        disabled={planModeUpdating}
                        onClick={() => setApprovalMenuOpen((current) => !current)}
                      >
                        <ApprovalSmallIcon className="approval-mini-icon" />
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
                  {showContextMeter ? (
                    <div className="context-meter">
                      <div
                        className={`context-ring ${contextProgress === null ? "is-empty" : ""} ${contextRingStateClass}`}
                        style={{ ["--context-progress" as string]: String(contextRingProgress) }}
                        aria-label={contextPercent === null ? "Context 预算使用率暂不可用" : `Context 预算使用率 ${contextPercentLabel}`}
                        title={contextRingTitle}
                      >
                        <span>{contextPercentLabel}</span>
                      </div>
                    </div>
                  ) : null}

                  <button
                    type="button"
                    className={`send-trigger send-trigger-inline ${sendingMessage ? "is-running" : ""}`}
                    onClick={() => {
                      if (sendingMessage) {
                        void stopActiveComposerRun();
                        return;
                      }
                      void submitComposer();
                    }}
                    disabled={stoppingMessage || planModeUpdating || (!sendingMessage && isComposerEmpty)}
                    aria-label={sendingMessage ? (stoppingMessage ? "正在停止当前任务" : "停止当前任务") : "发送"}
                    title={sendingMessage ? (stoppingMessage ? "正在停止当前任务" : "点击立即停止当前任务") : "发送"}
                  >
                    {sendingMessage ? (
                      <svg viewBox="0 0 20 20" aria-hidden="true">
                        <rect x="5.25" y="5.25" width="9.5" height="9.5" rx="2.4" fill="currentColor" />
                      </svg>
                    ) : (
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
                    )}
                  </button>
                </div>
              </div>
            </div>

            {showPlanSidecar ? renderComposerPlanTray(variant) : null}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div
      className={`screen-shell ${dragging ? "is-resizing" : ""}`}
      data-theme={uiTheme}
      style={{
        gridTemplateColumns: isMobile ? "1fr" : `${leftWidth}px ${HANDLE_WIDTH}px minmax(0, 1fr)`
      }}
    >
      <aside className="left-rail">
        <div className="brand">
          <div className="brand-logo">
            <img src={logo} alt="NewMan logo" className="brand-logo-image" />
          </div>
          <div className="brand-copy">
            <h1>NewMan</h1>
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
            <button
              type="button"
              className="session-create-button"
              aria-label="新建会话"
              onClick={() => void createDraftSession()}
            >
              <span className="session-create-button-mark" aria-hidden="true" />
            </button>
          </div>

          {sessionsError ? <div className="workspace-alert error">{sessionsError}</div> : null}
          {sessionsLoading && chatSessions.length === 0 ? <div className="workspace-empty">正在加载会话...</div> : null}

          <div className="session-list">
            {!sessionsLoading && chatSessions.length === 0 ? <div className="workspace-empty">当前还没有会话，点击右上角开始。</div> : null}
            {chatSessions.map((session) => {
              const displayTitle = session.scheduled ? scheduledSessionTitle(session.title) : session.title;
              return (
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
                    <span className={`session-title ${session.scheduled ? "scheduled" : ""}`}>
                      {session.scheduled ? <ScheduledSessionIcon className="session-scheduled-icon" /> : null}
                      <span className="session-title-text">{displayTitle}</span>
                    </span>
                    {!session.scheduled && session.background ? (
                      <span className="session-meta-line">
                        <span className="session-tag muted">后台</span>
                      </span>
                    ) : null}
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
                        onClick={() => {
                          setActiveSessionId(session.id);
                          setOpenSessionMenuId(null);
                          switchPage("automations");
                        }}
                      >
                        <svg viewBox="0 0 24 24" aria-hidden="true">
                          <path
                            d="M7 2v3M17 2v3M4 7h16M6 4h12a2 2 0 0 1 2 2v11a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3V6a2 2 0 0 1 2-2Zm2 6h3v3H8v-3Zm5 0h3v3h-3v-3Zm-5 5h3v2H8v-2Zm5 0h3v2h-3v-2Z"
                            fill="currentColor"
                          />
                        </svg>
                        <span>定时任务</span>
                      </button>
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
              );
            })}
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
                    <img src={logo} alt="NewMan logo" className="chat-empty-brand-image" />
                  </div>
                  <div className="chat-empty-brand-copy">
                    <h2>
                      <span className="chat-empty-brand-name">NewMan</span>
                      <span className="chat-empty-brand-for">for</span>
                      <span className="chat-empty-brand-cn">牛马</span>
                    </h2>
                  </div>
                </div>

                {renderChatComposer("hero")}
              </div>
            </section>
          ) : (
            <div
              ref={chatStageRef}
              className={`chat-stage ${htmlPreview ? "with-html-preview" : ""}`}
              style={htmlPreviewPanelStyle}
            >
              <div className="chat-stage-main">
                <section
                  ref={conversationPaneRef}
                  className="conversation-pane conversation-pane-floating"
                >
                  {chatError ? <div className="workspace-alert error">{chatError}</div> : null}
                  {chatLoading ? (
                    <div
                      className="chat-session-loading"
                      role="status"
                      aria-live="polite"
                      aria-label="正在加载会话内容"
                    >
                      <span className="chat-session-loading-spinner" aria-hidden="true" />
                    </div>
                  ) : null}

                  {!chatLoading ? (
                    <>
                      {displayTurns.length === 0 ? <div className="workspace-empty">这个会话还没有内容，直接开始提需求就行。</div> : null}

                      {displayTurns.map((turn) => {
                        const answerCopy = resolveAnswerCopy(turn.answer, turn.status);
                        const showAssistantMessageMeta = shouldRenderAssistantMessageMeta(turn);
                        const awaitingInput = turn.answer?.awaitingUserInput ?? null;
                        const showAwaitingInputInAnswer = Boolean(awaitingInput && !hasAwaitingInputTimelineCard(turn, awaitingInput));
                        const showAnswerBubble = shouldRenderAnswerBubble(turn) && (!awaitingInput || showAwaitingInputInAnswer);
                        const assistantCopyValue =
                          turn.answer?.content.trim() ? turn.answer.content : turn.answer?.phase === "failed" ? answerCopy : null;
                        const visibleThinkingNode = turn.timeline.find(
                          (node) => node.kind === "thinking" && node.state === "running" && turn.isLive
                        );
                        const hasVisibleThinkingNode = Boolean(visibleThinkingNode);
                        const visibleTimelineNodes = turn.timeline.filter((node) => node.kind !== "thinking");
                        const shouldShowTimelineStack = visibleTimelineNodes.length > 0 || hasVisibleThinkingNode;
                        return (
                          <div key={turn.id} className={`turn-block ${turn.isLive ? "live" : ""}`}>
                            <div className="user-row">
                              <div className="turn-user-stack">
                                <MessageHoverShell
                                  shellClassName="user"
                                  align="end"
                                  timestamp={turn.userMessage.createdAt}
                                  copyValue={turn.userMessage.content}
                                  copyLabel="用户输入"
                                >
                                  <div className={`user-bubble ${turn.userMessage.attachments.length > 0 ? "has-attachments" : ""}`}>
                                    <MessageContent
                                      apiBase={apiBase}
                                      variant="user"
                                      content={turn.userMessage.content}
                                      attachments={turn.userMessage.attachments}
                                    />
                                  </div>
                                </MessageHoverShell>
                              </div>
                            </div>

                            {shouldShowTimelineStack ? (
                              <div className="timeline-stack trace-turn-column">
                                {visibleTimelineNodes.map((node, index) => {
                                  if (node.kind === "system_meta") {
                                    const systemHasHead = index > 0;
                                    const systemHasTail = index < visibleTimelineNodes.length - 1 || hasVisibleThinkingNode;
                                    return (
                                      <div key={node.id} className="timeline-system-row">
                                        <div
                                          className={`timeline-primary-marker rail-only ${systemHasHead ? "has-head" : ""} ${
                                            systemHasTail ? "has-tail" : ""
                                          }`}
                                        />
                                        <div className="timeline-system-meta" role="status" aria-live="polite">
                                          <span className="timeline-system-meta-text">{node.primaryText}</span>
                                        </div>
                                      </div>
                                    );
                                  }

                                  if (node.kind === "approval" && node.approval) {
                                    const expanded = isTimelineExpanded(node);
                                    const markerIcon = resolveTimelineNodeIcon(node);
                                    const hasHead = index > 0;
                                    const hasTail = index < visibleTimelineNodes.length - 1 || hasVisibleThinkingNode;
                                    const payloadPreview = buildApprovalPayloadPreview(node.approval);
                                    const payloadCodePreview = buildTimelineCodePreview(
                                      node.approval.tool,
                                      payloadPreview,
                                      node.approval.arguments
                                    );
                                    const payloadLabel = buildApprovalPayloadLabel(node.approval);
                                    const isActivePendingApproval =
                                      pendingApproval?.approval_request_id === node.approval.approvalRequestId;
                                    const showPendingActions = node.state === "pending";
                                    const showResolvedDetail = !showPendingActions && Boolean(payloadPreview);
                                    const detailCardClass = node.approval.tool === "terminal" ? "terminal" : "generic";

                                    return (
                                      <article
                                        key={node.id}
                                        className={`timeline-node ${expanded ? "expanded" : ""} state-${node.state} kind-${node.kind}`}
                                      >
                                        <div className={`timeline-primary-marker ${hasHead ? "has-head" : ""} ${hasTail ? "has-tail" : ""}`}>
                                          <span className="timeline-marker-icon-wrap" aria-hidden="true">
                                            <TimelineMarkerIcon name={markerIcon} className="timeline-marker-icon" />
                                          </span>
                                        </div>

                                        <div className="timeline-primary-copy">
                                          <div className="timeline-approval-primary">
                                            <p className="timeline-primary-text">{node.primaryText}</p>
                                            {!showPendingActions ? (
                                              <span className={`timeline-approval-status-tag state-${node.state}`}>
                                                {buildApprovalStateLabel(node.state)}
                                              </span>
                                            ) : null}
                                          </div>

                                          {showPendingActions ? (
                                            <div className="timeline-approval-action-row">
                                              <button
                                                type="button"
                                                className="timeline-approval-button ghost"
                                                onClick={() => void resolveApproval("reject", node.approval?.approvalRequestId ?? null)}
                                                disabled={approvalActionLoading !== null || !isActivePendingApproval}
                                              >
                                                {approvalActionLoading === "reject" && isActivePendingApproval ? "拒绝中..." : "拒绝"}
                                              </button>
                                              <button
                                                type="button"
                                                className="timeline-approval-button solid"
                                                onClick={() => void resolveApproval("approve", node.approval?.approvalRequestId ?? null)}
                                                disabled={approvalActionLoading !== null || !isActivePendingApproval}
                                              >
                                                {approvalActionLoading === "approve" && isActivePendingApproval ? "允许中..." : "允许继续"}
                                              </button>
                                            </div>
                                          ) : null}

                                          {approvalError && showPendingActions && isActivePendingApproval ? (
                                            <div className="workspace-alert error timeline-approval-error">{approvalError}</div>
                                          ) : null}

                                          {showResolvedDetail ? (
                                            <button
                                              type="button"
                                              className={`timeline-tool-toggle ${expanded ? "expanded" : ""}`}
                                              onClick={() => toggleTimelineNode(node)}
                                              aria-expanded={expanded}
                                              aria-controls={`timeline-panel-${node.id}`}
                                            >
                                              <span className="timeline-tool-toggle-label">查看参数</span>
                                            </button>
                                          ) : null}

                                          {showResolvedDetail ? (
                                            <div
                                              id={`timeline-panel-${node.id}`}
                                              className={`timeline-secondary-region ${expanded ? "expanded" : ""}`}
                                              aria-hidden={!expanded}
                                            >
                                              <div className="timeline-secondary-region-inner">
                                                <div className="timeline-secondary-list">
                                                  <article className={`timeline-secondary-card ${detailCardClass}`}>
                                                    <div className="timeline-secondary-head">
                                                      <div className="timeline-secondary-head-main">
                                                        <div className="timeline-secondary-label-row">
                                                          <span className="timeline-secondary-label">{payloadLabel}</span>
                                                          <span className="timeline-secondary-time-inline">{node.time}</span>
                                                        </div>
                                                      </div>
                                                    </div>
                                                    <div className="timeline-secondary-result-wrap timeline-code-block">
                                                      <pre className={`timeline-secondary-result timeline-code-block-pre ${detailCardClass === "terminal" ? "terminal" : ""}`}>
                                                        <code
                                                          className={payloadCodePreview.language ? `language-${payloadCodePreview.language}` : undefined}
                                                          dangerouslySetInnerHTML={{ __html: payloadCodePreview.html }}
                                                        />
                                                      </pre>
                                                    </div>
                                                  </article>
                                                </div>
                                              </div>
                                            </div>
                                          ) : null}
                                        </div>
                                      </article>
                                    );
                                  }

                                  const expanded = isTimelineExpanded(node);
                                  const markerIcon = resolveTimelineNodeIcon(node);
                                  const hasHead = index > 0;
                                  const hasTail = index < visibleTimelineNodes.length - 1 || hasVisibleThinkingNode;
                                  return (
                                    <article
                                      key={node.id}
                                      className={`timeline-node ${expanded ? "expanded" : ""} state-${node.state} kind-${node.kind}`}
                                    >
                                      <div className={`timeline-primary-marker ${hasHead ? "has-head" : ""} ${hasTail ? "has-tail" : ""}`}>
                                        <span className="timeline-marker-icon-wrap" aria-hidden="true">
                                          <TimelineMarkerIcon name={markerIcon} className="timeline-marker-icon" />
                                        </span>
                                      </div>

                                      <div className="timeline-primary-copy">
                                        <p className="timeline-primary-text">{node.primaryText}</p>

                                        {node.secondaryItems.length > 0 ? (
                                          <button
                                            type="button"
                                            className={`timeline-tool-toggle ${expanded ? "expanded" : ""}`}
                                            onClick={() => toggleTimelineNode(node)}
                                            aria-expanded={expanded}
                                            aria-controls={`timeline-panel-${node.id}`}
                                          >
                                            <span className="timeline-tool-toggle-label">{buildTimelineToolSummary(node)}</span>
                                          </button>
                                        ) : null}

                                        {node.secondaryItems.length > 0 ? (
                                          <div
                                            id={`timeline-panel-${node.id}`}
                                            className={`timeline-secondary-region ${expanded ? "expanded" : ""}`}
                                            aria-hidden={!expanded}
                                          >
                                            <div className="timeline-secondary-region-inner">
                                              <div className="timeline-secondary-list">
                                                {node.secondaryItems.map((item) => {
                                                  const resultText = buildTimelineSecondaryResultText(item, {
                                                    isTurnRunning: turn.isLive && turn.status === "running",
                                                  });
                                                  const resultCodePreview = buildTimelineCodePreview(
                                                    item.toolName,
                                                    resultText,
                                                    item.argumentsPayload
                                                  );
                                                  return (
                                                    <article
                                                      key={item.id}
                                                      className={`timeline-secondary-card ${item.cardType} ${
                                                        item.awaitingUserInput ? "awaiting-input-secondary-card" : ""
                                                      }`}
                                                    >
                                                      {item.awaitingUserInput ? (
                                                        renderAwaitingUserInputCard(item.awaitingUserInput, turn, { compact: true })
                                                      ) : (
                                                        <>
                                                          <div className="timeline-secondary-head">
                                                            <div className="timeline-secondary-head-main">
                                                              <div className="timeline-secondary-label-row">
                                                                <div className="timeline-secondary-title-row">
                                                                  <span className="timeline-secondary-label">{item.label}</span>
                                                                  <span className={`timeline-secondary-status-tag tone-${item.statusTone}`}>
                                                                    {item.statusLabel}
                                                                  </span>
                                                                </div>
                                                                <span className="timeline-secondary-time-inline">{item.detail.time}</span>
                                                              </div>
                                                            </div>
                                                          </div>
                                                          <div className="timeline-secondary-result-wrap timeline-code-block">
                                                            {item.cardType === "terminal" && item.command ? (
                                                              <pre className="timeline-terminal-command">{`$ ${item.command}`}</pre>
                                                            ) : null}
                                                            <pre
                                                              className={`timeline-secondary-result timeline-code-block-pre ${
                                                                item.cardType === "terminal" ? "terminal" : ""
                                                              }`}
                                                            >
                                                              <code
                                                                className={resultCodePreview.language ? `language-${resultCodePreview.language}` : undefined}
                                                                dangerouslySetInnerHTML={{ __html: resultCodePreview.html }}
                                                              />
                                                            </pre>
                                                          </div>
                                                        </>
                                                      )}
                                                    </article>
                                                  );
                                                })}
                                              </div>
                                            </div>
                                          </div>
                                        ) : null}
                                      </div>
                                    </article>
                                  );
                                })}

                                {visibleThinkingNode ? (
                                  <article className="timeline-node timeline-thinking-node" aria-label="Thinking">
                                    <div
                                      className={`timeline-primary-marker rail-only ${
                                        visibleTimelineNodes.length > 0 ? "has-head" : ""
                                      }`}
                                    />

                                    <div className="timeline-primary-copy timeline-thinking-copy">
                                      <div className="thinking-logo-row">
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
                                    </div>
                                  </article>
                                ) : null}
                              </div>
                            ) : null}

                            {showAnswerBubble ? (
                              <div className="trace-row">
                                <MessageHoverShell
                                  shellClassName="assistant"
                                  align="start"
                                  timestamp={turn.answer?.createdAt ?? turn.userMessage.createdAt}
                                  copyValue={showAssistantMessageMeta ? assistantCopyValue : null}
                                  copyLabel="回复"
                                  showMeta={showAssistantMessageMeta && Boolean(turn.answer)}
                                  turnUsage={turn.usage}
                                  durationMs={turn.durationMs}
                                >
                                  <div className="trace-bubble wide final answer-bubble">
                                    {awaitingInput ? (
                                      renderAwaitingUserInputCard(awaitingInput, turn)
                                    ) : (
                                      <MessageContent
                                        apiBase={apiBase}
                                        variant="assistant"
                                        content={answerCopy}
                                        attachments={turn.answer?.attachments ?? []}
                                        className="trace-copy"
                                        onOpenHtmlPreview={openHtmlPreview}
                                        deferCodeBlocksUntilComplete={turn.isLive && turn.status === "running"}
                                      />
                                    )}
                                  </div>
                                </MessageHoverShell>
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

              <aside
                ref={htmlPreviewPanelRef}
                className={`html-preview-panel ${htmlPreview ? "open" : ""}`}
                aria-label="HTML 预览面板"
              >
                {htmlPreview && !isHtmlPreviewFloating ? (
                  <div
                    className="html-preview-resize-handle"
                    onPointerDown={(event) => {
                      event.preventDefault();
                      setDragging("html-preview");
                    }}
                    role="separator"
                    aria-orientation="vertical"
                    aria-label="调整 HTML 预览宽度"
                  />
                ) : null}
                <div className="html-preview-panel-inner">
                  <div className="html-preview-frame-topbar">
                    <div className="html-preview-frame-topbar-main">
                      <span className="html-preview-frame-badge">{htmlPreviewBadge}</span>
                      <span className="html-preview-frame-title">
                        {htmlPreview?.streaming ? "生成中 · " : htmlPreview?.saveStatus === "failed" ? "写入失败 · " : ""}
                        {htmlPreview?.title ?? "HTML 实时预览"}
                      </span>
                    </div>
                    <div className="html-preview-frame-actions">
                      <div className="html-preview-view-toggle" role="group" aria-label="HTML 查看模式">
                        <button
                          type="button"
                          className={htmlPreviewView === "preview" ? "active" : ""}
                          onClick={() => setHtmlPreviewView("preview")}
                          aria-pressed={htmlPreviewView === "preview"}
                          title="预览模式"
                        >
                          <EyePanelIcon className="html-preview-view-toggle-icon" />
                          <span>预览</span>
                        </button>
                        <button
                          type="button"
                          className={htmlPreviewView === "code" ? "active" : ""}
                          onClick={() => setHtmlPreviewView("code")}
                          aria-pressed={htmlPreviewView === "code"}
                          title="代码模式"
                        >
                          <CodePanelIcon className="html-preview-view-toggle-icon" />
                          <span>代码</span>
                        </button>
                      </div>
                      <button
                        type="button"
                        className="html-preview-panel-close"
                        onClick={() => {
                          setHtmlPreview(null);
                          setHtmlPreviewView("preview");
                        }}
                        aria-label="关闭 HTML 预览"
                      >
                        <ClosePanelIcon className="html-preview-panel-close-icon" />
                      </button>
                    </div>
                  </div>
                  <div className={`html-preview-frame-stage ${htmlPreviewView === "code" ? "code-mode" : "preview-mode"}`}>
                    {htmlPreview && htmlPreviewView === "preview" ? (
                      <iframe
                        key={`${htmlPreview.path ?? htmlPreview.title}:${htmlPreview.streaming ? "streaming" : "complete"}`}
                        className="html-preview-iframe"
                        title={htmlPreview.title}
                        srcDoc={normalizedHtmlPreviewContent}
                        sandbox="allow-downloads allow-forms allow-modals allow-popups allow-scripts"
                        referrerPolicy="no-referrer"
                      />
                    ) : null}
                    {htmlPreview && htmlPreviewView === "code" ? (
                      <pre className="chat-code-block-pre html-preview-code">
                        <code
                          className={htmlPreviewCodeHighlight.language ? `language-${htmlPreviewCodeHighlight.language}` : undefined}
                          dangerouslySetInnerHTML={{ __html: htmlPreviewCodeHighlight.html || "&nbsp;" }}
                        />
                      </pre>
                    ) : null}
                  </div>
                </div>
              </aside>
            </div>
          )
        ) : null}

        {activePage === "automations" ? (
          <AutomationsPage
            apiBase={apiBase}
            sessions={chatSessions}
            activeSession={chatSessions.find((session) => session.id === activeSessionId) ?? null}
            onRefreshSessions={async (preferredSessionId) => {
              await loadChatSessions(undefined, preferredSessionId)
            }}
            onOpenSession={(sessionId) => {
              setActiveSessionId(sessionId)
              switchPage("chat")
            }}
          />
        ) : null}

        {activePage === "evolution" ? <EvolutionPage apiBase={apiBase} /> : null}

        {activePage === "skills" ? (
          <section className="workspace-page skills-workspace-page">
            {skillsError ? <div className="workspace-alert error">{skillsError}</div> : null}
            {skillSaveNotice ? <div className="workspace-alert success">{skillSaveNotice}</div> : null}

            <div className="skills-workspace-shell">
              <aside className="skills-browser-pane">
                <div className="skills-browser-pane-head">
                  <div className="skills-browser-actions">
                    <button
                      type="button"
                      className={`skills-toolbar-button primary ${showSkillImportPanel ? "active" : ""}`}
                      onClick={() => {
                        setShowSkillImportPanel((current) => !current);
                        setSkillSaveNotice(null);
                      }}
                    >
                      <PlusSmallIcon className="skills-toolbar-button-icon" />
                      <span>{showSkillImportPanel ? "收起导入" : "导入 Skill"}</span>
                    </button>
                    <button
                      type="button"
                      className="skills-toolbar-button"
                      onClick={() => void refreshSkillsWorkspace()}
                      disabled={skillsLoading}
                    >
                      <RefreshSmallIcon className="skills-toolbar-button-icon" />
                      <span>{skillsLoading ? "刷新中..." : "刷新列表"}</span>
                    </button>
                  </div>

                  {showSkillImportPanel ? (
                    <div className="skill-import-inline">
                      <div className="skill-import-mode-toggle" role="tablist" aria-label="Skill import mode">
                        <button
                          type="button"
                          className={skillImportMode === "upload" ? "active" : ""}
                          onClick={() => {
                            setSkillImportMode("upload");
                            setSkillsError(null);
                          }}
                          aria-pressed={skillImportMode === "upload"}
                        >
                          上传装载
                        </button>
                        <button
                          type="button"
                          className={skillImportMode === "path" ? "active" : ""}
                          onClick={() => {
                            setSkillImportMode("path");
                            setSkillsError(null);
                          }}
                          aria-pressed={skillImportMode === "path"}
                        >
                          路径导入
                        </button>
                      </div>

                      {skillImportMode === "upload" ? (
                        <div className="skill-upload-loader">
                          <input
                            ref={skillUploadFileInputRef}
                            className="visually-hidden"
                            type="file"
                            multiple
                            accept={SKILL_UPLOAD_ACCEPT}
                            onChange={handleSkillUploadFileChange}
                          />
                          <input
                            ref={skillUploadFolderInputRef}
                            className="visually-hidden"
                            type="file"
                            multiple
                            accept={SKILL_UPLOAD_ACCEPT}
                            onChange={handleSkillUploadFileChange}
                            {...skillUploadDirectoryInputProps}
                          />
                          <input
                            className="workspace-text-input"
                            value={skillUploadName}
                            onChange={(event) => setSkillUploadName(event.target.value)}
                            placeholder="skill id（可选）"
                          />
                          <div className="skill-upload-dropzone">
                            <div className="skill-upload-dropzone-copy">
                              <strong>{skillUploadSummary}</strong>
                              <span>MD / Python / JPG / PNG</span>
                            </div>
                            <div className="skill-upload-actions">
                              <button
                                type="button"
                                className="skills-toolbar-button"
                                onClick={() => skillUploadFileInputRef.current?.click()}
                                disabled={skillImporting}
                              >
                                <SkillFileIcon className="skills-toolbar-button-icon" />
                                <span>文件</span>
                              </button>
                              <button
                                type="button"
                                className="skills-toolbar-button"
                                onClick={() => skillUploadFolderInputRef.current?.click()}
                                disabled={skillImporting}
                              >
                                <SkillFolderIcon className="skills-toolbar-button-icon" />
                                <span>文件夹</span>
                              </button>
                            </div>
                          </div>

                          {skillUploadFiles.length > 0 ? (
                            <div className="skill-upload-file-list">
                              {skillUploadFiles.slice(0, 5).map((item) => (
                                <div className="skill-upload-file-row" key={item.id}>
                                  <span>{item.relativePath}</span>
                                  <strong>{formatBytes(item.file.size)}</strong>
                                  <button type="button" onClick={() => removeSkillUploadFile(item.id)} disabled={skillImporting}>
                                    移除
                                  </button>
                                </div>
                              ))}
                              {skillUploadFiles.length > 5 ? (
                                <div className="skill-upload-file-row muted">还有 {skillUploadFiles.length - 5} 个文件</div>
                              ) : null}
                            </div>
                          ) : null}

                          <div className="skill-import-submit-row">
                            <button
                              type="button"
                              className="workspace-secondary-button"
                              onClick={clearSkillUploadFiles}
                              disabled={skillImporting || skillUploadFiles.length === 0}
                            >
                              清空
                            </button>
                            <button
                              type="button"
                              className="workspace-primary-button"
                              onClick={() => void uploadSkill()}
                              disabled={skillImporting || skillUploadFiles.length === 0}
                            >
                              {skillImporting ? "装载中..." : "装载 Skill"}
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="skill-import-path-row">
                          <input
                            id="skill-import-path"
                            className="workspace-text-input"
                            value={skillImportPath}
                            onChange={(event) => setSkillImportPath(event.target.value)}
                            onKeyDown={(event) => {
                              if (event.key === "Enter" && skillImportPath.trim()) {
                                event.preventDefault();
                                void importSkill();
                              }
                            }}
                            placeholder="例如 imports/my_custom_skill"
                          />
                          <button
                            type="button"
                            className="workspace-primary-button"
                            onClick={() => void importSkill()}
                            disabled={skillImporting || !skillImportPath.trim()}
                          >
                            {skillImporting ? "导入中..." : "确认导入"}
                          </button>
                        </div>
                      )}
                    </div>
                  ) : null}

                  {skillImportReport ? (
                    <div className="skill-import-report">
                      <strong>{skillImportReport.optimizer === "llm" ? "LLM 已优化" : "已完成装载"}</strong>
                      <span>
                        {skillImportReport.file_count} 个源文件 · {skillImportReport.normalized_files.length} 个目录文件
                      </span>
                      {skillImportReport.warnings.length > 0 ? <span>{skillImportReport.warnings[0]}</span> : null}
                    </div>
                  ) : null}
                </div>

                <div className="skills-browser-pane-body">
                  {skillsLoading ? <div className="workspace-empty">正在加载 Skills...</div> : null}

                  {!skillsLoading ? (
                    <div className="skills-tree-list">
                      {skills.length === 0 ? <div className="workspace-empty">当前还没有可用 Skill。</div> : null}
                      {skills.map((skill) => {
                        const isSelected = selectedSkillName === skill.name;
                        const isExpanded = Boolean(expandedSkillNames[skill.name]);
                        const nodeEntries = isSelected
                          ? selectedSkillTreeEntries
                          : orderSkillWorkspaceEntries(skillTreeEntriesByName[skill.name] ?? [], skill.path);
                        const nodeError = skillTreeErrors[skill.name] ?? null;
                        const nodeLoading = isSelected ? selectedSkillTreeLoading : Boolean(skillTreeLoadingByName[skill.name]);
                        const skillDirectoryPath = getSkillDirectoryPath(skill.path);

                        return (
                          <article
                            key={`${skill.source}-${skill.name}-${skill.path}`}
                            className={`skill-tree-item ${isSelected ? "active" : ""} ${isExpanded ? "expanded" : ""}`}
                          >
                            <button
                              type="button"
                              className="skill-tree-trigger"
                              onClick={() => {
                                setSelectedSkillName(skill.name);
                                setSkillDocumentView("preview");
                                setSkillSaveNotice(null);
                                const nextExpanded = isSelected ? !isExpanded : true;
                                setExpandedSkillNames((current) => ({
                                  ...current,
                                  [skill.name]: nextExpanded
                                }));
                                if (
                                  nextExpanded &&
                                  !Object.prototype.hasOwnProperty.call(skillTreeEntriesByName, skill.name) &&
                                  !skillTreeLoadingByName[skill.name]
                                ) {
                                  void loadSkillDirectoryEntries(skill.name, skillDirectoryPath);
                                }
                              }}
                              aria-expanded={isExpanded}
                              title={skill.description || skill.summary || skill.name}
                            >
                              <span className="skill-tree-icon-shell" aria-hidden="true">
                                <SkillSidebarIcon className="skill-tree-icon" />
                              </span>
                              <span className="skill-tree-copy">
                                <strong>{skill.name}</strong>
                              </span>
                              <span className={`skill-tree-chevron ${isExpanded ? "expanded" : ""}`} aria-hidden="true">
                                <ChevronStrokeIcon className="skill-tree-chevron-icon" />
                              </span>
                            </button>

                            {isExpanded ? (
                              <div className="skill-tree-children">
                                {nodeLoading ? <div className="skill-tree-node muted">正在读取 Skill 目录...</div> : null}
                                {!nodeLoading && nodeError ? <div className="skill-tree-node muted">{nodeError}</div> : null}
                                {!nodeLoading && !nodeError ? renderSkillTreeNodes(skill, nodeEntries) : null}
                                {!nodeLoading && !nodeError && nodeEntries.length === 0 ? (
                                  <div className="skill-tree-node muted">该 Skill 目录下暂无可展示项。</div>
                                ) : null}
                              </div>
                            ) : null}
                          </article>
                        );
                      })}
                    </div>
                  ) : null}
                </div>
              </aside>

              <section className="skills-detail-pane">
                <div className="skills-detail-pane-head">
                  <div className="skills-detail-title">
                    <h3>{skillDetail?.name || selectedSkillName || "选择一个 Skill"}</h3>
                    <p className="skills-detail-path">
                      {skillDetail ? skillDetail.path : "选择一个 Skill 后查看并编辑 SKILL.md。"}
                    </p>
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

                <div className="skills-detail-pane-body">
                  {skillDetailLoading ? <div className="workspace-empty">正在加载 Skill 详情...</div> : null}

                  {!skillDetailLoading && !skillDetail ? (
                    <div className="workspace-empty skills-empty-state">先从左侧选择一个 Skill，或导入新的 Skill 文件夹。</div>
                  ) : null}

                  {!skillDetailLoading && skillDetail ? (
                    <div className="skills-detail-scroll">
                      <div className="skills-summary-strip">
                        <div className="skills-summary-field">
                          <span>来源</span>
                          <strong>{skillSourceLabel(skillDetail)}</strong>
                        </div>
                        <div className="skills-summary-field">
                          <span>目录</span>
                          <strong title={skillDetail.directory_path}>{skillDetail.directory_path}</strong>
                        </div>
                      </div>

                      <div className="skills-detail-section">
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

                      <div className="skills-detail-section">
                        <span className="workspace-field-label">使用限制</span>
                        <p className="workspace-copy">
                          {skillDetail.usage_limits_summary || "暂未提取到明确限制，可直接查看下方 SKILL.md。"}
                        </p>
                      </div>

                      <div className="skills-markdown-panel">
                        <div className="skills-markdown-panel-head">
                          <div>
                            <span className="workspace-field-label">SKILL.md</span>
                            <p className="skills-markdown-panel-copy">预览排版或切换到源码编辑，整体交互参照原生文档查看器。</p>
                          </div>
                          <div className="skills-view-toggle" role="tablist" aria-label="Skill document view switcher">
                            <button
                              type="button"
                              className={skillDocumentView === "preview" ? "active" : ""}
                              onClick={() => setSkillDocumentView("preview")}
                              aria-pressed={skillDocumentView === "preview"}
                              title="预览"
                            >
                              <svg viewBox="0 0 24 24" aria-hidden="true">
                                <path
                                  d="M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6-10-6-10-6Z"
                                  fill="none"
                                  stroke="currentColor"
                                  strokeWidth="1.7"
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                />
                                <circle cx="12" cy="12" r="3.1" fill="none" stroke="currentColor" strokeWidth="1.7" />
                              </svg>
                            </button>
                            <button
                              type="button"
                              className={skillDocumentView === "edit" ? "active" : ""}
                              onClick={() => setSkillDocumentView("edit")}
                              aria-pressed={skillDocumentView === "edit"}
                              title="编辑"
                              disabled={skillDetail.readonly}
                            >
                              <svg viewBox="0 0 24 24" aria-hidden="true">
                                <path
                                  d="m4 18 4.2-1 9.4-9.4a1.8 1.8 0 0 0-2.6-2.6L5.6 14.4 4.6 18.6 9 17.6"
                                  fill="none"
                                  stroke="currentColor"
                                  strokeWidth="1.7"
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                />
                                <path
                                  d="M13.8 6.2 17.8 10.2"
                                  fill="none"
                                  stroke="currentColor"
                                  strokeWidth="1.7"
                                  strokeLinecap="round"
                                />
                              </svg>
                            </button>
                          </div>
                        </div>

                        <div className={`skills-markdown-surface ${skillDocumentView === "edit" ? "editing" : "previewing"}`}>
                          {skillDocumentView === "preview" ? (
                            <div className="skills-markdown-render">
                              <ReactMarkdown remarkPlugins={[remarkGfm]}>{skillDraft}</ReactMarkdown>
                            </div>
                          ) : (
                            <textarea
                              className="workspace-editor skills-editor"
                              value={skillDraft}
                              onChange={(event) => {
                                setSkillDraft(event.target.value);
                                setSkillSaveNotice(null);
                              }}
                              spellCheck={false}
                              disabled={skillDetail.readonly}
                            />
                          )}
                        </div>
                        {!skillDetail.readonly ? (
                          <span className="workspace-tiny-note">保存后会立即刷新 Skill 列表。</span>
                        ) : null}
                      </div>
                    </div>
                  ) : null}
                </div>
              </section>
            </div>
          </section>
        ) : null}

        {activePage === "settings" ? (
          <section className="workspace-page settings-page">
            <div className="workspace-page-head">
              <div>
                <h2>{activeSettingsTabOption.label}</h2>
              </div>
              <div className="workspace-page-actions">
                {activeSettingsTab === "plugins" ? (
                  <button
                    type="button"
                    className="workspace-secondary-button"
                    onClick={() => void rescanPlugins()}
                    disabled={pluginsLoading}
                  >
                    {pluginsLoading ? "扫描中..." : "重新扫描插件"}
                  </button>
                ) : null}
              </div>
            </div>

            <div className="workspace-tabbar" role="tablist" aria-label="设置分区">
              {settingsTabOptions.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  role="tab"
                  className={`workspace-tab ${activeSettingsTab === option.id ? "active" : ""}`}
                  aria-selected={activeSettingsTab === option.id}
                  onClick={() => setActiveSettingsTab(option.id)}
                >
                  {option.label}
                </button>
              ))}
            </div>

            {configError ? <div className="workspace-alert error">{configError}</div> : null}
            {configNotice ? <div className="workspace-alert success">{configNotice}</div> : null}
            {pluginsError ? <div className="workspace-alert error">{pluginsError}</div> : null}
            {pluginsNotice ? <div className="workspace-alert success">{pluginsNotice}</div> : null}

            <div className="workspace-stack">
              {activeSettingsTab === "theme" ? (
                <article className="workspace-card">
                  <div className="workspace-card-head">
                    <div>
                      <h3>界面主题</h3>
                      <p>保留当前原版配色，同时新增一套按参考图提炼的主题，可随时切换。</p>
                    </div>
                  </div>

                  <div className="workspace-card-body">
                    <div className="theme-grid">
                      {uiThemeOptions.map((option) => {
                        const active = option.id === uiTheme;
                        return (
                          <button
                            key={option.id}
                            type="button"
                            className={`theme-card ${active ? "active" : ""}`}
                            onClick={() => setUiTheme(option.id)}
                            aria-pressed={active}
                          >
                            <div className={`theme-card-preview ${option.previewClass}`} aria-hidden="true">
                              <span className="theme-preview-rail" />
                              <span className="theme-preview-stage" />
                              <span className="theme-preview-panel theme-preview-panel-hero" />
                              <span className="theme-preview-panel theme-preview-panel-body" />
                            </div>

                            <div className="theme-card-copy">
                              <p className="theme-card-kicker">{option.kicker}</p>
                              <div className="theme-card-headline">
                                <strong>{option.label}</strong>
                                <span className={`workspace-pill ${active ? "accent" : "subtle"}`}>{active ? "当前使用" : "点击切换"}</span>
                              </div>
                              <p>{option.description}</p>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </article>
              ) : null}

              {activeSettingsTab === "config" ? (
                <article className="workspace-card">
                  <div className="workspace-card-head">
                    <div>
                      <h3>项目配置</h3>
                      <p>{projectConfigPath || "正在定位 newman.yaml"}</p>
                    </div>
                    <div className="workspace-inline-actions">
                      <button
                        type="button"
                        className="workspace-secondary-button"
                        onClick={() => void saveProjectConfig()}
                        disabled={configLoading || configSaving || !hasProjectConfigChanges}
                      >
                        {configSaving ? "保存中..." : "保存配置"}
                      </button>
                      <button
                        type="button"
                        className="workspace-primary-button"
                        onClick={() => void reloadProjectConfig()}
                        disabled={configLoading || configReloading || configSaving}
                      >
                        {configReloading ? "Reload 中..." : "Reload 生效"}
                      </button>
                    </div>
                  </div>

                  <div className="workspace-card-body">
                    {configLoading ? <div className="workspace-empty">正在加载 newman.yaml...</div> : null}

                    {!configLoading ? (
                      <>
                        <div className="workspace-info-grid">
                          <div className="workspace-mini-card">
                            <span className="workspace-mini-label">当前生效 workspace</span>
                            <strong>{projectConfigEffectiveWorkspace || "未识别"}</strong>
                          </div>
                          <div className="workspace-mini-card">
                            <span className="workspace-mini-label">编辑状态</span>
                            <strong>{hasProjectConfigChanges ? "有未保存修改" : "磁盘内容已同步"}</strong>
                          </div>
                        </div>

                        <div className="workspace-detail-block">
                          <span className="workspace-field-label">生效顺序</span>
                          <p className="workspace-copy">
                            {projectConfigSourcePriority.length > 0
                              ? projectConfigSourcePriority.join(" > ")
                              : "environment > ~/.newman/config.yaml > newman.yaml > defaults.yaml"}
                          </p>
                        </div>

                        <div className="workspace-detail-block">
                          <span className="workspace-field-label">说明</span>
                          <p className="workspace-copy">
                            保存只会写回项目根目录的 <code>newman.yaml</code>。点击 Reload 后，新的 runtime、scheduler 和 channels
                            才会切到这份配置。
                          </p>
                        </div>

                        {configWarnings.length > 0 ? (
                          <div className="workspace-detail-block">
                            <span className="workspace-field-label">重载提示</span>
                            <div className="workspace-list">
                              {configWarnings.map((warning) => (
                                <div key={warning} className="workspace-list-row static">
                                  <p className="workspace-row-copy">{warning}</p>
                                </div>
                              ))}
                            </div>
                          </div>
                        ) : null}

                        <div className="workspace-detail-block">
                          <span className="workspace-field-label">newman.yaml</span>
                          <textarea
                            className="workspace-editor"
                            value={projectConfigDraft}
                            onChange={(event) => {
                              setProjectConfigDraft(event.target.value);
                              setConfigNotice(null);
                              setConfigError(null);
                            }}
                            spellCheck={false}
                          />
                        </div>
                      </>
                    ) : null}
                  </div>
                </article>
              ) : null}

              {activeSettingsTab === "plugins" ? (
                <>
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
                </>
              ) : null}

              {activeSettingsTab === "usage" ? <UsageDashboard apiBase={apiBase} embedded /> : null}
            </div>
          </section>
        ) : null}
      </main>

    </div>
  );
}

export default App;
