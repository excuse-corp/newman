import { useState, type FormEvent } from "react";
import "./auth-entry.css";
import "./setup-page.css";
import { fetchJson, getApiBase } from "../lib/api";
import logo from "../assets/newman-logo.png";

type LoginPageProps = {
  onLoggedIn?: () => void;
};

export default function LoginPage({ onLoggedIn }: LoginPageProps) {
  const apiBase = getApiBase();
  const [adminToken, setAdminToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!adminToken.trim() || submitting) {
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await fetchJson(`${apiBase}/api/auth/login`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          admin_token: adminToken.trim(),
        }),
      });
      onLoggedIn?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-entry-screen auth-entry-screen--setup">
      <div className="setup-page-shell setup-page-shell--login">
        <header className="setup-brand">
          <div className="setup-brand-mark">
            <img src={logo} alt="NewMan" className="setup-brand-image" />
          </div>
          <h1 className="setup-brand-title">
            <span>NewMan</span>
            <span className="setup-brand-title-cn">牛马</span>
          </h1>
          <span className="setup-brand-kicker">Unlock · 解锁</span>
          <p className="setup-brand-tagline">
            输入这个实例的访问密钥。验证成功后，服务端会写入 HttpOnly Cookie，当前浏览器直接恢复访问。
          </p>
        </header>

        <form className="setup-card setup-form" onSubmit={handleSubmit}>
          <section className="setup-section">
            <div className="setup-section-head">
              <span className="setup-section-label">Instance Key</span>
              <span className="setup-section-rule" aria-hidden="true" />
              <span className="setup-section-meta">NEWMAN_AUTH__ADMIN_TOKEN</span>
            </div>

            <div className="setup-field">
              <div className="setup-field-row">
                <label htmlFor="login-admin-token">实例访问密钥</label>
                <button
                  type="button"
                  className="setup-field-flag setup-field-toggle"
                  onClick={() => setShowToken((value) => !value)}
                  disabled={!adminToken}
                >
                  {showToken ? "hide" : "show"}
                </button>
              </div>
              <input
                id="login-admin-token"
                type={showToken ? "text" : "password"}
                className="setup-input"
                value={adminToken}
                onChange={(event) => setAdminToken(event.target.value)}
                placeholder="粘贴 .env 中的 admin token"
                autoComplete="off"
                spellCheck={false}
                autoFocus
              />
            </div>
          </section>

          {error ? <div className="setup-error">{error}</div> : null}

          <div className="setup-footer">
            <button type="submit" className="setup-submit" disabled={submitting || !adminToken.trim()}>
              {submitting ? "验证中…" : "进入 Newman"}
            </button>
            <p className="setup-foot-note">
              没有账号系统 · 密钥写在项目根目录 <code>.env</code>，可在 Settings &gt; Config 重新生成
            </p>
          </div>
        </form>
      </div>
    </div>
  );
}
