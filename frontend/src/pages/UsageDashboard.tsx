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
  };
  available_models: string[];
  totals: {
    request_count: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    usage_missing_count: number;
  };
  by_day: Array<{
    date: string;
    request_count: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
  }>;
  by_model: Array<{
    provider_type: string;
    model: string;
    request_count: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
  }>;
  by_request_kind: Array<{
    request_kind: string;
    request_count: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
  }>;
  by_session: Array<{
    session_id: string | null;
    session_title: string | null;
    request_count: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
  }>;
  recent_records: Array<{
    request_id: string;
    session_id: string | null;
    session_title: string | null;
    turn_id: string | null;
    request_kind: string;
    provider_type: string;
    model: string;
    usage_available: boolean;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
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
  context_compaction: "上下文压缩",
  manual_context_compaction: "手动压缩",
  memory_extraction: "记忆抽取",
  evolution_analysis: "进化分析",
  evolution_skill_update: "技能进化",
  multimodal_analysis: "多模态解析",
  rag_rerank: "RAG 重排",
  commentary_fallback: "工具前说明",
};

const PROVIDER_TYPE_LABELS: Record<string, string> = {
  openai_compatible: "OpenAI 兼容",
  anthropic_compatible: "Anthropic 兼容",
  mock: "模拟",
};

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

function compactTokens(value: number) {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)} 百万`;
  if (value >= 10_000) return `${(value / 10_000).toFixed(1)} 万`;
  return String(value);
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

function providerTypeLabel(providerType: string) {
  return PROVIDER_TYPE_LABELS[providerType] ?? providerType;
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
  const [summary, setSummary] = useState<UsageSummaryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadSeed, setReloadSeed] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({
      days: String(RANGE_DAYS[activeRange]),
      tz: "Asia/Shanghai",
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
  }, [activeRange, apiBase, modelFilter, reloadSeed]);

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
  };
  const inputRatio = totals.total_tokens > 0 ? Math.round((totals.input_tokens / totals.total_tokens) * 100) : 0;
  const outputRatio = totals.total_tokens > 0 ? 100 - inputRatio : 0;
  const topModel = summary?.by_model[0] ?? null;
  const topSession = summary?.by_session[0] ?? null;
  const rangeLabel = summary ? `${summary.range.start_date} 至 ${summary.range.end_date}` : "--";
  const rootClassName = embedded ? "usage-demo-shell embedded" : "usage-demo-shell";

  return (
    <section className={rootClassName}>
      <header className="usage-demo-header">
        <div>
          <p className="usage-demo-kicker">真实消耗统计</p>
          <h1>消耗监控</h1>
          <p className="usage-demo-subtitle">
            按模型返回的真实消耗汇总 · {summary?.range.timezone ?? "Asia/Shanghai"} · {rangeLabel}
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
          <strong>{formatTokens(totals.total_tokens)}</strong>
          <span>{totals.request_count} 次已返回消耗数据的请求</span>
        </article>
        <article className="usage-kpi-card">
          <span className="usage-kpi-label">输入</span>
          <strong>{formatTokens(totals.input_tokens)}</strong>
          <span>占总量 {inputRatio}%</span>
        </article>
        <article className="usage-kpi-card">
          <span className="usage-kpi-label">输出</span>
          <strong>{formatTokens(totals.output_tokens)}</strong>
          <span>占总量 {outputRatio}%</span>
        </article>
        <article className={`usage-kpi-card ${totals.usage_missing_count ? "warning" : ""}`}>
          <span className="usage-kpi-label">缺失统计</span>
          <strong>{totals.usage_missing_count}</strong>
          <span>{totals.usage_missing_count ? "未返回消耗数据，不计入汇总" : "全部请求均已返回消耗数据"}</span>
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
              <em>{topModel ? formatTokens(topModel.total_tokens) : "--"}</em>
            </div>
            <div className="usage-signal">
              <span>消耗最高会话</span>
              <strong>{topSession?.session_title ?? "无数据"}</strong>
              <em>{topSession ? formatTokens(topSession.total_tokens) : "--"}</em>
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
                  <strong>{formatTokens(bucket.total_tokens)}</strong>
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
              <p>主对话、压缩、RAG 等</p>
            </div>
          </div>
          <div className="usage-bar-list">
            {(summary?.by_request_kind ?? []).map((bucket) => (
              <div className="usage-meter-row compact" key={bucket.request_kind}>
                <div className="usage-meter-topline">
                  <span>{requestKindLabel(bucket.request_kind)}</span>
                  <strong>{formatTokens(bucket.total_tokens)}</strong>
                </div>
                <div className="usage-meter-track secondary">
                  <span style={{ width: `${Math.max(3, (bucket.total_tokens / maxKindTokens) * 100)}%` }} />
                </div>
                <div className="usage-meter-meta">
                  <span>{bucket.request_count} 次请求</span>
                  <span>{bucket.request_kind}</span>
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
                      <span>{bucket.session_id ?? "--"}</span>
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
              <div className={`usage-feed-item ${record.usage_available ? "" : "missing"}`} key={record.request_id}>
                <div>
                  <strong>{record.model}</strong>
                  <span>{record.session_title ?? "未关联会话"}</span>
                </div>
                <div>
                  <span>{formatTime(record.created_at)}</span>
                  <b>{record.usage_available ? compactTokens(record.total_tokens) : "缺失"}</b>
                </div>
              </div>
            ))}
          </div>
        </aside>
      </section>
    </section>
  );
}
