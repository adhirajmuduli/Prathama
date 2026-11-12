/**
 * Runtime schemas for the PDF report API.
 */

import { z } from "zod";

import { artifactRefSchema, runIdSchema } from "./models";

const idSchema = (prefix: string) =>
  z.string().regex(new RegExp(`^${prefix}_[0-9a-f]{32}$`));

export const reportIdSchema = idSchema("rpt");
export const jobIdSchema = idSchema("job");

export const createReportResponseSchema = z.object({
  report_id: reportIdSchema,
  job_id: jobIdSchema,
  run_id: runIdSchema,
  status: z.string(),
});

export type CreateReportResponse = z.infer<typeof createReportResponseSchema>;

export const reportResponseSchema = z.object({
  report_id: reportIdSchema,
  run_id: runIdSchema,
  job_id: jobIdSchema.nullish(),
  status: z.string(),
  artifact: artifactRefSchema,
  summary: z.record(z.string(), z.unknown()).default({}),
});

export type ReportResponse = z.infer<typeof reportResponseSchema>;
