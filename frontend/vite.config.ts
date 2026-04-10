import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@shared": path.resolve(__dirname, "src/shared") },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
  build: {
    rollupOptions: {
      input: {
        index: path.resolve(__dirname, "index.html"),
        client: path.resolve(__dirname, "client.html"),
        researcher: path.resolve(__dirname, "researcher.html"),
        analyzer: path.resolve(__dirname, "analyzer.html"),
      },
    },
  },
});
