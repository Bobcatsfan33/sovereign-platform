import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { deprovision, fetchInstances } from "../api/broker";
import StatusPill from "../components/StatusPill";
import type { ServiceInstance } from "../types/api";

export default function Instances() {
  const [tenantId, setTenantId] = useState<string>("");
  const qc = useQueryClient();
  const { data, isLoading, error, refetch, isRefetching } = useQuery({
    queryKey: ["instances", tenantId],
    queryFn: () => fetchInstances(tenantId || undefined),
    refetchInterval: 10_000,
  });

  const delMut = useMutation({
    mutationFn: (id: string) => deprovision(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["instances"] }),
  });

  if (isLoading) return <p>Loading instances…</p>;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">Instances</h1>
          <p className="mt-1 text-slate-600">
            Provisioned resources visible to your tenant scope. Auto-refresh every 10s.
          </p>
        </div>
        <label className="text-sm">
          Filter by tenant
          <input
            type="text"
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            placeholder="all"
            className="ml-2 rounded border border-slate-300 px-2 py-1 font-mono text-sm"
          />
        </label>
      </header>

      {error && (
        <div role="alert" className="rounded border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">
          Failed to load instances: {(error as Error).message}
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <caption className="sr-only">Provisioned service instances</caption>
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-2">Instance ID</th>
              <th className="px-4 py-2">Service</th>
              <th className="px-4 py-2">Plan</th>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2">Tenant</th>
              <th className="px-4 py-2">Created</th>
              <th className="px-4 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {(data?.instances ?? []).map((i) => (
              <Row key={i.instance_id} inst={i} onDelete={() => delMut.mutate(i.instance_id)} />
            ))}
            {(!data || data.instances.length === 0) && (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-slate-500">
                  No instances. <Link className="text-blue-700 underline" to="/">Browse catalog</Link>.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="text-right text-xs text-slate-500">
        <button type="button" onClick={() => refetch()} className="underline">
          Refresh now
        </button>
        {isRefetching && <span className="ml-2">(refreshing…)</span>}
      </div>
    </div>
  );
}

function Row({ inst, onDelete }: { inst: ServiceInstance; onDelete: () => void }) {
  return (
    <tr>
      <td className="px-4 py-2 font-mono">{inst.instance_id}</td>
      <td className="px-4 py-2">{inst.service_id}</td>
      <td className="px-4 py-2">{inst.plan_id}</td>
      <td className="px-4 py-2"><StatusPill status={inst.status} /></td>
      <td className="px-4 py-2 font-mono text-xs">{inst.organization_guid ?? "—"}</td>
      <td className="px-4 py-2 text-slate-600">{new Date(inst.created_at).toLocaleString()}</td>
      <td className="px-4 py-2 text-right">
        <button
          type="button"
          onClick={onDelete}
          aria-label={`Deprovision ${inst.instance_id}`}
          className="rounded border border-rose-300 px-2 py-1 text-xs text-rose-700 hover:bg-rose-50"
        >
          Deprovision
        </button>
      </td>
    </tr>
  );
}
