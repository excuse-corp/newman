import UsageDashboard from "./UsageDashboard";

function getApiBase() {
  if (import.meta.env.VITE_API_BASE) {
    return import.meta.env.VITE_API_BASE;
  }
  return window.location.origin;
}

export default function UsageDemoPage() {
  return <UsageDashboard apiBase={getApiBase()} />;
}
