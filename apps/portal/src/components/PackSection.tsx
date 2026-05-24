import type { PackSummary, ServiceType } from "../types/api";
import ServiceCard from "./ServiceCard";

export default function PackSection({
  pack,
  services,
}: {
  pack: PackSummary;
  services: ServiceType[];
}) {
  return (
    <section
      className="rounded-lg border border-slate-200 bg-slate-50 p-4"
      aria-labelledby={`pack-${pack.id}`}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 id={`pack-${pack.id}`} className="text-xl font-semibold text-slate-900">
            {pack.icon && <span aria-hidden className="mr-2">{pack.icon}</span>}
            {pack.name}
          </h2>
          {pack.description && (
            <p className="mt-1 text-sm text-slate-600">{pack.description}</p>
          )}
        </div>
        {pack.installed ? (
          <span className="rounded bg-emerald-100 px-2 py-1 text-xs font-medium text-emerald-800">
            Installed
          </span>
        ) : (
          <span className="rounded bg-amber-100 px-2 py-1 text-xs font-medium text-amber-800">
            Available — Contact Admin
          </span>
        )}
      </div>

      {pack.installed ? (
        services.length > 0 ? (
          <ul className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {services.map((s) => (
              <li key={s.id}>
                <ServiceCard service={s} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-4 text-sm italic text-slate-500">
            No service types registered yet for this pack.
          </p>
        )
      ) : (
        <p className="mt-4 text-sm italic text-slate-600">
          This service pack is not yet installed in your environment. Contact
          your platform admin to request it.
        </p>
      )}
    </section>
  );
}
