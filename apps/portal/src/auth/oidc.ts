import type { StoredAuth } from "../hooks/useAuth";

const PENDING_KEY = "sovereign-oidc-pending";

export interface OidcConfig {
  issuerUrl: string;
  clientId: string;
  audience?: string;
  redirectUri: string;
}

interface PendingOidc {
  nonce: string;
  state: string;
}

function env(name: string): string {
  return (import.meta.env[name] as string | undefined)?.trim() ?? "";
}

export function oidcConfig(): OidcConfig | null {
  const issuerUrl = env("VITE_OIDC_ISSUER_URL").replace(/\/$/, "");
  const clientId = env("VITE_OIDC_CLIENT_ID");
  if (!issuerUrl || !clientId) return null;
  return {
    issuerUrl,
    clientId,
    audience: env("VITE_OIDC_AUDIENCE") || undefined,
    redirectUri:
      env("VITE_OIDC_REDIRECT_URI") || `${window.location.origin}/oidc/callback`,
  };
}

export function oidcAvailable(): boolean {
  return oidcConfig() !== null;
}

function randomBase64Url(bytes = 32): string {
  const data = new Uint8Array(bytes);
  crypto.getRandomValues(data);
  return btoa(String.fromCharCode(...data))
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replaceAll("=", "");
}

function decodeBase64Url(input: string): string {
  const padded = input.replaceAll("-", "+").replaceAll("_", "/").padEnd(
    Math.ceil(input.length / 4) * 4,
    "=",
  );
  return atob(padded);
}

function decodeJwtPayload(token: string): Record<string, unknown> {
  const [, payload] = token.split(".");
  if (!payload) throw new Error("OIDC token is malformed");
  return JSON.parse(decodeBase64Url(payload)) as Record<string, unknown>;
}

function readPending(): PendingOidc {
  const raw = sessionStorage.getItem(PENDING_KEY);
  if (!raw) throw new Error("Missing OIDC login state");
  return JSON.parse(raw) as PendingOidc;
}

export function beginOidcLogin(config = oidcConfig()): void {
  if (!config) throw new Error("OIDC is not configured");
  const nonce = randomBase64Url();
  const state = randomBase64Url();
  sessionStorage.setItem(PENDING_KEY, JSON.stringify({ nonce, state }));

  const url = new URL(`${config.issuerUrl}/authorize`);
  url.searchParams.set("response_type", "id_token");
  url.searchParams.set("client_id", config.clientId);
  url.searchParams.set("redirect_uri", config.redirectUri);
  url.searchParams.set("scope", "openid profile email");
  url.searchParams.set("nonce", nonce);
  url.searchParams.set("state", state);
  if (config.audience) url.searchParams.set("audience", config.audience);
  window.location.assign(url.toString());
}

export function completeOidcLogin(callbackUrl = window.location.href): StoredAuth {
  const url = new URL(callbackUrl);
  const params = new URLSearchParams(url.hash.startsWith("#") ? url.hash.slice(1) : url.search);
  const error = params.get("error");
  if (error) throw new Error(`OIDC login failed: ${error}`);

  const token = params.get("id_token");
  const state = params.get("state");
  if (!token || !state) throw new Error("OIDC callback is missing id_token or state");

  const pending = readPending();
  if (state !== pending.state) throw new Error("OIDC state mismatch");

  const claims = decodeJwtPayload(token);
  if (claims.nonce !== pending.nonce) throw new Error("OIDC nonce mismatch");
  if (typeof claims.exp === "number" && claims.exp <= Math.floor(Date.now() / 1000)) {
    throw new Error("OIDC token is expired");
  }

  sessionStorage.removeItem(PENDING_KEY);
  const label =
    (typeof claims.email === "string" && claims.email) ||
    (typeof claims.preferred_username === "string" && claims.preferred_username) ||
    (typeof claims.sub === "string" && claims.sub) ||
    "oidc user";
  return { type: "bearer", value: token, label };
}
