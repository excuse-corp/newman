import { useEffect, useMemo, useState } from "react";
import "./usage-demo.css";

type RangeKey = "today" | "7d" | "30d";

type UsageSummaryResponse = {
  available: boolean;
  error: string | null;
  range: {
    days: number;
    timezone: string;
    start_at: string;
    end_at: string;
    start_date: string;
    end_date: string;
  };
  filters: {
    model: string | null;
    include_estimated: boolean;
  };
  available_models: string[];
  totals: {
    request_count: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    usage_missing_count: number;
    estimated_request_count: number;
    estimated_input_tokens: number;
    estimated_output_tokens: number;
    estimated_total_tokens: number;
  };
  by_day: Array<{
    date: string;
    request_count: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    estimated_request_count: number;
    estimated_input_tokens: number;
    estimated_output_tokens: number;
    estimated_total_tokens: number;
  }>;
  by_model: Array<{
    provider_type: string;
    model: string;
    request_count: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    estimated_request_count: number;
    estimated_input_tokens: number;
    estimated_output_tokens: number;
    estimated_total_tokens: number;
  }>;
  by_request_kind: Array<{
    request_kind: string;
    request_count: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    estimated_request_count: number;
    estimated_input_tokens: number;
    estimated_output_tokens: number;
    estimated_total_tokens: number;
  }>;
  by_session: Array<{
    session_id: string | null;
    session_title: string | null;
    request_count: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    estimated_request_count: number;
    estimated_input_tokens: number;
    estimated_output_tokens: number;
    estimated_total_tokens: number;
  }>;
  recent_records: Array<{
    request_id: string;
    session_id: string | null;
    session_title: string | null;
    attributed_session_id: string | null;
    attributed_session_title: string | null;
    turn_id: string | null;
    request_kind: string;
    provider_type: string;
    model: string;
    usage_available: boolean;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    estimated_total_tokens: number;
    finish_reason: string | null;
    created_at: string;
    metadata: Record<string, unknown>;
  }>;
};

type UsageDayBucket = {
  date: string;
  request_count: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
};

const RANGE_DAYS: Record<RangeKey, number> = {
  today: 1,
  "7d": 7,
  "30d": 30,
};

const REQUEST_KIND_LABELS: Record<string, string> = {
  session_turn: "主对话",
  session_turn_non_stream_fallback: "主对话兜底",
  subagent_turn: "子代理",
  context_compaction: "上下文压缩",
  manual_context_compaction: "手动压缩",
  memory_extraction: "记忆抽取",
  evolution_analysis: "自进化分析",
  evolution_skill_update: "Skill 自进化",
  multimodal_analysis: "多模态解析",
  skill_upload_optimization: "Skill 上传优化",
  rag_rerank: "RAG 重排",
  commentary_fallback: "工具前说明",
  completion_judge: "收尾判定",
  tool_limit_finalize: "工具上限收尾",
  fatal_tool_finalize: "故障收尾",
};

const REQUEST_KIND_DESCRIPTIONS: Record<string, string> = {
  session_turn: "用户消息触发的主模型调用，包含普通回复和工具调用前后的模型响应。",
  session_turn_non_stream_fallback: "主对话流式响应失败后，系统改用非流式方式重试。",
  subagent_turn: "多代理模式下子代理自己的模型调用成本，dashboard 会回卷到父任务会话。",
  context_compaction: "会话上下文接近上限时，后台生成 checkpoint 摘要来压缩历史。",
  manual_context_compaction: "用户手动触发的会话 checkpoint 摘要生成。",
  memory_extraction: "后台从会话里抽取稳定用户记忆，合并到 USER.md。",
  evolution_analysis: "自进化第一步，分析最近会话并判断是否需要更新 MEMORY.md 或 Skill。",
  evolution_skill_update: "自进化第二步，在确定要更新 Skill 后生成具体文件修改。",
  multimodal_analysis: "上传图片后，模型做视觉理解、OCR 和附件摘要。",
  skill_upload_optimization: "上传 Skill 时，模型把材料整理成 Newman 兼容的 SKILL.md。",
  rag_rerank: "检索到知识候选后，模型重新排序或筛选最相关内容。",
  commentary_fallback: "模型准备调用工具但缺少可见说明时，补生成一句工具前说明。",
  completion_judge: "主模型在准备结束本轮前，再做一次是否真的可以收尾的判断。",
  tool_limit_finalize: "达到工具调用上限时，模型生成本轮收尾回复。",
  fatal_tool_finalize: "工具连续失败或不可恢复时，模型生成错误说明和收尾回复。",
};

