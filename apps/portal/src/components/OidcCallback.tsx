import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { completeOidcLogin } from "../auth/oidc";
import type { StoredAuth } from "../hooks/useAuth";

export default function OidcCallback({
  onAuthenticated,
}: {
  onAuthenticated: (cred: StoredAuth) => void;
}) {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void completeOidcLogin()
      .then((auth) => {
        onAuthenticated(auth);
        navigate("/", { replace: true });
      })
      .catch((exc: unknown) => {
        setError(exc instanceof Error ? exc.message : "OIDC login failed");
      });
  }, [navigate, onAuthenticated]);

  if (error) {
    return (
      <main className="mx-auto mt-12 max-w-md rounded-lg border border-red-200 bg-white p-6 shadow-sm">
        <h1 className="text-xl font-semibold text-red-800">Sign in failed</h1>
        <p className="mt-2 text-sm text-red-700">{error}</p>
      </main>
    );
  }

  return (
    <main className="mx-auto mt-12 max-w-md rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <h1 className="text-xl font-semibold">Completing sign in</h1>
    </main>
  );
}
