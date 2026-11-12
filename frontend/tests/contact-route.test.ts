import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import {
  afterAll,
  afterEach,
  beforeAll,
  describe,
  expect,
  it,
  vi,
} from "vitest";

const TURNSTILE_URL =
  "https://challenges.cloudflare.com/turnstile/v0/siteverify";
const UPSTASH_URL = "https://upstash.test";
const RESEND_URL = "https://api.resend.com/emails";

// The route reads its provider configuration from the server env module, which
// is mocked here (deterministically) instead of relying on process.env, because
// the happy-dom environment does not expose per-test env changes to src modules.
vi.mock("@/lib/env/server", () => ({
  serverEnvironment: {
    BACKEND_API_ORIGIN: "http://localhost:8000",
    NEXT_PUBLIC_SITE_URL: "http://localhost:3000",
    TRENDSMAPP_API_TIMEOUT_MS: 10_000,
    TURNSTILE_SECRET_KEY: "turnstile-secret",
    UPSTASH_REST_URL: "https://upstash.test",
    UPSTASH_REST_TOKEN: "test-token-not-real",
    RESEND_API_KEY: "re_test_not_real",
    CONTACT_FROM_EMAIL: "contact@example.org",
    CONTACT_TO_EMAIL: "ops@example.org",
    CONTACT_HASH_SECRET: "test-hmac-secret-not-real",
    CONTACT_RATE_LIMIT_WINDOW_MS: 3_600_000,
    CONTACT_RATE_LIMIT_IP_PER_WINDOW: 5,
    CONTACT_RATE_LIMIT_EMAIL_PER_WINDOW: 3,
    CONTACT_IDEMPOTENCY_TTL_SECONDS: 86_400,
  },
}));

const server = setupServer();

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});

afterEach(() => {
  server.resetHandlers();
  vi.resetModules();
});

afterAll(() => {
  server.close();
});

function validBody(overrides: Record<string, unknown> = {}) {
  return {
    name: "Ada Lovelace",
    email: "ada@example.org",
    subject: "Question about the API",
    message: "Hello, this is a sufficiently long message.",
    consent: true,
    turnstileToken: "test-token-not-real",
    ...overrides,
  };
}

async function loadRoute() {
  return import("@/app/api/contact/route");
}

function installProviders(
  options: {
    turnstileSuccess?: boolean;
    rateLimited?: boolean;
    duplicate?: boolean;
  } = {},
) {
  const {
    turnstileSuccess = true,
    rateLimited = false,
    duplicate = false,
  } = options;
  let resendCalls = 0;
  server.use(
    // happy-dom performs CORS preflights; answer them like the edge does.
    ...[TURNSTILE_URL, `${UPSTASH_URL}/eval`, RESEND_URL].map((url) =>
      http.options(
        url,
        () =>
          new HttpResponse(null, {
            status: 204,
            headers: {
              "Access-Control-Allow-Origin": "*",
              "Access-Control-Allow-Headers": "*",
              "Access-Control-Allow-Methods": "*",
            },
          }),
      ),
    ),
    http.post(TURNSTILE_URL, () =>
      HttpResponse.json({
        success: turnstileSuccess,
        "error-codes": turnstileSuccess ? [] : ["invalid-input-response"],
      }),
    ),
    http.post(`${UPSTASH_URL}/eval`, async ({ request }) => {
      const body = (await request.json()) as { script?: string };
      const script = body.script ?? "";
      if (script.includes("SET")) {
        return HttpResponse.json({ result: duplicate ? 0 : 1 });
      }
      return HttpResponse.json({ result: rateLimited ? [0, 99] : [1, 1] });
    }),
    http.post(RESEND_URL, () => {
      resendCalls += 1;
      return HttpResponse.json({ id: "email_123" });
    }),
  );
  return {
    get resendCalls() {
      return resendCalls;
    },
  };
}

async function post(body: unknown, headers: Record<string, string> = {}) {
  const { POST } = await loadRoute();
  return POST(
    new Request("http://localhost:3000/api/contact", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-forwarded-for": "203.0.113.7",
        ...headers,
      },
      body: JSON.stringify(body),
    }),
  );
}

describe("POST /api/contact", () => {
  it("sends a verified message and returns a generic success", async () => {
    const providers = installProviders();
    const response = await post(validBody());
    expect(response.status).toBe(200);
    const body = (await response.json()) as { ok: boolean; request_id: string };
    expect(body.ok).toBe(true);
    expect(typeof body.request_id).toBe("string");
    expect(providers.resendCalls).toBe(1);
  });

  it("rejects a honeypot submission without calling any provider", async () => {
    const providers = installProviders();
    const response = await post(validBody({ website: "http://spam.example" }));
    expect(response.status).toBe(400);
    expect(providers.resendCalls).toBe(0);
  });

  it("rejects when Turnstile does not verify", async () => {
    const providers = installProviders({ turnstileSuccess: false });
    const response = await post(validBody());
    expect(response.status).toBe(403);
    expect(providers.resendCalls).toBe(0);
  });

  it("rate limits repeated submissions", async () => {
    installProviders({ rateLimited: true });
    const response = await post(validBody());
    expect(response.status).toBe(429);
  });

  it("does not resend a duplicate submission", async () => {
    const providers = installProviders({ duplicate: true });
    const response = await post(validBody());
    expect(response.status).toBe(200);
    expect(providers.resendCalls).toBe(0);
  });

  it("rejects invalid form data", async () => {
    installProviders();
    const response = await post(validBody({ email: "not-an-email" }));
    expect(response.status).toBe(400);
  });

  it("answers 503 when the providers are not configured", async () => {
    installProviders();
    vi.resetModules();
    vi.doMock("@/lib/env/server", () => ({
      serverEnvironment: {
        BACKEND_API_ORIGIN: "http://localhost:8000",
        NEXT_PUBLIC_SITE_URL: "http://localhost:3000",
        TRENDSMAPP_API_TIMEOUT_MS: 10_000,
        TURNSTILE_SECRET_KEY: null,
        UPSTASH_REST_URL: null,
        UPSTASH_REST_TOKEN: null,
        RESEND_API_KEY: null,
        CONTACT_FROM_EMAIL: null,
        CONTACT_TO_EMAIL: null,
        CONTACT_HASH_SECRET: null,
        CONTACT_RATE_LIMIT_WINDOW_MS: 3_600_000,
        CONTACT_RATE_LIMIT_IP_PER_WINDOW: 5,
        CONTACT_RATE_LIMIT_EMAIL_PER_WINDOW: 3,
        CONTACT_IDEMPOTENCY_TTL_SECONDS: 86_400,
      },
    }));
    const response = await post(validBody());
    expect(response.status).toBe(503);
    vi.doUnmock("@/lib/env/server");
    vi.resetModules();
  });
});
