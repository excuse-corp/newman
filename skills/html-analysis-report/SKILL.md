---
name: html-analysis-report
description: Generate professional HTML analysis reports with a polished editorial design. Collects info from uploaded files, provided links, and web search. All claims are cited with source links. Generates sections incrementally to handle long reports.
when_to_use: Use when the user asks to create an analysis report, research report, or thematic analysis in HTML format, especially when referencing a template design or asking for "分析报告", "专题分析", "HTML报告", "report generation".
---

# HTML Analysis Report Generator

## Goal

Generate a self-contained HTML analysis report with a polished editorial design. The report must be **fact-based**, **fully cited**, and **incrementally generated** to handle long-form content.

## Core Principles (MUST FOLLOW)

### 1. 真实性第一 — 严禁编造

- **禁止臆造数据、观点、现象、案例、引语。** 所有内容必须来自实际检索到的来源。
- **不确定的信息标注「待核实」或直接省略**，不要编造看似合理的内容。
- **数据必须标注来源**（年份、机构、链接），不能只写数字不写出处。
- **引用标注使用上标编号** `[1]`，对应底部参考文献列表中的完整链接。
- **当多个来源说法不一致时**，列出不同观点并分别标注来源，不要自行取舍。

### 2. 信息收集三通道

按以下优先级收集信息：

| 通道 | 工具 | 说明 |
|------|------|------|
| 用户上传文件 | `parse_attachment` | 最高优先级，用户提供的附件内容 |
| 用户提供的链接 | `fetch_url` | 用户明确给出的 URL，逐个抓取 |
| 自主搜索 | `google_search` → `fetch_url` | 用户未提供足够信息时主动搜索 |

**搜索策略：**
- 先根据报告主题确定 3-5 个核心搜索关键词
- 每个关键词搜索一轮，提取有价值的结果
- 对搜索结果中的高质量页面（官方发布、权威媒体、学术论文）进行 `fetch_url` 抓取
- 记录每条信息的来源 URL，用于后续引用标注

### 3. 分块生成机制

报告内容可能很长，**不要一次性生成全部 HTML**。采用以下分块策略：

```
阶段 1: 信息收集 → 收集所有素材，整理为结构化笔记
阶段 2: 大纲确认 → 生成报告大纲，用 request_user_input 让用户确认
阶段 3: 分块生成 → 逐个 section 生成内容，每块写入临时文件
阶段 4: 组装输出 → 读取模板 + 所有 section 临时文件 → 拼接为完整 HTML
```

**分块生成的具体做法：**

1. 在输出目录下创建 `sections/` 子目录
2. 每个 section 生成一个独立的 HTML 片段文件：`sections/01_intro.html`, `sections/02_analysis.html` 等
3. 每个片段只包含该 section 的 `<div class="section">...</div>` 内容
4. 最后用 Python 脚本或手动拼接：读取模板 → 替换 section 占位符 → 插入参考文献 → 输出最终 HTML

**为什么分块：**
- 避免单次生成超出上下文长度限制
- 每个 section 可以独立审核和修改
- 用户可以对某个 section 提出修改意见，只重生成该块

## Workflow

### Phase 1: 信息收集 (Information Gathering)

1. **解析用户上传的文件**（如有）
   - 使用 `parse_attachment` 读取附件内容
   - 提取关键数据、观点、引用

2. **抓取用户提供的链接**（如有）
   - 使用 `fetch_url` 逐个抓取
   - 提取页面核心内容

3. **自主搜索补充信息**
   - 使用 `google_search` 搜索核心关键词
   - 对高质量结果使用 `fetch_url` 抓取全文
   - 记录每条信息的来源 URL

4. **整理信息笔记**
   - 将收集到的信息整理为结构化笔记
   - 每条信息标注来源编号和 URL
   - 保存到临时文件 `research_notes.md`

### Phase 2: 大纲确认 (Outline Confirmation)

