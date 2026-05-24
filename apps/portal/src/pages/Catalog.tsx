import { useQuery } from "@tanstack/react-query";

import { fetchCatalog } from "../api/broker";
import PackSection from "../components/PackSection";
import type { PackSummary, ServiceType } from "../types/api";

export default function Catalog() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["catalog"],
    queryFn: fetchCatalog,
  });

  if (isLoading) return <p>Loading catalog…</p>;
  if (error) {
    return (
      <div role="alert" className="rounded border border-rose-200 bg-rose-50 p-4">
        Failed to load catalog: {(error as Error).message}
      </div>
    );
  }
  if (!data) return null;

  const services = data.services ?? [];
  const packs = data.packs ?? derivePacks(services);

  return (
    <div>
      <header className="mb-6">
        <h1 className="text-3xl font-bold text-slate-900">Service catalog</h1>
        <p className="mt-1 text-slate-600">
          Browse compliance-checked, self-service infrastructure. Every plan
          inherits the base chassis NIST and GovCloud baseline.
        </p>
      </header>
      <div className="space-y-6">
        {packs.map((pack) => (
          <PackSection
            key={pack.id}
            pack={pack}
            services={services.filter((s) => s.pack === pack.id)}
          />
        ))}
      </div>
    </div>
  );
}

// If the broker doesn't ship pack metadata, derive packs from the
// services' `pack` field. The chassis Phase 1 pack-registration system
// supplies the richer shape — this is the fallback.
function derivePacks(services: ServiceType[]): PackSummary[] {
  const seen = new Map<string, PackSummary>();
  for (const s of services) {
    const id = s.pack ?? "chassis";
    if (!seen.has(id)) {
      seen.set(id, {
        id,
        name: id === "chassis" ? "Base chassis" : id,
        installed: true,
      });
    }
  }
  return Array.from(seen.values());
}
