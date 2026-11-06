"use client";

/**
 * The analysis panel on a dataset version: a recipe form, a run poller, and
 * the results of the finished run — per-frame metrics, raster previews with
 * extent metadata, and the animation player.
 */

import { useMemo, useState } from "react";
import type { z } from "zod";

import { StatusBanner } from "../status-banner";
import {
  createAnalysis,
  createAnimation,
  getAnalysisResults,
  getRun,
  listRunArtifacts,
  pollJobUntilTerminal,
} from "../../lib/api/analyses";
import { createApiClient } from "../../lib/api/client";
import { ApiError } from "../../lib/api/errors";
import { publicApiBaseUrl } from "../../lib/env/client";
import {
  recipeSchema,
  type AnalysisResults,
  type Job,
  type Recipe,
  type Run,
} from "../../lib/contracts/analyses";
import type { spatialMethodSchema } from "../../lib/contracts/analyses";
import type { ArtifactRef } from "../../lib/contracts/ingest";
import { formatBytes, formatTimestamp } from "../../lib/format";

const METHODS = [
  { value: "idw", label: "IDW (baseline)" },
  { value: "rbf", label: "RBF" },
  { value: "kriging", label: "Kriging" },
  { value: "gaussian_process", label: "Gaussian process" },
] as const;

export interface AnalysisPanelProps {
  readonly datasetVersionId: string;
}

