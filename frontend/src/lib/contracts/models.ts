/**
 * Runtime schemas for the model-runs API (ML tasks, runs, metrics, folds,
 * predictions, explanations). Validated at the network boundary; unknown
 * fields are ignored so additive API changes never break the client.
 */

import { z } from "zod";

const sha256Schema = z.string().regex(/^[0-9a-f]{64}$/);
const idSchema = (prefix: string) =>
  z.string().regex(new RegExp(`^${prefix}_[0-9a-f]{32}$`));

export const runIdSchema = idSchema("run");
export const modelJobIdSchema = idSchema("job");

export const predictionSettingSchema = z.enum([
  "known_station_temporal",
  "unseen_station_spatial",
  "future_period",
  "missing_reconstruction",
]);

export const splitStrategySchema = z.enum([
  "station_group",
  "spatial_block",
  "leave_year_out",
  "rolling_origin",
  "sector",
  "combined",
  "random_row",
]);

export const modelFamilySchema = z.enum([
  "mean_baseline",
  "station_climatology",
  "seasonal_climatology",
  "elastic_net",
  "random_forest",
  "extra_trees",
  "hist_gradient_boosting",
  "xgboost",
]);

export const uncertaintyMethodSchema = z.enum([
  "bootstrap_ensemble",
  "quantile",
]);

export const explanationMethodSchema = z.enum([
  "permutation",
  "shap_tree",
  "partial_dependence",
]);

export const mlTaskSchema = z.object({
  schema_version: z.string().default("1.0.0"),
  dataset_version_id: z.string().min(1),
  target_parameter_id: z.string().min(1),
  prediction_unit: z.string().min(1),
  setting: predictionSettingSchema,
  eligible_start: z.string().nullish(),
  eligible_end: z.string().nullish(),
  eligible_station_ids: z.array(z.string()).default([]),
  feature_names: z.array(z.string()).default([]),
  lag_policy: z.string().default("none"),
  missing_data_policy: z.string().default("drop"),
  qc_policy: z.string().default("exclude_failed"),
  outer_split: splitStrategySchema.default("station_group"),
  inner_split: splitStrategySchema.default("station_group"),
  candidate_models: z.array(modelFamilySchema).min(1),
  search_budget: z.number().int().min(1).max(10_000).default(20),
  primary_metric: z.string().default("rmse"),
  seed: z.number().int().min(0).default(0),
  uncertainty_method: uncertaintyMethodSchema.default("bootstrap_ensemble"),
  explanation_methods: z.array(explanationMethodSchema).default([]),
});

export type MLTask = z.infer<typeof mlTaskSchema>;

export const createModelRunResponseSchema = z.object({
  run_id: runIdSchema,
  job_id: modelJobIdSchema,
  task_hash: sha256Schema,
  status: z.string(),
});

export type CreateModelRunResponse = z.infer<
  typeof createModelRunResponseSchema
>;

export const artifactRefSchema = z.object({
  artifact_id: idSchema("art"),
  kind: z.string(),
  sha256: sha256Schema,
  size_bytes: z.number().int().min(0),
  content_type: z.string(),
  schema_version: z.string(),
  created_at: z.string(),
  media_type_detail: z.record(z.string(), z.unknown()).default({}),
});

export const modelRunSchema = z.object({
  run_id: runIdSchema,
  dataset_version_id: z.string(),
  job_id: modelJobIdSchema.nullish(),
  status: z.string(),
  task: z.record(z.string(), z.unknown()),
  task_hash: sha256Schema,
  created_at: z.string(),
  finished_at: z.string().nullish(),
  results: z.record(z.string(), z.unknown()).nullish(),
  explanations: z.record(z.string(), z.unknown()).nullish(),
  artifacts: z.array(artifactRefSchema).default([]),
  warnings: z.array(z.string()).default([]),
});

export type ModelRun = z.infer<typeof modelRunSchema>;

export const foldMetricsSchema = z.object({
  fold_index: z.number().int(),
  family: z.string(),
  train_size: z.number().int(),
  test_size: z.number().int(),
  metrics: z.record(z.string(), z.number()),
});

export type FoldMetrics = z.infer<typeof foldMetricsSchema>;

export const mlMetricsSchema = z.object({
  schema_version: z.string(),
  application_version: z.string(),
  run_id: runIdSchema,
  task_hash: sha256Schema,
  feature_names: z.array(z.string()),
  feature_table_sha256: sha256Schema,
  rows: z.number().int(),
  aggregated: z.record(z.string(), z.record(z.string(), z.unknown())),
  baseline_comparison: z
    .record(z.string(), z.record(z.string(), z.unknown()))
    .default({}),
  selected_family: z.string(),
  selected_params: z.record(z.string(), z.unknown()).default({}),
  final_model_sha256: sha256Schema,
  uncertainty: z
    .object({
      method: z.string(),
      empirical_coverage: z.number().nullish(),
      notes: z.array(z.string()).default([]),
    })
    .default({ method: "unknown", empirical_coverage: null, notes: [] }),
  folds: z.array(foldMetricsSchema),
  warnings: z.array(z.string()).default([]),
});

export type MLMetrics = z.infer<typeof mlMetricsSchema>;

export const foldsResponseSchema = z.object({
  run_id: runIdSchema,
  folds: z.array(foldMetricsSchema),
});

export const predictionsResponseSchema = z.object({
  run_id: runIdSchema,
  folds: z.array(
    z.object({
      fold_index: z.number().int(),
      family: z.string(),
      test_size: z.number().int(),
      y_true: z.array(z.number()),
      y_pred: z.array(z.number()),
    }),
  ),
});

export type PredictionsResponse = z.infer<typeof predictionsResponseSchema>;

export const explanationsResponseSchema = z.object({
  run_id: runIdSchema,
  model_family: z.string(),
  method: z.string(),
  rows: z.array(
    z.object({
      feature: z.string(),
      method: z.string(),
      value: z.number(),
      baseline: z.number().nullish(),
      unit: z.string().nullish(),
      group: z.string().nullish(),
      rank: z.number().int().nullish(),
      detail: z.record(z.string(), z.unknown()).default({}),
    }),
  ),
  limitations: z.array(z.string()).default([]),
  detail: z.record(z.string(), z.unknown()).default({}),
  held_out_rows: z.number().int().default(0),
});

export type ExplanationsResponse = z.infer<typeof explanationsResponseSchema>;

export const modelRunArtifactListSchema = z.object({
  run_id: runIdSchema,
  items: z.array(artifactRefSchema),
});
