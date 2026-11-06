// @vitest-environment node
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { createApiClient } from "@/lib/api/client";
import { uploadFile } from "@/lib/api/uploader";

const API_ORIGIN = "http://api.test";

const server = setupServer();

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});

afterEach(() => {
  server.resetHandlers();
});

afterAll(() => {
  server.close();
});

function sha256HexOf(payload: Uint8Array): Promise<string> {
  return crypto.subtle.digest("SHA-256", payload as unknown as ArrayBuffer).then((digest) =>
    Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join(""),
  );
}

describe("uploadFile", () => {
  it("creates a session, uploads every part with its content range, and completes", async () => {
    const payload = new TextEncoder().encode("station,value\nA,1\nB,2\n".repeat(5000));
    const digest = await sha256HexOf(payload);
    const chunk = 4096;
    const partCount = Math.ceil(payload.length / chunk);

    const seenRanges: string[] = [];
    let completed = false;

    server.use(
      http.post(`${API_ORIGIN}/api/v1/uploads`, async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        expect(body.filename).toBe("data.csv");
        expect(body.size_bytes).toBe(payload.length);
        expect(body.sha256).toBe(digest);
        const parts = [];
        for (let index = 0; index < partCount; index += 1) {
          const start = index * chunk;
          const end = Math.min(start + chunk, payload.length) - 1;
          parts.push({
            part_number: index + 1,
            start_byte: start,
            end_byte: end,
            size_bytes: end - start + 1,
          });
        }
        return HttpResponse.json(
          {
            upload_id: "upl_" + "a".repeat(32),
            filename: "data.csv",
            extension: ".csv",
            size_bytes: payload.length,
            chunk_size_bytes: chunk,
            part_count: partCount,
            parts,
            status: "open",
            expires_at: new Date(Date.now() + 60_000).toISOString(),
            created_at: new Date().toISOString(),
          },
          { status: 201 },
        );
      }),
      http.put(`${API_ORIGIN}/api/v1/uploads/upl_${"a".repeat(32)}/parts/:part`, async ({ request, params }) => {
        const range = request.headers.get("content-range");
        expect(range).not.toBeNull();
        seenRanges.push(`${String(params.part)}/${range}`);
        const body = new Uint8Array(await request.arrayBuffer());
        return HttpResponse.json({
          upload_id: "upl_" + "a".repeat(32),
          part_number: Number(params.part),
          size_bytes: body.length,
          sha256: await sha256HexOf(body),
          received: true,
        });
      }),
      http.post(`${API_ORIGIN}/api/v1/uploads/upl_${"a".repeat(32)}/complete`, ({ request }) => {
        expect(request.headers.get("idempotency-key")).not.toBeNull();
        completed = true;
        return HttpResponse.json({
          upload_id: "upl_" + "a".repeat(32),
          status: "completed",
          artifact: {
            artifact_id: "art_" + "b".repeat(32),
            kind: "raw_upload",
            sha256: digest,
            size_bytes: payload.length,
            content_type: "text/csv",
            schema_version: "1.0.0",
            created_at: new Date().toISOString(),
            media_type_detail: {},
          },
          job_id: "job_" + "c".repeat(32),
        });
      }),
      http.get(`${API_ORIGIN}/api/v1/uploads/upl_${"a".repeat(32)}`, () =>
        HttpResponse.json({
          upload_id: "upl_" + "a".repeat(32),
          status: "completed",
          filename: "data.csv",
          extension: ".csv",
          size_bytes: payload.length,
          sha256: digest,
          parts_received: Array.from({ length: partCount }, (_, index) => index + 1),
          missing_parts: [],
          artifact: {
            artifact_id: "art_" + "b".repeat(32),
            kind: "raw_upload",
            sha256: digest,
            size_bytes: payload.length,
            content_type: "text/csv",
            schema_version: "1.0.0",
            created_at: new Date().toISOString(),
            media_type_detail: {},
          },
          job_id: "job_" + "c".repeat(32),
          expires_at: new Date(Date.now() + 60_000).toISOString(),
          created_at: new Date().toISOString(),
          completed_at: new Date().toISOString(),
        }),
      ),
    );

    const client = createApiClient({ baseUrl: API_ORIGIN });
    const progress: number[] = [];
    const result = await uploadFile(
      client,
      new Blob([payload]),
      "data.csv",
      {
        contentType: "text/csv",
        idempotencyKey: "key-1",
        retryDelayMs: 1,
        onProgress: (progressEvent) => {
          progress.push(progressEvent.uploadedParts);
        },
      },
    );

    expect(result.session.part_count).toBe(partCount);
    expect(seenRanges).toHaveLength(partCount);
    expect(seenRanges[0]).toContain("bytes 0-4095");
    expect(completed).toBe(true);
    expect(result.completion.job_id).toBe("job_" + "c".repeat(32));
    expect(result.status.status).toBe("completed");
    expect(progress[progress.length - 1]).toBe(partCount);
  });

  it("retries a part that fails with a server error, then succeeds", async () => {
    const payload = new TextEncoder().encode("a,b\n1,2\n");
    const digest = await sha256HexOf(payload);
    let partAttempts = 0;

    server.use(
      http.post(`${API_ORIGIN}/api/v1/uploads`, () =>
        HttpResponse.json(
          {
            upload_id: "upl_" + "d".repeat(32),
            filename: "x.csv",
            extension: ".csv",
            size_bytes: payload.length,
            chunk_size_bytes: payload.length,
            part_count: 1,
            parts: [
              {
                part_number: 1,
                start_byte: 0,
                end_byte: payload.length - 1,
                size_bytes: payload.length,
              },
            ],
            status: "open",
            expires_at: new Date(Date.now() + 60_000).toISOString(),
            created_at: new Date().toISOString(),
          },
          { status: 201 },
        ),
      ),
      http.put(`${API_ORIGIN}/api/v1/uploads/upl_${"d".repeat(32)}/parts/1`, async ({ request }) => {
        partAttempts += 1;
        if (partAttempts < 3) {
          return HttpResponse.json(
            { error: { code: "internal_error", message: "boom" }, request_id: "r1" },
            { status: 500 },
          );
        }
        const body = new Uint8Array(await request.arrayBuffer());
        return HttpResponse.json({
          upload_id: "upl_" + "d".repeat(32),
          part_number: 1,
          size_bytes: body.length,
          sha256: await sha256HexOf(body),
          received: true,
        });
      }),
      http.post(`${API_ORIGIN}/api/v1/uploads/upl_${"d".repeat(32)}/complete`, () =>
        HttpResponse.json({
          upload_id: "upl_" + "d".repeat(32),
          status: "completed",
          artifact: {
            artifact_id: "art_" + "e".repeat(32),
            kind: "raw_upload",
            sha256: digest,
            size_bytes: payload.length,
            content_type: "text/csv",
            schema_version: "1.0.0",
            created_at: new Date().toISOString(),
            media_type_detail: {},
          },
          job_id: "job_" + "f".repeat(32),
        }),
      ),
      http.get(`${API_ORIGIN}/api/v1/uploads/upl_${"d".repeat(32)}`, () =>
        HttpResponse.json({
          upload_id: "upl_" + "d".repeat(32),
          status: "completed",
          filename: "x.csv",
          extension: ".csv",
          size_bytes: payload.length,
          sha256: digest,
          parts_received: [1],
          missing_parts: [],
          artifact: null,
          job_id: "job_" + "f".repeat(32),
          expires_at: new Date(Date.now() + 60_000).toISOString(),
          created_at: new Date().toISOString(),
          completed_at: new Date().toISOString(),
        }),
      ),
    );

    const client = createApiClient({ baseUrl: API_ORIGIN });
    const result = await uploadFile(client, new Blob([payload]), "x.csv", {
      contentType: "text/csv",
      retryDelayMs: 1,
    });
    expect(partAttempts).toBe(3);
    expect(result.status.status).toBe("completed");
  });

  it("does not retry a client error", async () => {
    const payload = new TextEncoder().encode("a,b\n1,2\n");

    server.use(
      http.post(`${API_ORIGIN}/api/v1/uploads`, () =>
        HttpResponse.json(
          {
            upload_id: "upl_" + "0".repeat(32),
            filename: "x.csv",
            extension: ".csv",
            size_bytes: payload.length,
            chunk_size_bytes: payload.length,
            part_count: 1,
            parts: [
              {
                part_number: 1,
                start_byte: 0,
                end_byte: payload.length - 1,
                size_bytes: payload.length,
              },
            ],
            status: "open",
            expires_at: new Date(Date.now() + 60_000).toISOString(),
            created_at: new Date().toISOString(),
          },
          { status: 201 },
        ),
      ),
      http.put(`${API_ORIGIN}/api/v1/uploads/upl_${"0".repeat(32)}/parts/1`, () =>
        HttpResponse.json(
          { error: { code: "validation_error", message: "bad part" }, request_id: "r2" },
          { status: 422 },
        ),
      ),
    );

    const client = createApiClient({ baseUrl: API_ORIGIN });
    await expect(
      uploadFile(client, new Blob([payload]), "x.csv", { contentType: "text/csv", retryDelayMs: 1 }),
    ).rejects.toMatchObject({ code: "validation_error" });
  });

  it("rejects an empty file before creating a session", async () => {
    const client = createApiClient({ baseUrl: API_ORIGIN });
    await expect(uploadFile(client, new Blob([]), "empty.csv")).rejects.toMatchObject({
      code: "invalid_request",
    });
  });
});

void vi;