export function AnalysisPanel({ datasetVersionId }: AnalysisPanelProps) {
  const client = useMemo(
    () => (publicApiBaseUrl === null ? null : createApiClient({ baseUrl: publicApiBaseUrl })),
    [],
  );
  const [selectedMethods, setSelectedMethods] = useState<
    z.infer<typeof spatialMethodSchema>[]
  >(["idw"]);
  const [resolution, setResolution] = useState("5000");
  const [validation, setValidation] = useState<Recipe["spatial"]["validation"]>("leave_one_station_out");
  const [selectionRule, setSelectionRule] = useState<Recipe["spatial"]["selection_rule"]>("best_rmse");
  const [computeTemporal, setComputeTemporal] = useState(true);
  const [fps, setFps] = useState(2);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [results, setResults] = useState<AnalysisResults | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactRef[]>([]);
  const [videoArtifactId, setVideoArtifactId] = useState<string | null>(null);

  if (client === null) {
    return (
      <StatusBanner
        tone="warning"
        title="Analysis is not available"
        description="The public API origin is not configured, so no analysis can be started from the browser."
      />
    );
  }

  const toggleMethod = (method: z.infer<typeof spatialMethodSchema>) => {
    setSelectedMethods((current) =>
      current.includes(method)
        ? current.filter((item) => item !== method)
        : [...current, method],
    );
  };

  const startAnalysis = async () => {
    setBusy("analysis");
    setError(null);
    setResults(null);
    setArtifacts([]);
    setVideoArtifactId(null);
    try {
      const recipe = recipeSchema.parse({
        schema_version: "1.0.0",
        dataset_version_id: datasetVersionId,
        seed: 7,
        spatial: {
          methods: selectedMethods.map((method) => ({ method, params: {} })),
          grid_resolution_m: Number(resolution),
          max_grid_cells: 250_000,
          analysis_crs: "EPSG:32644",
          validation,
          selection_rule: selectionRule,
          permitted_qc_statuses: ["pass", "warning"],
        },
        temporal: computeTemporal
          ? {
              resolution: "day" as const,
              interpolation: "linear" as const,
              max_gap_days: 30,
              allow_extrapolation: false,
              frame_count: 0,
              compute_trends: true,
              compute_change_points: false,
            }
          : null,
      } satisfies Recipe);
      const created = await createAnalysis(client, recipe);
      const finishedJob = await pollJobUntilTerminal(client, created.job_id, setJob, {
        timeoutMs: 10 * 60_000,
      });
      if (finishedJob.status !== "succeeded") {
        throw new Error(
          finishedJob.error !== null && finishedJob.error !== undefined
            ? `${finishedJob.error.code}: ${finishedJob.error.message}`
            : "The analysis job failed.",
        );
      }
      const [runResponse, resultsResponse, artifactList] = await Promise.all([
        getRun(client, created.run_id),
        getAnalysisResults(client, created.run_id),
        listRunArtifacts(client, created.run_id),
      ]);
      setRun(runResponse);
      setResults(resultsResponse);
      setArtifacts(artifactList);
      const video = artifactList.find((item) => item.kind === "video");
      if (video !== undefined) {
        setVideoArtifactId(video.artifact_id);
      }
    } catch (caught) {
      setError(describeError(caught));
    } finally {
      setBusy(null);
    }
  };

  const startAnimation = async () => {
    if (run === null) {
      return;
    }
    setBusy("animation");
    setError(null);
    try {
      const created = await createAnimation(client, run.run_id, {
        parameter_id: results?.frames[0]?.parameter_id ?? null,
        method: results?.frames[0]?.methods[0]?.method ?? null,
        palette: "viridis",
        fps,
      });
      const finishedJob = await pollJobUntilTerminal(client, created.job_id, setJob, {
        timeoutMs: 10 * 60_000,
      });
      if (finishedJob.status !== "succeeded") {
        throw new Error("The animation job failed.");
      }
      const artifactList = await listRunArtifacts(client, run.run_id);
      setArtifacts(artifactList);
      const video = artifactList.find((item) => item.kind === "video");
      if (video !== undefined) {
        setVideoArtifactId(video.artifact_id);
      }
    } catch (caught) {
      setError(describeError(caught));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <fieldset>
          <legend className="text-sm font-medium text-slate-700">Spatial methods</legend>
          {METHODS.map((method) => (
            <label key={method.value} className="mt-1 flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={selectedMethods.includes(method.value)}
                onChange={() => toggleMethod(method.value)}
              />
              {method.label}
            </label>
          ))}
        </fieldset>
        <label className="block text-sm">
          <span className="font-medium text-slate-700">Grid resolution (m per cell)</span>
          <input
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
            value={resolution}
            onChange={(event) => setResolution(event.target.value)}
            inputMode="numeric"
          />
        </label>
        <label className="block text-sm">
          <span className="font-medium text-slate-700">Validation</span>
          <select
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
            value={validation}
            onChange={(event) =>
              setValidation(event.target.value as Recipe["spatial"]["validation"])
            }
          >
            <option value="leave_one_station_out">Leave one station out</option>
            <option value="spatial_block">Spatial blocks</option>
            <option value="none">None</option>
          </select>
        </label>
        <label className="block text-sm">
          <span className="font-medium text-slate-700">Selection rule</span>
          <select
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
            value={selectionRule}
            onChange={(event) =>
              setSelectionRule(event.target.value as Recipe["spatial"]["selection_rule"])
            }
          >
            <option value="best_rmse">Best RMSE (recorded)</option>
            <option value="none">None</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={computeTemporal}
            onChange={(event) => setComputeTemporal(event.target.checked)}
          />
          <span className="font-medium text-slate-700">Also compute temporal series</span>
        </label>
        <label className="block text-sm">
          <span className="font-medium text-slate-700">Animation fps</span>
          <input
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
            value={fps}
            onChange={(event) => setFps(Number(event.target.value))}
            inputMode="numeric"
          />
        </label>
      </div>

      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={() => void startAnalysis()}
          disabled={busy !== null || selectedMethods.length === 0}
          className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:opacity-60"
        >
          {busy === "analysis" ? "Analyzing…" : "Run analysis"}
        </button>
        {run !== null ? (
          <button
            type="button"
            onClick={() => void startAnimation()}
            disabled={busy !== null}
            className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-800 transition hover:bg-slate-50 disabled:opacity-60"
          >
            {busy === "animation" ? "Rendering animation…" : "Create animation"}
          </button>
        ) : null}
      </div>

      {error !== null ? (
        <StatusBanner tone="danger" title="The request failed" description={error} />
      ) : null}

      {job !== null ? (
        <p className="text-xs text-slate-500">
          Job {job.status}
          {job.stage !== null && job.stage !== undefined ? ` — ${job.stage}` : ""} —{" "}
          {(job.progress * 100).toFixed(0)}%
        </p>
      ) : null}

      {run !== null ? (
        <p className="text-xs text-slate-500">
          Run {run.run_id.slice(0, 12)}… — {run.status} — recipe{" "}
          {run.recipe_hash.slice(0, 12)}… — dataset {run.dataset_sha256.slice(0, 12)}… — boundary{" "}
          {(run.boundary_sha256 ?? "").slice(0, 12)}… — created {formatTimestamp(run.created_at)}
        </p>
      ) : null}

      {results !== null ? <ResultsView results={results} artifacts={artifacts} videoArtifactId={videoArtifactId} /> : null}
    </div>
  );
}

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    const issues =
      error.details !== null && "issues" in error.details
        ? (error.details["issues"] as unknown[])
        : [];
    const detail = issues
      .map((issue) => {
        const record = issue as Record<string, unknown>;
        return `${String(record.path)}: ${String(record.message)}`;
      })
      .join("; ");
    return detail.length > 0 ? `${error.message} (${detail})` : error.message;
  }
  return error instanceof Error ? error.message : "The request failed.";
}

