/**
 * Runtime schemas for the ingest API (uploads, probe, datasets, jobs).
 *
 * Every response from the ingest endpoints is validated at the network boundary
 * against these schemas. Unknown fields are ignored on purpose, so an additive
 * API change never breaks the client.
 */

import { z } from "zod";

const sha256Schema = z.string().regex(/^[0-9a-f]{64}$/);
const idSchema = (prefix: string) =>
  z.string().regex(new RegExp(`^${prefix}_[0-9a-f]{32}$`));

export const uploadIdSchema = idSchema("upl");
export const datasetIdSchema = idSchema("ds");
export const datasetVersionIdSchema = idSchema("dsv");
export const jobIdSchema = idSchema("job");
export const artifactIdSchema = idSchema("art");

export const columnRoleSchema = z.enum([
  "station",
  "latitude",
  "longitude",
  "easting",
  "northing",
  "timestamp",
  "parameter",
  "value",
  "unit",
  "qualifier",
  "depth",
  "sector",
  "ignored",
]);

export type ColumnRole = z.infer<typeof columnRoleSchema>;

export const mappedColumnSchema = z.object({
  column: z.string().min(1),
  role: columnRoleSchema,
  parameter_label: z.string().min(1).nullish(),
  station_label: z.string().min(1).nullish(),
  unit: z.string().min(1).nullish(),
});

export const columnMappingSchema = z.object({
  schema_version: z.string().min(1),
  layout: z.enum(["long", "wide"]),
  wide_axis: z.enum(["stations", "parameters"]).nullish(),
  columns: z.array(mappedColumnSchema).min(1),
  default_parameter: z.string().min(1).nullish(),
  default_unit: z.string().min(1).nullish(),
  source_crs: z.string().min(1).nullish(),
  date_order: z
    .enum(["day_first", "month_first", "year_first"])
    .default("day_first"),
  timezone_policy: z
    .enum(["assume_utc", "require_offset", "named"])
    .default("assume_utc"),
  timezone_name: z.string().min(1).nullish(),
  duplicate_policy: z
    .enum([
      "flag_all",
      "keep_first",
      "keep_last",
      "keep_most_complete",
      "error",
    ])
    .default("flag_all"),
});

export type ColumnMapping = z.infer<typeof columnMappingSchema>;

export const partPlanSchema = z.object({
  part_number: z.number().int().positive(),
  start_byte: z.number().int().min(0),
  end_byte: z.number().int().min(0),
  size_bytes: z.number().int().positive(),
});

export const uploadSessionSchema = z.object({
  upload_id: uploadIdSchema,
  filename: z.string(),
  extension: z.string(),
  size_bytes: z.number().int().positive(),
  chunk_size_bytes: z.number().int().positive(),
  part_count: z.number().int().positive(),
  parts: z.array(partPlanSchema),
  status: z.literal("open"),
  expires_at: z.string(),
  created_at: z.string(),
});

export type UploadSession = z.infer<typeof uploadSessionSchema>;

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

export const uploadStatusSchema = z.object({
  upload_id: uploadIdSchema,
  status: z.enum(["open", "completed", "cancelled"]),
  filename: z.string(),
  extension: z.string(),
  size_bytes: z.number().int().positive(),
  sha256: sha256Schema.nullish(),
  parts_received: z.array(z.number().int()),
  missing_parts: z.array(z.number().int()),
  artifact: artifactRefSchema.nullish(),
  job_id: jobIdSchema.nullish(),
  expires_at: z.string(),
  created_at: z.string(),
  completed_at: z.string().nullish(),
});

export type UploadStatus = z.infer<typeof uploadStatusSchema>;

export const partUploadSchema = z.object({
  upload_id: uploadIdSchema,
  part_number: z.number().int().positive(),
  size_bytes: z.number().int().positive(),
  sha256: sha256Schema,
  received: z.literal(true),
});

export const completeUploadSchema = z.object({
  upload_id: uploadIdSchema,
  status: z.literal("completed"),
  artifact: artifactRefSchema,
  job_id: jobIdSchema,
});

export type CompleteUpload = z.infer<typeof completeUploadSchema>;

