import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { AnalysisPanel } from "@/components/datasets/analysis-panel";

const API_ORIGIN = "http://api.test";

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

function installHappyPath() {
  server.use(
    // happy-dom performs CORS preflights; answer them like the backend does.
    http.options(`${API_ORIGIN}/*`, () =>
      new HttpResponse(null, {
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Headers": "*",
          "Access-Control-Allow-Methods": "*",
        },
      }),
    ),
    http.post(`${API_ORIGIN}/api/v1/analyses`, () =>
      HttpResponse.json(
        {
          run_id: "run_" + "a".repeat(32),
          job_id: "job_" + "b".repeat(32),
          recipe_hash: "c".repeat(64),
          status: "queued",
        },
        { status: 202 },
      ),
    ),
    http.get(`${API_ORIGIN}/api/v1/jobs/job_${"b".repeat(32)}`, () =>
      HttpResponse.json({
        job_id: "job_" + "b".repeat(32),
        job_type: "analyze",
        status: "succeeded",
        progress: 1,
        attempts: 1,
        cancel_requested: false,
        payload: {},
        result: { run_id: "run_" + "a".repeat(32) },
        created_at: "2026-11-06T10:00:00Z",
      }),
    ),
    http.get(`${API_ORIGIN}/api/v1/analyses/run_${"a".repeat(32)}`, () =>
      HttpResponse.json({
        run_id: "run_" + "a".repeat(32),
        dataset_version_id: "dsv_" + "d".repeat(32),
        job_id: "job_" + "b".repeat(32),
        recipe_hash: "c".repeat(64),
        recipe: {},
        dataset_sha256: "e".repeat(64),
        boundary_sha256: "f".repeat(64),
        seed: 7,
        application_version: "0.1.0",
        schema_version: "1.0.0",
        status: "succeeded",
        created_at: "2026-11-06T10:00:00Z",
        finished_at: "2026-11-06T10:01:00Z",
      }),
    ),
    http.get(`${API_ORIGIN}/api/v1/analyses/run_${"a".repeat(32)}/results`, () =>
      HttpResponse.json({
        run_id: "run_" + "a".repeat(32),
        frames: [
          {
            parameter_id: "dissolved_oxygen",
            sampled_at: "2024-01-15T00:00:00+00:00",
            point_count: 4,
            skipped_reason: null,
            methods: [
              {
                method: "idw",
                rmse: 0.1,
                mae: 0.08,
                bias: 0.01,
                folds: 4,
                geotiff_key: "k1",
                png_key: "p1",
                uncertainty_kind: "support_only",
              },
            ],
            decisions: [{ selected: "idw", rule: "best_rmse", evidence: { idw: 0.1 } }],
          },
        ],
        grid_cells: 120,
        masked_cells: 31,
        boundary_sha256: "f".repeat(64),
        temporal: null,
      }),
    ),
    http.get(`${API_ORIGIN}/api/v1/analyses/run_${"a".repeat(32)}/artifacts`, () =>
      HttpResponse.json({ run_id: "run_" + "a".repeat(32), items: [] }),
    ),
  );
}

describe("AnalysisPanel", () => {
  it("runs an analysis and shows the frame metrics", async () => {
    installHappyPath();
    render(<AnalysisPanel datasetVersionId={"dsv_" + "d".repeat(32)} />);

    expect(screen.getByText(/spatial methods/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /run analysis/i }));

    await waitFor(
      () => expect(screen.getByText(/1 frames/)).toBeInTheDocument(),
      { timeout: 15_000 },
    );
    expect(screen.getByText("idw")).toBeInTheDocument();
    expect(screen.getByText("0.1000")).toBeInTheDocument();
    expect(screen.getByText(/best_rmse|selected/i)).toBeInTheDocument();
  });
});
