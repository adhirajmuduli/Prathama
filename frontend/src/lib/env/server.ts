import "server-only";

import { z } from "zod";

/**
 * Server-side environment.
 *
 * The values are validated once at import time so that a misconfigured
 * deployment fails at build time instead of at the first request. Only the
 * server may read this module.
 */
const serverEnvironmentSchema = z.object({
  BACKEND_API_ORIGIN: z.string().url(),
  NEXT_PUBLIC_SITE_URL: z.string().url(),
  TRENDSMAPP_API_TIMEOUT_MS: z.coerce.number().int().positive().max(60_000),
  // Contact providers are optional at build time; the route answers 503 when
  // they are absent. Secrets never ship to the client bundle.
  TURNSTILE_SECRET_KEY: z.string().min(1).nullish(),
  UPSTASH_REST_URL: z.string().url().nullish(),
  UPSTASH_REST_TOKEN: z.string().min(1).nullish(),
  RESEND_API_KEY: z.string().min(1).nullish(),
  CONTACT_FROM_EMAIL: z.email().nullish(),
  CONTACT_TO_EMAIL: z.email().nullish(),
  CONTACT_HASH_SECRET: z.string().min(1).nullish(),
  CONTACT_RATE_LIMIT_WINDOW_MS: z.coerce
    .number()
    .int()
    .positive()
    .default(3_600_000),
  CONTACT_RATE_LIMIT_IP_PER_WINDOW: z.coerce
    .number()
    .int()
    .positive()
    .default(5),
  CONTACT_RATE_LIMIT_EMAIL_PER_WINDOW: z.coerce
    .number()
    .int()
    .positive()
    .default(3),
  CONTACT_IDEMPOTENCY_TTL_SECONDS: z.coerce
    .number()
    .int()
    .positive()
    .default(86_400),
});

export const serverEnvironment = serverEnvironmentSchema.parse({
  BACKEND_API_ORIGIN: process.env.BACKEND_API_ORIGIN ?? "http://localhost:8000",
  NEXT_PUBLIC_SITE_URL:
    process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000",
  TRENDSMAPP_API_TIMEOUT_MS: process.env.TRENDSMAPP_API_TIMEOUT_MS ?? "10000",
  TURNSTILE_SECRET_KEY: process.env.TURNSTILE_SECRET_KEY,
  UPSTASH_REST_URL: process.env.UPSTASH_REST_URL,
  UPSTASH_REST_TOKEN: process.env.UPSTASH_REST_TOKEN,
  RESEND_API_KEY: process.env.RESEND_API_KEY,
  CONTACT_FROM_EMAIL: process.env.CONTACT_FROM_EMAIL,
  CONTACT_TO_EMAIL: process.env.CONTACT_TO_EMAIL,
  CONTACT_HASH_SECRET: process.env.CONTACT_HASH_SECRET,
  CONTACT_RATE_LIMIT_WINDOW_MS:
    process.env.CONTACT_RATE_LIMIT_WINDOW_MS ?? "3600000",
  CONTACT_RATE_LIMIT_IP_PER_WINDOW:
    process.env.CONTACT_RATE_LIMIT_IP_PER_WINDOW ?? "5",
  CONTACT_RATE_LIMIT_EMAIL_PER_WINDOW:
    process.env.CONTACT_RATE_LIMIT_EMAIL_PER_WINDOW ?? "3",
  CONTACT_IDEMPOTENCY_TTL_SECONDS:
    process.env.CONTACT_IDEMPOTENCY_TTL_SECONDS ?? "86400",
});
