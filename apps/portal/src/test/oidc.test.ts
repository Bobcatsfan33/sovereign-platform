import { afterEach, describe, expect, it, vi } from "vitest";

import { completeOidcLogin, oidcAvailable } from "../auth/oidc";

function b64url(value: string): string {
  return btoa(value).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

function token(payload: Record<string, unknown>): string {
  return `${b64url('{"alg":"none"}')}.${b64url(JSON.stringify(payload))}.sig`;
}

function setPending(nonce = "nonce-1", state = "state-1") {
  sessionStorage.setItem("sovereign-oidc-pending", JSON.stringify({ nonce, state }));
}

afterEach(() => {
  sessionStorage.clear();
  vi.unstubAllEnvs();
});

describe("OIDC callback validation", () => {
  it("accepts a matching state and nonce", () => {
    setPending();
    const idToken = token({
      sub: "alice",
      email: "alice@example.gov",
      nonce: "nonce-1",
      exp: Math.floor(Date.now() / 1000) + 60,
    });

    const auth = completeOidcLogin(
      `https://portal.example.gov/oidc/callback#id_token=${idToken}&state=state-1`,
    );

    expect(auth).toEqual({ type: "bearer", value: idToken, label: "alice@example.gov" });
    expect(sessionStorage.getItem("sovereign-oidc-pending")).toBeNull();
  });

  it("rejects a state mismatch", () => {
    setPending();
    const idToken = token({ sub: "alice", nonce: "nonce-1" });

    expect(() =>
      completeOidcLogin(
        `https://portal.example.gov/oidc/callback#id_token=${idToken}&state=wrong`,
      ),
    ).toThrow(/state mismatch/i);
  });

  it("rejects a nonce mismatch", () => {
    setPending();
    const idToken = token({ sub: "alice", nonce: "wrong" });

    expect(() =>
      completeOidcLogin(
        `https://portal.example.gov/oidc/callback#id_token=${idToken}&state=state-1`,
      ),
    ).toThrow(/nonce mismatch/i);
  });

  it("rejects expired tokens", () => {
    setPending();
    const idToken = token({
      sub: "alice",
      nonce: "nonce-1",
      exp: Math.floor(Date.now() / 1000) - 1,
    });

    expect(() =>
      completeOidcLogin(
        `https://portal.example.gov/oidc/callback#id_token=${idToken}&state=state-1`,
      ),
    ).toThrow(/expired/i);
  });

  it("reports OIDC as available only when issuer and client are configured", () => {
    expect(oidcAvailable()).toBe(false);

    vi.stubEnv("VITE_OIDC_ISSUER_URL", "https://idp.example.gov");
    vi.stubEnv("VITE_OIDC_CLIENT_ID", "sovereign-portal");

    expect(oidcAvailable()).toBe(true);
  });
});
