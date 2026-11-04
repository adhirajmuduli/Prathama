import type { z } from "zod";

import { ApiError } from "./errors";
import { errorEnvelopeSchema } from "../contracts/runtime";

export interface ApiRequestOptions {
  readonly signal?: AbortSignal;
  readonly timeoutMs?: number;
  readonly headers?: Readonly<Record<string, string>>;
}

export interface ApiClient {
  readonly baseUrl: string;
  getJson<T>(
    path: string,
    schema: z.ZodType<T>,
    options?: ApiRequestOptions,
  ): Promise<T>;
}

export interface ApiClientOptions {
  readonly baseUrl: string;
  readonly timeoutMs?: number;
  readonly fetchImplementation?: typeof fetch;
}

const DEFAULT_TIMEOUT_MS = 10_000;

/**
 * Create the typed fetch client.
 *
 * The client attaches a request identifier to every call, aborts a request
 * that exceeds its timeout, validates the response against the published
 * contract, and converts an error envelope into a typed error.
 */
export function createApiClient(options: ApiClientOptions): ApiClient {
  const baseUrl = options.baseUrl.replace(/\/+$/, "");
  const defaultTimeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const doFetch = options.fetchImplementation ?? globalThis.fetch;

  return {
    baseUrl,
    async getJson<T>(
      path: string,
      schema: z.ZodType<T>,
      requestOptions: ApiRequestOptions = {},
    ): Promise<T> {
      const url = new URL(path, `${baseUrl}/`);
      const requestId = createRequestId();
      const controller = new AbortController();
      const timeoutMs = requestOptions.timeoutMs ?? defaultTimeoutMs;
      const timer = setTimeout(() => {
        controller.abort(new DOMException("The request timed out.", "TimeoutError"));
      }, timeoutMs);

      const signals: AbortSignal[] = [controller.signal];
      if (requestOptions.signal !== undefined) {
        signals.push(requestOptions.signal);
      }

      const headers: Record<string, string> = {
        Accept: "application/json",
        "X-Request-ID": requestId,
      };
      if (requestOptions.headers !== undefined) {
        Object.assign(headers, requestOptions.headers);
      }

      try {
        const response = await doFetch(url, {
          method: "GET",
          headers,
          signal: combineSignals(signals),
        });
        const payload = await readJson(response);

        if (!response.ok) {
          throw toApiError(response, payload, requestId);
        }

        const parsed = schema.safeParse(payload);
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

function toApiError(
  response: Response,
  payload: unknown,
  requestId: string,
): ApiError {
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
