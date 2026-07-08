---
name: report
description: Generate professional HTML analysis reports with a polished editorial design. Collects full source material from uploaded files, provided links, and web search. All claims are cited with source links. Generates sections incrementally to handle long reports.
when_to_use: Use when the user asks to create an analysis report, research report, or thematic analysis in HTML format, especially when referencing a template design or asking for "分析报告", "专题分析", "HTML报告", "report generation".
---

# Report Generator

## Goal

Generate a self-contained HTML analysis report with a polished editorial design. The report must be **fact-based**, **fully cited**, and **incrementally generated** to handle long-form content.

## Core Principles (MUST FOLLOW)

### 1. 真实性第一 — 严禁编造

- **禁止臆造数据、观点、现象、案例、引语。** 所有内容必须来自实际检索到的来源。
- **不确定的信息标注「待核实」或直接省略**，不要编造看似合理的内容。
- **数据必须标注来源**（年份、机构、链接），不能只写数字不写出处。
- **涉及数值计算时必须二次确认计算正确性。** 先区分来源原始数值与自行推导数值，再用独立步骤复算推导结果；必要时把公式、口径、单位换算、分母分子和中间值写入 `calculation_checks.md`。
- **关键计算必须分步校验。** 对增长率、占比、同比/环比、CAGR、均值、中位数、加总、差值、倍数、指数化等指标，至少检查：原始数据是否一致、单位是否统一、公式是否适用、四舍五入口径是否影响结论。
- **计算结果不得只凭直觉生成。** 如果无法复算或来源数据不足，标注「待核算」并避免把该结果作为核心结论。
- **引用标注使用上标编号** `[1]`，对应底部参考文献列表中的完整链接。
- **当多个来源说法不一致时**，列出不同观点并分别标注来源，不要自行取舍。

### 1.1 数值计算复核（MUST FOLLOW）

当报告包含任何自行计算、换算或汇总的数值时，必须执行以下复核流程：

1. **记录输入值**
   - 在 `research_notes.md` 或 `calculation_checks.md` 中列出用于计算的原始数值、单位、时间范围、来源编号和定位信息。
   - 不同来源的同名指标不可直接混用；若口径不同，先说明差异或放弃合并计算。

2. **分步计算**
   - 对复杂指标拆成可检查步骤，例如：先统一单位 → 计算分子/分母 → 得到未四舍五入结果 → 再按报告展示口径取整。
   - 对 CAGR、渗透率、利润率、市场份额、增速贡献、结构占比等容易出错的指标，必须保留公式和中间值。

3. **独立复算**
   - 用第二遍独立计算验证结果；可使用计算器、脚本、表格公式或手工分步复算。
   - 若两次计算不一致，回到原始数据检查单位、时间口径、负数/百分号、四舍五入和缺失值处理，不得直接选择较合理的结果。

4. **结论前检查**
   - 检查数值是否落在合理范围内，例如占比是否超过 100%、增长率方向是否与原始数值一致、总分项是否能大致相加。
   - 报告正文中展示的推导数值要能追溯到 `calculation_checks.md` 或对应证据包。

5. **披露口径**
   - 正文或脚注中说明必要的计算口径，例如“按公开披露数值测算”“按人民币口径换算”“由于四舍五入，合计可能存在尾差”。
   - 对关键结论依赖的计算，应在表格或注释中展示公式或关键中间值，避免只有最终数字。

### 2. 信息收集三通道

按以下优先级收集信息：

| 通道 | 工具 | 说明 |
|------|------|------|
| 用户上传文件 | `parse_attachment` | 最高优先级，用户提供的附件内容 |
| 用户提供的链接 | `fetch_url` | 用户明确给出的 URL，逐个抓取 |
| 自主搜索 | `google_search` → `fetch_url` | 用户未提供足够信息时主动搜索 |

### 附件全量读取要求（MUST FOLLOW）

生成报告时，只要用户上传了附件，就必须按下面流程拿到完整解析内容。`parse_attachment` 默认返回 `content_mode: "full"`，不能只依赖 `content_excerpt`。

1. **逐个附件调用 `parse_attachment`**
   - 优先使用当前回合附件元数据里的 `attachment_id`。
   - 如果没有明确 `attachment_id`，使用 `selector.order_index`、`selector.kind`、`selector.kind_index` 或 `selector.filename` 定位。
   - 多个附件必须逐个解析，不要只解析第一个附件。
   - 报告、分析、统计、完整总结类任务使用默认 `content_mode: "full"`；只有快速探查时才显式改用 `content_mode: "excerpt"`。

2. **读取解析产物路径，而不是只读 excerpt**
   - `parse_attachment` 成功后，解析返回 JSON。
   - 如果返回 `content` 且 `content_truncated=false`，可直接把该字段作为附件完整解析 Markdown。
   - 如果只返回 `content_excerpt`，或返回 `content_truncated=true`，必须继续读取解析产物路径。
   - 如果返回 `parsed_markdown_path`，用 `read_file` 或 `read_file_range` 读取该 Markdown 文件内容。
   - 如果返回 `parsed_chunks_path`，说明附件解析器生成了结构化 chunks；当 Markdown 过长或需要分段定位时，读取 chunks JSON，并按 chunk 顺序建立材料索引。
   - 如果返回 `parsed_structure_path`，用于表格、幻灯片、PDF 结构化分析时读取结构信息。
   - 如果返回 `parsed_html_path`，仅在需要保留原始 HTML/富文本结构时读取。

