import { afterEach, describe, expect, it, vi } from "vitest";

import { completeOidcLogin, oidcAvailable, type OidcConfig } from "../auth/oidc";

const CONFIG: OidcConfig = {
  issuerUrl: "https://idp.example.gov",
  clientId: "sovereign-portal",
  audience: "sovereign-api",
  redirectUri: "https://portal.example.gov/oidc/callback",
  authorizationEndpoint: "https://idp.example.gov/authorize",
  tokenEndpoint: "https://idp.example.gov/oauth/token",
};

function b64url(value: string): string {
  return btoa(value).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

function token(payload: Record<string, unknown>): string {
  return `${b64url('{"alg":"none"}')}.${b64url(JSON.stringify(payload))}.sig`;
}

function setPending(nonce = "nonce-1", state = "state-1", codeVerifier = "verifier-1") {
  sessionStorage.setItem(
    "sovereign-oidc-pending",
    JSON.stringify({ codeVerifier, nonce, state }),
  );
}

function mockTokenExchange(idToken: string, accessToken = "api-access-token") {
  const fetchMock = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
    const body = init?.body as URLSearchParams;
    expect(body.get("grant_type")).toBe("authorization_code");
    expect(body.get("client_id")).toBe(CONFIG.clientId);
    expect(body.get("code")).toBe("code-1");
    expect(body.get("redirect_uri")).toBe(CONFIG.redirectUri);
    expect(body.get("code_verifier")).toBe("verifier-1");
    expect(body.get("audience")).toBe(CONFIG.audience);
    return new Response(JSON.stringify({ access_token: accessToken, id_token: idToken }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  sessionStorage.clear();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("OIDC callback validation", () => {
  it("exchanges an authorization code and accepts a matching state and nonce", async () => {
    setPending();
    const idToken = token({
      sub: "alice",
      email: "alice@example.gov",
      iss: CONFIG.issuerUrl,
      aud: CONFIG.clientId,
      nonce: "nonce-1",
      exp: Math.floor(Date.now() / 1000) + 60,
    });
    const fetchMock = mockTokenExchange(idToken);

    const auth = await completeOidcLogin(
      "https://portal.example.gov/oidc/callback?code=code-1&state=state-1",
      CONFIG,
    );

    expect(fetchMock).toHaveBeenCalledWith(CONFIG.tokenEndpoint, expect.any(Object));
    expect(auth).toEqual({
      type: "bearer",
      value: "api-access-token",
      label: "alice@example.gov",
    });
    expect(sessionStorage.getItem("sovereign-oidc-pending")).toBeNull();
  });

  it("rejects a state mismatch before exchanging the code", async () => {
    setPending();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      completeOidcLogin(
        "https://portal.example.gov/oidc/callback?code=code-1&state=wrong",
        CONFIG,
      ),
    ).rejects.toThrow(/state mismatch/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects a nonce mismatch", async () => {
    setPending();
    const idToken = token({
      sub: "alice",
      iss: CONFIG.issuerUrl,
      aud: CONFIG.clientId,
      nonce: "wrong",
    });
    mockTokenExchange(idToken);

    await expect(
      completeOidcLogin(
        "https://portal.example.gov/oidc/callback?code=code-1&state=state-1",
        CONFIG,
      ),
    ).rejects.toThrow(/nonce mismatch/i);
  });

  it("rejects expired tokens", async () => {
    setPending();
    const idToken = token({
      sub: "alice",
      iss: CONFIG.issuerUrl,
      aud: CONFIG.clientId,
      nonce: "nonce-1",
      exp: Math.floor(Date.now() / 1000) - 1,
    });
    mockTokenExchange(idToken);

    await expect(
      completeOidcLogin(
        "https://portal.example.gov/oidc/callback?code=code-1&state=state-1",
        CONFIG,
      ),
    ).rejects.toThrow(/expired/i);
  });

  it("rejects issuer and audience mismatches", async () => {
    setPending();
    mockTokenExchange(
      token({
        sub: "alice",
        iss: "https://evil.example.gov",
        aud: CONFIG.clientId,
        nonce: "nonce-1",
      }),
    );

    await expect(
      completeOidcLogin(
        "https://portal.example.gov/oidc/callback?code=code-1&state=state-1",
        CONFIG,
      ),
    ).rejects.toThrow(/issuer mismatch/i);

    setPending();
    mockTokenExchange(
      token({
        sub: "alice",
        iss: CONFIG.issuerUrl,
        aud: "wrong-client",
        nonce: "nonce-1",
      }),
    );

    await expect(
      completeOidcLogin(
        "https://portal.example.gov/oidc/callback?code=code-1&state=state-1",
        CONFIG,
      ),
    ).rejects.toThrow(/audience mismatch/i);
  });

  it("reports OIDC as available only when issuer and client are configured", () => {
    expect(oidcAvailable()).toBe(false);

    vi.stubEnv("VITE_OIDC_ISSUER_URL", "https://idp.example.gov");
    vi.stubEnv("VITE_OIDC_CLIENT_ID", "sovereign-portal");

    expect(oidcAvailable()).toBe(true);
  });
});
