import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
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
                "/api": apiProxyTarget,
                "/healthz": apiProxyTarget,
                "/readyz": apiProxyTarget
            }
        },
        preview: {
            host: "0.0.0.0",
            port: 7775,
            strictPort: true
        }
    };
});
