const navigationItems = [
  { label: "Chat", hint: "对话", active: true },
  { label: "Memory", hint: "记忆", active: false },
  { label: "Skills", hint: "技能", active: false },
  { label: "Files", hint: "文件", active: false },
];

const sessions = [
  { title: "Chat2work 项目架构评审", active: true },
  { title: "供应商合同抽取与比对", active: false },
  { title: "经营周报问答", active: false },
];

const processCards = [
  "thinking...",
  "bing_search 工具调用中",
  "news_digest skill 调用中",
];

const agentBadges = [
  { label: "Planner", state: "完成", tone: "blue" },
  { label: "Retriever", state: "进行中", tone: "green" },
  { label: "Writer", state: "等待输入", tone: "orange" },
];

function App() {
  return (
    <div className="mock-page">
      <aside className="sidebar-shell">
        <div className="brand-row">
          <div className="brand-mark" />
          <h1>Newman</h1>
        </div>

        <nav className="primary-nav" aria-label="Primary">
          {navigationItems.map((item) => (
            <button key={item.label} type="button" className={`nav-item ${item.active ? "active" : ""}`}>
              <span>{item.label}</span>
              <small>{item.hint}</small>
            </button>
          ))}
        </nav>

        <section className="session-shell">
          <div className="session-header">
            <span>会话</span>
            <button type="button" className="session-plus" aria-label="new session">
              +
            </button>
          </div>

          <div className="session-list">
            {sessions.map((session) => (
              <button key={session.title} type="button" className={`session-item ${session.active ? "active" : ""}`}>
                {session.title}
              </button>
            ))}
          </div>
        </section>

        <button type="button" className="settings-button">
          Settings &amp; Profile
        </button>
      </aside>

      <div className="rail-divider" aria-hidden="true">
        <div className="rail-divider-line" />
        <div className="rail-divider-thumb" />
      </div>

      <main className="workspace-shell">
        <section className="workspace-stage">
          <div className="time-pill time-pill-top">2026-03-18 19:42</div>
          <div className="time-pill time-pill-middle">2026-03-18 19:43</div>
          <div className="time-pill time-pill-bottom">2026-03-18 19:45</div>

          <div className="workspace-body">
            <div className="trace-column">
              {processCards.map((card) => (
                <article key={card} className="trace-card">
                  {card}
                </article>
              ))}

              <article className="agent-card">
                <h2>多 Agent 协同构建中</h2>
                <div className="agent-badges">
                  {agentBadges.map((badge) => (
                    <span key={`${badge.label}-${badge.state}`} className={`agent-badge ${badge.tone}`}>
                      <strong>{badge.label}</strong> {badge.state}
                    </span>
                  ))}
                </div>
              </article>
            </div>

            <div className="conversation-column">
              <article className="message-bubble user-bubble">
                请给我曼联最新新闻，并展示你在主 Agent 中的思考、工具调用、skill 调用、多 agent 协作和最终总结论。
              </article>

              <div className="conversation-spacer" />

              <article className="message-bubble assistant-bubble">
                曼联最新动态已汇总：包含比赛结果、伤病更新与转会传闻。核心结论在此，详细证据与原始内容请查看右侧 Drawer。
              </article>
            </div>
          </div>
        </section>

        <section className="composer-shell">
          <button type="button" className="composer-plus" aria-label="add">
            +
          </button>
          <div className="composer-input">输入你的任务，按 Enter 发送；Shift + Enter 换行</div>
          <div className="composer-context">Context 63%</div>
          <button type="button" className="composer-send">
            发送
          </button>
        </section>
      </main>
    </div>
  );
}

export default App;
