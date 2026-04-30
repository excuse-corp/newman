---
name: arch-diagram_skill
description: 'name: arch-diagram'
when_to_use: Use when the user asks for work related to arch-diagram_SKILL.
---

# arch-diagram_skill

---
name: arch-diagram
description: Generate interactive architecture diagrams as editable HTML pages from text descriptions. Use this skill whenever the user wants to: draw an architecture diagram, create a system design diagram, visualize software/infrastructure layers, show module/service/component relationships, produce a technical diagram for documentation or presentations. Triggers include: "画架构图", "架构图", "系统架构", "architecture diagram", "system design diagram", "draw architecture", "create architecture diagram", "module diagram", "layer diagram", or any request to visualize technical system structure. Always use this skill — never try to draw architecture diagrams inline in chat.
---

# Architecture Diagram Skill

Generate beautiful, layered architecture diagrams as interactive HTML pages. All text is inline-editable and the diagram can be exported as a PNG image.

---

## Workflow

### Step 1 — Understand the content

Read the user's description (free text, bullet list, PRD excerpt, uploaded doc, or any format) and identify all the **components** mentioned: systems, modules, services, functions, databases, queues, layers, subsystems, etc.

No predefined layer taxonomy exists. You must infer the right structure from the content itself.

### Step 2 — Plan the architecture (think out loud briefly)

Before writing any HTML, produce a short planning block in your reply:

```
【架构规划】
层数: N 层
层 1 — <你起的名字>: <内容描述 + 布局方式>
层 2 — <你起的名字>: <内容描述 + 布局方式>
...
颜色分配: 层1→blue, 层2→orange, ...（从可用色顺序选取）
特殊节点: 哪些用圆柱体（存储/缓存/队列），哪些用普通 box
```

**Layer planning principles:**
- Let the content drive the structure. A simple frontend app may have 2 layers; a microservices platform might have 6. Don't force any preset template.
- Each layer should represent a **meaningful semantic grouping** (e.g. "用户接入层", "核心业务层", "数据持久层") — name layers from the actual domain, not generic labels.
- If the user names layers explicitly, use those names; otherwise infer sensible names from the components.
- Items that are truly parallel/sibling go in the same layer. Items that depend on the layer above go in a lower layer.
- Databases, caches, queues, and message brokers always use cylinder shape.

**Color assignment** — assign in order top-to-bottom, cycling if more than 6 layers. Colors carry no semantic meaning, they are purely for visual distinction:

`blue → orange → purple → green → teal → rose → (repeat)`

### Step 3 — Generate the HTML file

Produce a single self-contained `.html` file and save it to `/mnt/user-data/outputs/<diagram-name>.html`.

---

## HTML Shell (copy verbatim, fill in `#diagram` content)

