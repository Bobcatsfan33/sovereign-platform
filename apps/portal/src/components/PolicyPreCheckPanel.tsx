import type { PolicyDecision } from "../types/api";

export default function PolicyPreCheckPanel({
  decision,
  loading,
  error,
}: {
  decision: PolicyDecision | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="rounded border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600"
      >
        Running policy check…
      </div>
    );
  }
  if (error) {
    return (
      <div
        role="alert"
        className="rounded border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800"
      >
        Policy check failed: {error}
      </div>
    );
  }
  if (!decision) {
    return (
      <p className="text-sm text-slate-500">
        The policy engine will evaluate your request before you submit it.
      </p>
    );
  }

  if (decision.allow) {
    return (
      <div
        role="status"
        className="rounded border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900"
      >
        <p className="font-semibold">Policy pre-check passed.</p>
        <p className="mt-1">
          The chassis policy engine ({decision.matched_layers.length ? decision.matched_layers.join(", ") : "no layers triggered"})
          will allow this request when you submit.
        </p>
      </div>
    );
  }

  return (
    <div
      role="alert"
      className="rounded border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900"
    >
      <p className="font-semibold">Policy pre-check failed — the request would be rejected.</p>
      {decision.matched_layers.length > 0 && (
        <p className="mt-1">
          Matched layers: <span className="font-mono">{decision.matched_layers.join(", ")}</span>
        </p>
      )}
      <ul className="mt-2 list-disc space-y-1 pl-5">
        {decision.denies.map((d, i) => (
          <li key={i}>{d}</li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-rose-700">
        Adjust the parameters above and re-run the check.
      </p>
    </div>
  );
}
