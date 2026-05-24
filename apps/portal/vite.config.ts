import react from "@vitejs/plugin-react";
import tailwind from "@tailwindcss/vite";
import { defineConfig } from "vite";

// Vite config for the Sovereign Platform portal SPA.
// Dev server proxies API calls to the broker so localhost-served pages
// can hit /v2/* without CORS gymnastics during development; production
// builds talk to the broker directly using VITE_BROKER_URL (set at
// build time or injected via the nginx config map).
//
// Vitest config lives in vitest.config.ts so we don't end up with two
// `defineConfig` shapes fighting over the `test` key.
export default defineConfig({
  plugins: [react(), tailwind()],
  server: {
    port: 5173,
    host: "0.0.0.0",
    proxy: {
      "/v2": "http://localhost:8080",
      "/audit": {
        target: "http://localhost:8086",
        rewrite: (path) => path.replace(/^\/audit/, ""),
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
