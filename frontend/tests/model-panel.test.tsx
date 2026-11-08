import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { ModelPanel } from "@/components/datasets/model-panel";
import { ExportPanel } from "@/components/datasets/export-panel";
import { mlTaskSchema } from "@/lib/contracts/models";
import {
  createExportResponseSchema,
  exportResponseSchema,
} from "@/lib/contracts/exports";

const API_ORIGIN = "http://api.test";
const RUN_ID = "run_" + "a".repeat(32);
const JOB_ID = "job_" + "b".repeat(32);
const EXPORT_ID = "exp_" + "c".repeat(32);

const server = setupServer();

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});

afterEach(() => {
  server.resetHandlers();
});

afterAll(() => {
  server.close();
});

function cors() {
  server.use(
    http.options(
      `${API_ORIGIN}/*`,
      () =>
        new HttpResponse(null, {
          status: 204,
          headers: {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "*",
          },
        }),
    ),
  );
}

function installModelHappyPath() {
  cors();
  server.use(
    http.post(`${API_ORIGIN}/api/v1/model-runs`, () =>
      HttpResponse.json(
        {
          run_id: RUN_ID,
          job_id: JOB_ID,
          task_hash: "d".repeat(64),
          status: "queued",
        },
        { status: 202 },
      ),
    ),
    http.get(`${API_ORIGIN}/api/v1/jobs/${JOB_ID}`, () =>
      HttpResponse.json({
        job_id: JOB_ID,
        job_type: "train",
        status: "succeeded",
        progress: 1,
        attempts: 1,
        cancel_requested: false,
        payload: {},
        result: { run_id: RUN_ID },
        created_at: "2026-11-08T10:00:00Z",
      }),
    ),
    http.get(`${API_ORIGIN}/api/v1/model-runs/${RUN_ID}`, () =>
      HttpResponse.json({
        run_id: RUN_ID,
        dataset_version_id: "dsv_" + "e".repeat(32),
        job_id: JOB_ID,
        status: "succeeded",
        task: { target_parameter_id: "dissolved_oxygen" },
        task_hash: "d".repeat(64),
        created_at: "2026-11-08T10:00:00Z",
        finished_at: "2026-11-08T10:02:00Z",
        results: null,
        explanations: null,
        artifacts: [],
        warnings: [],
      }),
    ),
    http.get(`${API_ORIGIN}/api/v1/model-runs/${RUN_ID}/metrics`, () =>
      HttpResponse.json({
        schema_version: "1.0.0",
        application_version: "0.1.0",
        run_id: RUN_ID,
        task_hash: "d".repeat(64),
        feature_names: ["month", "x_m", "y_m"],
        feature_table_sha256: "f".repeat(64),
        rows: 72,
        aggregated: {
          elastic_net: {
            rmse_mean: 0.42,
            rmse_ci95: [0.4, 0.44],
            mae_mean: 0.3,
          },
          mean_baseline: {
            rmse_mean: 0.9,
            rmse_ci95: [0.8, 1.0],
            mae_mean: 0.7,
          },
        },
        baseline_comparison: {
          mean_baseline: { rmse_mean: 0.9 },
        },
        selected_family: "elastic_net",
        selected_params: { alpha: 0.1 },
        final_model_sha256: "0".repeat(64),
        uncertainty: {
          method: "bootstrap_ensemble",
          empirical_coverage: 0.93,
          notes: [],
        },
        folds: [
          {
            fold_index: 0,
            family: "elastic_net",
            train_size: 60,
            test_size: 12,
            metrics: { rmse: 0.42 },
          },
        ],
        warnings: [],
      }),
    ),
    http.get(`${API_ORIGIN}/api/v1/model-runs/${RUN_ID}/folds`, () =>
      HttpResponse.json({
        run_id: RUN_ID,
        folds: [
          {
            fold_index: 0,
            family: "elastic_net",
            train_size: 60,
            test_size: 12,
            metrics: { rmse: 0.42 },
          },
        ],
      }),
    ),
    http.get(`${API_ORIGIN}/api/v1/model-runs/${RUN_ID}/predictions`, () =>
      HttpResponse.json({
        run_id: RUN_ID,
        folds: [
          {
            fold_index: 0,
            family: "elastic_net",
            test_size: 2,
            y_true: [6.5, 6.6],
            y_pred: [6.4, 6.7],
          },
        ],
      }),
    ),
    http.get(`${API_ORIGIN}/api/v1/model-runs/${RUN_ID}/explanations`, () =>
      HttpResponse.json({
        run_id: RUN_ID,
        model_family: "elastic_net",
        method: "permutation",
        rows: [
          {
            feature: "month",
            method: "permutation",
            value: 0.31,
            baseline: 0.42,
            unit: "rmse",
            group: null,
            rank: 1,
            detail: {},
          },
        ],
        limitations: [],
        detail: {},
        held_out_rows: 12,
      }),
    ),
    http.get(`${API_ORIGIN}/api/v1/model-runs/${RUN_ID}/artifacts`, () =>
      HttpResponse.json({ run_id: RUN_ID, items: [] }),
    ),
  );
}

