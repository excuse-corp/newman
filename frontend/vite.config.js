import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
    plugins: [react()],
    server: {
        host: "0.0.0.0",
        port: 7775,
        strictPort: true,
        proxy: {
            "/api": "http://127.0.0.1:8005",
            "/healthz": "http://127.0.0.1:8005",
            "/readyz": "http://127.0.0.1:8005"
        }
    },
    preview: {
        host: "0.0.0.0",
        port: 7775,
        strictPort: true
    }
});
