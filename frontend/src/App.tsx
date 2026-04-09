import { useEffect, useState, type KeyboardEvent } from "react";
import logo from "./assets/newman-logo.png";
import "./styles.css";

type MemoryKey = "memory" | "user";
type TurnApprovalMode = "manual" | "auto_approve_level2";

type MemoryFile = {
  path: string;
  content: string;
};

type MemoryWorkspaceResponse = {
  files: Record<string, MemoryFile>;
};

type SubmittedTurn = {
  id: string;
  content: string;
  submittedAt: string;
  approvalMode: TurnApprovalMode;
};

const navItems = [
  { id: "chat", label: "Chat", hint: "对话" },
  { id: "memory", label: "Memory", hint: "记忆" },
  { id: "skills", label: "Skills", hint: "技能" },
  { id: "files", label: "Files", hint: "文件" }
];

const initialChatSessions = [
  { id: "chat2work", title: "Chat2work 项目架构评审" },
  { id: "contract-compare", title: "供应商合同抽取与比对" },
  { id: "weekly-report", title: "经营周报问答" }
];
const messageEntries = [
  {
    id: "thinking",
    type: "trace",
    time: "2026-03-18 19:42",
    text: "thinking...",
    detailTitle: "thinking...",
    summary:
      "主 Agent 先拆解目标，识别到用户既需要最新新闻结果，也需要全过程透明展示，因此先规划工具调用链路和最终答复结构。",
    inputs: ["intent = 最新新闻 + 全链路透明", "steps = search -> filter -> digest -> summarize"],
    citations: ["内部推理节点，无外部引用"]
  },
  {
    id: "bing-search",
    type: "tool",
    time: "2026-03-18 19:42",
    text: "bing_search 工具调用中",
    detailTitle: "bing_search",
    summary: "正在检索和曼联相关的最新新闻，并按发布时间和来源可信度进行排序。",
    inputs: [
      "bing_search.query = 曼联 最新 新闻",
      "bing_search.top_k = 5",
      "sort = published_at desc"
    ],
    citations: ["BBC", "The Guardian", "Reuters"]
  },
  {
    id: "news-digest",
    type: "skill",
    time: "2026-03-18 19:42",
    text: "news_digest skill 调用中",
    detailTitle: "news_digest",
    summary: "把搜索结果去重、压缩并整理成可引用的新闻摘要，输出给最终答复使用。",
    inputs: [
      "skill = news_digest",
      "input = search_results[]",
      "output = concise digest"
    ],
    citations: ["skill://news_digest"]
  },
  {
    id: "agent-collab",
    type: "agent",
    time: "2026-03-18 19:43",
    text: "多 Agent 协同构建中",
    detailTitle: "多 Agent 协同构建中",
    summary: "Planner 负责拆解任务，Retriever 负责拿来源，Writer 负责最终组织输出。",
    inputs: ["planner => 任务拆解", "retriever => 来源汇总", "writer => 生成回答"],
    citations: ["agent://planner", "agent://retriever", "agent://writer"],
    tags: [
      { label: "Planner 完成", tone: "blue" },
      { label: "Retriever 进行中", tone: "green" },
      { label: "Writer 等待输入", tone: "orange" }
    ]
  },
  {
    id: "final",
    type: "result",
    time: "2026-03-18 19:45",
    text: "曼联最新动态已汇总：包含比赛结果、伤病更新与转会传闻。核心结论在此，详细证据与原始内容请查看右侧 Drawer。",
    detailTitle: "最终结论",
    summary: "最终答复聚合多源新闻，并保留引用入口，方便继续追问或跳转到原文。",
    inputs: ["summary.length = concise", "citations.visible = true"],
    citations: ["BBC 链接", "The Guardian 链接", "club_report.pdf 第3页"],
    tags: [
      { label: "BBC 链接", tone: "blue" },
      { label: "The Guardian 链接", tone: "green" },
      { label: "club_report.pdf 第3页", tone: "orange" }
    ]
  }
];

