/**
 * Model-run API calls: create training runs from ML tasks and read their
 * metrics, folds, predictions, explanations, and artifacts.
 */

import type { ApiClient } from "./client";
import { getJob, pollJobUntilTerminal } from "./analyses";
import type { Job } from "../contracts/analyses";
import {
  createModelRunResponseSchema,
  explanationsResponseSchema,
  foldsResponseSchema,
  mlMetricsSchema,
  modelRunArtifactListSchema,
  modelRunSchema,
  predictionsResponseSchema,
  type CreateModelRunResponse,
  type ExplanationsResponse,
  type MLMetrics,
  type MLTask,
  type ModelRun,
  type PredictionsResponse,
} from "../contracts/models";

export async function createModelRun(
  client: ApiClient,
  task: MLTask,
): Promise<CreateModelRunResponse> {
  return client.postJson(
    "/api/v1/model-runs",
    task,
    createModelRunResponseSchema,
  );
}

export async function getModelRun(
  client: ApiClient,
  runId: string,
): Promise<ModelRun> {
  return client.getJson(`/api/v1/model-runs/${runId}`, modelRunSchema);
}

export async function getModelRunMetrics(
  client: ApiClient,
  runId: string,
): Promise<MLMetrics> {
  return client.getJson(`/api/v1/model-runs/${runId}/metrics`, mlMetricsSchema);
}

export async function getModelRunFolds(client: ApiClient, runId: string) {
  return client.getJson(
    `/api/v1/model-runs/${runId}/folds`,
    foldsResponseSchema,
  );
}

export async function getModelRunPredictions(
  client: ApiClient,
  runId: string,
): Promise<PredictionsResponse> {
  return client.getJson(
    `/api/v1/model-runs/${runId}/predictions`,
    predictionsResponseSchema,
  );
}

export async function getModelRunExplanations(
  client: ApiClient,
  runId: string,
): Promise<ExplanationsResponse> {
  return client.getJson(
    `/api/v1/model-runs/${runId}/explanations`,
    explanationsResponseSchema,
  );
}

export async function listModelRunArtifacts(client: ApiClient, runId: string) {
  const response = await client.getJson(
    `/api/v1/model-runs/${runId}/artifacts`,
    modelRunArtifactListSchema,
  );
  return response.items;
}

export { getJob, pollJobUntilTerminal };
export type { Job };
