import { defineConfig, loadEnv, type ProxyOptions } from "vite";
import react from "@vitejs/plugin-react";

function firstHeaderValue(value: string | string[] | undefined): string | null {
  if (Array.isArray(value)) {
    return value[0]?.trim() || null;
  }
  if (typeof value === "string" && value.trim()) {
    return value.trim();
  }
  return null;
}

function createBackendProxy(target: string): ProxyOptions {
  return {
    target,
    xfwd: true,
    configure(proxy) {
      proxy.on("proxyReq", (proxyReq, req) => {
        const forwardedHost = firstHeaderValue(req.headers["x-forwarded-host"]) ?? firstHeaderValue(req.headers.host);
        if (forwardedHost) {
          proxyReq.setHeader("x-forwarded-host", forwardedHost);
        }

        const forwardedProto =
          firstHeaderValue(req.headers["x-forwarded-proto"]) ?? (req.socket.encrypted ? "https" : "http");
        proxyReq.setHeader("x-forwarded-proto", forwardedProto);
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const apiProxyTarget = env.VITE_API_PROXY || "http://127.0.0.1:8005";

  return {
    plugins: [react()],
    server: {
      host: "0.0.0.0",
      port: 7775,
      strictPort: true,
      proxy: {
        "/api": createBackendProxy(apiProxyTarget),
        "/healthz": createBackendProxy(apiProxyTarget),
        "/readyz": createBackendProxy(apiProxyTarget),
      }
    },
    preview: {
      host: "0.0.0.0",
      port: 7775,
      strictPort: true
    }
  };
});
