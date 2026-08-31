import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Deliberately separate from vite.config.ts (which owns the dev-server proxy
// to the FastAPI observer backend) so the test runner never needs that proxy
// or a real network/EventSource connection -- store-level tests mock
// `../api/client` entirely (see src/liveworkflow/__tests__).
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
  },
});
