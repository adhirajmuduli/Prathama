/**
 * Analysis API calls: create runs from recipes, read results, animate.
 */

import { z } from "zod";

import type { ApiClient } from "./client";
import type { animationRequestSchema } from "../contracts/analyses";
import {
  analysisResultsSchema,
  animationResponseSchema,
  artifactRefSchema,
  createAnalysisResponseSchema,
  jobSchema,
  runSchema,
  type AnalysisResults,
  type Job,
  type Recipe,
  type Run,
} from "../contracts/analyses";

export async function createAnalysis(
  client: ApiClient,
  recipe: Recipe,
): Promise<z.infer<typeof createAnalysisResponseSchema>> {
  return client.postJson("/api/v1/analyses", recipe, createAnalysisResponseSchema);
}

export async function getRun(client: ApiClient, runId: string): Promise<Run> {
  return client.getJson(`/api/v1/analyses/${runId}`, runSchema);
}

export async function getAnalysisResults(
  client: ApiClient,
  runId: string,
): Promise<AnalysisResults> {
  return client.getJson(`/api/v1/analyses/${runId}/results`, analysisResultsSchema);
}

export async function listRunArtifacts(client: ApiClient, runId: string) {
  const response = await client.getJson(
    `/api/v1/analyses/${runId}/artifacts`,
    artifactListSchema,
  );
  return response.items;
}

export async function createAnimation(
  client: ApiClient,
  runId: string,
  request: AnimationRequest,
) {
  return client.postJson(
    `/api/v1/analyses/${runId}/animations`,
    request,
    animationResponseSchema,
  );
}

export async function getJob(client: ApiClient, jobId: string): Promise<Job> {
  return client.getJson(`/api/v1/jobs/${jobId}`, jobSchema);
}

export async function pollJobUntilTerminal(
  client: ApiClient,
  jobId: string,
  onUpdate: (job: Job) => void,
  options: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<Job> {
  const intervalMs = options.intervalMs ?? 1500;
  const timeoutMs = options.timeoutMs ?? 10 * 60_000;
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const job = await getJob(client, jobId);
    onUpdate(job);
    if (job.status === "succeeded" || job.status === "failed" || job.status === "cancelled") {
      return job;
    }
    if (Date.now() > deadline) {
      throw new Error("The job did not reach a terminal state in time.");
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

const artifactListSchema = z.object({
  run_id: z.string(),
  items: z.array(artifactRefSchema),
});

export type AnimationRequest = z.infer<typeof animationRequestSchema>;
