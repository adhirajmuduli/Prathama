// @vitest-environment node
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { createApiClient } from "@/lib/api/client";
import { readApiStatus } from "@/lib/api/status";

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

describe("readApiStatus", () => {
  it("reports a ready backend", async () => {
    server.use(
      http.get(`${API_ORIGIN}/api/v1/health/live`, () =>
        HttpResponse.json({ status: "ok", service: "trendsmapp" }),
      ),
      http.get(`${API_ORIGIN}/api/v1/health/ready`, () =>
        HttpResponse.json({
          status: "ready",
          components: { database: "ok", object_store: "ok" },
        }),
      ),
      http.get(`${API_ORIGIN}/api/v1/contracts/versions`, () =>
        HttpResponse.json({
          api_major: 1,
          application_version: "0.1.0",
          artifact_schema_version: "1.0.0",
          recipe_schema_version: "1.0.0",
          supported_api_majors: [1],
          supported_artifact_schema_versions: ["1.0.0"],
          supported_recipe_schema_versions: ["1.0.0"],
        }),
      ),
    );
    const client = createApiClient({ baseUrl: API_ORIGIN });

    const status = await readApiStatus(client);

    expect(status.reachable).toBe(true);
    expect(status.problem).toBeNull();
    expect(status.ready?.status).toBe("ready");
    expect(status.versions?.api_major).toBe(1);
  });

  it("reports a degraded backend without hiding the reason", async () => {
    server.use(
      http.get(`${API_ORIGIN}/api/v1/health/live`, () =>
        HttpResponse.json({ status: "ok", service: "trendsmapp" }),
      ),
      http.get(`${API_ORIGIN}/api/v1/health/ready`, () =>
        HttpResponse.json({
          status: "degraded",
          components: { database: "ok", object_store: "unavailable" },
        }),
      ),
      http.get(`${API_ORIGIN}/api/v1/contracts/versions`, () =>
        HttpResponse.json(
          {
            error: {
              code: "internal_error",
              message: "The contract versions could not be read.",
            },
            request_id: "0a1b2c3d4e5f60718293a4b5c6d7e8f9",
          },
          { status: 500 },
        ),
      ),
    );
    const client = createApiClient({ baseUrl: API_ORIGIN });

    const status = await readApiStatus(client);

    expect(status.reachable).toBe(true);
    expect(status.ready?.status).toBe("degraded");
    expect(status.ready?.components.object_store).toBe("unavailable");
    expect(status.versions).toBeNull();
    expect(status.problem).toContain("internal_error");
  });

  it("reports an unreachable backend", async () => {
    server.use(
      http.get(`${API_ORIGIN}/api/v1/health/live`, () => HttpResponse.error()),
      http.get(`${API_ORIGIN}/api/v1/health/ready`, () => HttpResponse.error()),
      http.get(`${API_ORIGIN}/api/v1/contracts/versions`, () =>
        HttpResponse.error(),
      ),
    );
    const client = createApiClient({ baseUrl: API_ORIGIN });

    const status = await readApiStatus(client);

    expect(status.reachable).toBe(false);
    expect(status.live).toBeNull();
    expect(status.problem).not.toBeNull();
  });
});
