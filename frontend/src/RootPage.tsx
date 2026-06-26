import { useEffect, useMemo, useState } from "react";
import App from "./App";
import UsageDemoPage from "./pages/UsageDemoPage";
import UploadTaskPage from "./pages/UploadTaskPage";
import SetupPage from "./pages/SetupPage";
import LoginPage from "./pages/LoginPage";
import "./styles.css";
import { fetchJson, getApiBase } from "./lib/api";

type AuthStatusResponse = {
  enabled: boolean;
  needs_setup: boolean;
  authenticated: boolean;
  auth_method: string | null;
  admin_token_configured: boolean;
};

function resolveSpecialPage(pathname: string) {
  if (pathname === "/upload-task") {
    return UploadTaskPage;
  }
  if (pathname === "/usage-demo") {
    return UsageDemoPage;
  }
  return null;
}

export default function RootPage() {
  const pathname = useMemo(() => window.location.pathname.replace(/\/+$/, "") || "/", []);
  const apiBase = getApiBase();
  const [status, setStatus] = useState<AuthStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const SpecialPage = resolveSpecialPage(pathname);

  useEffect(() => {
    if (SpecialPage) {
      return;
    }
    void loadStatus();
  }, [SpecialPage]);

  async function loadStatus() {
    setLoading(true);
    setError(null);
    try {
      const payload = await fetchJson<AuthStatusResponse>(`${apiBase}/api/auth/status`);
      setStatus(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载登录状态失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleLogout() {
    await fetchJson(`${apiBase}/api/auth/logout`, { method: "POST" });
    window.location.replace("/login");
  }

  function handleEnteredConsole() {
    window.location.replace("/");
  }

  if (SpecialPage) {
    return <SpecialPage />;
  }

  if (loading) {
    return (
      <div className="auth-entry-screen">
        <div className="auth-entry-loading">
          <span className="auth-entry-kicker">Newman Console</span>
          <p className="auth-entry-summary">正在检查当前实例状态。</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="auth-entry-screen">
        <div className="auth-entry-loading">
          <span className="auth-entry-kicker">Newman Console</span>
          <div className="auth-entry-error">{error}</div>
        </div>
      </div>
    );
  }

  if (status && !status.needs_setup && pathname === "/setup") {
    window.location.replace(status.authenticated ? "/" : "/login");
    return null;
  }

  if (status?.authenticated && pathname === "/login") {
    window.location.replace("/");
    return null;
  }

  if (status?.needs_setup) {
    return <SetupPage onConfigured={handleEnteredConsole} />;
  }

  if (!status?.authenticated) {
    return <LoginPage onLoggedIn={handleEnteredConsole} />;
  }

  return <App onLogout={handleLogout} />;
}
