"use client";

/**
 * The version explorer: pick a dataset version and inspect its preview, its
 * parse / normalization / QC reports, its provenance, and its artifacts.
 */

import { useMemo, useState } from "react";

import { createApiClient } from "../../lib/api/client";
import { publicApiBaseUrl } from "../../lib/env/client";
import {
  previewSchema,
  provenanceListSchema,
  type DatasetVersion,
} from "../../lib/contracts/ingest";
import { formatBytes, formatTimestamp } from "../../lib/format";

type Tab = "preview" | "parse" | "normalization" | "qc" | "provenance" | "artifacts";

const TABS: { id: Tab; label: string }[] = [
  { id: "preview", label: "Preview" },
  { id: "parse", label: "Parse report" },
  { id: "normalization", label: "Normalization" },
  { id: "qc", label: "Quality control" },
  { id: "provenance", label: "Provenance" },
  { id: "artifacts", label: "Artifacts" },
];

export interface VersionExplorerProps {
  readonly versions: readonly DatasetVersion[];
}

export function VersionExplorer({ versions }: VersionExplorerProps) {
  const [selectedId, setSelectedId] = useState<string | null>(
    versions.length > 0 ? (versions[versions.length - 1]?.version_id ?? null) : null,
  );
  const [tab, setTab] = useState<Tab>("preview");
  const client = useMemo(
    () => (publicApiBaseUrl === null ? null : createApiClient({ baseUrl: publicApiBaseUrl })),
    [],
  );
  const [preview, setPreview] = useState<unknown>(null);
  const [report, setReport] = useState<unknown>(null);
  const [provenance, setProvenance] = useState<unknown>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const selected = versions.find((version) => version.version_id === selectedId) ?? null;

  const loadTab = async (nextTab: Tab, versionId: string) => {
    setTab(nextTab);
    setLoadError(null);
    setPreview(null);
    setReport(null);
    setProvenance(null);
    if (client === null) {
      setLoadError("The public API origin is not configured.");
      return;
    }
    try {
      if (nextTab === "preview") {
        setPreview(
          await client.getJson(
            `/api/v1/dataset-versions/${versionId}/preview?limit=100`,
            previewSchema,
          ),
        );
      } else if (nextTab === "provenance") {
        setProvenance(
          await client.getJson(
            `/api/v1/dataset-versions/${versionId}/provenance`,
            provenanceListSchema,
          ),
        );
      } else if (nextTab !== "artifacts") {
        setReport(
          await client.getJson(
            `/api/v1/dataset-versions/${versionId}/reports/${nextTab}`,
            // Reports are free-form JSON documents; validate only that it is an object.
            reportDocumentSchema,
          ),
        );
      }
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "The tab could not be loaded.");
    }
  };

  if (versions.length === 0) {
    return (
      <p className="text-sm text-slate-600">
        This dataset has no versions yet. Its ingest job may still be running.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-sm">
          <span className="mr-2 font-medium text-slate-700">Version</span>
          <select
            className="rounded border border-slate-300 px-2 py-1"
            value={selectedId ?? ""}
            onChange={(event) => {
              setSelectedId(event.target.value);
              void loadTab(tab, event.target.value);
            }}
          >
            {versions.map((version) => (
              <option key={version.version_id} value={version.version_id}>
                v{version.version_number} {version.sealed ? "(sealed)" : "(unsealed)"} —{" "}
                {version.row_count} rows
              </option>
            ))}
          </select>
        </label>
        {selected !== null ? (
          <p className="text-xs text-slate-500">
            {selected.station_count} stations · {selected.parameter_count} parameters ·{" "}
            {selected.boundary_id ?? "no boundary"}
            {selected.first_sampled_at !== null && selected.first_sampled_at !== undefined
              ? ` · ${formatTimestamp(selected.first_sampled_at)} → ${formatTimestamp(selected.last_sampled_at ?? selected.first_sampled_at)}`
              : ""}
          </p>
        ) : null}
      </div>

      <div className="flex flex-wrap gap-2" role="tablist">
        {TABS.map((item) => (
          <button
            key={item.id}
            role="tab"
            aria-selected={tab === item.id}
            onClick={() => {
              if (selectedId !== null) {
                void loadTab(item.id, selectedId);
              }
            }}
            className={`rounded-lg border px-3 py-1 text-sm ${
              tab === item.id
                ? "border-sky-600 bg-sky-50 text-sky-900"
                : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      {loadError !== null ? (
        <p role="alert" className="rounded border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-900">
          {loadError}
        </p>
      ) : null}

      {tab === "preview" && preview !== null ? <PreviewTable data={preview} /> : null}
      {tab !== "preview" && tab !== "provenance" && tab !== "artifacts" && report !== null ? (
        <ReportView data={report} />
      ) : null}
      {tab === "provenance" && provenance !== null ? <ProvenanceView data={provenance} /> : null}
      {tab === "artifacts" && selected !== null ? <ArtifactList version={selected} /> : null}
    </div>
  );
}

import { z } from "zod";

const reportDocumentSchema = z.record(z.string(), z.unknown());

function PreviewTable({ data }: { readonly data: unknown }) {
  const parsed = previewSchema.parse(data);
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <p className="border-b border-slate-200 px-3 py-2 text-xs text-slate-500">
        Showing {parsed.rows.length} of {parsed.row_count} rows · artifact{" "}
        {parsed.artifact_sha256.slice(0, 16)}…
      </p>
      <table className="w-full text-xs">
        <thead className="bg-slate-50 text-left font-medium text-slate-600">
          <tr>
            {parsed.columns.map((column) => (
              <th key={column} className="whitespace-nowrap px-3 py-2">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {parsed.rows.map((row, rowIndex) => (
            <tr key={rowIndex} className="border-t border-slate-100">
              {row.map((cell, cellIndex) => (
                <td key={cellIndex} className="whitespace-nowrap px-3 py-1 font-mono text-slate-700">
                  {cell === null ? "∅" : String(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReportView({ data }: { readonly data: unknown }) {
  return (
    <pre className="max-h-[32rem] overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-800">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

function ProvenanceView({ data }: { readonly data: unknown }) {
  const parsed = provenanceListSchema.parse(data);
  if (parsed.items.length === 0) {
    return <p className="text-sm text-slate-600">No provenance events recorded for this version.</p>;
  }
  return (
    <ul className="space-y-2">
      {parsed.items.map((item) => (
        <li key={item.provenance_id} className="rounded-lg border border-slate-200 bg-white p-3 text-sm">
          <p className="font-semibold">{item.event_type}</p>
          <p className="text-xs text-slate-500">{formatTimestamp(item.occurred_at)}</p>
          <p className="mt-1 font-mono text-xs text-slate-600">
            inputs: {item.parent_artifact_ids.length} · steps: {item.transformations.join(" → ")}
          </p>
        </li>
      ))}
    </ul>
  );
}

function ArtifactList({ version }: { readonly version: DatasetVersion }) {
  return (
    <ul className="space-y-2">
      {version.artifacts.map((artifact) => (
        <li
          key={artifact.artifact_id}
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white p-3 text-sm"
        >
          <div>
            <p className="font-semibold text-slate-900">{artifact.kind}</p>
            <p className="font-mono text-xs text-slate-500">
              {artifact.sha256.slice(0, 16)}… · {formatBytes(artifact.size_bytes)} ·{" "}
              {formatTimestamp(artifact.created_at)}
            </p>
          </div>
          <a
            href={`${publicApiBaseUrl ?? ""}/api/v1/artifacts/${artifact.artifact_id}/content`}
            className="rounded border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            Download
          </a>
        </li>
      ))}
    </ul>
  );
}
