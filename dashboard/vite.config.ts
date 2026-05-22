import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/github_agent_bridge/dashboard_static",
    emptyOutDir: true,
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        manualChunks: {
          charts: ["recharts"],
        },
      },
    },
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8765",
      "/auth": "http://127.0.0.1:8765",
    },
  },
});
