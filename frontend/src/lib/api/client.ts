import type { z } from "zod";

import { ApiError } from "./errors";
import { errorEnvelopeSchema } from "../contracts/runtime";

export interface ApiRequestOptions {
  readonly signal?: AbortSignal;
  readonly timeoutMs?: number;
  readonly headers?: Readonly<Record<string, string>>;
  readonly idempotencyKey?: string;
}

export interface ApiClient {
  readonly baseUrl: string;
  getJson<T>(path: string, schema: z.ZodType<T>, options?: ApiRequestOptions): Promise<T>;
  postJson<T, B>(
    path: string,
    body: B,
    schema: z.ZodType<T>,
    options?: ApiRequestOptions,
  ): Promise<T>;
  postEmpty<T>(
    path: string,
    schema: z.ZodType<T>,
    options?: ApiRequestOptions,
  ): Promise<T>;
  putBytes<T>(
    path: string,
    payload: Blob | Uint8Array,
    schema: z.ZodType<T>,
    options?: ApiRequestOptions,
  ): Promise<T>;
}

export interface ApiClientOptions {
  readonly baseUrl: string;
  readonly timeoutMs?: number;
  readonly fetchImplementation?: typeof fetch;
}

const DEFAULT_TIMEOUT_MS = 30_000;

/**
 * Create the typed fetch client.
 *
 * The client attaches a request identifier to every call, aborts a request
 * that exceeds its timeout, validates the response against the published
 * contract, and converts an error envelope into a typed error. Non-GET bodies
 * are sent verbatim; the caller owns content typing.
 */
export function createApiClient(options: ApiClientOptions): ApiClient {
  const baseUrl = options.baseUrl.replace(/\/+$/, "");
  const defaultTimeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const doFetch = options.fetchImplementation ?? globalThis.fetch;

  async function request<T>(
    method: string,
    path: string,
    init: {
      readonly body?: BodyInit;
      readonly contentType?: string;
      readonly schema: z.ZodType<T>;
      readonly options: ApiRequestOptions;
    },
  ): Promise<T> {
    const url = new URL(path, `${baseUrl}/`);
    const requestId = createRequestId();
    const controller = new AbortController();
    const timeoutMs = init.options.timeoutMs ?? defaultTimeoutMs;
    const timer = setTimeout(() => {
      controller.abort(new DOMException("The request timed out.", "TimeoutError"));
    }, timeoutMs);

    const signals: AbortSignal[] = [controller.signal];
    if (init.options.signal !== undefined) {
      signals.push(init.options.signal);
    }

    const headers: Record<string, string> = {
      Accept: "application/json",
      "X-Request-ID": requestId,
    };
    if (init.contentType !== undefined) {
      headers["Content-Type"] = init.contentType;
    }
    if (init.options.idempotencyKey !== undefined) {
      headers["Idempotency-Key"] = init.options.idempotencyKey;
    }
    if (init.options.headers !== undefined) {
      Object.assign(headers, init.options.headers);
    }

    try {
      const requestInit: RequestInit = {
        method,
        headers,
        signal: combineSignals(signals),
      };
      if (init.body !== undefined) {
        requestInit.body = init.body;
      }
      const response = await doFetch(url, requestInit);
      const payload = await readJson(response);

      if (!response.ok) {
        throw toApiError(response, payload, requestId);
      }

      const parsed = init.schema.safeParse(payload);
      if (!parsed.success) {
        throw new ApiError({
          code: "invalid_response",
          message:
            "The API answered with a payload that does not match the published contract.",
          status: response.status,
          requestId,
          details: {
            issues: parsed.error.issues.map((issue) => ({
              path: issue.path.join("."),
              message: issue.message,
            })),
          },
        });
      }
      return parsed.data;
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }
      if (isAbortError(error)) {
        throw new ApiError({
          code: "request_aborted",
          message: "The request was cancelled before the API answered.",
          status: 0,
          requestId,
          details: null,
        });
      }
      throw new ApiError({
        code: "network_error",
        message: "The API could not be reached.",
        status: 0,
        requestId,
        details: null,
      });
    } finally {
      clearTimeout(timer);
    }
  }

  return {
    baseUrl,
    getJson<T>(path: string, schema: z.ZodType<T>, options: ApiRequestOptions = {}) {
      return request("GET", path, { schema, options });
    },
    postJson<T, B>(path: string, body: B, schema: z.ZodType<T>, options: ApiRequestOptions = {}) {
      return request("POST", path, {
        body: JSON.stringify(body),
        contentType: "application/json",
        schema,
        options,
      });
    },
    postEmpty<T>(path: string, schema: z.ZodType<T>, options: ApiRequestOptions = {}) {
      return request("POST", path, { schema, options });
    },
    putBytes<T>(
      path: string,
      payload: Blob | Uint8Array,
      schema: z.ZodType<T>,
      options: ApiRequestOptions = {},
    ) {
      const body: BodyInit = payload instanceof Uint8Array ? new Blob([payload.slice()]) : payload;
      return request("PUT", path, {
        body,
        contentType: "application/octet-stream",
        schema,
        options,
      });
    },
  };
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return (await response.json()) as unknown;
  } catch {
    return null;
  }
}

function toApiError(response: Response, payload: unknown, requestId: string): ApiError {
  const envelope = errorEnvelopeSchema.safeParse(payload);
  if (envelope.success) {
    return new ApiError({
      code: envelope.data.error.code,
      message: envelope.data.error.message,
      status: response.status,
      requestId: envelope.data.request_id ?? requestId,
      details: envelope.data.error.details ?? null,
    });
  }
  return new ApiError({
    code: "unexpected_error",
    message: `The API answered with status ${response.status}.`,
    status: response.status,
    requestId,
    details: null,
  });
}

function isAbortError(error: unknown): boolean {
  return (
    error instanceof DOMException &&
    (error.name === "AbortError" || error.name === "TimeoutError")
  );
}

function combineSignals(signals: readonly AbortSignal[]): AbortSignal {
  const controller = new AbortController();
  for (const signal of signals) {
    if (signal.aborted) {
      controller.abort(signal.reason);
      return controller.signal;
    }
    signal.addEventListener(
      "abort",
      () => {
        controller.abort(signal.reason);
      },
      { once: true },
    );
  }
  return controller.signal;
}

function createRequestId(): string {
  const cryptoApi = globalThis.crypto;
  const randomUuid = (cryptoApi as { randomUUID?: () => string }).randomUUID;
  if (typeof randomUuid === "function") {
    return randomUuid.call(cryptoApi);
  }
  const bytes = new Uint8Array(16);
  cryptoApi.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}
