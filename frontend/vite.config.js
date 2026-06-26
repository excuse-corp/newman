import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
function firstHeaderValue(value) {
    var _a;
    if (Array.isArray(value)) {
        return ((_a = value[0]) === null || _a === void 0 ? void 0 : _a.trim()) || null;
    }
    if (typeof value === "string" && value.trim()) {
        return value.trim();
    }
    return null;
}
function createBackendProxy(target) {
    return {
        target: target,
        xfwd: true,
        configure: function (proxy) {
            proxy.on("proxyReq", function (proxyReq, req) {
                var _a, _b;
                var forwardedHost = (_a = firstHeaderValue(req.headers["x-forwarded-host"])) !== null && _a !== void 0 ? _a : firstHeaderValue(req.headers.host);
                if (forwardedHost) {
                    proxyReq.setHeader("x-forwarded-host", forwardedHost);
                }
                var forwardedProto = (_b = firstHeaderValue(req.headers["x-forwarded-proto"])) !== null && _b !== void 0 ? _b : (req.socket.encrypted ? "https" : "http");
                proxyReq.setHeader("x-forwarded-proto", forwardedProto);
            });
        },
    };
}
export default defineConfig(function (_a) {
    var mode = _a.mode;
    var env = loadEnv(mode, ".", "");
    var apiProxyTarget = env.VITE_API_PROXY || "http://127.0.0.1:8005";
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
