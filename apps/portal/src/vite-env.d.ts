/// <reference types="vite/client" />

// Vite inlines VITE_* env vars at build time. Augment the typed shape
// so import.meta.env.VITE_* is strongly-typed instead of `any`.
interface ImportMetaEnv {
  readonly VITE_BROKER_URL?: string;
  readonly VITE_AUDIT_URL?: string;
  readonly VITE_DEV_BEARER_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare module "*.css";