3. **建立附件材料索引**
   - 为每个附件记录：`attachment_id`、文件名、类型、原文件路径、`parsed_markdown_path`、`parsed_chunks_path`、摘要、读取状态。
   - 将完整 Markdown 或 chunk 摘要写入 `research_notes.md`，并保留可追溯路径。
   - 引用附件内容时，使用附件文件名和章节/页码/表名/slide 编号等定位信息；如果原附件无法提供页码，使用解析后的标题或 chunk 序号。

4. **失败处理**
   - 如果某个附件解析失败，必须在报告前置说明或交付说明中标注该附件未被纳入分析。
   - 不得基于解析失败或未读取完整内容的附件编造结论。

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

### 长上下文应对方案（MUST FOLLOW）

当附件或网页材料过长时，不要尝试把所有原文一次性放进模型上下文。采用“材料索引 + 分段证据包 + 分块写作”的方案：

1. **材料索引层**
   - 先把全部来源登记到 `research_notes.md`：来源编号、来源类型、路径/URL、标题、时间、可信度、可引用范围。
   - 对超长附件，优先读取 `parsed_chunks_path`，生成 `chunk_index.md`，记录每个 chunk 的主题、关键词、页码/章节线索和关键信息。
   - 对网页来源，保留 URL、抓取时间和核心摘录。

2. **证据包层**
   - 每个报告 section 写作前，单独创建一个 `evidence/0X_section.md`。
   - 只从材料索引中抽取该 section 需要的证据、数据、引用和冲突信息。
   - 每条证据保留来源编号和定位信息，避免写作阶段丢失出处。

3. **分块写作层**
   - 每次只生成一个 section 的 HTML 片段。
   - 生成前读取对应 `evidence/0X_section.md` 和必要的少量原文 chunk。
   - section 生成后立即写入 `sections/0X_sectionname.html`，不要把全部 section 都留在上下文里。

4. **最终组装层**
   - 组装时只读取模板、section HTML 片段、参考文献列表和必要元数据。
   - 不再重新读取所有原始材料，避免上下文再次膨胀。

5. **质量控制**
   - 每个 section 结尾前检查：是否所有事实都有来源、是否有来源但证据不足的断言、是否遗漏冲突观点。
   - 如材料超长导致无法覆盖全部内容，在报告方法说明中明确“已基于附件解析 chunks 和证据索引进行分段分析”。

## Workflow

### Phase 1: 信息收集 (Information Gathering)

1. **解析用户上传的文件**（如有）
   - 使用 `parse_attachment` 逐个解析附件，分析/报告类任务使用默认 `content_mode: "full"`
   - 解析后优先使用返回的完整 `content`；若截断，再读取 `parsed_markdown_path` 或 `parsed_chunks_path` 获取附件全量 Markdown
   - 对超长附件读取 `parsed_chunks_path`，建立 chunk 级材料索引
   - 提取关键数据、观点、引用，并记录附件文件名、章节/页码/表名/slide 或 chunk 定位

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
   - 若涉及自行计算、换算、汇总或指标推导，同步创建 `calculation_checks.md`，记录原始输入、公式、中间值、复算结果和口径说明
   - 对超长来源额外保存 `chunk_index.md` 和 `evidence/` 分 section 证据包

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
   - 只读取该 section 对应的 evidence 文件和必要原文 chunk
   - 若该 section 使用计算结果，先读取并核对对应 `calculation_checks.md` 条目；没有复核记录的关键计算不得写入正文
   - 使用模板组件（callout、table、metric-grid 等）
   - 每个事实性陈述标注引用 `[n]`
   - 写入 `sections/0X_sectionname.html`
3. 每个 section 生成后，简要向用户确认内容方向

### Phase 4: 组装输出 (Assembly)

1. 读取 HTML 模板
2. 替换头部占位符（`{{TITLE}}`, `{{SUBTITLE}}`, `{{META}}`）
3. 将所有 section 片段按顺序拼接
4. 生成参考文献列表（`footer .sources`）
5. 复查全文数值：确认所有计算值均有来源输入、公式或复核记录；尾差和口径限制已说明
6. 写入最终 HTML 文件
7. 向用户确认完成，提供文件路径

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
- **Do not publish unverified derived numbers; all calculated metrics must be double-checked**
- **Every factual claim must have a citation with a working link**
- **When in doubt, omit rather than invent**

## Tool Guidance

| Step | Tool | Purpose |
|------|------|---------|
| 信息收集 | `parse_attachment` | 解析用户上传的文件 |
| 附件全量读取 | `read_file` | 读取 `parsed_markdown_path`、`parsed_chunks_path`、`parsed_structure_path` |
| 信息收集 | `fetch_url` | 抓取用户提供的链接或搜索结果 |
| 信息收集 | `google_search` | 自主搜索补充信息 |
| 大纲确认 | `request_user_input` | 让用户确认报告大纲 |
| 读取模板 | `read_file` | 读取 `templates/report_template.html` |
| 分块生成 | `write_file` | 写入 `sections/0X_sectionname.html` |
| 组装输出 | `write_file` | 写入最终 HTML 报告 |
| 大文件读取 | `read_file_range` | 读取大型附件的部分内容 |
