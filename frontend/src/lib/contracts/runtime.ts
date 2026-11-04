import { z } from "zod";

/**
 * Runtime schemas for the payloads the frontend consumes.
 *
 * The schemas validate at the network boundary. Unknown fields are ignored on
 * purpose: the contract allows additive fields inside a major version, and a
 * consumer must not break when the backend adds one.
 */

export const healthLiveSchema = z.object({
  status: z.string().min(1),
  service: z.string().min(1),
});

export type HealthLive = z.infer<typeof healthLiveSchema>;

export const healthReadySchema = z.object({
  status: z.enum(["ready", "degraded"]),
  components: z.object({
    database: z.string().min(1),
    object_store: z.string().min(1),
  }),
});

export type HealthReady = z.infer<typeof healthReadySchema>;

export const contractVersionsSchema = z.object({
  api_major: z.number().int().positive(),
  application_version: z.string().min(1),
  artifact_schema_version: z.string().min(1),
  recipe_schema_version: z.string().min(1),
  supported_api_majors: z.array(z.number().int().positive()).min(1),
  supported_artifact_schema_versions: z.array(z.string().min(1)).min(1),
  supported_recipe_schema_versions: z.array(z.string().min(1)).min(1),
});

export type ContractVersions = z.infer<typeof contractVersionsSchema>;

export const capabilitiesSchema = z.object({
  application_version: z.string().min(1),
  api_major: z.number().int().positive(),
  artifact_schema_version: z.string().min(1),
  recipe_schema_version: z.string().min(1),
  file_formats: z.array(z.string()),
  spatial_methods: z.array(z.string()),
  temporal_methods: z.array(z.string()),
  model_families: z.array(z.string()),
  configuration: z.object({
    analysis_crs: z.string().min(1),
    database_dialect: z.string().min(1),
    environment: z.string().min(1),
    object_store_backend: z.string().min(1),
  }),
  limits: z.object({
    upload_max_bytes: z.number().int().positive(),
    upload_chunk_bytes: z.number().int().positive(),
    preview_row_limit: z.number().int().positive(),
    max_grid_cells: z.number().int().positive(),
    max_timestamps_per_run: z.number().int().positive(),
    max_animation_frames: z.number().int().positive(),
  }),
});

export type Capabilities = z.infer<typeof capabilitiesSchema>;

export const errorEnvelopeSchema = z.object({
  error: z.object({
    code: z.string().min(1),
    message: z.string().min(1),
    details: z.record(z.string(), z.unknown()).nullish(),
  }),
  request_id: z.string().min(1).nullish(),
});

export type ErrorEnvelope = z.infer<typeof errorEnvelopeSchema>;
