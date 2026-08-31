import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // The FastAPI observer backend (flowstate.cli serve-ui, configs/ui/observer.yaml)
      // runs separately on 127.0.0.1:8000. Proxying keeps REST + SSE calls same-origin
      // during development; production serves both from the same FastAPI process.
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
