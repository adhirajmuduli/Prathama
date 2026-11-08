/**
 * The chunked uploader.
 *
 * The flow is: create a session, PUT each planned part with its Content-Range,
 * then complete. Every part is digest-verified by the server, and a failed
 * part is retried a bounded number of times before the upload fails. The
 * whole upload is idempotent under one key: completing twice with the same key
 * returns the same job instead of enqueuing a second one.
 */

import type { z } from "zod";

import type { ApiClient, ApiRequestOptions } from "./client";
import type { partPlanSchema } from "../contracts/ingest";
import {
  completeUploadSchema,
  partUploadSchema,
  uploadSessionSchema,
  uploadStatusSchema,
  type CompleteUpload,
  type UploadSession,
  type UploadStatus,
} from "../contracts/ingest";
import { ApiError } from "./errors";

export interface UploadProgress {
  readonly uploadedParts: number;
  readonly totalParts: number;
  readonly bytesUploaded: number;
  readonly totalBytes: number;
  readonly currentPart: number | null;
}

export interface UploadResult {
  readonly session: UploadSession;
  readonly status: UploadStatus;
  readonly completion: CompleteUpload;
}

export interface UploadOptions {
  readonly contentType?: string | null;
  readonly idempotencyKey?: string;
  readonly signal?: AbortSignal;
  readonly maxPartRetries?: number;
  readonly retryDelayMs?: number;
  readonly onProgress?: (progress: UploadProgress) => void;
}

const DEFAULT_MAX_PART_RETRIES = 3;
const DEFAULT_RETRY_DELAY_MS = 250;

/** Upload one file through the chunked protocol. */
export async function uploadFile(
  client: ApiClient,
  file: Blob,
  filename: string,
  options: UploadOptions = {},
): Promise<UploadResult> {
  const totalBytes = file.size;
  if (totalBytes < 1) {
    throw new ApiError({
      code: "invalid_request",
      message: "The selected file is empty.",
      status: 0,
      requestId: null,
      details: null,
    });
  }
  const sha256 = await sha256Hex(await file.arrayBuffer());

  const session = await client.postJson(
    "/api/v1/uploads",
    {
      filename,
      content_type: options.contentType ?? (file.type || null),
      size_bytes: totalBytes,
      sha256,
    },
    uploadSessionSchema,
    requestOptions({ signal: options.signal }),
  );

  const maxRetries = options.maxPartRetries ?? DEFAULT_MAX_PART_RETRIES;
  const retryDelayMs = options.retryDelayMs ?? DEFAULT_RETRY_DELAY_MS;
  let bytesUploaded = 0;

  for (const plan of session.parts) {
    options.onProgress?.({
      uploadedParts: bytesUploaded > 0 ? plan.part_number - 1 : 0,
      totalParts: session.part_count,
      bytesUploaded,
      totalBytes,
      currentPart: plan.part_number,
    });
    const slice = file.slice(plan.start_byte, plan.end_byte + 1);
    await uploadPartWithRetry(client, session.upload_id, plan, slice, {
      ...(options.signal !== undefined ? { signal: options.signal } : {}),
      maxRetries,
      retryDelayMs,
    });
    bytesUploaded += plan.size_bytes;
    options.onProgress?.({
      uploadedParts: plan.part_number,
      totalParts: session.part_count,
      bytesUploaded,
      totalBytes,
      currentPart: null,
    });
  }

  const completion = await client.postEmpty(
    `/api/v1/uploads/${session.upload_id}/complete`,
    completeUploadSchema,
    {
      ...(options.signal !== undefined ? { signal: options.signal } : {}),
      idempotencyKey: options.idempotencyKey ?? createRequestId(),
    },
  );
  const status = await client.getJson(
    `/api/v1/uploads/${session.upload_id}`,
    uploadStatusSchema,
    requestOptions({ signal: options.signal }),
  );
  return { session, status, completion };
}

async function uploadPartWithRetry(
  client: ApiClient,
  uploadId: string,
  plan: z.infer<typeof partPlanSchema>,
  slice: Blob,
  options: { signal?: AbortSignal; maxRetries: number; retryDelayMs: number },
): Promise<void> {
  let attempt = 0;
  for (;;) {
    attempt += 1;
    try {
      await client.putBytes(
        `/api/v1/uploads/${uploadId}/parts/${plan.part_number}`,
        slice,
        partUploadSchema,
        {
          ...(options.signal !== undefined ? { signal: options.signal } : {}),
          headers: {
            "Content-Range": `bytes ${plan.start_byte}-${plan.end_byte}/${plan.start_byte + plan.size_bytes}`,
          },
        },
      );
      return;
    } catch (error) {
      const retryable =
        error instanceof ApiError &&
        (error.status === 0 || error.status >= 500);
      if (!retryable || attempt > options.maxRetries) {
        throw error;
      }
      await delay(options.retryDelayMs * attempt, options.signal);
    }
  }
}

async function sha256Hex(buffer: ArrayBuffer): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest("SHA-256", buffer);
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(signal.reason);
    });
  });
}

/** Build request options, omitting keys that are undefined (exactOptionalPropertyTypes). */
function requestOptions(parts: {
  readonly signal: AbortSignal | undefined;
  readonly idempotencyKey?: string;
}): ApiRequestOptions {
  return {
    ...(parts.signal !== undefined ? { signal: parts.signal } : {}),
    ...(parts.idempotencyKey !== undefined
      ? { idempotencyKey: parts.idempotencyKey }
      : {}),
  };
}

function createRequestId(): string {
  const cryptoApi = globalThis.crypto;
  const randomUuid = (cryptoApi as { randomUUID?: () => string }).randomUUID;
  if (typeof randomUuid === "function") {
    return randomUuid.call(cryptoApi);
  }
  return "upload-" + Date.now().toString(16);
}
