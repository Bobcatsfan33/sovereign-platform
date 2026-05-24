import { useCallback, useEffect, useState } from "react";

export type AuthKind = "bearer" | "basic";

export interface StoredAuth {
  type: AuthKind;
  value: string; // bearer token, or base64(user:pass) for basic
  label: string; // display name in the navbar
}

const STORAGE_KEY = "sovereign-auth";

function read(): StoredAuth | null {
  const raw = sessionStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as StoredAuth;
  } catch {
    return null;
  }
}

export function useAuth(): {
  auth: StoredAuth | null;
  login: (cred: StoredAuth) => void;
  logout: () => void;
} {
  const [auth, setAuth] = useState<StoredAuth | null>(read());

  // Sync across tabs in the same browser session (StorageEvent fires
  // only on OTHER tabs — but it costs nothing to subscribe).
  useEffect(() => {
    const handler = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) setAuth(read());
    };
    window.addEventListener("storage", handler);
    return () => window.removeEventListener("storage", handler);
  }, []);

  const login = useCallback((cred: StoredAuth) => {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(cred));
    setAuth(cred);
  }, []);

  const logout = useCallback(() => {
    sessionStorage.removeItem(STORAGE_KEY);
    setAuth(null);
  }, []);

  return { auth, login, logout };
}