const PROVIDER_TYPE_LABELS: Record<string, string> = {
  openai_compatible: "OpenAI 兼容",
  anthropic_compatible: "Anthropic 兼容",
  mock: "模拟",
};

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    credentials: "include",
    ...init,
  });
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
      const detail =
        "detail" in payload
          ? payload.detail
          : "message" in payload
            ? payload.message
            : null;
      if (typeof detail === "string" && detail.trim()) {
        message = detail;
      }
    }
    throw new Error(message);
  }

  return (payload ?? {}) as T;
}

function addDays(dateKey: string, delta: number) {
  const [year, month, day] = dateKey.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day + delta));
  return date.toISOString().slice(0, 10);
}

function formatTokens(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function trimUnitFraction(value: string) {
  return value.replace(/\.0+$|(\.\d*[1-9])0+$/, "$1");
}

function compactTokens(value: number) {
  const absoluteValue = Math.abs(value);
  if (absoluteValue >= 100_000_000) {
    return `${trimUnitFraction((value / 100_000_000).toFixed(2))} 亿`;
  }
  if (absoluteValue >= 10_000) {
    const fractionDigits = absoluteValue >= 1_000_000 ? 1 : 2;
    return `${trimUnitFraction((value / 10_000).toFixed(fractionDigits))} 万`;
  }
  return formatTokens(value);
}

function formatTime(value: string) {
  return new Date(value).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function dayLabel(dateKey: string) {
  const [, month, day] = dateKey.split("-");
  return `${Number(month)}/${Number(day)}`;
}

function requestKindLabel(kind: string) {
  return REQUEST_KIND_LABELS[kind] ?? kind;
}

function requestKindDescription(kind: string) {
  return REQUEST_KIND_DESCRIPTIONS[kind] ?? "未配置说明的模型请求类型，通常来自新增后台流程或插件扩展。";
}

function providerTypeLabel(providerType: string) {
  return PROVIDER_TYPE_LABELS[providerType] ?? providerType;
}

function isEvolutionRequestKind(kind: string) {
  return kind.startsWith("evolution_");
}

function buildDaySeries(summary: UsageSummaryResponse | null): UsageDayBucket[] {
  if (!summary) {
    return [];
  }
  const buckets = new Map(summary.by_day.map((item) => [item.date, item]));
  const totalDays = summary.range.days;
  return Array.from({ length: totalDays }, (_, index) => {
    const date = addDays(summary.range.start_date, index);
    return (
      buckets.get(date) ?? {
        date,
        request_count: 0,
        input_tokens: 0,
        output_tokens: 0,
        total_tokens: 0,
      }
    );
  });
}

export default function UsageDashboard({
  apiBase,
  embedded = false,
}: {
  apiBase: string;
  embedded?: boolean;
}) {
  const [activeRange, setActiveRange] = useState<RangeKey>("7d");
  const [modelFilter, setModelFilter] = useState("all");
  const [includeEstimated, setIncludeEstimated] = useState(true);
  const [summary, setSummary] = useState<UsageSummaryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadSeed, setReloadSeed] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({
      days: String(RANGE_DAYS[activeRange]),
      tz: "Asia/Shanghai",
      include_estimated: String(includeEstimated),
    });
    if (modelFilter !== "all") {
      params.set("model", modelFilter);
    }

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const next = await fetchJson<UsageSummaryResponse>(`${apiBase}/api/usage/summary?${params.toString()}`, {
          signal: controller.signal,
        });
        if (controller.signal.aborted) {
          return;
        }
        setSummary(next);
        if (next.available_models.length > 0 && modelFilter !== "all" && !next.available_models.includes(modelFilter)) {
          setModelFilter("all");
        }
        if (!next.available && next.error) {
          setError(next.error);
        }
      } catch (nextError) {
        if (controller.signal.aborted) {
          return;
        }
        setError(nextError instanceof Error ? nextError.message : "Token 消耗加载失败");
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    }

    void load();
    return () => controller.abort();
  }, [activeRange, apiBase, includeEstimated, modelFilter, reloadSeed]);

  const byDay = useMemo(() => buildDaySeries(summary), [summary]);
  const maxDayTokens = Math.max(1, ...byDay.map((bucket) => bucket.total_tokens));
  const maxModelTokens = Math.max(1, ...(summary?.by_model.map((bucket) => bucket.total_tokens) ?? [0]));
  const maxKindTokens = Math.max(1, ...(summary?.by_request_kind.map((bucket) => bucket.total_tokens) ?? [0]));
  const totals = summary?.totals ?? {
    request_count: 0,
    input_tokens: 0,
    output_tokens: 0,
    total_tokens: 0,
    usage_missing_count: 0,
    estimated_request_count: 0,
    estimated_input_tokens: 0,
    estimated_output_tokens: 0,
    estimated_total_tokens: 0,
  };
  const resolvedIncludeEstimated = summary?.filters.include_estimated ?? includeEstimated;
  const actualRequestCount = Math.max(0, totals.request_count - totals.estimated_request_count);
  const actualInputTokens = Math.max(0, totals.input_tokens - totals.estimated_input_tokens);
  const actualOutputTokens = Math.max(0, totals.output_tokens - totals.estimated_output_tokens);
  const unresolvedMissingCount = Math.max(0, totals.usage_missing_count - totals.estimated_request_count);
  const inputRatio = totals.total_tokens > 0 ? Math.round((totals.input_tokens / totals.total_tokens) * 100) : 0;
  const outputRatio = totals.total_tokens > 0 ? 100 - inputRatio : 0;
  const evolutionTotals = (summary?.by_request_kind ?? [])
    .filter((bucket) => isEvolutionRequestKind(bucket.request_kind))
    .reduce(
      (current, bucket) => ({
        request_count: current.request_count + bucket.request_count,
        input_tokens: current.input_tokens + bucket.input_tokens,
        output_tokens: current.output_tokens + bucket.output_tokens,
        total_tokens: current.total_tokens + bucket.total_tokens,
      }),
      {
        request_count: 0,
        input_tokens: 0,
        output_tokens: 0,
        total_tokens: 0,
      },
    );
  const topModel = summary?.by_model[0] ?? null;
  const topSession = summary?.by_session[0] ?? null;
  const rangeLabel = summary ? `${summary.range.start_date} 至 ${summary.range.end_date}` : "--";
  const rootClassName = embedded ? "usage-demo-shell embedded" : "usage-demo-shell";
  const subtitle = resolvedIncludeEstimated
    ? "真实 usage + 对缺失 usage 的输入侧估算补齐"
    : "仅统计模型返回的真实 usage";

  return (
    <section className={rootClassName}>
      <header className="usage-demo-header">
        <div>
          <h1>消耗监控</h1>
          <p className="usage-demo-subtitle">
            {subtitle} · {summary?.range.timezone ?? "Asia/Shanghai"} · {rangeLabel}
          </p>
        </div>
        <div className="usage-demo-actions" aria-label="筛选条件">
          <div className="usage-segmented" aria-label="时间范围">
            {[
              ["today", "今天"],
              ["7d", "近 7 天"],
              ["30d", "近 30 天"],
            ].map(([key, label]) => (
              <button
                key={key}
                type="button"
                className={activeRange === key ? "active" : ""}
                onClick={() => setActiveRange(key as RangeKey)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="usage-segmented mode-toggle" aria-label="统计口径">
            {[
              [true, "含估算"],
              [false, "仅真实"],
            ].map(([value, label]) => (
              <button
                key={String(value)}
                type="button"
                className={includeEstimated === value ? "active" : ""}
                onClick={() => setIncludeEstimated(Boolean(value))}
              >
                {label}
              </button>
            ))}
          </div>
          <label className="usage-select-label">
            <span>模型</span>
            <select value={modelFilter} onChange={(event) => setModelFilter(event.target.value)}>
              <option value="all">全部模型</option>
              {(summary?.available_models ?? []).map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="usage-export-button" onClick={() => setReloadSeed((value) => value + 1)}>
            {loading ? "刷新中..." : "刷新"}
          </button>
        </div>
      </header>

      {error ? <div className="usage-status-banner error">{error}</div> : null}
      {!error && summary && !summary.available ? <div className="usage-status-banner warning">当前无法读取消耗数据。</div> : null}

      <section className="usage-kpi-grid" aria-label="总体消耗">
        <article className="usage-kpi-card primary">
          <span className="usage-kpi-label">总消耗</span>
          <strong
            title={
              resolvedIncludeEstimated
                ? `真实 ${formatTokens(Math.max(0, totals.total_tokens - totals.estimated_total_tokens))} + 估算 ${formatTokens(
                    totals.estimated_total_tokens
                  )}`
                : formatTokens(totals.total_tokens)
            }
          >
            {compactTokens(totals.total_tokens)}
          </strong>
          <span
            title={
              resolvedIncludeEstimated
                ? `${actualRequestCount} 次真实 usage + ${totals.estimated_request_count} 次估算补齐`
                : `${totals.request_count} 次已返回消耗数据的请求`
            }
          >
            {resolvedIncludeEstimated
              ? `${actualRequestCount} 次真实 + ${totals.estimated_request_count} 次估算`
              : `${totals.request_count} 次已返回消耗数据的请求`}
          </span>
        </article>
        <article className="usage-kpi-card">
          <span className="usage-kpi-label">输入</span>
          <strong title={formatTokens(totals.input_tokens)}>{compactTokens(totals.input_tokens)}</strong>
          <span
            title={
              resolvedIncludeEstimated
                ? `真实 ${formatTokens(actualInputTokens)} + 估算 ${formatTokens(totals.estimated_input_tokens)}`
                : `占总量 ${inputRatio}%`
            }
          >
            {resolvedIncludeEstimated ? `估算补入 ${compactTokens(totals.estimated_input_tokens)}` : `占总量 ${inputRatio}%`}
          </span>
        </article>
        <article className="usage-kpi-card">
          <span className="usage-kpi-label">输出</span>
          <strong title={formatTokens(totals.output_tokens)}>{compactTokens(totals.output_tokens)}</strong>
          <span title={`占总量 ${outputRatio}%`}>
            {resolvedIncludeEstimated ? `真实输出 ${compactTokens(actualOutputTokens)}` : `占总量 ${outputRatio}%`}
          </span>
        </article>
        <article className={`usage-kpi-card ${totals.usage_missing_count ? "warning" : ""}`}>
          <span className="usage-kpi-label">缺失统计</span>
          <strong>{totals.usage_missing_count}</strong>
          <span
            title={
              totals.usage_missing_count
                ? resolvedIncludeEstimated
                  ? `${totals.estimated_request_count} 条已估算补入，${unresolvedMissingCount} 条仍未计入`
                  : "未返回消耗数据，不计入汇总"
                : "全部请求均已返回消耗数据"
            }
          >
            {totals.usage_missing_count
              ? resolvedIncludeEstimated
                ? `${totals.estimated_request_count} 条已补入，${unresolvedMissingCount} 条未计入`
                : "未返回消耗数据，不计入汇总"
              : "全部请求均已返回消耗数据"}
          </span>
        </article>
        <article className="usage-kpi-card evolution">
          <span className="usage-kpi-label">自进化</span>
          <strong title={formatTokens(evolutionTotals.total_tokens)}>{compactTokens(evolutionTotals.total_tokens)}</strong>
          <span
            title={`${evolutionTotals.request_count} 次请求 · 输入 ${formatTokens(evolutionTotals.input_tokens)} / 输出 ${formatTokens(
              evolutionTotals.output_tokens
            )}`}
          >
            {evolutionTotals.request_count} 次请求 · 输入 {compactTokens(evolutionTotals.input_tokens)} / 输出{" "}
            {compactTokens(evolutionTotals.output_tokens)}
          </span>
        </article>
      </section>

      <section className="usage-hero-grid">
        <article className="usage-panel trend-panel">
          <div className="usage-panel-head">
            <div>
              <h2>按天消耗</h2>
              <p>输入与输出分开展示</p>
            </div>
            <span className="usage-chip">{summary ? `${summary.range.days} 天` : "--"}</span>
          </div>
          <div className="usage-day-chart">
            {byDay.map((bucket) => {
              const height = Math.max(4, Math.round((bucket.total_tokens / maxDayTokens) * 100));
              const inputHeight = bucket.total_tokens ? Math.max(3, Math.round((bucket.input_tokens / bucket.total_tokens) * height)) : 0;
              const outputHeight = Math.max(0, height - inputHeight);
              return (
                <div className="usage-day-column" key={bucket.date}>
                  <div className="usage-day-bars" title={`${bucket.date}\n${formatTokens(bucket.total_tokens)}`}>
                    <span className="usage-day-output" style={{ height: `${outputHeight}%` }} />
                    <span className="usage-day-input" style={{ height: `${inputHeight}%` }} />
                  </div>
                  <span className="usage-day-label">{dayLabel(bucket.date)}</span>
                  <strong>{compactTokens(bucket.total_tokens)}</strong>
                </div>
              );
            })}
          </div>
        </article>

        <aside className="usage-panel signal-panel">
          <div className="usage-panel-head">
            <div>
              <h2>当前高点</h2>
              <p>按所选范围实时聚合</p>
            </div>
          </div>
          <div className="usage-signal-list">
            <div className="usage-signal">
              <span>消耗最高模型</span>
              <strong>{topModel?.model ?? "无数据"}</strong>
              <em title={topModel ? formatTokens(topModel.total_tokens) : undefined}>
                {topModel ? compactTokens(topModel.total_tokens) : "--"}
              </em>
            </div>
            <div className="usage-signal">
              <span>消耗最高会话</span>
              <strong>{topSession?.session_title ?? "无数据"}</strong>
              <em title={topSession ? formatTokens(topSession.total_tokens) : undefined}>
                {topSession ? compactTokens(topSession.total_tokens) : "--"}
              </em>
            </div>
            <div className="usage-token-split" aria-label="输入输出占比">
              <span style={{ width: `${inputRatio}%` }} />
              <b style={{ width: `${outputRatio}%` }} />
            </div>
            <div className="usage-split-legend">
              <span><i className="legend-input" /> 输入</span>
              <span><i className="legend-output" /> 输出</span>
            </div>
          </div>
        </aside>
      </section>

      <section className="usage-breakdown-grid">
        <article className="usage-panel">
          <div className="usage-panel-head">
            <div>
              <h2>按模型</h2>
              <p>按提供方与模型聚合</p>
            </div>
          </div>
          <div className="usage-bar-list">
            {(summary?.by_model ?? []).map((bucket) => (
              <div className="usage-meter-row" key={`${bucket.provider_type}:${bucket.model}`}>
                <div className="usage-meter-topline">
                  <span>{bucket.model}</span>
                  <strong title={formatTokens(bucket.total_tokens)}>{compactTokens(bucket.total_tokens)}</strong>
                </div>
                <div className="usage-meter-track">
                  <span style={{ width: `${Math.max(3, (bucket.total_tokens / maxModelTokens) * 100)}%` }} />
                </div>
                <div className="usage-meter-meta">
                  <span>{bucket.request_count} 次请求</span>
                  <span>{providerTypeLabel(bucket.provider_type)}</span>
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="usage-panel">
          <div className="usage-panel-head">
            <div>
              <h2>按请求类型</h2>
              <p>主对话、压缩、自进化、RAG 等</p>
            </div>
          </div>
          <div className="usage-bar-list">
            {(summary?.by_request_kind ?? []).map((bucket) => (
              <div className="usage-meter-row compact" key={bucket.request_kind}>
                <div className="usage-meter-topline usage-kind-topline">
                  <span>{requestKindLabel(bucket.request_kind)}</span>
                  <strong title={formatTokens(bucket.total_tokens)}>{compactTokens(bucket.total_tokens)}</strong>
                </div>
                <p className="usage-kind-description">{requestKindDescription(bucket.request_kind)}</p>
                <div className="usage-meter-track secondary">
                  <span style={{ width: `${Math.max(3, (bucket.total_tokens / maxKindTokens) * 100)}%` }} />
                </div>
                <div className="usage-meter-meta usage-kind-meta">
                  <span>{bucket.request_count} 次请求</span>
                  <code>{bucket.request_kind}</code>
                </div>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="usage-table-grid">
        <article className="usage-panel session-panel">
          <div className="usage-panel-head">
            <div>
              <h2>会话消耗排行</h2>
              <p>用于定位高成本会话</p>
            </div>
          </div>
          <div className="usage-table-wrap">
            <table className="usage-table">
              <thead>
                <tr>
                  <th>会话</th>
                  <th>请求</th>
                  <th>输入</th>
                  <th>输出</th>
                  <th>总计</th>
                </tr>
              </thead>
              <tbody>
                {(summary?.by_session ?? []).map((bucket) => (
                  <tr key={bucket.session_id ?? "session:unknown"}>
                    <td>
                      <strong>{bucket.session_title ?? "未关联会话"}</strong>
                      <span>
                        {bucket.session_id ?? "--"}
                        {bucket.estimated_total_tokens > 0 ? ` · 估算 ${compactTokens(bucket.estimated_total_tokens)}` : ""}
                      </span>
                    </td>
                    <td>{bucket.request_count}</td>
                    <td>{formatTokens(bucket.input_tokens)}</td>
                    <td>{formatTokens(bucket.output_tokens)}</td>
                    <td>{formatTokens(bucket.total_tokens)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>

        <aside className="usage-panel latest-panel">
          <div className="usage-panel-head">
            <div>
              <h2>最近调用</h2>
              <p>最近返回的消耗明细</p>
            </div>
          </div>
          <div className="usage-feed">
            {(summary?.recent_records ?? []).map((record) => (
              <div
                className={`usage-feed-item ${
                  record.usage_available ? "" : resolvedIncludeEstimated && record.estimated_total_tokens > 0 ? "estimated" : "missing"
                }`}
                key={record.request_id}
              >
                <div>
                  <strong>{record.model}</strong>
                  <span>{requestKindLabel(record.request_kind)}</span>
                  <span>{record.attributed_session_title ?? record.session_title ?? "未关联会话"}</span>
                </div>
                <div>
                  <span>{formatTime(record.created_at)}</span>
                  <b
                    title={
                      record.usage_available
                        ? formatTokens(record.total_tokens)
                        : resolvedIncludeEstimated && record.estimated_total_tokens > 0
                          ? `估算 ${formatTokens(record.estimated_total_tokens)}`
                          : undefined
                    }
                  >
                    {record.usage_available
                      ? compactTokens(record.total_tokens)
                      : resolvedIncludeEstimated && record.estimated_total_tokens > 0
                        ? `估算 ${compactTokens(record.estimated_total_tokens)}`
                        : "缺失"}
                  </b>
                </div>
              </div>
            ))}
          </div>
        </aside>
      </section>
    </section>
  );
}
