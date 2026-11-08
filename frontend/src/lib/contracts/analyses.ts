/**
 * Runtime schemas for the analyses API (recipes, runs, results, animations).
 */

import { z } from "zod";

const sha256Schema = z.string().regex(/^[0-9a-f]{64}$/);
const idSchema = (prefix: string) =>
  z.string().regex(new RegExp(`^${prefix}_[0-9a-f]{32}$`));

export const runIdSchema = idSchema("run");
export const jobIdSchema = idSchema("job");
export const artifactIdSchema = idSchema("art");

export const spatialMethodSchema = z.enum([
  "idw",
  "rbf",
  "kriging",
  "gaussian_process",
]);

export const recipeSchema = z.object({
  schema_version: z.string().default("1.0.0"),
  dataset_version_id: z.string().min(1),
  seed: z.number().int().min(0).default(0),
  spatial: z.object({
    methods: z
      .array(
        z.object({
          method: spatialMethodSchema,
          params: z.record(z.string(), z.unknown()).default({}),
        }),
      )
      .min(1),
    grid_resolution_m: z.number().positive(),
    max_grid_cells: z.number().int().min(1000).max(250_000),
    analysis_crs: z.string().default("EPSG:32644"),
    validation: z
      .enum(["leave_one_station_out", "spatial_block", "none"])
      .default("leave_one_station_out"),
    selection_rule: z.enum(["none", "best_rmse"]).default("none"),
    permitted_qc_statuses: z.array(z.string()).default(["pass", "warning"]),
  }),
  temporal: z
    .object({
      resolution: z.enum(["hour", "day", "week", "month"]).default("day"),
      interpolation: z.enum(["linear", "pchip"]).default("linear"),
      max_gap_days: z.number().positive().default(60),
      allow_extrapolation: z.boolean().default(false),
      frame_count: z.number().int().min(0).max(900).default(0),
      compute_trends: z.boolean().default(true),
      compute_change_points: z.boolean().default(false),
    })
    .nullish(),
});

export type Recipe = z.infer<typeof recipeSchema>;

export const createAnalysisResponseSchema = z.object({
  run_id: runIdSchema,
  job_id: jobIdSchema,
  recipe_hash: sha256Schema,
  status: z.string(),
});

export const runSchema = z.object({
  run_id: runIdSchema,
  dataset_version_id: z.string(),
  job_id: z.string().nullish(),
  recipe_hash: sha256Schema,
  recipe: z.record(z.string(), z.unknown()),
  dataset_sha256: sha256Schema,
  boundary_sha256: sha256Schema.nullish(),
  seed: z.number().int(),
  application_version: z.string(),
  schema_version: z.string(),
  status: z.string(),
  created_at: z.string(),
  finished_at: z.string().nullish(),
});

export type Run = z.infer<typeof runSchema>;

export const artifactRefSchema = z.object({
  artifact_id: artifactIdSchema,
  kind: z.string(),
  sha256: sha256Schema,
  size_bytes: z.number().int().min(0),
  content_type: z.string(),
  schema_version: z.string(),
  created_at: z.string(),
  media_type_detail: z.record(z.string(), z.unknown()).default({}),
});

export type ArtifactRef = z.infer<typeof artifactRefSchema>;

export const analysisResultsSchema = z.object({
  run_id: z.string(),
  recipe_hash: sha256Schema.nullish(),
  frames: z.array(
    z.object({
      parameter_id: z.string(),
      sampled_at: z.string(),
      point_count: z.number().int(),
      skipped_reason: z.string().nullish(),
      methods: z.array(
        z.object({
          method: z.string(),
          rmse: z.number().nullish(),
          mae: z.number().nullish(),
          bias: z.number().nullish(),
          folds: z.number().int(),
          geotiff_key: z.string(),
          png_key: z.string(),
          uncertainty_kind: z.string(),
        }),
      ),
      decisions: z.array(
        z.object({
          selected: z.string(),
          rule: z.string(),
          evidence: z.record(z.string(), z.number()),
        }),
      ),
    }),
  ),
  grid_cells: z.number().int(),
  masked_cells: z.number().int(),
  boundary_sha256: sha256Schema,
  temporal: z
    .object({
      series: z.array(
        z.object({
          station_id: z.string(),
          parameter_id: z.string(),
          observed: z.number().int(),
          missing: z.number().int(),
          frames: z.number().int(),
          trend_slope_per_day: z.number().nullish(),
          seasonal_counts: z.record(z.string(), z.number()),
        }),
      ),
    })
    .nullish(),
});

export type AnalysisResults = z.infer<typeof analysisResultsSchema>;

export const animationRequestSchema = z.object({
  parameter_id: z.string().nullish(),
  method: z.string().nullish(),
  palette: z.string().default("viridis"),
  fps: z.number().int().min(1).max(30).default(2),
});

export const animationResponseSchema = z.object({
  job_id: jobIdSchema,
  run_id: runIdSchema,
  status: z.string(),
});

export const jobSchema = z.object({
  job_id: jobIdSchema,
  job_type: z.string(),
  status: z.enum(["queued", "running", "succeeded", "failed", "cancelled"]),
  progress: z.number().min(0).max(1),
  stage: z.string().nullish(),
  attempts: z.number().int().min(0),
  cancel_requested: z.boolean(),
  payload: z.record(z.string(), z.unknown()).default({}),
  result: z.record(z.string(), z.unknown()).nullish(),
  error: z
    .object({
      code: z.string(),
      message: z.string(),
      details: z.record(z.string(), z.unknown()).nullish(),
    })
    .nullish(),
  created_at: z.string(),
  started_at: z.string().nullish(),
  heartbeat_at: z.string().nullish(),
  finished_at: z.string().nullish(),
});

export type Job = z.infer<typeof jobSchema>;
