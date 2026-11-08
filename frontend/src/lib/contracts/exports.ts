/**
 * Runtime schemas for the exports API (reproducibility bundles).
 */

import { z } from "zod";

import { artifactRefSchema, runIdSchema } from "./models";

const idSchema = (prefix: string) =>
  z.string().regex(new RegExp(`^${prefix}_[0-9a-f]{32}$`));

export const exportIdSchema = idSchema("exp");
export const jobIdSchema = idSchema("job");

export const createExportRequestSchema = z.object({
  run_id: runIdSchema,
});

export const createExportResponseSchema = z.object({
  export_id: exportIdSchema,
  job_id: jobIdSchema,
  run_id: runIdSchema,
  status: z.string(),
});

export type CreateExportResponse = z.infer<typeof createExportResponseSchema>;

export const exportResponseSchema = z.object({
  export_id: exportIdSchema,
  run_id: runIdSchema,
  job_id: jobIdSchema.nullish(),
  status: z.string(),
  artifact: artifactRefSchema,
  manifest: z.record(z.string(), z.unknown()).default({}),
});

export type ExportResponse = z.infer<typeof exportResponseSchema>;
