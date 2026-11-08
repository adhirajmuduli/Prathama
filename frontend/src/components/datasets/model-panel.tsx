"use client";

/**
 * The model panel on a dataset version: an ML task form, a run poller, and
 * the finished run's comparison table, per-fold metrics, uncertainty
 * coverage, and explanation importances. The browser never computes any of
 * this; every number comes from the backend's stored run documents.
 */

import { useMemo, useState } from "react";

import { StatusBanner } from "../status-banner";
import { ExportPanel } from "./export-panel";
import {
  createModelRun,
  getModelRun,
  getModelRunExplanations,
  getModelRunFolds,
  getModelRunMetrics,
  getModelRunPredictions,
  listModelRunArtifacts,
  pollJobUntilTerminal,
} from "../../lib/api/models";
import { createApiClient } from "../../lib/api/client";
import { ApiError } from "../../lib/api/errors";
import { publicApiBaseUrl } from "../../lib/env/client";
import {
  mlTaskSchema,
  predictionSettingSchema,
  splitStrategySchema,
  uncertaintyMethodSchema,
  type ExplanationsResponse,
  type FoldMetrics,
  type MLMetrics,
  type MLTask,
  type ModelRun,
  type PredictionsResponse,
} from "../../lib/contracts/models";
import type { Job } from "../../lib/contracts/analyses";
import { formatTimestamp } from "../../lib/format";

const CANDIDATE_MODELS = [
  "elastic_net",
  "random_forest",
  "extra_trees",
  "hist_gradient_boosting",
  "xgboost",
] as const;

const EXPLANATION_METHODS = ["permutation", "shap_tree"] as const;

export interface ModelPanelProps {
  readonly datasetVersionId: string;
}