const approvalModeMeta: Record<
  TurnApprovalMode,
  {
    label: string;
    helper: string;
    status: string;
  }
> = {
  auto_approve_level2: {
    label: "全部默认通过",
    helper: "本轮命中 Level 2 的工具默认放行，不再逐个弹确认。",
    status: "本轮已锁定为 Level 2 默认通过"
  },
  manual: {
    label: "逐个确认 Level 2",
    helper: "本轮每个命中 Level 2 的工具都需要你点击确认后才继续。",
    status: "本轮已锁定为 Level 2 逐个确认"
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

function getApiBase() {
  if (import.meta.env.VITE_API_BASE) {
    return import.meta.env.VITE_API_BASE;
  }
  return `${window.location.protocol}//${window.location.hostname}:8005`;
}

function formatTurnTimestamp(date: Date) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

function App() {
  const apiBase = getApiBase();
  const [activeNavId, setActiveNavId] = useState("chat");
  const [chatSessions, setChatSessions] = useState(initialChatSessions);
  const [activeSessionId, setActiveSessionId] = useState(initialChatSessions[0]?.id ?? "");
  const [openSessionMenuId, setOpenSessionMenuId] = useState<string | null>(null);
  const [memoryFiles, setMemoryFiles] = useState<Record<MemoryKey, MemoryFile>>({
    memory: { path: "", content: "" },
    user: { path: "", content: "" }
  });
  const [memoryDrafts, setMemoryDrafts] = useState<Record<MemoryKey, string>>({
    memory: "",
    user: ""
  });
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [memorySaving, setMemorySaving] = useState(false);
  const [memoryError, setMemoryError] = useState<string | null>(null);
  const [memorySaveNotice, setMemorySaveNotice] = useState<string | null>(null);
  const [leftWidth, setLeftWidth] = useState(220);
  const [rightWidth, setRightWidth] = useState(320);
  const [dragging, setDragging] = useState<null | "left" | "right">(null);
  const [viewportWidth, setViewportWidth] = useState(() => window.innerWidth);
  const [openDetailId, setOpenDetailId] = useState<string | null>(null);
  const [composerValue, setComposerValue] = useState("");
  const [turnApprovalMode, setTurnApprovalMode] = useState<TurnApprovalMode>("manual");
  const [lastSubmittedTurn, setLastSubmittedTurn] = useState<SubmittedTurn | null>(null);

  useEffect(() => {
    const onResize = () => setViewportWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    const handleWindowClick = () => setOpenSessionMenuId(null);
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

  useEffect(() => {
    if (activeNavId !== "memory") return;

    const controller = new AbortController();

    async function loadMemoryWorkspace() {
      setMemoryLoading(true);
      setMemoryError(null);
      setMemorySaveNotice(null);

      try {
        const response = await fetch(`${apiBase}/api/workspace/memory`, { signal: controller.signal });
        if (!response.ok) {
          throw new Error(`Memory 加载失败：${response.status}`);
        }

        const data = (await response.json()) as MemoryWorkspaceResponse;
        const nextFiles = {
          memory: data.files.memory ?? { path: "", content: "" },
          user: data.files.user ?? { path: "", content: "" }
        };

        setMemoryFiles(nextFiles);
        setMemoryDrafts({
          memory: nextFiles.memory.content,
          user: nextFiles.user.content
        });
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
  }, [activeNavId, apiBase]);

  const isMobile = viewportWidth <= 820;
  const selectedDetail = messageEntries.find((entry) => entry.id === openDetailId) ?? null;
  const activeApprovalMode = approvalModeMeta[turnApprovalMode];

  const submitComposer = () => {
    const trimmed = composerValue.trim();
    if (!trimmed) return;

    setLastSubmittedTurn({
      id: `${Date.now()}`,
      content: trimmed,
      submittedAt: formatTurnTimestamp(new Date()),
      approvalMode: turnApprovalMode
    });
    setComposerValue("");
  };

  const handleComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey) {
      return;
    }
    event.preventDefault();
    submitComposer();
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

  const renameSession = (sessionId: string) => {
    setChatSessions((currentSessions) =>
      currentSessions.map((session) =>
        session.id === sessionId
          ? { ...session, title: session.title.includes("（重命名）") ? session.title : `${session.title}（重命名）` }
          : session
      )
    );
    setOpenSessionMenuId(null);
  };

  const deleteSession = (sessionId: string) => {
    const nextSessions = chatSessions.filter((session) => session.id !== sessionId);
    setChatSessions(nextSessions);
    if (activeSessionId === sessionId) {
      setActiveSessionId(nextSessions[0]?.id ?? "");
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
      await Promise.all(
        (["memory", "user"] as MemoryKey[]).map(async (key) => {
          const response = await fetch(`${apiBase}/api/workspace/memory/${key}`, {
            method: "PUT",
            headers: {
              "Content-Type": "application/json"
            },
            body: JSON.stringify({ content: memoryDrafts[key] })
          });

          if (!response.ok) {
            throw new Error(`${key.toUpperCase()} 保存失败：${response.status}`);
          }
        })
      );

      setMemoryFiles((currentFiles) => ({
        memory: { ...currentFiles.memory, content: memoryDrafts.memory },
        user: { ...currentFiles.user, content: memoryDrafts.user }
      }));
      setMemorySaveNotice("已保存到 MEMORY.md 和 USER.md");
    } catch (error) {
      setMemoryError(error instanceof Error ? error.message : "Memory 保存失败");
    } finally {
      setMemorySaving(false);
    }
  };

  const hasMemoryChanges =
    memoryDrafts.memory !== memoryFiles.memory.content || memoryDrafts.user !== memoryFiles.user.content;

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
              className={`rail-nav-item ${activeNavId === item.id ? "active" : ""}`}
              onClick={() => setActiveNavId(item.id)}
              aria-current={activeNavId === item.id ? "page" : undefined}
            >
              <span>{item.label}</span>
              <small>{item.hint}</small>
            </button>
          ))}
        </nav>

        <section className="rail-section">
          <div className="rail-section-head">
            <span>会话</span>
            <button type="button" className="icon-action" aria-label="新建会话">
              +
            </button>
          </div>

          <div className="session-list">
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
                  }}
                  aria-current={activeSessionId === session.id ? "page" : undefined}
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
                    <div
                      className="session-menu"
                      role="menu"
                      onClick={(event) => event.stopPropagation()}
                    >
                      <button type="button" className="session-menu-item" role="menuitem" onClick={() => renameSession(session.id)}>
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
                        onClick={() => deleteSession(session.id)}
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
          <button type="button" className="settings-trigger">
            Settings &amp; Profile
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
        {activeNavId === "memory" ? (
          <section className="memory-workspace">
            <div className="memory-workspace-head">
              <div>
                <p className="memory-eyebrow">Memory Workspace</p>
                <h2>直接编辑 `MEMORY.md` 和 `USER.md`</h2>
              </div>
              <div className="memory-head-actions">
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
        ) : (
          <>
            <section className="conversation-pane">
              <div className="time-chip top">2026-03-18 19:42</div>

              <div className="user-row">
                <div className="user-bubble">
                  <p>请给我曼联最新新闻，并展示你在主 Agent 中的思考、工具调用、skill 调用、多 agent 协作和最终总结结论。</p>
                </div>
              </div>

              <div className="trace-column">
                {messageEntries.slice(0, 3).map((entry) => (
                  <div key={entry.id} className="trace-row compact">
                    <button
                      type="button"
                      className={`trace-bubble compact clickable ${openDetailId === entry.id ? "active" : ""}`}
                      onClick={() => toggleDetail(entry.id)}
                    >
                      {entry.text}
                    </button>
                  </div>
                ))}
              </div>

              <div className="time-chip middle">2026-03-18 19:43</div>

              <div className="trace-row">
                <button
                  type="button"
                  className={`trace-bubble wide clickable ${openDetailId === "agent-collab" ? "active" : ""}`}
                  onClick={() => toggleDetail("agent-collab")}
                >
                  <p className="trace-title">多 Agent 协同构建中</p>
                  <div className="trace-tags">
                    {messageEntries[3].tags?.map((tag) => (
                      <span key={tag.label} className={`status-tag ${tag.tone}`}>
                        {tag.label}
                      </span>
                    ))}
                  </div>
                </button>
              </div>

              <div className="time-chip bottom">2026-03-18 19:45</div>

              <div className="trace-row">
                <button
                  type="button"
                  className={`trace-bubble wide final clickable ${openDetailId === "final" ? "active" : ""}`}
                  onClick={() => toggleDetail("final")}
                >
                  <p className="trace-copy">{messageEntries[4].text}</p>
                </button>
              </div>
            </section>

            <footer className="composer-bar">
              <button type="button" className="attach-trigger" aria-label="添加附件">
                +
              </button>
              <div className="composer-main">
                <div className="composer-approval-strip">
                  <div className="composer-approval-head">
                    <span className="composer-approval-label">本轮审批策略</span>
                    <span className="composer-approval-hint">只作用于你接下来发送的这一条消息</span>
                  </div>

                  <div className="composer-approval-options" role="radiogroup" aria-label="选择本轮审批策略">
                    {(Object.entries(approvalModeMeta) as Array<[TurnApprovalMode, (typeof approvalModeMeta)[TurnApprovalMode]]>).map(
                      ([mode, meta]) => (
                        <button
                          key={mode}
                          type="button"
                          className={`approval-mode-chip ${turnApprovalMode === mode ? "active" : ""}`}
                          onClick={() => setTurnApprovalMode(mode)}
                          role="radio"
                          aria-checked={turnApprovalMode === mode}
                        >
                          <span>{meta.label}</span>
                        </button>
                      )
                    )}
                  </div>

                  <p className="composer-approval-copy">{activeApprovalMode.helper}</p>
                </div>

                <textarea
                  className="composer-input"
                  value={composerValue}
                  onChange={(event) => setComposerValue(event.target.value)}
                  onKeyDown={handleComposerKeyDown}
                  aria-label="message composer"
                  placeholder="输入你的任务，按 Enter 发送；Shift + Enter 换行"
                  rows={3}
                />

                {lastSubmittedTurn ? (
                  <div className="composer-turn-status" aria-live="polite">
                    <span className="composer-turn-status-label">
                      {approvalModeMeta[lastSubmittedTurn.approvalMode].status}
                    </span>
                    <span className="composer-turn-status-time">{lastSubmittedTurn.submittedAt}</span>
                    <p>{lastSubmittedTurn.content}</p>
                  </div>
                ) : null}
              </div>

              <div className="composer-side">
                <div className="context-usage">Context 63%</div>
                <button type="button" className="send-trigger" onClick={submitComposer} disabled={!composerValue.trim()}>
                  发送
                </button>
              </div>
            </footer>
          </>
        )}
      </main>

      <aside className={`right-drawer ${activeNavId === "chat" && selectedDetail ? "open" : ""}`}>
        <div
          className="drawer-resize-handle"
          onPointerDown={() => setDragging("right")}
          role="separator"
          aria-orientation="vertical"
          aria-label="调整右侧栏宽度"
        />

        {activeNavId === "chat" && selectedDetail ? (
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
              <ul className="drawer-list">
                {selectedDetail.inputs.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </section>

            <section className="drawer-card">
              <span className="drawer-label">引用与来源</span>
              <ul className="drawer-list">
                {selectedDetail.citations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </section>
          </div>
        ) : null}
      </aside>
    </div>
  );
}

export default App;
