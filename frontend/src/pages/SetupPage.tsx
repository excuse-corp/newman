import { useMemo, useState, type FormEvent } from "react";
import "./auth-entry.css";
import "./setup-page.css";
import { fetchJson, getApiBase } from "../lib/api";
import logo from "../assets/newman-logo.png";

type SetupPageProps = {
  onConfigured?: () => void;
};

type BootstrapSetupResponse = {
  configured: boolean;
  authenticated: boolean;
  admin_token_configured: boolean;
  warnings?: string[];
};

export default function SetupPage({ onConfigured }: SetupPageProps) {
  const apiBase = getApiBase();
  const [primaryEndpoint, setPrimaryEndpoint] = useState("");
  const [primaryApiKey, setPrimaryApiKey] = useState("");
  const [primaryModel, setPrimaryModel] = useState("");
  const [sharePrimaryForMultimodal, setSharePrimaryForMultimodal] = useState(true);
  const [multimodalEndpoint, setMultimodalEndpoint] = useState("");
  const [multimodalApiKey, setMultimodalApiKey] = useState("");
  const [multimodalModel, setMultimodalModel] = useState("");
  const [anysearchApiKey, setAnysearchApiKey] = useState("");
  const [feishuAppId, setFeishuAppId] = useState("");
  const [feishuAppSecret, setFeishuAppSecret] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trimmedPrimaryEndpoint = primaryEndpoint.trim();
  const trimmedPrimaryApiKey = primaryApiKey.trim();
  const trimmedPrimaryModel = primaryModel.trim();
  const trimmedMultimodalEndpoint = multimodalEndpoint.trim();
  const trimmedMultimodalApiKey = multimodalApiKey.trim();
  const trimmedMultimodalModel = multimodalModel.trim();
  const trimmedFeishuAppId = feishuAppId.trim();
  const trimmedFeishuAppSecret = feishuAppSecret.trim();

  const canSubmit = useMemo(() => {
    if (!trimmedPrimaryEndpoint || !trimmedPrimaryApiKey || !trimmedPrimaryModel) {
      return false;
    }
    if (!sharePrimaryForMultimodal) {
      return Boolean(trimmedMultimodalEndpoint && trimmedMultimodalApiKey && trimmedMultimodalModel);
    }
    return true;
  }, [
    sharePrimaryForMultimodal,
    trimmedMultimodalApiKey,
    trimmedMultimodalEndpoint,
    trimmedMultimodalModel,
    trimmedPrimaryApiKey,
    trimmedPrimaryEndpoint,
    trimmedPrimaryModel,
  ]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting || !canSubmit) {
      return;
    }
    if ((trimmedFeishuAppId && !trimmedFeishuAppSecret) || (!trimmedFeishuAppId && trimmedFeishuAppSecret)) {
      setError("飞书接入需要同时填写 app_id 和 app_secret。");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      await fetchJson<BootstrapSetupResponse>(`${apiBase}/api/bootstrap/setup`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          primary_endpoint: trimmedPrimaryEndpoint,
          primary_api_key: trimmedPrimaryApiKey,
          primary_model: trimmedPrimaryModel,
          share_primary_for_multimodal: sharePrimaryForMultimodal,
          multimodal_endpoint: sharePrimaryForMultimodal ? undefined : trimmedMultimodalEndpoint,
          multimodal_api_key: sharePrimaryForMultimodal ? undefined : trimmedMultimodalApiKey,
          multimodal_model: trimmedMultimodalModel || undefined,
          anysearch_api_key: anysearchApiKey.trim() || undefined,
          feishu_app_id: trimmedFeishuAppId || undefined,
          feishu_app_secret: trimmedFeishuAppSecret || undefined,
          login_after_setup: true,
        }),
      });
      onConfigured?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "首次配置失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-entry-screen auth-entry-screen--setup">
      <div className="setup-page-shell">
        <header className="setup-brand">
          <div className="setup-brand-mark">
            <img src={logo} alt="NewMan" className="setup-brand-image" />
          </div>
          <h1 className="setup-brand-title">
            <span>NewMan</span>
            <span className="setup-brand-title-for">for</span>
            <span className="setup-brand-title-cn">牛马</span>
          </h1>
          <span className="setup-brand-kicker">First Run · 初始化</span>
          <p className="setup-brand-tagline">
            完成启动设置后进入你的牛马生涯帮手
          </p>
        </header>

        <form className="setup-card setup-form" onSubmit={handleSubmit}>
          <section className="setup-section">
            <div className="setup-section-head">
              <span className="setup-section-label">Model</span>
              <span className="setup-section-rule" aria-hidden="true" />
              <span className="setup-section-meta">openai_compatible</span>
            </div>

            <div className="setup-field">
              <div className="setup-field-row">
                <label htmlFor="setup-primary-endpoint">主模型 Endpoint</label>
                <span className="setup-field-flag" data-required="true">required</span>
              </div>
              <input
                id="setup-primary-endpoint"
                className="setup-input"
                value={primaryEndpoint}
                onChange={(event) => setPrimaryEndpoint(event.target.value)}
                placeholder="https://api.openai.com/v1"
                autoComplete="off"
                spellCheck={false}
              />
            </div>

            <div className="setup-field">
              <div className="setup-field-row">
                <label htmlFor="setup-primary-api-key">主模型 API key</label>
                <span className="setup-field-flag" data-required="true">required</span>
              </div>
              <input
                id="setup-primary-api-key"
                type="password"
                className="setup-input"
                value={primaryApiKey}
                onChange={(event) => setPrimaryApiKey(event.target.value)}
                placeholder="sk-..."
                autoComplete="off"
                spellCheck={false}
              />
            </div>

            <div className="setup-grid-2">
              <div className="setup-field">
                <div className="setup-field-row">
                  <label htmlFor="setup-primary-model">主模型</label>
                  <span className="setup-field-flag" data-required="true">required</span>
                </div>
                <input
                  id="setup-primary-model"
                  className="setup-input"
                  value={primaryModel}
                  onChange={(event) => setPrimaryModel(event.target.value)}
                  placeholder="gpt-4.1-mini"
                  autoComplete="off"
                  spellCheck={false}
                />
              </div>

              <div className="setup-field">
                <div className="setup-field-row">
                  <label htmlFor="setup-multimodal-model">多模态模型</label>
                  <span className="setup-field-flag">{sharePrimaryForMultimodal ? "optional" : "required"}</span>
                </div>
                <input
                  id="setup-multimodal-model"
                  className="setup-input"
                  value={multimodalModel}
                  onChange={(event) => setMultimodalModel(event.target.value)}
                  placeholder={sharePrimaryForMultimodal ? "留空沿用主模型" : "gpt-4.1"}
                  autoComplete="off"
                  spellCheck={false}
                />
              </div>
            </div>

            <label className="setup-check">
              <input
                type="checkbox"
                checked={sharePrimaryForMultimodal}
                onChange={(event) => setSharePrimaryForMultimodal(event.target.checked)}
              />
              <span>多模态沿用主模型的 endpoint 和 API key</span>
            </label>

            {!sharePrimaryForMultimodal ? (
              <div className="setup-grid-2">
                <div className="setup-field">
                  <div className="setup-field-row">
                    <label htmlFor="setup-multimodal-endpoint">多模态 Endpoint</label>
                    <span className="setup-field-flag" data-required="true">required</span>
                  </div>
                  <input
                    id="setup-multimodal-endpoint"
                    className="setup-input"
                    value={multimodalEndpoint}
                    onChange={(event) => setMultimodalEndpoint(event.target.value)}
                    placeholder="https://api.openai.com/v1"
                    autoComplete="off"
                    spellCheck={false}
                  />
                </div>

                <div className="setup-field">
                  <div className="setup-field-row">
                    <label htmlFor="setup-multimodal-api-key">多模态 API key</label>
                    <span className="setup-field-flag" data-required="true">required</span>
                  </div>
                  <input
                    id="setup-multimodal-api-key"
                    type="password"
                    className="setup-input"
                    value={multimodalApiKey}
                    onChange={(event) => setMultimodalApiKey(event.target.value)}
                    placeholder="sk-..."
                    autoComplete="off"
                    spellCheck={false}
                  />
                </div>
              </div>
            ) : null}
          </section>

          <section className="setup-section">
            <div className="setup-section-head">
              <span className="setup-section-label">Extras</span>
              <span className="setup-section-rule" aria-hidden="true" />
              <span className="setup-section-meta">AnySearch · 飞书</span>
            </div>

            <div className="setup-field">
              <div className="setup-field-row">
                <label htmlFor="setup-anysearch-key">AnySearch API key</label>
                <span className="setup-field-flag">optional</span>
              </div>
              <input
                id="setup-anysearch-key"
                type="password"
                className="setup-input"
                value={anysearchApiKey}
                onChange={(event) => setAnysearchApiKey(event.target.value)}
                placeholder="as_sk_..."
                autoComplete="off"
                spellCheck={false}
              />
            </div>

            <div className="setup-grid-2">
              <div className="setup-field">
                <div className="setup-field-row">
                  <label htmlFor="setup-feishu-app-id">飞书 app_id</label>
                  <span className="setup-field-flag">optional</span>
                </div>
                <input
                  id="setup-feishu-app-id"
                  className="setup-input"
                  value={feishuAppId}
                  onChange={(event) => setFeishuAppId(event.target.value)}
                  placeholder="cli_xxx"
                  autoComplete="off"
                  spellCheck={false}
                />
              </div>

              <div className="setup-field">
                <div className="setup-field-row">
                  <label htmlFor="setup-feishu-app-secret">飞书 app_secret</label>
                  <span className="setup-field-flag">optional</span>
                </div>
                <input
                  id="setup-feishu-app-secret"
                  type="password"
                  className="setup-input"
                  value={feishuAppSecret}
                  onChange={(event) => setFeishuAppSecret(event.target.value)}
                  placeholder="留空则不启用飞书入站"
                  autoComplete="off"
                  spellCheck={false}
                />
              </div>
            </div>
          </section>

          {error ? <div className="setup-error">{error}</div> : null}

          <div className="setup-footer">
            <button type="submit" className="setup-submit" disabled={submitting || !canSubmit}>
              {submitting ? "保存中…" : "保存配置并进入 Newman"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
