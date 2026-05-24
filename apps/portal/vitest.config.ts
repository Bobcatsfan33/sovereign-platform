import { defineConfig } from "vitest/config";

// Standalone Vitest config. Kept independent of vite.config.ts so the
// occasional vitest↔vite version skew doesn't surface as a type error
// on the React plugin.
//
// JSX is transformed by esbuild's automatic runtime (no plugin needed
// for tests); the real Vite build still uses @vitejs/plugin-react.
export default defineConfig({
  esbuild: {
    jsx: "automatic",
  },
  test: {
    environment: "happy-dom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
