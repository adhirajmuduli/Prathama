"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { StatusBanner } from "./status-banner";
import { createApiClient } from "../lib/api/client";
import { readApiStatus, type ApiStatus } from "../lib/api/status";
import { formatBytes, formatTimestamp } from "../lib/format";

export interface ApiStatusPanelProps {
  readonly initialStatus: ApiStatus;
  readonly publicApiBaseUrl: string | null;
}

export function ApiStatusPanel({
  initialStatus,
  publicApiBaseUrl,
}: ApiStatusPanelProps) {
  const client = useMemo(
    () =>
      publicApiBaseUrl === null
        ? null
        : createApiClient({ baseUrl: publicApiBaseUrl }),
    [publicApiBaseUrl],
  );

  const query = useQuery({
    queryKey: ["api-status"],
    queryFn: async () => {
      if (client === null) {
        throw new Error("The public API origin is not configured.");
      }
      return readApiStatus(client);
    },
    enabled: client !== null,
    refetchInterval: 30_000,
    staleTime: 15_000,
  });

  const status = query.data ?? initialStatus;
  const capabilities = status.capabilities;

  return (
    <section
      aria-labelledby="service-status-heading"
      className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="service-status-heading" className="text-lg font-semibold">
          Service status
        </h2>
        <p className="text-xs text-slate-500">
          {client === null
            ? "Rendered by the server at request time"
            : `Refreshed by the browser every 30 s${
                query.dataUpdatedAt === 0
                  ? ""
                  : `, last update ${formatTimestamp(new Date(query.dataUpdatedAt).toISOString())}`
              }`}
        </p>
      </div>

      {status.live === null ? (
        <div className="mt-4">
          <StatusBanner
            tone="danger"
            title="The backend is not answering"
            description={
              status.problem ??
              "The liveness probe did not return a response. The service may be starting, restarting, or unreachable from this deployment."
            }
          />
        </div>
      ) : (
        <div className="mt-4 space-y-4">
          <dl className="grid gap-3 sm:grid-cols-2">
            <Row label="Liveness" value={status.live.status} />
            <Row
              label="Readiness"
              value={
                status.ready === null
                  ? "not reported"
                  : `${status.ready.status} (database: ${status.ready.components.database}, object store: ${status.ready.components.object_store})`
              }
            />
            <Row
              label="Application version"
              value={status.versions?.application_version ?? "not reported"}
            />
            <Row
              label="API major version"
              value={
                status.versions === null
                  ? "not reported"
                  : `${status.versions.api_major} (supported: ${status.versions.supported_api_majors.join(", ")})`
              }
            />
            <Row
              label="Artifact schema version"
              value={status.versions?.artifact_schema_version ?? "not reported"}
            />
            <Row
              label="Recipe schema version"
              value={status.versions?.recipe_schema_version ?? "not reported"}
            />
          </dl>

          {capabilities === null ? null : (
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
              <h3 className="text-sm font-semibold text-slate-900">
                Implemented capabilities
              </h3>
              <p className="mt-1 text-xs text-slate-600">
                The backend publishes only the code paths that exist and are
                exercised by tests. An empty list means the capability is not
                implemented yet.
              </p>
              <ul className="mt-3 space-y-1 text-sm text-slate-700">
                <CapabilityLine
                  label="File formats"
                  values={capabilities.file_formats}
                />
                <CapabilityLine
                  label="Spatial methods"
                  values={capabilities.spatial_methods}
                />
                <CapabilityLine
                  label="Temporal methods"
                  values={capabilities.temporal_methods}
                />
                <CapabilityLine
                  label="Model families"
                  values={capabilities.model_families}
                />
              </ul>
              <p className="mt-3 text-xs text-slate-600">
                Analysis CRS: {capabilities.configuration.analysis_crs}. Upload
                ceiling: {formatBytes(capabilities.limits.upload_max_bytes)}.
              </p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function Row({
  label,
  value,
}: {
  readonly label: string;
  readonly value: string;
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </dt>
      <dd className="mt-1 text-sm font-medium text-slate-900">{value}</dd>
    </div>
  );
}

function CapabilityLine({
  label,
  values,
}: {
  readonly label: string;
  readonly values: readonly string[];
}) {
  return (
    <li>
      <span className="font-medium text-slate-900">{label}: </span>
      {values.length === 0 ? (
        <span className="text-slate-600">not implemented in this build</span>
      ) : (
        <span className="text-slate-700">{values.join(", ")}</span>
      )}
    </li>
  );
}