1. 基于收集的信息，生成报告大纲
2. 使用 `request_user_input` 让用户确认大纲
   - 报告标题、副标题
   - 各 section 标题和主要内容方向
   - 用户可调整顺序、增删 section

### Phase 3: 分块生成 (Section-by-Section Generation)

1. 读取 HTML 模板：`read_file` → `templates/report_template.html`
2. **逐个 section 生成内容：**
   - 根据大纲和收集的信息，生成该 section 的 HTML 片段
   - 使用模板组件（callout、table、metric-grid 等）
   - 每个事实性陈述标注引用 `[n]`
   - 写入 `sections/0X_sectionname.html`
3. 每个 section 生成后，简要向用户确认内容方向

### Phase 4: 组装输出 (Assembly)

1. 读取 HTML 模板
2. 替换头部占位符（`{{TITLE}}`, `{{SUBTITLE}}`, `{{META}}`）
3. 将所有 section 片段按顺序拼接
4. 生成参考文献列表（`footer .sources`）
5. 写入最终 HTML 文件
6. 向用户确认完成，提供文件路径

## Citation System

### Inline Citations

- 使用上标编号：`<sup><a href="#ref1">[1]</a></sup>`
- 每个事实性陈述后标注来源
- 同一来源多次引用使用同一编号

### Reference List (Footer)

```
<footer>
  <div class="sources">
    <h2>参考文献</h2>
    <ol>
      <li id="ref1">
        <span class="src-title">文章标题</span><br>
        <span class="src-meta">作者，来源，日期</span><br>
        <span class="src-url"><a href="https://...">原文链接</a></span>
      </li>
    </ol>
  </div>
</footer>
```

### Citation Rules

- 每条引用必须包含：标题、来源、可点击链接
- 链接必须是实际可访问的 URL，不能编造
- 如果来源无法获取链接，标注「来源不可达」
- 引用编号按出现顺序递增

## Template Components

The template provides these reusable HTML components:

| Component | Class | Use For |
|-----------|-------|---------|
| Header | `.report-header` | Report title, subtitle, metadata |
| Section | `.section` | Major content sections with h2 titles |
| Callout | `.callout` | Highlighted key points (add `.blue` for blue variant) |
| Blockquote | `blockquote` | Quotes with citations |
| Table | `.table-wrap` + `table` | Comparison tables, data tables |
| Metric Grid | `.metric-grid` + `.metric-card` | Key statistics display |
| Dimension Grid | `.dim-grid` + `.dim-card` | Multi-dimension breakdowns |
| Indicator Row | `.indicator-row` | Indicator lists with tags |
| References | `footer .sources` | Citation list with links |

## Design System

- **Colors**: Accent red `#b91c1c`, Accent blue `#1e40af`, Dark bg `#1a1a2e`, Light bg `#fafaf8`
- **Typography**: WorkSans + Noto Sans CJK SC + Microsoft YaHei
- **Max width**: 920px centered
- **Border radius**: 12px for sections, 16px for header
- **Shadows**: Subtle `0 1px 8px rgba(0,0,0,.04)`

## Constraints

- Generate a single self-contained HTML file (no external CSS/JS dependencies except fonts)
- Use inline styles within `<style>` tag
- Keep the HTML semantic and accessible
- **Do not fabricate any data, quotes, or claims**
- **Every factual claim must have a citation with a working link**
- **When in doubt, omit rather than invent**

## Tool Guidance

| Step | Tool | Purpose |
|------|------|---------|
| 信息收集 | `parse_attachment` | 解析用户上传的文件 |
| 信息收集 | `fetch_url` | 抓取用户提供的链接或搜索结果 |
| 信息收集 | `google_search` | 自主搜索补充信息 |
| 大纲确认 | `request_user_input` | 让用户确认报告大纲 |
| 读取模板 | `read_file` | 读取 `templates/report_template.html` |
| 分块生成 | `write_file` | 写入 `sections/0X_sectionname.html` |
| 组装输出 | `write_file` | 写入最终 HTML 报告 |
| 大文件读取 | `read_file_range` | 读取大型附件的部分内容 |
