// @vitest-environment node
import { delay, http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { createApiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { healthLiveSchema } from "@/lib/contracts/runtime";

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

describe("createApiClient", () => {
  it("returns the parsed payload of a successful response", async () => {
    server.use(
      http.get(`${API_ORIGIN}/api/v1/health/live`, () =>
        HttpResponse.json({ status: "ok", service: "trendsmapp" }),
      ),
    );
    const client = createApiClient({ baseUrl: API_ORIGIN });

    const payload = await client.getJson("/api/v1/health/live", healthLiveSchema);

    expect(payload).toEqual({ status: "ok", service: "trendsmapp" });
  });

  it("converts an error envelope into a typed error", async () => {
    server.use(
      http.get(`${API_ORIGIN}/api/v1/health/live`, () =>
        HttpResponse.json(
          {
            error: {
              code: "not_found",
              message: "The requested resource does not exist.",
              details: { path: "/api/v1/health/live" },
            },
            request_id: "6f1f2f7d0b1c4a5e8f90a1b2c3d4e5f6",
          },
          { status: 404 },
        ),
      ),
    );
    const client = createApiClient({ baseUrl: API_ORIGIN });

    const failure = await client
      .getJson("/api/v1/health/live", healthLiveSchema)
      .catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    const apiError = failure as ApiError;
    expect(apiError.code).toBe("not_found");
    expect(apiError.status).toBe(404);
    expect(apiError.requestId).toBe("6f1f2f7d0b1c4a5e8f90a1b2c3d4e5f6");
  });

  it("rejects a payload that does not match the published contract", async () => {
    server.use(
      http.get(`${API_ORIGIN}/api/v1/health/live`, () =>
        HttpResponse.json({ status: "ok" }),
      ),
    );
    const client = createApiClient({ baseUrl: API_ORIGIN });

    const failure = await client
      .getJson("/api/v1/health/live", healthLiveSchema)
      .catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).code).toBe("invalid_response");
  });

  it("reports an unreachable API as a network error", async () => {
    server.use(
      http.get(`${API_ORIGIN}/api/v1/health/live`, () => HttpResponse.error()),
    );
    const client = createApiClient({ baseUrl: API_ORIGIN });

    const failure = await client
      .getJson("/api/v1/health/live", healthLiveSchema)
      .catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).code).toBe("network_error");
  });

  it("aborts a request that exceeds its timeout", async () => {
    server.use(
      http.get(`${API_ORIGIN}/api/v1/health/live`, async () => {
        await delay(500);
        return HttpResponse.json({ status: "ok", service: "trendsmapp" });
      }),
    );
    const client = createApiClient({ baseUrl: API_ORIGIN });

    const failure = await client
      .getJson("/api/v1/health/live", healthLiveSchema, { timeoutMs: 25 })
      .catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).code).toBe("request_aborted");
  });
});
