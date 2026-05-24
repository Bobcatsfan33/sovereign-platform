// Thin fetch wrapper. Resolves URLs against VITE_BROKER_URL (build-time)
// with a fallback to same-origin so the dev proxy works.
//
// Auth is attached from sessionStorage on every call. The Auth context
// owns the storage; the client just reads.

import type { ProblemDetail } from "../types/api";

export class ApiError extends Error {
  readonly status: number;
  readonly problem: ProblemDetail | null;

  constructor(status: number, message: string, problem: ProblemDetail | null) {
    super(message);
    this.status = status;
    this.problem = problem;
  }
}

function baseUrl(prefix: string): string {
  const env = import.meta.env;
  if (prefix === "audit") {
    return (env.VITE_AUDIT_URL as string | undefined) || "/audit";
  }
  return (env.VITE_BROKER_URL as string | undefined) || "";
}

function authHeader(): Record<string, string> {
  const raw = sessionStorage.getItem("sovereign-auth");
  if (!raw) return {};
  try {
    const cred = JSON.parse(raw) as { type: "bearer" | "basic"; value: string };
    if (cred.type === "bearer") return { Authorization: `Bearer ${cred.value}` };
    if (cred.type === "basic") return { Authorization: `Basic ${cred.value}` };
  } catch {
    /* fall through */
  }
  return {};
}

export interface RequestOptions extends Omit<RequestInit, "body" | "headers"> {
  json?: unknown;
  // For endpoints served by the audit service. Defaults to broker.
  service?: "broker" | "audit";
  query?: Record<string, string | number | boolean | undefined>;
  headers?: Record<string, string>;
}

export async function apiFetch<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const prefix = baseUrl(options.service ?? "broker");
  let url = `${prefix}${path}`;
  if (options.query) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(options.query)) {
      if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
    }
    const str = qs.toString();
    if (str) url += `?${str}`;
  }

  const init: RequestInit = {
    ...options,
    headers: {
      Accept: "application/json",
      ...(options.json !== undefined ? { "Content-Type": "application/json" } : {}),
      ...authHeader(),
      ...options.headers,
    },
    body: options.json !== undefined ? JSON.stringify(options.json) : undefined,
  };

  const response = await fetch(url, init);
  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }

  if (!response.ok) {
    const problem =
      body && typeof body === "object" && "title" in body
        ? (body as ProblemDetail)
        : null;
    const message = problem?.title
      ? `${problem.title}${typeof problem.detail === "string" ? `: ${problem.detail}` : ""}`
      : `HTTP ${response.status}`;
    throw new ApiError(response.status, message, problem);
  }

  return body as T;
}