export const abortUploadSchema = z.object({
  upload_id: uploadIdSchema,
  status: z.literal("cancelled"),
});

export const probeSchema = z.object({
  upload_id: uploadIdSchema,
  filename: z.string(),
  extension: z.string(),
  file_format: z.string(),
  content_type: z.string().nullish(),
  encoding: z.string().nullish(),
  delimiter: z.string().nullish(),
  has_header: z.boolean(),
  fields: z.array(z.string()),
  decimal_style: z.string(),
  layout: z.string(),
  layout_confidence: z.number(),
  layout_evidence: z.array(z.string()),
  layout_warnings: z.array(z.string()),
  sniff_warnings: z.array(z.string()),
  sheet_names: z.array(z.string()),
  numeric_fields: z.array(z.string()),
  date_fields: z.array(z.string()),
  proposed_mapping: columnMappingSchema,
  proposal_warnings: z.array(z.string()),
});

export type Probe = z.infer<typeof probeSchema>;

export const createDatasetRequestSchema = z.object({
  upload_id: uploadIdSchema,
  name: z.string().min(1).max(255),
  description: z.string().max(4096).nullish(),
  mapping: columnMappingSchema,
});

export const createDatasetResponseSchema = z.object({
  dataset_id: datasetIdSchema,
  version_id: datasetVersionIdSchema,
  job_id: jobIdSchema,
  status: z.literal("accepted"),
});

export const datasetSchema = z.object({
  dataset_id: datasetIdSchema,
  name: z.string(),
  description: z.string().nullish(),
  current_version_id: datasetVersionIdSchema.nullish(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const datasetListSchema = z.object({
  items: z.array(datasetSchema),
  page: z.object({
    offset: z.number().int().min(0),
    limit: z.number().int().min(1),
    total: z.number().int().min(0),
  }),
});

export const datasetVersionSchema = z.object({
  version_id: datasetVersionIdSchema,
  dataset_id: datasetIdSchema,
  version_number: z.number().int().positive(),
  schema_version: z.string(),
  sealed: z.boolean(),
  row_count: z.number().int().min(0),
  parameter_count: z.number().int().min(0),
  station_count: z.number().int().min(0),
  first_sampled_at: z.string().nullish(),
  last_sampled_at: z.string().nullish(),
  boundary_id: z.string().nullish(),
  normalized_artifact: artifactRefSchema.nullish(),
  artifacts: z.array(artifactRefSchema),
  created_at: z.string(),
  sealed_at: z.string().nullish(),
});

export type DatasetVersion = z.infer<typeof datasetVersionSchema>;
export type Dataset = z.infer<typeof datasetSchema>;
export type ArtifactRef = z.infer<typeof artifactRefSchema>;
export type Preview = z.infer<typeof previewSchema>;
export type ProvenanceList = z.infer<typeof provenanceListSchema>;

export const datasetVersionListSchema = z.object({
  dataset_id: datasetIdSchema,
  items: z.array(datasetVersionSchema),
});

export const previewSchema = z.object({
  version_id: datasetVersionIdSchema,
  artifact_sha256: sha256Schema,
  columns: z.array(z.string()),
  rows: z.array(z.array(z.unknown())),
  row_count: z.number().int().min(0),
  limit: z.number().int().positive(),
});

export const jobSchema = z.object({
  job_id: jobIdSchema,
  job_type: z.string(),
  status: z.enum(["queued", "running", "succeeded", "failed", "cancelled"]),
  progress: z.number().min(0).max(1),
  stage: z.string().nullish(),
  attempts: z.number().int().min(0),
  cancel_requested: z.boolean(),
  worker_id: z.string().nullish(),
  run_id: z.string().nullish(),
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

export const cancelJobSchema = z.object({
  job_id: jobIdSchema,
  status: z.enum(["queued", "running", "succeeded", "failed", "cancelled"]),
  cancel_requested: z.boolean(),
});

export const provenanceListSchema = z.object({
  version_id: datasetVersionIdSchema,
  items: z.array(
    z.object({
      provenance_id: z.string(),
      event_type: z.string(),
      occurred_at: z.string(),
      parent_artifact_ids: z.array(z.string()),
      transformations: z.array(z.string()),
    }),
  ),
});
