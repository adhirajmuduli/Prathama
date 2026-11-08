"use client";

/**
 * The export panel for a succeeded run: create the checksum-verified
 * reproducibility bundle, poll the export job, and offer the verified
 * download with the manifest summary.
 */

import { useMemo, useState } from "react";

import { StatusBanner } from "../status-banner";
import {
  createExport,
  exportDownloadUrl,
  getExport,
} from "../../lib/api/exports";
import { pollJobUntilTerminal } from "../../lib/api/analyses";
import { createApiClient } from "../../lib/api/client";
import { ApiError } from "../../lib/api/errors";
import { publicApiBaseUrl } from "../../lib/env/client";
import type { ExportResponse } from "../../lib/contracts/exports";
import type { Job } from "../../lib/contracts/analyses";
import { formatBytes, formatTimestamp } from "../../lib/format";

export interface ExportPanelProps {
  readonly runId: string;
}

export function ExportPanel({ runId }: ExportPanelProps) {
  const client = useMemo(
    () =>
      publicApiBaseUrl === null
        ? null
        : createApiClient({ baseUrl: publicApiBaseUrl }),
    [],
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [exportInfo, setExportInfo] = useState<ExportResponse | null>(null);

  if (client === null) {
    return null;
  }

  const startExport = async () => {
    setBusy(true);
    setError(null);
    setExportInfo(null);
    try {
      const created = await createExport(client, runId);
      const finishedJob = await pollJobUntilTerminal(
        client,
        created.job_id,
        setJob,
        {
          timeoutMs: 10 * 60_000,
        },
      );
      if (finishedJob.status !== "succeeded") {
        throw new Error("The export job failed.");
      }
      setExportInfo(await getExport(client, created.export_id));
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : caught instanceof Error
            ? caught.message
            : "The request failed.",
      );
    } finally {
      setBusy(false);
    }
  };

  const manifest = exportInfo?.manifest ?? {};
  const recipeHash =
    typeof manifest["recipe_hash"] === "string"
      ? manifest["recipe_hash"]
      : null;
  const datasetSha =
    typeof manifest["dataset_sha256"] === "string"
      ? manifest["dataset_sha256"]
      : null;

  return (
    <div className="space-y-2 rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-sm font-semibold">Reproducibility export</p>
        <button
          type="button"
          onClick={() => void startExport()}
          disabled={busy}
          className="rounded-lg border border-slate-300 bg-white px-3 py-1 text-xs font-semibold text-slate-800 transition hover:bg-slate-50 disabled:opacity-60"
        >
          {busy ? "Exporting…" : "Export bundle"}
        </button>
        {exportInfo !== null ? (
          <a
            href={exportDownloadUrl(client, exportInfo.export_id)}
            className="rounded border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            Download ZIP ({formatBytes(exportInfo.artifact.size_bytes)})
          </a>
        ) : null}
      </div>
      {error !== null ? (
        <StatusBanner
          tone="danger"
          title="The export failed"
          description={error}
        />
      ) : null}
      {job !== null ? (
        <p className="text-xs text-slate-500">
          Export job {job.status} — {(job.progress * 100).toFixed(0)}%
        </p>
      ) : null}
      {exportInfo !== null ? (
        <p className="text-xs text-slate-500">
          {exportInfo.export_id} · {exportInfo.status} · bundle{" "}
          {exportInfo.artifact.sha256.slice(0, 12)}… · run{" "}
          {exportInfo.run_id.slice(0, 12)}…
          {recipeHash !== null ? ` · recipe ${recipeHash.slice(0, 12)}…` : ""}
          {datasetSha !== null ? ` · dataset ${datasetSha.slice(0, 12)}…` : ""}
          {typeof manifest["generated_at"] === "string"
            ? ` · generated ${formatTimestamp(manifest["generated_at"])}`
            : ""}
          {" — verify locally with `trendsmapp reproduce <bundle.zip>`"}
        </p>
      ) : null}
    </div>
  );
}
