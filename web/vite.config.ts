import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// ATOM_API overrides the backend the dev server proxies /api to (e.g. the mock server).
const target = process.env.ATOM_API ?? "http://127.0.0.1:8787";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target,
        changeOrigin: true,
        // Never ask the backend for compressed bodies: gzip would buffer SSE frames.
        headers: { "Accept-Encoding": "identity" },
        configure: (proxy) => {
          proxy.on("proxyRes", (res) => {
            if ((res.headers["content-type"] ?? "").includes("text/event-stream")) {
              res.headers["cache-control"] = "no-cache, no-transform";
              res.headers["x-accel-buffering"] = "no";
            }
          });
        },
      },
    },
  },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 900 },
});
