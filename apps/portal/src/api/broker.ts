import type {
  CatalogResponse,
  PolicyCheckRequest,
  PolicyDecision,
  ProvisionRequestBody,
  ServiceInstance,
} from "../types/api";
import { apiFetch } from "./client";

export function fetchCatalog(): Promise<CatalogResponse> {
  return apiFetch<CatalogResponse>("/v2/catalog");
}

export interface InstancesResponse {
  instances: ServiceInstance[];
}

export function fetchInstances(tenantId?: string): Promise<InstancesResponse> {
  return apiFetch<InstancesResponse>("/v2/instances", {
    query: { tenant_id: tenantId },
  });
}

export interface ProvisionResponse {
  dashboard_url?: string;
  operation: string;
  config?: unknown;
}

export function provision(
  instanceId: string,
  body: ProvisionRequestBody,
): Promise<ProvisionResponse> {
  return apiFetch<ProvisionResponse>(`/v2/service_instances/${encodeURIComponent(instanceId)}`, {
    method: "PUT",
    json: body,
  });
}

export function deprovision(instanceId: string): Promise<unknown> {
  return apiFetch(`/v2/service_instances/${encodeURIComponent(instanceId)}`, {
    method: "DELETE",
  });
}

export function bind(instanceId: string, bindingId: string): Promise<unknown> {
  return apiFetch(
    `/v2/service_instances/${encodeURIComponent(instanceId)}/service_bindings/${encodeURIComponent(bindingId)}`,
    { method: "PUT", json: {} },
  );
}

export function unbind(instanceId: string, bindingId: string): Promise<unknown> {
  return apiFetch(
    `/v2/service_instances/${encodeURIComponent(instanceId)}/service_bindings/${encodeURIComponent(bindingId)}`,
    { method: "DELETE" },
  );
}

export function policyCheck(req: PolicyCheckRequest): Promise<PolicyDecision> {
  return apiFetch<PolicyDecision>("/v2/policy/check", {
    method: "POST",
    json: req,
  });
}
