"use client";

/**
 * The mapping editor.
 *
 * The probe proposes a mapping; the analyst confirms or corrects every role
 * before anything is sent. The form is a controlled editor over the proposed
 * document: each column gets a role select, and the table-level settings
 * (layout, wide axis, default parameter and unit, CRS, date order, timezone,
 * duplicate policy) are editable. Submitting produces a validated
 * ColumnMapping document.
 */

import { useMemo, useState } from "react";

import {
  columnMappingSchema,
  type ColumnMapping,
  type ColumnRole,
  type Probe,
} from "../../lib/contracts/ingest";

const ROLE_LABELS: Record<ColumnRole, string> = {
  station: "Station",
  latitude: "Latitude (WGS84)",
  longitude: "Longitude (WGS84)",
  easting: "Easting (projected)",
  northing: "Northing (projected)",
  timestamp: "Timestamp",
  parameter: "Parameter",
  value: "Value",
  unit: "Unit",
  qualifier: "Qualifier",
  depth: "Depth",
  sector: "Sector",
  ignored: "Ignored",
};

const ROLE_VALUES = Object.keys(ROLE_LABELS) as ColumnRole[];

export interface MappingFormProps {
  readonly probe: Probe;
  readonly onSubmit: (mapping: ColumnMapping) => void;
  readonly submitting?: boolean;
  readonly error?: string | null;
}

export function MappingForm({
  probe,
  onSubmit,
  submitting,
  error,
}: MappingFormProps) {
  const [mapping, setMapping] = useState<ColumnMapping>(probe.proposed_mapping);
  const [validationError, setValidationError] = useState<string | null>(null);

  const wide = mapping.layout === "wide";
  const columns = useMemo(() => mapping.columns, [mapping]);

  const setRole = (column: string, role: ColumnRole) => {
    setMapping((current) => ({
      ...current,
      columns: current.columns.map((item) =>
        item.column === column ? { ...item, role } : item,
      ),
    }));
  };

  const setWideValue = (
    field:
      | "wide_axis"
      | "default_parameter"
      | "default_unit"
      | "source_crs"
      | "date_order"
      | "timezone_policy"
      | "duplicate_policy",
    value: string,
  ) => {
    setMapping((current) => ({
      ...current,
      [field]: value === "" ? null : value,
    }));
  };

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const parsed = columnMappingSchema.safeParse(mapping);
    if (!parsed.success) {
      setValidationError(
        parsed.error.issues[0]?.message ?? "The mapping is incomplete.",
      );
      return;
    }
    setValidationError(null);
    onSubmit(parsed.data);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-sm">
          <span className="font-medium text-slate-700">Layout</span>
          <select
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
            value={mapping.layout}
            onChange={(event) =>
              setMapping((current) => ({
                ...current,
                layout: event.target.value === "wide" ? "wide" : "long",
              }))
            }
          >
            <option value="long">Long (one observation per row)</option>
            <option value="wide">
              Wide (columns are stations or parameters)
            </option>
          </select>
        </label>
        {wide ? (
          <label className="block text-sm">
            <span className="font-medium text-slate-700">Wide axis</span>
            <select
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
              value={mapping.wide_axis ?? "stations"}
              onChange={(event) =>
                setWideValue("wide_axis", event.target.value)
              }
            >
              <option value="stations">Columns are stations</option>
              <option value="parameters">Columns are parameters</option>
            </select>
          </label>
        ) : null}
        <label className="block text-sm">
          <span className="font-medium text-slate-700">
            Default parameter (when no column carries it)
          </span>
          <input
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
            value={mapping.default_parameter ?? ""}
            onChange={(event) =>
              setWideValue("default_parameter", event.target.value)
            }
            placeholder="e.g. dissolved_oxygen"
          />
        </label>
        <label className="block text-sm">
          <span className="font-medium text-slate-700">
            Default unit (when no column carries it)
          </span>
          <input
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
            value={mapping.default_unit ?? ""}
            onChange={(event) =>
              setWideValue("default_unit", event.target.value)
            }
            placeholder="e.g. mg/L"
          />
        </label>
        <label className="block text-sm">
          <span className="font-medium text-slate-700">
            Source CRS (for projected columns)
          </span>
          <input
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
            value={mapping.source_crs ?? ""}
            onChange={(event) => setWideValue("source_crs", event.target.value)}
            placeholder="e.g. EPSG:32644"
          />
        </label>
        <label className="block text-sm">
          <span className="font-medium text-slate-700">
            Date order in numeric dates
          </span>
          <select
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
            value={mapping.date_order}
            onChange={(event) => setWideValue("date_order", event.target.value)}
          >
            <option value="day_first">Day first (03/04/2024 = 3 April)</option>
            <option value="month_first">
              Month first (03/04/2024 = March 4)
            </option>
            <option value="year_first">Year first</option>
          </select>
        </label>
        <label className="block text-sm">
          <span className="font-medium text-slate-700">Timezone policy</span>
          <select
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
            value={mapping.timezone_policy}
            onChange={(event) =>
              setWideValue("timezone_policy", event.target.value)
            }
          >
            <option value="assume_utc">Assume UTC when no offset</option>
            <option value="require_offset">Require an explicit offset</option>
            <option value="named">Named timezone</option>
          </select>
        </label>
        <label className="block text-sm">
          <span className="font-medium text-slate-700">Duplicate policy</span>
          <select
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
            value={mapping.duplicate_policy}
            onChange={(event) =>
              setWideValue("duplicate_policy", event.target.value)
            }
          >
            <option value="flag_all">Flag duplicates, keep first</option>
            <option value="keep_first">Keep first</option>
            <option value="keep_last">Keep last</option>
            <option value="keep_most_complete">Keep most complete</option>
            <option value="error">Fail on duplicates</option>
          </select>
        </label>
      </div>

      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-2">Column</th>
              <th className="px-3 py-2">Role</th>
            </tr>
          </thead>
          <tbody>
            {columns.map((item) => (
              <tr key={item.column} className="border-t border-slate-100">
                <td className="px-3 py-2 font-mono text-xs">{item.column}</td>
                <td className="px-3 py-2">
                  <select
                    aria-label={`Role for ${item.column}`}
                    className="rounded border border-slate-300 px-2 py-1"
                    value={item.role}
                    onChange={(event) =>
                      setRole(item.column, event.target.value as ColumnRole)
                    }
                  >
                    {ROLE_VALUES.map((role) => (
                      <option key={role} value={role}>
                        {ROLE_LABELS[role]}
                      </option>
                    ))}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {validationError !== null || error !== null ? (
        <p
          role="alert"
          className="rounded border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-900"
        >
          {validationError ?? error}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={submitting === true}
        className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:opacity-60"
      >
        {submitting === true
          ? "Creating dataset…"
          : "Confirm mapping and create dataset"}
      </button>
    </form>
  );
}
