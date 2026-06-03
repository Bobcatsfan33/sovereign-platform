import type { StoredAuth } from "../hooks/useAuth";

const PENDING_KEY = "sovereign-oidc-pending";

export interface OidcConfig {
  issuerUrl: string;
  clientId: string;
  audience?: string;
  redirectUri: string;
  authorizationEndpoint?: string;
  tokenEndpoint?: string;
}

interface PendingOidc {
  codeVerifier: string;
  nonce: string;
  state: string;
}

interface OidcMetadata {
  authorizationEndpoint: string;
  tokenEndpoint: string;
}

interface TokenResponse {
  access_token?: string;
  id_token?: string;
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
    authorizationEndpoint: env("VITE_OIDC_AUTHORIZATION_URL") || undefined,
    tokenEndpoint: env("VITE_OIDC_TOKEN_URL") || undefined,
  };
}

export function oidcAvailable(): boolean {
  return oidcConfig() !== null;
}

function randomBase64Url(bytes = 32): string {
  const data = new Uint8Array(bytes);
  crypto.getRandomValues(data);
  return base64Url(data);
}

function base64Url(data: Uint8Array): string {
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

async function pkceChallenge(verifier: string): Promise<string> {
  const data = new TextEncoder().encode(verifier);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return base64Url(new Uint8Array(digest));
}

async function oidcMetadata(config: OidcConfig): Promise<OidcMetadata> {
  if (config.authorizationEndpoint && config.tokenEndpoint) {
    return {
      authorizationEndpoint: config.authorizationEndpoint,
      tokenEndpoint: config.tokenEndpoint,
    };
  }

  const response = await fetch(`${config.issuerUrl}/.well-known/openid-configuration`);
  if (!response.ok) throw new Error(`OIDC discovery failed: ${response.status}`);
  const body = (await response.json()) as {
    authorization_endpoint?: string;
    token_endpoint?: string;
  };
  const authorizationEndpoint = config.authorizationEndpoint || body.authorization_endpoint;
  const tokenEndpoint = config.tokenEndpoint || body.token_endpoint;
  if (!authorizationEndpoint || !tokenEndpoint) {
    throw new Error("OIDC discovery is missing authorization_endpoint or token_endpoint");
  }
  return { authorizationEndpoint, tokenEndpoint };
}

export async function beginOidcLogin(config = oidcConfig()): Promise<void> {
  if (!config) throw new Error("OIDC is not configured");
  const metadata = await oidcMetadata(config);
  const codeVerifier = randomBase64Url(64);
  const codeChallenge = await pkceChallenge(codeVerifier);
  const nonce = randomBase64Url();
  const state = randomBase64Url();
  sessionStorage.setItem(PENDING_KEY, JSON.stringify({ codeVerifier, nonce, state }));

  const url = new URL(metadata.authorizationEndpoint);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("client_id", config.clientId);
  url.searchParams.set("redirect_uri", config.redirectUri);
  url.searchParams.set("scope", "openid profile email");
  url.searchParams.set("code_challenge", codeChallenge);
  url.searchParams.set("code_challenge_method", "S256");
  url.searchParams.set("nonce", nonce);
  url.searchParams.set("state", state);
  if (config.audience) url.searchParams.set("audience", config.audience);
  window.location.assign(url.toString());
}

async function exchangeCode(
  config: OidcConfig,
  metadata: OidcMetadata,
  code: string,
  codeVerifier: string,
): Promise<TokenResponse> {
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: config.clientId,
    code,
    redirect_uri: config.redirectUri,
    code_verifier: codeVerifier,
  });
  if (config.audience) body.set("audience", config.audience);

  const response = await fetch(metadata.tokenEndpoint, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!response.ok) throw new Error(`OIDC token exchange failed: ${response.status}`);
  return (await response.json()) as TokenResponse;
}

export async function completeOidcLogin(
  callbackUrl = window.location.href,
  config = oidcConfig(),
): Promise<StoredAuth> {
  if (!config) throw new Error("OIDC is not configured");
  const url = new URL(callbackUrl);
  const params = new URLSearchParams(url.search || (url.hash.startsWith("#") ? url.hash.slice(1) : ""));
  const error = params.get("error");
  if (error) throw new Error(`OIDC login failed: ${error}`);

  const code = params.get("code");
  const state = params.get("state");
  if (!code || !state) throw new Error("OIDC callback is missing code or state");

  const pending = readPending();
  if (state !== pending.state) throw new Error("OIDC state mismatch");

  const metadata = await oidcMetadata(config);
  const tokenResponse = await exchangeCode(config, metadata, code, pending.codeVerifier);
  if (!tokenResponse.id_token) throw new Error("OIDC token response is missing id_token");

  const claims = decodeJwtPayload(tokenResponse.id_token);
  if (claims.iss !== config.issuerUrl) throw new Error("OIDC issuer mismatch");
  const aud = claims.aud;
  const audiences = Array.isArray(aud) ? aud : [aud];
  if (!audiences.includes(config.clientId)) throw new Error("OIDC audience mismatch");
  if (claims.nonce !== pending.nonce) throw new Error("OIDC nonce mismatch");
  if (typeof claims.exp === "number" && claims.exp <= Math.floor(Date.now() / 1000)) {
    throw new Error("OIDC token is expired");
  }

  sessionStorage.removeItem(PENDING_KEY);
  const bearer = tokenResponse.access_token || tokenResponse.id_token;
  const label =
    (typeof claims.email === "string" && claims.email) ||
    (typeof claims.preferred_username === "string" && claims.preferred_username) ||
    (typeof claims.sub === "string" && claims.sub) ||
    "oidc user";
  return { type: "bearer", value: bearer, label };
}