export function ModelPanel({ datasetVersionId }: ModelPanelProps) {
  const client = useMemo(
    () =>
      publicApiBaseUrl === null
        ? null
        : createApiClient({ baseUrl: publicApiBaseUrl }),
    [],
  );
  const [target, setTarget] = useState("dissolved_oxygen");
  const [unit, setUnit] = useState("mg/L");
  const [setting, setSetting] = useState<MLTask["setting"]>(
    "known_station_temporal",
  );
  const [outerSplit, setOuterSplit] =
    useState<MLTask["outer_split"]>("station_group");
  const [innerSplit, setInnerSplit] =
    useState<MLTask["inner_split"]>("station_group");
  const [models, setModels] = useState<MLTask["candidate_models"]>([
    "elastic_net",
  ]);
  const [searchBudget, setSearchBudget] = useState(4);
  const [seed, setSeed] = useState(7);
  const [uncertainty, setUncertainty] =
    useState<MLTask["uncertainty_method"]>("bootstrap_ensemble");
  const [explanations, setExplanations] = useState<
    MLTask["explanation_methods"]
  >(["permutation"]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [run, setRun] = useState<ModelRun | null>(null);
  const [metrics, setMetrics] = useState<MLMetrics | null>(null);
  const [folds, setFolds] = useState<FoldMetrics[]>([]);
  const [predictions, setPredictions] = useState<PredictionsResponse | null>(
    null,
  );
  const [explanationDoc, setExplanationDoc] =
    useState<ExplanationsResponse | null>(null);
  const [artifactCount, setArtifactCount] = useState(0);

  if (client === null) {
    return (
      <StatusBanner
        tone="warning"
        title="Model training is not available"
        description="The public API origin is not configured, so no model run can be started from the browser."
      />
    );
  }

  const toggle = <T extends string>(
    list: readonly T[],
    value: T,
    setter: (next: T[]) => void,
  ) => {
    setter(
      list.includes(value)
        ? list.filter((item) => item !== value)
        : [...list, value],
    );
  };

  const startRun = async () => {
    setBusy(true);
    setError(null);
    setRun(null);
    setMetrics(null);
    setFolds([]);
    setPredictions(null);
    setExplanationDoc(null);
    try {
      const task = mlTaskSchema.parse({
        schema_version: "1.0.0",
        dataset_version_id: datasetVersionId,
        target_parameter_id: target,
        prediction_unit: unit,
        setting,
        outer_split: outerSplit,
        inner_split: innerSplit,
        candidate_models: models,
        search_budget: searchBudget,
        primary_metric: "rmse",
        seed,
        uncertainty_method: uncertainty,
        explanation_methods: explanations,
      } satisfies Partial<MLTask>);
      const created = await createModelRun(client, task);
      const finishedJob = await pollJobUntilTerminal(
        client,
        created.job_id,
        setJob,
        {
          timeoutMs: 10 * 60_000,
        },
      );
      if (finishedJob.status !== "succeeded") {
        throw new Error(
          finishedJob.error !== null && finishedJob.error !== undefined
            ? `${finishedJob.error.code}: ${finishedJob.error.message}`
            : "The training job failed.",
        );
      }
      const [
        runResponse,
        metricsResponse,
        foldsResponse,
        predictionsResponse,
        explanationsResponse,
        artifacts,
      ] = await Promise.all([
        getModelRun(client, created.run_id),
        getModelRunMetrics(client, created.run_id),
        getModelRunFolds(client, created.run_id),
        getModelRunPredictions(client, created.run_id),
        getModelRunExplanations(client, created.run_id),
        listModelRunArtifacts(client, created.run_id),
      ]);
      setRun(runResponse);
      setMetrics(metricsResponse);
      setFolds(foldsResponse.folds);
      setPredictions(predictionsResponse);
      setExplanationDoc(explanationsResponse);
      setArtifactCount(artifacts.length);
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

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <label className="block text-sm">
          <span className="font-medium text-slate-700">Target parameter</span>
          <input
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
            value={target}
            onChange={(event) => setTarget(event.target.value)}
          />
        </label>
        <label className="block text-sm">
          <span className="font-medium text-slate-700">Prediction unit</span>
          <input
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
            value={unit}
            onChange={(event) => setUnit(event.target.value)}
          />
        </label>
        <label className="block text-sm">
          <span className="font-medium text-slate-700">Prediction setting</span>
          <select
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
            value={setting}
            onChange={(event) =>
              setSetting(event.target.value as MLTask["setting"])
            }
          >
            {predictionSettingSchema.options.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          <span className="font-medium text-slate-700">Outer split</span>
          <select
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
            value={outerSplit}
            onChange={(event) =>
              setOuterSplit(event.target.value as MLTask["outer_split"])
            }
          >
            {splitStrategySchema.options.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          <span className="font-medium text-slate-700">Inner split</span>
          <select
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
            value={innerSplit}
            onChange={(event) =>
              setInnerSplit(event.target.value as MLTask["inner_split"])
            }
          >
            {splitStrategySchema.options.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          <span className="font-medium text-slate-700">
            Search budget per model
          </span>
          <input
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
            value={searchBudget}
            onChange={(event) => setSearchBudget(Number(event.target.value))}
            inputMode="numeric"
          />
        </label>
        <label className="block text-sm">
          <span className="font-medium text-slate-700">Seed</span>
          <input
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
            value={seed}
            onChange={(event) => setSeed(Number(event.target.value))}
            inputMode="numeric"
          />
        </label>
        <label className="block text-sm">
          <span className="font-medium text-slate-700">Uncertainty method</span>
          <select
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
            value={uncertainty}
            onChange={(event) =>
              setUncertainty(event.target.value as MLTask["uncertainty_method"])
            }
          >
            {uncertaintyMethodSchema.options.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <fieldset>
          <legend className="text-sm font-medium text-slate-700">
            Candidate models
          </legend>
          {CANDIDATE_MODELS.map((family) => (
            <label
              key={family}
              className="mt-1 flex items-center gap-2 text-sm"
            >
              <input
                type="checkbox"
                checked={models.includes(family)}
                onChange={() => toggle(models, family, setModels)}
              />
              {family}
            </label>
          ))}
        </fieldset>
        <fieldset>
          <legend className="text-sm font-medium text-slate-700">
            Explanations
          </legend>
          {EXPLANATION_METHODS.map((method) => (
            <label
              key={method}
              className="mt-1 flex items-center gap-2 text-sm"
            >
              <input
                type="checkbox"
                checked={explanations.includes(method)}
                onChange={() => toggle(explanations, method, setExplanations)}
              />
              {method}
            </label>
          ))}
        </fieldset>
      </div>

      <div>
        <button
          type="button"
          onClick={() => void startRun()}
          disabled={busy || models.length === 0}
          className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:opacity-60"
        >
          {busy ? "Training…" : "Train model run"}
        </button>
      </div>

      {error !== null ? (
        <StatusBanner
          tone="danger"
          title="The request failed"
          description={error}
        />
      ) : null}

      {job !== null ? (
        <p className="text-xs text-slate-500">
          Job {job.status}
          {job.stage !== null && job.stage !== undefined
            ? ` — ${job.stage}`
            : ""}{" "}
          — {(job.progress * 100).toFixed(0)}%
        </p>
      ) : null}

      {run !== null ? (
        <p className="text-xs text-slate-500">
          Run {run.run_id.slice(0, 12)}… — {run.status} — task{" "}
          {run.task_hash.slice(0, 12)}… — {artifactCount} artifacts — created{" "}
          {formatTimestamp(run.created_at)}
        </p>
      ) : null}

      {metrics !== null ? (
        <MetricsView metrics={metrics} folds={folds} />
      ) : null}
      {predictions !== null ? (
        <PredictionsSummary predictions={predictions} />
      ) : null}
      {explanationDoc !== null ? (
        <ExplanationsView explanations={explanationDoc} />
      ) : null}

      {run !== null && run.status === "succeeded" ? <ExportPanel runId={run.run_id} /> : null}
    </div>
  );
}

function MetricsView({
  metrics,
  folds,
}: {
  readonly metrics: MLMetrics;
  readonly folds: readonly FoldMetrics[];
}) {
  const families = Object.keys(metrics.aggregated).sort();
  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500">
        {metrics.rows} rows · {folds.length} fold results · selected family{" "}
        <span className="font-semibold">{metrics.selected_family}</span> ·
        uncertainty {metrics.uncertainty.method}
        {metrics.uncertainty.empirical_coverage !== null &&
        metrics.uncertainty.empirical_coverage !== undefined
          ? ` · empirical coverage ${(metrics.uncertainty.empirical_coverage * 100).toFixed(1)}%`
          : ""}
      </p>
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full text-xs">
          <thead className="bg-slate-50 text-left font-medium text-slate-600">
            <tr>
              <th className="px-3 py-2">Family</th>
              <th className="px-3 py-2">RMSE mean</th>
              <th className="px-3 py-2">RMSE 95% CI</th>
              <th className="px-3 py-2">MAE mean</th>
              <th className="px-3 py-2">Baseline</th>
            </tr>
          </thead>
          <tbody>
            {families.map((family) => {
              const aggregate = metrics.aggregated[family] ?? {};
              const ci = aggregate["rmse_ci95"];
              const isBaseline = family in metrics.baseline_comparison;
              return (
                <tr
                  key={family}
                  className={`border-t border-slate-100 ${
                    family === metrics.selected_family
                      ? "bg-sky-50 font-semibold"
                      : ""
                  }`}
                >
                  <td className="px-3 py-1">{family}</td>
                  <td className="px-3 py-1">
                    {formatMetric(aggregate["rmse_mean"])}
                  </td>
                  <td className="px-3 py-1">
                    {Array.isArray(ci) && ci.length === 2
                      ? `[${Number(ci[0]).toFixed(4)}, ${Number(ci[1]).toFixed(4)}]`
                      : "—"}
                  </td>
                  <td className="px-3 py-1">
                    {formatMetric(aggregate["mae_mean"])}
                  </td>
                  <td className="px-3 py-1">{isBaseline ? "yes" : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {folds.length > 0 ? (
        <details className="rounded-lg border border-slate-200 bg-white p-3 text-xs">
          <summary className="cursor-pointer font-medium">
            Per-fold metrics ({folds.length})
          </summary>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-left font-medium text-slate-600">
                <tr>
                  <th className="px-2 py-1">Fold</th>
                  <th className="px-2 py-1">Family</th>
                  <th className="px-2 py-1">Train</th>
                  <th className="px-2 py-1">Test</th>
                  <th className="px-2 py-1">RMSE</th>
                </tr>
              </thead>
              <tbody>
                {folds.map((fold) => (
                  <tr
                    key={`${fold.fold_index}-${fold.family}`}
                    className="border-t border-slate-100"
                  >
                    <td className="px-2 py-1">{fold.fold_index}</td>
                    <td className="px-2 py-1">{fold.family}</td>
                    <td className="px-2 py-1">{fold.train_size}</td>
                    <td className="px-2 py-1">{fold.test_size}</td>
                    <td className="px-2 py-1">
                      {fold.metrics["rmse"]?.toFixed(4) ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ) : null}
      {metrics.warnings.length > 0 ? (
        <ul className="list-disc space-y-1 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
          {metrics.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function PredictionsSummary({
  predictions,
}: {
  readonly predictions: PredictionsResponse;
}) {
  const heldOut = predictions.folds.reduce(
    (total, fold) => total + fold.test_size,
    0,
  );
  return (
    <p className="text-xs text-slate-500">
      Held-out predictions: {heldOut} rows across {predictions.folds.length}{" "}
      fold entries — every value was produced on rows the fold model never saw
      during fitting.
    </p>
  );
}

function ExplanationsView({
  explanations,
}: {
  readonly explanations: ExplanationsResponse;
}) {
  return (
    <div className="space-y-2 rounded-lg border border-slate-200 bg-white p-3">
      <p className="text-sm font-semibold">
        Explanations — {explanations.model_family} on{" "}
        {explanations.held_out_rows} held-out rows
      </p>
      <p className="text-xs text-slate-500">
        Importance values are associations in this model and data, not causal
        effects.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="bg-slate-50 text-left font-medium text-slate-600">
            <tr>
              <th className="px-2 py-1">Feature</th>
              <th className="px-2 py-1">Method</th>
              <th className="px-2 py-1">Value</th>
              <th className="px-2 py-1">Rank</th>
            </tr>
          </thead>
          <tbody>
            {explanations.rows.map((row) => (
              <tr
                key={`${row.method}-${row.feature}-${row.group ?? ""}`}
                className="border-t border-slate-100"
              >
                <td className="px-2 py-1">{row.feature}</td>
                <td className="px-2 py-1">{row.method}</td>
                <td className="px-2 py-1">{row.value.toFixed(4)}</td>
                <td className="px-2 py-1">{row.rank ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {explanations.limitations.length > 0 ? (
        <ul className="list-disc space-y-1 text-xs text-amber-800">
          {explanations.limitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function formatMetric(value: unknown): string {
  return typeof value === "number" ? value.toFixed(4) : "—";
}