```html
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>Architecture Diagram</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: #f8fafc; padding: 32px; min-height: 100vh;
  }
  .toolbar {
    display: flex; align-items: center; gap: 12px;
    margin-bottom: 24px; flex-wrap: wrap;
  }
  .toolbar h1 {
    font-size: 18px; font-weight: 600; color: #1e293b;
    flex: 1; min-width: 200px;
  }
  .toolbar h1[contenteditable]:focus { outline: 2px dashed #94a3b8; border-radius: 4px; }
  .btn {
    padding: 8px 18px; border-radius: 8px; border: none;
    font-size: 14px; font-weight: 500; cursor: pointer; transition: opacity .15s;
  }
  .btn:hover { opacity: .85; }
  .btn-export { background: #3b82f6; color: #fff; }
  .btn-reset  { background: #e2e8f0; color: #475569; }
  .btn-dl  { background: #0f172a; color: #fff; }
  .btn-png { background: #3b82f6; color: #fff; }

  #diagram {
    display: flex; flex-direction: column; gap: 20px;
    max-width: 1200px; margin: 0 auto;
    background: #fff; border-radius: 16px;
    padding: 28px; box-shadow: 0 1px 8px rgba(0,0,0,.06);
  }

  .layer { border-radius: 12px; padding: 16px 18px; border: 2px solid; }
  .layer-title {
    font-size: 15px; font-weight: 600; margin-bottom: 12px;
    color: #1e293b; display: inline-block;
  }
  .layer-title[contenteditable]:focus { outline: 2px dashed #94a3b8; border-radius: 4px; }

  .groups-row { display: flex; gap: 14px; flex-wrap: wrap; }
  .group {
    flex: 1 1 220px; border-radius: 10px; border: 2px solid;
    padding: 12px 14px; display: flex; flex-direction: column; gap: 8px;
  }
  .group-title { font-size: 13px; font-weight: 600; color: #374151; margin-bottom: 4px; }
  .group-title[contenteditable]:focus { outline: 2px dashed #94a3b8; border-radius: 4px; }

  .items-row { display: flex; gap: 8px; flex-wrap: wrap; }
  .plugin-row { display: flex; gap: 10px; flex-wrap: wrap; }

  .item {
    flex: 1 1 80px; background: #fff; border: 1.5px solid #e2e8f0;
    border-radius: 7px; padding: 7px 12px;
    font-size: 13px; color: #374151; text-align: center; min-width: 70px;
  }
  .item[contenteditable]:focus { outline: 2px dashed #94a3b8; }

  .cylinder-wrap {
    display: flex; flex-direction: column; align-items: center; gap: 6px;
    flex: 1 1 80px; padding: 8px 0;
  }
  .cylinder { width: 72px; height: 56px; }
  .cylinder svg { width: 100%; height: 100%; }
  .cylinder-label { font-size: 13px; color: #374151; text-align: center; font-weight: 500; }
  .cylinder-label[contenteditable]:focus { outline: 2px dashed #94a3b8; }

  /* Colour palette — assigned by layer order, no fixed semantic meaning */
  .blue   { background:#dbeafe; border-color:#93c5fd; }
  .orange { background:#ffedd5; border-color:#fdba74; }
  .purple { background:#f3e8ff; border-color:#d8b4fe; }
  .green  { background:#dcfce7; border-color:#86efac; }
  .teal   { background:#ccfbf1; border-color:#5eead4; }
  .rose   { background:#ffe4e6; border-color:#fda4af; }

  .blue   .group { border-color:#93c5fd; }
  .orange .group { border-color:#fdba74; }
  .purple .group { border-color:#d8b4fe; }
  .green  .group { border-color:#86efac; }
  .teal   .group { border-color:#5eead4; }
  .rose   .group { border-color:#fda4af; }
</style>
</head>
<body>

<div class="toolbar">
  <h1 contenteditable="true">系统架构图</h1>
  <button class="btn btn-reset" onclick="resetEdits()">↺ 重置</button>
  <button class="btn btn-dl"   onclick="saveHTML()">⬇ 下载 HTML</button>
  <button class="btn btn-png"  id="pngBtn" onclick="exportPNG()">📷 导出 PNG</button>
</div>
<div id="tip" style="max-width:1200px;margin:0 auto 14px;padding:9px 14px;background:#fffbeb;border:1.5px solid #fcd34d;border-radius:8px;font-size:12.5px;color:#92400e;display:none">
  💡 在 claude.ai 预览中无法直接导出 PNG。请点击「下载 HTML」，在浏览器本地打开后再点「导出 PNG」即可。
</div>

<div id="diagram">
  <!-- YOUR GENERATED LAYERS HERE -->
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
<script>
const _origHTML = document.getElementById('diagram').innerHTML;

function isSandboxed() {
  try { return window.self !== window.top; } catch(e) { return true; }
}

window.addEventListener('load', () => {
  if (isSandboxed()) {
    document.getElementById('tip').style.display = 'block';
  }
});

function saveHTML() {
  const tip = document.getElementById('tip');
  const prev = tip.style.display;
  tip.style.display = 'none';
  const html = '<!DOCTYPE html>\n' + document.documentElement.outerHTML;
  tip.style.display = prev;
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'architecture-diagram.html';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

async function exportPNG() {
  if (isSandboxed()) {
    alert('在 claude.ai 预览中无法导出 PNG。\n请先点击「下载 HTML」，在浏览器本地打开后再导出。');
    return;
  }
  if (typeof html2canvas === 'undefined') {
    alert('导出库加载失败，请检查网络后刷新重试。');
    return;
  }
  const btn = document.getElementById('pngBtn');
  btn.textContent = '导出中…'; btn.disabled = true;
  try {
    const canvas = await html2canvas(document.getElementById('diagram'), {
      scale: 2, backgroundColor: '#ffffff', useCORS: true, logging: false
    });
    const a = document.createElement('a');
    a.href = canvas.toDataURL('image/png');
    a.download = 'architecture-diagram.png';
    a.click();
  } catch(e) {
    alert('导出失败：' + e.message);
  }
  btn.textContent = '📷 导出 PNG'; btn.disabled = false;
}

function resetEdits() {
  if (confirm('重置所有编辑内容？')) {
    document.getElementById('diagram').innerHTML = _origHTML;
  }
}
</script>
</body>
</html>
```

---

## Layer Primitives

