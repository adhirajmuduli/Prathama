/**
 * Export API calls: create a reproducibility bundle for a succeeded run and
 * read its status and manifest.
 */

import type { ApiClient } from "./client";
import {
  createExportResponseSchema,
  exportResponseSchema,
  type CreateExportResponse,
  type ExportResponse,
} from "../contracts/exports";

export async function createExport(
  client: ApiClient,
  runId: string,
): Promise<CreateExportResponse> {
  return client.postJson(
    "/api/v1/exports",
    { run_id: runId },
    createExportResponseSchema,
  );
}

export async function getExport(
  client: ApiClient,
  exportId: string,
): Promise<ExportResponse> {
  return client.getJson(`/api/v1/exports/${exportId}`, exportResponseSchema);
}

/** Return the download URL of a verified bundle (streamed with its digest). */
export function exportDownloadUrl(client: ApiClient, exportId: string): string {
  return `${client.baseUrl}/api/v1/exports/${exportId}/download`;
}
