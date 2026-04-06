# M12 Frontend — Web 前端

> Newman 模块 PRD · Phase 4 · 预估 15 工作日

---

## 一、模块目标

实现基于 Next.js 的完整前端体验，涵盖对话、工具可视化、审批、RAG 引用、插件管理。

---

## 二、功能范围

### ✅ 包含

- 会话列表与聊天主界面
- SSE 事件消费与状态同步
- 工具调用时间线可视化
- Level 2 审批弹窗
- RAG 引用展示（Slide-out Drawer）
- Session 恢复与手动压缩
- 插件管理中心
- 前端状态管理（对话流 / 工具 / 审批 / 插件 / 会话元信息）

### ❌ 不包含

- 移动端适配
- 复杂图表组件

---

## 三、前置依赖

- M06 API & SSE（接口与事件消费）
- M07 RAG（引用数据）
- M09 Plugin（插件状态）

---

## 四、文件结构

```text
frontend/
  app/
    layout.tsx
    page.tsx
    sessions/[id]/page.tsx
    plugins/page.tsx
  components/
    chat/
      ChatPanel.tsx         # 聊天主面板
      MessageBubble.tsx     # 消息气泡
      StreamingText.tsx     # 流式文本渲染
    tools/
      ToolTimeline.tsx      # 工具调用时间线
      ToolStatusBadge.tsx   # 工具状态徽章
    approval/
      ApprovalModal.tsx     # 审批弹窗
    rag/
      CitationDrawer.tsx    # 引用侧滑抽屉
      CitationCard.tsx      # 引用卡片
    plugins/
      PluginList.tsx        # 插件列表
      PluginToggle.tsx      # 插件启停开关
    sessions/
      SessionList.tsx       # 会话列表
  stores/
    sessionStore.ts         # 会话状态
    chatStore.ts            # 对话流状态
    toolStore.ts            # 工具状态
    approvalStore.ts        # 审批状态
    pluginStore.ts          # 插件状态
  features/
    sse/
      useSSE.ts             # SSE 连接与事件分发 Hook
    compression/
      useCompression.ts     # 手动压缩 Hook
```

---

## 五、核心设计

### 页面布局

```text
┌──────────────────────────────────────────┐
│  Header (Newman 标题 + 设置)              │
├──────────┬───────────────────────────────┤
│          │                               │
│  Session │         Chat Panel            │
│  List    │  - 消息流                      │
│          │  - 工具调用时间线               │
│          │  - 审批弹窗                    │
│          │                               │
│          │              ┌────────────────┤
│          │              │ Citation       │
│          │              │ Drawer         │
│          │              │ (slide-out)    │
├──────────┴──────────────┴────────────────┤
│  Input Bar (消息输入 + 文件上传)           │
└──────────────────────────────────────────┘
```

### 可视化重点

| 状态 | 展示方式 |
|------|----------|
| 工具执行中 | 时间线条目 + 旋转图标 + 耗时计时 |
| 工具审批中 | 高亮弹窗 + 倒计时 + approve/reject 按钮 |
| 错误恢复中 | 错误卡片 + 风险级别标识 + 恢复进度 |
| 已压缩 checkpoint | 折叠摘要卡片 + 展开查看详情 |

### SSE 事件消费

```typescript
// useSSE Hook 核心逻辑
const eventSource = new EventSource(`/api/sessions/${id}/messages`);
eventSource.onmessage = (event) => {
  const { event: type, data, ts } = JSON.parse(event.data);
  switch (type) {
    case 'assistant_delta': chatStore.appendDelta(data); break;
    case 'tool_call_started': toolStore.addCall(data); break;
    case 'tool_approval_request': approvalStore.show(data); break;
    // ...
  }
};
```

---

## 六、验收标准

1. 对话流式输出体验流畅（无明显卡顿）
2. 工具执行中 / 审批中 / 错误恢复中状态清晰可见
3. RAG 引用点击可展开源文档片段
4. 插件可启停且状态实时同步
5. 会话恢复后上下文连贯
6. 审批弹窗超时后自动关闭并提示

---

## 七、技术备注

- 使用 Zustand 进行状态管理
- 使用 Tailwind CSS 进行样式开发
- SSE 重连策略：断连后指数退避重连（1s, 2s, 4s, 最大 30s）
- Markdown 渲染使用 react-markdown + rehype-highlight
