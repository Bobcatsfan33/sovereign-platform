// TypeScript shapes mirroring the Pydantic models the chassis ships.
// These are hand-typed (not generated) so the broker can evolve faster
// than the portal; CI catches accidental drift via Vitest contract tests.

export type InstanceStatus =
  | "provisioning"
  | "succeeded"
  | "failed"
  | "deprovisioning";

export interface ServicePlan {
  id: string;
  name: string;
  description?: string;
  // Optional t-shirt-size resource specs (Phase 4 task 4.2 cards).
  cpu?: string;
  memory?: string;
  storage?: string;
  // Free-form metadata (e.g. {price_per_hour: 0.12, region: "us-gov-*"}).
  metadata?: Record<string, unknown>;
}

export interface ServiceType {
  id: string;
  name: string;
  description: string;
  pack: string;
  bindable: boolean;
  plans: ServicePlan[];
  // NIST controls auto-satisfied by every instance of this service —
  // surfaces the compliance posture badge on the catalog card.
  compliance_controls?: string[];
  // JSON-schema for the provisioning wizard. When absent, the wizard
  // renders a freeform JSON textarea fallback.
  parameter_schema?: ParameterSchema;
}

export interface CatalogResponse {
  services: ServiceType[];
  // Packs present in the catalog; may include uninstalled packs marked
  // as installed=false so the UI can show "Available — Contact Admin".
  packs?: PackSummary[];
}

export interface PackSummary {
  id: string;
  name: string;
  description?: string;
  icon?: string;
  installed: boolean;
  // Service IDs belonging to this pack.
  services?: string[];
}

export interface ParameterSchema {
  // JSON-Schema-lite shape — the portal renders these forms natively
  // rather than via a heavyweight rjsf-style library.
  title?: string;
  description?: string;
  type: "object";
  properties: Record<string, ParameterField>;
  required?: string[];
}

export type ParameterField =
  | { type: "string"; title?: string; description?: string; enum?: string[]; default?: string; format?: string }
  | { type: "number" | "integer"; title?: string; description?: string; minimum?: number; maximum?: number; default?: number }
  | { type: "boolean"; title?: string; description?: string; default?: boolean }
  | { type: "array"; title?: string; description?: string; items: ParameterField };

export interface ServiceInstance {
  instance_id: string;
  service_id: string;
  plan_id: string;
  organization_guid?: string | null;
  space_guid?: string | null;
  status: InstanceStatus;
  version: number;
  created_at: string;
  updated_at: string;
  parameters: Record<string, unknown>;
  pack?: string;
}

export interface Binding {
  binding_id: string;
  instance_id: string;
  app_guid?: string | null;
  credentials: Record<string, string>;
  created_at: string;
}

export interface ProvisionRequestBody {
  service_id: string;
  plan_id: string;
  organization_guid?: string;
  space_guid?: string;
  parameters: Record<string, unknown>;
}

export interface PolicyCheckRequest {
  service_id: string;
  plan_id: string;
  tenant_id: string;
  parameters: Record<string, unknown>;
}

export interface PolicyDecision {
  allow: boolean;
  reason?: string;
  denies: string[];
  matched_layers: string[];
  obligations?: string[];
}

export interface AuditEvent {
  ts: string;
  tenant_id: string;
  actor: string;
  action: string;
  resource: string;
  decision: string;
  metadata?: Record<string, unknown>;
}

export interface AuditEventsPage {
  events: AuditEvent[];
  count: number;
}

export interface ProblemDetail {
  type?: string;
  title: string;
  status: number;
  // Detail may be a plain string OR a structured object (the broker
  // returns the latter for policy rejections with denies + matched_layers).
  detail: string | Record<string, unknown>;
  service?: string;
  errors?: unknown;
}