function installExportHappyPath() {
  cors();
  server.use(
    http.post(`${API_ORIGIN}/api/v1/exports`, () =>
      HttpResponse.json(
        {
          export_id: EXPORT_ID,
          job_id: JOB_ID,
          run_id: RUN_ID,
          status: "queued",
        },
        { status: 202 },
      ),
    ),
    http.get(`${API_ORIGIN}/api/v1/jobs/${JOB_ID}`, () =>
      HttpResponse.json({
        job_id: JOB_ID,
        job_type: "export",
        status: "succeeded",
        progress: 1,
        attempts: 1,
        cancel_requested: false,
        payload: {},
        result: {},
        created_at: "2026-11-08T10:00:00Z",
      }),
    ),
    http.get(`${API_ORIGIN}/api/v1/exports/${EXPORT_ID}`, () =>
      HttpResponse.json({
        export_id: EXPORT_ID,
        run_id: RUN_ID,
        job_id: JOB_ID,
        status: "succeeded",
        artifact: {
          artifact_id: "art_" + "1".repeat(32),
          kind: "export_bundle",
          sha256: "2".repeat(64),
          size_bytes: 4096,
          content_type: "application/zip",
          schema_version: "1.0.0",
          created_at: "2026-11-08T10:01:00Z",
          media_type_detail: {},
        },
        manifest: {
          run_id: RUN_ID,
          recipe_hash: "3".repeat(64),
          dataset_sha256: "4".repeat(64),
          generated_at: "2026-11-08T10:01:00Z",
        },
      }),
    ),
  );
}

describe("ModelPanel", () => {
  it("trains a model run and shows the comparison table", async () => {
    installModelHappyPath();
    render(<ModelPanel datasetVersionId={"dsv_" + "e".repeat(32)} />);

    fireEvent.click(screen.getByRole("button", { name: /train model run/i }));

    await waitFor(
      () => expect(screen.getByText(/selected family/)).toBeInTheDocument(),
      { timeout: 15_000 },
    );
    expect(screen.getAllByText("elastic_net").length).toBeGreaterThan(0);
    expect(screen.getAllByText("0.4200").length).toBeGreaterThan(0);
    expect(screen.getByText(/empirical coverage 93.0%/)).toBeInTheDocument();
    expect(screen.getByText(/held-out rows/)).toBeInTheDocument();
    expect(screen.getByText(/not causal effects/)).toBeInTheDocument();
  });
});

describe("ExportPanel", () => {
  it("exports a run and offers the verified download", async () => {
    installExportHappyPath();
    render(<ExportPanel runId={RUN_ID} />);

    fireEvent.click(screen.getByRole("button", { name: /export bundle/i }));

    await waitFor(
      () =>
        expect(
          screen.getByRole("link", { name: /download zip/i }),
        ).toBeInTheDocument(),
      { timeout: 15_000 },
    );
    expect(screen.getByText(/trendsmapp reproduce/)).toBeInTheDocument();
  });
});

describe("contract schemas", () => {
  it("accepts a valid ML task and rejects an unknown field", () => {
    const task = mlTaskSchema.parse({
      dataset_version_id: "dsv_" + "e".repeat(32),
      target_parameter_id: "dissolved_oxygen",
      prediction_unit: "mg/L",
      setting: "known_station_temporal",
      candidate_models: ["elastic_net"],
    });
    expect(task.outer_split).toBe("station_group");
    // Additive tolerance: unknown fields are stripped at the boundary, never fatal.
    const withExtra = mlTaskSchema.parse({
      dataset_version_id: "dsv_" + "e".repeat(32),
      target_parameter_id: "dissolved_oxygen",
      prediction_unit: "mg/L",
      setting: "known_station_temporal",
      candidate_models: ["elastic_net"],
      n_estimators: 100,
    });
    expect("n_estimators" in withExtra).toBe(false);
    expect(() =>
      mlTaskSchema.parse({
        setting: "not_a_setting",
        candidate_models: ["elastic_net"],
      }),
    ).toThrow();
  });

  it("validates export responses", () => {
    const parsed = createExportResponseSchema.parse({
      export_id: EXPORT_ID,
      job_id: JOB_ID,
      run_id: RUN_ID,
      status: "accepted",
    });
    expect(parsed.export_id).toBe(EXPORT_ID);
    expect(() => exportResponseSchema.parse({ export_id: "nope" })).toThrow();
  });
});
