import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { fetchCatalog, policyCheck, provision } from "../api/broker";
import ParamForm from "../components/ParamForm";
import PolicyPreCheckPanel from "../components/PolicyPreCheckPanel";
import type { PolicyDecision, ServiceType } from "../types/api";

type Step = "plan" | "params" | "policy" | "review";

export default function ProvisionWizard() {
  const { serviceId = "" } = useParams();
  const navigate = useNavigate();

  const { data: catalog, isLoading } = useQuery({
    queryKey: ["catalog"],
    queryFn: fetchCatalog,
  });

  const service = useMemo<ServiceType | undefined>(
    () => catalog?.services.find((s) => s.id === serviceId),
    [catalog, serviceId],
  );

  const [step, setStep] = useState<Step>("plan");
  const [planId, setPlanId] = useState<string>("");
  const [instanceId, setInstanceId] = useState<string>(`demo-${Date.now().toString(36)}`);
  const [tenantId, setTenantId] = useState<string>("default");
  const [parameters, setParameters] = useState<Record<string, unknown>>({});
  const [policy, setPolicy] = useState<PolicyDecision | null>(null);
  const [policyError, setPolicyError] = useState<string | null>(null);

  const checkMut = useMutation({
    mutationFn: async () => {
      setPolicyError(null);
      const dec = await policyCheck({
        service_id: serviceId,
        plan_id: planId,
        tenant_id: tenantId,
        parameters,
      });
      setPolicy(dec);
      return dec;
    },
    onError: (e: Error) => setPolicyError(e.message),
  });

  const provisionMut = useMutation({
    mutationFn: () =>
      provision(instanceId, {
        service_id: serviceId,
        plan_id: planId,
        organization_guid: tenantId,
        parameters,
      }),
    onSuccess: () => navigate("/instances"),
  });

  if (isLoading) return <p>Loading service…</p>;
  if (!service) {
    return (
      <div role="alert" className="rounded border border-rose-200 bg-rose-50 p-4">
        Unknown service <code>{serviceId}</code>. <a className="underline" href="/">Back to catalog</a>.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold">Provision {service.name}</h1>
        <p className="mt-1 text-slate-600">{service.description}</p>
      </header>

      <ol aria-label="Wizard progress" className="flex flex-wrap gap-2 text-sm">
        {(["plan", "params", "policy", "review"] as Step[]).map((s, i) => (
          <li
            key={s}
            aria-current={step === s ? "step" : undefined}
            className={`rounded-full border px-3 py-1 ${
              step === s
                ? "border-blue-500 bg-blue-50 font-semibold text-blue-900"
                : "border-slate-300 text-slate-700"
            }`}
          >
            {i + 1}. {labelFor(s)}
          </li>
        ))}
      </ol>

      {step === "plan" && (
        <section aria-labelledby="step-plan" className="space-y-4">
          <h2 id="step-plan" className="text-xl font-semibold">1. Choose a plan</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {service.plans.map((p) => (
              <label
                key={p.id}
                className={`block cursor-pointer rounded border p-4 ${
                  planId === p.id ? "border-blue-500 bg-blue-50" : "border-slate-200 bg-white"
                }`}
              >
                <input
                  type="radio"
                  name="plan"
                  value={p.id}
                  className="sr-only"
                  checked={planId === p.id}
                  onChange={() => setPlanId(p.id)}
                />
                <div className="font-semibold">{p.name}</div>
                {p.description && (
                  <p className="mt-1 text-sm text-slate-600">{p.description}</p>
                )}
              </label>
            ))}
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-sm font-medium">
              Instance ID
              <input
                type="text"
                value={instanceId}
                onChange={(e) => setInstanceId(e.target.value)}
                pattern="[a-zA-Z0-9_\-]+"
                className="mt-1 w-full rounded border border-slate-300 px-3 py-2 font-mono"
              />
            </label>
            <label className="block text-sm font-medium">
              Tenant ID
              <input
                type="text"
                value={tenantId}
                onChange={(e) => setTenantId(e.target.value)}
                pattern="[a-zA-Z0-9_\-]+"
                className="mt-1 w-full rounded border border-slate-300 px-3 py-2 font-mono"
              />
            </label>
          </div>

          <div className="flex justify-end">
            <button
              type="button"
              disabled={!planId || !instanceId || !tenantId}
              onClick={() => setStep("params")}
              className="rounded bg-blue-700 px-4 py-2 text-white disabled:opacity-50"
            >
              Next: parameters
            </button>
          </div>
        </section>
      )}

      {step === "params" && (
        <section aria-labelledby="step-params" className="space-y-4">
          <h2 id="step-params" className="text-xl font-semibold">2. Set parameters</h2>
          {service.parameter_schema ? (
            <ParamForm
              schema={service.parameter_schema}
              values={parameters}
              onChange={setParameters}
            />
          ) : (
            <div>
              <p className="text-sm text-slate-600">
                This service has no published parameter schema. Provide raw
                JSON parameters.
              </p>
              <textarea
                aria-label="Raw JSON parameters"
                rows={10}
                value={JSON.stringify(parameters, null, 2)}
                onChange={(e) => {
                  try {
                    setParameters(JSON.parse(e.target.value));
                  } catch {
                    /* ignore until valid */
                  }
                }}
                className="mt-2 w-full rounded border border-slate-300 p-3 font-mono text-sm"
              />
            </div>
          )}
          <div className="flex justify-between">
            <button type="button" onClick={() => setStep("plan")} className="rounded border border-slate-300 px-4 py-2">
              Back
            </button>
            <button type="button" onClick={() => setStep("policy")} className="rounded bg-blue-700 px-4 py-2 text-white">
              Next: policy pre-check
            </button>
          </div>
        </section>
      )}

      {step === "policy" && (
        <section aria-labelledby="step-policy" className="space-y-4">
          <h2 id="step-policy" className="text-xl font-semibold">3. Policy pre-check</h2>
          <p className="text-sm text-slate-600">
            The chassis policy engine evaluates your request against the base
            NIST + GovCloud bundle and any pack/tenant policies. Running this
            now lets you fix issues before you commit.
          </p>
          <button
            type="button"
            onClick={() => checkMut.mutate()}
            disabled={checkMut.isPending}
            className="rounded bg-slate-900 px-4 py-2 text-white disabled:opacity-50"
          >
            {checkMut.isPending ? "Checking…" : "Run policy check"}
          </button>
          <PolicyPreCheckPanel
            decision={policy}
            loading={checkMut.isPending}
            error={policyError}
          />
          <div className="flex justify-between">
            <button type="button" onClick={() => setStep("params")} className="rounded border border-slate-300 px-4 py-2">
              Back
            </button>
            <button
              type="button"
              onClick={() => setStep("review")}
              disabled={!policy || !policy.allow}
              className="rounded bg-blue-700 px-4 py-2 text-white disabled:opacity-50"
            >
              Next: review
            </button>
          </div>
        </section>
      )}

      {step === "review" && (
        <section aria-labelledby="step-review" className="space-y-4">
          <h2 id="step-review" className="text-xl font-semibold">4. Review and submit</h2>
          <dl className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
            <dt className="text-slate-500">Service</dt>
            <dd className="font-medium">{service.name}</dd>
            <dt className="text-slate-500">Plan</dt>
            <dd className="font-medium">{planId}</dd>
            <dt className="text-slate-500">Instance ID</dt>
            <dd className="font-mono">{instanceId}</dd>
            <dt className="text-slate-500">Tenant</dt>
            <dd className="font-mono">{tenantId}</dd>
          </dl>
          <details>
            <summary className="cursor-pointer text-sm font-medium">Parameters</summary>
            <pre className="mt-2 overflow-auto rounded bg-slate-100 p-3 text-xs">
{JSON.stringify(parameters, null, 2)}
            </pre>
          </details>
          {provisionMut.isError && (
            <div role="alert" className="rounded border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900">
              Provision failed: {(provisionMut.error as Error).message}
            </div>
          )}
          <div className="flex justify-between">
            <button type="button" onClick={() => setStep("policy")} className="rounded border border-slate-300 px-4 py-2">
              Back
            </button>
            <button
              type="button"
              onClick={() => provisionMut.mutate()}
              disabled={provisionMut.isPending}
              className="rounded bg-emerald-700 px-4 py-2 text-white disabled:opacity-50"
            >
              {provisionMut.isPending ? "Provisioning…" : "Provision"}
            </button>
          </div>
        </section>
      )}
    </div>
  );
}

function labelFor(s: Step): string {
  return { plan: "Plan", params: "Parameters", policy: "Policy", review: "Review" }[s];
}
