import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { fetchAuditEvents } from "../api/audit";
import type { AuditEvent } from "../types/api";

export default function Compliance() {
  const [tenantId, setTenantId] = useState<string>("");
  const [decision, setDecision] = useState<"" | "allow" | "deny">("");
  const [actionFilter, setActionFilter] = useState<string>("");

  const { data, isLoading, error, refetch, isRefetching } = useQuery({
    queryKey: ["audit", tenantId, decision, actionFilter],
    queryFn: () =>
      fetchAuditEvents({
        tenant_id: tenantId || undefined,
        decision: decision || undefined,
        action: actionFilter || undefined,
        limit: 200,
      }),
  });

  const events = useMemo(() => data?.events ?? [], [data]);
  const stats = useMemo(() => summarise(events), [events]);

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-3xl font-bold">Compliance</h1>
        <p className="mt-1 text-slate-600">
          Continuous compliance audit trail. Every policy evaluation and every
          lifecycle event lands here within seconds.
        </p>
      </header>

      <section aria-labelledby="posture" className="grid gap-4 sm:grid-cols-3">
        <h2 id="posture" className="sr-only">Posture summary</h2>
        <Stat label="Total events" value={stats.total} />
        <Stat label="Policy decisions" value={stats.policyTotal} />
        <Stat
          label="Compliance pass rate"
          value={stats.policyTotal === 0 ? "—" : `${stats.passRate}%`}
          tone={stats.passRate >= 99 ? "good" : stats.passRate >= 90 ? "warn" : "bad"}
        />
      </section>

      <section aria-labelledby="violations">
        <h2 id="violations" className="text-xl font-semibold">Recent policy violations</h2>
        {stats.violations.length === 0 ? (
          <p className="mt-2 text-sm text-slate-500">No policy denies in this window. </p>
        ) : (
          <ul className="mt-2 space-y-2">
            {stats.violations.slice(0, 10).map((v, i) => (
              <li key={i} className="rounded border border-rose-200 bg-rose-50 p-3 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono">{v.resource}</span>
                  <time className="text-xs text-rose-700">{new Date(v.ts).toLocaleString()}</time>
                </div>
                <p className="mt-1 text-rose-900">
                  {(v.metadata?.denies as string[] | undefined)?.join("; ") ?? "(no denies recorded)"}
                </p>
                <p className="mt-1 text-xs text-rose-700">
                  Actor: <span className="font-mono">{v.actor}</span> ·
                  Tenant: <span className="font-mono">{v.tenant_id}</span>
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="audit">
        <h2 id="audit" className="text-xl font-semibold">Audit log</h2>
        <fieldset className="mt-2 flex flex-wrap items-end gap-3 text-sm">
          <legend className="sr-only">Audit log filters</legend>
          <label>
            Tenant
            <input
              type="text"
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              placeholder="any"
              className="ml-2 rounded border border-slate-300 px-2 py-1 font-mono"
            />
          </label>
          <label>
            Decision
            <select
              value={decision}
              onChange={(e) => setDecision(e.target.value as "" | "allow" | "deny")}
              className="ml-2 rounded border border-slate-300 px-2 py-1"
            >
              <option value="">any</option>
              <option value="allow">allow</option>
              <option value="deny">deny</option>
            </select>
          </label>
          <label>
            Action
            <input
              type="text"
              value={actionFilter}
              onChange={(e) => setActionFilter(e.target.value)}
              placeholder="any"
              className="ml-2 rounded border border-slate-300 px-2 py-1 font-mono"
            />
          </label>
          <button
            type="button"
            onClick={() => refetch()}
            className="rounded border border-slate-300 px-3 py-1"
          >
            {isRefetching ? "Loading…" : "Apply"}
          </button>
        </fieldset>

        {error && (
          <div role="alert" className="mt-3 rounded border border-rose-200 bg-rose-50 p-3 text-sm">
            Failed to load audit events: {(error as Error).message}
          </div>
        )}

        <div className="mt-3 overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <caption className="sr-only">Audit events</caption>
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2">When</th>
                <th className="px-3 py-2">Tenant</th>
                <th className="px-3 py-2">Actor</th>
                <th className="px-3 py-2">Action</th>
                <th className="px-3 py-2">Resource</th>
                <th className="px-3 py-2">Decision</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {isLoading && (
                <tr><td colSpan={6} className="px-3 py-4 text-center text-slate-500">Loading…</td></tr>
              )}
              {!isLoading && events.length === 0 && (
                <tr><td colSpan={6} className="px-3 py-4 text-center text-slate-500">No events.</td></tr>
              )}
              {events.map((e, i) => (
                <tr key={i}>
                  <td className="px-3 py-2 text-xs">{new Date(e.ts).toLocaleString()}</td>
                  <td className="px-3 py-2 font-mono text-xs">{e.tenant_id}</td>
                  <td className="px-3 py-2 font-mono text-xs">{e.actor}</td>
                  <td className="px-3 py-2 font-mono text-xs">{e.action}</td>
                  <td className="px-3 py-2 font-mono text-xs">{e.resource}</td>
                  <td className="px-3 py-2">
                    <DecisionPill decision={e.decision} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string | number; tone?: "good" | "warn" | "bad" }) {
  const ring = tone === "good"
    ? "border-emerald-200 bg-emerald-50"
    : tone === "warn"
    ? "border-amber-200 bg-amber-50"
    : tone === "bad"
    ? "border-rose-200 bg-rose-50"
    : "border-slate-200 bg-white";
  return (
    <div className={`rounded-lg border p-4 ${ring}`}>
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-slate-900">{value}</div>
    </div>
  );
}

function DecisionPill({ decision }: { decision: string }) {
  const cls = decision === "allow"
    ? "bg-emerald-100 text-emerald-800"
    : decision === "deny"
    ? "bg-rose-100 text-rose-800"
    : "bg-slate-100 text-slate-700";
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {decision}
    </span>
  );
}

interface PolicyAuditMeta {
  denies?: string[];
  matched_layers?: string[];
  service_type?: string;
}

function summarise(events: AuditEvent[]) {
  const policyEvents = events.filter((e) => e.action === "policy.evaluated");
  const total = events.length;
  const policyTotal = policyEvents.length;
  const allows = policyEvents.filter((e) => e.decision === "allow").length;
  const passRate = policyTotal === 0 ? 100 : Math.round((allows / policyTotal) * 100);
  const violations = policyEvents.filter((e) => e.decision === "deny");
  return { total, policyTotal, passRate, violations: violations as (AuditEvent & { metadata?: PolicyAuditMeta })[] };
}