function ResultsView({
  results,
  artifacts,
  videoArtifactId,
}: {
  readonly results: AnalysisResults;
  readonly artifacts: ArtifactRef[];
  readonly videoArtifactId: string | null;
}) {
  const pngByKey = new Map(
    artifacts
      .filter((item) => item.content_type === "image/png")
      .map((item) => [item.media_type_detail["png_key"] ?? item.sha256, item] as const),
  );
  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500">
        {results.frames.length} frames · grid {results.grid_cells} cells ({results.masked_cells}{" "}
        inside the boundary) · boundary {results.boundary_sha256.slice(0, 12)}…
      </p>
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full text-xs">
          <thead className="bg-slate-50 text-left font-medium text-slate-600">
            <tr>
              <th className="px-3 py-2">Frame</th>
              <th className="px-3 py-2">Points</th>
              <th className="px-3 py-2">Method</th>
              <th className="px-3 py-2">RMSE</th>
              <th className="px-3 py-2">MAE</th>
              <th className="px-3 py-2">Folds</th>
              <th className="px-3 py-2">Selected</th>
            </tr>
          </thead>
          <tbody>
            {results.frames.flatMap((frame) =>
              frame.methods.map((method) => (
                <tr key={`${frame.sampled_at}-${method.method}`} className="border-t border-slate-100">
                  <td className="px-3 py-1 font-mono">{frame.sampled_at.slice(0, 19)}</td>
                  <td className="px-3 py-1">{frame.point_count}</td>
                  <td className="px-3 py-1">{method.method}</td>
                  <td className="px-3 py-1">{method.rmse === null || method.rmse === undefined ? "—" : method.rmse.toFixed(4)}</td>
                  <td className="px-3 py-1">{method.mae === null || method.mae === undefined ? "—" : method.mae.toFixed(4)}</td>
                  <td className="px-3 py-1">{method.folds}</td>
                  <td className="px-3 py-1">
                    {frame.decisions.find((decision) => decision.selected === method.method) !== undefined
                      ? "yes"
                      : "—"}
                  </td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {results.frames.slice(0, 6).map((frame) => {
          const method = frame.methods[0];
          const png = method === undefined ? undefined : pngByKey.get(method.png_key);
          if (png === undefined || method === undefined) {
            return null;
          }
          return (
            <figure key={frame.sampled_at} className="rounded-lg border border-slate-200 bg-white p-2">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`${publicApiBaseUrl ?? ""}/api/v1/artifacts/${png.artifact_id}/content`}
                alt={`surface ${frame.parameter_id} at ${frame.sampled_at}`}
                className="w-full rounded"
              />
              <figcaption className="mt-1 text-xs text-slate-600">
                {frame.parameter_id} · {frame.sampled_at.slice(0, 10)} · {method.method} ·{" "}
                {formatBytes(png.size_bytes)}
              </figcaption>
            </figure>
          );
        })}
      </div>

      {results.temporal !== null && results.temporal !== undefined ? (
        <div className="rounded-lg border border-slate-200 bg-white p-3 text-xs">
          <p className="font-semibold">Temporal series</p>
          <ul className="mt-1 space-y-1">
            {results.temporal.series.map((series) => (
              <li key={`${series.station_id}-${series.parameter_id}`}>
                {series.station_id.slice(0, 10)}… / {series.parameter_id} — {series.observed} observed,{" "}
                {series.missing} missing, {series.frames} frames
                {series.trend_slope_per_day !== null && series.trend_slope_per_day !== undefined
                  ? ` — trend ${series.trend_slope_per_day.toFixed(4)}/day`
                  : ""}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {videoArtifactId !== null ? (
        <div className="rounded-lg border border-slate-200 bg-white p-3">
          <p className="text-sm font-semibold">Animation</p>
          <video
            controls
            className="mt-2 w-full max-w-2xl rounded"
            src={`${publicApiBaseUrl ?? ""}/api/v1/artifacts/${videoArtifactId}/content`}
          />
          <p className="mt-1 text-xs text-slate-500">
            Frames carry timestamp, parameter, unit, method, and frame-status captions; the MP4 was
            verified for frame count, fps, duration, and digest by the worker.
          </p>
        </div>
      ) : null}
    </div>
  );
}
