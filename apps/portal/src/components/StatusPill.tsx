import type { InstanceStatus } from "../types/api";

const STATUS_COLOR: Record<InstanceStatus, string> = {
  provisioning: "bg-amber-100 text-amber-800 border-amber-200",
  succeeded: "bg-emerald-100 text-emerald-800 border-emerald-200",
  failed: "bg-rose-100 text-rose-800 border-rose-200",
  deprovisioning: "bg-slate-100 text-slate-700 border-slate-200",
};

const STATUS_LABEL: Record<InstanceStatus, string> = {
  provisioning: "Provisioning",
  succeeded: "Running",
  failed: "Failed",
  deprovisioning: "Deprovisioning",
};

export default function StatusPill({ status }: { status: InstanceStatus }) {
  const cls = STATUS_COLOR[status] ?? "bg-slate-100 text-slate-700";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${cls}`}
      aria-label={`Status: ${STATUS_LABEL[status] ?? status}`}
    >
      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-current" />
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}
