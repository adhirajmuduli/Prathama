import { describe, expect, it } from "vitest";

import {
  columnMappingSchema,
  completeUploadSchema,
  jobSchema,
  previewSchema,
  probeSchema,
  uploadSessionSchema,
  uploadStatusSchema,
} from "@/lib/contracts/ingest";

describe("ingest contract schemas", () => {
  it("validates an upload session document", () => {
    const document = {
      upload_id: "upl_" + "a".repeat(32),
      filename: "obs.csv",
      extension: ".csv",
      size_bytes: 998,
      chunk_size_bytes: 5_242_880,
      part_count: 1,
      parts: [{ part_number: 1, start_byte: 0, end_byte: 997, size_bytes: 998 }],
      status: "open",
      expires_at: "2026-11-05T12:00:00Z",
      created_at: "2026-11-05T11:00:00Z",
    };
    const parsed = uploadSessionSchema.parse(document);
    expect(parsed.part_count).toBe(1);
    expect(parsed.parts[0]?.size_bytes).toBe(998);
  });

  it("rejects an upload id with the wrong prefix", () => {
    const document = {
      upload_id: "ds_" + "a".repeat(32),
      filename: "obs.csv",
      extension: ".csv",
      size_bytes: 1,
      chunk_size_bytes: 10,
      part_count: 1,
      parts: [],
      status: "open",
      expires_at: "2026-11-05T12:00:00Z",
      created_at: "2026-11-05T11:00:00Z",
    };
    expect(() => uploadSessionSchema.parse(document)).toThrow();
  });

  it("validates a probe document with a proposed mapping", () => {
    const probe = {
      upload_id: "upl_" + "b".repeat(32),
      filename: "obs.csv",
      extension: ".csv",
      file_format: "csv",
      content_type: "text/csv",
      encoding: "utf-8",
      delimiter: ",",
      has_header: true,
      fields: ["station", "value"],
      decimal_style: "point",
      layout: "long",
      layout_confidence: 0.9,
      layout_evidence: [],
      layout_warnings: [],
      sniff_warnings: [],
      sheet_names: [],
      numeric_fields: ["value"],
      date_fields: [],
      proposed_mapping: {
        schema_version: "1.0.0",
        layout: "long",
        columns: [{ column: "station", role: "station" }],
      },
      proposal_warnings: [],
    };
    const parsed = probeSchema.parse(probe);
    expect(parsed.proposed_mapping.date_order).toBe("day_first");
    expect(columnMappingSchema.parse(parsed.proposed_mapping).columns).toHaveLength(1);
  });

  it("validates a completed upload and a terminal job", () => {
    const completion = completeUploadSchema.parse({
      upload_id: "upl_" + "c".repeat(32),
      status: "completed",
      artifact: {
        artifact_id: "art_" + "d".repeat(32),
        kind: "raw_upload",
        sha256: "e".repeat(64),
        size_bytes: 10,
        content_type: "text/csv",
        schema_version: "1.0.0",
        created_at: "2026-11-05T11:00:00Z",
      },
      job_id: "job_" + "f".repeat(32),
    });
    expect(completion.status).toBe("completed");

    const job = jobSchema.parse({
      job_id: "job_" + "f".repeat(32),
      job_type: "ingest",
      status: "succeeded",
      progress: 1,
      attempts: 1,
      cancel_requested: false,
      payload: {},
      result: { dataset_version_id: "dsv_" + "0".repeat(32) },
      created_at: "2026-11-05T11:00:00Z",
    });
    expect(job.status).toBe("succeeded");
  });

  it("validates a preview document and ignores unknown additive fields", () => {
    const preview = previewSchema.parse({
      version_id: "dsv_" + "1".repeat(32),
      artifact_sha256: "a".repeat(64),
      columns: ["observation_id", "value"],
      rows: [["obs_x", 6.8]],
      row_count: 12,
      limit: 100,
      future_field: "ignored",
    });
    expect(preview.rows).toHaveLength(1);
  });

  it("validates an in-progress upload status", () => {
    const status = uploadStatusSchema.parse({
      upload_id: "upl_" + "2".repeat(32),
      status: "open",
      filename: "obs.csv",
      extension: ".csv",
      size_bytes: 2048,
      sha256: null,
      parts_received: [1],
      missing_parts: [2],
      artifact: null,
      job_id: null,
      expires_at: "2026-11-05T12:00:00Z",
      created_at: "2026-11-05T11:00:00Z",
      completed_at: null,
    });
    expect(status.missing_parts).toEqual([2]);
  });
});