Mix and match these building blocks inside `#diagram`:

### A — Full-width layer, flat item list (no sub-groups)
```html
<div class="layer blue">
  <div class="layer-title" contenteditable="true">层名称</div>
  <div class="plugin-row">
    <div class="item" contenteditable="true">组件 A</div>
    <div class="item" contenteditable="true">组件 B</div>
  </div>
</div>
```

### B — Full-width layer with named sub-groups side by side
```html
<div class="layer orange">
  <div class="groups-row">
    <div class="group">
      <div class="group-title" contenteditable="true">子系统 1</div>
      <div class="items-row">
        <div class="item" contenteditable="true">功能 1</div>
        <div class="item" contenteditable="true">功能 2</div>
      </div>
      <div class="items-row">
        <div class="item" contenteditable="true">功能 3</div>
      </div>
    </div>
    <div class="group">
      <div class="group-title" contenteditable="true">子系统 2</div>
      <div class="items-row">
        <div class="item" contenteditable="true">功能 1</div>
      </div>
    </div>
  </div>
</div>
```

### C — Side-by-side panels in same row (different flex ratios)
```html
<div style="display:flex; gap:20px;">
  <div class="layer green" style="flex:2;">
    <div class="layer-title" contenteditable="true">主服务</div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
      <div class="item" contenteditable="true">服务 1</div>
      <div class="item" contenteditable="true">服务 2</div>
      <div class="item" contenteditable="true">服务 3</div>
      <div class="item" contenteditable="true">服务 4</div>
    </div>
  </div>
  <div class="layer green" style="flex:1;">
    <div class="layer-title" contenteditable="true">存储</div>
    <div style="display:flex; justify-content:space-around; padding-top:8px;">
      <!-- cylinder nodes -->
    </div>
  </div>
</div>
```

### D — Database / cache / queue cylinder node
```html
<div class="cylinder-wrap">
  <div class="cylinder">
    <svg viewBox="0 0 72 56" xmlns="http://www.w3.org/2000/svg">
      <ellipse cx="36" cy="10" rx="32" ry="9" fill="#bbf7d0" stroke="#4ade80" stroke-width="1.5"/>
      <rect x="4" y="10" width="64" height="30" fill="#bbf7d0" stroke="none"/>
      <line x1="4" y1="10" x2="4" y2="40" stroke="#4ade80" stroke-width="1.5"/>
      <line x1="68" y1="10" x2="68" y2="40" stroke="#4ade80" stroke-width="1.5"/>
      <ellipse cx="36" cy="40" rx="32" ry="9" fill="#bbf7d0" stroke="#4ade80" stroke-width="1.5"/>
    </svg>
  </div>
  <div class="cylinder-label" contenteditable="true">MySQL</div>
</div>
```
> Match the cylinder `fill`/`stroke` colours to the layer they live in.

### E — Header-only band (no child items)
```html
<div class="layer blue">
  <div class="layer-title" contenteditable="true">顶层标题</div>
</div>
```

---

## Output Rules

1. Always show the `【架构规划】` planning section first in the chat reply, then generate the HTML file.
2. Save the HTML to `/mnt/user-data/outputs/<diagram-name>.html` using `create_file`.
3. Every visible text node must have `contenteditable="true"`.
4. Use colour class names (`blue`, `orange`, `purple`, `green`, `teal`, `rose`) on `.layer` — never inline background colours.
5. Use exactly as many layers as the content semantically needs — no padding layers.
6. Items in the same layer must be semantically parallel. Different abstraction levels → different layers.
7. Minimum font size 12px; diagram fits within 1200px width.

---

## Worked Example

**Input:** "我们的系统有一个 React 前端，通过 API Gateway 转发请求。后端有三个微服务：用户服务、订单服务、支付服务，各自有独立数据库。公共基础设施包括 Redis 缓存、Kafka 消息队列、Elasticsearch。"

**Planning output:**
```
【架构规划】
层数: 3 层
层 1 — 前端接入层 (blue): React 前端 + API Gateway，flat 排列
层 2 — 微服务层 (orange): 3 个并排 group，每个含服务名 + 各自 DB 圆柱
层 3 — 公共基础设施层 (purple): Redis / Kafka / Elasticsearch 圆柱体并排
颜色分配: blue → orange → purple
特殊节点: 用户DB、订单DB、支付DB、Redis、Kafka、Elasticsearch 均用圆柱体
```

## Goal

Use this skill to apply the uploaded workflow and bundled resources.

## Constraints

- Keep changes scoped to the user's request.
- Do not load large bundled files unless they are directly relevant.
