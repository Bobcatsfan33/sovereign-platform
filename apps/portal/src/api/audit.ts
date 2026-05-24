import type { AuditEventsPage } from "../types/api";
import { apiFetch } from "./client";

export interface AuditQuery {
  tenant_id?: string;
  actor?: string;
  action?: string;
  resource?: string;
  decision?: "allow" | "deny";
  since?: string;
  until?: string;
  limit?: number;
}

export function fetchAuditEvents(q: AuditQuery = {}): Promise<AuditEventsPage> {
  return apiFetch<AuditEventsPage>("/events", {
    service: "audit",
    query: { ...q },
  });
}
