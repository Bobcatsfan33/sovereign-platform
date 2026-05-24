// Renders the NIST controls a service auto-satisfies. The catalog card
// shows up to N badges; overflow rolls into a "+ M more" badge that
// shows the full list on hover (and also via aria-describedby).

import { useId } from "react";

export default function ComplianceBadge({ controls, max = 4 }: { controls: string[]; max?: number }) {
  const overflowId = useId();
  if (!controls.length) {
    return <span className="text-xs text-slate-500">No control mapping published</span>;
  }
  const visible = controls.slice(0, max);
  const hidden = controls.slice(max);
  return (
    <div className="flex flex-wrap gap-1">
      {visible.map((c) => (
        <span
          key={c}
          className="rounded bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-800 border border-emerald-200"
        >
          {c}
        </span>
      ))}
      {hidden.length > 0 && (
        <>
          <span
            className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-700 border border-slate-200"
            aria-describedby={overflowId}
          >
            +{hidden.length} more
          </span>
          <span id={overflowId} className="sr-only">
            Additional controls: {hidden.join(", ")}
          </span>
        </>
      )}
    </div>
  );
}
