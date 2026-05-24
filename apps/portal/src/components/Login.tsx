import { type FormEvent, useId, useState } from "react";

import { useAuth } from "../hooks/useAuth";

const DEV_TOKEN = (import.meta.env.VITE_DEV_BEARER_TOKEN as string | undefined) ?? "dev-token";

export default function Login() {
  const { login } = useAuth();
  const [mode, setMode] = useState<"bearer" | "basic">("bearer");
  const [bearer, setBearer] = useState("");
  const [user, setUser] = useState("");
  const [pass, setPass] = useState("");
  const bearerId = useId();
  const userId = useId();
  const passId = useId();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (mode === "bearer") {
      const value = bearer.trim();
      if (!value) return;
      login({ type: "bearer", value, label: "bearer auth" });
    } else {
      const value = btoa(`${user}:${pass}`);
      login({ type: "basic", value, label: user || "basic auth" });
    }
  };

  const useDev = () => login({ type: "bearer", value: DEV_TOKEN, label: "dev token" });

  return (
    <div className="mx-auto mt-12 max-w-md rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <h1 className="text-2xl font-semibold">Sign in</h1>
      <p className="mt-1 text-sm text-slate-600">
        Use a bearer token from your agency IdP, or sign in with OSB basic
        credentials. In local development, click <em>Use dev token</em> below.
      </p>

      <div role="tablist" aria-label="Auth method" className="mt-4 flex gap-2">
        <button
          role="tab"
          aria-selected={mode === "bearer"}
          type="button"
          onClick={() => setMode("bearer")}
          className={`rounded px-3 py-1 text-sm ${mode === "bearer" ? "bg-slate-900 text-white" : "bg-slate-200"}`}
        >
          Bearer token
        </button>
        <button
          role="tab"
          aria-selected={mode === "basic"}
          type="button"
          onClick={() => setMode("basic")}
          className={`rounded px-3 py-1 text-sm ${mode === "basic" ? "bg-slate-900 text-white" : "bg-slate-200"}`}
        >
          OSB basic
        </button>
      </div>

      <form onSubmit={submit} className="mt-4 space-y-3">
        {mode === "bearer" ? (
          <div>
            <label htmlFor={bearerId} className="block text-sm font-medium">
              Token
            </label>
            <input
              id={bearerId}
              type="password"
              autoComplete="off"
              value={bearer}
              onChange={(e) => setBearer(e.target.value)}
              required
              className="mt-1 w-full rounded border border-slate-300 px-3 py-2 font-mono text-sm focus:outline-2 focus:outline-blue-500"
            />
          </div>
        ) : (
          <>
            <div>
              <label htmlFor={userId} className="block text-sm font-medium">
                Username
              </label>
              <input
                id={userId}
                value={user}
                onChange={(e) => setUser(e.target.value)}
                required
                autoComplete="username"
                className="mt-1 w-full rounded border border-slate-300 px-3 py-2 focus:outline-2 focus:outline-blue-500"
              />
            </div>
            <div>
              <label htmlFor={passId} className="block text-sm font-medium">
                Password
              </label>
              <input
                id={passId}
                type="password"
                value={pass}
                onChange={(e) => setPass(e.target.value)}
                required
                autoComplete="current-password"
                className="mt-1 w-full rounded border border-slate-300 px-3 py-2 focus:outline-2 focus:outline-blue-500"
              />
            </div>
          </>
        )}

        <button
          type="submit"
          className="w-full rounded bg-blue-700 px-4 py-2 text-white hover:bg-blue-800 focus:outline-2 focus:outline-amber-300"
        >
          Sign in
        </button>
      </form>

      <button
        type="button"
        onClick={useDev}
        className="mt-3 w-full rounded border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 focus:outline-2 focus:outline-amber-300"
      >
        Use dev token (local docker-compose)
      </button>
    </div>
  );
}
