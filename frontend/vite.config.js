import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Em desenvolvimento, o painel roda em :5173 e faz proxy das chamadas
// para a API do ATLAS OS em :8000 (/api, /media, /go).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/media": { target: "http://localhost:8000", changeOrigin: true },
      "/go": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
  },
});
