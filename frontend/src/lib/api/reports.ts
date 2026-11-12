/**
 * PDF report API calls: render a report for a succeeded run and read it.
 */

import type { ApiClient } from "./client";
import {
  createReportResponseSchema,
  reportResponseSchema,
  type CreateReportResponse,
  type ReportResponse,
} from "../contracts/reports";

export async function createReport(
  client: ApiClient,
  runId: string,
): Promise<CreateReportResponse> {
  return client.postJson(
    "/api/v1/reports",
    { run_id: runId },
    createReportResponseSchema,
  );
}

export async function getReport(
  client: ApiClient,
  reportId: string,
): Promise<ReportResponse> {
  return client.getJson(`/api/v1/reports/${reportId}`, reportResponseSchema);
}

/** Return the download URL of the rendered PDF report. */
export function reportDownloadUrl(client: ApiClient, reportId: string): string {
  return `${client.baseUrl}/api/v1/reports/${reportId}/download`;
}
