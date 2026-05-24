// JSON-Schema-lite form renderer. Built in-house to avoid a heavy
// rjsf dependency — the chassis only needs string/number/boolean/enum/
// array(of-string) for Phase 4 service types.

import { useId } from "react";

import type { ParameterField, ParameterSchema } from "../types/api";

interface Props {
  schema: ParameterSchema;
  values: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  errors?: Record<string, string>;
}

export default function ParamForm({ schema, values, onChange, errors = {} }: Props) {
  return (
    <fieldset className="space-y-4">
      <legend className="text-base font-semibold">{schema.title ?? "Parameters"}</legend>
      {schema.description && (
        <p className="text-sm text-slate-600">{schema.description}</p>
      )}
      {Object.entries(schema.properties).map(([key, field]) => (
        <Field
          key={key}
          name={key}
          field={field}
          value={values[key]}
          required={(schema.required ?? []).includes(key)}
          error={errors[key]}
          onChange={(v) => onChange({ ...values, [key]: v })}
        />
      ))}
    </fieldset>
  );
}

function Field({
  name,
  field,
  value,
  required,
  error,
  onChange,
}: {
  name: string;
  field: ParameterField;
  value: unknown;
  required: boolean;
  error?: string;
  onChange: (v: unknown) => void;
}) {
  const id = useId();
  const errId = useId();
  const label = field.title ?? name;
  const ariaDescribedBy = [field.description ? `${id}-desc` : "", error ? errId : ""]
    .filter(Boolean)
    .join(" ");

  let control: React.ReactNode = null;
  switch (field.type) {
    case "string": {
      if (field.enum) {
        control = (
          <select
            id={id}
            required={required}
            value={(value as string) ?? field.default ?? ""}
            onChange={(e) => onChange(e.target.value)}
            aria-describedby={ariaDescribedBy || undefined}
            aria-invalid={!!error}
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2 focus:outline-2 focus:outline-blue-500"
          >
            <option value="">— select —</option>
            {field.enum.map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
        );
      } else {
        control = (
          <input
            id={id}
            type="text"
            required={required}
            value={(value as string) ?? field.default ?? ""}
            onChange={(e) => onChange(e.target.value)}
            aria-describedby={ariaDescribedBy || undefined}
            aria-invalid={!!error}
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2 focus:outline-2 focus:outline-blue-500"
          />
        );
      }
      break;
    }
    case "number":
    case "integer": {
      control = (
        <input
          id={id}
          type="number"
          required={required}
          min={field.minimum}
          max={field.maximum}
          step={field.type === "integer" ? 1 : "any"}
          value={(value as number | undefined) ?? field.default ?? ""}
          onChange={(e) =>
            onChange(e.target.value === "" ? undefined : Number(e.target.value))
          }
          aria-describedby={ariaDescribedBy || undefined}
          aria-invalid={!!error}
          className="mt-1 w-full rounded border border-slate-300 px-3 py-2 focus:outline-2 focus:outline-blue-500"
        />
      );
      break;
    }
    case "boolean": {
      control = (
        <input
          id={id}
          type="checkbox"
          checked={(value as boolean) ?? field.default ?? false}
          onChange={(e) => onChange(e.target.checked)}
          aria-describedby={ariaDescribedBy || undefined}
          className="mt-2 h-4 w-4 rounded border-slate-300 text-blue-700 focus:outline-2 focus:outline-blue-500"
        />
      );
      break;
    }
    case "array": {
      const arr = (value as unknown[]) ?? [];
      control = (
        <div className="space-y-2">
          {arr.map((entry, idx) => (
            <div key={idx} className="flex gap-2">
              <input
                aria-label={`${label} item ${idx + 1}`}
                type="text"
                value={String(entry ?? "")}
                onChange={(e) => {
                  const next = [...arr];
                  next[idx] = e.target.value;
                  onChange(next);
                }}
                className="flex-1 rounded border border-slate-300 px-3 py-2 focus:outline-2 focus:outline-blue-500"
              />
              <button
                type="button"
                onClick={() => onChange(arr.filter((_, i) => i !== idx))}
                className="rounded border border-slate-300 px-3 text-sm hover:bg-slate-50"
              >
                Remove
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={() => onChange([...arr, ""])}
            className="rounded border border-dashed border-slate-300 px-3 py-1 text-sm text-slate-600 hover:border-slate-400"
          >
            + Add {label} item
          </button>
        </div>
      );
      break;
    }
  }

  return (
    <div>
      {field.type === "boolean" ? (
        <label htmlFor={id} className="flex items-center gap-2 text-sm font-medium">
          {control}
          <span>{label}{required && " *"}</span>
        </label>
      ) : (
        <label htmlFor={id} className="block text-sm font-medium">
          {label}{required && " *"}
        </label>
      )}
      {field.description && (
        <p id={`${id}-desc`} className="mt-0.5 text-xs text-slate-500">
          {field.description}
        </p>
      )}
      {field.type !== "boolean" && control}
      {error && (
        <p id={errId} role="alert" className="mt-1 text-xs text-rose-600">
          {error}
        </p>
      )}
    </div>
  );
}
