import { Link } from "react-router-dom";

import type { ServiceType } from "../types/api";
import ComplianceBadge from "./ComplianceBadge";

export default function ServiceCard({ service }: { service: ServiceType }) {
  return (
    <article className="flex flex-col rounded-lg border border-slate-200 bg-white p-4 shadow-sm focus-within:ring-2 focus-within:ring-blue-500">
      <header>
        <h3 className="text-lg font-semibold text-slate-900">{service.name}</h3>
        <p className="mt-1 text-sm text-slate-600">{service.description}</p>
      </header>

      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <dt className="text-slate-500">Plans</dt>
        <dd className="text-slate-900">
          {service.plans.map((p) => p.name).join(" · ") || "—"}
        </dd>
        <dt className="text-slate-500">Bindable</dt>
        <dd className="text-slate-900">{service.bindable ? "Yes" : "No"}</dd>
      </dl>

      <div className="mt-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Compliance — auto-satisfied
        </p>
        <div className="mt-1">
          <ComplianceBadge controls={service.compliance_controls ?? []} />
        </div>
      </div>

      <div className="mt-auto pt-4">
        <Link
          to={`/provision/${encodeURIComponent(service.id)}`}
          className="inline-flex items-center justify-center rounded bg-blue-700 px-4 py-2 text-sm font-medium text-white hover:bg-blue-800 focus:outline-2 focus:outline-amber-300"
        >
          Provision {service.name}
        </Link>
      </div>
    </article>
  );
}
